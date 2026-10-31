import re

import pytest

from clue_engine.engine import Engine
from clue_engine.models import Combination, EndTurn, Reveal, Suggest
from clue_engine.state import GameState
from clue_engine.webapp import create_app


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


def test_optional_setup_controls_are_disclosed_on_demand(client):
    page = client.get("/").get_data(as_text=True)
    for summary in ("Advanced options", "Saved setup profiles"):
        details = re.search(rf"<details\b([^>]*)>\s*<summary>{re.escape(summary)}</summary>", page)
        assert details is not None
        assert not re.search(r"\bopen(?:\s|=|$)", details.group(1))
    assert '<nav class="wizard-progress" aria-label="New game steps">' in page


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
    }
    assert "debug_info" in public_state and public_state["debug_info"] is None
    assert "solution" not in public_state

    private_view = client.get("/api/state?player=0").get_json()
    dagger = next(row for row in private_view["matrix"] if row["id"] == 7)
    assert dagger["marks"][1] == "+"
    assert private_view["activity"]["card_id"] == 7
    assert all(event["kind"] != "show" for event in private_view["events"])

    unrelated_view = client.get("/api/state?player=2").get_json()
    assert unrelated_view["activity"]["kind"] == "refute"
    assert "card_id" not in unrelated_view["activity"]


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
