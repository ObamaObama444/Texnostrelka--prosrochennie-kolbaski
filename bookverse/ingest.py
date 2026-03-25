from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil
import uuid

from fastapi import UploadFile

from bookverse.config import Settings
from bookverse.models import BookRecord
from bookverse.search_index import HybridSearchIndex
from bookverse.storage import Repository
from bookverse.text import parse_book_content, strip_extension


class BookIngestionService:
    def __init__(self, *, settings: Settings, repository: Repository, search_index: HybridSearchIndex) -> None:
        self.settings = settings
        self.repository = repository
        self.search_index = search_index

    def import_upload(self, upload: UploadFile) -> tuple[str, str]:
        filename = upload.filename or "book.txt"
        suffix = Path(filename).suffix.lower()
        allowed = {".txt"}
        if self.settings.enable_fb2:
            allowed.add(".fb2")
        if suffix not in allowed:
            raise ValueError("Поддерживаются только .txt и .fb2")

        book_id = f"book_{uuid.uuid4().hex}"
        timestamp = datetime.now(timezone.utc).isoformat()
        safe_name = f"{book_id}{suffix}"
        stored_path = self.settings.books_dir / safe_name

        with stored_path.open("wb") as destination:
            shutil.copyfileobj(upload.file, destination)

        self.repository.create_book(
            book_id=book_id,
            title=strip_extension(filename),
            filename=filename,
            file_type=suffix.lstrip(".").upper(),
            upload_date=timestamp,
            source_path=str(stored_path),
        )
        return book_id, "PROCESSING"

    def process_book(self, book_id: str) -> None:
        book = self.repository.get_book(book_id)
        if not book:
            return
        try:
            raw = book.source_file.read_bytes()
            parsed = parse_book_content(
                book_id=book.id,
                filename=book.filename,
                raw_bytes=raw,
                file_type=book.file_type,
                max_chunk_chars=self.settings.max_chunk_chars,
                overlap_chars=self.settings.chunk_overlap_chars,
            )
            self.repository.replace_chunks(book.id, parsed.chunks)
            self.repository.update_book_status(
                book.id,
                "READY",
                error_message=None,
                chapter_count=len(parsed.chapters),
                chunk_count=len(parsed.chunks),
                title=parsed.title,
            )
            self.search_index.rebuild()
        except Exception as error:
            self.repository.update_book_status(book.id, "ERROR", error_message=str(error))
            self.search_index.rebuild()

    def delete_book(self, book_id: str) -> BookRecord | None:
        book = self.repository.delete_book(book_id)
        if not book:
            return None
        if book.source_file.exists():
            book.source_file.unlink()
        self.search_index.rebuild()
        return book
