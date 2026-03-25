from __future__ import annotations

from pydantic import BaseModel, Field


class BookResponse(BaseModel):
    id: str
    title: str
    filename: str
    file_type: str
    upload_date: str
    status: str
    error_message: str | None = None
    chapter_count: int = 0
    chunk_count: int = 0


class BooksListResponse(BaseModel):
    items: list[BookResponse]
    llm_available: bool
    embedding_backend: str
    provider_name: str
    chat_model: str | None = None
    embed_model: str | None = None


class ImportBookResponse(BaseModel):
    book_id: str
    status: str
    message: str


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    book_ids: list[str] | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class FragmentResponse(BaseModel):
    book_id: str
    book_title: str
    chapter_number: int | None = None
    chapter_title: str | None = None
    line_start: int
    line_end: int
    char_start: int
    char_end: int
    text: str
    score: float
    lexical_score: float
    vector_score: float


class ReaderChunkResponse(BaseModel):
    id: str
    chunk_order: int
    chapter_number: int | None = None
    chapter_title: str | None = None
    line_start: int
    line_end: int
    char_start: int
    char_end: int
    text: str


class ChapterResponse(BaseModel):
    number: int | None = None
    title: str | None = None
    start_chunk: int


class SearchResponse(BaseModel):
    found: bool
    fragments: list[FragmentResponse]
    message: str | None = None


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    book_ids: list[str] | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    citations_k: int = Field(default=3, ge=1, le=10)


class AskResponse(BaseModel):
    found: bool
    answer: str
    citations: list[FragmentResponse]
    confidence: float = 0.0
    message: str | None = None


class StatusResponse(BaseModel):
    provider_name: str
    mistral_configured: bool
    llm_available: bool
    embedding_backend: str
    chat_model: str | None = None
    embed_model: str | None = None
    ready_books: int
    processing_books: int
    error_books: int
    total_books: int


class BookContentResponse(BaseModel):
    id: str
    title: str
    filename: str
    file_type: str
    status: str
    chapter_count: int
    chunk_count: int
    chapters: list[ChapterResponse]
    chunks: list[ReaderChunkResponse]
