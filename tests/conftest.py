from __future__ import annotations

from pathlib import Path

import pytest

from bookverse.config import Settings
from bookverse.models import LLMAnswer


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeLLMClient:
    def answer(self, question, fragments):
        question_lower = question.lower()
        context = " ".join(fragment.text for fragment in fragments).lower()
        if "космичес" in question_lower:
            return LLMAnswer(
                supported=False,
                answer="В загруженных текстах нет надежного ответа на этот вопрос.",
                confidence=0.11,
            )
        if "эпилог" in question_lower and ("семейной жизнью" in context or "семейной жизни" in context):
            return LLMAnswer(
                supported=True,
                answer="В эпилоге герои живут спокойной семейной жизнью и воспитывают детей.",
                confidence=0.93,
            )
        if fragments:
            return LLMAnswer(
                supported=True,
                answer=fragments[0].text.split(".")[0].strip() + ".",
                confidence=0.72,
            )
        return LLMAnswer(
            supported=False,
            answer="В загруженных текстах нет надежного ответа на этот вопрос.",
            confidence=0.05,
        )


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    settings = Settings(base_dir=PROJECT_ROOT)
    settings.data_dir = tmp_path / "data"
    settings.books_dir = settings.data_dir / "books"
    settings.index_dir = settings.data_dir / "index"
    settings.db_path = settings.data_dir / "bookverse.db"
    settings.embedding_backend = "hashing"
    settings.llm_api_key = None
    settings.llm_model = "mistral-small-latest"
    settings.embed_model = "mistral-embed"
    settings.ensure_directories()
    return settings


@pytest.fixture()
def fake_llm() -> FakeLLMClient:
    return FakeLLMClient()
