from dataclasses import dataclass
from .cards import CARDS, CardType, Card

class Action:
    """Base class for all actions."""
    pass


@dataclass(frozen=True,slots=True)
class Suggest(Action):
    suspect_id: int
    weapon_id: int
    room_id: int

@dataclass(frozen=True,slots=True)
class Reveal(Action):
    card_id: int

@dataclass(frozen=True,slots=True)
class Accuse(Action):
    suspect_id: int
    weapon_id: int
    room_id: int

@dataclass(frozen=True,slots=True)
class Pass(Action):
    pass


# generate action space programmatically

SUGGESTIONS: tuple[Suggest, ...] = tuple(
    Suggest(suspect_id=s.id, weapon_id=w.id, room_id=r.id)
    for s in CARDS[CardType.SUSPECT]
    for w in CARDS[CardType.WEAPON]
    for r in CARDS[CardType.ROOM]
)

REVEALS: tuple[Reveal, ...] = tuple (
    Reveal(card_id=c.id)
    for cards in CARDS.values()
    for c in cards
)

ACCUSES: tuple[Accuse, ...] = tuple(
    Accuse(suspect_id=s.id, weapon_id=w.id, room_id=r.id)
    for s in CARDS[CardType.SUSPECT]
    for w in CARDS[CardType.WEAPON]
    for r in CARDS[CardType.ROOM]
)

PASSES: tuple[Pass, ...] = (
    Pass(),
)

ACTIONS = (
    *SUGGESTIONS,
    *REVEALS,
    *ACCUSES,
    *PASSES,
)
    

