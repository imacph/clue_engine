"use strict";

window.setupWizard = (() => {
  const strategyLabels = {
    candidate_suggestions: "Favor possible solution cards",
    probe_suggestions: "Probe unknown cards using known controls",
    rank_suggestions: "Rank suggestions using deduction and responders",
    repeat_reveals: "Repeat cards already shown to the same player",
    candidate_rooms: "Favor possible solution rooms (board only)",
    prefer_suggest: "Favor suggesting when possible (cards only)",
    deal_analysis: "Analyze possible deals for deeper deductions",
    risk_accusation: "Allow calculated accusations at 75% (may eliminate the bot)",
  };
  const presets = {
    random: {},
    deductive: { candidate_suggestions: true, candidate_rooms: true, prefer_suggest: true },
    probing: {
      candidate_suggestions: true, probe_suggestions: true, repeat_reveals: true,
      candidate_rooms: true, prefer_suggest: true,
    },
    strategic: {
      candidate_suggestions: true, rank_suggestions: true,
      repeat_reveals: true, candidate_rooms: true, prefer_suggest: true,
      deal_analysis: true,
    },
    learned: {},
    analytical: {
      candidate_suggestions: true, rank_suggestions: true,
      repeat_reveals: true, candidate_rooms: true, prefer_suggest: true,
      deal_analysis: true, risk_accusation: true,
    },
  };
  const legacyPresetNames = ["random", "deductive", "probing", "strategic", "analytical"];
  const presetDescriptions = {
    random: "Random decisions; shared deduction and movement.",
    deductive: "Favors possible solution cards and useful rooms.",
    probing: "Adds controlled probes and repeats previously shown cards.",
    strategic: "Ranks suggestions and analyzes possible deals when practical; never guesses.",
    analytical: "Adds deeper deal counting and opponent modeling; risks accusations at 50% estimated confidence.",
  };
  const learnedProfiles = {
    hard: {
      label: "Hard",
      description: "Deterministic choices with aggressive, threat-aware accusations.",
      room_temperature: 0, suggestion_temperature: 0, accusation_temperature: 0,
      accusation_threshold: 0.275, threat_sensitivity: 0.9,
    },
    focused: {
      label: "Focused",
      description: "Nearly deterministic play with confident, threat-aware accusations.",
      room_temperature: 0.05, suggestion_temperature: 0.05, accusation_temperature: 0.05,
      accusation_threshold: 0.35, threat_sensitivity: 0.7,
    },
    steady: {
      label: "Steady",
      description: "A measured mix of decisive play and cautious accusations.",
      room_temperature: 0.1, suggestion_temperature: 0.1, accusation_temperature: 0.1,
      accusation_threshold: 0.45, threat_sensitivity: 0.5,
    },
    cautious: {
      label: "Cautious",
      description: "More varied choices and a higher bar for making an accusation.",
      room_temperature: 0.2, suggestion_temperature: 0.2, accusation_temperature: 0.2,
      accusation_threshold: 0.6, threat_sensitivity: 0.35,
    },
    gentle: {
      label: "Gentle",
      description: "The most exploratory profile, with conservative accusations.",
      room_temperature: 0.3, suggestion_temperature: 0.3, accusation_temperature: 0.3,
      accusation_threshold: 0.75, threat_sensitivity: 0.2,
    },
  };
  const learnedDefaults = {
    type: "learned", room_temperature: 0, suggestion_temperature: 0,
    accusation_temperature: 0, accusation_threshold: 0.275, opponent_model: true,
    threat_sensitivity: 0.9,
  };
  const learnedControls = {
    room_temperature: ["Room exploration", 5, 0.05],
    suggestion_temperature: ["Suggestion exploration", 5, 0.05],
    accusation_temperature: ["Accusation exploration", 5, 0.05],
    accusation_threshold: ["Accusation confidence threshold (higher is safer)", 1, 0.05],
    threat_sensitivity: ["Risk sensitivity to opponent threats", 1, 0.05],
  };
  function isLearned(value) {
    return value === "learned" || (value && typeof value === "object" && value.type === "learned");
  }
  function learnedSettings(value) {
    return {
      ...learnedDefaults, ...(value && typeof value === "object" ? value : {}), opponent_model: true,
    };
  }
  function learnedProfile(name) {
    return {
      type: "learned", opponent_model: true,
      ...Object.fromEntries(Object.keys(learnedControls).map((key) => [key, learnedProfiles[name][key]])),
    };
  }
  function learnedProfileName(value) {
    if (!isLearned(value)) return null;
    const settings = learnedSettings(value);
    return Object.keys(learnedProfiles).find((name) =>
      Object.keys(learnedControls).every((key) => settings[key] === learnedProfiles[name][key])
    ) || null;
  }
  function defaultLearnedProfile(index) {
    const names = Object.keys(learnedProfiles);
    return learnedProfile(names[Math.min(index, names.length - 1)]);
  }
  function isLegacyBot(value) {
    return !isLearned(value);
  }
  function botChoice(value) {
    if (isLearned(value)) return learnedProfileName(value) || "learned-custom";
    return typeof value === "string" ? value : "custom";
  }
  function botChoiceLabel(name) {
    if (learnedProfiles[name]) return learnedProfiles[name].label;
    if (name === "learned-custom") return "Custom learned";
    if (name === "custom") return "Custom";
    return name[0].toUpperCase() + name.slice(1);
  }
  function botFromChoice(name, current) {
    if (learnedProfiles[name]) return learnedProfile(name);
    if (name === "learned-custom") return isLearned(current) ? learnedSettings(current) : learnedProfile("steady");
    if (name === "custom") return strategy(current);
    return name;
  }
  const weights = {
    candidate_suggestions: 20, probe_suggestions: 15, rank_suggestions: 15,
    repeat_reveals: 15, candidate_rooms: 15, prefer_suggest: 10, deal_analysis: 15,
  };
  const ruleIds = {
    move_suspect: "rule-move-suspect", move_weapon: "rule-move-weapon",
    summoned_suggestion: "rule-summoned", secret_passages: "rule-passages",
    early_end: "rule-early-end", revisit_hallways: "rule-revisit",
    optional_suggestion: "rule-optional-suggestion", accuse_in_room: "rule-accuse-room",
    stay_to_suggest: "rule-stay-suggest", randomize_rooms: "rule-randomize-rooms",
    procedural_map: "rule-procedural-map",
    randomize_doors: "rule-randomize-doors", randomize_passages: "rule-randomize-passages",
  };
  const gameRuleIds = {
    reverse_refutation: "rule-reverse-refutation", public_refutations: "rule-public-refutations",
    all_refute: "rule-all-refute", face_up_card: "rule-face-up",
  };
  const standardRules = {
    move_suspect: true, move_weapon: true, summoned_suggestion: true, secret_passages: true,
    early_end: true, revisit_hallways: false, optional_suggestion: false, accuse_in_room: false,
    stay_to_suggest: false, randomize_rooms: false, procedural_map: false, randomize_doors: false,
    randomize_passages: false, passage_count: 2,
  };
  const storageKey = "clue-engine-setup-profiles";
  const quickplayProfile = "__clue_engine_quickplay__";
  const missingBoardSetup = "Board starting positions are unavailable. Reload the page and try again.";
  let step = 0;
  let characters = [0, 1, 2, 3, 4, 5];
  let bots = [];
  let metadata = null;
  let highlightedSeat = 0;
  let lastSetup = null;
  let batchMode = false;
  let shuffleBotProfileCount = 0;
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
    const required = ["players", "seed", "max-steps"];
    if (batchMode) required.push("batch-games");
    for (const id of required) {
      if (!$(id).validity.valid || $(id).value === "") {
        showStep(0, false);
        const details = $(id).closest("details");
        if (details) details.open = true;
        $(id).reportValidity();
        return false;
      }
    }
    if (isBoard() && !metadata) {
      showError(missingBoardSetup);
      return false;
    }
    if (!isBoard() && !$("enable-legacy-bots").checked) {
      showError("Enable legacy bots to play a card-only game.");
      return false;
    }
    if (!isBoard() && bots.some(
      (bot, i) => ($("mode").value !== "play" || i !== Number($("seat").value)) && isLearned(bot),
    )) {
      showError("Choose a legacy bot for each bot seat in a card-only game.");
      return false;
    }
    return true;
  }

  function syncSeats() {
    const count = Number($("players").value);
    if (!Number.isInteger(count) || count < 2 || (isBoard() && count > 6)) return;
    if (isBoard() && !$("enable-legacy-bots").checked) {
      bots = bots.map((bot, i) => isLegacyBot(bot) ? defaultLearnedProfile(i) : bot);
    }
    renderShuffleBotCount();
    while (bots.length < count) bots.push(
      isBoard() && !$("enable-legacy-bots").checked ? defaultLearnedProfile(bots.length) : "random",
    );
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
      label.textContent = `Player ${i + 1}${i === human
        ? ($("shuffle-seat").checked ? " (configured as you)" : " (you)") : " (bot)"}`;
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
    const list = $("bot-list");
    const expanded = new Set(
      [...list.querySelectorAll("details[open]")].map((item) => item.dataset.botDetails),
    );
    const legacyEnabled = $("enable-legacy-bots").checked;
    const learnedUnavailable = !isBoard();
    const blocked = learnedUnavailable && !legacyEnabled;
    const sharedBots = $("all-bots");
    const sharedChoices = blocked ? [] : learnedUnavailable
      ? [...legacyPresetNames] : [
        ...Object.keys(learnedProfiles), ...(legacyEnabled ? legacyPresetNames : []),
      ];
    const sharedValue = sharedBots.value;
    sharedBots.replaceChildren(...sharedChoices.map((name) => option(name, botChoiceLabel(name))));
    sharedBots.value = sharedChoices.includes(sharedValue) ? sharedValue : sharedChoices[0] || "";
    sharedBots.disabled = blocked;
    $("apply-bots").disabled = blocked;
    const human = $("mode").value === "play" ? Number($("seat").value) : null;
    const profileCount = batchMode && $("shuffle-bots").checked
      ? shuffleBotProfileCount : count;
    const message = $("bot-setup-message");
    const needsLegacyBots = learnedUnavailable && bots.some(
      (bot, i) => (human === null || i !== human) && isLearned(bot),
    );
    message.hidden = !blocked && !needsLegacyBots;
    message.textContent = blocked
      ? "Learned profiles require a board game. Enable legacy bots to configure bots for a card-only game."
      : needsLegacyBots ? "Choose a legacy bot for each seat to use this card-only game." : "";
    list.replaceChildren();
    if (blocked) return;
    list.dataset.botCount = String(profileCount - (human === null ? 0 : 1));
    for (let i = 0; i < profileCount; i++) {
      if (i === human) continue;
      const value = bots[i];
      const choices = learnedUnavailable ? [...legacyPresetNames, "custom"] : [
        ...Object.keys(learnedProfiles),
        ...(legacyEnabled ? [...legacyPresetNames, "custom"] : []),
        "learned-custom",
      ];
      const row = document.createElement("div");
      row.className = "setup-seat bot-seat-card";
      const label = document.createElement("label");
      label.className = "bot-choice-label";
      label.textContent = `Player ${i + 1} bot`;
      const select = document.createElement("select");
      select.className = "bot-profile-select";
      select.dataset.botSeat = String(i);
      select.append(option("", "Choose a bot profile"));
      for (const name of choices) select.append(option(name, botChoiceLabel(name)));
      const selectedChoice = botChoice(value);
      select.value = choices.includes(selectedChoice) ? selectedChoice : "";
      label.append(select);
      const summary = document.createElement("p");
      summary.className = "hint bot-score";
      summary.dataset.botScore = String(i);
      const profileName = learnedProfileName(value);
      summary.textContent = isLearned(value) ? `Learned · ${profileName ? learnedProfiles[profileName].label : "custom"} · opponent model on`
        : learnedUnavailable ? "Legacy bot · card-only compatible"
        : `Toolkit: ${score(value)}/100${value === "analytical" ? " · may accuse at 50%" : ""}`;
      const description = document.createElement("p");
      description.className = "hint";
      description.textContent = isLearned(value)
        ? profileName ? learnedProfiles[profileName].description
          : "Custom learned settings use the experimental opponent model."
        : typeof value === "string" ? presetDescriptions[value]
        : "Custom choices use probes first, then candidate filtering, followed by optional ranking; they do not include analytical opponent modeling.";
      const details = document.createElement("details");
      details.dataset.botDetails = String(i);
      details.open = expanded.has(String(i));
      const detailsTitle = document.createElement("summary");
      detailsTitle.textContent = isLearned(value) ? "Profile settings"
        : typeof value === "string" ? "Legacy bot details" : "Edit custom strategy";
      details.append(detailsTitle, description);
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
      row.append(label, summary, copyLabel, details);
      if (isLearned(value)) {
        const settings = learnedSettings(value);
        const hint = document.createElement("p");
        hint.className = "hint bot-settings-hint";
        hint.textContent = "Temperature 0 is deterministic; higher values add randomness. The experimental opponent model is always on for learned setup bots. Confidence is estimated from bounded deal counts, not guaranteed.";
        details.append(hint);
        for (const [key, [text, max, increment]] of Object.entries(learnedControls)) {
          const item = document.createElement("label");
          item.className = "bot-range-control";
          const output = document.createElement("span");
          output.textContent = `${text}: ${settings[key]}`;
          const input = document.createElement("input");
          input.type = "range";
          input.min = "0";
          input.max = String(max);
          input.step = String(increment);
          input.value = String(settings[key]);
          input.dataset.learnedSetting = key;
          input.dataset.botIndex = String(i);
          input.addEventListener("input", () => { output.textContent = `${text}: ${input.value}`; });
          item.append(output, input);
          details.append(item);
        }
      } else if (typeof value !== "string") {
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
        details.append(options);
      }
      list.append(row);
    }
  }

  function rules() {
    return {
      ...Object.fromEntries(Object.entries(ruleIds).map(([key, id]) => [key, $(id).checked])),
      passage_count: Number($("rule-passage-count").value),
    };
  }

  function setRules(value) {
    for (const [key, id] of Object.entries(ruleIds)) $(id).checked = value[key] ?? standardRules[key];
    $("rule-passage-count").value = String(value.passage_count ?? standardRules.passage_count);
    renderRules();
  }

  function renderRules() {
    $("board-rules-fields").disabled = !isBoard();
    $("card-rules-note").hidden = isBoard();
    $("rule-summoned").disabled = !isBoard() || !$("rule-move-suspect").checked;
    $("rule-procedural-map").disabled = !isBoard() || !$("rule-randomize-rooms").checked;
    $("rule-passage-count").disabled = !isBoard() || !$("rule-randomize-passages").checked;
    const value = rules();
    const matches = (preset) => Object.keys(standardRules).every((key) => value[key] === preset[key]);
    $("rule-preset").value = matches(standardRules) ? "standard"
      : matches({ ...standardRules, move_suspect: false, move_weapon: false, summoned_suggestion: false })
        ? "no-relocation" : "custom";
  }

  function payload() {
    if (!validBasics()) {
      throw new Error(lastError === missingBoardSetup ? missingBoardSetup : "Correct the game settings before continuing.");
    }
    syncSeats();
    const count = Number($("players").value);
    const value = {
      mode: batchMode ? "spectate" : $("mode").value,
      game_type: isBoard() ? "board" : "card_only",
      notebook_mode: batchMode || $("mode").value === "spectate" ? "automatic" : $("notebook-mode").value,
      players: count, seat: batchMode ? 0 : Number($("seat").value), seed: Number($("seed").value),
      bots: copy(bots.slice(0, batchMode && $("shuffle-bots").checked
        ? shuffleBotProfileCount : count)).map((bot, i) => {
        if (!isBoard() && $("mode").value === "play" && i === Number($("seat").value) && isLearned(bot)) {
          return "deductive";
        }
        return isLearned(bot) ? learnedSettings(bot) : bot;
      }),
      progress: $("progress").value,
      shuffle_bots: $("shuffle-bots").checked,
      shuffle_seat: !batchMode && $("mode").value === "play" && $("shuffle-seat").checked,
      max_steps: Number($("max-steps").value), debug: !batchMode && $("debug").checked,
      game_rules: Object.fromEntries(
        Object.entries(gameRuleIds).map(([key, id]) => [key, $(id).checked])
      ),
    };
    if (batchMode) value.progress = "auto";
    if (isBoard()) {
      value.seat_suspects = characters.slice(0, count);
      value.board_rules = rules();
    }
    return value;
  }

  function resolveBotSeats(data) {
    const result = copy(data);
    if (result.shuffle_seat && result.mode === "play") {
      const previous = result.seat;
      let mixed = (result.seed ^ 0x85ebca6b) >>> 0;
      mixed = Math.imul(mixed ^ (mixed >>> 16), 0x7feb352d);
      mixed = Math.imul(mixed ^ (mixed >>> 15), 0x846ca68b);
      mixed = (mixed ^ (mixed >>> 16)) >>> 0;
      result.seat = Math.floor(mixed / 4294967296 * result.players);
      [result.bots[previous], result.bots[result.seat]] = [result.bots[result.seat], result.bots[previous]];
    }
    if (result.shuffle_bots) {
      const seats = Array.from({ length: result.players }, (_, i) => i)
        .filter((i) => result.mode !== "play" || i !== result.seat);
      let state = (result.seed ^ 0x9e3779b9) >>> 0;
      for (let i = seats.length - 1; i > 0; i--) {
        state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
        const j = Math.floor(state / 4294967296 * (i + 1));
        [result.bots[seats[i]], result.bots[seats[j]]] = [result.bots[seats[j]], result.bots[seats[i]]];
      }
    }
    delete result.shuffle_bots;
    delete result.shuffle_seat;
    return result;
  }

  function renderReview(review = $("setup-review"), includeSeed = true) {
    const data = payload();
    review.replaceChildren();
    const add = (title, text) => {
      const paragraph = document.createElement("p");
      const bold = document.createElement("strong");
      bold.textContent = `${title}: `;
      paragraph.append(bold, document.createTextNode(text));
      review.append(paragraph);
    };
    add("Game", `${data.game_type === "board" ? "Board" : "Cards only"} · ${data.mode} · ${data.players} players`);
    if (batchMode) add("Games", String(Number($("batch-games").value)));
    else add("Notebook", data.notebook_mode === "manual" ? "Manual" : "Automatic");
    if (includeSeed) add("Seed", String(data.seed));
    if (data.shuffle_seat && data.mode === "play") add("Your seat", "Randomly assigned at startup");
    if (data.shuffle_bots || (data.shuffle_seat && data.mode === "play")) {
      const styles = data.bots.filter((_, i) => data.mode !== "play" || i !== data.seat)
        .map((bot) => isLearned(bot)
          ? learnedProfiles[learnedProfileName(bot)]?.label || "Custom learned"
          : typeof bot === "string" ? bot : "Custom");
      const assignment = batchMode
        ? " · balanced across full profile rotations; a partial final rotation can vary"
        : " · randomly assigned to bot seats";
      add("Bot styles", `${styles.join(", ")}${data.shuffle_bots ? assignment : ""}`);
    }
    if (data.bots.some((bot, i) => bot === "analytical" && (data.mode !== "play" || i !== data.seat))) {
      add("Analytical risk", "May accuse at 50% estimated confidence; a wrong accusation eliminates the bot");
    }
    for (let i = 0; i < data.players; i++) {
      const randomHuman = data.mode === "play" && data.shuffle_seat;
      const human = data.mode === "play" && i === data.seat && !randomHuman;
      const character = data.seat_suspects ? ` · ${cardName(data.seat_suspects[i])}` : "";
      const bot = randomHuman ? "You or bot" : human ? "You" : data.shuffle_bots ? "Bot (random style)"
        : isLearned(data.bots[i]) ? `Bot: ${learnedProfiles[learnedProfileName(data.bots[i])]?.label || "Custom learned"} · experimental opponent model on`
          : `Bot: ${typeof data.bots[i] === "string" ? data.bots[i] : "custom"} (${score(data.bots[i])}/100)`;
      add(`Player ${i + 1}`, `${bot}${character}${data.seat_suspects && data.seat_suspects[i] === 0 ? " · starts" : ""}`);
    }
    if (data.board_rules) {
      const changed = Object.entries(data.board_rules)
        .filter(([key, value]) => key === "passage_count"
          ? data.board_rules.randomize_passages : value !== standardRules[key])
        .map(([key, value]) => key === "passage_count" ? `passages ${value}`
          : `${key.replaceAll("_", " ")} ${value ? "on" : "off"}`);
      add("Board rules", changed.length ? changed.join(", ") : "Standard");
    }
    const gameChanges = Object.entries(data.game_rules).filter(([, value]) => value)
      .map(([key]) => key.replaceAll("_", " "));
    if (gameChanges.length) add("Game rules", gameChanges.join(", "));
    if (!batchMode) {
      const progression = { auto: "Automatic", turn: "Turn-by-turn", step: "Step-by-step" };
      add("Progression", `${progression[data.progress]} · action limit ${data.max_steps}`);
    } else {
      add("Action limit", String(data.max_steps));
    }
    if (data.debug) add("Warning", "Omniscient debug reveals hidden information.");
  }

  function renderShuffleBotCount() {
    const players = Number($("players").value);
    const countField = $("shuffle-bot-count-field");
    const select = $("shuffle-bot-count");
    countField.hidden = !batchMode || !$("shuffle-bots").checked;
    if (!Number.isInteger(players) || players < 2) return;
    const selected = shuffleBotProfileCount || players;
    shuffleBotProfileCount = Math.max(2, Math.min(players, selected));
    select.replaceChildren(...Array.from({ length: players - 1 }, (_, index) => {
      const count = index + 2;
      return option(count, `${count} profiles`);
    }));
    select.value = String(shuffleBotProfileCount);
  }

  function renderBatchMode() {
    const spectating = $("mode").value === "spectate";
    if (!spectating) {
      batchMode = false;
      $("batch-enabled").checked = false;
    }
    $("batch-option-field").hidden = !spectating;
    $("setup-heading").textContent = batchMode ? "Batch simulation setup" : "New game";
    $("setup-review-title").textContent = batchMode ? "Review batch setup" : "Review your game";
    $("batch-games-field").hidden = !batchMode;
    $("setup-quick-play").hidden = batchMode;
    $("save-quickplay-default").hidden = batchMode;
    $("setup-start").textContent = batchMode ? "Run batch" : "Start game";
    $("notebook-mode-field").hidden = spectating;
    $("notebook-mode-hint").hidden = spectating;
    $("progress-field").hidden = batchMode;
    $("debug-field").hidden = batchMode;
    $("spectator-warning").hidden = batchMode || $("mode").value !== "spectate";
    $("shuffle-bots-label").textContent = batchMode
      ? "Balance randomized bot profiles across seats"
      : "Randomly assign bot styles to seats";
    $("shuffle-bots-hint").textContent = batchMode
      ? "Choose fewer profiles than players to distribute them as evenly as possible across seats in the batch."
      : "Shuffle the configured bots among bot seats when the game starts.";
    renderShuffleBotCount();
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
    $("setup-back").textContent = step === 0 ? "Main menu" : "Back";
    document.querySelector(".setup-navigation").classList.toggle("review-step", step === 4);
    $("setup-quick-play").classList.toggle("navigation-placeholder", step === 4);
    $("setup-next").hidden = step === 4;
    $("setup-next").textContent = `Next: ${["Seats", "Bots", "Rules", "Review"][step] || "Review"}`;
    $("setup-start").hidden = step !== 4;
    if (step === 4) renderReview();
    if (focus) document.querySelector(`.setup-step[data-step="${step}"] h3`).focus();
  }

  function loadSetup(data, useSeed) {
    validateProfile(data, useSeed);
    document.querySelector(`input[name="game-type"][value="${data.game_type}"]`).checked = true;
    $("mode").value = batchMode ? "spectate" : data.mode;
    $("notebook-mode").value = data.notebook_mode === undefined ? "manual" : data.notebook_mode;
    $("players").value = String(data.players);
    $("progress").value = data.progress;
    $("max-steps").value = String(data.max_steps);
    $("debug").checked = data.debug;
    $("shuffle-bots").checked = data.shuffle_bots === true;
    $("shuffle-seat").checked = data.shuffle_seat === true;
    characters = data.seat_suspects ? [...data.seat_suspects] : [0, 1, 2, 3, 4, 5];
    bots = copy(data.bots).map((bot) => isLearned(bot) ? learnedSettings(bot) : bot);
    $("enable-legacy-bots").checked = bots.some(isLegacyBot);
    shuffleBotProfileCount = bots.length;
    if (batchMode) {
      for (let i = 0; i < bots.length; i++) {
        if (bots[i] == null) bots[i] = $("all-bots").value || "random";
      }
    }
    for (const [key, id] of Object.entries(gameRuleIds)) {
      $(id).checked = data.game_rules?.[key] === true;
    }
    if (data.board_rules) setRules(data.board_rules);
    updateMode(false);
    renderBatchMode();
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
      "board_rules", "game_rules", "progress", "max_steps", "debug", "shuffle_bots", "shuffle_seat", ...(withSeed ? ["seed"] : [])];
    if (Object.keys(data).some((key) => !allowed.includes(key))
      || !["play", "spectate"].includes(data.mode)
      || !["board", "card_only"].includes(data.game_type)
      || (data.notebook_mode !== undefined && !["manual", "automatic"].includes(data.notebook_mode))
      || !Number.isInteger(data.players) || data.players < 2
      || (data.game_type === "board" && (data.players < 3 || data.players > 6))
      || !Number.isInteger(data.seat) || data.seat < 0 || data.seat >= data.players
      || !Array.isArray(data.bots)
      || (data.bots.length !== data.players
        && !(data.shuffle_bots === true && data.bots.length >= 2 && data.bots.length < data.players))
      || !["auto", "turn", "step"].includes(data.progress)
      || !Number.isSafeInteger(data.max_steps) || data.max_steps < 0
      || typeof data.debug !== "boolean"
      || (data.shuffle_bots !== undefined && typeof data.shuffle_bots !== "boolean")
      || (data.shuffle_seat !== undefined && typeof data.shuffle_seat !== "boolean")
      || (withSeed && (!Number.isInteger(data.seed) || data.seed < 0 || data.seed > 4294967295))) {
      throw new Error("Invalid setup profile.");
    }
    for (const bot of data.bots) {
      if (typeof bot === "string") {
        if (!Object.hasOwn(presets, bot)) throw new Error("Unknown bot preset in setup profile.");
        if (bot === "learned" && data.game_type !== "board") {
          throw new Error("The learned policy supports board games only.");
        }
      } else if (isLearned(bot)) {
        if (data.game_type !== "board" || Array.isArray(bot)
          || Object.keys(bot).some((key) => key !== "type" && key !== "opponent_model"
            && !Object.hasOwn(learnedControls, key))
          || (bot.opponent_model !== undefined && typeof bot.opponent_model !== "boolean")
          || Object.entries(bot).some(([key, value]) => key !== "type" && key !== "opponent_model"
            && (typeof value !== "number" || !Number.isFinite(value) || value < 0
              || value > learnedControls[key][1]))) {
          throw new Error("Invalid learned bot settings.");
        }
      } else if (!bot || typeof bot !== "object" || Array.isArray(bot)
        || Object.keys(bot).some((key) => !Object.hasOwn(strategyLabels, key) || typeof bot[key] !== "boolean")) {
        throw new Error("Invalid bot strategy in setup profile.");
      }
    }
    if (data.game_type === "board") {
      if (!Array.isArray(data.seat_suspects) || data.seat_suspects.length !== data.players
        || new Set(data.seat_suspects).size !== data.players || !data.seat_suspects.includes(0)
        || data.seat_suspects.some((id) => !Number.isInteger(id) || id < 0 || id > 5)
        || !data.board_rules || !["move_suspect", "move_weapon", "summoned_suggestion", "secret_passages"].every((key) => Object.hasOwn(data.board_rules, key))
        || Object.keys(data.board_rules).some((key) => key === "passage_count"
          ? !Number.isInteger(data.board_rules[key]) || data.board_rules[key] < 0 || data.board_rules[key] > 4
          : !Object.hasOwn(ruleIds, key) || typeof data.board_rules[key] !== "boolean")
        || (!data.board_rules.move_suspect && data.board_rules.summoned_suggestion)
        || (data.board_rules.procedural_map && !data.board_rules.randomize_rooms)) {
        throw new Error("Invalid board settings in setup profile.");
      }
    } else if (data.seat_suspects !== undefined || data.board_rules !== undefined) {
      throw new Error("Card-only profiles cannot contain board settings.");
    }
    if (data.game_rules !== undefined && (!data.game_rules || typeof data.game_rules !== "object"
      || Array.isArray(data.game_rules) || Object.keys(data.game_rules).some(
        (key) => !Object.hasOwn(gameRuleIds, key) || typeof data.game_rules[key] !== "boolean"
      ))) throw new Error("Invalid game rules in setup profile.");
  }

  function renderProfiles() {
    const select = $("profile-select");
    const selected = select.value;
    select.replaceChildren(option("", "Choose a profile"));
    for (const name of Object.keys(profiles).sort()) {
      if (name !== quickplayProfile) select.append(option(name, name));
    }
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

  function beginFresh(batch = false) {
    batchMode = batch;
    $("batch-enabled").checked = batch;
    if (batchMode) {
      $("mode").value = "spectate";
      $("notebook-mode").value = "automatic";
      $("progress").value = "auto";
      $("debug").checked = false;
      const count = Number($("players").value);
      while (bots.length < count) bots.push("random");
      for (let i = 0; i < count; i++) {
        if (bots[i] == null) bots[i] = $("all-bots").value || "random";
      }
    }
    try {
      updateMode(false);
      renderBatchMode();
      syncSeats();
      rollSeed();
      showStep(0, false);
      $("replay-setup").disabled = lastSetup === null;
    } catch (error) { showError(error.message); }
  }

  function rememberStarted(data) {
    lastSetup = copy(data);
    $("replay-setup").disabled = false;
  }

  function defaultQuickplay() {
    return {
      mode: "play", game_type: "board", notebook_mode: "manual", players: 4, seat: 0,
      bots: ["hard", "focused", "steady", "cautious"].map(learnedProfile), shuffle_bots: true,
      seat_suspects: [0, 1, 2, 3], board_rules: { ...standardRules },
      game_rules: Object.fromEntries(Object.keys(gameRuleIds).map((key) => [key, false])),
      progress: "turn", max_steps: 10000, debug: false,
    };
  }

  async function loadQuickplay() {
    await profilesLoad;
    const data = profiles[quickplayProfile] ?? defaultQuickplay();
    if (data.game_type === "board") await metadataReady;
    loadSetup(data, false);
  }

  $("all-bots").value = "hard";
  $("roll-seed").addEventListener("click", () => {
    try { rollSeed(); showError(""); } catch (error) { showError(error.message); }
  });
  $("copy-seed").addEventListener("click", async () => {
    if (!await confirmAction("The seed can reveal the deal and solution. Copy it anyway?", {
      title: "Copy seed", confirmLabel: "Copy seed",
    })) return;
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
  $("setup-back").addEventListener("click", () => {
    if (step === 0) showMainMenu();
    else showStep(step - 1);
  });
  $("setup-next").addEventListener("click", () => {
    if (validBasics()) { showError(""); syncSeats(); showStep(step + 1); }
  });
  $("batch-games").addEventListener("input", () => {
    if (step === 4) renderReview();
  });
  for (const button of document.querySelectorAll("[data-setup-step]")) {
    button.addEventListener("click", () => {
      if (validBasics()) { showError(""); syncSeats(); showStep(Number(button.dataset.setupStep)); }
    });
  }
  for (const element of [$("players"), $("mode"), $("seat"), ...document.querySelectorAll('input[name="game-type"]')]) {
    element.addEventListener("change", syncSeats);
  }
  $("mode").addEventListener("change", renderBatchMode);
  $("batch-enabled").addEventListener("change", () => {
    batchMode = $("mode").value === "spectate" && $("batch-enabled").checked;
    renderBatchMode();
    syncSeats();
  });
  $("shuffle-bots").addEventListener("change", () => {
    renderBatchMode();
    renderBots();
  });
  $("enable-legacy-bots").addEventListener("change", async () => {
    if (!$("enable-legacy-bots").checked && !isBoard()) {
      $("enable-legacy-bots").checked = true;
      showError("Card-only games require legacy bots.");
      return;
    }
    if (!$("enable-legacy-bots").checked) {
      const legacySeats = bots.map((_, i) => i).filter((i) => isLegacyBot(bots[i]));
      if (legacySeats.length && !await confirmAction(
        "Replace the selected legacy bots with the Steady learned profile?",
        { title: "Disable legacy bots", confirmLabel: "Use learned profiles" },
      )) {
        $("enable-legacy-bots").checked = true;
        return;
      }
      for (const i of legacySeats) bots[i] = learnedProfile("steady");
    }
    showError("");
    renderBots();
    if (step === 4) renderReview();
  });
  $("shuffle-bot-count").addEventListener("change", () => {
    shuffleBotProfileCount = Number($("shuffle-bot-count").value);
    renderBots();
    if (step === 4) renderReview();
  });
  $("shuffle-seat").addEventListener("change", renderSeats);
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
  $("apply-bots").addEventListener("click", async () => {
    const human = $("mode").value === "play" ? Number($("seat").value) : -1;
    const count = Number($("players").value);
    if (bots.slice(0, count).some((bot, i) => i !== human && typeof bot !== "string")
      && !await confirmAction("Replace custom settings for all bots?", {
        title: "Replace bot settings", confirmLabel: "Replace settings",
      })) return;
    for (let i = 0; i < count; i++) {
      if (i !== human) bots[i] = botFromChoice($("all-bots").value, bots[i]);
    }
    renderBots();
  });
  $("bot-list").addEventListener("change", async (event) => {
    const target = event.target;
    if (target.dataset.botSeat !== undefined) {
      const i = Number(target.dataset.botSeat);
      bots[i] = botFromChoice(target.value, bots[i]);
      renderBots();
      document.querySelector(`[data-bot-seat="${i}"]`).focus();
    } else if (target.dataset.botSetting) {
      const i = Number(target.dataset.botIndex);
      bots[i][target.dataset.botSetting] = target.checked;
      document.querySelector(`[data-bot-score="${i}"]`).textContent =
        `Toolkit: ${score(bots[i])}/100`;
    } else if (target.dataset.learnedSetting) {
      const i = Number(target.dataset.botIndex);
      bots[i] = { ...learnedSettings(bots[i]), [target.dataset.learnedSetting]: Number(target.value) };
      renderBots();
      document.querySelector(`[data-bot-seat="${i}"]`).focus();
    } else if (target.dataset.copySeat !== undefined && target.value !== "") {
      const i = Number(target.dataset.copySeat);
      if (typeof bots[i] !== "string" && !await confirmAction("Replace this bot's custom settings?", {
        title: "Replace bot settings", confirmLabel: "Replace settings",
      })) {
        target.value = "";
        return;
      }
      bots[i] = copy(bots[Number(target.value)]);
      renderBots();
      document.querySelector(`[data-copy-seat="${i}"]`).focus();
    }
  });
  $("rule-preset").addEventListener("change", () => {
    if ($("rule-preset").value === "standard") setRules(standardRules);
    if ($("rule-preset").value === "no-relocation") setRules({
      ...standardRules, move_suspect: false, move_weapon: false, summoned_suggestion: false,
    });
  });
  $("reset-rules").addEventListener("click", () => {
    for (const id of Object.values(gameRuleIds)) $(id).checked = false;
    setRules(standardRules);
  });
  for (const id of Object.values(ruleIds)) {
    $(id).addEventListener("change", () => {
      if (!$("rule-move-suspect").checked) $("rule-summoned").checked = false;
      if (!$("rule-randomize-rooms").checked) $("rule-procedural-map").checked = false;
      renderRules();
    });
  }
  $("rule-passage-count").addEventListener("change", renderRules);
  $("profile-save").addEventListener("click", async () => {
    try {
      if (!profilesReady) throw new Error("Setup profiles were not loaded; reload before saving.");
      const name = $("profile-name").value.trim();
      if (!name || name.length > 80) throw new Error("Enter a profile name of up to 80 characters.");
      if (name === quickplayProfile) throw new Error("This profile name is reserved.");
      if (Object.hasOwn(profiles, name) && !await confirmAction(`Replace profile "${name}"?`, {
        title: "Replace profile", confirmLabel: "Replace profile",
      })) return;
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
      if (name === quickplayProfile) throw new Error("This profile name is reserved.");
      if (name === oldName) throw new Error("Enter a different profile name.");
      if (Object.hasOwn(profiles, name) && !await confirmAction(`Replace profile "${name}"?`, {
        title: "Replace profile", confirmLabel: "Replace profile",
      })) return;
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
      if (!await confirmAction(`Delete profile "${name}"?`, {
        title: "Delete profile", confirmLabel: "Delete profile",
      })) return;
      const next = Object.assign(Object.create(null), profiles);
      delete next[name];
      await persistProfiles(next);
      $("profile-status").textContent = `Deleted "${name}".`;
      showError("");
    } catch (error) { showError(error.message); }
  });
  $("save-quickplay-default").addEventListener("click", async () => {
    try {
      if (!profilesReady) throw new Error("Setup profiles were not loaded; reload before saving.");
      const data = payload();
      delete data.seed;
      validateProfile(data);
      if (!Object.hasOwn(profiles, quickplayProfile) && Object.keys(profiles).length >= 100) {
        throw new Error("A maximum of 100 profiles can be saved. Delete a profile first.");
      }
      await persistProfiles(Object.assign(Object.create(null), profiles, { [quickplayProfile]: data }));
      $("quickplay-status").textContent = "Quickplay defaults saved.";
      showError("");
    } catch (error) { showError(error.message); }
  });
  const metadataReady = requestJson("/api/setup").then((data) => { metadata = data; renderPreview(); });
  metadataReady.catch((error) => showError(`Could not load board setup: ${error.message}`));
  const profilesLoad = loadProfiles();
  profilesLoad.catch((error) => showError(`Could not load setup profiles: ${error.message}`));
  syncSeats();
  beginFresh();
  return {
    payload, resolveBotSeats, beginFresh, rememberStarted, loadQuickplay, renderReview,
    isBatchMode: () => batchMode,
    batchGames: () => Number($("batch-games").value),
  };
})();
