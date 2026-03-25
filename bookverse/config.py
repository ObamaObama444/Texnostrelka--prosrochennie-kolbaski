from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _env(name: str, *aliases: str, default: str | None = None) -> str | None:
    for key in (name, *aliases):
        raw = os.getenv(key)
        if raw is None:
            continue
        value = raw.strip()
        if value:
            return value
    return default


def _int_env(name: str, *aliases: str, default: int) -> int:
    raw = _env(name, *aliases, default=str(default))
    return int(raw or default)


def _float_env(name: str, *aliases: str, default: float) -> float:
    raw = _env(name, *aliases, default=str(default))
    return float(raw or default)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Settings:
    base_dir: Path = field(default_factory=lambda: PROJECT_ROOT)
    max_chunk_chars: int = field(default_factory=lambda: _int_env("BOOKVERSE_MAX_CHUNK_CHARS", default=1200))
    chunk_overlap_chars: int = field(default_factory=lambda: _int_env("BOOKVERSE_CHUNK_OVERLAP_CHARS", default=220))
    vector_dim: int = field(default_factory=lambda: _int_env("BOOKVERSE_VECTOR_DIM", default=1024))
    default_search_top_k: int = field(default_factory=lambda: _int_env("BOOKVERSE_SEARCH_TOP_K", default=5))
    default_citations_k: int = field(default_factory=lambda: _int_env("BOOKVERSE_CITATIONS_K", default=3))
    embedding_backend: str = field(default_factory=lambda: _env("EMBEDDING_BACKEND", default="mistral") or "mistral")
    embed_model: str = field(
        default_factory=lambda: _env("MISTRAL_EMBED_MODEL", "EMBEDDING_MODEL", default="mistral-embed")
        or "mistral-embed"
    )
    llm_base_url: str = field(
        default_factory=lambda: _env("MISTRAL_BASE_URL", "LLM_BASE_URL", default="https://api.mistral.ai/v1")
        or "https://api.mistral.ai/v1"
    )
    llm_api_key: str | None = field(default_factory=lambda: _env("MISTRAL_API_KEY", "LLM_API_KEY"))
    llm_model: str | None = field(
        default_factory=lambda: _env("MISTRAL_CHAT_MODEL", "LLM_MODEL", default="mistral-small-latest")
    )
    llm_timeout: float = field(default_factory=lambda: _float_env("MISTRAL_TIMEOUT", "LLM_TIMEOUT", default=45.0))
    embedding_batch_size: int = field(
        default_factory=lambda: _int_env("MISTRAL_EMBED_BATCH_SIZE", "BOOKVERSE_EMBED_BATCH_SIZE", default=32)
    )
    enable_fb2: bool = field(default_factory=lambda: _bool_env("BOOKVERSE_ENABLE_FB2", True))
    data_dir: Path = field(init=False)
    books_dir: Path = field(init=False)
    index_dir: Path = field(init=False)
    db_path: Path = field(init=False)
    templates_dir: Path = field(init=False)
    static_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        self.data_dir = self.base_dir / "data"
        self.books_dir = self.data_dir / "books"
        self.index_dir = self.data_dir / "index"
        self.db_path = self.data_dir / "bookverse.db"
        self.templates_dir = self.base_dir / "templates"
        self.static_dir = self.base_dir / "static"

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key and self.llm_model)

    @property
    def mistral_configured(self) -> bool:
        return bool(self.llm_api_key)

    @property
    def provider_name(self) -> str:
        return "Mistral AI"

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.books_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)
