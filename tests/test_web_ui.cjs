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
const learnedHelpers = setupSource.slice(
  setupSource.indexOf("  const learnedDefaults ="),
  setupSource.indexOf("  const weights ="),
);
const stylesheet = fs.readFileSync(
  path.join(__dirname, "..", "src", "clue_engine", "webapp", "static", "style.css"),
  "utf8",
);
const template = fs.readFileSync(
  path.join(__dirname, "..", "src", "clue_engine", "webapp", "templates", "index.html"),
  "utf8",
);
const startup = source.indexOf("\nsetTheme(document.documentElement.dataset.theme);");
assert.notEqual(startup, -1, "Could not find frontend initialization");

test("room-start suggestion explains whether the player was summoned", () => {
  const start = source.indexOf("function boardInstruction(state)");
  const end = source.indexOf("\nfunction roomBounds(", start);
  assert.ok(start >= 0 && end > start);
  const context = vm.createContext({ cardName: () => "Kitchen" });
  vm.runInContext(source.slice(start, end), context);
  const state = {
    board: { turn_player: 0, summoned_seats: [] },
    human_player: 0, to_move: 0,
    legal: { suggest: true, roll: true, suggest_room: 12, passage: false },
  };
  assert.match(context.boardInstruction(state), /^You are in Kitchen/);
  state.board.summoned_seats = [0];
  assert.match(context.boardInstruction(state), /^You were summoned to Kitchen/);
});

function frontend({ notebook = false, workspace = false, history = false, debug = false, board = false, cards = false } = {}) {
  const elements = new Map();
  const timers = new Map();
  let nextTimer = 0;
  function element() {
    const classes = new Set();
    return {
      children: [],
      textContent: "",
      hidden: false,
      disabled: false,
      dataset: {},
      style: { setProperty(name, value) { this[name] = value; } },
      classList: {
        add: (value) => classes.add(value),
        remove: (value) => classes.delete(value),
        contains: (value) => classes.has(value),
        toggle(value, enabled) { if (enabled) classes.add(value); else classes.delete(value); },
      },
      append(...children) {
        for (const child of children) child.parentElement = this;
        this.children.push(...children);
      },
      prepend(...children) {
        for (const child of children) child.parentElement = this;
        this.children.unshift(...children);
      },
      replaceChildren(...children) {
        for (const child of children) child.parentElement = this;
        this.children = children;
      },
      contains() { return false; },
      focus() {},
      addEventListener() {},
      remove() {
        if (this.parentElement) {
          this.parentElement.children = this.parentElement.children.filter((child) => child !== this);
        }
      },
      setAttribute(name, value) { this[name] = value; },
      getAttribute(name) { return this[name]; },
      removeAttribute(name) { delete this[name]; },
      insertBefore() {},
      querySelector(selector) {
        if (selector === ".card-annotations" || selector === ".card-topline") {
          const name = selector.slice(1);
          for (const child of this.children) {
            if (child.className === name) return child;
            const nested = child.querySelector?.(selector);
            if (nested) return nested;
          }
        }
        return null;
      },
      querySelectorAll(selector) {
        const result = [];
        function visit(node) {
          for (const child of node.children) {
            const name = selector.startsWith(".") ? selector.slice(1) : "";
            if (name && (child.classList.contains(name)
              || String(child.className || "").split(/\s+/).includes(name))) {
              result.push(child);
            }
            visit(child);
          }
        }
        visit(this);
        return result;
      },
      get childElementCount() { return this.children.length; },
    };
  }
  const document = {
    activeElement: { closest() { return null; } },
    body: element(),
    getElementById(id) {
      if (id === "board-room-notes" && !board) return null;
      if (!elements.has(id)) elements.set(id, element());
      return elements.get(id);
    },
    createElement(tag) { const result = element(); result.tagName = tag.toUpperCase(); return result; },
    createElementNS(namespace, tag) { const result = element(); result.tagName = tag.toUpperCase(); return result; },
    querySelector() { return { content: "" }; },
  };
  document.getElementById("board-locations-panel").parentElement = element();
  const context = vm.createContext({
    document,
    URLSearchParams,
    performance: { now: () => 10000 },
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
    setTimeout(callback, delay) {
      const id = ++nextTimer;
      timers.set(id, { callback, delay });
      return id;
    },
    clearTimeout(id) { timers.delete(id); },
  });
  vm.runInContext(source.slice(0, startup), context);
  vm.runInContext(`
    ${board ? "" : "renderBoard = "}${cards ? "" : "renderHand = "}renderActions = appendCardReferences = () => {};
    cardIllustration = () => document.createElement("svg");
    ${cards ? "" : `
    createCardFace = (card) => {
      const face = document.createElement("article");
      face.textContent = card.name;
      return face;
    };
    updateCardNotes = () => {};
    `}
  `, context);
  if (!history) vm.runInContext("renderHistory = () => {}", context);
  if (!notebook) vm.runInContext("renderNotebook = () => {}", context);
  if (!workspace) vm.runInContext("switchBoardTab = () => {}", context);
  if (!debug) vm.runInContext("renderDebug = () => {}", context);
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
    renderHistory(events, actors, kinds) {
      context.state = {
        num_players: Math.max(...events.map((event) => event.actor)) + 1,
        board: events.some((event) => ["roll", "move", "passage", "suspect_moved", "weapon_moved"]
          .includes(event.kind)) ? {} : null,
      };
      vm.runInContext("buildPlayerFilters(state)", context);
      for (const [id, selected] of [
        ["history-actor", actors],
        ["history-kind", kinds],
      ]) {
        const filter = document.getElementById(id);
        for (const label of filter.children) {
          const input = label.children[0];
          input.checked = selected === undefined || selected.map(String).includes(input.value);
        }
      }
      context.events = events;
      vm.runInContext("currentState = { events }; renderHistory(events)", context);
    },
    evaluate(code) {
      return vm.runInContext(code, context);
    },
    timers,
    async queueExclusions() {
      return vm.runInContext(`
        currentState = {
          notebook_mode: "manual", notebook_revision: 0, matrix: [],
          notebook_clauses: [{ id: 1, kind: "refute", holder: 1, cards: [0, 7, 12],
            active_cards: [0, 7, 12], status: "unresolved", excluded_cards: [] }],
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
        notebookQueue.then(() => ({
          excluded: currentState.notebook_clauses[0].excluded_cards, error: $("error-message").textContent,
        }));
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

test("theme controls stay synchronized in the main menu and game options", () => {
  const ui = frontend();
  const result = ui.evaluate(`(() => {
    document.documentElement = { dataset: {} };
    setTheme("dark");
    const dark = ["theme-toggle", "game-theme-toggle"].map((id) => $(id).textContent);
    setTheme("light");
    return { dark, light: ["theme-toggle", "game-theme-toggle"].map((id) => $(id).textContent) };
  })()`);
  assert.deepEqual(JSON.parse(JSON.stringify(result)), {
    dark: ["Light mode", "Light mode"], light: ["Dark mode", "Dark mode"],
  });
});

test("dice display shows both results and total, and clears on a new roll", () => {
  const ui = frontend();
  const result = ui.evaluate(`(() => {
    const dice = [document.createElement("span"), document.createElement("span")];
    $("board-dice").querySelectorAll = () => dice;
    renderDice([3, 6]);
    const rolled = {
      label: $("board-dice")["aria-label"], values: dice.map((die) => die.dataset.value),
      total: $("board-dice-total").textContent, hidden: $("board-dice-total").hidden,
    };
    renderDice(null);
    return { rolled, empty: {
      label: $("board-dice")["aria-label"], values: dice.map((die) => die.dataset.value),
      total: $("board-dice-total").textContent, hidden: $("board-dice-total").hidden,
    } };
  })()`);
  assert.deepEqual(JSON.parse(JSON.stringify(result)), {
    rolled: { label: "Dice: 3 and 6, total 9", values: ["3", "6"], total: "9", hidden: false },
    empty: { label: "Dice not rolled", values: ["0", "0"], total: "–", hidden: false },
  });
});

test("dice animate new forward rolls without restarting on rerenders or reduced motion", () => {
  const ui = frontend();
  const result = ui.evaluate(`(() => {
    let animations = 0, reduced = false;
    window.matchMedia = () => ({ matches: reduced });
    const dice = [document.createElement("span"), document.createElement("span")];
    dice.forEach((die) => {
      die.getAnimations = () => [];
      die.animate = () => { animations++; };
    });
    $("board-dice").querySelectorAll = () => dice;
    const board = { dice: [2, 4], turn_player: 1 };
    const previous = { dice: null, turn: 1 };
    const roll = isDiceRoll(board, previous, true);
    renderDice(board.dice, roll);
    renderDice(board.dice, isDiceRoll(board, { dice: [2, 4], turn: 1 }, true));
    const beforeReduced = animations;
    reduced = true;
    renderDice(board.dice, true);
    return { roll, beforeReduced, animations,
      sameValuesNextTurn: isDiceRoll(board, { dice: [2, 4], turn: 0 }, true),
      backward: isDiceRoll(board, previous, false),
      initial: isDiceRoll(board, null, true) };
  })()`);
  assert.deepEqual(JSON.parse(JSON.stringify(result)), {
    roll: true, beforeReduced: 2, animations: 2,
    sameValuesNextTurn: true, backward: false, initial: false,
  });
});

test("board animation converts screen displacement to SVG coordinates", () => {
  const ui = frontend();
  const result = ui.evaluate(`[
    boardAnimationOffset(20, -30, { a: 10, b: 0, c: 0, d: 10 }),
    boardAnimationOffset(6, 8, { a: 0, b: 2, c: -2, d: 0 }),
    boardAnimationOffset(1, 1, { a: 0, b: 0, c: 0, d: 0 }),
    boardAnimationOffset(1, 1, null)
  ]`);
  assert.deepEqual(JSON.parse(JSON.stringify(result)), [{ x: 2, y: -3 }, { x: 4, y: -3 }, null, null]);
});

test("active pawn gets an accessible turn label without extra circle overlays", () => {
  const ui = frontend();
  const result = ui.evaluate(`(() => {
    document.createElementNS = (_, name) => document.createElement(name);
    const group = document.createElement("g");
    const pawn = { id: 0, name: "Miss Scarlet", seat: 0, location: { kind: "hallway", x: 1, y: 2 } };
    appendPawn(group, pawn, { human_player: 0 }, 1.5, 2.5, true, .42);
    const marker = group.children[0];
    const circles = marker.children.filter((child) => child.tagName === "CIRCLE");
    return { label: marker["aria-label"], classes: marker.children.map((child) => child.class),
      circleCount: circles.length, radius: circles[0].r };
  })()`);
  assert.match(result.label, /current turn/);
  assert.ok(result.classes.includes("board-pawn board-pawn-active"));
  assert.equal(result.circleCount, 1);
  assert.equal(result.radius, "0.42");
});

test("board passage pairs have matching letters and no markers when passages are disabled", () => {
  const ui = frontend();
  const result = ui.evaluate(`(() => {
    document.createElementNS = (_, name) => document.createElement(name);
    const map = document.createElement("svg");
    const rooms = [12, 13, 14, 15, 16].map((id, i) => ({
      id, name: "Room " + id, squares: [{ x: i * 2, y: 0 }],
    }));
    const layout = { width: 10, height: 1, rooms, hallways: [], walls: [],
      passages: [[12, 14], [13, 15]] };
    buildBoardBase(layout, map);
    const labels = map.children[0].children.filter((child) => child.class === "board-passage-mark")
      .map((group) => [group["data-passage"], group.children[1].textContent]);
    buildBoardBase({ ...layout, passages: [] }, map);
    return { labels, disabled: map.children[0].children.filter(
      (child) => child.class === "board-passage-mark").length };
  })()`);
  assert.deepEqual(JSON.parse(JSON.stringify(result)), {
    labels: [["0", "A"], ["1", "B"], ["0", "A"], ["1", "B"]], disabled: 0,
  });
});

test("board card browser reserves stable space and keeps history independent of card count", () => {
  assert.match(stylesheet, /flex:\s*0 0 clamp\(153px,\s*calc\(100% - 486px\),\s*315px\)/);
  assert.match(stylesheet, /\.card-interaction-stage\s*\{\s*height:\s*150px/);
  assert.match(stylesheet, /body\.game-active\.board-game \.action-history\s*\{\s*flex:\s*1 0 140px/);
  assert.doesNotMatch(stylesheet, /mini-card \.card-topline\s*\{\s*display:\s*none/);
});

test("board turn highlight follows the notebook through review, next turn, replay and game end", () => {
  const ui = frontend({ board: true });
  const result = ui.evaluate(`(() => {
    document.createElementNS = (_, name) => document.createElement(name);
    document.createTextNode = (text) => ({ textContent: text });
    buildBoardBase = () => {};
    renderDice = () => {};
    $("board-dynamic").querySelectorAll = () => [];
    const state = {
      board: { turn_player: 1, phase: "roll", dice: null, visited: [], weapons: [],
        layout: { rooms: [], doors: [], passages: [] },
        suspects: [
          { id: 0, name: "Miss Scarlet", seat: 0, location: { kind: "hallway", x: 1, y: 1 } },
          { id: 1, name: "Colonel Mustard", seat: 1, location: { kind: "hallway", x: 2, y: 1 } },
          { id: 2, name: "Mrs. White", seat: null, location: { kind: "hallway", x: 3, y: 1 } },
        ] },
      legal: { moves: [] }, to_move: 1, human_player: 0, steps: 1,
      waiting_for_turn: true, notebook_focus: { turn: 0 },
    };
    const snapshot = () => ({
      label: $("board-turn-label").textContent, turn: $("board-turn").textContent,
      active: $("board-dynamic").children.filter((pawn) =>
        pawn.children.some((child) => child.class?.includes("board-pawn-active")))
        .map((pawn) => pawn.dataset.pawnId),
    });
    renderBoard(state);
    const review = snapshot();
    state.waiting_for_turn = false;
    state.notebook_focus.turn = 1;
    renderBoard(state);
    const next = snapshot();
    state.is_replay = true;
    state.position = 2;
    state.notebook_focus.turn = 0;
    renderBoard(state);
    const replay = snapshot();
    state.is_replay = false;
    state.is_over = true;
    state.status = "Game over";
    state.notebook_focus.turn = null;
    renderBoard(state);
    return { review, next, replay, ended: snapshot() };
  })()`);
  assert.deepEqual(JSON.parse(JSON.stringify(result)), {
    review: { label: "Turn review", turn: "P1 · Miss Scarlet", active: ["0"] },
    next: { label: "Current turn", turn: "P2 · Colonel Mustard", active: ["1"] },
    replay: { label: "Current turn", turn: "P1 · Miss Scarlet", active: ["0"] },
    ended: { label: "Current turn", turn: "Board", active: [] },
  });
});

test("suggestion cards fly from the actor's pawn and clean up", () => {
  const ui = frontend();
  const result = ui.evaluate(`(() => {
    const records = [];
    const pawn = { getClientRects: () => [1],
      getBoundingClientRect: () => ({ left: 100, top: 200, width: 20, height: 20 }) };
    $("board-dynamic").querySelector = () => pawn;
    const card = { getClientRects: () => [1],
      getBoundingClientRect: () => ({ left: 300, top: 400, width: 100, height: 80 }),
      animate: (frames, options) => records.push({ target: true, frames, options }),
      cloneNode: () => ({
        style: {}, classList: { add() {} }, setAttribute() {},
        remove() { records.push({ removed: true }); },
        animate(frames, options) {
          records.push({ frames, options });
          return { finished: new Promise(() => {}), cancel() { records.push({ cancelled: true }); } };
        },
      }) };
    animateSuggestionFromBoard({ board: { suspects: [{ id: 2, seat: 1 }] },
      activity: { actor: 1 } }, { children: [card] });
    clearSuggestionFlights();
    return records;
  })()`);
  assert.equal(result[0].frames[0].transform, "translate(-240px, -230px) scale(.25)");
  assert.equal(result[0].options.duration, 850);
  assert.equal(result[1].target, true);
  assert.equal(result[2].cancelled, true);
  assert.equal(result[3].removed, true);
});

test("automatic bot responses wait for suggestion flights, but manual advancement remains available", () => {
  const ui = frontend();
  const result = ui.evaluate(`(() => {
    const state = { waiting_for_turn: false, is_over: false, limit_reached: false,
      human_player: 0, to_move: 1 };
    const before = shouldAdvance(state);
    suggestionFlights.push({ node: { remove() {} }, animation: { cancel() {} } });
    const during = shouldAdvance(state);
    const manual = canAdvanceBot(state);
    clearSuggestionFlights();
    return [before, during, manual, shouldAdvance(state)];
  })()`);
  assert.deepEqual(Array.from(result), [true, false, true, true]);
});

test("suggestions and reveals have a readable automatic pause, including with reduced motion", () => {
  const ui = frontend();
  const result = ui.evaluate(`(() => {
    let now = 10000;
    performance.now = () => now;
    window.matchMedia = () => ({ matches: true });
    const state = { waiting_for_turn: false, is_over: false, limit_reached: false,
      human_player: 0, to_move: 1, selected_player: 0, steps: 1,
      activity: { kind: "suggest", actor: 0, cards: [0, 7, 12] },
      events: [{ kind: "suggest", number: 1 }] };
    const values = [cardAnimationKind(state), shouldAdvance(state), canAdvanceBot(state)];
    now += 799;
    values.push(shouldAdvance(state));
    now++;
    values.push(shouldAdvance(state));
    state.steps++;
    state.activity = { kind: "reveal", actor: 1, card_id: 7 };
    state.events.unshift({ kind: "show", number: 2 });
    values.push(cardAnimationKind(state), shouldAdvance(state));
    now += 800;
    values.push(shouldAdvance(state));
    return values;
  })()`);
  assert.deepEqual(Array.from(result), [null, false, true, false, true, null, false, true]);
});

test("consecutive passes stay visible and each receives its own automatic reading pause", () => {
  const ui = frontend();
  const result = ui.evaluate(`(() => {
    let now = 10000;
    performance.now = () => now;
    window.matchMedia = () => ({ matches: true });
    const state = { mode: "spectate", human_player: null, to_move: 1, selected_player: 0,
      hand: [], matrix: [], num_players: 4, legal: { reveals: [], pass: false },
      steps: 1, activity_event_number: 1,
      activity: { kind: "suggest", actor: 0, cards: [0, 7, 12] },
      events: [{ kind: "suggest", actor: 0, number: 1 }] };
    renderCardInteraction(state);
    now += 1000;
    state.steps++;
    state.events.unshift({ kind: "pass", actor: 1, number: 2 });
    renderCardInteraction(state);
    const first = { kind: $("activity-kind").textContent, actor: $("activity-player").textContent,
      passes: $("activity-passes").textContent,
      cards: $("focus-cards").children.length, waiting: !shouldAdvance(state) };
    now += 1199;
    const stillWaiting = !shouldAdvance(state);
    now++;
    const ready = shouldAdvance(state);
    state.steps++;
    state.events.unshift({ kind: "pass", actor: 2, number: 3 });
    renderCardInteraction(state);
    const second = { kind: $("activity-kind").textContent, actor: $("activity-player").textContent,
      passes: $("activity-passes").textContent, waiting: !shouldAdvance(state) };
    return { first, stillWaiting, ready, second, manual: canAdvanceBot(state) };
  })()`);
  assert.deepEqual(JSON.parse(JSON.stringify(result)), {
    first: { kind: "Pass", actor: "Player 2 · suggestion P1",
      passes: "Passed: P2", cards: 3, waiting: true },
    stillWaiting: true, ready: true,
    second: { kind: "Pass", actor: "Player 3 · suggestion P1", passes: "Passed: P2 · P3", waiting: true },
    manual: true,
  });
});

test("passes remain understandable for a human responder and after an unanswered suggestion", () => {
  const ui = frontend();
  const result = ui.evaluate(`(() => {
    const state = { mode: "play", human_player: 0, to_move: 0, selected_player: 0,
      hand: [], matrix: [], num_players: 3, steps: 2, activity_event_number: 1,
      activity: { kind: "suggest", actor: 2, cards: [0, 7, 12] },
      events: [{ kind: "pass", actor: 1, number: 2 }, { kind: "suggest", actor: 2, number: 1 }],
      legal: { reveals: [{ id: 7 }], pass: false, suggest: false, accuse: false } };
    renderCardInteraction(state);
    const response = { kind: $("activity-kind").textContent, actor: $("activity-player").textContent,
      cards: $("focus-cards").children.length };
    state.activity.actor = 0;
    state.events[1].actor = 0;
    state.legal = { reveals: [], pass: false, suggest: false, accuse: true, suggest_room: null };
    state.steps++;
    renderCardInteraction(state);
    const finalPass = { title: $("card-interaction-title").textContent,
      passes: $("activity-passes").textContent, cards: $("focus-cards").children.length };
    state.events.unshift({ kind: "end_turn", actor: 0, number: 3 });
    state.waiting_for_turn = true;
    state.to_move = 1;
    state.steps++;
    renderCardInteraction(state);
    const review = $("activity-passes").textContent;
    state.waiting_for_turn = false;
    state.steps++;
    renderCardInteraction(state);
    return { response, finalPass, review, nextTurn: $("activity-passes").textContent };
  })()`);
  assert.deepEqual(JSON.parse(JSON.stringify(result)), {
    response: { kind: "Pass", actor: "Player 2 · suggestion P3",
      cards: 3 },
    finalPass: { title: "Latest pass", passes: "Passed: P2", cards: 3 },
    review: "Passed: P2", nextTurn: "",
  });
});

test("a pass after a private refutation displays only the public suggestion and passer", () => {
  const ui = frontend();
  const result = ui.evaluate(`(() => {
    const state = { mode: "spectate", human_player: null, to_move: 3, selected_player: 0,
      hand: [], matrix: [], num_players: 4, legal: { reveals: [], pass: false },
      steps: 3, activity_event_number: 3,
      activity: { kind: "reveal", actor: 1, suggestion_actor: 0,
        card_id: 7, recipient: 0, cards: [0, 7, 12] },
      events: [{ kind: "pass", actor: 2, number: 3 }, { kind: "refute", actor: 1, number: 2 },
        { kind: "suggest", actor: 0, number: 1 }] };
    renderCardInteraction(state);
    return { title: $("card-interaction-title").textContent, kind: $("activity-kind").textContent,
      actor: $("activity-player").textContent, cards: $("focus-cards").children.length };
  })()`);
  assert.deepEqual(JSON.parse(JSON.stringify(result)), {
    title: "Latest pass", kind: "Pass",
    actor: "Player 3 · suggestion P1", cards: 3,
  });
});

test("activity metadata identifies suggestions, responses and reveal visibility without instructions", () => {
  const ui = frontend();
  const result = ui.evaluate(`(() => {
    const state = { mode: "play", human_player: 0, to_move: 0, selected_player: 0,
      hand: [], matrix: [], num_players: 4, steps: 1, activity_event_number: 1,
      activity: { kind: "suggest", actor: 3, cards: [0, 7, 12] },
      events: [{ kind: "suggest", actor: 3, number: 1 }],
      legal: { reveals: [], pass: true, suggest: false, accuse: false } };
    const snapshot = () => ({ title: $("card-interaction-title").textContent,
      kind: $("activity-kind").textContent, actor: $("activity-player").textContent,
      hidden: $("activity-meta").hidden, cards: $("focus-cards").children.length });
    renderCardInteraction(state);
    const pass = snapshot();
    state.legal = { reveals: [{ id: 7 }], pass: false, suggest: false, accuse: false };
    renderCardInteraction(state);
    const revealChoice = snapshot();
    state.legal = { reveals: [], pass: false, suggest: false, accuse: false };
    state.to_move = 1;
    state.activity = { kind: "refute", actor: 1, suggestion_actor: 3, cards: [0, 7, 12] };
    renderCardInteraction(state);
    const refute = snapshot();
    state.activity = { kind: "reveal", actor: 1, recipient: 3, public: false, card_id: 7 };
    renderCardInteraction(state);
    const privateReveal = snapshot();
    state.activity.public = true;
    renderCardInteraction(state);
    const publicReveal = snapshot();
    state.to_move = 0;
    state.activity = null;
    state.legal = { reveals: [], pass: false, suggest: true, accuse: true, suggest_room: 12 };
    renderCardInteraction(state);
    const builder = snapshot();
    return { pass, revealChoice, refute, privateReveal, publicReveal, builder };
  })()`);
  assert.deepEqual(JSON.parse(JSON.stringify(result)), {
    pass: { title: "Table activity", kind: "Suggestion", actor: "Player 4", hidden: false, cards: 3 },
    revealChoice: { title: "Respond to suggestion", kind: "Suggestion", actor: "Player 4", hidden: false, cards: 3 },
    refute: { title: "Table activity", kind: "Refutation", actor: "Player 2 · suggestion P4", hidden: false, cards: 3 },
    privateReveal: { title: "Latest reveal", kind: "Reveal", actor: "Player 2 · to P4", hidden: false, cards: 1 },
    publicReveal: { title: "Latest reveal", kind: "Reveal", actor: "Player 2 · public", hidden: false, cards: 1 },
    builder: { title: "Build a suggestion", kind: "Reveal", actor: "Player 2 · public", hidden: true, cards: 0 },
  });
  assert.doesNotMatch(source, /card-interaction-hint|You have no matching card; select Pass/);
  assert.doesNotMatch(template, /card-interaction-hint/);
  assert.match(template, /<h3>Actions help<\/h3>/);
  assert.match(template, /If you have no matching card, select Pass/);
});

test("suggestion reading time starts after the last card flight completes", async () => {
  const ui = frontend();
  const result = await ui.evaluate(`(async () => {
    let now = 10000;
    performance.now = () => now;
    const finish = [];
    $("board-dynamic").querySelector = () => ({ getClientRects: () => [1],
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 10, height: 10 }) });
    const card = { getClientRects: () => [1],
      getBoundingClientRect: () => ({ left: 100, top: 100, width: 20, height: 20 }),
      animate() {},
      cloneNode: () => ({
        style: {}, classList: { add() {} }, setAttribute() {}, remove() {},
        animate() { return { finished: new Promise((resolve) => finish.push(resolve)), cancel() {} }; },
      }) };
    animateSuggestionFromBoard({ board: { suspects: [{ id: 0, seat: 0 }] },
      activity: { actor: 0 } }, { children: [card, card] });
    now += 1000;
    finish[0]();
    await Promise.resolve();
    const oneRemaining = cardActivityPending();
    finish[1]();
    await Promise.resolve();
    const afterFlight = cardActivityPending();
    now += 799;
    const beforeDeadline = cardActivityPending();
    now++;
    return [oneRemaining, afterFlight, beforeDeadline, cardActivityPending()];
  })()`);
  assert.deepEqual(Array.from(result), [true, true, true, false]);
});

test("the human player's suggestion animates while a bot is responding", () => {
  const ui = frontend();
  const result = ui.evaluate(`(() => {
    const calls = [];
    animateSuggestionFromBoard = (state, container) => calls.push({
      actor: state.activity.actor, cards: container.children.map((card) => card.textContent),
    });
    const state = { mode: "play", human_player: 0, to_move: 1, selected_player: 0,
      hand: [], matrix: [], num_players: 2,
      legal: { reveals: [], pass: false }, steps: 2,
      activity: { kind: "suggest", actor: 0, cards: [0, 7, 12] },
      events: [{ kind: "suggest", number: 2 }] };
    renderCardInteraction(state);
    renderCardInteraction(state);
    return calls;
  })()`);
  assert.deepEqual(JSON.parse(JSON.stringify(result)), [
    { actor: 0, cards: ["Miss Scarlet", "Dagger", "Kitchen"] },
  ]);
});

test("card overlay controls independently toggle marks and clause markers", () => {
  const ui = frontend({ cards: true });
  for (const type of ["positive", "negative", "unknown", "clause"]) {
    assert.match(template, new RegExp(`id="show-card-${type}-markers"`));
    assert.match(template, new RegExp(`id="show-room-${type}-markers"`));
  }
  assert.match(template, /id="show-card-hand-indicators"/);
  const result = ui.evaluate(`(() => {
    const state = { mode: "play", human_player: 0, selected_player: 0, num_players: 3,
      hand: [0], notebook_mode: "manual", matrix: [{ id: 0, marks: ["+", "-", "?"] }],
      notebook_clauses: [
        { id: 4, holder: 1, active_cards: [0] },
        { id: 5, holder: 2, active_cards: [0] },
      ] };
    const face = createCardFace(cardsById.get(0), { button: true, notes: cardNoteContext(state) });
    const snapshot = () => ({ label: face["aria-label"],
      badges: face.querySelector(".card-annotations").children.map((badge) => [badge.textContent, badge.className]) });
    const defaults = snapshot();
    currentState = state;
    document.querySelectorAll = () => [face];
    setNotebookMarkerVisibility("card", "positive", false);
    setNotebookMarkerVisibility("card", "negative", true);
    const negative = snapshot();
    setNotebookMarkerVisibility("card", "unknown", true);
    setNotebookMarkerVisibility("card", "clause", true);
    const all = snapshot();
    setNotebookMarkerVisibility("card", "negative", false);
    setNotebookMarkerVisibility("card", "unknown", false);
    setNotebookMarkerVisibility("card", "clause", false);
    return { defaults, negative, all, handOnly: snapshot(),
      cardVisibility: { ...cardMarkerVisibility }, roomVisibility: { ...roomMarkerVisibility } };
  })()`);
  assert.deepEqual(JSON.parse(JSON.stringify(result)), {
    defaults: { label: "Miss Scarlet, suspect. In your hand. Notebook: Player 1: held",
      badges: [["In hand", "card-hand-badge"], ["P1+", "card-note-mark card-note-positive card-note-own"]] },
    negative: { label: "Miss Scarlet, suspect. In your hand. Notebook: Player 2: not held",
      badges: [["In hand", "card-hand-badge"], ["P2-", "card-note-mark card-note-negative"]] },
    all: {
      label: "Miss Scarlet, suspect. In your hand. Notebook: Player 2: not held, Player 3: unknown, Clause 4, Clause 5",
      badges: [
        ["In hand", "card-hand-badge"],
        ["P2-", "card-note-mark card-note-negative"],
        ["P3?", "card-note-mark card-note-unknown"],
        ["C4", "card-note-mark card-note-clause"],
        ["C5", "card-note-mark card-note-clause"],
      ],
    },
    handOnly: { label: "Miss Scarlet, suspect. In your hand",
      badges: [["In hand", "card-hand-badge"]] },
    cardVisibility: { positive: false, negative: false, unknown: false, clause: false },
    roomVisibility: { positive: true, negative: false, unknown: false, clause: false },
  });
});

test("card notes follow optimistic edits and revert in place after a failed save", async () => {
  const ui = frontend({ cards: true });
  const result = await ui.evaluate(`(async () => {
    currentState = { mode: "play", human_player: 0, selected_player: 0, num_players: 2,
      hand: [0], notebook_mode: "manual", notebook_revision: 0, notebook_clauses: [],
      matrix: [{ id: 0, marks: ["+", "?", "-"], editable: [true, true, true] }] };
    const face = createCardFace(cardsById.get(0), { button: true, notes: cardNoteContext(currentState) });
    document.querySelectorAll = () => [face];
    globalThis.fetch = async () => { throw new Error("offline"); };
    const before = face["aria-label"];
    changeNotebook(0, 0);
    const immediate = face["aria-label"];
    await notebookQueue;
    return { before, immediate, reverted: face["aria-label"],
      noteContainers: face.querySelector(".card-topline").children.filter((child) => child.className === "card-annotations").length,
      error: $("error-message").textContent };
  })()`);
  assert.match(result.before, /In your hand.*Player 1: held/);
  assert.equal(result.immediate, "Miss Scarlet, suspect. In your hand");
  assert.equal(result.reverted, result.before);
  assert.equal(result.noteContainers, 1);
  assert.match(result.error, /offline/);
});

test("board room indicators use the selected notebook, suppress conflicts and toggle independently", () => {
  const ui = frontend({ board: true });
  const result = ui.evaluate(`(() => {
    document.createElementNS = (_, name) => document.createElement(name);
    const state = { mode: "play", human_player: 0, selected_player: 0, num_players: 2,
      hand: [12], notebook_mode: "manual", board: { layout: { rooms: [
        { id: 12, name: "Kitchen", squares: [{ x: 0, y: 0 }, { x: 5, y: 5 }] },
        { id: 13, name: "Ballroom", squares: [{ x: 9, y: 0 }, { x: 15, y: 5 }] },
      ] } }, matrix: [
        { id: 12, name: "Kitchen", marks: ["+", "-", "?"] },
        { id: 13, name: "Ballroom", marks: ["-", "?", "+"] },
      ] };
    const snapshot = () => ({ groups: $("board-room-notes").children.map((group) => ({
      label: group["aria-label"], badges: group.children.slice(1).map((badge) => ({
        kind: badge.class, text: badge.children[1].textContent,
      })),
    })), warning: $("knowledge-conflicts").textContent });
    updateKnowledgeIndicators(state);
    const normal = snapshot();
    pendingNotebookEdits.push({ cardId: 12, holder: 1, mark: "+" });
    updateKnowledgeIndicators(state);
    const conflict = snapshot();
    showBoardIndicators = false;
    updateKnowledgeIndicators(state);
    return { normal, conflict, hidden: snapshot() };
  })()`);
  assert.deepEqual(JSON.parse(JSON.stringify(result)), {
    normal: { groups: [
      { label: "Kitchen: In your hand, Player 1: held", badges: [
        { kind: "board-note-hand", text: "Hand" }, { kind: "board-note-own", text: "P1+" },
      ] },
      { label: "Ballroom: Envelope: held", badges: [{ kind: "board-note-envelope", text: "E+" }] },
    ], warning: "" },
    conflict: { groups: [
      { label: "Kitchen: In your hand", badges: [{ kind: "board-note-hand", text: "Hand" }] },
      { label: "Ballroom: Envelope: held", badges: [{ kind: "board-note-envelope", text: "E+" }] },
    ], warning: "Conflicting + marks — check notebook: Kitchen · " },
    hidden: { groups: [], warning: "Conflicting + marks — check notebook: Kitchen · " },
  });
});

test("room overlay filters show selected mark types and active clauses without changing card filters", () => {
  const ui = frontend({ board: true, cards: true });
  const result = ui.evaluate(`(() => {
    document.createElementNS = (_, name) => document.createElement(name);
    document.querySelectorAll = () => [];
    const state = { mode: "play", human_player: 0, selected_player: 0, num_players: 2,
      hand: [], notebook_mode: "manual", board: { layout: { rooms: [
        { id: 12, name: "Kitchen", squares: [{ x: 0, y: 0 }, { x: 7, y: 6 }] },
      ] } }, matrix: [{ id: 12, name: "Kitchen", marks: ["+", "-", "?"] }],
      notebook_clauses: [
        { id: 3, holder: 0, active_cards: [12] },
        { id: 8, holder: 2, active_cards: [12] },
      ] };
    currentState = state;
    const snapshot = () => {
      const group = $("board-room-notes").children[0];
      return group ? {
        label: group["aria-label"],
        badges: group.children.slice(1).map((badge) => ({
          kind: badge.class, text: badge.children[1].textContent,
        })),
      } : null;
    };
    updateKnowledgeIndicators(state);
    const defaults = snapshot();
    setNotebookMarkerVisibility("room", "negative", true);
    setNotebookMarkerVisibility("room", "unknown", true);
    setNotebookMarkerVisibility("room", "clause", true);
    const all = snapshot();
    setNotebookMarkerVisibility("room", "positive", false);
    const noPositive = snapshot();
    return { defaults, all, noPositive, cardVisibility: { ...cardMarkerVisibility } };
  })()`);
  assert.deepEqual(JSON.parse(JSON.stringify(result)), {
    defaults: { label: "Kitchen: Player 1: held",
      badges: [{ kind: "board-note-own", text: "P1+" }] },
    all: {
      label: "Kitchen: Player 1: held, Player 2: not held, Envelope: unknown, Clause 3, Clause 8",
      badges: [
        { kind: "board-note-own", text: "P1+" },
        { kind: "board-note-negative", text: "P2-" },
        { kind: "board-note-unknown", text: "E?" },
        { kind: "board-note-clause", text: "C3" },
        { kind: "board-note-clause", text: "C8" },
      ],
    },
    noPositive: {
      label: "Kitchen: Player 2: not held, Envelope: unknown, Clause 3, Clause 8",
      badges: [
        { kind: "board-note-negative", text: "P2-" },
        { kind: "board-note-unknown", text: "E?" },
        { kind: "board-note-clause", text: "C3" },
        { kind: "board-note-clause", text: "C8" },
      ],
    },
    cardVisibility: { positive: true, negative: false, unknown: false, clause: false },
  });
});

test("card activity animates only for new forward events in the same perspective", () => {
  const ui = frontend();
  const result = ui.evaluate(`(() => {
    const state = { is_replay: true, selected_player: 0, steps: 1,
      activity: { kind: "suggest", actor: 0, cards: [0, 7, 12] },
      events: [{ kind: "suggest", number: 1 }] };
    const values = [cardAnimationKind(state)];
    state.steps++;
    state.events.unshift({ kind: "pass", number: 2 });
    values.push(cardAnimationKind(state));
    state.steps++;
    state.events.unshift({ kind: "suggest", number: 3 });
    values.push(cardAnimationKind(state));
    state.selected_player = 1;
    state.steps++;
    state.events.unshift({ kind: "suggest", number: 4 });
    values.push(cardAnimationKind(state));
    state.steps--;
    state.events = [{ kind: "suggest", number: 1 }];
    values.push(cardAnimationKind(state));
    window.matchMedia = () => ({ matches: true });
    state.steps += 2;
    state.events.unshift({ kind: "suggest", number: 5 });
    values.push(cardAnimationKind(state));
    return values;
  })()`);
  assert.deepEqual(Array.from(result), ["suggest", null, "suggest", null, null, null]);
});

test("wizard payload validates and synchronizes unvisited seat and bot defaults", () => {
  const start = setupSource.indexOf("  function payload() {");
  const end = setupSource.indexOf("  function renderReview(", start);
  assert.ok(start !== -1 && end !== -1);
  const context = vm.createContext({
    fields: {
      mode: { value: "play" }, "notebook-mode": { value: "manual" },
      players: { value: "6" }, seat: { value: "0" }, seed: { value: "42" },
      progress: { value: "turn" }, "max-steps": { value: "10000" }, debug: { checked: false },
      "shuffle-bots": { checked: false }, "shuffle-seat": { checked: false },
      "shuffle-bot-count": { value: "6" },
      "rule-reverse-refutation": { checked: false },
      "rule-public-refutations": { checked: false },
      "rule-all-refute": { checked: false },
      "rule-face-up": { checked: false },
    },
  });
  vm.runInContext(`
    const $ = (id) => fields[id];
    let bots = [], characters = [0, 1, 2, 3, 4, 5], valid = true, syncCount = 0;
    let batchMode = false, shuffleBotProfileCount = 6;
    let lastError = "";
    const missingBoardSetup = "Board starting positions are unavailable. Reload the page and try again.";
    const validBasics = () => valid;
    const isBoard = () => true;
    const syncSeats = () => { syncCount++; while (bots.length < Number(fields.players.value)) bots.push("random"); };
    const copy = (value) => JSON.parse(JSON.stringify(value));
    const rules = () => ({ secret_passages: true });
    const gameRuleIds = {
      reverse_refutation: "rule-reverse-refutation", public_refutations: "rule-public-refutations",
      all_refute: "rule-all-refute", face_up_card: "rule-face-up",
    };
    ${setupSource.slice(start, end)}
  `, context);
  const result = vm.runInContext("payload()", context);
  assert.equal(result.players, 6);
  assert.deepEqual(Array.from(result.bots), Array(6).fill("random"));
  assert.deepEqual(Array.from(result.seat_suspects), [0, 1, 2, 3, 4, 5]);
  assert.equal(vm.runInContext("syncCount", context), 1);
  vm.runInContext(`
    batchMode = true;
    fields["shuffle-bots"].checked = true;
    fields.debug.checked = true;
    fields.progress.value = "turn";
  `, context);
  const batch = vm.runInContext("payload()", context);
  assert.equal(batch.mode, "spectate");
  assert.equal(batch.progress, "auto");
  assert.equal(batch.debug, false);
  assert.equal(batch.shuffle_bots, true);
  assert.equal(batch.bots.length, 6);
  vm.runInContext("shuffleBotProfileCount = 2", context);
  assert.equal(vm.runInContext("payload()", context).bots.length, 2);
  vm.runInContext("valid = false", context);
  assert.throws(() => vm.runInContext("payload()", context), /Correct the game settings/);
  assert.equal(vm.runInContext("syncCount", context), 3);
  vm.runInContext("lastError = missingBoardSetup", context);
  assert.throws(() => vm.runInContext("payload()", context), /Board starting positions are unavailable/);
});

test("bot cards keep common controls in place and disclose custom options", () => {
  const start = setupSource.indexOf("  function renderBots() {");
  const end = setupSource.indexOf("  function rules()", start);
  const context = vm.createContext({});
  vm.runInContext(`
    const make = (tag) => ({
      tag, children: [], dataset: {}, open: false,
      append(...items) { this.children.push(...items); },
      replaceChildren(...items) { this.children = items; },
      addEventListener() {},
      querySelectorAll() { return this.children.flatMap((row) =>
        row.children.filter((child) => child.tag === "details" && child.open)); },
    });
    const list = make("div");
    const fields = {
      players: { value: "2" }, mode: { value: "spectate" },
      "shuffle-bots": { checked: false }, "bot-list": list,
    };
    const $ = (id) => fields[id];
    const document = { createElement: make };
    const option = (value, label) => ({ value, label });
    const isBoard = () => false;
    const presets = { random: {}, deductive: {} };
    const presetDescriptions = { random: "Random", deductive: "Deductive", learned: "Learned" };
    const strategyLabels = { candidate_suggestions: "Candidate cards" };
    const score = () => 50;
    const bots = ["random", { candidate_suggestions: true }];
    const batchMode = false, shuffleBotProfileCount = 2;
    ${learnedHelpers}
    ${setupSource.slice(start, end)}
    renderBots();
  `, context);
  const cards = vm.runInContext("list.children", context);
  assert.deepEqual(Array.from(cards, (card) => Array.from(card.children, (child) => child.tag)),
    [["label", "p", "label", "details"], ["label", "p", "label", "details"]]);
  assert.equal(cards[0].children[3].open, false);
  assert.equal(cards[1].children[3].children[0].textContent, "Edit strategy");
  assert.equal(cards[1].children[3].children[2].tag, "fieldset");
  cards[1].children[3].open = true;
  vm.runInContext("renderBots()", context);
  assert.equal(vm.runInContext("list.children[1].children[3].open", context), true);
  vm.runInContext('bots[0] = {type:"learned", room_temperature:0.7}; renderBots()', context);
  const controls = vm.runInContext("list.children[0].children[3].children.slice(3)", context);
  assert.equal(controls.length, 6);
  assert.equal(controls[0].children[1].value, "0.7");
  assert.equal(controls[3].children[1].value, "0.5");
  assert.equal(controls[5].children[0].checked, false);
});

test("batch mode is an option within spectator setup only", () => {
  const start = setupSource.indexOf("  function renderShuffleBotCount() {");
  const end = setupSource.indexOf("  function showStep(", start);
  const context = vm.createContext({});
  vm.runInContext(`
    const fields = Object.fromEntries([
      "mode", "batch-enabled", "batch-option-field", "setup-heading", "setup-review-title",
      "batch-games-field", "setup-quick-play", "save-quickplay-default", "setup-start",
      "notebook-mode-field", "notebook-mode-hint", "progress-field", "debug-field", "spectator-warning",
      "shuffle-bots-label", "shuffle-bots-hint", "shuffle-bots", "shuffle-bot-count-field",
      "shuffle-bot-count", "players",
    ].map(id => [id, {}]));
    fields.players.value = "3";
    fields["shuffle-bots"].checked = true;
    fields["shuffle-bot-count"].value = "2";
    fields["shuffle-bot-count"].replaceChildren = (...options) => { fields["shuffle-bot-count"].options = options; };
    const $ = (id) => fields[id];
    const option = (value, label) => ({ value: String(value), label });
    let shuffleBotProfileCount = 2;
    let batchMode = true;
    fields.mode.value = "spectate";
    fields["batch-enabled"].checked = true;
    ${setupSource.slice(start, end)}
    renderBatchMode();
  `, context);
  assert.equal(vm.runInContext('fields["batch-option-field"].hidden', context), false);
  assert.equal(vm.runInContext('fields["batch-games-field"].hidden', context), false);
  assert.equal(vm.runInContext('fields["shuffle-bots-label"].textContent', context),
    "Balance randomized bot profiles across seats");
  assert.match(vm.runInContext('fields["shuffle-bots-hint"].textContent', context),
    /as evenly as possible across seats/);
  assert.equal(vm.runInContext('fields["shuffle-bot-count"].value', context), "2");
  assert.equal(vm.runInContext('fields["shuffle-bot-count"].options.length', context), 2);
  vm.runInContext('fields.mode.value = "play"; renderBatchMode()', context);
  assert.equal(vm.runInContext("batchMode", context), false);
  assert.equal(vm.runInContext('fields["batch-enabled"].checked', context), false);
  assert.equal(vm.runInContext('fields["batch-option-field"].hidden', context), true);
  assert.equal(vm.runInContext('fields["batch-games-field"].hidden', context), true);
  assert.equal(vm.runInContext('fields["shuffle-bots-label"].textContent', context),
    "Randomly assign bot styles to seats");
});

test("batch comparison and chart show meaningful rates and exact statistics", () => {
  const ui = frontend();
  assert.equal(ui.evaluate("batchRelativeRate(0.5, 2, 8)"), "200%");
  assert.equal(ui.evaluate("batchRelativeRate(0, 2, 8)"), "0%");
  assert.equal(ui.evaluate("batchRelativeRate(null, 2, 8)"), "—");
  assert.equal(ui.evaluate("batchRelativeRate(0, 0, 8)"), "—");
  ui.element("batch-metric").value = "actions";
  ui.element("batch-display-mode").value = "count";
  ui.element("batch-chart-values").open = true;
  ui.evaluate(`
    lastBatchChart = {
      title: "Game actions", samples: 4, denominator: "completed games", details: "Excluded: timeout=1.",
      numeric_summary: { minimum: 1, mean: 3, median: 3, p90: 5, maximum: 5 },
      bins: [{ label: "0-9", count: 3, probability: .75 }, { label: "10-19", count: 1, probability: .25 }],
    };
    renderBatchChart();
  `);
  const bars = ui.element("batch-chart-graph").children.filter((child) => child.class === "batch-chart-bin");
  assert.equal(bars.length, 2);
  assert.match(bars[0]["aria-label"], /0-9: 3 of 4 \(75.0%\).*75.0% cumulative/);
  assert.match(bars[1]["aria-label"], /10-19: 1 of 4 \(25.0%\).*100.0% cumulative/);
  assert.ok(Number(bars[0].children[1].height) > Number(bars[1].children[1].height));
  const tableRows = ui.element("batch-chart-table").children[0].children[1].children;
  assert.deepEqual(tableRows.map((row) => row.children.map((cell) => cell.textContent)), [
    ["0-9", "3", "75.0%", "75.0%"], ["10-19", "1", "25.0%", "100.0%"],
  ]);
  assert.equal(ui.element("batch-chart-stats").children.length, 5);
  ui.evaluate("lastBatchChart = { samples: 0, title: 'Empty', denominator: 'games', details: '', bins: [] }; renderBatchChart()");
  assert.equal(ui.element("batch-chart-empty").hidden, false);
  assert.equal(ui.element("batch-chart-graph").children.length, 0);
});

test("batch summary displays the complete settings before results are available", () => {
  const ui = frontend();
  ui.evaluate(`renderBatchSummary({
    settings_display: "Batch\\n  Games requested: 12\\nBot profiles\\n  Candidate rooms: Yes",
    summary: null,
  })`);
  assert.equal(ui.element("batch-settings-disclosure").hidden, false);
  assert.match(ui.element("batch-settings").textContent, /Games requested: 12/);
  assert.match(ui.element("batch-settings").textContent, /Candidate rooms: Yes/);
  assert.doesNotMatch(ui.element("batch-settings").textContent, /"games"/);
});

test("distribution graph preserves gaps and groups dense bins without losing counts", () => {
  const ui = frontend();
  const result = ui.evaluate(`(() => {
    const sparse = batchGraphBuckets({
      numeric_summary: {}, bins: [{ label: "0", count: 2 }, { label: "500", count: 3 }],
    }, 500);
    const dense = batchGraphBuckets({
      numeric_summary: {}, bins: Array.from({ length: 1000 }, (_, i) => ({ label: String(i), count: 1 })),
    }, 500);
    return {
      sparse: sparse.bars, denseCount: dense.bars.length, group: dense.binsPerBar,
      samples: dense.bars.reduce((sum, bar) => sum + bar.count, 0),
    };
  })()`);
  assert.ok(result.sparse[1].start - result.sparse[0].end > 400);
  assert.ok(result.denseCount <= 80);
  assert.ok(result.group > 1);
  assert.equal(result.samples, 1000);
});

test("exact distribution data is paginated with cumulative counts across pages", () => {
  const ui = frontend();
  ui.element("batch-chart-values").open = true;
  ui.evaluate(`
    lastBatchChart = {
      samples: 120, numeric_summary: {},
      bins: Array.from({ length: 120 }, (_, i) => ({ label: String(i), count: 1, probability: 1 / 120 })),
    };
    batchBinOffset = 50;
    renderBatchBinTable();
  `);
  const rows = ui.element("batch-chart-table").children[0].children[1].children;
  assert.equal(rows.length, 50);
  assert.equal(rows[0].children[0].textContent, "50");
  assert.equal(rows[0].children[3].textContent, "42.5%");
  assert.equal(ui.element("batch-bin-status").textContent, "Showing 51–100 of 120 bins.");
  assert.equal(ui.element("batch-bin-previous").disabled, false);
  assert.equal(ui.element("batch-bin-next").disabled, false);
});

test("batch workspace tabs switch visible panels without losing the selection", () => {
  const ui = frontend();
  ui.evaluate('switchBatchTab("runs")');
  assert.equal(ui.element("batch-panel-runs").hidden, false);
  assert.equal(ui.element("batch-panel-distribution").hidden, true);
  assert.equal(ui.element("batch-tab-runs")["aria-selected"], "true");
  assert.equal(ui.element("batch-tab-summary").tabIndex, -1);
});

test("batch filter requests ignore out-of-order results", async () => {
  const ui = frontend();
  ui.element("batch-bin-width").value = "10";
  ui.element("batch-metric").value = "outcomes";
  ui.element("batch-policy-filter").value = "random";
  ui.element("batch-seat-filter").value = "0";
  ui.evaluate(`
    activeBatchId = "batch"; batchFinished = true;
    globalThis.pending = [];
    requestJson = (url) => new Promise((resolve) => pending.push({ url, resolve }));
    globalThis.first = loadBatchChart();
    $("batch-policy-filter").value = "deductive";
    globalThis.second = loadBatchChart();
  `);
  const urls = ui.evaluate("pending.map((request) => request.url)");
  assert.match(urls[0], /policy=random/);
  assert.match(urls[0], /seat=0/);
  assert.match(urls[1], /policy=deductive/);
  ui.evaluate(`pending[1].resolve({ title: "new", samples: 0, denominator: "games", details: "", bins: [] })`);
  await ui.evaluate("second");
  ui.evaluate(`pending[0].resolve({ title: "old", samples: 0, denominator: "games", details: "", bins: [] })`);
  await ui.evaluate("first");
  assert.equal(ui.element("batch-distribution-title").textContent, "new");
});

test("run list sorts, filters and ignores stale pages", async () => {
  const ui = frontend();
  ui.element("batch-policy-filter").value = "random";
  ui.element("batch-seat-filter").value = "1";
  ui.element("batch-runs-sort").value = "steps";
  ui.element("batch-runs-order").value = "desc";
  ui.evaluate(`
    activeBatchId = "batch"; batchFinished = true;
    globalThis.pending = [];
    requestJson = (url) => new Promise((resolve) => pending.push({ url, resolve }));
    globalThis.first = loadBatchRuns();
    batchRunsOffset = 25;
    globalThis.second = loadBatchRuns();
  `);
  const urls = ui.evaluate("pending.map((request) => request.url)");
  assert.match(urls[0], /sort=steps/);
  assert.match(urls[0], /order=desc/);
  assert.match(urls[0], /policy=random/);
  assert.match(urls[0], /seat=1/);
  assert.match(urls[1], /offset=25/);
  ui.evaluate("pending[1].resolve({ total: 0, offset: 25, runs: [] })");
  await ui.evaluate("second");
  ui.evaluate("pending[0].resolve({ total: 4, offset: 0, runs: [] })");
  await ui.evaluate("first");
  assert.equal(ui.element("batch-runs-status").textContent, "No runs match these filters.");
});

test("seeded bot seat shuffling preserves styles, human seat, and replay reproducibility", () => {
  const start = setupSource.indexOf("  function resolveBotSeats(");
  const end = setupSource.indexOf("  function renderReview(", start);
  const context = vm.createContext({});
  vm.runInContext(`const copy = (value) => JSON.parse(JSON.stringify(value)); ${setupSource.slice(start, end)}`, context);
  const input = {
    mode: "play", players: 4, seat: 1, seed: 42, shuffle_bots: true,
    bots: ["deductive", "human-placeholder", "probing", { deal_analysis: true }],
  };
  context.input = input;
  const first = context.resolveBotSeats(input);
  assert.deepEqual(JSON.parse(JSON.stringify(first)), JSON.parse(JSON.stringify(context.resolveBotSeats(input))));
  assert.equal(first.bots[1], "human-placeholder");
  assert.deepEqual(Array.from(first.bots).filter((_, i) => i !== 1).map(JSON.stringify).sort(),
    [JSON.stringify("deductive"), JSON.stringify("probing"), JSON.stringify({ deal_analysis: true })].sort());
  assert.equal(first.shuffle_bots, undefined);
  assert.equal(input.shuffle_bots, true);
  const assignments = new Set(Array.from({ length: 30 }, (_, seed) =>
    JSON.stringify(context.resolveBotSeats({ ...input, seed }).bots)));
  assert.ok(assignments.size > 1);
  const fixed = context.resolveBotSeats({ ...input, shuffle_bots: false });
  assert.deepEqual(JSON.parse(JSON.stringify(fixed.bots)), input.bots);
  const spectate = context.resolveBotSeats({ ...input, mode: "spectate" });
  assert.deepEqual(Array.from(spectate.bots).map(JSON.stringify).sort(), input.bots.map(JSON.stringify).sort());
});

test("random human seat preserves characters and every bot with or without bot shuffling", () => {
  const start = setupSource.indexOf("  function resolveBotSeats(");
  const end = setupSource.indexOf("  function renderReview(", start);
  const context = vm.createContext({});
  vm.runInContext(`const copy = (value) => JSON.parse(JSON.stringify(value)); ${setupSource.slice(start, end)}`, context);
  const input = {
    mode: "play", players: 4, seat: 0, seed: 42, shuffle_seat: true, shuffle_bots: false,
    seat_suspects: [2, 0, 3, 1],
    bots: ["human-placeholder", "deductive", "probing", { deal_analysis: true }],
  };
  const expectedBots = input.bots.slice(1).map(JSON.stringify).sort();
  for (const shuffle of [false, true]) {
    const counts = Array(4).fill(0);
    for (let seed = 0; seed < 200; seed++) {
      const source = { ...input, seed, shuffle_bots: shuffle };
      const result = context.resolveBotSeats(source);
      assert.deepEqual(JSON.parse(JSON.stringify(result)), JSON.parse(JSON.stringify(context.resolveBotSeats(source))));
      counts[result.seat]++;
      assert.deepEqual(Array.from(result.seat_suspects), input.seat_suspects);
      assert.equal(result.bots[result.seat], "human-placeholder");
      assert.deepEqual(Array.from(result.bots).filter((_, i) => i !== result.seat).map(JSON.stringify).sort(), expectedBots);
      assert.equal(result.shuffle_seat, undefined);
      assert.deepEqual(JSON.parse(JSON.stringify(context.resolveBotSeats(result))), JSON.parse(JSON.stringify(result)));
    }
    assert.ok(counts.every((count) => count >= 25 && count <= 75), counts.join(", "));
  }
  const spectate = context.resolveBotSeats({ ...input, mode: "spectate" });
  assert.equal(spectate.seat, input.seat);
  assert.deepEqual(JSON.parse(JSON.stringify(spectate.bots)), input.bots);
  assert.equal(input.seat, 0);
});

test("factory quickplay uses four board players and the three requested bot styles", () => {
  const start = setupSource.indexOf("  function defaultQuickplay()");
  const end = setupSource.indexOf("  async function loadQuickplay()", start);
  const context = vm.createContext({});
  vm.runInContext(`const standardRules = { secret_passages: true };
    const gameRuleIds = { all_refute: "rule-all-refute" }; ${setupSource.slice(start, end)}`, context);
  const config = context.defaultQuickplay();
  assert.equal(config.game_type, "board");
  assert.equal(config.players, 4);
  assert.equal(config.mode, "play");
  assert.equal(config.shuffle_bots, true);
  assert.deepEqual(Array.from(config.bots).slice(1).sort(), ["deductive", "probing", "strategic"]);
});

test("setup exposes the analytical preset with its additional reasoning described", () => {
  const start = setupSource.indexOf("  const presets = {");
  const end = setupSource.indexOf("  const weights = {", start);
  assert.ok(start >= 0 && end > start);
  const context = vm.createContext({});
  const preset = vm.runInContext(`${setupSource.slice(start, end)}
    ({ settings: presets.analytical, description: presetDescriptions.analytical })`, context);
  assert.equal(preset.settings.deal_analysis, true);
  assert.equal(preset.settings.rank_suggestions, true);
  assert.equal(preset.settings.risk_accusation, true);
  assert.match(preset.description, /opponent modeling/);
  assert.match(preset.description, /50% estimated confidence/);
});

test("quickplay review describes shuffled styles without claiming assigned bot seats", () => {
  const start = setupSource.indexOf("  function renderReview(");
  const end = setupSource.indexOf("  function showStep(", start);
  const context = vm.createContext({});
  const result = vm.runInContext(`(() => {
    let batchMode = false;
    const data = { game_type: "card_only", mode: "play", players: 3, seat: 0,
      notebook_mode: "manual", bots: ["random", "probing", "strategic"],
      shuffle_bots: true, seed: 12, progress: "turn", max_steps: 100, debug: false, game_rules: {} };
    const payload = () => data, score = () => 50, standardRules = {};
    const document = { createElement: () => ({ textContent: "", children: [],
      append(...items) { this.children.push(...items); } }),
      createTextNode: (text) => ({ textContent: text }) };
    ${learnedHelpers}
    ${setupSource.slice(start, end)}
    const review = { children: [], replaceChildren() { this.children = []; },
      append(child) { this.children.push(child); } };
    renderReview(review, false);
    return review.children.map((row) => row.children.map((item) => item.textContent).join(""));
  })()`, context);
  assert.ok(result.some((row) => row.includes("probing, strategic · randomly assigned")));
  assert.ok(result.some((row) => row === "Player 2: Bot (random style)"));
  assert.ok(!result.some((row) => row.startsWith("Seed:")));
});

test("batch review explains balanced randomized profile seat assignments", () => {
  const start = setupSource.indexOf("  function renderReview(");
  const end = setupSource.indexOf("  function showStep(", start);
  const context = vm.createContext({});
  const result = vm.runInContext(`(() => {
    let batchMode = true;
    const data = { game_type: "card_only", mode: "spectate", players: 3, seat: 0,
      bots: ["random", "probing", "strategic"], shuffle_bots: true, seed: 12,
      progress: "auto", max_steps: 100, debug: false, game_rules: {} };
    const payload = () => data, score = () => 50, standardRules = {};
    const $ = (id) => ({ value: id === "batch-games" ? "5" : "" });
    const document = { createElement: () => ({ textContent: "", children: [],
      append(...items) { this.children.push(...items); } }),
      createTextNode: (text) => ({ textContent: text }) };
    ${learnedHelpers}
    ${setupSource.slice(start, end)}
    const review = { children: [], replaceChildren() { this.children = []; },
      append(child) { this.children.push(child); } };
    renderReview(review, false);
    return review.children.map((row) => row.children.map((item) => item.textContent).join(""));
  })()`, context);
  assert.ok(result.some((row) => row === "Bot styles: random, probing, strategic · balanced across full profile rotations; a partial final rotation can vary"));
  assert.ok(result.some((row) => row === "Games: 5"));
});

test("review warns when an analytical bot can make risky accusations", () => {
  const start = setupSource.indexOf("  function renderReview(");
  const end = setupSource.indexOf("  function showStep(", start);
  const context = vm.createContext({});
  const result = vm.runInContext(`(() => {
    let batchMode = false;
    const data = { game_type: "card_only", mode: "spectate", players: 2, seat: 0,
      notebook_mode: "automatic", bots: ["analytical", "random"], seed: 12,
      progress: "turn", max_steps: 100, debug: false, game_rules: {} };
    const payload = () => data, score = () => 50, standardRules = {};
    const document = { createElement: () => ({ textContent: "", children: [],
      append(...items) { this.children.push(...items); } }),
      createTextNode: (text) => ({ textContent: text }) };
    ${learnedHelpers}
    ${setupSource.slice(start, end)}
    const review = { children: [], replaceChildren() { this.children = []; },
      append(child) { this.children.push(child); } };
    renderReview(review, false);
    return review.children.map((row) => row.children.map((item) => item.textContent).join(""));
  })()`, context);
  assert.ok(result.some((row) => /Analytical risk: .*50%.*eliminates/.test(row)));
});

test("setup profiles validate and persist in browser and desktop storage", async () => {
  const start = setupSource.indexOf("  function validateProfile(");
  const end = setupSource.indexOf("  function beginFresh(", start);
  assert.ok(start !== -1 && end !== -1);
  const context = vm.createContext({});
  const result = await vm.runInContext(`(async () => {
    const presets = { random: {} }, strategyLabels = {},
      ruleIds = {move_suspect: "", move_weapon: "", summoned_suggestion: "", secret_passages: ""},
      gameRuleIds = {};
    const storageKey = "profiles", quickplayProfile = "__clue_engine_quickplay__";
    let profiles = Object.create(null), profilesReady = false, saved = null, calls = [];
    const select = { value: "", replaceChildren(...items) { this.items = items; },
      append(item) { this.items.push(item); } };
    const $ = () => select;
    const option = (value, label) => ({ value, label });
    const window = { clueOptions: { desktop: false } };
    const localStorage = {
      getItem: () => saved,
      setItem: (key, value) => { saved = value; },
    };
    const requestJson = async (path, options) => {
      calls.push({ path, options });
      return { profiles: { Desktop: profile } };
    };
    ${learnedHelpers}
    ${setupSource.slice(start, end)}
    const profile = { mode: "play", game_type: "card_only", players: 2, seat: 0,
      bots: ["random", "random"], progress: "turn", max_steps: 100, debug: false };
    const balanced = { ...profile, players: 3, bots: ["random", "random"], shuffle_bots: true };
    validateProfile(balanced);
    const board = { ...profile, game_type: "board", players: 3, seat_suspects: [0, 1, 2],
      bots: ["random", {type: "learned", room_temperature: 0.7, opponent_model: true}, "random"],
      board_rules: {move_suspect: true, move_weapon: true, summoned_suggestion: true, secret_passages: true} };
    validateProfile(board);
    let invalidLearned;
    try { validateProfile({...board, bots: ["random", {type: "learned", room_temperature: -1}, "random"]}); }
    catch (error) { invalidLearned = error.message; }
    await loadProfiles();
    await persistProfiles({ Browser: profile });
    profiles = Object.create(null);
    await loadProfiles();
    const browserNames = Object.keys(profiles);
    saved = JSON.stringify({ version: 1, profiles: { Invalid: { ...profile, players: 1 } } });
    let invalid;
    try { await loadProfiles(); } catch (error) { invalid = error.message; }
    window.clueOptions.desktop = true;
    await loadProfiles();
    await persistProfiles({ Desktop: profile });
    return { browserNames, invalid, invalidLearned, desktopNames: Object.keys(profiles), ready: profilesReady, calls };
  })()`, context);
  assert.deepEqual(Array.from(result.browserNames), ["Browser"]);
  assert.match(result.invalid, /Invalid setup profile/);
  assert.match(result.invalidLearned, /Invalid learned bot settings/);
  assert.deepEqual(Array.from(result.desktopNames), ["Desktop"]);
  assert.equal(result.ready, true);
  assert.equal(result.calls[0].path, "/api/desktop/profiles");
  assert.equal(result.calls[1].options.method, "PUT");
});

test("in-app confirmation accepts, cancels and refuses overlapping dialogs", async () => {
  const ui = frontend();
  const dialog = ui.element("confirm-dialog");
  dialog.open = false;
  dialog.addEventListener = (name, callback) => { dialog.onclose = callback; };
  dialog.showModal = () => { dialog.open = true; };
  dialog.close = (value) => {
    dialog.open = false;
    dialog.returnValue = value;
    dialog.onclose();
  };
  const pending = ui.evaluate('confirmAction("Delete it?", { title: "Delete", confirmLabel: "Delete" })');
  assert.equal(dialog.open, true);
  assert.equal(ui.element("confirm-title").textContent, "Delete");
  assert.equal(ui.element("confirm-message").textContent, "Delete it?");
  assert.equal(ui.element("confirm-accept").textContent, "Delete");
  assert.equal(await ui.evaluate('confirmAction("Other")'), false);
  dialog.close("cancel");
  assert.equal(await pending, false);
  const accepted = ui.evaluate('confirmAction("Continue?")');
  dialog.close("confirm");
  assert.equal(await accepted, true);
  assert.doesNotMatch(source + setupSource, /\b(?:alert|confirm|prompt)\s*\(/);
});

test("queued clause edits apply to the latest notebook state", async () => {
  const result = await frontend().queueExclusions();
  assert.deepEqual(Array.from(result.excluded), [0, 7]);
  assert.equal(result.error, "");
});

test("clause draft selection updates cells without rebuilding the notebook", () => {
  const ui = frontend({ notebook: true });
  const state = {
    notebook_mode: "manual", num_players: 2, hand_sizes: [9, 9], notebook_clauses: [],
    matrix: [
      { id: 0, name: "Miss Scarlet", type: "suspect", marks: ["?", "?", "?"], editable: [true, true, true] },
      { id: 7, name: "Dagger", type: "weapon", marks: ["?", "?", "?"], editable: [true, true, true] },
      { id: 12, name: "Kitchen", type: "room", marks: ["?", "?", "?"], editable: [true, true, true] },
    ],
  };
  ui.renderNotebook(state);
  ui.evaluate("currentState = state; startClauseEntry()");
  const notebook = ui.element("notebook");
  function descendants(node) { return [node, ...node.children.flatMap(descendants)]; }
  notebook.querySelector = (selector) => {
    const match = selector.match(/data-notebook-card="(\d+)".*data-notebook-holder="(\d+)"/);
    return match && descendants(notebook).find((node) =>
      node.dataset.notebookCard === match[1] && node.dataset.notebookHolder === match[2]);
  };
  const find = (card, holder) => notebook.querySelector(
    `[data-notebook-card="${card}"][data-notebook-holder="${holder}"]`
  );
  const table = notebook.children[0];
  const oldCell = find(0, 1);
  const newCell = find(0, 2);
  ui.evaluate("selectClauseCell(0, 1)");
  assert.equal(oldCell["aria-pressed"], "true");
  assert.match(oldCell["aria-label"], /Selected for clause/);
  assert.ok(oldCell.parentElement.classList.contains("clause-draft-selected"));
  ui.evaluate("selectClauseCell(7, 2)");
  assert.equal(oldCell["aria-pressed"], "false");
  assert.equal(newCell["aria-pressed"], "true");
  assert.equal(find(7, 2)["aria-pressed"], "true");
  assert.ok(!oldCell.parentElement.classList.contains("clause-draft-selected"));
  assert.equal(notebook.children[0], table);
});

test("manual notebook updates cells immediately and saves rapid edits in order", async () => {
  const ui = frontend({ notebook: true });
  const state = {
    notebook_mode: "manual", num_players: 2, hand_sizes: [9, 9], notebook_revision: 0,
    matrix: [{ id: 0, name: "Miss Scarlet", type: "suspect", marks: ["?", "?", "?"],
      editable: [true, true, true] }],
    notebook_clauses: [],
    notebook_focus: { turn: 1, actor: 1, kind: "suggest", cards: [0], shown: { holder: 1, card: 0 } },
  };
  ui.renderNotebook(state);
  ui.evaluate("currentState = state");
  const notebook = ui.element("notebook");
  function descendants(node) {
    return [node, ...node.children.flatMap(descendants)];
  }
  notebook.querySelector = (selector) => {
    const match = selector.match(/data-notebook-card="(\d+)".*data-notebook-holder="(\d+)"/);
    return match && descendants(notebook).find((node) =>
      node.dataset.notebookCard === match[1] && node.dataset.notebookHolder === match[2]);
  };
  const button = notebook.querySelector('[data-notebook-card="0"][data-notebook-holder="1"]');
  const table = notebook.children[0];
  const result = await ui.evaluate(`(async () => {
    const calls = [];
    let release;
    let serverMark = "?";
    globalThis.fetch = async (path, options) => {
      const body = JSON.parse(options.body);
      calls.push(body.mark);
      if (calls.length === 1) await new Promise((resolve) => { release = resolve; });
      serverMark = body.mark;
      return { ok: true, json: async () => ({
        matrix: [{ ...state.matrix[0], marks: ["?", serverMark, "?"] }],
        notebook_clauses: [], notebook_revision: calls.length,
      }) };
    };
    changeNotebook(0, 1);
    const first = notebookDisplayMatrix(currentState)[0].marks[1];
    changeNotebook(0, 1);
    changeNotebook(0, 1);
    const immediate = notebookDisplayMatrix(currentState)[0].marks[1];
    await Promise.resolve();
    const beforeRelease = calls.length;
    release();
    await notebookQueue;
    return { first, immediate, beforeRelease, calls, saved: currentState.matrix[0].marks[1] };
  })()`);
  assert.equal(result.first, "+");
  assert.equal(result.immediate, "?");
  assert.equal(result.beforeRelease, 1);
  assert.deepEqual(Array.from(result.calls), ["+", "-", "?"]);
  assert.equal(result.saved, "?");
  assert.equal(notebook.children[0], table);
  assert.equal(notebook.querySelector('[data-notebook-card="0"][data-notebook-holder="1"]'), button);
  assert.equal(button.textContent, "?");
  assert.match(button["aria-label"], /unknown; turn owner, acting now; current suggestion; visibly shown/);
});

test("failed notebook save reverts the optimistic mark and reports the error", async () => {
  const ui = frontend({ notebook: true });
  const state = {
    notebook_mode: "manual", num_players: 2, hand_sizes: [9, 9], notebook_revision: 0,
    matrix: [{ id: 0, name: "Miss Scarlet", type: "suspect", marks: ["?", "?", "?"],
      editable: [true, true, true] }],
    notebook_clauses: [],
  };
  ui.renderNotebook(state);
  const result = await ui.evaluate(`(async () => {
    currentState = state;
    let release;
    globalThis.fetch = async () => {
      await new Promise((resolve) => { release = resolve; });
      throw new Error("offline");
    };
    changeNotebook(0, 1);
    const optimistic = notebookDisplayMatrix(currentState)[0].marks[1];
    await Promise.resolve();
    release();
    await notebookQueue;
    return { optimistic, reverted: notebookDisplayMatrix(currentState)[0].marks[1],
      error: $("error-message").textContent, pending: pendingNotebookEdits.length };
  })()`);
  assert.equal(result.optimistic, "+");
  assert.equal(result.reverted, "?");
  assert.equal(result.pending, 0);
  assert.match(result.error, /offline/);
});

test("pending notebook edits remain visible across refreshes and failed earlier saves", async () => {
  const ui = frontend();
  const result = await ui.evaluate(`(async () => {
    const matrix = [{ id: 0, marks: ["?", "?", "?"], editable: [true, true, true] }];
    currentState = { notebook_mode: "manual", notebook_revision: 0, matrix, notebook_clauses: [] };
    let releaseFirst;
    let releaseSecond;
    let calls = 0;
    globalThis.fetch = async (path, options) => {
      const body = JSON.parse(options.body);
      calls++;
      if (calls === 1) {
        await new Promise((resolve) => { releaseFirst = resolve; });
        throw new Error("offline");
      }
      await new Promise((resolve) => { releaseSecond = resolve; });
      return { ok: true, json: async () => ({
        matrix: [{ ...matrix[0], marks: ["?", body.mark, "?"] }],
        notebook_clauses: [], notebook_revision: 1,
      }) };
    };
    changeNotebook(0, 1);
    changeNotebook(0, 1);
    await Promise.resolve();
    acceptState({ notebook_mode: "manual", notebook_revision: 0, matrix, notebook_clauses: [] });
    const afterRefresh = notebookDisplayMatrix(currentState)[0].marks[1];
    releaseFirst();
    while (!releaseSecond) await Promise.resolve();
    const afterFailure = notebookDisplayMatrix(currentState)[0].marks[1];
    const error = $("error-message").textContent;
    releaseSecond();
    await notebookQueue;
    return { afterRefresh, afterFailure, error, saved: currentState.matrix[0].marks[1] };
  })()`);
  assert.equal(result.afterRefresh, "-");
  assert.equal(result.afterFailure, "-");
  assert.match(result.error, /offline/);
  assert.equal(result.saved, "-");
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

test("replay replaces the card browser without adding a workspace tab", () => {
  const ui = frontend({ workspace: true });
  ui.evaluate("replayMode = true; setReplayPresentation(true)");
  assert.equal(ui.element("replay-timeline").hidden, false);
  assert.equal(ui.element("replay-knowledge").hidden, false);
  assert.equal(ui.element("card-view-tabs").hidden, true);
  assert.equal(ui.element("hand-cards").hidden, true);
  assert.equal(ui.evaluate("insightsTabs.join(',')"), "history,clauses,help");
  assert.equal(ui.evaluate("boardTabs.join(',')"), "cards,history,clauses,locations,help");
  ui.switchBoard("history");
  assert.equal(ui.element("replay-timeline").hidden, false);
  ui.switchBoard("cards");
  assert.equal(ui.element("cards-panel").hidden, false);
  assert.equal(ui.element("insights-panel").hidden, true);
  ui.evaluate("replayMode = false; setReplayPresentation(false)");
  assert.equal(ui.element("replay-timeline").hidden, true);
  assert.equal(ui.element("replay-knowledge").hidden, true);
  assert.equal(ui.element("hand-cards").hidden, false);
});

test("replay options do not expose reveal-all controls", () => {
  const options = template.match(/<div id="replay-controls"[\s\S]*?<\/div>/)?.[0];
  assert.ok(options);
  assert.doesNotMatch(options, /Reveal all|replay-omniscient/);
  assert.doesNotMatch(source, /replay-omniscient/);
});

test("replay speed selector exposes faster modes without changing the default", () => {
  const selector = template.match(/<select id="replay-speed"[^>]*>([\s\S]*?)<\/select>/);
  assert.ok(selector);
  assert.deepEqual(
    [...selector[1].matchAll(/<option value="([^"]+)"( selected)?>([^<]+)<\/option>/g)]
      .map(([, value, selected, label]) => [value, Boolean(selected), label]),
    [["2000", false, "0.5×"], ["1000", true, "1×"], ["500", false, "2×"],
      ["250", false, "4×"], ["125", false, "8×"], ["62.5", false, "16×"]],
  );
});

for (const [speed, scale] of [[250, 0.5], [125, 0.25], [62.5, 0.125]]) {
  test(`replay at ${1000 / speed}x scales activity pauses and animations`, async () => {
    const ui = frontend();
    ui.element("replay-speed").value = String(speed);
    const result = ui.evaluate(`(() => {
      replayPlaying = true;
      currentState = { is_replay: true, selected_player: 0, steps: 1,
        activity: { kind: "suggest", actor: 0, cards: [0, 7, 12] },
        events: [{ kind: "suggest", number: 1 }] };
      cardAnimationKind(currentState);
      const suggestion = cardActivityReadUntil - performance.now();
      currentState.steps++;
      currentState.events.unshift({ kind: "pass", actor: 1, number: 2 });
      cardAnimationKind(currentState);
      const pass = cardActivityReadUntil - performance.now();
      currentState.steps++;
      currentState.activity = { kind: "reveal", actor: 1, card_id: 7 };
      currentState.events.unshift({ kind: "show", number: 3 });
      cardAnimationKind(currentState);
      const reveal = cardActivityReadUntil - performance.now();
      const container = document.createElement("div");
      renderMiniCards(container, [7], {}, 7, true);
      const revealAnimation = container.children[0].style.animationDuration;
      const records = [];
      $("board-dynamic").querySelector = () => ({
        getClientRects: () => [1],
        getBoundingClientRect: () => ({ left: 0, top: 0, width: 10, height: 10 }),
      });
      const card = { getClientRects: () => [1],
        getBoundingClientRect: () => ({ left: 20, top: 20, width: 10, height: 10 }),
        animate: (_, options) => records.push(options),
        cloneNode: () => ({ style: {}, classList: { add() {} }, setAttribute() {}, remove() {},
          animate(_, options) {
            records.push(options);
            return { finished: new Promise((resolve) => { globalThis.finishFlights.push(resolve); }), cancel() {} };
          } }),
      };
      globalThis.finishFlights = [];
      currentState.board = { suspects: [{ id: 2, seat: 1 }] };
      currentState.activity = { actor: 1 };
      animateSuggestionFromBoard(currentState, { children: [card, card] });
      return { suggestion, pass, reveal, revealAnimation, duration: records[0].duration,
        secondDelay: records[2].delay };
    })()`);
    assert.equal(result.suggestion, 800 * scale);
    assert.equal(result.pass, 1200 * scale);
    assert.equal(result.reveal, 800 * scale);
    assert.equal(result.revealAnimation, `${650 * scale}ms`);
    assert.equal(result.duration, 850 * scale);
    assert.equal(result.secondDelay, 100 * scale);
    ui.evaluate("finishFlights[0]()");
    await Promise.resolve();
    assert.equal(ui.evaluate("suggestionFlights.length"), 1);
    ui.evaluate("cardActivityReadUntil = 0; finishFlights[1]()");
    await Promise.resolve();
    assert.equal(ui.evaluate("cardActivityReadUntil - performance.now()"), 800 * scale);
    ui.evaluate("clearSuggestionFlights(); replayPlaying = false");
    assert.equal(ui.evaluate("replayActivityScale(currentState)"), 1);
    ui.evaluate("replayPlaying = true; currentState.is_replay = false");
    assert.equal(ui.evaluate("replayActivityScale(currentState)"), 1);
  });
}

test("faster replay schedules steps serially and waits for scaled reading time", async () => {
  const ui = frontend();
  ui.element("replay-speed").value = "125";
  ui.evaluate(`let now = 10000; performance.now = () => now;
    replayMode = true; currentState = { is_replay: true, position: 0, positions: 4, steps: 1,
      selected_player: 0, activity: { kind: "suggest", actor: 0, cards: [0, 7, 12] },
      events: [{ kind: "suggest", number: 1 }, { kind: "pass", actor: 1, number: 2 }] };
    loadReplay = async () => { currentState.position = Number($("replay-position").value); return true; };
    toggleReplayPlayback();
    currentState.events.reverse(); cardAnimationKind(currentState)`);
  let [id, timer] = [...ui.timers.entries()][0];
  assert.equal(timer.delay, 125);
  ui.timers.delete(id);
  ui.evaluate("now += 125");
  await timer.callback();
  assert.equal(ui.evaluate("currentState.position"), 0);
  [id, timer] = [...ui.timers.entries()][0];
  assert.equal(timer.delay, 175);
  ui.timers.delete(id);
  ui.evaluate("now += 175");
  await timer.callback();
  assert.equal(ui.evaluate("currentState.position"), 1);
  assert.equal(ui.timers.size, 1);
  ui.element("replay-speed").value = "62.5";
  [id, timer] = [...ui.timers.entries()][0];
  ui.timers.delete(id);
  await timer.callback();
  assert.equal(ui.evaluate("currentState.position"), 2);
  [id, timer] = [...ui.timers.entries()][0];
  assert.equal(timer.delay, 62.5);
  ui.timers.delete(id);
  await timer.callback();
  assert.equal(ui.evaluate("currentState.position"), 3);
  assert.equal(ui.timers.size, 0);
});

test("replay playback runs serially, respects speed, pauses, and stops at the end", async () => {
  const ui = frontend();
  ui.element("replay-speed").value = "500";
  ui.evaluate(`replayMode = true; currentState = { is_replay: true, position: 0, positions: 3 };
    loadReplay = async () => { currentState.position = Number($("replay-position").value); return true; };
    toggleReplayPlayback()`);
  assert.equal(ui.element("replay-play").textContent, "Pause");
  assert.equal(ui.timers.size, 1);
  assert.equal([...ui.timers.values()][0].delay, 500);
  let [id, timer] = [...ui.timers.entries()][0];
  ui.timers.delete(id);
  await timer.callback();
  assert.equal(ui.evaluate("currentState.position"), 1);
  assert.equal(ui.timers.size, 1);
  [id, timer] = [...ui.timers.entries()][0];
  ui.timers.delete(id);
  await timer.callback();
  assert.equal(ui.evaluate("currentState.position"), 2);
  assert.equal(ui.element("replay-play").textContent, "Play");
  assert.equal(ui.element("replay-play").disabled, true);
  assert.equal(ui.timers.size, 0);

  ui.evaluate("currentState.position = 0; toggleReplayPlayback(); stopReplayPlayback()");
  assert.equal(ui.timers.size, 0);
  assert.equal(ui.element("replay-play").textContent, "Play");
  ui.evaluate("loadReplay = async () => false; toggleReplayPlayback()");
  [id, timer] = [...ui.timers.entries()][0];
  ui.timers.delete(id);
  await timer.callback();
  assert.equal(ui.evaluate("replayPlaying"), false);
  assert.equal(ui.timers.size, 0);
});

test("continuous replay waits for card activity without blocking manual navigation", async () => {
  const ui = frontend();
  ui.element("replay-speed").value = "500";
  ui.evaluate(`let now = 10000; performance.now = () => now;
    replayMode = true; currentState = { is_replay: true, position: 0, positions: 3, turns: [] };
    loadReplay = async () => { currentState.position = Number($("replay-position").value); return true; };
    cardActivityReadUntil = now + 800; toggleReplayPlayback()`);
  let [id, timer] = [...ui.timers.entries()][0];
  ui.timers.delete(id);
  ui.evaluate("now += 500");
  await timer.callback();
  assert.equal(ui.evaluate("currentState.position"), 0);
  assert.equal([...ui.timers.values()][0].delay, 300);
  [id, timer] = [...ui.timers.entries()][0];
  ui.timers.delete(id);
  ui.evaluate("now += 300");
  await timer.callback();
  assert.equal(ui.evaluate("currentState.position"), 1);
  ui.evaluate("cardActivityReadUntil = now + 800; moveReplay(1)");
  assert.equal(ui.evaluate("currentState.position"), 2);
  assert.equal(ui.timers.size, 0);
});

test("continuous replay gives each pass its own reading time at fast speed", async () => {
  const ui = frontend();
  ui.element("replay-speed").value = "500";
  ui.evaluate(`let now = 10000; performance.now = () => now;
    replayMode = true;
    currentState = { is_replay: true, position: 0, positions: 3, steps: 2,
      mode: "replay", human_player: null, to_move: 2, selected_player: 0,
      hand: [], matrix: [], num_players: 3, legal: { reveals: [], pass: false },
      activity: { kind: "suggest", actor: 0, cards: [0, 7, 12] }, activity_event_number: 1,
      events: [{ kind: "pass", actor: 1, number: 2 }, { kind: "suggest", actor: 0, number: 1 }] };
    loadReplay = async () => { currentState.position = Number($("replay-position").value); return true; };
    renderCardInteraction(currentState); toggleReplayPlayback()`);
  let [id, timer] = [...ui.timers.entries()][0];
  ui.timers.delete(id);
  ui.evaluate("now += 500");
  await timer.callback();
  assert.equal(ui.evaluate("currentState.position"), 0);
  assert.equal([...ui.timers.values()][0].delay, 700);
  [id, timer] = [...ui.timers.entries()][0];
  ui.timers.delete(id);
  ui.evaluate("now += 700");
  await timer.callback();
  assert.equal(ui.evaluate("currentState.position"), 1);
  ui.evaluate("stopReplayPlayback()");
});

test("pausing ignores an in-flight replay response and playback errors stop explicitly", async () => {
  const ui = frontend();
  ui.element("replay-speed").value = "500";
  ui.element("replay-player").value = "0";
  ui.evaluate(`replayMode = true; currentState = { is_replay: true, position: 0, positions: 3 };
    requestJson = () => new Promise((resolve) => { globalThis.finishReplayRequest = resolve; });
    toggleReplayPlayback()`);
  let [id, timer] = [...ui.timers.entries()][0];
  ui.timers.delete(id);
  const pending = timer.callback();
  ui.evaluate("stopReplayPlayback(); finishReplayRequest({ is_replay: true, position: 1, positions: 3 })");
  await pending;
  assert.equal(ui.evaluate("currentState.position"), 0);
  assert.equal(ui.element("replay-position").value, "0");
  assert.equal(ui.timers.size, 0);

  ui.evaluate(`requestJson = async () => { throw new Error("offline"); }; toggleReplayPlayback()`);
  [id, timer] = [...ui.timers.entries()][0];
  ui.timers.delete(id);
  await timer.callback();
  assert.equal(ui.evaluate("replayPlaying"), false);
  assert.equal(ui.element("replay-position").value, "0");
  assert.match(ui.element("error-message").textContent, /offline/);
  assert.equal(ui.timers.size, 0);
});

test("clause entry selects notebook cells, validates, saves and preserves exclusions on edit", async () => {
  const ui = frontend({ notebook: true });
  const result = await ui.evaluate(`(async () => {
    currentState = {
      notebook_mode: "manual", num_players: 2, hand_sizes: [9, 9], notebook_revision: 0,
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

test("clause selection replaces the previous selection and can be cleared", () => {
  const ui = frontend();
  const values = ui.evaluate(`(() => {
    const result = [selectedClause];
    toggleClauseSelection(1); result.push(selectedClause);
    toggleClauseSelection(2); result.push(selectedClause);
    toggleClauseSelection(2); result.push(selectedClause);
    return result;
  })()`);
  assert.deepEqual(Array.from(values), [null, 1, 2, null]);
});

test("leaving clauses clears selection and refreshes the notebook in both workspaces", () => {
  const ui = frontend({ workspace: true });
  const result = ui.evaluate(`(() => {
    const updates = [];
    renderNotebook = () => updates.push("notebook");
    renderClauses = () => updates.push("clauses");
    currentState = {};
    document.body.classList.add("board-game");
    switchBoardTab("clauses");
    selectedClause = 1;
    switchBoardTab("clauses");
    const stillSelected = selectedClause;
    switchBoardTab("cards");
    const boardCleared = selectedClause;
    switchBoardTab("clauses");
    selectedClause = 2;
    switchBoardTab("history");
    const boardHistoryCleared = selectedClause;
    document.body.classList.remove("board-game");
    switchInsightsTab("clauses");
    selectedClause = 3;
    switchInsightsTab("help");
    return { stillSelected, boardCleared, boardHistoryCleared, cardsOnlyCleared: selectedClause, updates };
  })()`);
  assert.deepEqual(JSON.parse(JSON.stringify(result)), {
    stillSelected: 1, boardCleared: null, boardHistoryCleared: null, cardsOnlyCleared: null,
    updates: ["notebook", "clauses", "notebook", "clauses", "notebook", "clauses"],
  });
});

test("clause selection does not carry into another perspective or resolved clause", () => {
  const ui = frontend();
  const values = ui.evaluate(`(() => {
    const state = { selected_player: 0, notebook_mode: "automatic", notebook_clauses: [
      { id: 1, active_cards: [0] }, { id: 2, active_cards: [7] },
    ] };
    updateClausePerspective(state);
    selectedClause = 1;
    state.notebook_clauses[0].active_cards = [];
    updateClausePerspective(state);
    const remaining = selectedClause;
    selectedClause = 2;
    state.selected_player = 1;
    updateClausePerspective(state);
    return [remaining, selectedClause];
  })()`);
  assert.deepEqual(Array.from(values), [null, null]);
});

test("request errors retain HTTP status for JSON, HTML, and empty responses", async () => {
  const ui = frontend();
  const results = await ui.evaluate(`(async () => {
    const responses = [
      { ok: false, status: 400, headers: { get: () => "application/json" },
        json: async () => ({ error: "Bad input" }) },
      { ok: false, status: 500, headers: { get: () => "text/html" } },
      { ok: false, status: 503, headers: { get: () => null } },
      { ok: false, status: 502, headers: { get: () => "application/json" },
        json: async () => { throw new SyntaxError("invalid JSON"); } },
    ];
    const errors = [];
    for (const response of responses) {
      globalThis.fetch = async () => response;
      try { await requestJson("/test"); } catch (error) {
        errors.push({ message: error.message, status: error.status });
      }
    }
    return errors;
  })()`);
  assert.equal(results[0].message, "Bad input");
  assert.deepEqual(Array.from(results, (error) => error.status), [400, 500, 503, 502]);
  for (const error of results.slice(1)) assert.match(error.message, new RegExp(String(error.status)));
});

test("theme persistence failures are reported without reverting the active theme", () => {
  const ui = frontend();
  ui.evaluate(`
    document.documentElement = { dataset: {} };
    globalThis.localStorage = { setItem() { throw new Error("storage blocked"); } };
    setTheme("dark", true);
  `);
  assert.equal(ui.evaluate("document.documentElement.dataset.theme"), "dark");
  assert.match(ui.element("error-message").textContent, /Could not save theme: storage blocked/);
});

test("omniscient information uses a separate expandable panel", () => {
  const ui = frontend({ debug: true });
  ui.evaluate("renderDebug({ solution: [0, 7, 12], hands: [[0], [7]] })");
  assert.equal(ui.element("debug-panel").hidden, false);
  assert.ok(ui.element("debug-summary").textContent.includes("Miss Scarlet, Dagger, Kitchen"));
  assert.ok(ui.evaluate('document.body.classList.contains("debug-active")'));
  ui.element("debug-panel").open = true;
  ui.element("debug-content").append({ textContent: "private hand" });
  ui.evaluate("renderDebug(null)");
  assert.equal(ui.element("debug-panel").hidden, true);
  assert.equal(ui.element("debug-panel").open, false);
  assert.equal(ui.element("debug-content").children.length, 0);
  assert.equal(ui.element("debug-summary").textContent, "Omniscient information");
  assert.ok(!ui.evaluate('document.body.classList.contains("debug-active")'));
});

test("a failed clause save leaves the draft available for retry or cancellation", async () => {
  const ui = frontend({ notebook: true });
  const result = await ui.evaluate(`(async () => {
    currentState = { notebook_mode: "manual", num_players: 2, hand_sizes: [9, 9], matrix: [], notebook_revision: 0, notebook_clauses: [] };
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

test("history filters match multiple actors and event types in both lists", () => {
  const ui = frontend({ history: true });
  const events = [
    { number: 8, actor: 1, kind: "suggest", text: "Suggestion" },
    { number: 7, actor: 2, kind: "refute", text: "Refutation" },
    { number: 6, actor: 1, kind: "pass", text: "Pass" },
    { number: 5, actor: 3, kind: "suggest", text: "Suggestion" },
    { number: 4, actor: 2, kind: "suggest", text: "Suggestion" },
    { number: 3, actor: 1, kind: "refute", text: "Refutation" },
    { number: 2, actor: 0, kind: "refute", text: "Refutation" },
    { number: 1, actor: 2, kind: "pass", text: "Pass" },
  ];
  ui.renderHistory(events, [1, 2], ["suggest", "refute"]);
  const matchingNumbers = (list) => list.children.map((item) => item.children[0].textContent);
  assert.deepEqual(matchingNumbers(ui.element("history-list")), ["#8", "#7", "#4", "#3"]);
  assert.deepEqual(matchingNumbers(ui.element("action-history-list")), ["#8", "#7", "#4", "#3"]);

  ui.renderHistory(events, [], ["suggest", "refute"]);
  assert.equal(ui.element("history-list").children[0].textContent, "No events match these filters.");
  assert.equal(ui.element("action-history-list").children[0].textContent, "No events match these filters.");

  ui.renderHistory(events, [1], ["suggest"]);
  assert.equal(ui.element("history-list").children.length, 1);
  ui.evaluate("selectAllHistoryFilter('history-actor')");
  assert.equal(ui.element("history-list").children.length, 3);
});

test("card-information preset excludes movement and other non-card events", () => {
  const ui = frontend({ history: true });
  const kinds = [
    "suggest", "pass", "refute", "show", "expose", "accuse",
    "end_turn", "roll", "move", "passage", "suspect_moved", "weapon_moved",
  ];
  const events = kinds.map((kind, index) => ({
    number: kinds.length - index, actor: 0, kind, text: kind,
  }));
  ui.renderHistory(events);
  ui.evaluate("selectCardInfoHistoryTypes()");
  const checkedKinds = ui.evaluate(`
    Array.from($("history-kind").children)
      .filter((label) => label.children[0].checked)
      .map((label) => label.children[0].value)
  `);
  assert.deepEqual(Array.from(checkedKinds), [
    "suggest", "pass", "refute", "show", "expose", "accuse",
  ]);
  assert.equal(ui.element("history-list").children.length, 6);
  ui.evaluate("selectAllHistoryFilter('history-kind')");
  assert.equal(ui.element("history-list").children.length, kinds.length);
});

test("notebook renders overlapping clause references without replacing marks", () => {
  const ui = frontend({ notebook: true });
  const notebookState = {
    notebook_mode: "manual", num_players: 2, hand_sizes: [9, 9],
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
  const headers = all.filter((node) => node.tagName === "TH" && node.scope === "col");
  assert.ok(headers.some((node) => node.textContent === "P1 (9)"));
  assert.ok(headers.some((node) => node.textContent === "P2 (9)"));
  assert.equal(all.filter((node) => node.tagName === "TABLE").length, 1);
  assert.equal(all.filter((node) => node.tagName === "THEAD").length, 1);
  assert.equal(all.filter((node) => node.tagName === "TBODY").length, 3);
  const table = all.find((node) => node.tagName === "TABLE");
  assert.equal(table.children[0].children[0].children.length, 4);
  assert.deepEqual(
    table.children.slice(1).map((body) => body.children[0].children[0].colSpan),
    [4, 4, 4],
  );
  const links = all.filter((node) => node.dataset.clauseCard);
  assert.equal(links.length, 3);
  assert.match(links[0]["aria-label"], /clause 1/);
  assert.match(links[1]["aria-label"], /clause 2/);
  assert.notEqual(links[0].style["--clause-color"], links[1].style["--clause-color"]);
  assert.equal(links[0].style["--clause-color"], links[2].style["--clause-color"]);
  assert.equal(links[0]["aria-pressed"], "false");
  const mark = all.find((node) => node.dataset.notebookCard === "0" && node.dataset.notebookHolder === "1");
  assert.equal(mark.textContent, "+");
  ui.evaluate("selectedClause = 1");
  ui.renderNotebook(notebookState);
  const selected = descendants(ui.element("notebook"));
  const selectedLinks = selected.filter((node) => node.dataset.clauseCard);
  assert.equal(selected.find((node) => node.tagName === "TABLE"), table);
  assert.equal(selectedLinks[0], links[0]);
  assert.equal(selectedLinks[0]["aria-pressed"], "true");
  assert.equal(selectedLinks[1]["aria-pressed"], "false");
  assert.equal(selectedLinks[0].style["--clause-color"], links[0].style["--clause-color"]);
  assert.equal(selected.filter((node) => node.classList.contains("clause-linked-selected")).length, 2);
  ui.evaluate("selectedClause = null");
  ui.renderNotebook(notebookState);
  assert.equal(links[0]["aria-pressed"], "false");
  assert.equal(descendants(ui.element("notebook"))
    .filter((node) => node.classList.contains("clause-linked-selected")).length, 0);
  assert.equal(ui.element("notebook").children[0], table);
  notebookState.notebook_clauses[0].active_cards = [];
  ui.renderNotebook(notebookState);
  const remaining = descendants(ui.element("notebook")).filter((node) => node.dataset.clauseCard);
  assert.equal(remaining.length, 1);
  assert.match(remaining[0]["aria-label"], /clause 2/);
  assert.equal(remaining[0].style["--clause-color"], links[1].style["--clause-color"]);
});

test("manual notebook clause markers dim for negative and positive marks", () => {
  const ui = frontend({ notebook: true });
  const state = {
    notebook_mode: "manual", num_players: 3, hand_sizes: [9, 9, 9],
    matrix: [
      { id: 0, name: "Miss Scarlet", type: "suspect", marks: ["?", "-", "?", "?"], editable: [true, true, true, true] },
      { id: 7, name: "Dagger", type: "weapon", marks: ["?", "?", "+", "?"], editable: [true, true, true, true] },
      { id: 12, name: "Kitchen", type: "room", marks: ["?", "?", "?", "?"], editable: [true, true, true, true] },
    ],
    notebook_clauses: [
      { id: 1, holder: 1, active_cards: [0, 7] },
      { id: 2, holder: 2, active_cards: [7, 12] },
    ],
  };
  ui.renderNotebook(state);
  ui.evaluate("currentState = state");
  const notebook = ui.element("notebook");
  function descendants(node) {
    return [node, ...node.children.flatMap(descendants)];
  }
  notebook.querySelector = (selector) => {
    const match = selector.match(/data-notebook-card="(\d+)".*data-notebook-holder="(\d+)"/);
    return match && descendants(notebook).find((node) =>
      node.dataset.notebookCard === match[1] && node.dataset.notebookHolder === match[2]);
  };
  const findMarker = (card, clause) => descendants(notebook).find((node) =>
    node.dataset.clauseCard === String(card) && node.dataset.clauseId === String(clause));
  assert.equal(findMarker(0, 1).classList.contains("clause-marker-dimmed"), true);
  assert.equal(findMarker(7, 1).classList.contains("clause-marker-dimmed"), false);
  assert.equal(findMarker(7, 2).classList.contains("clause-marker-dimmed"), true);
  assert.equal(findMarker(12, 2).classList.contains("clause-marker-dimmed"), true);

  const table = notebook.children[0];
  ui.evaluate('pendingNotebookEdits.push({ cardId: 0, holder: 1, mark: "?" })');
  ui.renderNotebook(state);
  assert.equal(notebook.children[0], table);
  assert.equal(findMarker(0, 1).classList.contains("clause-marker-dimmed"), false);
  ui.evaluate("pendingNotebookEdits = []");
  ui.renderNotebook(state);
  assert.equal(findMarker(0, 1).classList.contains("clause-marker-dimmed"), true);

  state.matrix[0].marks[1] = "?";
  state.matrix[1].marks[2] = "?";
  ui.renderNotebook(state);
  assert.equal(notebook.children[0], table);
  assert.equal(findMarker(0, 1).classList.contains("clause-marker-dimmed"), false);
  assert.equal(findMarker(7, 2).classList.contains("clause-marker-dimmed"), false);
  assert.equal(findMarker(12, 2).classList.contains("clause-marker-dimmed"), false);

  state.notebook_mode = "automatic";
  ui.renderNotebook(state);
  assert.equal(findMarker(0, 1).classList.contains("clause-marker-dimmed"), false);
});

test("clause indicators stay out of notebook row layout and remain separate when crowded", () => {
  const containerRule = stylesheet.match(/\.clause-indicators\s*\{([^}]*)\}/);
  const indicatorRule = stylesheet.match(/\.clause-indicator\s*\{([^}]*)\}/);
  assert.ok(containerRule);
  assert.match(containerRule[1], /position:\s*absolute/);
  assert.doesNotMatch(containerRule[1], /flex-wrap:\s*wrap/);
  assert.ok(indicatorRule);
  assert.match(indicatorRule[1], /flex:\s*0\s+1\s+10px/);
  assert.match(indicatorRule[1], /min-width:\s*0/);

  const ui = frontend({ notebook: true });
  const state = {
    notebook_mode: "manual", num_players: 2, hand_sizes: [9, 9],
    matrix: [{ id: 0, name: "Miss Scarlet", type: "suspect", marks: ["?", "?", "?"],
      editable: [true, true, true] }],
    notebook_clauses: Array.from({ length: 20 }, (_, id) => ({ id, holder: 0, active_cards: [0] })),
  };
  ui.renderNotebook(state);
  const cell = ui.element("notebook").children[0].children[1].children[1].children[1];
  assert.equal(cell.children[0].dataset.notebookCard, "0");
  assert.equal(cell.children[1].children.length, 20);
  assert.equal(new Set(cell.children[1].children.map((indicator) => indicator.dataset.clauseId)).size, 20);
});

test("clause list colors match notebook colors and selection survives filtering", () => {
  const ui = frontend({ notebook: true });
  const state = {
    notebook_mode: "manual", num_players: 2, hand_sizes: [9, 9],
    matrix: [{ id: 0, name: "Miss Scarlet", type: "suspect", marks: ["?", "?", "?"],
      editable: [true, true, true] }],
    notebook_clauses: [
      { id: 7, holder: 1, actor: 0, kind: "refute", cards: [0], active_cards: [0], excluded_cards: [], status: "unresolved" },
      { id: 3, holder: 1, actor: 1, kind: "refute", cards: [0], active_cards: [0], excluded_cards: [], status: "unresolved" },
      { id: 2, holder: 0, actor: 0, kind: "refute", cards: [0], active_cards: [], excluded_cards: [], status: "resolved" },
    ],
  };
  ui.renderNotebook(state);
  ui.evaluate("selectedClause = 7");
  ui.evaluate("renderClauses(state)");
  const items = ui.element("clauses").children;
  assert.ok(items[0].classList.contains("clause-selected"));
  assert.equal(items[0].children[0]["aria-pressed"], "true");
  assert.equal(items[2].children[0].disabled, true);
  const colors = items.map((item) => item.style["--clause-color"]);
  const notebookColors = ui.element("notebook").children[0].children[1].children[1].children[2]
    .children[1].children.map((indicator) => indicator.style["--clause-color"]);
  assert.deepEqual(notebookColors, colors.slice(0, 2));
  assert.notEqual(colors[0], colors[1]);
  assert.equal(colors[1], colors[2]);
  ui.element("clause-actor").value = "0";
  ui.evaluate("renderClauses(state)");
  assert.equal(ui.element("clauses").children[0].style["--clause-color"], colors[0]);
  assert.equal(ui.evaluate("selectedClause"), 7);
});

test("clause colors stay distinct for the first two palette cycles in a column", () => {
  const ui = frontend();
  const colors = ui.evaluate(`(() => {
    const clauses = Array.from({ length: 24 }, (_, id) => ({ id, holder: 0 }));
    return clauses.map((clause) => clauseColor(clause, clauses));
  })()`);
  assert.equal(new Set(colors).size, 24);
});

test("replay flags group positions, filter discoveries and support next/previous navigation", () => {
  const ui = frontend();
  ui.evaluate(`cardIllustration = (id) => {
    const svg = document.createElement("svg"); svg.dataset.cardId = String(id); return svg;
  }`);
  ui.evaluate('replayMarkerType = "all"; replayMarkerPlayer = "all"');
  ui.evaluate(`currentState = {
    is_replay: true, num_players: 2, positions: 11, position: 0,
    deduction_timeline: [
      { player: 0, holder: 2, card: 0, step: 0, position: 0 },
      { player: 1, holder: 2, card: 7, step: 4, position: 6 },
      { player: 0, holder: 1, card: 12, step: 4, position: 6 },
      { player: 1, holder: 0, card: 0, step: 5, position: 7 },
    ],
  }; renderReplayMarkers(currentState)`);
  const markers = ui.element("replay-markers");
  assert.equal(markers.children.length, 3);
  assert.equal(markers.children[0].style.left, "0%");
  assert.equal(markers.children[1].style.left, "60%");
  const groupedBadges = markers.children[1].children[0].children;
  assert.deepEqual(groupedBadges.map((badge) => badge.children[1].textContent), ["1", "2"]);
  assert.deepEqual(groupedBadges.map((badge) => badge.children[0].dataset.cardId), ["12", "7"]);
  assert.notEqual(groupedBadges[0].style["--player-color"], groupedBadges[1].style["--player-color"]);
  assert.match(markers.children[1]["aria-label"], /Player 2 inferred Dagger in the envelope/);
  assert.match(markers.children[1]["aria-label"], /Player 1 inferred Kitchen in Player 2/);
  assert.equal(markers.children[0]["aria-current"], "true");
  const marker = markers.children[1];
  ui.evaluate("currentState.position = 6; renderReplayMarkers(currentState)");
  assert.equal(markers.children[1], marker);
  assert.equal(marker["aria-current"], "true");
  assert.match(ui.element("replay-marker-details").textContent, /Player 2 inferred Dagger/);
  ui.evaluate("loadReplay = () => {}; moveReplayMarker(1)");
  assert.equal(ui.element("replay-position").value, "7");
  ui.evaluate("moveReplayMarker(-1)");
  assert.equal(ui.element("replay-position").value, "0");
  ui.evaluate('replayMarkerType = "holder"; replayMarkerPlayer = "0"');
  ui.evaluate("renderReplayMarkers(currentState)");
  assert.equal(markers.children.length, 1);
  assert.equal(markers.children[0].dataset.replayPosition, "6");
  const cardBadge = markers.children[0].children[0].children[0];
  assert.equal(cardBadge.className, "replay-card-badge room");
  assert.equal(cardBadge.children[0].dataset.cardId, "12");
  ui.evaluate('replayMarkerType = "none"');
  ui.evaluate("renderReplayMarkers(currentState)");
  assert.equal(markers.children.length, 0);
  assert.equal(ui.element("replay-marker-status").textContent, "No matching flags");
  assert.equal(ui.element("replay-next-marker").disabled, true);
});

test("replay knowledge table emphasizes locations and compares all players by category", () => {
  const ui = frontend();
  ui.evaluate(`currentState = { is_replay: true, knowledge_summary: [
    { player: 0, categories: {
      suspect: { located: 2, total: 6, marks: 10, mark_total: 18, envelope: 1 },
      weapon: { located: 1, total: 6, marks: 7, mark_total: 18, envelope: 0 },
      room: { located: 3, total: 9, marks: 14, mark_total: 27, envelope: 0 },
    } },
    { player: 1, categories: {
      suspect: { located: 3, total: 6, marks: 12, mark_total: 18, envelope: 0 },
      weapon: { located: 2, total: 6, marks: 8, mark_total: 18, envelope: 1 },
      room: { located: 4, total: 9, marks: 16, mark_total: 27, envelope: 1 },
    } },
  ] }; renderReplayKnowledge(currentState.knowledge_summary)`);
  let rows = ui.element("replay-knowledge-body").children;
  assert.equal(rows.length, 2);
  assert.equal(rows[0].children[0].children[1].textContent, "Player 2");
  assert.equal(rows[1].children[1].children[0].textContent, "6/21 located");
  assert.equal(rows[1].children[1].children[1].textContent, "31/63 marks");
  assert.equal(rows[1].children[2].children[0].textContent, "2/6 located");
  assert.equal(rows[0].children[5].children[0].textContent, "2/3");
  assert.equal(ui.element("replay-knowledge-head-total")["aria-sort"], "descending");
  ui.evaluate('setReplayKnowledgeSort("total")');
  rows = ui.element("replay-knowledge-body").children;
  assert.equal(rows[0].children[0].children[1].textContent, "Player 1");
  assert.equal(ui.element("replay-knowledge-head-total")["aria-sort"], "ascending");
  ui.evaluate('setReplayKnowledgeSort("suspect"); setReplayKnowledgeColumn("suspect", false)');
  rows = ui.element("replay-knowledge-body").children;
  assert.equal(ui.element("replay-knowledge-head-suspect").hidden, true);
  assert.equal(ui.element("replay-knowledge-head-total")["aria-sort"], "descending");
  assert.equal(rows[0].children.length, 5);
  ui.evaluate(`for (const column of ["total", "weapon", "room", "envelope"])
    setReplayKnowledgeColumn(column, false)`);
  rows = ui.element("replay-knowledge-body").children;
  assert.equal(ui.element("replay-knowledge-head-player")["aria-sort"], "ascending");
  assert.equal(rows[0].children.length, 1);
  assert.equal(rows[0].children[0].children[1].textContent, "Player 1");
  ui.evaluate('setReplayKnowledgeColumn("room", true); setReplayKnowledgeSort("room")');
  rows = ui.element("replay-knowledge-body").children;
  assert.equal(rows[0].children[0].children[1].textContent, "Player 2");
  assert.equal(rows[0].children.length, 2);
  ui.evaluate(`currentState.knowledge_summary[0].categories.room.located = 4;
    currentState.knowledge_summary[0].categories.room.marks = 20;
    renderReplayKnowledge(currentState.knowledge_summary)`);
  rows = ui.element("replay-knowledge-body").children;
  assert.equal(rows[0].children[0].children[1].textContent, "Player 1");
  assert.equal(ui.element("replay-knowledge-head-room")["aria-sort"], "descending");
});

test("crowded replay flags retain all players in their details and category filters", () => {
  const ui = frontend();
  ui.evaluate(`cardIllustration = (id) => {
    const svg = document.createElement("svg"); svg.dataset.cardId = String(id); return svg;
  }`);
  ui.evaluate('replayMarkerType = "all"; replayMarkerPlayer = "all"');
  ui.evaluate(`currentState = {
    is_replay: true, num_players: 8, positions: 3, position: 0,
    deduction_timeline: [
      ...Array.from({ length: 8 }, (_, player) => ({ player, holder: 8, card: 0, step: 1, position: 1 })),
      { player: 7, holder: 8, card: 7, step: 1, position: 1 },
      { player: 7, holder: 8, card: 12, step: 1, position: 1 },
      { player: 7, holder: 8, card: 13, step: 1, position: 1 },
    ],
  }; renderReplayMarkers(currentState)`);
  const marker = ui.element("replay-markers").children[0];
  assert.deepEqual(marker.children[0].children.map((badge) =>
    badge.children.length ? badge.children[1].textContent : badge.textContent),
  ["1", "2", "3", "4", "5", "+6"]);
  assert.match(marker["aria-label"], /Player 8 inferred Dagger/);
  ui.evaluate('replayMarkerPlayer = "7"');
  ui.evaluate("renderReplayMarkers(currentState)");
  const cardBadges = ui.element("replay-markers").children[0].children[0].children;
  assert.deepEqual(cardBadges.map((badge) => badge.className),
    ["replay-card-badge suspect", "replay-card-badge weapon", "replay-card-badge room",
      "replay-card-badge room"]);
  assert.deepEqual(cardBadges.map((badge) => badge.children[0].dataset.cardId), ["0", "7", "12", "13"]);
});

test("notebook highlights turn, actor, cards and visible reveal without disturbing clauses", () => {
  const ui = frontend({ notebook: true });
  const state = {
    notebook_mode: "manual", num_players: 2, hand_sizes: [9, 9],
    matrix: [
      { id: 0, name: "Miss Scarlet", type: "suspect", marks: ["?", "+", "?"], editable: [true, true, true] },
      { id: 7, name: "Dagger", type: "weapon", marks: ["?", "-", "?"], editable: [true, true, true] },
      { id: 13, name: "Ballroom", type: "room", marks: ["?", "?", "?"], editable: [true, true, true] },
    ],
    notebook_clauses: [{ id: 1, holder: 1, active_cards: [0, 7] }],
    notebook_focus: {
      turn: 0, actor: 1, kind: "suggest", cards: [0, 7], shown: { card: 7, holder: 1 },
    },
  };
  function descendants(node) {
    return [node, ...node.children.flatMap(descendants)];
  }
  ui.renderNotebook(state);
  let all = descendants(ui.element("notebook"));
  const header0 = all.find((node) => node.dataset.notebookSeat === "0");
  const header1 = all.find((node) => node.dataset.notebookSeat === "1");
  assert.ok(header0.classList.contains("notebook-turn"));
  assert.ok(!header0.classList.contains("notebook-actor"));
  assert.ok(header1.classList.contains("notebook-actor"));
  assert.match(header1["aria-label"], /acting now/);
  let row = all.find((node) => node.dataset.cardId === "7");
  assert.ok(row.classList.contains("notebook-card-focus"));
  assert.ok(row.children[1].classList.contains("notebook-turn"));
  assert.ok(row.children[2].classList.contains("notebook-actor"));
  assert.ok(row.children[2].classList.contains("notebook-shown"));
  assert.match(row.children[2].children[0]["aria-label"], /current suggestion; visibly shown/);
  assert.equal(all.filter((node) => node.dataset.clauseCard).length, 2);

  state.notebook_focus = { turn: 0, actor: null, kind: "suggest", cards: [0, 7], shown: null };
  ui.renderNotebook(state);
  all = descendants(ui.element("notebook"));
  row = all.find((node) => node.dataset.cardId === "7");
  assert.ok(row.classList.contains("notebook-card-focus"));
  assert.ok(row.children[1].classList.contains("notebook-turn"));
  assert.ok(!row.children[2].classList.contains("notebook-actor"));
  assert.ok(!row.children[2].classList.contains("notebook-shown"));

  state.notebook_focus = { turn: 1, actor: 1, kind: null, cards: [], shown: null };
  ui.renderNotebook(state);
  all = descendants(ui.element("notebook"));
  row = all.find((node) => node.dataset.cardId === "7");
  assert.ok(!row.classList.contains("notebook-card-focus"));
  assert.ok(!row.children[2].classList.contains("notebook-shown"));
  assert.ok(row.children[2].classList.contains("notebook-turn"));
  assert.ok(row.children[2].classList.contains("notebook-actor"));
  assert.equal(all.filter((node) => node.dataset.clauseCard).length, 2);
});

test("notebook actor highlighting uses inset decoration instead of changing borders", () => {
  assert.match(stylesheet, /\.notebook-table th\.notebook-actor\s*\{\s*box-shadow:/);
  assert.match(stylesheet, /\.notebook-table th\.notebook-turn\.notebook-actor\s*\{\s*box-shadow:/);
});

test("notebook highlights every completed response and clears it at the right boundary", () => {
  const ui = frontend({ notebook: true });
  const state = {
    notebook_mode: "manual", num_players: 4, hand_sizes: [5, 5, 4, 4],
    matrix: [{ id: 0, name: "Miss Scarlet", type: "suspect",
      marks: ["?", "?", "?", "?", "?"], editable: [true, true, true, true, true] }],
    notebook_clauses: [],
    notebook_focus: { turn: 0, actor: 2, kind: "suggest", cards: [0], shown: null },
    events: [{ kind: "suggest", actor: 0 }],
    waiting_for_turn: false,
  };
  const descendants = (node) => [node, ...node.children.flatMap(descendants)];
  const column = (seat) => descendants(ui.element("notebook"))
    .find((node) => node.dataset.notebookSeat === String(seat));
  const cell = (seat) => descendants(ui.element("notebook"))
    .find((node) => node.dataset.cardId === "0").children[seat + 1];
  ui.renderNotebook(state);
  assert.ok(!column(1).classList.contains("notebook-pass"));

  state.events.unshift({ kind: "pass", actor: 1 });
  ui.renderNotebook(state);
  assert.ok(column(1).classList.contains("notebook-pass"));
  assert.ok(cell(1).classList.contains("notebook-pass"));
  assert.match(column(1)["aria-label"], /passed/);
  assert.match(cell(1).children[0]["aria-label"], /passed/);
  assert.ok(column(2).classList.contains("notebook-actor"));

  state.events.unshift({ kind: "show", actor: 2 }, { kind: "refute", actor: 2 });
  ui.renderNotebook(state);
  assert.ok(column(1).classList.contains("notebook-pass"));
  assert.ok(column(2).classList.contains("notebook-refute"));
  assert.ok(column(2).classList.contains("notebook-actor"));
  assert.match(cell(2).children[0]["aria-label"], /acting now, refuted/);
  state.events.unshift({ kind: "refute", actor: 3 });
  ui.renderNotebook(state);
  assert.ok(column(2).classList.contains("notebook-refute"));
  assert.ok(column(3).classList.contains("notebook-refute"));

  state.events.unshift({ kind: "end_turn", actor: 0 });
  state.waiting_for_turn = true;
  ui.renderNotebook(state);
  assert.ok(column(1).classList.contains("notebook-pass"));
  assert.ok(column(3).classList.contains("notebook-refute"));

  state.waiting_for_turn = false;
  state.notebook_focus = { turn: 1, actor: 1, kind: null, cards: [], shown: null };
  ui.renderNotebook(state);
  assert.ok(!column(1).classList.contains("notebook-pass"));
  assert.ok(!column(2).classList.contains("notebook-refute"));

  state.notebook_focus = { turn: 1, actor: 2, kind: "suggest", cards: [0], shown: null };
  state.events.unshift({ kind: "suggest", actor: 1 });
  ui.renderNotebook(state);
  assert.ok(!column(1).classList.contains("notebook-pass"));
  assert.ok(!column(2).classList.contains("notebook-refute"));
  state.events.unshift({ kind: "pass", actor: 3 });
  ui.renderNotebook(state);
  assert.ok(column(3).classList.contains("notebook-pass"));
  assert.ok(!column(3).classList.contains("notebook-refute"));
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
    hand: [], matrix: [], num_players: 2,
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

test("one turn button changes action and stays hidden when unavailable", () => {
  const ui = frontend();
  const legal = { ...state().legal, end_turn: true };
  ui.render(state({ legal }));
  const button = ui.element("turn-button");
  assert.equal(button.hidden, false);
  assert.equal(button.textContent, "End turn");
  ui.render(state({ waiting_for_turn: true, legal: { ...legal, end_turn: false } }));
  assert.equal(button.hidden, false);
  assert.equal(button.textContent, "Next turn");
  ui.render(state({ legal: { ...legal, end_turn: false } }));
  assert.equal(button.hidden, true);
});

test("turn button submits the appropriate action for each state", () => {
  const ui = frontend();
  const calls = ui.evaluate(`(() => {
    const calls = [];
    nextTurn = () => calls.push("next");
    submitAction = (action) => calls.push(action.action);
    currentState = { waiting_for_turn: false, legal: { end_turn: true } };
    useTurnButton();
    currentState = { waiting_for_turn: true, legal: { end_turn: false } };
    useTurnButton();
    currentState = { waiting_for_turn: false, legal: { end_turn: false } };
    useTurnButton();
    return calls;
  })()`);
  assert.deepEqual(Array.from(calls), ["end_turn", "next"]);
});

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

test("a reveal animates once per new event and respects reduced motion", () => {
  const ui = frontend();
  ui.render(state({
    events: [{ kind: "show", number: 4 }], legal: {
      ...state().legal, suggest: false, accuse: false,
    },
  }));
  assert.ok(ui.element("focus-cards").children[0].classList.contains("reveal-enter"));
  ui.evaluate("renderCardInteraction(state)");
  assert.ok(!ui.element("focus-cards").children[0].classList.contains("reveal-enter"));
  ui.evaluate("state.steps++; state.events.unshift({ kind: 'move', number: 5 }); renderCardInteraction(state)");
  assert.ok(!ui.element("focus-cards").children[0].classList.contains("reveal-enter"));
  ui.evaluate("state.steps++; state.events.unshift({ kind: 'show', number: 6 }); renderCardInteraction(state)");
  assert.ok(ui.element("focus-cards").children[0].classList.contains("reveal-enter"));
  ui.evaluate("window.matchMedia = () => ({ matches: true }); state.steps++; state.events.unshift({ kind: 'show', number: 7 }); renderCardInteraction(state)");
  assert.ok(!ui.element("focus-cards").children[0].classList.contains("reveal-enter"));
});

test("private spectator reveals use the selected view's event identity", () => {
  const ui = frontend();
  ui.render(state({
    mode: "spectate", selected_player: 0, activity_event_number: 3,
    events: [{ kind: "refute", number: 2 }, { kind: "suggest", number: 1 }],
    legal: { ...state().legal, suggest: false, accuse: false },
  }));
  assert.ok(ui.element("focus-cards").children[0].classList.contains("reveal-enter"));
  ui.evaluate("state.steps++; state.events.unshift({ kind: 'move', number: 3 }); renderCardInteraction(state)");
  assert.ok(!ui.element("focus-cards").children[0].classList.contains("reveal-enter"));
  ui.evaluate("state.steps++; state.activity_event_number = 7; renderCardInteraction(state)");
  assert.ok(ui.element("focus-cards").children[0].classList.contains("reveal-enter"));
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
