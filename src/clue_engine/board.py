"""Immutable board topology, independent of game rules and presentation."""

from dataclasses import dataclass

from .cards import CARDS
from .models import CardType


@dataclass(frozen=True, slots=True, order=True)
class Square:
    x: int
    y: int

    def __post_init__(self) -> None:
        if type(self.x) is not int or type(self.y) is not int:
            raise TypeError("square coordinates must be integers")


def _neighbors(square: Square) -> tuple[Square, ...]:
    return (
        Square(square.x, square.y - 1),
        Square(square.x + 1, square.y),
        Square(square.x, square.y + 1),
        Square(square.x - 1, square.y),
    )


def _connected(squares: frozenset[Square]) -> bool:
    if not squares:
        return False
    remaining = set(squares)
    pending = [remaining.pop()]
    while pending:
        for neighbor in _neighbors(pending.pop()):
            if neighbor in remaining:
                remaining.remove(neighbor)
                pending.append(neighbor)
    return not remaining


@dataclass(frozen=True, slots=True)
class Room:
    card_id: int
    squares: frozenset[Square]

    def __post_init__(self) -> None:
        if type(self.card_id) is not int:
            raise TypeError("room card ID must be an integer")
        if not isinstance(self.squares, frozenset) or not all(
            isinstance(square, Square) for square in self.squares
        ):
            raise TypeError("room squares must be a frozenset of squares")
        if not _connected(self.squares):
            raise ValueError("room squares must be nonempty and connected")


@dataclass(frozen=True, slots=True)
class Door:
    room_id: int
    room_square: Square
    hallway_square: Square

    def __post_init__(self) -> None:
        if type(self.room_id) is not int:
            raise TypeError("door room ID must be an integer")
        if not isinstance(self.room_square, Square) or not isinstance(self.hallway_square, Square):
            raise TypeError("door endpoints must be squares")


@dataclass(frozen=True, slots=True)
class CharacterStart:
    suspect_id: int
    square: Square

    def __post_init__(self) -> None:
        if type(self.suspect_id) is not int:
            raise TypeError("starting suspect ID must be an integer")
        if not isinstance(self.square, Square):
            raise TypeError("starting location must be a square")


@dataclass(frozen=True, slots=True)
class BoardLayout:
    layout_id: str
    width: int
    height: int
    rooms: tuple[Room, ...]
    hallways: frozenset[Square]
    walls: frozenset[Square]
    doors: tuple[Door, ...]
    passages: tuple[tuple[int, int], ...]
    starts: tuple[CharacterStart, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.layout_id, str):
            raise TypeError("board layout ID must be text")
        if not self.layout_id.strip():
            raise ValueError("board layout ID must be nonempty text")
        if type(self.width) is not int or type(self.height) is not int:
            raise TypeError("board dimensions must be integers")
        if self.width < 1 or self.height < 1:
            raise ValueError("board dimensions must be positive")
        if not isinstance(self.rooms, tuple) or not all(
            isinstance(room, Room) for room in self.rooms
        ):
            raise TypeError("rooms must be a tuple of rooms")
        if not isinstance(self.hallways, frozenset) or not isinstance(self.walls, frozenset):
            raise TypeError("hallways and walls must be frozensets")
        if not all(isinstance(square, Square) for square in self.hallways | self.walls):
            raise TypeError("hallways and walls must contain squares")
        room_ids = [room.card_id for room in self.rooms]
        expected_rooms = {card.id for card in CARDS[CardType.ROOM]}
        if len(room_ids) != len(expected_rooms) or set(room_ids) != expected_rooms:
            raise ValueError("board must contain each room card exactly once")

        grid = {Square(x, y) for y in range(self.height) for x in range(self.width)}
        occupied = set(self.hallways)
        if occupied & self.walls:
            raise ValueError("board squares must form a disjoint partition")
        occupied.update(self.walls)
        for room in self.rooms:
            if occupied.intersection(room.squares):
                raise ValueError("board squares must form a disjoint partition")
            occupied.update(room.squares)
        if occupied != grid:
            raise ValueError("board squares must form a complete partition")
        if not _connected(self.hallways):
            raise ValueError("hallways must be connected")

        if not isinstance(self.doors, tuple) or not all(
            isinstance(door, Door) for door in self.doors
        ):
            raise TypeError("doors must be a tuple of doors")
        if len(set(self.doors)) != len(self.doors):
            raise ValueError("duplicate door")
        rooms = {room.card_id: room for room in self.rooms}
        for door in self.doors:
            room = rooms.get(door.room_id)
            if (
                room is None
                or door.room_square not in room.squares
                or door.hallway_square not in self.hallways
                or door.hallway_square not in _neighbors(door.room_square)
            ):
                raise ValueError("door must connect a room square to an adjacent hallway")
        if {door.room_id for door in self.doors} != expected_rooms:
            raise ValueError("each room must have a door")

        corners = (
            Square(0, 0), Square(self.width - 1, 0),
            Square(0, self.height - 1), Square(self.width - 1, self.height - 1),
        )
        corner_rooms = [
            next((room.card_id for room in self.rooms if corner in room.squares), None)
            for corner in corners
        ]
        if None in corner_rooms or len(set(corner_rooms)) != 4:
            raise ValueError("four distinct rooms must occupy the board corners")
        if not isinstance(self.passages, tuple) or not all(
            isinstance(pair, tuple) and len(pair) == 2
            and all(type(room_id) is int for room_id in pair)
            for pair in self.passages
        ):
            raise TypeError("passages must be a tuple of integer room pairs")
        expected_passages = {
            frozenset((corner_rooms[0], corner_rooms[3])),
            frozenset((corner_rooms[1], corner_rooms[2])),
        }
        if len(self.passages) != 2 or {frozenset(pair) for pair in self.passages} != expected_passages:
            raise ValueError("passages must connect opposite corner rooms")

        if not isinstance(self.starts, tuple) or not all(
            isinstance(start, CharacterStart) for start in self.starts
        ):
            raise TypeError("starts must be a tuple of character starts")
        expected_suspects = {card.id for card in CARDS[CardType.SUSPECT]}
        start_ids = [start.suspect_id for start in self.starts]
        start_squares = [start.square for start in self.starts]
        if (
            len(start_ids) != len(expected_suspects)
            or set(start_ids) != expected_suspects
            or len(set(start_squares)) != len(start_squares)
            or not set(start_squares) <= self.hallways
        ):
            raise ValueError("each suspect needs a distinct hallway start")

    def doors_for(self, room_id: int) -> tuple[Door, ...]:
        self._require_room(room_id)
        return tuple(door for door in self.doors if door.room_id == room_id)

    def passage_from(self, room_id: int) -> int | None:
        self._require_room(room_id)
        for first, second in self.passages:
            if room_id == first:
                return second
            if room_id == second:
                return first
        return None

    def hallway_neighbors(self, square: Square) -> tuple[Square, ...]:
        if square not in self.hallways:
            raise ValueError("square is not a hallway")
        return tuple(neighbor for neighbor in _neighbors(square) if neighbor in self.hallways)

    def _require_room(self, room_id: int) -> None:
        if type(room_id) is not int or room_id not in {room.card_id for room in self.rooms}:
            raise ValueError(f"invalid room ID: {room_id!r}")


_ROOM_SYMBOLS = {
    "K": 12, "B": 13, "C": 14, "D": 15, "I": 16,
    "L": 17, "G": 18, "H": 19, "S": 20,
}

_BOARD_ROWS = (
    *("KKKKKK...BBBBBBB...CCCCCC",) * 6,
    *(".........................",) * 2,
    *("...................IIIIII",) * 2,
    *("DDDDDD...#######...IIIIII",) * 2,
    *("DDDDDD...#######.........",) * 3,
    *("DDDDDD...#######...LLLLLL",) * 2,
    *("...................LLLLLL",) * 2,
    *(".........................",) * 2,
    *("GGGGGG...HHHHHHH...SSSSSS",) * 6,
)

_DOORS = (
    Door(12, Square(3, 5), Square(3, 6)),
    Door(12, Square(5, 3), Square(6, 3)),
    Door(13, Square(11, 5), Square(11, 6)),
    Door(13, Square(9, 3), Square(8, 3)),
    Door(13, Square(15, 3), Square(16, 3)),
    Door(14, Square(21, 5), Square(21, 6)),
    Door(14, Square(19, 3), Square(18, 3)),
    Door(15, Square(5, 12), Square(6, 12)),
    Door(15, Square(3, 16), Square(3, 17)),
    Door(16, Square(19, 9), Square(18, 9)),
    Door(16, Square(22, 11), Square(22, 12)),
    Door(17, Square(19, 16), Square(18, 16)),
    Door(17, Square(22, 18), Square(22, 19)),
    Door(18, Square(5, 23), Square(6, 23)),
    Door(18, Square(3, 21), Square(3, 20)),
    Door(19, Square(9, 23), Square(8, 23)),
    Door(19, Square(12, 21), Square(12, 20)),
    Door(19, Square(15, 23), Square(16, 23)),
    Door(20, Square(19, 23), Square(18, 23)),
    Door(20, Square(22, 21), Square(22, 20)),
)

_STARTS = (
    CharacterStart(0, Square(7, 26)),
    CharacterStart(1, Square(0, 18)),
    CharacterStart(2, Square(7, 0)),
    CharacterStart(3, Square(17, 0)),
    CharacterStart(4, Square(24, 13)),
    CharacterStart(5, Square(24, 19)),
)


def _make_default_board() -> BoardLayout:
    room_squares: dict[int, set[Square]] = {card.id: set() for card in CARDS[CardType.ROOM]}
    hallways: set[Square] = set()
    walls: set[Square] = set()
    for y, row in enumerate(_BOARD_ROWS):
        for x, symbol in enumerate(row):
            square = Square(x, y)
            if symbol == ".":
                hallways.add(square)
            elif symbol == "#":
                walls.add(square)
            elif symbol in _ROOM_SYMBOLS:
                room_squares[_ROOM_SYMBOLS[symbol]].add(square)
            else:
                raise ValueError(f"unknown board symbol: {symbol!r}")
    return BoardLayout(
        layout_id="original-25x27-v1",
        width=25,
        height=27,
        rooms=tuple(Room(card.id, frozenset(room_squares[card.id])) for card in CARDS[CardType.ROOM]),
        hallways=frozenset(hallways),
        walls=frozenset(walls),
        doors=_DOORS,
        passages=((12, 20), (14, 18)),
        starts=_STARTS,
    )


DEFAULT_BOARD = _make_default_board()
