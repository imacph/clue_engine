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
