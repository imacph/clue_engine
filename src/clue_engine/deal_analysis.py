"""Bounded exact analysis of deals consistent with a player's knowledge."""

from itertools import combinations, product
from math import comb

from .cards import CARDS
from .knowledge import InconsistentKnowledgeError, Knowledge, Mark, _propagate, _set
from .models import CardType, Combination


def _envelope_choices(knowledge: Knowledge) -> list[list[int]]:
    row = knowledge.marks[knowledge.envelope]
    choices = []
    for category in (CardType.SUSPECT, CardType.WEAPON, CardType.ROOM):
        held = [card.id for card in CARDS[category] if row[card.id] is Mark.HELD]
        choices.append(held or [
            card.id for card in CARDS[category] if row[card.id] is not Mark.NOT_HELD
        ])
    return choices


def _possible_hands(knowledge: Knowledge, max_combinations: int) -> list[list[int]] | None:
    assert knowledge.hand_sizes is not None
    result: list[list[int]] = []
    for holder, size in enumerate(knowledge.hand_sizes):
        row = knowledge.marks[holder]
        held = sum(1 << card for card, mark in enumerate(row) if mark is Mark.HELD)
        unknown = [card for card, mark in enumerate(row) if mark is Mark.UNKNOWN]
        needed = size - held.bit_count()
        if needed < 0 or needed > len(unknown):
            raise InconsistentKnowledgeError(f"holder {holder} cannot have {size} cards")
        if comb(len(unknown), needed) > max_combinations:
            return None
        clauses = [
            sum(1 << card for card in clause.cards)
            for clause in knowledge.clauses if clause.holder == holder
        ]
        hands = []
        for selected in combinations(unknown, needed):
            mask = held | sum(1 << card for card in selected)
            if all(mask & clause for clause in clauses):
                hands.append(mask)
        result.append(hands)
    return result


def _settle_hand_clauses(knowledge: Knowledge, holder: int, size: int) -> bool:
    row = knowledge.marks[holder]
    clauses = [
        sum(1 << card for card in clause.cards if row[card] is Mark.UNKNOWN)
        for clause in knowledge.clauses if clause.holder == holder
        and not any(row[card] is Mark.HELD for card in clause.cards)
    ]
    if len(clauses) < 2:
        return False
    unknown = [card for card, mark in enumerate(row) if mark is Mark.UNKNOWN]
    remaining = size - sum(mark is Mark.HELD for mark in row)
    if remaining < 0 or remaining > len(unknown):
        raise InconsistentKnowledgeError(f"holder {holder} cannot have {size} cards")
    if comb(len(unknown), remaining) > 10000:
        return False
    all_unknown = sum(1 << card for card in unknown)
    intersection, union = all_unknown, 0
    found = False
    for selected in combinations(unknown, remaining):
        mask = sum(1 << card for card in selected)
        if all(mask & clause for clause in clauses):
            found = True
            intersection &= mask
            union |= mask
            if not intersection and union == all_unknown:
                break
    if not found:
        raise InconsistentKnowledgeError(f"holder {holder} has no hand satisfying the clauses")
    changed = False
    for card in unknown:
        if intersection & (1 << card):
            changed |= _set(knowledge, holder, card, Mark.HELD)
        elif not union & (1 << card):
            changed |= _set(knowledge, holder, card, Mark.NOT_HELD)
    return changed


def feasible_solutions(
    knowledge: Knowledge, *, max_candidates: int = 48, max_nodes: int = 15000,
) -> tuple[Combination, ...] | None:
    """Find every feasible solution, or return None if the search is incomplete."""
    if knowledge.hand_sizes is None:
        return None
    choices = _envelope_choices(knowledge)
    if not all(choices) or len(choices[0]) * len(choices[1]) * len(choices[2]) > max_candidates:
        return None
    possible_hands = _possible_hands(knowledge, 10000)
    if possible_hands is None:
        return None
    budget = max_nodes
    results = []
    for cards in product(*choices):
        if frozenset(cards) in knowledge.wrong_accusations:
            continue
        envelope = sum(1 << card for card in cards)
        groups = sorted(
            ([hand for hand in hands if not hand & envelope] for hands in possible_hands),
            key=len,
        )

        def find(index: int, used: int, hands: list[list[int]]) -> bool:
            nonlocal budget
            if index == len(hands):
                return True
            for hand in hands[index]:
                budget -= 1
                if budget < 0:
                    raise _SearchLimit
                if not hand & used and find(index + 1, used | hand, hands):
                    return True
            return False

        try:
            if find(0, envelope, groups):
                results.append(Combination(*cards))
        except _SearchLimit:
            return None
    return tuple(results)


def deduce_deal_constraints(knowledge: Knowledge) -> None:
    """Apply only deductions proven by complete hand or deal searches."""
    if knowledge.hand_sizes is None:
        return
    while True:
        changed = False
        for holder, size in enumerate(knowledge.hand_sizes):
            changed |= _settle_hand_clauses(knowledge, holder, size)
        if changed:
            _propagate(knowledge)
            continue
        solutions = feasible_solutions(knowledge)
        if solutions is None:
            return
        if not solutions:
            raise InconsistentKnowledgeError("no deal satisfies the player's knowledge")
        possible = {
            CardType.SUSPECT: {item.suspect_id for item in solutions},
            CardType.WEAPON: {item.weapon_id for item in solutions},
            CardType.ROOM: {item.room_id for item in solutions},
        }
        for category, cards in CARDS.items():
            for card in cards:
                if (
                    card.id not in possible[category]
                    and knowledge.mark_of(knowledge.envelope, card.id) is Mark.UNKNOWN
                ):
                    changed |= _set(knowledge, knowledge.envelope, card.id, Mark.NOT_HELD)
        if not changed:
            return
        _propagate(knowledge)


def solution_deal_counts(
    knowledge: Knowledge, *, max_candidates: int = 12, max_nodes: int = 30000,
) -> dict[Combination, int] | None:
    """Count consistent deals per solution, or return None if the budget is exceeded.

    Counts are exact only for completed searches. A partial search must not be used
    for either deductions or probability estimates.
    """
    if knowledge.hand_sizes is None:
        return None
    choices = _envelope_choices(knowledge)
    if not all(choices) or len(choices[0]) * len(choices[1]) * len(choices[2]) > max_candidates:
        return None

    possible_hands = _possible_hands(knowledge, 10000)
    if possible_hands is None:
        return None

    budget = max_nodes
    results: dict[Combination, int] = {}
    for cards in product(*choices):
        if any(set(cards) == wrong for wrong in knowledge.wrong_accusations):
            continue
        envelope_mask = sum(1 << card for card in cards)
        hands_by_player = [
            [hand for hand in hands if not hand & envelope_mask] for hands in possible_hands
        ]
        hands_by_player.sort(key=len)

        def count_assignments(index: int, used: int, hands: list[list[int]]) -> int:
            nonlocal budget
            budget -= 1
            if budget < 0:
                raise _SearchLimit
            if index == len(hands):
                return 1
            return sum(
                count_assignments(index + 1, used | hand, hands)
                for hand in hands[index] if not hand & used
            )

        try:
            count = count_assignments(0, envelope_mask, hands_by_player)
        except _SearchLimit:
            return None
        if count:
            results[Combination(*cards)] = count
    return results


def consistent_deals(
    knowledge: Knowledge, counts: dict[Combination, int], *, max_deals: int = 128,
    max_nodes: int = 30000,
) -> tuple[tuple[Combination, tuple[int, ...]], ...] | None:
    """Enumerate a small, completely counted deal space, preserving player identities."""
    if knowledge.hand_sizes is None or sum(counts.values()) > max_deals:
        return None
    possible_hands = _possible_hands(knowledge, 10000)
    if possible_hands is None:
        return None
    budget = max_nodes
    results: list[tuple[Combination, tuple[int, ...]]] = []

    def visit(
        index: int, used: int, solution: Combination,
        groups: list[tuple[int, list[int]]], selected: list[int],
    ) -> None:
        nonlocal budget
        budget -= 1
        if budget < 0:
            raise _SearchLimit
        if index == len(groups):
            results.append((solution, tuple(selected)))
            return
        seat, hands = groups[index]
        for hand in hands:
            if not hand & used:
                selected[seat] = hand
                visit(index + 1, used | hand, solution, groups, selected)

    for solution, expected in counts.items():
        envelope = sum(1 << card for card in (
            solution.suspect_id, solution.weapon_id, solution.room_id,
        ))
        groups = sorted(
            (
                (seat, [hand for hand in hands if not hand & envelope])
                for seat, hands in enumerate(possible_hands)
            ),
            key=lambda item: len(item[1]),
        )
        selected = [0] * knowledge.num_players
        before = len(results)

        try:
            visit(0, envelope, solution, groups, selected)
        except _SearchLimit:
            return None
        if len(results) - before != expected:
            raise InconsistentKnowledgeError("deal enumeration disagrees with completed counts")
    return tuple(results)


class _SearchLimit(Exception):
    pass
