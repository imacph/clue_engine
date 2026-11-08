"""Streaming empirical distributions for batch results and saved traces."""

import json
import math
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .batch import GameResult

BOARD_METRICS = (
    "rolls", "moves", "room_entries", "passages",
    "suspect_relocations", "weapon_relocations",
)
METRIC_TITLES = {
    "rolls": "Board dice rolls",
    "moves": "Board movement actions",
    "room_entries": "Room entries",
    "passages": "Secret passage uses",
    "suspect_relocations": "Suspect relocations",
    "weapon_relocations": "Weapon relocations",
}
METRICS = ("actions", "turns", "outcomes", "deduction", *BOARD_METRICS)
MODES = ("count", "percent")
OUTCOMES = ("won", "all_eliminated", "timeout", "error", "cancelled")


@dataclass(frozen=True)
class DistributionBin:
    label: str
    count: int
    probability: float


@dataclass(frozen=True)
class NumericSummary:
    minimum: int
    maximum: int
    mean: float
    median: float
    p90: int


@dataclass(frozen=True)
class Distribution:
    title: str
    denominator: str
    samples: int
    details: str
    bins: tuple[DistributionBin, ...]
    numeric_summary: NumericSummary | None = None


def _numeric_summary(counts: Counter[int]) -> NumericSummary | None:
    samples = sum(counts.values())
    if not samples:
        return None
    ordered = sorted(counts.items())

    def at_rank(rank: int) -> int:
        seen = 0
        for value, count in ordered:
            seen += count
            if seen >= rank:
                return value
        raise RuntimeError("invalid distribution counts")

    return NumericSummary(
        minimum=ordered[0][0], maximum=ordered[-1][0],
        mean=sum(value * count for value, count in ordered) / samples,
        median=(at_rank((samples + 1) // 2) + at_rank(samples // 2 + 1)) / 2,
        p90=at_rank(math.ceil(0.9 * samples)),
    )


def validate_distribution_options(
    metric: str, width: int, policy: str | None = None, seat: int | None = None,
) -> None:
    if metric not in METRICS:
        raise ValueError(f"unknown metric: {metric}")
    if width < 1:
        raise ValueError("bin width must be at least 1")
    if seat is not None and seat < 0:
        raise ValueError("seat must be non-negative")
    if policy is not None and not policy.strip():
        raise ValueError("policy filter must not be empty")
    if metric != "deduction" and (policy is not None or seat is not None):
        raise ValueError("policy and seat filters apply only to deduction")


class Distributions:
    """Accumulate counts without retaining individual games."""

    def __init__(self) -> None:
        self.outcomes: Counter[str] = Counter()
        self.actions: Counter[int] = Counter()
        self.turns: Counter[int] = Counter()
        self.board_metrics = {metric: Counter[int]() for metric in BOARD_METRICS}
        self.first_steps: dict[tuple[str, int], Counter[int]] = {}
        self.exposures: Counter[tuple[str, int]] = Counter()
        self.incomplete_games = 0
        self.missing_batch_result = False

    def add_game(self, result: GameResult) -> None:
        self._add(
            result.outcome, result.steps, result.turns, result.policies, result.first_solution_step,
            game_type=result.game_type,
            board_metrics={metric: getattr(result, metric) for metric in BOARD_METRICS},
        )

    def _add(
        self, outcome: str, steps: int, turns: Sequence[int], policies: Sequence[str],
        first_steps: Sequence[int | None],
        *,
        game_type: str = "card_only",
        board_metrics: dict[str, int] | None = None,
    ) -> None:
        if outcome not in OUTCOMES:
            raise ValueError(f"unknown outcome: {outcome}")
        if game_type not in {"card_only", "board"}:
            raise ValueError(f"unknown game type: {game_type}")
        metrics = board_metrics or {}
        if set(metrics) - set(BOARD_METRICS) or any(
            type(value) is not int or value < 0 for value in metrics.values()
        ):
            raise ValueError("invalid board metrics")
        if game_type == "card_only" and any(metrics.values()):
            raise ValueError("card-only results cannot contain board metrics")
        if steps < 0 or len(turns) < 2 or len(turns) != len(policies) or len(turns) != len(first_steps):
            raise ValueError("invalid game result lengths or action count")
        if any(turn < 0 for turn in turns) or sum(turns) > steps or any(
            step is not None and (step < 0 or step > steps) for step in first_steps
        ):
            raise ValueError("invalid turn count or first-solution step")
        if any(not name for name in policies):
            raise ValueError("invalid policy name")
        self.outcomes[outcome] += 1
        if outcome in {"won", "all_eliminated"}:
            self.actions[steps] += 1
            self.turns[turns[0]] += 1
            if game_type == "board":
                for metric in BOARD_METRICS:
                    self.board_metrics[metric][metrics.get(metric, 0)] += 1
        for seat, (name, first) in enumerate(zip(policies, first_steps, strict=True)):
            key = (name, seat)
            self.exposures[key] += 1
            if first is not None:
                self.first_steps.setdefault(key, Counter())[first] += 1

    def chart(
        self, metric: str, *, width: int = 10, policy: str | None = None, seat: int | None = None,
    ) -> Distribution:
        validate_distribution_options(metric, width, policy, seat)
        incomplete = ""
        if self.incomplete_games:
            incomplete += f" {self.incomplete_games} started game without a result is excluded."
        if self.missing_batch_result:
            incomplete += " Trace has no batch_result."

        if metric == "outcomes":
            samples = sum(self.outcomes.values())
            bins = tuple(
                DistributionBin(name, self.outcomes[name], self.outcomes[name] / samples if samples else 0.0)
                for name in OUTCOMES
            )
            return Distribution(
                "Outcomes", "recorded game results", samples,
                "Includes timeouts, errors, and cancellations." + incomplete, bins,
            )
        if metric == "deduction":
            counts: Counter[int] = Counter()
            exposures = 0
            for key, total in self.exposures.items():
                name, player = key
                if (policy is None or policy == name) and (seat is None or seat == player):
                    exposures += total
                    counts.update(self.first_steps.get(key, Counter()))
            samples = sum(counts.values())
            policy_label = policy if policy is not None else "all"
            seat_label = str(seat) if seat is not None else "all"
            title = f"First solution action (policy={policy_label}, seat={seat_label})"
            denominator = "seat exposures recorded as learned"
            details = (
                f"{exposures} seat exposures; {exposures - samples} not recorded as learned "
                "(includes partial games)." + incomplete
            )
        elif metric in BOARD_METRICS:
            counts = self.board_metrics[metric]
            samples = sum(counts.values())
            title = METRIC_TITLES[metric]
            denominator = "completed board games"
            details = (
                f"Excluded: timeout={self.outcomes['timeout']}, error={self.outcomes['error']}, "
                f"cancelled={self.outcomes['cancelled']}." + incomplete
            )
        else:
            counts = self.actions if metric == "actions" else self.turns
            samples = sum(counts.values())
            title = "Game actions" if metric == "actions" else "Player 0 completed turns"
            denominator = "completed games"
            details = (
                f"Excluded: timeout={self.outcomes['timeout']}, error={self.outcomes['error']}, "
                f"cancelled={self.outcomes['cancelled']}." + incomplete
            )
        grouped: Counter[int] = Counter()
        for value, count in counts.items():
            grouped[value // width * width] += count
        bins = tuple(
            DistributionBin(
                str(start) if width == 1 else f"{start}-{start + width - 1}",
                count, count / samples if samples else 0.0,
            )
            for start, count in sorted(grouped.items())
        )
        return Distribution(
            title, denominator, samples, details + " Empty bins omitted.", bins,
            _numeric_summary(counts),
        )


def format_distribution(chart: Distribution, *, mode: str = "count") -> str:
    if mode not in MODES:
        raise ValueError(f"unknown distribution mode: {mode}")
    lines = [
        f"Distribution: {chart.title}",
        f"Denominator: {chart.samples} {chart.denominator}",
        chart.details,
    ]
    if not chart.samples:
        lines.append("No observations.")
        return "\n".join(lines)
    maximum = max(row.count for row in chart.bins)
    for row in chart.bins:
        length = round(row.count / maximum * 40) if maximum else 0
        value = str(row.count) if mode == "count" else f"{row.probability * 100:.1f}%"
        lines.append(f"{row.label:>15} | {'#' * length} {value}")
    return "\n".join(lines)


def _integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field} must be an integer")
    return value


def _read_result(data: Distributions, record: dict[str, object], schema_version: int) -> None:
    outcome = record.get("outcome")
    turns = record.get("turns")
    policies = record.get("policies")
    first = record.get("first_solution_step")
    if not isinstance(outcome, str) or not isinstance(turns, list) or not isinstance(policies, list):
        raise TypeError("missing outcome, turns, or policies")
    if not isinstance(first, list) or any(not isinstance(name, str) for name in policies):
        raise TypeError("invalid first-solution steps or policies")
    game_type = record.get("game_type", "card_only")
    if not isinstance(game_type, str):
        raise TypeError("game_type must be text")
    board_metrics = {
        metric: _integer(record.get(metric, 0), metric)
        for metric in BOARD_METRICS
    } if schema_version >= 2 else None
    data._add(
        outcome,
        _integer(record.get("steps"), "steps"),
        [_integer(turn, "turn") for turn in turns],
        policies,
        [_integer(step, "first-solution step") if step is not None else None for step in first],
        game_type=game_type,
        board_metrics=board_metrics,
    )


def read_distributions(
    path: Path, *, cancelled: Callable[[], bool] | None = None,
) -> Distributions:
    """Read supported batch trace versions without retaining action histories."""
    data = Distributions()
    header = False
    schema_version = 0
    finished = False
    active: int | None = None
    last_game = -1
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if cancelled is not None and cancelled():
                raise RuntimeError("trace loading cancelled")
            try:
                record = json.loads(line)
                if not isinstance(record, dict) or not isinstance(record.get("type"), str):
                    raise TypeError("record must be an object with a type")
                kind = record["type"]
                if not header:
                    schema_version = _integer(record.get("schema_version"), "schema_version")
                    if kind != "batch_start" or schema_version not in {1, 2}:
                        raise ValueError("expected schema-1 or schema-2 batch_start")
                    header = True
                elif finished:
                    raise ValueError("records follow batch_result")
                elif kind == "game_start":
                    game = _integer(record.get("game"), "game")
                    if active is not None or game <= last_game:
                        raise ValueError("unexpected game_start")
                    active = game
                    last_game = game
                elif kind == "game_result":
                    game = _integer(record.get("game"), "game")
                    if active is None or game != active:
                        raise ValueError("game_result does not match game_start")
                    _read_result(data, record, schema_version)
                    active = None
                elif kind == "batch_result":
                    if active is not None:
                        raise ValueError("batch_result precedes game_result")
                    finished = True
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid trace at line {line_number}: {exc}") from exc
    if not header:
        raise ValueError("trace is empty")
    data.incomplete_games = int(active is not None)
    data.missing_batch_result = not finished
    return data
