import hashlib
import json
import platform
import sys

import pytest

from clue_engine.actions import SUGGESTIONS
from clue_engine.session import create_game
from clue_engine.simulation import play


@pytest.mark.parametrize("num_players", [2, 7])
def test_default_game_remains_card_only_outside_board_player_limits(num_players):
    engine, policies = create_game(num_players, 42, "deductive")

    assert len(policies) == len(engine.state.player_hands) == num_players
    assert engine.to_move == 0
    assert set(SUGGESTIONS) <= set(engine.legal_actions())


@pytest.mark.skipif(
    platform.python_implementation() != "CPython" or sys.version_info[:2] != (3, 13),
    reason="the frozen baseline uses CPython 3.13 seeded random behavior",
)
@pytest.mark.parametrize(
    "num_players,policy,winner,event_count,digest",
    [
        (2, "strategic", 1, 45, "394909bdd3dce46aca68fbd49662370a1e4a3d26a3d2918f3cac10bd4bb14dfe"),
        (
            4,
            "random,deductive,probing,strategic",
            1,
            88,
            "1781a12c362c4bcb7367ba3ee7e4d8904012ad71f7528f60e4393a11e1b1960b",
        ),
    ],
)
def test_seeded_card_only_event_log_matches_frozen_baseline(
    num_players, policy, winner, event_count, digest
):
    engine, policies = create_game(num_players, 42, policy)
    play(engine, policies)
    events = [
        [
            event.kind.name,
            event.actor,
            (
                [event.combo.suspect_id, event.combo.weapon_id, event.combo.room_id]
                if event.combo is not None
                else None
            ),
            event.card_id,
            event.private_to,
        ]
        for event in engine.log
    ]

    assert engine.winner == winner
    assert len(events) == event_count
    assert hashlib.sha256(json.dumps(events, separators=(",", ":")).encode()).hexdigest() == digest
