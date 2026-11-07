"""Public board-turn state and incremental movement actions."""

from dataclasses import dataclass
from enum import Enum, auto

from .actions import ACCUSES, ENDTURNS, SUGGESTIONS
from .board import Square
from .board_state import BoardState, RoomPosition
from .cards import CARDS
from .game_settings import DEFAULT_BOARD_RULES, BoardRules
from .models import Action, CardType, Suggest


class BoardPhase(Enum):
    START = auto()
    MOVE = auto()
    SUGGEST = auto()
    AFTER_SUGGESTION = auto()


@dataclass(frozen=True, slots=True)
class Roll(Action):
    pass


@dataclass(frozen=True, slots=True)
class Move(Action):
    destination: Square | RoomPosition


@dataclass(frozen=True, slots=True)
class UsePassage(Action):
    pass


@dataclass(frozen=True, slots=True)
class BoardTurn:
    board: BoardState
    phase: BoardPhase = BoardPhase.START
    dice: tuple[int, int] | None = None
    remaining: int = 0
    visited: frozenset[Square] = frozenset()
    starting_room: int | None = None
    summoned_seats: frozenset[int] = frozenset()


_ROOM_SUGGESTIONS = {
    room_id: tuple(
        action for action in SUGGESTIONS
        if isinstance(action, Suggest) and action.combination.room_id == room_id
    )
    for room_id in (card.id for card in CARDS[CardType.ROOM])
}


def suspect_location(board: BoardState, suspect_id: int) -> Square | RoomPosition:
    return next(token.location for token in board.suspects if token.suspect_id == suspect_id)


def movement_actions(
    turn: BoardTurn, player: int, rules: BoardRules = DEFAULT_BOARD_RULES,
) -> tuple[Move, ...]:
    board = turn.board
    suspect_id = board.seat_suspects[player]
    location = suspect_location(board, suspect_id)
    if turn.remaining <= 0:
        return ()
    occupied = board.occupied_hallways(excluding_suspect_id=suspect_id)
    visited = frozenset() if rules.revisit_hallways else turn.visited
    if isinstance(location, RoomPosition):
        return tuple(
            Move(door.hallway_square) for door in board.layout.doors_for(location.room_id)
            if door.hallway_square not in occupied and door.hallway_square not in visited
        )
    neighbors = tuple(
        Move(square) for square in board.layout.hallway_neighbors(location)
        if square not in occupied and square not in visited
    )
    rooms = tuple(
        Move(RoomPosition(door.room_id)) for door in board.layout.doors
        if door.hallway_square == location and door.room_id != turn.starting_room
    )
    return neighbors + rooms


def legal_board_actions(
    turn: BoardTurn, player: int, rules: BoardRules = DEFAULT_BOARD_RULES,
) -> tuple[Action, ...]:
    location = suspect_location(turn.board, turn.board.seat_suspects[player])
    accusations = ACCUSES if not rules.accuse_in_room or isinstance(location, RoomPosition) else ()
    if turn.phase is BoardPhase.START:
        actions: tuple[Action, ...] = (Roll(),)
        if isinstance(location, RoomPosition):
            if rules.secret_passages and turn.board.layout.passage_from(location.room_id) is not None:
                actions += (UsePassage(),)
            if rules.stay_to_suggest or (
                rules.summoned_suggestion and player in turn.summoned_seats
            ):
                actions += _ROOM_SUGGESTIONS[location.room_id]
        return actions + accusations
    if turn.phase is BoardPhase.MOVE:
        moves = movement_actions(turn, player, rules)
        end = ENDTURNS if rules.early_end or turn.remaining == 0 or not moves else ()
        return moves + accusations + end
    if turn.phase is BoardPhase.SUGGEST:
        if not isinstance(location, RoomPosition):
            raise ValueError("suggestion phase requires a room")
        return _ROOM_SUGGESTIONS[location.room_id] + accusations + (
            ENDTURNS if rules.optional_suggestion else ()
        )
    if turn.phase is BoardPhase.AFTER_SUGGESTION:
        return accusations + ENDTURNS
    raise ValueError(f"unknown board phase: {turn.phase!r}")
