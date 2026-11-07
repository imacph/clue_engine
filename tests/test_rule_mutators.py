from copy import deepcopy
from dataclasses import replace

import pytest

from clue_engine.board_record import read_board_record, write_board_record
from clue_engine.board_state import RoomPosition, SuspectToken
from clue_engine.engine import Engine, replay_history
from clue_engine.game_settings import BoardRules, GameRules
from clue_engine.knowledge import Mark, knowledge_for
from clue_engine.models import Combination, EndTurn, Pass, Reveal, Suggest
from clue_engine.observations import EventKind, public_events
from clue_engine.replay import Replay, decode_replay, encode_replay
from clue_engine.session import GameSession, create_board_game, create_game
from clue_engine.state import GameState


def scripted_game(*, public=False, all_refute=True, reverse=False):
    state = GameState(
        Combination(0, 6, 12),
        [
            frozenset({1, 2, 3, 4, 5}),
            frozenset({7, 8, 9, 10, 11}),
            frozenset({13, 14, 15, 16}),
            frozenset({17, 18, 19, 20}),
        ],
        0,
        game_rules=GameRules(
            public_refutations=public, all_refute=all_refute, reverse_refutation=reverse,
        ),
    )
    return Engine(state)


@pytest.mark.parametrize("public", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_all_players_respond_and_reveal_visibility(public, reverse):
    engine = scripted_game(public=public, reverse=reverse)
    initial = deepcopy(engine.state)
    engine.step(Suggest(Combination(0, 7, 13)))
    if reverse:
        assert engine.to_move == 3
        engine.step(Pass())
        assert engine.to_move == 2
        engine.step(Reveal(13))
        assert engine.to_move == 1
        engine.step(Reveal(7))
    else:
        assert engine.to_move == 1
        engine.step(Reveal(7))
        assert engine.to_move == 2
        engine.step(Reveal(13))
        assert engine.to_move == 3
        engine.step(Pass())
    assert engine.to_move == 0
    assert EndTurn() in engine.legal_actions()
    assert len([event for event in engine.view(0).events if event.kind is EventKind.SHOW]) == 2
    shows_for_player3 = [event for event in engine.view(3).events if event.kind is EventKind.SHOW]
    assert len(shows_for_player3) == (2 if public else 0)
    assert len([event for event in public_events(engine.log) if event.kind is EventKind.SHOW]) == (
        2 if public else 0
    )
    if public:
        knowledge = knowledge_for(engine.view(3), 4)
        assert knowledge.mark_of(1, 7) is Mark.HELD
        assert knowledge.mark_of(2, 13) is Mark.HELD
    replayed = replay_history(initial, engine.history)
    assert replayed.log == engine.log


def test_first_refutation_still_ends_response_without_all_refute():
    engine = scripted_game(all_refute=False)
    engine.step(Suggest(Combination(0, 7, 13)))
    engine.step(Reveal(7))
    assert engine.to_move == 0


@pytest.mark.parametrize("board", [False, True])
def test_face_up_cards_are_public_reproducible_and_in_initial_replay(board):
    factory = create_board_game if board else create_game
    engine, _ = factory(3, 42, "random", game_rules=GameRules(face_up_card=True))
    same, _ = factory(3, 42, "random", game_rules=GameRules(face_up_card=True))
    standard, _ = factory(3, 42, "random")
    assert engine.state.player_hands == standard.state.player_hands
    assert engine.state.solution == standard.state.solution
    assert engine.state.public_cards == same.state.public_cards
    assert [event.kind for event in engine.log] == [EventKind.EXPOSE] * 3
    for seat, card in enumerate(engine.state.public_cards):
        assert card in engine.state.player_hands[seat]
        assert knowledge_for(engine.view((seat + 1) % 3), 3).mark_of(seat, card) is Mark.HELD
    record = Replay(deepcopy(engine.state), (), None, "automatic", ())
    restored = decode_replay(encode_replay(record))
    assert replay_history(restored.initial, restored.history).log == engine.log


def test_stay_to_suggest_is_available_without_summoning():
    engine, _ = create_board_game(3, 5, "random", board_rules=BoardRules(stay_to_suggest=True))
    turn = engine.state.board
    seat = engine.state.current_player
    suspect = turn.board.seat_suspects[seat]
    tokens = tuple(
        SuspectToken(token.suspect_id, RoomPosition(12) if token.suspect_id == suspect else token.location)
        for token in turn.board.suspects
    )
    engine.state.board = replace(turn, board=replace(turn.board, suspects=tokens))
    assert any(isinstance(action, Suggest) and action.combination.room_id == 12
               for action in engine.legal_actions())


def test_layered_mutators_run_with_bots():
    engine, policies = create_board_game(
        3, 42, "strategic",
        board_rules=BoardRules(stay_to_suggest=True),
        game_rules=GameRules(public_refutations=True, all_refute=True, face_up_card=True),
    )
    session = GameSession(engine, policies, max_steps=150)
    while not session.snapshot().is_over and not session.snapshot().limit_reached:
        session.advance_bot()
    assert session.snapshot().steps > 0


@pytest.mark.parametrize("board", [False, True])
def test_public_refutation_replay_round_trip_after_actions(board, tmp_path):
    rules = GameRules(public_refutations=True, all_refute=True, face_up_card=True)
    if board:
        engine, _ = create_board_game(
            3, 42, "random", game_rules=rules, board_rules=BoardRules(stay_to_suggest=True),
        )
        turn = engine.state.board
        suspect = turn.board.seat_suspects[engine.state.current_player]
        tokens = tuple(
            SuspectToken(token.suspect_id, RoomPosition(12) if token.suspect_id == suspect else token.location)
            for token in turn.board.suspects
        )
        engine.state.board = replace(turn, board=replace(turn.board, suspects=tokens))
    else:
        engine, _ = create_game(3, 42, "random", game_rules=rules)
    initial = deepcopy(engine.state)
    next_seat = (engine.state.current_player + 1) % engine.num_players
    suggestion = next(
        action for action in engine.legal_actions()
        if isinstance(action, Suggest) and {
            action.combination.suspect_id, action.combination.weapon_id, action.combination.room_id,
        } & engine.state.player_hands[next_seat]
    )
    engine.step(suggestion)
    engine.step(next(action for action in engine.legal_actions() if isinstance(action, Reveal)))
    record = Replay(initial, engine.history, None, "automatic", ())
    restored = decode_replay(encode_replay(record))
    assert replay_history(restored.initial, restored.history).log == engine.log
    if board:
        path = tmp_path / "public-board.json"
        write_board_record(path, initial, engine.history)
        assert read_board_record(path).log == engine.log


def test_face_up_cards_reject_empty_hands():
    with pytest.raises(ValueError, match="at least one card per player"):
        create_game(19, 42, "random", game_rules=GameRules(face_up_card=True))
