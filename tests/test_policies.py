import random

import pytest

from clue_engine.actions import ACCUSES, ENDTURNS, SUGGESTIONS
from clue_engine.engine import Engine
from clue_engine.knowledge import Mark, knowledge_for, known_solution
from clue_engine.models import Accuse, Combination, EndTurn, Pass, Reveal, Suggest
from clue_engine.observations import Event, EventKind, PlayerView, view_for
from clue_engine.policies import DeductivePolicy, RandomPolicy, sound_actions
from clue_engine.simulation import play
from clue_engine.state import deal

NUM_PLAYERS = 4
SOLUTION = Combination(suspect_id=0, weapon_id=6, room_id=12)
POLICIES = [RandomPolicy, DeductivePolicy]


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
            engine.log[:index], accusation.actor, engine.state.player_hands[accusation.actor]
        )
        assert known_solution(knowledge_for(view, NUM_PLAYERS)) == accusation.combo


@pytest.mark.parametrize("policy_cls", POLICIES)
def test_games_are_reproducible_from_a_seed(policy_cls):
    assert play_game(policy_cls, 3).log == play_game(policy_cls, 3).log


def test_deductive_play_needs_fewer_suggestions_than_random_play():
    def suggestions(policy_cls) -> int:
        return sum(
            sum(event.kind is EventKind.SUGGEST for event in play_game(policy_cls, seed).log)
            for seed in range(15)
        )

    assert suggestions(DeductivePolicy) < suggestions(RandomPolicy)
