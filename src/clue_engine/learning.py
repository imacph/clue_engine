"""Offline REINFORCE training and reproducible board-policy evaluation."""

import argparse
import json
import math
import os
import random
from dataclasses import asdict
from pathlib import Path

from .game_settings import (
    DEFAULT_BOARD_RULES,
    DEFAULT_LEARNED_STRATEGY,
    BoardRules,
    LearnedStrategy,
    training_board_rules,
)
from .learning_policy import (
    ACCUSATION_FEATURE_COUNT,
    FEATURE_COUNT,
    LearningPolicy,
    LinearModel,
)
from .opponent_model import OpponentModel
from .opponent_model import load_model as load_opponent_model
from .policies import POLICY_NAMES, Policy, make_policy, validate_policy_names
from .session import create_board_game

DEFAULT_OPPONENTS = ("deductive", "probing", "strategic")
ANALYTICAL_OPPONENTS = ("deductive", "strategic", "analytical")
TOURNAMENT_POOLS = (DEFAULT_OPPONENTS, ANALYTICAL_OPPONENTS)
MODEL_SCHEMA = 3
LEGACY_FEATURE_COUNT = 8
DEFAULT_WIN_SPEED = 0.001


def save_model(path: Path, model: LinearModel, metadata: dict[str, object]) -> None:
    data = {
        "schema": MODEL_SCHEMA,
        "room_weights": model.room_weights,
        "suggestion_weights": model.suggestion_weights,
        "accusation_weights": model.accusation_weights,
        "metadata": metadata,
    }
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, allow_nan=False)
        stream.write("\n")


def load_model(path: Path) -> LinearModel:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or type(data.get("schema")) is not int:
        raise ValueError("unsupported learned model schema")
    schema = data["schema"]
    if schema not in (1, 2, MODEL_SCHEMA):
        raise ValueError("unsupported learned model schema")
    expected_count = LEGACY_FEATURE_COUNT if schema == 1 else FEATURE_COUNT
    weights = []
    for key in ("room_weights", "suggestion_weights"):
        values = data.get(key)
        if (
            not isinstance(values, list) or len(values) != expected_count or not all(
            type(value) in (int, float) and math.isfinite(value) for value in values
            )
        ):
            raise ValueError(f"invalid {key}")
        converted = tuple(float(value) for value in values)
        if schema == 1:
            converted += (0.0,) * (FEATURE_COUNT - LEGACY_FEATURE_COUNT)
        weights.append(converted)
    if schema == MODEL_SCHEMA:
        values = data.get("accusation_weights")
        if (
            not isinstance(values, list) or len(values) != ACCUSATION_FEATURE_COUNT
            or not all(type(value) in (int, float) and math.isfinite(value) for value in values)
        ):
            raise ValueError("invalid accusation_weights")
        accusation = tuple(float(value) for value in values)
    else:
        accusation = (0.0,) * ACCUSATION_FEATURE_COUNT
    return LinearModel(weights[0], weights[1], accusation)


def load_default_model() -> LinearModel:
    """Load the explicitly configured model, or the one shipped with the package."""
    override = os.environ.get("CLUE_LEARNED_MODEL")
    if override is not None:
        if not override.strip():
            raise ValueError("CLUE_LEARNED_MODEL must name a model file")
        return load_model(Path(override))
    return load_model(Path(__file__).with_name("learned_model.json"))


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
    *, board_rules: BoardRules = DEFAULT_BOARD_RULES,
) -> tuple[int | None, int, bool]:
    engine, _ = create_board_game(4, seed, "random", board_rules=board_rules)
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
    win_speed: float = DEFAULT_WIN_SPEED,
    opponent_model: OpponentModel | None = None,
    boards: str = "standard",
) -> tuple[LinearModel, dict[str, object]]:
    _validate(games, max_steps, opponents)
    training_board_rules(boards, 0)
    if not math.isfinite(learning_rate) or learning_rate <= 0:
        raise ValueError("learning_rate must be positive and finite")
    if not math.isfinite(win_speed) or win_speed < 0:
        raise ValueError("win_speed must be non-negative and finite")
    model = initial_model if initial_model is not None else LinearModel.zeros()
    initial = model
    wins = timeouts = 0
    for game in range(games):
        game_seed = seed + game
        seat = game % 4
        policy = LearningPolicy(
            random.Random(f"{game_seed}:learner:{seat}"), model, explore=True,
            opponent_model=opponent_model,
        )
        game_options = {"board_rules": training_board_rules(boards, game)} if boards != "standard" else {}
        winner, steps, timeout = _game(policy, seat, game_seed, opponents, max_steps, **game_options)
        if timeout:
            timeouts += 1
            continue
        won = winner == seat
        wins += won
        advantage = _win_reward(steps, win_speed) * won - 0.25
        room = list(model.room_weights)
        suggestion = list(model.suggestion_weights)
        accusation = list(model.accusation_weights)
        scale = learning_rate * advantage
        for kind, gradient in policy.decisions:
            weights = {"room": room, "suggestion": suggestion, "accusation": accusation}[kind]
            for index in range(len(weights)):
                weights[index] += scale * gradient[index]
        model = LinearModel(tuple(room), tuple(suggestion), tuple(accusation))
    return model, {
        "algorithm": "reinforce-linear-v2",
        "games": games,
        "seed": seed,
        "opponents": list(opponents),
        "boards": boards,
        "max_steps": max_steps,
        "learning_rate": learning_rate,
        "initial_room_weights": list(initial.room_weights),
        "initial_suggestion_weights": list(initial.suggestion_weights),
        "initial_accusation_weights": list(initial.accusation_weights),
        "win_speed": win_speed,
        "opponent_model": asdict(opponent_model) if opponent_model is not None else None,
        "wins": wins,
        "timeouts": timeouts,
    }


def _win_reward(steps: int, win_speed: float) -> float:
    return 1.0 / (1.0 + win_speed * steps)


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
    strategy: LearnedStrategy = DEFAULT_LEARNED_STRATEGY,
    opponent_model: OpponentModel | None = None,
    boards: str = "standard",
) -> dict[str, object]:
    _validate(games, max_steps, opponents)
    training_board_rules(boards, 0)
    if baseline is not None:
        validate_policy_names((baseline,))
        if strategy != DEFAULT_LEARNED_STRATEGY:
            raise ValueError("learned strategy settings cannot be used with a baseline policy")
        if opponent_model is not None:
            raise ValueError("opponent model cannot be used with a baseline policy")
    seats = [{"games": 0, "wins": 0, "timeouts": 0} for _ in range(4)]
    wins = losses = timeouts = 0
    win_reward = 0.0
    winning_steps = 0
    opponent_model_choices = opponent_model_weightings = 0
    for game in range(games):
        game_seed = seed + game
        seat = game % 4
        rng = random.Random(f"{game_seed}:learner:{seat}")
        policy: Policy = (
            LearningPolicy(rng, model, strategy=strategy, opponent_model=opponent_model)
            if baseline is None else make_policy(baseline, rng)
        )
        game_options = {"board_rules": training_board_rules(boards, game)} if boards != "standard" else {}
        winner, steps, timeout = _game(policy, seat, game_seed, opponents, max_steps, **game_options)
        if isinstance(policy, LearningPolicy):
            opponent_model_choices += policy.opponent_model_choices
            opponent_model_weightings += policy.opponent_model_weightings
        seats[seat]["games"] += 1
        if timeout:
            timeouts += 1
            seats[seat]["timeouts"] += 1
        elif winner == seat:
            wins += 1
            winning_steps += steps
            win_reward += _win_reward(steps, DEFAULT_WIN_SPEED)
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
        "games": games, "seed": seed, "opponents": list(opponents), "baseline": baseline, "boards": boards,
        "strategy": asdict(strategy) if baseline is None else None,
        "opponent_model": asdict(opponent_model) if opponent_model is not None else None,
        "wins": wins, "losses": losses, "timeouts": timeouts, "seats": seat_results,
        "win_rate": wins / completed if completed else None,
        "win_rate_ci95": _wilson(wins, completed),
        "mean_winning_steps": winning_steps / wins if wins else None,
        "speed_adjusted_win_score": win_reward / games,
        "opponent_model_choices": opponent_model_choices,
        "opponent_model_weightings": opponent_model_weightings,
    }


def benchmark(
    model: LinearModel, *, games: int, seed: int, max_steps: int = 10_000,
    incumbent: LinearModel | None = None,
    opponent_model: OpponentModel | None = None,
    boards: str = "standard",
) -> dict[str, object]:
    """Compare every named policy on identical seeds, seats, and opponent pools."""
    if type(games) is not int or games < 4 or games % 4:
        raise ValueError("benchmark games must be a positive multiple of four")
    _validate(games, max_steps, DEFAULT_OPPONENTS)
    training_board_rules(boards, 0)
    profiles = (
        "learned", *(("incumbent",) if incumbent is not None else ()), *POLICY_NAMES,
    )
    reports = []
    for pool_index, opponents in enumerate(TOURNAMENT_POOLS):
        outcomes: dict[str, list[int | None]] = {}
        seat_wins: dict[str, list[int]] = {}
        timeouts: dict[str, int] = {}
        winning_steps: dict[str, int] = {}
        rewards: dict[str, float] = {}
        model_activity: dict[str, tuple[int, int]] = {}
        for profile in profiles:
            profile_outcomes = []
            profile_seat_wins = [0, 0, 0, 0]
            profile_timeouts = 0
            profile_winning_steps = 0
            profile_reward = 0.0
            profile_choices = profile_weightings = 0
            for game in range(games):
                game_seed = seed + pool_index * 100_000 + game
                seat = game % 4
                rng = random.Random(f"{game_seed}:learner:{seat}")
                if profile == "learned":
                    policy: Policy = LearningPolicy(rng, model, opponent_model=opponent_model)
                elif profile == "incumbent":
                    assert incumbent is not None
                    policy = LearningPolicy(rng, incumbent)
                else:
                    policy = make_policy(profile, rng)
                game_options = {"board_rules": training_board_rules(boards, game)} if boards != "standard" else {}
                winner, steps, timeout = _game(policy, seat, game_seed, opponents, max_steps, **game_options)
                if isinstance(policy, LearningPolicy):
                    profile_choices += policy.opponent_model_choices
                    profile_weightings += policy.opponent_model_weightings
                won = None if timeout else int(winner == seat)
                profile_outcomes.append(won)
                profile_seat_wins[seat] += won or 0
                profile_timeouts += timeout
                if won:
                    profile_winning_steps += steps
                    profile_reward += _win_reward(steps, DEFAULT_WIN_SPEED)
            outcomes[profile] = profile_outcomes
            seat_wins[profile] = profile_seat_wins
            timeouts[profile] = profile_timeouts
            winning_steps[profile] = profile_winning_steps
            rewards[profile] = profile_reward
            model_activity[profile] = (profile_choices, profile_weightings)

        profile_report = {}
        learned_outcomes = outcomes["learned"]
        paired = {}
        for profile in profiles:
            wins = sum(won for won in outcomes[profile] if won is not None)
            completed = games - timeouts[profile]
            profile_report[profile] = {
                "wins": wins,
                "losses": completed - wins,
                "timeouts": timeouts[profile],
                "win_rate": wins / completed if completed else None,
                "win_rate_ci95": _wilson(wins, completed),
                "seat_wins": seat_wins[profile],
                "mean_winning_steps": winning_steps[profile] / wins if wins else None,
                "speed_adjusted_win_score": rewards[profile] / games,
                "opponent_model_choices": model_activity[profile][0],
                "opponent_model_weightings": model_activity[profile][1],
            }
            if profile == "learned":
                continue
            differences = [
                learned - baseline
                for learned, baseline in zip(learned_outcomes, outcomes[profile], strict=True)
                if learned is not None and baseline is not None
            ]
            pairs = len(differences)
            delta = sum(differences) / pairs if pairs else None
            if delta is not None and pairs > 1:
                variance = sum((value - delta) ** 2 for value in differences) / (pairs - 1)
                radius = 1.959963984540054 * math.sqrt(variance / pairs)
                interval = (max(-1.0, delta - radius), min(1.0, delta + radius))
            else:
                interval = None
            paired[profile] = {
                "learned_only_wins": differences.count(1),
                "profile_only_wins": differences.count(-1),
                "ties": differences.count(0),
                "completed_pairs": pairs,
                "excluded_pairs": games - pairs,
                "win_rate_delta": delta,
                "win_rate_delta_ci95": interval,
            }
        reports.append({
            "opponents": list(opponents),
            "games": games,
            "profiles": profile_report,
            "paired_vs_learned": paired,
        })
    return {
        "seed": seed, "max_steps": max_steps, "boards": boards, "pools": reports,
        "opponent_model": asdict(opponent_model) if opponent_model is not None else None,
    }


def _tuning_score(
    model: LinearModel, *, games: int, seed: int, max_steps: int,
    opponent_model: OpponentModel | None = None,
    boards: str = "standard",
    pools: tuple[tuple[str, ...], ...] = TOURNAMENT_POOLS,
) -> tuple[float, list[dict[str, object]]]:
    reports = [
        evaluate(
            model, games=games, seed=seed + pool_index * 100_000,
            opponents=opponents, max_steps=max_steps,
            opponent_model=opponent_model,
            boards=boards,
        )
        for pool_index, opponents in enumerate(pools)
    ]
    return sum(report["speed_adjusted_win_score"] for report in reports) / len(reports), reports


def tune(
    *, initial_model: LinearModel, games_per_pool: int, seed: int,
    population: int = 8, generations: int = 4, max_steps: int = 10_000,
    opponent_model: OpponentModel | None = None,
    boards: str = "standard",
    pools: tuple[tuple[str, ...], ...] = TOURNAMENT_POOLS,
) -> tuple[LinearModel, dict[str, object]]:
    """Use common-random-number cross-entropy search over both policy heads."""
    if type(games_per_pool) is not int or games_per_pool < 4 or games_per_pool % 4:
        raise ValueError("games_per_pool must be a positive multiple of four")
    if type(population) is not int or population < 4:
        raise ValueError("population must be an integer of at least four")
    if type(generations) is not int or generations < 1:
        raise ValueError("generations must be a positive integer")
    _validate(games_per_pool, max_steps, DEFAULT_OPPONENTS)
    training_board_rules(boards, 0)
    if not pools:
        raise ValueError("at least one opponent pool is required")
    for opponents in pools:
        _validate(games_per_pool, max_steps, opponents)

    def flatten(model: LinearModel) -> tuple[float, ...]:
        return (*model.room_weights, *model.suggestion_weights, *model.accusation_weights)

    def expand(values: tuple[float, ...]) -> LinearModel:
        return LinearModel(
            values[:FEATURE_COUNT], values[FEATURE_COUNT:2 * FEATURE_COUNT],
            values[2 * FEATURE_COUNT:],
        )

    initial_values = flatten(initial_model)
    center = list(initial_values)
    room_sigma = (
        0.75, 0.75, 0.75, 0.5, 1.5, 0.75, 0.4, 0.75,
        *(0.0 for _ in range(FEATURE_COUNT - LEGACY_FEATURE_COUNT)),
    )
    suggestion_sigma = (
        1.25, 1.25, 1.25, 0.75, 1.0, 1.0, 0.75, 0.75,
        1.0, 1.0, 0.6, 0.6, 0.75, 0.75, 0.75, 0.5, 0.75,
    )
    sigma = [*room_sigma, *suggestion_sigma, 1.0, 1.0]
    minimum_sigma = [item * 0.12 for item in sigma]
    rng = random.Random(f"{seed}:cross-entropy")
    best_model = initial_model
    initial_score: float | None = None
    best_score = float("-inf")
    generation_reports = []

    for generation in range(generations):
        generation_seed = seed
        candidates = [tuple(center)]
        for _ in range(population - 1):
            candidates.append(tuple(
                max(-12.0, min(12.0, value + rng.gauss(0, spread)))
                for value, spread in zip(center, sigma, strict=True)
            ))
        scored = []
        for index, values in enumerate(candidates):
            candidate = expand(values)
            kwargs = {"opponent_model": opponent_model} if opponent_model is not None else {}
            if boards != "standard":
                kwargs["boards"] = boards
            if pools != TOURNAMENT_POOLS:
                kwargs["pools"] = pools
            score, pool_reports = _tuning_score(
                candidate, games=games_per_pool, seed=generation_seed, max_steps=max_steps, **kwargs,
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
            for index in range(FEATURE_COUNT * 2 + ACCUSATION_FEATURE_COUNT)
        ]
        elite_sigma = [
            math.sqrt(sum((values[index] - center[index]) ** 2 for _, _, values, _ in elites)
                      / elite_count)
            for index in range(FEATURE_COUNT * 2 + ACCUSATION_FEATURE_COUNT)
        ]
        sigma = [
            max(minimum_sigma[index], 0.65 * sigma[index] + 0.35 * elite_sigma[index])
            for index in range(FEATURE_COUNT * 2 + ACCUSATION_FEATURE_COUNT)
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
        "algorithm": "common-random-cross-entropy-v2",
        "seed": seed,
        "population": population,
        "generations": generations,
        "games_per_pool": games_per_pool,
        "max_steps": max_steps,
        "boards": boards,
        "win_speed": DEFAULT_WIN_SPEED,
        "opponent_model": asdict(opponent_model) if opponent_model is not None else None,
        "opponent_pools": [list(pool) for pool in pools],
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
        child.add_argument("--boards", choices=("standard", "random", "mixed"), default="standard")
        child.add_argument("--opponents", default=",".join(DEFAULT_OPPONENTS))
        if command == "train":
            child.add_argument("--output", type=Path, required=True)
            child.add_argument("--learning-rate", type=float, default=0.02)
            child.add_argument("--win-speed", type=float, default=DEFAULT_WIN_SPEED)
            child.add_argument("--initial", type=Path)
            child.add_argument("--opponent-model", type=Path)
        else:
            child.add_argument("--model", type=Path, required=True)
            child.add_argument("--baseline")
            child.add_argument("--room-temperature", type=float, default=0.0)
            child.add_argument("--suggestion-temperature", type=float, default=0.0)
            child.add_argument("--accusation-temperature", type=float, default=0.0)
            child.add_argument("--accusation-threshold", type=float, default=0.5)
            child.add_argument("--opponent-model", type=Path)
    tuner = commands.add_parser("tune")
    tuner.add_argument("--initial", type=Path, required=True)
    tuner.add_argument("--output", type=Path, required=True)
    tuner.add_argument("--games-per-pool", type=int, default=16)
    tuner.add_argument("--seed", type=int, required=True)
    tuner.add_argument("--population", type=int, default=8)
    tuner.add_argument("--generations", type=int, default=4)
    tuner.add_argument("--max-steps", type=int, default=10_000)
    tuner.add_argument("--boards", choices=("standard", "random", "mixed"), default="standard")
    tuner.add_argument("--opponent-model", type=Path)
    tuner.add_argument("--opponents", help="one fixed pool of three opponent names")
    tournament = commands.add_parser("benchmark")
    tournament.add_argument("--model", type=Path, required=True)
    tournament.add_argument("--incumbent", type=Path)
    tournament.add_argument("--opponent-model", type=Path)
    tournament.add_argument("--games", type=int, default=64)
    tournament.add_argument("--seed", type=int, required=True)
    tournament.add_argument("--max-steps", type=int, default=10_000)
    tournament.add_argument("--boards", choices=("standard", "random", "mixed"), default="standard")
    args = parser.parse_args(argv)
    if args.command == "train":
        opponents = tuple(name.strip() for name in args.opponents.split(","))
        model, summary = train(
            games=args.games, seed=args.seed, opponents=opponents, max_steps=args.max_steps,
            learning_rate=args.learning_rate,
            win_speed=args.win_speed,
            initial_model=load_model(args.initial) if args.initial else None,
            opponent_model=load_opponent_model(args.opponent_model) if args.opponent_model else None,
            boards=args.boards,
        )
        save_model(args.output, model, summary)
    elif args.command == "evaluate":
        opponents = tuple(name.strip() for name in args.opponents.split(","))
        summary = evaluate(
            load_model(args.model), games=args.games, seed=args.seed, opponents=opponents,
            max_steps=args.max_steps, baseline=args.baseline,
            strategy=LearnedStrategy(
                room_temperature=args.room_temperature,
                suggestion_temperature=args.suggestion_temperature,
                accusation_temperature=args.accusation_temperature,
                accusation_threshold=args.accusation_threshold,
            ),
            opponent_model=load_opponent_model(args.opponent_model) if args.opponent_model else None,
            boards=args.boards,
        )
    elif args.command == "tune":
        kwargs = {}
        if args.opponent_model:
            kwargs["opponent_model"] = load_opponent_model(args.opponent_model)
        if args.boards != "standard":
            kwargs["boards"] = args.boards
        if args.opponents:
            kwargs["pools"] = (tuple(name.strip() for name in args.opponents.split(",")),)
        model, summary = tune(
            initial_model=load_model(args.initial), games_per_pool=args.games_per_pool,
            seed=args.seed, population=args.population, generations=args.generations,
            max_steps=args.max_steps, **kwargs,
        )
        save_model(args.output, model, summary)
    else:
        kwargs = {}
        if args.opponent_model:
            kwargs["opponent_model"] = load_opponent_model(args.opponent_model)
        if args.boards != "standard":
            kwargs["boards"] = args.boards
        summary = benchmark(
            load_model(args.model), games=args.games, seed=args.seed, max_steps=args.max_steps,
            incumbent=load_model(args.incumbent) if args.incumbent else None, **kwargs,
        )
    print(json.dumps(summary, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
