import random
from collections.abc import Sequence
from dataclasses import dataclass

from .board import DEFAULT_BOARD, BoardLayout
from .board_setup import BoardSetup
from .board_state import create_board
from .board_turn import BoardTurn
from .cards import CARDS, CARDS_BY_ID
from .game_settings import DEFAULT_BOARD_RULES, BoardRules
from .models import CardType, Combination


@dataclass
class GameState:
    solution: Combination
    player_hands: list[frozenset[int]]
    current_player: int
    board: BoardTurn | None = None
    board_rules: BoardRules = DEFAULT_BOARD_RULES

def deal(rng: random.Random, num_players: int) -> GameState:
    if num_players < 2:
        raise ValueError("a game requires at least two players")
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


def deal_board(
    rng: random.Random,
    num_players: int,
    *,
    layout: BoardLayout = DEFAULT_BOARD,
    seat_suspects: Sequence[int] | None = None,
    weapon_rooms: Sequence[int] | None = None,
    board_rules: BoardRules = DEFAULT_BOARD_RULES,
) -> GameState:
    """Deal an opt-in board game; invalid setup is rejected before dealing."""
    if not isinstance(board_rules, BoardRules):
        raise TypeError("board_rules must be BoardRules")
    board = create_board(
        BoardSetup(num_players), layout=layout,
        seat_suspects=seat_suspects, weapon_rooms=weapon_rooms,
    )
    state = deal(rng, num_players)
    state.current_player = board.first_player
    state.board = BoardTurn(board)
    state.board_rules = board_rules
    return state