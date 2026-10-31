import runpy
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("modern_parser", "expected"),
    [
        (False, ["pycparser.lextab", "pycparser.yacctab"]),
        (True, []),
    ],
)
def test_pycparser_hook_preserves_legacy_tables(monkeypatch, modern_parser, expected):
    hooks = pytest.importorskip("PyInstaller.utils.hooks")

    def check_requirement(requirement):
        assert requirement == "pycparser >= 3"
        return modern_parser

    monkeypatch.setattr(hooks, "check_requirement", check_requirement)
    hook = Path(__file__).resolve().parents[1] / "tools" / "pyinstaller_hooks" / "hook-pycparser.py"
    assert runpy.run_path(str(hook))["hiddenimports"] == expected
