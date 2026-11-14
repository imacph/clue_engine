import json
import re
import threading
import time

import pytest

from clue_engine.batch import GameResult, _Aggregate
from clue_engine.engine import IllegalActionError
from clue_engine.webapp import create_app
from clue_engine.webapp.batch_charts import knowledge_charts


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
    assert result["settings"]["games"] == 2
    assert result["settings"]["seed"] == 13
    assert result["settings"]["max_steps"] == 0
    assert result["settings"]["players"] == 2
    assert result["settings"]["policies"] == ["random", "deductive"]
    assert "Game type: Card-only game" in result["settings_display"]
    assert "Rotate profiles across seats: Yes" in result["settings_display"]
    assert set(result["summary"]["policy_stats"]) == {"random", "deductive"}

    chart = client.get(f"/api/batch/{batch_id}/distribution?metric=outcomes&width=1")
    assert chart.status_code == 200
    assert chart.get_json()["samples"] == 2
    knowledge = client.get(
        f"/api/batch/{batch_id}/distribution?metric=knowledge_candidates&seat=0"
    )
    assert knowledge.status_code == 200
    assert knowledge.get_json()["points"][0]["samples"] == 2
    first = client.get(f"/api/batch/{batch_id}/distribution?metric=solution_turn&seat=1")
    assert first.status_code == 200
    assert first.get_json()["samples"] <= 2
    assert client.get(
        f"/api/batch/{batch_id}/distribution?metric=rolls&width=1"
    ).status_code == 400


def test_batch_api_balances_two_profiles_across_three_player_seats(client):
    token = csrf_token(client)
    setup = {
        "game_type": "card_only",
        "players": 3,
        "bots": ["random", "deductive"],
        "shuffle_bots": True,
        "max_steps": 0,
    }
    started = post(client, token, "/api/batch", {"setup": setup, "games": 5})
    assert started.status_code == 202
    result = wait_for_batch(client, started.get_json()["batch_id"])
    assert result["status"] == "completed"
    assert len(result["summary"]["wins_by_seat"]) == 3
    random_seats = result["summary"]["policy_stats"]["random"]["seat_games"]
    deductive_seats = result["summary"]["policy_stats"]["deductive"]["seat_games"]
    assert random_seats + deductive_seats == 15
    assert abs(random_seats - deductive_seats) == 1


@pytest.mark.parametrize("game_type,players", [("card_only", 2), ("board", 3)])
def test_batch_api_accepts_analytical_bots(client, game_type, players):
    token = csrf_token(client)
    setup = {
        "game_type": game_type, "players": players,
        "bots": ["analytical"] + ["random"] * (players - 1),
        "seed": 13, "max_steps": 1,
    }
    started = post(client, token, "/api/batch", {"setup": setup, "games": 1})
    assert started.status_code == 202
    result = wait_for_batch(client, started.get_json()["batch_id"])
    assert result["status"] == "completed"
    assert result["summary"]["outcomes"]["error"] == 0
    assert result["summary"]["policy_stats"]["analytical"]["seat_games"] == 1


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


@pytest.mark.parametrize("game_type", ["card_only", "board"])
def test_filtered_distributions_count_games_and_seat_exposures(client, monkeypatch, game_type):
    def fake_run(config, trace_path, *, progress, cancelled, on_game):
        aggregate = _Aggregate(config)
        for index, (policies, outcome, winner, steps, first) in enumerate([
            (("random", "random", "deductive"), "won", 0, 9, [1, None, 4]),
            (("deductive", "random", "random"), "all_eliminated", None, 11, [8, 3, None]),
            (("deductive", "deductive", "random"), "timeout", None, 20, [None, 15, None]),
        ]):
            result = GameResult(
                game=index, seed=index, policies=policies, outcome=outcome, winner=winner,
                steps=steps, turns=[index + 1, 2, 3], suggestions=0, passes=0, refutations=0,
                first_solution_step=first, final_knowledge=[], game_type=game_type,
                moves=(index * 5 if game_type == "board" else 0),
            )
            aggregate.add(result)
            on_game(result)
        return aggregate.summary(False)

    monkeypatch.setattr("clue_engine.webapp.run_batch", fake_run)
    token = csrf_token(client)
    setup = {
        "game_type": game_type, "players": 3,
        "bots": ["random", "random", "deductive"],
    }
    batch_id = post(client, token, "/api/batch", {"setup": setup, "games": 3}).get_json()["batch_id"]
    assert wait_for_batch(client, batch_id)["status"] == "completed"
    path = f"/api/batch/{batch_id}/distribution"

    def chart(**params):
        response = client.get(path, query_string=params)
        assert response.status_code == 200
        return response.get_json()

    outcomes = chart(metric="outcomes", policy="random")
    assert outcomes["samples"] == 3  # repeated profiles do not duplicate games
    assert chart(metric="outcomes", policy="deductive", seat=0)["samples"] == 2
    assert chart(metric="outcomes", policy="random", seat=0)["samples"] == 1
    assert chart(metric="outcomes", policy="absent")["samples"] == 0
    actions = chart(metric="actions", policy="random", width=100)
    assert actions["samples"] == 2
    assert actions["numeric_summary"] == {
        "minimum": 9, "maximum": 11, "mean": 10, "median": 10, "p90": 11,
    }
    assert "timeout=1" in actions["details"]
    assert chart(metric="actions", policy="deductive", seat=0)["samples"] == 1
    deduction = chart(metric="deduction", policy="random")
    assert deduction["samples"] == 2
    assert "5 seat exposures; 3 not recorded as learned" in deduction["details"]
    seats = chart(metric="seat_outcomes", policy="random")
    assert seats["samples"] == 5
    assert {item["label"]: item["count"] for item in seats["bins"]} == {
        "won": 1, "not_won": 3, "timeout": 1, "error": 0, "cancelled": 0,
    }
    assert chart(metric="seat_outcomes", policy="random", seat=0)["samples"] == 1
    turns = chart(metric="seat_turns", policy="random", width=1)
    assert turns["samples"] == 4
    assert {item["label"]: item["count"] for item in turns["bins"]} == {"1": 1, "2": 2, "3": 1}
    assert chart(metric="seat_turns", policy="random", seat=0, width=1)["samples"] == 1
    assert chart(metric="seat_turns", policy="absent")["samples"] == 0
    runs_path = f"/api/batch/{batch_id}/runs"
    runs = client.get(runs_path, query_string={
        "policy": "random", "sort": "steps", "order": "desc", "offset": 1, "limit": 1,
    }).get_json()
    assert runs["total"] == 3
    assert len(runs["runs"]) == 1
    assert runs["runs"][0]["game"] == 1
    assert runs["runs"][0]["first_solution"] == 3
    assert runs["runs"][0]["first_solution_steps"] == [8, 3, None]
    assert "seed" not in runs["runs"][0]
    ordered = client.get(runs_path, query_string={"sort": "first_solution"}).get_json()["runs"]
    assert [row["first_solution"] for row in ordered] == [1, 3, 15]
    assert client.get(runs_path, query_string={"policy": "deductive", "seat": 0}).get_json()["total"] == 2
    assert client.get(runs_path, query_string={"sort": "bad"}).status_code == 400
    assert client.get(runs_path, query_string={"limit": 101}).status_code == 400
    if game_type == "board":
        moves = chart(metric="moves", policy="random", width=10)
        assert moves["samples"] == 2
        assert moves["numeric_summary"]["median"] == 2.5
    assert client.get(path, query_string={"metric": "seat_outcomes", "seat": -1}).status_code == 400
    assert client.get(path, query_string={"metric": "seat_outcomes", "width": 0}).status_code == 400


def test_seat_comparison_api_uses_matching_appearances_and_metric_denominators(client, monkeypatch):
    def fake_run(config, trace_path, *, progress, cancelled, on_game):
        aggregate = _Aggregate(config)
        for index, (policies, outcome, winner, turns, first) in enumerate([
            (("random", "random", "deductive"), "won", 0, [1, 2, 3], [0, None, None]),
            (("deductive", "random", "random"), "all_eliminated", None, [2, 4, 6], [1, 4, 5]),
            (("deductive", "deductive", "random"), "timeout", None, [3, 5, 7], [None, None, 9]),
            (("deductive", "deductive", "probing"), "error", None, [0, 0, 0], [None, None, None]),
        ]):
            result = GameResult(
                game=index, seed=index, policies=policies, outcome=outcome, winner=winner,
                steps=20, turns=turns, suggestions=0, passes=0, refutations=0,
                first_solution_step=first, final_knowledge=[],
            )
            aggregate.add(result)
            on_game(result)
        return aggregate.summary(False)

    monkeypatch.setattr("clue_engine.webapp.run_batch", fake_run)
    token = csrf_token(client)
    started = post(client, token, "/api/batch", {
        "setup": {"game_type": "card_only", "players": 3,
                  "bots": ["random", "deductive", "probing"]},
        "games": 4,
    })
    batch_id = started.get_json()["batch_id"]
    assert wait_for_batch(client, batch_id)["status"] == "completed"
    path = f"/api/batch/{batch_id}/distribution"

    def chart(metric, **filters):
        response = client.get(path, query_string={"metric": metric, **filters})
        assert response.status_code == 200
        data = response.get_json()
        assert set(data) == {"title", "details", "seat_bars", "unit"}
        return data

    turns = chart("seat_compare_turns", policy="random")
    assert turns["unit"] == "turns"
    assert turns["seat_bars"] == [
        {"seat": 0, "value": 1, "samples": 1},
        {"seat": 1, "value": 3, "samples": 2},
        {"seat": 2, "value": 6, "samples": 1},
    ]
    assert "1 incomplete matching appearances excluded" in turns["details"]
    wins = chart("seat_compare_win_rate", policy="random")
    assert wins["unit"] == "%"
    assert wins["seat_bars"] == [
        {"seat": 0, "value": 100, "samples": 1},
        {"seat": 1, "value": 0, "samples": 2},
        {"seat": 2, "value": 0, "samples": 1},
    ]
    learned = chart("seat_compare_learned_rate", policy="random")
    assert learned["unit"] == "%"
    assert learned["seat_bars"] == [
        {"seat": 0, "value": 100, "samples": 1},
        {"seat": 1, "value": 50, "samples": 2},
        {"seat": 2, "value": 100, "samples": 2},
    ]
    assert "including incomplete games" in learned["details"]
    first = chart("seat_compare_first_action", policy="random")
    assert first["unit"] == "actions"
    assert first["seat_bars"] == [
        {"seat": 0, "value": 0, "samples": 1},
        {"seat": 1, "value": 4, "samples": 1},
        {"seat": 2, "value": 7, "samples": 2},
    ]
    assert "1 appearances not recorded as learned are excluded" in first["details"]
    assert chart("seat_compare_win_rate", seat=2)["seat_bars"] == [
        {"seat": 2, "value": 0, "samples": 2},
    ]
    assert chart("seat_compare_turns", policy="random", seat=2)["seat_bars"] == [
        {"seat": 2, "value": 6, "samples": 1},
    ]
    assert chart("seat_compare_win_rate", policy="random", seat=0)["seat_bars"][0]["value"] == 100
    for metric in ("seat_compare_turns", "seat_compare_win_rate", "seat_compare_learned_rate",
                   "seat_compare_first_action"):
        assert chart(metric, policy="random", seat=9)["seat_bars"] == []
        assert chart(metric, policy="absent")["seat_bars"] == []
    unavailable_turns = chart("seat_compare_turns", policy="probing")
    assert "unavailable" in unavailable_turns["details"]
    assert unavailable_turns["seat_bars"] == [
        {"seat": 2, "value": None, "samples": 0},
    ]
    assert chart("seat_compare_win_rate", policy="probing")["seat_bars"] == [
        {"seat": 2, "value": None, "samples": 0},
    ]
    assert chart("seat_compare_learned_rate", policy="probing")["seat_bars"] == [
        {"seat": 2, "value": 0, "samples": 1},
    ]
    unavailable_action = chart("seat_compare_first_action", policy="probing")
    assert "unavailable" in unavailable_action["details"]
    assert unavailable_action["seat_bars"] == [
        {"seat": 2, "value": None, "samples": 0},
    ]
    assert chart("seat_compare_turns", policy="probing", seat=1)["seat_bars"] == []
    assert client.get(path, query_string={"metric": "seat_compare_turns", "seat": -1}).status_code == 400
    assert client.get(path, query_string={"metric": "seat_compare_turns", "width": 0}).status_code == 400


def test_knowledge_charts_use_filtered_seat_turns_and_last_snapshots(tmp_path):
    solution = {"suspect_id": 1, "weapon_id": 2, "room_id": 3}

    def item(player, candidates, learned=False):
        return {"player": player, "candidates": {"suspect": candidates, "weapon": 1, "room": 1},
                "knows_solution": learned}

    records = [
        {"type": "game_start", "policies": ["random", "random"], "solution": solution},
        {"type": "initial_knowledge", "knowledge": [item(0, 3), item(1, 2)]},
        {"type": "action", "actor": 0, "action": {"kind": "EndTurn"},
         "events": [{"kind": "END_TURN", "actor": 0}]},
        {"type": "knowledge", "knowledge": [item(0, 2), item(1, 2)]},
        {"type": "action", "actor": 1, "action": {"kind": "Pass"}, "events": []},
        {"type": "knowledge", "knowledge": [item(0, 1, True), item(1, 2)]},
        {"type": "action", "actor": 0, "action": {"kind": "Accuse", "combination": solution}, "events": []},
        {"type": "knowledge", "knowledge": [item(0, 1, True), item(1, 2)]},
        {"type": "game_result"},
        {"type": "game_start", "policies": ["deductive", "random"], "solution": solution},
        {"type": "initial_knowledge", "knowledge": [item(0, 1, True), item(1, 3)]},
        {"type": "game_result"},
    ]
    path = tmp_path / "trace.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    histogram = knowledge_charts(path, "random", 0, 1, "solution_turn")
    assert histogram.samples == 1
    assert [(bin.label, bin.count) for bin in histogram.bins] == [("1", 1)]
    assert "1 matching seat appearances; 0 not recorded" in histogram.details
    assert knowledge_charts(path, "absent", None, 1, "solution_turn").samples == 0
    series = knowledge_charts(path, "random", 0, 1, "knowledge_candidates")
    assert series["points"] == [
        {"turn": 0, "samples": 1, "mean": 5, "minimum": 5, "maximum": 5},
        {"turn": 1, "samples": 1, "mean": 3, "minimum": 3, "maximum": 3},
        {"turn": 2, "samples": 1, "mean": 3, "minimum": 3, "maximum": 3},
    ]
    learned = knowledge_charts(path, "random", None, 1, "knowledge_learned")
    assert learned["points"][0]["samples"] == 3
    assert learned["points"][1]["mean"] == 1


@pytest.mark.parametrize("game_type", ["card_only", "board"])
def test_batch_run_replay_uses_recorded_actions_and_stays_session_private(client, game_type):
    token = csrf_token(client)
    setup = {
        "game_type": game_type, "players": 3,
        "bots": ["random", "deductive", "probing"], "seed": 17, "max_steps": 12,
    }
    batch_id = post(client, token, "/api/batch", {"setup": setup, "games": 2}).get_json()["batch_id"]
    assert wait_for_batch(client, batch_id)["status"] == "completed"
    runs = client.get(f"/api/batch/{batch_id}/runs").get_json()["runs"]
    replay_path = f"/api/batch/{batch_id}/runs/1/replay"
    assert client.post(replay_path, json={}).status_code == 403
    other = client.application.test_client()
    other_token = csrf_token(other)
    assert post(other, other_token, replay_path, {}).status_code == 404
    assert post(client, token, f"/api/batch/{batch_id}/runs/99/replay", {}).status_code == 404
    opened = post(client, token, replay_path, {})
    assert opened.status_code == 200
    assert opened.get_json()["positions"] == runs[1]["steps"] + 1
    state = client.get(f"/api/replay/state?position={runs[1]['steps']}&player=0")
    assert state.status_code == 200
    assert state.get_json()["is_replay"]
    assert state.get_json()["steps"] == runs[1]["steps"]
    export = client.get("/api/replay/export")
    assert export.status_code == 200
    assert len(export.get_json()["history"]) == runs[1]["steps"]
    assert client.get(f"/api/batch/{batch_id}/runs").get_json()["total"] == 2


def test_error_run_still_has_a_replay_when_initial_state_was_recorded(client, monkeypatch):
    def fail_deductions(engine):
        raise IllegalActionError("forced deduction failure")

    monkeypatch.setattr("clue_engine.batch._deductions", fail_deductions)
    token = csrf_token(client)
    started = post(client, token, "/api/batch", {
        "setup": {"game_type": "card_only", "players": 2, "bots": ["random", "random"]},
        "games": 1,
    })
    batch_id = started.get_json()["batch_id"]
    assert wait_for_batch(client, batch_id)["summary"]["outcomes"]["error"] == 1
    replay = post(client, token, f"/api/batch/{batch_id}/runs/0/replay", {})
    assert replay.status_code == 200
    assert replay.get_json()["positions"] == 1
