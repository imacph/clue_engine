"""Seat-level charts derived from batch results and their private traces."""

import json
from collections import Counter, defaultdict
from pathlib import Path

from ..batch import GameResult
from ..distributions import Distribution, DistributionBin, _numeric_summary


def _matching_seats(policies: tuple[str, ...] | list[str], policy: str | None, seat: int | None):
    return [
        index for index, name in enumerate(policies)
        if (policy is None or policy == name) and (seat is None or seat == index)
    ]


def _histogram(title: str, counts: Counter[int], width: int, denominator: str, details: str):
    samples = sum(counts.values())
    grouped: Counter[int] = Counter()
    for value, count in counts.items():
        grouped[value // width * width] += count
    bins = tuple(
        DistributionBin(
            str(start) if width == 1 else f"{start}-{start + width - 1}",
            count, count / samples,
        )
        for start, count in sorted(grouped.items())
    )
    return Distribution(title, denominator, samples, details, bins, _numeric_summary(counts))


def seat_turns(results: list[GameResult], policy: str | None, seat: int | None, width: int):
    counts: Counter[int] = Counter()
    excluded = 0
    for result in results:
        seats = _matching_seats(result.policies, policy, seat)
        if result.outcome not in {"won", "all_eliminated"}:
            excluded += len(seats)
            continue
        counts.update(result.turns[index] for index in seats)
    return _histogram(
        "Turns per seat", counts, width, "completed matching seat appearances",
        f"Each matching seat counts once; {excluded} incomplete seat appearances excluded.",
    )


def seat_comparison(results: list[GameResult], policy: str | None, seat: int | None, metric: str):
    """Compare matching seat appearances using the denominator for each metric."""
    titles = {
        "seat_compare_turns": ("Mean turns by seat", "turns"),
        "seat_compare_win_rate": ("Win rate by seat", "%"),
        "seat_compare_learned_rate": ("Solution learned rate by seat", "%"),
        "seat_compare_first_action": ("Mean first solution action by seat", "actions"),
    }
    title, unit = titles[metric]
    appearances: dict[int, list[GameResult]] = defaultdict(list)
    for result in results:
        for index in _matching_seats(result.policies, policy, seat):
            appearances[index].append(result)

    bars = []
    excluded = 0
    missing = 0
    for index, games in sorted(appearances.items()):
        completed = [game for game in games if game.outcome in {"won", "all_eliminated"}]
        learned = [game.first_solution_step[index] for game in games
                   if game.first_solution_step[index] is not None]
        missing += len(games) - len(learned)
        if metric in {"seat_compare_turns", "seat_compare_win_rate"}:
            excluded += len(games) - len(completed)
            samples = len(completed)
            if metric == "seat_compare_turns":
                total = sum(game.turns[index] for game in completed)
            else:
                total = 100 * sum(game.outcome == "won" and game.winner == index
                                  for game in completed)
        elif metric == "seat_compare_learned_rate":
            samples = len(games)
            total = 100 * len(learned)
        else:
            samples = len(learned)
            total = sum(learned)
        bars.append({"seat": index, "value": total / samples if samples else None, "samples": samples})

    if metric in {"seat_compare_turns", "seat_compare_win_rate"}:
        details = (
            "Each sample is a completed matching seat appearance (won or all eliminated); "
            f"{excluded} incomplete matching appearances excluded. "
            "Values are unavailable for observed seats without completed appearances."
        )
    elif metric == "seat_compare_learned_rate":
        details = (
            "Each sample is a matching seat appearance, including incomplete games; "
            f"{missing} appearances were not recorded as learned and count as not learned. "
            "No matching appearances are excluded."
        )
    else:
        details = (
            "Each sample is a matching appearance recorded as learned, including incomplete games; "
            f"{missing} appearances not recorded as learned are excluded. "
            "Values are unavailable for observed seats without recorded learning."
        )
    return {"title": title, "details": details, "seat_bars": bars, "unit": unit}


def knowledge_charts(path: Path, policy: str | None, seat: int | None, width: int, metric: str):
    """Aggregate the last knowledge snapshot at each seat's own turn."""
    series: dict[int, list[int]] = defaultdict(list)
    first_turns: Counter[int] = Counter()
    exposures = 0
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            kind = record["type"]
            if kind == "game_start":
                seats = _matching_seats(record["policies"], policy, seat)
                solution = record["solution"]
                turns = [0] * len(record["policies"])
                snapshots = {index: {} for index in seats}
                first: dict[int, int] = {}
            elif kind == "action":
                for event in record["events"]:
                    if event["kind"] == "END_TURN":
                        turns[event["actor"]] += 1
                if (record["action"]["kind"] == "Accuse"
                        and record["action"]["combination"] == solution):
                    turns[record["actor"]] += 1
            elif kind in {"initial_knowledge", "knowledge"}:
                for item in record["knowledge"]:
                    index = item["player"]
                    if index not in snapshots:
                        continue
                    turn = turns[index]
                    candidates = sum(item["candidates"].values())
                    snapshots[index][turn] = (candidates, item["knows_solution"])
                    if item["knows_solution"] and index not in first:
                        first[index] = turn
            elif kind == "game_result":
                exposures += len(seats)
                first_turns.update(first.values())
                for seat_snapshots in snapshots.values():
                    for turn, (candidates, learned) in seat_snapshots.items():
                        series[turn].append(int(learned) if metric == "knowledge_learned" else candidates)
    if metric == "solution_turn":
        learned = sum(first_turns.values())
        return _histogram(
            "First solution turn", first_turns, width, "seat appearances recorded as learned",
            f"{exposures} matching seat appearances; {exposures - learned} not recorded as learned (includes incomplete games).",
        )
    points = [
        {"turn": turn, "samples": len(values), "mean": sum(values) / len(values),
         "minimum": min(values), "maximum": max(values)}
        for turn, values in sorted(series.items())
    ]
    return {
        "title": "Solution learned over turns" if metric == "knowledge_learned" else "Remaining candidates over turns",
        "details": "Last recorded knowledge at each seat's own completed-turn count; later turns include only seats still observed. Includes incomplete games.",
        "points": points,
        "percent": metric == "knowledge_learned",
    }
