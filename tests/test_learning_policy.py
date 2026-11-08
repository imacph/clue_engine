import random
from dataclasses import replace

import pytest

from clue_engine.board_state import RoomPosition
from clue_engine.board_turn import Move, Roll, UsePassage, legal_board_actions
from clue_engine.knowledge import knowledge_for
from clue_engine.learning_policy import LearningPolicy, LinearModel, suggestion_features
from clue_engine.models import Accuse, Combination, Reveal
from clue_engine.observations import Event, EventKind, view_for
from clue_engine.session import create_board_game, create_game


def test_model_validates_dimensions_and_finite_values():
    with pytest.raises(ValueError):
        LinearModel((0.0,), (0.0,))
    with pytest.raises(ValueError):
        LinearModel((float("nan"),) * 8, (0.0,) * 8)


def test_policy_rejects_card_only_games():
    engine, _ = create_game(4, 1, "random")
    policy = LearningPolicy(random.Random(1), LinearModel.zeros())
    with pytest.raises(ValueError, match="board"):
        policy.choose(engine.view(engine.to_move), 4, engine.legal_actions())


def test_suggestions_use_only_legal_actions_and_player_visible_features():
    engine, _ = create_board_game(4, 2, "random")
    player = engine.to_move
    view = engine.view(player)
    knowledge = knowledge_for(view, 4)
    from clue_engine.actions import SUGGESTIONS

    choices = tuple(action for action in SUGGESTIONS if action.combination.room_id == 12)[:3]
    policy = LearningPolicy(random.Random(3), LinearModel.zeros())
    picked = policy._board_suggestion(view, knowledge, choices)
    assert picked in choices
    assert len(suggestion_features(view, knowledge, picked)) == 8


def test_room_goal_and_movement_are_legal_throughout_game():
    engine, opponents = create_board_game(4, 13, "random")
    learned = LearningPolicy(random.Random(4), LinearModel.zeros())
    policies = (learned, *opponents[1:])
    for _ in range(1200):
        player = engine.to_move
        if player is None:
            break
        legal = engine.legal_actions()
        action = policies[player].choose(engine.view(player), 4, legal)
        assert action in legal
        engine.step(action)
    assert engine.is_over


def test_nonlearned_actions_use_sound_rules():
    engine, _ = create_board_game(4, 4, "random")
    player = engine.to_move
    policy = LearningPolicy(random.Random(2), LinearModel.zeros())
    view = engine.view(player)
    assert policy.choose(view, 4, (Reveal(next(iter(view.own_hand))),)) in (
        Reveal(next(iter(view.own_hand))),
    )
    assert not isinstance(policy.choose(view, 4, engine.legal_actions()), Accuse)


def test_known_solution_is_accused_by_deterministic_rules():
    engine, _ = create_board_game(4, 4, "random")
    solution = Combination(0, 6, 12)
    view = replace(
        engine.view(0), own_hand=frozenset({1, 2, 3, 4, 5}), hand_sizes=None,
        events=(
            Event(EventKind.SUGGEST, 0, combo=solution),
            Event(EventKind.PASS, 1),
            Event(EventKind.PASS, 2),
            Event(EventKind.PASS, 3),
        ),
    )
    policy = LearningPolicy(random.Random(2), LinearModel.zeros())
    assert policy.choose(view, 4, (Accuse(solution),)) == Accuse(solution)


def test_goal_router_moves_towards_selected_room():
    engine, _ = create_board_game(4, 7, "random")
    player = engine.to_move
    policy = LearningPolicy(random.Random(5), LinearModel.zeros())
    engine.step(Roll())
    view = engine.view(player)
    knowledge = knowledge_for(view, 4)
    moves = tuple(action for action in engine.legal_actions() if isinstance(action, Move))
    routes = policy._routes(view, moves)
    assert routes
    room = next(iter(routes))
    policy._goal = room
    chosen = policy._board_move(view, knowledge, moves)
    assert chosen in routes[room][1]


def test_room_features_do_not_depend_on_hidden_solution():
    engine, _ = create_board_game(4, 9, "random")
    view = engine.view(engine.to_move)
    policy = LearningPolicy(random.Random(1), LinearModel.zeros())
    first = policy._room_candidates(view, knowledge_for(view, 4), engine.legal_actions())
    assert first
    assert all(len(features) == 8 for _, features in first)
    assert all(isinstance(room, int) for room, _ in first)


def test_private_reveals_to_other_players_cannot_affect_decisions():
    engine, _ = create_board_game(4, 19, "random")
    player = engine.to_move
    view = engine.view(player)
    combo = Combination(0, 6, 12)
    shared = (Event(EventKind.SUGGEST, 1, combo=combo), Event(EventKind.REFUTE, 2))
    views = tuple(
        view_for(
            shared + (Event(EventKind.SHOW, 2, card_id=card, private_to=1),),
            player, view.own_hand, board=view.board,
        )
        for card in (0, 6)
    )
    assert views[0] == views[1]
    policies = [LearningPolicy(random.Random(7), LinearModel.zeros()) for _ in views]
    assert policies[0].choose(views[0], 4, engine.legal_actions()) == policies[1].choose(
        views[1], 4, engine.legal_actions()
    )


def test_room_goal_survives_an_ended_turn_when_still_viable():
    engine, _ = create_board_game(4, 21, "random")
    player = engine.to_move
    view = engine.view(player)
    policy = LearningPolicy(random.Random(8), LinearModel.zeros())
    policy.choose(view, 4, engine.legal_actions())
    goal = policy._goal
    assert goal is not None
    later = replace(view, events=(*view.events, Event(EventKind.END_TURN, player)))
    policy.choose(later, 4, engine.legal_actions())
    assert policy._goal == goal


def test_selected_passage_is_used_when_legal():
    engine, _ = create_board_game(4, 22, "random")
    player = engine.to_move
    view = engine.view(player)
    turn = view.board
    source, destination = turn.board.layout.passages[0]
    suspect = turn.board.seat_suspects[player]
    board = replace(
        turn.board,
        suspects=tuple(
            replace(token, location=RoomPosition(source)) if token.suspect_id == suspect else token
            for token in turn.board.suspects
        ),
    )
    view = replace(view, board=replace(turn, board=board))
    legal = legal_board_actions(view.board, player, view.board_rules)
    policy = LearningPolicy(random.Random(8), LinearModel.zeros())
    policy._goal = destination
    assert policy.choose(view, 4, legal) == UsePassage()
