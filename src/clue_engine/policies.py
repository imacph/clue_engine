import heapq
import random
from collections.abc import Sequence
from typing import Protocol

from .board import Square
from .board_state import RoomPosition
from .board_turn import Move, Roll, UsePassage, suspect_location
from .game_settings import BotStrategy
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
        if view.board is not None:
            return self._pick_board(view, knowledge, options)
        return self._pick(knowledge, options)

    def _pick(self, knowledge: Knowledge, options: tuple[Action, ...]) -> Action:
        return self.rng.choice(options)

    def _pick_board(
        self, view: PlayerView, knowledge: Knowledge, options: tuple[Action, ...],
    ) -> Action:
        if len(options) == 1:
            return options[0]
        reveals = tuple(action for action in options if isinstance(action, Reveal))
        if reveals:
            return self._board_reveal(view, reveals)
        suggestions = tuple(action for action in options if isinstance(action, Suggest))
        if suggestions:
            return self._board_suggestion(view, knowledge, suggestions)
        moves = tuple(action for action in options if isinstance(action, Move))
        if moves:
            return self._board_move(view, knowledge, moves)
        if UsePassage() in options:
            assert view.board is not None
            board = view.board.board
            location = suspect_location(board, board.seat_suspects[view.player])
            assert isinstance(location, RoomPosition)
            destination = board.layout.passage_from(location.room_id)
            occupied = board.occupied_hallways(
                excluding_suspect_id=board.seat_suspects[view.player]
            )
            exits_blocked = all(
                door.hallway_square in occupied for door in board.layout.doors_for(location.room_id)
            )
            if exits_blocked or destination not in self._recent_rooms(view):
                return UsePassage()
        if Roll() in options:
            return Roll()
        return self.rng.choice(options)

    def _board_reveal(self, view: PlayerView, reveals: tuple[Reveal, ...]) -> Reveal:
        return self.rng.choice(reveals)

    def _board_suggestion(
        self, view: PlayerView, knowledge: Knowledge, suggestions: tuple[Suggest, ...],
    ) -> Action:
        return self.rng.choice(suggestions)

    @staticmethod
    def _recent_rooms(view: PlayerView) -> tuple[int, ...]:
        return tuple(
            event.combo.room_id for event in view.events
            if event.kind is EventKind.SUGGEST and event.actor == view.player
            and event.combo is not None
        )[-2:]

    def _room_penalty(self, knowledge: Knowledge, room_id: int, recent: tuple[int, ...]) -> int:
        return 8 if room_id in recent else 0

    def _board_move(
        self, view: PlayerView, knowledge: Knowledge, moves: tuple[Move, ...],
    ) -> Move:
        assert view.board is not None
        turn = view.board
        board = turn.board
        recent = self._recent_rooms(view)
        fresh_rooms = tuple(
            move for move in moves
            if isinstance(move.destination, RoomPosition) and move.destination.room_id not in recent
        )
        if fresh_rooms:
            return self.rng.choice(fresh_rooms)

        blocked = board.occupied_hallways(
            excluding_suspect_id=board.seat_suspects[view.player]
        ) | turn.visited
        distances: dict[Square, int] = {}
        queue: list[tuple[int, Square]] = []
        for door in board.layout.doors:
            if door.room_id == turn.starting_room or door.hallway_square in blocked:
                continue
            cost = 1 + self._room_penalty(knowledge, door.room_id, recent)
            if cost < distances.get(door.hallway_square, 1_000_000):
                distances[door.hallway_square] = cost
                heapq.heappush(queue, (cost, door.hallway_square))
        while queue:
            cost, square = heapq.heappop(queue)
            if cost != distances[square]:
                continue
            for neighbor in board.layout.hallway_neighbors(square):
                if neighbor in blocked or cost + 1 >= distances.get(neighbor, 1_000_000):
                    continue
                distances[neighbor] = cost + 1
                heapq.heappush(queue, (cost + 1, neighbor))

        scored = [
            (
                self._room_penalty(knowledge, move.destination.room_id, recent)
                if isinstance(move.destination, RoomPosition)
                else distances.get(move.destination, 1_000_000),
                move,
            )
            for move in moves
        ]
        best = min(score for score, _ in scored)
        return self.rng.choice(tuple(move for score, move in scored if score == best))


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

    @staticmethod
    def _board_candidates(
        knowledge: Knowledge, suggestions: tuple[Suggest, ...],
    ) -> tuple[Suggest, ...]:
        candidates = tuple(
            action for action in suggestions
            if all(
                knowledge.mark_of(knowledge.envelope, card_id) is not Mark.NOT_HELD
                for card_id in (action.combination.suspect_id, action.combination.weapon_id)
            )
        )
        return candidates or suggestions

    def _board_suggestion(
        self, view: PlayerView, knowledge: Knowledge, suggestions: tuple[Suggest, ...],
    ) -> Action:
        return self.rng.choice(self._board_candidates(knowledge, suggestions))

    def _room_penalty(self, knowledge: Knowledge, room_id: int, recent: tuple[int, ...]) -> int:
        return super()._room_penalty(knowledge, room_id, recent) + (
            2 if knowledge.mark_of(knowledge.envelope, room_id) is Mark.NOT_HELD else 0
        )


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
        if view.board is not None:
            return self._pick_board(view, knowledge, options)
        reveals = tuple(action for action in options if isinstance(action, Reveal))
        if reveals:
            return self._pick_reveal(view, reveals)
        suggestions = tuple(action for action in options if isinstance(action, Suggest))
        if suggestions:
            return self._pick_suggestion(view, knowledge, options, suggestions)
        return self.rng.choice(options)

    def _board_reveal(self, view: PlayerView, reveals: tuple[Reveal, ...]) -> Reveal:
        return self._pick_reveal(view, reveals)

    def _board_suggestion(
        self, view: PlayerView, knowledge: Knowledge, suggestions: tuple[Suggest, ...],
    ) -> Action:
        probes = tuple(action for action in suggestions if _is_probe(view, knowledge, action))
        candidates = probes or self._board_candidates(knowledge, suggestions)
        return self._pick_suggestion(view, knowledge, candidates, candidates)

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
        return self._rank_suggestions(view, knowledge, suggestions, prefer_probe=True)

    def _rank_suggestions(
        self, view: PlayerView, knowledge: Knowledge, suggestions: tuple[Suggest, ...],
        *, prefer_probe: bool,
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
                int(prefer_probe and _is_probe(view, knowledge, suggestion)), int(opportunities > 0),
                clause_targets, envelope_unknown, opportunities, unknown_marks,
            )

        ranked = [(score(suggestion), suggestion) for suggestion in suggestions]
        best = max(item[0] for item in ranked)
        return self.rng.choice(tuple(suggestion for value, suggestion in ranked if value == best))


class CustomPolicy(StrategicPolicy):
    """Combine independent strategy choices while using only the player's view."""

    def __init__(self, rng: random.Random, strategy: BotStrategy):
        super().__init__(rng)
        if not isinstance(strategy, BotStrategy):
            raise TypeError("strategy must be BotStrategy")
        self.strategy = strategy

    def choose(self, view: PlayerView, num_players: int, legal: tuple[Action, ...]) -> Action:
        knowledge = knowledge_for(view, num_players)
        options = sound_actions(legal, known_solution(knowledge))
        if view.board is not None:
            return self._pick_board(view, knowledge, options)
        reveals = tuple(action for action in options if isinstance(action, Reveal))
        if reveals:
            return self._board_reveal(view, reveals)
        suggestions = tuple(action for action in options if isinstance(action, Suggest))
        if suggestions:
            if not self.strategy.prefer_suggest:
                selected = self.rng.choice(options)
                if not isinstance(selected, Suggest):
                    return selected
            return self._custom_suggestion(view, knowledge, suggestions)
        return self.rng.choice(options)

    def _board_reveal(self, view: PlayerView, reveals: tuple[Reveal, ...]) -> Reveal:
        if self.strategy.repeat_reveals:
            return self._pick_reveal(view, reveals)
        return self.rng.choice(reveals)

    def _board_suggestion(
        self, view: PlayerView, knowledge: Knowledge, suggestions: tuple[Suggest, ...],
    ) -> Action:
        return self._custom_suggestion(view, knowledge, suggestions)

    def _custom_suggestion(
        self, view: PlayerView, knowledge: Knowledge, suggestions: tuple[Suggest, ...],
    ) -> Action:
        candidates = suggestions
        if self.strategy.probe_suggestions:
            probes = tuple(item for item in candidates if _is_probe(view, knowledge, item))
            if probes:
                candidates = probes
        if candidates is suggestions and self.strategy.candidate_suggestions:
            if view.board is not None:
                candidates = self._board_candidates(knowledge, candidates)
            else:
                possible = tuple(
                    item for item in candidates
                    if all(
                        knowledge.mark_of(knowledge.envelope, card) is not Mark.NOT_HELD
                        for card in _cards(item.combination)
                    )
                )
                candidates = possible or candidates
        if self.strategy.rank_suggestions:
            return self._rank_suggestions(
                view, knowledge, candidates, prefer_probe=self.strategy.probe_suggestions,
            )
        return self.rng.choice(candidates)

    def _room_penalty(self, knowledge: Knowledge, room_id: int, recent: tuple[int, ...]) -> int:
        penalty = RandomPolicy._room_penalty(self, knowledge, room_id, recent)
        if self.strategy.candidate_rooms and knowledge.mark_of(knowledge.envelope, room_id) is Mark.NOT_HELD:
            penalty += 2
        return penalty


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
