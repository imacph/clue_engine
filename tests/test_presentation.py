from clue_engine.engine import Engine
from clue_engine.models import Combination, Reveal, Suggest
from clue_engine.presentation import (
    format_event,
    format_hand,
    format_knowledge,
    public_events,
)
from clue_engine.state import GameState


def test_public_events_exclude_private_show():
    engine = Engine(GameState(
        Combination(0, 6, 12),
        [frozenset({1}), frozenset({7}), frozenset({13})],
        0,
    ))
    engine.step(Suggest(Combination(0, 7, 13)))
    engine.step(Reveal(7))
    events = public_events(engine.log)
    assert len(events) == 2
    assert all("showed" not in format_event(event) for event in events)
    assert "showed Dagger" in format_event(engine.view(0).events[-1])


def test_hand_and_knowledge_formatting():
    engine = Engine(GameState(
        Combination(0, 6, 12),
        [frozenset({1}), frozenset({7})],
        0,
    ))
    view = engine.view(0)
    assert "Colonel Mustard" in format_hand(view.own_hand)
    table = format_knowledge(view, engine.num_players)
    assert "Knowledge" in table
    assert "Colonel Mustard" in table
    assert "Envelope" in table
