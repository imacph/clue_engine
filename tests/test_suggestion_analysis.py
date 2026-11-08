import random
from dataclasses import replace

import pytest

from clue_engine.knowledge import knowledge_for
from clue_engine.models import Accuse, Combination, EndTurn, Suggest
from clue_engine.observations import Event, EventKind, PlayerView, view_for
from clue_engine.policies import AnalyticalPolicy, StrategicPolicy
from clue_engine.suggestion_analysis import expected_solution_certainty


def test_suggestion_certainty_distinguishes_informative_responses():
    view = PlayerView(0, frozenset(), ())
    deals = (
        (Combination(0, 6, 12), (0, 1 << 1)),
        (Combination(1, 6, 12), (0, 1 << 0)),
    )
    assert expected_solution_certainty(view, Combination(0, 7, 13), deals) == 1
    assert expected_solution_certainty(view, Combination(2, 7, 13), deals) == 0.5


@pytest.mark.parametrize(
    ("all_refute", "reverse", "expected"),
    [(False, False, 0.5), (True, False, 1), (False, True, 1), (True, True, 1)],
)
def test_suggestion_certainty_respects_refutation_order_and_all_refute(
    all_refute, reverse, expected,
):
    view = PlayerView(0, frozenset(), (), reverse_refutation=reverse, all_refute=all_refute)
    deals = (
        (Combination(0, 6, 12), (0, 1 << 7, 1 << 1)),
        (Combination(1, 6, 12), (0, 1 << 7, 1 << 0)),
    )
    assert expected_solution_certainty(view, Combination(0, 7, 13), deals) == expected


def test_suggestion_certainty_averages_multiple_possible_reveals():
    view = PlayerView(0, frozenset(), ())
    deals = (
        (Combination(0, 6, 12), (0, (1 << 7) | (1 << 13))),
        (Combination(1, 6, 12), (0, 1 << 7)),
    )
    score = expected_solution_certainty(view, Combination(2, 7, 13), deals)
    assert score == pytest.approx(2 / 3)
    assert expected_solution_certainty(replace(view, all_refute=True), Combination(2, 7, 13), deals) == score


def test_suggestion_certainty_uses_relative_deal_weights():
    view = PlayerView(0, frozenset(), ())
    deals = (
        (Combination(0, 6, 12), (0, 1 << 1)),
        (Combination(1, 6, 12), (0, 1 << 0)),
    )
    suggestion = Combination(2, 7, 13)
    assert expected_solution_certainty(view, suggestion, deals, weights=(3, 1)) == pytest.approx(0.625)
    assert expected_solution_certainty(view, suggestion, deals, weights=(6, 2)) == pytest.approx(0.625)
    for weights in ((1,), (1, 0), (1, float("nan")), (1, float("inf"))):
        with pytest.raises(ValueError):
            expected_solution_certainty(view, suggestion, deals, weights=weights)


def test_analytical_suggestion_uses_opponent_hint_as_a_soft_tiebreaker():
    event = Event(EventKind.SUGGEST, 1, combo=Combination(0, 6, 12))
    view = PlayerView(0, frozenset({1, 7, 13}), (event,))
    knowledge = knowledge_for(view, 4)
    hinted = Suggest(Combination(0, 7, 13))
    other = Suggest(Combination(2, 7, 13))
    bot = AnalyticalPolicy(random.Random(0))
    assert bot._rank_suggestions(view, knowledge, (other, hinted), prefer_probe=False) == hinted
    hints, _ = bot._suggestion_evidence(replace(view, events=(event, event)), knowledge, None)
    assert hints[0] == 1
    assert knowledge.mark_of(knowledge.envelope, 0).name == "UNKNOWN"


def test_analytical_model_weights_deals_without_eliminating_any():
    event = Event(EventKind.SUGGEST, 1, combo=Combination(0, 6, 12))
    view = PlayerView(0, frozenset({1, 7, 13}), (event,))
    knowledge = knowledge_for(view, 2)
    deals = (
        (Combination(0, 6, 12), (0, 0)),
        (Combination(2, 8, 14), (0, (1 << 0) | (1 << 6) | (1 << 12))),
    )
    hints, weights = AnalyticalPolicy(random.Random(0))._suggestion_evidence(view, knowledge, deals)
    assert hints == {0: 1, 6: 1, 12: 1}
    assert weights == (1, 0.75 ** 3)
    duplicate = replace(view, events=(event, event))
    assert AnalyticalPolicy(random.Random(0))._suggestion_evidence(duplicate, knowledge, deals)[1] == weights
    own = replace(view, events=(replace(event, actor=0),))
    assert AnalyticalPolicy(random.Random(0))._suggestion_evidence(own, knowledge, deals) == ({}, (1, 1))


def test_known_opponent_cards_do_not_saturate_deal_weighting():
    suggestion = Event(EventKind.SUGGEST, 1, combo=Combination(0, 6, 12))
    view = PlayerView(
        0, frozenset({1, 7, 13}),
        (suggestion, Event(EventKind.SHOW, 1, card_id=12, private_to=0)),
    )
    knowledge = knowledge_for(view, 2)
    deals = (
        (Combination(0, 6, 14), (0, 1 << 12)),
        (Combination(2, 8, 14), (0, (1 << 0) | (1 << 6) | (1 << 12))),
    )
    _, weights = AnalyticalPolicy(random.Random(0))._suggestion_evidence(view, knowledge, deals)
    assert weights == (1, 0.75 ** 2)


def test_analytical_ignores_forced_board_room_in_opponent_model():
    from clue_engine.session import create_board_game

    engine, _ = create_board_game(3, 21, "analytical")
    event = Event(EventKind.SUGGEST, 1, combo=Combination(0, 6, 12))
    view = replace(engine.view(0), events=(event,))
    knowledge = knowledge_for(view, 3)
    hints, _ = AnalyticalPolicy(random.Random(0))._suggestion_evidence(view, knowledge, None)
    assert 12 not in hints


def test_analytical_increases_exact_counting_budget_without_using_partial_counts(monkeypatch):
    from clue_engine import policies

    calls = []

    def incomplete(knowledge, *, max_candidates, max_nodes):
        calls.append((max_candidates, max_nodes))

    monkeypatch.setattr(policies, "solution_deal_counts", incomplete)
    view = PlayerView(0, frozenset({1, 7, 13}), ())
    bot = AnalyticalPolicy(random.Random(0))
    assert bot._count_deals(knowledge_for(view, 2)) is None
    assert calls == [(24, 60000)]


def test_analytical_risk_uses_completed_counts_and_inclusive_half_threshold(monkeypatch):
    from clue_engine import policies

    view = PlayerView(
        0, frozenset({1, 7, 13}),
        (Event(EventKind.SUGGEST, 1, combo=Combination(0, 6, 12)),),
    )
    bot = AnalyticalPolicy(random.Random(0))
    first, second = Combination(0, 6, 12), Combination(2, 8, 14)
    third = Combination(3, 9, 15)
    legal = (Accuse(first), Accuse(second), Accuse(third), EndTurn())
    monkeypatch.setattr(policies, "consistent_deals", lambda knowledge, counts: None)
    monkeypatch.setattr(bot, "_count_deals", lambda knowledge: {first: 2, second: 1, third: 1})
    assert bot.choose(view, 2, legal) == Accuse(first)
    monkeypatch.setattr(bot, "_count_deals", lambda knowledge: {first: 1, second: 1, third: 1})
    assert bot.choose(view, 2, legal) == EndTurn()
    monkeypatch.setattr(bot, "_count_deals", lambda knowledge: None)
    assert bot.choose(view, 2, legal) == EndTurn()
    assert bot.choose(view, 2, (EndTurn(),)) == EndTurn()


def test_analytical_risk_uses_opponent_weighted_complete_deals(monkeypatch):
    from clue_engine import policies

    view = PlayerView(
        0, frozenset({1, 7, 13}),
        (Event(EventKind.SUGGEST, 1, combo=Combination(0, 6, 12)),),
    )
    first, second = Combination(0, 6, 12), Combination(2, 8, 14)
    deals = ((first, (0, 0)),) * 2 + ((second, (0, (1 << 0) | (1 << 6) | (1 << 12))),) * 3
    bot = AnalyticalPolicy(random.Random(0))
    monkeypatch.setattr(bot, "_count_deals", lambda knowledge: {first: 2, second: 3})
    monkeypatch.setattr(policies, "consistent_deals", lambda knowledge, counts: deals)
    assert bot.choose(view, 2, (Accuse(first), Accuse(second), EndTurn())) == Accuse(first)


def test_strategic_ranking_uses_response_information_when_deals_are_available(monkeypatch):
    from clue_engine import policies

    view = PlayerView(0, frozenset(), ())
    first = Combination(0, 6, 12)
    second = Combination(1, 6, 12)
    deals = (
        (first, (0, (1 << 1) | (1 << 7), 0)),
        (second, (0, 1 << 7, 1 << 0)),
    )
    monkeypatch.setattr(policies, "consistent_deals", lambda knowledge, counts: deals)
    bot = StrategicPolicy(random.Random(0))
    bot._deal_counts = {first: 1, second: 1}
    uninformative = Suggest(Combination(0, 7, 13))
    informative = Suggest(Combination(1, 7, 13))
    assert bot._rank_suggestions(
        view, knowledge_for(view, 3), (uninformative, informative), prefer_probe=False,
    ) == informative


@pytest.mark.parametrize("policy_cls", [StrategicPolicy, AnalyticalPolicy])
def test_suggestion_planner_cannot_observe_another_players_private_show(policy_cls):
    common = (
        Event(EventKind.SUGGEST, 0, combo=Combination(0, 7, 12)),
        Event(EventKind.REFUTE, 1),
    )
    hidden = (
        Event(EventKind.SHOW, 1, card_id=7, private_to=0),
        Event(EventKind.SHOW, 1, card_id=12, private_to=0),
    )
    views = tuple(view_for((*common, event), 2, frozenset({1, 8, 13})) for event in hidden)
    assert views[0] == views[1]
    legal = (Suggest(Combination(0, 6, 12)), Suggest(Combination(2, 6, 12)))
    assert policy_cls(random.Random(2)).choose(views[0], 4, legal) == (
        policy_cls(random.Random(2)).choose(views[1], 4, legal)
    )
