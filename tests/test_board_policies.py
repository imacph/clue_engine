import random
from copy import deepcopy
from dataclasses import replace

import pytest

from clue_engine.board import Square
from clue_engine.board_record import read_board_record, write_board_record
from clue_engine.board_state import RoomPosition, SuspectToken
from clue_engine.board_turn import BoardPhase, Move, Roll, UsePassage
from clue_engine.game_settings import BotStrategy
from clue_engine.knowledge import Mark, knowledge_for
from clue_engine.models import Accuse, Combination, EndTurn, Reveal, Suggest
from clue_engine.observations import Event, EventKind
from clue_engine.policies import (
    CustomPolicy,
    DeductivePolicy,
    ProbingPolicy,
    RandomPolicy,
    StrategicPolicy,
)
from clue_engine.session import create_board_game
from clue_engine.simulation import play

POLICIES = (RandomPolicy, DeductivePolicy, ProbingPolicy, StrategicPolicy)
NAMES = ("random", "deductive", "probing", "strategic")


def place(engine, locations):
    turn = engine.state.board
    board = turn.board
    board = replace(
        board,
        suspects=tuple(
            SuspectToken(token.suspect_id, locations.get(token.suspect_id, token.location))
            for token in board.suspects
        ),
    )
    engine.state.board = replace(turn, board=board)


@pytest.mark.parametrize("policy_cls", POLICIES)
def test_board_policy_enters_an_adjacent_room_and_suggests(policy_cls):
    engine, _ = create_board_game(3, 10, "random")
    place(engine, {0: Square(3, 6)})
    engine.step(Roll())
    policy = policy_cls(random.Random(2))
    move = policy.choose(engine.view(0), 3, engine.legal_actions())
    assert move == Move(RoomPosition(12))
    engine.step(move)
    action = policy.choose(engine.view(0), 3, engine.legal_actions())
    assert isinstance(action, Suggest) and action.combination.room_id == 12
    assert action in engine.legal_actions()


def test_deductive_fixed_room_still_prefers_possible_suspects_and_weapons():
    engine, _ = create_board_game(3, 10, "deductive")
    place(engine, {0: Square(3, 6)})
    engine.step(Roll())
    engine.step(Move(RoomPosition(12)))
    view = replace(engine.view(0), own_hand=frozenset({1, 7, 12}), hand_sizes=None)
    knowledge = knowledge_for(view, 3)
    policy = DeductivePolicy(random.Random(1))
    for _ in range(20):
        action = policy.choose(view, 3, engine.legal_actions())
        assert isinstance(action, Suggest)
        assert action.combination.room_id == 12
        assert knowledge.mark_of(knowledge.envelope, action.combination.suspect_id) is not Mark.NOT_HELD
        assert knowledge.mark_of(knowledge.envelope, action.combination.weapon_id) is not Mark.NOT_HELD


def test_strategic_routing_reaches_a_useful_room_within_the_same_roll():
    engine, _ = create_board_game(3, 10, "random")
    place(engine, {0: Square(6, 3)})
    engine.state.board = replace(
        engine.state.board, phase=BoardPhase.MOVE, remaining=6, dice=(3, 3),
        visited=frozenset({Square(6, 3)}), starting_room=None,
    )
    view = replace(engine.view(0), own_hand=frozenset({1, 7, 12}), hand_sizes=None)
    assert Move(RoomPosition(12)) in engine.legal_actions()
    assert StrategicPolicy(random.Random(0)).choose(view, 3, engine.legal_actions()) == Move(Square(7, 3))
    custom = CustomPolicy(random.Random(0), BotStrategy(candidate_rooms=False))
    assert custom.choose(view, 3, engine.legal_actions()) == Move(RoomPosition(12))


def test_strategic_routing_can_decline_a_less_useful_passage():
    engine, _ = create_board_game(3, 10, "random")
    place(engine, {0: RoomPosition(12)})
    view = replace(engine.view(0), own_hand=frozenset({1, 7, 20}), hand_sizes=None)
    assert UsePassage() in engine.legal_actions()
    assert StrategicPolicy(random.Random(0)).choose(view, 3, engine.legal_actions()) == Roll()


def test_strategic_suggestion_avoids_helping_an_opponent_on_a_tie():
    engine, _ = create_board_game(3, 10, "random")
    place(engine, {0: RoomPosition(12), 1: RoomPosition(20)})
    engine.state.board = replace(engine.state.board, phase=BoardPhase.SUGGEST)
    view = replace(engine.view(0), own_hand=frozenset({4, 7, 13}), hand_sizes=None)
    own = Suggest(Combination(0, 6, 12))
    rival = Suggest(Combination(1, 6, 12))
    assert own in engine.legal_actions() and rival in engine.legal_actions()
    assert StrategicPolicy(random.Random(0)).choose(view, 3, (own, rival)) == own


@pytest.mark.parametrize("policy_cls", POLICIES)
def test_summoned_policy_prefers_suggesting_and_keeps_refutation_legal(policy_cls):
    engine, _ = create_board_game(3, 10, "random")
    place(engine, {0: RoomPosition(12)})
    engine.state.board = replace(engine.state.board, summoned_seats=frozenset({0}))
    policy = policy_cls(random.Random(2))
    assert Roll() in engine.legal_actions() and UsePassage() in engine.legal_actions()
    action = policy.choose(engine.view(0), 3, engine.legal_actions())
    assert isinstance(action, Suggest) and action in engine.legal_actions()
    engine.step(action)
    responder = engine.to_move
    response = policy.choose(engine.view(responder), 3, engine.legal_actions())
    assert response in engine.legal_actions()
    if any(isinstance(option, Reveal) for option in engine.legal_actions()):
        assert isinstance(response, Reveal)


@pytest.mark.parametrize("policy_cls", POLICIES)
def test_board_navigation_uses_only_public_view_and_avoids_occupied_square(policy_cls):
    engine, _ = create_board_game(3, 10, "random")
    place(engine, {0: Square(7, 25), 3: Square(7, 24)})
    engine.step(Roll())
    view = engine.view(0)
    legal = engine.legal_actions()
    assert Move(Square(7, 24)) not in legal
    first = policy_cls(random.Random(7)).choose(view, 3, legal)
    second = policy_cls(random.Random(7)).choose(view, 3, legal)
    assert first == second and isinstance(first, Move) and first in legal
    assert view.board.phase is BoardPhase.MOVE
    assert not hasattr(view, "solution") and not hasattr(view, "player_hands")


@pytest.mark.parametrize("policy_cls", POLICIES)
def test_policy_does_not_repeat_recent_room_by_passage(policy_cls):
    engine, _ = create_board_game(3, 10, "random")
    place(engine, {0: RoomPosition(20)})
    view = replace(engine.view(0), events=(Event(
        EventKind.SUGGEST, 0, combo=Combination(1, 6, 12),
    ),))
    assert UsePassage() in engine.legal_actions()
    assert policy_cls(random.Random(2)).choose(view, 3, engine.legal_actions()) == Roll()


@pytest.mark.parametrize("policy_cls", POLICIES)
def test_policy_uses_passage_to_escape_blocked_room_even_if_recent(policy_cls):
    engine, _ = create_board_game(3, 10, "random")
    place(engine, {0: RoomPosition(12), 3: Square(3, 6), 4: Square(6, 3)})
    view = replace(engine.view(0), events=(Event(
        EventKind.SUGGEST, 0, combo=Combination(1, 6, 20),
    ),))
    assert policy_cls(random.Random(2)).choose(
        view, 3, engine.legal_actions()
    ) == UsePassage()


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("players", [3, 4, 5, 6])
@pytest.mark.parametrize("seed", [100, 200, 300])
def test_board_bot_profiles_finish_seeded_games_without_stalling(name, players, seed):
    engine, policies = create_board_game(players, seed + players, name)
    finished = play(engine, policies, max_steps=1500)
    assert finished.is_over and finished.winner is not None
    assert any(event.kind.name == "ROLL" for event in finished.log)
    assert any(event.kind.name == "SUGGEST" for event in finished.log)
    assert len(finished.history) <= 1500


def test_seeded_mixed_board_game_is_reproducible(tmp_path):
    results = []
    for _ in range(2):
        engine, policies = create_board_game(4, 21, "random,deductive,probing,strategic")
        initial = deepcopy(engine.state)
        play(engine, policies, max_steps=1500)
        results.append((engine.log, engine.state.board, engine.winner))
    assert results[0] == results[1]
    path = tmp_path / "completed-private-board-game.json"
    write_board_record(path, initial, engine.history)
    replayed = read_board_record(path)
    assert replayed.log == engine.log
    assert replayed.state.board == engine.state.board
    assert replayed.winner == engine.winner


def test_board_policies_do_not_accuse_early_or_end_before_movement():
    engine, policies = create_board_game(4, 17, "deductive")
    action = policies[0].choose(engine.view(0), 4, engine.legal_actions())
    assert action == Roll()
    engine.step(action)
    action = policies[0].choose(engine.view(0), 4, engine.legal_actions())
    assert not isinstance(action, (Accuse, EndTurn))
    assert isinstance(action, Move)
