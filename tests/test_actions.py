from clue_engine.actions import ACCUSES, ACTIONS, COMBINATIONS, REVEALS, SUGGESTIONS


def test_action_space_contains_each_action_once():
    assert len(COMBINATIONS) == 324
    assert len(SUGGESTIONS) == len(ACCUSES) == 324
    assert len(REVEALS) == 21
    assert len(ACTIONS) == 671
    assert len(set(ACTIONS)) == len(ACTIONS)
