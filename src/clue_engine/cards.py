from dataclasses import dataclass
from enum import Enum, auto

class CardType(Enum):
    SUSPECT = auto()
    WEAPON = auto()
    ROOM = auto()

@dataclass(frozen=True,slots=True)
class Card:
    id: int
    name: str

CARDS: dict[CardType, tuple[Card, ...]] = {
    CardType.SUSPECT: (
        Card(0, "Miss Scarlet"),
        Card(1, "Colonel Mustard"),
        Card(2, "Mrs. White"),
        Card(3, "Reverend Green"),
        Card(4, "Mrs. Peacock"),
        Card(5, "Professor Plum"),
    ),
    CardType.WEAPON: (
        Card(6, "Candlestick"),
        Card(7, "Dagger"),
        Card(8, "Lead Pipe"),
        Card(9, "Revolver"),
        Card(10, "Rope"),
        Card(11, "Wrench"),
    ),
    CardType.ROOM: (
        Card(12, "Kitchen"),
        Card(13, "Ballroom"),
        Card(14, "Conservatory"),
        Card(15, "Dining Room"),
        Card(16, "Billiard Room"),
        Card(17, "Library"),
        Card(18, "Lounge"),
        Card(19, "Hall"),
        Card(20, "Study"),
    ),
}