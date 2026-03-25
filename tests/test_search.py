from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from bookverse.embedding import build_embedder
from bookverse.search_index import HybridSearchIndex
from bookverse.storage import Repository
from bookverse.text import parse_book_content, strip_extension


def ingest_fixture(repository: Repository, fixture: Path, settings) -> str:
    book_id = f"book_{fixture.stem}"
    stored_path = settings.books_dir / fixture.name
    stored_path.write_bytes(fixture.read_bytes())
    repository.create_book(
        book_id=book_id,
        title=strip_extension(fixture.name),
        filename=fixture.name,
        file_type=fixture.suffix.lstrip(".").upper(),
        upload_date=datetime.now(timezone.utc).isoformat(),
        source_path=str(stored_path),
    )
    parsed = parse_book_content(
        book_id=book_id,
        filename=fixture.name,
        raw_bytes=fixture.read_bytes(),
        file_type=fixture.suffix.lstrip(".").upper(),
        max_chunk_chars=settings.max_chunk_chars,
        overlap_chars=settings.chunk_overlap_chars,
    )
    repository.replace_chunks(book_id, parsed.chunks)
    repository.update_book_status(
        book_id,
        "READY",
        chapter_count=len(parsed.chapters),
        chunk_count=len(parsed.chunks),
        title=parsed.title,
    )
    return book_id


def test_hybrid_search_finds_explicit_fragment_in_top_three(settings) -> None:
    repository = Repository(settings.db_path)
    repository.init()
    ingest_fixture(repository, Path(__file__).resolve().parents[1] / "demo_books" / "family_epilogue.txt", settings)

    search_index = HybridSearchIndex(
        settings=settings,
        repository=repository,
        embedder=build_embedder(settings),
    )
    search_index.rebuild()

    fragments = search_index.search("семейная жизнь героев", None, 3)

    assert fragments
    assert any(fragment.chapter_number == 2 for fragment in fragments[:3])


def test_hybrid_search_handles_synonym_query(settings) -> None:
    repository = Repository(settings.db_path)
    repository.init()
    ingest_fixture(repository, Path(__file__).resolve().parents[1] / "demo_books" / "garage_story.txt", settings)

    search_index = HybridSearchIndex(
        settings=settings,
        repository=repository,
        embedder=build_embedder(settings),
    )
    search_index.rebuild()

    fragments = search_index.search("Есть ли упоминание машины?", None, 5)

    assert fragments
    assert "автомобиль" in fragments[0].text.lower()
