const state = {
  books: [],
  pollHandle: null,
};

const els = {
  uploadForm: document.getElementById("upload-form"),
  uploadInput: document.getElementById("upload-input"),
  uploadStatus: document.getElementById("upload-status"),
  booksList: document.getElementById("books-list"),
  booksSummary: document.getElementById("books-summary"),
  refreshBooks: document.getElementById("refresh-books"),
  searchForm: document.getElementById("search-form"),
  searchQuery: document.getElementById("search-query"),
  searchStatus: document.getElementById("search-status"),
  searchResults: document.getElementById("search-results"),
  askForm: document.getElementById("ask-form"),
  askQuery: document.getElementById("question-query"),
  askStatus: document.getElementById("ask-status"),
  answerOutput: document.getElementById("answer-output"),
  answerConfidence: document.getElementById("answer-confidence"),
  citationResults: document.getElementById("citation-results"),
  tabButtons: Array.from(document.querySelectorAll(".tab-btn")),
  tabPanels: Array.from(document.querySelectorAll(".tab-panel")),
  exampleButtons: Array.from(document.querySelectorAll("[data-example]")),
};

function setStatus(node, text, isError = false) {
  if (!node) return;
  node.textContent = text;
  node.classList.toggle("error", Boolean(isError));
}

function currentScope() {
  return document.querySelector('input[name="scope"]:checked')?.value || "all";
}

function selectedBookIds() {
  if (currentScope() === "all") return null;
  const selected = Array.from(document.querySelectorAll('input[name="book-select"]:checked'));
  return selected.map((input) => input.value);
}

function statusBadge(status) {
  const value = (status || "").toUpperCase();
  if (value === "READY") return ["Готово", "status-ready"];
  if (value === "PROCESSING") return ["Индексация", "status-processing"];
  return ["Ошибка", "status-error"];
}

function renderBooks() {
  const readyCount = state.books.filter((book) => book.status === "READY").length;
  els.booksSummary.textContent = `${state.books.length} книг, готово ${readyCount}`;

  if (!state.books.length) {
    els.booksList.innerHTML = '<div class="empty-box">Пока книг нет. Загрузите первую книгу для демонстрации кейса.</div>';
    return;
  }

  els.booksList.innerHTML = state.books.map((book) => {
    const [statusLabel, statusClass] = statusBadge(book.status);
    const disabled = book.status !== "READY" ? "disabled" : "";
    const error = book.error_message ? `<div class="book-meta">${book.error_message}</div>` : "";
    return `
      <article class="book-card">
        <div class="book-top">
          <label class="book-actions">
            <input type="checkbox" name="book-select" value="${book.id}" ${disabled}>
            <div>
              <div class="book-title">${book.title}</div>
              <div class="book-meta">${book.filename} · ${book.file_type} · chunks: ${book.chunk_count}</div>
            </div>
          </label>
          <span class="status-pill ${statusClass}">${statusLabel}</span>
        </div>
        <div class="book-bottom">
          <div class="book-meta">Глав: ${book.chapter_count} · Загружена: ${new Date(book.upload_date).toLocaleString("ru-RU")}</div>
          <button class="danger-btn" type="button" data-delete="${book.id}">Удалить</button>
        </div>
        ${error}
      </article>
    `;
  }).join("");

  document.querySelectorAll("[data-delete]").forEach((button) => {
    button.addEventListener("click", async () => {
      const bookId = button.dataset.delete;
      if (!bookId) return;
      setStatus(els.uploadStatus, "Удаляю книгу...");
      const response = await fetch(`/api/books/${bookId}`, { method: "DELETE" });
      if (!response.ok) {
        setStatus(els.uploadStatus, "Не удалось удалить книгу.", true);
        return;
      }
      await loadBooks();
      setStatus(els.uploadStatus, "Книга удалена.");
    });
  });
}

async function loadBooks() {
  const response = await fetch("/api/books");
  if (!response.ok) {
    setStatus(els.uploadStatus, "Не удалось получить список книг.", true);
    return;
  }
  const payload = await response.json();
  state.books = payload.items || [];
  renderBooks();

  const hasProcessing = state.books.some((book) => book.status === "PROCESSING");
  clearTimeout(state.pollHandle);
  if (hasProcessing) {
    setStatus(els.uploadStatus, "Индексация еще идет. Список обновится автоматически.");
    state.pollHandle = setTimeout(loadBooks, 2500);
  }
}

function renderFragments(target, fragments) {
  if (!target) return;
  if (!fragments.length) {
    target.innerHTML = '<div class="empty-box">Фрагменты появятся здесь.</div>';
    return;
  }
  target.innerHTML = fragments.map((fragment) => `
    <article class="result-card">
      <div class="result-meta">
        <span>${fragment.book_title}</span>
        <span>глава ${fragment.chapter_number ?? "—"}</span>
        <span>${fragment.chapter_title ?? "Без названия"}</span>
        <span>строки ${fragment.line_start}-${fragment.line_end}</span>
        <span>score ${fragment.score.toFixed(4)}</span>
      </div>
      <p class="result-text">${fragment.text}</p>
    </article>
  `).join("");
}

async function submitJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(body.detail || "Не удалось выполнить запрос.");
  }
  return body;
}

els.uploadForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = els.uploadInput?.files?.[0];
  if (!file) {
    setStatus(els.uploadStatus, "Сначала выберите файл книги.", true);
    return;
  }
  const formData = new FormData();
  formData.append("file", file);
  setStatus(els.uploadStatus, `Загружаю ${file.name}...`);
  const response = await fetch("/api/books/import", { method: "POST", body: formData });
  const payload = await response.json();
  if (!response.ok) {
    setStatus(els.uploadStatus, payload.detail || "Ошибка загрузки книги.", true);
    return;
  }
  setStatus(els.uploadStatus, payload.message);
  els.uploadForm.reset();
  await loadBooks();
});

els.refreshBooks?.addEventListener("click", () => loadBooks());

els.searchForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = els.searchQuery.value.trim();
  if (!query) {
    setStatus(els.searchStatus, "Введите запрос для поиска.", true);
    return;
  }
  setStatus(els.searchStatus, "Ищу фрагменты...");
  try {
    const payload = await submitJson("/api/search", {
      query,
      book_ids: selectedBookIds(),
      top_k: 5,
    });
    if (!payload.found) {
      setStatus(els.searchStatus, payload.message || "Ничего не найдено.");
      renderFragments(els.searchResults, []);
      return;
    }
    setStatus(els.searchStatus, `Найдено ${payload.fragments.length} фрагментов.`);
    renderFragments(els.searchResults, payload.fragments);
  } catch (error) {
    setStatus(els.searchStatus, error.message, true);
  }
});

els.askForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = els.askQuery.value.trim();
  if (!question) {
    setStatus(els.askStatus, "Введите вопрос.", true);
    return;
  }
  setStatus(els.askStatus, "Ищу опорные фрагменты и формирую ответ...");
  els.answerOutput.textContent = "Ответ формируется...";
  try {
    const payload = await submitJson("/api/ask", {
      question,
      book_ids: selectedBookIds(),
      top_k: 5,
      citations_k: 3,
    });
    els.answerOutput.textContent = payload.answer;
    els.answerConfidence.textContent = `confidence: ${(payload.confidence || 0).toFixed(2)}`;
    renderFragments(els.citationResults, payload.citations || []);
    if (!payload.found) {
      setStatus(els.askStatus, payload.message || payload.answer);
      return;
    }
    setStatus(els.askStatus, `Ответ основан на ${(payload.citations || []).length} цитатах.`);
  } catch (error) {
    els.answerOutput.textContent = "Не удалось получить ответ.";
    setStatus(els.askStatus, error.message, true);
    renderFragments(els.citationResults, []);
  }
});

els.tabButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const tab = button.dataset.tab;
    els.tabButtons.forEach((node) => node.classList.toggle("active", node === button));
    els.tabPanels.forEach((panel) => panel.classList.toggle("active", panel.id === `tab-${tab}`));
  });
});

els.exampleButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const example = button.dataset.example || "";
    els.searchQuery.value = example;
    els.askQuery.value = example;
  });
});

renderFragments(els.searchResults, []);
renderFragments(els.citationResults, []);
loadBooks();
