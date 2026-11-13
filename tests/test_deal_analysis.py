import random

import pytest

from clue_engine.actions import ACCUSES, ENDTURNS
from clue_engine.cards import CARDS
from clue_engine.deal_analysis import (
    _settle_hand_clauses,
    consistent_deals,
    deduce_deal_constraints,
    feasible_solutions,
    solution_deal_counts,
)
from clue_engine.game_settings import BotStrategy, GameRules
from clue_engine.knowledge import (
    Clause,
    InconsistentKnowledgeError,
    Knowledge,
    Mark,
    _settle_hand_size,
    knowledge_for,
)
from clue_engine.learning_policy import LearningPolicy, LinearModel
from clue_engine.models import Accuse, CardType, Combination
from clue_engine.observations import Event, EventKind, PlayerView
from clue_engine.opponent_model import OpponentModel
from clue_engine.policies import CustomPolicy
from clue_engine.session import create_game
from clue_engine.state import deal


def ambiguous_deal():
    state = deal(random.Random(21), 4)
    sizes = tuple(map(len, state.player_hands))
    solution = (
        state.solution.suspect_id, state.solution.weapon_id, state.solution.room_id,
    )
    marks = [[Mark.NOT_HELD] * 21 for _ in range(5)]
    for holder, hand in enumerate(state.player_hands):
        for card in hand:
            marks[holder][card] = Mark.HELD
    for card in solution:
        marks[4][card] = Mark.HELD
    alternatives = []
    holders = []
    for category, solution_card in zip(
        (CardType.SUSPECT, CardType.WEAPON), solution, strict=False
    ):
        alternative = next(card.id for card in CARDS[category] if card.id != solution_card)
        holder = next(seat for seat, hand in enumerate(state.player_hands) if alternative in hand)
        for row in (holder, 4):
            marks[row][solution_card] = Mark.UNKNOWN
            marks[row][alternative] = Mark.UNKNOWN
        alternatives.append(alternative)
        holders.append(holder)
    return state, Knowledge(4, marks, [], hand_sizes=sizes), alternatives, holders


def test_counts_all_consistent_deals_and_wrong_accusations():
    state, knowledge, alternatives, _ = ambiguous_deal()
    counts = solution_deal_counts(knowledge)
    assert counts is not None
    assert len(counts) == 4
    assert set(counts.values()) == {1}
    assert state.solution in counts
    wrong = Combination(alternatives[0], alternatives[1], state.solution.room_id)
    knowledge.wrong_accusations.append(frozenset(
        (wrong.suspect_id, wrong.weapon_id, wrong.room_id)
    ))
    counts = solution_deal_counts(knowledge)
    assert counts is not None
    assert wrong not in counts
    assert len(counts) == 3


def test_clause_filters_deals_and_search_limit_is_never_used_as_proof():
    state, knowledge, alternatives, holders = ambiguous_deal()
    holder = holders[0]
    controls = [
        card for card, mark in enumerate(knowledge.marks[holder])
        if mark is Mark.NOT_HELD and card != alternatives[0]
    ][:2]
    knowledge.clauses.append(Clause(holder, frozenset((state.solution.suspect_id, *controls))))
    counts = solution_deal_counts(knowledge)
    assert counts is not None
    assert len(counts) == 2
    assert all(combo.suspect_id == alternatives[0] for combo in counts)
    assert solution_deal_counts(knowledge, max_nodes=1) is None


def test_feasible_solutions_are_complete_or_explicitly_unavailable():
    state, knowledge, _, _ = ambiguous_deal()
    counts = solution_deal_counts(knowledge)
    assert counts is not None
    assert set(feasible_solutions(knowledge)) == set(counts)
    assert state.solution in feasible_solutions(knowledge)
    assert feasible_solutions(knowledge, max_nodes=0) is None
    assert feasible_solutions(knowledge, max_candidates=1) is None


def test_enumerated_deals_match_complete_counts_and_respect_limits():
    _, knowledge, _, _ = ambiguous_deal()
    counts = solution_deal_counts(knowledge)
    assert counts is not None
    deals = consistent_deals(knowledge, counts)
    assert deals is not None
    assert {solution: sum(item[0] == solution for item in deals) for solution in counts} == counts
    for solution, hands in deals:
        envelope = {solution.suspect_id, solution.weapon_id, solution.room_id}
        for seat, hand in enumerate(hands):
            assert hand.bit_count() == knowledge.hand_sizes[seat]
            assert not any(hand & (1 << card) for card in envelope)
            for card, mark in enumerate(knowledge.marks[seat]):
                assert mark is Mark.UNKNOWN or (mark is Mark.HELD) == bool(hand & (1 << card))
    assert consistent_deals(knowledge, counts, max_deals=1) is None
    assert consistent_deals(knowledge, counts, max_nodes=0) is None


def test_opponent_model_uses_real_enumerated_consistent_deals():
    state, knowledge, alternatives, _ = ambiguous_deal()
    counts = solution_deal_counts(knowledge)
    assert counts is not None
    deals = consistent_deals(knowledge, counts)
    assert deals is not None
    suggestion = Combination(alternatives[0], alternatives[1], state.solution.room_id)
    view = PlayerView(0, state.player_hands[0], (Event(EventKind.SUGGEST, 1, combo=suggestion),))
    policy = LearningPolicy(
        random.Random(1), LinearModel.zeros(),
        opponent_model=OpponentModel((-2.0, 0, 0, 0, 0), (0, 0)),
    )
    _, weights = policy._suggestion_evidence(view, knowledge, deals)
    assert weights is not None and len(weights) == len(deals)
    assert len(set(weights)) > 1
    assert all(weight > 0 for weight in weights)
    assert policy.opponent_model_weightings == 1


def test_hand_size_combines_overlapping_clauses():
    row = [Mark.NOT_HELD] * 21
    for card in (0, 6, 7):
        row[card] = Mark.UNKNOWN
    knowledge = Knowledge(
        1, [row, [Mark.UNKNOWN] * 21],
        [Clause(0, frozenset({0, 6, 12})), Clause(0, frozenset({0, 7, 13}))],
        hand_sizes=(1,),
    )
    assert _settle_hand_clauses(knowledge, 0, 1)
    assert row[0] is Mark.HELD
    assert row[6] is row[7] is Mark.NOT_HELD


def test_deal_deduction_eliminates_only_proven_solutions():
    state, knowledge, _, _ = ambiguous_deal()
    all_solutions = feasible_solutions(knowledge)
    assert all_solutions is not None
    knowledge.wrong_accusations.extend(
        frozenset((item.suspect_id, item.weapon_id, item.room_id))
        for item in all_solutions if item != state.solution
    )
    deduce_deal_constraints(knowledge)
    assert knowledge.mark_of(knowledge.envelope, state.solution.suspect_id) is Mark.HELD
    assert knowledge.mark_of(knowledge.envelope, state.solution.weapon_id) is Mark.HELD
    assert knowledge.mark_of(knowledge.envelope, state.solution.room_id) is Mark.HELD


def test_incomplete_feasibility_search_does_not_change_knowledge(monkeypatch):
    from clue_engine import deal_analysis

    _, knowledge, _, _ = ambiguous_deal()
    before = [row.copy() for row in knowledge.marks]
    monkeypatch.setattr(
        deal_analysis, "feasible_solutions",
        lambda value: feasible_solutions(value, max_nodes=0),
    )
    deduce_deal_constraints(knowledge)
    assert knowledge.marks == before


def test_hand_size_propagation_is_sound():
    state = deal(random.Random(4), 4)
    sizes = tuple(map(len, state.player_hands))
    view = PlayerView(0, state.player_hands[0], (), hand_sizes=sizes)
    knowledge = knowledge_for(view, 4)
    for holder, row in enumerate(knowledge.marks):
        actual = state.player_hands[holder] if holder < 4 else {
            state.solution.suspect_id, state.solution.weapon_id, state.solution.room_id,
        }
        for card, mark in enumerate(row):
            assert mark is Mark.UNKNOWN or (mark is Mark.HELD) == (card in actual)


def test_hand_size_fills_or_closes_a_hand_and_detects_conflicts():
    row = [Mark.UNKNOWN] * 21
    knowledge = Knowledge(1, [row, [Mark.UNKNOWN] * 21], [])
    for card in range(4):
        row[card] = Mark.HELD
    assert _settle_hand_size(knowledge, 0, 4)
    assert all(mark is Mark.NOT_HELD for mark in row[4:])
    with pytest.raises(InconsistentKnowledgeError):
        _settle_hand_size(knowledge, 0, 3)
    row[:] = [Mark.NOT_HELD] * 21
    row[0] = row[1] = Mark.UNKNOWN
    assert _settle_hand_size(knowledge, 0, 2)
    assert row[:2] == [Mark.HELD, Mark.HELD]


@pytest.mark.parametrize("sizes", [(5, 5), (5, 5, 4, -1), (5, 5, 4, 3)])
def test_invalid_public_hand_sizes_are_rejected(sizes):
    with pytest.raises(ValueError, match="hand sizes"):
        knowledge_for(PlayerView(0, frozenset({0, 1, 2, 3, 4}), (), hand_sizes=sizes), 4)


def test_risk_is_optional_and_only_uses_completed_deal_counts(monkeypatch):
    from clue_engine import policies

    view = PlayerView(0, frozenset({1, 7, 13}), ())
    best = Combination(0, 6, 12)
    other = Combination(2, 6, 12)
    monkeypatch.setattr(policies, "solution_deal_counts", lambda knowledge: {best: 3, other: 1})
    safe = CustomPolicy(random.Random(0), BotStrategy(deal_analysis=True))
    risky = CustomPolicy(random.Random(0), BotStrategy(risk_accusation=True))
    legal = (*ACCUSES, *ENDTURNS)
    assert not isinstance(safe.choose(view, 4, legal), Accuse)
    assert risky.choose(view, 4, legal) == Accuse(best)
    monkeypatch.setattr(policies, "solution_deal_counts", lambda knowledge: {best: 2, other: 1})
    assert not isinstance(risky.choose(view, 4, legal), Accuse)
    monkeypatch.setattr(policies, "solution_deal_counts", lambda knowledge: None)
    assert not isinstance(risky.choose(view, 4, legal), Accuse)


@pytest.mark.parametrize(
    ("players", "rules", "seed_count"),
    [
        (4, GameRules(), 8),
        (2, GameRules(), 2),
        (3, GameRules(public_refutations=True, all_refute=True, face_up_card=True), 2),
        (6, GameRules(public_refutations=True, all_refute=True, face_up_card=True), 2),
    ],
)
def test_completed_analysis_in_play_never_excludes_the_actual_deal(players, rules, seed_count):
    completed = 0
    for seed in range(seed_count):
        engine, bots = create_game(players, seed, "strategic", game_rules=rules)
        for _ in range(1000):
            player = engine.to_move
            if player is None:
                break
            view = engine.view(player)
            legal = engine.legal_actions()
            if any(isinstance(action, Accuse) for action in legal):
                knowledge = knowledge_for(view, players)
                deduce_deal_constraints(knowledge)
                actual = (*engine.state.player_hands, frozenset((
                    engine.state.solution.suspect_id, engine.state.solution.weapon_id,
                    engine.state.solution.room_id,
                )))
                for holder, row in enumerate(knowledge.marks):
                    for card, mark in enumerate(row):
                        assert mark is Mark.UNKNOWN or (mark is Mark.HELD) == (card in actual[holder])
                counts = solution_deal_counts(knowledge)
                if counts is not None:
                    completed += 1
                    assert engine.state.solution in counts
                    deals = consistent_deals(knowledge, counts)
                    if deals is not None:
                        actual_hands = tuple(
                            sum(1 << card for card in hand) for hand in engine.state.player_hands
                        )
                        assert (engine.state.solution, actual_hands) in deals
            engine.step(bots[player].choose(view, players, legal))
        assert engine.is_over
    assert completed > 0
