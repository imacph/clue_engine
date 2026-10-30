"""Interface-independent coordination for a single game session."""

import random
from collections.abc import Sequence
from dataclasses import dataclass

from .engine import Engine
from .models import Action, Combination
from .observations import Event, EventKind, PlayerView, public_events
from .policies import Policy, make_policy, policies_for_players
from .state import deal


@dataclass(frozen=True)
class DebugInfo:
    solution: Combination
    hands: tuple[frozenset[int], ...]


@dataclass(frozen=True)
class SessionSnapshot:
    num_players: int
    human_player: int | None
    to_move: int | None
    is_over: bool
    winner: int | None
    steps: int
    player0_turns: int
    max_steps: int
    limit_reached: bool
    view: PlayerView | None
    events: tuple[Event, ...]
    legal_actions: tuple[Action, ...]
    debug_info: DebugInfo | None


def create_game(num_players: int, seed: int, policy_name: str) -> tuple[Engine, tuple[Policy, ...]]:
    names = policies_for_players(policy_name, num_players)
    engine = Engine(deal(random.Random(seed), num_players))
    policies = tuple(make_policy(name, random.Random(f"{seed}:{i}")) for i, name in enumerate(names))
    return engine, policies


class GameSession:
    """Coordinate actions while exposing only the selected observer's information."""

    def __init__(
        self,
        engine: Engine,
        policies: Sequence[Policy],
        *,
        human_player: int | None = None,
        debug: bool = False,
        max_steps: int = 10_000,
    ):
        if len(policies) != engine.num_players:
            raise ValueError("one policy is required for each player")
        if human_player is not None and not 0 <= human_player < engine.num_players:
            raise ValueError("human_player must identify an existing player")
        if max_steps < 0:
            raise ValueError("max_steps must be non-negative")
        self._engine = engine
        self._policies = tuple(policies)
        self._human_player = human_player
        self._debug = debug
        self._max_steps = max_steps
        self._steps = 0

    def snapshot(self) -> SessionSnapshot:
        engine = self._engine
        player = engine.to_move
        view = engine.view(self._human_player) if self._human_player is not None else None
        events = engine.log if self._debug else (
            view.events if view is not None else public_events(engine.log)
        )
        debug_info = (
            DebugInfo(engine.state.solution, tuple(engine.state.player_hands))
            if self._debug else None
        )
        is_over = engine.is_over
        winner = engine.winner
        player0_turns = sum(
            event.kind is EventKind.END_TURN and event.actor == 0 for event in engine.log
        ) + int(winner == 0)
        limit_reached = not is_over and self._steps >= self._max_steps
        legal = (
            engine.legal_actions()
            if player is not None and player == self._human_player and not limit_reached
            else ()
        )
        return SessionSnapshot(
            num_players=engine.num_players,
            human_player=self._human_player,
            to_move=player,
            is_over=is_over,
            winner=winner,
            steps=self._steps,
            player0_turns=player0_turns,
            max_steps=self._max_steps,
            limit_reached=limit_reached,
            view=view,
            events=events,
            legal_actions=legal,
            debug_info=debug_info,
        )

    def spectator_view(self, player: int) -> PlayerView:
        """Return a player's private view only when the session is spectating."""
        if self._human_player is not None:
            raise ValueError("player views are only available in spectator mode")
        return self._engine.view(player)

    def _active_player(self) -> int:
        player = self._engine.to_move
        if player is None:
            raise ValueError("game is over")
        if self._steps >= self._max_steps:
            raise ValueError("game reached its action limit")
        return player

    def submit(self, action: Action) -> None:
        player = self._active_player()
        if player != self._human_player:
            raise ValueError("it is not the human player's turn")
        self._engine.step(action)
        self._steps += 1

    def advance_bot(self) -> None:
        player = self._active_player()
        if player == self._human_player:
            raise ValueError("waiting for the human player")
        action = self._policies[player].choose(
            self._engine.view(player), self._engine.num_players, self._engine.legal_actions()
        )
        self._engine.step(action)
        self._steps += 1
