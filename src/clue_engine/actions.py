from .cards import CARDS, CardType
from .models import Accuse, Action, Combination, EndTurn, Pass, Reveal, Suggest

# Generate action spaces from validated card data
COMBINATIONS: tuple[Combination, ...] = tuple(
    Combination(s.id, w.id, r.id)
    for s in CARDS[CardType.SUSPECT]
    for w in CARDS[CardType.WEAPON]
    for r in CARDS[CardType.ROOM]
)

SUGGESTIONS: tuple[Suggest, ...] = tuple(
    Suggest(c)
    for c in COMBINATIONS
)

ACCUSES: tuple[Accuse, ...] = tuple(
    Accuse(c)
    for c in COMBINATIONS
)

REVEALS: tuple[Reveal, ...] = tuple(
    Reveal(c.id)
    for cards in CARDS.values()
    for c in cards
)

PASSES: tuple[Pass, ...] = (Pass(),)

ENDTURNS: tuple[EndTurn, ...] = (EndTurn(),)

ACTIONS: tuple[Action, ...] = (*SUGGESTIONS, *ACCUSES, *REVEALS, *PASSES, *ENDTURNS)
