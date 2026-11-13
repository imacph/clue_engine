import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from tools import release, versioning


def next_patch(version):
    major, minor, patch = (int(part) for part in version.split("."))
    return f"{major}.{minor}.{patch + 1}"


@pytest.fixture
def release_tree(tmp_path):
    root = Path(__file__).resolve().parents[1]
    for relative in (versioning.VERSION_PATH, Path("README.md"), Path("CHANGELOG.md")):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / relative, target)
    versions = versioning.read_versions(tmp_path)
    (tmp_path / "CHANGELOG.md").write_text(
        f"# Changelog\n\n{versions.heading('Unreleased')}\n\n### Changed\n\n- Example.\n",
        encoding="utf-8",
    )
    return tmp_path


def test_current_version_files_are_consistent():
    versions = versioning.check()
    assert versions.tag == (
        f"desktop-{versions.desktop}-app-{versions.app}-api-{versions.api}"
    )


def test_update_and_finalize_versions(release_tree):
    old = versioning.check(release_tree)
    new = versioning.Versions(old.api, old.app, next_patch(old.desktop))
    versioning.set_versions(release_tree, new)
    assert versioning.check(release_tree) == new
    with pytest.raises(ValueError, match="dated changelog"):
        versioning.check(release_tree, require_release=True)
    versioning.finalize(release_tree, "2026-11-06")
    assert versioning.check(release_tree, require_release=True) == new
    changelog = (release_tree / "CHANGELOG.md").read_text(encoding="utf-8")
    assert new.heading("2026-11-06") in changelog
    next_versions = versioning.Versions(next_patch(new.api), new.app, new.desktop)
    versioning.set_versions(release_tree, next_versions)
    changelog = (release_tree / "CHANGELOG.md").read_text(encoding="utf-8")
    assert changelog.index(next_versions.heading("Unreleased")) < changelog.index(
        new.heading("2026-11-06")
    )
    assert versioning.check(release_tree) == next_versions


def test_version_drift_and_invalid_inputs_are_rejected(release_tree):
    readme = release_tree / "README.md"
    current = versioning.read_versions(release_tree)
    readme.write_text(readme.read_text(encoding="utf-8").replace(
        f"**{current.api}**", "**not-a-version**"), encoding="utf-8")
    with pytest.raises(ValueError, match="README component versions"):
        versioning.check(release_tree)
    with pytest.raises(ValueError, match="Invalid component version"):
        versioning.Versions("01.0.0", "1.0.0", "1.0.0")
    with pytest.raises(ValueError, match="Invalid release date"):
        versioning.finalize(release_tree, "2026-02-30")


def test_finalize_rejects_empty_notes(release_tree):
    versions = versioning.check(release_tree)
    changelog = release_tree / "CHANGELOG.md"
    changelog.write_text(f"# Changelog\n\n{versions.heading('Unreleased')}\n\n### Changed\n",
                         encoding="utf-8")
    with pytest.raises(ValueError, match="with notes"):
        versioning.finalize(release_tree, "2026-11-06")


def test_version_update_rejects_bad_assignment_without_writing(release_tree):
    path = release_tree / versioning.VERSION_PATH
    original = path.read_text(encoding="utf-8")
    current = versioning.read_versions(release_tree)
    path.write_text(original.replace(f'__version__ = "{current.api}"',
                                     f'__version__ = ("{current.api}")'),
                    encoding="utf-8")
    original_readme = (release_tree / "README.md").read_bytes()
    with pytest.raises(ValueError, match="Cannot safely update"):
        versioning.set_versions(release_tree, versioning.Versions(next_patch(current.api), current.app,
                                                                 current.desktop))
    assert (release_tree / "README.md").read_bytes() == original_readme


def test_release_requires_matching_tag_and_clean_checkout(monkeypatch):
    versions = versioning.Versions("1.2.3", "2.3.4", "3.4.5")
    with pytest.raises(ValueError, match="does not match"):
        release.verify_checkout("wrong", versions)

    def fake_command(args, **_kwargs):
        output = "changed file\n" if args[1] == "status" else "abc\n"
        return subprocess.CompletedProcess(args, 0, stdout=output)

    monkeypatch.setattr(release, "command", fake_command)
    with pytest.raises(ValueError, match="clean working tree"):
        release.verify_checkout(versions.tag, versions)

    def different_tag(args, **_kwargs):
        output = "" if args[1] == "status" else ("tag\n" if "--verify" in args else "head\n")
        return subprocess.CompletedProcess(args, 0, stdout=output)

    monkeypatch.setattr(release, "command", different_tag)
    with pytest.raises(ValueError, match="does not point"):
        release.verify_checkout(versions.tag, versions)


def test_release_archive_manifest_checksum_and_no_overwrite(tmp_path):
    executable = tmp_path / "source.exe"
    executable.write_bytes(b"portable executable")
    versions = versioning.Versions("1.2.3", "2.3.4", "3.4.5")
    output = release.create_artifacts(executable, tmp_path / "releases", versions,
                                      "a" * 40, {"pyinstaller": "6.0"}, "v22.20.0", "Notes\n")
    archive = next(output.glob("*.zip"))
    checksum = (output / f"{archive.name}.sha256").read_text(encoding="ascii")
    assert checksum == f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n"
    manifest = json.loads((output / "release-manifest.json").read_text(encoding="utf-8"))
    assert manifest["versions"] == {"api": "1.2.3", "app": "2.3.4", "desktop": "3.4.5"}
    assert manifest["commit"] == "a" * 40
    assert manifest["executable"]["sha256"] == hashlib.sha256(executable.read_bytes()).hexdigest()
    with zipfile.ZipFile(archive) as bundle:
        assert set(bundle.namelist()) == {"ClueEngine.exe", "release-manifest.json"}
        assert bundle.read("ClueEngine.exe") == executable.read_bytes()
        assert json.loads(bundle.read("release-manifest.json")) == manifest
    with pytest.raises(FileExistsError):
        release.create_artifacts(executable, tmp_path / "releases", versions,
                                 "b" * 40, {}, "v22.20.0", "Notes\n")
    assert json.loads((output / "release-manifest.json").read_text()) == manifest


def test_wheel_verification_requires_version_and_web_assets(tmp_path):
    versions = versioning.Versions("1.2.3", "2.3.4", "3.4.5")
    wheel = tmp_path / "test.whl"
    assets = (
        "clue_engine/learned_model.json",
        "clue_engine/opponent_model.json",
        "clue_engine/threat_model.json",
        "clue_engine/webapp/templates/index.html",
        "clue_engine/webapp/static/app.js",
        "clue_engine/webapp/static/setup.js",
        "clue_engine/webapp/static/style.css",
    )
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("clue_engine-1.2.3.dist-info/METADATA",
                         "Name: clue-engine\nVersion: 1.2.3\n")
        for asset in assets:
            archive.writestr(asset, "asset")
    release.verify_wheel(tmp_path, versions)
    with pytest.raises(ValueError, match="does not match"):
        release.verify_wheel(tmp_path, versioning.Versions("1.2.4", "2.3.4", "3.4.5"))
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("clue_engine-1.2.3.dist-info/METADATA",
                         "Name: clue-engine\nVersion: 1.2.3\n")
    with pytest.raises(ValueError, match="missing package assets"):
        release.verify_wheel(tmp_path, versions)


def test_packaged_self_check_rejects_wrong_versions(tmp_path, monkeypatch):
    versions = versioning.Versions("1.2.3", "2.3.4", "3.4.5")
    output = tmp_path / "result.json"

    def fake_command(args, **_kwargs):
        output.write_text(json.dumps({"status": "ok", "versions": {}}), encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(release, "command", fake_command)
    with pytest.raises(ValueError, match="unexpected self-check data"):
        release.self_check(tmp_path / "app.exe", output, versions)
