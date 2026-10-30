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

`clue_engine.actions.ACTIONS` provides a fixed action ordering. The project does
not yet define an RL environment, observation encoding, rewards, or action mask.

Install the project with its development dependencies and run the checks:

```text
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
```
