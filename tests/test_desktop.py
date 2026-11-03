import re
import socket
import sys
from types import SimpleNamespace
from urllib.request import urlopen

import pytest

from clue_engine import desktop
from clue_engine.desktop_preferences import DesktopPreferences
from clue_engine.webapp import create_app


def test_desktop_theme_persists_across_apps_and_requires_csrf(tmp_path):
    preferences = DesktopPreferences(tmp_path / "settings")
    client = create_app(desktop_preferences=preferences).test_client()
    page = client.get("/")
    assert b"const savedTheme = null;" in page.data
    token = re.search(rb'name="csrf-token" content="([^"]+)"', page.data).group(1).decode()

    assert client.post("/api/desktop/theme", json={"theme": "dark"}).status_code == 403
    headers = {"X-CSRF-Token": token}
    assert client.post("/api/desktop/theme", json={"theme": "blue"}, headers=headers).status_code == 400
    assert preferences.get_theme() is None
    assert client.post("/api/desktop/theme", json={"theme": "dark"}, headers=headers).status_code == 200

    new_app = create_app(desktop_preferences=DesktopPreferences(tmp_path / "settings"))
    assert b'const savedTheme = "dark";' in new_app.test_client().get("/").data
    assert create_app().test_client().post("/api/desktop/theme").status_code == 403


def test_invalid_saved_theme_is_reported(tmp_path):
    (tmp_path / "theme.txt").write_text("blue", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid desktop theme"):
        DesktopPreferences(tmp_path).get_theme()


def test_theme_write_failure_returns_error(tmp_path, monkeypatch):
    preferences = DesktopPreferences(tmp_path)
    client = create_app(desktop_preferences=preferences).test_client()
    page = client.get("/")
    token = re.search(rb'name="csrf-token" content="([^"]+)"', page.data).group(1).decode()

    def fail(_theme):
        raise OSError("disk unavailable")

    monkeypatch.setattr(preferences, "set_theme", fail)
    response = client.post(
        "/api/desktop/theme", json={"theme": "dark"}, headers={"X-CSRF-Token": token}
    )
    assert response.status_code == 500
    assert response.get_json()["error"] == "Could not save the desktop theme."


def test_desktop_profiles_persist_validate_and_require_csrf(tmp_path):
    preferences = DesktopPreferences(tmp_path / "settings")
    client = create_app(desktop_preferences=preferences).test_client()
    page = client.get("/")
    token = re.search(rb'name="csrf-token" content="([^"]+)"', page.data).group(1).decode()
    headers = {"X-CSRF-Token": token}
    profile = {
        "mode": "play", "game_type": "board", "players": 3, "seat": 0,
        "bots": ["random", "deductive", {"repeat_reveals": True}],
        "seat_suspects": [2, 0, 1],
        "board_rules": {
            "move_suspect": False, "move_weapon": False,
            "summoned_suggestion": False, "secret_passages": True,
        },
        "progress": "step", "max_steps": 100, "debug": False,
    }
    assert client.put("/api/desktop/profiles", json={"profiles": {"Game": profile}}).status_code == 403
    response = client.put(
        "/api/desktop/profiles", json={"profiles": {"Game": profile}}, headers=headers
    )
    assert response.status_code == 200
    reloaded = create_app(desktop_preferences=DesktopPreferences(tmp_path / "settings")).test_client()
    assert reloaded.get("/api/desktop/profiles").get_json() == {"profiles": {"Game": profile}}
    invalid = dict(profile, seed=42)
    assert client.put(
        "/api/desktop/profiles", json={"profiles": {"Bad": invalid}}, headers=headers
    ).status_code == 400
    assert preferences.get_profiles() == {"Game": profile}
    for mode in ("manual", "automatic"):
        updated = dict(profile, notebook_mode=mode)
        response = client.put(
            "/api/desktop/profiles", json={"profiles": {"Game": updated}}, headers=headers
        )
        assert response.status_code == 200
        assert reloaded.get("/api/desktop/profiles").get_json() == {"profiles": {"Game": updated}}
    for progress in ("auto", "turn", "step"):
        updated = dict(profile, progress=progress)
        response = client.put(
            "/api/desktop/profiles", json={"profiles": {"Game": updated}}, headers=headers
        )
        assert response.status_code == 200
        assert reloaded.get("/api/desktop/profiles").get_json() == {"profiles": {"Game": updated}}
    invalid_mode = dict(profile, notebook_mode="unknown")
    assert client.put(
        "/api/desktop/profiles", json={"profiles": {"Bad": invalid_mode}}, headers=headers
    ).status_code == 400


@pytest.mark.parametrize("fail", [False, True])
def test_desktop_server_is_local_and_stops_after_window(tmp_path, monkeypatch, fail):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(desktop.sys, "platform", "win32")
    monkeypatch.setattr(desktop, "_require_webview2", lambda: None)
    result = {}

    def create_window(title, url, **kwargs):
        result["url"] = url
        assert title == "Clue Engine"
        assert url.startswith("http://127.0.0.1:")
        assert kwargs["min_size"] == (320, 568)

    def start(**kwargs):
        assert kwargs["gui"] == "edgechromium"
        with urlopen(result["url"], timeout=5) as response:
            assert b"New game" in response.read()
        with urlopen(result["url"] + "static/app.js", timeout=5) as response:
            assert b"renderBoard" in response.read()
        if fail:
            raise RuntimeError("window failed")

    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(create_window=create_window, start=start))
    if fail:
        with pytest.raises(RuntimeError, match="window failed"):
            desktop.run_desktop()
    else:
        desktop.run_desktop()

    port = int(result["url"].split(":")[-1].rstrip("/"))
    with socket.socket() as connection:
        connection.settimeout(1)
        assert connection.connect_ex(("127.0.0.1", port)) != 0


def test_missing_local_app_data_is_reported(monkeypatch):
    monkeypatch.setattr(desktop.sys, "platform", "win32")
    monkeypatch.setattr(desktop, "_require_webview2", lambda: None)
    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace())
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    with pytest.raises(RuntimeError, match="LOCALAPPDATA"):
        desktop.run_desktop()


@pytest.mark.parametrize("reason", [
    "Failed to resolve Python.Runtime.Loader.Initialize",
    "Microsoft Edge WebView2 Runtime was not found.",
])
def test_startup_error_reports_the_actual_cause(monkeypatch, reason):
    messages = []

    def fail():
        raise RuntimeError(reason)

    monkeypatch.setattr(desktop, "run_desktop", fail)
    monkeypatch.setattr(desktop.sys, "platform", "win32")
    monkeypatch.setattr(desktop.ctypes, "windll", SimpleNamespace(
        user32=SimpleNamespace(MessageBoxW=lambda _owner, message, *_args: messages.append(message)),
    ), raising=False)
    with pytest.raises(SystemExit) as exc:
        desktop.main()
    assert exc.value.code == 1
    assert messages == [f"Could not start Clue Engine:\n\n{reason}"]


@pytest.mark.parametrize(
    ("release", "runtime", "error"),
    [(533509, "156.0.0.0", None), (394801, "156.0.0.0", ".NET Framework"),
     (533509, None, "WebView2 Runtime")],
)
def test_required_windows_runtimes(monkeypatch, release, runtime, error):
    class RegistryKey:
        def __init__(self, path):
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def open_key(_root, path, *_args):
        if "EdgeUpdate" in path and runtime is None:
            raise FileNotFoundError(path)
        return RegistryKey(path)

    def query(key, _name):
        return (release if "NET Framework" in key.path else runtime, 0)

    registry = SimpleNamespace(
        HKEY_CURRENT_USER=1, HKEY_LOCAL_MACHINE=2, KEY_WOW64_32KEY=4,
        KEY_WOW64_64KEY=8, KEY_READ=16, OpenKey=open_key, QueryValueEx=query,
    )
    monkeypatch.setitem(sys.modules, "winreg", registry)
    if error:
        with pytest.raises(RuntimeError, match=error):
            desktop._require_webview2()
    else:
        desktop._require_webview2()
