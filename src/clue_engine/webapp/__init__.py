"""Flask application for the local browser interface."""

import hmac
import random
import secrets
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request
from flask import session as browser_session

from .._version import DESKTOP_VERSION, FRONTEND_VERSION, __version__
from ..batch import (
    BatchConfig,
    BatchSummary,
    GameResult,
    batch_config_from_setup,
    format_batch_settings,
    run_batch,
)
from ..board import DEFAULT_BOARD, Square
from ..board_setup import BoardSetup
from ..board_state import RoomPosition, create_board
from ..board_turn import BoardTurn, Move, Roll, UsePassage
from ..cards import CARDS, CARDS_BY_ID
from ..desktop_preferences import DesktopPreferences
from ..distributions import BOARD_METRICS, Distribution, DistributionBin, Distributions
from ..engine import Engine, IllegalActionError, replay_history
from ..game_settings import (
    BoardRules,
    GameRules,
    LearnedStrategy,
    bot_strategy_from_dict,
)
from ..knowledge import Knowledge, Mark, knowledge_for
from ..models import (
    Accuse,
    Action,
    Combination,
    EndTurn,
    Pass,
    Reveal,
    Suggest,
)
from ..observations import (
    Event,
    EventKind,
    PlayerView,
    is_incorrect_accusation,
    view_for,
)
from ..policies import POLICY_NAMES, make_policy, policies_for_players
from ..presentation import (
    format_clauses,
    format_event,
    notebook_activity,
    notebook_actor,
)
from ..replay import Replay, decode_replay, encode_replay, replay_from_batch_trace
from ..session import (
    DebugInfo,
    GameSession,
    completed_turns,
    create_board_game,
    create_game,
)
from .batch_charts import knowledge_charts, seat_comparison, seat_turns

_SESSION_TTL_SECONDS = 60 * 60
_MAX_ACTIVE_SESSIONS = 64
_MAX_ACTIVE_BATCH_RUNS = 1


@dataclass
class WebGame:
    game: GameSession
    mode: str
    auto_progress: bool
    paused: bool
    confirm_turns: bool
    selected_player: int
    waiting_for_turn: bool = False
    notebook_mode: str = "automatic"
    notebook_marks: dict[tuple[int, int], str] = field(default_factory=dict)
    notebook_clauses: dict[int, dict[str, Any]] = field(default_factory=dict)
    next_clause_id: int = 1
    notebook_revision: int = 0
    notebook_history: list[dict[str, Any]] = field(default_factory=list)
    abandoned: bool = False
    imported_replay: Replay | None = None
    replay_deduction_step: int = -1
    replay_deduction_events: tuple[Event, ...] = ()
    replay_deductions: list[dict[str, int]] = field(default_factory=list)
    replay_knowledge_summaries: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    last_access: float = field(default_factory=time.monotonic)
    lock: threading.RLock = field(default_factory=threading.RLock)


@dataclass
class WebBatch:
    owner: str
    game_type: str
    requested_games: int
    settings: dict[str, object]
    last_access: float = field(default_factory=time.monotonic)
    finished_games: int = 0
    status: str = "queued"
    cancel_requested: bool = False
    summary: BatchSummary | None = None
    error: str | None = None
    distributions: Distributions = field(default_factory=Distributions)
    observations: list[GameResult] = field(default_factory=list)
    trace_directory: tempfile.TemporaryDirectory[str] | None = None


def _seat_outcomes(
    results: list[GameResult], policy: str | None, seat: int | None,
) -> Distribution:
    counts = dict.fromkeys(("won", "not_won", "timeout", "error", "cancelled"), 0)
    for result in results:
        for index, name in enumerate(result.policies):
            if (policy is not None and policy != name) or (seat is not None and seat != index):
                continue
            outcome = (
                "won" if result.winner == index
                else "not_won" if result.outcome in {"won", "all_eliminated"}
                else result.outcome
            )
            counts[outcome] += 1
    samples = sum(counts.values())
    return Distribution(
        "Bot seat outcomes", "matching seat exposures", samples,
        "Each matching seat is counted once per game; unfinished games are shown separately.",
        tuple(
            DistributionBin(name, count, count / samples if samples else 0.0)
            for name, count in counts.items()
        ),
    )


def _matches_cohort(result: GameResult, policy: str | None, seat: int | None) -> bool:
    return any(
        (policy is None or policy == name) and (seat is None or seat == index)
        for index, name in enumerate(result.policies)
    )


def _automatic_clauses(view: PlayerView, knowledge: Knowledge) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    suggested: list[int] | None = None
    for index, event in enumerate(view.events):
        if event.kind is EventKind.SUGGEST:
            if event.combo is None:
                raise ValueError("SUGGEST event without a combination")
            suggested = sorted((event.combo.suspect_id, event.combo.weapon_id, event.combo.room_id))
        elif event.kind is EventKind.REFUTE:
            if suggested is None:
                raise ValueError("REFUTE before any SUGGEST")
            result.append({
                "id": len(result) + 1, "kind": "refute", "holder": event.actor,
                "actor": event.actor, "cards": suggested,
            })
        elif is_incorrect_accusation(view.events, index):
            if event.combo is None:
                raise ValueError("ACCUSE event without a combination")
            result.append({
                "id": len(result) + 1, "kind": "accuse", "holder": knowledge.envelope,
                "actor": event.actor,
                "cards": sorted((event.combo.suspect_id, event.combo.weapon_id, event.combo.room_id)),
            })
    for clause in result:
        target = Mark.HELD if clause["kind"] == "refute" else Mark.NOT_HELD
        satisfied = any(
            knowledge.mark_of(clause["holder"], card) is target for card in clause["cards"]
        )
        clause["status"] = "satisfied" if satisfied else "unresolved"
        clause["active_cards"] = [] if satisfied else [
            card for card in clause["cards"]
            if knowledge.mark_of(clause["holder"], card) is Mark.UNKNOWN
        ]
    return result


def _manual_clause(body: dict[str, Any], num_players: int) -> dict[str, Any]:
    required = {"kind", "holder", "cards", "resolved"}
    if not required <= set(body) or set(body) - required - {"excluded_cards"}:
        raise ValueError("Supply kind, holder, cards, resolved, and optionally excluded_cards.")
    kind = body["kind"]
    holder = _integer(body, "holder")
    cards = body["cards"]
    resolved = body["resolved"]
    excluded = body.get("excluded_cards", [])
    if kind not in ("refute", "accuse"):
        raise ValueError("Clause type must be refute or accuse.")
    if (kind == "refute" and not 0 <= holder < num_players) or (
        kind == "accuse" and holder != num_players
    ):
        raise ValueError("Clause holder must identify a player, or the envelope for an accusation.")
    if (
        not isinstance(cards, list) or len(cards) != len(CARDS)
        or any(type(card) is not int or card not in CARDS_BY_ID for card in cards)
        or len(set(cards)) != len(cards)
        or {CARDS_BY_ID[card].type for card in cards} != set(CARDS)
    ):
        raise ValueError("Choose exactly one suspect, one weapon, and one room.")
    if (
        not isinstance(excluded, list)
        or any(type(card) is not int or card not in cards for card in excluded)
        or len(set(excluded)) != len(excluded)
    ):
        raise ValueError("Excluded cards must be distinct cards from the clause.")
    if type(resolved) is not bool:
        raise ValueError("resolved must be a boolean.")
    return {
        "kind": kind, "holder": holder, "actor": holder if kind == "refute" else None,
        "cards": sorted(cards), "status": "resolved" if resolved else "unresolved",
        "excluded_cards": sorted(excluded),
        "active_cards": [] if resolved else sorted(card for card in cards if card not in excluded),
    }


def _card_options() -> dict[str, list[dict[str, Any]]]:
    return {
        card_type.name.lower(): [
            {"id": card.id, "name": card.name} for card in cards
        ]
        for card_type, cards in CARDS.items()
    }


def _json_body() -> dict[str, Any]:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise TypeError("Request body must be a JSON object.")
    return body


def _integer(body: dict[str, Any], key: str, default: int | None = None) -> int:
    value = body.get(key, default)
    if type(value) is not int:
        raise ValueError(f"{key} must be an integer.")
    return value


def _make_combination(body: dict[str, Any]) -> Combination:
    return Combination(
        _integer(body, "suspect_id"),
        _integer(body, "weapon_id"),
        _integer(body, "room_id"),
    )


def _game_from_request(
    games: dict[str, WebGame], games_lock: threading.Lock
) -> WebGame | None:
    game_id = browser_session.get("game_id")
    if not isinstance(game_id, str):
        return None
    now = time.monotonic()
    with games_lock:
        expired = [
            key for key, game in games.items()
            if now - game.last_access > _SESSION_TTL_SECONDS
        ]
        for key in expired:
            games.pop(key, None)
        game = games.get(game_id)
        if game is not None:
            game.last_access = now
        return game


def _event_payload(events: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [
        {
            "number": index + 1,
            "actor": events[index].actor,
            "kind": events[index].kind.name.lower(),
            "text": format_event(
                events[index],
                events[index - 1] if index else None,
            ),
        }
        for index in range(len(events) - 1, -1, -1)
    ]


def _activity_payload(events: tuple[Any, ...]) -> tuple[dict[str, Any] | None, int | None]:
    for index in range(len(events) - 1, -1, -1):
        event = events[index]
        if event.kind not in (
            EventKind.SUGGEST,
            EventKind.ACCUSE,
            EventKind.REFUTE,
            EventKind.SHOW,
        ):
            continue
        if event.kind in (EventKind.SUGGEST, EventKind.ACCUSE):
            if event.combo is None:
                raise ValueError(f"{event.kind.name} event without a combination")
            return {
                "kind": event.kind.name.lower(),
                "actor": event.actor,
                "cards": [
                    event.combo.suspect_id,
                    event.combo.weapon_id,
                    event.combo.room_id,
                ],
            }, index + 1

        suggestion = next(
            (item for item in reversed(events[:index]) if item.kind is EventKind.SUGGEST),
            None,
        )
        if suggestion is None or suggestion.combo is None:
            raise ValueError(f"{event.kind.name} event without a preceding suggestion")
        activity = {
            "kind": "reveal" if event.kind is EventKind.SHOW else "refute",
            "actor": event.actor,
            "suggestion_actor": suggestion.actor,
            "cards": [
                suggestion.combo.suspect_id,
                suggestion.combo.weapon_id,
                suggestion.combo.room_id,
            ],
        }
        if event.kind is EventKind.SHOW:
            if event.card_id is None or event.private_to is None:
                raise ValueError("SHOW event without a card or recipient")
            activity["card_id"] = event.card_id
            activity["recipient"] = event.private_to
            activity["public"] = event.public
        return activity, index + 1
    return None, None


def _square_payload(square: Square) -> dict[str, int]:
    return {"x": square.x, "y": square.y}


def _location_payload(location: Square | RoomPosition) -> dict[str, Any]:
    if isinstance(location, Square):
        return {"kind": "hallway", **_square_payload(location)}
    return {"kind": "room", "room_id": location.room_id}


def _board_payload(turn: BoardTurn, turn_player: int | None) -> dict[str, Any]:
    board = turn.board
    layout = board.layout
    return {
        "layout": {
            "id": layout.layout_id,
            "width": layout.width,
            "height": layout.height,
            "rooms": [
                {
                    "id": room.card_id,
                    "name": CARDS_BY_ID[room.card_id].name,
                    "squares": [_square_payload(square) for square in sorted(room.squares)],
                }
                for room in layout.rooms
            ],
            "hallways": [_square_payload(square) for square in sorted(layout.hallways)],
            "walls": [_square_payload(square) for square in sorted(layout.walls)],
            "doors": [
                {
                    "room_id": door.room_id,
                    "room_square": _square_payload(door.room_square),
                    "hallway_square": _square_payload(door.hallway_square),
                }
                for door in layout.doors
            ],
            "passages": [list(pair) for pair in layout.passages],
        },
        "suspects": [
            {
                "id": token.suspect_id,
                "name": CARDS_BY_ID[token.suspect_id].name,
                "seat": (
                    board.seat_suspects.index(token.suspect_id)
                    if token.suspect_id in board.seat_suspects else None
                ),
                "location": _location_payload(token.location),
            }
            for token in board.suspects
        ],
        "weapons": [
            {
                "id": token.weapon_id,
                "name": CARDS_BY_ID[token.weapon_id].name,
                "room_id": token.room_id,
            }
            for token in board.weapons
        ],
        "phase": turn.phase.name.lower(),
        "dice": list(turn.dice) if turn.dice is not None else None,
        "remaining": turn.remaining,
        "visited": [_square_payload(square) for square in sorted(turn.visited)],
        "turn_player": turn_player,
        "summoned_seats": sorted(turn.summoned_seats),
    }


def _initial_notebook_mark(view: PlayerView, holder: int, card_id: int) -> str:
    if holder == view.player:
        return "+" if card_id in view.own_hand else "-"
    return "-" if card_id in view.own_hand else "?"


def _replay_deductions(
    game: WebGame, replay: Replay, timeline: list[tuple[int, int]], target_step: int,
) -> list[dict[str, int]]:
    positions: dict[int, int] = {}
    for position, (step, _) in enumerate(timeline):
        positions.setdefault(step, position)
    if game.replay_deduction_step < 0:
        game.replay_deduction_events = tuple(
            Event(EventKind.EXPOSE, seat, card_id=card)
            for seat, card in enumerate(replay.initial.public_cards)
        )
    relevant = {EventKind.PASS, EventKind.REFUTE, EventKind.SHOW, EventKind.EXPOSE,
                EventKind.ACCUSE, EventKind.END_TURN}
    sizes = tuple(len(hand) for hand in replay.initial.player_hands)
    seen = {(item["player"], item["holder"], item["card"]) for item in game.replay_deductions}
    for step in range(game.replay_deduction_step + 1, target_step + 1):
        events = replay.history[step - 1].events if step else ()
        replay_events = game.replay_deduction_events + events
        deductions = list(game.replay_deductions)
        if step == 0 or any(event.kind in relevant for event in events):
            for player, hand in enumerate(replay.initial.player_hands):
                view = view_for(replay_events, player, hand, hand_sizes=sizes)
                knowledge = knowledge_for(view, len(sizes))
                shown = {
                    (event.actor, event.card_id) for event in view.events
                    if event.kind in (EventKind.SHOW, EventKind.EXPOSE)
                }
                for holder in range(len(sizes) + 1):
                    if holder == player:
                        continue
                    for card_id in CARDS_BY_ID:
                        key = (player, holder, card_id)
                        if (key not in seen and (holder, card_id) not in shown
                                and knowledge.mark_of(holder, card_id) is Mark.HELD):
                            deductions.append({
                                "player": player, "holder": holder, "card": card_id,
                                "step": step, "position": positions[step],
                            })
                            seen.add(key)
        game.replay_deduction_events = replay_events
        game.replay_deductions = deductions
        game.replay_deduction_step = step
    return [item for item in game.replay_deductions if item["step"] <= target_step]


def _replay_knowledge_summary(engine: Engine) -> list[dict[str, Any]]:
    summaries = []
    for player in range(engine.num_players):
        knowledge = knowledge_for(engine.view(player), engine.num_players)
        categories = {}
        for card_type, cards in CARDS.items():
            marks = [
                knowledge.mark_of(holder, card.id)
                for card in cards for holder in range(engine.num_players + 1)
            ]
            categories[card_type.name.lower()] = {
                "located": sum(mark is Mark.HELD for mark in marks),
                "total": len(cards),
                "marks": sum(mark is not Mark.UNKNOWN for mark in marks),
                "mark_total": len(marks),
                "envelope": sum(
                    knowledge.mark_of(knowledge.envelope, card.id) is Mark.HELD
                    for card in cards
                ),
            }
        summaries.append({"player": player, "categories": categories})
    return summaries


def _serialize_state(
    game: WebGame, query: Any, *, replay_snapshot: Any = None, replay_player: int | None = None,
) -> dict[str, Any]:
    snapshot = replay_snapshot if replay_snapshot is not None else game.game.snapshot()
    selected_player = replay_player if replay_snapshot is not None else snapshot.human_player
    if selected_player is None:
        requested_player = query.get("player")
        if requested_player is not None:
            try:
                selected_player = int(requested_player)
            except ValueError as exc:
                raise ValueError("player must be a valid seat number.") from exc
            if not 0 <= selected_player < snapshot.num_players:
                raise ValueError("player must identify an existing seat.")
            game.selected_player = selected_player
        else:
            selected_player = game.selected_player

    view = snapshot.view
    if view is None:
        view = game.game.spectator_view(selected_player)
    knowledge = (
        knowledge_for(view, snapshot.num_players)
        if game.notebook_mode == "automatic" else None
    )
    marks = {Mark.UNKNOWN: "?", Mark.HELD: "+", Mark.NOT_HELD: "-"}

    def card_mark(holder: int, card_id: int) -> str:
        if knowledge is not None:
            return marks[knowledge.mark_of(holder, card_id)]
        return game.notebook_marks.get(
            (holder, card_id), _initial_notebook_mark(view, holder, card_id),
        )

    matrix = [
        {
            "id": card.id,
            "name": card.name,
            "type": card_type.name.lower(),
            "marks": [card_mark(holder, card.id) for holder in range(snapshot.num_players + 1)],
            "editable": [game.notebook_mode == "manual" for _ in range(snapshot.num_players + 1)],
        }
        for card_type, cards in CARDS.items()
        for card in cards
    ]

    clause_actor = query.get("clause_actor", "all")
    actor = None
    if clause_actor != "all":
        try:
            actor = int(clause_actor)
        except ValueError as exc:
            raise ValueError("Clause actor must be a valid seat number.") from exc
        if not 0 <= actor < snapshot.num_players:
            raise ValueError("Clause actor must identify an existing seat.")
    clause_kind_value = query.get("clause_kind", "all")
    clause_kinds = {
        "all": None,
        "refute": EventKind.REFUTE,
        "accuse": EventKind.ACCUSE,
    }
    if clause_kind_value not in clause_kinds:
        raise ValueError("Clause type must be all, refute, or accuse.")
    clauses = (
        format_clauses(knowledge, view=view, actor=actor, kind=clause_kinds[clause_kind_value])
        if knowledge is not None else
        "Automatic clause deductions are disabled in manual notebook mode."
    )

    legal = snapshot.legal_actions
    can_act = (
        game.mode == "play" and snapshot.to_move == snapshot.human_player
        and not game.waiting_for_turn and not game.abandoned
    )
    reveals = [
        {"id": action.card_id, "name": next(
            card.name for cards in CARDS.values() for card in cards
            if card.id == action.card_id
        )}
        for action in legal
        if can_act and isinstance(action, Reveal)
    ]
    suggestions = [action for action in legal if can_act and isinstance(action, Suggest)]
    board = _board_payload(snapshot.board, snapshot.turn_player) if snapshot.board else None
    debug_info = None
    if snapshot.debug_info is not None:
        debug_info = {
            "solution": [
                snapshot.debug_info.solution.suspect_id,
                snapshot.debug_info.solution.weapon_id,
                snapshot.debug_info.solution.room_id,
            ],
            "hands": [
                sorted(hand) for hand in snapshot.debug_info.hands
            ],
        }
    activity_events = snapshot.events if snapshot.debug_info is not None else view.events
    activity, activity_event_number = _activity_payload(activity_events)
    review_completed_turn = (
        game.waiting_for_turn and replay_snapshot is None and not game.abandoned
        and not snapshot.is_over and not snapshot.limit_reached
    )
    if review_completed_turn:
        if not activity_events or activity_events[-1].kind is not EventKind.END_TURN:
            raise ValueError("Turn confirmation requires a completed turn.")
        focus_turn = activity_events[-1].actor
        focus_actor = focus_turn
        focus_events = activity_events[:-1]
    else:
        focus_turn = snapshot.turn_player
        focus_actor = snapshot.to_move
        focus_events = activity_events
    if review_completed_turn and focus_events and focus_events[-1].kind is EventKind.END_TURN:
        focus_event, focus_show = None, None
    else:
        focus_event, focus_show = notebook_activity(focus_events)
    focus_combo = focus_event.combo if focus_event is not None else None
    notebook_focus = {
        "turn": (
            focus_turn
            if not snapshot.is_over and not snapshot.limit_reached and not game.abandoned else None
        ),
        "actor": notebook_actor(
            focus_turn,
            focus_actor
            if not snapshot.is_over and not snapshot.limit_reached and not game.abandoned else None,
            view.player,
            public_refutations=game.game.game_rules.public_refutations,
            omniscient=snapshot.debug_info is not None,
        ),
        "kind": focus_event.kind.name.lower() if focus_event is not None else None,
        "cards": (
            [focus_combo.suspect_id, focus_combo.weapon_id, focus_combo.room_id]
            if focus_combo is not None else []
        ),
        "shown": (
            {"card": focus_show.card_id, "holder": focus_show.actor}
            if focus_show is not None else None
        ),
    }

    if game.abandoned and replay_snapshot is None:
        status = "Game ended and revealed."
    elif snapshot.is_over:
        status = (
            "Game over: all players were eliminated."
            if snapshot.winner is None
            else f"Game over: Player {snapshot.winner} wins."
        )
    elif snapshot.limit_reached:
        status = f"Game stopped at the {snapshot.max_steps}-action limit."
    elif game.waiting_for_turn:
        status = f"Player {snapshot.turn_player} is next. Select Next turn to continue."
    else:
        status = f"Player {snapshot.to_move} to act."

    return {
        "mode": game.mode,
        "notebook_mode": game.notebook_mode,
        "notebook_revision": game.notebook_revision,
        "game_type": "board" if board is not None else "card_only",
        "board": board,
        "board_rules": asdict(game.game.board_rules) if board is not None else None,
        "game_rules": asdict(game.game.game_rules),
        "auto_progress": game.auto_progress,
        "paused": game.paused,
        "waiting_for_turn": game.waiting_for_turn,
        "num_players": snapshot.num_players,
        "hand_sizes": view.hand_sizes,
        "human_player": snapshot.human_player,
        "selected_player": selected_player,
        "to_move": snapshot.to_move,
        "is_over": snapshot.is_over or game.abandoned,
        "winner": snapshot.winner,
        "steps": snapshot.steps,
        "player0_turns": snapshot.player0_turns,
        "limit_reached": snapshot.limit_reached,
        "status": status,
        "hand": sorted(view.own_hand),
        "activity": activity,
        "activity_event_number": activity_event_number,
        "notebook_focus": notebook_focus,
        "events": _event_payload(snapshot.events),
        "matrix": matrix,
        "clauses": clauses,
        "notebook_clauses": (
            _automatic_clauses(view, knowledge) if knowledge is not None
            else list(game.notebook_clauses.values())
        ),
        "debug_info": debug_info,
        "legal": {
            "suggest": bool(suggestions),
            "accuse": can_act and any(isinstance(action, Accuse) for action in legal),
            "end_turn": can_act and any(isinstance(action, EndTurn) for action in legal),
            "pass": can_act and any(isinstance(action, Pass) for action in legal),
            "reveals": reveals,
            "roll": can_act and any(isinstance(action, Roll) for action in legal),
            "passage": can_act and any(isinstance(action, UsePassage) for action in legal),
            "moves": [
                _location_payload(action.destination)
                for action in legal if can_act and isinstance(action, Move)
            ],
            "suggest_room": suggestions[0].combination.room_id if board and suggestions else None,
        },
    }


def create_app(*, desktop_preferences: DesktopPreferences | None = None) -> Flask:
    app = Flask(__name__)
    app.secret_key = secrets.token_bytes(32)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,
    )
    games: dict[str, WebGame] = {}
    games_lock = threading.Lock()
    batches: dict[str, WebBatch] = {}
    batches_lock = threading.Lock()

    @app.before_request
    def protect_mutations():
        if (
            request.path != "/api/replay/import"
            and request.content_length is not None
            and request.content_length > 16 * 1024
        ):
            return jsonify(error="Request is too large."), 413
        if request.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            expected = browser_session.get("csrf_token")
            supplied = request.headers.get("X-CSRF-Token", "")
            if not isinstance(expected, str) or not hmac.compare_digest(expected, supplied):
                return jsonify(error="Missing or invalid CSRF token. Reload the page and try again."), 403
        return None

    @app.get("/")
    def index():
        token = browser_session.get("csrf_token")
        if not isinstance(token, str):
            token = secrets.token_urlsafe(32)
            browser_session["csrf_token"] = token
        return render_template(
            "index.html",
            csrf_token=token,
            cards=_card_options(),
            policies=POLICY_NAMES,
            desktop_theme=desktop_preferences.get_theme() if desktop_preferences else None,
            desktop_mode=desktop_preferences is not None,
            api_version=__version__,
            frontend_version=FRONTEND_VERSION,
            desktop_version=DESKTOP_VERSION,
        )

    @app.get("/api/setup")
    def setup_metadata():
        board = create_board(BoardSetup(3))
        return jsonify(
            layout=_board_payload(BoardTurn(board), None)["layout"],
            starts=[
                {"suspect_id": start.suspect_id, **_square_payload(start.square)}
                for start in DEFAULT_BOARD.starts
            ],
        )

    def batch_for_request(batch_id: str) -> WebBatch | None:
        owner = browser_session.get("batch_owner")
        now = time.monotonic()
        with batches_lock:
            batch = batches.get(batch_id)
            if batch is None or owner != batch.owner:
                return None
            batch.last_access = now
            return batch

    def run_batch_in_background(batch_id: str, config: BatchConfig, batch: WebBatch) -> None:
        def cancelled() -> bool:
            with batches_lock:
                return batch.cancel_requested

        def record_game(result: GameResult) -> None:
            with batches_lock:
                batch.finished_games += 1
                batch.last_access = time.monotonic()
                batch.distributions.add_game(result)
                batch.observations.append(
                    replace(result, seed=0, final_knowledge=[], error=None)
                )

        def update_progress(summary: BatchSummary) -> None:
            with batches_lock:
                batch.status = "running"
                batch.summary = summary
                batch.last_access = time.monotonic()

        try:
            directory = tempfile.TemporaryDirectory(prefix="clue-engine-batch-")
            with batches_lock:
                batch.trace_directory = directory
            summary = run_batch(
                config,
                Path(directory.name) / "trace.jsonl",
                progress=update_progress,
                cancelled=cancelled,
                on_game=record_game,
            )
            with batches_lock:
                batch.summary = summary
                batch.status = "cancelled" if summary["cancelled"] else "completed"
                batch.last_access = time.monotonic()
        except Exception as exc:
            app.logger.exception("Batch simulation %s failed", batch_id)
            with batches_lock:
                batch.status = "error"
                batch.error = f"{type(exc).__name__}: {exc}"
                batch.last_access = time.monotonic()

    @app.post("/api/batch")
    def start_batch():
        try:
            body = _json_body()
            if set(body) != {"setup", "games"}:
                raise ValueError("Supply setup and games.")
            games_requested = _integer(body, "games")
            config = batch_config_from_setup(body["setup"], games=games_requested)
        except (TypeError, ValueError) as exc:
            return jsonify(error=str(exc)), 400

        now = time.monotonic()
        with batches_lock:
            expired = [
                key for key, current in batches.items()
                if current.status not in {"queued", "running"}
                and now - current.last_access > _SESSION_TTL_SECONDS
            ]
            expired_batches = [batches.pop(key) for key in expired]
            if sum(current.status in {"queued", "running"} for current in batches.values()) >= _MAX_ACTIVE_BATCH_RUNS:
                return jsonify(error="A batch simulation is already running."), 409
            owner = browser_session.get("batch_owner")
            if not isinstance(owner, str):
                owner = secrets.token_urlsafe(24)
                browser_session["batch_owner"] = owner
            batch_id = secrets.token_urlsafe(24)
            settings = asdict(config) | {"players": config.player_count}
            batch = WebBatch(owner, config.game_type, config.games, settings)
            batches[batch_id] = batch
        for expired_batch in expired_batches:
            if expired_batch.trace_directory is not None:
                expired_batch.trace_directory.cleanup()

        worker = threading.Thread(
            target=run_batch_in_background, args=(batch_id, config, batch), daemon=True,
        )
        try:
            worker.start()
        except RuntimeError:
            app.logger.exception("Could not start batch simulation %s", batch_id)
            with batches_lock:
                batches.pop(batch_id, None)
            return jsonify(error="The batch simulation could not be started."), 503
        return jsonify(batch_id=batch_id, status=batch.status), 202

    @app.get("/api/batch/<batch_id>")
    def get_batch(batch_id: str):
        batch = batch_for_request(batch_id)
        if batch is None:
            return jsonify(error="Batch simulation not found."), 404
        with batches_lock:
            return jsonify(
                batch_id=batch_id,
                status=batch.status,
                game_type=batch.game_type,
                requested_games=batch.requested_games,
                settings=batch.settings,
                settings_display=format_batch_settings(batch.settings),
                finished_games=batch.finished_games,
                cancel_requested=batch.cancel_requested,
                summary=batch.summary,
                error=batch.error,
            )

    @app.post("/api/batch/<batch_id>/cancel")
    def cancel_batch(batch_id: str):
        batch = batch_for_request(batch_id)
        if batch is None:
            return jsonify(error="Batch simulation not found."), 404
        with batches_lock:
            if batch.status not in {"queued", "running"}:
                return jsonify(error="Batch simulation is no longer running."), 409
            batch.cancel_requested = True
            return jsonify(batch_id=batch_id, cancel_requested=True)

    @app.get("/api/batch/<batch_id>/distribution")
    def get_batch_distribution(batch_id: str):
        batch = batch_for_request(batch_id)
        if batch is None:
            return jsonify(error="Batch simulation not found."), 404
        metric = request.args.get("metric", "actions")
        try:
            width = int(request.args.get("width", "10"))
            policy = request.args.get("policy") or None
            raw_seat = request.args.get("seat")
            seat = int(raw_seat) if raw_seat is not None else None
            if seat is not None and seat < 0:
                raise ValueError("Seat must be non-negative.")
            if policy is not None and not policy.strip():
                raise ValueError("Policy must not be empty.")
            if width < 1:
                raise ValueError("Bin width must be at least 1.")
            if metric in BOARD_METRICS and batch.game_type != "board":
                raise ValueError("Board event distributions require a board simulation.")
            with batches_lock:
                if metric == "deduction":
                    chart = batch.distributions.chart(
                        metric, width=width, policy=policy, seat=seat,
                    )
                elif metric in {"seat_turns", "solution_turn", "knowledge_candidates", "knowledge_learned"}:
                    observations = list(batch.observations)
                    directory = batch.trace_directory
                    status = batch.status
                elif metric in {
                    "seat_compare_turns", "seat_compare_win_rate",
                    "seat_compare_learned_rate", "seat_compare_first_action",
                }:
                    observations = list(batch.observations)
                elif metric != "seat_outcomes" and policy is None and seat is None:
                    chart = batch.distributions.chart(metric, width=width)
                else:
                    observations = list(batch.observations)
            if metric == "seat_outcomes":
                chart = _seat_outcomes(observations, policy, seat)
            elif metric in {
                "seat_compare_turns", "seat_compare_win_rate",
                "seat_compare_learned_rate", "seat_compare_first_action",
            }:
                return jsonify(seat_comparison(observations, policy, seat, metric))
            elif metric == "seat_turns":
                chart = seat_turns(observations, policy, seat, width)
            elif metric in {"solution_turn", "knowledge_candidates", "knowledge_learned"}:
                if status not in {"completed", "cancelled"} or directory is None:
                    return jsonify(error="Knowledge charts are available after the batch finishes."), 409
                chart = knowledge_charts(Path(directory.name) / "trace.jsonl", policy, seat, width, metric)
                if isinstance(chart, dict):
                    return jsonify(chart)
            elif metric != "deduction" and (policy is not None or seat is not None):
                selected = Distributions()
                for result in observations:
                    if _matches_cohort(result, policy, seat):
                        selected.add_game(result)
                chart = selected.chart(metric, width=width)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(asdict(chart))

    @app.get("/api/batch/<batch_id>/runs")
    def get_batch_runs(batch_id: str):
        batch = batch_for_request(batch_id)
        if batch is None:
            return jsonify(error="Batch simulation not found."), 404
        try:
            policy = request.args.get("policy") or None
            raw_seat = request.args.get("seat")
            seat = int(raw_seat) if raw_seat is not None else None
            offset = int(request.args.get("offset", "0"))
            limit = int(request.args.get("limit", "25"))
            sort = request.args.get("sort", "game")
            order = request.args.get("order", "asc")
            if seat is not None and seat < 0:
                raise ValueError("Seat must be non-negative.")
            if policy is not None and not policy.strip():
                raise ValueError("Policy must not be empty.")
            if offset < 0 or not 1 <= limit <= 100:
                raise ValueError("Invalid run page.")
            if sort not in {
                "game", "outcome", "steps", "winner", "turns", "learned", "first_solution",
                "suggestions", "passes", "refutations", *BOARD_METRICS,
            } or order not in {"asc", "desc"}:
                raise ValueError("Invalid run sort.")
            if sort in BOARD_METRICS and batch.game_type != "board":
                raise ValueError("Board event sorting requires a board simulation.")
            with batches_lock:
                results = [
                    result for result in batch.observations
                    if _matches_cohort(result, policy, seat)
                ]
            def sort_key(result: GameResult) -> tuple[Any, int]:
                if sort == "turns":
                    value = sum(result.turns)
                elif sort == "learned":
                    value = sum(step is not None for step in result.first_solution_step)
                elif sort == "winner":
                    value = result.winner if result.winner is not None else -1
                elif sort == "first_solution":
                    value = min(
                        (step for step in result.first_solution_step if step is not None),
                        default=-1,
                    )
                else:
                    value = getattr(result, sort)
                return value, result.game

            results.sort(key=sort_key, reverse=order == "desc")
            rows = [
                {
                    "game": item.game, "outcome": item.outcome, "winner": item.winner,
                    "steps": item.steps, "turns": item.turns, "policies": item.policies,
                    "learned": sum(step is not None for step in item.first_solution_step),
                    "first_solution": min(
                        (step for step in item.first_solution_step if step is not None),
                        default=None,
                    ),
                    "first_solution_steps": item.first_solution_step,
                    "suggestions": item.suggestions, "passes": item.passes,
                    "refutations": item.refutations,
                    **{metric: getattr(item, metric) for metric in BOARD_METRICS},
                }
                for item in results[offset:offset + limit]
            ]
            return jsonify(total=len(results), offset=offset, limit=limit, runs=rows)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

    if desktop_preferences is not None:
        @app.post("/api/desktop/theme")
        def set_desktop_theme():
            try:
                body = _json_body()
                theme = body.get("theme")
                if not isinstance(theme, str):
                    raise TypeError("Theme must be light or dark.")
                desktop_preferences.set_theme(theme)
            except (TypeError, ValueError) as exc:
                return jsonify(error=str(exc)), 400
            except OSError:
                app.logger.exception("Failed to save desktop theme")
                return jsonify(error="Could not save the desktop theme."), 500
            return jsonify(theme=theme)

        @app.get("/api/desktop/profiles")
        def get_desktop_profiles():
            try:
                return jsonify(profiles=desktop_preferences.get_profiles())
            except (OSError, ValueError):
                app.logger.exception("Failed to load desktop setup profiles")
                return jsonify(error="Could not load the desktop setup profiles."), 500

        @app.put("/api/desktop/profiles")
        def set_desktop_profiles():
            try:
                body = _json_body()
                if set(body) != {"profiles"}:
                    raise ValueError("Expected a profiles object.")
                desktop_preferences.set_profiles(body["profiles"])
            except (TypeError, ValueError) as exc:
                return jsonify(error=str(exc)), 400
            except OSError:
                app.logger.exception("Failed to save desktop setup profiles")
                return jsonify(error="Could not save the desktop setup profiles."), 500
            return jsonify(profiles=body["profiles"])

    @app.post("/api/game")
    def start_game():
        try:
            body = _json_body()
            mode = body.get("mode", "play")
            if mode not in {"play", "spectate"}:
                raise ValueError("Mode must be play or spectate.")
            notebook_mode = body.get("notebook_mode", "automatic")
            if not isinstance(notebook_mode, str) or notebook_mode not in {"manual", "automatic"}:
                raise ValueError("Notebook mode must be manual or automatic.")
            if mode == "spectate" and notebook_mode == "manual":
                raise ValueError("Spectator games require an automatic notebook.")
            game_type = body.get("game_type", "card_only")
            if not isinstance(game_type, str) or game_type not in {"card_only", "board"}:
                raise ValueError("Game type must be card_only or board.")
            num_players = _integer(body, "players", 4)
            if num_players < 2:
                raise ValueError("A game requires at least two players.")
            seed = _integer(body, "seed", 0)
            max_steps = _integer(body, "max_steps", 10_000)
            progress = body.get("progress", "auto")
            if progress not in {"auto", "turn", "step"}:
                raise ValueError("Progress must be auto, turn, or step.")
            if max_steps < 0:
                raise ValueError("The action limit must be non-negative.")
            seat = None
            if mode == "play":
                seat = _integer(body, "seat", 0)
                if not 0 <= seat < num_players:
                    raise ValueError("Your seat must identify an existing player.")
            bots = body.get("bots")
            additional_policies = ("learned",)
            if "bots" in body and ("policy" in body or "policies" in body):
                raise ValueError("Use either bots or legacy policy fields, not both.")
            if "bots" in body:
                if not isinstance(bots, list) or len(bots) != num_players:
                    raise ValueError("Supply one bot configuration per seat.")
                if game_type != "board" and any(bot == "learned" for bot in bots):
                    raise ValueError("the learned policy supports board games only")
                for index, bot in enumerate(bots):
                    if bot is None:
                        if index != seat:
                            raise ValueError("Only the human seat may omit its bot configuration.")
                    elif isinstance(bot, str):
                        policies_for_players(bot, 1, additional=additional_policies)
                    elif isinstance(bot, dict):
                        strategy = bot_strategy_from_dict(bot)
                        if isinstance(strategy, LearnedStrategy) and game_type != "board":
                            raise ValueError("the learned policy supports board games only")
                    else:
                        raise TypeError("Each bot must be a policy name or strategy object.")
            per_seat_policies = body.get("policies", "")
            if not isinstance(per_seat_policies, str):
                raise TypeError("Policies must be text.")
            policy_selection = (
                "random" if bots is not None else
                per_seat_policies.strip() or body.get("policy", "deductive")
            )
            if not isinstance(policy_selection, str):
                raise TypeError("Policy must be text.")
            policies_for_players(
                policy_selection, num_players, additional=additional_policies,
            )
            debug = body.get("debug", False)
            if type(debug) is not bool:
                raise ValueError("Debug must be true or false.")
            board_options: dict[str, Any] = {}
            raw_game_rules = body.get("game_rules", {})
            if not isinstance(raw_game_rules, dict) or set(raw_game_rules) - {
                item.name for item in fields(GameRules)
            }:
                raise ValueError("Invalid game rules.")
            if "game_rules" in body:
                board_options["game_rules"] = GameRules(**raw_game_rules)
            if "board_rules" in body:
                if game_type != "board" or not isinstance(body["board_rules"], dict):
                    raise ValueError("Board rules require a board game and an object.")
                raw_rules = body["board_rules"]
                if set(raw_rules) - {item.name for item in fields(BoardRules)}:
                    raise ValueError("Unknown board rule.")
                board_options["board_rules"] = BoardRules(**raw_rules)
            if "seat_suspects" in body:
                suspects = body["seat_suspects"]
                if game_type != "board" or not isinstance(suspects, list):
                    raise ValueError("Character assignments require a board game and an array.")
                if len(suspects) != num_players or any(type(item) is not int for item in suspects):
                    raise ValueError("Assign one character to each seat.")
                board_options["seat_suspects"] = suspects
            factory = create_board_game if game_type == "board" else create_game
            engine, policies = factory(num_players, seed, policy_selection, **board_options)
            if bots is not None:
                policies = tuple(
                    make_policy(
                        bot_strategy_from_dict(bot) if isinstance(bot, dict)
                        else bot if isinstance(bot, str) else "random",
                        random.Random(f"{seed}:{index}"),
                    )
                    for index, bot in enumerate(bots)
                )
        except (TypeError, ValueError) as exc:
            return jsonify(error=str(exc)), 400
        except OSError:
            app.logger.exception("Failed to load a learned or opponent model")
            return jsonify(error=(
                "Could not load a model. Check CLUE_LEARNED_MODEL and CLUE_OPPONENT_MODEL."
            )), 500

        session_game = GameSession(
            engine,
            policies,
            human_player=seat,
            debug=debug,
            max_steps=max_steps,
        )
        game_id = secrets.token_urlsafe(24)
        game = WebGame(
            game=session_game,
            mode=mode,
            auto_progress=progress != "step",
            paused=progress == "step",
            confirm_turns=mode == "play" or progress == "turn",
            selected_player=0,
            notebook_mode=notebook_mode,
        )
        now = time.monotonic()
        with games_lock:
            previous_game_id = browser_session.get("game_id")
            if isinstance(previous_game_id, str):
                games.pop(previous_game_id, None)
            expired = [
                key for key, current in games.items()
                if now - current.last_access > _SESSION_TTL_SECONDS
            ]
            for key in expired:
                games.pop(key, None)
            if len(games) >= _MAX_ACTIVE_SESSIONS:
                return jsonify(error="The local server has too many active games. Restart it to clear them."), 503
            games[game_id] = game
        browser_session["game_id"] = game_id
        try:
            return jsonify(_serialize_state(game, request.args)), 201
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

    @app.delete("/api/game")
    def exit_game():
        game_id = browser_session.pop("game_id", None)
        if isinstance(game_id, str):
            with games_lock:
                games.pop(game_id, None)
        return jsonify(ok=True)

    @app.get("/api/state")
    def game_state():
        game = _game_from_request(games, games_lock)
        if game is None:
            return jsonify(error="Start a game before requesting its state."), 404
        with game.lock:
            try:
                return jsonify(_serialize_state(game, request.args))
            except ValueError as exc:
                return jsonify(error=str(exc)), 400

    def available_replay(game: WebGame) -> Replay:
        if not game.abandoned and not game.game.snapshot().is_over:
            raise ValueError("Replay is available only after the game ends.")
        if game.imported_replay is not None:
            return game.imported_replay
        return Replay(
            game.game.initial_state, game.game.history,
            game.game.snapshot().human_player, game.notebook_mode, tuple(game.notebook_history),
        )

    def install_replay(replay: Replay) -> bool:
        engine = replay_history(replay.initial, ())
        policies = tuple(
            make_policy("random", random.Random(seat)) for seat in range(engine.num_players)
        )
        session_game = GameSession(engine, policies, human_player=replay.human)
        game = WebGame(
            game=session_game, mode="spectate", auto_progress=False, paused=True,
            confirm_turns=False, selected_player=0, abandoned=True, imported_replay=replay,
        )
        game_id = secrets.token_urlsafe(24)
        with games_lock:
            old_id = browser_session.get("game_id")
            if isinstance(old_id, str):
                games.pop(old_id, None)
            if len(games) >= _MAX_ACTIVE_SESSIONS:
                return False
            games[game_id] = game
        browser_session["game_id"] = game_id
        return True

    @app.post("/api/batch/<batch_id>/runs/<int:game_number>/replay")
    def open_batch_replay(batch_id: str, game_number: int):
        batch = batch_for_request(batch_id)
        if batch is None:
            return jsonify(error="Batch simulation not found."), 404
        with batches_lock:
            if batch.status in {"queued", "running"}:
                return jsonify(error="Wait for the batch to finish before opening a replay."), 409
            if not any(result.game == game_number for result in batch.observations):
                return jsonify(error="Batch run not found."), 404
            directory = batch.trace_directory
        if directory is None:
            return jsonify(error="Batch replay trace is unavailable."), 409
        try:
            replay = replay_from_batch_trace(Path(directory.name) / "trace.jsonl", game_number)
            if not install_replay(replay):
                return jsonify(error="The local server has too many active games."), 503
        except (OSError, KeyError, TypeError, ValueError) as exc:
            app.logger.exception("Could not load batch replay %s/%s", batch_id, game_number)
            return jsonify(error=f"Could not load batch replay: {exc}"), 409
        return jsonify(positions=len(replay.history) + 1)

    @app.post("/api/replay/end")
    def end_and_reveal():
        game = _game_from_request(games, games_lock)
        if game is None:
            return jsonify(error="Start a game first."), 404
        with game.lock:
            try:
                body = _json_body()
            except TypeError as exc:
                return jsonify(error=str(exc)), 400
            if body.get("confirmed") is not True:
                return jsonify(error="Confirm ending and revealing the game."), 400
            if game.game.snapshot().is_over or game.abandoned:
                return jsonify(error="This game has already ended."), 409
            game.abandoned = True
            game.paused = True
            game.waiting_for_turn = False
            return jsonify(_serialize_state(game, {}))

    @app.get("/api/replay/export")
    def export_replay():
        game = _game_from_request(games, games_lock)
        if game is None:
            return jsonify(error="Start a game first."), 404
        with game.lock:
            try:
                response = jsonify(encode_replay(available_replay(game)))
                response.headers["Content-Disposition"] = 'attachment; filename="clue-private-replay.json"'
                response.headers["Cache-Control"] = "no-store"
                return response
            except ValueError as exc:
                return jsonify(error=str(exc)), 409

    @app.post("/api/replay/import")
    def import_replay():
        try:
            replay = decode_replay(_json_body())
            for note in replay.notes:
                if note["kind"] == "clause":
                    ids = set()
                    for clause in note["clauses"]:
                        if not isinstance(clause, dict):
                            raise TypeError("Invalid recorded clause.")
                        if clause.get("status") not in ("resolved", "unresolved"):
                            raise ValueError("Invalid recorded clause status.")
                        clause_id = _integer(clause, "id")
                        if clause_id < 1 or clause_id in ids:
                            raise ValueError("Invalid recorded clause id.")
                        ids.add(clause_id)
                        normalized = _manual_clause({
                            "kind": clause.get("kind"), "holder": clause.get("holder"),
                            "cards": clause.get("cards"),
                            "resolved": clause.get("status") == "resolved",
                            "excluded_cards": clause.get("excluded_cards", []),
                        }, len(replay.initial.player_hands))
                        normalized["id"] = clause_id
                        clause.clear()
                        clause.update(normalized)
            if not install_replay(replay):
                return jsonify(error="The local server has too many active games."), 503
        except (TypeError, ValueError) as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(positions=len(replay.history) + len(replay.notes) + 1)

    @app.get("/api/replay/state")
    def replay_state():
        game = _game_from_request(games, games_lock)
        if game is None:
            return jsonify(error="Start or import a game first."), 404
        with game.lock:
            try:
                replay = available_replay(game)
                position = int(request.args.get("position", "0"))
                player = int(request.args.get("player", "0"))
                if not 0 <= player < len(replay.initial.player_hands):
                    raise ValueError("Invalid player.")
                timeline: list[tuple[int, int]] = [(0, 0)]
                note_index = 0
                turns = [0]
                for step in range(len(replay.history) + 1):
                    while note_index < len(replay.notes) and replay.notes[note_index]["step"] == step:
                        note_index += 1
                        timeline.append((step, note_index))
                    if step < len(replay.history):
                        timeline.append((step + 1, note_index))
                        if any(e.kind is EventKind.END_TURN for e in replay.history[step].events):
                            turns.append(len(timeline) - 1)
                if not 0 <= position < len(timeline):
                    raise ValueError("Invalid replay position.")
                step, note_count = timeline[position]
                engine = replay_history(replay.initial, replay.history[:step])
                view = engine.view(player)
                show_all = request.args.get("omniscient") == "1"
                snapshot = replace(
                    game.game.snapshot(), human_player=player, to_move=None, is_over=True,
                    winner=engine.winner, steps=step, player0_turns=completed_turns(engine, 0),
                    limit_reached=False, view=view,
                    events=engine.log if show_all else view.events, legal_actions=(),
                    debug_info=DebugInfo(engine.state.solution, tuple(engine.state.player_hands))
                    if show_all else None,
                    board=engine.state.board, turn_player=engine.state.current_player,
                )
                manual = (
                    request.args.get("manual") == "1" and player == replay.human
                    and replay.notebook_mode == "manual"
                )
                marks: dict[tuple[int, int], str] = {}
                clauses: dict[int, dict[str, Any]] = {}
                for note in replay.notes[:note_count]:
                    if note["kind"] == "mark":
                        marks[(note["holder"], note["card"])] = note["mark"]
                    else:
                        clauses = {clause["id"]: clause for clause in note["clauses"]}
                temporary = replace(
                    game, mode="replay", notebook_mode="manual" if manual else "automatic",
                    notebook_marks=marks, notebook_clauses=clauses, waiting_for_turn=False,
                )
                result = _serialize_state(
                    temporary, request.args, replay_snapshot=snapshot, replay_player=player,
                )
                result["notebook_focus"]["turn"] = (
                    engine.state.current_player if not engine.is_over else None
                )
                result["notebook_focus"]["actor"] = notebook_actor(
                    engine.state.current_player, engine.to_move, player,
                    public_refutations=engine.state.game_rules.public_refutations,
                    omniscient=show_all,
                )
                if step not in game.replay_knowledge_summaries:
                    game.replay_knowledge_summaries[step] = _replay_knowledge_summary(engine)
                result.update(
                    mode="replay", paused=True, auto_progress=False, is_replay=True,
                    position=position, positions=len(timeline), turns=turns,
                    manual_available=player == replay.human and replay.notebook_mode == "manual",
                    status=f"Replay: action {step} of {len(replay.history)}.",
                    board_rules=asdict(engine.state.board_rules) if engine.state.board else None,
                    game_rules=asdict(engine.state.game_rules),
                    deduction_timeline=_replay_deductions(game, replay, timeline, len(replay.history)),
                    knowledge_summary=game.replay_knowledge_summaries[step],
                )
                for card in result["matrix"]:
                    card["editable"] = [False] * len(card["editable"])
                return jsonify(result)
            except (TypeError, ValueError) as exc:
                return jsonify(error=str(exc)), 400

    @app.put("/api/notebook")
    def update_notebook():
        game = _game_from_request(games, games_lock)
        if game is None:
            return jsonify(error="Start a game before editing its notebook."), 404
        try:
            body = _json_body()
            if set(body) != {"card_id", "holder", "mark"}:
                raise ValueError("Supply a card_id, holder, and mark.")
            card_id = _integer(body, "card_id")
            holder = _integer(body, "holder")
            mark = body["mark"]
            if card_id not in CARDS_BY_ID:
                raise ValueError("Card must identify an existing card.")
            if not isinstance(mark, str) or mark not in {"?", "+", "-"}:
                raise ValueError("Mark must be ?, +, or -.")
        except (TypeError, ValueError) as exc:
            return jsonify(error=str(exc)), 400

        with game.lock:
            if game.notebook_mode != "manual":
                return jsonify(error="This notebook is automatic and cannot be edited."), 409
            if game.abandoned:
                return jsonify(error="This game has ended."), 409
            snapshot = game.game.snapshot()
            view = snapshot.view
            if view is None:
                return jsonify(error="A manual notebook requires a player view."), 409
            if not 0 <= holder <= snapshot.num_players:
                return jsonify(error="Holder must identify a player or the envelope."), 400
            key = (holder, card_id)
            initial = _initial_notebook_mark(view, holder, card_id)
            if game.notebook_marks.get(key, initial) != mark:
                if mark == initial:
                    game.notebook_marks.pop(key, None)
                else:
                    game.notebook_marks[key] = mark
                game.notebook_revision += 1
                game.notebook_history.append({
                    "step": snapshot.steps, "kind": "mark", "holder": holder,
                    "card": card_id, "mark": mark,
                })
            return jsonify(_serialize_state(game, {}))

    @app.route("/api/notebook/clauses", methods=["POST"])
    @app.route("/api/notebook/clauses/<int:clause_id>", methods=["PUT", "DELETE"])
    def update_notebook_clause(clause_id: int | None = None):
        game = _game_from_request(games, games_lock)
        if game is None:
            return jsonify(error="Start a game before editing its notebook."), 404
        with game.lock:
            if game.abandoned:
                return jsonify(error="This game has ended."), 409
            if game.notebook_mode != "manual" or game.game.snapshot().view is None:
                return jsonify(error="This notebook is automatic and cannot be edited."), 409
            if clause_id is not None and clause_id not in game.notebook_clauses:
                return jsonify(error="Clause not found."), 404
            if request.method == "DELETE":
                del game.notebook_clauses[clause_id]
                game.notebook_revision += 1
            else:
                try:
                    clause = _manual_clause(_json_body(), game.game.snapshot().num_players)
                except (TypeError, ValueError) as exc:
                    return jsonify(error=str(exc)), 400
                if clause_id is None:
                    clause_id = game.next_clause_id
                    game.next_clause_id += 1
                clause["id"] = clause_id
                if game.notebook_clauses.get(clause_id) != clause:
                    game.notebook_clauses[clause_id] = clause
                    game.notebook_revision += 1
            if game.notebook_revision > len(game.notebook_history):
                game.notebook_history.append({
                    "step": game.game.snapshot().steps, "kind": "clause",
                    "clauses": list(game.notebook_clauses.values()),
                })
            return jsonify(_serialize_state(game, {}))

    @app.post("/api/action")
    def submit_action():
        game = _game_from_request(games, games_lock)
        if game is None:
            return jsonify(error="Start a game before submitting an action."), 404
        try:
            body = _json_body()
            action_name = body.get("action")
            match action_name:
                case "suggest":
                    action: Action = Suggest(_make_combination(body))
                case "accuse":
                    if body.get("confirmed") is not True:
                        raise ValueError("Confirm the accusation before submitting it.")
                    action = Accuse(_make_combination(body))
                case "reveal":
                    action = Reveal(_integer(body, "card_id"))
                case "pass":
                    action = Pass()
                case "end_turn":
                    action = EndTurn()
                case "roll":
                    action = Roll()
                case "passage":
                    action = UsePassage()
                case "move":
                    destination = body.get("destination")
                    if not isinstance(destination, dict):
                        raise TypeError("Move destination must be an object.")
                    if destination.get("kind") == "hallway":
                        action = Move(Square(_integer(destination, "x"), _integer(destination, "y")))
                    elif destination.get("kind") == "room":
                        action = Move(RoomPosition(_integer(destination, "room_id")))
                    else:
                        raise ValueError("Move destination must be a hallway square or room.")
                case _:
                    raise ValueError("Unknown action.")
        except (TypeError, ValueError) as exc:
            return jsonify(error=str(exc)), 400

        with game.lock:
            if game.abandoned:
                return jsonify(error="This game has ended."), 409
            if game.waiting_for_turn:
                return jsonify(error="Select Next turn before taking an action."), 409
            try:
                game.game.submit(action)
            except IllegalActionError as exc:
                return jsonify(error=str(exc)), 409
            except ValueError as exc:
                return jsonify(error=str(exc)), 409
            try:
                return jsonify(_serialize_state(game, request.args))
            except ValueError as exc:
                return jsonify(error=str(exc)), 400

    @app.post("/api/advance")
    def advance_bot():
        game = _game_from_request(games, games_lock)
        if game is None:
            return jsonify(error="Start a game before advancing it."), 404
        try:
            body = _json_body()
            step = body.get("step", False)
            if type(step) is not bool:
                raise ValueError("step must be true or false.")
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

        with game.lock:
            snapshot = game.game.snapshot()
            is_bot_turn = (
                not game.abandoned and not snapshot.is_over
                and not snapshot.limit_reached
                and not game.waiting_for_turn
                and snapshot.to_move != snapshot.human_player
            )
            allowed = (step and game.paused) or (
                not step and game.auto_progress and not game.paused
            )
            if not is_bot_turn or not allowed:
                return jsonify(error="No bot action is currently available."), 409
            try:
                game.game.advance_bot()
            except IllegalActionError as exc:
                game.paused = True
                return jsonify(error=f"Bot attempted an illegal action; game paused: {exc}"), 409
            except ValueError as exc:
                return jsonify(error=str(exc)), 409
            after = game.game.snapshot()
            if (
                game.confirm_turns and not after.is_over and not after.limit_reached
                and any(
                    event.kind is EventKind.END_TURN
                    for event in after.events[len(snapshot.events):]
                )
            ):
                game.waiting_for_turn = True
            try:
                return jsonify(_serialize_state(game, request.args))
            except ValueError as exc:
                return jsonify(error=str(exc)), 400

    @app.post("/api/next-turn")
    def next_turn():
        game = _game_from_request(games, games_lock)
        if game is None:
            return jsonify(error="Start a game before continuing to the next turn."), 404
        with game.lock:
            if game.abandoned:
                return jsonify(error="This game has ended."), 409
            if not game.waiting_for_turn:
                return jsonify(error="No turn is waiting for confirmation."), 409
            game.waiting_for_turn = False
            selected_player = game.selected_player
            try:
                return jsonify(_serialize_state(game, request.args))
            except ValueError as exc:
                game.waiting_for_turn = True
                game.selected_player = selected_player
                return jsonify(error=str(exc)), 400

    @app.post("/api/pause")
    def toggle_pause():
        game = _game_from_request(games, games_lock)
        if game is None:
            return jsonify(error="Start a game before changing pause state."), 404
        with game.lock:
            snapshot = game.game.snapshot()
            if game.abandoned or snapshot.is_over or snapshot.limit_reached:
                return jsonify(error="This game can no longer be paused or resumed."), 409
            game.paused = not game.paused
            if not game.paused:
                game.auto_progress = True
            return jsonify(_serialize_state(game, request.args))

    return app
