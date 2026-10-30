from clue_engine.engine import Engine
from clue_engine.models import Accuse, Combination, Reveal, Suggest
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


def test_knowledge_displays_unresolved_and_resolved_refutation_clauses():
    engine = Engine(GameState(
        Combination(0, 6, 12),
        [frozenset({1, 2, 3, 4, 5}), frozenset({7, 8, 9, 10, 11}),
         frozenset({13, 14, 15, 16}), frozenset({17, 18, 19, 20})],
        0,
    ))
    engine.step(Suggest(Combination(0, 7, 13)))
    engine.step(Reveal(7))
    uninvolved = format_knowledge(engine.view(2), engine.num_players)
    assert "Player 1 holds at least one of: Miss Scarlet, Dagger, Ballroom" in uninvolved
    assert "unresolved" in uninvolved
    assert "remaining: Miss Scarlet, Dagger" in uninvolved
    suggester = format_knowledge(engine.view(0), engine.num_players)
    assert "satisfied" in suggester
    assert "Dagger" in suggester


def test_knowledge_displays_wrong_accusation_clause():
    engine = Engine(GameState(
        Combination(0, 6, 12),
        [frozenset({1}), frozenset({7}), frozenset({13})],
        0,
    ))
    engine.step(Accuse(Combination(1, 6, 12)))
    text = format_knowledge(engine.view(1), engine.num_players)
    assert "at least one is not in the envelope" in text
    assert "Colonel Mustard, Candlestick, Kitchen" in text
    own_view = format_knowledge(engine.view(0), engine.num_players)
    assert "satisfied: Colonel Mustard" in own_view


def test_knowledge_displays_unresolved_wrong_accusation_clause():
    engine = Engine(GameState(
        Combination(0, 6, 12),
        [frozenset({1, 2, 3, 4, 5}), frozenset({7, 8, 9, 10, 11}),
         frozenset({13, 14, 15, 16}), frozenset({17, 18, 19, 20})],
        0,
    ))
    engine.step(Accuse(Combination(2, 8, 14)))
    text = format_knowledge(engine.view(3), engine.num_players)
    assert "unresolved; remaining: Mrs. White, Lead Pipe, Conservatory" in text
