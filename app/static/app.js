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

function progressPollIntervalMs() {
  const value = Number(window.APP_CONFIG?.progressPollIntervalMs || 200);
  return Number.isFinite(value) ? Math.max(100, Math.round(value)) : 200;
}

function progressMaxPercentPerSecond() {
  const value = Number(window.APP_CONFIG?.progressMaxPercentPerSecond || 35);
  return Number.isFinite(value) ? Math.max(5, value) : 35;
}

function renderDeck(deck, index) {
  const cardLabels = Array.isArray(deck.card_keys) && deck.card_keys.length
    ? deck.card_keys
    : deck.card_names;
  const cardImageUrls = Array.isArray(deck.card_image_urls) ? deck.card_image_urls : [];
  return `
    <article class="deck-card" style="animation-delay:${index * 60}ms">
      <h3>#${index + 1}</h3>
      <ul class="deck-cards-grid" aria-label="Deck cards">
        ${cardLabels.map((cardName, cardIndex) => renderCardImage(
          cardName,
          cardImageUrls[cardIndex] || "",
        )).join("")}
      </ul>
      <div class="metric-row">
        <span class="metric-pill">Score ${deck.final_score.toFixed(4)}</span>
        <span class="metric-pill">Win rate ${formatPercent(deck.win_rate)}</span>
        <span class="metric-pill">Games ${deck.games}</span>
        <span class="metric-pill">Players ${deck.unique_players}</span>
      </div>
    </article>
  `;
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

function renderStatCard(label, value) {
  return `
    <article class="stat-card">
      <p class="stat-label">${label}</p>
      <strong class="stat-value">${value}</strong>
    </article>
  `;
}

function renderStats(stats) {
  const lastPlayerPoolUpdate = stats.last_player_pool_update || "None";
  const lastBattleIngest = stats.last_battle_ingest || "None";

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

function renderProgressCount(progress) {
  const unitLabel = progress.unit ? ` ${progress.unit}` : "";
  if (progress.total <= 0) {
    return progress.current ? `${progress.current}${unitLabel}` : `0${unitLabel}`;
  }
  return `${progress.current} / ${progress.total}${unitLabel}`;
}

function showProgressModal(modalEl) {
  modalEl.hidden = false;
  document.body.classList.add("modal-open");
}

function hideProgressModal(modalEl) {
  modalEl.hidden = true;
  document.body.classList.remove("modal-open");
}

function updateProgressModal(progressElements, progress) {
  progressElements.title.textContent = progress.label || "Working";
  progressElements.count.textContent = renderProgressCount(progress);
  progressElements.percent.textContent = `${Math.round((progress.percent || 0) * 100)}%`;
  progressElements.fill.style.width = `${Math.round((progress.percent || 0) * 100)}%`;
  progressElements.close.hidden = progress.active;
  progressElements.close.disabled = progress.active;
}

function createProgressAnimator(progressElements) {
  const state = {
    displayPercent: 0,
    frameId: 0,
    lastFrameAt: 0,
    settleResolvers: [],
    targetProgress: null,
  };

  function getTargetPercent() {
    return Math.max(0, Math.min(1, Number(state.targetProgress?.percent || 0)));
  }

  function isSettled() {
    return Math.abs(state.displayPercent - getTargetPercent()) < 0.001;
  }

  function render() {
    const progress = state.targetProgress || {
      label: "Working",
      current: 0,
      total: 0,
      active: false,
      unit: "items",
    };
    progressElements.title.textContent = progress.label || "Working";
    progressElements.count.textContent = renderProgressCount(progress);
    progressElements.percent.textContent = `${Math.round(state.displayPercent * 100)}%`;
    progressElements.fill.style.width = `${Math.round(state.displayPercent * 100)}%`;
    const canClose = !progress.active && isSettled();
    progressElements.close.hidden = !canClose;
    progressElements.close.disabled = !canClose;
  }

  function resolveSettledIfNeeded() {
    if (!isSettled()) {
      return;
    }
    const resolvers = state.settleResolvers.splice(0, state.settleResolvers.length);
    resolvers.forEach((resolve) => resolve());
  }

  function stop() {
    if (state.frameId) {
      window.cancelAnimationFrame(state.frameId);
      state.frameId = 0;
    }
    state.lastFrameAt = 0;
  }

  function tick(timestamp) {
    if (!state.targetProgress) {
      stop();
      return;
    }
    if (!state.lastFrameAt) {
      state.lastFrameAt = timestamp;
    }

    const deltaSeconds = Math.max(0, (timestamp - state.lastFrameAt) / 1000);
    state.lastFrameAt = timestamp;

    const maxStep = (progressMaxPercentPerSecond() / 100) * deltaSeconds;
    const targetPercent = getTargetPercent();
    if (state.displayPercent < targetPercent) {
      state.displayPercent = Math.min(targetPercent, state.displayPercent + maxStep);
    } else if (state.displayPercent > targetPercent) {
      state.displayPercent = targetPercent;
    }

    render();

    if (isSettled()) {
      stop();
      resolveSettledIfNeeded();
      return;
    }

    state.frameId = window.requestAnimationFrame(tick);
  }

  function start() {
    if (state.frameId) {
      return;
    }
    state.frameId = window.requestAnimationFrame(tick);
  }

  return {
    reset(progress) {
      stop();
      state.targetProgress = progress;
      state.displayPercent = Math.max(0, Math.min(1, Number(progress?.percent || 0)));
      render();
      resolveSettledIfNeeded();
    },
    update(progress) {
      const actionChanged = Boolean(
        state.targetProgress &&
        progress &&
        state.targetProgress.action &&
        progress.action &&
        state.targetProgress.action !== progress.action,
      );
      state.targetProgress = progress;
      if (actionChanged) {
        state.displayPercent = 0;
      }
      render();
      if (isSettled()) {
        resolveSettledIfNeeded();
        return;
      }
      start();
    },
    settle() {
      if (isSettled()) {
        return Promise.resolve();
      }
      return new Promise((resolve) => {
        state.settleResolvers.push(resolve);
        start();
      });
    },
  };
}

async function loadProgress() {
  const response = await fetch("/api/admin/progress");
  if (!response.ok) {
    throw new Error("Failed to load progress.");
  }
  return response.json();
}

async function loadDecks(form, statusEl, resultsEl) {
  resultsEl.innerHTML = "";
  statusEl.textContent = "Loading decks...";

  const params = new URLSearchParams(new FormData(form));
  const response = await fetch(`/api/decks?${params.toString()}`);

  if (!response.ok) {
    statusEl.textContent = "Request failed.";
    return;
  }

  const data = await response.json();
  statusEl.textContent = data.length ? `${data.length} deck(s) found.` : "No decks found for those filters.";
  resultsEl.innerHTML = data.map(renderDeck).join("");
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

function setAdminButtonsDisabled(adminButtons, disabled) {
  adminButtons.forEach((button) => {
    button.disabled = disabled;
  });
}

async function runAdminAction(
  action,
  adminButtons,
  adminStatusEl,
  statsEl,
  form,
  statusEl,
  resultsEl,
  progressElements,
  progressAnimator,
) {
  setAdminButtonsDisabled(adminButtons, true);
  adminStatusEl.textContent = `Running ${action.replace(/-/g, " ")}...`;
  showProgressModal(progressElements.modal);
  progressAnimator.reset({
    action,
    label: action.replace(/-/g, " "),
    current: 0,
    total: 0,
    percent: 0,
    active: true,
    unit: "items",
  });

  const response = await fetch(`/api/admin/${action}`, { method: "POST" });
  const payload = await response.json().catch(() => ({ message: "Request failed." }));

  if (!response.ok) {
    adminStatusEl.textContent = payload.detail || payload.message || "Request failed.";
    progressElements.close.hidden = false;
    progressElements.close.disabled = false;
    setAdminButtonsDisabled(adminButtons, false);
    return;
  }

  adminStatusEl.textContent = payload.message || "Started.";

  while (true) {
    try {
      const progress = await loadProgress();
      progressAnimator.update(progress);
      if (progress.action === action && !progress.active) {
        if (progress.status === "error") {
          adminStatusEl.textContent = progress.message || "Request failed.";
          setAdminButtonsDisabled(adminButtons, false);
          return;
        }
        break;
      }
    } catch (_error) {
      progressElements.title.textContent = "Progress unavailable";
    }
    await new Promise((resolve) => window.setTimeout(resolve, progressPollIntervalMs()));
  }

  await progressAnimator.settle();
  adminStatusEl.textContent = "Done.";
  await loadStats(statsEl);
  resultsEl.innerHTML = "";
  statusEl.textContent = "Run the deck query to refresh results.";
  setAdminButtonsDisabled(adminButtons, false);
}

function initPage() {
  const form = document.getElementById("deck-form");
  const statusEl = document.getElementById("status");
  const resultsEl = document.getElementById("results");
  const adminStatusEl = document.getElementById("admin-status");
  const statsEl = document.getElementById("db-stats");
  const refreshStatsButton = document.getElementById("refresh-stats");
  const adminButtons = Array.from(document.querySelectorAll("[data-admin-action]"));
  const progressModalEl = document.getElementById("progress-modal");
  const progressCloseEl = document.getElementById("progress-close");
  const progressElements = {
    modal: progressModalEl,
    title: document.getElementById("progress-title"),
    fill: document.getElementById("progress-fill"),
    count: document.getElementById("progress-count"),
    percent: document.getElementById("progress-percent"),
    close: progressCloseEl,
  };

  if (
    !form || !statusEl || !resultsEl || !adminStatusEl || !statsEl || !refreshStatsButton ||
    !progressModalEl || !progressCloseEl || !progressElements.title ||
    !progressElements.fill || !progressElements.count || !progressElements.percent
  ) {
    return;
  }

  const progressAnimator = createProgressAnimator(progressElements);

  progressCloseEl.addEventListener("click", () => {
    hideProgressModal(progressModalEl);
  });

  hideProgressModal(progressModalEl);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await loadDecks(form, statusEl, resultsEl);
    } catch (_error) {
      statusEl.textContent = "Request failed.";
    }
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
          adminStatusEl,
          statsEl,
          form,
          statusEl,
          resultsEl,
          progressElements,
          progressAnimator,
        );
      } catch (_error) {
        adminStatusEl.textContent = "Request failed.";
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
