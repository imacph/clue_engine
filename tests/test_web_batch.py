import re
import threading
import time

import pytest

from clue_engine.webapp import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def csrf_token(client):
    response = client.get("/")
    assert response.status_code == 200
    match = re.search(rb'name="csrf-token" content="([^"]+)"', response.data)
    assert match is not None
    return match.group(1).decode()


def post(client, token, path, body):
    return client.post(path, json=body, headers={"X-CSRF-Token": token})


def wait_for_batch(client, batch_id):
    for _ in range(300):
        response = client.get(f"/api/batch/{batch_id}")
        assert response.status_code == 200
        result = response.get_json()
        if result["status"] not in {"queued", "running"}:
            return result
        time.sleep(0.01)
    pytest.fail("batch simulation did not finish")


def test_batch_ui_is_available_in_the_shared_browser_and_desktop_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b'id="main-batch"' in response.data
    assert b'id="batch-games"' in response.data
    assert b'id="batch-screen"' in response.data
    assert b'id="batch-metric"' in response.data
    assert b'data-board-only' in response.data


def test_batch_api_runs_setup_and_returns_summary_and_distributions(client):
    token = csrf_token(client)
    setup = {
        "game_type": "card_only",
        "players": 2,
        "bots": ["random", "deductive"],
        "seed": 13,
        "max_steps": 0,
    }
    started = post(client, token, "/api/batch", {"setup": setup, "games": 2})
    assert started.status_code == 202
    batch_id = started.get_json()["batch_id"]
    result = wait_for_batch(client, batch_id)
    assert result["status"] == "completed"
    assert result["finished_games"] == 2
    assert result["summary"]["requested_games"] == 2
    assert result["summary"]["game_type"] == "card_only"
    assert set(result["summary"]["policy_stats"]) == {"random", "deductive"}

    chart = client.get(f"/api/batch/{batch_id}/distribution?metric=outcomes&width=1")
    assert chart.status_code == 200
    assert chart.get_json()["samples"] == 2
    assert client.get(
        f"/api/batch/{batch_id}/distribution?metric=rolls&width=1"
    ).status_code == 400


def test_batch_api_accepts_full_board_setup_and_rejects_invalid_requests(client):
    token = csrf_token(client)
    invalid = post(client, token, "/api/batch", {
        "setup": {"game_type": "board", "players": 2, "bots": ["random", "random"]},
        "games": 1,
    })
    assert invalid.status_code == 400
    assert "between 3 and 6" in invalid.get_json()["error"]

    setup = {
        "game_type": "board",
        "players": 3,
        "bots": ["random", {"candidate_rooms": True, "deal_analysis": True}, "probing"],
        "game_rules": {"reverse_refutation": True},
        "board_rules": {
            "randomize_rooms": True, "procedural_map": True, "randomize_passages": True,
            "passage_count": 1,
        },
        "seat_suspects": [0, 1, 2],
        "shuffle_bots": True,
        "seed": 42,
        "max_steps": 0,
    }
    started = post(client, token, "/api/batch", {"setup": setup, "games": 1})
    assert started.status_code == 202
    result = wait_for_batch(client, started.get_json()["batch_id"])
    assert result["status"] == "completed"
    assert result["summary"]["game_type"] == "board"
    chart = client.get(
        f"/api/batch/{started.get_json()['batch_id']}/distribution?metric=room_entries&width=1"
    )
    assert chart.status_code == 200
    assert chart.get_json()["denominator"] == "completed board games"


def test_batch_api_requires_csrf_and_hides_other_sessions(client):
    token = csrf_token(client)
    body = {
        "setup": {
            "game_type": "card_only", "players": 2, "bots": ["random", "random"],
            "max_steps": 0,
        },
        "games": 1,
    }
    assert client.post("/api/batch", json=body).status_code == 403
    started = post(client, token, "/api/batch", body)
    assert started.status_code == 202
    batch_id = started.get_json()["batch_id"]
    other = client.application.test_client()
    assert other.get(f"/api/batch/{batch_id}").status_code == 404
    assert wait_for_batch(client, batch_id)["status"] == "completed"


def test_batch_cancel_stops_the_background_run(client, monkeypatch):
    entered_runner = threading.Event()

    def wait_for_cancel(config, trace_path, *, progress, cancelled, on_game):
        entered_runner.set()
        while not cancelled():
            time.sleep(0.005)
        return {"cancelled": True}

    monkeypatch.setattr("clue_engine.webapp.run_batch", wait_for_cancel)
    token = csrf_token(client)
    started = post(client, token, "/api/batch", {
        "setup": {
            "game_type": "card_only", "players": 2, "bots": ["random", "random"],
        },
        "games": 1,
    })
    assert started.status_code == 202
    batch_id = started.get_json()["batch_id"]
    assert entered_runner.wait(timeout=2)
    cancelled = post(client, token, f"/api/batch/{batch_id}/cancel", {})
    assert cancelled.status_code == 200
    result = wait_for_batch(client, batch_id)
    assert result["status"] == "cancelled"
    assert result["cancel_requested"]
