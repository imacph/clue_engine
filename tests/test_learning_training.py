import json

import pytest

from clue_engine.learning import evaluate, load_model, save_model, train
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


def test_evaluation_balances_seats_and_is_reproducible():
    result = evaluate(LinearModel.zeros(), games=4, seed=23, opponents=("random",) * 3)
    assert result == evaluate(LinearModel.zeros(), games=4, seed=23, opponents=("random",) * 3)
    assert [seat["games"] for seat in result["seats"]] == [1, 1, 1, 1]
    assert result["wins"] + result["losses"] + result["timeouts"] == 4
    assert 0 <= result["win_rate_ci95"][0] <= result["win_rate_ci95"][1] <= 1
