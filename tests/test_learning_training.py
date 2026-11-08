import json

import pytest

from clue_engine import learning
from clue_engine.learning import (
    benchmark,
    evaluate,
    load_model,
    save_model,
    train,
    tune,
)
from clue_engine.learning_policy import LinearModel


def test_model_round_trip_and_refuse_overwrite(tmp_path):
    path = tmp_path / "model.json"
    model = LinearModel.zeros()
    save_model(path, model, {"games": 1})
    assert load_model(path) == model
    with pytest.raises(FileExistsError):
        save_model(path, model, {})


@pytest.mark.parametrize("data", [
    {},
    {"schema": True, "room_weights": [0] * 8, "suggestion_weights": [0] * 8},
    {"schema": 2, "room_weights": [0] * 8, "suggestion_weights": [0] * 8},
    {"schema": 1, "room_weights": [float("inf")] * 8, "suggestion_weights": [0] * 8},
])
def test_invalid_models_are_rejected(tmp_path, data):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_model(path)


def test_training_reproducible_and_updates_weights():
    first, summary = train(games=2, seed=3, opponents=("random",) * 3)
    second, second_summary = train(games=2, seed=3, opponents=("random",) * 3)
    assert (first, summary) == (second, second_summary)
    assert summary["timeouts"] == 0
    assert first != LinearModel.zeros()


def test_training_can_continue_from_an_existing_model():
    initial = LinearModel((1.0,) * 8, (2.0,) * 8)
    _, summary = train(games=1, seed=3, opponents=("random",) * 3, initial_model=initial)
    assert summary["initial_room_weights"] == list(initial.room_weights)
    assert summary["initial_suggestion_weights"] == list(initial.suggestion_weights)


def test_evaluation_balances_seats_and_is_reproducible():
    result = evaluate(LinearModel.zeros(), games=4, seed=23, opponents=("random",) * 3)
    assert result == evaluate(LinearModel.zeros(), games=4, seed=23, opponents=("random",) * 3)
    assert [seat["games"] for seat in result["seats"]] == [1, 1, 1, 1]
    assert result["wins"] + result["losses"] + result["timeouts"] == 4
    assert 0 <= result["win_rate_ci95"][0] <= result["win_rate_ci95"][1] <= 1
    for seat in result["seats"]:
        assert seat["wins"] + seat["losses"] + seat["timeouts"] == seat["games"]
        assert seat["win_rate"] in (0.0, 1.0)
        assert 0 <= seat["win_rate_ci95"][0] <= seat["win_rate_ci95"][1] <= 1


def test_tuning_is_reproducible_and_keeps_best_observed_candidate():
    initial = LinearModel((1.0,) * 8, (2.0,) * 8)
    arguments = {
        "initial_model": initial,
        "games_per_pool": 4,
        "seed": 31,
        "population": 4,
        "generations": 1,
    }
    first, first_summary = tune(**arguments)
    second, second_summary = tune(**arguments)
    assert first == second
    assert first_summary == second_summary
    assert first_summary["best_score"] >= first_summary["initial_score"]
    assert len(first_summary["generation_history"]) == 1


def test_benchmark_pairs_all_profiles_on_balanced_seats():
    report = benchmark(LinearModel.zeros(), games=4, seed=38)
    assert len(report["pools"]) == 2
    for pool in report["pools"]:
        assert pool["games"] == 4
        assert "learned" in pool["profiles"]
        for result in pool["profiles"].values():
            assert sum(result["seat_wins"]) == result["wins"]
            assert len(result["seat_wins"]) == 4
        for comparison in pool["paired_vs_learned"].values():
            assert (
                comparison["learned_only_wins"]
                + comparison["profile_only_wins"]
                + comparison["ties"] == 4
            )
            assert -1 <= comparison["win_rate_delta"] <= 1


def test_benchmark_pairs_candidate_with_incumbent_on_same_games():
    model = LinearModel((1.0,) * 8, (2.0,) * 8)
    report = benchmark(model, games=4, seed=39, incumbent=model)
    for pool in report["pools"]:
        assert pool["profiles"]["learned"] == pool["profiles"]["incumbent"]
        comparison = pool["paired_vs_learned"]["incumbent"]
        assert comparison == {
            "learned_only_wins": 0,
            "profile_only_wins": 0,
            "ties": 4,
            "win_rate_delta": 0.0,
            "win_rate_delta_ci95": (0.0, 0.0),
        }


@pytest.mark.parametrize("kwargs", [
    {"games_per_pool": 3, "population": 4, "generations": 1},
    {"games_per_pool": 4, "population": 3, "generations": 1},
    {"games_per_pool": 4, "population": 4, "generations": 0},
])
def test_tuning_rejects_unbalanced_or_invalid_searches(kwargs):
    with pytest.raises(ValueError):
        tune(initial_model=LinearModel.zeros(), seed=1, **kwargs)


def test_tune_cli_dispatches_without_opponents_argument(tmp_path, monkeypatch, capsys):
    initial = tmp_path / "initial.json"
    output = tmp_path / "candidate.json"
    save_model(initial, LinearModel.zeros(), {})
    calls = []

    def fake_tune(**kwargs):
        calls.append(kwargs)
        return LinearModel.zeros(), {"status": "tuned"}

    monkeypatch.setattr(learning, "tune", fake_tune)
    assert learning.main([
        "tune", "--initial", str(initial), "--output", str(output),
        "--games-per-pool", "4", "--seed", "1",
    ]) == 0
    assert calls[0]["games_per_pool"] == 4
    assert load_model(output) == LinearModel.zeros()
    assert '"status": "tuned"' in capsys.readouterr().out


def test_benchmark_cli_dispatches_without_opponents_argument(tmp_path, monkeypatch, capsys):
    model_path = tmp_path / "model.json"
    save_model(model_path, LinearModel.zeros(), {})
    calls = []

    def fake_benchmark(model, **kwargs):
        calls.append(kwargs)
        return {"seed": kwargs["seed"]}

    monkeypatch.setattr(learning, "benchmark", fake_benchmark)
    assert learning.main([
        "benchmark", "--model", str(model_path), "--games", "4", "--seed", "2",
    ]) == 0
    assert calls == [{"games": 4, "seed": 2, "max_steps": 10_000, "incumbent": None}]
    assert '"seed": 2' in capsys.readouterr().out
