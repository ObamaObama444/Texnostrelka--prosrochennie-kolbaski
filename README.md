# BookVerse Case

`BookVerse Case` сохраняет визуальную оболочку старого `BookVerse`, но внутри работает как Python-first сервис под кейс «Умный поиск по книгам».

Решение покрывает полный сценарий:

1. загрузка `.txt` и `.fb2` книг;
2. фоновая индексация с разбиением на главы и фрагменты;
3. hybrid retrieval `BM25 + Mistral embeddings + FAISS`;
4. grounded QA через `Mistral`, где ответ строится только по найденным цитатам;
5. честный refusal, если надежной опоры в текстах нет.

## Что внутри

- `FastAPI` и `Jinja2` для API и web UI
- `SQLite` для книг, статусов и фрагментов
- `FAISS` для локального векторного индекса
- `Mistral embeddings` как основной backend для semantic retrieval
- `Mistral chat completions` для answer generation по найденным citations
- legacy shell `BookVerse` как интерфейс для жюри

## Быстрый запуск

```bash
cd BookVerse
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env
uvicorn bookverse.main:app --reload
```

После этого сервис будет доступен на [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Настройка Mistral

Проект ожидает Mistral-конфиг через `.env` или переменные окружения:

```bash
export MISTRAL_API_KEY="..."
export MISTRAL_BASE_URL="https://api.mistral.ai/v1"
export MISTRAL_CHAT_MODEL="mistral-small-latest"
export MISTRAL_EMBED_MODEL="mistral-embed"
export MISTRAL_TIMEOUT="45"
```

Поддерживаются и backward-compatible алиасы:

- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL`
- `EMBEDDING_MODEL`

Если `Mistral` не настроен:

- загрузка и лексический поиск все равно работают;
- embeddings переходят на локальный hashing fallback;
- `/api/ask` честно сообщает, что QA-режим временно недоступен.

Если ключ уже где-то светился публично, лучше его ротировать после локальной доводки проекта.

## Интерфейс для жюри

На главной странице сохранен старый shell `BookVerse`:

- библиотека книг;
- поиск по списку и сортировка;
- чекбоксы для ограничения области поиска;
- боковая панель `Обзор / Инструменты / Обновить книги`;
- инструмент `Поиск фрагментов`;
- инструмент `Ответы по книге`.

В панели видно:

- сколько книг загружено;
- сколько готовы к поиску;
- сколько в индексации;
- сколько с ошибкой;
- какой retrieval backend сейчас активен;
- доступен ли `Mistral QA`.

## Демо-книги

В репозитории лежат готовые файлы для быстрой проверки:

- `demo_books/family_epilogue.txt`
- `demo_books/family_epilogue.fb2`
- `demo_books/garage_story.txt`

## Jury Flow

### Сценарий 1. Поиск фрагментов

1. Загрузи `demo_books/family_epilogue.txt`.
2. Дождись статуса `Готово`.
3. Открой `Инструменты -> Поиск фрагментов`.
4. Введи:

```text
Найди, где говорится о семейной жизни героев
```

Ожидаемый результат:

- сервис вернет фрагмент из `Глава 2`;
- в выдаче будут книга, глава, строки и score.

### Сценарий 2. Ответ по книге

1. Загрузи `demo_books/family_epilogue.txt`.
2. Открой `Инструменты -> Ответы по книге`.
3. Введи:

```text
Что произошло с героями в эпилоге?
```

Ожидаемый результат:

- ответ будет опираться на найденные citations;
- внизу появятся цитаты из релевантного фрагмента.

### Сценарий 3. Синонимы в поиске

1. Загрузи `demo_books/garage_story.txt`.
2. Открой `Инструменты -> Поиск фрагментов`.
3. Введи:

```text
Есть ли в тексте упоминание машины?
```

Ожидаемый результат:

- сервис найдет фрагмент, где в тексте есть `автомобиль`;
- это показывает, что retrieval не ограничен наивным совпадением словоформ.

### Сценарий 4. Честный отказ

Вопрос:

```text
Что герои говорили о космических перелетах?
```

Ожидаемый результат:

- сервис не выдумывает ответ;
- показывает refusal в духе: `В загруженных текстах нет надежного ответа на этот вопрос.`

## API

- `GET /health` — базовый healthcheck
- `GET /api/status` — статус провайдера, backend и счетчики книг
- `GET /api/books` — книги + provider metadata
- `POST /api/books/import` — загрузка книги
- `DELETE /api/books/{book_id}` — удаление книги
- `POST /api/search` — поиск релевантных фрагментов
- `POST /api/ask` — grounded QA с citations и confidence

### Пример поиска

```bash
curl -X POST http://127.0.0.1:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query":"семейная жизнь героев","top_k":5}'
```

### Пример вопроса

```bash
curl -X POST http://127.0.0.1:8000/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"Что произошло с героями в эпилоге?","top_k":5,"citations_k":3}'
```

## Тесты

```bash
source .venv/bin/activate
pytest
```

Покрыто:

- парсинг `.txt` и `.fb2`;
- chunking без перехода через границы главы;
- hybrid retrieval;
- статусный API;
- интеграционный сценарий `upload -> search -> ask -> delete`;
- graceful degradation при сбое `Mistral QA`.
