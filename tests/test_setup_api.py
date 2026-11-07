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
        "bots": [None, "deductive", {"repeat_reveals": True}],
    }
    response = client.post("/api/game", json=config, headers=headers)
    assert response.status_code == 201
    state = response.get_json()
    assert state["board"]["turn_player"] == 1
    assert state["board_rules"] == {
        **config["board_rules"], "early_end": False, "revisit_hallways": False,
        "optional_suggestion": False, "accuse_in_room": False,
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
