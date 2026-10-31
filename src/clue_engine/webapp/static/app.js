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
let refreshTimer = null;
let advancing = false;
let submitting = false;
let refreshing = false;
let requestVersion = 0;
let lastError = "";
let desktopThemeWrite = Promise.resolve();
let cardView = "hand";
let lastActivityKey = null;
let lastRenderedState = null;
let lastNotebookFingerprint = null;
let notebookGeneration = 0;
let notebookQueue = Promise.resolve();
let lastBoardState = null;
let lastBoardLayout = null;
let lastSuggestionRoom = null;
let hadReveal = false;
let hadBoardMovement = false;
let hadBoardResponse = false;
const boardTabs = ["board", "notebook", "cards", "insights", "locations"];
const narrowBoardLayout = window.matchMedia("(max-width: 800px)");
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
  if (!response.ok) {
    const error = new Error(data.error || `Request failed (${response.status}).`);
    error.status = response.status;
    throw error;
  }
  return data;
}

async function startGame(event) {
  event.preventDefault();
  notebookGeneration++;
  notebookQueue = Promise.resolve();
  const version = ++requestVersion;
  showError("");
  clearSelectedCards();
  cardView = "hand";
  lastActivityKey = null;
  lastRenderedState = null;
  lastNotebookFingerprint = null;
  lastBoardState = null;
  lastSuggestionRoom = null;
  hadReveal = false;
  hadBoardMovement = false;
  hadBoardResponse = false;
  const debug = $("debug").checked;
  if (debug && !window.confirm("Debug mode reveals every hand, the solution, and private events. Continue?")) {
    $("debug").checked = false;
    return;
  }
  try {
    const setup = window.setupWizard.payload();
    const state = await requestJson("/api/game", {
      method: "POST",
      body: setup,
    });
    if (version !== requestVersion) return;
    window.setupWizard.rememberStarted(setup);
    sessionStorage.setItem(activeGameKey, "1");
    activateGame(state);
  } catch (error) {
    showError(error.message);
  }
}

function activateGame(state) {
  lastError = "";
  document.body.classList.add("game-active");
  document.body.classList.toggle("board-game", Boolean(state.board));
  document.body.classList.toggle("manual-notebook-active", state.notebook_mode === "manual");
  configureBoardWorkspace(Boolean(state.board));
  $("setup-screen").hidden = true;
  $("game-screen").hidden = false;
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
    ["show", "Shown card"], ["accuse", "Accusation"], ["end_turn", "End turn"],
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
    state.notebook_revision = currentState.notebook_revision;
  }
  currentState = state;
}

async function refreshState() {
  if (refreshing || submitting) return;
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
    if (error.status === 404) clearInterval(refreshTimer);
    showError(error.message);
  } finally {
    refreshing = false;
  }
}

function shouldAdvance(state) {
  return !advancing && !submitting && !state.is_over && !state.limit_reached
    && (state.human_player === null || state.to_move !== state.human_player);
}

function renderState(state) {
  const fingerprint = JSON.stringify(state);
  if (fingerprint === lastRenderedState) return;
  lastRenderedState = fingerprint;
  const fixedRoom = state.board && state.legal.suggest ? state.legal.suggest_room : null;
  const hasReveal = state.legal.reveals.length > 0;
  const hasBoardMovement = state.board && (
    state.legal.roll || state.legal.passage || state.legal.moves.length > 0
  );
  const hasBoardResponse = state.board && (hasReveal || state.legal.pass);
  const moveHadFocus = state.board && (
    document.activeElement === $("board-map-shell")
    || ($("board-panel").contains(document.activeElement)
      && document.activeElement?.hasAttribute("data-board-move"))
  );
  let focusCards = false;
  if (state.board) {
    if (hasBoardResponse && !hadBoardResponse) {
      switchBoardTab("cards");
    } else if (fixedRoom !== null && fixedRoom !== lastSuggestionRoom
      && (!narrowBoardLayout.matches || !hasBoardMovement)) {
      switchBoardTab("cards");
      focusCards = moveHadFocus;
    } else if (hasBoardMovement && !hadBoardMovement && narrowBoardLayout.matches) {
      switchBoardTab("board");
    }
  }
  hadBoardMovement = Boolean(hasBoardMovement);
  hadBoardResponse = Boolean(hasBoardResponse);
  if (fixedRoom !== null && fixedRoom !== lastSuggestionRoom) {
    selectedCardIds.room = fixedRoom;
    cardView = "suspect";
  }
  lastSuggestionRoom = fixedRoom;
  if (hasReveal && !hadReveal) cardView = "hand";
  hadReveal = hasReveal;
  const activityKey = state.activity
    ? `${state.activity.kind}:${state.activity.actor}:${state.activity.suggestion_actor ?? ""}`
      + `:${state.activity.card_id ?? ""}:${state.activity.recipient ?? ""}`
    : null;
  if (state.activity?.kind === "reveal" && activityKey !== lastActivityKey) {
    clearSelectedCards();
  }
  lastActivityKey = activityKey;
  setText("game-status", displayPlayerText(state.status));
  $("game-meta").textContent =
    `Actions: ${state.steps} · Player 1 turns: ${state.player0_turns}`
    + (state.paused ? " · Paused" : "")
    + (state.board_rules && Object.values(state.board_rules).some((value) => !value)
      ? " · House rules active" : "");
  $("pause-button").textContent = state.paused ? "Resume" : "Pause";
  $("pause-button").disabled = state.is_over || state.limit_reached;
  $("next-button").hidden = !(state.paused && shouldAdvance(state));
  $("viewer-select").value = String(state.selected_player);
  $("viewer-field").hidden = state.mode !== "spectate";
  renderBoard(state);
  renderHand(state);
  renderCardInteraction(state);
  renderNotebook(state);
  renderHistory(state.events);
  $("clauses").replaceChildren();
  appendCardReferences($("clauses"), displayPlayerText(state.clauses));
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
  if (state.to_move !== board.turn_player) {
    return state.to_move === state.human_player
      ? "Respond to the suggestion in Cards & actions."
      : `Player ${state.to_move + 1} is responding to Player ${board.turn_player + 1}'s suggestion.`;
  }
  if (state.to_move !== state.human_player) {
    return `Following Player ${board.turn_player + 1}. Watch the highlighted pawn move around the mansion.`;
  }
  const legal = state.legal;
  if (legal.suggest && legal.roll) {
    return `You were summoned to ${cardName(legal.suggest_room)}. Suggest there, roll to leave`
      + (legal.passage ? ", or take the passage." : ".");
  }
  if (legal.suggest) {
    return `In ${cardName(legal.suggest_room)}: choose a suspect and weapon in Cards & actions.`;
  }
  if (legal.moves.length) {
    return "Select a square or use arrow keys.";
  }
  if (legal.roll) {
    return legal.passage
      ? "Roll to move, or take the secret passage to the opposite corner."
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
    if (layout.passages.some((pair) => pair.includes(room.id))) {
      base.append(svgElement("text", {
        x: bounds.maxX + .65, y: bounds.minY + .65, class: "board-passage-mark",
      }, "↗"));
    }
  }
  map.append(base, svgElement("g", { id: dynamicId }));
}

function appendPawn(group, pawn, state, x, y, active, radius) {
  const style = pawnStyles[pawn.id];
  const description = `${pawn.name}, ${pawnController(pawn, state)}, ${boardLocation(pawn.location)}`;
  const marker = svgElement("g", { role: "img", "aria-label": description });
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

function renderBoard(state) {
  const panel = $("board-panel");
  panel.hidden = !state.board;
  if (!state.board) {
    lastBoardState = null;
    return;
  }
  const board = state.board;
  const key = JSON.stringify([board, state.legal, state.to_move, state.human_player, state.is_over, state.limit_reached]);
  if (key === lastBoardState) return;
  lastBoardState = key;
  const activeElement = document.activeElement;
  const restoreMoveFocus = panel.contains(activeElement) && activeElement?.hasAttribute("data-board-move");
  const actor = board.suspects.find((pawn) => pawn.seat === board.turn_player);
  setText("board-turn", actor ? `P${board.turn_player + 1} · ${actor.name}` : "Board");
  setText("board-instruction", boardInstruction(state));
  setText("board-remaining", board.phase === "move"
    ? `${board.remaining} step${board.remaining === 1 ? "" : "s"} left`
    : board.dice ? "Movement complete" : "Not rolled");
  $("board-dice").setAttribute("aria-label", board.dice
    ? `Dice: ${board.dice[0]} and ${board.dice[1]}` : "Dice not rolled");
  $("board-dice").querySelectorAll(".die").forEach((die, index) => {
    die.textContent = board.dice ? String(board.dice[index]) : "–";
  });
  $("board-roll-button").hidden = !state.legal.roll;
  $("board-passage-button").hidden = !state.legal.passage;
  $("board-end-button").hidden = !state.legal.end_turn;

  const displayLayout = state.board_rules && !state.board_rules.secret_passages
    ? { ...board.layout, passages: [] } : board.layout;
  const layoutKey = JSON.stringify(displayLayout);
  if (layoutKey !== lastBoardLayout) {
    buildBoardBase(displayLayout);
    lastBoardLayout = layoutKey;
  }
  const dynamic = $("board-dynamic");
  dynamic.replaceChildren();
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
    const pawns = board.suspects.filter((pawn) =>
      pawn.location.kind === "room" && pawn.location.room_id === room.id);
    const baseY = bounds.minY + Math.max(1.7, (bounds.maxY - bounds.minY + 1) / 2 + .35);
    pawns.forEach((pawn, index) => appendPawn(
      dynamic, pawn, state, center + (index % 3 - 1) * .75, baseY + Math.floor(index / 3) * .72,
      pawn.seat === board.turn_player, .34,
    ));
    const weapons = board.weapons.filter((weapon) => weapon.room_id === room.id);
    if (weapons.length) {
      dynamic.append(svgElement("text", {
        x: center, y: bounds.maxY + .78, class: "board-room-contents", "aria-hidden": "true",
      }, `◆ ${weapons.length} weapon${weapons.length === 1 ? "" : "s"}`));
    }
  }
  for (const pawn of board.suspects) {
    if (pawn.location.kind === "hallway") {
      appendPawn(dynamic, pawn, state, pawn.location.x + .5, pawn.location.y + .5,
        pawn.seat === board.turn_player, .42);
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
    const passage = displayLayout.passages.find((pair) => pair.includes(room.id));
    const item = document.createElement("li");
    const title = document.createElement("strong");
    title.textContent = `${room.name}: `;
    const contents = [
      pawnNames.length ? pawnNames.join(", ") : "no suspects",
      weaponNames.length ? weaponNames.join(", ") : "no weapons",
      ...(passage ? [`passage to ${cardName(passage.find((id) => id !== room.id))}`] : []),
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
      $("board-end-button").focus({ preventScroll: true });
    }
  }
}

function renderHand(state) {
  const container = $("hand-cards");
  container.replaceChildren();
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
    face.dataset.cardId = String(card.id);
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
      : `Player ${actor + 1} suggested these cards. Click a matching card you hold to reveal it.`;
    renderMiniCards(focusCards, state.activity?.cards || []);
  } else if (humanTurn && (legal.suggest || legal.accuse)) {
    const activity = state.activity;
    if (activity?.kind === "reveal") {
      $("card-interaction-title").textContent = "Latest reveal";
      renderActivityMeta(activity);
      $("card-interaction-hint").textContent = `Shown to Player ${activity.recipient + 1}.`;
      renderMiniCards(focusCards, [activity.card_id], activity.card_id);
    } else {
      $("card-interaction-title").textContent = legal.suggest
        ? "Build a suggestion"
        : "Build an accusation";
      if (activity?.kind === "refute" || activity?.kind === "reveal") {
        renderActivityMeta(activity);
      }
      $("card-interaction-hint").textContent = legal.suggest_room !== null
        ? `Suggestions must name ${cardName(legal.suggest_room)}. Accusations may name any room.`
        : "Select one suspect, weapon, and room from any card view.";
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
    const matchesRoom = legal.suggest_room === null || selectedCardIds.room === legal.suggest_room;
    const revealIsActive = activity?.kind === "reveal";
    $("card-suggest-button").hidden = !legal.suggest || (revealIsActive && !hasCombination);
    $("card-accuse-button").hidden = !legal.accuse || (revealIsActive && !hasCombination);
    $("card-suggest-button").disabled = !hasCombination || !matchesRoom;
    $("card-accuse-button").disabled = !hasCombination;
    $("use-room-button").hidden = !legal.suggest || legal.suggest_room === null || matchesRoom;
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
      hint = `Player ${activity.actor + 1} suggested these cards.`;
    } else if (activity?.kind === "accuse") {
      hint = `Player ${activity.actor + 1} accused this combination.`;
    } else if (activity?.kind === "refute") {
      hint = `Player ${activity.actor + 1} refuted Player ${activity.suggestion_actor + 1}'s suggestion.`;
    } else if (activity?.kind === "reveal") {
      hint = `Shown to Player ${activity.recipient + 1}.`;
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
  $("use-room-button").hidden = true;
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
  $("activity-player").textContent = `Player ${activity.actor + 1}`;
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
  $("notebook-instructions").hidden = state.notebook_mode !== "manual";
  const fingerprint = JSON.stringify([state.notebook_mode, state.num_players, state.matrix]);
  if (fingerprint === lastNotebookFingerprint) return;
  lastNotebookFingerprint = fingerprint;
  const focused = document.activeElement.closest("[data-notebook-card]");
  const focusCard = focused?.dataset.notebookCard;
  const focusHolder = focused?.dataset.notebookHolder;
  notebook.classList.toggle("manual-notebook", state.notebook_mode === "manual");
  notebook.replaceChildren();
  for (const type of ["suspect", "weapon", "room"]) {
    const category = document.createElement("section");
    category.className = `category-table ${type}`;
    const title = document.createElement("h4");
    title.textContent = type;
    category.append(title);
    const table = document.createElement("table");
    if (state.notebook_mode === "manual") {
      table.style.minWidth = `${Math.ceil(24 * (state.num_players + 1) / 0.52)}px`;
    }
    const head = document.createElement("thead");
    const body = document.createElement("tbody");
    const heading = document.createElement("tr");
    const cardHeading = document.createElement("th");
    cardHeading.textContent = "Card";
    heading.append(cardHeading);
    for (let seat = 0; seat < state.num_players; seat++) {
      const th = document.createElement("th");
      th.textContent = `P${seat + 1}`;
      heading.append(th);
    }
    const envelope = document.createElement("th");
    envelope.className = "matrix-envelope";
    envelope.setAttribute("aria-label", "Envelope");
    envelope.title = "Envelope";
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
      for (const [holder, mark] of card.marks.entries()) {
        const cell = document.createElement("td");
        cell.className = mark === "+" ? "mark-held" : mark === "-" ? "mark-not-held" : "mark-unknown";
        const meaning = mark === "+" ? "held" : mark === "-" ? "not held" : "unknown";
        const owner = holder === state.num_players ? "Envelope" : `Player ${holder + 1}`;
        if (card.editable[holder]) {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "notebook-mark";
          button.dataset.notebookCard = String(card.id);
          button.dataset.notebookHolder = String(holder);
          button.setAttribute("aria-label", `${card.name}, ${owner}: ${meaning}. Activate to change.`);
          button.title = `${card.name}, ${owner}: ${meaning}. Activate to change.`;
          button.textContent = mark;
          cell.append(button);
        } else {
          cell.textContent = mark;
          cell.setAttribute("aria-label", `${card.name}, ${owner}: ${meaning}`);
        }
        row.append(cell);
      }
      body.append(row);
    }
    table.append(head, body);
    category.append(table);
    notebook.append(category);
  }
  if (focusCard !== undefined) {
    notebook.querySelector(`[data-notebook-card="${focusCard}"][data-notebook-holder="${focusHolder}"]`)
      ?.focus({ preventScroll: true });
  }
}

function changeNotebook(cardId, holder) {
  const generation = notebookGeneration;
  notebookQueue = notebookQueue.then(async () => {
    if (generation !== notebookGeneration || !currentState) return;
    const card = currentState.matrix.find((item) => item.id === cardId);
    if (!card || !card.editable[holder]) return;
    const next = { "?": "+", "+": "-", "-": "?" }[card.marks[holder]];
    const result = await requestJson("/api/notebook", {
      method: "PUT", body: { card_id: cardId, holder, mark: next },
    });
    if (generation !== notebookGeneration || !currentState) return;
    if (result.notebook_revision >= currentState.notebook_revision) {
      currentState.matrix = result.matrix;
      currentState.notebook_revision = result.notebook_revision;
      renderState(currentState);
    }
    if (lastError.startsWith("Could not save notebook:")) showError("");
  }).catch((error) => {
    if (generation === notebookGeneration) showError(`Could not save notebook: ${error.message}`);
  });
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
  panel.replaceChildren();
  if (!debugInfo) return;
  const solution = debugInfo.solution.map(cardName).join(", ");
  const lines = [`WARNING: omniscient debug mode is enabled.`, `Solution: ${solution}`];
  debugInfo.hands.forEach((hand, seat) => {
    lines.push(`Player ${seat + 1} hand: ${hand.map(cardName).join(", ") || "(empty)"}`);
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
  if (advancing || submitting || !currentState) return;
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
  if (!currentState) return;
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

function newGame() {
  requestVersion++;
  sessionStorage.removeItem(activeGameKey);
  notebookGeneration++;
  notebookQueue = Promise.resolve();
  clearInterval(refreshTimer);
  currentState = null;
  clearSelectedCards();
  cardView = "hand";
  lastActivityKey = null;
  lastRenderedState = null;
  lastNotebookFingerprint = null;
  lastBoardState = null;
  lastBoardLayout = null;
  lastSuggestionRoom = null;
  hadReveal = false;
  hadBoardMovement = false;
  hadBoardResponse = false;
  lastError = "";
  document.body.classList.remove("game-active", "board-game", "manual-notebook-active");
  $("board-map-shell").classList.remove("zoomed");
  $("board-zoom-button").setAttribute("aria-pressed", "false");
  showError("");
  $("game-screen").hidden = true;
  $("setup-screen").hidden = false;
  window.setupWizard.beginFresh();
}

function configureBoardWorkspace(isBoard) {
  $("board-workspace-tabs").hidden = !isBoard;
  (isBoard ? $("notebook-heading-tools") : $("card-view-tabs")).append($("viewer-field"));
  if (isBoard) {
    for (const name of ["notebook", "cards", "insights", "locations"]) {
      const panel = $(name === "locations" ? "board-locations-panel" : `${name}-panel`);
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", `board-tab-${name}`);
    }
    switchBoardTab(narrowBoardLayout.matches ? "board" : "notebook");
  } else {
    for (const name of ["notebook", "cards", "insights", "locations"]) {
      const panel = $(name === "locations" ? "board-locations-panel" : `${name}-panel`);
      panel.removeAttribute("role");
      panel.removeAttribute("aria-labelledby");
      panel.hidden = name === "locations";
    }
    for (const name of ["board", "notebook"]) {
      const panel = $(`${name}-panel`);
      panel.removeAttribute("role");
      panel.setAttribute("aria-labelledby", `${name}-title`);
    }
    delete document.body.dataset.boardTab;
  }
}

function switchBoardTab(name) {
  if (!narrowBoardLayout.matches && name === "board") name = "notebook";
  document.body.dataset.boardTab = name;
  for (const item of boardTabs) {
    const tab = $(`board-tab-${item}`);
    tab.setAttribute("aria-selected", String(item === name));
    tab.tabIndex = item === name ? 0 : -1;
  }
  for (const item of ["notebook", "cards", "insights", "locations"]) {
    const panel = $(item === "locations" ? "board-locations-panel" : `${item}-panel`);
    panel.hidden = item !== name;
  }
  const boardPanel = $("board-panel");
  if (narrowBoardLayout.matches) {
    boardPanel.setAttribute("role", "tabpanel");
    boardPanel.setAttribute("aria-labelledby", "board-tab-board");
  } else {
    boardPanel.removeAttribute("role");
    boardPanel.setAttribute("aria-labelledby", "board-title");
  }
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
  if (persist) {
    if (window.clueOptions.desktop) {
      desktopThemeWrite = desktopThemeWrite
        .then(() => requestJson("/api/desktop/theme", {
          method: "POST", body: { theme: isDark ? "dark" : "light" },
        }))
        .catch((error) => showError(error.message));
    } else {
      localStorage.setItem("clue-engine-theme", isDark ? "dark" : "light");
    }
  }
}

setTheme(document.documentElement.dataset.theme);
$("setup-form").addEventListener("submit", startGame);
$("mode").addEventListener("change", updateMode);
for (const choice of document.querySelectorAll('input[name="game-type"]')) {
  choice.addEventListener("change", updateGameType);
}
$("players").addEventListener("input", updateGameType);
$("theme-toggle").addEventListener("click", () => {
  setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark", true);
});
$("notebook").addEventListener("click", (event) => {
  const button = event.target.closest("[data-notebook-card]");
  if (button) changeNotebook(Number(button.dataset.notebookCard), Number(button.dataset.notebookHolder));
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
$("card-accuse-button").addEventListener("click", () => {
  if (window.confirm("An incorrect accusation eliminates you. Continue?")) {
    submitAction({ action: "accuse", confirmed: true, ...selectedCombination() });
  }
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
$("board-end-button").addEventListener("click", () => submitAction({ action: "end_turn" }));
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
  const available = boardTabs.filter((name) => narrowBoardLayout.matches || name !== "board");
  const index = available.indexOf(tab.id.replace("board-tab-", ""));
  let next = null;
  if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
    const offset = event.key === "ArrowRight" ? 1 : -1;
    next = available[(index + offset + available.length) % available.length];
  } else if (event.key === "Home") next = available[0];
  else if (event.key === "End") next = available[available.length - 1];
  if (next === null) return;
  event.preventDefault();
  switchBoardTab(next);
  $(`board-tab-${next}`).focus();
});
narrowBoardLayout.addEventListener("change", () => {
  if (document.body.classList.contains("board-game")) {
    switchBoardTab(document.body.dataset.boardTab);
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
updateGameType();
restoreGame();
