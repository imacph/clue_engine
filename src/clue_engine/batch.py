"""Reproducible batch simulations and streaming private JSONL traces."""

import json
import math
import random
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TextIO, TypedDict

from .cards import CARDS
from .engine import Engine, IllegalActionError
from .knowledge import InconsistentKnowledgeError, Mark, knowledge_for, known_solution
from .models import Accuse, Action, EndTurn, Pass, Reveal, Suggest
from .observations import Event, EventKind
from .policies import Policy, make_policy, validate_policy_names
from .policies import policies_for_players as _policies_for_players
from .state import deal


@dataclass(frozen=True)
class BatchConfig:
    games: int
    policies: tuple[str, ...]
    seed: int = 0
    max_steps: int = 10_000
    rotate: bool = True

    def validate(self) -> None:
        if self.games < 1:
            raise ValueError("games must be at least 1")
        if len(self.policies) < 2:
            raise ValueError("at least two player policies are required")
        validate_policy_names(self.policies)
        if self.max_steps < 0:
            raise ValueError("max_steps must be non-negative")


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


def _make_game(seed: int, names: tuple[str, ...], game: int) -> tuple[Engine, tuple[Policy, ...]]:
    engine = Engine(deal(random.Random(seed), len(names)))
    policies = tuple(make_policy(name, random.Random(f"{seed}:{game}:{seat}")) for seat, name in enumerate(names))
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
    }


def _action_data(action: Action) -> dict[str, object]:
    match action:
        case Suggest(combination=combo) | Accuse(combination=combo):
            return {"kind": type(action).__name__, "combination": asdict(combo)}
        case Reveal(card_id=card_id):
            return {"kind": "Reveal", "card_id": card_id}
        case Pass() | EndTurn():
            return {"kind": type(action).__name__}
    raise TypeError(f"unknown action {action!r}")


def _write(stream: TextIO, record: dict[str, object]) -> None:
    stream.write(json.dumps(record, separators=(",", ":"), ensure_ascii=True) + "\n")


def _run_game(
    game: int,
    seed: int,
    names: tuple[str, ...],
    max_steps: int,
    stream: TextIO,
    cancelled: Callable[[], bool],
) -> GameResult:
    engine, policies = _make_game(seed, names, game)
    result = GameResult(
        game=game, seed=seed, policies=names, outcome="timeout", winner=None, steps=0,
        turns=[0] * len(names), suggestions=0, passes=0, refutations=0,
        first_solution_step=[None] * len(names), final_knowledge=[],
    )
    _write(stream, {
        "type": "game_start", "game": game, "seed": seed, "policies": names,
        "policy_seeds": [f"{seed}:{game}:{seat}" for seat in range(len(names))],
        "solution": asdict(engine.state.solution),
        "hands": [sorted(hand) for hand in engine.state.player_hands],
        "current_player": engine.state.current_player,
    })
    try:
        knowledge = _deductions(engine)
        result.final_knowledge = knowledge
        for item in knowledge:
            if item["knows_solution"]:
                result.first_solution_step[item["player"]] = 0
        _write(stream, {"type": "initial_knowledge", "game": game, "knowledge": knowledge})
        while not engine.is_over and result.steps < max_steps and not cancelled():
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
        self.policy_stats = {
            name: [self._empty_stats() for _ in range(len(config.policies) + 1)]
            for name in set(config.policies)
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
        "Policies (win rate per completed seat; deduction over all started seats):",
    ]
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
            "type": "batch_start", "schema_version": 1, "config": asdict(config),
            "python_version": sys.version, "private": True,
        })
        for game in range(config.games):
            if should_cancel():
                break
            rotation = game % len(config.policies) if config.rotate else 0
            names = config.policies[rotation:] + config.policies[:rotation]
            seed = config.seed + (game // len(names) if config.rotate else game)
            result = _run_game(game, seed, names, config.max_steps, stream, should_cancel)
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
