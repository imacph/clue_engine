"""Player-view-only learned choices for board games."""

import math
import random
from dataclasses import dataclass
from typing import TypeVar

from .board_state import RoomPosition
from .board_turn import BoardPhase, Move, Roll, UsePassage, suspect_location
from .knowledge import Knowledge, Mark, known_solution
from .models import Action, Reveal, Suggest
from .observations import EventKind, PlayerView
from .policies import StrategicPolicy

FEATURE_COUNT = 8
T = TypeVar("T")


@dataclass(frozen=True)
class LinearModel:
    room_weights: tuple[float, ...]
    suggestion_weights: tuple[float, ...]

    def __post_init__(self) -> None:
        for weights in (self.room_weights, self.suggestion_weights):
            if len(weights) != FEATURE_COUNT or not all(math.isfinite(x) for x in weights):
                raise ValueError(f"model weights must contain {FEATURE_COUNT} finite values")

    @classmethod
    def zeros(cls) -> "LinearModel":
        return cls((0.0,) * FEATURE_COUNT, (0.0,) * FEATURE_COUNT)


def suggestion_features(
    view: PlayerView, knowledge: Knowledge, suggestion: Suggest,
) -> tuple[float, ...]:
    combo = suggestion.combination
    cards = (combo.suspect_id, combo.weapon_id, combo.room_id)
    envelope = tuple(knowledge.mark_of(knowledge.envelope, card) for card in cards)
    other_players = [
        (view.player + (-offset if view.reverse_refutation else offset)) % knowledge.num_players
        for offset in range(1, knowledge.num_players)
    ]
    uncertain = 0
    blockers = 0
    for seat in other_players:
        marks = tuple(knowledge.mark_of(seat, card) for card in cards)
        uncertain += marks.count(Mark.UNKNOWN)
        if Mark.HELD in marks:
            blockers += 1
            if not view.all_refute:
                break
    clauses = sum(
        bool(clause.cards.intersection(cards))
        and not any(knowledge.mark_of(clause.holder, card) is Mark.HELD for card in clause.cards)
        for clause in knowledge.clauses
    )
    repeats = sum(
        event.kind is EventKind.SUGGEST and event.actor == view.player and event.combo == combo
        for event in view.events
    )
    return (
        envelope.count(Mark.UNKNOWN) / 3,
        envelope.count(Mark.HELD) / 3,
        envelope.count(Mark.NOT_HELD) / 3,
        sum(card in view.own_hand for card in cards) / 3,
        uncertain / max(1, 3 * len(other_players)),
        min(clauses, 6) / 6,
        min(repeats, 3) / 3,
        blockers / max(1, len(other_players)),
    )


class LearningPolicy(StrategicPolicy):
    """Choose suggestions and room goals with a linear model; retain sound game rules."""

    def __init__(
        self, rng: random.Random, model: LinearModel, *, explore: bool = False,
    ) -> None:
        super().__init__(rng)
        self.model = model
        self.explore = explore
        self.decisions: list[tuple[str, tuple[float, ...]]] = []
        self._goal: int | None = None

    def _select(
        self, kind: str, candidates: tuple[tuple[T, tuple[float, ...]], ...],
    ) -> T:
        if not candidates:
            raise ValueError("learned decisions require at least one candidate")
        weights = self.model.room_weights if kind == "room" else self.model.suggestion_weights
        scores = [sum(a * b for a, b in zip(weights, features, strict=True))
                  for _, features in candidates]
        if not self.explore:
            best = max(scores)
            return self.rng.choice(tuple(item for (item, _), score in zip(candidates, scores, strict=True)
                                         if score == best))
        peak = max(scores)
        values = [math.exp(score - peak) for score in scores]
        total = sum(values)
        probabilities = [value / total for value in values]
        index = self.rng.choices(range(len(candidates)), weights=probabilities, k=1)[0]
        chosen = candidates[index][1]
        gradient = tuple(
            chosen[i] - sum(p * candidate[1][i]
                            for p, candidate in zip(probabilities, candidates, strict=True))
            for i in range(FEATURE_COUNT)
        )
        self.decisions.append((kind, gradient))
        return candidates[index][0]

    def choose(self, view: PlayerView, num_players: int, legal: tuple[Action, ...]) -> Action:
        if view.board is None:
            raise ValueError("learned policy supports board games only")
        return super().choose(view, num_players, legal)

    def _board_suggestion(
        self, view: PlayerView, knowledge: Knowledge, suggestions: tuple[Suggest, ...],
    ) -> Action:
        self._goal = None
        return self._select("suggestion", tuple(
            (action, suggestion_features(view, knowledge, action)) for action in suggestions
        ))

    def _routes(
        self, view: PlayerView, moves: tuple[Move, ...],
    ) -> dict[int, tuple[int, tuple[Move, ...]]]:
        assert view.board is not None
        turn = view.board
        board = turn.board
        blocked = board.occupied_hallways(
            excluding_suspect_id=board.seat_suspects[view.player]
        ) | (frozenset() if view.board_rules.revisit_hallways else turn.visited)
        routes: dict[int, tuple[int, tuple[Move, ...]]] = {}
        for move in moves:
            if isinstance(move.destination, RoomPosition):
                distances = {move.destination.room_id: 0}
            else:
                distances = self._room_distances(view, move.destination, blocked, turn.starting_room)
            for room, distance in distances.items():
                previous = routes.get(room)
                if previous is None or distance < previous[0]:
                    routes[room] = (distance, (move,))
                elif distance == previous[0]:
                    routes[room] = (distance, (*previous[1], move))
        return routes

    def _room_candidates(
        self, view: PlayerView, knowledge: Knowledge, options: tuple[Action, ...],
    ) -> tuple[tuple[int, tuple[float, ...]], ...]:
        assert view.board is not None
        turn = view.board
        board = turn.board
        location = suspect_location(board, board.seat_suspects[view.player])
        moves = tuple(action for action in options if isinstance(action, Move))
        if turn.phase is BoardPhase.START and Roll() in options:
            occupied = board.occupied_hallways(excluding_suspect_id=board.seat_suspects[view.player])
            if isinstance(location, RoomPosition):
                moves = tuple(Move(door.hallway_square) for door in board.layout.doors_for(
                    location.room_id
                ) if door.hallway_square not in occupied)
            else:
                moves = (Move(location),)
        routes = self._routes(view, moves)
        if turn.phase is BoardPhase.START and isinstance(location, RoomPosition):
            routes.pop(location.room_id, None)
            if any(isinstance(action, Suggest) for action in options):
                routes[location.room_id] = (0, ())
            if UsePassage() in options:
                destination = board.layout.passage_from(location.room_id)
                assert destination is not None
                routes[destination] = (0, ())
        recent = self._recent_rooms(view)
        candidates = []
        for room, (distance, _) in sorted(routes.items()):
            mark = knowledge.mark_of(knowledge.envelope, room)
            features = (
                float(mark is Mark.UNKNOWN),
                float(mark is Mark.HELD),
                float(mark is Mark.NOT_HELD),
                float(room in view.own_hand),
                min(distance, 30) / 30,
                float(room in recent),
                float(isinstance(location, RoomPosition) and location.room_id == room),
                float(isinstance(location, RoomPosition)
                      and UsePassage() in options and board.layout.passage_from(location.room_id) == room),
            )
            candidates.append((room, features))
        return tuple(candidates)

    def _board_move(
        self, view: PlayerView, knowledge: Knowledge, moves: tuple[Move, ...],
    ) -> Move:
        routes = self._routes(view, moves)
        if self._goal not in routes:
            candidates = self._room_candidates(view, knowledge, moves)
            self._goal = self._select("room", candidates) if candidates else None
        if self._goal is not None and self._goal in routes:
            return self.rng.choice(routes[self._goal][1])
        return super()._board_move(view, knowledge, moves)

    def _pick_board(
        self, view: PlayerView, knowledge: Knowledge, options: tuple[Action, ...],
    ) -> Action:
        assert view.board is not None
        if any(isinstance(action, Reveal) for action in options) or known_solution(knowledge):
            return super()._pick_board(view, knowledge, options)
        if view.board.phase is BoardPhase.START:
            candidates = self._room_candidates(view, knowledge, options)
            if candidates:
                if self._goal not in {room for room, _ in candidates}:
                    self._goal = self._select("room", candidates)
                board = view.board.board
                location = suspect_location(board, board.seat_suspects[view.player])
                if isinstance(location, RoomPosition):
                    if self._goal == location.room_id:
                        suggestions = tuple(action for action in options if isinstance(action, Suggest))
                        if suggestions:
                            return self._board_suggestion(view, knowledge, suggestions)
                    if UsePassage() in options and board.layout.passage_from(location.room_id) == self._goal:
                        return UsePassage()
                if Roll() in options:
                    return Roll()
        return super()._pick_board(view, knowledge, options)
