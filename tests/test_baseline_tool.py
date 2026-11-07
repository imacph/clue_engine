import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "capture_card_only_baseline.py"


def run_tool(directory, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--trace-dir", str(directory), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_baseline_tool_records_all_profiles_and_player_counts(tmp_path):
    result = run_tool(tmp_path, "--games", "1", "--source-revision", "example-revision")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["games_per_group"] == 1
    assert data["seed"] == 42
    assert data["source_revision"] == "example-revision"
    assert len(data["groups"]) == 21
    assert {(group["players"], group["profile"]) for group in data["groups"]} == {
        *((players, profile) for players in range(2, 7)
          for profile in ("random", "deductive", "probing", "strategic")),
        (4, "mixed"),
    }
    assert all(group["summary"]["started_games"] == 1 for group in data["groups"])
    assert len(list(tmp_path.glob("card-only-*.jsonl"))) == 21


def test_baseline_tool_warns_when_source_revision_is_not_provided(tmp_path):
    result = run_tool(tmp_path, "--games", "1", "--max-steps", "0")
    assert result.returncode != 0
    assert json.loads(result.stdout)["source_revision"] is None
    assert "source revision" in result.stderr


def test_baseline_tool_checks_for_existing_traces_before_running(tmp_path):
    existing = tmp_path / "card-only-4-mixed.jsonl"
    existing.write_text("do not overwrite", encoding="utf-8")
    result = run_tool(tmp_path, "--games", "1")

    assert result.returncode != 0
    assert "already exists" in result.stderr
    assert existing.read_text(encoding="utf-8") == "do not overwrite"
    assert list(tmp_path.iterdir()) == [existing]


def test_baseline_tool_reports_timeout_groups_and_fails(tmp_path):
    result = run_tool(tmp_path, "--games", "1", "--max-steps", "0")

    assert result.returncode != 0
    data = json.loads(result.stdout)
    assert all(group["summary"]["outcomes"]["timeout"] == 1 for group in data["groups"])
    assert all(group["winner_turns"] is None for group in data["groups"])


def test_recorded_baseline_contains_only_aggregate_results():
    path = SCRIPT.parents[1] / "docs" / "card-only-baseline.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["games_per_group"] == 120
    assert data["seed"] == 42
    assert data["rotate"] is True
    assert len(data["groups"]) == 21
    for group in data["groups"]:
        assert group["summary"]["outcomes"]["won"] == 120
        assert group["summary"]["outcomes"]["error"] == 0
        assert group["summary"]["outcomes"]["timeout"] == 0
        assert group["winner_turns"]["count"] == 120
    mixed = next(group for group in data["groups"] if group["profile"] == "mixed")
    assert mixed["players"] == 4
    assert round(mixed["winner_turns"]["mean"], 2) == 5.65
    assert mixed["winner_turns"]["p90"] == 7

    def keys(value):
        if isinstance(value, dict):
            return set(value).union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value))
        return set()

    assert keys(data).isdisjoint({"hands", "solution", "card_id", "private_to"})
