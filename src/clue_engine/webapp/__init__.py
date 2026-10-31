"""Flask application for the local browser interface."""

import hmac
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from flask import Flask, jsonify, render_template, request
from flask import session as browser_session

from ..cards import CARDS
from ..engine import IllegalActionError
from ..knowledge import Mark, knowledge_for
from ..models import (
    Accuse,
    Action,
    Combination,
    EndTurn,
    Pass,
    Reveal,
    Suggest,
)
from ..observations import EventKind
from ..policies import POLICY_NAMES, policies_for_players
from ..presentation import format_clauses, format_event
from ..session import GameSession, create_game

_SESSION_TTL_SECONDS = 60 * 60
_MAX_ACTIVE_SESSIONS = 64


@dataclass
class WebGame:
    game: GameSession
    mode: str
    auto_progress: bool
    paused: bool
    selected_player: int
    last_access: float = field(default_factory=time.monotonic)
    lock: threading.RLock = field(default_factory=threading.RLock)


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


def _activity_payload(events: tuple[Any, ...]) -> dict[str, Any] | None:
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
            }

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
        }
        if event.kind is EventKind.SHOW:
            if event.card_id is None or event.private_to is None:
                raise ValueError("SHOW event without a card or recipient")
            activity["card_id"] = event.card_id
            activity["recipient"] = event.private_to
        else:
            activity["cards"] = [
                suggestion.combo.suspect_id,
                suggestion.combo.weapon_id,
                suggestion.combo.room_id,
            ]
        return activity
    return None


def _serialize_state(game: WebGame, query: Any) -> dict[str, Any]:
    snapshot = game.game.snapshot()
    selected_player = snapshot.human_player
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
    knowledge = knowledge_for(view, snapshot.num_players)
    marks = {Mark.UNKNOWN: "?", Mark.HELD: "+", Mark.NOT_HELD: "-"}
    matrix = [
        {
            "id": card.id,
            "name": card.name,
            "type": card_type.name.lower(),
            "marks": [
                marks[knowledge.mark_of(holder, card.id)]
                for holder in range(snapshot.num_players + 1)
            ],
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
    clauses = format_clauses(
        knowledge,
        view=view,
        actor=actor,
        kind=clause_kinds[clause_kind_value],
    )

    legal = snapshot.legal_actions
    can_act = game.mode == "play" and snapshot.to_move == snapshot.human_player
    reveals = [
        {"id": action.card_id, "name": next(
            card.name for cards in CARDS.values() for card in cards
            if card.id == action.card_id
        )}
        for action in legal
        if can_act and isinstance(action, Reveal)
    ]
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

    if snapshot.is_over:
        status = (
            "Game over: all players were eliminated."
            if snapshot.winner is None
            else f"Game over: Player {snapshot.winner} wins."
        )
    elif snapshot.limit_reached:
        status = f"Game stopped at the {snapshot.max_steps}-action limit."
    else:
        status = f"Player {snapshot.to_move} to act."

    return {
        "mode": game.mode,
        "auto_progress": game.auto_progress,
        "paused": game.paused,
        "num_players": snapshot.num_players,
        "human_player": snapshot.human_player,
        "selected_player": selected_player,
        "to_move": snapshot.to_move,
        "is_over": snapshot.is_over,
        "winner": snapshot.winner,
        "steps": snapshot.steps,
        "player0_turns": snapshot.player0_turns,
        "limit_reached": snapshot.limit_reached,
        "status": status,
        "hand": sorted(view.own_hand),
        "activity": _activity_payload(
            snapshot.events if snapshot.debug_info is not None else view.events
        ),
        "events": _event_payload(snapshot.events),
        "matrix": matrix,
        "clauses": clauses,
        "debug_info": debug_info,
        "legal": {
            "suggest": can_act and any(isinstance(action, Suggest) for action in legal),
            "accuse": can_act and any(isinstance(action, Accuse) for action in legal),
            "end_turn": can_act and any(isinstance(action, EndTurn) for action in legal),
            "pass": can_act and any(isinstance(action, Pass) for action in legal),
            "reveals": reveals,
        },
    }


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = secrets.token_bytes(32)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=16 * 1024,
    )
    games: dict[str, WebGame] = {}
    games_lock = threading.Lock()

    @app.before_request
    def protect_mutations():
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
        )

    @app.post("/api/game")
    def start_game():
        try:
            body = _json_body()
            mode = body.get("mode", "play")
            if mode not in {"play", "spectate"}:
                raise ValueError("Mode must be play or spectate.")
            num_players = _integer(body, "players", 4)
            if num_players < 2:
                raise ValueError("A game requires at least two players.")
            seed = _integer(body, "seed", 0)
            max_steps = _integer(body, "max_steps", 10_000)
            progress = body.get("progress", "auto")
            if progress not in {"auto", "step"}:
                raise ValueError("Progress must be auto or step.")
            if max_steps < 0:
                raise ValueError("The action limit must be non-negative.")
            seat = None
            if mode == "play":
                seat = _integer(body, "seat", 0)
                if not 0 <= seat < num_players:
                    raise ValueError("Your seat must identify an existing player.")
            per_seat_policies = body.get("policies", "")
            if not isinstance(per_seat_policies, str):
                raise TypeError("Policies must be text.")
            policy_selection = per_seat_policies.strip() or body.get("policy", "deductive")
            if not isinstance(policy_selection, str):
                raise TypeError("Policy must be text.")
            policies_for_players(policy_selection, num_players)
            debug = body.get("debug", False)
            if type(debug) is not bool:
                raise ValueError("Debug must be true or false.")
        except (TypeError, ValueError) as exc:
            return jsonify(error=str(exc)), 400

        engine, policies = create_game(num_players, seed, policy_selection)
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
            auto_progress=progress == "auto",
            paused=progress == "step",
            selected_player=0,
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
                case _:
                    raise ValueError("Unknown action.")
        except (TypeError, ValueError) as exc:
            return jsonify(error=str(exc)), 400

        with game.lock:
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
                not snapshot.is_over
                and not snapshot.limit_reached
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
            try:
                return jsonify(_serialize_state(game, request.args))
            except ValueError as exc:
                return jsonify(error=str(exc)), 400

    @app.post("/api/pause")
    def toggle_pause():
        game = _game_from_request(games, games_lock)
        if game is None:
            return jsonify(error="Start a game before changing pause state."), 404
        with game.lock:
            snapshot = game.game.snapshot()
            if snapshot.is_over or snapshot.limit_reached:
                return jsonify(error="This game can no longer be paused or resumed."), 409
            game.paused = not game.paused
            return jsonify(_serialize_state(game, request.args))

    return app
