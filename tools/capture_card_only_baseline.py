"""Capture reproducible card-only batch statistics and private game traces."""

import argparse
import json
import math
import platform
import sys
from pathlib import Path
from statistics import mean, median

from clue_engine.batch import BatchConfig, GameResult, run_batch

PROFILES = ("random", "deductive", "probing", "strategic")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace-dir", type=Path, required=True, help="existing empty trace directory")
    parser.add_argument("--games", type=int, default=120, help="games per group (default: 120)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-steps", type=int, default=10_000)
    args = parser.parse_args()
    if not args.trace_dir.is_dir():
        parser.error("--trace-dir must be an existing directory")
    if args.games < 1:
        parser.error("--games must be at least 1")
    if args.max_steps < 0:
        parser.error("--max-steps must be non-negative")

    configurations = [
        (players, (profile,) * players, profile)
        for players in range(2, 7)
        for profile in PROFILES
    ]
    configurations.append((4, PROFILES, "mixed"))
    paths = [
        args.trace_dir / f"card-only-{players}-{profile}.jsonl"
        for players, _, profile in configurations
    ]
    existing = next((path for path in paths if path.exists()), None)
    if existing is not None:
        parser.error(f"trace already exists: {existing}")
    if args.games % 60:
        print(
            "WARNING: games per group is not divisible by every player count; "
            "seat rotations are incomplete.",
            file=sys.stderr,
        )
    print("WARNING: traces contain private hands, shown cards, and solutions.", file=sys.stderr)

    groups = []
    failed = False
    for (players, policies, profile), path in zip(configurations, paths, strict=True):
        games: list[GameResult] = []
        config = BatchConfig(args.games, policies, seed=args.seed, max_steps=args.max_steps)
        summary = run_batch(config, path, on_game=games.append)
        winner_turns = sorted(
            game.turns[game.winner] for game in games if game.winner is not None
        )
        turn_stats = None
        if winner_turns:
            turn_stats = {
                "count": len(winner_turns),
                "mean": mean(winner_turns),
                "median": median(winner_turns),
                "p90": winner_turns[math.ceil(0.9 * len(winner_turns)) - 1],
            }
        groups.append({
            "players": players,
            "profile": profile,
            "policies": policies,
            "winner_turns": turn_stats,
            "summary": summary,
        })
        failed = failed or bool(summary["outcomes"]["error"] or summary["outcomes"]["timeout"])
        print(f"Finished {players} players / {profile}.", file=sys.stderr)

    print(json.dumps({
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "games_per_group": args.games,
        "seed": args.seed,
        "max_steps": args.max_steps,
        "rotate": True,
        "groups": groups,
    }, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
