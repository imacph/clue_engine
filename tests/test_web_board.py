import random
import re
from dataclasses import replace

import pytest

from clue_engine.board import Square
from clue_engine.board_state import SuspectToken
from clue_engine.engine import Engine
from clue_engine.policies import make_policy
from clue_engine.state import deal_board
from clue_engine.webapp import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def token(client):
    page = client.get("/")
    match = re.search(rb'name="csrf-token" content="([^"]+)"', page.data)
    assert match is not None
    return match.group(1).decode()


def post(client, csrf, path, body):
    return client.post(path, json=body, headers={"X-CSRF-Token": csrf})


@pytest.mark.parametrize("players", [2, 7])
def test_board_player_limits_do_not_change_card_only(client, players):
    csrf = token(client)
    board = post(client, csrf, "/api/game", {"game_type": "board", "players": players})
    assert board.status_code == 400
    assert "3" in board.get_json()["error"] and "6" in board.get_json()["error"]
    cards = post(client, csrf, "/api/game", {"players": players, "progress": "step"})
    assert cards.status_code == 201
    assert cards.get_json()["board"] is None
    assert cards.get_json()["legal"]["suggest"] is True


def test_setup_page_and_public_board_state(client):
    csrf = token(client)
    page = client.get("/").data
    assert b'id="board-panel"' in page
    assert b'id="board-workspace-tabs"' in page
    for section in (
        b"cards-panel", b"history-panel", b"clauses-panel", b"board-locations-panel", b"help-panel",
    ):
        assert b'aria-controls="' + section + b'"' in page
    assert b'id="board-tab-notebook"' not in page
    assert b'id="card-details-tabs"' not in page
    assert b'id="notebook-workspace"' in page
    assert b'id="clause-entry"' in page
    assert b'id="notebook-instructions"' not in page
    assert b'aria-label="Detective notebook"' in page
    assert b'id="clause-form"' not in page
    assert b'aria-orientation="vertical"' in page
    assert b'id="action-history-list"' in page
    assert page.count(b'id="notebook-panel"') == 1
    assert page.count(b'id="insights-panel"') == 1
    assert b'id="board-map"' in page
    assert b"Board viewport; use arrow keys to move" in page
    assert b'id="board-moves"' not in page
    assert b'name="game-type"' in page
    response = post(client, csrf, "/api/game", {
        "game_type": "board", "players": 4, "seed": 42, "progress": "step",
    })
    assert response.status_code == 201
    state = response.get_json()
    board = state["board"]
    assert state["game_type"] == "board"
    assert (board["layout"]["width"], board["layout"]["height"]) == (25, 27)
    assert len(board["layout"]["rooms"]) == 9
    assert len(board["layout"]["doors"]) == 20
    assert len(board["layout"]["passages"]) == 2
    assert len(board["suspects"]) == len(board["weapons"]) == 6
    assert [suspect["seat"] for suspect in board["suspects"]] == [0, 1, 2, 3, None, None]
    assert board["turn_player"] == 0
    assert state["legal"]["roll"] and not state["legal"]["moves"]
    assert board["dice"] is None
    assert state["debug_info"] is None and "solution" not in state
    assert "rng" not in str(board).lower()


def test_board_roll_movement_and_invalid_actions(client):
    csrf = token(client)
    initial = post(client, csrf, "/api/game", {
        "game_type": "board", "players": 4, "seed": 42, "progress": "step",
    }).get_json()
    rejected = post(client, csrf, "/api/action", {
        "action": "move", "destination": {"kind": "hallway", "x": 7, "y": 25},
    })
    assert rejected.status_code == 409
    assert client.get("/api/state").get_json()["board"] == initial["board"]
    rolled = post(client, csrf, "/api/action", {"action": "roll"})
    assert rolled.status_code == 200
    state = rolled.get_json()
    assert len(state["board"]["dice"]) == 2
    assert state["board"]["remaining"] == sum(state["board"]["dice"])
    destination = state["legal"]["moves"][0]
    moved = post(client, csrf, "/api/action", {"action": "move", "destination": destination})
    assert moved.status_code == 200
    assert moved.get_json()["board"]["suspects"][0]["location"] == destination
    assert moved.get_json()["board"]["remaining"] == state["board"]["remaining"] - 1
    assert moved.get_json()["events"][0]["kind"] == "move"


def test_room_entry_fixed_suggestion_and_accusation_choices(client, monkeypatch):
    def board_game(players, seed, policy_name):
        state = deal_board(random.Random(seed), players)
        turn = state.board
        board = turn.board
        tokens = tuple(
            SuspectToken(item.suspect_id, Square(3, 6)) if item.suspect_id == 0 else item
            for item in board.suspects
        )
        state.board = replace(turn, board=replace(board, suspects=tokens))
        return Engine(state, dice_rng=random.Random(1)), tuple(
            make_policy(policy_name, random.Random(seat)) for seat in range(players)
        )

    monkeypatch.setattr("clue_engine.webapp.create_board_game", board_game)
    csrf = token(client)
    post(client, csrf, "/api/game", {
        "game_type": "board", "players": 3, "seed": 4, "policy": "deductive",
        "progress": "step",
    })
    post(client, csrf, "/api/action", {"action": "roll"})
    response = post(client, csrf, "/api/action", {
        "action": "move", "destination": {"kind": "room", "room_id": 12},
    })
    state = response.get_json()
    assert state["legal"]["suggest_room"] == 12
    assert state["legal"]["suggest"] and state["legal"]["accuse"]
    wrong = post(client, csrf, "/api/action", {
        "action": "suggest", "suspect_id": 0, "weapon_id": 6, "room_id": 13,
    })
    assert wrong.status_code == 409
    assert client.get("/api/state").get_json()["board"] == state["board"]
    valid = post(client, csrf, "/api/action", {
        "action": "suggest", "suspect_id": 1, "weapon_id": 6, "room_id": 12,
    })
    assert valid.status_code == 200
    assert valid.get_json()["board"]["suspects"][1]["location"] == {"kind": "room", "room_id": 12}


def test_malformed_board_actions_and_unknown_game_type_are_reported(client):
    csrf = token(client)
    bad_setup = post(client, csrf, "/api/game", {"game_type": "unknown"})
    assert bad_setup.status_code == 400
    post(client, csrf, "/api/game", {"game_type": "board", "players": 3})
    for destination in (None, {}, {"kind": "hallway", "x": True, "y": 1}, {"kind": "other"}):
        response = post(client, csrf, "/api/action", {"action": "move", "destination": destination})
        assert response.status_code == 400
        assert response.get_json()["error"]


def test_spectated_board_bots_complete_a_web_game(client):
    csrf = token(client)
    state = post(client, csrf, "/api/game", {
        "game_type": "board", "mode": "spectate", "players": 4, "seed": 21,
        "policies": "random,deductive,probing,strategic", "progress": "step", "max_steps": 1500,
    }).get_json()
    while not state["is_over"] and not state["limit_reached"]:
        response = post(client, csrf, "/api/advance", {"step": True})
        assert response.status_code == 200, response.get_json()
        state = response.get_json()
    assert state["is_over"] and state["winner"] is not None
    assert state["steps"] < 1500
    assert any(event["kind"] == "roll" for event in state["events"])
    assert all(event["kind"] != "show" for event in state["events"])
