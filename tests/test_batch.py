import json
from dataclasses import replace

import pytest

from clue_engine.batch import (
    BatchConfig,
    batch_config_from_setup,
    read_game_trace,
    run_batch,
)
from clue_engine.board_state import RoomPosition
from clue_engine.board_turn import Move, Roll
from clue_engine.engine import Engine
from clue_engine.game_settings import BoardRules, BotStrategy, GameRules
from clue_engine.models import Accuse, Combination, EndTurn, Pass, Reveal, Suggest
from clue_engine.session import create_board_game
from clue_engine.state import GameState


def records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_seeded_batches_are_reproducible_and_rotate_same_deal(tmp_path):
    config = BatchConfig(games=4, policies=("deductive", "random"), seed=10, max_steps=3)
    first, second = tmp_path / "first.jsonl", tmp_path / "second.jsonl"
    summary = run_batch(config, first)
    assert summary == run_batch(config, second)
    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")
    starts = [item for item in records(first) if item["type"] == "game_start"]
    assert [item["seed"] for item in starts] == [10, 10, 11, 11]
    assert starts[0]["hands"] == starts[1]["hands"]
    assert starts[0]["policies"] == ["deductive", "random"]
    assert starts[1]["policies"] == ["random", "deductive"]
    assert summary["outcomes"]["timeout"] == 4
    assert summary["completed_games"] == 0


def test_batch_accepts_rotated_advanced_profiles(tmp_path):
    path = tmp_path / "profiles.jsonl"
    summary = run_batch(BatchConfig(4, ("probing", "strategic"), seed=15, max_steps=500), path)
    starts = [item for item in records(path) if item["type"] == "game_start"]
    assert [start["policies"] for start in starts] == [
        ["probing", "strategic"], ["strategic", "probing"],
        ["probing", "strategic"], ["strategic", "probing"],
    ]
    assert summary["outcomes"]["error"] == 0
    assert summary["outcomes"]["timeout"] == 0
    assert summary["policy_stats"]["probing"]["seat_games"] == 4
    assert summary["policy_stats"]["strategic"]["seat_games"] == 4


def test_action_counts_and_trace_preserve_multi_event_refutation(tmp_path, monkeypatch):
    from clue_engine import batch

    solution = Combination(0, 6, 12)
    engine = Engine(GameState(
        solution,
        [frozenset({1, 2, 3, 4, 5}), frozenset({7, 8, 9, 10, 11}),
         frozenset({13, 14, 15, 16}), frozenset({17, 18, 19, 20})],
        0,
    ))

    class Policy:
        def __init__(self, actions):
            self.actions = iter(actions)

        def choose(self, view, num_players, legal):
            return next(self.actions)

    policies = [Policy([Suggest(Combination(0, 7, 13)), Accuse(solution)]),
                Policy([Reveal(7)]), Policy([]), Policy([])]
    monkeypatch.setattr(batch, "_make_game", lambda *args: (engine, policies))
    path = tmp_path / "trace.jsonl"
    summary = run_batch(BatchConfig(games=1, policies=("random",) * 4), path)
    game = read_game_trace(path, 0)
    actions = [item for item in game if item["type"] == "action"]
    assert len(actions) == 3
    assert [event["kind"] for event in actions[1]["events"]] == ["REFUTE", "SHOW"]
    assert actions[1]["events"][1]["card_id"] == 7
    knowledge = [item for item in game if item["type"] == "knowledge"]
    assert len(knowledge[1]["knowledge"]) == 4
    result = game[-1]
    assert result["outcome"] == "won"
    assert result["steps"] == 3
    assert result["turns"][0] == 1
    assert result["refutations"] == 1
    assert summary["completed_games"] == 1
    assert summary["wins_by_seat"][0] == 1


def test_existing_trace_is_never_overwritten(tmp_path):
    path = tmp_path / "trace.jsonl"
    path.write_text("existing", encoding="utf-8")
    with pytest.raises(FileExistsError):
        run_batch(BatchConfig(games=1, policies=("random", "random")), path)
    assert path.read_text(encoding="utf-8") == "existing"


def test_cancellation_and_missing_trace_are_explicit(tmp_path):
    path = tmp_path / "trace.jsonl"
    summary = run_batch(
        BatchConfig(games=3, policies=("random", "random")), path, cancelled=lambda: True
    )
    assert summary["cancelled"]
    assert summary["started_games"] == 0
    with pytest.raises(ValueError, match="game"):
        read_game_trace(path, 0)


@pytest.mark.parametrize(
    "config",
    [
        BatchConfig(games=0, policies=("random", "random")),
        BatchConfig(games=1, policies=("random",)),
        BatchConfig(games=1, policies=("random", "unknown")),
        BatchConfig(games=1, policies=("random", "random"), max_steps=-1),
    ],
)
def test_invalid_config_is_rejected_before_creating_file(tmp_path, config):
    path = tmp_path / "trace.jsonl"
    with pytest.raises(ValueError):
        run_batch(config, path)
    assert not path.exists()


def test_saved_actions_replay_and_match_deductions(tmp_path):
    from clue_engine.batch import _deductions, _event_data

    path = tmp_path / "replay.jsonl"
    run_batch(BatchConfig(games=1, policies=("deductive", "random"), seed=45, max_steps=40), path)
    trace = read_game_trace(path, 0)
    start = trace[0]
    engine = Engine(GameState(
        Combination(**start["solution"]),
        [frozenset(hand) for hand in start["hands"]],
        start["current_player"],
    ))
    assert trace[1]["knowledge"] == _deductions(engine)
    first_known = [0 if player["knows_solution"] else None for player in trace[1]["knowledge"]]
    constructors = {"Suggest": Suggest, "Accuse": Accuse, "Reveal": Reveal, "Pass": Pass, "EndTurn": EndTurn}
    actions = [item for item in trace if item["type"] == "action"]
    snapshots = [item for item in trace if item["type"] == "knowledge"]
    assert len(actions) == len(snapshots)
    for record, snapshot in zip(actions, snapshots, strict=True):
        data = dict(record["action"])
        kind = data.pop("kind")
        if "combination" in data:
            data["combination"] = Combination(**data["combination"])
        assert engine.to_move == record["actor"]
        events = engine.step(constructors[kind](**data))
        assert [_event_data(event) for event in events] == record["events"]
        assert snapshot["step"] == record["step"]
        assert _deductions(engine) == snapshot["knowledge"]
        for item in snapshot["knowledge"]:
            if item["knows_solution"] and first_known[item["player"]] is None:
                first_known[item["player"]] = record["step"]
    assert first_known == trace[-1]["first_solution_step"]
    assert len(actions) == trace[-1]["steps"]


def test_all_eliminated_counts_as_completed(tmp_path, monkeypatch):
    from clue_engine import batch

    solution = Combination(0, 6, 12)
    engine = Engine(GameState(
        solution,
        [frozenset({1, 2, 3, 4, 5}), frozenset({7, 8, 9, 10, 11}),
         frozenset({13, 14, 15, 16}), frozenset({17, 18, 19, 20})],
        0,
    ))

    class WrongPolicy:
        def choose(self, view, num_players, legal):
            return Accuse(Combination(1, 6, 12))

    monkeypatch.setattr(batch, "_make_game", lambda *args: (engine, [WrongPolicy()] * 4))
    path = tmp_path / "eliminated.jsonl"
    summary = run_batch(BatchConfig(1, ("random",) * 4), path)
    assert summary["outcomes"]["all_eliminated"] == 1
    assert summary["completed_games"] == 1
    assert summary["mean_turns_by_seat"] == [1, 1, 1, 1]
    assert read_game_trace(path, 0)[-1]["winner"] is None


def test_invalid_action_is_recorded_as_error(tmp_path, monkeypatch):
    from clue_engine import batch

    make_game = batch._make_game

    class InvalidPolicy:
        def choose(self, view, num_players, legal):
            return Reveal(999)

    def invalid_game(seed, names, game, config):
        engine, _ = make_game(seed, names, game, config)
        return engine, [InvalidPolicy()] * len(names)

    monkeypatch.setattr(batch, "_make_game", invalid_game)
    path = tmp_path / "invalid.jsonl"
    summary = run_batch(BatchConfig(1, ("random", "random")), path)
    trace = read_game_trace(path, 0)
    assert summary["outcomes"]["error"] == 1
    assert trace[-2]["type"] == "action_error"
    assert trace[-2]["action"] == {"kind": "Reveal", "card_id": 999}
    assert "IllegalActionError" in trace[-1]["error"]


def test_failed_deduction_keeps_the_action_and_events(tmp_path, monkeypatch):
    from clue_engine import batch
    from clue_engine.knowledge import InconsistentKnowledgeError

    real_deductions = batch._deductions
    calls = 0

    def deductions(engine):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise InconsistentKnowledgeError("test inconsistency")
        return real_deductions(engine)

    monkeypatch.setattr(batch, "_deductions", deductions)
    path = tmp_path / "failed-deduction.jsonl"
    summary = run_batch(BatchConfig(1, ("deductive", "deductive"), seed=1), path)
    trace = read_game_trace(path, 0)
    assert summary["outcomes"]["error"] == 1
    action = trace[-3]
    assert action["type"] == "action"
    assert action["events"]
    assert trace[-2]["type"] == "knowledge_error"
    assert trace[-2]["error"] == "test inconsistency"
    assert trace[-1]["steps"] == action["step"]
    assert trace[-1]["final_knowledge"] == trace[1]["knowledge"]


def test_unexpected_error_propagates_with_partial_trace(tmp_path, monkeypatch):
    from clue_engine import batch

    make_game = batch._make_game

    class CrashingPolicy:
        def choose(self, view, num_players, legal):
            raise RuntimeError("policy crashed")

    def crashing_game(seed, names, game, config):
        engine, _ = make_game(seed, names, game, config)
        return engine, [CrashingPolicy()] * len(names)

    monkeypatch.setattr(batch, "_make_game", crashing_game)
    path = tmp_path / "partial.jsonl"
    with pytest.raises(RuntimeError, match="policy crashed"):
        run_batch(BatchConfig(1, ("random", "random")), path)
    assert [item["type"] for item in records(path)] == ["batch_start", "game_start", "initial_knowledge"]


def test_unexpected_deduction_error_still_records_applied_action(tmp_path, monkeypatch):
    from clue_engine import batch

    original = batch._deductions
    calls = 0

    def deductions(engine):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("unexpected deduction failure")
        return original(engine)

    monkeypatch.setattr(batch, "_deductions", deductions)
    path = tmp_path / "partial-action.jsonl"
    with pytest.raises(RuntimeError, match="unexpected deduction failure"):
        run_batch(BatchConfig(1, ("deductive", "deductive"), seed=1), path)
    assert records(path)[-1]["type"] == "action"
    assert records(path)[-1]["events"]


def test_cancel_during_game_preserves_partial_game(tmp_path):
    calls = 0

    def cancelled():
        nonlocal calls
        calls += 1
        return calls >= 3

    path = tmp_path / "cancelled.jsonl"
    summary = run_batch(BatchConfig(3, ("random", "random")), path, cancelled=cancelled)
    trace = read_game_trace(path, 0)
    assert summary["outcomes"]["cancelled"] == 1
    assert summary["started_games"] == 1
    assert trace[-1]["steps"] == 1
    assert trace[-1]["outcome"] == "cancelled"


def test_summary_denominators_seat_comparisons_and_percentiles():
    from clue_engine.batch import GameResult, _Aggregate

    aggregate = _Aggregate(BatchConfig(5, ("random", "deductive")))
    for index, steps in enumerate((1, 3, 7, 9)):
        names = ("random", "deductive") if index % 2 == 0 else ("deductive", "random")
        aggregate.add(GameResult(
            index, index, names, "won", 0, steps, [2, 1], 1, 0, 1, [steps, None], [],
        ))
    aggregate.add(GameResult(
        4, 4, ("random", "deductive"), "timeout", None, 100, [9, 9], 0, 0, 0, [0, None], [],
    ))
    summary = aggregate.summary(False)
    assert (summary["mean_actions"], summary["median_actions"], summary["p90_actions"]) == (5, 5, 9)
    assert summary["mean_turns_by_seat"] == [2, 1]
    random = summary["policy_stats"]["random"]
    assert (random["seat_games"], random["completed_seats"], random["wins"]) == (5, 4, 2)
    assert random["win_rate_per_completed_seat"] == 0.5
    assert random["learned_solution"] == 3
    assert random["mean_first_solution_step"] == (1 + 7) / 3
    assert random["by_seat"][0]["win_rate_per_completed_seat"] == 1
    assert random["by_seat"][1]["win_rate_per_completed_seat"] == 0


def test_batch_setup_accepts_board_rules_and_custom_per_seat_bots():
    config = batch_config_from_setup(
        {
            "game_type": "board",
            "players": 3,
            "bots": ["random", {"candidate_rooms": True, "risk_accusation": True}, "strategic"],
            "game_rules": {"all_refute": True, "public_refutations": True},
            "board_rules": {
                "randomize_rooms": True, "procedural_map": True,
                "randomize_passages": True, "passage_count": 3,
            },
            "seat_suspects": [0, 3, 5],
            "shuffle_bots": True,
            "mode": "play",
            "seat": 1,
            "notebook_mode": "manual",
            "progress": "step",
            "debug": False,
            "shuffle_seat": False,
            "seed": 17,
            "max_steps": 250,
        },
        games=5,
    )
    config.validate()
    assert config.game_type == "board"
    assert config.policies == (
        "random", BotStrategy(candidate_rooms=True, risk_accusation=True), "strategic",
    )
    assert config.game_rules == GameRules(all_refute=True, public_refutations=True)
    assert config.board_rules.procedural_map and config.board_rules.passage_count == 3
    assert config.seat_suspects == (0, 3, 5)
    assert config.shuffle_bots
    assert (config.seed, config.max_steps) == (17, 250)


@pytest.mark.parametrize(
    "setup, message",
    [
        ({"game_type": "board", "players": 2, "bots": ["random", "random"]}, "between 3 and 6"),
        ({"game_type": "card_only", "players": 19, "bots": ["random"] * 19,
          "game_rules": {"face_up_card": True}}, "at least one card per player"),
        ({"game_type": "board", "players": 3, "bots": ["random"] * 3,
          "board_rules": {"procedural_map": True}}, "require scrambled rooms"),
        ({"game_type": "board", "players": 3, "bots": ["random", None, "random"]},
         "bot for every seat"),
    ],
)
def test_batch_setup_rejects_unsupported_or_invalid_combinations(setup, message):
    with pytest.raises((TypeError, ValueError), match=message):
        batch_config_from_setup(setup, games=1)


def test_board_batch_records_events_and_reports_board_statistics(tmp_path, monkeypatch):
    from clue_engine import batch
    from clue_engine.distributions import read_distributions

    board_rules = BoardRules(optional_suggestion=True)
    engine, _ = create_board_game(3, 29, "random", board_rules=board_rules)
    solution = engine.state.solution
    turn = engine.state.board
    assert turn is not None
    board = turn.board
    suspect_id = board.seat_suspects[0]
    occupied = board.occupied_hallways()
    door = next(door for door in board.layout.doors if door.hallway_square not in occupied)
    suspects = tuple(
        replace(token, location=door.hallway_square) if token.suspect_id == suspect_id else token
        for token in board.suspects
    )
    engine.state.board = replace(turn, board=replace(board, suspects=suspects))

    class BoardPolicy:
        def __init__(self, seat):
            self.seat = seat

        def choose(self, view, num_players, legal):
            if self.seat != 0 and Accuse(solution) in legal:
                return Accuse(solution)
            if Roll() in legal:
                return Roll()
            room_moves = tuple(
                action for action in legal
                if isinstance(action, Move) and isinstance(action.destination, RoomPosition)
            )
            if room_moves:
                return room_moves[0]
            hallway_moves = tuple(
                action for action in legal
                if isinstance(action, Move) and not isinstance(action.destination, RoomPosition)
            )
            if hallway_moves:
                return hallway_moves[0]
            if EndTurn() in legal:
                return EndTurn()
            return legal[0]

    monkeypatch.setattr(
        batch, "_make_game",
        lambda *args: (engine, tuple(BoardPolicy(seat) for seat in range(3))),
    )
    trace_path = tmp_path / "board.jsonl"
    distributions = []
    summary = run_batch(
        BatchConfig(
            1, ("random",) * 3, seed=29, game_type="board", board_rules=board_rules,
        ),
        trace_path,
        on_game=distributions.append,
    )
    result = distributions[0]
    trace = records(trace_path)
    game_start = next(record for record in trace if record["type"] == "game_start")
    game_result = trace[-2]
    move = next(
        event for record in trace if record["type"] == "action"
        for event in record["events"] if event["kind"] == "MOVE"
        and "room_id" in (event["location"] or {})
    )
    assert game_start["game_type"] == "board"
    assert game_start["board_state"]["board"]["layout"]["rooms"]
    assert game_start["board_rules"]["optional_suggestion"]
    assert move["location"]["room_id"] >= 0
    assert result.outcome == "won"
    assert result.rolls >= 1 and result.moves >= 1 and result.room_entries >= 1
    assert game_result["rolls"] == result.rolls
    assert game_result["moves"] == result.moves
    assert game_result["room_entries"] == result.room_entries
    assert summary["game_type"] == "board"
    assert summary["mean_room_entries"] == result.room_entries
    assert read_distributions(trace_path).chart("room_entries").bins[0].count == 1


def test_custom_policy_batch_is_reproducible_and_named_in_summary(tmp_path):
    config = BatchConfig(
        2,
        (BotStrategy(candidate_suggestions=True), BotStrategy(candidate_suggestions=True)),
        seed=6,
        max_steps=0,
    )
    first, second = tmp_path / "custom-1.jsonl", tmp_path / "custom-2.jsonl"
    summary = run_batch(config, first)
    assert summary == run_batch(config, second)
    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")
    assert "custom:candidate_suggestions" in summary["policy_stats"]
