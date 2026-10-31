import re
import tomllib
from pathlib import Path

import clue_engine
from clue_engine._version import DESKTOP_VERSION, FRONTEND_VERSION, __version__
from clue_engine.desktop_preferences import DesktopPreferences
from clue_engine.webapp import create_app


def test_versions_are_semantic_and_package_uses_api_version():
    assert clue_engine.__version__ == __version__ == "0.3.0"
    assert FRONTEND_VERSION == "0.2.1"
    assert DESKTOP_VERSION == "0.2.1"
    assert all(re.fullmatch(r"\d+\.\d+\.\d+", version) for version in (
        __version__, FRONTEND_VERSION, DESKTOP_VERSION
    ))
    project_file = Path(__file__).resolve().parents[1] / "pyproject.toml"
    project = tomllib.loads(project_file.read_text(encoding="utf-8"))
    assert "version" in project["project"]["dynamic"]
    assert project["tool"]["hatch"]["version"]["path"] == "src/clue_engine/_version.py"


def test_versions_in_web_and_desktop_pages(tmp_path):
    browser_page = create_app().test_client().get("/").get_data(as_text=True)
    assert f"Game API {__version__}" in browser_page
    assert f"App {FRONTEND_VERSION}" in browser_page
    assert f"Desktop {DESKTOP_VERSION}" not in browser_page

    app = create_app(desktop_preferences=DesktopPreferences(tmp_path))
    desktop_page = app.test_client().get("/").get_data(as_text=True)
    assert f"Game API {__version__}" in desktop_page
    assert f"App {FRONTEND_VERSION}" in desktop_page
    assert f"Desktop {DESKTOP_VERSION}" in desktop_page
