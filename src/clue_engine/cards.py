from .models import Card, CardType

CARDS: dict[CardType, tuple[Card, ...]] = {
    CardType.SUSPECT: (
        Card(0, "Miss Scarlet", CardType.SUSPECT),
        Card(1, "Colonel Mustard", CardType.SUSPECT),
        Card(2, "Mrs. White", CardType.SUSPECT),
        Card(3, "Reverend Green", CardType.SUSPECT),
        Card(4, "Mrs. Peacock", CardType.SUSPECT),
        Card(5, "Professor Plum", CardType.SUSPECT),
    ),
    CardType.WEAPON: (
        Card(6, "Candlestick", CardType.WEAPON),
        Card(7, "Dagger", CardType.WEAPON),
        Card(8, "Lead Pipe", CardType.WEAPON),
        Card(9, "Revolver", CardType.WEAPON),
        Card(10, "Rope", CardType.WEAPON),
        Card(11, "Wrench", CardType.WEAPON),
    ),
    CardType.ROOM: (
        Card(12, "Kitchen", CardType.ROOM),
        Card(13, "Ballroom", CardType.ROOM),
        Card(14, "Conservatory", CardType.ROOM),
        Card(15, "Dining Room", CardType.ROOM),
        Card(16, "Billiard Room", CardType.ROOM),
        Card(17, "Library", CardType.ROOM),
        Card(18, "Lounge", CardType.ROOM),
        Card(19, "Hall", CardType.ROOM),
        Card(20, "Study", CardType.ROOM),
    ),
}

CARDS_BY_ID: dict[int, Card] = {card.id: card for cards in CARDS.values() for card in cards}