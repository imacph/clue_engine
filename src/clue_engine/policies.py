import random
from collections.abc import Sequence
from typing import Protocol

from .knowledge import Knowledge, Mark, knowledge_for, known_solution
from .models import Accuse, Action, Combination, Reveal, Suggest
from .observations import EventKind, PlayerView, last_suggest_index


class Policy(Protocol):
    def choose(self, view: PlayerView, num_players: int, legal: tuple[Action, ...]) -> Action: ...


def sound_actions(legal: tuple[Action, ...], solution: Combination | None) -> tuple[Action, ...]:
    """Accusing is only sound once the solution is deduced, and then it is the only choice."""
    if solution is not None and Accuse(solution) in legal:
        return (Accuse(solution),)
    return tuple(action for action in legal if not isinstance(action, Accuse))


class RandomPolicy:
    """Chooses uniformly among legal actions, never accusing before the solution is deduced."""

    def __init__(self, rng: random.Random):
        self.rng = rng

    def choose(self, view: PlayerView, num_players: int, legal: tuple[Action, ...]) -> Action:
        knowledge = knowledge_for(view, num_players)
        options = sound_actions(legal, known_solution(knowledge))
        return self._pick(knowledge, options)

    def _pick(self, knowledge: Knowledge, options: tuple[Action, ...]) -> Action:
        return self.rng.choice(options)


class DeductivePolicy(RandomPolicy):
    """Prefer legal suggestions containing only cards that could be in the solution."""

    def _pick(self, knowledge: Knowledge, options: tuple[Action, ...]) -> Action:
        suggestions = tuple(
            action for action in options
            if isinstance(action, Suggest) and all(
                knowledge.mark_of(knowledge.envelope, card_id) is not Mark.NOT_HELD
                for card_id in (
                    action.combination.suspect_id,
                    action.combination.weapon_id,
                    action.combination.room_id,
                )
            )
        )
        if suggestions:
            return self.rng.choice(suggestions)
        return super()._pick(knowledge, options)


def _cards(combination: Combination) -> tuple[int, int, int]:
    return combination.suspect_id, combination.weapon_id, combination.room_id


def _is_probe(view: PlayerView, knowledge: Knowledge, suggestion: Suggest) -> bool:
    cards = _cards(suggestion.combination)
    controls = [
        card in view.own_hand or knowledge.mark_of(knowledge.envelope, card) is Mark.HELD
        for card in cards
    ]
    return sum(controls) == 2 and any(
        not control and knowledge.mark_of(knowledge.envelope, card) is Mark.UNKNOWN
        for card, control in zip(cards, controls, strict=True)
    )


class ProbingPolicy(DeductivePolicy):
    """Isolate an unknown solution candidate and repeat previously shown cards."""

    def choose(self, view: PlayerView, num_players: int, legal: tuple[Action, ...]) -> Action:
        knowledge = knowledge_for(view, num_players)
        options = sound_actions(legal, known_solution(knowledge))
        reveals = tuple(action for action in options if isinstance(action, Reveal))
        if reveals:
            return self._pick_reveal(view, reveals)
        suggestions = tuple(action for action in options if isinstance(action, Suggest))
        if suggestions:
            return self._pick_suggestion(view, knowledge, options, suggestions)
        return self.rng.choice(options)

    def _pick_reveal(self, view: PlayerView, reveals: tuple[Reveal, ...]) -> Reveal:
        index = last_suggest_index(view.events)
        if index is not None:
            recipient = view.events[index].actor
            shown = {
                event.card_id for event in view.events
                if event.kind is EventKind.SHOW and event.actor == view.player
                and event.private_to == recipient
            }
            repeated = tuple(action for action in reveals if action.card_id in shown)
            if repeated:
                return self.rng.choice(repeated)
        return self.rng.choice(reveals)

    def _pick_suggestion(
        self, view: PlayerView, knowledge: Knowledge, options: tuple[Action, ...],
        suggestions: tuple[Suggest, ...],
    ) -> Action:
        probes = tuple(suggestion for suggestion in suggestions if _is_probe(view, knowledge, suggestion))
        if probes:
            return self.rng.choice(probes)
        return super()._pick(knowledge, options)


class StrategicPolicy(ProbingPolicy):
    """Rank probes and suggestions using reachable responders and unresolved clauses."""

    def _pick_suggestion(
        self, view: PlayerView, knowledge: Knowledge, options: tuple[Action, ...],
        suggestions: tuple[Suggest, ...],
    ) -> Action:
        unresolved: dict[int, set[frozenset[int]]] = {}
        for clause in knowledge.clauses:
            if any(knowledge.mark_of(clause.holder, card) is Mark.HELD for card in clause.cards):
                continue
            unknown = frozenset(
                card for card in clause.cards if knowledge.mark_of(clause.holder, card) is Mark.UNKNOWN
            )
            if len(unknown) > 1:
                unresolved.setdefault(clause.holder, set()).add(unknown)

        def score(suggestion: Suggest) -> tuple[int, int, int, int, int, int]:
            cards = _cards(suggestion.combination)
            opportunities = 0
            unknown_marks = 0
            clause_targets = 0
            for offset in range(1, knowledge.num_players):
                seat = (view.player + offset) % knowledge.num_players
                marks = tuple(knowledge.mark_of(seat, card) for card in cards)
                if Mark.HELD in marks:
                    break
                unknown = tuple(card for card, mark in zip(cards, marks, strict=True) if mark is Mark.UNKNOWN)
                if unknown:
                    opportunities += 1
                    unknown_marks += len(unknown)
                    if len(unknown) == 1:
                        clause_targets += sum(
                            unknown[0] in clause for clause in unresolved.get(seat, ())
                        )
            envelope_unknown = sum(
                knowledge.mark_of(knowledge.envelope, card) is Mark.UNKNOWN for card in cards
            )
            return (
                int(_is_probe(view, knowledge, suggestion)), int(opportunities > 0),
                clause_targets, envelope_unknown, opportunities, unknown_marks,
            )

        ranked = [(score(suggestion), suggestion) for suggestion in suggestions]
        best = max(item[0] for item in ranked)
        return self.rng.choice(tuple(suggestion for value, suggestion in ranked if value == best))


POLICY_TYPES: dict[str, type[RandomPolicy]] = {
    "random": RandomPolicy,
    "deductive": DeductivePolicy,
    "probing": ProbingPolicy,
    "strategic": StrategicPolicy,
}
POLICY_NAMES = tuple(POLICY_TYPES)


def validate_policy_names(names: Sequence[str]) -> None:
    for name in names:
        if name not in POLICY_TYPES:
            raise ValueError(f"unknown policy {name!r}; choose from {', '.join(POLICY_NAMES)}")


def policies_for_players(value: str, players: int) -> tuple[str, ...]:
    names = tuple(name.strip().lower() for name in value.split(","))
    if len(names) == 1:
        names = names * players
    if len(names) != players:
        raise ValueError("supply one policy or one policy per player")
    validate_policy_names(names)
    return names


def make_policy(name: str, rng: random.Random) -> Policy:
    validate_policy_names((name,))
    return POLICY_TYPES[name](rng)
