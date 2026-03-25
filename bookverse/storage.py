from __future__ import annotations

import sqlite3
from pathlib import Path

from bookverse.models import BookRecord, ChunkRecord


class Repository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def init(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS books (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    upload_date TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    source_path TEXT NOT NULL,
                    chapter_count INTEGER NOT NULL DEFAULT 0,
                    chunk_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
                    chunk_order INTEGER NOT NULL,
                    chapter_number INTEGER,
                    chapter_title TEXT,
                    line_start INTEGER NOT NULL,
                    line_end INTEGER NOT NULL,
                    char_start INTEGER NOT NULL,
                    char_end INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    search_text TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_books_status ON books(status);
                CREATE INDEX IF NOT EXISTS idx_chunks_book_id ON chunks(book_id);
                CREATE INDEX IF NOT EXISTS idx_chunks_order ON chunks(book_id, chunk_order);
                """
            )

    def create_book(
        self,
        *,
        book_id: str,
        title: str,
        filename: str,
        file_type: str,
        upload_date: str,
        source_path: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO books (id, title, filename, file_type, upload_date, status, source_path)
                VALUES (?, ?, ?, ?, ?, 'PROCESSING', ?)
                """,
                (book_id, title, filename, file_type, upload_date, source_path),
            )

    def update_book_status(
        self,
        book_id: str,
        status: str,
        *,
        error_message: str | None = None,
        chapter_count: int | None = None,
        chunk_count: int | None = None,
        title: str | None = None,
    ) -> None:
        assignments = ["status = ?", "error_message = ?"]
        params: list[object] = [status, error_message]
        if chapter_count is not None:
            assignments.append("chapter_count = ?")
            params.append(chapter_count)
        if chunk_count is not None:
            assignments.append("chunk_count = ?")
            params.append(chunk_count)
        if title is not None:
            assignments.append("title = ?")
            params.append(title)
        params.append(book_id)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE books SET {', '.join(assignments)} WHERE id = ?",
                params,
            )

    def list_books(self) -> list[BookRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, title, filename, file_type, upload_date, status, error_message, source_path, chapter_count, chunk_count
                FROM books
                ORDER BY upload_date DESC
                """
            ).fetchall()
        return [self._row_to_book(row) for row in rows]

    def get_book(self, book_id: str) -> BookRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, title, filename, file_type, upload_date, status, error_message, source_path, chapter_count, chunk_count
                FROM books
                WHERE id = ?
                """,
                (book_id,),
            ).fetchone()
        return self._row_to_book(row) if row else None

    def replace_chunks(self, book_id: str, chunks: list[ChunkRecord]) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM chunks WHERE book_id = ?", (book_id,))
            connection.executemany(
                """
                INSERT INTO chunks (
                    id, book_id, chunk_order, chapter_number, chapter_title,
                    line_start, line_end, char_start, char_end, text, search_text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.id,
                        chunk.book_id,
                        chunk.chunk_order,
                        chunk.chapter_number,
                        chunk.chapter_title,
                        chunk.line_start,
                        chunk.line_end,
                        chunk.char_start,
                        chunk.char_end,
                        chunk.text,
                        chunk.search_text,
                    )
                    for chunk in chunks
                ],
            )

    def get_ready_chunks(self) -> list[ChunkRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT c.id, c.book_id, c.chunk_order, c.chapter_number, c.chapter_title,
                       c.line_start, c.line_end, c.char_start, c.char_end, c.text, c.search_text
                FROM chunks c
                JOIN books b ON b.id = c.book_id
                WHERE b.status = 'READY'
                ORDER BY b.upload_date DESC, c.chunk_order ASC
                """
            ).fetchall()
        return [self._row_to_chunk(row) for row in rows]

    def get_book_chunks(self, book_id: str) -> list[ChunkRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, book_id, chunk_order, chapter_number, chapter_title,
                       line_start, line_end, char_start, char_end, text, search_text
                FROM chunks
                WHERE book_id = ?
                ORDER BY chunk_order ASC
                """,
                (book_id,),
            ).fetchall()
        return [self._row_to_chunk(row) for row in rows]

    def delete_book(self, book_id: str) -> BookRecord | None:
        book = self.get_book(book_id)
        if not book:
            return None
        with self._connect() as connection:
            connection.execute("DELETE FROM books WHERE id = ?", (book_id,))
        return book

    def ready_titles(self) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, title FROM books WHERE status = 'READY'"
            ).fetchall()
        return {str(row["id"]): str(row["title"]) for row in rows}

    def status_summary(self) -> dict[str, int]:
        counts = {"READY": 0, "PROCESSING": 0, "ERROR": 0}
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT status, COUNT(*) AS total
                FROM books
                GROUP BY status
                """
            ).fetchall()
        for row in rows:
            status = str(row["status"])
            if status in counts:
                counts[status] = int(row["total"])
        counts["TOTAL"] = sum(counts.values())
        return counts

    @staticmethod
    def _row_to_book(row: sqlite3.Row) -> BookRecord:
        return BookRecord(
            id=str(row["id"]),
            title=str(row["title"]),
            filename=str(row["filename"]),
            file_type=str(row["file_type"]),
            upload_date=str(row["upload_date"]),
            status=str(row["status"]),
            error_message=row["error_message"],
            source_path=str(row["source_path"]),
            chapter_count=int(row["chapter_count"]),
            chunk_count=int(row["chunk_count"]),
        )

    @staticmethod
    def _row_to_chunk(row: sqlite3.Row) -> ChunkRecord:
        return ChunkRecord(
            id=str(row["id"]),
            book_id=str(row["book_id"]),
            chunk_order=int(row["chunk_order"]),
            chapter_number=row["chapter_number"],
            chapter_title=row["chapter_title"],
            line_start=int(row["line_start"]),
            line_end=int(row["line_end"]),
            char_start=int(row["char_start"]),
            char_end=int(row["char_end"]),
            text=str(row["text"]),
            search_text=str(row["search_text"]),
        )
