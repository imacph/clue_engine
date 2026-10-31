import hashlib
import json
from collections import deque
from dataclasses import FrozenInstanceError, replace

import pytest

from clue_engine.board import DEFAULT_BOARD, CharacterStart, Door, Square
from clue_engine.board_setup import BoardSetup
from clue_engine.board_state import (
    RoomPosition,
    SuspectToken,
    WeaponToken,
    create_board,
)
from clue_engine.cards import CARDS
from clue_engine.models import CardType


def connected(squares):
    remaining = set(squares)
    if not remaining:
        return False
    queue = deque([remaining.pop()])
    while queue:
        square = queue.popleft()
        for neighbor in (
            Square(square.x, square.y - 1),
            Square(square.x + 1, square.y),
            Square(square.x, square.y + 1),
            Square(square.x - 1, square.y),
        ):
            if neighbor in remaining:
                remaining.remove(neighbor)
                queue.append(neighbor)
    return not remaining


def test_full_board_partitions_the_grid_and_maps_every_room_card():
    board = DEFAULT_BOARD
    assert board.layout_id == "original-25x27-v1"
    assert (board.width, board.height) == (25, 27)
    assert {room.card_id for room in board.rooms} == {
        card.id for card in CARDS[CardType.ROOM]
    }

    occupied = set(board.hallways) | set(board.walls)
    assert not board.hallways & board.walls
    for room in board.rooms:
        assert room.squares
        assert not occupied.intersection(room.squares)
        occupied.update(room.squares)
        assert connected(room.squares)
    assert occupied == {
        Square(x, y) for y in range(board.height) for x in range(board.width)
    }
    assert connected(board.hallways)


def test_each_room_has_valid_doors_and_reachable_hallways():
    board = DEFAULT_BOARD
    assert len(board.doors) == len(set(board.doors)) == 20
    for room in board.rooms:
        doors = board.doors_for(room.card_id)
        assert doors
        for door in doors:
            assert door.room_square in room.squares
            assert door.hallway_square in board.hallways
            assert (
                abs(door.room_square.x - door.hallway_square.x)
                + abs(door.room_square.y - door.hallway_square.y)
            ) == 1
            assert board.hallway_neighbors(door.hallway_square)
    with pytest.raises(ValueError, match="room"):
        board.doors_for(0)
    with pytest.raises(ValueError, match="hallway"):
        board.hallway_neighbors(Square(0, 0))


def test_versioned_layout_matches_its_reference_topology():
    board = DEFAULT_BOARD

    def point(square):
        return square.x, square.y

    payload = {
        "size": [board.width, board.height],
        "rooms": [
            [room.card_id, sorted(map(point, room.squares))]
            for room in sorted(board.rooms, key=lambda room: room.card_id)
        ],
        "hallways": sorted(map(point, board.hallways)),
        "walls": sorted(map(point, board.walls)),
        "doors": sorted(
            (door.room_id, *point(door.room_square), *point(door.hallway_square))
            for door in board.doors
        ),
        "passages": sorted(sorted(pair) for pair in board.passages),
        "starts": sorted((start.suspect_id, *point(start.square)) for start in board.starts),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert digest == "f28d6640ee6d19f853a797beee26a9d638b2c1de0bde5bb5103578c6c0bdcb96"


def test_corner_room_passages_are_bidirectional():
    board = DEFAULT_BOARD
    assert {frozenset(pair) for pair in board.passages} == {
        frozenset((12, 20)),
        frozenset((14, 18)),
    }
    assert board.passage_from(12) == 20
    assert board.passage_from(20) == 12
    assert board.passage_from(14) == 18
    assert board.passage_from(18) == 14
    assert board.passage_from(13) is None
    with pytest.raises(ValueError, match="room"):
        board.passage_from(0)


@pytest.mark.parametrize("players", [3, 4, 5, 6])
def test_initial_board_places_all_tokens_and_assigns_active_characters(players):
    board = create_board(BoardSetup(players))
    starts = {start.suspect_id: start.square for start in DEFAULT_BOARD.starts}
    assert board.layout is DEFAULT_BOARD
    assert board.seat_suspects == tuple(range(players))
    assert board.first_player == 0
    assert {token.suspect_id: token.location for token in board.suspects} == starts
    assert {token.weapon_id for token in board.weapons} == {
        card.id for card in CARDS[CardType.WEAPON]
    }
    assert len({token.room_id for token in board.weapons}) == 6
    assert all(token.room_id in {room.card_id for room in DEFAULT_BOARD.rooms}
               for token in board.weapons)
    assert board.occupied_hallways() == frozenset(starts.values())
    assert board.blocked_doors() == ()


def test_custom_seats_and_weapon_rooms_remain_distinct_at_setup():
    board = create_board(
        BoardSetup(3),
        seat_suspects=(4, 0, 2),
        weapon_rooms=(20, 19, 18, 17, 16, 15),
    )
    assert board.seat_suspects == (4, 0, 2)
    assert board.first_player == 1
    assert tuple(token.room_id for token in board.weapons) == (20, 19, 18, 17, 16, 15)


@pytest.mark.parametrize("suspects", [(0, 1), (0, 1, 1), (1, 2, 3), (0, 1, 6)])
def test_setup_rejects_invalid_character_assignments(suspects):
    with pytest.raises(ValueError):
        create_board(BoardSetup(3), seat_suspects=suspects)


@pytest.mark.parametrize(
    "rooms",
    [(12, 13), (12, 13, 14, 15, 16, 16), (12, 13, 14, 15, 16, 0)],
)
def test_setup_rejects_invalid_weapon_rooms(rooms):
    with pytest.raises(ValueError):
        create_board(BoardSetup(3), weapon_rooms=rooms)


def test_unassigned_suspect_blocks_a_door_and_can_be_excluded():
    board = create_board(BoardSetup(3))
    door = DEFAULT_BOARD.doors_for(12)[0]
    assert 3 not in board.seat_suspects
    moved = tuple(
        replace(token, location=door.hallway_square) if token.suspect_id == 3 else token
        for token in board.suspects
    )
    blocked = replace(board, suspects=moved)
    assert door in blocked.blocked_doors()
    assert door not in blocked.blocked_doors(excluding_suspect_id=3)
    assert door.hallway_square not in board.occupied_hallways()
    with pytest.raises(ValueError, match="suspect"):
        blocked.occupied_hallways(excluding_suspect_id=999)


def test_room_occupancy_is_shared_but_hallway_occupancy_is_exclusive():
    board = create_board(BoardSetup(3))
    shared_room = tuple(
        replace(token, location=RoomPosition(12)) if token.suspect_id in (0, 1) else token
        for token in board.suspects
    )
    assert replace(board, suspects=shared_room).suspects == shared_room

    shared_square = tuple(
        replace(token, location=board.suspects[0].location) if token.suspect_id == 1 else token
        for token in board.suspects
    )
    with pytest.raises(ValueError, match="hallway"):
        replace(board, suspects=shared_square)

    shared_weapon_room = tuple(replace(token, room_id=12) for token in board.weapons)
    assert replace(board, weapons=shared_weapon_room).weapons == shared_weapon_room


def test_invalid_token_positions_and_missing_pieces_are_rejected():
    board = create_board(BoardSetup(3))
    for location in (Square(-1, 0), Square(0, 0), RoomPosition(0)):
        suspects = (replace(board.suspects[0], location=location), *board.suspects[1:])
        with pytest.raises(ValueError):
            replace(board, suspects=suspects)
    with pytest.raises(ValueError, match="suspect"):
        replace(board, suspects=board.suspects[:-1])
    with pytest.raises(ValueError, match="suspect"):
        replace(board, suspects=(board.suspects[0], board.suspects[0], *board.suspects[2:]))
    with pytest.raises(ValueError, match="weapon"):
        replace(board, weapons=board.weapons[:-1])
    with pytest.raises(ValueError, match="weapon"):
        replace(board, weapons=(board.weapons[0], board.weapons[0], *board.weapons[2:]))
    with pytest.raises(ValueError, match="room"):
        replace(board, weapons=(replace(board.weapons[0], room_id=0), *board.weapons[1:]))


def test_layout_rejects_invalid_partitions_doors_and_passages():
    board = DEFAULT_BOARD
    with pytest.raises(ValueError, match="layout ID"):
        replace(board, layout_id="")
    with pytest.raises(ValueError, match="partition"):
        replace(board, hallways=board.hallways - {next(iter(board.hallways))})
    barriers = frozenset({Square(6, 0), Square(8, 0), Square(7, 1)})
    with pytest.raises(ValueError, match="hallways"):
        replace(board, hallways=board.hallways - barriers, walls=board.walls | barriers)
    with pytest.raises(ValueError, match="door"):
        replace(board, doors=board.doors + (board.doors[0],))
    with pytest.raises(ValueError, match="door"):
        replace(board, doors=(replace(board.doors[0], hallway_square=Square(10, 10)), *board.doors[1:]))
    with pytest.raises(ValueError, match="door"):
        replace(board, doors=tuple(door for door in board.doors if door.room_id != 12))
    with pytest.raises(ValueError, match="passage"):
        replace(board, passages=((12, 20), (12, 18)))
    with pytest.raises(TypeError, match="passage"):
        replace(board, passages=((12.0, 20), (14, 18)))
    with pytest.raises(ValueError, match="start"):
        replace(board, starts=board.starts[:-1])
    with pytest.raises(ValueError, match="start"):
        replace(board, starts=(replace(board.starts[0], square=board.starts[1].square), *board.starts[1:]))


@pytest.mark.parametrize(
    "factory",
    [
        lambda: Square(True, 0),
        lambda: Door(12.0, Square(0, 0), Square(1, 0)),
        lambda: CharacterStart(True, Square(0, 0)),
        lambda: RoomPosition(12.0),
        lambda: SuspectToken(True, Square(0, 0)),
        lambda: WeaponToken(6, False),
    ],
)
def test_non_integer_coordinates_and_card_ids_are_rejected(factory):
    with pytest.raises(TypeError, match="integer"):
        factory()


def test_board_layout_and_state_are_immutable():
    board = create_board(BoardSetup(3))
    with pytest.raises(FrozenInstanceError):
        board.suspects = ()
    with pytest.raises(FrozenInstanceError):
        board.layout.width = 1
