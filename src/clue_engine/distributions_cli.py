"""Display empirical distributions from an existing private batch trace."""

import argparse
import sys
from pathlib import Path

from .distributions import (
    METRICS,
    MODES,
    Distributions,
    format_distribution,
    read_distributions,
    validate_distribution_options,
)


def add_distribution_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--metric", choices=METRICS, default="actions", help="distribution metric")
    parser.add_argument("--bin-width", type=int, default=10, help="numeric histogram bin width")
    parser.add_argument("--display", choices=MODES, default="count", help="display counts or percentages")
    parser.add_argument("--filter-policy", help="deduction metric: restrict to this policy")
    parser.add_argument("--filter-seat", type=int, help="deduction metric: restrict to this zero-based seat")


def validate_options(args: argparse.Namespace) -> None:
    validate_distribution_options(args.metric, args.bin_width, args.filter_policy, args.filter_seat)


def render_options(data: Distributions, args: argparse.Namespace) -> str:
    chart = data.chart(args.metric, width=args.bin_width, policy=args.filter_policy, seat=args.filter_seat)
    return format_distribution(chart, mode=args.display)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze a saved private batch trace.")
    parser.add_argument("--trace", type=Path, required=True, help="existing JSONL trace")
    add_distribution_options(parser)
    args = parser.parse_args(argv)
    try:
        validate_options(args)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        data = read_distributions(args.trace)
    except (OSError, ValueError) as exc:
        print(f"Unable to read trace: {exc}", file=sys.stderr)
        return 2
    print(render_options(data, args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
