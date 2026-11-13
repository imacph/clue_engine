import random

import pytest

from clue_engine.board_turn import Roll
from clue_engine.game_settings import LearnedStrategy, training_board_rules
from clue_engine.learning_policy import LearningPolicy, LinearModel
from clue_engine.models import Accuse, Combination
from clue_engine.observations import Event, EventKind, view_for
from clue_engine.policies import make_policy
from clue_engine.session import create_board_game
from clue_engine.threat_model import (
    ThreatModel,
    collect_examples,
    evaluate,
    features,
    fit,
    probability,
)


def test_mixed_boards_balance_each_set_of_four_seats():
    assert [training_board_rules("mixed", i).randomize_rooms for i in range(8)] == [
        False, False, False, False, True, True, True, True,
    ]
    with pytest.raises(ValueError):
        training_board_rules("unknown", 0)


def test_threat_features_cannot_see_other_players_private_reveals():
    combo = Combination(0, 6, 12)
    events = (Event(EventKind.SUGGEST, 1, combo=combo),)
    views = [
        view_for(events + (Event(EventKind.SHOW, 2, card_id=card, private_to=1),), 0, frozenset())
        for card in (0, 6)
    ]
    assert features(views[0], 4) == features(views[1], 4)


def test_threat_features_count_opponent_movement_but_not_own():
    events = (Event(EventKind.MOVE, 1), Event(EventKind.PASSAGE, 2), Event(EventKind.MOVE, 0))
    assert features(view_for(events, 0, frozenset()), 4)[4] == 2 / 120


def test_factory_loads_threat_model_only_when_enabled():
    off = make_policy(LearnedStrategy(), random.Random(1))
    on = make_policy(LearnedStrategy(threat_sensitivity=0.7), random.Random(1))
    assert isinstance(off, LearningPolicy) and off.threat_model is None
    assert isinstance(on, LearningPolicy) and on.threat_model is not None


def test_supervised_forecast_is_reproducible_and_evaluated():
    examples, timeouts = collect_examples(games=4, seed=3, opponents=("random",))
    assert examples and timeouts == 0
    assert (examples, timeouts) == collect_examples(games=4, seed=3, opponents=("random",))
    model = fit(examples)
    report = evaluate(model, examples)
    assert 0 <= report["brier"] <= 1
    engine, _ = create_board_game(4, 3, "random")
    assert 0 < probability(model, engine.view(0), 4) < 1


def test_threat_adjusts_guessing_without_bypassing_sound_only_mode(monkeypatch):
    engine, _ = create_board_game(4, 4, "random")
    view = engine.view(engine.to_move)
    combinations = (Combination(0, 6, 12), Combination(1, 7, 13), Combination(2, 8, 14))
    legal = tuple(Accuse(combo) for combo in combinations) + (Roll(),)

    def analyze(policy, knowledge, actions, *, enabled, risk):
        policy._deal_counts = dict(zip(combinations, (4, 3, 3), strict=True))

    monkeypatch.setattr(LearningPolicy, "_analyze", analyze)
    monkeypatch.setattr(LearningPolicy, "_choose_with_knowledge", lambda *args: Roll())
    monkeypatch.setattr("clue_engine.learning_policy.threat_probability", lambda *args: 0.5)
    threat = ThreatModel((0.0,) * 7)
    cautious = LearningPolicy(random.Random(1), LinearModel.zeros(), threat_model=threat)
    responsive = LearningPolicy(
        random.Random(1), LinearModel.zeros(), threat_model=threat,
        strategy=LearnedStrategy(threat_sensitivity=1),
    )
    sound = LearningPolicy(
        random.Random(1), LinearModel.zeros(), threat_model=threat,
        strategy=LearnedStrategy(threat_sensitivity=1, accusation_threshold=1),
    )
    assert cautious.choose(view, 4, legal) == Roll()
    assert responsive.choose(view, 4, legal) == Accuse(combinations[0])
    assert sound.choose(view, 4, legal) == Roll()
