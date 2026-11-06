"""Build a verified, versioned Windows portable release from a clean Git tag."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import zipfile
from datetime import UTC, datetime
from email.parser import BytesParser
from pathlib import Path

from tools.versioning import ROOT, changelog_status, check

REQUIREMENTS = ROOT / "tools" / "release-requirements.txt"


def command(args, *, cwd=ROOT, env=None, capture=False, timeout=None):
    return subprocess.run(
        args, cwd=cwd, env=env, capture_output=capture, text=True, check=True, timeout=timeout
    )


def pinned_dependencies(path=REQUIREMENTS):
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)", line)
        if not match:
            raise ValueError(f"Expected an exact dependency pin: {line!r}")
        name, expected = match.groups()
        try:
            installed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise ValueError(f"Required release dependency is not installed: {name}") from exc
        if installed != expected:
            raise ValueError(f"{name} must be {expected}, found {installed}")
        result[name] = installed
    if not result:
        raise ValueError("Release dependency list is empty")
    return result


def verify_checkout(tag, versions):
    if tag != versions.tag:
        raise ValueError(f"Tag {tag!r} does not match component versions: {versions.tag}")
    status = command(["git", "status", "--porcelain", "--untracked-files=normal"],
                     capture=True).stdout
    if status:
        raise ValueError("Release builds require a clean working tree")
    head = command(["git", "rev-parse", "HEAD"], capture=True).stdout.strip()
    tagged = command(["git", "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}"],
                     capture=True).stdout.strip()
    if head != tagged:
        raise ValueError(f"Tag {tag} does not point to the checked-out commit")
    return head


def check_environment():
    if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise ValueError("The release build requires 64-bit Windows")
    if sys.version_info[:3] != (3, 13, 3) or platform.architecture()[0] != "64bit":
        raise ValueError("The release build requires 64-bit CPython 3.13.3")
    if platform.python_implementation() != "CPython":
        raise ValueError("The release build requires CPython")
    node = command(["node", "--version"], capture=True).stdout.strip()
    match = re.fullmatch(r"v(\d+)\.\d+\.\d+", node)
    if not match or int(match.group(1)) < 18:
        raise ValueError(f"Node.js 18 or newer is required, found {node!r}")
    command([sys.executable, "-m", "pip", "check"])
    return node, pinned_dependencies()


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def self_check(executable, output, versions):
    try:
        result = command([str(executable), "--release-self-check", str(output)],
                         capture=True, timeout=120)
    except subprocess.CalledProcessError as exc:
        detail = output.read_text(encoding="utf-8") if output.exists() else exc.stderr
        raise ValueError(f"Packaged executable self-check failed: {detail}") from exc
    if result.stdout or result.stderr:
        print(result.stdout + result.stderr, end="")
    data = json.loads(output.read_text(encoding="utf-8"))
    expected = {"api": versions.api, "app": versions.app, "desktop": versions.desktop}
    if data != {"status": "ok", "versions": expected}:
        raise ValueError(f"Packaged executable reported unexpected self-check data: {data}")


def verify_wheel(directory, versions):
    wheels = list(directory.glob("*.whl"))
    if len(wheels) != 1:
        raise ValueError(f"Expected one Python wheel, found {len(wheels)}")
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())
        metadata = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata) != 1:
            raise ValueError("Python wheel must contain exactly one metadata file")
        message = BytesParser().parsebytes(wheel.read(metadata[0]))
        if message["Name"] != "clue-engine" or message["Version"] != versions.api:
            raise ValueError("Python wheel metadata does not match the API version")
        required = {
            "clue_engine/webapp/templates/index.html",
            "clue_engine/webapp/static/app.js",
            "clue_engine/webapp/static/setup.js",
            "clue_engine/webapp/static/style.css",
        }
        missing = required - names
        if missing:
            raise ValueError(f"Python wheel is missing web assets: {sorted(missing)}")


def create_artifacts(executable, destination_root, versions, commit, dependencies, node, notes):
    destination_root.mkdir(parents=True, exist_ok=True)
    destination = destination_root / versions.tag
    if destination.exists():
        raise FileExistsError(f"Release artifact directory already exists: {destination}")
    name = f"ClueEngine-{versions.tag}-windows-x64-portable.zip"
    manifest = {
        "tag": versions.tag,
        "commit": commit,
        "versions": {"api": versions.api, "app": versions.app, "desktop": versions.desktop},
        "target": "windows-x64",
        "python": platform.python_version(),
        "node": node,
        "dependencies": dependencies,
        "built_utc": datetime.now(UTC).isoformat(),
        "executable": {"name": "ClueEngine.exe", "sha256": sha256(executable)},
        "prerequisites": ["Microsoft Edge WebView2 Runtime", ".NET Framework 4.6.2 or newer"],
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with tempfile.TemporaryDirectory(prefix=".release-", dir=destination_root) as directory:
        stage = Path(directory) / "artifacts"
        stage.mkdir()
        archive = stage / name
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.write(executable, "ClueEngine.exe")
            bundle.writestr("release-manifest.json", manifest_bytes)
        (stage / "release-manifest.json").write_bytes(manifest_bytes)
        (stage / "release-notes.md").write_text(notes, encoding="utf-8")
        (stage / f"{name}.sha256").write_text(
            f"{sha256(archive)}  {name}\n", encoding="ascii"
        )
        os.rename(stage, destination)
    return destination


def build(tag):
    versions = check(require_release=True)
    commit = verify_checkout(tag, versions)
    node, dependencies = check_environment()
    output = ROOT / "dist" / "releases"
    if (output / tag).exists():
        raise FileExistsError(f"Release artifact directory already exists: {output / tag}")
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "src"), str(ROOT), env.get("PYTHONPATH", "")]
    )
    command([sys.executable, "-m", "pytest", "-q"], env=env)
    command([sys.executable, "-m", "ruff", "check", "."], env=env)
    with tempfile.TemporaryDirectory(prefix="clue-portable-build-") as directory:
        temporary = Path(directory)
        env["PYINSTALLER_CONFIG_DIR"] = str(temporary / "pyinstaller-cache")
        wheel_dir = temporary / "wheel"
        command([sys.executable, "-m", "build", "--wheel", "--no-isolation",
                 "--outdir", str(wheel_dir)], env=env)
        verify_wheel(wheel_dir, versions)
        command([
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--distpath", str(temporary / "dist"), "--workpath", str(temporary / "build"),
            str(ROOT / "ClueEngine.spec"),
        ], env=env)
        executable = temporary / "dist" / "ClueEngine.exe"
        self_check(executable, temporary / "self-check.json", versions)
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        heading, _, body = changelog_status(changelog, versions)
        notes = f"{heading.group()}\n{body.strip()}\n"
        result = create_artifacts(executable, output, versions, commit, dependencies, node, notes)
    print(f"Release artifacts created in {result}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="Existing tag matching all component versions")
    args = parser.parse_args()
    try:
        build(args.tag)
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr or exc.stdout or ""
        parser.exit(1, f"Release build failed: {exc}\n{detail}")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Release build failed: {exc}\n")


if __name__ == "__main__":
    main()
