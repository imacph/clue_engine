from dataclasses import dataclass
from enum import Enum, auto

"""Cards and card combinations"""
class CardType(Enum):
    SUSPECT = auto()
    WEAPON = auto()
    ROOM = auto()

@dataclass(frozen=True,slots=True)
class Card:
    id: int
    name: str
    type: CardType

@dataclass(frozen=True,slots=True)
class Combination:
    suspect_id: int
    weapon_id: int
    room_id: int


"""Actions in the game"""
class Action:
    """Base class for all actions."""
    pass

@dataclass(frozen=True,slots=True)
class Suggest(Action):
    combination: Combination

@dataclass(frozen=True,slots=True)
class Accuse(Action):
    combination: Combination

@dataclass(frozen=True,slots=True)
class Reveal(Action):
    card_id: int

@dataclass(frozen=True,slots=True)
class Pass(Action):
    pass

