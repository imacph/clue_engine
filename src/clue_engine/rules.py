from .actions import ACCUSES, ENDTURNS, PASSES, SUGGESTIONS
from .models import Action, Reveal
from .observations import Event, EventKind, last_suggest_index, pending
from .state import GameState

_TURN_START_ACTIONS = (*SUGGESTIONS, *ACCUSES, *ENDTURNS)
_AFTER_SUGGESTION_ACTIONS = (*ACCUSES, *ENDTURNS)


def winner(state: GameState, log: tuple[Event, ...]) -> int | None:
    return next(
        (e.actor for e in log if e.kind is EventKind.ACCUSE and e.combo == state.solution),
        None,
    )


def is_over(state: GameState, log: tuple[Event, ...]) -> bool:
    """The game ends on a correct accusation or once every player is eliminated."""
    return winner(state, log) is not None or len(eliminated(state, log)) == len(state.player_hands)


def eliminated(state: GameState, log: tuple[Event, ...]) -> frozenset[int]:
    return frozenset(
        e.actor for e in log if e.kind is EventKind.ACCUSE and e.combo != state.solution
    )


def legal_actions(state: GameState, log: tuple[Event, ...], player: int) -> tuple[Action, ...]:
    if is_over(state, log):
        return ()

    response = pending(log, len(state.player_hands))
    if response is not None:
        return _response_actions(state, log, player) if response.player == player else ()

    if player != state.current_player:
        return ()
    if player in eliminated(state, log):
        return ENDTURNS
    if _suggested_this_turn(log):
        return _AFTER_SUGGESTION_ACTIONS
    return _TURN_START_ACTIONS


def _response_actions(state: GameState, log: tuple[Event, ...], player: int) -> tuple[Action, ...]:
    # Refuting is mandatory when able, so PASS is only legal with no matching card.
    index = last_suggest_index(log)
    assert index is not None
    combo = log[index].combo
    assert combo is not None
    matching = sorted({combo.suspect_id, combo.weapon_id, combo.room_id} & state.player_hands[player])
    if not matching:
        return PASSES
    return tuple(Reveal(card_id) for card_id in matching)


def _suggested_this_turn(log: tuple[Event, ...]) -> bool:
    turn_start = max(
        (i + 1 for i, e in enumerate(log) if e.kind is EventKind.END_TURN),
        default=0,
    )
    return any(e.kind is EventKind.SUGGEST for e in log[turn_start:])
