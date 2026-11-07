"""Formatting helpers for public and player-specific game observations."""

from .board import Square
from .board_state import RoomPosition
from .cards import CARDS, CARDS_BY_ID
from .knowledge import Knowledge, Mark, knowledge_for
from .models import Combination
from .observations import Event, EventKind, PlayerView, is_incorrect_accusation
from .observations import public_events as _public_events
from .state import GameState


def public_events(log: tuple[Event, ...]) -> tuple[Event, ...]:
    """Return only events visible without a player identity."""
    return _public_events(log)


def notebook_activity(events: tuple[Event, ...]) -> tuple[Event | None, Event | None]:
    """Return the current turn's combination and its latest visible reveal."""
    shown = None
    for index in range(len(events) - 1, -1, -1):
        event = events[index]
        if event.kind is EventKind.END_TURN:
            if index == len(events) - 1 and index > 0:
                previous = events[index - 1]
                if previous.kind is EventKind.ACCUSE and previous.actor == event.actor:
                    if previous.combo is None:
                        raise ValueError("ACCUSE event without a combination")
                    return previous, None
            break
        if event.kind is EventKind.SHOW and shown is None:
            if event.card_id is None:
                raise ValueError("SHOW event without a card")
            shown = event
        if event.kind in (EventKind.SUGGEST, EventKind.ACCUSE):
            if event.combo is None:
                raise ValueError(f"{event.kind.name} event without a combination")
            return event, shown if event.kind is EventKind.SUGGEST else None
    return None, None


def notebook_actor(
    turn: int | None, actor: int | None, viewer: int, *,
    public_refutations: bool, omniscient: bool,
) -> int | None:
    """Hide private response activity from uninvolved notebook perspectives."""
    if (
        actor is not None and turn is not None and actor != turn
        and viewer not in (turn, actor) and not public_refutations and not omniscient
    ):
        return None
    return actor


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
            if event.public:
                return f"{actor} publicly showed {CARDS_BY_ID[event.card_id].name}."
            return (
                f"{actor} showed {CARDS_BY_ID[event.card_id].name} "
                f"to Player {event.private_to}."
            )
        case EventKind.EXPOSE:
            if event.card_id is None:
                raise ValueError("EXPOSE event without a card")
            return f"{actor} started with {CARDS_BY_ID[event.card_id].name} face up."
        case EventKind.END_TURN:
            if previous is not None and (
                previous.kind is EventKind.ACCUSE and previous.actor == event.actor
            ):
                return f"{actor} was eliminated after an incorrect accusation."
            return f"{actor} ended their turn."
        case EventKind.ROLL:
            if event.dice is None:
                raise ValueError("ROLL event without dice")
            return f"{actor} rolled {event.dice[0]} and {event.dice[1]}."
        case EventKind.MOVE | EventKind.PASSAGE | EventKind.SUSPECT_MOVED:
            if event.suspect_id is None or event.location is None:
                raise ValueError(f"{event.kind.name} event without a suspect or location")
            if isinstance(event.location, Square):
                destination = f"hallway ({event.location.x}, {event.location.y})"
            elif isinstance(event.location, RoomPosition):
                destination = CARDS_BY_ID[event.location.room_id].name
            else:
                raise TypeError(f"invalid movement location: {event.location!r}")
            suspect = CARDS_BY_ID[event.suspect_id].name
            verb = "used a passage to" if event.kind is EventKind.PASSAGE else "moved to"
            return f"{actor}: {suspect} {verb} {destination}."
        case EventKind.WEAPON_MOVED:
            if event.weapon_id is None or not isinstance(event.location, RoomPosition):
                raise ValueError("WEAPON_MOVED event without a weapon or room")
            return (
                f"{actor}: {CARDS_BY_ID[event.weapon_id].name} moved to "
                f"{CARDS_BY_ID[event.location.room_id].name}."
            )
    raise ValueError(f"unknown event kind: {event.kind!r}")


def format_knowledge(view: PlayerView, num_players: int) -> str:
    knowledge = knowledge_for(view, num_players)
    labels = [f"P{i}" for i in range(num_players)] + ["Envelope"]
    symbols = {Mark.UNKNOWN: "?", Mark.HELD: "+", Mark.NOT_HELD: "-"}
    lines = [
        "Public hand sizes: " + ", ".join(
            f"P{seat}: {size}" for seat, size in enumerate(view.hand_sizes)
        ) if view.hand_sizes is not None else "Public hand sizes: unavailable",
        "Knowledge (+ held, - not held, ? unknown):",
        f"{'Card':<20} " + " ".join(f"{label:>8}" for label in labels),
    ]
    for cards in CARDS.values():
        for card in cards:
            marks = [symbols[knowledge.mark_of(holder, card.id)] for holder in range(num_players + 1)]
            lines.append(f"{card.name:<20} " + " ".join(f"{mark:>8}" for mark in marks))
    lines.extend(("", format_clauses(knowledge)))
    return "\n".join(lines)


def format_clauses(
    knowledge: Knowledge,
    *,
    view: PlayerView | None = None,
    actor: int | None = None,
    kind: EventKind | None = None,
) -> str:
    """Describe constraints, optionally filtering by their actor and source event type.

    The player view supplies accusers, which are not stored in Knowledge.
    """
    if kind not in (None, EventKind.REFUTE, EventKind.ACCUSE):
        raise ValueError("clause type must be REFUTE or ACCUSE")
    if actor is not None and view is None:
        raise ValueError("actor filtering requires the player view")

    accusation_events = None
    if view is not None:
        accusation_events = tuple(
            event for index, event in enumerate(view.events)
            if is_incorrect_accusation(view.events, index)
        )
        if len(accusation_events) != len(knowledge.wrong_accusations):
            raise ValueError("player view does not match the knowledge's incorrect accusations")
        for event, cards in zip(accusation_events, knowledge.wrong_accusations, strict=True):
            combo = event.combo
            if combo is None or frozenset(
                (combo.suspect_id, combo.weapon_id, combo.room_id)
            ) != cards:
                raise ValueError("player view does not match the knowledge's incorrect accusations")

    lines = ["Clauses:"]

    def names(cards: list[int]) -> str:
        return ", ".join(CARDS_BY_ID[card_id].name for card_id in cards)

    for clause in knowledge.clauses:
        if kind is EventKind.ACCUSE or (actor is not None and clause.holder != actor):
            continue
        cards = sorted(clause.cards)
        held = [card_id for card_id in cards if knowledge.mark_of(clause.holder, card_id) is Mark.HELD]
        remaining = [
            card_id for card_id in cards if knowledge.mark_of(clause.holder, card_id) is Mark.UNKNOWN
        ]
        status = f"satisfied: {names(held)}" if held else f"unresolved; remaining: {names(remaining)}"
        lines.append(f"Player {clause.holder} holds at least one of: {names(cards)} ({status}).")

    for index, clause in enumerate(knowledge.wrong_accusations):
        event = accusation_events[index] if accusation_events is not None else None
        if kind is EventKind.REFUTE or (actor is not None and (event is None or event.actor != actor)):
            continue
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
        source = f" by Player {event.actor}" if event is not None else ""
        lines.append(
            f"Incorrect accusation{source}: {names(cards)}; "
            f"at least one is not in the envelope ({status})."
        )
    if len(lines) == 1:
        lines.append(
            "No clauses match the current filters."
            if actor is not None or kind is not None else "No clauses recorded."
        )
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
