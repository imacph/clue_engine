"""Reproducible batch simulations and streaming private JSONL traces."""

import json
import math
import random
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import TextIO, TypeAlias, TypedDict

from .board_state import RoomPosition
from .board_turn import Move, Roll, UsePassage
from .cards import CARDS, CARDS_BY_ID
from .engine import Engine, IllegalActionError
from .game_settings import (
    DEFAULT_BOARD_RULES,
    DEFAULT_GAME_RULES,
    BoardRules,
    BotStrategy,
    GameRules,
)
from .knowledge import InconsistentKnowledgeError, Mark, knowledge_for, known_solution
from .models import Accuse, Action, EndTurn, Pass, Reveal, Suggest
from .observations import Event, EventKind
from .policies import CustomPolicy, Policy, make_policy, validate_policy_names
from .policies import policies_for_players as _policies_for_players
from .session import create_board_game, create_game

PolicySpec: TypeAlias = str | BotStrategy
GAME_TYPES = ("card_only", "board")


@dataclass(frozen=True)
class BatchConfig:
    games: int
    policies: tuple[PolicySpec, ...]
    seed: int = 0
    max_steps: int = 10_000
    rotate: bool = True
    game_type: str = "card_only"
    game_rules: GameRules = DEFAULT_GAME_RULES
    board_rules: BoardRules = DEFAULT_BOARD_RULES
    seat_suspects: tuple[int, ...] | None = None
    shuffle_bots: bool = False

    def validate(self) -> None:
        if type(self.games) is not int or self.games < 1:
            raise ValueError("games must be at least 1")
        if len(self.policies) < 2:
            raise ValueError("at least two player policies are required")
        for policy in self.policies:
            if isinstance(policy, str):
                validate_policy_names((policy,))
            elif not isinstance(policy, BotStrategy):
                raise TypeError("policies must be named policies or BotStrategy values")
        if type(self.seed) is not int:
            raise TypeError("seed must be an integer")
        if type(self.max_steps) is not int or self.max_steps < 0:
            raise ValueError("max_steps must be non-negative")
        if type(self.rotate) is not bool or type(self.shuffle_bots) is not bool:
            raise TypeError("rotate and shuffle_bots must be true or false")
        if not isinstance(self.game_type, str) or self.game_type not in GAME_TYPES:
            raise ValueError(f"game_type must be one of {', '.join(GAME_TYPES)}")
        if not isinstance(self.game_rules, GameRules):
            raise TypeError("game_rules must be GameRules")
        if not isinstance(self.board_rules, BoardRules):
            raise TypeError("board_rules must be BoardRules")
        if self.game_rules.face_up_card and len(self.policies) > len(CARDS_BY_ID) - 3:
            raise ValueError("face-up cards require at least one card per player")
        if self.game_type == "board":
            from .board_setup import BoardSetup
            from .board_state import create_board

            if self.seat_suspects is not None and not isinstance(self.seat_suspects, tuple):
                raise TypeError("seat_suspects must be a tuple")
            create_board(BoardSetup(len(self.policies)), seat_suspects=self.seat_suspects)
        elif self.seat_suspects is not None or self.board_rules != DEFAULT_BOARD_RULES:
            raise ValueError("board rules and character assignments require a board game")


def batch_config_from_setup(
    value: object,
    *,
    games: int,
    seed: int | None = None,
    max_steps: int | None = None,
    rotate: bool = True,
) -> BatchConfig:
    """Create a batch config from a browser/API setup object or saved setup profile."""
    if not isinstance(value, dict):
        raise TypeError("setup must be an object")
    allowed = {
        "game_type", "players", "bots", "policy", "policies", "game_rules",
        "board_rules", "seat_suspects", "shuffle_bots", "mode", "seat",
        "notebook_mode", "progress", "max_steps", "debug", "shuffle_seat", "seed",
    }
    if set(value) - allowed:
        raise ValueError(f"unsupported setup fields: {', '.join(sorted(set(value) - allowed))}")
    players = value.get("players", 4)
    if type(players) is not int or players < 2:
        raise ValueError("players must be an integer of at least two")

    if "bots" in value:
        raw_bots = value["bots"]
        if not isinstance(raw_bots, list) or len(raw_bots) != players:
            raise ValueError("bots must contain one configuration per player")
        policies: list[PolicySpec] = []
        for index, bot in enumerate(raw_bots):
            if isinstance(bot, str):
                policies.append(bot)
            elif isinstance(bot, dict):
                policies.append(BotStrategy(**bot))
            else:
                raise TypeError(
                    f"bot {index} must be a named policy or strategy object; "
                    "batch games require a bot for every seat"
                )
        policy_specs = tuple(policies)
    else:
        policy_text = value.get("policies", value.get("policy", "deductive"))
        if not isinstance(policy_text, str):
            raise TypeError("policy or policies must be text when bots are omitted")
        policy_specs = _policies_for_players(policy_text, players)

    game_type = value.get("game_type", "card_only")
    if not isinstance(game_type, str):
        raise TypeError("game_type must be text")
    raw_game_rules = value.get("game_rules", {})
    if not isinstance(raw_game_rules, dict):
        raise TypeError("game_rules must be an object")
    game_rules = GameRules(**raw_game_rules)
    raw_board_rules = value.get("board_rules", {})
    if not isinstance(raw_board_rules, dict):
        raise TypeError("board_rules must be an object")
    board_rules = BoardRules(**raw_board_rules)
    raw_suspects = value.get("seat_suspects")
    if raw_suspects is not None:
        if not isinstance(raw_suspects, list) or any(type(item) is not int for item in raw_suspects):
            raise TypeError("seat_suspects must be an array of integer character IDs")
        seat_suspects = tuple(raw_suspects)
    else:
        seat_suspects = None

    for field, choices in (
        ("mode", ("play", "spectate")),
        ("progress", ("auto", "turn", "step")),
    ):
        if field in value and value[field] not in choices:
            raise ValueError(f"{field} must be one of {', '.join(choices)}")
    if "notebook_mode" in value and value["notebook_mode"] not in {"manual", "automatic"}:
        raise ValueError("notebook_mode must be manual or automatic")
    for field in ("debug", "shuffle_bots", "shuffle_seat"):
        if field in value and type(value[field]) is not bool:
            raise TypeError(f"{field} must be true or false")
    if "seat" in value and (
        type(value["seat"]) is not int or not 0 <= value["seat"] < players
    ):
        raise ValueError("seat must identify an existing player")

    selected_seed = value.get("seed", 0) if seed is None else seed
    selected_max_steps = value.get("max_steps", 10_000) if max_steps is None else max_steps
    config = BatchConfig(
        games=games,
        policies=policy_specs,
        seed=selected_seed,
        max_steps=selected_max_steps,
        rotate=rotate,
        game_type=game_type,
        game_rules=game_rules,
        board_rules=board_rules,
        seat_suspects=seat_suspects,
        shuffle_bots=value.get("shuffle_bots", False),
    )
    config.validate()
    return config


class Deduction(TypedDict):
    player: int
    candidates: dict[str, int]
    knows_solution: bool


@dataclass
class GameResult:
    game: int
    seed: int
    policies: tuple[str, ...]
    outcome: str
    winner: int | None
    steps: int
    turns: list[int]
    suggestions: int
    passes: int
    refutations: int
    first_solution_step: list[int | None]
    final_knowledge: list[Deduction]
    error: str | None = None
    game_type: str = "card_only"
    rolls: int = 0
    moves: int = 0
    room_entries: int = 0
    passages: int = 0
    suspect_relocations: int = 0
    weapon_relocations: int = 0


class PolicySummary(TypedDict):
    seat_games: int
    completed_seats: int
    wins: int
    win_rate_per_completed_seat: float | None
    learned_solution: int
    mean_first_solution_step: float | None


class PolicyComparison(PolicySummary):
    by_seat: list[PolicySummary]


class BatchSummary(TypedDict):
    game_type: str
    requested_games: int
    started_games: int
    completed_games: int
    outcomes: dict[str, int]
    cancelled: bool
    wins_by_seat: list[int]
    policy_stats: dict[str, PolicyComparison]
    mean_turns_by_seat: list[float] | None
    mean_actions: float | None
    median_actions: float | None
    p90_actions: int | None
    mean_suggestions: float | None
    mean_passes: float | None
    mean_refutations: float | None
    mean_rolls: float | None
    mean_moves: float | None
    mean_room_entries: float | None
    mean_passages: float | None
    mean_suspect_relocations: float | None
    mean_weapon_relocations: float | None


def _policy_label(spec: PolicySpec) -> str:
    if isinstance(spec, str):
        return spec
    enabled = [item.name for item in fields(BotStrategy) if getattr(spec, item.name)]
    return f"custom:{','.join(enabled) if enabled else 'none'}"


def _policy_data(spec: PolicySpec) -> str | dict[str, bool]:
    return spec if isinstance(spec, str) else asdict(spec)


def _make_game(
    seed: int, specs: tuple[PolicySpec, ...], game: int, config: BatchConfig,
) -> tuple[Engine, tuple[Policy, ...]]:
    factory = create_board_game if config.game_type == "board" else create_game
    engine, _ = factory(
        len(specs),
        seed,
        "random",
        game_rules=config.game_rules,
        **(
            {
                "board_rules": config.board_rules,
                "seat_suspects": config.seat_suspects,
            }
            if config.game_type == "board" else {}
        ),
    )
    policies = tuple(
        CustomPolicy(random.Random(f"{seed}:{game}:{seat}"), spec)
        if isinstance(spec, BotStrategy) else
        make_policy(spec, random.Random(f"{seed}:{game}:{seat}"))
        for seat, spec in enumerate(specs)
    )
    return engine, policies


def policies_for_players(value: str, players: int) -> tuple[str, ...]:
    return _policies_for_players(value, players)


def _deductions(engine: Engine) -> list[Deduction]:
    result: list[Deduction] = []
    for player in range(engine.num_players):
        knowledge = knowledge_for(engine.view(player), engine.num_players)
        candidates = {
            category.name.lower(): sum(
                knowledge.mark_of(knowledge.envelope, card.id) is not Mark.NOT_HELD
                for card in cards
            )
            for category, cards in CARDS.items()
        }
        result.append({
            "player": player,
            "candidates": candidates,
            "knows_solution": known_solution(knowledge) is not None,
        })
    return result


def _event_data(event: Event) -> dict[str, object]:
    return {
        "kind": event.kind.name,
        "actor": event.actor,
        "combo": asdict(event.combo) if event.combo is not None else None,
        "card_id": event.card_id,
        "private_to": event.private_to,
        "dice": list(event.dice) if event.dice is not None else None,
        "location": asdict(event.location) if event.location is not None else None,
        "suspect_id": event.suspect_id,
        "weapon_id": event.weapon_id,
        "public": event.public,
    }


def _action_data(action: Action) -> dict[str, object]:
    match action:
        case Suggest(combination=combo) | Accuse(combination=combo):
            return {"kind": type(action).__name__, "combination": asdict(combo)}
        case Reveal(card_id=card_id):
            return {"kind": "Reveal", "card_id": card_id}
        case Pass() | EndTurn():
            return {"kind": type(action).__name__}
        case Move(destination=destination):
            return {"kind": "Move", "destination": asdict(destination)}
        case Roll() | UsePassage():
            return {"kind": type(action).__name__}
    raise TypeError(f"unknown action {action!r}")


def _write(stream: TextIO, record: dict[str, object]) -> None:
    def encode(value: object) -> object:
        if isinstance(value, Enum):
            return value.name
        if isinstance(value, (set, frozenset)):
            return sorted(value)
        if is_dataclass(value) and not isinstance(value, type):
            return asdict(value)
        raise TypeError(f"cannot encode {type(value).__name__}")

    stream.write(json.dumps(record, separators=(",", ":"), ensure_ascii=True, default=encode) + "\n")


def _run_game(
    game: int,
    seed: int,
    specs: tuple[PolicySpec, ...],
    config: BatchConfig,
    stream: TextIO,
    cancelled: Callable[[], bool],
) -> GameResult:
    engine, policies = _make_game(seed, specs, game, config)
    names = tuple(_policy_label(spec) for spec in specs)
    result = GameResult(
        game=game, seed=seed, policies=names, outcome="timeout", winner=None, steps=0,
        turns=[0] * len(names), suggestions=0, passes=0, refutations=0,
        first_solution_step=[None] * len(names), final_knowledge=[],
        game_type=config.game_type,
    )
    _write(stream, {
        "type": "game_start", "game": game, "seed": seed, "policies": names,
        "game_type": config.game_type,
        "policy_configs": [_policy_data(spec) for spec in specs],
        "policy_seeds": [f"{seed}:{game}:{seat}" for seat in range(len(names))],
        "solution": asdict(engine.state.solution),
        "hands": [sorted(hand) for hand in engine.state.player_hands],
        "current_player": engine.state.current_player,
        "public_cards": list(engine.state.public_cards),
        "game_rules": asdict(engine.state.game_rules),
        "board_rules": asdict(engine.state.board_rules) if engine.state.board is not None else None,
        "board_state": asdict(engine.state.board) if engine.state.board is not None else None,
    })
    try:
        knowledge = _deductions(engine)
        result.final_knowledge = knowledge
        for item in knowledge:
            if item["knows_solution"]:
                result.first_solution_step[item["player"]] = 0
        _write(stream, {"type": "initial_knowledge", "game": game, "knowledge": knowledge})
        while not engine.is_over and result.steps < config.max_steps and not cancelled():
            player = engine.to_move
            assert player is not None
            action = policies[player].choose(engine.view(player), engine.num_players, engine.legal_actions())
            try:
                events = engine.step(action)
            except IllegalActionError as exc:
                _write(stream, {
                    "type": "action_error", "game": game, "actor": player,
                    "action": _action_data(action), "error": str(exc),
                })
                raise
            result.steps += 1
            _write(stream, {
                "type": "action", "game": game, "step": result.steps, "actor": player,
                "action": _action_data(action), "events": [_event_data(event) for event in events],
            })
            result.suggestions += isinstance(action, Suggest)
            result.passes += isinstance(action, Pass)
            result.refutations += isinstance(action, Reveal)
            for event in events:
                if event.kind is EventKind.END_TURN:
                    result.turns[event.actor] += 1
                elif event.kind is EventKind.ROLL:
                    result.rolls += 1
                elif event.kind is EventKind.MOVE:
                    result.moves += 1
                    result.room_entries += int(isinstance(event.location, RoomPosition))
                elif event.kind is EventKind.PASSAGE:
                    result.passages += 1
                elif event.kind is EventKind.SUSPECT_MOVED:
                    result.suspect_relocations += 1
                elif event.kind is EventKind.WEAPON_MOVED:
                    result.weapon_relocations += 1
            if isinstance(action, Accuse) and engine.winner == player:
                result.turns[player] += 1
            # Suggestions and ordinary end-turns do not change any deduction marks.
            if any(event.kind in {EventKind.PASS, EventKind.REFUTE, EventKind.SHOW, EventKind.ACCUSE}
                   for event in events):
                try:
                    knowledge = _deductions(engine)
                    result.final_knowledge = knowledge
                except InconsistentKnowledgeError as exc:
                    _write(stream, {
                        "type": "knowledge_error", "game": game, "step": result.steps,
                        "error": str(exc),
                    })
                    raise
            for item in knowledge:
                seat = item["player"]
                if item["knows_solution"] and result.first_solution_step[seat] is None:
                    result.first_solution_step[seat] = result.steps
            _write(stream, {
                "type": "knowledge", "game": game, "step": result.steps, "knowledge": knowledge,
            })
        result.final_knowledge = knowledge
        if engine.is_over:
            result.winner = engine.winner
            result.outcome = "won" if result.winner is not None else "all_eliminated"
        elif cancelled():
            result.outcome = "cancelled"
    except (IllegalActionError, InconsistentKnowledgeError) as exc:
        result.outcome = "error"
        result.error = f"{type(exc).__name__}: {exc}"
    _write(stream, {"type": "game_result", **asdict(result)})
    return result


class _Aggregate:
    def __init__(self, config: BatchConfig):
        self.config = config
        self.outcomes: Counter[str] = Counter()
        self.wins_by_seat = [0] * len(config.policies)
        self.actions: Counter[int] = Counter()
        self.suggestions = 0
        self.passes = 0
        self.refutations = 0
        self.turns = [0] * len(config.policies)
        self.board_metrics = Counter[str]()
        self.policy_stats = {
            name: [self._empty_stats() for _ in range(len(config.policies) + 1)]
            for name in {_policy_label(spec) for spec in config.policies}
        }

    @staticmethod
    def _empty_stats() -> dict[str, int]:
        return {"seat_games": 0, "completed_seats": 0, "wins": 0,
                "learned_solution": 0, "first_sum": 0}

    def add(self, result: GameResult) -> None:
        self.outcomes[result.outcome] += 1
        completed = result.outcome in {"won", "all_eliminated"}
        if completed:
            self.actions[result.steps] += 1
            self.suggestions += result.suggestions
            self.passes += result.passes
            self.refutations += result.refutations
            if result.game_type == "board":
                for metric in (
                    "rolls", "moves", "room_entries", "passages",
                    "suspect_relocations", "weapon_relocations",
                ):
                    self.board_metrics[metric] += getattr(result, metric)
            for seat, turns in enumerate(result.turns):
                self.turns[seat] += turns
        if result.winner is not None:
            self.wins_by_seat[result.winner] += 1
        for seat, name in enumerate(result.policies):
            first = result.first_solution_step[seat]
            for stats in (self.policy_stats[name][0], self.policy_stats[name][seat + 1]):
                stats["seat_games"] += 1
                stats["completed_seats"] += int(completed)
                stats["wins"] += int(result.winner == seat)
                if first is not None:
                    stats["learned_solution"] += 1
                    stats["first_sum"] += first

    def _quantile(self, fraction: float, completed: int) -> int | None:
        if not completed:
            return None
        rank = max(1, math.ceil(fraction * completed))
        total = 0
        for value, count in sorted(self.actions.items()):
            total += count
            if total >= rank:
                return value
        raise RuntimeError("invalid action histogram")

    def summary(self, cancelled: bool) -> BatchSummary:
        completed = self.outcomes["won"] + self.outcomes["all_eliminated"]
        lower = self._quantile(0.5, completed)
        upper = self._quantile((completed // 2 + 1) / completed, completed) if completed else None
        median = (lower + upper) / 2 if lower is not None and upper is not None else None
        def summarize_stats(stats: dict[str, int]) -> PolicySummary:
            seats = stats["completed_seats"]
            learned = stats["learned_solution"]
            return {
                "seat_games": stats["seat_games"], "completed_seats": seats, "wins": stats["wins"],
                "win_rate_per_completed_seat": stats["wins"] / seats if seats else None,
                "learned_solution": learned,
                "mean_first_solution_step": stats["first_sum"] / learned if learned else None,
            }
        policies: dict[str, PolicyComparison] = {}
        for name, stats in sorted(self.policy_stats.items()):
            policies[name] = {
                **summarize_stats(stats[0]),
                "by_seat": [summarize_stats(seat) for seat in stats[1:]],
            }
        return {
            "game_type": self.config.game_type,
            "requested_games": self.config.games, "started_games": sum(self.outcomes.values()),
            "completed_games": completed,
            "outcomes": {kind: self.outcomes[kind] for kind in ("won", "all_eliminated", "timeout", "error", "cancelled")},
            "cancelled": cancelled, "wins_by_seat": list(self.wins_by_seat), "policy_stats": policies,
            "mean_turns_by_seat": [turns / completed for turns in self.turns] if completed else None,
            "mean_actions": sum(k * v for k, v in self.actions.items()) / completed if completed else None,
            "median_actions": median,
            "p90_actions": self._quantile(0.9, completed),
            "mean_suggestions": self.suggestions / completed if completed else None,
            "mean_passes": self.passes / completed if completed else None,
            "mean_refutations": self.refutations / completed if completed else None,
            "mean_rolls": self.board_metrics["rolls"] / completed if completed and self.config.game_type == "board" else None,
            "mean_moves": self.board_metrics["moves"] / completed if completed and self.config.game_type == "board" else None,
            "mean_room_entries": self.board_metrics["room_entries"] / completed if completed and self.config.game_type == "board" else None,
            "mean_passages": self.board_metrics["passages"] / completed if completed and self.config.game_type == "board" else None,
            "mean_suspect_relocations": self.board_metrics["suspect_relocations"] / completed if completed and self.config.game_type == "board" else None,
            "mean_weapon_relocations": self.board_metrics["weapon_relocations"] / completed if completed and self.config.game_type == "board" else None,
        }


def format_summary(summary: BatchSummary) -> str:
    lines = [
        f"Games: {summary['started_games']} started / {summary['requested_games']} requested",
        f"Completed: {summary['completed_games']}",
        "Outcomes: " + ", ".join(f"{name}={count}" for name, count in summary["outcomes"].items()),
        f"Wins by seat: {summary['wins_by_seat']}",
        (f"Actions (completed games): mean={summary['mean_actions']}, "
         f"median={summary['median_actions']}, p90={summary['p90_actions']}"),
        f"Mean completed turns by seat: {summary['mean_turns_by_seat']}",
        (f"Mean suggestions={summary['mean_suggestions']}, passes={summary['mean_passes']}, "
         f"refutations={summary['mean_refutations']}"),
        "Policies (win rate per completed seat; automatic-notebook deduction over all started seats):",
    ]
    if summary["game_type"] == "board":
        lines.append(
            "Mean board events (completed games): "
            f"rolls={summary['mean_rolls']}, moves={summary['mean_moves']}, "
            f"room entries={summary['mean_room_entries']}, passages={summary['mean_passages']}, "
            f"suspect relocations={summary['mean_suspect_relocations']}, "
            f"weapon relocations={summary['mean_weapon_relocations']}"
        )
    for name, stats in summary["policy_stats"].items():
        lines.append(
            f"  {name}: wins={stats['wins']}, completed seats={stats['completed_seats']}, "
            f"rate={stats['win_rate_per_completed_seat']}, learned={stats['learned_solution']}/"
            f"{stats['seat_games']}, mean first knowledge step={stats['mean_first_solution_step']}"
        )
        for seat, seat_stats in enumerate(stats["by_seat"]):
            if seat_stats["seat_games"]:
                lines.append(
                    f"    seat {seat}: wins={seat_stats['wins']}, "
                    f"completed seats={seat_stats['completed_seats']}, "
                    f"rate={seat_stats['win_rate_per_completed_seat']}, "
                    f"learned={seat_stats['learned_solution']}/{seat_stats['seat_games']}"
                )
    if summary["cancelled"]:
        lines.append("Batch cancelled.")
    return "\n".join(lines)


def run_batch(
    config: BatchConfig,
    trace_path: Path,
    *,
    progress: Callable[[BatchSummary], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    on_game: Callable[[GameResult], None] | None = None,
) -> BatchSummary:
    """Write all private traces to a new file and return aggregate statistics."""
    config.validate()
    should_cancel = cancelled if cancelled is not None else lambda: False
    aggregate = _Aggregate(config)
    with trace_path.open("x", encoding="utf-8", newline="\n") as stream:
        _write(stream, {
            "type": "batch_start", "schema_version": 2, "config": asdict(config),
            "python_version": sys.version, "private": True,
        })
        for game in range(config.games):
            if should_cancel():
                break
            seed = config.seed + (game // len(config.policies) if config.rotate else game)
            specs = list(config.policies)
            if config.shuffle_bots:
                random.Random(f"{config.seed}:{game}:bot-shuffle").shuffle(specs)
            if config.rotate:
                rotation = game % len(specs)
                specs = specs[rotation:] + specs[:rotation]
            result = _run_game(game, seed, tuple(specs), config, stream, should_cancel)
            aggregate.add(result)
            game_cancelled = result.outcome == "cancelled"
            if on_game is not None:
                on_game(result)
            if progress is not None:
                progress(aggregate.summary(should_cancel()))
            if game_cancelled:
                break
        summary = aggregate.summary(should_cancel())
        _write(stream, {"type": "batch_result", "summary": summary})
    return summary


def read_game_trace(path: Path, game: int) -> list[dict[str, object]]:
    """Load one game's records without loading the rest of the batch."""
    if game < 0:
        raise ValueError("game must be non-negative")
    result: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            if record.get("game") == game:
                result.append(record)
                if record.get("type") == "game_result":
                    break
    if not result:
        raise ValueError(f"game {game} not found in trace")
    return result
