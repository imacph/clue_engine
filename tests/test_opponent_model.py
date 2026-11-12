import random

import pytest

from clue_engine.learning_policy import LearningPolicy, LinearModel
from clue_engine.models import Accuse, Combination
from clue_engine.observations import Event, EventKind, view_for
from clue_engine.opponent_model import (
    OpponentModel,
    collect_examples,
    deal_weights,
    evaluate,
    fit,
    load_configured_model,
    load_model,
    save_model,
)


def test_fitting_predicts_observed_choices_better_than_uniform():
    examples = [
        ("suggestion", ((1.0, 0, 0, 0, 0), (0.0, 0, 0, 0, 0)), 0),
        ("reveal", ((1.0, 0), (0.0, 0)), 0),
    ] * 30
    model = fit(examples)
    report = evaluate(model, examples)
    for kind in ("suggestion", "reveal"):
        assert report[kind]["log_loss"] < report[kind]["uniform_log_loss"]


def test_model_round_trip_and_explicit_configuration(tmp_path, monkeypatch):
    model = OpponentModel((1.0, 0, 0, 0, 0), (1.0, 0))
    path = tmp_path / "opponent.json"
    save_model(path, model, {"games": 1})
    assert load_model(path) == model
    with pytest.raises(FileExistsError):
        save_model(path, model, {})
    monkeypatch.setenv("CLUE_OPPONENT_MODEL", str(path))
    assert load_configured_model() == model
    monkeypatch.setenv("CLUE_OPPONENT_MODEL", "")
    with pytest.raises(ValueError, match="CLUE_OPPONENT_MODEL"):
        load_configured_model()


def test_policy_factory_uses_opponent_override(tmp_path, monkeypatch):
    from clue_engine.policies import make_policy

    model = OpponentModel((1.0, 0, 0, 0, 0), (0, 0))
    path = tmp_path / "opponent.json"
    save_model(path, model, {})
    monkeypatch.setenv("CLUE_OPPONENT_MODEL", str(path))
    policy = make_policy("learned", random.Random(1))
    assert isinstance(policy, LearningPolicy)
    assert policy.opponent_model == model



def test_weights_respect_visible_evidence_without_eliminating_deals():
    first = Combination(0, 6, 12)
    second = Combination(1, 7, 13)
    deals = ((first, (0, 1 << 1)), (second, (0, 1 << 0)))
    event = Event(EventKind.SUGGEST, 1, combo=first)
    model = OpponentModel((-2.0, 0, 0, 0, 0), (0.0, 0.0))
    weights = deal_weights(model, 0, (event,), deals)
    assert 0 < weights[1] < weights[0] <= 1
    assert deal_weights(model, 0, (event,), deals, strength=0) == (1, 1)


def test_private_reveals_to_other_players_are_never_observed():
    combo = Combination(0, 6, 12)
    shared = (Event(EventKind.SUGGEST, 1, combo=combo), Event(EventKind.REFUTE, 2))
    views = [
        view_for(shared + (Event(EventKind.SHOW, 2, card_id=card, private_to=1),), 0, frozenset())
        for card in (0, 6)
    ]
    assert views[0] == views[1]
    model = OpponentModel((1.0, 0, 0, 0, 0), (1.0, 0))
    deals = ((combo, (0, 0, 1 << 0)), (combo, (0, 0, 1 << 6)))
    assert deal_weights(model, 0, views[0].events, deals) == deal_weights(
        model, 0, views[1].events, deals,
    )


def test_observed_reveal_uses_only_choices_possible_in_each_deal():
    combo = Combination(0, 6, 12)
    events = (
        Event(EventKind.SUGGEST, 0, combo=combo),
        Event(EventKind.SHOW, 1, card_id=6, private_to=0),
        Event(EventKind.SUGGEST, 0, combo=combo),
        Event(EventKind.SHOW, 1, card_id=0, private_to=0),
    )
    deals = (
        (combo, (0, (1 << 0) | (1 << 6))),
        (combo, (0, (1 << 0) | (1 << 6) | (1 << 12))),
    )
    model = OpponentModel((0, 0, 0, 0, 0), (2.0, 0))
    weights = deal_weights(model, 0, events, deals, strength=1)
    assert weights[0] > weights[1] > 0


def test_policy_weights_accusation_support_without_changing_sound_constraints(monkeypatch):
    from clue_engine.session import create_board_game

    engine, _ = create_board_game(4, 4, "random")
    view = engine.view(engine.to_move)
    first = Combination(0, 6, 12)
    second = Combination(1, 7, 13)
    deals = ((first, (0, 0, 0, 0)), (second, (0, 0, 0, 0)))
    policy = LearningPolicy(
        random.Random(1), LinearModel.zeros(),
        opponent_model=OpponentModel((0, 0, 0, 0, 0), (0, 0)),
    )

    def analyze(policy, knowledge, actions, *, enabled, risk):
        policy._deal_counts = {first: 1, second: 1}

    monkeypatch.setattr(LearningPolicy, "_analyze", analyze)
    monkeypatch.setattr("clue_engine.learning_policy.consistent_deals", lambda *args: deals)
    monkeypatch.setattr("clue_engine.learning_policy.deal_weights", lambda *args: (0.1, 1.0))
    assert policy.choose(view, 4, (Accuse(first), Accuse(second))) == Accuse(second)


def test_simulated_training_is_reproducible():
    first, timeouts = collect_examples(games=2, seed=7, opponents=("random",))
    assert first
    assert timeouts == 0
    assert (first, timeouts) == collect_examples(games=2, seed=7, opponents=("random",))


def test_benchmark_cli_compares_opponent_model_to_unmodeled_incumbent(tmp_path, monkeypatch):
    from clue_engine import learning

    learned_path = tmp_path / "learned.json"
    opponent_path = tmp_path / "opponent.json"
    learning.save_model(learned_path, LinearModel.zeros(), {})
    opponent = OpponentModel((1.0, 0, 0, 0, 0), (0, 0))
    save_model(opponent_path, opponent, {})
    calls = []

    def fake_benchmark(model, **kwargs):
        calls.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(learning, "benchmark", fake_benchmark)
    assert learning.main([
        "benchmark", "--model", str(learned_path), "--incumbent", str(learned_path),
        "--opponent-model", str(opponent_path), "--games", "4", "--seed", "1",
    ]) == 0
    assert calls[0]["opponent_model"] == opponent
    assert calls[0]["incumbent"] == LinearModel.zeros()


def test_policy_training_can_use_and_record_opponent_model(monkeypatch):
    from clue_engine import learning

    opponent = OpponentModel((1.0, 0, 0, 0, 0), (0, 0))
    seen = []

    def fake_game(policy, seat, seed, opponents, max_steps):
        seen.append(policy.opponent_model)
        return seat, 10, False

    monkeypatch.setattr(learning, "_game", fake_game)
    _, report = learning.train(games=1, seed=3, opponent_model=opponent)
    assert seen == [opponent]
    assert report["opponent_model"]["suggestion_weights"] == opponent.suggestion_weights
