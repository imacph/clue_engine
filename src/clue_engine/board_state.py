"""Token positions and initial setup for a future board game."""

from collections.abc import Sequence
from dataclasses import dataclass

from .board import DEFAULT_BOARD, BoardLayout, Door, Square
from .board_setup import BoardSetup
from .cards import CARDS
from .models import CardType


@dataclass(frozen=True, slots=True)
class RoomPosition:
    room_id: int

    def __post_init__(self) -> None:
        if type(self.room_id) is not int:
            raise TypeError("room ID must be an integer")


@dataclass(frozen=True, slots=True)
class SuspectToken:
    suspect_id: int
    location: Square | RoomPosition

    def __post_init__(self) -> None:
        if type(self.suspect_id) is not int:
            raise TypeError("suspect ID must be an integer")
        if not isinstance(self.location, (Square, RoomPosition)):
            raise TypeError("suspect location must be a hallway square or room")


@dataclass(frozen=True, slots=True)
class WeaponToken:
    weapon_id: int
    room_id: int

    def __post_init__(self) -> None:
        if type(self.weapon_id) is not int or type(self.room_id) is not int:
            raise TypeError("weapon and room IDs must be integers")


@dataclass(frozen=True, slots=True)
class BoardState:
    layout: BoardLayout
    seat_suspects: tuple[int, ...]
    suspects: tuple[SuspectToken, ...]
    weapons: tuple[WeaponToken, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.layout, BoardLayout):
            raise TypeError("layout must be a board layout")
        if not isinstance(self.seat_suspects, tuple):
            raise TypeError("seat suspects must be a tuple")
        BoardSetup(len(self.seat_suspects))
        suspect_ids = {card.id for card in CARDS[CardType.SUSPECT]}
        if (
            any(type(suspect_id) is not int for suspect_id in self.seat_suspects)
            or len(set(self.seat_suspects)) != len(self.seat_suspects)
            or not set(self.seat_suspects) <= suspect_ids
            or 0 not in self.seat_suspects
        ):
            raise ValueError("seats must have distinct suspects including Miss Scarlet")
        if not isinstance(self.suspects, tuple) or not all(
            isinstance(token, SuspectToken) for token in self.suspects
        ):
            raise TypeError("suspects must be a tuple of suspect tokens")
        token_ids = [token.suspect_id for token in self.suspects]
        if (
            any(type(suspect_id) is not int for suspect_id in token_ids)
            or len(token_ids) != len(suspect_ids)
            or set(token_ids) != suspect_ids
        ):
            raise ValueError("board must contain each suspect token exactly once")
        room_ids = {room.card_id for room in self.layout.rooms}
        occupied: set[Square] = set()
        for token in self.suspects:
            if isinstance(token.location, Square):
                if token.location not in self.layout.hallways or token.location in occupied:
                    raise ValueError("suspect hallway locations must be valid and distinct")
                occupied.add(token.location)
            elif isinstance(token.location, RoomPosition):
                if type(token.location.room_id) is not int or token.location.room_id not in room_ids:
                    raise ValueError("suspect location must identify a room")
            else:
                raise TypeError("suspect location must be a hallway square or room")

        if not isinstance(self.weapons, tuple) or not all(
            isinstance(token, WeaponToken) for token in self.weapons
        ):
            raise TypeError("weapons must be a tuple of weapon tokens")
        weapon_ids = {card.id for card in CARDS[CardType.WEAPON]}
        token_ids = [token.weapon_id for token in self.weapons]
        if (
            any(type(weapon_id) is not int for weapon_id in token_ids)
            or len(token_ids) != len(weapon_ids)
            or set(token_ids) != weapon_ids
        ):
            raise ValueError("board must contain each weapon token exactly once")
        if any(type(token.room_id) is not int or token.room_id not in room_ids
               for token in self.weapons):
            raise ValueError("weapon location must identify a room")

    @property
    def first_player(self) -> int:
        return self.seat_suspects.index(0)

    def occupied_hallways(self, *, excluding_suspect_id: int | None = None) -> frozenset[Square]:
        if excluding_suspect_id is not None and (
            type(excluding_suspect_id) is not int
            or excluding_suspect_id not in {token.suspect_id for token in self.suspects}
        ):
            raise ValueError(f"invalid suspect ID: {excluding_suspect_id!r}")
        return frozenset(
            token.location for token in self.suspects
            if isinstance(token.location, Square) and token.suspect_id != excluding_suspect_id
        )

    def blocked_doors(self, *, excluding_suspect_id: int | None = None) -> tuple[Door, ...]:
        occupied = self.occupied_hallways(excluding_suspect_id=excluding_suspect_id)
        return tuple(door for door in self.layout.doors if door.hallway_square in occupied)


def create_board(
    setup: BoardSetup,
    *,
    layout: BoardLayout = DEFAULT_BOARD,
    seat_suspects: Sequence[int] | None = None,
    weapon_rooms: Sequence[int] | None = None,
) -> BoardState:
    """Create positions for all tokens without starting a playable game."""
    if not isinstance(setup, BoardSetup):
        raise TypeError("setup must be a BoardSetup")
    if not isinstance(layout, BoardLayout):
        raise TypeError("layout must be a board layout")
    suspects = tuple(card.id for card in CARDS[CardType.SUSPECT])
    seats = tuple(seat_suspects) if seat_suspects is not None else suspects[:setup.num_players]
    if len(seats) != setup.num_players:
        raise ValueError("seat assignments must match the player count")
    rooms = (
        tuple(weapon_rooms)
        if weapon_rooms is not None
        else tuple(card.id for card in CARDS[CardType.ROOM][:len(CARDS[CardType.WEAPON])])
    )
    valid_rooms = {room.card_id for room in layout.rooms}
    if (
        len(rooms) != len(CARDS[CardType.WEAPON])
        or any(type(room_id) is not int or room_id not in valid_rooms for room_id in rooms)
        or len(set(rooms)) != len(rooms)
    ):
        raise ValueError("initial weapons must occupy six distinct rooms")
    return BoardState(
        layout=layout,
        seat_suspects=seats,
        suspects=tuple(SuspectToken(start.suspect_id, start.square) for start in layout.starts),
        weapons=tuple(
            WeaponToken(card.id, room_id)
            for card, room_id in zip(CARDS[CardType.WEAPON], rooms, strict=True)
        ),
    )
