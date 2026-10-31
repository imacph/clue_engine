from dataclasses import dataclass
from enum import Enum, auto

from .models import Combination


class EventKind(Enum):
    SUGGEST = auto()
    PASS = auto()
    REFUTE = auto()
    SHOW = auto()
    ACCUSE = auto()
    END_TURN = auto()

@dataclass(frozen=True)
class Event:
    kind: EventKind
    actor: int
    combo: Combination | None = None
    card_id: int | None = None
    private_to: int | None = None

@dataclass(frozen=True)
class PlayerView:
    player: int
    own_hand: frozenset[int]
    events: tuple[Event, ...]

def refutation_events(refuter: int, refutation_card_id: int, suggest: Event ) -> tuple[Event, ...]:
    return (
        Event(kind=EventKind.REFUTE, actor=refuter),
        Event(kind=EventKind.SHOW, actor=refuter, card_id=refutation_card_id, private_to=suggest.actor),
    )

def view_for(log: tuple[Event, ...], player: int, own_hand: frozenset[int]) -> PlayerView:
    return PlayerView(
        player=player,
        own_hand=own_hand,
        events=tuple(event for event in log if visible_to(event, player))
    )

def visible_to(event: Event, player: int) -> bool:
    return event.private_to is None or player in (event.private_to, event.actor)


def public_events(log: tuple[Event, ...]) -> tuple[Event, ...]:
    """Return only events visible without a player identity."""
    return tuple(event for event in log if event.private_to is None)


def is_incorrect_accusation(events: tuple[Event, ...], index: int) -> bool:
    event = events[index]
    if event.kind is not EventKind.ACCUSE or index + 1 >= len(events):
        return False
    next_event = events[index + 1]
    return next_event.kind is EventKind.END_TURN and next_event.actor == event.actor


def last_suggest_index(log: tuple[Event, ...]) -> int | None:
    return max(
        (i for i, event in enumerate(log) if event.kind is EventKind.SUGGEST),
        default=None
    )

@dataclass(frozen=True)
class Pending:
    player: int

def pending(log: tuple[Event, ...], num_players: int) -> Pending | None:
    """Return the next seat that must refute or pass, or None if no response is due.

    None means no suggestion has been made, or it was refuted or passed by everyone.
    """
    last_suggest = last_suggest_index(log)
    if last_suggest is None:
        return None

    tail = log[last_suggest + 1:]
    suggester = log[last_suggest].actor

    if any(event.kind is EventKind.REFUTE for event in tail):
        return None

    passed = {event.actor for event in tail if event.kind is EventKind.PASS}
    for offset in range(1, num_players):
        seat = (suggester + offset) % num_players
        if seat not in passed:
            return Pending(seat)
    return None