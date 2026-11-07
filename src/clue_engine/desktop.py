"""Windows desktop launcher for the local web interface."""

import ctypes
import json
import os
import re
import sys
import tempfile
import threading
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

from werkzeug.serving import make_server

from ._version import DESKTOP_VERSION, FRONTEND_VERSION, __version__
from .desktop_preferences import DesktopPreferences
from .webapp import create_app

if TYPE_CHECKING:
    from webview.window import Window


class _DesktopWindowApi:
    def __init__(self) -> None:
        self._window: Window | None = None
        self._fullscreen = False
        self._lock = threading.Lock()

    def _bind_window(self, window: "Window") -> None:
        self._window = window

    def fullscreen_state(self) -> bool:
        with self._lock:
            return self._fullscreen

    def toggle_fullscreen(self) -> bool:
        with self._lock:
            if self._window is None:
                raise RuntimeError("The desktop window is not available.")
            self._window.toggle_fullscreen()
            self._fullscreen = not self._fullscreen
            return self._fullscreen


def _require_webview2() -> None:
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_32KEY,
        ) as key:
            release, _ = winreg.QueryValueEx(key, "Release")
    except FileNotFoundError as exc:
        raise RuntimeError(".NET Framework 4.6.2 or newer is required.") from exc
    if not isinstance(release, int) or release < 394802:
        raise RuntimeError(".NET Framework 4.6.2 or newer is required.")

    key_path = (
        r"SOFTWARE\Microsoft\EdgeUpdate\Clients"
        r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    )
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(root, key_path, 0, winreg.KEY_READ | view) as key:
                    version, _ = winreg.QueryValueEx(key, "pv")
            except FileNotFoundError:
                continue
            if isinstance(version, str) and version not in {"", "0.0.0.0"}:
                return
    raise RuntimeError(
        "Microsoft Edge WebView2 Runtime was not found. Install it from "
        "https://developer.microsoft.com/microsoft-edge/webview2/ and try again."
    )


def run_desktop() -> None:
    if sys.platform != "win32":
        raise RuntimeError("The desktop launcher currently supports Windows only.")
    _require_webview2()
    import webview

    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is not set; desktop preferences cannot be stored.")
    preferences = DesktopPreferences(Path(local_app_data) / "ClueEngine")
    preferences.get_theme()
    server = make_server("127.0.0.1", 0, create_app(desktop_preferences=preferences), threaded=True)
    thread = threading.Thread(target=server.serve_forever, name="clue-desktop-server", daemon=True)
    try:
        thread.start()
        window_api = _DesktopWindowApi()
        window = webview.create_window(
            "Clue Engine",
            f"http://127.0.0.1:{server.server_port}/",
            width=1440,
            height=900,
            min_size=(320, 568),
            js_api=window_api,
        )
        if window is None:
            raise RuntimeError("Could not create the desktop window.")
        window_api._bind_window(window)
        webview.start(gui="edgechromium")
    finally:
        if thread.is_alive():
            server.shutdown()
            thread.join()
        server.server_close()


def _release_self_check() -> dict[str, object]:
    if getattr(sys, "frozen", False):
        import webview

        if not callable(webview.create_window):
            raise RuntimeError("The bundled desktop window backend is unavailable")
    with tempfile.TemporaryDirectory(prefix="clue-self-check-") as directory:
        app = create_app(desktop_preferences=DesktopPreferences(Path(directory)))
        client = app.test_client()
        page = client.get("/")
        if page.status_code != 200:
            raise RuntimeError(f"Desktop page returned HTTP {page.status_code}")
        for label, version in (
            ("Game API", __version__), ("App", FRONTEND_VERSION), ("Desktop", DESKTOP_VERSION)
        ):
            if f"{label} {version}".encode() not in page.data:
                raise RuntimeError(f"Desktop page is missing {label} version {version}")
        for asset in ("app.js", "setup.js", "style.css"):
            if client.get(f"/static/{asset}").status_code != 200:
                raise RuntimeError(f"Desktop asset is missing: {asset}")
        token = re.search(rb'name="csrf-token" content="([^"]+)"', page.data)
        if token is None:
            raise RuntimeError("Desktop page is missing its CSRF token")
        headers = {"X-CSRF-Token": token.group(1).decode()}
        response = client.post("/api/game", json={
            "mode": "play", "players": 4, "seat": 0, "seed": 42,
            "policy": "deductive", "progress": "step", "max_steps": 100,
        }, headers=headers)
        if response.status_code != 201:
            raise RuntimeError(f"Could not start a self-check game: HTTP {response.status_code}")
        response = client.post("/api/action", json={
            "action": "suggest", "suspect_id": 0, "weapon_id": 6, "room_id": 12,
        }, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"Self-check game action failed: HTTP {response.status_code}")
    return {
        "status": "ok",
        "versions": {"api": __version__, "app": FRONTEND_VERSION, "desktop": DESKTOP_VERSION},
    }


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--release-self-check":
        if len(sys.argv) != 3:
            raise SystemExit("--release-self-check requires an output file")
        path = Path(sys.argv[2])
        try:
            result = _release_self_check()
        except Exception as exc:
            with path.open("x", encoding="utf-8") as output:
                json.dump({"status": "error", "traceback": traceback.format_exc()}, output)
            raise SystemExit(1) from exc
        with path.open("x", encoding="utf-8") as output:
            json.dump(result, output)
        return
    try:
        run_desktop()
    except Exception as exc:
        message = f"Could not start Clue Engine:\n\n{exc}"
        if sys.platform == "win32":
            ctypes.windll.user32.MessageBoxW(None, message, "Clue Engine", 0x10)
        else:
            print(message, file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
