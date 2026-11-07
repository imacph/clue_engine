# Card-only baseline

These are pre-board measurements from the existing card-only engine at
revision `fd6813a`, using CPython 3.13.3. They are a comparison point, not a
target for the future board game or a guarantee of bot strength.

Each group ran 120 games with seed 42, a 10,000-action limit, and the existing
seat rotation. Each rotation cycle reuses one deal, so a group has `120 /
players` distinct deals; policy RNG seeds differ between games and seats.
There were **2,520 games**, all won, with no timeouts, errors, or all-eliminated
games. The full aggregate data, including policy-by-seat results, is in
[card-only-baseline.json](card-only-baseline.json). It contains no hands,
solutions, or per-game private traces.

## Homogeneous policies

Each row uses the same profile at every seat. Winner turns count the winning
player's completed turns, including the winning accusation. P90 is the
nearest-rank 90th percentile. Actions and winner turns are calculated over
completed wins; `learned` counts seat exposures that had deduced the solution
by game end. First-solution timing is the mean **action index** among those
exposures, including step 0 when the initial hand sufficed. Wins by seat are
counts out of 120, ordered from seat 0.

| Players | Profile | Winner turns mean | Winner turns p90 | Actions mean | Actions p90 | Wins by seat | Learned / exposures | First-solution action mean |
|---:|---|---:|---:|---:|---:|---|---:|---:|
| 2 | random | 14.98 | 26 | 87.93 | 156 | 72, 48 | 120 / 240 | 86.93 |
| 2 | deductive | 6.22 | 9 | 35.35 | 51 | 78, 42 | 120 / 240 | 34.35 |
| 2 | probing | 5.63 | 7 | 31.90 | 42 | 76, 44 | 120 / 240 | 30.90 |
| 2 | strategic | 5.63 | 7 | 31.90 | 42 | 76, 44 | 120 / 240 | 30.90 |
| 3 | random | 10.97 | 17 | 106.18 | 161 | 36, 45, 39 | 143 / 360 | 106.27 |
| 3 | deductive | 5.64 | 8 | 52.28 | 72 | 46, 42, 32 | 148 / 360 | 52.49 |
| 3 | probing | 5.61 | 7 | 56.35 | 72 | 50, 39, 31 | 134 / 360 | 55.40 |
| 3 | strategic | 6.58 | 8 | 68.51 | 79 | 43, 47, 30 | 125 / 360 | 67.41 |
| 4 | random | 9.03 | 14 | 124.99 | 201 | 27, 41, 23, 29 | 150 / 480 | 125.13 |
| 4 | deductive | 4.88 | 7 | 64.88 | 89 | 32, 40, 21, 27 | 189 / 480 | 68.23 |
| 4 | probing | 4.96 | 6 | 75.80 | 92 | 35, 38, 21, 26 | 165 / 480 | 75.13 |
| 4 | strategic | 5.59 | 7 | 88.68 | 104 | 38, 41, 20, 21 | 139 / 480 | 87.61 |
| 5 | random | 7.55 | 10 | 139.08 | 198 | 25, 27, 29, 19, 20 | 196 / 600 | 137.01 |
| 5 | deductive | 4.33 | 6 | 75.87 | 102 | 31, 31, 24, 16, 18 | 244 / 600 | 78.91 |
| 5 | probing | 4.34 | 5 | 92.91 | 107 | 31, 26, 22, 19, 22 | 217 / 600 | 91.33 |
| 5 | strategic | 4.98 | 6 | 108.60 | 128 | 33, 25, 22, 23, 17 | 180 / 600 | 108.14 |
| 6 | random | 6.51 | 9 | 150.45 | 222 | 23, 26, 17, 21, 17, 16 | 234 / 720 | 144.83 |
| 6 | deductive | 3.99 | 5 | 91.97 | 116 | 17, 20, 12, 26, 17, 28 | 368 / 720 | 91.38 |
| 6 | probing | 3.70 | 4 | 104.91 | 127 | 18, 21, 19, 22, 19, 21 | 267 / 720 | 104.49 |
| 6 | strategic | 4.41 | 5 | 124.72 | 146 | 27, 29, 12, 18, 17, 17 | 212 / 720 | 124.99 |

## Four-player mixed policies

The initial seat order is random, deductive, probing, strategic, rotated across
seats. Winner turns averaged **5.65**, with p90 **7**; actions averaged
**82.26**, with p90 **105**. Wins by seat were **36, 33, 24, 27**.

| Profile | Wins / completed exposures | Learned / exposures | First-solution action mean |
|---|---:|---:|---:|
| random | 9 / 120 | 36 / 120 | 83.14 |
| deductive | 40 / 120 | 60 / 120 | 80.13 |
| probing | 31 / 120 | 46 / 120 | 84.20 |
| strategic | 40 / 120 | 57 / 120 | 85.58 |

The sample uses only 30 distinct four-player deals and does not establish
statistical significance. The built-in `turns` distribution instead reports
Player 0's completed turns and should not be read as winner turns.

## Capture a current comparison

The original measurements used the engine at `fd6813a`. The capture tool was
added later, so the exact historical capture procedure is not verified. Running
the current tool uses the current implementation and does not necessarily
reproduce the numbers above.

To capture a new comparison, install the project, check that the source tree is
clean, create an empty private trace directory, and run in PowerShell:

```powershell
python tools\capture_card_only_baseline.py --trace-dir <empty-directory> --source-revision (git rev-parse HEAD) > baseline-summary.json
```

Defaults are the settings above. The tool writes 21 private JSONL traces to
that directory and prints aggregate JSON, including the caller-supplied source
revision, to standard output. It warns if no source revision is provided.
Record any uncommitted changes separately; the supplied revision alone does not
prove the source tree was clean. The tool refuses to
overwrite any existing trace, reports errors or timeouts with a nonzero exit
status, and warns when the game count does not balance all seat rotations.
Traces include solutions, hands, and private reveals; store them securely and
do not share them with players. Reproducibility across Python versions is not
guaranteed.
