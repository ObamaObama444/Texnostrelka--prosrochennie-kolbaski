from __future__ import annotations

from pathlib import Path
import time

from fastapi.testclient import TestClient

from bookverse.main import create_app
from bookverse.qa import LLMProviderError


class BrokenLLMClient:
    def answer(self, question, fragments):
        raise LLMProviderError("provider offline")


def wait_until_ready(client: TestClient, book_id: str, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        books = client.get("/api/books").json()["items"]
        current = next((book for book in books if book["id"] == book_id), None)
        if current and current["status"] == "READY":
            return
        time.sleep(0.1)
    raise AssertionError(f"Book {book_id} did not reach READY in time")


def test_api_upload_search_ask_and_delete(settings, fake_llm) -> None:
    app = create_app(settings=settings, qa_client=fake_llm)
    client = TestClient(app)

    fixture = Path(__file__).resolve().parents[1] / "demo_books" / "family_epilogue.txt"
    with fixture.open("rb") as source:
        response = client.post(
            "/api/books/import",
            files={"file": (fixture.name, source, "text/plain")},
        )
    assert response.status_code == 200
    book_id = response.json()["book_id"]
    wait_until_ready(client, book_id)

    books = client.get("/api/books").json()["items"]
    assert any(book["id"] == book_id and book["status"] == "READY" for book in books)

    reader_page = client.get(f"/reader/{book_id}")
    assert reader_page.status_code == 200
    assert "BookVerse - Чтение" in reader_page.text
    assert "Поиск фрагментов" in reader_page.text
    assert "Ответы по книге" in reader_page.text

    content_response = client.get(f"/api/books/{book_id}/content")
    assert content_response.status_code == 200
    content_payload = content_response.json()
    assert content_payload["id"] == book_id
    assert content_payload["chunks"]
    assert content_payload["chapters"]

    search_response = client.post(
        "/api/search",
        json={"query": "Найди, где говорится о семейной жизни героев", "top_k": 5},
    )
    assert search_response.status_code == 200
    search_payload = search_response.json()
    assert search_payload["found"] is True
    assert any(fragment["chapter_number"] == 2 for fragment in search_payload["fragments"])

    ask_response = client.post(
        "/api/ask",
        json={"question": "Что произошло с героями в эпилоге?", "top_k": 5, "citations_k": 3},
    )
    assert ask_response.status_code == 200
    ask_payload = ask_response.json()
    assert ask_payload["found"] is True
    assert "семейной жизнью" in ask_payload["answer"].lower()
    assert ask_payload["citations"]

    refusal_response = client.post(
        "/api/ask",
        json={"question": "Что герои говорили о космических перелетах?", "top_k": 5, "citations_k": 3},
    )
    refusal_payload = refusal_response.json()
    assert refusal_payload["found"] is False
    assert "нет надежного ответа" in refusal_payload["answer"].lower()

    delete_response = client.delete(f"/api/books/{book_id}")
    assert delete_response.status_code == 200
    books_after_delete = client.get("/api/books").json()["items"]
    assert all(book["id"] != book_id for book in books_after_delete)


def test_status_endpoint_reports_provider_metadata(settings, fake_llm) -> None:
    app = create_app(settings=settings, qa_client=fake_llm)
    client = TestClient(app)

    status_response = client.get("/api/status")

    assert status_response.status_code == 200
    payload = status_response.json()
    assert payload["provider_name"] == "Mistral AI"
    assert payload["embedding_backend"] == "hashing"
    assert payload["chat_model"] == "mistral-small-latest"
    assert payload["embed_model"] == "mistral-embed"
    assert payload["total_books"] == 0


def test_ask_handles_provider_error_without_breaking_search(settings) -> None:
    app = create_app(settings=settings, qa_client=BrokenLLMClient())
    client = TestClient(app)

    fixture = Path(__file__).resolve().parents[1] / "demo_books" / "family_epilogue.txt"
    with fixture.open("rb") as source:
        response = client.post(
            "/api/books/import",
            files={"file": (fixture.name, source, "text/plain")},
        )
    assert response.status_code == 200
    wait_until_ready(client, response.json()["book_id"])

    search_response = client.post(
        "/api/search",
        json={"query": "семейная жизнь героев", "top_k": 5},
    )
    assert search_response.status_code == 200
    assert search_response.json()["found"] is True

    ask_response = client.post(
        "/api/ask",
        json={"question": "Что произошло с героями в эпилоге?", "top_k": 5, "citations_k": 3},
    )
    assert ask_response.status_code == 200
    payload = ask_response.json()
    assert payload["found"] is False
    assert "mistral" in payload["answer"].lower()
    assert payload["citations"]
