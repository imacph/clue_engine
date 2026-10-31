"""Windows desktop launcher for the local web interface."""

import ctypes
import os
import sys
import threading
from pathlib import Path

from werkzeug.serving import make_server

from .desktop_preferences import DesktopPreferences
from .webapp import create_app


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
        webview.create_window(
            "Clue Engine",
            f"http://127.0.0.1:{server.server_port}/",
            width=1440,
            height=900,
            min_size=(320, 568),
        )
        webview.start(gui="edgechromium")
    finally:
        if thread.is_alive():
            server.shutdown()
            thread.join()
        server.server_close()


def main() -> None:
    try:
        run_desktop()
    except Exception as exc:
        message = (
            f"Could not start Clue Engine:\n\n{exc}\n\n"
            "The Windows desktop app requires the Microsoft Edge WebView2 Runtime."
        )
        if sys.platform == "win32":
            ctypes.windll.user32.MessageBoxW(None, message, "Clue Engine", 0x10)
        else:
            print(message, file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
