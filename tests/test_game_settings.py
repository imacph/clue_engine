import json
import random
from copy import deepcopy
from dataclasses import replace

import pytest

from clue_engine.board import Square
from clue_engine.board_record import read_board_record, write_board_record
from clue_engine.board_state import RoomPosition, SuspectToken
from clue_engine.board_turn import Move, Roll, UsePassage
from clue_engine.engine import Engine
from clue_engine.game_settings import BoardRules
from clue_engine.models import Combination, EndTurn, Suggest
from clue_engine.observations import EventKind
from clue_engine.state import deal_board


def positioned_game(rules):
    state = deal_board(random.Random(4), 3, board_rules=rules)
    turn = state.board
    tokens = tuple(
        SuspectToken(token.suspect_id, Square(3, 6) if token.suspect_id == 0 else token.location)
        for token in turn.board.suspects
    )
    state.board = replace(turn, board=replace(turn.board, suspects=tokens))
    return Engine(state, dice_rng=random.Random(1))


def test_suggestion_relocation_can_be_disabled_and_recorded(tmp_path):
    rules = BoardRules(move_suspect=False, move_weapon=False, summoned_suggestion=False)
    engine = positioned_game(rules)
    initial = deepcopy(engine.state)
    before = engine.state.board.board
    engine.step(Roll())
    engine.step(Move(RoomPosition(12)))
    events = engine.step(Suggest(Combination(1, 8, 12)))
    assert [event.kind for event in events] == [EventKind.SUGGEST]
    assert engine.state.board.board.suspects[1].location == before.suspects[1].location
    assert engine.state.board.board.weapons == before.weapons
    path = tmp_path / "custom.json"
    write_board_record(path, initial, engine.history)
    assert json.loads(path.read_text())["version"] == 2
    assert read_board_record(path).state == engine.state


def test_version_one_board_record_uses_standard_rules(tmp_path):
    engine = positioned_game(BoardRules())
    initial = deepcopy(engine.state)
    engine.step(Roll())
    engine.step(Move(RoomPosition(12)))
    engine.step(Suggest(Combination(1, 8, 12)))
    path = tmp_path / "version-one.json"
    write_board_record(path, initial, engine.history)
    payload = json.loads(path.read_text())
    payload["version"] = 1
    del payload["initial_state"]["board_rules"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert read_board_record(path).state == engine.state


@pytest.mark.parametrize(
    ("move_suspect", "move_weapon", "summoned_suggestion"),
    [(True, True, True), (True, False, False), (False, True, False), (False, False, False)],
)
def test_suggestion_relocation_rule_combinations(move_suspect, move_weapon, summoned_suggestion):
    engine = positioned_game(BoardRules(
        move_suspect=move_suspect,
        move_weapon=move_weapon,
        summoned_suggestion=summoned_suggestion,
    ))
    engine.step(Roll())
    engine.step(Move(RoomPosition(12)))
    events = engine.step(Suggest(Combination(1, 8, 12)))
    kinds = {event.kind for event in events}
    assert (EventKind.SUSPECT_MOVED in kinds) is move_suspect
    assert (EventKind.WEAPON_MOVED in kinds) is move_weapon
    assert (1 in engine.state.board.summoned_seats) is summoned_suggestion


def test_summoned_suggestion_can_be_disabled():
    engine = positioned_game(BoardRules(summoned_suggestion=False))
    engine.step(Roll())
    engine.step(Move(RoomPosition(12)))
    engine.step(Suggest(Combination(1, 8, 12)))
    while engine.to_move != 0:
        engine.step(engine.legal_actions()[0])
    engine.step(EndTurn())
    assert engine.state.board.board.suspects[1].location == RoomPosition(12)
    assert not any(isinstance(action, Suggest) for action in engine.legal_actions())


def test_passages_can_be_disabled():
    engine = positioned_game(BoardRules(secret_passages=False))
    turn = engine.state.board
    tokens = tuple(
        SuspectToken(token.suspect_id, RoomPosition(12) if token.suspect_id == 0 else token.location)
        for token in turn.board.suspects
    )
    engine.state.board = replace(turn, board=replace(turn.board, suspects=tokens))
    assert UsePassage() not in engine.legal_actions()
    assert Roll() in engine.legal_actions()


def test_invalid_rules_are_rejected():
    with pytest.raises(ValueError):
        BoardRules(move_suspect=False)
    with pytest.raises(TypeError):
        BoardRules(move_weapon=1)
    rng = random.Random(42)
    before = rng.getstate()
    with pytest.raises(TypeError):
        deal_board(rng, 3, board_rules=None)
    assert rng.getstate() == before
