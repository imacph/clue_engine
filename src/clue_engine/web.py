"""Local browser interface entry point."""

import argparse
import threading
import webbrowser

from .webapp import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Clue Engine local web app.")
    parser.add_argument("--port", type=int, default=8765, help="local HTTP port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    url = f"http://127.0.0.1:{args.port}"
    print(f"Clue Engine is available at {url} (Ctrl+C to stop).")
    if not args.no_browser:
        threading.Timer(0.7, webbrowser.open, args=(url,)).start()
    create_app().run(host="127.0.0.1", port=args.port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
