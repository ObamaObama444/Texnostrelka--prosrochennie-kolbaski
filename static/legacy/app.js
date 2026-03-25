const state = {
  books: [],
  currentView: "overview",
  pollHandle: null,
  panelOpen: false,
  selectedBooks: new Set(),
  prefillSearchQuery: "",
  prefillAskQuery: "",
  status: {
    providerName: window.BOOKVERSE_CONFIG?.providerName || "Mistral AI",
    mistralConfigured: Boolean(window.BOOKVERSE_CONFIG?.llmAvailable),
    llmAvailable: Boolean(window.BOOKVERSE_CONFIG?.llmAvailable),
    embeddingBackend: window.BOOKVERSE_CONFIG?.embeddingBackend || "unknown",
    chatModel: window.BOOKVERSE_CONFIG?.chatModel || null,
    embedModel: window.BOOKVERSE_CONFIG?.embedModel || null,
    readyBooks: 0,
    processingBooks: 0,
    errorBooks: 0,
    totalBooks: 0,
  },
};

const el = {
  booksGrid: document.getElementById("books-grid"),
  emptyState: document.getElementById("empty-state"),
  errorMessage: document.getElementById("error-message"),
  loading: document.getElementById("loading"),
  uploadOverlay: document.getElementById("upload-overlay"),
  uploadButton: document.getElementById("uploadButton"),
  uploadCtaBtn: document.getElementById("uploadCtaBtn"),
  closeModalBtn: document.getElementById("closeModalBtn"),
  fileInput: document.getElementById("file-input"),
  uploadNowBtn: document.getElementById("uploadNowBtn"),
  panel: document.getElementById("right-panel"),
  panelScreen: document.getElementById("panel-screen"),
  menuButton: document.getElementById("menuButton"),
  closeBtn: document.getElementById("closeBtn"),
  refreshBooksBtn: document.getElementById("refreshBooksBtn"),
  showToolsBtn: document.getElementById("showToolsBtn"),
  showOverviewBtn: document.getElementById("showOverviewBtn"),
  sortBy: document.getElementById("sort-by"),
  librarySearchInput: document.getElementById("library-search-input"),
};

function showError(text) {
  if (!el.errorMessage) return;
  el.errorMessage.textContent = text;
  el.errorMessage.style.display = text ? "block" : "none";
}

function setStatusLine(node, text, isError = false) {
  if (!node) return;
  node.textContent = text;
  node.classList.toggle("error", Boolean(isError));
}

function setCaption(node, text, tone = "neutral") {
  if (!node) return;
  node.textContent = text;
  node.dataset.tone = tone;
}

function openPanel() {
  state.panelOpen = true;
  el.panel?.classList.add("visible");
  el.panel?.classList.add("open");
}

function closePanel() {
  state.panelOpen = false;
  el.panel?.classList.remove("visible");
  el.panel?.classList.remove("open");
}

function openUploadModal() {
  if (el.uploadOverlay) el.uploadOverlay.style.display = "flex";
}

function closeUploadModal() {
  if (el.uploadOverlay) el.uploadOverlay.style.display = "none";
}

function updateUploadProgress(percent, text) {
  const fill = document.querySelector(".progress-fill");
  const status = document.querySelector(".progress-text");
  if (fill) fill.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  if (status) status.textContent = text || `${percent}%`;
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : null;
  if (!response.ok) {
    throw new Error(payload?.detail || payload?.message || `HTTP ${response.status}`);
  }
  return payload;
}

function syncSelectedBooks() {
  const readyIds = new Set(
    state.books.filter((book) => book.status === "READY").map((book) => book.id)
  );
  state.selectedBooks = new Set(
    Array.from(state.selectedBooks).filter((bookId) => readyIds.has(bookId))
  );
}

function selectedReadyBookIds() {
  return Array.from(state.selectedBooks).filter((bookId) =>
    state.books.some((book) => book.id === bookId && book.status === "READY")
  );
}

function statusClass(status) {
  if (status === "READY") return ["Готово", "ready"];
  if (status === "PROCESSING") return ["Индексация", "processing"];
  return ["Ошибка", "error"];
}

function filteredBooks() {
  const query = (el.librarySearchInput?.value || "").trim().toLowerCase();
  const sortBy = el.sortBy?.value || "date";
  let items = [...state.books];
  if (query) {
    items = items.filter((book) =>
      `${book.title} ${book.filename}`.toLowerCase().includes(query)
    );
  }
  items.sort((a, b) => {
    if (sortBy === "title") return a.title.localeCompare(b.title, "ru");
    if (sortBy === "status") return a.status.localeCompare(b.status, "ru");
    return new Date(b.upload_date).getTime() - new Date(a.upload_date).getTime();
  });
  return items;
}

function renderBooks() {
  const books = filteredBooks();
  if (!books.length) {
    if (el.booksGrid) el.booksGrid.innerHTML = "";
    if (el.emptyState) el.emptyState.style.display = "block";
    return;
  }
  if (el.emptyState) el.emptyState.style.display = "none";
  if (!el.booksGrid) return;

  el.booksGrid.innerHTML = books.map((book) => {
    const [statusText, klass] = statusClass(book.status);
    const disabled = book.status !== "READY";
    const checked = !disabled && state.selectedBooks.has(book.id);
    return `
      <div class="book-card" data-book-id="${book.id}">
        <div class="book-cover-wrapper">
          <div class="book-cover" style="display:flex;align-items:center;justify-content:center;font-size:42px;">📘</div>
          <div class="book-overlay">
            <div class="book-status ${klass}">${statusText}</div>
          </div>
        </div>
        <div class="book-info">
          <div class="book-check">
            <input type="checkbox" name="book-select" value="${book.id}" ${disabled ? "disabled" : ""} ${checked ? "checked" : ""}>
            <div>
              <h3 class="book-title">${book.title}</h3>
              <div class="book-meta">${book.filename}</div>
              <div class="book-meta">Глав: ${book.chapter_count} · Фрагментов: ${book.chunk_count}</div>
              <div class="book-meta">Добавлено: ${new Date(book.upload_date).toLocaleString("ru-RU")}</div>
              ${book.error_message ? `<div class="book-meta" style="color:#fca5a5;">${book.error_message}</div>` : ""}
            </div>
          </div>
          <div class="book-toolbox" style="margin-top:12px;">
            <button class="small-btn" type="button" data-open-book="${book.id}" ${disabled ? "disabled" : ""}>Открыть</button>
            <button class="small-btn" type="button" data-use-book="${book.id}" ${disabled ? "disabled" : ""}>Использовать</button>
            <button class="small-btn" type="button" data-delete-book="${book.id}">Удалить</button>
          </div>
        </div>
      </div>
    `;
  }).join("");

  document.querySelectorAll('input[name="book-select"]').forEach((input) => {
    input.addEventListener("change", () => {
      if (input.checked) state.selectedBooks.add(input.value);
      else state.selectedBooks.delete(input.value);
      if (state.panelOpen) renderPanel();
    });
  });

  document.querySelectorAll("[data-open-book]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const bookId = button.dataset.openBook;
      if (!bookId || button.disabled) return;
      window.location.href = `/reader/${bookId}`;
    });
  });

  document.querySelectorAll("[data-delete-book]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      const bookId = button.dataset.deleteBook;
      if (!bookId) return;
      try {
        await fetchJson(`/api/books/${bookId}`, { method: "DELETE" });
        showError("");
        await loadBooks();
        renderPanel();
      } catch (error) {
        showError(error.message || "Не удалось удалить книгу");
      }
    });
  });

  document.querySelectorAll("[data-use-book]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const bookId = button.dataset.useBook;
      if (!bookId) return;
      state.selectedBooks.add(bookId);
      state.currentView = "search";
      state.prefillSearchQuery = "";
      openPanel();
      renderBooks();
      renderPanel();
      const scopeInput = document.querySelector('input[name="search-scope"][value="selected"]');
      if (scopeInput) scopeInput.checked = true;
      setStatusLine(
        document.getElementById("search-status"),
        "Книга отмечена для поиска. Теперь введите запрос.",
      );
    });
  });

  document.querySelectorAll(".book-card").forEach((card) => {
    card.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      if (target.closest("button") || target.closest("input")) return;
      const checkbox = card.querySelector('input[name="book-select"]');
      if (!checkbox || checkbox.disabled) return;
      const bookId = card.dataset.bookId;
      if (!bookId) return;
      window.location.href = `/reader/${bookId}`;
    });
  });
}

function overviewHtml() {
  const examples = window.BOOKVERSE_CONFIG?.demoQueries || [];
  return `
    <div class="panel-header">
      <h2>Обзор</h2>
      <button class="back-btn" type="button" id="closePanelInline">Закрыть</button>
    </div>
    <div class="profile-content">
      <div class="stats-section">
        <div class="meta-row">
          <div class="meta-chip">Книг: ${state.status.totalBooks}</div>
          <div class="meta-chip">Готово: ${state.status.readyBooks}</div>
          <div class="meta-chip">Индексация: ${state.status.processingBooks}</div>
          <div class="meta-chip">Ошибок: ${state.status.errorBooks}</div>
          <div class="meta-chip">Выбрано: ${selectedReadyBookIds().length}</div>
        </div>
      </div>
      <div class="status-box">
        <strong>Провайдер:</strong> ${state.status.providerName}<br>
        <strong>Embeddings:</strong> ${state.status.embedModel || "не задана"}<br>
        <strong>Retrieval backend:</strong> ${state.status.embeddingBackend}<br>
        <strong>Chat model:</strong> ${state.status.chatModel || "не задана"}<br>
        <strong>QA mode:</strong> ${state.status.llmAvailable ? "Mistral готов" : "Mistral не настроен"}
      </div>
      <div class="status-box">
        Используй чекбоксы в библиотеке, если хочешь ограничить поиск только выбранными книгами.
      </div>
      <div class="examples-section">
        <h3>Примеры запросов</h3>
        <div class="chips-grid">
          ${examples.map((query) => `<button class="example-chip" type="button" data-example="${query}">${query}</button>`).join("")}
        </div>
      </div>
    </div>
  `;
}

function toolsHtml() {
  return `
    <div class="panel-header">
      <h2>Инструменты</h2>
      <button class="back-btn" type="button" id="backOverviewBtn">← Назад</button>
    </div>
    <div class="tool-container">
      <div class="status-box">
        Старый интерфейс BookVerse оставлен как оболочка, а кейсовые инструменты работают через Python backend и Mistral-backed retrieval/QA.
      </div>
      <div class="tool-grid">
        <button class="tool-card" type="button" data-tool="search">
          <h3>🔎 Поиск фрагментов</h3>
          <p>Найти релевантные места в одной или нескольких книгах.</p>
        </button>
        <button class="tool-card" type="button" data-tool="ask">
          <h3>💬 Ответы по книге</h3>
          <p>Сформировать grounded-ответ по найденным цитатам.</p>
        </button>
      </div>
    </div>
  `;
}

function searchToolHtml() {
  return `
    <div class="panel-header">
      <h2>Поиск фрагментов</h2>
      <button class="back-btn" type="button" id="backToolsBtn">← Назад</button>
    </div>
    <div class="tool-content smart-tool">
      <div class="scope-row">
        <label><input type="radio" name="search-scope" value="all" checked> Все готовые книги</label>
        <label><input type="radio" name="search-scope" value="selected"> Только выбранные книги</label>
      </div>
      <section class="tool-section">
        <div class="action-row">
          <input type="text" id="search-query" placeholder="Например: Найди, где говорится о семейной жизни героев">
          <button id="search-button" type="button">Искать</button>
        </div>
        <div id="search-status" class="status-line">Ожидание запроса.</div>
        <div id="search-results" class="results-list">
          <div class="empty-placeholder">Результаты поиска появятся здесь.</div>
        </div>
      </section>
    </div>
  `;
}

function askToolHtml() {
  const initialStatus = state.status.llmAvailable
    ? "Mistral QA готов. Ответ будет собран только по найденным цитатам."
    : "Mistral не настроен. Поиск фрагментов работает, режим ответов временно отключен.";
  return `
    <div class="panel-header">
      <h2>Ответы по книге</h2>
      <button class="back-btn" type="button" id="backToolsBtn">← Назад</button>
    </div>
    <div class="tool-content smart-tool">
      <div class="scope-row">
        <label><input type="radio" name="ask-scope" value="all" checked> Все готовые книги</label>
        <label><input type="radio" name="ask-scope" value="selected"> Только выбранные книги</label>
      </div>
      <section class="tool-section">
        <div class="action-row">
          <textarea id="ask-query" rows="4" placeholder="Например: Что произошло с героями в эпилоге?"></textarea>
          <button id="ask-button" type="button">Ответить</button>
        </div>
        <div id="ask-status" class="status-line">${initialStatus}</div>
        <div class="answer-box">
          <p class="answer-text" id="answer-box">Ответ появится здесь.</p>
        </div>
        <div id="citation-caption" class="results-caption" data-tone="neutral">Цитаты появятся здесь.</div>
        <div id="citation-results" class="results-list">
          <div class="empty-placeholder">Цитаты появятся здесь.</div>
        </div>
      </section>
    </div>
  `;
}

function renderResults(target, fragments, emptyText = "Результаты появятся здесь.") {
  if (!target) return;
  if (!fragments?.length) {
    target.innerHTML = `<div class="empty-placeholder">${emptyText}</div>`;
    return;
  }
  target.innerHTML = fragments.map((fragment) => `
    <div class="result-item">
      <div class="result-meta">
        <span>${fragment.book_title}</span>
        <span>глава ${fragment.chapter_number ?? "—"}</span>
        <span>${fragment.chapter_title ?? "Без названия"}</span>
        <span>строки ${fragment.line_start}-${fragment.line_end}</span>
        <span>score ${Number(fragment.score).toFixed(4)}</span>
      </div>
      <div class="result-text">${fragment.text}</div>
    </div>
  `).join("");
}

function resolveScope(groupName) {
  const mode = document.querySelector(`input[name="${groupName}"]:checked`)?.value || "all";
  if (mode === "all") {
    return { ok: true, bookIds: null };
  }
  const bookIds = selectedReadyBookIds();
  if (!bookIds.length) {
    return {
      ok: false,
      bookIds: [],
      message: "Сначала отметьте хотя бы одну готовую книгу в библиотеке.",
    };
  }
  return { ok: true, bookIds };
}

function updateProviderMeta(payload) {
  state.status.llmAvailable = Boolean(payload.llm_available);
  state.status.embeddingBackend = payload.embedding_backend || state.status.embeddingBackend;
  state.status.providerName = payload.provider_name || state.status.providerName;
  state.status.chatModel = payload.chat_model || state.status.chatModel;
  state.status.embedModel = payload.embed_model || state.status.embedModel;
}

async function loadBooks() {
  if (el.loading) el.loading.style.display = "flex";
  try {
    const [booksPayload, statusPayload] = await Promise.all([
      fetchJson("/api/books"),
      fetchJson("/api/status"),
    ]);
    state.books = booksPayload.items || [];
    updateProviderMeta(booksPayload);
    state.status.mistralConfigured = Boolean(statusPayload.mistral_configured);
    state.status.readyBooks = statusPayload.ready_books || 0;
    state.status.processingBooks = statusPayload.processing_books || 0;
    state.status.errorBooks = statusPayload.error_books || 0;
    state.status.totalBooks = statusPayload.total_books || state.books.length;
    updateProviderMeta(statusPayload);
    syncSelectedBooks();
    renderBooks();
    showError("");
  } catch (error) {
    showError(error.message || "Не удалось загрузить список книг");
  } finally {
    if (el.loading) el.loading.style.display = "none";
  }

  clearTimeout(state.pollHandle);
  if (state.books.some((book) => book.status === "PROCESSING")) {
    state.pollHandle = setTimeout(async () => {
      await loadBooks();
      if (state.panelOpen) renderPanel();
    }, 2000);
  }
}

async function submitUpload(file) {
  const formData = new FormData();
  formData.append("file", file);
  updateUploadProgress(25, `Загрузка ${file.name}...`);
  try {
    const payload = await fetchJson("/api/books/import", { method: "POST", body: formData });
    updateUploadProgress(100, payload.message || "Файл загружен");
    closeUploadModal();
    await loadBooks();
    renderPanel();
  } catch (error) {
    updateUploadProgress(0, error.message || "Ошибка загрузки");
  }
}

function applyPanelPrefill() {
  const searchInput = document.getElementById("search-query");
  if (searchInput && state.prefillSearchQuery) {
    searchInput.value = state.prefillSearchQuery;
  }
  const askInput = document.getElementById("ask-query");
  if (askInput && state.prefillAskQuery) {
    askInput.value = state.prefillAskQuery;
  }
}

function bindDynamicPanelButtons() {
  document.getElementById("closePanelInline")?.addEventListener("click", closePanel);
  document.getElementById("backOverviewBtn")?.addEventListener("click", () => {
    state.currentView = "overview";
    renderPanel();
  });
  document.getElementById("backToolsBtn")?.addEventListener("click", () => {
    state.currentView = "tools";
    renderPanel();
  });
  document.querySelectorAll("[data-example]").forEach((node) => {
    node.addEventListener("click", () => {
      state.currentView = "search";
      state.prefillSearchQuery = node.dataset.example || "";
      openPanel();
      renderPanel();
    });
  });
  document.querySelectorAll("[data-tool]").forEach((node) => {
    node.addEventListener("click", () => {
      state.currentView = node.dataset.tool || "overview";
      renderPanel();
    });
  });
  document.getElementById("search-button")?.addEventListener("click", async () => {
    const query = document.getElementById("search-query")?.value.trim() || "";
    const statusNode = document.getElementById("search-status");
    const resultsNode = document.getElementById("search-results");
    if (!query) {
      setStatusLine(statusNode, "Введите запрос.", true);
      return;
    }
    const scope = resolveScope("search-scope");
    if (!scope.ok) {
      setStatusLine(statusNode, scope.message, true);
      renderResults(resultsNode, []);
      return;
    }
    setStatusLine(statusNode, "Ищу фрагменты...");
    try {
      const payload = await fetchJson("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, book_ids: scope.bookIds, top_k: 5 }),
      });
      const weakMatch = Boolean(payload.message);
      setStatusLine(
        statusNode,
        payload.found
          ? (payload.message || `Найдено ${payload.fragments.length} фрагментов.`)
          : (payload.message || "Ничего не найдено."),
        !payload.found || weakMatch,
      );
      renderResults(
        resultsNode,
        payload.fragments || [],
        !payload.found
          ? "Подходящие фрагменты не найдены."
          : weakMatch
            ? "Нашлись только приблизительные совпадения."
            : "Результаты появятся здесь.",
      );
    } catch (error) {
      setStatusLine(statusNode, error.message || "Ошибка поиска", true);
      renderResults(resultsNode, []);
    }
  });
  document.getElementById("ask-button")?.addEventListener("click", async () => {
    const query = document.getElementById("ask-query")?.value.trim() || "";
    const statusNode = document.getElementById("ask-status");
    const answerBox = document.getElementById("answer-box");
    const answerWrap = answerBox?.closest(".answer-box");
    const citationsNode = document.getElementById("citation-results");
    const captionNode = document.getElementById("citation-caption");
    if (!query) {
      setStatusLine(statusNode, "Введите вопрос.", true);
      return;
    }
    const scope = resolveScope("ask-scope");
    if (!scope.ok) {
      setStatusLine(statusNode, scope.message, true);
      if (answerBox) answerBox.textContent = "Ответ появится здесь.";
      renderResults(citationsNode, []);
      return;
    }
    setStatusLine(statusNode, "Формирую ответ...");
    setCaption(captionNode, "Подбираю цитаты и проверяю, хватает ли их для надежного ответа.", "neutral");
    try {
      const payload = await fetchJson("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: query, book_ids: scope.bookIds, top_k: 5, citations_k: 3 }),
      });
      if (answerBox) answerBox.textContent = payload.answer || "Ответ не получен.";
      answerWrap?.classList.toggle("is-hidden", !payload.found);
      setStatusLine(
        statusNode,
        payload.found
          ? `Ответ основан на ${(payload.citations || []).length} цитатах. Confidence ${Number(payload.confidence || 0).toFixed(2)}.`
          : (payload.message || "Нашлись только близкие фрагменты, но опоры для ответа недостаточно. Возможно, вопрос не связан с содержанием книги."),
        !payload.found,
      );
      setCaption(
        captionNode,
        payload.found
          ? "Ниже показаны цитаты, на которых основан ответ."
          : "Ниже показаны ближайшие фрагменты. Они похожи на запрос, но точного ответа из них не следует. Возможно, сам вопрос не относится к книге.",
        payload.found ? "ok" : "warning",
      );
      renderResults(
        citationsNode,
        payload.citations || [],
        payload.found ? "Цитаты появятся здесь." : "Подходящих фрагментов для надежного ответа не нашлось.",
      );
    } catch (error) {
      if (answerBox) answerBox.textContent = "Mistral временно недоступен.";
      answerWrap?.classList.remove("is-hidden");
      setStatusLine(statusNode, error.message || "Ошибка запроса", true);
      setCaption(captionNode, "Не удалось получить ответ или подобрать цитаты.", "warning");
      renderResults(citationsNode, [], "Цитаты пока недоступны.");
    }
  });
}

function syncPanelNavState() {
  const toolsActive = state.currentView === "tools" || state.currentView === "search" || state.currentView === "ask";
  el.showToolsBtn?.classList.toggle("is-active", toolsActive);
  el.showOverviewBtn?.classList.toggle("is-active", state.currentView === "overview");
}

function renderPanel() {
  if (!el.panelScreen) return;
  if (state.currentView === "tools") el.panelScreen.innerHTML = toolsHtml();
  else if (state.currentView === "search") el.panelScreen.innerHTML = searchToolHtml();
  else if (state.currentView === "ask") el.panelScreen.innerHTML = askToolHtml();
  else el.panelScreen.innerHTML = overviewHtml();
  syncPanelNavState();
  bindDynamicPanelButtons();
  applyPanelPrefill();
}

el.uploadButton?.addEventListener("click", openUploadModal);
el.uploadCtaBtn?.addEventListener("click", openUploadModal);
el.closeModalBtn?.addEventListener("click", closeUploadModal);
el.uploadNowBtn?.addEventListener("click", async () => {
  const file = el.fileInput?.files?.[0];
  if (!file) {
    updateUploadProgress(0, "Сначала выберите файл");
    return;
  }
  await submitUpload(file);
});
el.fileInput?.addEventListener("change", () => {
  const file = el.fileInput?.files?.[0];
  if (!file) return;
  updateUploadProgress(10, `Файл выбран: ${file.name}`);
});
el.menuButton?.addEventListener("click", () => {
  if (state.panelOpen) closePanel();
  else {
    openPanel();
    renderPanel();
  }
});
el.closeBtn?.addEventListener("click", closePanel);
el.refreshBooksBtn?.addEventListener("click", async () => {
  await loadBooks();
  renderPanel();
});
el.showToolsBtn?.addEventListener("click", () => {
  openPanel();
  state.currentView = "tools";
  renderPanel();
});
el.showOverviewBtn?.addEventListener("click", () => {
  openPanel();
  state.currentView = "overview";
  renderPanel();
});
el.sortBy?.addEventListener("change", renderBooks);
el.librarySearchInput?.addEventListener("input", renderBooks);
document.addEventListener("click", (event) => {
  if (el.panel && el.menuButton && !el.panel.contains(event.target) && !el.menuButton.contains(event.target)) {
    closePanel();
  }
});

loadBooks().then(() => {
  renderPanel();
});
