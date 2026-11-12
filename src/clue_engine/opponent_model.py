"""Supervised models of observable board-game suggestions and reveals."""

import argparse
import json
import math
import os
import random
from dataclasses import dataclass
from pathlib import Path

from .cards import CARDS
from .models import CardType, Combination, Reveal, Suggest
from .observations import Event, EventKind, last_suggest_index

SUGGESTION_FEATURES = 5
REVEAL_FEATURES = 2
DEFAULT_OPPONENTS = ("random", "deductive", "probing", "strategic", "analytical")


@dataclass(frozen=True)
class OpponentModel:
    suggestion_weights: tuple[float, ...]
    reveal_weights: tuple[float, ...]

    def __post_init__(self) -> None:
        for values, size in (
            (self.suggestion_weights, SUGGESTION_FEATURES),
            (self.reveal_weights, REVEAL_FEATURES),
        ):
            if len(values) != size or any(not math.isfinite(value) for value in values):
                raise ValueError(f"opponent model requires {size} finite weights")


def _probabilities(
    weights: tuple[float, ...], features: tuple[tuple[float, ...], ...],
) -> tuple[float, ...]:
    scores = [sum(x * w for x, w in zip(row, weights, strict=True)) for row in features]
    peak = max(scores)
    values = [math.exp(score - peak) for score in scores]
    total = sum(values)
    return tuple(value / total for value in values)


def _suggestion_features(
    card: int, hand: int, solution: Combination, events: tuple[Event, ...], actor: int,
) -> tuple[float, ...]:
    previous = any(
        event.kind is EventKind.SUGGEST and event.actor == actor and event.combo is not None
        and card in (event.combo.suspect_id, event.combo.weapon_id)
        for event in events
    )
    held = bool(hand & (1 << card))
    envelope = card in (solution.suspect_id, solution.weapon_id)
    return float(held), float(envelope), float(previous), float(held and previous), float(envelope and previous)


def _reveal_features(
    card: int, events: tuple[Event, ...], actor: int, recipient: int,
) -> tuple[float, ...]:
    shown_to_recipient = shown_publicly = False
    suggester = None
    for event in events:
        if event.kind is EventKind.SUGGEST:
            suggester = event.actor
        elif event.kind is EventKind.SHOW and event.actor == actor and event.card_id == card:
            shown_to_recipient |= suggester == recipient
            shown_publicly |= event.public
    return float(shown_to_recipient), float(shown_publicly)


def _suggestion_examples(
    combo: Combination, hand: int, solution: Combination, events: tuple[Event, ...], actor: int,
) -> tuple[tuple[tuple[tuple[float, ...], ...], int], ...]:
    result = []
    for card_type, chosen in ((CardType.SUSPECT, combo.suspect_id), (CardType.WEAPON, combo.weapon_id)):
        cards = tuple(card.id for card in CARDS[card_type])
        result.append((tuple(_suggestion_features(card, hand, solution, events, actor) for card in cards),
                       cards.index(chosen)))
    return tuple(result)


def _reveal_example(
    combo: Combination, hand: int, events: tuple[Event, ...], actor: int, recipient: int, chosen: int,
) -> tuple[tuple[tuple[float, ...], ...], int]:
    cards = tuple(
        card for card in (combo.suspect_id, combo.weapon_id, combo.room_id) if hand & (1 << card)
    )
    return tuple(_reveal_features(card, events, actor, recipient) for card in cards), cards.index(chosen)


def deal_weights(
    model: OpponentModel, player: int, events: tuple[Event, ...],
    deals: tuple[tuple[Combination, tuple[int, ...]], ...], *, strength: float = 0.3,
) -> tuple[float, ...]:
    """Weight complete consistent deals using only actions visible to the observer."""
    if not math.isfinite(strength) or not 0 <= strength <= 1:
        raise ValueError("opponent model strength must be between 0 and 1")
    if not deals:
        raise ValueError("at least one consistent deal is required")
    log_weights = [0.0] * len(deals)
    for index, event in enumerate(events):
        prefix = events[:index]
        if event.kind is EventKind.SUGGEST and event.actor != player and event.combo is not None:
            for position, (solution, hands) in enumerate(deals):
                for features, chosen in _suggestion_examples(
                    event.combo, hands[event.actor], solution, prefix, event.actor,
                ):
                    log_weights[position] += math.log(max(
                        _probabilities(model.suggestion_weights, features)[chosen], 1e-300,
                    ))
        elif event.kind is EventKind.SHOW and event.actor != player and event.card_id is not None:
            suggest_index = last_suggest_index(prefix)
            if suggest_index is None:
                continue
            suggestion = prefix[suggest_index]
            if suggestion.actor != player or suggestion.combo is None:
                continue
            for position, (_, hands) in enumerate(deals):
                features, chosen = _reveal_example(
                    suggestion.combo, hands[event.actor], prefix, event.actor, player, event.card_id,
                )
                log_weights[position] += math.log(max(
                    _probabilities(model.reveal_weights, features)[chosen], 1e-300,
                ))
    peak = max(log_weights)
    return tuple(math.exp(max(-4.0, strength * (value - peak))) for value in log_weights)


def save_model(path: Path, model: OpponentModel, metadata: dict[str, object]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump({"schema": 1, "suggestion_weights": model.suggestion_weights,
                   "reveal_weights": model.reveal_weights, "metadata": metadata},
                  stream, indent=2, allow_nan=False)
        stream.write("\n")


def load_model(path: Path) -> OpponentModel:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or type(data.get("schema")) is not int or data["schema"] != 1:
        raise ValueError("unsupported opponent model schema")
    values = []
    for key, size in (("suggestion_weights", SUGGESTION_FEATURES), ("reveal_weights", REVEAL_FEATURES)):
        row = data.get(key)
        if (not isinstance(row, list) or len(row) != size
                or any(type(item) not in (int, float) or not math.isfinite(item) for item in row)):
            raise ValueError(f"invalid {key}")
        values.append(tuple(float(item) for item in row))
    return OpponentModel(*values)


def load_configured_model() -> OpponentModel | None:
    path = os.environ.get("CLUE_OPPONENT_MODEL")
    if path is None:
        return None
    if not path.strip():
        raise ValueError("CLUE_OPPONENT_MODEL must name an opponent model file")
    return load_model(Path(path))


Example = tuple[str, tuple[tuple[float, ...], ...], int]


def collect_examples(
    *, games: int, seed: int, opponents: tuple[str, ...] = DEFAULT_OPPONENTS, max_steps: int = 10000,
) -> tuple[list[Example], int]:
    from .policies import make_policy, validate_policy_names
    from .session import create_board_game

    if type(games) is not int or games < 1 or type(max_steps) is not int or max_steps < 1:
        raise ValueError("games and max_steps must be positive integers")
    if not opponents:
        raise ValueError("at least one opponent profile is required")
    validate_policy_names(opponents, additional=("learned",))
    examples: list[Example] = []
    timeouts = 0
    for game in range(games):
        game_seed = seed + game
        rng = random.Random(f"{game_seed}:opponent-pool")
        names = tuple(rng.choice(opponents) for _ in range(4))
        engine, _ = create_board_game(4, game_seed, "random")
        policies = tuple(make_policy(name, random.Random(f"{game_seed}:opponent:{seat}"))
                         for seat, name in enumerate(names))
        for _ in range(max_steps):
            actor = engine.to_move
            if actor is None:
                break
            view = engine.view(actor)
            action = policies[actor].choose(view, 4, engine.legal_actions())
            hand = sum(1 << card for card in engine.state.player_hands[actor])
            if isinstance(action, Suggest):
                public = tuple(event for event in view.events if event.private_to is None or event.public)
                for features, chosen in _suggestion_examples(
                    action.combination, hand, engine.state.solution, public, actor,
                ):
                    examples.append(("suggestion", features, chosen))
            elif isinstance(action, Reveal):
                index = last_suggest_index(view.events)
                if index is None or view.events[index].combo is None:
                    raise ValueError("reveal without a visible suggestion")
                suggestion = view.events[index]
                recipient_events = engine.view(suggestion.actor).events
                features, chosen = _reveal_example(
                    suggestion.combo, hand, recipient_events, actor, suggestion.actor, action.card_id,
                )
                if len(features) > 1:
                    examples.append(("reveal", features, chosen))
            engine.step(action)
        if not engine.is_over:
            timeouts += 1
    return examples, timeouts


def fit(examples: list[Example], *, epochs: int = 12, learning_rate: float = 0.03) -> OpponentModel:
    if not examples or type(epochs) is not int or epochs < 1:
        raise ValueError("training requires examples and positive epochs")
    if not math.isfinite(learning_rate) or learning_rate <= 0:
        raise ValueError("learning rate must be positive and finite")
    weights = {"suggestion": [0.0] * SUGGESTION_FEATURES, "reveal": [0.0] * REVEAL_FEATURES}
    for _ in range(epochs):
        for kind, features, chosen in examples:
            current = weights[kind]
            probabilities = _probabilities(tuple(current), features)
            for index in range(len(current)):
                gradient = features[chosen][index] - sum(
                    probability * row[index] for probability, row in zip(probabilities, features, strict=True)
                )
                current[index] = max(-5.0, min(5.0, current[index] + learning_rate * gradient))
    return OpponentModel(tuple(weights["suggestion"]), tuple(weights["reveal"]))


def evaluate(model: OpponentModel, examples: list[Example]) -> dict[str, object]:
    result = {}
    for kind in ("suggestion", "reveal"):
        selected = [(features, chosen) for name, features, chosen in examples if name == kind]
        result[kind] = {
            "examples": len(selected),
            "log_loss": (
                -sum(math.log(max(_probabilities(getattr(model, f"{kind}_weights"), features)[chosen], 1e-300))
                     for features, chosen in selected) / len(selected) if selected else None
            ),
            "uniform_log_loss": (
                sum(math.log(len(features)) for features, _ in selected) / len(selected)
                if selected else None
            ),
        }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("train", "evaluate"))
    parser.add_argument("--games", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--opponents", default=",".join(DEFAULT_OPPONENTS))
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
        games=args.games, seed=args.seed, opponents=opponents, max_steps=args.max_steps,
    )
    model = fit(examples) if args.command == "train" else load_model(args.model)
    report = {"games": args.games, "seed": args.seed, "opponents": list(opponents),
              "timeouts": timeouts,
              "training_prediction" if args.command == "train" else "prediction": evaluate(model, examples)}
    if args.command == "train":
        save_model(args.output, model, report)
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
