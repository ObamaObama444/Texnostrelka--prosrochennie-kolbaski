from __future__ import annotations

import logging

import httpx
import numpy as np

from bookverse.config import Settings
from bookverse.text import hashing_vector


logger = logging.getLogger(__name__)


class BaseEmbedder:
    backend_name = "base"

    def encode(self, texts: list[str]) -> np.ndarray:
        raise NotImplementedError


class HashingEmbedder(BaseEmbedder):
    def __init__(self, dim: int, *, backend_name: str = "hashing") -> None:
        self.dim = dim
        self.backend_name = backend_name

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = [hashing_vector(text, self.dim) for text in texts]
        return np.asarray(vectors, dtype="float32")


class MistralEmbedder(BaseEmbedder):
    def __init__(self, *, base_url: str, api_key: str, model_name: str, timeout: float, batch_size: int, fallback_dim: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.timeout = timeout
        self.batch_size = max(1, batch_size)
        self.fallback_dim = fallback_dim
        self.backend_name = f"mistral:{model_name}"

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.fallback_dim), dtype="float32")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        rows: list[list[float]] = []
        with httpx.Client(timeout=self.timeout) as client:
            for start in range(0, len(texts), self.batch_size):
                batch = texts[start : start + self.batch_size]
                response = client.post(
                    f"{self.base_url}/embeddings",
                    json={"model": self.model_name, "input": batch},
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json()
                vectors = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
                rows.extend([list(item["embedding"]) for item in vectors])

        matrix = np.asarray(rows, dtype="float32")
        if matrix.size == 0:
            return np.zeros((0, self.fallback_dim), dtype="float32")
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms = np.clip(norms, 1e-12, None)
        return matrix / norms


class SentenceTransformerEmbedder(BaseEmbedder):
    backend_name = "sentence-transformers"

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore

        self.model = SentenceTransformer(model_name)

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.asarray(
            self.model.encode(texts, normalize_embeddings=True, convert_to_numpy=True),
            dtype="float32",
        )


def build_embedder(settings: Settings) -> BaseEmbedder:
    backend = settings.embedding_backend.strip().lower()
    if backend in {"mistral", "mistral-embed", "api"}:
        if settings.mistral_configured and settings.embed_model:
            return MistralEmbedder(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key or "",
                model_name=settings.embed_model,
                timeout=settings.llm_timeout,
                batch_size=settings.embedding_batch_size,
                fallback_dim=settings.vector_dim,
            )
        logger.warning("Mistral embeddings are not configured, using hashing fallback")
        return HashingEmbedder(settings.vector_dim, backend_name="hashing-fallback")
    if backend in {"sentence-transformers", "st", "transformers"}:
        try:
            return SentenceTransformerEmbedder(settings.embed_model)
        except Exception as error:  # pragma: no cover - exercised only with optional dependency
            logger.warning("Failed to initialize sentence-transformers backend, using hashing fallback: %s", error)
    return HashingEmbedder(settings.vector_dim)
