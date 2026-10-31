from dataclasses import replace

import pytest

from clue_engine.engine import Engine
from clue_engine.knowledge import knowledge_for
from clue_engine.models import Accuse, Combination, EndTurn, Reveal, Suggest
from clue_engine.observations import EventKind
from clue_engine.presentation import (
    format_clauses,
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


def test_clause_filters_use_source_actors_for_repeated_accusations():
    engine = Engine(GameState(
        Combination(0, 6, 12),
        [frozenset({1, 2, 3, 4, 5}), frozenset({7, 8, 9, 10, 11}),
         frozenset({13, 14, 15, 16}), frozenset({17, 18, 19, 20})],
        0,
    ))
    engine.step(Suggest(Combination(0, 7, 13)))
    engine.step(Reveal(7))
    engine.step(EndTurn())
    engine.step(Accuse(Combination(2, 8, 14)))
    engine.step(Accuse(Combination(2, 8, 14)))
    engine.step(Accuse(Combination(0, 6, 12)))
    view = engine.view(0)
    knowledge = knowledge_for(view, engine.num_players)

    text = format_clauses(knowledge, view=view)
    assert "Player 1 holds at least one of" in text
    assert "Incorrect accusation by Player 1:" in text
    assert "Incorrect accusation by Player 2:" in text
    assert "Incorrect accusation by Player 3:" not in text

    text = format_clauses(knowledge, view=view, actor=1, kind=EventKind.ACCUSE)
    assert "Incorrect accusation by Player 1:" in text
    assert "Player 2" not in text
    assert "holds at least one" not in text
    text = format_clauses(knowledge, view=view, actor=1, kind=EventKind.REFUTE)
    assert "Player 1 holds at least one of" in text
    assert "Incorrect accusation" not in text
    assert "No clauses match" in format_clauses(
        knowledge, view=view, actor=2, kind=EventKind.REFUTE
    )

    with pytest.raises(ValueError, match="requires the player view"):
        format_clauses(knowledge, actor=1)
    with pytest.raises(ValueError, match="clause type"):
        format_clauses(knowledge, view=view, kind=EventKind.SHOW)
    altered_events = tuple(
        replace(event, combo=Combination(1, 6, 12))
        if event.kind is EventKind.ACCUSE and event.actor == 1 else event
        for event in view.events
    )
    with pytest.raises(ValueError, match="does not match"):
        format_clauses(knowledge, view=replace(view, events=altered_events))
