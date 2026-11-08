"""Command-line entry point for batch simulations."""

import argparse
import json
import signal
import sys
from pathlib import Path
from threading import Event

from .batch import (
    BatchConfig,
    BatchSummary,
    batch_config_from_setup,
    format_summary,
    policies_for_players,
    run_batch,
)
from .distributions import Distributions
from .distributions_cli import (
    add_distribution_options,
    render_options,
    validate_options,
)
from .policies import POLICY_NAMES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run seeded Clue simulations and save private traces.")
    parser.add_argument("--games", type=int, default=100)
    parser.add_argument("--players", type=int, help="card-only player count (default: 4)")
    parser.add_argument(
        "--policies",
        help=f"one policy or comma-separated policies: {', '.join(POLICY_NAMES)}",
    )
    parser.add_argument(
        "--setup", type=Path,
        help="JSON object using game setup fields (game type, bots, and rule settings)",
    )
    parser.add_argument("--seed", type=int, help="base seed (default: setup seed or 0)")
    parser.add_argument("--max-steps", type=int, help="action limit per game (default: setup value or 10000)")
    parser.add_argument("--no-rotate", action="store_true", help="do not rotate policies across seats")
    parser.add_argument("--trace", type=Path, required=True, help="new JSONL trace file (never overwritten)")
    add_distribution_options(parser)
    args = parser.parse_args(argv)
    try:
        if args.setup is not None:
            if args.players is not None or args.policies is not None:
                parser.error("--setup cannot be combined with --players or --policies")
            try:
                setup = json.loads(args.setup.read_text(encoding="utf-8"))
            except OSError as exc:
                parser.error(f"unable to read setup file: {exc}")
            except json.JSONDecodeError as exc:
                parser.error(f"invalid setup JSON: {exc}")
            config = batch_config_from_setup(
                setup,
                games=args.games,
                seed=args.seed,
                max_steps=args.max_steps,
                rotate=not args.no_rotate,
            )
        else:
            players = args.players if args.players is not None else 4
            if players < 2:
                parser.error("--players must be at least 2")
            names = policies_for_players(
                args.policies if args.policies is not None else "deductive", players,
            )
            config = BatchConfig(
                args.games, names, args.seed if args.seed is not None else 0,
                args.max_steps if args.max_steps is not None else 10_000, not args.no_rotate,
            )
        config.validate()
        validate_options(args)
    except ValueError as exc:
        parser.error(str(exc))
    except TypeError as exc:
        parser.error(str(exc))

    print("WARNING: trace contains private hands, shown cards, and solutions.", file=sys.stderr)
    if config.rotate and config.games % len(config.policies):
        print("WARNING: the final rotation is incomplete; policy seat exposures may be unbalanced.",
              file=sys.stderr)

    def progress(summary: BatchSummary) -> None:
        done = summary["started_games"]
        if done == 1 or done % 10 == 0 or done == summary["requested_games"]:
            print(f"Progress: {done}/{summary['requested_games']}", file=sys.stderr, flush=True)

    stop = Event()
    previous_handler = signal.getsignal(signal.SIGINT)

    def interrupt(_signum: int, _frame: object) -> None:
        stop.set()
        print("Cancelling after the current action...", file=sys.stderr, flush=True)

    signal.signal(signal.SIGINT, interrupt)
    distributions = Distributions()
    try:
        summary = run_batch(
            config, args.trace, progress=progress, cancelled=stop.is_set, on_game=distributions.add_game,
        )
    except OSError as exc:
        print(f"Unable to write trace: {exc}", file=sys.stderr)
        return 2
    finally:
        signal.signal(signal.SIGINT, previous_handler)
    print(format_summary(summary))
    print(render_options(distributions, args))
    print(f"Private trace: {args.trace}")
    if summary["cancelled"]:
        return 130
    return 1 if summary["outcomes"]["error"] or summary["outcomes"]["timeout"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
