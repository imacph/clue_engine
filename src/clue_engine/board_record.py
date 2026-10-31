"""Private, self-contained JSON records for verified board-game replay."""

import json
from collections.abc import Sequence
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path

from .board import BoardLayout, CharacterStart, Door, Room, Square
from .board_state import BoardState, RoomPosition, SuspectToken, WeaponToken
from .board_turn import BoardPhase, BoardTurn, Move, Roll, UsePassage
from .engine import ActionRecord, DiceRandom, Engine, replay_board
from .models import Accuse, Action, Combination, EndTurn, Pass, Reveal, Suggest
from .observations import Event, EventKind
from .state import GameState


def _json_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, frozenset):
        return sorted(value)
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError(f"cannot encode {type(value).__name__}")


def write_board_record(
    path: Path, initial_state: GameState, history: Sequence[ActionRecord],
) -> None:
    """Write a new private record, after verifying it can be replayed."""
    replay_board(initial_state, history)
    records: list[dict[str, object]] = []
    for record in history:
        action = record.action
        if not isinstance(action, (Accuse, Suggest, Reveal, Pass, EndTurn, Roll, Move, UsePassage)):
            raise TypeError(f"unsupported action: {action!r}")
        records.append({
            "actor": record.actor,
            "action": {"kind": type(action).__name__, "data": asdict(action)},
            "events": [asdict(event) for event in record.events],
        })
    payload = {
        "version": 1, "private": True, "initial_state": asdict(initial_state), "history": records,
    }
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, default=_json_value, separators=(",", ":"), ensure_ascii=True)
        stream.write("\n")


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("expected an object with string keys")
    return {key: item for key, item in value.items()}


def _array(value: object) -> list[object]:
    if not isinstance(value, list):
        raise TypeError("expected an array")
    return list(value)


def _int(value: object) -> int:
    if type(value) is not int:
        raise ValueError("expected an integer")
    return value


def _str(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("expected a string")
    return value


def _optional_int(value: object) -> int | None:
    return None if value is None else _int(value)


def _square(value: object) -> Square:
    data = _object(value)
    return Square(_int(data["x"]), _int(data["y"]))


def _location(value: object) -> Square | RoomPosition:
    data = _object(value)
    if "room_id" in data:
        return RoomPosition(_int(data["room_id"]))
    return _square(data)


def _combo(value: object) -> Combination:
    data = _object(value)
    return Combination(
        _int(data["suspect_id"]), _int(data["weapon_id"]), _int(data["room_id"]),
    )


def _dice(value: object) -> tuple[int, int]:
    values = _array(value)
    if len(values) != 2:
        raise ValueError("expected two dice")
    return _int(values[0]), _int(values[1])


def _layout(value: object) -> BoardLayout:
    data = _object(value)
    rooms = [_object(item) for item in _array(data["rooms"])]
    doors = [_object(item) for item in _array(data["doors"])]
    starts = [_object(item) for item in _array(data["starts"])]
    passages = [_array(item) for item in _array(data["passages"])]
    if any(len(pair) != 2 for pair in passages):
        raise ValueError("each passage must have two rooms")
    return BoardLayout(
        layout_id=_str(data["layout_id"]),
        width=_int(data["width"]),
        height=_int(data["height"]),
        rooms=tuple(
            Room(_int(room["card_id"]), frozenset(_square(s) for s in _array(room["squares"])))
            for room in rooms
        ),
        hallways=frozenset(_square(s) for s in _array(data["hallways"])),
        walls=frozenset(_square(s) for s in _array(data["walls"])),
        doors=tuple(
            Door(_int(door["room_id"]), _square(door["room_square"]), _square(door["hallway_square"]))
            for door in doors
        ),
        passages=tuple((_int(pair[0]), _int(pair[1])) for pair in passages),
        starts=tuple(
            CharacterStart(_int(start["suspect_id"]), _square(start["square"])) for start in starts
        ),
    )


def _initial_state(value: object) -> GameState:
    data = _object(value)
    turn = _object(data["board"])
    board_data = _object(turn["board"])
    board = BoardState(
        layout=_layout(board_data["layout"]),
        seat_suspects=tuple(_int(seat) for seat in _array(board_data["seat_suspects"])),
        suspects=tuple(
            SuspectToken(_int(token["suspect_id"]), _location(token["location"]))
            for token in (_object(item) for item in _array(board_data["suspects"]))
        ),
        weapons=tuple(
            WeaponToken(_int(token["weapon_id"]), _int(token["room_id"]))
            for token in (_object(item) for item in _array(board_data["weapons"]))
        ),
    )
    dice = None if turn["dice"] is None else _dice(turn["dice"])
    starting_room = _optional_int(turn["starting_room"])
    board_turn = BoardTurn(
        board=board,
        phase=BoardPhase[_str(turn["phase"])],
        dice=dice,
        remaining=_int(turn["remaining"]),
        visited=frozenset(_square(s) for s in _array(turn["visited"])),
        starting_room=starting_room,
        summoned_seats=frozenset(_int(seat) for seat in _array(turn["summoned_seats"])),
    )
    if (
        not 0 <= board_turn.remaining <= 12
        or not board_turn.visited <= board.layout.hallways
        or any(not 0 <= seat < len(board.seat_suspects) for seat in board_turn.summoned_seats)
        or (dice is not None and any(not 1 <= die <= 6 for die in dice))
        or (starting_room is not None and starting_room not in {room.card_id for room in board.layout.rooms})
    ):
        raise ValueError("invalid board turn")
    return GameState(
        solution=_combo(data["solution"]),
        player_hands=[frozenset(_int(card) for card in _array(hand)) for hand in _array(data["player_hands"])],
        current_player=_int(data["current_player"]),
        board=board_turn,
    )


def _action(value: object) -> Action:
    record = _object(value)
    kind = _str(record["kind"])
    data = _object(record["data"])
    match kind:
        case "Suggest":
            return Suggest(_combo(data["combination"]))
        case "Accuse":
            return Accuse(_combo(data["combination"]))
        case "Reveal":
            return Reveal(_int(data["card_id"]))
        case "Pass":
            return Pass()
        case "EndTurn":
            return EndTurn()
        case "Roll":
            return Roll()
        case "Move":
            return Move(_location(data["destination"]))
        case "UsePassage":
            return UsePassage()
        case _:
            raise ValueError(f"unknown action kind: {kind}")


def _event(value: object) -> Event:
    data = _object(value)
    return Event(
        kind=EventKind[_str(data["kind"])],
        actor=_int(data["actor"]),
        combo=None if data["combo"] is None else _combo(data["combo"]),
        card_id=_optional_int(data["card_id"]),
        private_to=_optional_int(data["private_to"]),
        dice=None if data["dice"] is None else _dice(data["dice"]),
        location=None if data["location"] is None else _location(data["location"]),
        suspect_id=_optional_int(data["suspect_id"]),
        weapon_id=_optional_int(data["weapon_id"]),
    )


def read_board_record(path: Path, *, dice_rng: DiceRandom | None = None) -> Engine:
    """Verify a private record; supply a dice RNG to continue an unfinished game."""
    try:
        with path.open(encoding="utf-8") as stream:
            payload = _object(json.load(stream))
        if payload["version"] != 1 or payload["private"] is not True:
            raise ValueError("unsupported board record")
        initial = _initial_state(payload["initial_state"])
        history = tuple(
            ActionRecord(
                actor=_int(record["actor"]),
                action=_action(record["action"]),
                events=tuple(_event(event) for event in _array(record["events"])),
            )
            for record in (_object(item) for item in _array(payload["history"]))
        )
        return replay_board(initial, history, dice_rng=dice_rng)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid board record: {exc}") from exc
