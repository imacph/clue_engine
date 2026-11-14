"""Player-view-only learned choices for board games."""

import math
import random
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeVar

from .board_state import RoomPosition
from .board_turn import BoardPhase, Move, Roll, UsePassage, suspect_location
from .deal_analysis import consistent_deals
from .game_settings import (
    BOARD_PLAYER_COUNTS,
    DEFAULT_LEARNED_STRATEGY,
    LearnedStrategy,
)
from .knowledge import Knowledge, Mark, knowledge_for, known_solution
from .models import Accuse, Action, Combination, Reveal, Suggest
from .observations import EventKind, PlayerView
from .opponent_model import OpponentModel, deal_weights
from .policies import StrategicPolicy
from .threat_model import ThreatModel
from .threat_model import probability as threat_probability

FEATURE_COUNT = 17
ACCUSATION_FEATURE_COUNT = 2
T = TypeVar("T")


@dataclass(frozen=True)
class LinearModel:
    room_weights: tuple[float, ...]
    suggestion_weights: tuple[float, ...]
    accusation_weights: tuple[float, ...] = (0.0, 0.0)

    def __post_init__(self) -> None:
        for weights, count in (
            (self.room_weights, FEATURE_COUNT),
            (self.suggestion_weights, FEATURE_COUNT),
            (self.accusation_weights, ACCUSATION_FEATURE_COUNT),
        ):
            if len(weights) != count or not all(math.isfinite(x) for x in weights):
                raise ValueError(f"model weights must contain {count} finite values")

    @classmethod
    def zeros(cls) -> "LinearModel":
        return cls((0.0,) * FEATURE_COUNT, (0.0,) * FEATURE_COUNT)


def suggestion_features(
    view: PlayerView,
    knowledge: Knowledge,
    suggestion: Suggest,
    strategic: tuple[int | float, ...] | None = None,
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
    features = (
        envelope.count(Mark.UNKNOWN) / 3,
        envelope.count(Mark.HELD) / 3,
        envelope.count(Mark.NOT_HELD) / 3,
        sum(card in view.own_hand for card in cards) / 3,
        uncertain / max(1, 3 * len(other_players)),
        min(clauses, 6) / 6,
        min(repeats, 3) / 3,
        blockers / max(1, len(other_players)),
    )
    components = strategic or (0,) * 10
    if len(components) != 10:
        raise ValueError("strategic suggestion features must contain 10 values")
    return features + (
        float(components[1]),
        float(components[2]),
        math.log1p(components[3]) / 20,
        min(components[4], 8) / 8,
        components[5] / 3,
        components[6] / max(1, len(other_players)),
        components[7] / max(1, 3 * len(other_players)),
        min(math.log1p(components[8]), 5) / 5,
        float(components[9]),
    )


class LearningPolicy(StrategicPolicy):
    """Choose room goals, suggestions, and calculated accusations from visible evidence."""

    def __init__(
        self, rng: random.Random, model: LinearModel, *, explore: bool = False,
        strategy: LearnedStrategy = DEFAULT_LEARNED_STRATEGY,
        opponent_model: OpponentModel | None = None,
        threat_model: ThreatModel | None = None,
        models_by_player_count: Mapping[int, LinearModel] | None = None,
    ) -> None:
        super().__init__(rng)
        if models_by_player_count is not None and set(models_by_player_count) != set(BOARD_PLAYER_COUNTS):
            raise ValueError("player-count models are required for 3, 4, 5, and 6 players")
        if models_by_player_count is not None:
            model = models_by_player_count[4]
        self.model = model
        self.models_by_player_count = models_by_player_count
        self.explore = explore
        self.strategy = strategy
        self.opponent_model = opponent_model
        self.threat_model = threat_model
        self._threat = 0.0
        self.opponent_model_choices = 0
        self.opponent_model_weightings = 0
        self.decisions: list[tuple[str, tuple[float, ...]]] = []
        self._goal: int | None = None
        self._declined_accusation: tuple[float, tuple[tuple[Combination, float], ...]] | None = None

    def _count_deals(self, knowledge: Knowledge) -> dict[Combination, int] | None:
        from .deal_analysis import solution_deal_counts

        return solution_deal_counts(knowledge, max_candidates=24, max_nodes=60000)

    def _select(
        self, kind: str, candidates: tuple[tuple[T, tuple[float, ...]], ...],
        *, offsets: tuple[float, ...] | None = None,
    ) -> T:
        if not candidates:
            raise ValueError("learned decisions require at least one candidate")
        weights = {
            "room": self.model.room_weights,
            "suggestion": self.model.suggestion_weights,
            "accusation": self.model.accusation_weights,
        }[kind]
        temperature = 1.0 if self.explore else getattr(self.strategy, f"{kind}_temperature")
        offsets = offsets if offsets is not None else (0.0,) * len(candidates)
        scores = [
            offset + sum(a * b for a, b in zip(weights, features, strict=True))
            for (_, features), offset in zip(candidates, offsets, strict=True)
        ]
        if temperature == 0:
            best = max(scores)
            if kind == "accusation":
                return candidates[-1][0] if scores[-1] == best else candidates[0][0]
            return self.rng.choice(tuple(item for (item, _), score in zip(candidates, scores, strict=True)
                                         if score == best))
        peak = max(scores)
        values = [math.exp((score - peak) / temperature) for score in scores]
        total = sum(values)
        probabilities = [value / total for value in values]
        index = self.rng.choices(range(len(candidates)), weights=probabilities, k=1)[0]
        chosen = candidates[index][1]
        gradient = tuple(
            (chosen[i] - sum(p * candidate[1][i]
                             for p, candidate in zip(probabilities, candidates, strict=True)))
            / temperature
            for i in range(len(weights))
        )
        if self.explore:
            self.decisions.append((kind, gradient))
        return candidates[index][0]

    def choose(self, view: PlayerView, num_players: int, legal: tuple[Action, ...]) -> Action:
        if view.board is None:
            raise ValueError("learned policy supports board games only")
        if self.models_by_player_count is not None:
            try:
                self.model = self.models_by_player_count[num_players]
            except KeyError as exc:
                raise ValueError("player-count models support games with 3 to 6 players") from exc
        if self.opponent_model is not None:
            self.opponent_model_choices += 1
        if self.threat_model is not None and view.board.phase is BoardPhase.START:
            self._threat = threat_probability(self.threat_model, view, num_players)
        knowledge = knowledge_for(view, num_players)
        accusation = self._analyze(knowledge, legal, enabled=True, risk=False)
        if accusation is not None:
            return accusation
        if self._deal_counts and self.strategy.accusation_threshold < 1:
            counts = self._deal_counts
            support = {combo: float(count) for combo, count in counts.items()}
            if self.opponent_model is not None:
                deals = consistent_deals(knowledge, counts)
                if deals:
                    self.opponent_model_weightings += 1
                    support = {}
                    for (solution, _), weight in zip(
                        deals, deal_weights(self.opponent_model, view.player, view.events, deals), strict=True,
                    ):
                        support[solution] = support.get(solution, 0.0) + weight
            threshold = self.strategy.accusation_threshold * (
                1.0 - self.strategy.threat_sensitivity * self._threat
            )
            signature = (threshold, tuple(sorted(support.items(), key=lambda item: (
                item[0].suspect_id, item[0].weapon_id, item[0].room_id,
            ))))
            if signature != self._declined_accusation:
                best, count = max(support.items(), key=lambda item: item[1])
                confidence = count / sum(support.values())
                candidate = Accuse(best)
                if candidate in legal:
                    selected = self._select(
                        "accusation",
                        ((False, (0.0, 0.0)), (True, (1.0, confidence))),
                        offsets=(0.0, 8.0 * (confidence - threshold)),
                    )
                    if selected:
                        return candidate
                    self._declined_accusation = signature
        return self._choose_with_knowledge(view, knowledge, legal)

    def _suggestion_evidence(
        self, view: PlayerView, knowledge: Knowledge,
        deals: tuple[tuple[Combination, tuple[int, ...]], ...] | None,
    ) -> tuple[dict[int, int], tuple[float, ...] | None]:
        if self.opponent_model is not None and deals:
            self.opponent_model_weightings += 1
            return {}, deal_weights(self.opponent_model, view.player, view.events, deals)
        return super()._suggestion_evidence(view, knowledge, deals)

    def _board_suggestion(
        self, view: PlayerView, knowledge: Knowledge, suggestions: tuple[Suggest, ...],
    ) -> Action:
        self._goal = None
        candidates = self._board_candidates(knowledge, suggestions)
        components = self._suggestion_components(
            view, knowledge, candidates, prefer_probe=False,
        )
        return self._select("suggestion", tuple(
            (action, suggestion_features(view, knowledge, action, components[action]))
            for action in candidates
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
            ) + (0.0,) * (FEATURE_COUNT - 8)
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
