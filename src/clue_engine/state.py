import random
from dataclasses import dataclass

from clue_engine.cards import CARDS, CARDS_BY_ID

from .models import CardType, Combination


@dataclass
class GameState:
    solution: Combination
    player_hands: list[frozenset[int]]
    current_player: int

def deal(rng: random.Random, num_players: int) -> GameState:
    solution = Combination(
        rng.choice([c.id for c in CARDS[CardType.SUSPECT]]),
        rng.choice([c.id for c in CARDS[CardType.WEAPON]]),
        rng.choice([c.id for c in CARDS[CardType.ROOM]]),
    )
    rest = sorted(set(CARDS_BY_ID) - {solution.suspect_id, solution.weapon_id, solution.room_id})
    rng.shuffle(rest)
    hands = [set() for _ in range(num_players)]
    for i, cid in enumerate(rest):
        hands[i % num_players].add(cid)

    return GameState(
        solution=solution,
        player_hands=[frozenset(hand) for hand in hands],
        current_player=0,
    )