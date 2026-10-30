from clue_engine.actions import ACCUSES, ENDTURNS, SUGGESTIONS
from clue_engine.models import Combination, Pass, Reveal
from clue_engine.observations import Event, EventKind, refutation_events
from clue_engine.rules import eliminated, is_over, legal_actions
from clue_engine.state import GameState

# Card ids: suspects 0-5, weapons 6-11, rooms 12-20.
SOLUTION = Combination(suspect_id=0, weapon_id=6, room_id=12)
WRONG = Combination(suspect_id=1, weapon_id=6, room_id=12)
SUGGESTED = Combination(suspect_id=0, weapon_id=7, room_id=13)

HANDS = [
    frozenset({1}),        # player 0: no matching card for SUGGESTED
    frozenset({0, 7}),     # player 1: holds both the suspect and the weapon
    frozenset({13}),       # player 2: holds the room
    frozenset({14, 15}),   # player 3: no matching card
]


def make_state(current_player: int = 0) -> GameState:
    return GameState(solution=SOLUTION, player_hands=list(HANDS), current_player=current_player)


def suggest_event(actor: int = 0) -> Event:
    return Event(kind=EventKind.SUGGEST, actor=actor, combo=SUGGESTED)


def pass_event(actor: int) -> Event:
    return Event(kind=EventKind.PASS, actor=actor)


def end_turn_event(actor: int) -> Event:
    return Event(kind=EventKind.END_TURN, actor=actor)


def accuse_event(actor: int, combo: Combination) -> Event:
    return Event(kind=EventKind.ACCUSE, actor=actor, combo=combo)


def test_turn_owner_may_suggest_accuse_or_end_turn_at_start():
    legal = legal_actions(make_state(current_player=0), (), player=0)
    assert set(legal) == {*SUGGESTIONS, *ACCUSES, *ENDTURNS}


def test_player_off_turn_has_no_actions_when_nothing_is_pending():
    assert legal_actions(make_state(current_player=0), (), player=2) == ()


def test_responder_with_matching_cards_may_only_reveal_them():
    log = (suggest_event(),)
    assert legal_actions(make_state(), log, player=1) == (Reveal(0), Reveal(7))


def test_responder_with_one_matching_card_may_only_reveal_it():
    log = (suggest_event(), pass_event(1))
    assert legal_actions(make_state(), log, player=2) == (Reveal(13),)


def test_responder_without_matching_cards_may_only_pass():
    log = (suggest_event(), pass_event(1), pass_event(2))
    assert legal_actions(make_state(), log, player=3) == (Pass(),)


def test_suggester_has_no_actions_while_a_response_is_pending():
    log = (suggest_event(),)
    assert legal_actions(make_state(), log, player=0) == ()


def test_seat_after_pending_responder_has_no_actions():
    log = (suggest_event(),)
    assert legal_actions(make_state(), log, player=2) == ()


def test_after_refutation_suggester_may_accuse_or_end_turn_but_not_suggest():
    suggest = suggest_event()
    refute, show = refutation_events(refuter=1, refutation_card_id=0, suggest=suggest)
    log = (suggest, refute, show)
    legal = legal_actions(make_state(), log, player=0)
    assert set(legal) == {*ACCUSES, *ENDTURNS}


def test_after_everyone_passes_suggester_may_accuse_or_end_turn():
    log = (suggest_event(), pass_event(1), pass_event(2), pass_event(3))
    legal = legal_actions(make_state(), log, player=0)
    assert set(legal) == {*ACCUSES, *ENDTURNS}


def test_new_turn_allows_suggesting_again():
    log = (
        suggest_event(),
        pass_event(1), pass_event(2), pass_event(3),
        end_turn_event(0),
    )
    legal = legal_actions(make_state(current_player=0), log, player=0)
    assert set(legal) == {*SUGGESTIONS, *ACCUSES, *ENDTURNS}


def test_wrong_accusation_eliminates_actor_to_end_turn_only():
    log = (accuse_event(0, WRONG),)
    state = make_state(current_player=0)
    assert eliminated(state, log) == frozenset({0})
    assert legal_actions(state, log, player=0) == ENDTURNS


def test_eliminated_player_still_refutes():
    log = (
        accuse_event(1, WRONG),
        end_turn_event(1),
        suggest_event(actor=0),
    )
    assert legal_actions(make_state(), log, player=1) == (Reveal(0), Reveal(7))


def test_correct_accusation_ends_the_game_for_everyone():
    log = (accuse_event(0, SOLUTION),)
    state = make_state()
    assert is_over(state, log)
    for player in range(len(HANDS)):
        assert legal_actions(state, log, player=player) == ()


def test_wrong_accusation_does_not_end_the_game():
    log = (accuse_event(0, WRONG),)
    assert not is_over(make_state(), log)
