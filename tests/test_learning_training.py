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
from clue_engine.learning_policy import FEATURE_COUNT, LinearModel


def test_model_round_trip_and_refuse_overwrite(tmp_path):
    path = tmp_path / "model.json"
    model = LinearModel((0.0,) * FEATURE_COUNT, (0.0,) * FEATURE_COUNT, (1.0, -0.5))
    save_model(path, model, {"games": 1})
    assert load_model(path) == model
    with pytest.raises(FileExistsError):
        save_model(path, model, {})


def test_legacy_model_is_padded_with_zero_weights(tmp_path):
    path = tmp_path / "legacy.json"
    legacy_weights = [float(index) for index in range(8)]
    path.write_text(json.dumps({
        "schema": 1,
        "room_weights": legacy_weights,
        "suggestion_weights": legacy_weights,
    }), encoding="utf-8")
    model = load_model(path)
    assert model.room_weights == tuple(legacy_weights) + (0.0,) * (FEATURE_COUNT - 8)
    assert model.suggestion_weights == model.room_weights
    assert model.accusation_weights == (0.0, 0.0)


def test_schema_two_model_defaults_accusation_weights(tmp_path):
    path = tmp_path / "schema-two.json"
    path.write_text(json.dumps({
        "schema": 2, "room_weights": [0] * FEATURE_COUNT,
        "suggestion_weights": [0] * FEATURE_COUNT,
    }), encoding="utf-8")
    assert load_model(path).accusation_weights == (0.0, 0.0)


def test_default_model_override_loads_explicit_file_and_reports_errors(tmp_path, monkeypatch):
    path = tmp_path / "candidate.json"
    model = LinearModel((1.0,) * FEATURE_COUNT, (0.0,) * FEATURE_COUNT, (0.1, 0.2))
    save_model(path, model, {})
    monkeypatch.setenv("CLUE_LEARNED_MODEL", str(path))
    assert learning.load_default_model() == model
    monkeypatch.setenv("CLUE_LEARNED_MODEL", "")
    with pytest.raises(ValueError, match="CLUE_LEARNED_MODEL"):
        learning.load_default_model()
    monkeypatch.setenv("CLUE_LEARNED_MODEL", str(tmp_path / "missing.json"))
    with pytest.raises(FileNotFoundError):
        learning.load_default_model()


@pytest.mark.parametrize("data", [
    {},
    {"schema": True, "room_weights": [0] * FEATURE_COUNT,
     "suggestion_weights": [0] * FEATURE_COUNT},
    {"schema": 2, "room_weights": [0] * 8, "suggestion_weights": [0] * 8},
    {"schema": 1, "room_weights": [float("inf")] * 8, "suggestion_weights": [0] * 8},
    {"schema": 3, "room_weights": [0] * FEATURE_COUNT,
     "suggestion_weights": [0] * FEATURE_COUNT, "accusation_weights": [True, 0]},
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
    initial = LinearModel((1.0,) * FEATURE_COUNT, (2.0,) * FEATURE_COUNT)
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


def test_mixed_board_evaluation_balances_seats(monkeypatch):
    seen = []

    def fake_game(policy, seat, seed, opponents, max_steps, *, board_rules):
        seen.append((seat, board_rules.randomize_rooms))
        return seat, 10, False

    monkeypatch.setattr(learning, "_game", fake_game)
    evaluate(LinearModel.zeros(), games=8, seed=23, opponents=("random",) * 3, boards="mixed")
    assert seen == [(seat, shuffled) for shuffled in (False, True) for seat in range(4)]


def test_tune_cli_passes_board_and_opponent_options(tmp_path, monkeypatch):
    initial = tmp_path / "initial.json"
    output = tmp_path / "candidate.json"
    save_model(initial, LinearModel.zeros(), {})
    seen = {}

    def fake_tune(**kwargs):
        seen.update(kwargs)
        return LinearModel.zeros(), {}

    monkeypatch.setattr(learning, "tune", fake_tune)
    assert learning.main([
        "tune", "--initial", str(initial), "--output", str(output),
        "--seed", "1", "--games-per-pool", "8", "--boards", "mixed",
        "--opponents", "analytical,analytical,analytical",
    ]) == 0
    assert seen["boards"] == "mixed"
    assert seen["pools"] == (("analytical",) * 3,)


def test_tuning_is_reproducible_and_keeps_best_observed_candidate():
    initial = LinearModel((1.0,) * FEATURE_COUNT, (2.0,) * FEATURE_COUNT)
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
    model = LinearModel((1.0,) * FEATURE_COUNT, (2.0,) * FEATURE_COUNT)
    report = benchmark(model, games=4, seed=39, incumbent=model)
    for pool in report["pools"]:
        assert pool["profiles"]["learned"] == pool["profiles"]["incumbent"]
        comparison = pool["paired_vs_learned"]["incumbent"]
        assert comparison == {
            "learned_only_wins": 0,
            "profile_only_wins": 0,
            "ties": 4,
            "completed_pairs": 4,
            "excluded_pairs": 0,
            "win_rate_delta": 0.0,
            "win_rate_delta_ci95": (0.0, 0.0),
        }


def test_benchmark_excludes_timed_out_pairs(monkeypatch):
    def fake_game(policy, seat, seed, opponents, max_steps):
        if isinstance(policy, learning.LearningPolicy) and seed % 4 == 0:
            return None, max_steps, True
        return seat, 10, False

    monkeypatch.setattr(learning, "_game", fake_game)
    report = benchmark(LinearModel.zeros(), games=4, seed=40)
    comparison = report["pools"][0]["paired_vs_learned"]["random"]
    assert comparison["completed_pairs"] == 3
    assert comparison["excluded_pairs"] == 1
    assert comparison["ties"] == 3
    assert comparison["win_rate_delta"] == 0

    def always_timeout(policy, seat, seed, opponents, max_steps):
        return None, max_steps, True

    monkeypatch.setattr(learning, "_game", always_timeout)
    comparison = benchmark(LinearModel.zeros(), games=4, seed=40)["pools"][0]["paired_vs_learned"]["random"]
    assert comparison["completed_pairs"] == 0
    assert comparison["win_rate_delta"] is None
    assert comparison["win_rate_delta_ci95"] is None


def test_training_reward_favors_fast_wins():
    assert 0 < learning._win_reward(200, 0.001) < learning._win_reward(20, 0.001) < 1
    assert learning._win_reward(200, 0) == 1


def test_training_updates_accusation_weights_with_terminal_outcome(monkeypatch):
    def fake_game(policy, seat, seed, opponents, max_steps):
        policy.decisions.append(("accusation", (1.0, 0.6)))
        return seat, 10, False

    monkeypatch.setattr(learning, "_game", fake_game)
    model, summary = train(games=1, seed=3, opponents=("random",) * 3)
    assert model.accusation_weights[0] > 0
    assert model.accusation_weights[1] > 0
    assert summary["wins"] == 1


def test_tuning_uses_same_search_seeds_in_every_generation(monkeypatch):
    seeds = []

    def fake_score(model, *, games, seed, max_steps):
        seeds.append(seed)
        return 0.1, [{"opponents": [], "wins": 0, "games": games}]

    monkeypatch.setattr(learning, "_tuning_score", fake_score)
    tune(initial_model=LinearModel.zeros(), games_per_pool=4, seed=10, population=4, generations=2)
    assert seeds == [10] * 8


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


def test_evaluate_cli_passes_learned_controls(tmp_path, monkeypatch, capsys):
    model_path = tmp_path / "model.json"
    save_model(model_path, LinearModel.zeros(), {})
    calls = []

    def fake_evaluate(model, **kwargs):
        calls.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(learning, "evaluate", fake_evaluate)
    assert learning.main([
        "evaluate", "--model", str(model_path), "--games", "4", "--seed", "2",
        "--room-temperature", "0.5", "--suggestion-temperature", "1",
        "--accusation-temperature", "0.2", "--accusation-threshold", "0.75",
    ]) == 0
    strategy = calls[0]["strategy"]
    assert (strategy.room_temperature, strategy.suggestion_temperature,
            strategy.accusation_temperature, strategy.accusation_threshold) == (0.5, 1, 0.2, 0.75)
    assert '"ok": true' in capsys.readouterr().out
