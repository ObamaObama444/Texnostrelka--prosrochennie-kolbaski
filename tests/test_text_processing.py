from __future__ import annotations

from pathlib import Path

from bookverse.text import parse_book_content


def test_parse_txt_respects_chapter_boundaries() -> None:
    raw = (
        "Глава 1\n\n"
        "Первая часть рассказывает о знакомстве героев и их сомнениях.\n\n"
        "Глава 2\n\n"
        "Во второй части герои принимают решение о семейной жизни и будущем доме."
    ).encode("utf-8")

    parsed = parse_book_content(
        book_id="book_txt",
        filename="sample.txt",
        raw_bytes=raw,
        file_type="TXT",
        max_chunk_chars=90,
        overlap_chars=20,
    )

    assert len(parsed.chapters) == 2
    chapter_bounds = {chapter.number: chapter for chapter in parsed.chapters}
    assert any(chunk.chapter_number == 2 for chunk in parsed.chunks)
    for chunk in parsed.chunks:
        bounds = chapter_bounds[chunk.chapter_number or 1]
        assert bounds.start <= chunk.char_start < chunk.char_end <= bounds.end
        assert chunk.line_start >= 1
        assert chunk.line_end >= chunk.line_start


def test_parse_fb2_extracts_chapters_and_text() -> None:
    fixture = Path(__file__).resolve().parents[1] / "demo_books" / "family_epilogue.fb2"
    parsed = parse_book_content(
        book_id="book_fb2",
        filename=fixture.name,
        raw_bytes=fixture.read_bytes(),
        file_type="FB2",
        max_chunk_chars=220,
        overlap_chars=40,
    )

    assert len(parsed.chapters) >= 2
    assert any("новую жизнь" in chunk.text.lower() for chunk in parsed.chunks)
    assert all(chunk.chapter_title for chunk in parsed.chunks)
    assert not any("глава глава" in chunk.text.lower() for chunk in parsed.chunks)
    assert all(chunk.text.strip().lower() not in {"глава 1", "глава 2", "глава 3"} for chunk in parsed.chunks)
