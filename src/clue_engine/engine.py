from . import rules
from .models import Accuse, Action, EndTurn, Pass, Reveal, Suggest
from .observations import (
    Event,
    EventKind,
    PlayerView,
    last_suggest_index,
    pending,
    refutation_events,
    view_for,
)
from .state import GameState


class IllegalActionError(ValueError):
    pass


class Engine:
    """Applies actions to a game. It owns the event log and the turn marker."""

    def __init__(self, state: GameState):
        if len(state.player_hands) < 2:
            raise ValueError("a game requires at least two players")
        if not 0 <= state.current_player < len(state.player_hands):
            raise ValueError("current_player must identify an existing player")
        self.state = state
        self.log: tuple[Event, ...] = ()

    @property
    def num_players(self) -> int:
        return len(self.state.player_hands)

    @property
    def is_over(self) -> bool:
        return rules.is_over(self.state, self.log)

    @property
    def winner(self) -> int | None:
        return rules.winner(self.state, self.log)

    @property
    def to_move(self) -> int | None:
        """The player who must act next: a pending responder, else the turn owner."""
        if self.is_over:
            return None
        response = pending(self.log, self.num_players)
        return response.player if response is not None else self.state.current_player

    def legal_actions(self) -> tuple[Action, ...]:
        player = self.to_move
        if player is None:
            return ()
        return rules.legal_actions(self.state, self.log, player)

    def view(self, player: int) -> PlayerView:
        if not 0 <= player < self.num_players:
            raise ValueError(f"invalid player: {player}")
        return view_for(self.log, player, self.state.player_hands[player])

    def step(self, action: Action) -> tuple[Event, ...]:
        """Apply an action for the player to move and return the events it produced."""
        player = self.to_move
        if player is None or action not in self.legal_actions():
            raise IllegalActionError(f"{action} is not legal for player {player}")
        events = self._events_for(player, action)
        self.log += events
        if events[-1].kind is EventKind.END_TURN:
            self._advance_turn()
        return events

    def _events_for(self, player: int, action: Action) -> tuple[Event, ...]:
        match action:
            case Suggest(combination=combo):
                return (Event(EventKind.SUGGEST, player, combo=combo),)
            case Pass():
                return (Event(EventKind.PASS, player),)
            case Reveal(card_id=card_id):
                index = last_suggest_index(self.log)
                assert index is not None
                return refutation_events(player, card_id, self.log[index])
            case Accuse(combination=combo):
                accusation = Event(EventKind.ACCUSE, player, combo=combo)
                if combo == self.state.solution:
                    return (accusation,)
                # An eliminated player has nothing left to do on their turn.
                return (accusation, Event(EventKind.END_TURN, player))
            case EndTurn():
                return (Event(EventKind.END_TURN, player),)
            case _:
                raise TypeError(f"unknown action {action!r}")

    def _advance_turn(self) -> None:
        out = rules.eliminated(self.state, self.log)
        for offset in range(1, self.num_players + 1):
            seat = (self.state.current_player + offset) % self.num_players
            if seat not in out:
                self.state.current_player = seat
                return
