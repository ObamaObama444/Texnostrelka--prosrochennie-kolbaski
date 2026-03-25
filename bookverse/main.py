from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import threading
import time
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from bookverse.config import Settings
from bookverse.embedding import build_embedder
from bookverse.ingest import BookIngestionService
from bookverse.qa import GroundedQAService, MistralClient
from bookverse.schemas import (
    AskRequest,
    AskResponse,
    BookResponse,
    BookContentResponse,
    BooksListResponse,
    ChapterResponse,
    FragmentResponse,
    ImportBookResponse,
    ReaderChunkResponse,
    SearchRequest,
    SearchResponse,
    StatusResponse,
)
from bookverse.search_index import HybridSearchIndex
from bookverse.storage import Repository


def is_weak_search_result(fragments: list[Any]) -> bool:
    if not fragments:
        return False
    top = fragments[0]
    top_lexical = float(getattr(top, "lexical_score", 0.0) or 0.0)
    top_vector = float(getattr(top, "vector_score", 0.0) or 0.0)
    top_score = float(getattr(top, "score", 0.0) or 0.0)
    if top_lexical >= 1.0:
        return False
    return top_score < 0.2 and top_vector < 0.78


def create_app(settings: Settings | None = None, qa_client: Any | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.ensure_directories()
    asset_version = str(int(time.time()))
    repository = Repository(settings.db_path)
    repository.init()
    search_index = HybridSearchIndex(settings=settings, repository=repository, embedder=build_embedder(settings))
    ingestion = BookIngestionService(settings=settings, repository=repository, search_index=search_index)
    qa_service = GroundedQAService(qa_client or MistralClient(settings))
    templates = Jinja2Templates(directory=str(settings.templates_dir))

    def provider_metadata() -> dict[str, Any]:
        return {
            "llm_available": settings.llm_configured,
            "mistral_configured": settings.mistral_configured,
            "embedding_backend": search_index.backend_name,
            "provider_name": settings.provider_name,
            "chat_model": settings.llm_model,
            "embed_model": settings.embed_model,
        }

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        search_index.rebuild()
        yield

    app = FastAPI(
        title="BookVerse Case",
        description="Умный поиск по книгам для кейса Цифровой вызов",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.repository = repository
    app.state.search_index = search_index
    app.state.ingestion = ingestion
    app.state.qa_service = qa_service
    app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")

    @app.middleware("http")
    async def disable_cache(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "request": request,
                **provider_metadata(),
                "asset_version": asset_version,
                "demo_queries": [
                    "Найди, где говорится о семейной жизни героев",
                    "Что произошло с героями в эпилоге?",
                    "Есть ли в текстах упоминание автомобиля?",
                ],
            },
        )

    @app.get("/reader/{book_id}", response_class=HTMLResponse)
    async def reader(request: Request, book_id: str) -> HTMLResponse:
        book = repository.get_book(book_id)
        if book is None:
            raise HTTPException(status_code=404, detail="Книга не найдена")
        return templates.TemplateResponse(
            request,
            "reader.html",
            {
                "request": request,
                "book_id": book.id,
                "book_title": book.title,
                "asset_version": asset_version,
            },
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/status", response_model=StatusResponse)
    async def status() -> StatusResponse:
        counts = repository.status_summary()
        return StatusResponse(
            **provider_metadata(),
            ready_books=counts["READY"],
            processing_books=counts["PROCESSING"],
            error_books=counts["ERROR"],
            total_books=counts["TOTAL"],
        )

    @app.get("/api/books", response_model=BooksListResponse)
    async def list_books() -> BooksListResponse:
        items = [BookResponse.model_validate(book, from_attributes=True) for book in repository.list_books()]
        return BooksListResponse(
            items=items,
            **provider_metadata(),
        )

    @app.get("/api/books/{book_id}/content", response_model=BookContentResponse)
    async def book_content(book_id: str) -> BookContentResponse:
        book = repository.get_book(book_id)
        if book is None:
            raise HTTPException(status_code=404, detail="Книга не найдена")
        if book.status != "READY":
            raise HTTPException(status_code=409, detail="Книга еще не готова к чтению")

        chunks = repository.get_book_chunks(book_id)
        chapters: list[ChapterResponse] = []
        seen_chapters: set[tuple[int | None, str | None]] = set()
        for chunk in chunks:
            key = (chunk.chapter_number, chunk.chapter_title)
            if key in seen_chapters:
                continue
            seen_chapters.add(key)
            chapters.append(
                ChapterResponse(
                    number=chunk.chapter_number,
                    title=chunk.chapter_title,
                    start_chunk=chunk.chunk_order,
                )
            )

        return BookContentResponse(
            id=book.id,
            title=book.title,
            filename=book.filename,
            file_type=book.file_type,
            status=book.status,
            chapter_count=book.chapter_count,
            chunk_count=book.chunk_count,
            chapters=chapters,
            chunks=[
                ReaderChunkResponse.model_validate(chunk, from_attributes=True)
                for chunk in chunks
            ],
        )

    @app.post("/api/books/import", response_model=ImportBookResponse)
    async def import_book(file: UploadFile = File(...)) -> ImportBookResponse:
        try:
            book_id, status = ingestion.import_upload(file)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        finally:
            await file.close()
        threading.Thread(target=ingestion.process_book, args=(book_id,), daemon=True).start()
        return ImportBookResponse(
            book_id=book_id,
            status=status,
            message="Книга загружена и отправлена на индексацию.",
        )

    @app.delete("/api/books/{book_id}", response_model=ImportBookResponse)
    async def delete_book(book_id: str) -> ImportBookResponse:
        book = ingestion.delete_book(book_id)
        if book is None:
            raise HTTPException(status_code=404, detail="Книга не найдена")
        return ImportBookResponse(book_id=book_id, status="DELETED", message="Книга удалена.")

    @app.post("/api/search", response_model=SearchResponse)
    async def search(request_data: SearchRequest) -> SearchResponse:
        fragments = search_index.search(
            request_data.query,
            request_data.book_ids,
            request_data.top_k or settings.default_search_top_k,
        )
        if not fragments:
            return SearchResponse(found=False, fragments=[], message="Подходящие фрагменты не найдены.")
        message = None
        if is_weak_search_result(fragments):
            message = "Нашлись только приблизительные совпадения. Возможно, ваш запрос не связан с текстом книги."
        return SearchResponse(
            found=True,
            fragments=[FragmentResponse.model_validate(fragment, from_attributes=True) for fragment in fragments],
            message=message,
        )

    @app.post("/api/ask", response_model=AskResponse)
    async def ask(request_data: AskRequest) -> AskResponse:
        fragments = search_index.search(
            request_data.question,
            request_data.book_ids,
            request_data.top_k or settings.default_search_top_k,
        )
        found, answer, citations, confidence, message = qa_service.answer(
            request_data.question,
            fragments,
            request_data.citations_k or settings.default_citations_k,
        )
        return AskResponse(
            found=found,
            answer=answer,
            citations=[FragmentResponse.model_validate(fragment, from_attributes=True) for fragment in citations],
            confidence=confidence,
            message=message,
        )

    return app


app = create_app()
