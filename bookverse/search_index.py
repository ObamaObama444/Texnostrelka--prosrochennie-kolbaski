from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import threading
from typing import Iterable

try:
    import faiss  # type: ignore
except Exception:  # pragma: no cover - fallback covered instead
    faiss = None

import numpy as np

from bookverse.config import Settings
from bookverse.embedding import BaseEmbedder
from bookverse.models import ChunkRecord, SearchFragment
from bookverse.storage import Repository
from bookverse.text import extract_requested_chapter, query_terms


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SearchCandidate:
    index: int
    lexical_score: float = 0.0
    vector_score: float = 0.0
    rank_score: float = 0.0


class BM25Index:
    def __init__(self, documents: list[list[str]]) -> None:
        self.documents = documents
        self.avgdl = sum(len(doc) for doc in documents) / max(1, len(documents))
        self.k1 = 1.5
        self.b = 0.75
        self.doc_freqs = [Counter(doc) for doc in documents]
        self.idf: dict[str, float] = {}
        df = Counter()
        for doc in documents:
            for term in set(doc):
                df[term] += 1
        total = len(documents)
        for term, count in df.items():
            self.idf[term] = np.log1p((total - count + 0.5) / (count + 0.5)) + 1.0

    def score(self, query: list[str], allowed: set[int] | None = None) -> dict[int, float]:
        if not query:
            return {}
        scores: dict[int, float] = {}
        for index, frequencies in enumerate(self.doc_freqs):
            if allowed is not None and index not in allowed:
                continue
            length = len(self.documents[index]) or 1
            total = 0.0
            for term in query:
                freq = frequencies.get(term)
                if not freq:
                    continue
                idf = self.idf.get(term, 0.0)
                numerator = freq * (self.k1 + 1.0)
                denominator = freq + self.k1 * (1.0 - self.b + self.b * length / self.avgdl)
                total += idf * numerator / denominator
            if total > 0:
                scores[index] = total
        return scores


class HybridSearchIndex:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: Repository,
        embedder: BaseEmbedder,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.embedder = embedder
        self._lock = threading.RLock()
        self._rebuild_lock = threading.Lock()
        self._bm25: BM25Index | None = None
        self._chunks: list[ChunkRecord] = []
        self._book_titles: dict[str, str] = {}
        self._embeddings: np.ndarray = np.zeros((0, settings.vector_dim), dtype="float32")
        self._faiss_index = None
        self._chunk_ids_path = self.settings.index_dir / "chunk_ids.json"
        self._vectors_path = self.settings.index_dir / "embeddings.npy"
        self._faiss_path = self.settings.index_dir / "vectors.faiss"

    @property
    def backend_name(self) -> str:
        return self.embedder.backend_name

    def rebuild(self) -> None:
        with self._rebuild_lock:
            chunks = self.repository.get_ready_chunks()
            book_titles = self.repository.ready_titles()
            lexical_docs = [chunk.search_text.split() for chunk in chunks]
            bm25 = BM25Index(lexical_docs) if lexical_docs else None

            if not chunks:
                self._write_snapshot_metadata([])
                with self._lock:
                    self._chunks = []
                    self._book_titles = {}
                    self._bm25 = None
                    self._embeddings = np.zeros((0, self.settings.vector_dim), dtype="float32")
                    self._faiss_index = None
                return

            chunk_ids = [chunk.id for chunk in chunks]
            loaded = self._load_vectors_snapshot(chunk_ids)
            if loaded is None:
                embeddings = self.embedder.encode([chunk.text for chunk in chunks])
                faiss_index = self._build_faiss(embeddings)
                self._persist_vectors_snapshot(chunk_ids, embeddings, faiss_index)
            else:
                embeddings, faiss_index = loaded

            with self._lock:
                self._chunks = chunks
                self._book_titles = book_titles
                self._bm25 = bm25
                self._embeddings = embeddings
                self._faiss_index = faiss_index

    def search(self, query: str, book_ids: list[str] | None, top_k: int) -> list[SearchFragment]:
        with self._lock:
            if not self._chunks or self._bm25 is None:
                return []

            selected_books = None if book_ids is None else set(book_ids)
            chapter_filter = extract_requested_chapter(query)
            allowed = {
                index
                for index, chunk in enumerate(self._chunks)
                if (selected_books is None or chunk.book_id in selected_books)
                and (chapter_filter is None or chunk.chapter_number == chapter_filter)
            }
            if not allowed:
                return []

            terms = query_terms(query)
            lexical_scores = self._bm25.score(terms, allowed)
            vector_scores = self._vector_scores(query, allowed, limit=max(20, top_k * 8))

            combined: dict[int, SearchCandidate] = defaultdict(lambda: SearchCandidate(index=-1))

            for rank, (index, score) in enumerate(sorted(lexical_scores.items(), key=lambda item: item[1], reverse=True), start=1):
                candidate = combined[index]
                candidate.index = index
                candidate.lexical_score = score
                candidate.rank_score += 1.0 / (60 + rank)

            for rank, (index, score) in enumerate(vector_scores, start=1):
                candidate = combined[index]
                candidate.index = index
                candidate.vector_score = score
                candidate.rank_score += 1.0 / (60 + rank)

            results = [
                candidate
                for candidate in combined.values()
                if candidate.lexical_score > 0 or candidate.vector_score >= 0.12
            ]
            results.sort(
                key=lambda candidate: (
                    candidate.rank_score + candidate.lexical_score * 0.08 + candidate.vector_score * 0.15
                ),
                reverse=True,
            )

            fragments: list[SearchFragment] = []
            for candidate in results[:top_k]:
                chunk = self._chunks[candidate.index]
                fragments.append(
                    SearchFragment(
                        chunk_id=chunk.id,
                        book_id=chunk.book_id,
                        book_title=self._book_titles.get(chunk.book_id, chunk.book_id),
                        chapter_number=chunk.chapter_number,
                        chapter_title=chunk.chapter_title,
                        line_start=chunk.line_start,
                        line_end=chunk.line_end,
                        char_start=chunk.char_start,
                        char_end=chunk.char_end,
                        text=chunk.text,
                        score=round(candidate.rank_score + candidate.lexical_score * 0.08 + candidate.vector_score * 0.15, 4),
                        lexical_score=round(candidate.lexical_score, 4),
                        vector_score=round(candidate.vector_score, 4),
                    )
                )
            return fragments

    def _vector_scores(self, query: str, allowed: set[int], limit: int) -> list[tuple[int, float]]:
        if self._embeddings.size == 0:
            return []
        try:
            query_vector = self.embedder.encode([query])
        except Exception as error:
            logger.warning("Vector query failed, falling back to lexical retrieval only: %s", error)
            return []
        if self._faiss_index is not None and faiss is not None:
            search_limit = min(len(self._chunks), max(limit, len(allowed)))
            scores, indices = self._faiss_index.search(query_vector, search_limit)
            rows: list[tuple[int, float]] = []
            for index, score in zip(indices[0].tolist(), scores[0].tolist()):
                if index < 0 or index not in allowed:
                    continue
                rows.append((index, float(score)))
                if len(rows) >= limit:
                    break
            return rows

        similarities = self._embeddings @ query_vector[0]
        ranked = sorted(
            ((index, float(score)) for index, score in enumerate(similarities.tolist()) if index in allowed),
            key=lambda item: item[1],
            reverse=True,
        )
        return ranked[:limit]

    def _build_faiss(self, vectors: np.ndarray):
        if faiss is None:
            return None
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)
        return index

    def _write_snapshot_metadata(self, chunk_ids: Iterable[str]) -> None:
        payload = {
            "chunk_ids": list(chunk_ids),
            "backend": self.backend_name,
        }
        self._chunk_ids_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _persist_vectors_snapshot(self, chunk_ids: list[str], embeddings: np.ndarray, faiss_index) -> None:
        self._write_snapshot_metadata(chunk_ids)
        np.save(self._vectors_path, embeddings)
        if faiss is not None and faiss_index is not None:
            faiss.write_index(faiss_index, str(self._faiss_path))

    def _load_vectors_snapshot(self, chunk_ids: list[str]) -> tuple[np.ndarray, object | None] | None:
        if not self._chunk_ids_path.exists() or not self._vectors_path.exists():
            return None
        try:
            snapshot = json.loads(self._chunk_ids_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        if isinstance(snapshot, list):
            saved_ids = snapshot
            saved_backend = None
        else:
            saved_ids = snapshot.get("chunk_ids", [])
            saved_backend = snapshot.get("backend")
        if saved_ids != chunk_ids:
            return None
        if saved_backend != self.backend_name:
            return None
        embeddings = np.load(self._vectors_path)
        if faiss is not None and self._faiss_path.exists():
            faiss_index = faiss.read_index(str(self._faiss_path))
        else:
            faiss_index = self._build_faiss(embeddings)
        logger.info("Loaded vector index snapshot from disk")
        return embeddings, faiss_index
