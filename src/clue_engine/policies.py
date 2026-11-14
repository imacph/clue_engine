import heapq
import random
from collections import deque
from collections.abc import Sequence
from typing import Protocol

from .board import Square
from .board_state import RoomPosition
from .board_turn import Move, Roll, UsePassage, suspect_location
from .deal_analysis import (
    consistent_deals,
    deduce_deal_constraints,
    solution_deal_counts,
)
from .game_settings import BotStrategy, LearnedStrategy
from .knowledge import (
    InconsistentKnowledgeError,
    Knowledge,
    Mark,
    knowledge_for,
    known_solution,
)
from .models import Accuse, Action, Combination, Reveal, Suggest
from .observations import EventKind, PlayerView, last_suggest_index
from .suggestion_analysis import expected_solution_certainty


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
            room_id = suggestions[0].combination.room_id
            recent = self._recent_rooms(view)
            if not (
                view.board_rules.stay_to_suggest and Roll() in options
                and recent and recent[-1] == room_id
            ):
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
        ) | (frozenset() if view.board_rules.revisit_hallways else turn.visited)
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
        public = {
            event.card_id for event in view.events
            if event.actor == view.player
            and (event.kind is EventKind.EXPOSE or (event.kind is EventKind.SHOW and event.public))
        }
        known_publicly = tuple(action for action in reveals if action.card_id in public)
        if known_publicly:
            return self.rng.choice(known_publicly)
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
    """Rank suggestions using reachable responders and unresolved clauses."""

    def __init__(self, rng: random.Random):
        super().__init__(rng)
        self._deal_counts: dict[Combination, int] | None = None

    def _route_planning_enabled(self) -> bool:
        return True

    def _count_deals(self, knowledge: Knowledge) -> dict[Combination, int] | None:
        return solution_deal_counts(knowledge)

    def _suggestion_evidence(
        self, view: PlayerView, knowledge: Knowledge,
        deals: tuple[tuple[Combination, tuple[int, ...]], ...] | None,
    ) -> tuple[dict[int, int], tuple[float, ...] | None]:
        return {}, None

    @staticmethod
    def _room_distances(
        view: PlayerView, start: Square, blocked: frozenset[Square], forbidden_room: int | None,
    ) -> dict[int, int]:
        assert view.board is not None
        layout = view.board.board.layout
        doors: dict[Square, list[int]] = {}
        for door in layout.doors:
            if door.room_id != forbidden_room:
                doors.setdefault(door.hallway_square, []).append(door.room_id)
        distances: dict[int, int] = {}
        queue = deque([(start, 0)])
        visited = {start}
        while queue:
            square, distance = queue.popleft()
            for room in doors.get(square, ()):
                distances.setdefault(room, distance + 1)
            for neighbor in layout.hallway_neighbors(square):
                if neighbor not in blocked and neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, distance + 1))
        return distances

    def _route_cost(
        self, knowledge: Knowledge, room: int, recent: tuple[int, ...], distance: int, budget: int,
    ) -> tuple[int, int]:
        penalty = 0 if known_solution(knowledge) is not None else self._room_penalty(
            knowledge, room, recent
        )
        return penalty + 4 * ((max(0, distance - budget) + 6) // 7), distance

    def _board_move(
        self, view: PlayerView, knowledge: Knowledge, moves: tuple[Move, ...],
    ) -> Move:
        if not self._route_planning_enabled():
            return super()._board_move(view, knowledge, moves)
        assert view.board is not None
        turn = view.board
        board = turn.board
        recent = self._recent_rooms(view)
        blocked = board.occupied_hallways(
            excluding_suspect_id=board.seat_suspects[view.player]
        ) | (frozenset() if view.board_rules.revisit_hallways else turn.visited)
        scored = []
        for move in moves:
            if isinstance(move.destination, RoomPosition):
                distances = {move.destination.room_id: 0}
            else:
                distances = self._room_distances(view, move.destination, blocked, turn.starting_room)
            if distances:
                score = min(
                    self._route_cost(knowledge, room, recent, distance, turn.remaining - 1)
                    for room, distance in distances.items()
                )
                scored.append((score, move))
        if not scored:
            return super()._board_move(view, knowledge, moves)
        best = min(score for score, _ in scored)
        return self.rng.choice(tuple(move for score, move in scored if score == best))

    def _pick_board(
        self, view: PlayerView, knowledge: Knowledge, options: tuple[Action, ...],
    ) -> Action:
        selected = super()._pick_board(view, knowledge, options)
        if (
            not self._route_planning_enabled()
            or not isinstance(selected, (Roll, UsePassage))
            or Roll() not in options or UsePassage() not in options
        ):
            return selected
        assert view.board is not None
        board = view.board.board
        location = suspect_location(board, board.seat_suspects[view.player])
        assert isinstance(location, RoomPosition)
        destination = board.layout.passage_from(location.room_id)
        assert destination is not None
        occupied = board.occupied_hallways(excluding_suspect_id=board.seat_suspects[view.player])
        distances: dict[int, int] = {}
        for door in board.layout.doors_for(location.room_id):
            if door.hallway_square in occupied:
                continue
            for room, distance in self._room_distances(
                view, door.hallway_square, occupied, location.room_id,
            ).items():
                distances[room] = min(distances.get(room, 1_000_000), distance + 1)
        if not distances:
            return UsePassage()
        recent = self._recent_rooms(view)
        roll_cost = sum(
            min(
                self._route_cost(knowledge, room, recent, distance, first + second)[0]
                for room, distance in distances.items()
            )
            for first in range(1, 7) for second in range(1, 7)
        )
        passage_cost = self._route_cost(knowledge, destination, recent, 0, 0)[0]
        return UsePassage() if 36 * passage_cost <= roll_cost else Roll()

    def _analyze(
        self, knowledge: Knowledge, legal: tuple[Action, ...], *, enabled: bool, risk: bool,
    ) -> Accuse | None:
        self._deal_counts = None
        if not enabled or not any(
            isinstance(action, Accuse) for action in legal
        ):
            return None
        if known_solution(knowledge) is None:
            deduce_deal_constraints(knowledge)
        if known_solution(knowledge) is not None:
            return None
        counts = self._count_deals(knowledge)
        if counts is None:
            return None
        if not counts:
            raise InconsistentKnowledgeError("no deal satisfies the player's knowledge")
        self._deal_counts = counts
        best, count = max(counts.items(), key=lambda item: item[1])
        if len(counts) == 1 or (risk and count * 4 >= 3 * sum(counts.values())):
            accusation = Accuse(best)
            if accusation in legal:
                return accusation
        return None

    def choose(self, view: PlayerView, num_players: int, legal: tuple[Action, ...]) -> Action:
        knowledge = knowledge_for(view, num_players)
        accusation = self._analyze(knowledge, legal, enabled=True, risk=False)
        if accusation is not None:
            return accusation
        return self._choose_with_knowledge(view, knowledge, legal)

    def _choose_with_knowledge(
        self, view: PlayerView, knowledge: Knowledge, legal: tuple[Action, ...],
    ) -> Action:
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

    def _pick_suggestion(
        self, view: PlayerView, knowledge: Knowledge, options: tuple[Action, ...],
        suggestions: tuple[Suggest, ...],
    ) -> Action:
        candidates = tuple(
            item for item in suggestions
            if all(
                knowledge.mark_of(knowledge.envelope, card) is not Mark.NOT_HELD
                for card in _cards(item.combination)
            )
        )
        return self._rank_suggestions(view, knowledge, candidates or suggestions, prefer_probe=False)

    def _board_suggestion(
        self, view: PlayerView, knowledge: Knowledge, suggestions: tuple[Suggest, ...],
    ) -> Action:
        candidates = self._board_candidates(knowledge, suggestions)
        return self._rank_suggestions(view, knowledge, candidates, prefer_probe=False)

    def _rank_suggestions(
        self, view: PlayerView, knowledge: Knowledge, suggestions: tuple[Suggest, ...],
        *, prefer_probe: bool,
    ) -> Action:
        ranked = self._suggestion_components(
            view, knowledge, suggestions, prefer_probe=prefer_probe,
        )
        best = max(ranked.values())
        return self.rng.choice(tuple(
            suggestion for suggestion, score in ranked.items() if score == best
        ))

    def _suggestion_components(
        self, view: PlayerView, knowledge: Knowledge, suggestions: tuple[Suggest, ...],
        *, prefer_probe: bool,
    ) -> dict[Suggest, tuple[int | float, ...]]:
        deals = consistent_deals(knowledge, self._deal_counts) if self._deal_counts else None
        hints, weights = self._suggestion_evidence(view, knowledge, deals)
        unresolved: dict[int, set[frozenset[int]]] = {}
        for clause in knowledge.clauses:
            if any(knowledge.mark_of(clause.holder, card) is Mark.HELD for card in clause.cards):
                continue
            unknown = frozenset(
                card for card in clause.cards if knowledge.mark_of(clause.holder, card) is Mark.UNKNOWN
            )
            if len(unknown) > 1:
                unresolved.setdefault(clause.holder, set()).add(unknown)

        def score(suggestion: Suggest) -> tuple[int | float, ...]:
            cards = _cards(suggestion.combination)
            opportunities = 0
            unknown_marks = 0
            clause_targets = 0
            for offset in range(1, knowledge.num_players):
                direction = -1 if view.reverse_refutation else 1
                seat = (view.player + direction * offset) % knowledge.num_players
                marks = tuple(knowledge.mark_of(seat, card) for card in cards)
                if Mark.HELD in marks and not view.all_refute:
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
            diversity = 0
            if self._deal_counts:
                total = sum(self._deal_counts.values())
                for card in cards:
                    hits = sum(
                        count for combo, count in self._deal_counts.items() if card in _cards(combo)
                    )
                    diversity += hits * (total - hits)
            certainty = (
                expected_solution_certainty(view, suggestion.combination, deals, weights=weights)
                if deals else 0
            )
            relocation = 0
            if view.board is not None and view.board_rules.move_suspect:
                board = view.board.board
                suspect = suggestion.combination.suspect_id
                location = suspect_location(board, suspect)
                relocation = int(
                    suspect == board.seat_suspects[view.player]
                    or suspect not in board.seat_suspects
                    or location == RoomPosition(suggestion.combination.room_id)
                )
            return (
                int(prefer_probe and _is_probe(view, knowledge, suggestion)), certainty,
                int(opportunities > 0), diversity, clause_targets, envelope_unknown, opportunities,
                unknown_marks, sum(hints.get(card, 0) for card in cards),
                relocation,
            )

        return {suggestion: score(suggestion) for suggestion in suggestions}


class AnalyticalPolicy(StrategicPolicy):
    """Use bounded deal counting, opponent modeling, and calculated accusations."""

    def _count_deals(self, knowledge: Knowledge) -> dict[Combination, int] | None:
        return solution_deal_counts(knowledge, max_candidates=24, max_nodes=60000)

    def choose(self, view: PlayerView, num_players: int, legal: tuple[Action, ...]) -> Action:
        knowledge = knowledge_for(view, num_players)
        accusation = self._analyze(knowledge, legal, enabled=True, risk=False)
        if accusation is not None:
            return accusation
        if self._deal_counts:
            deals = consistent_deals(knowledge, self._deal_counts)
            if deals:
                _, weights = self._suggestion_evidence(view, knowledge, deals)
                assert weights is not None
                support: dict[Combination, float] = {}
                for (solution, _), weight in zip(deals, weights, strict=True):
                    support[solution] = support.get(solution, 0) + weight
            else:
                support = {solution: float(count) for solution, count in self._deal_counts.items()}
            best = max(support.values())
            if 2 * best >= sum(support.values()):
                candidates = tuple(
                    Accuse(solution) for solution, weight in support.items()
                    if weight == best and Accuse(solution) in legal
                )
                if candidates:
                    return self.rng.choice(candidates)
        return self._choose_with_knowledge(view, knowledge, legal)

    def _suggestion_evidence(
        self, view: PlayerView, knowledge: Knowledge,
        deals: tuple[tuple[Combination, tuple[int, ...]], ...] | None,
    ) -> tuple[dict[int, int], tuple[float, ...] | None]:
        suggested: set[tuple[int, int]] = set()
        for event in view.events:
            if event.kind is not EventKind.SUGGEST or event.actor == view.player or event.combo is None:
                continue
            cards = _cards(event.combo)
            for card in cards[:2] if view.board is not None else cards:
                suggested.add((event.actor, card))
        hints: dict[int, int] = {}
        for seat, card in suggested:
            if (
                knowledge.mark_of(seat, card) is not Mark.HELD
                and knowledge.mark_of(knowledge.envelope, card) is Mark.UNKNOWN
            ):
                hints[card] = hints.get(card, 0) + 1
        if not deals:
            return hints, None
        uncertain = tuple(
            (seat, card) for seat, card in suggested
            if knowledge.mark_of(seat, card) is Mark.UNKNOWN
        )
        weights = tuple(
            max(0.25, 0.75 ** sum(bool(hands[seat] & (1 << card)) for seat, card in uncertain))
            for _, hands in deals
        )
        return hints, weights


class CustomPolicy(StrategicPolicy):
    """Combine independent strategy choices while using only the player's view."""

    def __init__(self, rng: random.Random, strategy: BotStrategy):
        super().__init__(rng)
        if not isinstance(strategy, BotStrategy):
            raise TypeError("strategy must be BotStrategy")
        self.strategy = strategy

    def _route_planning_enabled(self) -> bool:
        return self.strategy.candidate_rooms

    def choose(self, view: PlayerView, num_players: int, legal: tuple[Action, ...]) -> Action:
        knowledge = knowledge_for(view, num_players)
        accusation = self._analyze(
            knowledge, legal,
            enabled=self.strategy.deal_analysis or self.strategy.risk_accusation,
            risk=self.strategy.risk_accusation,
        )
        if accusation is not None:
            return accusation
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
    "analytical": AnalyticalPolicy,
}
POLICY_NAMES = tuple(POLICY_TYPES)


def validate_policy_names(names: Sequence[str], *, additional: Sequence[str] = ()) -> None:
    for name in names:
        if name not in POLICY_TYPES and name not in additional:
            raise ValueError(
                f"unknown policy {name!r}; choose from {', '.join((*POLICY_NAMES, *additional))}"
            )


def policies_for_players(
    value: str, players: int, *, additional: Sequence[str] = (),
) -> tuple[str, ...]:
    names = tuple(name.strip().lower() for name in value.split(","))
    if len(names) == 1:
        names = names * players
    if len(names) != players:
        raise ValueError("supply one policy or one policy per player")
    validate_policy_names(names, additional=additional)
    return names


def make_policy(name: str | BotStrategy | LearnedStrategy, rng: random.Random) -> Policy:
    if isinstance(name, BotStrategy):
        return CustomPolicy(rng, name)
    if name == "learned" or isinstance(name, LearnedStrategy):
        from .learning import load_default_models
        from .learning_policy import LearningPolicy
        from .opponent_model import load_packaged_model
        from .threat_model import load_packaged_model as load_threat_model

        models = load_default_models()
        return LearningPolicy(
            rng, models[4],
            strategy=name if isinstance(name, LearnedStrategy) else LearnedStrategy(),
            models_by_player_count=models,
            opponent_model=(
                load_packaged_model() if isinstance(name, LearnedStrategy) and name.opponent_model
                else None
            ),
            threat_model=(
                load_threat_model() if isinstance(name, LearnedStrategy) and name.threat_sensitivity > 0
                else None
            ),
        )
    validate_policy_names((name,))
    return POLICY_TYPES[name](rng)
