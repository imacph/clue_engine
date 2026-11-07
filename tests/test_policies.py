import random

import pytest

from clue_engine.actions import ACCUSES, ENDTURNS, SUGGESTIONS
from clue_engine.deal_analysis import solution_deal_counts
from clue_engine.engine import Engine
from clue_engine.knowledge import Mark, knowledge_for, known_solution
from clue_engine.models import Accuse, Combination, EndTurn, Pass, Reveal, Suggest
from clue_engine.observations import Event, EventKind, PlayerView, view_for
from clue_engine.policies import (
    DeductivePolicy,
    ProbingPolicy,
    RandomPolicy,
    StrategicPolicy,
    sound_actions,
)
from clue_engine.session import create_game
from clue_engine.simulation import play
from clue_engine.state import GameState, deal

NUM_PLAYERS = 4
SOLUTION = Combination(suspect_id=0, weapon_id=6, room_id=12)
POLICIES = [RandomPolicy, DeductivePolicy, ProbingPolicy, StrategicPolicy]
ADVANCED_POLICIES = [ProbingPolicy, StrategicPolicy]


def solved_view() -> PlayerView:
    """Player 0 holds the other suspects and everyone passed on the solution."""
    log = (
        Event(EventKind.SUGGEST, 0, combo=SOLUTION),
        Event(EventKind.PASS, 1),
        Event(EventKind.PASS, 2),
        Event(EventKind.PASS, 3),
    )
    return PlayerView(player=0, own_hand=frozenset({1, 2, 3, 4, 5}), events=log)


def unsolved_view() -> PlayerView:
    return PlayerView(player=0, own_hand=frozenset({1, 2, 3}), events=())


def play_game(policy_cls, seed: int) -> Engine:
    rng = random.Random(seed)
    engine = Engine(deal(rng, NUM_PLAYERS))
    return play(engine, [policy_cls(rng) for _ in range(NUM_PLAYERS)])


def test_sound_actions_drops_every_accusation_when_solution_unknown():
    legal = (*ACCUSES, *ENDTURNS)
    assert sound_actions(legal, None) == ENDTURNS


def test_sound_actions_keeps_other_actions_untouched():
    legal = (*SUGGESTIONS, *ACCUSES, *ENDTURNS)
    assert sound_actions(legal, None) == (*SUGGESTIONS, *ENDTURNS)


def test_sound_actions_forces_the_known_solution_accusation():
    legal = (*SUGGESTIONS, *ACCUSES, *ENDTURNS)
    assert sound_actions(legal, SOLUTION) == (Accuse(SOLUTION),)


def test_sound_actions_cannot_accuse_when_accusing_is_not_legal():
    legal = (Pass(),)
    assert sound_actions(legal, SOLUTION) == (Pass(),)


@pytest.mark.parametrize("policy_cls", POLICIES)
def test_policy_accuses_once_the_solution_is_deduced(policy_cls):
    view = solved_view()
    assert known_solution(knowledge_for(view, NUM_PLAYERS)) == SOLUTION
    legal = (*SUGGESTIONS, *ACCUSES, *ENDTURNS)
    policy = policy_cls(random.Random(0))
    assert policy.choose(view, NUM_PLAYERS, legal) == Accuse(SOLUTION)


@pytest.mark.parametrize("policy_cls", POLICIES)
def test_policy_never_accuses_while_the_solution_is_unknown(policy_cls):
    policy = policy_cls(random.Random(0))
    legal = (*ACCUSES, *ENDTURNS)
    for _ in range(50):
        assert policy.choose(unsolved_view(), NUM_PLAYERS, legal) == EndTurn()


@pytest.mark.parametrize("policy_cls", POLICIES)
def test_policy_picks_only_from_the_legal_responses(policy_cls):
    policy = policy_cls(random.Random(0))
    legal = (Reveal(2), Reveal(3))
    for _ in range(20):
        assert policy.choose(unsolved_view(), NUM_PLAYERS, legal) in legal
    assert policy.choose(unsolved_view(), NUM_PLAYERS, (Pass(),)) == Pass()


def test_deductive_suggestions_avoid_cards_known_to_be_outside_the_solution():
    view = unsolved_view()
    knowledge = knowledge_for(view, NUM_PLAYERS)
    policy = DeductivePolicy(random.Random(0))
    legal = (*SUGGESTIONS, *ACCUSES, *ENDTURNS)
    for _ in range(50):
        action = policy.choose(view, NUM_PLAYERS, legal)
        assert isinstance(action, Suggest)
        combo = action.combination
        for card_id in (combo.suspect_id, combo.weapon_id, combo.room_id):
            assert knowledge.mark_of(knowledge.envelope, card_id) is not Mark.NOT_HELD


def test_deductive_policy_respects_restricted_suggestion_actions():
    legal = (Suggest(Combination(0, 6, 12)),)
    policy = DeductivePolicy(random.Random(0))
    assert policy.choose(unsolved_view(), NUM_PLAYERS, legal) in legal


def test_probing_policy_isolates_unknown_card_with_own_controls():
    view = PlayerView(player=0, own_hand=frozenset({1, 7, 13}), events=())
    probe = Suggest(Combination(0, 7, 13))
    legal = (probe, Suggest(Combination(0, 6, 12)), EndTurn())
    assert ProbingPolicy(random.Random(0)).choose(view, NUM_PLAYERS, legal) == probe


@pytest.mark.parametrize("policy_cls", ADVANCED_POLICIES)
@pytest.mark.parametrize("target,holder", [(0, None), (4, 1)])
def test_controlled_probe_learns_envelope_or_holder(policy_cls, target, holder):
    engine = Engine(GameState(
        Combination(0, 6, 12),
        [frozenset({1, 2, 3, 7, 13}), frozenset({4, 8, 14, 15, 16}),
         frozenset({5, 9, 17, 18, 19}), frozenset({10, 11, 20})],
        0,
    ))
    probe = Suggest(Combination(target, 7, 13))
    policy = policy_cls(random.Random(0))
    assert policy.choose(engine.view(0), NUM_PLAYERS, (probe,)) == probe
    engine.step(probe)
    while engine.to_move != 0:
        engine.step(engine.legal_actions()[0])
    knowledge = knowledge_for(engine.view(0), NUM_PLAYERS)
    assert knowledge.mark_of(knowledge.envelope if holder is None else holder, target) is Mark.HELD


def test_known_envelope_card_is_a_valid_probe_control():
    view = PlayerView(player=0, own_hand=frozenset({7, 8, 9, 10, 11, 13}), events=())
    probe = Suggest(Combination(0, 6, 13))
    legal = (probe, Suggest(Combination(0, 6, 12)))
    assert ProbingPolicy(random.Random(0)).choose(view, NUM_PLAYERS, legal) == probe


def test_strategic_prefers_solution_candidates_to_forced_probes():
    view = PlayerView(player=0, own_hand=frozenset({1, 7, 13}), events=())
    candidate = Suggest(Combination(0, 6, 12))
    probe = Suggest(Combination(0, 7, 13))
    assert StrategicPolicy(random.Random(0)).choose(view, NUM_PLAYERS, (probe, candidate)) == candidate


@pytest.mark.parametrize("policy_cls", ADVANCED_POLICIES)
def test_advanced_policy_repeats_a_card_shown_to_same_recipient(policy_cls):
    events = (
        Event(EventKind.SUGGEST, 0, combo=Combination(0, 7, 12)),
        Event(EventKind.REFUTE, 1),
        Event(EventKind.SHOW, 1, card_id=7, private_to=0),
        Event(EventKind.END_TURN, 0),
        Event(EventKind.SUGGEST, 0, combo=Combination(0, 7, 13)),
    )
    view = PlayerView(1, frozenset({7, 13}), events)
    legal = (Reveal(7), Reveal(13))
    assert policy_cls(random.Random(0)).choose(view, NUM_PLAYERS, legal) == Reveal(7)
    different_recipient = PlayerView(
        1, view.own_hand, (*events[:-1], Event(EventKind.SUGGEST, 2, combo=Combination(0, 7, 13)))
    )
    assert policy_cls(random.Random(0)).choose(different_recipient, NUM_PLAYERS, legal) == Reveal(13)


@pytest.mark.parametrize("policy_cls", ADVANCED_POLICIES)
@pytest.mark.parametrize("kind", [EventKind.EXPOSE, EventKind.SHOW])
def test_advanced_policy_prefers_an_already_public_card(policy_cls, kind):
    events = (
        Event(kind, 1, card_id=7, private_to=3 if kind is EventKind.SHOW else None, public=True),
        Event(EventKind.SUGGEST, 2, combo=Combination(0, 7, 13)),
    )
    view = PlayerView(1, frozenset({7, 13}), events)
    assert policy_cls(random.Random(0)).choose(view, NUM_PLAYERS, (Reveal(7), Reveal(13))) == Reveal(7)


@pytest.mark.parametrize("policy_cls", ADVANCED_POLICIES)
def test_advanced_policy_cannot_use_unseen_private_cards(policy_cls):
    public = Event(EventKind.SUGGEST, 0, combo=Combination(0, 7, 12))
    refute = Event(EventKind.REFUTE, 1)
    latest = Event(EventKind.SUGGEST, 2, combo=Combination(0, 8, 13))
    base = (public, refute)
    hidden_a = Event(EventKind.SHOW, 1, card_id=7, private_to=0)
    hidden_b = Event(EventKind.SHOW, 1, card_id=12, private_to=0)
    view_a = view_for((*base, hidden_a, latest), 3, frozenset({8, 13}))
    view_b = view_for((*base, hidden_b, latest), 3, frozenset({8, 13}))
    assert view_a == view_b
    legal = (Reveal(8), Reveal(13))
    assert policy_cls(random.Random(4)).choose(view_a, NUM_PLAYERS, legal) == (
        policy_cls(random.Random(4)).choose(view_b, NUM_PLAYERS, legal)
    )


def test_strategic_policy_avoids_a_known_early_blocker():
    events = (
        Event(EventKind.SUGGEST, 0, combo=Combination(4, 6, 12)),
        Event(EventKind.REFUTE, 1),
        Event(EventKind.SHOW, 1, card_id=4, private_to=0),
        Event(EventKind.END_TURN, 0),
    )
    view = PlayerView(0, frozenset({1, 7}), events)
    blocked = Suggest(Combination(4, 8, 14))
    useful = Suggest(Combination(0, 8, 14))
    assert StrategicPolicy(random.Random(0)).choose(view, NUM_PLAYERS, (blocked, useful)) == useful


def test_strategic_policy_prefers_probe_relevant_to_unresolved_clause():
    events = (
        Event(EventKind.SUGGEST, 3, combo=Combination(0, 6, 12)),
        Event(EventKind.PASS, 0),
        Event(EventKind.PASS, 1),
        Event(EventKind.REFUTE, 2),
        Event(EventKind.END_TURN, 3),
    )
    view = PlayerView(0, frozenset({1, 7, 13}), events)
    clause_probe = Suggest(Combination(0, 7, 13))
    other_probe = Suggest(Combination(2, 7, 13))
    assert StrategicPolicy(random.Random(0)).choose(view, NUM_PLAYERS, (other_probe, clause_probe)) == clause_probe


@pytest.mark.parametrize(
    "name,expected",
    [
        ("random", [
            Suggest(Combination(0, 10, 18)), Pass(), Pass(), Reveal(10), EndTurn(),
            Suggest(Combination(0, 8, 14)), Reveal(14), EndTurn(),
        ]),
        ("deductive", [
            Suggest(Combination(0, 10, 12)), Pass(), Reveal(12), EndTurn(),
            Suggest(Combination(0, 8, 16)), Pass(), Reveal(0), EndTurn(),
        ]),
    ],
)
def test_existing_seeded_policy_behavior_is_preserved(name, expected):
    engine, bots = create_game(4, 17, name)
    actual = []
    for _ in expected:
        player = engine.to_move
        assert player is not None
        action = bots[player].choose(engine.view(player), engine.num_players, engine.legal_actions())
        actual.append(action)
        engine.step(action)
    assert actual == expected


def accusation_indexes(engine: Engine) -> list[int]:
    return [i for i, event in enumerate(engine.log) if event.kind is EventKind.ACCUSE]


@pytest.mark.parametrize("policy_cls", POLICIES)
@pytest.mark.parametrize("seed", range(15))
def test_games_are_won_by_a_correct_deduced_accusation(policy_cls, seed):
    engine = play_game(policy_cls, seed)
    assert engine.winner is not None
    assert len(accusation_indexes(engine)) == 1
    assert engine.log[-1].combo == engine.state.solution


@pytest.mark.parametrize("policy_cls", POLICIES)
@pytest.mark.parametrize("seed", range(15))
def test_every_accusation_was_implied_by_the_accusers_knowledge_at_the_time(policy_cls, seed):
    engine = play_game(policy_cls, seed)
    for index in accusation_indexes(engine):
        accusation = engine.log[index]
        view = view_for(
            engine.log[:index], accusation.actor, engine.state.player_hands[accusation.actor],
            hand_sizes=tuple(map(len, engine.state.player_hands)),
        )
        knowledge = knowledge_for(view, NUM_PLAYERS)
        if known_solution(knowledge) is None:
            assert policy_cls is StrategicPolicy
            assert set(solution_deal_counts(knowledge)) == {accusation.combo}
        else:
            assert known_solution(knowledge) == accusation.combo


@pytest.mark.parametrize("policy_cls", POLICIES)
def test_games_are_reproducible_from_a_seed(policy_cls):
    assert play_game(policy_cls, 3).log == play_game(policy_cls, 3).log


@pytest.mark.parametrize("policy_cls", ADVANCED_POLICIES)
@pytest.mark.parametrize("players", [2, 3, 6])
def test_advanced_policies_finish_with_different_player_counts(policy_cls, players):
    engine = Engine(deal(random.Random(21), players))
    bots = [policy_cls(random.Random(f"21:{seat}")) for seat in range(players)]
    play(engine, bots, max_steps=1_000)
    assert engine.winner is not None
    accusation = engine.log[-1]
    winner_view = view_for(
        engine.log[:-1], accusation.actor, engine.state.player_hands[accusation.actor],
        hand_sizes=tuple(map(len, engine.state.player_hands)),
    )
    knowledge = knowledge_for(winner_view, players)
    if known_solution(knowledge) is None:
        assert policy_cls is StrategicPolicy
        assert set(solution_deal_counts(knowledge)) == {accusation.combo}
    else:
        assert known_solution(knowledge) == accusation.combo


def test_deductive_play_needs_fewer_suggestions_than_random_play():
    def suggestions(policy_cls) -> int:
        return sum(
            sum(event.kind is EventKind.SUGGEST for event in play_game(policy_cls, seed).log)
            for seed in range(15)
        )

    assert suggestions(DeductivePolicy) < suggestions(RandomPolicy)
