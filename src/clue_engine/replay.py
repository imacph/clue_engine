"""Private, verified records for postgame replay."""

import json
from dataclasses import asdict, dataclass

from .board_record import (
    _action,
    _array,
    _combo,
    _event,
    _initial_state,
    _int,
    _json_value,
    _object,
)
from .cards import CARDS_BY_ID
from .engine import ActionRecord, replay_history
from .game_settings import GameRules
from .models import CardType
from .state import GameState


@dataclass(frozen=True)
class Replay:
    initial: GameState
    history: tuple[ActionRecord, ...]
    human: int | None
    notebook_mode: str
    notes: tuple[dict, ...]


def encode_replay(replay: Replay) -> dict:
    replay_history(replay.initial, replay.history)
    payload = {
        "version": 1,
        "private": True,
        "kind": "clue-replay",
        "initial_state": asdict(replay.initial),
        "history": [
            {
                "actor": record.actor,
                "action": {"kind": type(record.action).__name__, "data": asdict(record.action)},
                "events": [asdict(event) for event in record.events],
            }
            for record in replay.history
        ],
        "human": replay.human,
        "notebook_mode": replay.notebook_mode,
        "notes": replay.notes,
    }
    return json.loads(json.dumps(payload, default=_json_value))


def decode_replay(payload: object) -> Replay:
    try:
        data = _object(payload)
        legacy = data.get("kind") != "clue-replay"
        version = _int(data["version"])
        if data.get("private") is not True:
            raise ValueError("record must be private")
        if (legacy and version not in (1, 2, 3)) or (not legacy and version != 1):
            raise ValueError("unsupported replay version")
        raw_initial = _object(data["initial_state"])
        if raw_initial.get("board") is not None:
            initial = _initial_state(raw_initial, version if legacy else 3)
        else:
            if legacy:
                raise ValueError("legacy records require a board")
            initial = GameState(
                solution=_combo(raw_initial["solution"]),
                player_hands=[
                    frozenset(_int(card) for card in _array(hand))
                    for hand in _array(raw_initial["player_hands"])
                ],
                current_player=_int(raw_initial["current_player"]),
                game_rules=GameRules(**_object(raw_initial.get("game_rules", {}))),
            )
        solution = (initial.solution.suspect_id, initial.solution.weapon_id, initial.solution.room_id)
        if any(card not in CARDS_BY_ID for card in solution) or tuple(
            CARDS_BY_ID[card].type for card in solution
        ) != (CardType.SUSPECT, CardType.WEAPON, CardType.ROOM):
            raise ValueError("invalid solution")
        all_cards = list(solution) + [card for hand in initial.player_hands for card in hand]
        if len(all_cards) != len(CARDS_BY_ID) or set(all_cards) != set(CARDS_BY_ID):
            raise ValueError("hands and solution must partition the deck")
        history = tuple(
            ActionRecord(
                actor=_int(record["actor"]),
                action=_action(record["action"]),
                events=tuple(_event(event) for event in _array(record["events"])),
            )
            for record in (_object(item) for item in _array(data["history"]))
        )
        replay_history(initial, history)
        human = None if legacy or data["human"] is None else _int(data["human"])
        if human is not None and not 0 <= human < len(initial.player_hands):
            raise ValueError("invalid human seat")
        notebook_mode = "automatic" if legacy else data["notebook_mode"]
        if notebook_mode not in ("manual", "automatic") or (
            notebook_mode == "manual" and human is None
        ):
            raise ValueError("invalid notebook mode")
        notes = () if legacy else tuple(_object(note) for note in _array(data["notes"]))
        if notes and notebook_mode != "manual":
            raise ValueError("automatic notebooks cannot contain manual notes")
        previous_step = -1
        for note in notes:
            step = _int(note["step"])
            if human is None or not previous_step <= step <= len(history):
                raise ValueError("invalid notebook timeline")
            previous_step = step
            kind = note["kind"]
            if kind == "mark":
                holder, card = _int(note["holder"]), _int(note["card"])
                if (
                    not 0 <= holder <= len(initial.player_hands)
                    or holder == human or card not in CARDS_BY_ID
                    or card in initial.player_hands[human] or note["mark"] not in ("?", "+", "-")
                ):
                    raise ValueError("invalid notebook mark")
            elif kind == "clause":
                if not isinstance(note.get("clauses"), list):
                    raise ValueError("invalid notebook clauses")
            else:
                raise ValueError("invalid notebook event")
        return Replay(initial, history, human, notebook_mode, notes)
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise ValueError(f"invalid replay record: {exc}") from exc
