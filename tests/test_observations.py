from clue_engine.observations import (
    Event,
    EventKind,
    Pending,
    PlayerView,
    pending,
    refutation_events,
    view_for,
    visible_to,
)


def test_event_privacy():
    event = Event(kind=EventKind.SHOW, actor=1, card_id=0, private_to=2)
    assert visible_to(event, 1) is True
    assert visible_to(event, 2) is True
    assert visible_to(event, 3) is False


SUGGEST_BY_0 = Event(kind=EventKind.SUGGEST, actor=0)
def PASS(actor: int) -> Event:
    return Event(kind=EventKind.PASS, actor=actor)


def test_pending_none_without_suggestion():
    assert pending((), num_players=4) is None


def test_pending_first_responder_is_next_seat_after_suggester():
    assert pending((SUGGEST_BY_0,), num_players=4) == Pending(1)


def test_pending_advances_past_passes():
    log = (SUGGEST_BY_0, PASS(1))
    assert pending(log, num_players=4) == Pending(2)


def test_pending_wraps_around_seats():
    log = (Event(kind=EventKind.SUGGEST, actor=2), PASS(3))
    assert pending(log, num_players=4) == Pending(0)


def test_pending_none_when_everyone_passes():
    log = (SUGGEST_BY_0, PASS(1), PASS(2), PASS(3))
    assert pending(log, num_players=4) is None


def test_pending_none_after_refutation():
    refute = Event(kind=EventKind.REFUTE, actor=1)
    assert pending((SUGGEST_BY_0, refute), num_players=4) is None


def test_pending_ignores_responses_before_latest_suggestion():
    log = (
        SUGGEST_BY_0,
        PASS(1), PASS(2), PASS(3),
        Event(kind=EventKind.SUGGEST, actor=1),
    )
    assert pending(log, num_players=4) == Pending(2)


def test_pending_ignores_refutation_before_latest_suggestion():
    refute = Event(kind=EventKind.REFUTE, actor=1)
    log = (SUGGEST_BY_0, refute, Event(kind=EventKind.SUGGEST, actor=2))
    assert pending(log, num_players=4) == Pending(3)


def test_refutation_public_refute_hides_card():
    refute, _ = refutation_events(refuter=2, refutation_card_id=5, suggest=SUGGEST_BY_0)
    assert refute.kind is EventKind.REFUTE
    assert refute.actor == 2
    assert refute.card_id is None
    assert refute.private_to is None


def test_refutation_show_is_private_to_suggester():
    _, show = refutation_events(refuter=2, refutation_card_id=5, suggest=SUGGEST_BY_0)
    assert show.kind is EventKind.SHOW
    assert show.actor == 2
    assert show.card_id == 5
    assert show.private_to == 0


def test_view_for_uninvolved_player_never_sees_card():
    refute, show = refutation_events(refuter=2, refutation_card_id=5, suggest=SUGGEST_BY_0)
    log = (SUGGEST_BY_0, refute, show)
    for player in (1, 3):
        view = view_for(log, player=player, own_hand=frozenset())
        assert show not in view.events
        assert refute in view.events


def test_view_for_suggester_and_refuter_see_show():
    refute, show = refutation_events(refuter=2, refutation_card_id=5, suggest=SUGGEST_BY_0)
    log = (SUGGEST_BY_0, refute, show)
    assert show in view_for(log, player=0, own_hand=frozenset()).events
    assert show in view_for(log, player=2, own_hand=frozenset()).events


def test_view_for_keeps_own_hand():
    hand = frozenset({3, 7, 15})
    view = view_for((SUGGEST_BY_0,), player=1, own_hand=hand)
    assert isinstance(view, PlayerView)
    assert view.player == 1
    assert view.own_hand == hand
    assert view.events == (SUGGEST_BY_0,)
