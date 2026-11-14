from pathlib import Path

root = Path(SPECPATH)

a = Analysis(
    [str(root / "tools" / "run_desktop.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=[
        (str(root / "src" / "clue_engine" / "learned_model.json"), "clue_engine"),
        (str(root / "src" / "clue_engine" / "learned_model_3.json"), "clue_engine"),
        (str(root / "src" / "clue_engine" / "learned_model_4.json"), "clue_engine"),
        (str(root / "src" / "clue_engine" / "learned_model_5.json"), "clue_engine"),
        (str(root / "src" / "clue_engine" / "learned_model_6.json"), "clue_engine"),
        (str(root / "src" / "clue_engine" / "opponent_model.json"), "clue_engine"),
        (str(root / "src" / "clue_engine" / "threat_model.json"), "clue_engine"),
        (str(root / "src" / "clue_engine" / "webapp" / "templates"), "clue_engine/webapp/templates"),
        (str(root / "src" / "clue_engine" / "webapp" / "static"), "clue_engine/webapp/static"),
    ],
    hiddenimports=[],
    hookspath=[str(root / "tools" / "pyinstaller_hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ClueEngine",
    console=False,
)
