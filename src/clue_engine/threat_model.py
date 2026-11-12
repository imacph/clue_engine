"""Supervised forecast of an opponent winning before the observer's next turn."""

import argparse
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path

from .board_turn import BoardPhase
from .game_settings import training_board_rules
from .models import Accuse
from .observations import EventKind, PlayerView

FEATURE_COUNT = 7
DEFAULT_OPPONENTS = ("analytical", "analytical", "analytical", "strategic", "probing", "deductive")


@dataclass(frozen=True)
class ThreatModel:
    weights: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.weights) != FEATURE_COUNT or any(not math.isfinite(value) for value in self.weights):
            raise ValueError(f"threat model requires {FEATURE_COUNT} finite weights")


def features(view: PlayerView, num_players: int) -> tuple[float, ...]:
    others = [seat for seat in range(num_players) if seat != view.player]
    suggestions = {
        seat: [event for event in view.events if event.kind is EventKind.SUGGEST
               and event.actor == seat and event.combo is not None]
        for seat in others
    }
    own = sum(event.kind is EventKind.SUGGEST and event.actor == view.player for event in view.events)
    turns = sum(event.kind is EventKind.END_TURN and event.actor != view.player for event in view.events)
    moves = sum(
        event.kind in (EventKind.MOVE, EventKind.PASSAGE) and event.actor != view.player
        for event in view.events
    )
    max_rooms = max((len({event.combo.room_id for event in items}) for items in suggestions.values()), default=0)
    last_opponent_suggestion = max(
        (i for i, event in enumerate(view.events)
         if event.kind is EventKind.SUGGEST and event.actor != view.player),
        default=-1,
    )
    passes = 0
    if last_opponent_suggestion >= 0:
        for event in view.events[last_opponent_suggestion + 1:]:
            if event.kind in (EventKind.SUGGEST, EventKind.REFUTE, EventKind.END_TURN):
                break
            passes += event.kind is EventKind.PASS
    return (
        1.0, min(1.0, max((len(items) for items in suggestions.values()), default=0) / 10),
        min(1.0, own / 10), min(1.0, turns / max(1, 10 * len(others))),
        min(1.0, moves / max(1, 40 * len(others))), max_rooms / 9,
        min(1.0, passes / max(1, num_players - 1)),
    )


def probability(model: ThreatModel, view: PlayerView, num_players: int) -> float:
    score = sum(a * b for a, b in zip(model.weights, features(view, num_players), strict=True))
    return 1 / (1 + math.exp(-max(-30.0, min(30.0, score))))


def collect_examples(
    *, games: int, seed: int, opponents: tuple[str, ...] = DEFAULT_OPPONENTS,
    boards: str = "mixed", max_steps: int = 10000,
) -> tuple[list[tuple[tuple[float, ...], int]], int]:
    from .policies import make_policy, validate_policy_names
    from .session import create_board_game

    if type(games) is not int or games < 1 or type(max_steps) is not int or max_steps < 1:
        raise ValueError("games and max_steps must be positive integers")
    if not opponents:
        raise ValueError("at least one opponent profile is required")
    validate_policy_names(opponents)
    training_board_rules(boards, 0)
    examples = []
    timeouts = 0
    for game in range(games):
        game_seed = seed + game
        rng = random.Random(f"{game_seed}:threat-pool")
        names = tuple(rng.choice(opponents) for _ in range(4))
        engine, _ = create_board_game(4, game_seed, "random", board_rules=training_board_rules(boards, game))
        policies = tuple(make_policy(name, random.Random(f"{game_seed}:threat:{seat}"))
                         for seat, name in enumerate(names))
        pending: dict[int, tuple[float, ...]] = {}
        for _ in range(max_steps):
            actor = engine.to_move
            if actor is None:
                break
            view = engine.view(actor)
            if actor == engine.state.current_player and view.board.phase is BoardPhase.START:
                if actor in pending:
                    examples.append((pending.pop(actor), 0))
                pending[actor] = features(view, 4)
            action = policies[actor].choose(view, 4, engine.legal_actions())
            engine.step(action)
            if isinstance(action, Accuse) and not engine.is_over:
                pending.pop(actor, None)
            if engine.is_over:
                for seat, row in pending.items():
                    examples.append((row, int(engine.winner is not None and engine.winner != seat)))
                break
        if not engine.is_over:
            timeouts += 1
    return examples, timeouts


def fit(examples: list[tuple[tuple[float, ...], int]], *, epochs: int = 30) -> ThreatModel:
    if not examples or type(epochs) is not int or epochs < 1:
        raise ValueError("training requires examples and positive epochs")
    weights = [0.0] * FEATURE_COUNT
    for _ in range(epochs):
        for row, label in examples:
            score = sum(a * b for a, b in zip(weights, row, strict=True))
            prediction = 1 / (1 + math.exp(-max(-30.0, min(30.0, score))))
            for index in range(FEATURE_COUNT):
                weights[index] += 0.03 * ((label - prediction) * row[index] - 0.001 * weights[index])
    return ThreatModel(tuple(weights))


def evaluate(model: ThreatModel, examples: list[tuple[tuple[float, ...], int]]) -> dict[str, object]:
    if not examples:
        raise ValueError("evaluation requires completed turn examples")
    positives = sum(label for _, label in examples)
    base = positives / len(examples)
    predictions = [
        1 / (1 + math.exp(-max(-30.0, min(30.0, sum(
            a * b for a, b in zip(model.weights, row, strict=True)
        )))))
        for row, _ in examples
    ]
    return {
        "examples": len(examples), "events": positives, "event_rate": base,
        "mean_prediction": sum(predictions) / len(predictions),
        "brier": sum((predicted - label) ** 2 for predicted, (_, label)
                     in zip(predictions, examples, strict=True)) / len(examples),
        "constant_brier": base * (1 - base),
    }


def load_model(path: Path) -> ThreatModel:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or type(data.get("schema")) is not int or data["schema"] != 1:
        raise ValueError("unsupported threat model schema")
    weights = data.get("weights")
    if (not isinstance(weights, list) or len(weights) != FEATURE_COUNT
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in weights)):
        raise ValueError("invalid threat model weights")
    return ThreatModel(tuple(float(value) for value in weights))


def load_packaged_model() -> ThreatModel:
    return load_model(Path(__file__).with_name("threat_model.json"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("train", "evaluate"))
    parser.add_argument("--games", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--opponents", default=",".join(DEFAULT_OPPONENTS))
    parser.add_argument("--boards", choices=("standard", "random", "mixed"), default="mixed")
    parser.add_argument("--max-steps", type=int, default=10000)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.command == "train" and (args.output is None or args.model is not None):
        parser.error("train requires --output and does not accept --model")
    if args.command == "evaluate" and (args.model is None or args.output is not None):
        parser.error("evaluate requires --model and does not accept --output")
    opponents = tuple(name.strip() for name in args.opponents.split(","))
    examples, timeouts = collect_examples(
        games=args.games, seed=args.seed, opponents=opponents, boards=args.boards, max_steps=args.max_steps,
    )
    model = fit(examples) if args.command == "train" else load_model(args.model)
    report = {
        "games": args.games, "seed": args.seed, "opponents": list(opponents),
        "boards": args.boards, "timeouts": timeouts,
        "training_prediction" if args.command == "train" else "prediction": evaluate(model, examples),
    }
    if args.command == "train":
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump({"schema": 1, "weights": model.weights, "metadata": report}, stream, indent=2, allow_nan=False)
            stream.write("\n")
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
