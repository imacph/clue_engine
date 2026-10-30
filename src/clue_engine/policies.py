import random
from typing import Protocol

from .knowledge import Knowledge, Mark, knowledge_for, known_solution
from .models import Accuse, Action, Combination, Suggest
from .observations import PlayerView


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
