"""Offline REINFORCE training and reproducible board-policy evaluation."""

import argparse
import json
import math
import random
from pathlib import Path

from .learning_policy import FEATURE_COUNT, LearningPolicy, LinearModel
from .policies import Policy, make_policy, validate_policy_names
from .session import create_board_game

DEFAULT_OPPONENTS = ("deductive", "probing", "strategic")
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
    if not isinstance(data, dict) or data.get("schema") != MODEL_SCHEMA:
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
    return {
        "games": games, "seed": seed, "opponents": list(opponents), "baseline": baseline,
        "wins": wins, "losses": losses, "timeouts": timeouts, "seats": seats,
        "win_rate": wins / completed if completed else None,
        "win_rate_ci95": _wilson(wins, completed),
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
    args = parser.parse_args(argv)
    opponents = tuple(name.strip() for name in args.opponents.split(","))
    if args.command == "train":
        model, summary = train(
            games=args.games, seed=args.seed, opponents=opponents, max_steps=args.max_steps,
            learning_rate=args.learning_rate,
            initial_model=load_model(args.initial) if args.initial else None,
        )
        save_model(args.output, model, summary)
    else:
        summary = evaluate(
            load_model(args.model), games=args.games, seed=args.seed, opponents=opponents,
            max_steps=args.max_steps, baseline=args.baseline,
        )
    print(json.dumps(summary, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
