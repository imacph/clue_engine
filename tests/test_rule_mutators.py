import random
from copy import deepcopy
from dataclasses import replace

import pytest

from clue_engine.board import DEFAULT_BOARD, Door, Square, randomize_board_layout
from clue_engine.board_record import read_board_record, write_board_record
from clue_engine.board_state import RoomPosition, SuspectToken
from clue_engine.board_turn import Roll, UsePassage
from clue_engine.engine import Engine, replay_history
from clue_engine.game_settings import BoardRules, GameRules
from clue_engine.knowledge import Mark, knowledge_for
from clue_engine.models import Combination, EndTurn, Pass, Reveal, Suggest
from clue_engine.observations import EventKind, public_events
from clue_engine.policies import ProbingPolicy, StrategicPolicy
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


@pytest.mark.parametrize("policy", [ProbingPolicy, StrategicPolicy])
@pytest.mark.parametrize("source", ["face_up", "public_show", "private_show"])
def test_bot_reveal_preference_uses_actual_event_visibility(policy, source):
    state = GameState(
        Combination(0, 6, 12),
        [
            frozenset({1, 2, 3, 4, 5}),
            frozenset({7, 8, 9, 10, 13}),
            frozenset({11, 14, 15, 16}),
            frozenset({17, 18, 19, 20}),
        ],
        0,
        game_rules=GameRules(
            face_up_card=source == "face_up",
            public_refutations=source == "public_show",
        ),
        public_cards=(1, 7, 11, 17) if source == "face_up" else (),
    )
    engine = Engine(state)
    engine.step(Suggest(Combination(0, 7, 13)))
    if source != "face_up":
        engine.step(Reveal(7))
        engine.step(EndTurn())
        engine.step(Suggest(Combination(0, 6, 12)))
        for _ in range(3):
            engine.step(Pass())
        engine.step(EndTurn())
        engine.step(Suggest(Combination(0, 7, 13)))
        engine.step(Pass())
        engine.step(Pass())
    assert engine.to_move == 1
    legal = engine.legal_actions()
    assert Reveal(7) in legal and Reveal(13) in legal
    result = policy(random.Random(0)).choose(engine.view(1), 4, legal)
    assert result == Reveal(13 if source == "private_show" else 7)


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


@pytest.mark.parametrize("count", range(5))
def test_randomized_passages_are_distinct_seeded_pairs(count):
    rules = BoardRules(randomize_passages=True, passage_count=count)
    first, _ = create_board_game(4, 42, "random", board_rules=rules)
    second, _ = create_board_game(4, 42, "random", board_rules=rules)
    normal, _ = create_board_game(4, 42, "random")
    layout = first.state.board.board.layout
    assert layout == second.state.board.board.layout
    assert len(layout.passages) == count
    rooms = [room for pair in layout.passages for room in pair]
    assert len(rooms) == len(set(rooms))
    for a, b in layout.passages:
        assert layout.passage_from(a) == b
        assert layout.passage_from(b) == a
    assert first.state.solution == normal.state.solution
    assert first.state.player_hands == normal.state.player_hands


@pytest.mark.parametrize("value", [-1, 5, True, 2.5])
def test_passage_count_rejects_invalid_values(value):
    with pytest.raises((TypeError, ValueError), match="passage_count"):
        BoardRules(passage_count=value)


def test_room_shuffle_remaps_doors_and_passages_without_moving_geometry():
    rules = BoardRules(randomize_rooms=True)
    engine, _ = create_board_game(4, 42, "random", board_rules=rules)
    same, _ = create_board_game(4, 42, "random", board_rules=rules)
    other, _ = create_board_game(4, 43, "random", board_rules=rules)
    layout = engine.state.board.board.layout
    assert layout == same.state.board.board.layout
    assert layout.rooms != DEFAULT_BOARD.rooms
    assert layout.rooms != other.state.board.board.layout.rooms
    mapping = {old.card_id: new.card_id for old, new in zip(DEFAULT_BOARD.rooms, layout.rooms, strict=True)}
    assert [room.squares for room in layout.rooms] == [room.squares for room in DEFAULT_BOARD.rooms]
    assert layout.doors == tuple(replace(door, room_id=mapping[door.room_id]) for door in DEFAULT_BOARD.doors)
    assert layout.passages == tuple((mapping[a], mapping[b]) for a, b in DEFAULT_BOARD.passages)
    assert layout.hallways == DEFAULT_BOARD.hallways
    assert layout.starts == DEFAULT_BOARD.starts


@pytest.mark.parametrize("seed", range(20))
def test_randomized_doors_preserve_each_location_count_and_valid_connections(seed):
    rules = BoardRules(randomize_rooms=True, randomize_doors=True)
    engine, _ = create_board_game(4, seed, "random", board_rules=rules)
    layout = engine.state.board.board.layout
    original_by_squares = {room.squares: room.card_id for room in DEFAULT_BOARD.rooms}
    for room in layout.rooms:
        doors = layout.doors_for(room.card_id)
        assert len(doors) == len(DEFAULT_BOARD.doors_for(original_by_squares[room.squares]))
        sides = {
            (door.hallway_square.x - door.room_square.x, door.hallway_square.y - door.room_square.y)
            for door in doors
        }
        assert len(sides) == len(doors)
        for door in doors:
            assert door.room_square in room.squares
            assert door.hallway_square in layout.hallways
            assert abs(door.room_square.x - door.hallway_square.x) + abs(
                door.room_square.y - door.hallway_square.y
            ) == 1
            dx = door.hallway_square.x - door.room_square.x
            dy = door.hallway_square.y - door.room_square.y
            for offset in (-1, 1):
                assert Square(door.room_square.x - offset * dy, door.room_square.y + offset * dx) in room.squares
                assert Square(
                    door.hallway_square.x - offset * dy, door.hallway_square.y + offset * dx
                ) in layout.hallways
    assert {(d.room_square, d.hallway_square) for d in layout.doors} != {
        (d.room_square, d.hallway_square) for d in DEFAULT_BOARD.doors
    }


def test_door_randomization_rejects_layouts_with_too_few_sides():
    room = DEFAULT_BOARD.rooms[0]
    original_doors = set(DEFAULT_BOARD.doors)
    extra = next(
        door for square in sorted(room.squares)
        for neighbor in (
            Square(square.x, square.y - 1), Square(square.x + 1, square.y),
            Square(square.x, square.y + 1), Square(square.x - 1, square.y),
        )
        if neighbor in DEFAULT_BOARD.hallways
        for door in (Door(room.card_id, square, neighbor),)
        if door not in original_doors
    )
    layout = replace(DEFAULT_BOARD, doors=(*DEFAULT_BOARD.doors, extra))
    with pytest.raises(ValueError, match="too few eligible sides"):
        randomize_board_layout(layout, random.Random(42), doors=True)


def test_randomized_passage_is_a_legal_move_to_its_generated_destination():
    rules = BoardRules(randomize_passages=True, passage_count=4)
    engine, _ = create_board_game(4, 42, "random", board_rules=rules)
    turn = engine.state.board
    source, destination = turn.board.layout.passages[0]
    suspect = turn.board.seat_suspects[engine.state.current_player]
    tokens = tuple(
        replace(token, location=RoomPosition(source)) if token.suspect_id == suspect else token
        for token in turn.board.suspects
    )
    engine.state.board = replace(turn, board=replace(turn.board, suspects=tokens))
    assert UsePassage() in engine.legal_actions()
    engine.step(UsePassage())
    pawn = next(token for token in engine.state.board.board.suspects if token.suspect_id == suspect)
    assert pawn.location == RoomPosition(destination)


def test_layout_randomizers_are_independent_for_the_same_seed():
    def layout(rules):
        engine, _ = create_board_game(4, 42, "random", board_rules=rules)
        return engine.state.board.board.layout

    doors_only = layout(BoardRules(randomize_doors=True))
    passages_only = layout(BoardRules(randomize_passages=True, passage_count=4))
    combined = layout(BoardRules(
        randomize_rooms=True, randomize_doors=True, randomize_passages=True, passage_count=4,
    ))
    assert {(door.room_square, door.hallway_square) for door in doors_only.doors} == {
        (door.room_square, door.hallway_square) for door in combined.doors
    }

    def passage_locations(board):
        by_id = {room.card_id: room.squares for room in board.rooms}
        return {frozenset((by_id[a], by_id[b])) for a, b in board.passages}

    assert passage_locations(passages_only) == passage_locations(combined)
    assert doors_only.rooms == DEFAULT_BOARD.rooms
    assert doors_only.passages == DEFAULT_BOARD.passages


def test_randomized_layout_round_trips_in_replays_and_private_board_records(tmp_path):
    rules = BoardRules(randomize_rooms=True, randomize_doors=True, randomize_passages=True, passage_count=4)
    engine, _ = create_board_game(4, 42, "random", board_rules=rules)
    initial = deepcopy(engine.state)
    engine.step(Roll())
    record = Replay(initial, engine.history, None, "automatic", ())
    restored = decode_replay(encode_replay(record))
    assert restored.initial.board.board.layout == initial.board.board.layout
    assert restored.initial.board_rules == rules
    assert replay_history(restored.initial, restored.history).log == engine.log
    path = tmp_path / "randomized-board.json"
    write_board_record(path, initial, engine.history)
    board_replay = read_board_record(path)
    assert board_replay.state.board.board.layout == initial.board.board.layout
    assert board_replay.log == engine.log


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
