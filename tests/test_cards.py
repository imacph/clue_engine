import random

import pytest

from clue_engine.actions import COMBINATIONS
from clue_engine.cards import CARDS, CARDS_BY_ID
from clue_engine.models import CardType
from clue_engine.state import deal


def all_cards():
    return [card for cards in CARDS.values() for card in cards]


def test_deck_has_21_unique_ids():
    ids = [card.id for card in all_cards()]
    assert len(ids) == 21
    assert len(set(ids)) == 21


def test_ids_are_0_through_20():
    assert sorted(card.id for card in all_cards()) == list(range(21))


def test_category_sizes():
    assert len(CARDS[CardType.SUSPECT]) == 6
    assert len(CARDS[CardType.WEAPON]) == 6
    assert len(CARDS[CardType.ROOM]) == 9


def test_each_card_matches_its_category():
    for card_type, cards in CARDS.items():
        assert all(card.type is card_type for card in cards)


def test_lookup_round_trips():
    for card in all_cards():
        assert CARDS_BY_ID[card.id] is card


def test_lookup_rejects_unknown_id():
    with pytest.raises(KeyError):
        CARDS_BY_ID[21]


def test_combinations_cover_full_product():
    assert len(COMBINATIONS) == 6 * 6 * 9
    assert len(set(COMBINATIONS)) == 324


def test_combinations_use_correct_categories():
    for combo in COMBINATIONS:
        assert CARDS_BY_ID[combo.suspect_id].type is CardType.SUSPECT
        assert CARDS_BY_ID[combo.weapon_id].type is CardType.WEAPON
        assert CARDS_BY_ID[combo.room_id].type is CardType.ROOM

def deal_with_seed(seed, num_players=4):
    return deal(random.Random(seed), num_players)

def solution_ids(state):
    s = state.solution
    return {s.suspect_id, s.weapon_id, s.room_id}


def test_same_seed_gives_same_deal():
    state1 = deal_with_seed(42, 4)
    state2 = deal_with_seed(42, 4)
    assert state1 == state2

def test_different_seeds_give_different_deal():
    state1 = deal_with_seed(42, 4)
    state2 = deal_with_seed(43, 4)
    assert state1 != state2

def test_different_seeds_give_different_solution():
    # since the solution is only 3 cards,
    # there is a strong possibility that a couple
    # of the deals might have the same solution, but over 20 different seeds
    # we expect to see more than one unique solution
    assert len({deal_with_seed(seed).solution for seed in range(20)}) > 1

def test_solution_not_in_any_hand():
    state = deal_with_seed(42)
    for hand in state.player_hands:
        assert not solution_ids(state) & hand

def test_every_non_solution_card_dealt_exactly_once():
    state = deal_with_seed(42)
    dealt = [cid for hand in state.player_hands for cid in hand]
    assert sorted(dealt) == sorted(set(CARDS_BY_ID) - solution_ids(state))

@pytest.mark.parametrize(
    "num_players, expected_sizes",
    [(4, [5, 5, 4, 4]), (6, [3, 3, 3, 3, 3, 3])],
)
def test_hand_sizes_are_balanced(num_players, expected_sizes):
    state = deal_with_seed(42, num_players)
    assert sorted((len(h) for h in state.player_hands), reverse=True) == expected_sizes


@pytest.mark.parametrize("num_players", [-1, 0, 1])
def test_deal_rejects_fewer_than_two_players(num_players):
    rng = random.Random(42)
    original_state = rng.getstate()
    with pytest.raises(ValueError, match="at least two"):
        deal(rng, num_players)
    assert rng.getstate() == original_state


@pytest.mark.parametrize("num_players", range(2, 7))
def test_deal_partitions_the_deck_for_each_player_count(num_players):
    state = deal_with_seed(42, num_players)
    dealt = [card for hand in state.player_hands for card in hand]
    assert sorted(dealt) == sorted(set(CARDS_BY_ID) - solution_ids(state))
    assert max(map(len, state.player_hands)) - min(map(len, state.player_hands)) <= 1