const readerConfig = window.BOOKVERSE_READER || {};

const state = {
  book: null,
  chunks: [],
  chapters: [],
  currentPage: 1,
  panelOpen: false,
  currentView: null,
  status: {
    providerName: "Mistral AI",
    llmAvailable: false,
    chatModel: null,
    embedModel: null,
    embeddingBackend: "unknown",
  },
};

const el = {
  readerTitle: document.getElementById("reader-title"),
  readerMeta: document.getElementById("reader-meta"),
  sideMeta: document.getElementById("reader-side-meta"),
  error: document.getElementById("reader-error"),
  pageContent: document.getElementById("page-content"),
  pageCount: document.getElementById("page-count"),
  pageInput: document.getElementById("page-input"),
  breadcrumbChapter: document.getElementById("breadcrumb-chapter"),
  breadcrumbPage: document.getElementById("breadcrumb-page"),
  progress: document.getElementById("progress-percentage"),
  chaptersList: document.getElementById("chapters-list"),
  chaptersPanel: document.getElementById("chapters-panel"),
  toggleChapters: document.getElementById("toggle-chapters"),
  closeChapters: document.getElementById("close-chapters"),
  prevPage: document.getElementById("prev-page"),
  nextPage: document.getElementById("next-page"),
  menuButton: document.getElementById("menuButton"),
  rightPanel: document.getElementById("right-panel"),
  closeBtn: document.getElementById("closeBtn"),
  showSearchBtn: document.getElementById("showSearchBtn"),
  showAskBtn: document.getElementById("showAskBtn"),
  panelContent: document.getElementById("panel-content"),
  panelScreen: document.getElementById("reader-panel-screen"),
};

function setError(message) {
  if (el.error) {
    el.error.textContent = message;
    el.error.style.display = message ? "block" : "none";
  }
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

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || payload.message || `HTTP ${response.status}`);
  }
  return payload;
}

function currentChunk() {
  return state.chunks[state.currentPage - 1] || null;
}

function pageForOffset(charStart) {
  const offset = Number(charStart);
  if (!Number.isFinite(offset)) return 1;
  const exact = state.chunks.findIndex((chunk) => offset >= chunk.char_start && offset <= chunk.char_end);
  if (exact >= 0) return exact + 1;
  const next = state.chunks.findIndex((chunk) => chunk.char_start >= offset);
  return next >= 0 ? next + 1 : 1;
}

function currentChapterLabel() {
  const chunk = currentChunk();
  if (!chunk) return "Глава: не найдена";
  if (chunk.chapter_title) return `Глава: ${chunk.chapter_title}`;
  if (chunk.chapter_number) return `Глава: ${chunk.chapter_number}`;
  return "Глава: без названия";
}

function renderChapterList() {
  if (!el.chaptersList) return;
  if (!state.chapters.length) {
    el.chaptersList.innerHTML = '<p class="empty-placeholder">Главы не найдены.</p>';
    return;
  }
  el.chaptersList.innerHTML = state.chapters.map((chapter) => `
    <button class="chapter-button" type="button" data-page="${chapter.start_chunk + 1}">
      ${chapter.number ? `${chapter.number}. ` : ""}${chapter.title || "Без названия"}
    </button>
  `).join("");

  el.chaptersList.querySelectorAll("[data-page]").forEach((button) => {
    button.addEventListener("click", () => {
      displayPage(Number(button.dataset.page));
      el.chaptersPanel?.classList.remove("active");
    });
  });
}

function updateProgress() {
  const percentage = state.chunks.length
    ? Math.round((state.currentPage / state.chunks.length) * 100)
    : 0;
  if (el.progress) el.progress.textContent = `${percentage}%`;
  localStorage.setItem(`reader_page_${readerConfig.bookId}`, String(state.currentPage));
}

function highlightActiveChapter() {
  const chunk = currentChunk();
  if (!chunk) return;
  const currentOrder = chunk.chunk_order;
  el.chaptersList?.querySelectorAll("[data-page]").forEach((button) => {
    const startPage = Number(button.dataset.page) - 1;
    button.classList.toggle("active", startPage === currentOrder);
  });
}

function displayPage(page) {
  if (!Number.isFinite(page) || page < 1 || page > state.chunks.length) return;
  state.currentPage = page;
  const chunk = currentChunk();
  if (!chunk) return;

  if (el.pageContent) el.pageContent.textContent = chunk.text;
  if (el.pageCount) el.pageCount.textContent = String(state.chunks.length);
  if (el.pageInput) el.pageInput.value = String(page);
  if (el.breadcrumbPage) el.breadcrumbPage.textContent = `Фрагмент: ${page}`;
  if (el.breadcrumbChapter) el.breadcrumbChapter.textContent = currentChapterLabel();
  updateProgress();
  highlightActiveChapter();
}

function openPanel() {
  state.panelOpen = true;
  el.rightPanel?.classList.add("visible");
  el.rightPanel?.classList.add("open");
}

function closePanel() {
  state.panelOpen = false;
  state.currentView = null;
  el.rightPanel?.classList.remove("visible");
  el.rightPanel?.classList.remove("open");
  el.panelContent?.classList.remove("reader-tool-open");
}

function updateMenuState() {
  el.showSearchBtn?.classList.toggle("is-active", state.currentView === "search");
  el.showAskBtn?.classList.toggle("is-active", state.currentView === "ask");
}

function searchHtml() {
  return `
    <div class="panel-header">
      <h2>Поиск фрагментов</h2>
      <button class="back-btn" type="button" id="closePanelInline">Закрыть</button>
    </div>
    <div class="tool-content smart-tool">
      <section class="tool-section">
        <div class="action-row">
          <input type="text" id="reader-search-query" placeholder="Например: Найди, где говорится про автомобиль">
          <button id="reader-search-button" type="button">Искать</button>
        </div>
        <div id="reader-search-status" class="status-line">Ожидание запроса.</div>
        <div id="reader-search-caption" class="results-caption" data-tone="neutral">Результаты поиска появятся здесь.</div>
        <div id="reader-search-results" class="results-list">
          <div class="empty-placeholder">Результаты поиска появятся здесь.</div>
        </div>
      </section>
    </div>
  `;
}

function askHtml() {
  const initial = state.status.llmAvailable
    ? "Mistral QA готов. Ответ будет собран по цитатам."
    : "Mistral не настроен. Поиск по фрагментам остается доступным.";
  return `
    <div class="panel-header">
      <h2>Ответы по книге</h2>
      <button class="back-btn" type="button" id="closePanelInline">Закрыть</button>
    </div>
    <div class="tool-content smart-tool">
      <section class="tool-section">
        <div class="action-row">
          <textarea id="reader-ask-query" rows="4" placeholder="Например: Что произошло с героями в эпилоге?"></textarea>
          <button id="reader-ask-button" type="button">Ответить</button>
        </div>
        <div id="reader-ask-status" class="status-line">${initial}</div>
        <div class="answer-box">
          <p class="answer-text" id="reader-answer-box">Ответ появится здесь.</p>
        </div>
        <div id="reader-citation-caption" class="results-caption" data-tone="neutral">Цитаты появятся здесь.</div>
        <div id="reader-citation-results" class="results-list">
          <div class="empty-placeholder">Цитаты появятся здесь.</div>
        </div>
      </section>
    </div>
  `;
}

function renderResultList(target, fragments, emptyText = "Результаты появятся здесь.") {
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
      </div>
      <div class="result-text">${fragment.text}</div>
      ${fragment.book_id === readerConfig.bookId ? `
        <div class="reader-result-actions">
          <button class="small-btn" type="button" data-jump-offset="${fragment.char_start}">Перейти к месту</button>
        </div>
      ` : ""}
    </div>
  `).join("");

  target.querySelectorAll("[data-jump-offset]").forEach((button) => {
    button.addEventListener("click", () => {
      const page = pageForOffset(button.dataset.jumpOffset);
      displayPage(page);
      closePanel();
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  });
}

function resolveScope(groupName) {
  return [readerConfig.bookId];
}

function bindPanelDynamic() {
  document.getElementById("closePanelInline")?.addEventListener("click", closePanel);

  document.getElementById("reader-search-button")?.addEventListener("click", async () => {
    const query = document.getElementById("reader-search-query")?.value.trim() || "";
    const statusNode = document.getElementById("reader-search-status");
    const resultsNode = document.getElementById("reader-search-results");
    const captionNode = document.getElementById("reader-search-caption");
    if (!query) {
      setStatusLine(statusNode, "Введите запрос.", true);
      return;
    }
    setStatusLine(statusNode, "Ищу фрагменты...");
    setCaption(captionNode, "Подбираю лучшие фрагменты из текущей книги.", "neutral");
    try {
      const payload = await fetchJson("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, book_ids: resolveScope("reader-search-scope"), top_k: 5 }),
      });
      const weakMatch = Boolean(payload.message);
      setStatusLine(
        statusNode,
        payload.found
          ? (payload.message || `Найдено ${payload.fragments.length} фрагментов.`)
          : (payload.message || "Ничего не найдено."),
        !payload.found || weakMatch,
      );
      setCaption(
        captionNode,
        !payload.found
          ? "Подходящих фрагментов в этой книге не нашлось."
          : weakMatch
            ? "Ниже показаны ближайшие фрагменты. Возможно, запрос не связан с текстом книги."
            : "Ниже показаны фрагменты, которые лучше всего совпали с запросом."
        ,
        payload.found && !weakMatch ? "ok" : "warning",
      );
      renderResultList(
        resultsNode,
        payload.fragments || [],
        !payload.found
          ? "Подходящие фрагменты не найдены."
          : weakMatch
            ? "Нашлись только приблизительные совпадения."
            : "Подходящие фрагменты не найдены.",
      );
    } catch (error) {
      setStatusLine(statusNode, error.message || "Ошибка поиска", true);
      setCaption(captionNode, "Поиск не выполнился из-за ошибки.", "warning");
      renderResultList(resultsNode, [], "Результаты поиска пока недоступны.");
    }
  });

  document.getElementById("reader-ask-button")?.addEventListener("click", async () => {
    const query = document.getElementById("reader-ask-query")?.value.trim() || "";
    const statusNode = document.getElementById("reader-ask-status");
    const answerBox = document.getElementById("reader-answer-box");
    const answerWrap = answerBox?.closest(".answer-box");
    const resultsNode = document.getElementById("reader-citation-results");
    const captionNode = document.getElementById("reader-citation-caption");
    if (!query) {
      setStatusLine(statusNode, "Введите вопрос.", true);
      return;
    }
    setStatusLine(statusNode, "Формирую ответ...");
    setCaption(captionNode, "Подбираю цитаты и проверяю, хватает ли их для надежного ответа.", "neutral");
    try {
      const payload = await fetchJson("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: query, book_ids: resolveScope("reader-ask-scope"), top_k: 5, citations_k: 3 }),
      });
      if (answerBox) answerBox.textContent = payload.answer || "Ответ не получен.";
      answerWrap?.classList.toggle("is-hidden", !payload.found);
      setStatusLine(
        statusNode,
        payload.found
          ? `Ответ основан на ${(payload.citations || []).length} цитатах.`
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
      renderResultList(
        resultsNode,
        payload.citations || [],
        payload.found ? "Цитаты появятся здесь." : "Подходящих фрагментов для надежного ответа не нашлось.",
      );
    } catch (error) {
      if (answerBox) answerBox.textContent = "Ответ не получен.";
      answerWrap?.classList.remove("is-hidden");
      setStatusLine(statusNode, error.message || "Ошибка запроса", true);
      setCaption(captionNode, "Не удалось получить ответ или подобрать цитаты.", "warning");
      renderResultList(resultsNode, [], "Цитаты пока недоступны.");
    }
  });
}

function renderPanel() {
  if (!el.panelScreen) return;
  if (state.currentView === "search") el.panelScreen.innerHTML = searchHtml();
  else if (state.currentView === "ask") el.panelScreen.innerHTML = askHtml();
  else el.panelScreen.innerHTML = "";
  el.panelContent?.classList.toggle("reader-tool-open", Boolean(state.currentView));
  updateMenuState();
  if (state.currentView) {
    bindPanelDynamic();
  }
}

function bindStaticReaderActions() {
  el.toggleChapters?.addEventListener("click", (event) => {
    event.stopPropagation();
    el.chaptersPanel?.classList.toggle("active");
    closePanel();
  });
  el.closeChapters?.addEventListener("click", () => {
    el.chaptersPanel?.classList.remove("active");
  });
  el.prevPage?.addEventListener("click", () => displayPage(state.currentPage - 1));
  el.nextPage?.addEventListener("click", () => displayPage(state.currentPage + 1));
  el.pageInput?.addEventListener("change", () => {
    displayPage(Number(el.pageInput?.value));
  });

  el.menuButton?.addEventListener("click", (event) => {
    event.stopPropagation();
    if (state.panelOpen) closePanel();
    else {
      openPanel();
      renderPanel();
    }
    el.chaptersPanel?.classList.remove("active");
  });

  el.closeBtn?.addEventListener("click", closePanel);
  el.showSearchBtn?.addEventListener("click", () => {
    state.currentView = "search";
    openPanel();
    renderPanel();
  });
  el.showAskBtn?.addEventListener("click", () => {
    state.currentView = "ask";
    openPanel();
    renderPanel();
  });

  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Node)) return;
    if (el.chaptersPanel && !el.chaptersPanel.contains(target) && !el.toggleChapters?.contains(target)) {
      el.chaptersPanel.classList.remove("active");
    }
    if (el.rightPanel && !el.rightPanel.contains(target) && !el.menuButton?.contains(target)) {
      closePanel();
    }
  });
}

async function initReader() {
  try {
    const [bookPayload, statusPayload] = await Promise.all([
      fetchJson(`/api/books/${readerConfig.bookId}/content`),
      fetchJson("/api/status"),
    ]);
    state.book = bookPayload;
    state.chunks = bookPayload.chunks || [];
    state.chapters = bookPayload.chapters || [];
    state.status.providerName = statusPayload.provider_name || "Mistral AI";
    state.status.llmAvailable = Boolean(statusPayload.llm_available);
    state.status.chatModel = statusPayload.chat_model || null;
    state.status.embedModel = statusPayload.embed_model || null;
    state.status.embeddingBackend = statusPayload.embedding_backend || "unknown";

    if (!state.chunks.length) {
      throw new Error("У книги нет доступных фрагментов для чтения.");
    }

    if (el.readerTitle) el.readerTitle.textContent = bookPayload.title;
    if (el.readerMeta) {
      el.readerMeta.textContent = `${bookPayload.filename} · ${bookPayload.chapter_count} глав · ${bookPayload.chunk_count} фрагментов`;
    }
    if (el.sideMeta) {
      el.sideMeta.innerHTML = `
        <div><strong>Файл:</strong> ${bookPayload.filename}</div>
        <div><strong>Формат:</strong> ${bookPayload.file_type}</div>
        <div><strong>Глав:</strong> ${bookPayload.chapter_count}</div>
        <div><strong>Фрагментов:</strong> ${bookPayload.chunk_count}</div>
      `;
    }
    setError("");
    renderChapterList();
    renderPanel();

    const savedPage = Number(localStorage.getItem(`reader_page_${readerConfig.bookId}`));
    const initialPage = Number.isFinite(savedPage) && savedPage >= 1 && savedPage <= state.chunks.length
      ? savedPage
      : 1;
    displayPage(initialPage);
  } catch (error) {
    setError(error.message || "Не удалось открыть книгу");
    if (el.pageContent) {
      el.pageContent.textContent = "Не удалось загрузить текст книги.";
    }
  }
}

bindStaticReaderActions();
initReader();
