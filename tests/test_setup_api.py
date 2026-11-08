import re

from clue_engine.webapp import create_app


def client_and_token():
    client = create_app().test_client()
    page = client.get("/")
    token = re.search(rb'name="csrf-token" content="([^"]+)"', page.data).group(1).decode()
    return client, token


def test_setup_metadata_is_available_without_dealing():
    client, _ = client_and_token()
    page = client.get("/").get_data(as_text=True)
    assert re.search(
        r'<select id="progress"[^>]*>\s*<option value="turn">Turn-by-turn</option>',
        page,
    )
    response = client.get("/api/setup")
    assert response.status_code == 200
    data = response.get_json()
    assert len(data["starts"]) == 6
    assert len(data["layout"]["rooms"]) == 9
    assert "hand" not in data and "solution" not in data
    assert client.get("/api/state").status_code == 404


def test_structured_board_setup_and_validation():
    client, token = client_and_token()
    headers = {"X-CSRF-Token": token}
    config = {
        "game_type": "board", "players": 3, "seat": 0, "seed": 42,
        "progress": "step", "seat_suspects": [2, 0, 1],
        "board_rules": {
            "move_suspect": False, "move_weapon": False,
            "summoned_suggestion": False, "secret_passages": False,
        },
        "bots": [None, "deductive", {
            "repeat_reveals": True, "deal_analysis": True, "risk_accusation": True,
        }],
    }
    response = client.post("/api/game", json=config, headers=headers)
    assert response.status_code == 201
    state = response.get_json()
    assert state["hand_sizes"] == [6, 6, 6]
    assert len(state["hand"]) == state["hand_sizes"][0]
    assert state["debug_info"] is None
    assert state["board"]["turn_player"] == 1
    assert state["board_rules"] == {
        **config["board_rules"], "early_end": True, "revisit_hallways": False,
        "optional_suggestion": False, "accuse_in_room": False, "stay_to_suggest": False,
        "randomize_rooms": False, "procedural_map": False, "randomize_doors": False, "randomize_passages": False,
        "passage_count": 2,
    }
    assert state["board"]["suspects"][2]["seat"] == 0

    invalid = dict(config, seat_suspects=[1, 2, 3])
    assert client.post("/api/game", json=invalid, headers=headers).status_code == 400
    invalid = dict(config, bots=[None, "unknown", "random"])
    assert client.post("/api/game", json=invalid, headers=headers).status_code == 400
    invalid = dict(config, bots=[None, {"unknown": True}, "random"])
    assert client.post("/api/game", json=invalid, headers=headers).status_code == 400
    invalid = dict(config, bots=[None, "random", "random"], policy="random")
    assert client.post("/api/game", json=invalid, headers=headers).status_code == 400
    invalid = dict(config, bots=None)
    assert client.post("/api/game", json=invalid, headers=headers).status_code == 400


def test_random_layout_options_are_validated_and_recorded_in_web_replay():
    client, token = client_and_token()
    headers = {"X-CSRF-Token": token}
    rules = {
        "randomize_rooms": True, "procedural_map": True, "randomize_doors": True,
        "randomize_passages": True, "passage_count": 4,
    }
    config = {"game_type": "board", "players": 4, "seed": 42, "progress": "step", "board_rules": rules}
    response = client.post("/api/game", json=config, headers=headers)
    assert response.status_code == 201
    initial = response.get_json()
    assert {key: initial["board_rules"][key] for key in rules} == rules
    assert len(initial["board"]["layout"]["passages"]) == 4
    assert client.post("/api/replay/end", json={"confirmed": True}, headers=headers).status_code == 200
    replay = client.get("/api/replay/state?position=0&player=0").get_json()
    assert replay["board"]["layout"] == initial["board"]["layout"]
    response = client.post(
        "/api/game", json={**config, "board_rules": {**rules, "randomize_rooms": False}}, headers=headers,
    )
    assert response.status_code == 400
    assert "procedural" in response.get_json()["error"]
    for bad in (-1, 5, True, 2.5):
        response = client.post(
            "/api/game", json={**config, "board_rules": {**rules, "passage_count": bad}}, headers=headers,
        )
        assert response.status_code == 400
