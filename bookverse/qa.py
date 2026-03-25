from __future__ import annotations

import json
import re
from typing import Protocol, Sequence

import httpx

from bookverse.config import Settings
from bookverse.models import LLMAnswer, SearchFragment


class LLMClient(Protocol):
    def answer(self, question: str, fragments: Sequence[SearchFragment]) -> LLMAnswer:
        ...


class LLMNotConfiguredError(RuntimeError):
    pass


class LLMProviderError(RuntimeError):
    pass


class MistralClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def answer(self, question: str, fragments: Sequence[SearchFragment]) -> LLMAnswer:
        if not self.settings.mistral_configured or not self.settings.llm_model:
            raise LLMNotConfiguredError("Mistral API не настроен")

        citations = [
            {
                "citation_id": index,
                "book_title": fragment.book_title,
                "chapter_number": fragment.chapter_number,
                "chapter_title": fragment.chapter_title,
                "line_start": fragment.line_start,
                "line_end": fragment.line_end,
                "char_start": fragment.char_start,
                "char_end": fragment.char_end,
                "text": fragment.text,
            }
            for index, fragment in enumerate(fragments, start=1)
        ]
        system_prompt = (
            "Ты помогаешь отвечать на вопросы по книгам в сервисе BookVerse. "
            "Опирайся только на переданные цитаты. "
            "Если среди цитат нет достаточной опоры, верни supported=false и ответ "
            "\"В загруженных текстах нет надежного ответа на этот вопрос.\" "
            "Не придумывай факты и не добавляй сведения вне цитат. "
            "Верни только JSON-объект со схемой "
            "{\"supported\": bool, \"answer\": str, \"confidence\": float, \"message\": str|null}."
        )
        user_prompt = {
            "question": question,
            "citations": citations,
        }
        payload = {
            "model": self.settings.llm_model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            with httpx.Client(timeout=self.settings.llm_timeout) as client:
                response = client.post(f"{self.settings.llm_base_url.rstrip('/')}/chat/completions", json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as error:
            raise LLMProviderError("Mistral API временно недоступен") from error
        content = self._stringify_content(data["choices"][0]["message"]["content"])
        parsed = self._parse_json(content)
        return LLMAnswer(
            supported=bool(parsed.get("supported")),
            answer=str(parsed.get("answer", "")).strip(),
            confidence=float(parsed.get("confidence", 0.0)),
            message=str(parsed.get("message")).strip() if parsed.get("message") is not None else None,
        )

    @staticmethod
    def _parse_json(content: str) -> dict[str, object]:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if not match:
                return {"supported": False, "answer": content.strip(), "confidence": 0.0}
            return json.loads(match.group(0))

    @staticmethod
    def _stringify_content(content: object) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            rows: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    if "text" in item:
                        rows.append(str(item["text"]))
                    elif item.get("type") == "text" and isinstance(item.get("content"), str):
                        rows.append(str(item["content"]))
                else:
                    rows.append(str(item))
            return "".join(rows)
        return str(content)


class GroundedQAService:
    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def answer(self, question: str, fragments: Sequence[SearchFragment], citations_k: int) -> tuple[bool, str, list[SearchFragment], float, str | None]:
        citations = list(fragments[:citations_k])
        if not fragments:
            return False, "В загруженных текстах нет надежного ответа на этот вопрос. Возможно, ваш запрос не связан с текстом книги.", [], 0.0, "Ответ не найден"
        try:
            llm_answer = self.client.answer(question, citations)
        except LLMNotConfiguredError as error:
            return False, "Mistral API не настроен. Поиск фрагментов доступен, режим ответов временно отключен.", citations, 0.0, str(error)
        except LLMProviderError as error:
            return False, "Mistral временно недоступен. Поиск фрагментов продолжает работать.", citations, 0.0, str(error)

        if not llm_answer.supported:
            answer = llm_answer.answer.strip() or "В загруженных текстах нет надежного ответа на этот вопрос."
            if "возможно" not in answer.lower() and "не связан" not in answer.lower():
                answer = f"{answer} Возможно, ваш запрос не связан с текстом книги."
            return False, answer, citations, 0.0, llm_answer.message or "Нашлись только близкие фрагменты, но опоры для точного ответа недостаточно. Возможно, вопрос не связан с содержанием книги."
        return True, llm_answer.answer.strip(), citations, llm_answer.confidence, None
