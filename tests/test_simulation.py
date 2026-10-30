import random

import pytest

from clue_engine.engine import Engine
from clue_engine.models import Accuse, EndTurn
from clue_engine.simulation import play
from clue_engine.state import deal


class FixedPolicy:
    def __init__(self, action):
        self.action = action

    def choose(self, view, num_players, legal):
        return self.action


def test_finishing_on_last_allowed_step_succeeds():
    engine = Engine(deal(random.Random(0), 2))
    policies = [FixedPolicy(Accuse(engine.state.solution))] * 2
    assert play(engine, policies, max_steps=1) is engine
    assert engine.winner == 0


def test_already_finished_game_succeeds_with_zero_steps():
    engine = Engine(deal(random.Random(0), 2))
    engine.step(Accuse(engine.state.solution))
    assert play(engine, [FixedPolicy(EndTurn())] * 2, max_steps=0) is engine


def test_unfinished_game_hits_step_limit():
    engine = Engine(deal(random.Random(0), 2))
    with pytest.raises(RuntimeError, match="within 1 steps"):
        play(engine, [FixedPolicy(EndTurn())] * 2, max_steps=1)


def test_negative_step_limit_is_invalid():
    engine = Engine(deal(random.Random(0), 2))
    with pytest.raises(ValueError, match="max_steps"):
        play(engine, [FixedPolicy(EndTurn())] * 2, max_steps=-1)


@pytest.mark.parametrize("count", [0, 1, 3])
def test_rejects_policy_count_mismatch(count):
    engine = Engine(deal(random.Random(0), 2))
    with pytest.raises(ValueError, match="polic"):
        play(engine, [FixedPolicy(EndTurn())] * count)
