import json

import pytest

from clue_engine.batch import BatchConfig, GameResult, run_batch
from clue_engine.distributions import (
    Distributions,
    format_distribution,
    read_distributions,
)


def game(outcome, steps, turns, policies, first):
    return GameResult(
        game=0, seed=0, policies=tuple(policies), outcome=outcome, winner=None,
        steps=steps, turns=turns, suggestions=0, passes=0, refutations=0,
        first_solution_step=first, final_knowledge=[],
    )


@pytest.fixture
def distributions():
    data = Distributions()
    data.add_game(game("won", 9, [2, 1], ["random", "deductive"], [0, None]))
    data.add_game(game("won", 10, [3, 3], ["deductive", "random"], [7, 10]))
    data.add_game(game("timeout", 20, [5, 5], ["random", "deductive"], [None, 15]))
    data.add_game(game("error", 1, [0, 0], ["random", "deductive"], [None, None]))
    return data


def test_game_length_bins_exclude_incomplete_games(distributions):
    chart = distributions.chart("actions", width=10)
    assert chart.samples == 2
    assert [(row.label, row.count, row.probability) for row in chart.bins] == [
        ("0-9", 1, 0.5), ("10-19", 1, 0.5),
    ]
    assert "timeout=1" in chart.details
    assert "error=1" in chart.details
    assert chart.numeric_summary is not None
    assert chart.numeric_summary.minimum == 9
    assert chart.numeric_summary.maximum == 10
    assert chart.numeric_summary.mean == 9.5
    assert chart.numeric_summary.median == 9.5
    assert chart.numeric_summary.p90 == 10
    turns = distributions.chart("turns", width=2)
    assert [(row.label, row.count) for row in turns.bins] == [("2-3", 2)]


def test_outcome_probabilities_include_all_recorded_results(distributions):
    chart = distributions.chart("outcomes")
    assert chart.samples == 4
    by_label = {row.label: row for row in chart.bins}
    assert by_label["won"].probability == 0.5
    assert by_label["timeout"].probability == 0.25
    assert by_label["error"].probability == 0.25
    assert sum(row.count for row in chart.bins) == chart.samples


def test_deduction_filters_use_seat_exposures_and_report_unlearned(distributions):
    chart = distributions.chart("deduction", width=10, policy="deductive")
    assert chart.samples == 2
    assert [(row.label, row.count) for row in chart.bins] == [("0-9", 1), ("10-19", 1)]
    assert "4 seat exposures" in chart.details
    assert "2 not recorded as learned" in chart.details
    assert "policy=deductive" in chart.title
    chart = distributions.chart("deduction", width=10, policy="deductive", seat=1)
    assert chart.samples == 1
    assert [(row.label, row.count) for row in chart.bins] == [("10-19", 1)]
    assert "3 seat exposures" in chart.details


def test_empty_charts_and_invalid_settings_are_explicit(distributions):
    assert Distributions().chart("actions").numeric_summary is None
    assert distributions.chart("deduction", policy="absent").samples == 0
    assert "No observations" in format_distribution(Distributions().chart("actions"))
    with pytest.raises(ValueError, match="width"):
        distributions.chart("actions", width=0)
    with pytest.raises(ValueError, match="deduction"):
        distributions.chart("actions", policy="random")
    with pytest.raises(ValueError, match="seat"):
        distributions.chart("deduction", seat=-1)
    with pytest.raises(ValueError, match="metric"):
        distributions.chart("unknown")


def test_all_eliminated_game_is_completed_and_repeated_policy_counts_both_seats():
    data = Distributions()
    data.add_game(game("all_eliminated", 12, [1, 1], ["deductive", "deductive"], [0, 5]))
    assert data.chart("actions", width=10).samples == 1
    deduction = data.chart("deduction", policy="deductive", width=10)
    assert deduction.samples == 2
    assert "2 seat exposures" in deduction.details
    assert deduction.bins[0].count == 2


def test_text_output_shows_counts_or_empirical_percentages(distributions):
    chart = distributions.chart("actions", width=10)
    assert "1" in format_distribution(chart, mode="count")
    assert "50.0%" in format_distribution(chart, mode="percent")
    with pytest.raises(ValueError, match="mode"):
        format_distribution(chart, mode="unknown")


def test_loading_existing_trace_matches_live_observations(tmp_path):
    path = tmp_path / "old.jsonl"
    live = Distributions()
    run_batch(
        BatchConfig(games=4, policies=("deductive", "random"), seed=3), path, on_game=live.add_game,
    )
    loaded = read_distributions(path)
    for metric in ("actions", "turns", "outcomes", "deduction"):
        assert loaded.chart(metric, width=5) == live.chart(metric, width=5)


def test_partial_trace_exposes_missing_results(tmp_path):
    path = tmp_path / "partial.jsonl"
    path.write_text(
        "\n".join(json.dumps(item) for item in [
            {"type": "batch_start", "schema_version": 1},
            {"type": "game_start", "game": 0},
            {"type": "action", "game": 0},
        ]) + "\n",
        encoding="utf-8",
    )
    data = read_distributions(path)
    chart = data.chart("outcomes")
    assert chart.samples == 0
    assert "1 started game without a result" in chart.details
    assert "batch_result" in chart.details


def test_invalid_trace_fails_with_line_information(tmp_path):
    path = tmp_path / "invalid.jsonl"
    path.write_text('{"type":"batch_start","schema_version":1}\nnot json\n', encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        read_distributions(path)


def test_invalid_game_result_is_not_silently_counted(tmp_path):
    path = tmp_path / "invalid-result.jsonl"
    path.write_text(
        "\n".join(json.dumps(item) for item in [
            {"type": "batch_start", "schema_version": 1},
            {"type": "game_start", "game": 0},
            {"type": "game_result", "game": 0, "outcome": "won", "steps": -1},
        ]) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="line 3"):
        read_distributions(path)


def test_invalid_turn_counts_are_rejected():
    data = Distributions()
    with pytest.raises(ValueError, match="turn count"):
        data.add_game(game("won", 1, [1, 1], ["random", "deductive"], [None, None]))


def test_trace_loading_can_be_cancelled(tmp_path):
    path = tmp_path / "cancel.jsonl"
    path.write_text('{"type":"batch_start","schema_version":1}\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="cancelled"):
        read_distributions(path, cancelled=lambda: True)
