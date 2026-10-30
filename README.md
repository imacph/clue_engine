# Clue Engine

A card-deduction simulator with player-specific observations and simple policies.
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
automated actions without waiting. Use `--policy random` to choose random
instead of deductive policies, and `--max-steps` to limit actions. The limit
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
bot policy, action limit, and automatic or step-by-step progression. Select
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

`clue_engine.actions.ACTIONS` provides a fixed action ordering. The project does
not yet define an RL environment, observation encoding, rewards, or action mask.

Install the project with its development dependencies and run the checks:

```text
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
```
