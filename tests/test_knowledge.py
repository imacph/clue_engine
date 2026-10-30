import random

import pytest

from clue_engine.actions import COMBINATIONS
from clue_engine.cards import CARDS_BY_ID
from clue_engine.knowledge import (
    Clause,
    InconsistentKnowledgeError,
    Mark,
    knowledge_for,
    known_solution,
)
from clue_engine.models import Combination
from clue_engine.observations import (
    Event,
    EventKind,
    PlayerView,
    refutation_events,
    view_for,
)
from clue_engine.state import GameState, deal

# Card ids: suspects 0-5, weapons 6-11, rooms 12-20.
NUM_PLAYERS = 4
SUGGESTED = Combination(suspect_id=0, weapon_id=7, room_id=13)


def suggest_event(actor: int = 0, combo: Combination = SUGGESTED) -> Event:
    return Event(kind=EventKind.SUGGEST, actor=actor, combo=combo)


def pass_event(actor: int) -> Event:
    return Event(kind=EventKind.PASS, actor=actor)


def make_view(player: int, hand: set[int], *events: Event) -> PlayerView:
    return PlayerView(player=player, own_hand=frozenset(hand), events=tuple(events))


def test_own_hand_is_held_and_everything_else_is_not_held_for_viewer():
    k = knowledge_for(make_view(3, {1, 2}), NUM_PLAYERS)
    assert k.mark_of(3, 1) is Mark.HELD
    assert k.mark_of(3, 2) is Mark.HELD
    assert k.mark_of(3, 0) is Mark.NOT_HELD
    assert k.mark_of(3, 20) is Mark.NOT_HELD


def test_own_cards_are_not_held_by_anyone_else():
    k = knowledge_for(make_view(3, {1, 2}), NUM_PLAYERS)
    for holder in (0, 1, 2, k.envelope):
        assert k.mark_of(holder, 1) is Mark.NOT_HELD


def test_pass_means_passer_holds_none_of_the_suggested_cards():
    view = make_view(0, {1}, suggest_event(), pass_event(1))
    k = knowledge_for(view, NUM_PLAYERS)
    for card_id in (0, 7, 13):
        assert k.mark_of(1, card_id) is Mark.NOT_HELD


def test_public_refute_records_clause_without_resolving_it():
    suggest = suggest_event()
    refute, _ = refutation_events(refuter=2, refutation_card_id=7, suggest=suggest)
    view = make_view(3, {1, 2}, suggest, pass_event(1), refute)
    k = knowledge_for(view, NUM_PLAYERS)
    assert k.clauses == [Clause(holder=2, cards=frozenset({0, 7, 13}))]
    for card_id in (0, 7, 13):
        assert k.mark_of(2, card_id) is Mark.UNKNOWN


def test_clause_resolves_when_other_cards_are_ruled_out():
    suggest = suggest_event()
    refute, _ = refutation_events(refuter=2, refutation_card_id=13, suggest=suggest)
    # Viewer 3 holds 0 and 7 and so knows player 2 must hold 13.
    view = make_view(3, {0, 7}, suggest, pass_event(1), refute)
    k = knowledge_for(view, NUM_PLAYERS)
    assert k.mark_of(2, 13) is Mark.HELD


def test_suggester_learns_the_shown_card():
    suggest = suggest_event()
    refute, show = refutation_events(refuter=2, refutation_card_id=7, suggest=suggest)
    log = (suggest, pass_event(1), refute, show)
    k = knowledge_for(view_for(log, player=0, own_hand=frozenset({1})), NUM_PLAYERS)
    assert k.mark_of(2, 7) is Mark.HELD


def test_uninvolved_player_does_not_learn_the_shown_card():
    suggest = suggest_event()
    refute, show = refutation_events(refuter=2, refutation_card_id=7, suggest=suggest)
    log = (suggest, pass_event(1), refute, show)
    k = knowledge_for(view_for(log, player=3, own_hand=frozenset({1})), NUM_PLAYERS)
    assert k.mark_of(2, 7) is Mark.UNKNOWN


def test_envelope_card_deduced_from_category_exclusion():
    # Viewer holds the five other suspects, so the envelope must hold suspect 0.
    k = knowledge_for(make_view(0, {1, 2, 3, 4, 5}), NUM_PLAYERS)
    assert k.mark_of(k.envelope, 0) is Mark.HELD
    assert k.mark_of(1, 0) is Mark.NOT_HELD


def test_solution_deduced_when_everyone_passes_on_it():
    solution = Combination(suspect_id=0, weapon_id=6, room_id=12)
    log = (suggest_event(0, solution), pass_event(1), pass_event(2), pass_event(3))
    k = knowledge_for(make_view(0, {1, 2, 3, 4, 5}, *log), NUM_PLAYERS)
    assert known_solution(k) == solution


def test_solution_unknown_without_evidence():
    k = knowledge_for(make_view(0, {1, 2, 3}), NUM_PLAYERS)
    assert known_solution(k) is None


def test_passing_on_a_card_the_viewer_holds_is_inconsistent():
    view = make_view(3, {0}, suggest_event(), pass_event(3))
    with pytest.raises(InconsistentKnowledgeError):
        knowledge_for(view, NUM_PLAYERS)


def test_two_holders_of_the_same_card_is_inconsistent():
    suggest = suggest_event()
    show = Event(kind=EventKind.SHOW, actor=2, card_id=1, private_to=0)
    with pytest.raises(InconsistentKnowledgeError):
        knowledge_for(make_view(0, {1}, suggest, show), NUM_PLAYERS)


def test_response_before_any_suggestion_is_rejected():
    with pytest.raises(ValueError):
        knowledge_for(make_view(0, {1}, pass_event(1)), NUM_PLAYERS)


def truth(state: GameState, holder: int, card_id: int) -> bool:
    if holder == len(state.player_hands):
        return card_id in {state.solution.suspect_id, state.solution.weapon_id, state.solution.room_id}
    return card_id in state.player_hands[holder]


def play_suggestion(state: GameState, suggester: int, combo: Combination) -> list[Event]:
    """Responses follow the rules: seats in order, refute with the lowest matching card."""
    suggest = suggest_event(suggester, combo)
    events = [suggest]
    cards = {combo.suspect_id, combo.weapon_id, combo.room_id}
    num_players = len(state.player_hands)
    for offset in range(1, num_players):
        seat = (suggester + offset) % num_players
        matching = sorted(cards & state.player_hands[seat])
        if not matching:
            events.append(pass_event(seat))
            continue
        events.extend(refutation_events(seat, matching[0], suggest))
        break
    return events


@pytest.mark.parametrize("seed", range(10))
def test_deductions_are_sound_against_the_real_deal(seed):
    rng = random.Random(seed)
    state = deal(rng, NUM_PLAYERS)
    log: list[Event] = []
    for turn in range(12):
        log.extend(play_suggestion(state, turn % NUM_PLAYERS, rng.choice(COMBINATIONS)))

    for viewer in range(NUM_PLAYERS):
        view = view_for(tuple(log), viewer, state.player_hands[viewer])
        k = knowledge_for(view, NUM_PLAYERS)
        for holder in range(NUM_PLAYERS + 1):
            for card_id in CARDS_BY_ID:
                mark = k.mark_of(holder, card_id)
                if mark is Mark.HELD:
                    assert truth(state, holder, card_id)
                elif mark is Mark.NOT_HELD:
                    assert not truth(state, holder, card_id)
