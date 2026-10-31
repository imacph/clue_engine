from clue_engine.actions import ACCUSES, ACTIONS, COMBINATIONS, REVEALS, SUGGESTIONS
from clue_engine.models import Accuse, Combination, EndTurn, Pass, Reveal, Suggest


def test_action_space_contains_each_action_once():
    assert len(COMBINATIONS) == 324
    assert len(SUGGESTIONS) == len(ACCUSES) == 324
    assert len(REVEALS) == 21
    assert len(ACTIONS) == 671
    assert len(set(ACTIONS)) == len(ACTIONS)


def test_card_only_action_order_stays_fixed():
    assert ACTIONS[0] == Suggest(Combination(0, 6, 12))
    assert ACTIONS[323] == Suggest(Combination(5, 11, 20))
    assert ACTIONS[324] == Accuse(Combination(0, 6, 12))
    assert ACTIONS[647] == Accuse(Combination(5, 11, 20))
    assert ACTIONS[648] == Reveal(0)
    assert ACTIONS[668] == Reveal(20)
    assert ACTIONS[669:] == (Pass(), EndTurn())
