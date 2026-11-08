"""Offline REINFORCE training and reproducible board-policy evaluation."""

import argparse
import json
import math
import random
from pathlib import Path

from .learning_policy import FEATURE_COUNT, LearningPolicy, LinearModel
from .policies import POLICY_NAMES, Policy, make_policy, validate_policy_names
from .session import create_board_game

DEFAULT_OPPONENTS = ("deductive", "probing", "strategic")
ANALYTICAL_OPPONENTS = ("deductive", "strategic", "analytical")
TOURNAMENT_POOLS = (DEFAULT_OPPONENTS, ANALYTICAL_OPPONENTS)
MODEL_SCHEMA = 1


def save_model(path: Path, model: LinearModel, metadata: dict[str, object]) -> None:
    data = {
        "schema": MODEL_SCHEMA,
        "room_weights": model.room_weights,
        "suggestion_weights": model.suggestion_weights,
        "metadata": metadata,
    }
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, allow_nan=False)
        stream.write("\n")


def load_model(path: Path) -> LinearModel:
    data = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict) or type(data.get("schema")) is not int
        or data["schema"] != MODEL_SCHEMA
    ):
        raise ValueError("unsupported learned model schema")
    weights = []
    for key in ("room_weights", "suggestion_weights"):
        values = data.get(key)
        if not isinstance(values, list) or not all(
            type(value) in (int, float) and math.isfinite(value) for value in values
        ):
            raise ValueError(f"invalid {key}")
        weights.append(tuple(float(value) for value in values))
    return LinearModel(weights[0], weights[1])


def _validate(games: int, max_steps: int, opponents: tuple[str, ...]) -> None:
    if type(games) is not int or games < 1:
        raise ValueError("games must be a positive integer")
    if type(max_steps) is not int or max_steps < 1:
        raise ValueError("max_steps must be a positive integer")
    if len(opponents) != 3:
        raise ValueError("the benchmark requires exactly three opponents")
    validate_policy_names(opponents)


def _game(
    policy: Policy, seat: int, seed: int, opponents: tuple[str, ...], max_steps: int,
) -> tuple[int | None, int, bool]:
    engine, _ = create_board_game(4, seed, "random")
    rival_names = iter(opponents)
    policies = tuple(
        policy if position == seat else make_policy(
            next(rival_names), random.Random(f"{seed}:opponent:{position}")
        )
        for position in range(4)
    )
    for steps in range(max_steps):
        player = engine.to_move
        if player is None:
            return engine.winner, steps, False
        action = policies[player].choose(engine.view(player), 4, engine.legal_actions())
        engine.step(action)
    return engine.winner, max_steps, not engine.is_over


def train(
    *, games: int, seed: int, opponents: tuple[str, ...] = DEFAULT_OPPONENTS,
    max_steps: int = 10_000, learning_rate: float = 0.02,
    initial_model: LinearModel | None = None,
) -> tuple[LinearModel, dict[str, object]]:
    _validate(games, max_steps, opponents)
    if not math.isfinite(learning_rate) or learning_rate <= 0:
        raise ValueError("learning_rate must be positive and finite")
    model = initial_model if initial_model is not None else LinearModel.zeros()
    initial = model
    wins = timeouts = 0
    for game in range(games):
        game_seed = seed + game
        seat = game % 4
        policy = LearningPolicy(random.Random(f"{game_seed}:learner:{seat}"), model, explore=True)
        winner, _, timeout = _game(policy, seat, game_seed, opponents, max_steps)
        if timeout:
            timeouts += 1
            continue
        won = winner == seat
        wins += won
        advantage = float(won) - 0.25
        room = list(model.room_weights)
        suggestion = list(model.suggestion_weights)
        scale = learning_rate * advantage / math.sqrt(max(1, len(policy.decisions)))
        for kind, gradient in policy.decisions:
            weights = room if kind == "room" else suggestion
            for index in range(FEATURE_COUNT):
                weights[index] += scale * gradient[index]
        model = LinearModel(tuple(room), tuple(suggestion))
    return model, {
        "algorithm": "reinforce-linear-v1",
        "games": games,
        "seed": seed,
        "opponents": list(opponents),
        "max_steps": max_steps,
        "learning_rate": learning_rate,
        "initial_room_weights": list(initial.room_weights),
        "initial_suggestion_weights": list(initial.suggestion_weights),
        "wins": wins,
        "timeouts": timeouts,
    }


def _wilson(wins: int, count: int) -> tuple[float, float] | None:
    if not count:
        return None
    z = 1.959963984540054
    proportion = wins / count
    denominator = 1 + z * z / count
    center = (proportion + z * z / (2 * count)) / denominator
    radius = z * math.sqrt(proportion * (1 - proportion) / count + z * z / (4 * count * count))
    return max(0.0, center - radius / denominator), min(1.0, center + radius / denominator)


def evaluate(
    model: LinearModel, *, games: int, seed: int,
    opponents: tuple[str, ...] = DEFAULT_OPPONENTS, max_steps: int = 10_000,
    baseline: str | None = None,
) -> dict[str, object]:
    _validate(games, max_steps, opponents)
    if baseline is not None:
        validate_policy_names((baseline,))
    seats = [{"games": 0, "wins": 0, "timeouts": 0} for _ in range(4)]
    wins = losses = timeouts = 0
    for game in range(games):
        game_seed = seed + game
        seat = game % 4
        rng = random.Random(f"{game_seed}:learner:{seat}")
        policy: Policy = LearningPolicy(rng, model) if baseline is None else make_policy(baseline, rng)
        winner, _, timeout = _game(policy, seat, game_seed, opponents, max_steps)
        seats[seat]["games"] += 1
        if timeout:
            timeouts += 1
            seats[seat]["timeouts"] += 1
        elif winner == seat:
            wins += 1
            seats[seat]["wins"] += 1
        else:
            losses += 1
    completed = wins + losses
    seat_results = []
    for seat in seats:
        seat_completed = seat["games"] - seat["timeouts"]
        seat_results.append({
            **seat,
            "losses": seat_completed - seat["wins"],
            "win_rate": seat["wins"] / seat_completed if seat_completed else None,
            "win_rate_ci95": _wilson(seat["wins"], seat_completed),
        })
    return {
        "games": games, "seed": seed, "opponents": list(opponents), "baseline": baseline,
        "wins": wins, "losses": losses, "timeouts": timeouts, "seats": seat_results,
        "win_rate": wins / completed if completed else None,
        "win_rate_ci95": _wilson(wins, completed),
    }


def benchmark(
    model: LinearModel, *, games: int, seed: int, max_steps: int = 10_000,
) -> dict[str, object]:
    """Compare every named policy on identical seeds, seats, and opponent pools."""
    if type(games) is not int or games < 4 or games % 4:
        raise ValueError("benchmark games must be a positive multiple of four")
    _validate(games, max_steps, DEFAULT_OPPONENTS)
    profiles = ("learned", *POLICY_NAMES)
    reports = []
    for pool_index, opponents in enumerate(TOURNAMENT_POOLS):
        outcomes: dict[str, list[int]] = {}
        seat_wins: dict[str, list[int]] = {}
        timeouts: dict[str, int] = {}
        for profile in profiles:
            profile_outcomes = []
            profile_seat_wins = [0, 0, 0, 0]
            profile_timeouts = 0
            for game in range(games):
                game_seed = seed + pool_index * 100_000 + game
                seat = game % 4
                rng = random.Random(f"{game_seed}:learner:{seat}")
                policy: Policy = (
                    LearningPolicy(rng, model) if profile == "learned"
                    else make_policy(profile, rng)
                )
                winner, _, timeout = _game(policy, seat, game_seed, opponents, max_steps)
                won = int(not timeout and winner == seat)
                profile_outcomes.append(won)
                profile_seat_wins[seat] += won
                profile_timeouts += timeout
            outcomes[profile] = profile_outcomes
            seat_wins[profile] = profile_seat_wins
            timeouts[profile] = profile_timeouts

        profile_report = {}
        learned_outcomes = outcomes["learned"]
        paired = {}
        for profile in profiles:
            wins = sum(outcomes[profile])
            completed = games - timeouts[profile]
            profile_report[profile] = {
                "wins": wins,
                "losses": completed - wins,
                "timeouts": timeouts[profile],
                "win_rate": wins / completed if completed else None,
                "win_rate_ci95": _wilson(wins, completed),
                "seat_wins": seat_wins[profile],
            }
            if profile == "learned":
                continue
            differences = [
                learned - baseline
                for learned, baseline in zip(learned_outcomes, outcomes[profile], strict=True)
            ]
            delta = sum(differences) / games
            variance = sum((value - delta) ** 2 for value in differences) / max(1, games - 1)
            radius = 1.959963984540054 * math.sqrt(variance / games)
            paired[profile] = {
                "learned_only_wins": differences.count(1),
                "profile_only_wins": differences.count(-1),
                "ties": differences.count(0),
                "win_rate_delta": delta,
                "win_rate_delta_ci95": (max(-1.0, delta - radius), min(1.0, delta + radius)),
            }
        reports.append({
            "opponents": list(opponents),
            "games": games,
            "profiles": profile_report,
            "paired_vs_learned": paired,
        })
    return {"seed": seed, "max_steps": max_steps, "pools": reports}


def _tuning_score(
    model: LinearModel, *, games: int, seed: int, max_steps: int,
) -> tuple[float, list[dict[str, object]]]:
    reports = [
        evaluate(
            model, games=games, seed=seed + pool_index * 100_000,
            opponents=opponents, max_steps=max_steps,
        )
        for pool_index, opponents in enumerate(TOURNAMENT_POOLS)
    ]
    return sum(report["wins"] / games for report in reports) / len(reports), reports


def tune(
    *, initial_model: LinearModel, games_per_pool: int, seed: int,
    population: int = 8, generations: int = 4, max_steps: int = 10_000,
) -> tuple[LinearModel, dict[str, object]]:
    """Use common-random-number cross-entropy search over both policy heads."""
    if type(games_per_pool) is not int or games_per_pool < 4 or games_per_pool % 4:
        raise ValueError("games_per_pool must be a positive multiple of four")
    if type(population) is not int or population < 4:
        raise ValueError("population must be an integer of at least four")
    if type(generations) is not int or generations < 1:
        raise ValueError("generations must be a positive integer")
    _validate(games_per_pool, max_steps, DEFAULT_OPPONENTS)

    def flatten(model: LinearModel) -> tuple[float, ...]:
        return (*model.room_weights, *model.suggestion_weights)

    def expand(values: tuple[float, ...]) -> LinearModel:
        return LinearModel(values[:FEATURE_COUNT], values[FEATURE_COUNT:])

    initial_values = flatten(initial_model)
    center = list(initial_values)
    room_sigma = (0.75, 0.75, 0.75, 0.5, 1.5, 0.75, 0.4, 0.75)
    suggestion_sigma = (1.25, 1.25, 1.25, 0.75, 1.0, 1.0, 0.75, 0.75)
    sigma = [*room_sigma, *suggestion_sigma]
    minimum_sigma = [item * 0.12 for item in sigma]
    rng = random.Random(f"{seed}:cross-entropy")
    best_model = initial_model
    initial_score: float | None = None
    best_score = float("-inf")
    generation_reports = []

    for generation in range(generations):
        generation_seed = seed + generation * 10_000_000
        candidates = [tuple(center)]
        for _ in range(population - 1):
            candidates.append(tuple(
                max(-12.0, min(12.0, value + rng.gauss(0, spread)))
                for value, spread in zip(center, sigma, strict=True)
            ))
        scored = []
        for index, values in enumerate(candidates):
            candidate = expand(values)
            score, pool_reports = _tuning_score(
                candidate, games=games_per_pool, seed=generation_seed, max_steps=max_steps,
            )
            scored.append((score, index, values, pool_reports))
            if generation == 0 and index == 0:
                initial_score = score
            if score > best_score:
                best_score = score
                best_model = candidate
        scored.sort(key=lambda result: (-result[0], result[1]))
        elite_count = max(2, population // 4)
        elites = scored[:elite_count]
        center = [
            sum(values[index] for _, _, values, _ in elites) / elite_count
            for index in range(FEATURE_COUNT * 2)
        ]
        elite_sigma = [
            math.sqrt(sum((values[index] - center[index]) ** 2 for _, _, values, _ in elites)
                      / elite_count)
            for index in range(FEATURE_COUNT * 2)
        ]
        sigma = [
            max(minimum_sigma[index], 0.65 * sigma[index] + 0.35 * elite_sigma[index])
            for index in range(FEATURE_COUNT * 2)
        ]
        generation_reports.append({
            "generation": generation + 1,
            "seed": generation_seed,
            "best_score": scored[0][0],
            "mean_score": sum(score for score, _, _, _ in scored) / population,
            "incumbent_score": next(score for score, index, _, _ in scored if index == 0),
            "incumbent_rank": next(
                rank for rank, (_, index, _, _) in enumerate(scored, 1) if index == 0
            ),
            "elite_count": elite_count,
            "pool_scores": [
                {
                    "opponents": report["opponents"],
                    "wins": report["wins"],
                    "games": report["games"],
                }
                for report in scored[0][3]
            ],
        })
    return best_model, {
        "algorithm": "common-random-cross-entropy-v1",
        "seed": seed,
        "population": population,
        "generations": generations,
        "games_per_pool": games_per_pool,
        "max_steps": max_steps,
        "opponent_pools": [list(pool) for pool in TOURNAMENT_POOLS],
        "initial_score": initial_score,
        "best_score": best_score,
        "generation_history": generation_reports,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("train", "evaluate"):
        child = commands.add_parser(command)
        child.add_argument("--games", type=int, required=True)
        child.add_argument("--seed", type=int, required=True)
        child.add_argument("--max-steps", type=int, default=10_000)
        child.add_argument("--opponents", default=",".join(DEFAULT_OPPONENTS))
        if command == "train":
            child.add_argument("--output", type=Path, required=True)
            child.add_argument("--learning-rate", type=float, default=0.02)
            child.add_argument("--initial", type=Path)
        else:
            child.add_argument("--model", type=Path, required=True)
            child.add_argument("--baseline")
    tuner = commands.add_parser("tune")
    tuner.add_argument("--initial", type=Path, required=True)
    tuner.add_argument("--output", type=Path, required=True)
    tuner.add_argument("--games-per-pool", type=int, default=16)
    tuner.add_argument("--seed", type=int, required=True)
    tuner.add_argument("--population", type=int, default=8)
    tuner.add_argument("--generations", type=int, default=4)
    tuner.add_argument("--max-steps", type=int, default=10_000)
    tournament = commands.add_parser("benchmark")
    tournament.add_argument("--model", type=Path, required=True)
    tournament.add_argument("--games", type=int, default=64)
    tournament.add_argument("--seed", type=int, required=True)
    tournament.add_argument("--max-steps", type=int, default=10_000)
    args = parser.parse_args(argv)
    if args.command == "train":
        opponents = tuple(name.strip() for name in args.opponents.split(","))
        model, summary = train(
            games=args.games, seed=args.seed, opponents=opponents, max_steps=args.max_steps,
            learning_rate=args.learning_rate,
            initial_model=load_model(args.initial) if args.initial else None,
        )
        save_model(args.output, model, summary)
    elif args.command == "evaluate":
        opponents = tuple(name.strip() for name in args.opponents.split(","))
        summary = evaluate(
            load_model(args.model), games=args.games, seed=args.seed, opponents=opponents,
            max_steps=args.max_steps, baseline=args.baseline,
        )
    elif args.command == "tune":
        model, summary = tune(
            initial_model=load_model(args.initial), games_per_pool=args.games_per_pool,
            seed=args.seed, population=args.population, generations=args.generations,
            max_steps=args.max_steps,
        )
        save_model(args.output, model, summary)
    else:
        summary = benchmark(
            load_model(args.model), games=args.games, seed=args.seed, max_steps=args.max_steps,
        )
    print(json.dumps(summary, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
