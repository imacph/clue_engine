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
