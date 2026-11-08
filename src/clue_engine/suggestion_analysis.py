"""Bounded suggestion evaluation using only deals consistent with a player view."""

from collections import defaultdict
from itertools import product
from math import isfinite

from .models import Combination
from .observations import PlayerView


def expected_solution_certainty(
    view: PlayerView, suggestion: Combination,
    deals: tuple[tuple[Combination, tuple[int, ...]], ...],
    *, weights: tuple[float, ...] | None = None,
) -> float:
    """Expected posterior solution concentration under uniform matching-card reveals."""
    if weights is None:
        weights = (1.0,) * len(deals)
    if len(weights) != len(deals) or any(not isfinite(weight) or weight <= 0 for weight in weights):
        raise ValueError("each deal must have a positive weight")
    total_weight = sum(weights)
    if not isfinite(total_weight) or total_weight <= 0:
        raise ValueError("at least one weighted deal is required")
    cards = (suggestion.suspect_id, suggestion.weapon_id, suggestion.room_id)
    outcomes: dict[tuple[int, ...], dict[Combination, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    direction = -1 if view.reverse_refutation else 1
    for (solution, hands), deal_weight in zip(deals, weights, strict=True):
        responses = []
        for offset in range(1, len(hands)):
            seat = (view.player + direction * offset) % len(hands)
            matching = tuple(card for card in cards if hands[seat] & (1 << card))
            if view.all_refute:
                responses.append(matching or (-1,))
            elif matching:
                responses.append(tuple((seat, card) for card in matching))
                break
        if view.all_refute:
            choices = tuple(product(*responses))
        elif responses:
            choices = responses[0]
        else:
            choices = ((-1, -1),)
        weight = deal_weight / len(choices)
        for outcome in choices:
            outcomes[outcome][solution] += weight
    return sum(
        sum(weight * weight for weight in solutions.values()) / sum(solutions.values())
        for solutions in outcomes.values()
    ) / total_weight
