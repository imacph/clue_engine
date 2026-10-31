import random

import pytest

from clue_engine.game_settings import BotStrategy
from clue_engine.knowledge import knowledge_for
from clue_engine.models import Combination, EndTurn, Reveal, Suggest
from clue_engine.observations import Event, EventKind, PlayerView, view_for
from clue_engine.policies import CustomPolicy
from clue_engine.session import create_board_game, create_game
from clue_engine.simulation import play


def test_custom_strategy_validation():
    with pytest.raises(TypeError):
        BotStrategy(rank_suggestions=1)


def test_prefer_suggestion_does_not_end_card_only_turn():
    engine, _ = create_game(4, 17, "random")
    policy = CustomPolicy(random.Random(2), BotStrategy(prefer_suggest=True))
    for _ in range(20):
        assert isinstance(policy.choose(engine.view(0), 4, engine.legal_actions()), Suggest)


def test_repeat_reveal_uses_only_own_visible_history():
    engine, _ = create_game(4, 17, "random")
    view = engine.view(0)
    shown = next(iter(view.own_hand))
    other = next(card for card in view.own_hand if card != shown)
    from dataclasses import replace
    view = replace(view, events=(
        Event(EventKind.SHOW, 0, card_id=shown, private_to=1),
        Event(EventKind.SUGGEST, 1, combo=engine.state.solution),
    ))
    policy = CustomPolicy(random.Random(5), BotStrategy(repeat_reveals=True))
    assert policy.choose(view, 4, (Reveal(shown), Reveal(other))) == Reveal(shown)


def test_candidate_and_probe_strategy_have_distinct_precedence():
    view = PlayerView(0, frozenset({1, 7, 13}), ())
    probe = Suggest(Combination(0, 7, 13))
    candidate = Suggest(Combination(0, 6, 12))
    legal = (probe, candidate, EndTurn())
    candidate_bot = CustomPolicy(random.Random(0), BotStrategy(
        candidate_suggestions=True, prefer_suggest=True,
    ))
    probe_bot = CustomPolicy(random.Random(0), BotStrategy(
        candidate_suggestions=True, probe_suggestions=True, prefer_suggest=True,
    ))
    assert candidate_bot.choose(view, 4, legal) == candidate
    assert probe_bot.choose(view, 4, legal) == probe


def test_ranking_avoids_a_known_blocker_without_enabling_probes():
    events = (
        Event(EventKind.SUGGEST, 0, combo=Combination(4, 6, 12)),
        Event(EventKind.REFUTE, 1),
        Event(EventKind.SHOW, 1, card_id=4, private_to=0),
        Event(EventKind.END_TURN, 0),
    )
    view = PlayerView(0, frozenset({1, 7}), events)
    blocked = Suggest(Combination(4, 8, 14))
    useful = Suggest(Combination(0, 8, 14))
    policy = CustomPolicy(random.Random(0), BotStrategy(
        rank_suggestions=True, prefer_suggest=True,
    ))
    assert policy.choose(view, 4, (blocked, useful)) == useful


def test_candidate_room_preference_uses_player_knowledge():
    knowledge = knowledge_for(PlayerView(0, frozenset({12}), ()), 4)
    baseline = CustomPolicy(random.Random(0), BotStrategy())
    selective = CustomPolicy(random.Random(0), BotStrategy(candidate_rooms=True))
    assert selective._room_penalty(knowledge, 12, ()) == baseline._room_penalty(knowledge, 12, ()) + 2
    assert selective._room_penalty(knowledge, 13, ()) == baseline._room_penalty(knowledge, 13, ())


def test_custom_policy_ignores_unseen_private_cards():
    suggestion = Event(EventKind.SUGGEST, 1, combo=Combination(0, 6, 12))
    first = Event(EventKind.SHOW, 2, card_id=0, private_to=1)
    second = Event(EventKind.SHOW, 2, card_id=6, private_to=1)
    view_a = view_for((suggestion, first), 3, frozenset({8, 13}))
    view_b = view_for((suggestion, second), 3, frozenset({8, 13}))
    config = BotStrategy(repeat_reveals=True)
    legal = (Reveal(8), Reveal(13))
    assert CustomPolicy(random.Random(4), config).choose(view_a, 4, legal) == (
        CustomPolicy(random.Random(4), config).choose(view_b, 4, legal)
    )


@pytest.mark.parametrize("board", [False, True])
def test_custom_bots_make_legal_progress(board):
    factory = create_board_game if board else create_game
    engine, _ = factory(3, 42, "random")
    strategy = BotStrategy(
        candidate_suggestions=True, probe_suggestions=True, rank_suggestions=True,
        repeat_reveals=True, candidate_rooms=True, prefer_suggest=True,
    )
    bots = tuple(CustomPolicy(random.Random(seat), strategy) for seat in range(3))
    result = play(engine, bots, max_steps=2000)
    assert result.is_over
