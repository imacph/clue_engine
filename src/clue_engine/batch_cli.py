"""Command-line entry point for batch simulations."""

import argparse
import signal
import sys
from pathlib import Path
from threading import Event

from .batch import (
    BatchConfig,
    BatchSummary,
    format_summary,
    policies_for_players,
    run_batch,
)
from .policies import POLICY_NAMES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run seeded Clue simulations and save private traces.")
    parser.add_argument("--games", type=int, default=100)
    parser.add_argument("--players", type=int, default=4)
    parser.add_argument(
        "--policies", default="deductive",
        help=f"one policy or comma-separated policies: {', '.join(POLICY_NAMES)}",
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-steps", type=int, default=10_000)
    parser.add_argument("--no-rotate", action="store_true", help="do not rotate policies across seats")
    parser.add_argument("--trace", type=Path, required=True, help="new JSONL trace file (never overwritten)")
    args = parser.parse_args(argv)
    if args.players < 2:
        parser.error("--players must be at least 2")
    try:
        names = policies_for_players(args.policies, args.players)
        config = BatchConfig(args.games, names, args.seed, args.max_steps, not args.no_rotate)
        config.validate()
    except ValueError as exc:
        parser.error(str(exc))

    print("WARNING: trace contains private hands, shown cards, and solutions.", file=sys.stderr)
    if config.rotate and config.games % args.players:
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
    try:
        summary = run_batch(config, args.trace, progress=progress, cancelled=stop.is_set)
    except OSError as exc:
        print(f"Unable to write trace: {exc}", file=sys.stderr)
        return 2
    finally:
        signal.signal(signal.SIGINT, previous_handler)
    print(format_summary(summary))
    print(f"Private trace: {args.trace}")
    if summary["cancelled"]:
        return 130
    return 1 if summary["outcomes"]["error"] or summary["outcomes"]["timeout"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
