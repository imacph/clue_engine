"""Formatting helpers for public and player-specific game observations."""

from .cards import CARDS, CARDS_BY_ID
from .knowledge import Knowledge, Mark, knowledge_for
from .models import Combination
from .observations import Event, EventKind, PlayerView
from .observations import public_events as _public_events
from .state import GameState


def public_events(log: tuple[Event, ...]) -> tuple[Event, ...]:
    """Return only events visible without a player identity."""
    return _public_events(log)


def format_combination(combo: Combination) -> str:
    return ", ".join(
        CARDS_BY_ID[card_id].name
        for card_id in (combo.suspect_id, combo.weapon_id, combo.room_id)
    )


def format_hand(hand: frozenset[int]) -> str:
    return ", ".join(CARDS_BY_ID[card_id].name for card_id in sorted(hand)) or "(empty)"


def format_event(event: Event, previous: Event | None = None) -> str:
    actor = f"Player {event.actor}"
    match event.kind:
        case EventKind.SUGGEST | EventKind.ACCUSE:
            if event.combo is None:
                raise ValueError(f"{event.kind.name} event without a combination")
            verb = "suggested" if event.kind is EventKind.SUGGEST else "accused"
            return f"{actor} {verb}: {format_combination(event.combo)}."
        case EventKind.PASS:
            return f"{actor} passed."
        case EventKind.REFUTE:
            return f"{actor} refuted the suggestion."
        case EventKind.SHOW:
            if event.card_id is None or event.private_to is None:
                raise ValueError("SHOW event without a card or recipient")
            return (
                f"{actor} showed {CARDS_BY_ID[event.card_id].name} "
                f"to Player {event.private_to}."
            )
        case EventKind.END_TURN:
            if previous is not None and (
                previous.kind is EventKind.ACCUSE and previous.actor == event.actor
            ):
                return f"{actor} was eliminated after an incorrect accusation."
            return f"{actor} ended their turn."
    raise ValueError(f"unknown event kind: {event.kind!r}")


def format_knowledge(view: PlayerView, num_players: int) -> str:
    knowledge = knowledge_for(view, num_players)
    labels = [f"P{i}" for i in range(num_players)] + ["Envelope"]
    symbols = {Mark.UNKNOWN: "?", Mark.HELD: "+", Mark.NOT_HELD: "-"}
    lines = [
        "Knowledge (+ held, - not held, ? unknown):",
        f"{'Card':<20} " + " ".join(f"{label:>8}" for label in labels),
    ]
    for cards in CARDS.values():
        for card in cards:
            marks = [symbols[knowledge.mark_of(holder, card.id)] for holder in range(num_players + 1)]
            lines.append(f"{card.name:<20} " + " ".join(f"{mark:>8}" for mark in marks))
    lines.extend(("", format_clauses(knowledge)))
    return "\n".join(lines)


def format_clauses(knowledge: Knowledge) -> str:
    """Describe the stored refutation and incorrect-accusation constraints."""
    lines = ["Clauses:"]

    def names(cards: list[int]) -> str:
        return ", ".join(CARDS_BY_ID[card_id].name for card_id in cards)

    for clause in knowledge.clauses:
        cards = sorted(clause.cards)
        held = [card_id for card_id in cards if knowledge.mark_of(clause.holder, card_id) is Mark.HELD]
        remaining = [
            card_id for card_id in cards if knowledge.mark_of(clause.holder, card_id) is Mark.UNKNOWN
        ]
        status = f"satisfied: {names(held)}" if held else f"unresolved; remaining: {names(remaining)}"
        lines.append(f"Player {clause.holder} holds at least one of: {names(cards)} ({status}).")

    for clause in knowledge.wrong_accusations:
        cards = sorted(clause)
        excluded = [
            card_id for card_id in cards
            if knowledge.mark_of(knowledge.envelope, card_id) is Mark.NOT_HELD
        ]
        remaining = [
            card_id for card_id in cards
            if knowledge.mark_of(knowledge.envelope, card_id) is Mark.UNKNOWN
        ]
        status = (
            f"satisfied: {names(excluded)}" if excluded
            else f"unresolved; remaining: {names(remaining)}"
        )
        lines.append(f"Incorrect accusation: {names(cards)}; at least one is not in the envelope ({status}).")
    if len(lines) == 1:
        lines.append("No clauses recorded.")
    return "\n".join(lines)


def format_debug_state(state: GameState) -> str:
    """Format hidden information; callers must opt in to debugging."""
    return format_debug_information(state.solution, tuple(state.player_hands))


def format_debug_information(
    solution: Combination, hands: tuple[frozenset[int], ...]
) -> str:
    lines = [
        "WARNING: omniscient debug mode reveals all hands and the solution.",
        f"Solution: {format_combination(solution)}",
    ]
    lines.extend(
        f"Player {player} hand: {format_hand(hand)}"
        for player, hand in enumerate(hands)
    )
    return "\n".join(lines)
