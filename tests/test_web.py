import re

import pytest

from clue_engine.engine import Engine
from clue_engine.knowledge import Mark, knowledge_for
from clue_engine.models import Accuse, Combination, EndTurn, Pass, Reveal, Suggest
from clue_engine.state import GameState
from clue_engine.webapp import _automatic_clauses, create_app


class ScriptedPolicy:
    def __init__(self, *actions):
        self.actions = iter(actions)

    def choose(self, view, num_players, legal):
        action = next(self.actions)
        assert action in legal
        return action


def make_engine():
    return Engine(GameState(
        Combination(0, 6, 12),
        [
            frozenset({1, 2, 3, 4, 5}),
            frozenset({7, 8, 9, 10, 11}),
            frozenset({13, 14, 15, 16}),
            frozenset({17, 18, 19, 20}),
        ],
        0,
    ))


@pytest.fixture
def client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def csrf_token(client):
    response = client.get("/")
    assert response.status_code == 200
    match = re.search(rb'name="csrf-token" content="([^"]+)"', response.data)
    assert match is not None
    return match.group(1).decode()


def post(client, token, path, body):
    return client.post(path, json=body, headers={"X-CSRF-Token": token})


def test_local_page_sets_csrf_token_and_serves_assets(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"New game" in response.data
    assert b"/static/app.js" in response.data
    assert b"csrf-token" in response.data
    assert b'id="theme-toggle"' in response.data
    assert b'id="action-dialog"' not in response.data
    assert b'id="action-menu-button"' not in response.data
    assert b'id="card-action-buttons"' in response.data
    assert b'id="end-button"' in response.data
    assert b'id="pass-button"' in response.data
    assert b'class="game-dashboard"' in response.data
    assert b'data-card-view="all"' in response.data
    assert b'id="card-suggest-button"' in response.data
    assert b'id="card-accuse-button"' in response.data
    assert b'id="activity-meta"' in response.data
    assert b'id="history-tab"' in response.data
    assert b'id="clauses-tab"' in response.data
    assert b'id="clauses-panel" class="panel clauses-panel" role="tabpanel"' in response.data
    assert b"Private view" not in response.data
    assert b"Your cards" not in response.data
    assert client.get("/static/app.js").status_code == 200
    stylesheet = client.get("/static/style.css")
    assert stylesheet.status_code == 200
    assert b"[hidden] { display: none !important; }" in stylesheet.data


def test_private_replay_captures_perspectives_and_manual_history(client, monkeypatch):
    def scripted(num_players, seed, policy_name):
        return make_engine(), (
            ScriptedPolicy(), ScriptedPolicy(Reveal(7)), ScriptedPolicy(), ScriptedPolicy(),
        )

    monkeypatch.setattr("clue_engine.webapp.create_game", scripted)
    token = csrf_token(client)
    assert post(client, token, "/api/game", {
        "players": 4, "seat": 0, "progress": "step", "notebook_mode": "manual",
    }).status_code == 201
    assert client.get("/api/replay/export").status_code == 409
    assert client.get("/api/replay/state").status_code == 400
    assert post(client, token, "/api/replay/end", {}).status_code == 400
    assert client.put("/api/notebook", json={"card_id": 7, "holder": 2, "mark": "+"},
                      headers={"X-CSRF-Token": token}).status_code == 200
    assert post(client, token, "/api/notebook/clauses", {
        "kind": "refute", "holder": 1, "cards": [0, 7, 13], "resolved": False,
    }).status_code == 200
    assert post(client, token, "/api/action", {
        "action": "suggest", "suspect_id": 0, "weapon_id": 7, "room_id": 13,
    }).status_code == 200
    assert post(client, token, "/api/advance", {"step": True}).status_code == 200
    assert post(client, token, "/api/replay/end", {"confirmed": True}).status_code == 200
    assert post(client, token, "/api/action", {"action": "end_turn"}).status_code == 409
    assert post(client, token, "/api/advance", {"step": True}).status_code == 409

    before = client.get("/api/replay/state?position=0&player=0&manual=1").get_json()
    marked = client.get("/api/replay/state?position=1&player=0&manual=1").get_json()
    noted = client.get("/api/replay/state?position=2&player=0&manual=1").get_json()
    assert before["matrix"][7]["marks"][2] == "?"
    assert marked["matrix"][7]["marks"][2] == "+"
    assert len(noted["notebook_clauses"]) == 1
    assert not any(noted["matrix"][7]["editable"])
    player0 = client.get("/api/replay/state?position=4&player=0").get_json()
    player2 = client.get("/api/replay/state?position=4&player=2").get_json()
    assert player0["matrix"][7]["marks"][1] == "+"
    assert player2["matrix"][7]["marks"][1] == "?"
    assert all(event["kind"] != "show" for event in player2["events"])
    assert client.get("/api/replay/state?position=4&player=2&omniscient=1").get_json()["debug_info"]

    exported = client.get("/api/replay/export")
    assert exported.headers["Content-Disposition"] == 'attachment; filename="clue-private-replay.json"'
    assert exported.headers["Cache-Control"] == "no-store"
    record = exported.get_json()
    assert record["private"] is True
    assert post(client, token, "/api/replay/import", record).status_code == 200
    restored = client.get("/api/replay/state?position=2&player=0&manual=1").get_json()
    assert restored["matrix"][7]["marks"][2] == "+"
    assert len(restored["notebook_clauses"]) == 1
    record["history"][0]["actor"] = 3
    assert post(client, token, "/api/replay/import", record).status_code == 400


@pytest.mark.parametrize("public", [False, True])
def test_multi_response_activity_and_replay_with_face_up_cards(client, monkeypatch, public):
    def scripted(num_players, seed, policy_name, *, game_rules):
        state = make_engine().state
        state.game_rules = game_rules
        state.public_cards = (2, 8, 14, 17)
        return Engine(state), (
            ScriptedPolicy(Suggest(Combination(0, 7, 13))),
            ScriptedPolicy(Reveal(7)), ScriptedPolicy(), ScriptedPolicy(Pass()),
        )

    monkeypatch.setattr("clue_engine.webapp.create_game", scripted)
    token = csrf_token(client)
    response = post(client, token, "/api/game", {
        "players": 4, "seat": 2, "progress": "step", "notebook_mode": "manual",
        "game_rules": {
            "public_refutations": public, "all_refute": True, "face_up_card": True,
        },
    })
    assert response.status_code == 201
    assert response.get_json()["game_rules"] == {
        "reverse_refutation": False, "public_refutations": public,
        "all_refute": True, "face_up_card": True,
    }
    assert len([event for event in response.get_json()["events"] if event["kind"] == "expose"]) == 4
    assert post(client, token, "/api/advance", {"step": True}).status_code == 200
    state = post(client, token, "/api/advance", {"step": True}).get_json()
    assert state["to_move"] == 2
    assert state["activity"]["cards"] == [0, 7, 13]
    assert [card["id"] for card in state["legal"]["reveals"]] == [13]
    assert state["activity"]["kind"] == ("reveal" if public else "refute")
    assert post(client, token, "/api/action", {"action": "reveal", "card_id": 13}).status_code == 200
    assert post(client, token, "/api/replay/end", {"confirmed": True}).status_code == 200
    record = client.get("/api/replay/export").get_json()
    assert post(client, token, "/api/replay/import", record).status_code == 200
    initial = client.get("/api/replay/state?position=0&player=3").get_json()
    assert len([event for event in initial["events"] if event["kind"] == "expose"]) == 4
    replay = client.get("/api/replay/state?position=3&player=3").get_json()
    assert len([event for event in replay["events"] if event["kind"] == "show"]) == (
        2 if public else 0
    )


def test_replay_unlocks_on_game_over_but_not_action_limit(client, monkeypatch):
    def scripted(num_players, seed, policy_name):
        return make_engine(), tuple(ScriptedPolicy() for _ in range(num_players))

    monkeypatch.setattr("clue_engine.webapp.create_game", scripted)
    token = csrf_token(client)
    assert post(client, token, "/api/game", {
        "players": 4, "seat": 0, "progress": "step", "max_steps": 0,
    }).status_code == 201
    assert client.get("/api/replay/export").status_code == 409
    assert post(client, token, "/api/game", {
        "players": 4, "seat": 0, "progress": "step",
    }).status_code == 201
    assert post(client, token, "/api/action", {
        "action": "accuse", "confirmed": True, "suspect_id": 0, "weapon_id": 6, "room_id": 12,
    }).get_json()["is_over"]
    assert client.get("/api/replay/export").status_code == 200
    replay = client.get("/api/replay/state?position=1&player=1").get_json()
    assert replay["winner"] == 0
    assert replay["manual_available"] is False


def test_optional_setup_controls_are_disclosed_on_demand(client):
    page = client.get("/").get_data(as_text=True)
    for summary in ("Advanced options", "Saved setup profiles"):
        details = re.search(rf"<details\b([^>]*)>\s*<summary>{re.escape(summary)}</summary>", page)
        assert details is not None
        assert not re.search(r"\bopen(?:\s|=|$)", details.group(1))
    assert '<nav class="wizard-progress" aria-label="New game steps">' in page
    assert 'id="setup-form" novalidate' in page
    assert 'id="setup-quick-play" type="submit"' in page
    assert page.index('id="setup-next"') < page.index('data-step="0"')


def test_start_game_and_submit_actions_without_exposing_solution(client):
    token = csrf_token(client)
    response = post(client, token, "/api/game", {
        "mode": "play",
        "players": 4,
        "seat": 0,
        "seed": 42,
        "policy": "deductive",
        "progress": "step",
        "max_steps": 100,
    })
    assert response.status_code == 201
    state = response.get_json()
    assert state["hand"]
    assert state["legal"]["suggest"] is True
    assert "solution" not in state
    assert state["paused"] is True

    response = post(client, token, "/api/action", {
        "action": "suggest",
        "suspect_id": 0,
        "weapon_id": 6,
        "room_id": 12,
    })
    assert response.status_code == 200
    assert response.get_json()["to_move"] == 1
    assert response.get_json()["steps"] == 1
    assert response.get_json()["activity"] == {
        "kind": "suggest",
        "actor": 0,
        "cards": [0, 6, 12],
    }

    response = post(client, token, "/api/action", {"action": "reveal", "card_id": 20})
    assert response.status_code == 409
    assert response.get_json()["error"]


@pytest.mark.parametrize("game_type,players", [("card_only", 4), ("board", 3)])
def test_manual_notebook_starts_with_only_hand_facts_and_persists(client, game_type, players):
    token = csrf_token(client)
    headers = {"X-CSRF-Token": token}
    config = {
        "game_type": game_type, "players": players, "seat": 0,
        "seed": 42, "progress": "step", "notebook_mode": "manual",
    }
    state = post(client, token, "/api/game", config).get_json()
    assert state["notebook_mode"] == "manual"
    assert "disabled" in state["clauses"]
    hand = set(state["hand"])
    for row in state["matrix"]:
        in_hand = row["id"] in hand
        assert row["marks"][0] == ("+" if in_hand else "-")
        for holder in range(1, players + 1):
            assert row["marks"][holder] == ("-" if in_hand else "?")
            assert row["editable"][holder] == (not in_hand)
        assert row["editable"][0] is False
    card_id = next(row["id"] for row in state["matrix"] if row["id"] not in hand)
    edit = {"card_id": card_id, "holder": players, "mark": "+"}
    response = client.put("/api/notebook", json=edit, headers=headers)
    assert response.status_code == 200
    assert response.get_json()["notebook_revision"] == 1
    state = client.get("/api/state").get_json()
    row = next(row for row in state["matrix"] if row["id"] == card_id)
    assert row["marks"][players] == "+"
    assert client.put("/api/notebook", json=edit, headers=headers).get_json()["notebook_revision"] == 1
    edit["mark"] = "?"
    reset = client.put("/api/notebook", json=edit, headers=headers).get_json()
    assert reset["notebook_revision"] == 2
    assert next(row for row in reset["matrix"] if row["id"] == card_id)["marks"][players] == "?"
    edit["mark"] = "-"
    client.put("/api/notebook", json=edit, headers=headers)
    new_state = post(client, token, "/api/game", config).get_json()
    assert new_state["notebook_revision"] == 0
    assert next(row for row in new_state["matrix"] if row["id"] == card_id)["marks"][players] == "?"


@pytest.mark.parametrize("mode", ["manual", "automatic"])
def test_notebook_only_automatic_mode_records_shown_cards(client, monkeypatch, mode):
    def create_scripted_game(num_players, seed, policy_name):
        return make_engine(), (
            ScriptedPolicy(), ScriptedPolicy(Reveal(7)),
            ScriptedPolicy(), ScriptedPolicy(),
        )

    monkeypatch.setattr("clue_engine.webapp.create_game", create_scripted_game)
    token = csrf_token(client)
    state = post(client, token, "/api/game", {
        "players": 4, "seat": 0, "progress": "step", "notebook_mode": mode,
    }).get_json()
    assert state["notebook_mode"] == mode
    if mode == "manual":
        response = client.put(
            "/api/notebook",
            json={"card_id": 13, "holder": 4, "mark": "-"},
            headers={"X-CSRF-Token": token},
        )
        assert response.status_code == 200
    assert post(client, token, "/api/action", {
        "action": "suggest", "suspect_id": 0, "weapon_id": 7, "room_id": 13,
    }).status_code == 200
    response = post(client, token, "/api/advance", {"step": True})
    assert response.status_code == 200
    state = response.get_json()
    assert state["activity"]["card_id"] == 7
    assert next(row for row in state["matrix"] if row["id"] == 7)["marks"][1] == (
        "?" if mode == "manual" else "+"
    )
    if mode == "manual":
        assert "disabled" in state["clauses"]
        assert next(row for row in state["matrix"] if row["id"] == 13)["marks"][4] == "-"
    else:
        assert "disabled" not in state["clauses"]


def test_notebook_rejects_invalid_edits_and_preserves_legacy_auto_mode(client):
    token = csrf_token(client)
    headers = {"X-CSRF-Token": token}
    edit = {"card_id": 0, "holder": 1, "mark": "+"}
    assert client.put("/api/notebook", json=edit, headers=headers).status_code == 404
    assert post(client, token, "/api/game", {"notebook_mode": []}).status_code == 400
    assert post(client, token, "/api/game", {
        "mode": "spectate", "notebook_mode": "manual",
    }).status_code == 400
    state = post(client, token, "/api/game", {"progress": "step"}).get_json()
    assert state["notebook_mode"] == "automatic"
    assert client.put("/api/notebook", json=edit, headers=headers).status_code == 409
    state = post(client, token, "/api/game", {
        "progress": "step", "notebook_mode": "manual",
    }).get_json()
    free_card = next(row["id"] for row in state["matrix"] if row["id"] not in state["hand"])
    for invalid in (
        {"card_id": -1, "holder": 1, "mark": "+"},
        {"card_id": True, "holder": 1, "mark": "+"},
        {"card_id": free_card, "holder": -1, "mark": "+"},
        {"card_id": free_card, "holder": 5, "mark": "+"},
        {"card_id": free_card, "holder": 1, "mark": "maybe"},
        {"card_id": free_card, "holder": 1, "mark": "+", "extra": True},
    ):
        assert client.put("/api/notebook", json=invalid, headers=headers).status_code == 400
    for locked in (
        {"card_id": free_card, "holder": 0, "mark": "+"},
        {"card_id": state["hand"][0], "holder": 1, "mark": "+"},
    ):
        assert client.put("/api/notebook", json=locked, headers=headers).status_code == 409
    assert client.put("/api/notebook", json=edit).status_code == 403
    assert client.get("/api/state").get_json()["notebook_revision"] == 0


def test_manual_notebooks_are_isolated_between_sessions():
    app = create_app()
    first, second = app.test_client(), app.test_client()
    first_token, second_token = csrf_token(first), csrf_token(second)
    config = {"notebook_mode": "manual", "seed": 12, "progress": "step"}
    state = post(first, first_token, "/api/game", config).get_json()
    post(second, second_token, "/api/game", config)
    card_id = next(row["id"] for row in state["matrix"] if row["id"] not in state["hand"])
    response = first.put(
        "/api/notebook", json={"card_id": card_id, "holder": 1, "mark": "+"},
        headers={"X-CSRF-Token": first_token},
    )
    assert response.status_code == 200
    other = second.get("/api/state").get_json()
    assert other["notebook_revision"] == 0
    assert next(row for row in other["matrix"] if row["id"] == card_id)["marks"][1] == "?"


@pytest.mark.parametrize("game_type,players", [("card_only", 4), ("board", 3)])
def test_manual_clause_lifecycle_is_independent_of_marks(client, game_type, players):
    token = csrf_token(client)
    headers = {"X-CSRF-Token": token}
    config = {
        "game_type": game_type, "players": players, "seat": 0,
        "seed": 42, "progress": "step", "notebook_mode": "manual",
    }
    initial = post(client, token, "/api/game", config).get_json()
    free = [
        next(row["id"] for row in initial["matrix"]
             if row["type"] == kind and row["id"] not in initial["hand"])
        for kind in ("suspect", "weapon", "room")
    ]
    refute = {"kind": "refute", "holder": 1, "cards": free, "resolved": False}
    accusation = {"kind": "accuse", "holder": players, "cards": free, "resolved": False}
    state = post(client, token, "/api/notebook/clauses", refute).get_json()
    assert state["notebook_revision"] == 1
    assert state["notebook_clauses"] == [{
        "id": 1, "kind": "refute", "holder": 1, "actor": 1,
        "cards": sorted(free), "active_cards": sorted(free), "excluded_cards": [],
        "status": "unresolved",
    }]
    state = post(client, token, "/api/notebook/clauses", accusation).get_json()
    assert [clause["id"] for clause in state["notebook_clauses"]] == [1, 2]
    assert state["notebook_clauses"][1]["holder"] == players
    state = client.put(
        "/api/notebook", json={"card_id": free[0], "holder": 1, "mark": "+"}, headers=headers,
    ).get_json()
    assert state["notebook_clauses"][0]["active_cards"] == sorted(free)
    refute["excluded_cards"] = [free[0]]
    state = client.put("/api/notebook/clauses/1", json=refute, headers=headers).get_json()
    assert state["notebook_clauses"][0]["active_cards"] == sorted(free[1:])
    refute["resolved"] = True
    state = client.put("/api/notebook/clauses/1", json=refute, headers=headers).get_json()
    assert state["notebook_clauses"][0]["status"] == "resolved"
    assert state["notebook_clauses"][0]["active_cards"] == []
    assert state["notebook_clauses"][0]["cards"] == sorted(free)
    assert state["notebook_clauses"][0]["excluded_cards"] == [free[0]]
    revision = state["notebook_revision"]
    assert client.put(
        "/api/notebook/clauses/1", json=refute, headers=headers,
    ).get_json()["notebook_revision"] == revision
    refute["resolved"] = False
    state = client.put("/api/notebook/clauses/1", json=refute, headers=headers).get_json()
    assert state["notebook_clauses"][0]["active_cards"] == sorted(free[1:])
    assert client.get("/api/state?clause_kind=accuse").get_json()["notebook_clauses"] == (
        state["notebook_clauses"]
    )
    assert client.delete("/api/notebook/clauses/1", headers=headers).status_code == 200
    state = post(client, token, "/api/notebook/clauses", refute).get_json()
    assert [clause["id"] for clause in state["notebook_clauses"]] == [2, 3]
    assert client.get("/api/state").get_json()["notebook_clauses"] == state["notebook_clauses"]
    assert post(client, token, "/api/game", config).get_json()["notebook_clauses"] == []


def test_manual_clause_validation_and_session_isolation():
    app = create_app()
    first, second = app.test_client(), app.test_client()
    first_token, second_token = csrf_token(first), csrf_token(second)
    config = {"notebook_mode": "manual", "seed": 12, "progress": "step"}
    post(first, first_token, "/api/game", config)
    post(second, second_token, "/api/game", config)
    clause = {"kind": "refute", "holder": 1, "cards": [0, 7, 13], "resolved": False}
    for bad in (
        {**clause, "kind": "other"}, {**clause, "holder": 4},
        {**clause, "kind": "accuse"}, {**clause, "cards": []},
        {**clause, "cards": [0, 0]}, {**clause, "cards": [True]},
        {**clause, "cards": [999]}, {**clause, "resolved": 1},
        {**clause, "cards": [0, 7]}, {**clause, "cards": [0, 1, 13]},
        {**clause, "cards": [0, 1, 7, 13]},
        {**clause, "excluded_cards": [1]}, {**clause, "excluded_cards": [0, 0]},
        {**clause, "extra": 1},
    ):
        assert post(first, first_token, "/api/notebook/clauses", bad).status_code == 400
    assert first.post("/api/notebook/clauses", json=clause).status_code == 403
    initial = post(first, first_token, "/api/notebook/clauses", clause).get_json()
    invalid_edit = {**clause, "cards": [0, 1, 13]}
    response = first.put(
        "/api/notebook/clauses/1", json=invalid_edit, headers={"X-CSRF-Token": first_token},
    )
    assert response.status_code == 400
    unchanged = first.get("/api/state").get_json()
    assert unchanged["notebook_clauses"] == initial["notebook_clauses"]
    assert unchanged["notebook_revision"] == initial["notebook_revision"]
    assert second.get("/api/state").get_json()["notebook_clauses"] == []
    assert second.delete(
        "/api/notebook/clauses/1", headers={"X-CSRF-Token": second_token},
    ).status_code == 404
    post(first, first_token, "/api/game", {"progress": "step"})
    assert post(first, first_token, "/api/notebook/clauses", clause).status_code == 409


def test_automatic_clause_identity_and_types_follow_public_events():
    engine = make_engine()
    engine.step(Suggest(Combination(0, 7, 13)))
    engine.step(Reveal(7))
    view = engine.view(0)
    before = _automatic_clauses(view, knowledge_for(view, engine.num_players))
    assert before[0]["status"] == "satisfied"
    engine.step(EndTurn())
    engine.step(Accuse(Combination(2, 8, 14)))
    engine.step(Accuse(Combination(2, 8, 14)))
    view = engine.view(0)
    after = _automatic_clauses(view, knowledge_for(view, engine.num_players))
    assert after[0] == before[0]
    assert [clause["id"] for clause in after] == [1, 2, 3]
    assert [clause["actor"] for clause in after] == [1, 1, 2]
    assert all(clause["kind"] == "accuse" and clause["holder"] == 4 for clause in after[1:])
    assert all(clause["status"] == "satisfied" for clause in after[1:])
    other = engine.view(3)
    other_clauses = _automatic_clauses(other, knowledge_for(other, engine.num_players))
    assert [clause["id"] for clause in other_clauses] == [1, 2, 3]
    assert other_clauses[1]["status"] == "unresolved"
    assert other_clauses[1]["active_cards"] == [2, 8, 14]
    other_knowledge = knowledge_for(other, engine.num_players)
    other_knowledge.marks[other_knowledge.envelope][2] = Mark.HELD
    narrowed = _automatic_clauses(other, other_knowledge)[1]
    assert narrowed["status"] == "unresolved"
    assert narrowed["active_cards"] == [8, 14]
    other_knowledge.marks[other_knowledge.envelope][8] = Mark.NOT_HELD
    satisfied = _automatic_clauses(other, other_knowledge)[1]
    assert satisfied["status"] == "satisfied"
    assert satisfied["active_cards"] == []


@pytest.mark.parametrize("players", [2, 7])
def test_default_card_only_web_game_supports_counts_outside_board_range(client, players):
    token = csrf_token(client)
    response = post(client, token, "/api/game", {"players": players, "progress": "step"})
    assert response.status_code == 201
    assert response.get_json()["legal"]["suggest"] is True

    response = post(client, token, "/api/action", {
        "action": "suggest",
        "suspect_id": 0,
        "weapon_id": 6,
        "room_id": 20,
    })
    assert response.status_code == 200
    assert response.get_json()["to_move"] == 1


def test_spectator_history_hides_private_show_and_notebook_uses_selected_view(
    client, monkeypatch
):
    def create_scripted_game(num_players, seed, policy_name):
        return make_engine(), (
            ScriptedPolicy(Suggest(Combination(0, 7, 13))),
            ScriptedPolicy(Reveal(7)),
            ScriptedPolicy(EndTurn()),
            ScriptedPolicy(EndTurn()),
        )

    monkeypatch.setattr("clue_engine.webapp.create_game", create_scripted_game)
    token = csrf_token(client)
    response = post(client, token, "/api/game", {
        "mode": "spectate",
        "players": 4,
        "seed": 0,
        "policy": "deductive",
        "progress": "step",
        "max_steps": 20,
    })
    assert response.status_code == 201
    for _ in range(2):
        response = post(client, token, "/api/advance", {"step": True})
        assert response.status_code == 200
    public_state = client.get("/api/state").get_json()
    assert all(event["kind"] != "show" for event in public_state["events"])
    assert [event["kind"] for event in public_state["events"]] == ["refute", "suggest"]
    assert [event["number"] for event in public_state["events"]] == [2, 1]
    assert public_state["activity"] == {
        "kind": "reveal",
        "actor": 1,
        "suggestion_actor": 0,
        "card_id": 7,
        "recipient": 0,
        "cards": [0, 7, 13],
        "public": False,
    }
    assert "debug_info" in public_state and public_state["debug_info"] is None
    assert "solution" not in public_state

    private_view = client.get("/api/state?player=0").get_json()
    dagger = next(row for row in private_view["matrix"] if row["id"] == 7)
    assert dagger["marks"][1] == "+"
    assert private_view["activity"]["card_id"] == 7
    assert all(event["kind"] != "show" for event in private_view["events"])
    assert private_view["notebook_clauses"][0]["status"] == "satisfied"
    assert private_view["notebook_clauses"][0]["active_cards"] == []

    unrelated_view = client.get("/api/state?player=2").get_json()
    assert unrelated_view["activity"]["kind"] == "refute"
    assert "card_id" not in unrelated_view["activity"]
    clause = unrelated_view["notebook_clauses"][0]
    assert clause["id"] == private_view["notebook_clauses"][0]["id"]
    assert clause["status"] == "unresolved"
    assert clause["active_cards"] == [0, 7]


def test_mutations_require_csrf_and_invalid_setup_is_reported(client):
    response = client.post("/api/game", json={"mode": "play"})
    assert response.status_code == 403

    token = csrf_token(client)
    response = post(client, token, "/api/game", {
        "mode": "play",
        "players": 1,
        "seat": 0,
        "seed": 1,
        "policy": "deductive",
        "progress": "auto",
        "max_steps": 100,
    })
    assert response.status_code == 400
    assert "at least two" in response.get_json()["error"]


def test_debug_exposes_solution_only_when_explicitly_enabled(client):
    token = csrf_token(client)
    response = post(client, token, "/api/game", {
        "mode": "spectate",
        "players": 4,
        "seed": 42,
        "policy": "deductive",
        "progress": "step",
        "max_steps": 100,
        "debug": True,
    })
    assert response.status_code == 201
    assert response.get_json()["debug_info"] is not None
