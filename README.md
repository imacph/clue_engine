# Clue Engine

A card-deduction simulator with player-specific observations and configurable bot policies.
It models suggestions, mandatory refutations, accusations, elimination, and turns;
it does not model a board, movement, room restrictions, or character relocation.
Players may suggest any combination once per turn and may end a turn without
suggesting. Eliminated players still respond to suggestions. The game ends after
a correct accusation or when every player has made an incorrect accusation.

`deal` supports two or more players and distributes the 18 non-solution cards
in seat order as evenly as possible. The random generator is supplied by the
caller for reproducibility.

```python
import random

from clue_engine.engine import Engine
from clue_engine.policies import DeductivePolicy
from clue_engine.simulation import play
from clue_engine.state import deal

engine = Engine(deal(random.Random(1), num_players=4))
policies = [DeductivePolicy(random.Random(i)) for i in range(4)]
play(engine, policies)
print(engine.winner)
```

`Engine.view(player)` exposes that player's hand and visible events. The engine
itself, including its state, full log, and events returned by `step`, is intended
for a trusted controller and can contain the solution or privately shown cards.
Pass views rather than the engine to player policies. `play` requires one policy
per player and raises `RuntimeError` if the game has not ended after `max_steps`;
policies are not guaranteed to terminate every game.

## Console play and observation

After installing the project, play as seat 0 against three deductive policies:

```text
python -m clue_engine.console --mode play --players 4 --seat 0 --seed 42
```

At your action prompt, enter `suggest`, `accuse`, `reveal`, `pass`, or `end`
when offered. For a suggestion or accusation, select a suspect, weapon, and
room by the displayed card ID or full name. On a reveal prompt, only matching
cards are available. At an action or step prompt, `hand`, `knowledge`, `history`,
`help`, and `quit` are also available. Seats and card IDs are zero-based.

To spectate automated players, use:

```text
python -m clue_engine.console --mode spectate --players 4 --seed 42 --progress step
```

Press Enter to advance one automated action at a time; `--progress auto` runs
automated actions without waiting. Use `--policy strategic` to choose one
profile for all bots, or `--policies random,deductive,probing,strategic` to
choose a profile per seat. In play mode the human seat still needs an entry,
but its bot profile is unused. Use `--max-steps` to limit actions. The limit
returns exit status 1 if the game has not ended; quitting returns status 0.
Run `python -m clue_engine.console --help` for all options.

Ordinary play displays only the human player's hand and visible events.
During spectator stepping, `knowledge` shows every player's knowledge, and
`knowledge 2` shows only Player 2's. These views include each player's private
hand and cards shown to them, so they are not suitable for a player who wants
to preserve hidden information. The ordinary spectator history remains public.
`--debug-omniscient` additionally reveals the actual solution and private events,
including during play. Do not enable it for a fair game.

## Desktop interface

The desktop interface requires Python's Tkinter support. Start it with:

```text
python -m clue_engine.gui
```

The setup screen offers play or spectator mode, player count, human seat, seed,
bot policy, action limit, and automatic or step-by-step progression. The bot
policy selector applies to every bot. Optionally enter comma-separated
per-seat profiles, such as `random,deductive,probing,strategic`, to override it.
Include the human seat in play mode; its profile is ignored. Select
**Start game** to open the notebook. Use the card selectors and action buttons
to play; when responding, only legal cards are offered for reveal. An accusation
requires confirmation. The read-only notebook shows deductions from the human
player's view. Spectators can select any player's private hand and notebook; the
history remains public unless omniscient debug is enabled. Both interfaces show
the recorded refutation and incorrect-accusation clauses, distinguishing
unresolved constraints from those already satisfied.

**Pause** stops automated actions; **Next action** advances one bot action while
paused, and **Resume** continues. Human actions are always submitted manually.
**New game** returns to setup. The optional omniscient debug setting requires
confirmation and exposes all hands, the solution, and private events.

The Player 0 turn counter starts at zero and increases when Player 0 completes
their own turn, including by making an accusation. Refuting another player's
suggestion does not increase it. Once Player 0 is eliminated, the counter
remains unchanged even if they continue to refute.

## Bot profiles

All profiles use only their own player view, and accuse only when the existing
knowledge engine has deduced the complete solution and an accusation is legal.
They use seeded randomness for choices and ties.

- `random`: chooses among legal non-accusation actions at random.
- `deductive`: randomly suggests cards still possible in the envelope.
- `probing`: when possible, tests one unknown solution candidate alongside two
  controls known to be in its own hand or the envelope. It otherwise falls
  back to `deductive` suggestions. When revealing, it prefers a card previously
  shown to that same opponent; otherwise it chooses randomly.
- `strategic`: uses the same probes and repeat-reveal behavior, and ranks
  suggestions using potentially reachable responders, known blockers, unresolved
  clauses, and remaining envelope candidates.

The newer profiles use heuristics to select actions; they share the existing
deduction engine rather than an exhaustive possible-deal solver. They are not
guaranteed to win more often in every matchup. Use batch comparisons to measure
their behavior with different opponents, seeds, and seat positions.

## Batch statistics and private traces

Run reproducible simulations from the command line:

```text
python -m clue_engine.batch_cli --games 100 --players 4 --policies random,deductive,probing,strategic --seed 42 --trace batch-42.jsonl
```

Provide one policy name to use it for every player, or a comma-separated policy
for every seat. Available profiles are `random`, `deductive`, `probing`, and
`strategic`. The default limit is 10,000 actions per game; change it with
`--max-steps`. A game that
reaches the limit is reported as a timeout, not a completed game. The trace
file must be new: existing files are never overwritten. Errors and timeouts
give the CLI a nonzero exit status. Ctrl+C requests cancellation between
actions, saves the partial game and batch summary, and returns status 130.

The desktop setup screen also has **Batch statistics**. Configure the batch
and a new trace file there, start or cancel it, and inspect its progress and
summary while it runs. The trace controls can also open an existing JSONL file
and display one zero-based game number at a time. Trace loading and batch work
run off the Tk thread. Closing the window requests cancellation.

**Traces contain all private information**, including every hand, the solution,
and private shown cards. Keep them in a secure location and do not share them
with players who should not see that information. A trace includes every
started game and can grow large; plan disk space for long batches.

By default, policies rotate across seats. Each cycle of `players` games uses
the same deal seed, `seed + game_index // players`, while policies move one
seat per game. Each seat's policy has an independent deterministic random
generator, seeded from the deal seed, game index, and seat; action randomness
is therefore not paired between games. An incomplete final cycle can give
unbalanced seat exposures, so use a game count divisible by the number of
players for balanced comparisons. `--no-rotate` keeps the supplied seat order
and uses `seed + game_index` as the deal seed. The trace records Python's
version and the seeds; reproducibility across Python versions is not guaranteed.

Summaries count wins, all-eliminated games, timeouts, errors, and cancellations
separately. Only wins and all-eliminated games count as completed. Policy
win rates divide wins by completed seat exposures, including multiple seats
using the same policy; policy-by-seat rates use the corresponding seat
exposures. Mean actions, mean completed turns per seat, suggestions, passes,
and refutations use completed games only. The action median averages the two
middle values for an even sample; p90 uses the nearest-rank definition.
Deduction totals use all started seat exposures, including partial games.
Their mean first-solution step is averaged only over players who learned the
solution: step 0 means the initial hand was sufficient, and subsequent steps
count actions, not events. Snapshot candidate counts and solution knowledge
are calculated independently from each player's filtered view.

The newline-delimited JSON trace begins with `batch_start`, followed by each
`game_start` (deal and policy seeds), `initial_knowledge`, alternating `action`
and `knowledge` records, and `game_result`. An action contains all events it
produced; for example, one reveal may produce both refutation and private-show
events. Expected failures may add `action_error` or `knowledge_error` records.
The final `batch_result` contains the same aggregate data as the displayed
summary, including policy-by-seat breakdowns. Unexpected errors are surfaced
and may leave a partial trace without a final result; successfully applied
actions are written before deduction snapshots. One game's records can be
loaded in Python with `read_game_trace(Path("batch-42.jsonl"), 0)` from
`clue_engine.batch`.

`clue_engine.actions.ACTIONS` provides a fixed action ordering. The project does
not yet define an RL environment, observation encoding, rewards, or action mask.

Install the project with its development dependencies and run the checks:

```text
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
```
