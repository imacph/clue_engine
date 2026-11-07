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
const startup = source.indexOf("\nsetTheme(document.documentElement.dataset.theme);");
assert.notEqual(startup, -1, "Could not find frontend initialization");

function frontend({ notebook = false } = {}) {
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
      setAttribute(name, value) { this[name] = value; },
      querySelector() { return null; },
    };
  }
  const document = {
    activeElement: { closest() { return null; } },
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, element());
      return elements.get(id);
    },
    createElement: element,
    querySelector() { return { content: "" }; },
  };
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
    renderBoard = renderHand = renderHistory = renderDebug =
      renderActions = switchBoardTab = appendCardReferences = () => {};
    cardIllustration = () => document.createElement("svg");
    createCardFace = (card) => {
      const face = document.createElement("article");
      face.textContent = card.name;
      return face;
    };
  `, context);
  if (!notebook) vm.runInContext("renderNotebook = () => {}", context);
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
    select(suspect, weapon, room) {
      context.selection = { suspect, weapon, room };
      vm.runInContext(`
        Object.assign(selectedCardIds, selection);
        renderCardInteraction(state);
      `, context);
    },
  };
}

test("notebook renders overlapping clause references without replacing marks", () => {
  const ui = frontend({ notebook: true });
  const notebookState = {
    notebook_mode: "manual", num_players: 2,
    matrix: [
      { id: 0, name: "Miss Scarlet", type: "suspect", marks: ["?", "+"], editable: [true, true] },
      { id: 7, name: "Dagger", type: "weapon", marks: ["?", "-"], editable: [true, true] },
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
