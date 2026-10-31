"use strict";

window.setupWizard = (() => {
  const strategyLabels = {
    candidate_suggestions: "Favor possible solution cards",
    probe_suggestions: "Probe unknown cards using known controls",
    rank_suggestions: "Rank suggestions using deduction and responders",
    repeat_reveals: "Repeat cards already shown to the same player",
    candidate_rooms: "Favor possible solution rooms (board only)",
    prefer_suggest: "Favor suggesting when possible (cards only)",
  };
  const presets = {
    random: {},
    deductive: { candidate_suggestions: true, candidate_rooms: true, prefer_suggest: true },
    probing: {
      candidate_suggestions: true, probe_suggestions: true, repeat_reveals: true,
      candidate_rooms: true, prefer_suggest: true,
    },
    strategic: {
      candidate_suggestions: true, probe_suggestions: true, rank_suggestions: true,
      repeat_reveals: true, candidate_rooms: true, prefer_suggest: true,
    },
  };
  const presetDescriptions = {
    random: "Random decisions; shared deduction and movement.",
    deductive: "Favors possible solution cards and useful rooms.",
    probing: "Adds controlled probes and repeats previously shown cards.",
    strategic: "Ranks suggestions using responders, knowledge, and unresolved clauses.",
  };
  const weights = {
    candidate_suggestions: 20, probe_suggestions: 15, rank_suggestions: 15,
    repeat_reveals: 15, candidate_rooms: 15, prefer_suggest: 10,
  };
  const ruleIds = {
    move_suspect: "rule-move-suspect", move_weapon: "rule-move-weapon",
    summoned_suggestion: "rule-summoned", secret_passages: "rule-passages",
  };
  const storageKey = "clue-engine-setup-profiles";
  let step = 0;
  let characters = [0, 1, 2, 3, 4, 5];
  let bots = [];
  let metadata = null;
  let highlightedSeat = 0;
  let lastSetup = null;
  let profiles = Object.create(null);
  let profilesReady = false;

  function isBoard() {
    return document.querySelector('input[name="game-type"]:checked').value === "board";
  }

  function strategy(value) {
    const source = typeof value === "string" ? presets[value] : value;
    if (!source || typeof source !== "object") throw new Error("Invalid bot configuration.");
    return Object.fromEntries(Object.keys(strategyLabels).map((key) => [key, source[key] === true]));
  }

  function score(value) {
    const settings = strategy(value);
    const applicable = Object.keys(weights).filter((key) =>
      isBoard() ? key !== "prefer_suggest" : key !== "candidate_rooms"
    );
    const total = applicable.reduce((sum, key) => sum + weights[key], 0);
    return Math.round(100 * applicable.reduce(
      (sum, key) => sum + (settings[key] ? weights[key] : 0), 0
    ) / total);
  }

  function copy(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function rollSeed() {
    if (!window.crypto || !window.crypto.getRandomValues) {
      throw new Error("Secure random seed generation is unavailable. Enter a seed manually.");
    }
    const previous = $("seed").value;
    const random = new Uint32Array(1);
    do { window.crypto.getRandomValues(random); } while (String(random[0]) === previous);
    $("seed").value = String(random[0]);
  }

  function validBasics() {
    updateGameType();
    for (const id of ["players", "seed", "max-steps"]) {
      if (!$(id).validity.valid || $(id).value === "") {
        showStep(0, false);
        const details = $(id).closest("details");
        if (details) details.open = true;
        $(id).reportValidity();
        return false;
      }
    }
    if (isBoard() && !metadata) {
      showError("Board starting positions are unavailable. Reload the page and try again.");
      return false;
    }
    return true;
  }

  function syncSeats() {
    const count = Number($("players").value);
    if (!Number.isInteger(count) || count < 2 || (isBoard() && count > 6)) return;
    while (bots.length < count) bots.push("random");
    const oldSeat = Number($("seat").value || 0);
    const human = Math.min(oldSeat, count - 1);
    if (oldSeat !== human) $("seat-notice").textContent = `Your seat moved to Player ${human + 1}.`;
    $("seat").replaceChildren(...Array.from({ length: count }, (_, i) => option(i, `Player ${i + 1}`)));
    $("seat").value = String(human);
    if (isBoard()) {
      const active = characters.slice(0, count);
      const used = new Set();
      for (let i = 0; i < count; i++) {
        if (!Number.isInteger(active[i]) || used.has(active[i])) {
          active[i] = [0, 1, 2, 3, 4, 5].find((id) => !used.has(id));
        }
        used.add(active[i]);
      }
      if (!used.has(0)) {
        const replacement = active.findIndex((_, i) => i !== human);
        active[replacement < 0 ? 0 : replacement] = 0;
        $("seat-notice").textContent = "Miss Scarlet was assigned to a bot because she starts the game.";
      }
      active.forEach((value, i) => { characters[i] = value; });
    }
    highlightedSeat = Math.min(highlightedSeat, count - 1);
    renderSeats();
    renderBots();
    renderRules();
  }

  function renderSeats() {
    const count = Number($("players").value);
    const human = $("mode").value === "play" ? Number($("seat").value) : null;
    const list = $("seat-list");
    list.replaceChildren();
    for (let i = 0; i < count; i++) {
      const row = document.createElement("div");
      row.className = "setup-seat";
      const label = document.createElement("label");
      label.textContent = `Player ${i + 1}${i === human ? " (you)" : " (bot)"}`;
      if (isBoard()) {
        const select = document.createElement("select");
        select.dataset.characterSeat = String(i);
        for (const card of cardsByType.suspect) select.append(option(card.id, card.name));
        select.value = String(characters[i]);
        label.append(select);
      }
      row.append(label);
      if (isBoard() && characters[i] === 0) {
        const hint = document.createElement("small");
        hint.textContent = "Starts the game";
        row.append(hint);
      }
      list.append(row);
    }
    $("setup-board-preview").hidden = !isBoard();
    renderPreview();
  }

  function renderPreview() {
    if (!isBoard() || !metadata) return;
    const map = $("setup-board-map");
    buildBoardBase(metadata.layout, map, "setup-board-dynamic");
    const group = $("setup-board-dynamic");
    const count = Number($("players").value);
    for (const start of metadata.starts) {
      const seat = characters.slice(0, count).indexOf(start.suspect_id);
      const active = seat === highlightedSeat;
      const style = pawnStyles[start.suspect_id];
      const label = `${cardName(start.suspect_id)}: ${seat < 0 ? "unassigned" : `Player ${seat + 1}`}`;
      const marker = svgElement("g", { role: "img", "aria-label": label });
      marker.append(svgElement("title", {}, label));
      marker.append(svgElement("circle", {
        cx: start.x + .5, cy: start.y + .5, r: active ? .62 : .43,
        fill: style.color, class: active ? "setup-preview-active" : "setup-preview-pawn",
      }));
      marker.append(svgElement("text", {
        x: start.x + .5, y: start.y + .6, fill: style.ink, class: "board-pawn-text",
      }, seat < 0 ? style.label : String(seat + 1)));
      group.append(marker);
    }
  }

  function selectCharacter(index, value) {
    const previous = characters[index];
    const count = Number($("players").value);
    const other = characters.slice(0, count).indexOf(value);
    characters[index] = value;
    if (other >= 0 && other !== index) characters[other] = previous;
    if (!characters.slice(0, count).includes(0)) {
      const human = $("mode").value === "play" ? Number($("seat").value) : -1;
      const replacement = characters.slice(0, count).findIndex((_, i) => i !== index && i !== human);
      characters[replacement < 0 ? (index + 1) % count : replacement] = 0;
      $("seat-notice").textContent = "Miss Scarlet was assigned to another seat because she starts.";
    } else {
      $("seat-notice").textContent = other >= 0 && other !== index ? "Characters were swapped." : "";
    }
    highlightedSeat = index;
    renderSeats();
    const select = document.querySelector(`[data-character-seat="${index}"]`);
    if (select) select.focus();
  }

  function renderBots() {
    const count = Number($("players").value);
    if (!Number.isInteger(count) || count < 2 || (isBoard() && count > 6)) return;
    const human = $("mode").value === "play" ? Number($("seat").value) : null;
    const list = $("bot-list");
    list.replaceChildren();
    list.dataset.botCount = String(count - (human === null ? 0 : 1));
    for (let i = 0; i < count; i++) {
      if (i === human) continue;
      const value = bots[i];
      const row = document.createElement("div");
      row.className = "setup-seat";
      const label = document.createElement("label");
      label.textContent = `Player ${i + 1} bot`;
      const select = document.createElement("select");
      select.dataset.botSeat = String(i);
      for (const name of Object.keys(presets)) select.append(option(name, name[0].toUpperCase() + name.slice(1)));
      select.append(option("custom", "Custom"));
      select.value = typeof value === "string" ? value : "custom";
      label.append(select);
      const summary = document.createElement("p");
      summary.className = "hint bot-score";
      summary.dataset.botScore = String(i);
      summary.textContent = `Toolkit: ${score(value)}/100`;
      const description = document.createElement("p");
      description.className = "hint";
      description.textContent = typeof value === "string" ? presetDescriptions[value]
        : "Custom choices use probes first, then candidate filtering, followed by optional ranking.";
      const copyLabel = document.createElement("label");
      copyLabel.className = "bot-copy";
      copyLabel.textContent = "Copy from";
      const copySelect = document.createElement("select");
      copySelect.dataset.copySeat = String(i);
      const otherBotCount = count - (human === null ? 0 : 1) - 1;
      copySelect.disabled = otherBotCount === 0;
      copySelect.append(option("", otherBotCount ? "Choose a bot" : "No other bots"));
      for (let j = 0; j < count; j++) {
        if (j !== i && j !== human) copySelect.append(option(j, `Player ${j + 1}`));
      }
      copyLabel.append(copySelect);
      row.append(label, summary, description, copyLabel);
      if (typeof value !== "string") {
        const options = document.createElement("fieldset");
        const legend = document.createElement("legend");
        legend.textContent = "Custom strategies";
        options.append(legend);
        for (const [key, text] of Object.entries(strategyLabels)) {
          if ((key === "candidate_rooms" && !isBoard()) || (key === "prefer_suggest" && isBoard())) continue;
          const item = document.createElement("label");
          item.className = "check-row";
          const input = document.createElement("input");
          input.type = "checkbox";
          input.checked = value[key] === true;
          input.dataset.botSetting = key;
          input.dataset.botIndex = String(i);
          const textNode = document.createElement("span");
          textNode.textContent = text;
          item.append(input, textNode);
          options.append(item);
        }
        row.append(options);
      }
      list.append(row);
    }
  }

  function rules() {
    return Object.fromEntries(Object.entries(ruleIds).map(([key, id]) => [key, $(id).checked]));
  }

  function setRules(value) {
    for (const [key, id] of Object.entries(ruleIds)) $(id).checked = value[key];
    renderRules();
  }

  function renderRules() {
    $("board-rules-fields").disabled = !isBoard();
    $("card-rules-note").hidden = isBoard();
    $("rule-summoned").disabled = !isBoard() || !$("rule-move-suspect").checked;
    const value = rules();
    $("rule-preset").value = Object.values(value).every(Boolean) ? "standard"
      : !value.move_suspect && !value.move_weapon && !value.summoned_suggestion && value.secret_passages
        ? "no-relocation" : "custom";
  }

  function payload() {
    if (!validBasics()) throw new Error("Correct the game settings before continuing.");
    const count = Number($("players").value);
    const value = {
      mode: $("mode").value, game_type: isBoard() ? "board" : "card_only",
      notebook_mode: $("mode").value === "spectate" ? "automatic" : $("notebook-mode").value,
      players: count, seat: Number($("seat").value), seed: Number($("seed").value),
      bots: copy(bots.slice(0, count)), progress: $("progress").value,
      max_steps: Number($("max-steps").value), debug: $("debug").checked,
    };
    if (isBoard()) {
      value.seat_suspects = characters.slice(0, count);
      value.board_rules = rules();
    }
    return value;
  }

  function renderReview() {
    const data = payload();
    const review = $("setup-review");
    review.replaceChildren();
    const add = (title, text) => {
      const paragraph = document.createElement("p");
      const bold = document.createElement("strong");
      bold.textContent = `${title}: `;
      paragraph.append(bold, document.createTextNode(text));
      review.append(paragraph);
    };
    add("Game", `${data.game_type === "board" ? "Board" : "Cards only"} · ${data.mode} · ${data.players} players`);
    add("Notebook", data.notebook_mode === "manual" ? "Manual" : "Automatic");
    add("Seed", String(data.seed));
    for (let i = 0; i < data.players; i++) {
      const human = data.mode === "play" && i === data.seat;
      const character = data.seat_suspects ? ` · ${cardName(data.seat_suspects[i])}` : "";
      const bot = human ? "You" : `Bot: ${typeof data.bots[i] === "string" ? data.bots[i] : "custom"} (${score(data.bots[i])}/100)`;
      add(`Player ${i + 1}`, `${bot}${character}${data.seat_suspects && data.seat_suspects[i] === 0 ? " · starts" : ""}`);
    }
    if (data.board_rules) {
      const changed = Object.entries(data.board_rules).filter(([, value]) => !value)
        .map(([key]) => key.replaceAll("_", " "));
      add("Rules", changed.length ? `House rules: disabled ${changed.join(", ")}` : "Standard");
    }
    add("Progression", `${data.progress} · action limit ${data.max_steps}`);
    if (data.debug) add("Warning", "Omniscient debug reveals hidden information.");
  }

  function showStep(next, focus = true) {
    step = next;
    for (const section of document.querySelectorAll(".setup-step")) {
      section.hidden = Number(section.dataset.step) !== step;
    }
    for (const button of document.querySelectorAll("[data-setup-step]")) {
      if (Number(button.dataset.setupStep) === step) button.setAttribute("aria-current", "step");
      else button.removeAttribute("aria-current");
    }
    $("setup-back").hidden = step === 0;
    $("setup-next").hidden = step === 4;
    $("setup-next").textContent = `Next: ${["Seats", "Bots", "Rules", "Review"][step] || "Review"}`;
    $("setup-start").hidden = step !== 4;
    if (step === 4) renderReview();
    if (focus) document.querySelector(`.setup-step[data-step="${step}"] h3`).focus();
  }

  function loadSetup(data, useSeed) {
    validateProfile(data, useSeed);
    document.querySelector(`input[name="game-type"][value="${data.game_type}"]`).checked = true;
    $("mode").value = data.mode;
    $("notebook-mode").value = data.notebook_mode === undefined ? "manual" : data.notebook_mode;
    $("players").value = String(data.players);
    $("progress").value = data.progress;
    $("max-steps").value = String(data.max_steps);
    $("debug").checked = data.debug;
    characters = data.seat_suspects ? [...data.seat_suspects] : [0, 1, 2, 3, 4, 5];
    bots = copy(data.bots);
    if (data.board_rules) setRules(data.board_rules);
    updateMode(false);
    updateGameType();
    syncSeats();
    $("seat").value = String(data.seat);
    syncSeats();
    if (useSeed) $("seed").value = String(data.seed);
    else rollSeed();
    showStep(0, false);
  }

  function validateProfile(data, withSeed = false) {
    if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("Invalid setup profile.");
    const allowed = ["mode", "game_type", "notebook_mode", "players", "seat", "bots", "seat_suspects",
      "board_rules", "progress", "max_steps", "debug", ...(withSeed ? ["seed"] : [])];
    if (Object.keys(data).some((key) => !allowed.includes(key))
      || !["play", "spectate"].includes(data.mode)
      || !["board", "card_only"].includes(data.game_type)
      || (data.notebook_mode !== undefined && !["manual", "automatic"].includes(data.notebook_mode))
      || !Number.isInteger(data.players) || data.players < 2
      || (data.game_type === "board" && (data.players < 3 || data.players > 6))
      || !Number.isInteger(data.seat) || data.seat < 0 || data.seat >= data.players
      || !Array.isArray(data.bots) || data.bots.length !== data.players
      || !["auto", "step"].includes(data.progress)
      || !Number.isSafeInteger(data.max_steps) || data.max_steps < 0
      || typeof data.debug !== "boolean"
      || (withSeed && (!Number.isInteger(data.seed) || data.seed < 0 || data.seed > 4294967295))) {
      throw new Error("Invalid setup profile.");
    }
    for (const bot of data.bots) {
      if (typeof bot === "string") {
        if (!Object.hasOwn(presets, bot)) throw new Error("Unknown bot preset in setup profile.");
      } else if (!bot || typeof bot !== "object" || Array.isArray(bot)
        || Object.keys(bot).some((key) => !Object.hasOwn(strategyLabels, key) || typeof bot[key] !== "boolean")) {
        throw new Error("Invalid bot strategy in setup profile.");
      }
    }
    if (data.game_type === "board") {
      if (!Array.isArray(data.seat_suspects) || data.seat_suspects.length !== data.players
        || new Set(data.seat_suspects).size !== data.players || !data.seat_suspects.includes(0)
        || data.seat_suspects.some((id) => !Number.isInteger(id) || id < 0 || id > 5)
        || !data.board_rules || Object.keys(data.board_rules).length !== Object.keys(ruleIds).length
        || Object.keys(data.board_rules).some((key) => !Object.hasOwn(ruleIds, key) || typeof data.board_rules[key] !== "boolean")
        || (!data.board_rules.move_suspect && data.board_rules.summoned_suggestion)) {
        throw new Error("Invalid board settings in setup profile.");
      }
    } else if (data.seat_suspects !== undefined || data.board_rules !== undefined) {
      throw new Error("Card-only profiles cannot contain board settings.");
    }
  }

  function renderProfiles() {
    const select = $("profile-select");
    const selected = select.value;
    select.replaceChildren(option("", "Choose a profile"));
    for (const name of Object.keys(profiles).sort()) select.append(option(name, name));
    select.value = Object.hasOwn(profiles, selected) ? selected : "";
  }

  async function loadProfiles() {
    let data;
    if (window.clueOptions.desktop) {
      data = (await requestJson("/api/desktop/profiles")).profiles;
    } else {
      const text = localStorage.getItem(storageKey);
      if (text === null) data = {};
      else {
        const saved = JSON.parse(text);
        if (!saved || saved.version !== 1 || !saved.profiles || typeof saved.profiles !== "object"
          || Array.isArray(saved.profiles)) throw new Error("Invalid saved setup profiles.");
        data = saved.profiles;
      }
    }
    for (const profile of Object.values(data)) validateProfile(profile);
    if (Object.keys(data).length > 100 || Object.keys(data).some((name) => !name.trim() || name.length > 80)) {
      throw new Error("Invalid saved profile names or too many profiles.");
    }
    profiles = Object.assign(Object.create(null), data);
    profilesReady = true;
    renderProfiles();
  }

  async function persistProfiles(next) {
    if (window.clueOptions.desktop) {
      await requestJson("/api/desktop/profiles", { method: "PUT", body: { profiles: next } });
    } else {
      localStorage.setItem(storageKey, JSON.stringify({ version: 1, profiles: next }));
    }
    profiles = next;
    renderProfiles();
  }

  function beginFresh() {
    try {
      rollSeed();
      showStep(0, false);
      $("replay-setup").disabled = lastSetup === null;
    } catch (error) { showError(error.message); }
  }

  function rememberStarted(data) {
    lastSetup = copy(data);
    $("replay-setup").disabled = false;
  }

  for (const name of Object.keys(presets)) {
    $("all-bots").append(option(name, name[0].toUpperCase() + name.slice(1)));
  }
  $("all-bots").value = "random";
  $("roll-seed").addEventListener("click", () => {
    try { rollSeed(); showError(""); } catch (error) { showError(error.message); }
  });
  $("copy-seed").addEventListener("click", async () => {
    if (!window.confirm("The seed can reveal the deal and solution. Copy it anyway?")) return;
    try {
      await navigator.clipboard.writeText($("seed").value);
      $("profile-status").textContent = "Seed copied.";
    } catch (error) { showError(`Could not copy the seed: ${error.message}`); }
  });
  $("replay-setup").addEventListener("click", () => {
    if (lastSetup) {
      try { loadSetup(lastSetup, true); } catch (error) { showError(error.message); }
    }
  });
  $("setup-back").addEventListener("click", () => showStep(step - 1));
  $("setup-next").addEventListener("click", () => {
    if (validBasics()) { showError(""); syncSeats(); showStep(step + 1); }
  });
  for (const button of document.querySelectorAll("[data-setup-step]")) {
    button.addEventListener("click", () => {
      if (validBasics()) { showError(""); syncSeats(); showStep(Number(button.dataset.setupStep)); }
    });
  }
  for (const element of [$("players"), $("mode"), $("seat"), ...document.querySelectorAll('input[name="game-type"]')]) {
    element.addEventListener("change", syncSeats);
  }
  $("seat-list").addEventListener("change", (event) => {
    if (event.target.dataset.characterSeat !== undefined) {
      selectCharacter(Number(event.target.dataset.characterSeat), Number(event.target.value));
    }
  });
  $("seat-list").addEventListener("focusin", (event) => {
    if (event.target.dataset.characterSeat !== undefined) {
      highlightedSeat = Number(event.target.dataset.characterSeat);
      renderPreview();
    }
  });
  $("apply-bots").addEventListener("click", () => {
    const human = $("mode").value === "play" ? Number($("seat").value) : -1;
    const count = Number($("players").value);
    if (bots.slice(0, count).some((bot, i) => i !== human && typeof bot !== "string")
      && !window.confirm("Replace custom settings for all bots?")) return;
    for (let i = 0; i < count; i++) if (i !== human) bots[i] = $("all-bots").value;
    renderBots();
  });
  $("bot-list").addEventListener("change", (event) => {
    const target = event.target;
    if (target.dataset.botSeat !== undefined) {
      const i = Number(target.dataset.botSeat);
      bots[i] = target.value === "custom" ? strategy(bots[i]) : target.value;
      renderBots();
      document.querySelector(`[data-bot-seat="${i}"]`).focus();
    } else if (target.dataset.botSetting) {
      const i = Number(target.dataset.botIndex);
      bots[i][target.dataset.botSetting] = target.checked;
      document.querySelector(`[data-bot-score="${i}"]`).textContent =
        `Toolkit: ${score(bots[i])}/100`;
    } else if (target.dataset.copySeat !== undefined && target.value !== "") {
      const i = Number(target.dataset.copySeat);
      if (typeof bots[i] !== "string" && !window.confirm("Replace this bot's custom settings?")) {
        target.value = "";
        return;
      }
      bots[i] = copy(bots[Number(target.value)]);
      renderBots();
      document.querySelector(`[data-copy-seat="${i}"]`).focus();
    }
  });
  $("rule-preset").addEventListener("change", () => {
    if ($("rule-preset").value === "standard") setRules({
      move_suspect: true, move_weapon: true, summoned_suggestion: true, secret_passages: true,
    });
    if ($("rule-preset").value === "no-relocation") setRules({
      move_suspect: false, move_weapon: false, summoned_suggestion: false, secret_passages: true,
    });
  });
  $("reset-rules").addEventListener("click", () => setRules({
    move_suspect: true, move_weapon: true, summoned_suggestion: true, secret_passages: true,
  }));
  for (const id of Object.values(ruleIds)) {
    $(id).addEventListener("change", () => {
      if (!$("rule-move-suspect").checked) $("rule-summoned").checked = false;
      renderRules();
    });
  }
  $("profile-save").addEventListener("click", async () => {
    try {
      if (!profilesReady) throw new Error("Setup profiles were not loaded; reload before saving.");
      const name = $("profile-name").value.trim();
      if (!name || name.length > 80) throw new Error("Enter a profile name of up to 80 characters.");
      if (Object.hasOwn(profiles, name) && !window.confirm(`Replace profile "${name}"?`)) return;
      if (!Object.hasOwn(profiles, name) && Object.keys(profiles).length >= 100) {
        throw new Error("A maximum of 100 profiles can be saved.");
      }
      const data = payload();
      delete data.seed;
      validateProfile(data);
      const next = Object.assign(Object.create(null), profiles, { [name]: data });
      await persistProfiles(next);
      $("profile-select").value = name;
      $("profile-status").textContent = `Saved "${name}" without a seed.`;
      showError("");
    } catch (error) { showError(error.message); }
  });
  $("profile-load").addEventListener("click", () => {
    try {
      if (!profilesReady) throw new Error("Setup profiles were not loaded; reload before using them.");
      const name = $("profile-select").value;
      if (!Object.hasOwn(profiles, name)) throw new Error("Choose a saved profile.");
      loadSetup(profiles[name], false);
      $("profile-status").textContent = `Loaded "${name}" with a new seed.`;
      showError("");
    } catch (error) { showError(error.message); }
  });
  $("profile-rename").addEventListener("click", async () => {
    try {
      if (!profilesReady) throw new Error("Setup profiles were not loaded; reload before renaming.");
      const oldName = $("profile-select").value;
      const name = $("profile-name").value.trim();
      if (!Object.hasOwn(profiles, oldName)) throw new Error("Choose a saved profile to rename.");
      if (!name || name.length > 80) throw new Error("Enter a new profile name of up to 80 characters.");
      if (name === oldName) throw new Error("Enter a different profile name.");
      if (Object.hasOwn(profiles, name) && !window.confirm(`Replace profile "${name}"?`)) return;
      const next = Object.assign(Object.create(null), profiles);
      next[name] = next[oldName];
      delete next[oldName];
      await persistProfiles(next);
      $("profile-select").value = name;
      $("profile-status").textContent = `Renamed "${oldName}" to "${name}".`;
      showError("");
    } catch (error) { showError(error.message); }
  });
  $("profile-delete").addEventListener("click", async () => {
    try {
      if (!profilesReady) throw new Error("Setup profiles were not loaded; reload before deleting.");
      const name = $("profile-select").value;
      if (!Object.hasOwn(profiles, name)) throw new Error("Choose a saved profile.");
      if (!window.confirm(`Delete profile "${name}"?`)) return;
      const next = Object.assign(Object.create(null), profiles);
      delete next[name];
      await persistProfiles(next);
      $("profile-status").textContent = `Deleted "${name}".`;
      showError("");
    } catch (error) { showError(error.message); }
  });
  requestJson("/api/setup").then((data) => { metadata = data; renderPreview(); })
    .catch((error) => showError(`Could not load board setup: ${error.message}`));
  loadProfiles().catch((error) => showError(`Could not load setup profiles: ${error.message}`));
  syncSeats();
  beginFresh();
  return { payload, beginFresh, rememberStarted };
})();
