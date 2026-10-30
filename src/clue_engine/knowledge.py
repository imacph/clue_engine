from dataclasses import dataclass
from enum import Enum, auto

from .cards import CARDS, CARDS_BY_ID
from .models import CardType, Combination
from .observations import Event, EventKind, PlayerView


class Mark(Enum):
    UNKNOWN = auto()
    HELD = auto()
    NOT_HELD = auto()


class InconsistentKnowledgeError(ValueError):
    pass


@dataclass(frozen=True)
class Clause:
    """The holder has at least one of these cards."""
    holder: int
    cards: frozenset[int]


@dataclass
class Knowledge:
    """One player's deductions, derived from their view. Row `envelope` is the solution."""
    num_players: int
    marks: list[list[Mark]]
    clauses: list[Clause]

    @property
    def envelope(self) -> int:
        return self.num_players

    def mark_of(self, holder: int, card_id: int) -> Mark:
        return self.marks[holder][card_id]


def knowledge_for(view: PlayerView, num_players: int) -> Knowledge:
    knowledge = Knowledge(
        num_players=num_players,
        marks=[[Mark.UNKNOWN] * len(CARDS_BY_ID) for _ in range(num_players + 1)],
        clauses=[],
    )
    for card_id in CARDS_BY_ID:
        mark = Mark.HELD if card_id in view.own_hand else Mark.NOT_HELD
        _set(knowledge, view.player, card_id, mark)

    suggested: frozenset[int] | None = None
    for event in view.events:
        match event.kind:
            case EventKind.SUGGEST:
                suggested = _suggested_cards(event)
            case EventKind.PASS:
                for card_id in _require_suggestion(suggested):
                    _set(knowledge, event.actor, card_id, Mark.NOT_HELD)
            case EventKind.REFUTE:
                knowledge.clauses.append(Clause(event.actor, _require_suggestion(suggested)))
            case EventKind.SHOW:
                if event.card_id is None:
                    raise ValueError("SHOW event without a card")
                _set(knowledge, event.actor, event.card_id, Mark.HELD)

    _propagate(knowledge)
    return knowledge


def known_solution(knowledge: Knowledge) -> Combination | None:
    """The solution, once the envelope row pins down one card per category."""
    found = {
        card_type: [
            card.id for card in cards
            if knowledge.mark_of(knowledge.envelope, card.id) is Mark.HELD
        ]
        for card_type, cards in CARDS.items()
    }
    if any(len(ids) != 1 for ids in found.values()):
        return None
    return Combination(
        found[CardType.SUSPECT][0],
        found[CardType.WEAPON][0],
        found[CardType.ROOM][0],
    )


def _suggested_cards(event: Event) -> frozenset[int]:
    combo = event.combo
    if combo is None:
        raise ValueError("SUGGEST event without a combination")
    return frozenset({combo.suspect_id, combo.weapon_id, combo.room_id})


def _require_suggestion(suggested: frozenset[int] | None) -> frozenset[int]:
    if suggested is None:
        raise ValueError("PASS or REFUTE before any SUGGEST")
    return suggested


def _set(knowledge: Knowledge, holder: int, card_id: int, mark: Mark) -> bool:
    """Record a mark and return whether it changed anything."""
    current = knowledge.marks[holder][card_id]
    if current is mark:
        return False
    if current is not Mark.UNKNOWN:
        raise InconsistentKnowledgeError(
            f"holder {holder}, card {card_id}: {current.name} conflicts with {mark.name}"
        )
    knowledge.marks[holder][card_id] = mark
    return True


def _propagate(knowledge: Knowledge) -> None:
    changed = True
    while changed:
        changed = False
        for card_id in CARDS_BY_ID:
            changed |= _settle_card(knowledge, card_id)
        for cards in CARDS.values():
            changed |= _settle_envelope_category(knowledge, [card.id for card in cards])
        for clause in knowledge.clauses:
            changed |= _settle_clause(knowledge, clause)


def _settle_card(knowledge: Knowledge, card_id: int) -> bool:
    """Every card has exactly one holder: a player or the envelope."""
    rows = range(knowledge.num_players + 1)
    held = [row for row in rows if knowledge.marks[row][card_id] is Mark.HELD]
    if len(held) > 1:
        raise InconsistentKnowledgeError(f"card {card_id} held by {held}")
    if held:
        changed = False
        for row in rows:
            if row != held[0]:
                changed |= _set(knowledge, row, card_id, Mark.NOT_HELD)
        return changed
    unknown = [row for row in rows if knowledge.marks[row][card_id] is Mark.UNKNOWN]
    if not unknown:
        raise InconsistentKnowledgeError(f"card {card_id} has no possible holder")
    if len(unknown) == 1:
        return _set(knowledge, unknown[0], card_id, Mark.HELD)
    return False


def _settle_envelope_category(knowledge: Knowledge, card_ids: list[int]) -> bool:
    """The envelope holds exactly one card of each category."""
    row = knowledge.marks[knowledge.envelope]
    held = [card_id for card_id in card_ids if row[card_id] is Mark.HELD]
    if len(held) > 1:
        raise InconsistentKnowledgeError(f"envelope holds several of {card_ids}")
    if held:
        changed = False
        for card_id in card_ids:
            if card_id != held[0]:
                changed |= _set(knowledge, knowledge.envelope, card_id, Mark.NOT_HELD)
        return changed
    unknown = [card_id for card_id in card_ids if row[card_id] is Mark.UNKNOWN]
    if not unknown:
        raise InconsistentKnowledgeError(f"envelope holds none of {card_ids}")
    if len(unknown) == 1:
        return _set(knowledge, knowledge.envelope, unknown[0], Mark.HELD)
    return False


def _settle_clause(knowledge: Knowledge, clause: Clause) -> bool:
    row = knowledge.marks[clause.holder]
    if any(row[card_id] is Mark.HELD for card_id in clause.cards):
        return False
    unknown = [card_id for card_id in sorted(clause.cards) if row[card_id] is Mark.UNKNOWN]
    if not unknown:
        raise InconsistentKnowledgeError(
            f"holder {clause.holder} cannot hold any of {sorted(clause.cards)}"
        )
    if len(unknown) == 1:
        return _set(knowledge, clause.holder, unknown[0], Mark.HELD)
    return False
