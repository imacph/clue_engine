import json
import random
from dataclasses import replace

import pytest

from clue_engine.board import DEFAULT_BOARD, Square
from clue_engine.board_record import read_board_record, write_board_record
from clue_engine.board_state import RoomPosition, SuspectToken
from clue_engine.board_turn import BoardPhase, Move, Roll, UsePassage
from clue_engine.engine import Engine, IllegalActionError, replay_board
from clue_engine.models import Accuse, Combination, EndTurn, Pass, Reveal, Suggest
from clue_engine.observations import EventKind
from clue_engine.presentation import format_event
from clue_engine.session import GameSession, create_board_game
from clue_engine.state import deal, deal_board


class FixedDice:
    def __init__(self, *values):
        self.values = iter(values)
        self.calls = 0

    def randint(self, a: int, b: int) -> int:
        assert (a, b) == (1, 6)
        self.calls += 1
        return next(self.values)


def make_engine(*, positions=None, dice=(1, 1), seats=None):
    state = deal_board(random.Random(4), 3, seat_suspects=seats)
    if positions:
        turn = state.board
        assert turn is not None
        board = turn.board
        tokens = tuple(
            SuspectToken(token.suspect_id, positions.get(token.suspect_id, token.location))
            for token in board.suspects
        )
        state.board = replace(turn, board=replace(board, suspects=tokens))
    roller = FixedDice(*dice)
    return Engine(state, dice_rng=roller), roller


def respond(engine):
    owner = engine.state.current_player
    while engine.to_move != owner:
        engine.step(engine.legal_actions()[0])


@pytest.mark.parametrize("players", [0, 1, 2, 7, 8])
def test_board_player_limits_preserve_card_only_support(players):
    with pytest.raises(ValueError):
        deal_board(random.Random(0), players)
    if players >= 2:
        assert len(deal(random.Random(0), players).player_hands) == players


def test_scarlet_starts_even_when_assigned_a_later_seat():
    engine, _ = make_engine(seats=(2, 0, 1))
    assert engine.to_move == 1
    assert Roll() in engine.legal_actions()
    assert not any(isinstance(action, Suggest) for action in engine.legal_actions())


def test_roll_uses_private_rng_and_invalid_actions_do_not_consume_it():
    engine, roller = make_engine()
    before = engine.state.board
    with pytest.raises(IllegalActionError):
        engine.step(Move(Square(7, 25)))
    assert roller.calls == 0
    assert engine.state.board == before and not engine.log
    events = engine.step(Roll())
    assert roller.calls == 2
    assert events[0].kind is EventKind.ROLL and events[0].dice == (1, 1)
    assert engine.view(0).board is not None
    assert not hasattr(engine.view(0).board, "dice_rng")
    after_roll = engine.state.board
    with pytest.raises(IllegalActionError):
        engine.step(Move(Square(8, 25)))
    assert roller.calls == 2 and engine.state.board == after_roll


def test_seeded_board_game_reproduces_rolls_independently_of_bot_rng():
    first, policies = create_board_game(3, 42, "random")
    second, _ = create_board_game(3, 42, "strategic")
    for _ in range(10):
        policies[0].choose(first.view(0), 3, first.legal_actions())
    assert first.state.solution == second.state.solution
    assert first.state.player_hands == second.state.player_hands
    assert first.step(Roll()) == second.step(Roll())


def test_roll_allows_early_stop_and_disallows_revisits():
    engine, _ = make_engine()
    engine.step(Roll())
    assert EndTurn() in engine.legal_actions()
    assert Move(Square(8, 25)) not in engine.legal_actions()
    engine.step(Move(Square(7, 25)))
    assert Move(Square(7, 26)) not in engine.legal_actions()
    engine.step(Move(Square(7, 24)))
    assert EndTurn() in engine.legal_actions()
    assert Move(Square(7, 23)) not in engine.legal_actions()
    engine.step(EndTurn())
    assert engine.to_move == 1
    assert engine.state.board.phase is BoardPhase.START


def test_unassigned_tokens_block_hallways_and_trapped_players_can_end():
    center = next(
        square for square in sorted(DEFAULT_BOARD.hallways)
        if len(DEFAULT_BOARD.hallway_neighbors(square)) == 4
        and square not in {door.hallway_square for door in DEFAULT_BOARD.doors}
    )
    neighbors = DEFAULT_BOARD.hallway_neighbors(center)
    engine, _ = make_engine(positions=dict(enumerate((center, *neighbors))))
    engine.step(Roll())
    assert all(Move(square) not in engine.legal_actions() for square in neighbors)
    assert EndTurn() in engine.legal_actions()


def test_door_entry_consumes_a_step_and_ends_movement_in_fixed_room():
    engine, _ = make_engine(positions={0: Square(3, 6)})
    engine.step(Roll())
    engine.step(Move(RoomPosition(12)))
    board = engine.state.board
    assert board is not None and board.phase is BoardPhase.SUGGEST
    legal = engine.legal_actions()
    suggestions = [action for action in legal if isinstance(action, Suggest)]
    assert len(suggestions) == 36
    assert all(action.combination.room_id == 12 for action in suggestions)
    assert EndTurn() not in legal
    assert not any(isinstance(action, Move) for action in legal)
    with pytest.raises(IllegalActionError):
        engine.step(Suggest(Combination(0, 6, 13)))


def test_cannot_enter_room_after_using_last_step():
    engine, _ = make_engine(positions={0: Square(3, 8)})
    engine.step(Roll())
    engine.step(Move(Square(3, 7)))
    engine.step(Move(Square(3, 6)))
    assert Move(RoomPosition(12)) not in engine.legal_actions()
    assert EndTurn() in engine.legal_actions()


def test_room_exit_blocks_same_turn_reentry_and_occupied_doors():
    engine, _ = make_engine(positions={0: RoomPosition(12), 3: Square(6, 3)})
    engine.step(Roll())
    assert Move(Square(6, 3)) not in engine.legal_actions()
    engine.step(Move(Square(3, 6)))
    assert Move(RoomPosition(12)) not in engine.legal_actions()
    engine.step(Move(Square(3, 7)))
    assert EndTurn() in engine.legal_actions()


def test_blocked_room_can_end_but_passage_remains_available():
    engine, _ = make_engine(
        positions={0: RoomPosition(12), 3: Square(3, 6), 4: Square(6, 3)}
    )
    assert UsePassage() in engine.legal_actions()
    engine.step(Roll())
    assert EndTurn() in engine.legal_actions()
    assert not any(isinstance(action, Move) for action in engine.legal_actions())
    engine.step(EndTurn())
    assert engine.to_move == 1


def test_passage_is_start_only_and_requires_destination_room_suggestion():
    engine, roller = make_engine(positions={0: RoomPosition(12)})
    events = engine.step(UsePassage())
    assert roller.calls == 0 and events[0].kind is EventKind.PASSAGE
    assert engine.state.board.board.suspects[0].location == RoomPosition(20)
    assert Suggest(Combination(0, 6, 20)) in engine.legal_actions()
    assert Suggest(Combination(0, 6, 12)) not in engine.legal_actions()
    assert Roll() not in engine.legal_actions()


def test_suggestion_relocates_tokens_and_summoned_player_can_suggest():
    engine, _ = make_engine(positions={0: Square(3, 6)})
    engine.step(Roll())
    engine.step(Move(RoomPosition(12)))
    events = engine.step(Suggest(Combination(1, 8, 12)))
    assert [event.kind for event in events] == [
        EventKind.SUGGEST, EventKind.SUSPECT_MOVED, EventKind.WEAPON_MOVED
    ]
    board = engine.state.board.board
    assert board.suspects[1].location == RoomPosition(12)
    assert next(token for token in board.weapons if token.weapon_id == 8).room_id == 12
    respond(engine)
    engine.step(EndTurn())
    assert engine.to_move == 1
    assert Suggest(Combination(2, 7, 12)) in engine.legal_actions()
    assert Roll() in engine.legal_actions()
    engine.step(Suggest(Combination(2, 7, 12)))
    respond(engine)
    assert Roll() not in engine.legal_actions()


def test_naming_a_token_already_in_room_does_not_summon_it():
    engine, _ = make_engine(positions={0: Square(3, 6), 1: RoomPosition(12)})
    engine.step(Roll())
    engine.step(Move(RoomPosition(12)))
    events = engine.step(Suggest(Combination(1, 6, 12)))
    assert EventKind.SUSPECT_MOVED not in [event.kind for event in events]
    respond(engine)
    engine.step(EndTurn())
    assert not any(isinstance(action, Suggest) for action in engine.legal_actions())


def test_summoned_player_who_rolls_cannot_suggest_without_entering_another_room():
    engine, _ = make_engine(positions={0: Square(3, 6)}, dice=(1, 1, 1, 1))
    engine.step(Roll())
    engine.step(Move(RoomPosition(12)))
    engine.step(Suggest(Combination(1, 8, 12)))
    respond(engine)
    engine.step(EndTurn())
    engine.step(Roll())
    assert not any(isinstance(action, Suggest) for action in engine.legal_actions())
    assert 1 not in engine.state.board.summoned_seats


def test_unrefuted_suggestion_cannot_be_repeated_without_a_new_room_entry():
    engine, _ = make_engine()
    room_id = engine.state.solution.room_id
    turn = engine.state.board
    tokens = tuple(
        SuspectToken(token.suspect_id, RoomPosition(room_id))
        if token.suspect_id == 0 else token for token in turn.board.suspects
    )
    engine.state.board = replace(
        turn, board=replace(turn.board, suspects=tokens), summoned_seats=frozenset({0}),
    )
    engine.step(Suggest(engine.state.solution))
    engine.step(Pass())
    engine.step(Pass())
    assert engine.to_move == 0
    assert not any(isinstance(action, Suggest) for action in engine.legal_actions())
    engine.step(EndTurn())
    wrong = Combination(0, 6, 12)
    if wrong == engine.state.solution:
        wrong = Combination(1, 6, 12)
    engine.step(Accuse(wrong))
    engine.step(Accuse(wrong))
    assert engine.to_move == 0
    assert Roll() in engine.legal_actions()
    assert not any(isinstance(action, Suggest) for action in engine.legal_actions())


def test_suggesting_own_card_and_accusing_after_refutation_are_legal():
    engine, _ = make_engine(positions={0: Square(3, 6)})
    engine.step(Roll())
    engine.step(Move(RoomPosition(12)))
    assert 0 in engine.state.player_hands[0]
    engine.step(Suggest(Combination(0, 6, 12)))
    respond(engine)
    assert Accuse(engine.state.solution) in engine.legal_actions()
    engine.step(Accuse(engine.state.solution))
    assert engine.is_over and engine.winner == 0


def test_wrong_accusation_on_a_door_moves_pawn_without_breaking_refutation():
    engine, _ = make_engine(positions={0: Square(3, 6), 1: RoomPosition(13)})
    engine.state.board = replace(engine.state.board, summoned_seats=frozenset({1}))
    wrong = Combination(0, 6, 12)
    if wrong == engine.state.solution:
        wrong = Combination(1, 6, 12)
    events = engine.step(Accuse(wrong))
    assert [event.kind for event in events] == [
        EventKind.ACCUSE, EventKind.END_TURN, EventKind.SUSPECT_MOVED
    ]
    assert engine.state.board.board.suspects[0].location == RoomPosition(12)
    assert engine.to_move == 1
    relocated = engine.step(Suggest(Combination(0, 6, 13)))
    assert any(event.kind is EventKind.SUSPECT_MOVED for event in relocated)
    assert engine.state.board.board.suspects[0].location == RoomPosition(13)
    assert 0 not in engine.state.board.summoned_seats
    assert engine.to_move == 2
    engine.step(Pass())
    assert engine.to_move == 0
    assert any(isinstance(action, Reveal) for action in engine.legal_actions())
    assert Pass() not in engine.legal_actions()


def test_board_accusations_reveal_only_a_correct_solution_and_all_eliminated_ends():
    engine, _ = make_engine()
    solution = engine.state.solution
    engine.step(Accuse(solution))
    assert engine.is_over and engine.winner == 0
    assert all(engine.view(player).events[-1].combo == solution for player in range(3))

    engine, _ = make_engine()
    wrong = Combination(0, 6, 12)
    if wrong == engine.state.solution:
        wrong = Combination(1, 6, 12)
    for _ in range(3):
        engine.step(Accuse(wrong))
    assert engine.is_over and engine.winner is None
    assert all(event.combo != engine.state.solution for event in engine.view(0).events)


def test_public_views_hide_private_reveals_and_future_dice():
    engine, _ = make_engine(positions={0: RoomPosition(12)})
    engine.step(UsePassage())
    combo = next(
        action.combination for action in engine.legal_actions()
        if isinstance(action, Suggest) and (
            {action.combination.suspect_id, action.combination.weapon_id, 20}
            & engine.state.player_hands[1]
        )
    )
    engine.step(Suggest(combo))
    engine.step(engine.legal_actions()[0])
    assert any(event.kind is EventKind.SHOW for event in engine.view(0).events)
    assert not any(event.kind is EventKind.SHOW for event in engine.view(2).events)
    view = engine.view(2)
    assert not hasattr(view, "solution")
    assert not hasattr(view, "player_hands")
    assert not hasattr(view.board, "dice_rng")
    session = GameSession(engine, create_board_game(3, 4, "random")[1])
    snapshot = session.snapshot()
    assert snapshot.board == engine.state.board and snapshot.debug_info is None
    assert not any(event.kind is EventKind.SHOW for event in snapshot.events)
    assert all(format_event(event) for event in snapshot.events)


def test_replay_checks_recorded_rolls_actions_events_and_positions():
    engine, _ = make_engine(dice=(2, 3))
    initial = deal_board(random.Random(4), 3)
    engine.step(Roll())
    for square in (Square(7, 25), Square(7, 24), Square(7, 23), Square(8, 23)):
        engine.step(Move(square))
    engine.step(Move(RoomPosition(19)))
    engine.step(Suggest(Combination(2, 7, 19)))
    respond(engine)
    engine.step(EndTurn())
    replayed = replay_board(initial, engine.history)
    assert replayed.log == engine.log
    assert replayed.state.board == engine.state.board
    assert replayed.state.current_player == engine.state.current_player
    assert initial.current_player == 0 and initial.board.phase is BoardPhase.START
    modified = list(engine.history)
    modified[0] = replace(modified[0], events=())
    with pytest.raises(ValueError, match="roll|record"):
        replay_board(initial, tuple(modified))


def test_private_board_record_round_trip_and_tamper_detection(tmp_path):
    engine, _ = make_engine()
    initial = deal_board(random.Random(4), 3)
    engine.step(Roll())
    engine.step(Move(Square(7, 25)))
    engine.step(Move(Square(7, 24)))
    engine.step(EndTurn())
    path = tmp_path / "game.json"
    write_board_record(path, initial, engine.history)
    roller = FixedDice(4, 5)
    replayed = read_board_record(path, dice_rng=roller)
    assert roller.calls == 0
    assert replayed.log == engine.log
    assert replayed.state.board == engine.state.board
    assert replayed.state.solution == engine.state.solution
    assert replayed.step(Roll())[0].dice == (4, 5)
    with pytest.raises(FileExistsError):
        write_board_record(path, initial, engine.history)
    content = json.loads(path.read_text(encoding="utf-8"))
    content["history"][1]["events"][0]["location"]["x"] = 8
    path.write_text(json.dumps(content), encoding="utf-8")
    with pytest.raises(ValueError, match="record"):
        read_board_record(path)


def test_board_record_preserves_custom_layout_and_setup(tmp_path):
    layout = replace(DEFAULT_BOARD, layout_id="custom-board")
    initial = deal_board(
        random.Random(12), 3, layout=layout,
        seat_suspects=(2, 0, 1), weapon_rooms=(20, 19, 18, 17, 16, 15),
    )
    engine = Engine(initial, dice_rng=FixedDice(1, 2))
    engine.step(Roll())
    path = tmp_path / "custom.json"
    initial_again = deal_board(
        random.Random(12), 3, layout=layout,
        seat_suspects=(2, 0, 1), weapon_rooms=(20, 19, 18, 17, 16, 15),
    )
    write_board_record(path, initial_again, engine.history)
    replayed = read_board_record(path)
    assert replayed.state.board == engine.state.board
    assert replayed.log == engine.log
