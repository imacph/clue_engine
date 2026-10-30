import pytest

from clue_engine.engine import Engine, IllegalActionError
from clue_engine.models import Accuse, Combination, EndTurn, Reveal, Suggest
from clue_engine.observations import EventKind
from clue_engine.session import GameSession
from clue_engine.state import GameState

SOLUTION = Combination(0, 6, 12)
SUGGESTION = Combination(0, 7, 13)


class ScriptedPolicy:
    def __init__(self, *actions):
        self.actions = iter(actions)

    def choose(self, view, num_players, legal):
        action = next(self.actions)
        assert action in legal
        return action


def make_engine():
    return Engine(GameState(
        SOLUTION,
        [
            frozenset({1, 2, 3, 4, 5}),
            frozenset({7, 8, 9, 10, 11}),
            frozenset({13, 14, 15, 16}),
            frozenset({17, 18, 19, 20}),
        ],
        0,
    ))


def policies():
    return [ScriptedPolicy(Suggest(SUGGESTION)), ScriptedPolicy(Reveal(7)),
            ScriptedPolicy(), ScriptedPolicy()]


@pytest.mark.parametrize("viewer", [None, 2])
def test_snapshot_hides_private_events_and_other_players_legal_actions(viewer):
    session = GameSession(make_engine(), policies(), human_player=viewer)
    session.advance_bot()
    snapshot = session.snapshot()
    assert snapshot.legal_actions == ()
    session.advance_bot()
    snapshot = session.snapshot()
    assert all(event.kind is not EventKind.SHOW for event in snapshot.events)
    assert snapshot.debug_info is None


def test_player_observes_shown_card_and_debug_is_explicit():
    session = GameSession(make_engine(), policies(), human_player=0)
    session.submit(Suggest(SUGGESTION))
    session.advance_bot()
    snapshot = session.snapshot()
    assert snapshot.view is not None
    assert snapshot.view.own_hand == frozenset({1, 2, 3, 4, 5})
    assert snapshot.events[-1].kind is EventKind.SHOW
    assert snapshot.debug_info is None

    debug = GameSession(make_engine(), policies(), debug=True)
    debug.advance_bot()
    debug.advance_bot()
    assert debug.snapshot().debug_info is not None
    assert debug.snapshot().events[-1].kind is EventKind.SHOW


def test_wrong_actor_and_illegal_action_do_not_mutate_state():
    engine = make_engine()
    session = GameSession(engine, policies(), human_player=0)
    with pytest.raises(ValueError, match="human"):
        session.advance_bot()
    with pytest.raises(IllegalActionError):
        session.submit(Reveal(7))
    assert engine.log == ()
    assert session.snapshot().steps == 0
    session.submit(EndTurn())
    with pytest.raises(ValueError, match="human"):
        session.submit(EndTurn())


def test_action_limit_and_winning_on_last_action():
    policies = [ScriptedPolicy() for _ in range(4)]
    session = GameSession(make_engine(), policies, human_player=0, max_steps=1)
    session.submit(Accuse(SOLUTION))
    assert session.snapshot().is_over
    assert not session.snapshot().limit_reached
    with pytest.raises(ValueError, match="over"):
        session.submit(EndTurn())

    session = GameSession(make_engine(), policies, human_player=0, max_steps=1)
    session.submit(EndTurn())
    assert session.snapshot().limit_reached
    with pytest.raises(ValueError, match="limit"):
        session.advance_bot()
