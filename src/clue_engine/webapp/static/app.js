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
const $ = (id) => document.getElementById(id);
let currentState = null;
let refreshTimer = null;
let advancing = false;
let lastError = "";
let cardView = "hand";
let lastActivityKey = null;
const selectedCardIds = { suspect: null, weapon: null, room: null };

function option(value, label) {
  const item = document.createElement("option");
  item.value = value;
  item.textContent = label;
  return item;
}

function initializeChoices() {
  for (const policy of window.clueOptions.policies) $("policy").append(option(policy, policy));
}

function showError(message) {
  lastError = message;
  $("error-message").textContent = message;
  $("error-message").hidden = !message;
}

async function requestJson(path, { method = "GET", body } = {}) {
  const options = { method, headers: {} };
  if (method !== "GET") {
    options.headers["Content-Type"] = "application/json";
    options.headers["X-CSRF-Token"] = csrfToken;
  }
  if (body !== undefined) options.body = JSON.stringify(body);
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status}).`);
  return data;
}

async function startGame(event) {
  event.preventDefault();
  clearSelectedCards();
  cardView = "hand";
  lastActivityKey = null;
  const mode = $("mode").value;
  const debug = $("debug").checked;
  if (debug && !window.confirm("Debug mode reveals every hand, the solution, and private events. Continue?")) {
    $("debug").checked = false;
    return;
  }
  try {
    const state = await requestJson("/api/game", {
      method: "POST",
      body: {
        mode,
        players: Number($("players").value),
        seat: Number($("seat").value),
        seed: Number($("seed").value),
        policy: $("policy").value,
        policies: $("policies").value,
        progress: $("progress").value,
        max_steps: Number($("max-steps").value),
        debug,
      },
    });
    lastError = "";
    document.body.classList.add("game-active");
    $("setup-screen").hidden = true;
    $("game-screen").hidden = false;
    $("error-message").hidden = true;
    buildPlayerFilters(state.num_players);
    currentState = state;
    renderState(state);
    clearInterval(refreshTimer);
    refreshTimer = setInterval(refreshState, 700);
  } catch (error) {
    showError(error.message);
  }
}

function buildPlayerFilters(numPlayers) {
  const selectors = ["viewer-select", "history-actor", "clause-actor"];
  for (const id of selectors) {
    const select = $(id);
    select.replaceChildren();
    if (id !== "viewer-select") select.append(option("all", "All players"));
    for (let seat = 0; seat < numPlayers; seat++) {
      select.append(option(seat, `Player ${seat}`));
    }
  }
  const historyKind = $("history-kind");
  historyKind.replaceChildren(option("all", "All types"));
  for (const [value, label] of [
    ["suggest", "Suggestion"], ["pass", "Pass"], ["refute", "Refutation"],
    ["show", "Shown card"], ["accuse", "Accusation"], ["end_turn", "End turn"],
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

async function refreshState() {
  try {
    const state = await requestJson(`/api/state?${selectedFilters()}`);
    currentState = state;
    renderState(state);
    if (state.auto_progress && !state.paused && shouldAdvance(state)) {
      await advanceBot(false);
    }
  } catch (error) {
    showError(error.message);
  }
}

function shouldAdvance(state) {
  return !advancing && !state.is_over && !state.limit_reached
    && (state.human_player === null || state.to_move !== state.human_player);
}

function renderState(state) {
  const activityKey = state.activity
    ? `${state.steps}:${state.activity.kind}:${state.activity.actor}:${state.activity.card_id ?? ""}`
    : null;
  if (state.activity?.kind === "reveal" && activityKey !== lastActivityKey) {
    clearSelectedCards();
  }
  lastActivityKey = activityKey;
  $("game-status").textContent = state.status;
  $("game-meta").textContent =
    `Actions: ${state.steps} · Player 0 turns: ${state.player0_turns}`
    + (state.paused ? " · Paused" : "");
  $("pause-button").textContent = state.paused ? "Resume" : "Pause";
  $("pause-button").disabled = state.is_over || state.limit_reached;
  $("next-button").hidden = !(state.paused && shouldAdvance(state));
  $("viewer-select").value = String(state.selected_player);
  $("viewer-field").hidden = state.mode !== "spectate" || !state.debug_info;
  renderHand(state);
  renderCardInteraction(state);
  renderNotebook(state);
  renderHistory(state.events);
  $("clauses").replaceChildren();
  appendCardReferences($("clauses"), state.clauses);
  renderDebug(state.debug_info);
  renderActions(state);
  $("error-message").hidden = !lastError;
  $("error-message").textContent = lastError;
}

function renderHand(state) {
  const container = $("hand-cards");
  container.replaceChildren();
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

function createCardFace(card, { button = false, mini = false, disabled = false, pressed = false } = {}) {
  const face = document.createElement(button ? "button" : "article");
  if (button) {
    face.type = "button";
    face.disabled = disabled;
    face.setAttribute("aria-pressed", String(pressed));
  }
  face.className = `playing-card ${card.type}${mini ? " mini-card" : ""}`;
  face.setAttribute("aria-label", `${card.name}, ${card.type}`);

  const header = document.createElement("div");
  header.className = "card-topline";
  const number = document.createElement("span");
  number.className = "card-number";
  number.textContent = `ID ${card.id}`;
  const category = document.createElement("span");
  category.className = "card-category";
  category.textContent = card.type;
  header.append(number, category);

  const art = document.createElement("div");
  art.className = "card-art";
  art.append(cardIllustration(card.id));

  const name = document.createElement("h4");
  name.className = "playing-card-name";
  name.textContent = card.name;
  face.append(header, art, name);
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
  selectedCardIds[card.type] = card.id;
  renderHand(currentState);
  renderCardInteraction(currentState);
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

function renderCardInteraction(state) {
  const legal = state.legal;
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
    const actor = state.activity?.suggestion_actor ?? state.activity?.actor;
    renderActivityMeta(actor === undefined ? null : { kind: "suggest", actor });
    $("card-interaction-hint").textContent = actor === undefined
      ? "Click one of your matching cards to reveal it."
      : `Player ${actor} suggested these cards. Click a matching card you hold to reveal it.`;
    renderMiniCards(focusCards, state.activity?.cards || []);
  } else if (humanTurn && (legal.suggest || legal.accuse)) {
    const activity = state.activity;
    if (activity?.kind === "reveal") {
      $("card-interaction-title").textContent = "Latest reveal";
      renderActivityMeta(activity);
      $("card-interaction-hint").textContent = `Shown to Player ${activity.recipient}.`;
      renderMiniCards(focusCards, [activity.card_id], activity.card_id);
    } else {
      $("card-interaction-title").textContent = legal.suggest
        ? "Build a suggestion"
        : "Build an accusation";
      if (activity?.kind === "refute" || activity?.kind === "reveal") {
        renderActivityMeta(activity);
      }
      $("card-interaction-hint").textContent =
        "Select one suspect, weapon, and room from any card view.";
    }
    for (const type of ["suspect", "weapon", "room"]) {
      const card = cardsById.get(selectedCardIds[type]);
      if (card) {
        if (activity?.kind === "reveal") {
          const chip = document.createElement("span");
          chip.className = `card-reference ${type}`;
          chip.textContent = card.name;
          selectedCards.append(chip);
        } else {
          selectedCards.append(createCardFace(card, { mini: true }));
        }
      } else if (activity?.kind !== "reveal") {
        const slot = document.createElement("div");
        slot.className = `selection-slot ${type}`;
        slot.textContent = type[0].toUpperCase() + type.slice(1);
        selectedCards.append(slot);
      }
    }
    if (activity?.kind === "reveal") selectedCards.classList.add("reveal-selection");
    const hasCombination = Object.values(selectedCardIds).every((id) => id !== null);
    const revealIsActive = activity?.kind === "reveal";
    $("card-suggest-button").hidden = !legal.suggest || (revealIsActive && !hasCombination);
    $("card-accuse-button").hidden = !legal.accuse || (revealIsActive && !hasCombination);
    $("card-suggest-button").disabled = !hasCombination;
    $("card-accuse-button").disabled = !hasCombination;
    $("clear-cards-button").hidden = !Object.values(selectedCardIds).some((id) => id !== null);
    return;
  } else {
    const activity = state.activity;
    $("card-interaction-title").textContent = activity?.kind === "reveal"
      ? "Latest reveal"
      : "Table activity";
    renderActivityMeta(activity);
    let hint = "No suggestion, accusation, or refutation has been made yet.";
    if (activity?.kind === "suggest") {
      hint = `Player ${activity.actor} suggested these cards.`;
    } else if (activity?.kind === "accuse") {
      hint = `Player ${activity.actor} accused this combination.`;
    } else if (activity?.kind === "refute") {
      hint = `Player ${activity.actor} refuted Player ${activity.suggestion_actor}'s suggestion.`;
    } else if (activity?.kind === "reveal") {
      hint = `Shown to Player ${activity.recipient}.`;
    }
    if (humanTurn && legal.pass && !legal.reveals.length) {
      hint += " You have no matching card; select Pass below.";
    }
    $("card-interaction-hint").textContent = hint;
    if (activity?.kind === "reveal") {
      renderMiniCards(focusCards, [activity.card_id], activity.card_id);
    } else {
      renderMiniCards(focusCards, activity?.cards || []);
    }
  }

  $("card-suggest-button").hidden = true;
  $("card-accuse-button").hidden = true;
  $("card-suggest-button").disabled = true;
  $("card-accuse-button").disabled = true;
  $("clear-cards-button").hidden = true;
  if (!humanTurn && state.mode !== "spectate" && !state.is_over && !state.limit_reached) {
    $("card-interaction-hint").textContent += " Waiting for your turn.";
  }
}

function renderActivityMeta(activity) {
  const labels = {
    suggest: "Suggestion",
    accuse: "Accusation",
    refute: "Refutation",
    reveal: "Reveal",
  };
  if (!activity || !labels[activity.kind]) return;
  $("activity-kind").textContent = labels[activity.kind];
  $("activity-player").textContent = `Player ${activity.actor}`;
  $("activity-meta").hidden = false;
}

function renderMiniCards(container, cardIds, shownCardId = null) {
  for (const id of cardIds) {
    const card = cardsById.get(id);
    if (!card) continue;
    const face = createCardFace(card, { mini: true });
    if (id === shownCardId) face.classList.add("shown-card");
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

function renderNotebook(state) {
  const notebook = $("notebook");
  notebook.replaceChildren();
  for (const type of ["suspect", "weapon", "room"]) {
    const category = document.createElement("section");
    category.className = `category-table ${type}`;
    const title = document.createElement("h4");
    title.textContent = type;
    category.append(title);
    const table = document.createElement("table");
    const head = document.createElement("thead");
    const body = document.createElement("tbody");
    const heading = document.createElement("tr");
    const cardHeading = document.createElement("th");
    cardHeading.textContent = "Card";
    heading.append(cardHeading);
    for (let seat = 0; seat < state.num_players; seat++) {
      const th = document.createElement("th");
      th.textContent = `P${seat}`;
      heading.append(th);
    }
    const envelope = document.createElement("th");
    envelope.textContent = "Env.";
    envelope.title = "Envelope";
    heading.append(envelope);
    head.append(heading);
    for (const card of state.matrix.filter((item) => item.type === type)) {
      const row = document.createElement("tr");
      const name = document.createElement("td");
      name.className = "card-name";
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
      for (const mark of card.marks) {
        const cell = document.createElement("td");
        cell.textContent = mark;
        cell.className = mark === "+" ? "mark-held" : mark === "-" ? "mark-not-held" : "mark-unknown";
        cell.setAttribute("aria-label", mark === "+" ? "held" : mark === "-" ? "not held" : "unknown");
        row.append(cell);
      }
      body.append(row);
    }
    table.append(head, body);
    category.append(table);
    notebook.append(category);
  }
}

function renderHistory(events) {
  const list = $("history-list");
  list.replaceChildren();
  const actor = $("history-actor").value;
  const kind = $("history-kind").value;
  const visible = events.filter((event) =>
    (actor === "all" || Number(actor) === event.actor)
    && (kind === "all" || kind === event.kind));
  if (!visible.length) {
    const empty = document.createElement("li");
    empty.className = "empty-history";
    empty.textContent = events.length ? "No events match these filters." : "No events yet.";
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
    appendCardReferences(text, event.text);
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
  panel.replaceChildren();
  if (!debugInfo) return;
  const solution = debugInfo.solution.map(cardName).join(", ");
  const lines = [`WARNING: omniscient debug mode is enabled.`, `Solution: ${solution}`];
  debugInfo.hands.forEach((hand, seat) => {
    lines.push(`Player ${seat} hand: ${hand.map(cardName).join(", ") || "(empty)"}`);
  });
  appendCardReferences(panel, lines.join("\n"));
}

function cardName(id) {
  return cardsById.get(id)?.name || `Card ${id}`;
}

function renderActions(state) {
  const legal = state.legal;
  $("end-button").hidden = !legal.end_turn;
  $("end-button").disabled = !legal.end_turn;
  $("pass-button").hidden = !legal.pass;
  $("pass-button").disabled = !legal.pass;
  $("card-action-buttons").hidden = [
    "card-suggest-button",
    "card-accuse-button",
    "end-button",
    "pass-button",
    "clear-cards-button",
  ].every((id) => $(id).hidden);
}

async function submitAction(action) {
  lastError = "";
  try {
    const state = await requestJson(`/api/action?${selectedFilters()}`, {
      method: "POST",
      body: action,
    });
    currentState = state;
    if (action.action !== "suggest") clearSelectedCards();
    renderState(state);
  } catch (error) {
    showError(error.message);
  }
}

async function advanceBot(step) {
  if (advancing) return;
  advancing = true;
  try {
    const state = await requestJson(`/api/advance?${selectedFilters()}`, {
      method: "POST",
      body: { step },
    });
    currentState = state;
    renderState(state);
  } catch (error) {
    if (!step) showError(error.message);
    else showError(error.message);
    await refreshState();
  } finally {
    advancing = false;
  }
}

async function togglePause() {
  try {
    const state = await requestJson(`/api/pause?${selectedFilters()}`, { method: "POST", body: {} });
    currentState = state;
    renderState(state);
  } catch (error) {
    showError(error.message);
  }
}

function newGame() {
  clearInterval(refreshTimer);
  currentState = null;
  clearSelectedCards();
  cardView = "hand";
  lastActivityKey = null;
  lastError = "";
  document.body.classList.remove("game-active");
  $("game-screen").hidden = true;
  $("setup-screen").hidden = false;
}

function updateMode() {
  const spectating = $("mode").value === "spectate";
  $("seat-field").hidden = spectating;
  $("spectator-warning").hidden = !spectating;
}

function switchInsightsTab(name) {
  const isHistory = name === "history";
  $("history-tab").setAttribute("aria-selected", String(isHistory));
  $("history-tab").tabIndex = isHistory ? 0 : -1;
  $("history-panel").hidden = !isHistory;
  $("clauses-tab").setAttribute("aria-selected", String(!isHistory));
  $("clauses-tab").tabIndex = isHistory ? -1 : 0;
  $("clauses-panel").hidden = isHistory;
}

function setTheme(theme, persist = false) {
  const isDark = theme === "dark";
  document.documentElement.dataset.theme = isDark ? "dark" : "light";
  $("theme-icon").textContent = isDark ? "☀" : "☾";
  $("theme-label").textContent = isDark ? "Light mode" : "Dark mode";
  $("theme-toggle").setAttribute(
    "aria-label",
    isDark ? "Switch to light mode" : "Switch to dark mode"
  );
  if (persist) localStorage.setItem("clue-engine-theme", isDark ? "dark" : "light");
}

initializeChoices();
setTheme(document.documentElement.dataset.theme);
$("setup-form").addEventListener("submit", startGame);
$("mode").addEventListener("change", updateMode);
$("theme-toggle").addEventListener("click", () => {
  setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark", true);
});
$("card-suggest-button").addEventListener("click", () => {
  submitAction({ action: "suggest", ...selectedCombination() });
});
$("card-accuse-button").addEventListener("click", () => {
  if (window.confirm("An incorrect accusation eliminates you. Continue?")) {
    submitAction({ action: "accuse", confirmed: true, ...selectedCombination() });
  }
});
$("clear-cards-button").addEventListener("click", () => {
  clearSelectedCards();
  if (currentState) {
    renderHand(currentState);
    renderCardInteraction(currentState);
  }
});
$("end-button").addEventListener("click", () => submitAction({ action: "end_turn" }));
$("pass-button").addEventListener("click", () => submitAction({ action: "pass" }));
$("card-view-tabs").addEventListener("click", (event) => {
  const button = event.target.closest("[data-card-view]");
  if (!button || !currentState) return;
  cardView = button.dataset.cardView;
  renderHand(currentState);
});
$("pause-button").addEventListener("click", togglePause);
$("next-button").addEventListener("click", () => advanceBot(true));
$("new-game-button").addEventListener("click", newGame);
for (const id of ["viewer-select", "clause-actor", "clause-kind"]) {
  $(id).addEventListener("change", refreshState);
}
for (const id of ["history-actor", "history-kind"]) {
  $(id).addEventListener("change", () => currentState && renderHistory(currentState.events));
}
for (const name of ["history", "clauses"]) {
  $(`${name}-tab`).addEventListener("click", () => switchInsightsTab(name));
}
$("insights-tabs").addEventListener("keydown", (event) => {
  const tab = event.target.closest("[role='tab']");
  if (!tab) return;
  const next = event.key === "ArrowRight" || event.key === "ArrowLeft"
    ? (tab.id === "history-tab" ? "clauses" : "history")
    : event.key === "Home" ? "history"
      : event.key === "End" ? "clauses" : null;
  if (!next) return;
  event.preventDefault();
  switchInsightsTab(next);
  $(`${next}-tab`).focus();
});
updateMode();
