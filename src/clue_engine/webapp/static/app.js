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
let refreshTimer = null;
let advancing = false;
let submitting = false;
let refreshing = false;
let requestVersion = 0;
let lastError = "";
let desktopThemeWrite = Promise.resolve();
let desktopFullscreen = false;
let fullscreenBusy = false;
let cardView = "hand";
let lastActivityKey = null;
let lastRenderedState = null;
let lastNotebookFingerprint = null;
let lastNotebookStructureFingerprint = null;
let lastNotebookMarks = null;
let lastNotebookDraft = null;
let lastClauseFingerprint = null;
let lastReplayDeductionFingerprint = null;
let lastDebugFingerprint = null;
let lastNotebookPerspective = null;
let selectedClause = null;
let clauseDraft = null;
let notebookGeneration = 0;
let notebookQueue = Promise.resolve();
let pendingNotebookEdits = [];
let lastBoardState = null;
let lastBoardLayout = null;
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

async function startGame(event) {
  event.preventDefault();
  const debug = $("debug").checked;
  if (debug && !await confirmAction("Debug mode reveals every hand, the solution, and private events. Continue?")) {
    $("debug").checked = false;
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
  lastSuggestionRoom = null;
  hadReveal = false;
  hadBoardResponse = false;
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
  clauseDraft = null;
  document.body.classList.add("game-active");
  document.body.classList.toggle("board-game", Boolean(state.board));
  document.body.classList.toggle("manual-notebook-active", state.notebook_mode === "manual");
  $("game-toolbar").append($("header-tools"));
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
  if (refreshing || submitting || replayMode || $("confirm-dialog").open) return;
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
  return !advancing && !submitting && !$("confirm-dialog").open && canAdvanceBot(state);
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
  if (state.board) {
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
  $("game-meta").textContent =
    `Actions: ${state.steps} · Player 1 turns: ${state.player0_turns}`
    + (state.paused ? " · Paused" : "")
    + (state.waiting_for_turn ? " · Waiting for next turn" : "")
    + ((state.board_rules && Object.entries(state.board_rules).some(([key, value]) =>
      ["move_suspect", "move_weapon", "summoned_suggestion", "secret_passages"].includes(key)
        ? !value : (key === "early_end" ? !value : value)))
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
  $("next-button").hidden = !(state.paused && canAdvanceBot(state));
  $("viewer-select").value = String(state.selected_player);
  $("viewer-field").hidden = state.mode !== "spectate";
  renderBoard(state);
  renderHand(state);
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
    const location = board.summoned_seats.includes(board.turn_player)
      ? `You were summoned to ${cardName(legal.suggest_room)}.`
      : `You are in ${cardName(legal.suggest_room)}.`;
    return `${location} Suggest there, roll to leave`
      + (legal.passage ? ", or take the passage." : ".");
  }
  if (legal.suggest) {
    return `In ${cardName(legal.suggest_room)}: choose a suspect and weapon in Cards & actions`
      + (legal.end_turn ? ", or end your turn." : ".");
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

function renderDice(dice) {
  const total = dice ? dice[0] + dice[1] : null;
  $("board-dice").setAttribute("aria-label", dice
    ? `Dice: ${dice[0]} and ${dice[1]}, total ${total}` : "Dice not rolled");
  $("board-dice").querySelectorAll(".die").forEach((die, index) => {
    die.textContent = dice ? String(dice[index]) : "–";
  });
  $("board-dice-total").hidden = total === null;
  setText("board-dice-total", total === null ? "" : `Total ${total}`);
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
  renderDice(board.dice);
  $("board-roll-button").hidden = !state.legal.roll;
  $("board-passage-button").hidden = !state.legal.passage;

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
      $("turn-button").focus({ preventScroll: true });
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
    const revealIsActive = activity?.kind === "reveal"
      && state.events.find((event) => event.kind === "show" || event.kind === "end_turn")?.kind === "show";
    if (revealIsActive) {
      $("card-interaction-title").textContent = "Latest reveal";
      renderActivityMeta(activity);
      $("card-interaction-hint").textContent = activity.public
        ? "Shown to everyone." : `Shown to Player ${activity.recipient + 1}.`;
      renderMiniCards(focusCards, [activity.card_id], activity.card_id);
    } else {
      $("card-interaction-title").textContent = legal.suggest
        ? "Build a suggestion"
        : "Build an accusation";
      if (activity?.kind === "refute") {
        renderActivityMeta(activity);
      }
      $("card-interaction-hint").textContent = legal.suggest_room !== null
        ? `Suggestions must name ${cardName(legal.suggest_room)}. Accusations may name any room.`
        : "Select one suspect, weapon, and room from any card view.";
    }
    for (const type of ["suspect", "weapon", "room"]) {
      const card = cardsById.get(selectedCardIds[type]);
      if (card) {
        if (revealIsActive) {
          const chip = document.createElement("span");
          chip.className = `card-reference ${type}`;
          chip.textContent = card.name;
          selectedCards.append(chip);
        } else {
          selectedCards.append(createCardFace(card, { mini: true }));
        }
      } else if (!revealIsActive) {
        const slot = document.createElement("div");
        slot.className = `selection-slot ${type}`;
        slot.textContent = type[0].toUpperCase() + type.slice(1);
        selectedCards.append(slot);
      }
    }
    if (revealIsActive) selectedCards.classList.add("reveal-selection");
    const hasCombination = Object.values(selectedCardIds).every((id) => id !== null);
    const matchesRoom = legal.suggest_room === null || selectedCardIds.room === legal.suggest_room;
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
      hint = activity.public ? "Shown to everyone." : `Shown to Player ${activity.recipient + 1}.`;
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

function notebookDisplayMatrix(state) {
  if (!pendingNotebookEdits.length || state.notebook_mode !== "manual" || state.is_replay) return state.matrix;
  const pending = new Map();
  for (const edit of pendingNotebookEdits) pending.set(`${edit.cardId}:${edit.holder}`, edit.mark);
  return state.matrix.map((card) => ({
    ...card,
    marks: card.marks.map((mark, holder) => pending.get(`${card.id}:${holder}`) ?? mark),
  }));
}

function updateNotebookMark(button, card, holder, mark, state, draft) {
  const cell = button.parentElement;
  cell.classList.remove("mark-held", "mark-not-held", "mark-unknown");
  cell.classList.add(mark === "+" ? "mark-held" : mark === "-" ? "mark-not-held" : "mark-unknown");
  const focus = state.notebook_focus || { cards: [] };
  const roles = [];
  if (holder === focus.turn) roles.push("turn owner");
  if (holder === focus.actor) roles.push("acting now");
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
  const focusCards = new Set(focus.cards);
  const matrix = notebookDisplayMatrix(state);
  updateClauseEntryControls(state);
  const fingerprint = JSON.stringify([
    state.notebook_mode, state.num_players, state.hand_sizes, matrix, state.notebook_clauses,
    state.notebook_focus, selectedClause, clauseDraft,
  ]);
  if (fingerprint === lastNotebookFingerprint) return;
  const structure = JSON.stringify([
    state.notebook_mode, state.num_players, state.hand_sizes,
    matrix.map(({ marks, ...card }) => card), state.notebook_clauses,
    state.notebook_focus, selectedClause, Boolean(clauseDraft),
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
        updateNotebookMark(button, card, holder, mark, state, draft);
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
    const roles = [];
    if (seat === focus.turn) {
      th.classList.add("notebook-turn");
      roles.push("turn owner");
    }
    if (seat === focus.actor) {
      th.classList.add("notebook-actor");
      roles.push("acting now");
    }
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
        const roles = [];
        if (holder === focus.turn) {
          cell.classList.add("notebook-turn");
          roles.push("turn owner");
        }
        if (holder === focus.actor) {
          cell.classList.add("notebook-actor");
          roles.push("acting now");
        }
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
      renderClauses(currentState);
      lastRenderedState = JSON.stringify(currentState);
    } else {
      renderNotebook(currentState);
    }
    if (lastError.startsWith("Could not save notebook:")) showError("");
  }).catch((error) => {
    if (generation === notebookGeneration) {
      pendingNotebookEdits = pendingNotebookEdits.filter((pending) => pending !== edit);
      if (currentState) renderNotebook(currentState);
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
  replayMode = false;
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
  $("setup-screen").hidden = false;
  window.setupWizard.beginFresh();
}

async function loadReplay() {
  if (!replayMode) return;
  const version = ++requestVersion;
  const params = new URLSearchParams({
    position: $("replay-position").value,
    player: $("replay-player").value,
    manual: $("replay-manual").checked ? "1" : "0",
    omniscient: $("replay-omniscient").checked ? "1" : "0",
  });
  try {
    const state = await requestJson(`/api/replay/state?${params}`);
    if (version !== requestVersion || !replayMode) return;
    currentState = state;
    $("replay-position").max = String(state.positions - 1);
    $("replay-manual").disabled = !state.manual_available;
    if (!state.manual_available) $("replay-manual").checked = false;
    renderReplayDeductions(state.deduction_timeline);
    renderState(state);
  } catch (error) {
    if (version === requestVersion) showError(error.message);
  }
}

function renderReplayDeductions(deductions) {
  const fingerprint = JSON.stringify(deductions);
  if (fingerprint === lastReplayDeductionFingerprint) return;
  lastReplayDeductionFingerprint = fingerprint;
  const list = $("replay-deductions");
  const focused = document.activeElement.closest("[data-replay-deduction]");
  const focusKey = focused?.dataset.replayDeduction;
  list.replaceChildren();
  if (!deductions.length) {
    list.textContent = "No envelope cards inferred yet.";
    return;
  }
  for (const deduction of deductions) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.replayDeduction = `${deduction.player}:${deduction.card}`;
    button.dataset.replayPosition = String(deduction.position);
    button.textContent = `Player ${deduction.player + 1}: ${cardName(deduction.card)}`
      + (deduction.step ? ` · action ${deduction.step}` : " · start");
    list.append(button);
  }
  if (focusKey) {
    list.querySelector(`[data-replay-deduction="${focusKey}"]`)?.focus({ preventScroll: true });
  }
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
  $("replay-position").value = "0";
  $("replay-player").replaceChildren(...Array.from(
    { length: currentState.num_players }, (_, seat) => option(seat, `Player ${seat + 1}`)
  ));
  $("replay-player").value = String(currentState.selected_player);
  $("replay-manual").checked = false;
  $("replay-omniscient").checked = false;
  await loadReplay();
}

async function closeReplay() {
  replayMode = false;
  document.body.classList.remove("replay-active");
  $("replay-controls").hidden = true;
  lastRenderedState = null;
  await refreshState();
}

function moveReplay(amount, turn = false) {
  if (!currentState?.is_replay) return;
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
  const board = document.body.classList.contains("board-game");
  for (const item of insightsTabs) {
    const active = item === name;
    $(`${item}-tab`).setAttribute("aria-selected", String(active));
    $(`${item}-tab`).tabIndex = active ? 0 : -1;
    $(`${item}-panel`).hidden = !active;
    $(`${item}-panel`).setAttribute("aria-labelledby", board ? `board-tab-${item}` : `${item}-tab`);
  }
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
  const button = $("fullscreen-toggle");
  button.textContent = fullscreen ? "Exit full screen" : "Full screen";
  button.setAttribute("aria-pressed", String(fullscreen));
}

async function initializeFullscreen() {
  if (!window.clueOptions.desktop) return;
  try {
    showFullscreenState(await window.pywebview.api.fullscreen_state());
    $("fullscreen-toggle").disabled = false;
  } catch (error) {
    showError(`Could not initialize full screen: ${error.message}`);
  }
}

async function toggleDesktopFullscreen() {
  if (fullscreenBusy || $("fullscreen-toggle").disabled) return;
  fullscreenBusy = true;
  $("fullscreen-toggle").disabled = true;
  try {
    showFullscreenState(await window.pywebview.api.toggle_fullscreen());
    if (lastError.startsWith("Could not change full screen:")) showError("");
  } catch (error) {
    showError(`Could not change full screen: ${error.message}`);
  } finally {
    fullscreenBusy = false;
    $("fullscreen-toggle").disabled = false;
  }
}

setTheme(document.documentElement.dataset.theme);
if (window.clueThemeStorageError) {
  showError(`Could not load saved theme: ${window.clueThemeStorageError}`);
}
window.addEventListener("pywebviewready", initializeFullscreen);
if (window.clueOptions.desktop && window.pywebview?.api) initializeFullscreen();
$("fullscreen-toggle").addEventListener("click", toggleDesktopFullscreen);
document.addEventListener("keydown", (event) => {
  if (!window.clueOptions.desktop || event.repeat || event.altKey || event.ctrlKey || event.metaKey
    || event.shiftKey || $("fullscreen-toggle").disabled || $("confirm-dialog").open) return;
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
$("mode").addEventListener("change", updateMode);
for (const choice of document.querySelectorAll('input[name="game-type"]')) {
  choice.addEventListener("change", updateGameType);
}
$("players").addEventListener("input", updateGameType);
$("theme-toggle").addEventListener("click", () => {
  setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark", true);
});
$("notebook").addEventListener("click", (event) => {
  const indicator = event.target.closest("[data-clause-card]");
  if (indicator && currentState) {
    selectedClause = Number(indicator.dataset.clauseId);
    $("clause-actor").value = "all";
    $("clause-kind").value = "all";
    renderNotebook(currentState);
    renderClauses(currentState);
    openClauses();
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
  event.currentTarget.closest("details").open = false;
  if (submitting || advancing) {
    showError("Wait for the current action to finish.");
    return;
  }
  if (await confirmAction("Start a new game and leave the current game?", {
    title: "New game", confirmLabel: "New game",
  })) newGame();
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
  event.currentTarget.closest("details").open = false;
  if (submitting || advancing) {
    showError("Wait for the current action to finish.");
    return;
  }
  if (!await confirmAction("End this game permanently and reveal all private information?", {
    title: "End and reveal", confirmLabel: "End and reveal",
  })) return;
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
$("replay-deductions").addEventListener("click", (event) => {
  const button = event.target.closest("[data-replay-position]");
  if (!button || !replayMode) return;
  $("replay-position").value = button.dataset.replayPosition;
  loadReplay();
});
for (const id of ["replay-position", "replay-player", "replay-manual", "replay-omniscient"]) {
  $(id).addEventListener("change", loadReplay);
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
  const index = insightsTabs.indexOf(tab.id.replace("-tab", ""));
  let next = null;
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    const offset = event.key === "ArrowDown" ? 1 : -1;
    next = insightsTabs[(index + offset + insightsTabs.length) % insightsTabs.length];
  } else if (event.key === "Home") next = insightsTabs[0];
  else if (event.key === "End") next = insightsTabs[insightsTabs.length - 1];
  if (!next) return;
  event.preventDefault();
  switchInsightsTab(next);
  $(`${next}-tab`).focus();
});
updateMode();
updateGameType();
restoreGame();
