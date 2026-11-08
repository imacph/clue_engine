import json
import signal
import subprocess
import sys


def test_batch_cli_writes_traces_and_reports_timeouts(tmp_path):
    trace = tmp_path / "batch.jsonl"
    result = subprocess.run(
        [sys.executable, "-m", "clue_engine.batch_cli", "--games", "2", "--players", "2",
         "--policies", "deductive,random", "--max-steps", "0", "--trace", str(trace)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 1
    assert "timeout=2" in result.stdout
    assert "private" in result.stderr
    assert json.loads(trace.read_text(encoding="utf-8").splitlines()[-1])["type"] == "batch_result"


def test_batch_cli_rejects_bad_policy_count_before_writing(tmp_path):
    trace = tmp_path / "batch.jsonl"
    result = subprocess.run(
        [sys.executable, "-m", "clue_engine.batch_cli", "--players", "3",
         "--policies", "deductive,random", "--trace", str(trace)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 2
    assert not trace.exists()


def test_batch_cli_accepts_advanced_profiles(tmp_path):
    trace = tmp_path / "advanced.jsonl"
    result = subprocess.run(
        [sys.executable, "-m", "clue_engine.batch_cli", "--games", "2", "--players", "2",
         "--policies", "probing,strategic", "--trace", str(trace)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0
    assert "probing:" in result.stdout
    assert "strategic:" in result.stdout


def test_batch_and_existing_trace_cli_display_distributions(tmp_path):
    trace = tmp_path / "distribution.jsonl"
    result = subprocess.run(
        [sys.executable, "-m", "clue_engine.batch_cli", "--games", "2", "--players", "2",
         "--max-steps", "0", "--trace", str(trace), "--metric", "outcomes", "--display", "percent"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 1
    assert "Distribution: Outcomes" in result.stdout
    assert "100.0%" in result.stdout
    loaded = subprocess.run(
        [sys.executable, "-m", "clue_engine.distributions_cli", "--trace", str(trace),
         "--metric", "outcomes", "--display", "percent"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert loaded.returncode == 0
    assert "100.0%" in loaded.stdout
    deduction = subprocess.run(
        [sys.executable, "-m", "clue_engine.distributions_cli", "--trace", str(trace),
         "--metric", "deduction", "--filter-policy", "deductive", "--filter-seat", "1"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert deduction.returncode == 0
    assert "policy=deductive, seat=1" in deduction.stdout
    assert "2 seat exposures" in deduction.stdout


def test_invalid_distribution_options_do_not_create_trace(tmp_path):
    trace = tmp_path / "bad.jsonl"
    result = subprocess.run(
        [sys.executable, "-m", "clue_engine.batch_cli", "--trace", str(trace),
         "--metric", "actions", "--filter-seat", "0"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 2
    assert "only to deduction" in result.stderr
    assert not trace.exists()


def test_batch_cli_success_and_incomplete_rotation_warning(tmp_path):
    trace = tmp_path / "successful.jsonl"
    result = subprocess.run(
        [sys.executable, "-m", "clue_engine.batch_cli", "--games", "1", "--players", "2",
         "--seed", "41", "--trace", str(trace)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0
    assert "won=1" in result.stdout
    assert "rotation is incomplete" in result.stderr


def test_batch_cli_accepts_board_setup_json(tmp_path):
    setup = tmp_path / "board-setup.json"
    setup.write_text(json.dumps({
        "game_type": "board",
        "players": 3,
        "bots": ["random", {"candidate_rooms": True, "deal_analysis": True}, "strategic"],
        "game_rules": {"all_refute": True},
        "board_rules": {"randomize_passages": True, "passage_count": 1},
        "seat_suspects": [0, 2, 4],
        "shuffle_bots": True,
        "mode": "spectate",
        "notebook_mode": "automatic",
    }), encoding="utf-8")
    trace = tmp_path / "board.jsonl"
    result = subprocess.run(
        [sys.executable, "-m", "clue_engine.batch_cli", "--games", "1",
         "--setup", str(setup), "--max-steps", "0", "--trace", str(trace)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 1
    records = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    start = next(record for record in records if record["type"] == "game_start")
    assert start["game_type"] == "board"
    assert start["board_rules"]["randomize_passages"]
    assert start["game_rules"]["all_refute"]
    assert any(
        isinstance(policy, dict) and policy["deal_analysis"]
        for policy in start["policy_configs"]
    )
    assert start["board_state"]["board"]["seat_suspects"] == [0, 2, 4]


def test_batch_cli_rejects_setup_with_missing_bot_seat(tmp_path):
    setup = tmp_path / "incomplete.json"
    setup.write_text(json.dumps({
        "game_type": "board", "players": 3, "bots": ["random", None, "random"],
    }), encoding="utf-8")
    trace = tmp_path / "should-not-exist.jsonl"
    result = subprocess.run(
        [sys.executable, "-m", "clue_engine.batch_cli", "--setup", str(setup), "--trace", str(trace)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 2
    assert "bot for every seat" in result.stderr
    assert not trace.exists()


def test_cli_interrupt_writes_cancelled_batch_and_restores_handler(tmp_path, monkeypatch):
    from clue_engine import batch_cli

    real_run_batch = batch_cli.run_batch
    original_handler = signal.getsignal(signal.SIGINT)

    def interrupt_before_run(*args, **kwargs):
        signal.raise_signal(signal.SIGINT)
        return real_run_batch(*args, **kwargs)

    monkeypatch.setattr(batch_cli, "run_batch", interrupt_before_run)
    path = tmp_path / "interrupt.jsonl"
    assert batch_cli.main(["--trace", str(path)]) == 130
    assert signal.getsignal(signal.SIGINT) == original_handler
    assert json.loads(path.read_text(encoding="utf-8").splitlines()[-1])["summary"]["cancelled"]
