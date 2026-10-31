from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Protocol

from . import rules
from .board import Square
from .board_state import BoardState, RoomPosition, SuspectToken, WeaponToken
from .board_turn import BoardPhase, BoardTurn, Move, Roll, UsePassage, suspect_location
from .models import Accuse, Action, Combination, EndTurn, Pass, Reveal, Suggest
from .observations import (
    Event,
    EventKind,
    PlayerView,
    last_suggest_index,
    pending,
    refutation_events,
    view_for,
)
from .state import GameState


class IllegalActionError(ValueError):
    pass


class DiceRandom(Protocol):
    def randint(self, a: int, b: int) -> int: ...


@dataclass(frozen=True)
class ActionRecord:
    actor: int
    action: Action
    events: tuple[Event, ...]


class Engine:
    """Applies actions to a game. It owns the event log and the turn marker."""

    def __init__(self, state: GameState, *, dice_rng: DiceRandom | None = None):
        if len(state.player_hands) < 2:
            raise ValueError("a game requires at least two players")
        if not 0 <= state.current_player < len(state.player_hands):
            raise ValueError("current_player must identify an existing player")
        if state.board is not None:
            if len(state.board.board.seat_suspects) != len(state.player_hands):
                raise ValueError("board seats must match the player count")
            if dice_rng is None:
                raise ValueError("board games require a separate dice RNG")
        self.state = state
        self._dice_rng = dice_rng
        self.log: tuple[Event, ...] = ()
        self.history: tuple[ActionRecord, ...] = ()

    @property
    def num_players(self) -> int:
        return len(self.state.player_hands)

    @property
    def is_over(self) -> bool:
        return rules.is_over(self.state, self.log)

    @property
    def winner(self) -> int | None:
        return rules.winner(self.state, self.log)

    @property
    def to_move(self) -> int | None:
        """The player who must act next: a pending responder, else the turn owner."""
        if self.is_over:
            return None
        response = pending(self.log, self.num_players)
        return response.player if response is not None else self.state.current_player

    def legal_actions(self) -> tuple[Action, ...]:
        player = self.to_move
        if player is None:
            return ()
        return rules.legal_actions(self.state, self.log, player)

    def view(self, player: int) -> PlayerView:
        if not 0 <= player < self.num_players:
            raise ValueError(f"invalid player: {player}")
        return view_for(self.log, player, self.state.player_hands[player], self.state.board)

    def step(self, action: Action) -> tuple[Event, ...]:
        """Apply an action for the player to move and return the events it produced."""
        player = self.to_move
        if player is None or action not in self.legal_actions():
            raise IllegalActionError(f"{action} is not legal for player {player}")
        events = self._events_for(player, action)
        self.log += events
        if self.state.board is not None:
            self.history += (ActionRecord(player, action, events),)
        if any(event.kind is EventKind.END_TURN for event in events):
            self._advance_turn()
        return events

    def _events_for(self, player: int, action: Action) -> tuple[Event, ...]:
        match action:
            case Suggest(combination=combo):
                if self.state.board is not None:
                    return self._board_suggestion(player, combo)
                return (Event(EventKind.SUGGEST, player, combo=combo),)
            case Pass():
                return (Event(EventKind.PASS, player),)
            case Reveal(card_id=card_id):
                index = last_suggest_index(self.log)
                assert index is not None
                return refutation_events(player, card_id, self.log[index])
            case Accuse(combination=combo):
                accusation = Event(EventKind.ACCUSE, player, combo=combo)
                if combo == self.state.solution:
                    return (accusation,)
                # An eliminated player has nothing left to do on their turn.
                events = (accusation, Event(EventKind.END_TURN, player))
                if self.state.board is not None:
                    events += self._clear_eliminated_door(player)
                return events
            case EndTurn():
                return (Event(EventKind.END_TURN, player),)
            case Roll():
                return self._roll(player)
            case Move(destination=destination):
                return self._move(player, destination, EventKind.MOVE)
            case UsePassage():
                turn = self._board_turn()
                location = suspect_location(turn.board, turn.board.seat_suspects[player])
                assert isinstance(location, RoomPosition)
                room_id = turn.board.layout.passage_from(location.room_id)
                assert room_id is not None
                return self._move(player, RoomPosition(room_id), EventKind.PASSAGE)
            case _:
                raise TypeError(f"unknown action {action!r}")

    def _board_turn(self) -> BoardTurn:
        if self.state.board is None:
            raise ValueError("action requires a board game")
        return self.state.board

    def _roll(self, player: int) -> tuple[Event, ...]:
        turn = self._board_turn()
        if self._dice_rng is None:
            raise ValueError("board games require a separate dice RNG")
        dice = (self._dice_rng.randint(1, 6), self._dice_rng.randint(1, 6))
        if any(type(value) is not int or not 1 <= value <= 6 for value in dice):
            raise ValueError("dice RNG must produce integers from 1 to 6")
        location = suspect_location(turn.board, turn.board.seat_suspects[player])
        self.state.board = replace(
            turn, phase=BoardPhase.MOVE, dice=dice, remaining=sum(dice),
            visited=frozenset((location,)) if isinstance(location, Square) else frozenset(),
            starting_room=location.room_id if isinstance(location, RoomPosition) else None,
            summoned_seats=turn.summoned_seats - {player},
        )
        return (Event(EventKind.ROLL, player, dice=dice),)

    @staticmethod
    def _with_suspect(
        board: BoardState, suspect_id: int, destination: Square | RoomPosition,
    ) -> BoardState:
        return replace(
            board,
            suspects=tuple(
                SuspectToken(token.suspect_id, destination)
                if token.suspect_id == suspect_id else token
                for token in board.suspects
            ),
        )

    def _move(
        self, player: int, destination: Square | RoomPosition, kind: EventKind,
    ) -> tuple[Event, ...]:
        turn = self._board_turn()
        suspect_id = turn.board.seat_suspects[player]
        board = self._with_suspect(turn.board, suspect_id, destination)
        in_room = isinstance(destination, RoomPosition)
        self.state.board = replace(
            turn,
            board=board,
            phase=BoardPhase.SUGGEST if in_room else BoardPhase.MOVE,
            remaining=0 if in_room else turn.remaining - 1,
            visited=turn.visited if in_room else turn.visited | {destination},
            summoned_seats=turn.summoned_seats - {player},
        )
        return (Event(kind, player, location=destination, suspect_id=suspect_id),)

    def _board_suggestion(self, player: int, combo: Combination) -> tuple[Event, ...]:
        turn = self._board_turn()
        board = turn.board
        room = RoomPosition(combo.room_id)
        events = (Event(EventKind.SUGGEST, player, combo=combo),)
        summoned = turn.summoned_seats - {player}
        if suspect_location(board, combo.suspect_id) != room:
            board = self._with_suspect(board, combo.suspect_id, room)
            events += (Event(
                EventKind.SUSPECT_MOVED, player, location=room, suspect_id=combo.suspect_id,
            ),)
            if combo.suspect_id in board.seat_suspects:
                seat = board.seat_suspects.index(combo.suspect_id)
                if seat != player and seat not in rules.eliminated(self.state, self.log):
                    summoned = summoned | {seat}
        weapon = next(token for token in board.weapons if token.weapon_id == combo.weapon_id)
        if weapon.room_id != combo.room_id:
            board = replace(
                board,
                weapons=tuple(
                    WeaponToken(token.weapon_id, combo.room_id)
                    if token.weapon_id == combo.weapon_id else token
                    for token in board.weapons
                ),
            )
            events += (Event(
                EventKind.WEAPON_MOVED, player, location=room, weapon_id=combo.weapon_id,
            ),)
        self.state.board = replace(
            turn, board=board, phase=BoardPhase.AFTER_SUGGESTION, summoned_seats=summoned,
        )
        return events

    def _clear_eliminated_door(self, player: int) -> tuple[Event, ...]:
        turn = self._board_turn()
        suspect_id = turn.board.seat_suspects[player]
        location = suspect_location(turn.board, suspect_id)
        door = next(
            (door for door in turn.board.layout.doors if door.hallway_square == location),
            None,
        )
        summoned = turn.summoned_seats - {player}
        if door is None:
            self.state.board = replace(turn, summoned_seats=summoned)
            return ()
        room = RoomPosition(door.room_id)
        self.state.board = replace(
            turn, board=self._with_suspect(turn.board, suspect_id, room),
            summoned_seats=summoned,
        )
        return (Event(EventKind.SUSPECT_MOVED, player, location=room, suspect_id=suspect_id),)

    def _advance_turn(self) -> None:
        out = rules.eliminated(self.state, self.log)
        for offset in range(1, self.num_players + 1):
            seat = (self.state.current_player + offset) % self.num_players
            if seat not in out:
                self.state.current_player = seat
                if self.state.board is not None:
                    turn = self.state.board
                    self.state.board = BoardTurn(
                        board=turn.board, summoned_seats=turn.summoned_seats,
                    )
                return


class _RecordedDice:
    def __init__(self, values: Sequence[int]):
        self._values = iter(values)

    def randint(self, a: int, b: int) -> int:
        try:
            return next(self._values)
        except StopIteration as exc:
            raise ValueError("record does not contain enough roll values") from exc


def replay_board(
    initial_state: GameState, history: Sequence[ActionRecord], *,
    dice_rng: DiceRandom | None = None,
) -> Engine:
    """Verify a full record; an optional dice RNG enables subsequent play."""
    if initial_state.board is None:
        raise ValueError("replay requires an initial board game")
    values: list[int] = []
    for record in history:
        rolls = tuple(event for event in record.events if event.kind is EventKind.ROLL)
        if isinstance(record.action, Roll):
            if len(rolls) != 1 or rolls[0].dice is None:
                raise ValueError("recorded roll is missing its dice")
            values.extend(rolls[0].dice)
        elif rolls:
            raise ValueError("unexpected roll in action record")
    engine = Engine(deepcopy(initial_state), dice_rng=_RecordedDice(values))
    for record in history:
        if engine.to_move != record.actor:
            raise ValueError("recorded actor does not match the player to move")
        events = engine.step(record.action)
        if events != record.events:
            raise ValueError("recorded events do not match replay")
    if dice_rng is not None:
        engine._dice_rng = dice_rng
    return engine
