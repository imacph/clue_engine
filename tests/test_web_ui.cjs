"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "..", "src", "clue_engine", "webapp", "static", "app.js"),
  "utf8",
);
const setupSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "clue_engine", "webapp", "static", "setup.js"),
  "utf8",
);
const startup = source.indexOf("\nsetTheme(document.documentElement.dataset.theme);");
assert.notEqual(startup, -1, "Could not find frontend initialization");

function frontend({ notebook = false, workspace = false, history = false } = {}) {
  const elements = new Map();
  function element() {
    const classes = new Set();
    return {
      children: [],
      textContent: "",
      hidden: false,
      disabled: false,
      dataset: {},
      style: {},
      classList: {
        add: (value) => classes.add(value),
        remove: (value) => classes.delete(value),
        contains: (value) => classes.has(value),
        toggle(value, enabled) { if (enabled) classes.add(value); else classes.delete(value); },
      },
      append(...children) { this.children.push(...children); },
      replaceChildren(...children) { this.children = children; },
      contains() { return false; },
      focus() {},
      setAttribute(name, value) { this[name] = value; },
      removeAttribute(name) { delete this[name]; },
      insertBefore() {},
      querySelector() { return null; },
    };
  }
  const document = {
    activeElement: { closest() { return null; } },
    body: element(),
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, element());
      return elements.get(id);
    },
    createElement(tag) { const result = element(); result.tagName = tag.toUpperCase(); return result; },
    querySelector() { return { content: "" }; },
  };
  document.getElementById("board-locations-panel").parentElement = element();
  const context = vm.createContext({
    document,
    window: {
      clueOptions: {
        cards: {
          suspect: [{ id: 0, name: "Miss Scarlet" }],
          weapon: [{ id: 7, name: "Dagger" }],
          room: [{ id: 12, name: "Kitchen" }, { id: 13, name: "Ballroom" }],
        },
      },
      matchMedia: () => ({ matches: false }),
    },
  });
  vm.runInContext(source.slice(0, startup), context);
  vm.runInContext(`
    renderBoard = renderHand = renderDebug =
      renderActions = appendCardReferences = () => {};
    cardIllustration = () => document.createElement("svg");
    createCardFace = (card) => {
      const face = document.createElement("article");
      face.textContent = card.name;
      return face;
    };
  `, context);
  if (!history) vm.runInContext("renderHistory = () => {}", context);
  if (!notebook) vm.runInContext("renderNotebook = () => {}", context);
  if (!workspace) vm.runInContext("switchBoardTab = () => {}", context);
  return {
    element: (id) => document.getElementById(id),
    render(state) {
      context.state = state;
      vm.runInContext("renderState(state)", context);
    },
    renderNotebook(state) {
      context.state = state;
      vm.runInContext("renderNotebook(state)", context);
    },
    accept(current, incoming) {
      context.current = current;
      context.incoming = incoming;
      return vm.runInContext("currentState = current; acceptState(incoming); currentState", context);
    },
    switchBoard(name) {
      document.body.classList.add("board-game");
      context.boardTab = name;
      vm.runInContext("switchBoardTab(boardTab)", context);
    },
    renderHistory(events, actor, kind) {
      document.getElementById("history-actor").value = actor;
      document.getElementById("history-kind").value = kind;
      context.events = events;
      vm.runInContext("renderHistory(events)", context);
    },
    evaluate(code) {
      return vm.runInContext(code, context);
    },
    async queueExclusions() {
      return vm.runInContext(`
        currentState = {
          notebook_mode: "manual", notebook_revision: 0, matrix: [],
          notebook_clauses: [{ id: 1, kind: "refute", holder: 1, cards: [0, 7, 12],
            status: "unresolved", excluded_cards: [] }],
        };
        renderState = () => {};
        globalThis.fetch = async (path, options) => {
          const body = JSON.parse(options.body);
          const clause = { ...currentState.notebook_clauses[0], ...body };
          return { ok: true, json: async () => ({
            matrix: [], notebook_revision: currentState.notebook_revision + 1,
            notebook_clauses: [clause],
          }) };
        };
        changeClause(1, (latest) => ({ excluded_cards: [...latest.excluded_cards, 0] }));
        changeClause(1, (latest) => ({ excluded_cards: [...latest.excluded_cards, 7] }));
        notebookQueue.then(() => currentState.notebook_clauses[0].excluded_cards);
      `, context);
    },
    async fullscreen(api) {
      context.window.clueOptions.desktop = true;
      context.window.pywebview = { api };
      context.document.getElementById("fullscreen-toggle").disabled = true;
      await vm.runInContext("initializeFullscreen()", context);
      return () => vm.runInContext("toggleDesktopFullscreen()", context);
    },
    select(suspect, weapon, room) {
      context.selection = { suspect, weapon, room };
      vm.runInContext(`
        Object.assign(selectedCardIds, selection);
        renderCardInteraction(state);
      `, context);
    },
  };
}

test("desktop full screen initializes, toggles, and reports failures", async () => {
  const ui = frontend();
  let fullscreen = true;
  const toggle = await ui.fullscreen({
    fullscreen_state: async () => fullscreen,
    toggle_fullscreen: async () => { fullscreen = !fullscreen; return fullscreen; },
  });
  const button = ui.element("fullscreen-toggle");
  assert.equal(button.textContent, "Exit full screen");
  assert.equal(button["aria-pressed"], "true");
  await toggle();
  assert.equal(button.textContent, "Full screen");
  assert.equal(button["aria-pressed"], "false");
  const failing = await ui.fullscreen({
    fullscreen_state: async () => false,
    toggle_fullscreen: async () => { throw new Error("native error"); },
  });
  await failing();
  assert.equal(button.disabled, false);
  assert.match(ui.element("error-message").textContent, /native error/);
});

test("dice display shows both results and total, and clears on a new roll", () => {
  const ui = frontend();
  const result = ui.evaluate(`(() => {
    const dice = [document.createElement("span"), document.createElement("span")];
    $("board-dice").querySelectorAll = () => dice;
    renderDice([3, 6]);
    const rolled = {
      label: $("board-dice")["aria-label"], values: dice.map((die) => die.textContent),
      total: $("board-dice-total").textContent, hidden: $("board-dice-total").hidden,
    };
    renderDice(null);
    return { rolled, empty: {
      label: $("board-dice")["aria-label"], values: dice.map((die) => die.textContent),
      total: $("board-dice-total").textContent, hidden: $("board-dice-total").hidden,
    } };
  })()`);
  assert.deepEqual(JSON.parse(JSON.stringify(result)), {
    rolled: { label: "Dice: 3 and 6, total 9", values: ["3", "6"], total: "Total 9", hidden: false },
    empty: { label: "Dice not rolled", values: ["–", "–"], total: "", hidden: true },
  });
});

test("wizard payload validates and synchronizes unvisited seat and bot defaults", () => {
  const start = setupSource.indexOf("  function payload() {");
  const end = setupSource.indexOf("  function renderReview()", start);
  assert.ok(start !== -1 && end !== -1);
  const context = vm.createContext({
    fields: {
      mode: { value: "play" }, "notebook-mode": { value: "manual" },
      players: { value: "6" }, seat: { value: "0" }, seed: { value: "42" },
      progress: { value: "turn" }, "max-steps": { value: "10000" }, debug: { checked: false },
    },
  });
  vm.runInContext(`
    const $ = (id) => fields[id];
    let bots = [], characters = [0, 1, 2, 3, 4, 5], valid = true, syncCount = 0;
    let lastError = "";
    const missingBoardSetup = "Board starting positions are unavailable. Reload the page and try again.";
    const validBasics = () => valid;
    const isBoard = () => true;
    const syncSeats = () => { syncCount++; while (bots.length < Number(fields.players.value)) bots.push("random"); };
    const copy = (value) => JSON.parse(JSON.stringify(value));
    const rules = () => ({ secret_passages: true });
    ${setupSource.slice(start, end)}
  `, context);
  const result = vm.runInContext("payload()", context);
  assert.equal(result.players, 6);
  assert.deepEqual(Array.from(result.bots), Array(6).fill("random"));
  assert.deepEqual(Array.from(result.seat_suspects), [0, 1, 2, 3, 4, 5]);
  assert.equal(vm.runInContext("syncCount", context), 1);
  vm.runInContext("valid = false", context);
  assert.throws(() => vm.runInContext("payload()", context), /Correct the game settings/);
  assert.equal(vm.runInContext("syncCount", context), 1);
  vm.runInContext("lastError = missingBoardSetup", context);
  assert.throws(() => vm.runInContext("payload()", context), /Board starting positions are unavailable/);
});

test("queued clause edits apply to the latest notebook state", async () => {
  const excluded = await frontend().queueExclusions();
  assert.deepEqual(Array.from(excluded), [0, 7]);
});

test("board workspace tabs leave the board and notebook independent", () => {
  const ui = frontend({ workspace: true });
  for (const name of ["cards", "history", "clauses", "locations", "help"]) {
    ui.switchBoard(name);
    assert.equal(ui.element("notebook-panel").hidden, false);
    assert.equal(ui.element("board-panel").hidden, false);
    assert.equal(ui.element("insights-panel").hidden, !["history", "clauses", "help"].includes(name));
    if (["history", "clauses", "help"].includes(name)) {
      assert.equal(ui.element("history-panel").hidden, name !== "history");
      assert.equal(ui.element("clauses-panel").hidden, name !== "clauses");
      assert.equal(ui.element("help-panel").hidden, name !== "help");
      assert.equal(ui.element("help-panel")["aria-labelledby"], "board-tab-help");
    }
    assert.equal(ui.element(`board-tab-${name}`)["aria-selected"], "true");
  }
});

test("cards-only help tab selects and labels its panel", () => {
  const ui = frontend();
  ui.evaluate('switchInsightsTab("help")');
  assert.equal(ui.element("help-panel").hidden, false);
  assert.equal(ui.element("help-panel")["aria-labelledby"], "help-tab");
  assert.equal(ui.element("history-panel").hidden, true);
  assert.equal(ui.element("clauses-panel").hidden, true);
  assert.equal(ui.element("help-tab")["aria-selected"], "true");
});

test("clause entry selects notebook cells, validates, saves and preserves exclusions on edit", async () => {
  const ui = frontend({ notebook: true });
  const result = await ui.evaluate(`(async () => {
    currentState = {
      notebook_mode: "manual", num_players: 2, notebook_revision: 0,
      matrix: [
        { id: 0, name: "Miss Scarlet", type: "suspect", marks: ["+", "?", "?"], editable: [false, true, true] },
        { id: 7, name: "Dagger", type: "weapon", marks: ["?", "?", "?"], editable: [true, true, true] },
        { id: 12, name: "Kitchen", type: "room", marks: ["?", "?", "?"], editable: [true, true, true] },
        { id: 13, name: "Ballroom", type: "room", marks: ["?", "?", "?"], editable: [true, true, true] },
      ],
      notebook_clauses: [],
    };
    renderState = () => {};
    const calls = [];
    globalThis.fetch = async (path, options) => {
      calls.push({ path, body: JSON.parse(options.body) });
      return { ok: true, json: async () => ({
        matrix: currentState.matrix, notebook_revision: currentState.notebook_revision + 1,
        notebook_clauses: currentState.notebook_clauses,
      }) };
    };
    const descendants = (node) => [node, ...node.children.flatMap(descendants)];
    renderNotebook(currentState);
    const fixedBefore = descendants($("notebook")).some((node) =>
      node.dataset.notebookCard === "0" && node.dataset.notebookHolder === "0");
    startClauseEntry();
    const draftLabel = $("clause-entry")["aria-label"];
    const legendHiddenInDraft = $("notebook-legend").hidden;
    const fixedInDraft = descendants($("notebook")).some((node) =>
      node.dataset.notebookCard === "0" && node.dataset.notebookHolder === "0");
    const initiallyDisabled = $("clause-entry").disabled;
    selectClauseCell(0, 0);
    selectClauseCell(7, 0);
    confirmClauseEntry();
    const incompleteError = $("error-message").textContent;
    selectClauseCell(12, 0);
    selectClauseCell(13, 0);
    selectClauseCell(13, 0);
    const deselected = clauseDraft.cards.room === undefined;
    selectClauseCell(12, 2);
    const holderChanged = clauseDraft.holder;
    confirmClauseEntry();
    await notebookQueue;
    const closedAfterSave = clauseDraft === null;
    const legendRestored = !$("notebook-legend").hidden;
    currentState.notebook_clauses = [{
      id: 4, kind: "refute", holder: 1, cards: [0, 7, 12], status: "resolved",
      active_cards: [], excluded_cards: [7, 12],
    }];
    startClauseEntry(currentState.notebook_clauses[0]);
    selectClauseCell(13, 1);
    confirmClauseEntry();
    await notebookQueue;
    return { fixedBefore, fixedInDraft, draftLabel, legendHiddenInDraft, legendRestored,
      initiallyDisabled, incompleteError, deselected, holderChanged, closedAfterSave, calls };
  })()`);
  assert.equal(result.fixedBefore, false);
  assert.equal(result.fixedInDraft, true);
  assert.equal(result.draftLabel, "Confirm clause");
  assert.equal(result.legendHiddenInDraft, true);
  assert.equal(result.legendRestored, true);
  assert.equal(result.initiallyDisabled, true);
  assert.match(result.incompleteError, /one suspect, one weapon, and one room/);
  assert.equal(result.deselected, true);
  assert.equal(result.holderChanged, 2);
  assert.equal(result.closedAfterSave, true);
  assert.deepEqual(JSON.parse(JSON.stringify(result.calls)), [
    { path: "/api/notebook/clauses", body: { kind: "accuse", holder: 2, cards: [0, 7, 12], resolved: false, excluded_cards: [] } },
    { path: "/api/notebook/clauses/4", body: { kind: "refute", holder: 1, cards: [0, 7, 13], resolved: true, excluded_cards: [7] } },
  ]);
});

test("clause highlighting can be cleared or switched", () => {
  const ui = frontend();
  const values = ui.evaluate(`(() => {
    const result = [selectedClause];
    toggleClauseHighlight(1); result.push(selectedClause);
    toggleClauseHighlight(2); result.push(selectedClause);
    toggleClauseHighlight(2); result.push(selectedClause);
    return result;
  })()`);
  assert.deepEqual(Array.from(values), [null, 1, 2, null]);
});

test("a failed clause save leaves the draft available for retry or cancellation", async () => {
  const ui = frontend({ notebook: true });
  const result = await ui.evaluate(`(async () => {
    currentState = { notebook_mode: "manual", num_players: 2, matrix: [], notebook_revision: 0, notebook_clauses: [] };
    globalThis.fetch = async () => { throw new Error("offline"); };
    startClauseEntry();
    selectClauseCell(0, 1); selectClauseCell(7, 1); selectClauseCell(12, 1);
    confirmClauseEntry();
    await notebookQueue;
    const retained = clauseDraft !== null && !clauseDraft.saving;
    const error = $("error-message").textContent;
    cancelClauseEntry();
    return { retained, error, cancelled: clauseDraft === null };
  })()`);
  assert.equal(result.retained, true);
  assert.match(result.error, /offline/);
  assert.equal(result.cancelled, true);
});

test("action history remains unfiltered and shows only the latest eight events", () => {
  const ui = frontend({ history: true });
  const events = Array.from({ length: 10 }, (_, index) => ({
    number: 10 - index, actor: index % 2, kind: "suggest", text: "Suggestion",
  }));
  ui.renderHistory(events, "1", "suggest");
  assert.equal(ui.element("history-list").children.length, 5);
  assert.equal(ui.element("action-history-list").children.length, 8);
  assert.equal(ui.element("action-history-list").children[0].children[0].textContent, "#10");
});

test("notebook renders overlapping clause references without replacing marks", () => {
  const ui = frontend({ notebook: true });
  const notebookState = {
    notebook_mode: "manual", num_players: 2,
    matrix: [
      { id: 0, name: "Miss Scarlet", type: "suspect", marks: ["?", "+", "?"], editable: [true, true, true] },
      { id: 7, name: "Dagger", type: "weapon", marks: ["?", "-", "?"], editable: [true, true, true] },
    ],
    notebook_clauses: [
      { id: 1, holder: 1, active_cards: [0, 7] },
      { id: 2, holder: 1, active_cards: [0] },
      { id: 3, holder: 1, active_cards: [] },
    ],
  };
  ui.renderNotebook(notebookState);
  function descendants(node) {
    return [node, ...node.children.flatMap(descendants)];
  }
  const all = descendants(ui.element("notebook"));
  assert.equal(all.filter((node) => node.tagName === "TABLE").length, 1);
  assert.equal(all.filter((node) => node.tagName === "THEAD").length, 1);
  assert.equal(all.filter((node) => node.tagName === "TBODY").length, 3);
  const table = all.find((node) => node.tagName === "TABLE");
  assert.equal(table.children[0].children[0].children.length, 4);
  assert.deepEqual(
    table.children.slice(1).map((body) => body.children[0].children[0].colSpan),
    [4, 4, 4],
  );
  const links = all.filter((node) => node.dataset.clauseId);
  assert.deepEqual(links.map((node) => node.textContent), ["#1", "#2", "#1"]);
  const mark = all.find((node) => node.dataset.notebookCard === "0" && node.dataset.notebookHolder === "1");
  assert.equal(mark.textContent, "+");
  notebookState.notebook_clauses[0].active_cards = [];
  ui.renderNotebook(notebookState);
  const remaining = descendants(ui.element("notebook")).filter((node) => node.dataset.clauseId);
  assert.deepEqual(remaining.map((node) => node.textContent), ["#2"]);
});

test("stale refresh preserves the entire manual notebook snapshot", () => {
  const ui = frontend();
  const current = {
    notebook_mode: "manual", notebook_revision: 3, matrix: ["new"],
    notebook_clauses: [{ id: 2 }],
  };
  const incoming = {
    notebook_mode: "manual", notebook_revision: 2, matrix: ["old"],
    notebook_clauses: [{ id: 1 }],
  };
  const accepted = ui.accept(current, incoming);
  assert.deepEqual(accepted.matrix, ["new"]);
  assert.deepEqual(accepted.notebook_clauses, [{ id: 2 }]);
  assert.equal(accepted.notebook_revision, 3);
});

function state(overrides = {}) {
  return {
    mode: "play",
    to_move: 0,
    human_player: 0,
    is_over: false,
    limit_reached: false,
    waiting_for_turn: false,
    paused: false,
    board: {},
    board_rules: {},
    steps: 2,
    player0_turns: 1,
    selected_player: 0,
    status: "Player 0",
    clauses: "",
    events: [
      { kind: "move" }, { kind: "roll" }, { kind: "end_turn" },
      { kind: "end_turn" }, { kind: "end_turn" }, { kind: "show" },
    ],
    activity: { kind: "reveal", actor: 1, suggestion_actor: 0, recipient: 0, card_id: 7 },
    legal: {
      reveals: [], pass: false, roll: false, passage: false, moves: [],
      suggest: true, accuse: true, suggest_room: 12,
    },
    ...overrides,
  };
}

test("a previous-turn reveal does not hide a new room suggestion", () => {
  const ui = frontend();
  ui.render(state());
  assert.equal(ui.element("card-interaction-title").textContent, "Build a suggestion");
  assert.equal(ui.element("card-suggest-button").hidden, false);
  assert.equal(ui.element("card-suggest-button").disabled, true);
  assert.deepEqual(
    ui.element("selected-cards").children.map((child) => child.textContent),
    ["Suspect", "Weapon", "Kitchen"],
  );
  ui.select(0, 7, 12);
  assert.equal(ui.element("card-suggest-button").disabled, false);
  assert.equal(ui.element("card-accuse-button").disabled, false);
  ui.select(0, 7, 13);
  assert.equal(ui.element("card-suggest-button").disabled, true);
  assert.equal(ui.element("card-accuse-button").disabled, false);
  assert.equal(ui.element("use-room-button").hidden, false);
});

test("the builder replaces the previous reveal as the next room turn begins", () => {
  const ui = frontend();
  ui.render(state({
    events: [{ kind: "show" }, { kind: "refute" }, { kind: "suggest" }],
    legal: {
      reveals: [], pass: false, roll: false, passage: false, moves: [],
      suggest: false, accuse: true, suggest_room: null,
    },
  }));
  assert.equal(ui.element("card-interaction-title").textContent, "Latest reveal");
  ui.render(state());
  assert.equal(ui.element("card-interaction-title").textContent, "Build a suggestion");
  assert.equal(ui.element("selected-cards").children[2].textContent, "Kitchen");
});

test("a previous-turn reveal does not hide the card-only suggestion builder", () => {
  const ui = frontend();
  ui.render(state({
    board: null,
    legal: {
      reveals: [], pass: false, roll: false, passage: false, moves: [],
      suggest: true, accuse: true, suggest_room: null,
    },
  }));
  assert.equal(ui.element("card-interaction-title").textContent, "Build a suggestion");
  assert.equal(ui.element("card-suggest-button").hidden, false);
  assert.deepEqual(
    ui.element("selected-cards").children.map((child) => child.textContent),
    ["Suspect", "Weapon", "Room"],
  );
});

test("a reveal made in the current turn stays visible", () => {
  const ui = frontend();
  ui.render(state({
    events: [{ kind: "show" }, { kind: "refute" }, { kind: "suggest" }, { kind: "end_turn" }],
    legal: {
      reveals: [], pass: false, roll: false, passage: false, moves: [],
      suggest: false, accuse: true, suggest_room: null,
    },
  }));
  assert.equal(ui.element("card-interaction-title").textContent, "Latest reveal");
  assert.equal(ui.element("focus-cards").children[0].textContent, "Dagger");
  assert.equal(ui.element("card-accuse-button").hidden, true);
  ui.select(0, 7, 12);
  assert.equal(ui.element("card-accuse-button").hidden, false);
  assert.equal(ui.element("card-accuse-button").disabled, false);
});

test("the previous reveal remains visible while waiting for the next turn", () => {
  const ui = frontend();
  ui.render(state({ to_move: 1, waiting_for_turn: true }));
  assert.equal(ui.element("card-interaction-title").textContent, "Latest reveal");
  assert.equal(ui.element("focus-cards").children[0].textContent, "Dagger");
  assert.equal(ui.element("card-suggest-button").hidden, true);
});

test("spectators can still review a selected player's reveal", () => {
  const ui = frontend();
  ui.render(state({ mode: "spectate", human_player: null, to_move: 1 }));
  assert.equal(ui.element("card-interaction-title").textContent, "Latest reveal");
  assert.equal(ui.element("focus-cards").children[0].textContent, "Dagger");
  assert.equal(ui.element("card-suggest-button").hidden, true);
});
