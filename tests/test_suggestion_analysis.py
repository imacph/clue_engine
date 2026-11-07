import random
from dataclasses import replace

import pytest

from clue_engine.knowledge import knowledge_for
from clue_engine.models import Combination, Suggest
from clue_engine.observations import Event, EventKind, PlayerView, view_for
from clue_engine.policies import StrategicPolicy
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


def test_suggestion_planner_cannot_observe_another_players_private_show():
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
    assert StrategicPolicy(random.Random(2)).choose(views[0], 4, legal) == (
        StrategicPolicy(random.Random(2)).choose(views[1], 4, legal)
    )
