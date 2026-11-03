import runpy
from pathlib import Path
from types import SimpleNamespace

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


def test_desktop_spec_builds_one_self_contained_executable():
    root = Path(__file__).resolve().parents[1]
    analysis = SimpleNamespace(
        pure=object(),
        scripts=object(),
        binaries=object(),
        datas=object(),
    )
    executable = {}

    def make_executable(*args, **kwargs):
        executable["args"] = args
        executable["kwargs"] = kwargs
        return object()

    def reject_collection(*_args, **_kwargs):
        raise AssertionError("The portable executable must not require a separate collection")

    runpy.run_path(str(root / "ClueEngine.spec"), init_globals={
        "SPECPATH": str(root),
        "Analysis": lambda *_args, **_kwargs: analysis,
        "PYZ": lambda *_args, **_kwargs: object(),
        "EXE": make_executable,
        "COLLECT": reject_collection,
    })
    assert analysis.scripts in executable["args"]
    assert analysis.binaries in executable["args"]
    assert analysis.datas in executable["args"]
    assert executable["kwargs"].get("exclude_binaries", False) is False
    assert executable["kwargs"]["console"] is False
