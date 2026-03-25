from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ChapterSpan:
    number: int
    title: str
    start: int
    end: int


@dataclass(slots=True)
class ChunkRecord:
    id: str
    book_id: str
    chunk_order: int
    chapter_number: int | None
    chapter_title: str | None
    line_start: int
    line_end: int
    char_start: int
    char_end: int
    text: str
    search_text: str


@dataclass(slots=True)
class ParsedBook:
    title: str
    file_type: str
    content: str
    chapters: list[ChapterSpan]
    chunks: list[ChunkRecord]


@dataclass(slots=True)
class BookRecord:
    id: str
    title: str
    filename: str
    file_type: str
    upload_date: str
    status: str
    error_message: str | None
    source_path: str
    chapter_count: int
    chunk_count: int

    @property
    def source_file(self) -> Path:
        return Path(self.source_path)


@dataclass(slots=True)
class SearchFragment:
    chunk_id: str
    book_id: str
    book_title: str
    chapter_number: int | None
    chapter_title: str | None
    line_start: int
    line_end: int
    char_start: int
    char_end: int
    text: str
    score: float
    lexical_score: float
    vector_score: float


@dataclass(slots=True)
class LLMAnswer:
    supported: bool
    answer: str
    confidence: float
    message: str | None = None

