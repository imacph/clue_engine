import random
import re
from dataclasses import replace

import pytest

from clue_engine.board_turn import BoardPhase
from clue_engine.engine import Engine
from clue_engine.models import Accuse, Combination, EndTurn, Pass, Reveal, Suggest
from clue_engine.observations import Event, EventKind
from clue_engine.state import GameState, deal_board
from clue_engine.webapp import create_app


class ScriptedPolicy:
    def __init__(self, *actions):
        self.actions = iter(actions)

    def choose(self, view, num_players, legal):
        action = next(self.actions)
        assert action in legal
        return action


def client_and_token():
    client = create_app().test_client()
    page = client.get("/")
    match = re.search(rb'name="csrf-token" content="([^"]+)"', page.data)
    assert match is not None
    return client, match.group(1).decode()


def post(client, token, path, body=None):
    return client.post(path, json=body or {}, headers={"X-CSRF-Token": token})


def card_engine(players=4):
    hands = [
        frozenset({1, 2, 3, 4, 5}),
        frozenset({7, 8, 9, 10, 11}),
        frozenset({13, 14, 15, 16}),
        frozenset({17, 18, 19, 20}),
    ]
    if players == 2:
        hands = [hands[0], frozenset().union(*hands[1:])]
    return Engine(GameState(Combination(0, 6, 12), hands[:players], 0))


@pytest.mark.parametrize("progress", ["auto", "turn", "step"])
def test_play_waits_after_bot_turn_but_not_between_responders(monkeypatch, progress):
    def create_scripted_game(num_players, seed, policy_name):
        return card_engine(), (
            ScriptedPolicy(),
            ScriptedPolicy(Suggest(Combination(0, 8, 13)), EndTurn()),
            ScriptedPolicy(Reveal(13)),
            ScriptedPolicy(),
        )

    monkeypatch.setattr("clue_engine.webapp.create_game", create_scripted_game)
    client, token = client_and_token()
    state = post(client, token, "/api/game", {
        "players": 4, "seat": 0, "progress": progress, "notebook_mode": "manual",
    }).get_json()
    assert state["waiting_for_turn"] is False
    state = post(client, token, "/api/action", {"action": "end_turn"}).get_json()
    assert state["to_move"] == 1 and state["waiting_for_turn"] is False
    step = {"step": progress == "step"}
    state = post(client, token, "/api/advance", step).get_json()
    assert state["to_move"] == 2 and state["waiting_for_turn"] is False
    state = post(client, token, "/api/advance", step).get_json()
    assert state["to_move"] == 1 and state["waiting_for_turn"] is False
    state = post(client, token, "/api/advance", step).get_json()
    assert state["to_move"] == 2 and state["waiting_for_turn"] is True
    assert state["activity"] == {
        "kind": "refute", "actor": 2, "suggestion_actor": 1, "cards": [0, 8, 13],
    }
    assert all(event["kind"] != "show" for event in state["events"])
    assert client.get("/api/state").get_json()["waiting_for_turn"] is True
    edit = client.put(
        "/api/notebook",
        json={"card_id": 8, "holder": 1, "mark": "+"},
        headers={"X-CSRF-Token": token},
    )
    assert edit.status_code == 200 and edit.get_json()["waiting_for_turn"] is True
    assert post(client, token, "/api/advance", step).status_code == 409
    assert post(client, token, "/api/action", {"action": "end_turn"}).status_code == 409
    assert client.post("/api/next-turn", json={}).status_code == 403
    assert post(client, token, "/api/next-turn?clause_actor=invalid").status_code == 400
    assert client.get("/api/state").get_json()["waiting_for_turn"] is True
    resumed = post(client, token, "/api/next-turn")
    assert resumed.status_code == 200
    assert resumed.get_json()["waiting_for_turn"] is False
    assert resumed.get_json()["steps"] == state["steps"]
    assert post(client, token, "/api/next-turn").status_code == 409


def test_human_can_respond_without_a_turn_confirmation(monkeypatch):
    def create_scripted_game(num_players, seed, policy_name):
        return card_engine(), (
            ScriptedPolicy(),
            ScriptedPolicy(Suggest(Combination(1, 6, 12)), EndTurn()),
            ScriptedPolicy(Pass()),
            ScriptedPolicy(Pass()),
        )

    monkeypatch.setattr("clue_engine.webapp.create_game", create_scripted_game)
    client, token = client_and_token()
    post(client, token, "/api/game", {"players": 4, "seat": 0})
    post(client, token, "/api/action", {"action": "end_turn"})
    for responder in (2, 3, 0):
        state = post(client, token, "/api/advance", {"step": False}).get_json()
        assert state["to_move"] == responder and state["waiting_for_turn"] is False
    assert state["legal"]["reveals"][0]["id"] == 1
    state = post(client, token, "/api/action", {"action": "reveal", "card_id": 1}).get_json()
    assert state["to_move"] == 1 and state["waiting_for_turn"] is False
    assert post(client, token, "/api/advance", {"step": False}).get_json()["waiting_for_turn"]


def test_bot_turn_waits_before_human_can_act(monkeypatch):
    monkeypatch.setattr("clue_engine.webapp.create_game", lambda *args: (
        card_engine(2), (ScriptedPolicy(), ScriptedPolicy(EndTurn())),
    ))
    client, token = client_and_token()
    post(client, token, "/api/game", {"players": 2, "seat": 0})
    post(client, token, "/api/action", {"action": "end_turn"})
    state = post(client, token, "/api/advance", {"step": False}).get_json()
    assert state["to_move"] == 0 and state["waiting_for_turn"] is True
    assert state["legal"]["suggest"] is False and state["legal"]["end_turn"] is False
    assert post(client, token, "/api/action", {"action": "end_turn"}).status_code == 409
    state = post(client, token, "/api/next-turn").get_json()
    assert state["legal"]["suggest"] is True and state["legal"]["end_turn"] is True


@pytest.mark.parametrize("accuser", [0, 1])
def test_incorrect_accusation_counts_as_a_completed_turn(monkeypatch, accuser):
    wrong = Combination(1, 7, 13)
    monkeypatch.setattr("clue_engine.webapp.create_game", lambda *args: (
        card_engine(2), (ScriptedPolicy(), ScriptedPolicy(Accuse(wrong))),
    ))
    client, token = client_and_token()
    post(client, token, "/api/game", {"players": 2, "seat": 0})
    if accuser == 0:
        state = post(client, token, "/api/action", {
            "action": "accuse", "suspect_id": 1, "weapon_id": 7,
            "room_id": 13, "confirmed": True,
        }).get_json()
        assert state["to_move"] == 1 and state["waiting_for_turn"] is False
    else:
        post(client, token, "/api/action", {"action": "end_turn"})
        state = post(client, token, "/api/advance", {"step": False}).get_json()
        assert state["to_move"] == 0 and state["waiting_for_turn"] is True
        assert state["activity"]["kind"] == "accuse"


@pytest.mark.parametrize(("progress", "step", "waiting"), [
    ("auto", False, False),
    ("turn", False, True),
    ("step", True, False),
])
def test_spectator_progress_modes(monkeypatch, progress, step, waiting):
    monkeypatch.setattr("clue_engine.webapp.create_game", lambda *args: (
        card_engine(2), (ScriptedPolicy(EndTurn()), ScriptedPolicy(EndTurn())),
    ))
    client, token = client_and_token()
    state = post(client, token, "/api/game", {
        "mode": "spectate", "players": 2, "progress": progress,
    }).get_json()
    assert state["auto_progress"] is (progress != "step")
    state = post(client, token, "/api/advance", {"step": step}).get_json()
    assert state["to_move"] == 1 and state["waiting_for_turn"] is waiting
    if waiting:
        assert post(client, token, "/api/advance", {"step": False}).status_code == 409
        state = post(client, token, "/api/next-turn").get_json()
        assert state["waiting_for_turn"] is False
    if step:
        state = post(client, token, "/api/pause").get_json()
        assert state["paused"] is False and state["auto_progress"] is True
    assert post(client, token, "/api/advance", {"step": False}).status_code == 200


def test_turn_confirmation_survives_pause_and_same_seat(monkeypatch):
    def create_scripted_game(num_players, seed, policy_name):
        engine = card_engine(2)
        engine.state.current_player = 1
        engine.log = (
            Event(EventKind.ACCUSE, 0, combo=Combination(1, 7, 13)),
            Event(EventKind.END_TURN, 0),
        )
        return engine, (ScriptedPolicy(), ScriptedPolicy(EndTurn(), EndTurn()))

    monkeypatch.setattr("clue_engine.webapp.create_game", create_scripted_game)
    client, token = client_and_token()
    post(client, token, "/api/game", {
        "mode": "spectate", "players": 2, "progress": "turn",
    })
    state = post(client, token, "/api/advance", {"step": False}).get_json()
    assert state["to_move"] == 1 and state["waiting_for_turn"] is True
    assert post(client, token, "/api/pause").get_json()["waiting_for_turn"] is True
    assert post(client, token, "/api/pause").get_json()["waiting_for_turn"] is True
    assert post(client, token, "/api/advance", {"step": False}).status_code == 409


def test_board_turn_confirmation(monkeypatch):
    def create_scripted_board(num_players, seed, policy_name, **kwargs):
        state = deal_board(random.Random(seed), num_players)
        state.board = replace(state.board, phase=BoardPhase.AFTER_SUGGESTION)
        return Engine(state, dice_rng=random.Random(seed)), (
            ScriptedPolicy(EndTurn()), ScriptedPolicy(), ScriptedPolicy(),
        )

    monkeypatch.setattr("clue_engine.webapp.create_board_game", create_scripted_board)
    client, token = client_and_token()
    post(client, token, "/api/game", {
        "game_type": "board", "mode": "spectate", "players": 3, "progress": "turn",
    })
    state = post(client, token, "/api/advance", {"step": False}).get_json()
    assert state["board"]["turn_player"] == 1 and state["waiting_for_turn"] is True


@pytest.mark.parametrize("ending", ["limit", "win"])
def test_terminal_state_does_not_wait_for_next_turn(monkeypatch, ending):
    action = EndTurn() if ending == "limit" else Accuse(Combination(0, 6, 12))
    monkeypatch.setattr("clue_engine.webapp.create_game", lambda *args: (
        card_engine(2), (ScriptedPolicy(action), ScriptedPolicy()),
    ))
    client, token = client_and_token()
    post(client, token, "/api/game", {
        "mode": "spectate", "players": 2, "progress": "turn", "max_steps": 1,
    })
    state = post(client, token, "/api/advance", {"step": False}).get_json()
    assert state["is_over"] or state["limit_reached"]
    assert state["waiting_for_turn"] is False
    assert post(client, token, "/api/next-turn").status_code == 409
