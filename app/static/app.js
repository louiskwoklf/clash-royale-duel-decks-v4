function formatPercent(value) {
  return `${(value * 100).toFixed(1)}%`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#39;");
}

function renderCardImage(cardName, imageUrl) {
  const safeName = escapeHtml(cardName);
  const safeImageUrl = escapeHtml(imageUrl);
  return `
    <li class="card-thumb">
      <img
        src="${safeImageUrl}"
        alt="${safeName}"
        title="${safeName}"
        loading="lazy"
        decoding="async"
      >
    </li>
  `;
}

function renderDeckCardGrid(deck) {
  const cardLabels = Array.isArray(deck.card_keys) && deck.card_keys.length
    ? deck.card_keys
    : deck.card_names;
  const cardImageUrls = Array.isArray(deck.card_image_urls) ? deck.card_image_urls : [];
  return `
    <ul class="deck-cards-grid" aria-label="Deck cards">
      ${cardLabels.map((cardName, cardIndex) => renderCardImage(
        cardName,
        cardImageUrls[cardIndex] || "",
      )).join("")}
    </ul>
  `;
}

function renderDeckMetrics(deck) {
  return `
    <div class="metric-row">
      <span class="metric-pill">Score ${deck.final_score.toFixed(4)}</span>
      <span class="metric-pill">Win rate ${formatPercent(deck.win_rate)}</span>
      <span class="metric-pill">Games ${deck.games}</span>
      <span class="metric-pill">Players ${deck.unique_players}</span>
    </div>
  `;
}

function renderSourceDeck(deck, index) {
  return `
    <article class="deck-card" style="animation-delay:${index * 40}ms">
      <h3>Pool #${index + 1}</h3>
      ${renderDeckCardGrid(deck)}
      ${renderDeckMetrics(deck)}
    </article>
  `;
}

function renderSubdeck(deck, index) {
  return `
    <section class="subdeck-card">
      <div class="subdeck-header">
        <h4>Deck ${index + 1}</h4>
        <span class="subdeck-score">Score ${deck.final_score.toFixed(4)}</span>
      </div>
      ${renderDeckCardGrid(deck)}
      ${renderDeckMetrics(deck)}
    </section>
  `;
}

function renderDuelDeck(duelDeck, index) {
  return `
    <article class="duel-deck-card" style="animation-delay:${index * 50}ms">
      <div class="duel-deck-header">
        <div>
          <h3>Duel Deck ${index + 1}</h3>
          <p class="duel-deck-copy">${duelDeck.unique_card_count} unique cards across four decks.</p>
        </div>
        <div class="metric-row">
          <span class="metric-pill">Total score ${duelDeck.total_final_score.toFixed(4)}</span>
          <span class="metric-pill">Total games ${duelDeck.total_games}</span>
          <span class="metric-pill">Total players ${duelDeck.total_unique_players}</span>
        </div>
      </div>
      <div class="duel-deck-grid">
        ${duelDeck.subdecks.map(renderSubdeck).join("")}
      </div>
    </article>
  `;
}

function renderEmptyState(message) {
  return `<article class="empty-state">${escapeHtml(message)}</article>`;
}

function formatBytes(bytes) {
  if (!bytes) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(value >= 100 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

function formatTimestamp(value) {
  if (!value) {
    return "None";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function renderStatCard(label, value) {
  return `
    <article class="stat-card">
      <p class="stat-label">${label}</p>
      <strong class="stat-value">${value}</strong>
    </article>
  `;
}

function renderStats(stats) {
  const lastPlayerPoolUpdate = formatTimestamp(stats.last_player_pool_update);
  const lastBattleIngest = formatTimestamp(stats.last_battle_ingest);

  return [
    renderStatCard("Players", stats.counts.players),
    renderStatCard("Cards", stats.counts.cards),
    renderStatCard("Battles", stats.counts.battles),
    renderStatCard("Decks", stats.counts.decks),
    renderStatCard("Battle records", stats.counts.battle_records),
    renderStatCard("DB size", formatBytes(stats.db_size_bytes)),
    renderStatCard("Last player pool update", lastPlayerPoolUpdate),
    renderStatCard("Last battle ingest", lastBattleIngest),
  ].join("");
}

function formatAdminActionLabel(action) {
  return String(action || "")
    .split("-")
    .filter(Boolean)
    .map((token) => token.charAt(0).toUpperCase() + token.slice(1))
    .join(" ");
}

function isStoppableProgress(progress) {
  return Boolean(progress?.stoppable);
}

function renderProgressStatus(status) {
  switch (status) {
    case "stopped":
      return "Stopped";
    case "stopping":
      return "Stopping";
    case "success":
      return "Complete";
    case "error":
      return "Failed";
    case "running":
      return "Running";
    default:
      return "Idle";
  }
}

function renderProgressTitle(progress) {
  return progress.label || "Working";
}

function showProgressModal(modalEl) {
  modalEl.hidden = false;
  document.body.classList.add("modal-open");
}

function hideProgressModal(modalEl) {
  modalEl.hidden = true;
  document.body.classList.remove("modal-open");
}

function createProgressRenderer(progressElements) {
  let lastProgress = {
    action: "",
    label: "Working",
    current: 0,
    total: 0,
    active: false,
    status: "idle",
    unit: "items",
    percent: 0,
    message: "",
    stoppable: false,
  };

  function render(progress) {
    const currentProgress = {
      ...lastProgress,
      ...(progress || {}),
    };
    lastProgress = currentProgress;
    const displayPercent = Math.max(0, Math.min(1, Number(currentProgress.percent || 0)));
    progressElements.title.textContent = renderProgressTitle(currentProgress);
    progressElements.status.textContent = renderProgressStatus(currentProgress.status);
    progressElements.status.dataset.status = currentProgress.status || "idle";
    progressElements.percent.textContent = `${Math.round(displayPercent * 100)}%`;
    progressElements.fill.style.width = `${Math.round(displayPercent * 100)}%`;
    const showError = currentProgress.status === "error" && Boolean(currentProgress.message);
    progressElements.error.hidden = !showError;
    progressElements.error.textContent = showError ? currentProgress.message : "";
    if (currentProgress.active && isStoppableProgress(currentProgress)) {
      progressElements.close.textContent = currentProgress.status === "stopping" ? "Stopping..." : "Stop";
      progressElements.close.dataset.mode = "stop";
      progressElements.close.disabled = currentProgress.status !== "running";
    } else {
      progressElements.close.textContent = "Close";
      progressElements.close.dataset.mode = "close";
      progressElements.close.disabled = Boolean(currentProgress.active);
    }
    progressElements.close.hidden = false;
  }

  return {
    reset(progress) {
      render(progress);
    },
    update(progress) {
      render(progress);
    },
    current() {
      return { ...lastProgress };
    },
  };
}

function createProgressStream(progressRenderer) {
  const state = {
    eventSource: null,
    lastEventId: 0,
    lastRenderedKey: "",
    openWaiters: [],
    pendingActionWatcher: null,
  };

  function buildProgressRenderKey(progress) {
    return [
      progress.action || "",
      progress.label || "",
      progress.unit || "",
      progress.status || "",
      progress.active ? "1" : "0",
      progress.stoppable ? "1" : "0",
      Number(progress.current || 0),
      Number(progress.total || 0),
      Math.round(Number(progress.percent || 0) * 1000),
      progress.status === "error" ? String(progress.message || "") : "",
    ].join("|");
  }

  function settlePendingAction(progress, eventId) {
    const watcher = state.pendingActionWatcher;
    if (!watcher || watcher.action !== progress.action || progress.active || eventId <= watcher.startEventId) {
      return;
    }
    state.pendingActionWatcher = null;
    if (progress.status === "error") {
      watcher.reject(new Error(progress.message || "Request failed."));
      return;
    }
    watcher.resolve(progress);
  }

  function applyProgress(progress, eventId) {
    const key = buildProgressRenderKey(progress);
    if (key === state.lastRenderedKey) {
      settlePendingAction(progress, eventId);
      return;
    }
    progressRenderer.update(progress);
    state.lastRenderedKey = key;
    settlePendingAction(progress, eventId);
  }

  function connect() {
    const eventSource = new EventSource("/api/admin/progress/stream");
    state.eventSource = eventSource;

    eventSource.addEventListener("progress", (event) => {
      let progress;
      try {
        progress = JSON.parse(event.data);
      } catch (_error) {
        return;
      }

      const eventId = Number(event.lastEventId || 0);
      if (Number.isFinite(eventId)) {
        state.lastEventId = Math.max(state.lastEventId, eventId);
      }
      applyProgress(progress, eventId);
    });

    eventSource.onopen = () => {
      const waiters = state.openWaiters.splice(0, state.openWaiters.length);
      waiters.forEach((resolve) => resolve());
    };

    eventSource.onerror = () => {};
  }

  connect();

  return {
    async awaitReady(timeoutMs = 3000) {
      if (state.eventSource && state.eventSource.readyState === EventSource.OPEN) {
        return;
      }
      let timeoutId = 0;
      let resolver = null;
      try {
        await new Promise((resolve, reject) => {
          resolver = resolve;
          state.openWaiters.push(resolve);
          timeoutId = window.setTimeout(() => {
            state.openWaiters = state.openWaiters.filter((waiter) => waiter !== resolve);
            reject(new Error("Could not connect to progress updates."));
          }, timeoutMs);
        });
      } finally {
        if (timeoutId) {
          window.clearTimeout(timeoutId);
        }
        if (resolver) {
          state.openWaiters = state.openWaiters.filter((waiter) => waiter !== resolver);
        }
      }
    },
    watchAction(action) {
      let active = true;
      const watcher = {
        action,
        startEventId: state.lastEventId,
        resolve: () => {},
        reject: () => {},
      };
      const promise = new Promise((resolve, reject) => {
        watcher.resolve = resolve;
        watcher.reject = reject;
      });
      state.pendingActionWatcher = watcher;
      return {
        promise,
        cancel() {
          if (!active) {
            return;
          }
          active = false;
          if (state.pendingActionWatcher === watcher) {
            state.pendingActionWatcher = null;
          }
        },
      };
    },
  };
}

async function loadDuelDecks(form, resultsEl, sourceResultsEl) {
  resultsEl.innerHTML = "";
  sourceResultsEl.innerHTML = "";

  const params = new URLSearchParams(new FormData(form));
  const response = await fetch(`/api/duel-decks?${params.toString()}`);

  if (!response.ok) {
    return;
  }

  const data = await response.json();
  const duelDeckCount = Array.isArray(data.duel_decks) ? data.duel_decks.length : 0;
  const sourceDeckCount = Array.isArray(data.source_decks) ? data.source_decks.length : 0;

  if (duelDeckCount > 0) {
    resultsEl.innerHTML = data.duel_decks.map(renderDuelDeck).join("");
  } else {
    resultsEl.innerHTML = renderEmptyState("No duel deck bundles matched these ranked deck filters.");
  }

  sourceResultsEl.innerHTML = sourceDeckCount
    ? data.source_decks.map(renderSourceDeck).join("")
    : renderEmptyState("No ranked individual decks matched these filters.");
}

async function loadStats(statsEl) {
  statsEl.innerHTML = "Loading stats...";
  const response = await fetch("/api/admin/stats");
  if (!response.ok) {
    statsEl.textContent = "Failed to load stats.";
    return;
  }
  const data = await response.json();
  statsEl.innerHTML = renderStats(data);
}

async function refreshProgressSnapshot(progressRenderer) {
  try {
    const response = await fetch("/api/admin/progress");
    if (!response.ok) {
      return false;
    }
    const progress = await response.json();
    progressRenderer.update(progress);
    return true;
  } catch (_error) {
    return false;
  }
}

function setAdminButtonsDisabled(adminButtons, disabled) {
  adminButtons.forEach((button) => {
    button.disabled = disabled;
  });
}

async function runAdminAction(
  action,
  adminButtons,
  statsEl,
  resultsEl,
  sourceResultsEl,
  progressElements,
  progressRenderer,
  progressStream,
) {
  const actionLabel = formatAdminActionLabel(action);
  const previousProgress = progressRenderer.current();
  const resumeStoppedAction = previousProgress.status === "stopped" && previousProgress.action === action;
  setAdminButtonsDisabled(adminButtons, true);
  showProgressModal(progressElements.modal);
  progressRenderer.reset({
    action,
    label: actionLabel,
    current: resumeStoppedAction ? Number(previousProgress.current || 0) : 0,
    total: resumeStoppedAction ? Number(previousProgress.total || 0) : 0,
    percent: resumeStoppedAction ? Number(previousProgress.percent || 0) : 0,
    active: true,
    status: "running",
    unit: resumeStoppedAction ? previousProgress.unit || "items" : "items",
    stoppable: false,
  });

  try {
    await progressStream.awaitReady();
  } catch (error) {
    progressRenderer.reset({
      action,
      label: actionLabel,
      current: 0,
      total: 0,
      percent: 0,
      active: false,
      status: "error",
      unit: "items",
      message: error instanceof Error ? error.message : "Could not connect to progress updates.",
      stoppable: false,
    });
    setAdminButtonsDisabled(adminButtons, false);
    return;
  }
  const actionWatcher = progressStream.watchAction(action);
  let response;
  try {
    response = await fetch(`/api/admin/${action}`, { method: "POST" });
  } catch (error) {
    actionWatcher.cancel();
    progressRenderer.reset({
      action,
      label: actionLabel,
      current: 0,
      total: 0,
      percent: 0,
      active: false,
      status: "error",
      unit: "items",
      message: error instanceof Error ? error.message : "Request failed.",
      stoppable: false,
    });
    setAdminButtonsDisabled(adminButtons, false);
    return;
  }
  const payload = await response.json().catch(() => ({ message: "Request failed." }));

  if (!response.ok) {
    actionWatcher.cancel();
    progressRenderer.reset({
      action,
      label: actionLabel,
      current: 0,
      total: 0,
      percent: 0,
      active: false,
      status: "error",
      unit: "items",
      message: payload.detail || payload.message || "Request failed.",
      stoppable: false,
    });
    setAdminButtonsDisabled(adminButtons, false);
    return;
  }

  try {
    await actionWatcher.promise;
  } catch (_error) {
    setAdminButtonsDisabled(adminButtons, false);
    return;
  }

  await loadStats(statsEl);
  resultsEl.innerHTML = "";
  sourceResultsEl.innerHTML = "";
  setAdminButtonsDisabled(adminButtons, false);
}

function initPage() {
  const form = document.getElementById("duel-deck-form");
  const daysInputEl = document.getElementById("days-input");
  const daysValueEl = document.getElementById("days-value");
  const resultsEl = document.getElementById("results");
  const sourceResultsEl = document.getElementById("source-results");
  const statsEl = document.getElementById("db-stats");
  const refreshStatsButton = document.getElementById("refresh-stats");
  const adminButtons = Array.from(document.querySelectorAll("[data-admin-action]"));
  const progressModalEl = document.getElementById("progress-modal");
  const progressCloseEl = document.getElementById("progress-close");
  const progressElements = {
    modal: progressModalEl,
    title: document.getElementById("progress-title"),
    status: document.getElementById("progress-status"),
    fill: document.getElementById("progress-fill"),
    percent: document.getElementById("progress-percent"),
    error: document.getElementById("progress-error"),
    close: progressCloseEl,
  };

  if (
    !form || !daysInputEl || !daysValueEl || !resultsEl || !sourceResultsEl ||
    !statsEl || !refreshStatsButton || !progressModalEl ||
    !progressCloseEl || !progressElements.title || !progressElements.status ||
    !progressElements.fill || !progressElements.percent || !progressElements.error
  ) {
    return;
  }

  const progressRenderer = createProgressRenderer(progressElements);
  const progressStream = createProgressStream(progressRenderer);
  const syncDaysValue = () => {
    daysValueEl.textContent = daysInputEl.value;
  };

  syncDaysValue();
  daysInputEl.addEventListener("input", syncDaysValue);

  progressCloseEl.addEventListener("click", async () => {
    const currentProgress = progressRenderer.current();
    if (currentProgress.active && isStoppableProgress(currentProgress)) {
      if (currentProgress.status !== "running") {
        return;
      }
      progressCloseEl.disabled = true;
      progressCloseEl.textContent = "Stopping...";
      try {
        const response = await fetch("/api/admin/stop", { method: "POST" });
        if (response.ok) {
          progressRenderer.update({
            ...currentProgress,
            status: "stopping",
          });
          return;
        }
        const refreshed = await refreshProgressSnapshot(progressRenderer);
        if (!refreshed) {
          progressRenderer.update(currentProgress);
        }
      } catch (_error) {
        const refreshed = await refreshProgressSnapshot(progressRenderer);
        if (!refreshed) {
          progressRenderer.update(currentProgress);
        }
      }
      return;
    }
    hideProgressModal(progressModalEl);
  });

  hideProgressModal(progressModalEl);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await loadDuelDecks(form, resultsEl, sourceResultsEl);
    } catch (_error) {}
  });

  refreshStatsButton.addEventListener("click", async () => {
    try {
      await loadStats(statsEl);
    } catch (_error) {
      statsEl.textContent = "Failed to load stats.";
    }
  });

  adminButtons.forEach((button) => {
    button.addEventListener("click", async () => {
      if (button.dataset.confirm && !window.confirm(button.dataset.confirm)) {
        return;
      }
      try {
        await runAdminAction(
          button.dataset.adminAction,
          adminButtons,
          statsEl,
          resultsEl,
          sourceResultsEl,
          progressElements,
          progressRenderer,
          progressStream,
        );
      } catch (_error) {
        setAdminButtonsDisabled(adminButtons, false);
      }
    });
  });

  loadStats(statsEl).catch(() => {
    statsEl.textContent = "Failed to load stats.";
  });

  registerServiceWorker();
}

function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) {
    return;
  }

  const version = encodeURIComponent(window.APP_CONFIG?.staticVersion || "1");
  navigator.serviceWorker.register(`/sw.js?v=${version}`).catch(() => {});
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initPage);
} else {
  initPage();
}
