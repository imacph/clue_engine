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
        (2, "strategic", 0, 67, "82df85706238a0d2fcb4bc1cce934b1cc5cb780ca12b6d19fab39cb7f8349a55"),
        (
            4,
            "random,deductive,probing,strategic",
            3,
            95,
            "1f30b85d41882bde704f6d3a64472684703c61108e5d9d6a3f08ee70ea7d0752",
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
