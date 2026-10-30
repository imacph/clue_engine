from collections.abc import Sequence

from .engine import Engine
from .policies import Policy


def play(engine: Engine, policies: Sequence[Policy], max_steps: int = 10_000) -> Engine:
    """Run a game to the end. Each policy sees only its own player's view."""
    if len(policies) != engine.num_players:
        raise ValueError("one policy is required for each player")
    if max_steps < 0:
        raise ValueError("max_steps must be non-negative")
    for _ in range(max_steps):
        player = engine.to_move
        if player is None:
            return engine
        action = policies[player].choose(
            engine.view(player), engine.num_players, engine.legal_actions()
        )
        engine.step(action)
    if engine.is_over:
        return engine
    raise RuntimeError(f"game did not finish within {max_steps} steps")
