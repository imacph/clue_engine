"use strict";

const cardsByType = window.clueOptions.cards;
const cardsByName = new Map(
  Object.entries(cardsByType).flatMap(([type, cards]) =>
    cards.map((card) => [card.name, { ...card, type }])
  )
);
const cardsById = new Map(
  [...cardsByName.values()].map((card) => [card.id, card])
);
const cardNamePattern = [...cardsByName.keys()]
  .sort((left, right) => right.length - left.length)
  .map((name) => name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
  .join("|");
const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
const activeGameKey = "clue-engine-active-game";
const $ = (id) => document.getElementById(id);
let currentState = null;
let replayMode = false;
let replayPlaying = false;
let replayTimer = null;
let replayPlaybackGeneration = 0;
let refreshTimer = null;
let advancing = false;
let submitting = false;
let starting = false;
let mainMenuBusy = false;
let batchPollTimer = null;
let batchPolling = false;
let activeBatchId = null;
let batchFinished = false;
let lastBatchChart = null;
let batchChartVersion = 0;
let batchBinOffset = 0;
let batchRunsVersion = 0;
let batchRunsOffset = 0;
let batchRunsTotal = 0;
let batchReplay = false;
let batchReplayOpening = false;
let batchPolicyLabels = new Map();
let refreshing = false;
let requestVersion = 0;
let lastError = "";
let desktopThemeWrite = Promise.resolve();
let desktopFullscreen = false;
let fullscreenBusy = false;
let showCardIndicators = true;
let showBoardIndicators = true;
let cardView = "hand";
let lastActivityKey = null;
let lastRenderedState = null;
let lastNotebookFingerprint = null;
let lastNotebookStructureFingerprint = null;
let lastNotebookMarks = null;
let lastNotebookDraft = null;
let lastClauseFingerprint = null;
let lastReplayDeductionFingerprint = null;
let lastReplayKnowledgeFingerprint = null;
let replayMarkerType = "envelope";
let replayMarkerPlayer = "all";
let replayKnowledgeSort = "total";
let replayKnowledgeAscending = false;
const replayKnowledgeColumns = ["total", "suspect", "weapon", "room", "envelope"];
const replayKnowledgeVisible = new Set(replayKnowledgeColumns);
let lastDebugFingerprint = null;
let lastNotebookPerspective = null;
let selectedClause = null;
let clauseDraft = null;
let notebookGeneration = 0;
let notebookQueue = Promise.resolve();
let pendingNotebookEdits = [];
let lastBoardState = null;
let lastBoardLayout = null;
let lastBoardMoment = null;
let lastDiceState = null;
let lastCardAnimation = null;
let suggestionFlights = [];
let cardActivityReadUntil = 0;
const cardActivityReadTime = 800;
const cardPassReadTime = 1200;
let lastSuggestionRoom = null;
let hadReveal = false;
let hadBoardResponse = false;
const boardTabs = ["cards", "history", "clauses", "locations", "help"];
const insightsTabs = ["history", "clauses", "help"];
const selectedCardIds = { suspect: null, weapon: null, room: null };

function option(value, label) {
  const item = document.createElement("option");
  item.value = value;
  item.textContent = label;
  return item;
}

function displayPlayerText(text) {
  return text.replace(/\bPlayer (\d+)\b/g, (_, seat) => `Player ${Number(seat) + 1}`);
}

function showError(message) {
  lastError = message;
  $("error-message").textContent = message;
  $("error-message").hidden = !message;
  $("game-options-error").textContent = message;
  $("game-options-error").hidden = !message;
}

function confirmAction(message, { title = "Confirm action", confirmLabel = "Continue" } = {}) {
  const dialog = $("confirm-dialog");
  if (dialog.open) return Promise.resolve(false);
  $("confirm-title").textContent = title;
  $("confirm-message").textContent = message;
  $("confirm-accept").textContent = confirmLabel;
  dialog.returnValue = "";
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), { once: true });
    dialog.showModal();
  });
}

async function requestJson(path, { method = "GET", body } = {}) {
  const options = { method, headers: {} };
  if (method !== "GET") {
    options.headers["Content-Type"] = "application/json";
    options.headers["X-CSRF-Token"] = csrfToken;
  }
  if (body !== undefined) options.body = JSON.stringify(body);
  const response = await fetch(path, options);
  if (!response.ok) {
    let message = `Request failed (HTTP ${response.status}).`;
    if ((response.headers.get("content-type") || "").includes("json")) {
      try {
        const data = await response.json();
        if (typeof data?.error === "string" && data.error) message = data.error;
      } catch (error) {
        if (!(error instanceof SyntaxError)) throw error;
      }
    }
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

function formatBatchNumber(value) {
  return typeof value === "number"
    ? value.toLocaleString(undefined, { maximumFractionDigits: 2 })
    : "—";
}

function appendBatchStat(container, label, value) {
  const item = document.createElement("div");
  item.className = "batch-stat";
  const name = document.createElement("strong");
  name.textContent = label;
  const result = document.createElement("span");
  result.textContent = value;
  item.append(name, result);
  container.append(item);
}

function batchRelativeRate(rate, totalWins, completedSeats) {
  if (rate === null || !completedSeats || !totalWins) return "—";
  return `${(rate / (totalWins / completedSeats) * 100).toFixed(0)}%`;
}

function batchPolicyLabel(name, entries) {
  if (!name.startsWith("custom:")) return name;
  const customNames = entries.map(([policy]) => policy).filter((policy) => policy.startsWith("custom:"));
  return `Custom profile ${customNames.indexOf(name) + 1}`;
}

function renderBatchSummary(data) {
  const summary = data.summary;
  $("batch-summary").replaceChildren();
  $("batch-policy-summary").replaceChildren();
  if (!summary) return;

  const summaryGrid = document.createElement("div");
  summaryGrid.className = "batch-summary-grid";
  appendBatchStat(
    summaryGrid, "Simulations finished",
    `${data.finished_games} / ${data.requested_games}`,
  );
  appendBatchStat(summaryGrid, "Games completed", String(summary.completed_games));
  appendBatchStat(
    summaryGrid, "Outcomes",
    Object.entries(summary.outcomes).map(([outcome, count]) => `${outcome}: ${count}`).join(" · "),
  );
  appendBatchStat(summaryGrid, "Mean actions", formatBatchNumber(summary.mean_actions));
  appendBatchStat(summaryGrid, "Median actions", formatBatchNumber(summary.median_actions));
  appendBatchStat(summaryGrid, "90th percentile actions", formatBatchNumber(summary.p90_actions));
  appendBatchStat(
    summaryGrid, "Mean turns by seat",
    summary.mean_turns_by_seat
      ? summary.mean_turns_by_seat.map((value, seat) => `P${seat + 1}: ${formatBatchNumber(value)}`).join(" · ")
      : "—",
  );
  appendBatchStat(
    summaryGrid, "Wins by seat",
    summary.wins_by_seat.map((value, seat) => `P${seat + 1}: ${value}`).join(" · "),
  );
  for (const [label, key] of [
    ["Mean suggestions", "mean_suggestions"],
    ["Mean passes", "mean_passes"],
    ["Mean refutations", "mean_refutations"],
  ]) {
    appendBatchStat(summaryGrid, label, formatBatchNumber(summary[key]));
  }
  if (data.game_type === "board") {
    for (const [label, key] of [
      ["Mean dice rolls", "mean_rolls"],
      ["Mean movement actions", "mean_moves"],
      ["Mean room entries", "mean_room_entries"],
      ["Mean secret passages", "mean_passages"],
      ["Mean suspect relocations", "mean_suspect_relocations"],
      ["Mean weapon relocations", "mean_weapon_relocations"],
    ]) {
      appendBatchStat(summaryGrid, label, formatBatchNumber(summary[key]));
    }
  }
  $("batch-summary").append(summaryGrid);

  const entries = Object.entries(summary.policy_stats);
  batchPolicyLabels = new Map(entries.map(([name]) => [name, batchPolicyLabel(name, entries)]));
  const policyFilter = $("batch-policy-filter");
  const selectedPolicy = policyFilter.value;
  policyFilter.replaceChildren(option("", "All profiles"), ...entries.map(
    ([name]) => option(name, batchPolicyLabel(name, entries)),
  ));
  policyFilter.value = entries.some(([name]) => name === selectedPolicy) ? selectedPolicy : "";
  const seatFilter = $("batch-seat-filter");
  const selectedSeat = seatFilter.value;
  seatFilter.replaceChildren(option("", "All seats"), ...summary.wins_by_seat.map(
    (_, seat) => option(seat, `Player ${seat + 1}`),
  ));
  seatFilter.value = selectedSeat;
  if (entries.length === 0) return;
  const totalWins = entries.reduce((sum, [, stats]) => sum + stats.wins, 0);
  const completedSeats = entries.reduce((sum, [, stats]) => sum + stats.completed_seats, 0);
  const table = document.createElement("table");
  table.className = "batch-policy-table";
  table.setAttribute("aria-label", "Bot policy statistics");
  const head = document.createElement("thead");
  const headerRow = document.createElement("tr");
  for (const title of ["Bot", "Wins", "Completed seats", "Win rate", "Relative to equal share", "Learned solution"]) {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = title;
    headerRow.append(cell);
  }
  head.append(headerRow);
  const body = document.createElement("tbody");
  for (const [name, stats] of entries) {
    const row = document.createElement("tr");
    const values = [
      name,
      String(stats.wins),
      String(stats.completed_seats),
      stats.win_rate_per_completed_seat === null
        ? "—" : `${(stats.win_rate_per_completed_seat * 100).toFixed(1)}%`,
      batchRelativeRate(stats.win_rate_per_completed_seat, totalWins, completedSeats),
      `${stats.learned_solution} / ${stats.seat_games}`,
    ];
    for (const [index, value] of values.entries()) {
      const cell = document.createElement("td");
      if (index === 0 && name.startsWith("custom:")) {
        const details = document.createElement("details");
        const title = document.createElement("summary");
        title.textContent = batchPolicyLabel(name, entries);
        const description = document.createElement("span");
        description.textContent = name.slice(7).replaceAll("_", " ").replaceAll(",", ", ");
        details.append(title, description);
        cell.append(details);
      } else {
        cell.textContent = value;
      }
      row.append(cell);
    }
    body.append(row);
  }
  table.append(head, body);
  $("batch-policy-summary").append(table);
}

const batchTabs = ["distribution", "summary", "runs"];

function switchBatchTab(name) {
  for (const tab of batchTabs) {
    const active = tab === name;
    $(`batch-tab-${tab}`).setAttribute("aria-selected", String(active));
    $(`batch-tab-${tab}`).tabIndex = active ? 0 : -1;
    $(`batch-panel-${tab}`).hidden = !active;
  }
  if (name === "distribution" && lastBatchChart) drawBatchGraph(lastBatchChart);
}

function batchGraphBuckets(chart, plotWidth) {
  if (!chart.numeric_summary) {
    return {
      numeric: false, binsPerBar: 1,
      bars: chart.bins.map((bin, index) => ({
        label: bin.label.replaceAll("_", " "), count: bin.count, start: index, end: index + 1,
      })),
      start: 0, end: chart.bins.length,
    };
  }
  const ranges = chart.bins.map((bin) => {
    const match = /^(\d+)(?:-(\d+))?$/.exec(bin.label);
    if (!match) throw new Error(`Invalid numeric distribution bin: ${bin.label}`);
    return { start: Number(match[1]), end: Number(match[2] ?? match[1]), count: bin.count };
  });
  const start = ranges[0].start;
  const last = ranges[ranges.length - 1];
  const width = ranges[0].end - start + 1;
  const slots = Math.round((last.start - start) / width) + 1;
  const maxBars = Math.max(1, Math.min(80, Math.floor(plotWidth / 6)));
  const binsPerBar = Math.max(1, Math.ceil(slots / maxBars));
  const groupWidth = binsPerBar * width;
  const grouped = new Map();
  for (const bin of ranges) {
    const index = Math.floor((bin.start - start) / groupWidth);
    grouped.set(index, (grouped.get(index) || 0) + bin.count);
  }
  const bars = [...grouped].map(([index, count]) => {
    const first = start + index * groupWidth;
    const lastValue = Math.min(last.end, first + groupWidth - 1);
    return {
      label: first === lastValue ? String(first) : `${first}-${lastValue}`,
      count, start: first, end: lastValue + 1,
    };
  });
  return { numeric: true, binsPerBar, bars, start, end: last.end + 1 };
}

function drawBatchGraph(chart) {
  const graph = $("batch-chart-graph");
  graph.replaceChildren();
  $("batch-chart-grouping").textContent = "";
  if (!chart || !chart.samples) return;
  const width = Math.max(240, graph.clientWidth || 900);
  const height = Math.max(190, graph.clientHeight || 240);
  graph.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const left = 60, right = 18, top = 24, bottom = height - 38;
  const plotWidth = width - left - right;
  const plotHeight = bottom - top;
  const buckets = batchGraphBuckets(chart, plotWidth);
  const maximum = buckets.bars.reduce((value, bar) => Math.max(value, bar.count), 0);
  const mode = $("batch-display-mode").value;
  graph.append(svgElement("text", { x: 5, y: 13, class: "batch-chart-axis" },
    mode === "percent" ? "Share (%)" : "Count"));
  const ticks = new Set([0, ...[1, 2, 3, 4].map((step) => Math.round(maximum * step / 4))]);
  for (const count of ticks) {
    const y = bottom - count / maximum * plotHeight;
    graph.append(svgElement("line", { x1: left, y1: y, x2: width - right, y2: y, class: "batch-chart-grid" }));
    const label = mode === "percent" ? `${formatBatchNumber(count / chart.samples * 100)}%` : String(count);
    graph.append(svgElement("text", { x: left - 6, y: y + 4, "text-anchor": "end", class: "batch-chart-axis" }, label));
  }
  const domain = buckets.end - buckets.start;
  let cumulative = 0;
  for (const bar of buckets.bars) {
    cumulative += bar.count;
    const x = left + (bar.start - buckets.start) / domain * plotWidth;
    const barWidth = (bar.end - bar.start) / domain * plotWidth;
    const barHeight = bar.count / maximum * plotHeight;
    const share = (bar.count / chart.samples * 100).toFixed(1);
    const description = `${bar.label}: ${formatBatchNumber(bar.count)} of ${formatBatchNumber(chart.samples)} `
      + `(${share}%)${buckets.numeric ? ` · ${(cumulative / chart.samples * 100).toFixed(1)}% cumulative` : ""}`;
    const group = svgElement("g", {
      class: "batch-chart-bin", tabindex: 0, role: "img", "aria-label": description,
    });
    group.append(
      svgElement("title", {}, description),
      svgElement("rect", {
        x: x + 1, y: bottom - barHeight, width: Math.max(0, barWidth - 2),
        height: barHeight, class: "batch-chart-bar",
      }),
      svgElement("rect", { x, y: top, width: barWidth, height: plotHeight, class: "batch-chart-hit" }),
    );
    const inspect = () => { $("batch-chart-inspection").textContent = description; };
    group.addEventListener("mouseenter", inspect);
    group.addEventListener("focus", inspect);
    graph.append(group);
    if (!buckets.numeric) {
      const center = x + barWidth / 2;
      const label = svgElement("text", {
        x: center, y: bottom + 15, "text-anchor": "middle", class: "batch-chart-axis",
      });
      bar.label.split(" ").forEach((word, index) => {
        const attrs = { x: center, dy: index ? 12 : 0 };
        if (word.length * 6 > barWidth - 4) {
          attrs.textLength = Math.max(1, barWidth - 4);
          attrs.lengthAdjust = "spacingAndGlyphs";
        }
        label.append(svgElement("tspan", attrs, word));
      });
      graph.append(label);
    }
  }
  if (buckets.numeric) {
    const intervals = width < 500 ? 2 : 4;
    for (let index = 0; index <= intervals; index++) {
      const fraction = index / intervals;
      const value = Math.round(buckets.start + fraction * domain);
      graph.append(svgElement("text", {
        x: left + fraction * plotWidth, y: bottom + 17,
        "text-anchor": index === 0 ? "start" : index === intervals ? "end" : "middle",
        class: "batch-chart-axis",
      }, formatBatchNumber(value)));
    }
    if (buckets.binsPerBar > 1) {
      $("batch-chart-grouping").textContent =
        `Graph combines up to ${formatBatchNumber(buckets.binsPerBar)} adjacent bins per bar; exact bins are available below.`;
    }
  }
}

function renderBatchBinTable() {
  const container = $("batch-chart-table");
  container.replaceChildren();
  const chart = lastBatchChart;
  if (!chart || !chart.samples || !$("batch-chart-values").open) return;
  const end = Math.min(batchBinOffset + 50, chart.bins.length);
  $("batch-bin-status").textContent =
    `Showing ${batchBinOffset + 1}–${end} of ${chart.bins.length} bins.`;
  $("batch-bin-previous").disabled = batchBinOffset === 0;
  $("batch-bin-next").disabled = end >= chart.bins.length;
  const table = document.createElement("table");
  table.className = "batch-policy-table";
  table.setAttribute("aria-label", "Exact distribution bins");
  const head = document.createElement("thead");
  const header = document.createElement("tr");
  for (const label of ["Bin", "Count", "Share", ...(chart.numeric_summary ? ["Cumulative"] : [])]) {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = label;
    header.append(cell);
  }
  head.append(header);
  const body = document.createElement("tbody");
  let cumulative = chart.bins.slice(0, batchBinOffset).reduce((sum, bin) => sum + bin.count, 0);
  for (const bin of chart.bins.slice(batchBinOffset, end)) {
    cumulative += bin.count;
    const row = document.createElement("tr");
    const values = [bin.label.replaceAll("_", " "), formatBatchNumber(bin.count), `${(bin.probability * 100).toFixed(1)}%`];
    if (chart.numeric_summary) values.push(`${(cumulative / chart.samples * 100).toFixed(1)}%`);
    for (const value of values) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    body.append(row);
  }
  table.append(head, body);
  container.append(table);
}

function renderBatchChart() {
  const chart = lastBatchChart;
  const stats = $("batch-chart-stats");
  stats.replaceChildren();
  $("batch-chart-graph").replaceChildren();
  $("batch-chart-table").replaceChildren();
  $("batch-chart-empty").hidden = !chart || Boolean(chart.samples);
  $("batch-chart-values").hidden = !chart || !chart.samples;
  $("batch-chart-grouping").textContent = "";
  $("batch-chart-inspection").textContent = "Hover or focus a bar to inspect its count and share.";
  if (!chart) return;
  $("batch-distribution-title").textContent =
    $("batch-metric").value === "deduction" ? "First solution action" : displayPlayerText(chart.title);
  $("batch-chart-details").textContent =
    `${chart.samples} samples · ${chart.denominator}. ${chart.details}`;
  if (chart.numeric_summary) {
    for (const [label, key] of [
      ["Minimum", "minimum"], ["Mean", "mean"], ["Median", "median"],
      ["90th percentile", "p90"], ["Maximum", "maximum"],
    ]) appendBatchStat(stats, label, formatBatchNumber(chart.numeric_summary[key]));
  }
  drawBatchGraph(chart);
  renderBatchBinTable();
}

async function loadBatchChart() {
  if (!activeBatchId || !batchFinished) return;
  const version = ++batchChartVersion;
  const batchId = activeBatchId;
  batchBinOffset = 0;
  lastBatchChart = null;
  renderBatchChart();
  $("batch-chart-details").textContent = "Loading distribution…";
  const width = Number($("batch-bin-width").value);
  if (!Number.isSafeInteger(width) || width < 1) {
    $("batch-chart-details").textContent = "Histogram bin width must be a positive whole number.";
    throw new Error("Histogram bin width must be a positive whole number.");
  }
  const query = new URLSearchParams({
    metric: $("batch-metric").value,
    width: String(width),
  });
  if ($("batch-policy-filter").value) query.set("policy", $("batch-policy-filter").value);
  if ($("batch-seat-filter").value !== "") query.set("seat", $("batch-seat-filter").value);
  let chart;
  try {
    chart = await requestJson(`/api/batch/${encodeURIComponent(batchId)}/distribution?${query}`);
  } catch (error) {
    if (version !== batchChartVersion || batchId !== activeBatchId) return;
    $("batch-chart-details").textContent = `Could not load distribution: ${error.message}`;
    throw error;
  }
  if (version !== batchChartVersion || batchId !== activeBatchId) return;
  lastBatchChart = chart;
  renderBatchChart();
}

async function loadBatchRuns() {
  if (!activeBatchId || !batchFinished) return;
  const version = ++batchRunsVersion;
  const batchId = activeBatchId;
  $("batch-runs-status").textContent = "Loading runs…";
  $("batch-runs-table").replaceChildren();
  $("batch-runs-previous").disabled = true;
  $("batch-runs-next").disabled = true;
  const query = new URLSearchParams({
    sort: $("batch-runs-sort").value, order: $("batch-runs-order").value,
    offset: String(batchRunsOffset), limit: "25",
  });
  if ($("batch-policy-filter").value) query.set("policy", $("batch-policy-filter").value);
  if ($("batch-seat-filter").value !== "") query.set("seat", $("batch-seat-filter").value);
  let data;
  try {
    data = await requestJson(`/api/batch/${encodeURIComponent(batchId)}/runs?${query}`);
  } catch (error) {
    if (version !== batchRunsVersion || batchId !== activeBatchId) return;
    $("batch-runs-status").textContent = `Could not load runs: ${error.message}`;
    throw error;
  }
  if (version !== batchRunsVersion || batchId !== activeBatchId) return;
  batchRunsTotal = data.total;
  $("batch-runs-status").textContent = data.total
    ? `Showing ${data.offset + 1}–${data.offset + data.runs.length} of ${data.total} matching runs.`
    : "No runs match these filters.";
  $("batch-runs-previous").disabled = data.offset === 0;
  $("batch-runs-next").disabled = data.offset + data.runs.length >= data.total;
  if (!data.runs.length) return;
  const table = document.createElement("table");
  table.className = "batch-policy-table";
  table.setAttribute("aria-label", "Individual batch runs");
  const head = document.createElement("thead");
  const header = document.createElement("tr");
  const sort = $("batch-runs-sort");
  const extra = !["game", "outcome", "winner", "steps", "turns", "learned", "first_solution"].includes(sort.value);
  for (const label of [
    "Run", "Outcome", "Winner", "Actions", "Turns", "Learned", "First solution",
    ...(extra ? [sort.selectedOptions[0].textContent] : []), "Profiles", "Replay",
  ]) {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = label;
    header.append(cell);
  }
  head.append(header);
  const body = document.createElement("tbody");
  for (const run of data.runs) {
    const row = document.createElement("tr");
    const values = [
      String(run.game + 1), run.outcome.replaceAll("_", " "),
      run.winner === null ? "—" : `Player ${run.winner + 1}`,
      String(run.steps), String(run.turns.reduce((sum, turns) => sum + turns, 0)),
      `${run.learned} / ${run.policies.length}`,
      run.first_solution === null ? "—" : String(run.first_solution),
      ...(extra ? [String(run[sort.value])] : []),
    ];
    for (const value of values) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    const profiles = document.createElement("td");
    const details = document.createElement("details");
    const title = document.createElement("summary");
    title.textContent = "View profiles";
    details.append(title);
    run.policies.forEach((name, seat) => {
      const item = document.createElement("div");
      const learned = run.first_solution_steps[seat];
      item.textContent = `Player ${seat + 1}: ${batchPolicyLabels.get(name) || name} · `
        + (learned === null ? "not recorded as learned" : `learned at action ${learned}`);
      details.append(item);
    });
    profiles.append(details);
    row.append(profiles);
    const replayCell = document.createElement("td");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button button-secondary";
    button.textContent = "Open replay";
    button.setAttribute("aria-label", `Open replay for run ${run.game + 1}`);
    button.addEventListener("click", () => openBatchReplay(run.game));
    replayCell.append(button);
    row.append(replayCell);
    body.append(row);
  }
  table.append(head, body);
  $("batch-runs-table").append(table);
}

async function openBatchReplay(game) {
  if (!activeBatchId || batchReplayOpening) return;
  batchReplayOpening = true;
  try {
    await requestJson(`/api/batch/${encodeURIComponent(activeBatchId)}/runs/${game}/replay`, {
      method: "POST", body: {},
    });
    const state = await requestJson("/api/state");
    batchReplay = true;
    sessionStorage.setItem(activeGameKey, "1");
    activateGame(state);
    await openReplay();
  } catch (error) {
    showError(`Could not open batch replay: ${error.message}`);
  } finally {
    batchReplayOpening = false;
  }
}

function updateBatchScreen(data) {
  const running = data.status === "queued" || data.status === "running";
  const progress = data.requested_games > 0
    ? Math.min(100, data.finished_games / data.requested_games * 100) : 0;
  $("batch-progress").value = progress;
  if (running) {
    $("batch-run-status").textContent =
      `Running ${data.finished_games} of ${data.requested_games} games…`;
  } else if (data.status === "completed") {
    $("batch-run-status").textContent =
      `Finished ${data.finished_games} of ${data.requested_games} games.`;
  } else if (data.status === "cancelled") {
    $("batch-run-status").textContent =
      `Cancelled after ${data.finished_games} of ${data.requested_games} games.`;
  } else {
    $("batch-run-status").textContent = data.error || "The batch simulation failed.";
  }
  $("batch-cancel").hidden = !running;
  $("batch-cancel").disabled = data.cancel_requested;
  $("batch-new-run").hidden = running;
  $("batch-main-menu").hidden = running;
  $("batch-metric").disabled = running;
  $("batch-bin-width").disabled = running;
  $("batch-policy-filter").disabled = running;
  $("batch-seat-filter").disabled = running;
  batchFinished = !running;
  if (data.summary) renderBatchSummary(data);
  if (data.game_type === "board") {
    for (const option of document.querySelectorAll("[data-board-only]")) option.hidden = false;
  } else {
    for (const option of document.querySelectorAll("[data-board-only]")) option.hidden = true;
    if ($("batch-metric").selectedOptions[0]?.hasAttribute("data-board-only")) {
      $("batch-metric").value = "outcomes";
    }
    if ($("batch-runs-sort").selectedOptions[0]?.hasAttribute("data-board-only")) {
      $("batch-runs-sort").value = "game";
    }
  }
}

async function pollBatch() {
  if (!activeBatchId || batchPolling) return;
  batchPolling = true;
  try {
    const data = await requestJson(`/api/batch/${encodeURIComponent(activeBatchId)}`);
    updateBatchScreen(data);
    if (data.status === "completed" || data.status === "cancelled" || data.status === "error") {
      clearInterval(batchPollTimer);
      batchPollTimer = null;
      await Promise.all([loadBatchChart(), loadBatchRuns()]);
    }
  } catch (error) {
    clearInterval(batchPollTimer);
    batchPollTimer = null;
    showError(`Could not update batch results: ${error.message}`);
  } finally {
    batchPolling = false;
  }
}

async function submitBatch(setup) {
  const startedBatch = await requestJson("/api/batch", {
    method: "POST",
    body: { setup, games: window.setupWizard.batchGames() },
  });
  activeBatchId = startedBatch.batch_id;
  batchChartVersion++;
  batchRunsVersion++;
  batchRunsOffset = 0;
  batchBinOffset = 0;
  batchFinished = false;
  lastBatchChart = null;
  window.setupWizard.rememberStarted(setup);
  $("main-menu").hidden = true;
  $("setup-screen").hidden = true;
  $("game-screen").hidden = true;
  $("batch-screen").hidden = false;
  document.body.classList.add("batch-active");
  switchBatchTab("distribution");
  $("batch-title").focus();
  $("batch-run-status").textContent = "Starting batch…";
  $("batch-progress").value = 0;
  $("batch-summary").replaceChildren();
  $("batch-policy-summary").replaceChildren();
  $("batch-chart-graph").replaceChildren();
  $("batch-chart-table").replaceChildren();
  $("batch-chart-empty").hidden = true;
  $("batch-chart-values").hidden = true;
  $("batch-chart-values").open = false;
  $("batch-chart-grouping").textContent = "";
  $("batch-chart-inspection").textContent = "Hover or focus a bar to inspect its count and share.";
  $("batch-chart-stats").replaceChildren();
  $("batch-policy-filter").replaceChildren(option("", "All profiles"));
  $("batch-seat-filter").replaceChildren(option("", "All seats"));
  $("batch-chart-details").textContent = "Distributions will be available when the batch finishes.";
  $("batch-runs-table").replaceChildren();
  $("batch-runs-status").textContent = "Runs will be available when the batch finishes.";
  $("batch-new-run").hidden = true;
  $("batch-main-menu").hidden = true;
  clearInterval(batchPollTimer);
  batchPollTimer = setInterval(pollBatch, 500);
  await pollBatch();
}

async function startGame(event) {
  event?.preventDefault();
  if (starting) return;
  starting = true;
  try {
    const batchMode = window.setupWizard.isBatchMode();
    const debug = !batchMode && $("debug").checked;
    if (debug && !await confirmAction("Debug mode reveals every hand, the solution, and private events. Continue?")) {
      $("debug").checked = false;
      return;
    }
    showError("");
    const setup = window.setupWizard.payload();
    if (batchMode) {
      await submitBatch(setup);
      return;
    }
    notebookGeneration++;
    notebookQueue = Promise.resolve();
    pendingNotebookEdits = [];
    const version = ++requestVersion;
    showError("");
    clearSelectedCards();
    cardView = "hand";
    lastActivityKey = null;
    lastRenderedState = null;
    lastNotebookFingerprint = null;
    lastNotebookStructureFingerprint = null;
    lastNotebookMarks = null;
    lastNotebookDraft = null;
    lastClauseFingerprint = null;
    selectedClause = null;
    clauseDraft = null;
    lastBoardState = null;
    lastBoardMoment = null;
    lastDiceState = null;
    lastCardAnimation = null;
    clearSuggestionFlights();
    lastSuggestionRoom = null;
    hadReveal = false;
    hadBoardResponse = false;
    const gameSetup = window.setupWizard.resolveBotSeats(setup);
    const state = await requestJson("/api/game", {
      method: "POST",
      body: gameSetup,
    });
    if (version !== requestVersion) return;
    window.setupWizard.rememberStarted(gameSetup);
    sessionStorage.setItem(activeGameKey, "1");
    activateGame(state);
  } catch (error) {
    showError(error.message);
  } finally {
    starting = false;
  }
}

function activateGame(state) {
  lastError = "";
  clauseDraft = null;
  document.body.classList.add("game-active");
  document.body.classList.remove("batch-active");
  document.body.classList.toggle("board-game", Boolean(state.board));
  document.body.classList.toggle("manual-notebook-active", state.notebook_mode === "manual");
  $("game-toolbar").append($("header-tools"));
  configureBoardWorkspace(Boolean(state.board));
  $("main-menu").hidden = true;
  $("setup-screen").hidden = true;
  $("batch-screen").hidden = true;
  $("game-screen").hidden = false;
  $("batch-replay-return").hidden = !batchReplay;
  $("error-message").hidden = true;
  currentState = state;
  buildPlayerFilters(state);
  renderState(state);
  clearInterval(refreshTimer);
  refreshTimer = setInterval(refreshState, state.board ? 250 : 700);
}

async function restoreGame() {
  if (sessionStorage.getItem(activeGameKey) !== "1") return;
  const version = requestVersion;
  try {
    const state = await requestJson("/api/state");
    if (version === requestVersion) activateGame(state);
  } catch (error) {
    if (version !== requestVersion) return;
    if (error.status === 404) sessionStorage.removeItem(activeGameKey);
    showError(error.status === 404 ? "The previous game is no longer available." : error.message);
  }
}

function buildPlayerFilters(state) {
  const numPlayers = state.num_players;
  const selectors = ["viewer-select", "history-actor", "clause-actor"];
  for (const id of selectors) {
    const select = $(id);
    select.replaceChildren();
    if (id !== "viewer-select") select.append(option("all", "All players"));
    for (let seat = 0; seat < numPlayers; seat++) {
      select.append(option(seat, `Player ${seat + 1}`));
    }
  }
  const historyKind = $("history-kind");
  historyKind.replaceChildren(option("all", "All types"));
  for (const [value, label] of [
    ["suggest", "Suggestion"], ["pass", "Pass"], ["refute", "Refutation"],
    ["show", "Shown card"], ["expose", "Face-up card"], ["accuse", "Accusation"], ["end_turn", "End turn"],
    ...(state.board ? [
      ["roll", "Dice roll"], ["move", "Movement"], ["passage", "Passage"],
      ["suspect_moved", "Suspect moved"], ["weapon_moved", "Weapon moved"],
    ] : []),
  ]) historyKind.append(option(value, label));
  $("viewer-select").value = String(currentState?.selected_player ?? 0);
}

function selectedFilters() {
  return new URLSearchParams({
    player: $("viewer-select").value || "0",
    clause_actor: $("clause-actor").value || "all",
    clause_kind: $("clause-kind").value || "all",
  });
}

function acceptState(state) {
  if (currentState && state.notebook_mode === "manual"
    && currentState.notebook_mode === "manual"
    && state.notebook_revision < currentState.notebook_revision) {
    state.matrix = currentState.matrix;
    state.notebook_clauses = currentState.notebook_clauses;
    state.notebook_revision = currentState.notebook_revision;
  }
  currentState = state;
}

async function refreshState() {
  if (refreshing || submitting || replayMode || $("confirm-dialog").open
    || $("game-options-dialog").open) return;
  refreshing = true;
  const version = requestVersion;
  try {
    const state = await requestJson(`/api/state?${selectedFilters()}`);
    if (version !== requestVersion || !currentState) return;
    acceptState(state);
    renderState(state);
    if (state.auto_progress && !state.paused && shouldAdvance(state)) {
      await advanceBot(false);
    }
  } catch (error) {
    if (version === requestVersion) {
      if (error.status === 404) clearInterval(refreshTimer);
      showError(error.message);
    }
  } finally {
    refreshing = false;
  }
}

function shouldAdvance(state) {
  return !advancing && !submitting && !cardActivityPending()
    && !$("confirm-dialog").open && canAdvanceBot(state);
}

function cardActivityPending() {
  return suggestionFlights.length > 0 || performance.now() < cardActivityReadUntil;
}

function canAdvanceBot(state) {
  return !state.waiting_for_turn && !state.is_over && !state.limit_reached
    && (state.human_player === null || state.to_move !== state.human_player);
}

function renderState(state) {
  const fingerprint = JSON.stringify(state);
  if (fingerprint === lastRenderedState) return;
  lastRenderedState = fingerprint;
  updateClausePerspective(state);
  const fixedRoom = state.board && state.legal.suggest ? state.legal.suggest_room : null;
  const hasReveal = state.legal.reveals.length > 0;
  const hasBoardResponse = state.board && (hasReveal || state.legal.pass);
  const moveHadFocus = state.board && (
    document.activeElement === $("board-map-shell")
    || ($("board-panel").contains(document.activeElement)
      && document.activeElement?.hasAttribute("data-board-move"))
  );
  let focusCards = false;
  if (state.board && !replayMode) {
    if (hasBoardResponse && !hadBoardResponse) {
      switchBoardTab("cards");
    } else if (fixedRoom !== null && fixedRoom !== lastSuggestionRoom) {
      switchBoardTab("cards");
      focusCards = moveHadFocus;
    }
  }
  hadBoardResponse = Boolean(hasBoardResponse);
  const activityKey = state.activity
    ? `${state.activity.kind}:${state.activity.actor}:${state.activity.suggestion_actor ?? ""}`
      + `:${state.activity.card_id ?? ""}:${state.activity.recipient ?? ""}`
    : null;
  if (state.activity?.kind === "reveal" && activityKey !== lastActivityKey) {
    clearSelectedCards();
  }
  lastActivityKey = activityKey;
  if (fixedRoom !== null && fixedRoom !== lastSuggestionRoom) {
    selectedCardIds.room = fixedRoom;
    cardView = "suspect";
  }
  lastSuggestionRoom = fixedRoom;
  if (hasReveal && !hadReveal) cardView = "hand";
  hadReveal = hasReveal;
  setText("game-status", displayPlayerText(state.status));
  $("game-progress-meta").textContent =
    `Actions: ${state.steps} · Player 1 turns: ${state.player0_turns}`
    + (state.paused ? " · Paused" : "")
    + (state.waiting_for_turn ? " · Waiting for next turn" : "")
    + ((state.board_rules && Object.entries(state.board_rules).some(([key, value]) =>
      ["move_suspect", "move_weapon", "summoned_suggestion", "secret_passages"].includes(key)
        ? !value : (key === "early_end" ? !value : key === "passage_count" ? false : value)))
      || (state.game_rules && Object.values(state.game_rules).some(Boolean))
      ? " · House rules active" : "");
  $("pause-button").textContent = state.paused ? "Resume" : "Pause";
  $("pause-button").disabled = state.is_over || state.limit_reached;
  $("replay-open").hidden = !state.is_over || replayMode;
  $("replay-end").hidden = state.is_over || replayMode;
  $("pause-button").hidden = replayMode;
  const turnButton = $("turn-button");
  turnButton.hidden = replayMode || (!state.waiting_for_turn && !state.legal.end_turn);
  turnButton.textContent = state.waiting_for_turn ? "Next turn" : "End turn";
  $("next-button").hidden = replayMode || !(state.paused && canAdvanceBot(state));
  $("viewer-select").value = String(state.selected_player);
  $("viewer-field").hidden = state.mode !== "spectate";
  renderBoard(state);
  updateKnowledgeIndicators(state);
  if (!replayMode) renderHand(state);
  renderCardInteraction(state);
  renderNotebook(state);
  renderHistory(state.events);
  renderClauses(state);
  renderDebug(state.debug_info);
  renderActions(state);
  $("error-message").hidden = !lastError;
  $("error-message").textContent = lastError;
  if (focusCards) document.querySelector('[data-card-view="suspect"]').focus({ preventScroll: true });
}

function setText(id, text) {
  if ($(id).textContent !== text) $(id).textContent = text;
}

const pawnStyles = [
  { label: "Sc", color: "#b72940", ink: "#fff" },
  { label: "Mu", color: "#e5ba35", ink: "#222" },
  { label: "Wh", color: "#f6f3e9", ink: "#263238" },
  { label: "Gr", color: "#36885a", ink: "#fff" },
  { label: "Pe", color: "#346cac", ink: "#fff" },
  { label: "Pl", color: "#82559a", ink: "#fff" },
];
const svgNamespace = "http://www.w3.org/2000/svg";

function svgElement(name, attributes = {}, text = null) {
  const element = document.createElementNS(svgNamespace, name);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
  if (text !== null) element.textContent = text;
  return element;
}

function boardLocation(location) {
  return location.kind === "room"
    ? cardName(location.room_id)
    : `hallway (${location.x}, ${location.y})`;
}

function pawnController(pawn, state) {
  if (pawn.seat === null) return "Unassigned";
  return `Player ${pawn.seat + 1} (${pawn.seat === state.human_player ? "you" : "bot"})`;
}

function moveLabel(move, state) {
  if (move.kind === "room") return `Enter ${cardName(move.room_id)}`;
  const pawn = state.board.suspects.find((item) => item.seat === state.board.turn_player);
  if (pawn?.location.kind === "hallway") {
    const dx = move.x - pawn.location.x;
    const dy = move.y - pawn.location.y;
    const direction = dy < 0 ? "Up" : dy > 0 ? "Down" : dx < 0 ? "Left" : "Right";
    return `${direction} (${move.x}, ${move.y})`;
  }
  return `Exit to hallway (${move.x}, ${move.y})`;
}

function directionalMoves(state, dx, dy) {
  const board = state.board;
  const pawn = board.suspects.find((item) => item.seat === board.turn_player);
  if (!pawn) return [];
  return state.legal.moves.filter((move) => {
    if (pawn.location.kind === "hallway" && move.kind === "hallway") {
      return move.x - pawn.location.x === dx && move.y - pawn.location.y === dy;
    }
    return board.layout.doors.some((door) => {
      if (pawn.location.kind === "hallway" && move.kind === "room") {
        return door.room_id === move.room_id
          && door.hallway_square.x === pawn.location.x && door.hallway_square.y === pawn.location.y
          && door.room_square.x - door.hallway_square.x === dx
          && door.room_square.y - door.hallway_square.y === dy;
      }
      return pawn.location.kind === "room" && move.kind === "hallway"
        && door.room_id === pawn.location.room_id
        && door.hallway_square.x === move.x && door.hallway_square.y === move.y
        && door.hallway_square.x - door.room_square.x === dx
        && door.hallway_square.y - door.room_square.y === dy;
    });
  });
}

function boardInstruction(state) {
  const board = state.board;
  if (state.is_over || state.limit_reached) return displayPlayerText(state.status);
  if (state.waiting_for_turn) return "Review the completed turn, then select Next turn.";
  if (state.to_move !== board.turn_player) {
    return state.to_move === state.human_player
      ? "Respond to the suggestion in Actions."
      : `Player ${state.to_move + 1} is responding to Player ${board.turn_player + 1}'s suggestion.`;
  }
  if (state.to_move !== state.human_player) {
    return `Following Player ${board.turn_player + 1}. Watch the highlighted pawn move around the mansion.`;
  }
  const legal = state.legal;
  if (legal.suggest && legal.roll) {
    const location = board.summoned_seats.includes(board.turn_player)
      ? `You were summoned to ${cardName(legal.suggest_room)}.`
      : `You are in ${cardName(legal.suggest_room)}.`;
    return `${location} Suggest there, roll to leave`
      + (legal.passage ? ", or take the passage." : ".");
  }
  if (legal.suggest) {
    return `In ${cardName(legal.suggest_room)}: choose a suspect and weapon in Actions`
      + (legal.end_turn ? ", or end your turn." : ".");
  }
  if (legal.moves.length) {
    return "Select a square or use arrow keys.";
  }
  if (legal.roll) {
    return legal.passage
      ? "Roll to move, or take the secret passage to another room."
      : "Roll both dice to begin moving.";
  }
  if (legal.end_turn) return "Movement or the suggestion is complete. End your turn when ready.";
  return "Use the available actions below.";
}

function roomBounds(room) {
  const xs = room.squares.map((square) => square.x);
  const ys = room.squares.map((square) => square.y);
  return {
    minX: Math.min(...xs), maxX: Math.max(...xs),
    minY: Math.min(...ys), maxY: Math.max(...ys),
  };
}

function buildBoardBase(layout, map = $("board-map"), dynamicId = "board-dynamic") {
  map.replaceChildren();
  map.setAttribute("viewBox", `0 0 ${layout.width} ${layout.height}`);
  const base = svgElement("g", { "aria-hidden": "true" });
  layout.rooms.forEach((room, index) => {
    for (const square of room.squares) {
      base.append(svgElement("rect", {
        x: square.x, y: square.y, width: 1, height: 1, class: `board-room-${index}`,
      }));
    }
  });
  for (const square of layout.hallways) {
    base.append(svgElement("rect", {
      x: square.x, y: square.y, width: 1, height: 1, class: "board-hallway",
    }));
  }
  for (const square of layout.walls) {
    base.append(svgElement("rect", {
      x: square.x, y: square.y, width: 1, height: 1, class: "board-wall",
    }));
  }
  for (const room of layout.rooms) {
    const bounds = roomBounds(room);
    const center = (bounds.minX + bounds.maxX + 1) / 2;
    const name = room.name.endsWith(" Room")
      ? [room.name.slice(0, -5), "Room"] : [room.name];
    const label = svgElement("text", { x: center, y: bounds.minY + .64, class: "board-room-name" });
    name.forEach((part, index) => label.append(svgElement("tspan", {
      x: center, dy: index ? .48 : 0,
    }, part)));
    base.append(label);
    const passageIndex = layout.passages.findIndex((pair) => pair.includes(room.id));
    if (passageIndex !== -1) {
      const x = bounds.maxX + .55;
      const y = bounds.minY + .55;
      const badge = svgElement("g", { class: "board-passage-mark", "data-passage": passageIndex });
      badge.append(svgElement("circle", { cx: x, cy: y, r: .4 }));
      badge.append(svgElement("text", { x, y: y + .17 }, String.fromCharCode(65 + passageIndex)));
      base.append(badge);
    }
  }
  map.append(base, svgElement("g", { id: dynamicId }));
}

function appendPawn(group, pawn, state, x, y, active, radius) {
  const style = pawnStyles[pawn.id];
  const description = `${pawn.name}, ${pawnController(pawn, state)}, ${boardLocation(pawn.location)}`
    + (active ? (state.waiting_for_turn ? ", turn under review" : ", current turn") : "");
  const marker = svgElement("g", { role: "img", "aria-label": description });
  marker.dataset.pawnId = String(pawn.id);
  marker.append(svgElement("title", {}, description));
  marker.append(svgElement("circle", {
    cx: x, cy: y, r: radius, fill: style.color,
    class: `board-pawn${active ? " board-pawn-active" : ""}${pawn.seat === null ? " board-pawn-unassigned" : ""}`,
  }));
  marker.append(svgElement("text", {
    x, y: y + .09, fill: style.ink, class: "board-pawn-text", "aria-hidden": "true",
  }, pawn.seat === null ? style.label : `P${pawn.seat + 1}`));
  group.append(marker);
}

function renderDice(dice, animate = false) {
  const total = dice ? dice[0] + dice[1] : null;
  $("board-dice").setAttribute("aria-label", dice
    ? `Dice: ${dice[0]} and ${dice[1]}, total ${total}` : "Dice not rolled");
  $("board-dice").querySelectorAll(".die").forEach((die, index) => {
    die.dataset.value = dice ? String(dice[index]) : "0";
    if (animate && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      die.getAnimations().forEach((animation) => animation.cancel());
      const direction = index ? -1 : 1;
      die.animate([
        { transform: `translateY(-8px) rotate(${direction * -65}deg) scale(.8)`, opacity: .5 },
        { transform: `translateY(2px) rotate(${direction * 20}deg) scale(1.05)`, opacity: 1, offset: .7 },
        { transform: "translateY(0) rotate(0) scale(1)", opacity: 1 },
      ], { duration: 480, easing: "ease-out" });
    }
  });
  setText("board-dice-total", total === null ? "–" : String(total));
}

function isDiceRoll(board, previous, forward) {
  return Boolean(forward && board.dice && previous
    && (!previous.dice || previous.turn !== board.turn_player
      || board.dice.some((value, index) => value !== previous.dice[index])));
}

function boardAnimationOffset(dx, dy, matrix) {
  if (!matrix) return null;
  const determinant = matrix.a * matrix.d - matrix.b * matrix.c;
  if (!determinant) return null;
  return {
    x: (dx * matrix.d - dy * matrix.c) / determinant,
    y: (dy * matrix.a - dx * matrix.b) / determinant,
  };
}

function renderBoard(state) {
  const panel = $("board-panel");
  panel.hidden = !state.board;
  if (!state.board) {
    lastBoardState = null;
    lastBoardMoment = null;
    lastDiceState = null;
    return;
  }
  const board = state.board;
  panel.classList.toggle("board-no-turn-actions", state.mode !== "play");
  const moment = state.is_replay ? state.position : state.steps;
  const forward = lastBoardMoment !== null && lastBoardMoment.replay === Boolean(state.is_replay)
    && moment > lastBoardMoment.position;
  const adjacent = lastBoardMoment !== null && lastBoardMoment.replay === Boolean(state.is_replay)
    && Math.abs(moment - lastBoardMoment.position) === 1;
  lastBoardMoment = { replay: Boolean(state.is_replay), position: moment };
  const turnFocus = state.notebook_focus?.turn ?? null;
  const key = JSON.stringify([board, state.legal, state.to_move, state.human_player, state.is_over,
    state.limit_reached, state.waiting_for_turn, turnFocus]);
  if (key === lastBoardState) return;
  lastBoardState = key;
  const activeElement = document.activeElement;
  const restoreMoveFocus = panel.contains(activeElement) && activeElement?.hasAttribute("data-board-move");
  const actor = board.suspects.find((pawn) => pawn.seat === board.turn_player);
  const focusedPawn = turnFocus === null ? null : board.suspects.find((pawn) => pawn.seat === turnFocus);
  setText("board-turn-label", state.waiting_for_turn ? "Turn review" : "Current turn");
  setText("board-turn", focusedPawn ? `P${turnFocus + 1} · ${focusedPawn.name}` : "Board");
  setText("board-turn-marker", focusedPawn ? `P${turnFocus + 1}` : "–");
  $("board-turn-marker").style.backgroundColor = focusedPawn ? pawnStyles[focusedPawn.id].color : "";
  $("board-turn-marker").style.color = focusedPawn ? pawnStyles[focusedPawn.id].ink : "";
  setText("board-instruction", boardInstruction(state));
  setText("board-remaining", board.phase === "move"
    ? `${board.remaining} step${board.remaining === 1 ? "" : "s"} left`
    : board.dice ? "Movement complete" : "Not rolled");
  renderDice(board.dice, isDiceRoll(board, lastDiceState, forward));
  lastDiceState = { dice: board.dice ? [...board.dice] : null, turn: board.turn_player };
  $("board-roll-button").hidden = !state.legal.roll;
  $("board-passage-button").hidden = !state.legal.passage;

  const displayLayout = state.board_rules && !state.board_rules.secret_passages
    ? { ...board.layout, passages: [] } : board.layout;
  const layoutKey = JSON.stringify(displayLayout);
  const animatePawns = adjacent && layoutKey === lastBoardLayout
    && !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const previousPawns = new Map(animatePawns
    ? [...$("board-dynamic").querySelectorAll("[data-pawn-id]")].map((pawn) => {
      const bounds = pawn.getBoundingClientRect();
      return [pawn.dataset.pawnId, { x: bounds.x + bounds.width / 2, y: bounds.y + bounds.height / 2 }];
    }) : []);
  if (layoutKey !== lastBoardLayout) {
    buildBoardBase(displayLayout);
    lastBoardLayout = layoutKey;
  }
  const dynamic = $("board-dynamic");
  dynamic.replaceChildren();
  dynamic.append(svgElement("g", { id: "board-room-notes" }));
  for (const square of board.visited) {
    dynamic.append(svgElement("rect", {
      x: square.x, y: square.y, width: 1, height: 1, class: "board-visited",
      "aria-hidden": "true",
    }));
  }
  for (const door of board.layout.doors) {
    const room = door.room_square;
    const hall = door.hallway_square;
    const x = (room.x + hall.x + 1) / 2;
    const y = (room.y + hall.y + 1) / 2;
    const horizontal = room.x === hall.x;
    const blocked = board.suspects.some((pawn) => pawn.location.kind === "hallway"
      && pawn.location.x === hall.x && pawn.location.y === hall.y);
    dynamic.append(svgElement("line", {
      x1: x - (horizontal ? .3 : 0), x2: x + (horizontal ? .3 : 0),
      y1: y - (horizontal ? 0 : .3), y2: y + (horizontal ? 0 : .3),
      class: `board-door${blocked ? " blocked" : ""}`, "aria-hidden": "true",
    }));
  }
  for (const room of board.layout.rooms) {
    const bounds = roomBounds(room);
    const center = (bounds.minX + bounds.maxX + 1) / 2;
    const rectangular = room.squares.length
      === (bounds.maxX - bounds.minX + 1) * (bounds.maxY - bounds.minY + 1);
    const stem = rectangular ? [] : room.squares.filter((square) => square.y === bounds.maxY);
    const pawnCenter = rectangular ? center
      : (Math.min(...stem.map((square) => square.x)) + Math.max(...stem.map((square) => square.x)) + 1) / 2;
    const pawns = board.suspects.filter((pawn) =>
      pawn.location.kind === "room" && pawn.location.room_id === room.id);
    const baseY = rectangular ? bounds.minY + Math.max(1.7, (bounds.maxY - bounds.minY + 1) / 2 + .35)
      : bounds.maxY - .5;
    pawns.forEach((pawn, index) => appendPawn(
      dynamic, pawn, state, pawnCenter + (index % 3 - 1) * .75, baseY + Math.floor(index / 3) * .72,
      turnFocus !== null && pawn.seat === turnFocus, .34,
    ));
    const weapons = board.weapons.filter((weapon) => weapon.room_id === room.id);
    if (weapons.length) {
      dynamic.append(svgElement("text", {
        x: center, y: rectangular ? bounds.maxY + .78 : bounds.minY + 2.7,
        class: "board-room-contents", "aria-hidden": "true",
      }, `◆ ${weapons.length} weapon${weapons.length === 1 ? "" : "s"}`));
    }
  }
  for (const pawn of board.suspects) {
    if (pawn.location.kind === "hallway") {
      appendPawn(dynamic, pawn, state, pawn.location.x + .5, pawn.location.y + .5,
        turnFocus !== null && pawn.seat === turnFocus, .42);
    }
  }
  if (animatePawns) {
    const matrix = dynamic.getScreenCTM();
    for (const pawn of dynamic.querySelectorAll("[data-pawn-id]")) {
      const previous = previousPawns.get(pawn.dataset.pawnId);
      if (!previous) continue;
      const bounds = pawn.getBoundingClientRect();
      const dx = previous.x - (bounds.x + bounds.width / 2);
      const dy = previous.y - (bounds.y + bounds.height / 2);
      const offset = boardAnimationOffset(dx, dy, matrix);
      if (offset && (Math.abs(dx) > .1 || Math.abs(dy) > .1)) pawn.animate(
        [{ transform: `translate(${offset.x}px, ${offset.y}px)` }, { transform: "translate(0, 0)" }],
        { duration: 300, easing: "ease-out" }
      );
    }
  }
  for (const move of state.legal.moves) {
    const label = moveLabel(move, state);
    const encoded = JSON.stringify(move);
    let target = move;
    if (move.kind === "room") {
      const door = board.layout.doors.find((item) => item.room_id === move.room_id
        && actor?.location.kind === "hallway"
        && item.hallway_square.x === actor.location.x && item.hallway_square.y === actor.location.y);
      if (!door) continue;
      target = door.room_square;
    }
    const square = svgElement("rect", {
      x: target.x + .08, y: target.y + .08, width: .84, height: .84, rx: .12,
      class: "board-target", role: "button", tabindex: "0", "aria-label": label,
      "data-board-move": encoded,
    });
    square.append(svgElement("title", {}, label));
    dynamic.append(square);
  }
  const legend = $("board-legend");
  legend.replaceChildren();
  for (const pawn of board.suspects) {
    const item = document.createElement("span");
    item.className = "board-legend-item";
    const chip = document.createElement("span");
    chip.className = `pawn-chip${pawn.seat === null ? " pawn-chip-unassigned" : ""}`;
    chip.style.backgroundColor = pawnStyles[pawn.id].color;
    chip.style.color = pawnStyles[pawn.id].ink;
    chip.textContent = pawn.seat === null ? pawnStyles[pawn.id].label : `P${pawn.seat + 1}`;
    const label = document.createElement("span");
    const name = document.createElement("strong");
    name.textContent = pawn.name;
    label.append(name, document.createTextNode(
      ` · ${pawnController(pawn, state)} · ${boardLocation(pawn.location)}`
    ));
    item.append(chip, label);
    legend.append(item);
  }
  const roomList = $("board-room-list");
  roomList.replaceChildren();
  for (const room of board.layout.rooms) {
    const pawnNames = board.suspects.filter((pawn) =>
      pawn.location.kind === "room" && pawn.location.room_id === room.id).map((pawn) => pawn.name);
    const weaponNames = board.weapons.filter((weapon) => weapon.room_id === room.id).map((weapon) => weapon.name);
    const passageIndex = displayLayout.passages.findIndex((pair) => pair.includes(room.id));
    const passage = displayLayout.passages[passageIndex];
    const item = document.createElement("li");
    const title = document.createElement("strong");
    title.textContent = `${room.name}: `;
    const contents = [
      pawnNames.length ? pawnNames.join(", ") : "no suspects",
      weaponNames.length ? weaponNames.join(", ") : "no weapons",
      ...(passage ? [`passage ${String.fromCharCode(65 + passageIndex)} to ${cardName(passage.find((id) => id !== room.id))}`] : []),
    ];
    item.append(title, document.createTextNode(contents.join(" · ")));
    roomList.append(item);
  }
  if (restoreMoveFocus) {
    const next = dynamic.querySelector("[data-board-move]");
    if (next) next.focus({ preventScroll: true });
    else if (state.legal.suggest) {
      document.querySelector('[data-card-view="suspect"]').focus({ preventScroll: true });
    } else if (state.legal.end_turn) {
      $("turn-button").focus({ preventScroll: true });
    }
  }
}

function renderHand(state) {
  const container = $("hand-cards");
  container.replaceChildren();
  const notes = cardNoteContext(state);
  const viewLabels = {
    hand: "Cards in hand", suspect: "Suspect cards", weapon: "Weapon cards",
    room: "Room cards", all: "All cards",
  };
  container.setAttribute("aria-label", viewLabels[cardView]);
  const hand = new Set(state.hand);
  const allCards = [...cardsByName.values()];
  const visibleCards = allCards.filter((card) => {
    if (cardView === "hand") return hand.has(card.id);
    if (cardView === "all") return true;
    return card.type === cardView;
  });
  const canReveal = state.legal.reveals.length > 0;
  const canCompose = state.mode === "play"
    && state.to_move === state.human_player
    && (state.legal.suggest || state.legal.accuse);
  for (const card of visibleCards) {
    const revealable = state.legal.reveals.some((reveal) => reveal.id === card.id);
    const face = createCardFace(card, {
      button: true,
      disabled: canReveal ? !revealable : !canCompose,
      pressed: selectedCardIds[card.type] === card.id,
      notes,
    });
    face.addEventListener("click", () => selectCard(card.id));
    container.append(face);
  }
  if (!container.childElementCount) {
    const empty = document.createElement("span");
    empty.className = "muted";
    empty.textContent = cardView === "hand" ? "(empty hand)" : "No cards to show.";
    container.append(empty);
  }
  for (const button of $("card-view-tabs").querySelectorAll("[data-card-view]")) {
    button.setAttribute("aria-pressed", String(button.dataset.cardView === cardView));
  }
}

function cardNoteContext(state) {
  return {
    hand: new Set(state.hand),
    marks: new Map(notebookDisplayMatrix(state).map((card) => [card.id, card.marks])),
    player: state.selected_player,
    human: state.mode === "play" && !state.is_replay && state.selected_player === state.human_player,
    players: state.num_players,
  };
}

function positiveKnowledge(marks) {
  const holders = marks ? marks.flatMap((mark, holder) => mark === "+" ? [holder] : []) : [];
  return { holder: holders.length === 1 ? holders[0] : null, conflict: holders.length > 1 };
}

function updateKnowledgeIndicators(state) {
  const notes = cardNoteContext(state);
  const conflicts = notebookDisplayMatrix(state)
    .filter((card) => positiveKnowledge(card.marks).conflict).map((card) => card.name);
  const warning = conflicts.length
    ? `Conflicting + marks — check notebook: ${conflicts.join(", ")} · ` : "";
  setText("knowledge-conflicts", warning);
  $("game-meta").title = warning ? warning.slice(0, -3) : "";
  $("board-indicators-option").hidden = !state.board;
  if (!state.board) return;
  const layer = $("board-room-notes");
  if (!layer) return;
  layer.replaceChildren();
  if (!showBoardIndicators) return;
  for (const room of state.board.layout.rooms) {
    const knowledge = positiveKnowledge(notes.marks.get(room.id));
    const badges = [];
    if (notes.hand.has(room.id)) badges.push({
      text: "Hand", kind: "hand", description: notes.human ? "In your hand" : `In Player ${notes.player + 1}'s hand`,
    });
    if (knowledge.holder !== null) {
      const envelope = knowledge.holder === notes.players;
      badges.push({
        text: envelope ? "E+" : `P${knowledge.holder + 1}+`,
        kind: envelope ? "envelope" : knowledge.holder === notes.player ? "own" : "player",
        description: envelope ? "Envelope: held" : `Player ${knowledge.holder + 1}: held`,
      });
    }
    if (!badges.length) continue;
    const bounds = roomBounds(room);
    const center = (bounds.minX + bounds.maxX + 1) / 2;
    const group = svgElement("g", {
      class: "board-room-notes", role: "img", "aria-label": `${room.name}: ${badges.map((badge) => badge.description).join(", ")}`,
    });
    group.append(svgElement("title", {}, `${room.name}: ${badges.map((badge) => badge.description).join(", ")}`));
    badges.forEach((badge, index) => {
      const x = center + (index - (badges.length - 1) / 2) * 1.3;
      const y = bounds.minY + 1.3;
      const item = svgElement("g", { class: `board-note-${badge.kind}` });
      item.append(svgElement("rect", { x: x - .6, y, width: 1.2, height: .58, rx: .12 }));
      item.append(svgElement("text", { x, y: y + .42 }, badge.text));
      group.append(item);
    });
    layer.append(group);
  }
}

function renderCardNotes(face, card, notes) {
  const knowledge = positiveKnowledge(notes.marks.get(card.id));
  const inHand = showCardIndicators && notes.hand.has(card.id);
  const handDescription = notes.human ? "In your hand" : `In Player ${notes.player + 1}'s hand`;
  const annotations = document.createElement("div");
  annotations.className = "card-annotations";
  annotations.setAttribute("aria-hidden", "true");
  if (inHand) {
    const badge = document.createElement("span");
    badge.className = "card-hand-badge";
    badge.textContent = notes.human ? "In hand" : `P${notes.player + 1} hand`;
    annotations.append(badge);
  }
  let description = "";
  if (showCardIndicators && knowledge.holder !== null) {
    const holder = knowledge.holder;
    const envelope = holder === notes.players;
    const owner = envelope ? "Envelope" : `Player ${holder + 1}`;
    description = `${owner}: held`;
    const badge = document.createElement("span");
    badge.className = `card-note-mark ${envelope ? "card-note-envelope"
      : holder === notes.player ? "card-note-own" : "card-note-player"}`;
    badge.textContent = `${envelope ? "E" : `P${holder + 1}`}+`;
    badge.title = description;
    annotations.append(badge);
  }
  const previous = face.querySelector(".card-annotations");
  if (previous) previous.remove();
  face.querySelector(".card-topline").prepend(annotations);
  face.dataset.cardNoteId = String(card.id);
  const label = [`${card.name}, ${card.type}`, ...(inHand ? [handDescription] : []),
    ...(description ? [`Notebook: ${description}`] : [])].join(". ");
  face.setAttribute("aria-label", label);
  face.title = label;
}

function updateCardNotes(state, cardId = null) {
  const notes = cardNoteContext(state);
  const selector = cardId === null ? "#cards-panel [data-card-note-id]"
    : `#cards-panel [data-card-note-id="${cardId}"]`;
  for (const face of document.querySelectorAll(selector)) {
    renderCardNotes(face, cardsById.get(Number(face.dataset.cardNoteId)), notes);
  }
  updateKnowledgeIndicators(state);
}

function createCardFace(card, { button = false, mini = false, disabled = false, pressed = false, notes } = {}) {
  const face = document.createElement(button ? "button" : "article");
  if (button) {
    face.type = "button";
    face.disabled = disabled;
    face.dataset.cardId = String(card.id);
    face.setAttribute("aria-pressed", String(pressed));
  }
  face.className = `playing-card ${card.type}${mini ? " mini-card" : ""}`;
  face.setAttribute("aria-label", `${card.name}, ${card.type}`);

  const header = document.createElement("div");
  header.className = "card-topline";
  const category = document.createElement("span");
  category.className = "card-category";
  category.textContent = card.type;
  header.append(category);

  const art = document.createElement("div");
  art.className = "card-art";
  art.append(cardIllustration(card.id));

  const name = document.createElement("h4");
  name.className = "playing-card-name";
  name.textContent = card.name;
  face.append(header, art, name);
  if (notes) renderCardNotes(face, card, notes);
  return face;
}

function selectCard(cardId) {
  if (!currentState) return;
  if (currentState.legal.reveals.some((reveal) => reveal.id === cardId)) {
    submitAction({ action: "reveal", card_id: cardId });
    return;
  }
  const card = cardsById.get(cardId);
  const canCompose = currentState.mode === "play"
    && currentState.to_move === currentState.human_player
    && (currentState.legal.suggest || currentState.legal.accuse);
  if (!card || !canCompose) return;
  const restoreFocus = $("hand-cards").contains(document.activeElement);
  selectedCardIds[card.type] = card.id;
  renderHand(currentState);
  renderCardInteraction(currentState);
  if (restoreFocus) $("hand-cards").querySelector(`[data-card-id="${card.id}"]`)?.focus({ preventScroll: true });
}

function selectedCombination() {
  return {
    suspect_id: selectedCardIds.suspect,
    weapon_id: selectedCardIds.weapon,
    room_id: selectedCardIds.room,
  };
}

function clearSelectedCards() {
  selectedCardIds.suspect = null;
  selectedCardIds.weapon = null;
  selectedCardIds.room = null;
}

function clearSuggestionFlights() {
  cardActivityReadUntil = 0;
  for (const flight of suggestionFlights) {
    flight.animation.cancel();
    flight.node.remove();
  }
  suggestionFlights = [];
}

function cardActivity(state) {
  const activity = state.activity;
  const latest = state.events[0];
  if (latest?.kind === "pass" && activity
      && ["suggest", "refute", "reveal"].includes(activity.kind)) {
    return {
      kind: "pass", actor: latest.actor, cards: activity.cards,
      suggestion_actor: activity.kind === "suggest" ? activity.actor : activity.suggestion_actor,
    };
  }
  return activity;
}

function currentSuggestionResponses(state) {
  const events = state.events || [];
  const suggestionIndex = events.findIndex((event) => event.kind === "suggest" || event.kind === "accuse");
  const suggestion = events[suggestionIndex];
  const responses = suggestion?.kind === "suggest" ? events.slice(0, suggestionIndex) : [];
  const ends = responses.filter((event) => event.kind === "end_turn");
  const current = !ends.length || (state.waiting_for_turn && ends.length === 1
    && ends[0].actor === suggestion?.actor);
  return current ? responses : [];
}

function renderActivityPasses(state) {
  const passed = currentSuggestionResponses(state).filter((event) => event.kind === "pass").reverse();
  const summary = passed.length
    ? `Passed: ${passed.map((event) => `P${event.actor + 1}`).join(" · ")}` : "";
  setText("activity-passes", summary);
  $("activity-passes").title = summary;
}

function replayActivityScale(state) {
  return state?.is_replay && replayPlaying
    ? Math.min(1, Number($("replay-speed").value) / 500)
    : 1;
}

function cardAnimationKind(state) {
  const activity = cardActivity(state);
  const eventKind = activity?.kind === "reveal" ? "show" : activity?.kind;
  const event = state.events.find((item) => item.kind === eventKind);
  const eventNumber = activity?.kind === "pass" ? event?.number : state.activity_event_number ?? event?.number;
  const key = activity ? JSON.stringify([eventNumber, activity]) : null;
  const perspective = `${Boolean(state.is_replay)}:${state.selected_player}`;
  const previous = lastCardAnimation;
  lastCardAnimation = { key, perspective, step: state.steps };
  if (key !== previous?.key || perspective !== previous?.perspective || state.steps < previous?.step) {
    clearSuggestionFlights();
  }
  if (!activity || !["suggest", "reveal", "pass"].includes(activity.kind)) return null;
  if (previous && (previous.key === key || previous.perspective !== perspective
    || state.steps <= previous.step)) return null;
  cardActivityReadUntil = performance.now()
    + (activity.kind === "pass" ? cardPassReadTime : cardActivityReadTime) * replayActivityScale(state);
  if (activity.kind === "pass" || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return null;
  return activity.kind;
}

function animateSuggestionFromBoard(state, container) {
  const actor = state.board?.suspects?.find((pawn) => pawn.seat === state.activity.actor);
  if (!actor) return;
  const pawn = $("board-dynamic").querySelector(`[data-pawn-id="${actor.id}"]`);
  if (!pawn || !pawn.getClientRects().length) return;
  const origin = pawn.getBoundingClientRect();
  const scale = replayActivityScale(state);
  for (const [index, card] of [...container.children].entries()) {
    if (!card.getClientRects().length) continue;
    const target = card.getBoundingClientRect();
    if (!target.width || !target.height) continue;
    const clone = card.cloneNode(true);
    clone.classList.add("suggestion-flight");
    clone.setAttribute("aria-hidden", "true");
    Object.assign(clone.style, {
      left: `${target.left}px`, top: `${target.top}px`,
      width: `${target.width}px`, height: `${target.height}px`, minWidth: "0", minHeight: "0",
    });
    document.body.append(clone);
    const dx = origin.left + origin.width / 2 - (target.left + target.width / 2);
    const dy = origin.top + origin.height / 2 - (target.top + target.height / 2);
    const duration = 850 * scale;
    const delay = index * 100 * scale;
    const animation = clone.animate([
      { transform: `translate(${dx}px, ${dy}px) scale(.25)`, opacity: .35 },
      { transform: "translate(0, 0) scale(1)", opacity: 1 },
    ], { duration, delay, easing: "ease-in-out", fill: "backwards" });
    card.animate([
      { opacity: 0, offset: 0 }, { opacity: 0, offset: .8 }, { opacity: 1, offset: 1 },
    ], { duration, delay, fill: "backwards" });
    const flight = { node: clone, animation };
    suggestionFlights.push(flight);
    animation.finished.then(() => {
      clone.remove();
      const active = suggestionFlights.includes(flight);
      suggestionFlights = suggestionFlights.filter((item) => item !== flight);
      if (active && !suggestionFlights.length) {
        cardActivityReadUntil = performance.now() + cardActivityReadTime * scale;
      }
    }, () => {
      clone.remove();
      suggestionFlights = suggestionFlights.filter((item) => item !== flight);
    });
  }
}

function renderCardInteraction(state) {
  const legal = state.legal;
  const notes = cardNoteContext(state);
  const activity = cardActivity(state);
  renderActivityPasses(state);
  const animationKind = cardAnimationKind(state);
  const animateReveal = animationKind === "reveal";
  const focusCards = $("focus-cards");
  const selectedCards = $("selected-cards");
  focusCards.replaceChildren();
  selectedCards.replaceChildren();
  selectedCards.classList.remove("reveal-selection");
  $("activity-meta").hidden = true;
  const humanTurn = state.mode === "play"
    && state.to_move === state.human_player
    && !state.is_over
    && !state.limit_reached;

  if (legal.reveals.length) {
    $("card-interaction-title").textContent = "Respond to suggestion";
    const actor = activity?.suggestion_actor ?? activity?.actor;
    renderActivityMeta(activity?.kind === "pass" ? activity
      : actor === undefined ? null : { kind: "suggest", actor });
    renderMiniCards(focusCards, activity?.cards || [], notes);
    if (animationKind === "suggest") animateSuggestionFromBoard(state, focusCards);
  } else if (humanTurn && (legal.suggest || legal.accuse)) {
    const revealIsActive = activity?.kind === "reveal"
      && state.events.find((event) => event.kind === "show" || event.kind === "end_turn")?.kind === "show";
    const passIsActive = activity?.kind === "pass";
    const responseIsActive = revealIsActive || passIsActive;
    if (responseIsActive) {
      $("card-interaction-title").textContent = revealIsActive ? "Latest reveal" : "Latest pass";
      renderActivityMeta(activity);
      renderMiniCards(focusCards, passIsActive ? activity.cards : [activity.card_id],
        notes, activity.card_id, animateReveal);
    } else {
      $("card-interaction-title").textContent = legal.suggest
        ? "Build a suggestion"
        : "Build an accusation";
      if (activity?.kind === "refute") {
        renderActivityMeta(activity);
      }
    }
    for (const type of ["suspect", "weapon", "room"]) {
      const card = cardsById.get(selectedCardIds[type]);
      if (card) {
        if (responseIsActive) {
          const chip = document.createElement("span");
          chip.className = `card-reference ${type}`;
          chip.textContent = card.name;
          selectedCards.append(chip);
        } else {
          selectedCards.append(createCardFace(card, { mini: true, notes }));
        }
      } else if (!responseIsActive) {
        const slot = document.createElement("div");
        slot.className = `selection-slot ${type}`;
        slot.textContent = type[0].toUpperCase() + type.slice(1);
        selectedCards.append(slot);
      }
    }
    if (responseIsActive) selectedCards.classList.add("reveal-selection");
    const hasCombination = Object.values(selectedCardIds).every((id) => id !== null);
    const matchesRoom = legal.suggest_room === null || selectedCardIds.room === legal.suggest_room;
    $("card-suggest-button").hidden = !legal.suggest || (responseIsActive && !hasCombination);
    $("card-accuse-button").hidden = !legal.accuse || (responseIsActive && !hasCombination);
    $("card-suggest-button").disabled = !hasCombination || !matchesRoom;
    $("card-accuse-button").disabled = !hasCombination;
    $("use-room-button").hidden = !legal.suggest || legal.suggest_room === null || matchesRoom;
    $("clear-cards-button").hidden = !Object.values(selectedCardIds).some((id) => id !== null);
    return;
  } else {
    $("card-interaction-title").textContent = activity?.kind === "reveal"
      ? "Latest reveal" : activity?.kind === "pass" ? "Latest pass"
      : "Table activity";
    renderActivityMeta(activity);
    if (activity?.kind === "reveal") {
      renderMiniCards(focusCards, [activity.card_id], notes, activity.card_id, animateReveal);
    } else {
      renderMiniCards(focusCards, activity?.cards || [], notes);
      if (animationKind === "suggest") animateSuggestionFromBoard(state, focusCards);
    }
  }

  $("card-suggest-button").hidden = true;
  $("card-accuse-button").hidden = true;
  $("card-suggest-button").disabled = true;
  $("card-accuse-button").disabled = true;
  $("use-room-button").hidden = true;
  $("clear-cards-button").hidden = true;
}

function renderActivityMeta(activity) {
  const labels = {
    suggest: "Suggestion",
    pass: "Pass",
    accuse: "Accusation",
    refute: "Refutation",
    reveal: "Reveal",
  };
  if (!activity || !labels[activity.kind]) return;
  $("activity-kind").textContent = labels[activity.kind];
  let context = "";
  if (activity.kind === "pass" || activity.kind === "refute") {
    context = ` · suggestion P${activity.suggestion_actor + 1}`;
  } else if (activity.kind === "reveal") {
    context = activity.public ? " · public" : ` · to P${activity.recipient + 1}`;
  }
  const player = $("activity-player");
  player.textContent = `Player ${activity.actor + 1}${context}`;
  player.title = player.textContent;
  $("activity-meta").hidden = false;
}

function renderMiniCards(container, cardIds, notes, shownCardId = null, animateReveal = false) {
  for (const id of cardIds) {
    const card = cardsById.get(id);
    if (!card) continue;
    const face = createCardFace(card, { mini: true, notes });
    if (id === shownCardId) {
      face.classList.add("shown-card");
      if (animateReveal) {
        face.classList.add("reveal-enter");
        const scale = replayActivityScale(currentState);
        if (scale < 1) face.style.animationDuration = `${650 * scale}ms`;
      }
    }
    container.append(face);
  }
}

function cardIllustration(cardId) {
  const namespace = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(namespace, "svg");
  svg.setAttribute("viewBox", "0 0 64 64");
  svg.setAttribute("aria-hidden", "true");
  svg.classList.add("card-illustration");
  const icons = {
    0: [
      ["path", { d: "M15 22h34l-5-9H21z" }],
      ["line", { x1: "11", y1: "23", x2: "53", y2: "23" }],
      ["circle", { cx: "32", cy: "34", r: "8" }],
      ["path", { d: "M16 57c1-10 7-15 16-15s15 5 16 15" }],
    ],
    1: [
      ["circle", { cx: "32", cy: "27", r: "12" }],
      ["path", { d: "M20 31c4-5 8-5 12 0 4-5 8-5 12 0-3 7-7 7-12 3-5 4-9 4-12-3z", fill: "currentColor" }],
      ["path", { d: "M20 56l5-12h14l5 12M28 45l4 7 4-7" }],
    ],
    2: [
      ["path", { d: "M17 25c0-12 7-18 15-18s15 6 15 18M13 25h38" }],
      ["circle", { cx: "32", cy: "31", r: "8" }],
      ["path", { d: "M18 57l4-13h20l4 13M25 44l7 8 7-8" }],
    ],
    3: [
      ["circle", { cx: "32", cy: "23", r: "9" }],
      ["path", { d: "M17 57c1-12 6-18 15-18s14 6 15 18M24 42l8 7 8-7" }],
      ["line", { x1: "32", y1: "11", x2: "32", y2: "21" }],
      ["line", { x1: "28", y1: "16", x2: "36", y2: "16" }],
    ],
    4: [
      ["circle", { cx: "28", cy: "34", r: "8" }],
      ["path", { d: "M36 29c9-11 13-9 10-19 10 5 9 14 2 19M37 33c11-4 15 0 17 7-8-2-12 0-18 2M19 56c1-8 4-12 9-14" }],
      ["circle", { cx: "31", cy: "33", r: "1.5", fill: "currentColor" }],
    ],
    5: [
      ["circle", { cx: "32", cy: "34", r: "10" }],
      ["path", { d: "M18 23l14-12 14 12-14 5zM22 22h20M25 55c1-6 3-10 7-10s6 4 7 10" }],
      ["circle", { cx: "28", cy: "34", r: "3" }],
      ["circle", { cx: "37", cy: "34", r: "3" }],
      ["line", { x1: "31", y1: "34", x2: "34", y2: "34" }],
    ],
    6: [
      ["path", { d: "M32 8c-7 8-6 13 0 16 6-3 7-8 0-16z", fill: "currentColor" }],
      ["line", { x1: "32", y1: "25", x2: "32", y2: "49" }],
      ["path", { d: "M23 31h18M27 50h10M21 57h22l-3-7H24z" }],
    ],
    7: [
      ["path", { d: "M32 7L42 34 32 44 22 34z" }],
      ["line", { x1: "32", y1: "44", x2: "32", y2: "58" }],
      ["line", { x1: "23", y1: "48", x2: "41", y2: "48" }],
      ["line", { x1: "28", y1: "55", x2: "36", y2: "55" }],
    ],
    8: [
      ["path", { d: "M16 12h16v13H20v13h25v14H17" }],
      ["line", { x1: "13", y1: "12", x2: "20", y2: "12" }],
      ["line", { x1: "14", y1: "52", x2: "21", y2: "52" }],
    ],
    9: [
      ["path", { d: "M12 25h27l8 7-8 7H27l-5 9h-8l4-11h-6z" }],
      ["line", { x1: "39", y1: "25", x2: "39", y2: "39" }],
      ["circle", { cx: "31", cy: "32", r: "4" }],
    ],
    10: [
      ["path", { d: "M45 17c-8-8-20-7-27 0s-7 18 0 25 18 7 25 0 7-18 0-25-18-7-25 0-5 12 0 16 12 4 16 0" }],
      ["path", { d: "M34 33l12 12 8 8" }],
    ],
    11: [
      ["path", { d: "M17 13a13 13 0 0 0 15 17l17 17-8 8-17-17a13 13 0 0 0-17-15l8 8-7 7-8-8a13 13 0 0 0 17-17z" }],
      ["line", { x1: "41", y1: "45", x2: "47", y2: "39" }],
    ],
    12: [
      ["path", { d: "M15 28h34l-4 23H19zM12 28h40" }],
      ["path", { d: "M22 20h20M26 15h12" }],
      ["line", { x1: "24", y1: "51", x2: "21", y2: "57" }],
      ["line", { x1: "40", y1: "51", x2: "43", y2: "57" }],
      ["path", { d: "M27 8c-4 4 4 4 0 8M37 8c-4 4 4 4 0 8" }],
    ],
    13: [
      ["line", { x1: "32", y1: "8", x2: "32", y2: "20" }],
      ["path", { d: "M14 20h36L32 34zM18 20l5 14M46 20l-5 14M23 34h18" }],
      ["path", { d: "M28 35h8v8h-8zM16 43h8v8h-8zM40 43h8v8h-8z" }],
    ],
    14: [
      ["path", { d: "M32 52V15M32 32C18 32 14 23 14 16c12 0 18 6 18 16zM32 40c14 0 18-9 18-16-12 0-18 6-18 16z" }],
      ["path", { d: "M20 52h24l-3 7H23z" }],
      ["line", { x1: "32", y1: "20", x2: "32", y2: "50" }],
    ],
    15: [
      ["circle", { cx: "34", cy: "33", r: "18" }],
      ["circle", { cx: "34", cy: "33", r: "11" }],
      ["line", { x1: "12", y1: "17", x2: "12", y2: "49" }],
      ["line", { x1: "8", y1: "17", x2: "8", y2: "27" }],
      ["line", { x1: "16", y1: "17", x2: "16", y2: "27" }],
      ["line", { x1: "55", y1: "17", x2: "55", y2: "49" }],
    ],
    16: [
      ["path", { d: "M20 14l12-6 12 6v10H20z" }],
      ["circle", { cx: "20", cy: "34", r: "8" }],
      ["circle", { cx: "43", cy: "34", r: "8" }],
      ["circle", { cx: "32", cy: "51", r: "8" }],
      ["path", { d: "M18 34h4M41 34h4M30 51h4" }],
    ],
    17: [
      ["path", { d: "M11 14h18c3 0 5 2 5 5v34H16c-3 0-5-2-5-5zM53 14H35c-3 0-5 2-5 5v34h18c3 0 5-2 5-5z" }],
      ["line", { x1: "17", y1: "25", x2: "27", y2: "25" }],
      ["line", { x1: "39", y1: "25", x2: "49", y2: "25" }],
      ["line", { x1: "17", y1: "32", x2: "27", y2: "32" }],
      ["line", { x1: "39", y1: "32", x2: "49", y2: "32" }],
    ],
    18: [
      ["path", { d: "M14 35v-8c0-5 4-8 9-8h18c5 0 9 3 9 8v8M10 35h44v15H10z" }],
      ["path", { d: "M14 50v7M50 50v7M17 38h30" }],
    ],
    19: [
      ["path", { d: "M10 56V19h10v37M44 56V19h10v37M7 56h50M8 19h48L32 8z" }],
      ["path", { d: "M24 56V39c0-5 3-8 8-8s8 3 8 8v17" }],
    ],
    20: [
      ["path", { d: "M13 53h38M20 53V43h24v10M25 43V31h14v12" }],
      ["path", { d: "M32 31V17M25 17h14l-2-8h-10zM27 58h10" }],
      ["line", { x1: "46", y1: "21", x2: "52", y2: "15" }],
    ],
  };
  const shapes = icons[cardId];
  if (!shapes) throw new RangeError(`No card illustration is defined for card ${cardId}.`);
  for (const [tag, attributes] of shapes) {
    const shape = document.createElementNS(namespace, tag);
    for (const [attribute, value] of Object.entries(attributes)) {
      shape.setAttribute(attribute, value);
    }
    svg.append(shape);
  }
  return svg;
}

function notebookDisplayMatrix(state) {
  if (!pendingNotebookEdits.length || state.notebook_mode !== "manual" || state.is_replay) return state.matrix;
  const pending = new Map();
  for (const edit of pendingNotebookEdits) pending.set(`${edit.cardId}:${edit.holder}`, edit.mark);
  return state.matrix.map((card) => ({
    ...card,
    marks: card.marks.map((mark, holder) => pending.get(`${card.id}:${holder}`) ?? mark),
  }));
}

function notebookResponseRoles(state) {
  const roles = Array(state.num_players).fill(null);
  if (state.notebook_focus?.kind !== "suggest") return roles;
  for (const event of currentSuggestionResponses(state).reverse()) {
    if (Number.isInteger(event.actor) && event.actor >= 0 && event.actor < state.num_players) {
      if (event.kind === "pass") roles[event.actor] = "pass";
      else if (event.kind === "refute") roles[event.actor] = "refute";
    }
  }
  return roles;
}

function notebookColumnRoles(holder, focus, responses) {
  const roles = [];
  if (holder === focus.turn) roles.push(["notebook-turn", "turn owner"]);
  if (holder === focus.actor) roles.push(["notebook-actor", "acting now"]);
  if (responses[holder] === "pass") roles.push(["notebook-pass", "passed"]);
  if (responses[holder] === "refute") roles.push(["notebook-refute", "refuted"]);
  return roles;
}

function updateNotebookMark(button, card, holder, mark, state, draft, responses) {
  const cell = button.parentElement;
  cell.classList.remove("mark-held", "mark-not-held", "mark-unknown");
  cell.classList.add(mark === "+" ? "mark-held" : mark === "-" ? "mark-not-held" : "mark-unknown");
  const focus = state.notebook_focus || { cards: [] };
  const roles = notebookColumnRoles(holder, focus, responses).map(([, label]) => label);
  const cardContext = focus.cards.includes(card.id)
    ? `; ${focus.kind === "accuse" ? "current accusation" : "current suggestion"}` : "";
  const shown = focus.shown?.holder === holder && focus.shown?.card === card.id;
  const context = (roles.length ? `; ${roles.join(", ")}` : "")
    + cardContext + (shown ? "; visibly shown" : "");
  const meaning = mark === "+" ? "held" : mark === "-" ? "not held" : "unknown";
  const owner = holder === state.num_players ? "Envelope" : `Player ${holder + 1}`;
  const selected = draft?.holder === holder && draft.cards[card.type] === card.id;
  cell.classList.toggle("clause-draft-selected", Boolean(selected));
  const action = draft ? `${selected ? "Selected" : "Not selected"} for clause. Activate to select.`
    : "Activate to change.";
  const label = `${card.name}, ${owner}: ${meaning}${context}. ${action}`;
  button.textContent = mark;
  button.setAttribute("aria-label", label);
  if (draft) button.setAttribute("aria-pressed", String(Boolean(selected)));
  else button.removeAttribute("aria-pressed");
  button.title = label;
}

function renderNotebook(state) {
  const notebook = $("notebook");
  const focus = state.notebook_focus || { cards: [] };
  const responses = notebookResponseRoles(state);
  const focusCards = new Set(focus.cards);
  const matrix = notebookDisplayMatrix(state);
  updateClauseEntryControls(state);
  const fingerprint = JSON.stringify([
    state.notebook_mode, state.num_players, state.hand_sizes, matrix, state.notebook_clauses,
    state.notebook_focus, responses, selectedClause, clauseDraft,
  ]);
  if (fingerprint === lastNotebookFingerprint) return;
  const structure = JSON.stringify([
    state.notebook_mode, state.num_players, state.hand_sizes,
    matrix.map(({ marks, ...card }) => card), state.notebook_clauses,
    state.notebook_focus, responses, selectedClause, Boolean(clauseDraft),
  ]);
  const marks = matrix.map((card) => card.marks.slice());
  const draft = clauseDraft ? { holder: clauseDraft.holder, cards: { ...clauseDraft.cards } } : null;
  if (structure === lastNotebookStructureFingerprint && lastNotebookMarks
      && state.notebook_mode === "manual") {
    const changes = [];
    let canUpdate = true;
    for (const [index, card] of matrix.entries()) {
      for (const [holder, mark] of card.marks.entries()) {
        const selected = draft?.holder === holder && draft.cards[card.type] === card.id;
        const wasSelected = lastNotebookDraft?.holder === holder
          && lastNotebookDraft.cards[card.type] === card.id;
        if (mark === lastNotebookMarks[index][holder] && Boolean(selected) === Boolean(wasSelected)) continue;
        const button = notebook.querySelector(
          `[data-notebook-card="${card.id}"][data-notebook-holder="${holder}"]`
        );
        if (!button || (!card.editable[holder] && !draft)) {
          canUpdate = false;
          break;
        }
        changes.push([button, card, holder, mark]);
      }
      if (!canUpdate) break;
    }
    if (canUpdate) {
      for (const [button, card, holder, mark] of changes) {
        updateNotebookMark(button, card, holder, mark, state, draft, responses);
      }
      lastNotebookFingerprint = fingerprint;
      lastNotebookMarks = marks;
      lastNotebookDraft = draft;
      return;
    }
  }
  lastNotebookFingerprint = fingerprint;
  lastNotebookStructureFingerprint = structure;
  lastNotebookMarks = marks;
  lastNotebookDraft = draft;
  const focused = document.activeElement.closest("[data-notebook-card]");
  const focusCard = focused?.dataset.notebookCard;
  const focusHolder = focused?.dataset.notebookHolder;
  notebook.classList.toggle("manual-notebook", state.notebook_mode === "manual");
  notebook.replaceChildren();
  const table = document.createElement("table");
  table.className = "category-table notebook-table";
  const head = document.createElement("thead");
  const heading = document.createElement("tr");
  const cardHeading = document.createElement("th");
  cardHeading.textContent = "Card";
  cardHeading.scope = "col";
  heading.append(cardHeading);
  for (let seat = 0; seat < state.num_players; seat++) {
    const th = document.createElement("th");
    th.scope = "col";
    th.dataset.notebookSeat = String(seat);
    th.textContent = `P${seat + 1} (${state.hand_sizes[seat]})`;
    const columnRoles = notebookColumnRoles(seat, focus, responses);
    for (const [className] of columnRoles) th.classList.add(className);
    const roles = columnRoles.map(([, label]) => label);
    th.title = `Player ${seat + 1}: ${state.hand_sizes[seat]} cards`
      + (roles.length ? `; ${roles.join(", ")}` : "");
    th.setAttribute("aria-label", th.title);
    heading.append(th);
  }
  const envelope = document.createElement("th");
  envelope.className = "matrix-envelope";
  envelope.scope = "col";
  envelope.setAttribute("aria-label", "Envelope");
  envelope.title = "Envelope";
  envelope.textContent = "E";
  heading.append(envelope);
  head.append(heading);
  table.append(head);
  for (const type of ["suspect", "weapon", "room"]) {
    const body = document.createElement("tbody");
    body.className = type;
    const category = document.createElement("tr");
    const title = document.createElement("th");
    title.scope = "rowgroup";
    title.colSpan = state.num_players + 2;
    title.className = "category-heading";
    title.textContent = type;
    category.append(title);
    body.append(category);
    for (const card of matrix.filter((item) => item.type === type)) {
      const row = document.createElement("tr");
      row.dataset.cardId = String(card.id);
      const cardInFocus = focusCards.has(card.id);
      if (cardInFocus) row.classList.add("notebook-card-focus");
      const name = document.createElement("td");
      name.className = "card-name";
      const cardContext = cardInFocus
        ? `; ${focus.kind === "accuse" ? "current accusation" : "current suggestion"}` : "";
      name.setAttribute("aria-label", `${card.name}${cardContext}`);
      const label = document.createElement("span");
      label.className = "matrix-card-label";
      const icon = document.createElement("span");
      icon.className = "matrix-card-icon";
      icon.append(cardIllustration(card.id));
      const cardName = document.createElement("span");
      cardName.textContent = card.name;
      label.append(icon, cardName);
      name.append(label);
      row.append(name);
      for (const [holder, mark] of card.marks.entries()) {
        const cell = document.createElement("td");
        cell.className = mark === "+" ? "mark-held" : mark === "-" ? "mark-not-held" : "mark-unknown";
        const columnRoles = notebookColumnRoles(holder, focus, responses);
        for (const [className] of columnRoles) cell.classList.add(className);
        const roles = columnRoles.map(([, label]) => label);
        const shown = focus.shown?.holder === holder && focus.shown?.card === card.id;
        if (shown) cell.classList.add("notebook-shown");
        const cellContext = (roles.length ? `; ${roles.join(", ")}` : "")
          + cardContext + (shown ? "; visibly shown" : "");
        const links = (state.notebook_clauses || []).filter((clause) =>
          clause.holder === holder && clause.active_cards.includes(card.id));
        if (links.some((clause) => clause.id === selectedClause)) cell.classList.add("clause-linked-selected");
        const draftSelected = clauseDraft?.holder === holder && clauseDraft.cards[type] === card.id;
        if (draftSelected) cell.classList.add("clause-draft-selected");
        const meaning = mark === "+" ? "held" : mark === "-" ? "not held" : "unknown";
        const owner = holder === state.num_players ? "Envelope" : `Player ${holder + 1}`;
        if (card.editable[holder] || clauseDraft) {
          const button = document.createElement("button");
          button.type = "button";
          button.className = card.editable[holder] ? "notebook-mark" : "notebook-mark notebook-fixed-mark";
          button.dataset.notebookCard = String(card.id);
          button.dataset.notebookHolder = String(holder);
          const action = clauseDraft ? `${draftSelected ? "Selected" : "Not selected"} for clause. Activate to select.`
            : "Activate to change.";
          button.setAttribute("aria-label", `${card.name}, ${owner}: ${meaning}${cellContext}. ${action}`);
          if (clauseDraft) button.setAttribute("aria-pressed", String(draftSelected));
          button.title = `${card.name}, ${owner}: ${meaning}${cellContext}. ${action}`;
          button.textContent = mark;
          cell.append(button);
        } else {
          const value = document.createElement("span");
          value.textContent = mark;
          value.setAttribute("aria-label", `${card.name}, ${owner}: ${meaning}${cellContext}`);
          cell.append(value);
        }
        if (links.length && !clauseDraft) {
          const indicators = document.createElement("span");
          indicators.className = "clause-indicators";
          for (const clause of links) {
            const indicator = document.createElement("button");
            indicator.type = "button";
            indicator.className = "clause-indicator";
            indicator.dataset.clauseCard = String(card.id);
            indicator.dataset.clauseId = String(clause.id);
            indicator.style.setProperty("--clause-color", clauseColor(clause, state.notebook_clauses));
            const description = `View clause ${clause.id} for ${card.name}, ${owner}`;
            indicator.setAttribute("aria-label", description);
            indicator.setAttribute("aria-pressed", String(clause.id === selectedClause));
            indicator.title = description;
            indicators.append(indicator);
          }
          cell.append(indicators);
        }
        row.append(cell);
      }
      body.append(row);
    }
    table.append(body);
  }
  notebook.append(table);
  if (focusCard !== undefined) {
    notebook.querySelector(`[data-notebook-card="${focusCard}"][data-notebook-holder="${focusHolder}"]`)
      ?.focus({ preventScroll: true });
  }
}

function changeNotebook(cardId, holder) {
  if (!currentState || currentState.is_replay) return;
  const card = currentState.matrix.find((item) => item.id === cardId);
  if (!card || !card.editable[holder]) return;
  const previous = [...pendingNotebookEdits].reverse().find(
    (edit) => edit.cardId === cardId && edit.holder === holder
  );
  const mark = { "?": "+", "+": "-", "-": "?" }[previous?.mark ?? card.marks[holder]];
  const edit = { cardId, holder, mark };
  pendingNotebookEdits.push(edit);
  renderNotebook(currentState);
  updateCardNotes(currentState, cardId);
  const generation = notebookGeneration;
  notebookQueue = notebookQueue.then(async () => {
    if (generation !== notebookGeneration || !currentState) return;
    const result = await requestJson("/api/notebook", {
      method: "PUT", body: { card_id: cardId, holder, mark },
    });
    if (generation !== notebookGeneration || !currentState) return;
    pendingNotebookEdits = pendingNotebookEdits.filter((pending) => pending !== edit);
    if (result.notebook_revision >= currentState.notebook_revision) {
      currentState.matrix = result.matrix;
      currentState.notebook_clauses = result.notebook_clauses;
      currentState.notebook_revision = result.notebook_revision;
      renderNotebook(currentState);
      updateCardNotes(currentState, cardId);
      renderClauses(currentState);
      lastRenderedState = JSON.stringify(currentState);
    } else {
      renderNotebook(currentState);
      updateCardNotes(currentState, cardId);
    }
    if (lastError.startsWith("Could not save notebook:")) showError("");
  }).catch((error) => {
    if (generation === notebookGeneration) {
      pendingNotebookEdits = pendingNotebookEdits.filter((pending) => pending !== edit);
      if (currentState) {
        renderNotebook(currentState);
        updateCardNotes(currentState, cardId);
      }
      showError(`Could not save notebook: ${error.message}`);
    }
  });
}

function updateClauseEntryControls(state) {
  const button = $("clause-entry");
  button.hidden = state.notebook_mode !== "manual" || state.is_replay;
  button.textContent = clauseDraft ? "Confirm" : "Clause";
  button.setAttribute("aria-label", clauseDraft ? "Confirm clause" : "Add clause");
  button.setAttribute("aria-pressed", String(Boolean(clauseDraft)));
  const missing = ["suspect", "weapon", "room"].filter((type) => clauseDraft?.cards[type] == null);
  button.disabled = Boolean(clauseDraft && (clauseDraft.saving || missing.length));
  $("cancel-clause").hidden = !clauseDraft;
  $("cancel-clause").disabled = Boolean(clauseDraft?.saving);
  const hint = $("clause-entry-hint");
  hint.hidden = !clauseDraft;
  $("notebook-legend").hidden = Boolean(clauseDraft);
  if (clauseDraft) {
    const owner = clauseDraft.holder === null ? "Choose player or E"
      : clauseDraft.holder === state.num_players ? "Envelope" : `Player ${clauseDraft.holder + 1}`;
    hint.textContent = `${owner} · ${missing.length ? `Select ${missing.join(", ")}` : "Ready to confirm"}`;
    const description = `${clauseDraft.id === null ? "New clause" : `Editing clause ${clauseDraft.id}`}. ${owner}. `
      + (missing.length ? `Select: ${missing.join(", ")}.` : "Ready to confirm.")
      + " Click a different column to change the holder.";
    hint.title = description;
    hint.setAttribute("aria-label", description);
  }
}

function startClauseEntry(clause = null) {
  if (!currentState || currentState.notebook_mode !== "manual" || currentState.is_replay) return;
  if (clauseDraft) {
    showError("Finish or cancel the current clause before editing another.");
    return;
  }
  const cards = {};
  for (const id of clause?.cards || []) cards[cardsById.get(id).type] = id;
  clauseDraft = { id: clause?.id ?? null, holder: clause?.holder ?? null, cards, saving: false };
  renderNotebook(currentState);
  $("clause-entry-hint").focus();
}

function selectClauseCell(cardId, holder) {
  if (!clauseDraft || clauseDraft.saving || !currentState) return;
  const card = cardsById.get(cardId);
  if (!card || holder < 0 || holder > currentState.num_players) return;
  if (clauseDraft.holder === holder && clauseDraft.cards[card.type] === cardId) {
    delete clauseDraft.cards[card.type];
  } else {
    clauseDraft.holder = holder;
    clauseDraft.cards[card.type] = cardId;
  }
  renderNotebook(currentState);
}

function cancelClauseEntry() {
  if (!clauseDraft || clauseDraft.saving) return;
  clauseDraft = null;
  if (currentState) renderNotebook(currentState);
  $("clause-entry").focus({ preventScroll: true });
}

function confirmClauseEntry() {
  if (!clauseDraft || clauseDraft.saving || !currentState) return;
  const draft = clauseDraft;
  const types = ["suspect", "weapon", "room"];
  const cards = types.map((type) => draft.cards[type]);
  if (draft.holder === null || cards.some((id, index) => cardsById.get(id)?.type !== types[index])) {
    showError("Could not save notebook: Choose one suspect, one weapon, and one room.");
    return;
  }
  const holder = draft.holder;
  const kind = holder === currentState.num_players ? "accuse" : "refute";
  const clauseId = draft.id;
  draft.saving = true;
  renderNotebook(currentState);
  saveClause(clauseId === null ? "POST" : "PUT", clauseId, () => {
    const original = currentState.notebook_clauses.find((clause) => clause.id === clauseId);
    if (clauseId !== null && !original) throw new Error(`Clause #${clauseId} no longer exists.`);
    const preserveExclusions = original?.kind === kind && original?.holder === holder;
    return {
      kind, holder, cards, resolved: original?.status === "resolved",
      excluded_cards: preserveExclusions
        ? original.excluded_cards.filter((id) => cards.includes(id)) : [],
    };
  }, () => {
    if (clauseDraft !== draft) return;
    clauseDraft = null;
    renderNotebook(currentState);
    $("clause-entry").focus({ preventScroll: true });
  }, () => {
    if (clauseDraft !== draft) return;
    draft.saving = false;
    renderNotebook(currentState);
  });
}

function openClauses() {
  if (currentState?.board) switchBoardTab("clauses");
  else switchInsightsTab("clauses");
}

function clearClauseSelection() {
  if (selectedClause === null) return;
  selectedClause = null;
  if (currentState) {
    renderNotebook(currentState);
    renderClauses(currentState);
  }
}

function updateClausePerspective(state) {
  const perspective = `${state.is_replay ? "replay" : "live"}:${state.selected_player}:${state.notebook_mode}`;
  if (lastNotebookPerspective !== null && perspective !== lastNotebookPerspective) selectedClause = null;
  lastNotebookPerspective = perspective;
  const active = new Set((state.notebook_clauses || [])
    .filter((clause) => clause.active_cards.length).map((clause) => clause.id));
  if (!active.has(selectedClause)) selectedClause = null;
}

function clauseColor(clause, clauses) {
  const hues = [0, 210, 120, 35, 285, 175, 330, 65, 245, 155, 20, 265];
  const index = clauses.filter((item) => item.holder === clause.holder && item.id < clause.id).length;
  const hue = hues[index % hues.length];
  const lightness = Math.floor(index / hues.length) % 2 ? 65 : 45;
  return `hsl(${hue} 80% ${lightness}%)`;
}

function toggleClauseSelection(id) {
  selectedClause = selectedClause === id ? null : id;
}

function renderClauses(state) {
  const clauses = state.notebook_clauses || [];
  const actor = $("clause-actor").value || "all";
  const kind = $("clause-kind").value || "all";
  const fingerprint = JSON.stringify([clauses, actor, kind, selectedClause, state.notebook_mode, state.is_replay]);
  if (fingerprint === lastClauseFingerprint) return;
  lastClauseFingerprint = fingerprint;
  const list = $("clauses");
  const focused = document.activeElement.closest("[data-clause-action]");
  const focusAction = focused?.dataset.clauseAction;
  const focusId = focused?.dataset.clauseId;
  list.replaceChildren();
  const visible = clauses.filter((clause) =>
    (actor === "all" || clause.actor === Number(actor))
    && (kind === "all" || clause.kind === kind));
  if (!visible.length) {
    list.textContent = clauses.length ? "No clauses match these filters." : "No clauses recorded.";
    return;
  }
  for (const clause of visible) {
    const item = document.createElement("article");
    item.className = "clause-item";
    item.tabIndex = -1;
    const selected = selectedClause === clause.id;
    if (selected) item.classList.add("clause-selected");
    item.style.setProperty("--clause-color", clauseColor(clause, clauses));
    item.dataset.clauseItem = String(clause.id);
    const heading = document.createElement("button");
    heading.type = "button";
    heading.className = "clause-select";
    heading.dataset.clauseAction = "select";
    heading.dataset.clauseId = String(clause.id);
    heading.disabled = !clause.active_cards.length;
    heading.setAttribute("aria-pressed", String(selected));
    const subject = clause.kind === "refute"
      ? `Player ${clause.holder + 1} holds at least one`
      : "At least one is not in the envelope";
    const source = clause.kind === "accuse" && clause.actor !== null
      ? ` (incorrect accusation by Player ${clause.actor + 1})` : "";
    const swatch = document.createElement("span");
    swatch.className = "clause-swatch";
    swatch.setAttribute("aria-hidden", "true");
    const headingText = document.createElement("span");
    headingText.textContent = `#${clause.id}: ${subject}${source}`;
    heading.append(swatch, headingText);
    const description = document.createElement("p");
    description.textContent = clause.cards.map((id) => cardsById.get(id).name).join(", ");
    const status = document.createElement("p");
    status.textContent = state.notebook_mode === "manual"
      ? `Your note: ${clause.status}${clause.status === "unresolved" && !clause.active_cards.length
        ? "; no linked cards remain, check your notes." : ""}`
      : clause.status === "satisfied" ? "Satisfied"
        : `Unresolved; remaining: ${clause.active_cards.map((id) => cardsById.get(id).name).join(", ")}`;
    const actions = document.createElement("div");
    actions.className = "clause-actions";
    for (const [action, label] of [
      ...(state.notebook_mode === "manual" && !state.is_replay ? [
        ["edit", "Edit"], ["resolve", clause.status === "resolved" ? "Reopen" : "Resolve"],
        ["delete", "Delete"],
      ] : []),
    ]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "button button-quiet";
      button.dataset.clauseAction = action;
      button.dataset.clauseId = String(clause.id);
      button.textContent = label;
      button.setAttribute("aria-label", `${label} clause ${clause.id}`);
      actions.append(button);
    }
    item.append(heading, description, status);
    if (state.notebook_mode === "manual" && !state.is_replay) {
      const candidates = document.createElement("div");
      candidates.className = "clause-actions";
      for (const id of clause.cards) {
        const excluded = clause.excluded_cards.includes(id);
        const button = document.createElement("button");
        button.type = "button";
        button.className = "button button-quiet";
        button.dataset.clauseAction = "toggle-card";
        button.dataset.clauseId = String(clause.id);
        button.dataset.cardId = String(id);
        button.textContent = `${excluded ? "Restore" : "Exclude"} ${cardsById.get(id).name}`;
        button.setAttribute("aria-label", `${button.textContent} in clause ${clause.id}`);
        candidates.append(button);
      }
      item.append(candidates);
    }
    item.append(actions);
    list.append(item);
  }
  if (focusAction && focusId) {
    const cardSelector = focused.dataset.cardId ? `[data-card-id="${focused.dataset.cardId}"]` : "";
    list.querySelector(`[data-clause-action="${focusAction}"][data-clause-id="${focusId}"]${cardSelector}`)
      ?.focus({ preventScroll: true });
  }
}

function saveClause(method, clauseId, body, onSuccess = null, onFailure = null) {
  const generation = notebookGeneration;
  notebookQueue = notebookQueue.then(async () => {
    if (generation !== notebookGeneration || !currentState) return;
    const path = `/api/notebook/clauses${clauseId === null ? "" : `/${clauseId}`}`;
    const requestBody = typeof body === "function" ? body() : body;
    const result = await requestJson(path, { method, body: requestBody });
    if (generation !== notebookGeneration || !currentState) return;
    if (result.notebook_revision >= currentState.notebook_revision) {
      currentState.matrix = result.matrix;
      currentState.notebook_clauses = result.notebook_clauses;
      currentState.notebook_revision = result.notebook_revision;
      updateClausePerspective(currentState);
      renderNotebook(currentState);
      updateCardNotes(currentState);
      renderClauses(currentState);
      lastRenderedState = JSON.stringify(currentState);
    }
    if (onSuccess) onSuccess();
    if (lastError.startsWith("Could not save notebook:")) showError("");
  }).catch((error) => {
    if (generation === notebookGeneration) {
      if (onFailure) onFailure();
      showError(`Could not save notebook: ${error.message}`);
    }
  });
}

function changeClause(clauseId, change) {
  saveClause("PUT", clauseId, () => {
    const clause = currentState.notebook_clauses.find((item) => item.id === clauseId);
    if (!clause) throw new Error(`Clause #${clauseId} no longer exists.`);
    return {
      kind: clause.kind, holder: clause.holder, cards: clause.cards,
      resolved: clause.status === "resolved", excluded_cards: clause.excluded_cards,
      ...change(clause),
    };
  });
}

function renderHistory(events) {
  const actor = $("history-actor").value;
  const kind = $("history-kind").value;
  const visible = events.filter((event) =>
    (actor === "all" || Number(actor) === event.actor)
    && (kind === "all" || kind === event.kind));
  renderHistoryList($("history-list"), visible, events.length);
  renderHistoryList($("action-history-list"), events.slice(0, 8), events.length);
}

function renderHistoryList(list, visible, total) {
  list.replaceChildren();
  if (!visible.length) {
    const empty = document.createElement("li");
    empty.className = "empty-history";
    empty.textContent = total ? "No events match these filters." : "No events yet.";
    list.append(empty);
    return;
  }
  for (const event of visible) {
    const item = document.createElement("li");
    const number = document.createElement("span");
    number.className = "event-number";
    number.textContent = `#${event.number}`;
    const text = document.createElement("span");
    text.className = "event-text";
    appendCardReferences(text, displayPlayerText(event.text));
    item.append(number, text);
    list.append(item);
  }
}

function appendCardReferences(container, text) {
  const matcher = new RegExp(`(${cardNamePattern})`, "g");
  for (const part of text.split(matcher)) {
    if (!part) continue;
    const card = cardsByName.get(part);
    if (!card) {
      container.append(document.createTextNode(part));
      continue;
    }
    const reference = document.createElement("span");
    reference.className = `card-reference ${card.type}`;
    reference.textContent = part;
    container.append(reference);
  }
}

function renderDebug(debugInfo) {
  const panel = $("debug-panel");
  panel.hidden = !debugInfo;
  document.body.classList.toggle("debug-active", Boolean(debugInfo));
  const fingerprint = JSON.stringify(debugInfo);
  if (fingerprint === lastDebugFingerprint) return;
  lastDebugFingerprint = fingerprint;
  if (!debugInfo) {
    panel.open = false;
    setText("debug-summary", "Omniscient information");
    $("debug-content").replaceChildren();
    return;
  }
  const solution = debugInfo.solution.map(cardName).join(", ");
  setText("debug-summary", `Omniscient · Solution: ${solution} · Hands`);
  const lines = ["Private hands and events are visible."];
  debugInfo.hands.forEach((hand, seat) => {
    lines.push(`Player ${seat + 1} hand: ${hand.map(cardName).join(", ") || "(empty)"}`);
  });
  const content = $("debug-content");
  content.replaceChildren();
  appendCardReferences(content, lines.join("\n"));
}

function cardName(id) {
  return cardsById.get(id)?.name || `Card ${id}`;
}

function renderActions(state) {
  const legal = state.legal;
  $("pass-button").hidden = !legal.pass;
  $("pass-button").disabled = !legal.pass;
  $("card-action-buttons").hidden = [
    "card-suggest-button",
    "card-accuse-button",
    "pass-button",
    "use-room-button",
    "clear-cards-button",
  ].every((id) => $(id).hidden);
}

async function submitAction(action) {
  if (submitting || advancing || !currentState) return;
  const focusBoardAfterRoll = action.action === "roll" && document.activeElement === $("board-roll-button");
  const version = ++requestVersion;
  submitting = true;
  $("board-panel").setAttribute("aria-busy", "true");
  lastError = "";
  try {
    const state = await requestJson(`/api/action?${selectedFilters()}`, {
      method: "POST",
      body: action,
    });
    if (version !== requestVersion || !currentState) return;
    acceptState(state);
    if (["reveal", "end_turn", "pass", "accuse"].includes(action.action)) clearSelectedCards();
    renderState(state);
    if (focusBoardAfterRoll && state.legal.moves.length
      && (document.activeElement === $("board-roll-button") || document.activeElement === document.body)) {
      $("board-map-shell").focus({ preventScroll: true });
    }
  } catch (error) {
    if (version === requestVersion) showError(error.message);
  } finally {
    submitting = false;
    $("board-panel").removeAttribute("aria-busy");
  }
}

async function advanceBot(step) {
  if (advancing || submitting || !currentState || $("confirm-dialog").open) return;
  advancing = true;
  const version = ++requestVersion;
  try {
    const state = await requestJson(`/api/advance?${selectedFilters()}`, {
      method: "POST",
      body: { step },
    });
    if (version !== requestVersion || !currentState) return;
    acceptState(state);
    renderState(state);
  } catch (error) {
    if (version === requestVersion) {
      showError(error.message);
      await refreshState();
    }
  } finally {
    advancing = false;
  }
}

async function togglePause() {
  if (!currentState || advancing || submitting) return;
  const version = ++requestVersion;
  try {
    const state = await requestJson(`/api/pause?${selectedFilters()}`, { method: "POST", body: {} });
    if (version !== requestVersion || !currentState) return;
    acceptState(state);
    renderState(state);
  } catch (error) {
    showError(error.message);
  }
}

async function nextTurn() {
  if (!currentState?.waiting_for_turn || advancing || submitting) return;
  const version = ++requestVersion;
  submitting = true;
  $("turn-button").disabled = true;
  try {
    const state = await requestJson(`/api/next-turn?${selectedFilters()}`, {
      method: "POST", body: {},
    });
    if (version !== requestVersion || !currentState) return;
    acceptState(state);
    renderState(state);
  } catch (error) {
    if (version === requestVersion) showError(error.message);
  } finally {
    submitting = false;
    $("turn-button").disabled = false;
  }
}

function useTurnButton() {
  if (currentState?.waiting_for_turn) nextTurn();
  else if (currentState?.legal.end_turn) submitAction({ action: "end_turn" });
}

function newGame() {
  batchReplay = false;
  $("batch-replay-return").hidden = true;
  stopReplayPlayback();
  replayMode = false;
  setReplayPresentation(false);
  renderDebug(null);
  $("replay-controls").hidden = true;
  document.body.classList.remove("replay-active");
  requestVersion++;
  sessionStorage.removeItem(activeGameKey);
  notebookGeneration++;
  notebookQueue = Promise.resolve();
  pendingNotebookEdits = [];
  clearInterval(refreshTimer);
  currentState = null;
  clearSelectedCards();
  cardView = "hand";
  lastActivityKey = null;
  lastRenderedState = null;
  lastNotebookFingerprint = null;
  lastNotebookStructureFingerprint = null;
  lastNotebookMarks = null;
  lastNotebookDraft = null;
  lastClauseFingerprint = null;
  selectedClause = null;
  clauseDraft = null;
  lastBoardState = null;
  lastBoardLayout = null;
  lastBoardMoment = null;
  lastDiceState = null;
  lastCardAnimation = null;
  clearSuggestionFlights();
  lastSuggestionRoom = null;
  hadReveal = false;
  hadBoardResponse = false;
  lastError = "";
  document.body.classList.remove("game-active", "board-game", "manual-notebook-active");
  $("site-header").append($("header-tools"));
  $("board-map-shell").classList.remove("zoomed");
  $("board-zoom-button").setAttribute("aria-pressed", "false");
  showError("");
  $("game-screen").hidden = true;
  showMainMenu();
}

function showMainMenu() {
  batchChartVersion++;
  batchRunsVersion++;
  document.body.classList.remove("batch-active");
  $("setup-screen").hidden = true;
  $("batch-screen").hidden = true;
  $("main-menu").hidden = false;
  $("main-menu-title").focus();
}

function showSetup(batch = false) {
  batchChartVersion++;
  batchRunsVersion++;
  document.body.classList.remove("batch-active");
  $("main-menu").hidden = true;
  $("batch-screen").hidden = true;
  $("setup-screen").hidden = false;
  window.setupWizard.beginFresh(batch);
  $("setup-game-title").focus();
}

async function loadReplay() {
  if (!replayMode) return false;
  const version = ++requestVersion;
  const params = new URLSearchParams({
    position: $("replay-position").value,
    player: $("replay-player").value,
    manual: $("replay-manual").checked ? "1" : "0",
    omniscient: $("replay-omniscient").checked ? "1" : "0",
  });
  try {
    const state = await requestJson(`/api/replay/state?${params}`);
    if (version !== requestVersion || !replayMode) return false;
    currentState = state;
    $("replay-position").max = String(state.positions - 1);
    $("replay-manual").disabled = !state.manual_available;
    if (!state.manual_available) $("replay-manual").checked = false;
    renderReplayMarkers(state);
    renderReplayKnowledge(state.knowledge_summary);
    renderState(state);
    updateReplayPlaybackControls();
    return true;
  } catch (error) {
    if (version === requestVersion) {
      if (currentState?.is_replay) $("replay-position").value = String(currentState.position);
      showError(error.message);
    }
    return false;
  }
}

function replayMarkerGroups(state) {
  const type = replayMarkerType;
  const player = replayMarkerPlayer;
  const groups = new Map();
  for (const item of state.deduction_timeline) {
    const envelope = item.holder === state.num_players;
    if (type === "none" || (type === "envelope" && !envelope)
        || (type === "holder" && envelope)
        || (player !== "all" && Number(player) !== item.player)) continue;
    if (!groups.has(item.position)) groups.set(item.position, []);
    groups.get(item.position).push(item);
  }
  return [...groups.entries()].sort((a, b) => a[0] - b[0]);
}

function renderReplayMarkers(state) {
  const groups = replayMarkerGroups(state);
  const playerFilter = replayMarkerPlayer;
  const fingerprint = JSON.stringify([groups, state.positions, playerFilter]);
  const track = $("replay-markers");
  if (fingerprint !== lastReplayDeductionFingerprint) {
    lastReplayDeductionFingerprint = fingerprint;
    const focused = document.activeElement.closest("[data-replay-position]");
    const focusPosition = focused?.dataset.replayPosition;
    track.replaceChildren();
    for (const [position, deductions] of groups) {
      const descriptions = deductions.map((item) => {
        const owner = item.holder === state.num_players ? "the envelope" : `Player ${item.holder + 1}`;
        return `Player ${item.player + 1} inferred ${cardName(item.card)} in ${owner}`;
      });
      const when = deductions[0].step ? `action ${deductions[0].step}` : "start";
      const description = `${when}: ${descriptions.join("; ")}`;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "replay-marker";
      button.dataset.replayPosition = String(position);
      const percent = state.positions > 1 ? position * 100 / (state.positions - 1) : 0;
      button.style.left = `${percent}%`;
      button.setAttribute("aria-label", description);
      button.title = description;
      const badges = document.createElement("span");
      badges.className = "replay-marker-badges";
      badges.style.setProperty("--anchor", `${percent}%`);
      badges.setAttribute("aria-hidden", "true");
      const players = [...new Set(deductions.map((item) => item.player))].sort((a, b) => a - b);
      const byPlayer = players.map((player) => ({
        player, cards: [...new Set(deductions.filter((item) => item.player === player).map((item) => item.card))],
      }));
      const discoveries = [];
      for (let index = 0; byPlayer.some((entry) => index < entry.cards.length); index++) {
        for (const entry of byPlayer) {
          if (index < entry.cards.length) discoveries.push({ player: entry.player, card: entry.cards[index] });
        }
      }
      if (playerFilter === "all") {
        for (const item of discoveries.slice(0, 5)) {
          const badge = document.createElement("span");
          badge.className = "replay-card-badge replay-card-player";
          badge.style.setProperty("--player-color", replayPlayerColor(item.player));
          badge.append(cardIllustration(item.card));
          const number = document.createElement("span");
          number.textContent = String(item.player + 1);
          badge.append(number);
          badges.append(badge);
        }
      } else {
        for (const { card: cardId } of discoveries.slice(0, 5)) {
          const badge = document.createElement("span");
          badge.className = `replay-card-badge ${cardsById.get(cardId).type}`;
          badge.append(cardIllustration(cardId));
          badges.append(badge);
        }
      }
      const extra = discoveries.length - 5;
      if (extra > 0) {
        const more = document.createElement("span");
        more.className = "replay-player-badge replay-player-more";
        more.textContent = `+${extra}`;
        badges.append(more);
      }
      button.append(badges);
      track.append(button);
    }
    layoutReplayMarkers();
    if (focusPosition) {
      track.querySelector(`[data-replay-position="${focusPosition}"]`)?.focus({ preventScroll: true });
    }
  }
  for (const marker of track.children) {
    marker.setAttribute("aria-current", String(Number(marker.dataset.replayPosition) === state.position));
  }
  $("replay-previous-marker").disabled = !groups.some(([position]) => position < state.position);
  $("replay-next-marker").disabled = !groups.some(([position]) => position > state.position);
  $("replay-marker-status").textContent = groups.length
    ? `${groups.length} flagged ${groups.length === 1 ? "position" : "positions"}` : "No matching flags";
  const currentMarker = [...track.children].find(
    (marker) => Number(marker.dataset.replayPosition) === state.position
  );
  $("replay-marker-details").textContent = currentMarker?.getAttribute("aria-label")
    ?? "";
}

function setReplayMarkerFilter(kind, value) {
  const isType = kind === "type";
  if (isType) replayMarkerType = value;
  else replayMarkerPlayer = value;
  const container = $(isType ? "replay-marker-types" : "replay-marker-players");
  for (const button of container.children) {
    button.setAttribute("aria-pressed", String(
      (isType ? button.dataset.markerType : button.dataset.markerPlayer) === value
    ));
  }
  if (currentState?.is_replay) renderReplayMarkers(currentState);
}

function renderReplayPlayerFilters(count) {
  const container = $("replay-marker-players");
  container.replaceChildren();
  for (const player of ["all", ...Array.from({ length: count }, (_, seat) => String(seat))]) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.markerPlayer = player;
    if (player === "all") button.textContent = "All";
    else {
      button.setAttribute("aria-label", `Player ${Number(player) + 1}`);
      const badge = document.createElement("span");
      badge.className = "replay-player-badge";
      badge.style.setProperty("--player-color", replayPlayerColor(Number(player)));
      badge.textContent = String(Number(player) + 1);
      badge.setAttribute("aria-hidden", "true");
      button.append(badge);
    }
    container.append(button);
  }
}

function layoutReplayMarkers() {
  const track = $("replay-markers");
  if (!track.isConnected || !track.getClientRects().length) return;
  const laneEnds = [-Infinity, -Infinity];
  const markers = [...track.children].map((marker) => ({
    marker, bounds: marker.querySelector(".replay-marker-badges").getBoundingClientRect(),
  })).sort((a, b) => a.bounds.left - b.bounds.left);
  for (const { marker, bounds } of markers) {
    let lane = laneEnds.findIndex((end) => bounds.left >= end + 2);
    if (lane < 0) lane = laneEnds[0] <= laneEnds[1] ? 0 : 1;
    laneEnds[lane] = Math.max(laneEnds[lane], bounds.right);
    marker.style.setProperty("--marker-lane", String(lane));
  }
}

function replayPlayerColor(player) {
  return `hsl(${(player * 137.508) % 360} 65% 26%)`;
}

function replayKnowledgeValues(summary) {
  const categories = ["suspect", "weapon", "room"].map((type) => summary.categories[type]);
  return {
    ...summary.categories,
    total: {
      located: categories.reduce((sum, item) => sum + item.located, 0),
      total: categories.reduce((sum, item) => sum + item.total, 0),
      marks: categories.reduce((sum, item) => sum + item.marks, 0),
      mark_total: categories.reduce((sum, item) => sum + item.mark_total, 0),
    },
    envelope: {
      located: categories.reduce((sum, item) => sum + item.envelope, 0),
      total: categories.length,
      marks: 0,
    },
  };
}

function renderReplayKnowledge(summaries) {
  const fingerprint = JSON.stringify([
    summaries, replayKnowledgeSort, replayKnowledgeAscending, [...replayKnowledgeVisible],
  ]);
  if (fingerprint === lastReplayKnowledgeFingerprint) return;
  lastReplayKnowledgeFingerprint = fingerprint;
  for (const column of ["player", ...replayKnowledgeColumns]) {
    const header = $(`replay-knowledge-head-${column}`);
    header.hidden = column !== "player" && !replayKnowledgeVisible.has(column);
    if (column === replayKnowledgeSort) {
      header.setAttribute("aria-sort", replayKnowledgeAscending ? "ascending" : "descending");
    } else header.removeAttribute("aria-sort");
  }
  const body = $("replay-knowledge-body");
  const animate = replayPlaying && !window.matchMedia("(prefers-reduced-motion: reduce)").matches
    && body.getClientRects().length > 0;
  const previousPositions = new Map(animate
    ? [...body.children].map((row) => [row.dataset.player, row.getBoundingClientRect().top]) : []);
  body.replaceChildren();
  const sorted = [...summaries].sort((a, b) => {
    const aValue = replayKnowledgeSort === "player"
      ? { located: a.player, marks: 0 } : replayKnowledgeValues(a)[replayKnowledgeSort];
    const bValue = replayKnowledgeSort === "player"
      ? { located: b.player, marks: 0 } : replayKnowledgeValues(b)[replayKnowledgeSort];
    const order = (aValue.located - bValue.located) || (aValue.marks - bValue.marks);
    return (replayKnowledgeAscending ? order : -order) || a.player - b.player;
  });
  for (const summary of sorted) {
    const row = document.createElement("tr");
    row.dataset.player = String(summary.player);
    const name = document.createElement("th");
    name.scope = "row";
    const badge = document.createElement("span");
    badge.className = "replay-player-badge";
    badge.style.setProperty("--player-color", replayPlayerColor(summary.player));
    badge.textContent = String(summary.player + 1);
    badge.setAttribute("aria-hidden", "true");
    const label = document.createElement("span");
    label.textContent = `Player ${summary.player + 1}`;
    name.append(badge, label);
    row.append(name);
    const values = replayKnowledgeValues(summary);
    for (const column of replayKnowledgeColumns) {
      if (!replayKnowledgeVisible.has(column)) continue;
      const item = values[column];
      const cell = document.createElement("td");
      const located = document.createElement("strong");
      located.textContent = `${item.located}/${item.total}${column === "envelope" ? "" : " located"}`;
      cell.append(located);
      if (column !== "envelope") {
        const marks = document.createElement("span");
        marks.textContent = `${item.marks}/${item.mark_total} marks`;
        cell.append(marks);
      }
      row.append(cell);
    }
    body.append(row);
  }
  if (animate) {
    for (const row of body.children) {
      const previous = previousPositions.get(row.dataset.player);
      if (previous === undefined) continue;
      const distance = previous - row.getBoundingClientRect().top;
      if (distance) row.animate(
        [{ transform: `translateY(${distance}px)` }, { transform: "translateY(0)" }],
        { duration: Math.min(350, Number($("replay-speed").value) / 2), easing: "ease-out" }
      );
    }
  }
}

function setReplayKnowledgeSort(column) {
  if (replayKnowledgeSort === column) replayKnowledgeAscending = !replayKnowledgeAscending;
  else {
    replayKnowledgeSort = column;
    replayKnowledgeAscending = column === "player";
  }
  if (currentState?.is_replay) renderReplayKnowledge(currentState.knowledge_summary);
}

function setReplayKnowledgeColumn(column, visible) {
  if (visible) replayKnowledgeVisible.add(column);
  else replayKnowledgeVisible.delete(column);
  if (!replayKnowledgeVisible.has(replayKnowledgeSort) && replayKnowledgeSort !== "player") {
    replayKnowledgeSort = replayKnowledgeColumns.find((item) => replayKnowledgeVisible.has(item)) ?? "player";
    replayKnowledgeAscending = replayKnowledgeSort === "player";
  }
  if (currentState?.is_replay) renderReplayKnowledge(currentState.knowledge_summary);
}

function moveReplayMarker(direction) {
  if (!currentState?.is_replay) return;
  const positions = replayMarkerGroups(currentState).map(([position]) => position);
  const target = direction < 0
    ? positions.reverse().find((position) => position < currentState.position)
    : positions.find((position) => position > currentState.position);
  if (target === undefined) return;
  stopReplayPlayback();
  $("replay-position").value = String(target);
  loadReplay();
}

async function openReplay() {
  if (!currentState?.is_over) return;
  let queued;
  do {
    queued = notebookQueue;
    await queued;
  } while (queued !== notebookQueue);
  if (!currentState?.is_over || replayMode) return;
  clauseDraft = null;
  selectedClause = null;
  replayMode = true;
  document.body.classList.add("replay-active");
  $("replay-controls").hidden = false;
  setReplayPresentation(true);
  $("replay-position").value = "0";
  $("replay-player").replaceChildren(...Array.from(
    { length: currentState.num_players }, (_, seat) => option(seat, `Player ${seat + 1}`)
  ));
  $("replay-player").value = String(currentState.selected_player);
  renderReplayPlayerFilters(currentState.num_players);
  setReplayMarkerFilter("type", "envelope");
  setReplayMarkerFilter("player", "all");
  lastReplayDeductionFingerprint = null;
  lastReplayKnowledgeFingerprint = null;
  $("replay-manual").checked = false;
  $("replay-omniscient").checked = false;
  if (currentState.board) switchBoardTab("cards");
  await loadReplay();
}

async function closeReplay() {
  stopReplayPlayback();
  replayMode = false;
  setReplayPresentation(false);
  document.body.classList.remove("replay-active");
  $("replay-controls").hidden = true;
  lastRenderedState = null;
  await refreshState();
}

function setReplayPresentation(visible) {
  $("replay-timeline").hidden = !visible;
  $("replay-knowledge").hidden = !visible;
  $("card-view-tabs").hidden = visible;
  $("hand-cards").hidden = visible;
}

function updateReplayPlaybackControls() {
  const position = currentState?.is_replay ? currentState.position : 0;
  const last = currentState?.is_replay ? currentState.positions - 1 : 0;
  $("replay-play").textContent = replayPlaying ? "Pause" : "Play";
  $("replay-play").disabled = !replayPlaying && position >= last;
  $("replay-previous").disabled = $("replay-previous-turn").disabled = position <= 0;
  $("replay-next").disabled = $("replay-next-turn").disabled = position >= last;
}

function stopReplayPlayback() {
  if (replayPlaying) {
    requestVersion++;
    if (currentState?.is_replay) $("replay-position").value = String(currentState.position);
  }
  replayPlaying = false;
  replayPlaybackGeneration++;
  clearTimeout(replayTimer);
  replayTimer = null;
  updateReplayPlaybackControls();
}

function scheduleReplayPlayback(generation, delay = Number($("replay-speed").value)) {
  replayTimer = setTimeout(async () => {
    replayTimer = null;
    if (!replayPlaying || generation !== replayPlaybackGeneration || !currentState?.is_replay) return;
    if (cardActivityPending()) {
      const remaining = Math.max(0, cardActivityReadUntil - performance.now());
      const flightPoll = Math.min(100, Number($("replay-speed").value) / 5);
      scheduleReplayPlayback(generation, suggestionFlights.length ? flightPoll : Math.max(1, remaining));
      return;
    }
    $("replay-position").value = String(currentState.position + 1);
    const loaded = await loadReplay();
    if (!replayPlaying || generation !== replayPlaybackGeneration) return;
    if (!loaded || currentState.position >= currentState.positions - 1) stopReplayPlayback();
    else scheduleReplayPlayback(generation);
  }, delay);
}

function toggleReplayPlayback() {
  if (replayPlaying) {
    stopReplayPlayback();
  } else if (currentState?.is_replay && currentState.position < currentState.positions - 1) {
    replayPlaying = true;
    const generation = ++replayPlaybackGeneration;
    updateReplayPlaybackControls();
    scheduleReplayPlayback(generation);
  }
}

function moveReplay(amount, turn = false) {
  if (!currentState?.is_replay) return;
  stopReplayPlayback();
  const position = currentState.position;
  const max = currentState.positions - 1;
  const target = turn
    ? (amount < 0
      ? [...currentState.turns].reverse().find((item) => item < position) ?? 0
      : currentState.turns.find((item) => item > position) ?? max)
    : Math.max(0, Math.min(max, position + amount));
  $("replay-position").value = String(target);
  loadReplay();
}

async function importReplay(file) {
  if (!file) return;
  const message = (currentState ? "Importing a replay replaces the current game. " : "")
    + "This private replay contains hands, the solution, and private actions. Continue?";
  if (!await confirmAction(message, { title: "Import private replay", confirmLabel: "Import replay" })) return;
  try {
    if (file.size > 8 * 1024 * 1024) throw new Error("Replay file exceeds 8 MB.");
    const data = JSON.parse(await file.text());
    await requestJson("/api/replay/import", { method: "POST", body: data });
    const state = await requestJson("/api/state");
    sessionStorage.setItem(activeGameKey, "1");
    activateGame(state);
    await openReplay();
  } catch (error) {
    showError(`Could not import replay: ${error.message}`);
  }
}

async function saveReplay() {
  try {
    await requestJson("/api/replay/export");
    const link = document.createElement("a");
    link.href = "/api/replay/export";
    link.download = "clue-private-replay.json";
    document.body.append(link);
    link.click();
    link.remove();
  } catch (error) { showError(error.message); }
}

function configureBoardWorkspace(isBoard) {
  $("board-workspace-tabs").hidden = !isBoard;
  $("insights-tabs").hidden = isBoard;
  $("action-history").hidden = !isBoard;
  moveViewerField("notebook-heading-tools");
  const clauses = $("clauses-panel");
  if (isBoard) {
    for (const name of ["cards", "locations"]) {
      const panel = $(name === "locations" ? "board-locations-panel" : `${name}-panel`);
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", `board-tab-${name}`);
    }
    $("notebook-panel").hidden = false;
    $("board-panel").hidden = false;
    $("board-panel").setAttribute("aria-labelledby", "board-title");
    $("insights-panel").removeAttribute("role");
    $("insights-panel").removeAttribute("aria-labelledby");
    switchBoardTab("cards");
  } else {
    for (const name of ["cards", "insights", "locations"]) {
      const panel = $(name === "locations" ? "board-locations-panel" : `${name}-panel`);
      panel.removeAttribute("role");
      panel.removeAttribute("aria-labelledby");
      panel.hidden = name === "locations";
    }
    $("notebook-panel").hidden = false;
    clauses.setAttribute("role", "tabpanel");
    $("board-panel").removeAttribute("role");
    $("board-panel").setAttribute("aria-labelledby", "board-title");
    delete document.body.dataset.boardTab;
    switchInsightsTab("history");
  }
}

function moveViewerField(destinationId) {
  const viewer = $("viewer-field");
  const destination = $(destinationId);
  if (viewer.parentElement !== destination) destination.append(viewer);
}

function switchBoardTab(name) {
  document.body.dataset.boardTab = name;
  for (const item of boardTabs) {
    const tab = $(`board-tab-${item}`);
    tab.setAttribute("aria-selected", String(item === name));
    tab.tabIndex = item === name ? 0 : -1;
  }
  for (const item of ["cards", "locations"]) {
    const panel = $(item === "locations" ? "board-locations-panel" : `${item}-panel`);
    panel.hidden = item !== name;
  }
  $("insights-panel").hidden = !insightsTabs.includes(name);
  if (insightsTabs.includes(name)) switchInsightsTab(name);
  if (name !== "clauses") clearClauseSelection();
}

function updateMode(restoreNotebook = true) {
  const spectating = $("mode").value === "spectate";
  const notebook = $("notebook-mode");
  if (spectating) {
    if (!notebook.disabled) notebook.dataset.playMode = notebook.value;
    notebook.value = "automatic";
    notebook.disabled = true;
  } else {
    if (notebook.disabled && restoreNotebook) notebook.value = notebook.dataset.playMode || "manual";
    notebook.disabled = false;
  }
  $("seat-field").hidden = spectating;
  $("shuffle-seat-field").hidden = spectating;
  $("notebook-mode-field").hidden = spectating;
  $("notebook-mode-hint").hidden = spectating;
  $("spectator-warning").hidden = !spectating;
}

function updateGameType() {
  const board = document.querySelector('input[name="game-type"]:checked').value === "board";
  $("players").min = board ? "3" : "2";
  if (board) $("players").max = "6";
  else $("players").removeAttribute("max");
  $("players-hint").textContent = board ? "(3–6 players)" : "(at least 2)";
  $("game-style-hint").textContent = board
    ? "Board games use 3–6 players and an original layout inspired by Clue."
    : "Cards only supports two or more players.";
}

function switchInsightsTab(name) {
  const board = document.body.classList.contains("board-game");
  for (const item of insightsTabs) {
    const active = item === name;
    $(`${item}-tab`).setAttribute("aria-selected", String(active));
    $(`${item}-tab`).tabIndex = active ? 0 : -1;
    $(`${item}-panel`).hidden = !active;
    $(`${item}-panel`).setAttribute("aria-labelledby", board ? `board-tab-${item}` : `${item}-tab`);
  }
  if (name !== "clauses") clearClauseSelection();
}

function setTheme(theme, persist = false) {
  const isDark = theme === "dark";
  document.documentElement.dataset.theme = isDark ? "dark" : "light";
  for (const id of ["theme-toggle", "game-theme-toggle"]) {
    $(id).textContent = isDark ? "Light mode" : "Dark mode";
    $(id).setAttribute("aria-label", isDark ? "Switch to light mode" : "Switch to dark mode");
  }
  if (persist) {
    if (window.clueOptions.desktop) {
      desktopThemeWrite = desktopThemeWrite
        .then(() => requestJson("/api/desktop/theme", {
          method: "POST", body: { theme: isDark ? "dark" : "light" },
        }))
        .catch((error) => showError(error.message));
    } else {
      try {
        localStorage.setItem("clue-engine-theme", isDark ? "dark" : "light");
      } catch (error) {
        showError(`Could not save theme: ${error.message}`);
      }
    }
  }
}

function showFullscreenState(fullscreen) {
  desktopFullscreen = fullscreen;
  for (const id of ["fullscreen-toggle", "game-fullscreen"]) {
    const button = $(id);
    button.textContent = fullscreen ? "Exit full screen" : "Full screen";
    button.setAttribute("aria-pressed", String(fullscreen));
  }
}

function setFullscreenDisabled(disabled) {
  for (const id of ["fullscreen-toggle", "game-fullscreen"]) $(id).disabled = disabled;
}

async function initializeFullscreen() {
  if (!window.clueOptions.desktop) {
    showFullscreenState(Boolean(document.fullscreenElement));
    setFullscreenDisabled(!document.fullscreenEnabled);
    return;
  }
  try {
    showFullscreenState(await window.pywebview.api.fullscreen_state());
    setFullscreenDisabled(false);
  } catch (error) {
    showError(`Could not initialize full screen: ${error.message}`);
  }
}

async function toggleDesktopFullscreen() {
  if (fullscreenBusy || $("fullscreen-toggle").disabled) return;
  fullscreenBusy = true;
  setFullscreenDisabled(true);
  try {
    if (window.clueOptions.desktop) {
      showFullscreenState(await window.pywebview.api.toggle_fullscreen());
    } else {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
      showFullscreenState(Boolean(document.fullscreenElement));
    }
    if (lastError.startsWith("Could not change full screen:")) showError("");
  } catch (error) {
    showError(`Could not change full screen: ${error.message}`);
  } finally {
    fullscreenBusy = false;
    setFullscreenDisabled(false);
  }
}

setTheme(document.documentElement.dataset.theme);
if (window.clueThemeStorageError) {
  showError(`Could not load saved theme: ${window.clueThemeStorageError}`);
}
window.addEventListener("pywebviewready", initializeFullscreen);
if (window.clueOptions.desktop && window.pywebview?.api) initializeFullscreen();
if (!window.clueOptions.desktop) initializeFullscreen();
document.addEventListener("fullscreenchange", () => {
  if (!window.clueOptions.desktop) showFullscreenState(Boolean(document.fullscreenElement));
});
$("fullscreen-toggle").addEventListener("click", toggleDesktopFullscreen);
$("game-fullscreen").addEventListener("click", toggleDesktopFullscreen);
document.addEventListener("keydown", (event) => {
  if (!window.clueOptions.desktop || event.repeat || event.altKey || event.ctrlKey || event.metaKey
    || event.shiftKey || $("fullscreen-toggle").disabled || document.querySelector("dialog[open]")) return;
  if (event.key === "F11" || (event.key === "Escape" && desktopFullscreen)) {
    event.preventDefault();
    toggleDesktopFullscreen();
  }
});
$("confirm-dialog").addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    event.preventDefault();
    $("confirm-dialog").close("cancel");
  }
});
$("setup-form").addEventListener("submit", startGame);
$("main-setup").addEventListener("click", () => showSetup());
$("main-batch").addEventListener("click", () => showSetup(true));
$("setup-menu").addEventListener("click", showMainMenu);
$("main-quick-play").addEventListener("click", async () => {
  if (mainMenuBusy) return;
  mainMenuBusy = true;
  for (const id of ["main-quick-play", "main-setup", "main-batch", "replay-import-button"]) {
    $(id).disabled = true;
  }
  try {
    await window.setupWizard.loadQuickplay();
    window.setupWizard.renderReview($("quickplay-summary"), false);
    showError("");
    $("quickplay-dialog").showModal();
  } catch (error) {
    showError(`Could not load quickplay defaults: ${error.message}`);
  } finally {
    mainMenuBusy = false;
    for (const id of ["main-quick-play", "main-setup", "main-batch", "replay-import-button"]) {
      $(id).disabled = false;
    }
  }
});
$("batch-cancel").addEventListener("click", async () => {
  if (!activeBatchId) return;
  $("batch-cancel").disabled = true;
  try {
    await requestJson(`/api/batch/${encodeURIComponent(activeBatchId)}/cancel`, {
      method: "POST", body: {},
    });
    await pollBatch();
  } catch (error) {
    showError(`Could not cancel batch: ${error.message}`);
    $("batch-cancel").disabled = false;
  }
});
$("batch-new-run").addEventListener("click", () => showSetup(true));
$("batch-main-menu").addEventListener("click", () => {
  activeBatchId = null;
  showMainMenu();
});
$("batch-metric").addEventListener("change", () => {
  loadBatchChart().catch((error) => showError(`Could not load distribution: ${error.message}`));
});
$("batch-bin-width").addEventListener("change", () => {
  loadBatchChart().catch((error) => showError(`Could not load distribution: ${error.message}`));
});
for (const id of ["batch-policy-filter", "batch-seat-filter"]) {
  $(id).addEventListener("change", () => {
    loadBatchChart().catch((error) => showError(`Could not load distribution: ${error.message}`));
    batchRunsOffset = 0;
    loadBatchRuns().catch((error) => showError(`Could not load runs: ${error.message}`));
  });
}
for (const id of ["batch-runs-sort", "batch-runs-order"]) {
  $(id).addEventListener("change", () => {
    batchRunsOffset = 0;
    loadBatchRuns().catch((error) => showError(`Could not load runs: ${error.message}`));
  });
}
$("batch-runs-previous").addEventListener("click", () => {
  batchRunsOffset = Math.max(0, batchRunsOffset - 25);
  loadBatchRuns().catch((error) => showError(`Could not load runs: ${error.message}`));
});
$("batch-runs-next").addEventListener("click", () => {
  if (batchRunsOffset + 25 >= batchRunsTotal) return;
  batchRunsOffset += 25;
  loadBatchRuns().catch((error) => showError(`Could not load runs: ${error.message}`));
});
$("batch-replay-return").addEventListener("click", () => {
  newGame();
  $("main-menu").hidden = true;
  $("batch-screen").hidden = false;
  document.body.classList.add("batch-active");
  $("batch-title").focus();
});
$("batch-display-mode").addEventListener("change", renderBatchChart);
for (const name of batchTabs) {
  const tab = $(`batch-tab-${name}`);
  tab.addEventListener("click", () => switchBatchTab(name));
  tab.addEventListener("keydown", (event) => {
    let index = batchTabs.indexOf(name);
    if (event.key === "ArrowRight") index = (index + 1) % batchTabs.length;
    else if (event.key === "ArrowLeft") index = (index + batchTabs.length - 1) % batchTabs.length;
    else if (event.key === "Home") index = 0;
    else if (event.key === "End") index = batchTabs.length - 1;
    else return;
    event.preventDefault();
    switchBatchTab(batchTabs[index]);
    $(`batch-tab-${batchTabs[index]}`).focus();
  });
}
$("batch-chart-values").addEventListener("toggle", renderBatchBinTable);
$("batch-bin-previous").addEventListener("click", () => {
  batchBinOffset = Math.max(0, batchBinOffset - 50);
  renderBatchBinTable();
});
$("batch-bin-next").addEventListener("click", () => {
  if (!lastBatchChart || batchBinOffset + 50 >= lastBatchChart.bins.length) return;
  batchBinOffset += 50;
  renderBatchBinTable();
});
if (window.ResizeObserver) {
  const batchChartObserver = new ResizeObserver(() => {
    if (lastBatchChart && !$("batch-panel-distribution").hidden) drawBatchGraph(lastBatchChart);
  });
  batchChartObserver.observe($("batch-chart-graph"));
}
$("quickplay-cancel").addEventListener("click", () => $("quickplay-dialog").close());
$("main-edit-default").addEventListener("click", () => {
  $("quickplay-dialog").close();
  showSetup();
});
$("quickplay-start").addEventListener("click", () => {
  $("quickplay-dialog").close();
  startGame();
});
$("main-quit").addEventListener("click", async () => {
  try { await window.pywebview.api.quit(); }
  catch (error) { showError(`Could not quit the desktop app: ${error.message}`); }
});
$("game-options-open").addEventListener("click", () => {
  if (replayMode) stopReplayPlayback();
  $("game-options-dialog").showModal();
});
$("game-options-close").addEventListener("click", () => $("game-options-dialog").close());
$("show-card-indicators").addEventListener("change", (event) => {
  showCardIndicators = event.target.checked;
  if (currentState) updateCardNotes(currentState);
});
$("show-board-indicators").addEventListener("change", (event) => {
  showBoardIndicators = event.target.checked;
  if (currentState) updateKnowledgeIndicators(currentState);
});
$("mode").addEventListener("change", updateMode);
for (const choice of document.querySelectorAll('input[name="game-type"]')) {
  choice.addEventListener("change", updateGameType);
}
$("players").addEventListener("input", updateGameType);
for (const id of ["theme-toggle", "game-theme-toggle"]) {
  $(id).addEventListener("click", () => {
    setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark", true);
  });
}
$("notebook").addEventListener("click", (event) => {
  const indicator = event.target.closest("[data-clause-card]");
  if (indicator && currentState) {
    $("clause-actor").value = "all";
    $("clause-kind").value = "all";
    openClauses();
    selectedClause = Number(indicator.dataset.clauseId);
    renderNotebook(currentState);
    renderClauses(currentState);
    const item = $("clauses").querySelector(`[data-clause-action="select"][data-clause-id="${selectedClause}"]`);
    item?.scrollIntoView({ block: "nearest" });
    item?.focus({ preventScroll: true });
    return;
  }
  const button = event.target.closest("[data-notebook-card]");
  if (button) {
    const card = Number(button.dataset.notebookCard);
    const holder = Number(button.dataset.notebookHolder);
    if (clauseDraft) selectClauseCell(card, holder);
    else changeNotebook(card, holder);
  }
});
$("clause-entry").addEventListener("click", () => {
  if (clauseDraft) confirmClauseEntry();
  else startClauseEntry();
});
$("cancel-clause").addEventListener("click", cancelClauseEntry);
$("clauses").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-clause-action]");
  if (!button || !currentState) return;
  const clause = currentState.notebook_clauses.find((item) => item.id === Number(button.dataset.clauseId));
  if (!clause) return;
  const action = button.dataset.clauseAction;
  if (action === "select") {
    toggleClauseSelection(clause.id);
    renderNotebook(currentState);
    renderClauses(currentState);
  } else if (action === "edit") {
    startClauseEntry(clause);
  } else if (action === "resolve") {
    changeClause(clause.id, (latest) => ({ resolved: latest.status !== "resolved" }));
  } else if (action === "toggle-card") {
    const card = Number(button.dataset.cardId);
    changeClause(clause.id, (latest) => ({
      excluded_cards: latest.excluded_cards.includes(card)
        ? latest.excluded_cards.filter((id) => id !== card)
        : [...latest.excluded_cards, card],
    }));
  } else if (action === "delete") {
    if (clauseDraft?.id === clause.id) {
      showError("Finish or cancel editing this clause before deleting it.");
      return;
    }
    if (!await confirmAction(`Delete clause #${clause.id}?`, {
      title: "Delete clause", confirmLabel: "Delete clause",
    })) return;
    saveClause("DELETE", clause.id, undefined, () => {
      if (selectedClause === clause.id) selectedClause = null;
      renderNotebook(currentState);
      renderClauses(currentState);
    });
  }
});
$("notebook").addEventListener("keydown", (event) => {
  const button = event.target.closest("[data-notebook-card]");
  if (!button || !currentState || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
  const direction = {
    ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1],
  }[event.key];
  if (!direction) return;
  let cardIndex = currentState.matrix.findIndex((card) => card.id === Number(button.dataset.notebookCard));
  let holder = Number(button.dataset.notebookHolder);
  while (true) {
    cardIndex += direction[0];
    holder += direction[1];
    if (cardIndex < 0 || cardIndex >= currentState.matrix.length
      || holder < 0 || holder > currentState.num_players) return;
    const target = $("notebook").querySelector(
      `[data-notebook-card="${currentState.matrix[cardIndex].id}"][data-notebook-holder="${holder}"]`
    );
    if (target) {
      event.preventDefault();
      target.focus();
      return;
    }
  }
});
$("card-suggest-button").addEventListener("click", () => {
  submitAction({ action: "suggest", ...selectedCombination() });
});
$("card-accuse-button").addEventListener("click", async () => {
  if (submitting || advancing || !currentState?.legal.accuse) return;
  const combination = selectedCombination();
  if (await confirmAction("An incorrect accusation eliminates you. Continue?", {
    title: "Make accusation", confirmLabel: "Accuse",
  })) submitAction({ action: "accuse", confirmed: true, ...combination });
});
$("clear-cards-button").addEventListener("click", () => {
  clearSelectedCards();
  if (currentState) {
    if (currentState.legal.suggest_room !== null) {
      selectedCardIds.room = currentState.legal.suggest_room;
    }
    renderHand(currentState);
    renderCardInteraction(currentState);
  }
});
$("use-room-button").addEventListener("click", () => {
  if (!currentState || currentState.legal.suggest_room === null) return;
  selectedCardIds.room = currentState.legal.suggest_room;
  renderHand(currentState);
  renderCardInteraction(currentState);
});
$("board-roll-button").addEventListener("click", () => submitAction({ action: "roll" }));
$("board-passage-button").addEventListener("click", () => submitAction({ action: "passage" }));
$("board-zoom-button").addEventListener("click", () => {
  const zoomed = $("board-map-shell").classList.toggle("zoomed");
  $("board-zoom-button").setAttribute("aria-pressed", String(zoomed));
});
$("board-panel").addEventListener("click", (event) => {
  const target = event.target.closest("[data-board-move]");
  if (target) submitAction({ action: "move", destination: JSON.parse(target.dataset.boardMove) });
});
$("board-map").addEventListener("keydown", (event) => {
  const target = event.target.closest("[data-board-move]");
  if (target && (event.key === "Enter" || event.key === " ")) {
    event.preventDefault();
    submitAction({ action: "move", destination: JSON.parse(target.dataset.boardMove) });
  }
});
$("board-map-shell").addEventListener("keydown", (event) => {
  const directions = {
    ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0],
  };
  const direction = directions[event.key];
  if (!direction || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey
    || !currentState?.board || !currentState.legal.moves.length) return;
  event.preventDefault();
  if (event.repeat || submitting || advancing) return;
  const moves = directionalMoves(currentState, ...direction);
  if (moves.length === 1) {
    submitAction({ action: "move", destination: moves[0] });
  } else if (moves.length > 1) {
    const targets = [...$("board-map").querySelectorAll("[data-board-move]")]
      .filter((target) => moves.some((move) => target.dataset.boardMove === JSON.stringify(move)));
    const next = (targets.indexOf(document.activeElement) + 1) % targets.length;
    targets[next]?.focus({ preventScroll: true });
    setText("board-instruction", "Multiple exits: use the arrow key to choose, then press Enter.");
  }
});
$("board-workspace-tabs").addEventListener("click", (event) => {
  const tab = event.target.closest("[role='tab']");
  if (tab) switchBoardTab(tab.id.replace("board-tab-", ""));
});
$("board-workspace-tabs").addEventListener("keydown", (event) => {
  const tab = event.target.closest("[role='tab']");
  if (!tab) return;
  const available = boardTabs;
  const index = available.indexOf(tab.id.replace("board-tab-", ""));
  let next = null;
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    const offset = event.key === "ArrowDown" ? 1 : -1;
    next = available[(index + offset + available.length) % available.length];
  } else if (event.key === "Home") next = available[0];
  else if (event.key === "End") next = available[available.length - 1];
  if (next === null) return;
  event.preventDefault();
  switchBoardTab(next);
  $(`board-tab-${next}`).focus();
});
$("pass-button").addEventListener("click", () => submitAction({ action: "pass" }));
$("card-view-tabs").addEventListener("click", (event) => {
  const button = event.target.closest("[data-card-view]");
  if (!button || !currentState) return;
  cardView = button.dataset.cardView;
  renderHand(currentState);
});
$("pause-button").addEventListener("click", togglePause);
$("turn-button").addEventListener("click", useTurnButton);
$("next-button").addEventListener("click", () => advanceBot(true));
$("new-game-button").addEventListener("click", async (event) => {
  if (submitting || advancing) {
    showError("Wait for the current action to finish.");
    return;
  }
  if (!await confirmAction("Exit the current game and return to the main menu? Unsaved progress will be lost.", {
    title: "Exit game", confirmLabel: "Exit game",
  })) return;
  submitting = true;
  requestVersion++;
  try {
    await requestJson("/api/game", { method: "DELETE" });
    $("game-options-dialog").close();
    newGame();
  } catch (error) {
    showError(`Could not exit the game: ${error.message}`);
  } finally {
    submitting = false;
  }
});
$("replay-open").addEventListener("click", openReplay);
$("replay-close").addEventListener("click", closeReplay);
$("replay-export").addEventListener("click", saveReplay);
$("replay-import-button").addEventListener("click", () => $("replay-import").click());
$("replay-import").addEventListener("change", (event) => {
  importReplay(event.target.files[0]);
  event.target.value = "";
});
$("replay-end").addEventListener("click", async (event) => {
  if (submitting || advancing) {
    showError("Wait for the current action to finish.");
    return;
  }
  if (!await confirmAction("End this game permanently and reveal all private information?", {
    title: "End and reveal", confirmLabel: "End and reveal",
  })) return;
  $("game-options-dialog").close();
  const version = ++requestVersion;
  submitting = true;
  try {
    await notebookQueue;
    const state = await requestJson("/api/replay/end", {
      method: "POST", body: { confirmed: true },
    });
    if (version !== requestVersion) return;
    acceptState(state);
    renderState(state);
    await openReplay();
  } catch (error) { showError(error.message); }
  finally { submitting = false; }
});
$("replay-previous").addEventListener("click", () => moveReplay(-1));
$("replay-next").addEventListener("click", () => moveReplay(1));
$("replay-previous-turn").addEventListener("click", () => moveReplay(-1, true));
$("replay-next-turn").addEventListener("click", () => moveReplay(1, true));
$("replay-play").addEventListener("click", toggleReplayPlayback);
$("replay-markers").addEventListener("click", (event) => {
  const button = event.target.closest("[data-replay-position]");
  if (!button || !replayMode) return;
  stopReplayPlayback();
  $("replay-position").value = button.dataset.replayPosition;
  loadReplay();
});
for (const name of ["focusin", "mouseover"]) {
  $("replay-markers").addEventListener(name, (event) => {
    const marker = event.target.closest("[data-replay-position]");
    if (marker) $("replay-marker-details").textContent = marker.getAttribute("aria-label");
  });
}
$("replay-previous-marker").addEventListener("click", () => moveReplayMarker(-1));
$("replay-next-marker").addEventListener("click", () => moveReplayMarker(1));
$("replay-marker-types").addEventListener("click", (event) => {
  const button = event.target.closest("[data-marker-type]");
  if (button) setReplayMarkerFilter("type", button.dataset.markerType);
});
$("replay-marker-players").addEventListener("click", (event) => {
  const button = event.target.closest("[data-marker-player]");
  if (button) setReplayMarkerFilter("player", button.dataset.markerPlayer);
});
$("replay-knowledge-columns").addEventListener("change", (event) => {
  const input = event.target.closest("[data-knowledge-column]");
  if (input) setReplayKnowledgeColumn(input.dataset.knowledgeColumn, input.checked);
});
$("replay-knowledge-table").addEventListener("click", (event) => {
  const button = event.target.closest("[data-knowledge-sort]");
  if (button) setReplayKnowledgeSort(button.dataset.knowledgeSort);
});
window.addEventListener("resize", () => {
  if (replayMode) layoutReplayMarkers();
});
$("replay-position").addEventListener("input", () => {
  const target = $("replay-position").value;
  stopReplayPlayback();
  $("replay-position").value = target;
});
for (const id of ["replay-position", "replay-player", "replay-manual", "replay-omniscient"]) {
  $(id).addEventListener("change", () => {
    const target = $("replay-position").value;
    stopReplayPlayback();
    $("replay-position").value = target;
    loadReplay();
  });
}
for (const id of ["viewer-select", "clause-actor", "clause-kind"]) {
  $(id).addEventListener("change", () => {
    if (id !== "viewer-select" && currentState) renderClauses(currentState);
    refreshState();
  });
}
for (const id of ["history-actor", "history-kind"]) {
  $(id).addEventListener("change", () => currentState && renderHistory(currentState.events));
}
for (const name of insightsTabs) {
  $(`${name}-tab`).addEventListener("click", () => switchInsightsTab(name));
}
$("insights-tabs").addEventListener("keydown", (event) => {
  const tab = event.target.closest("[role='tab']");
  if (!tab) return;
  const available = insightsTabs;
  const index = available.indexOf(tab.id.replace("-tab", ""));
  let next = null;
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    const offset = event.key === "ArrowDown" ? 1 : -1;
    next = available[(index + offset + available.length) % available.length];
  } else if (event.key === "Home") next = available[0];
  else if (event.key === "End") next = available[available.length - 1];
  if (!next) return;
  event.preventDefault();
  switchInsightsTab(next);
  $(`${next}-tab`).focus();
});
updateMode();
updateGameType();
restoreGame();
