"""Update and validate the independently versioned release components."""

import argparse
import ast
import datetime
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_PATH = Path("src/clue_engine/_version.py")
START = "<!-- component-versions:start -->"
END = "<!-- component-versions:end -->"
VERSION_RE = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\Z")
HEADING_RE = re.compile(r"^## (.+)$", re.MULTILINE)


@dataclass(frozen=True)
class Versions:
    api: str
    app: str
    desktop: str

    def __post_init__(self):
        for value in (self.api, self.app, self.desktop):
            if not VERSION_RE.fullmatch(value):
                raise ValueError(f"Invalid component version: {value!r}")

    @property
    def tag(self):
        return f"desktop-{self.desktop}-app-{self.app}-api-{self.api}"

    def heading(self, status):
        return f"## Desktop {self.desktop} / App {self.app} / API {self.api} - {status}"


def read_versions(root=ROOT):
    tree = ast.parse((root / VERSION_PATH).read_text(encoding="utf-8"))
    names = {"__version__": "api", "FRONTEND_VERSION": "app", "DESKTOP_VERSION": "desktop"}
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in names:
                    if target.id in values or not isinstance(node.value, ast.Constant):
                        raise ValueError(f"Invalid or duplicate version assignment: {target.id}")
                    if not isinstance(node.value.value, str):
                        raise ValueError(f"Version must be a string: {target.id}")
                    values[target.id] = node.value.value
    if values.keys() != names.keys():
        raise ValueError("Version file must define all three component versions")
    return Versions(**{names[name]: value for name, value in values.items()})


def readme_block(versions):
    return (
        f"{START}\n"
        f"The game API and Python distribution are **{versions.api}**, the shared browser/desktop\n"
        f"frontend is **{versions.app}**, and the Windows desktop wrapper is "
        f"**{versions.desktop}**.\n"
        f"{END}"
    )


def replace_readme_block(text, versions):
    if text.count(START) != 1 or text.count(END) != 1 or text.index(START) > text.index(END):
        raise ValueError("README must contain exactly one ordered pair of version markers")
    start = text.index(START)
    end = text.index(END) + len(END)
    return text[:start] + readme_block(versions) + text[end:]


def changelog_status(text, versions):
    match = HEADING_RE.search(text)
    if not match:
        raise ValueError("Changelog has no version heading")
    heading = match.group()
    prefix = versions.heading("")
    if not heading.startswith(prefix):
        raise ValueError(f"Latest changelog heading must start with {prefix!r}")
    status = heading[len(prefix):]
    if status != "Unreleased":
        try:
            if datetime.date.fromisoformat(status).isoformat() != status:
                raise ValueError
        except ValueError as exc:
            raise ValueError(f"Invalid changelog release date: {status!r}") from exc
    next_heading = HEADING_RE.search(text, match.end())
    body = text[match.end():next_heading.start() if next_heading else len(text)]
    return match, status, body


def has_notes(body):
    return any(line.strip() and not line.lstrip().startswith("#") for line in body.splitlines())


def check(root=ROOT, require_release=False):
    versions = read_versions(root)
    readme = (root / "README.md").read_text(encoding="utf-8")
    if replace_readme_block(readme, versions) != readme:
        raise ValueError("README component versions are out of date")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    _, status, body = changelog_status(changelog, versions)
    if require_release and (status == "Unreleased" or not has_notes(body)):
        raise ValueError("Release requires a dated changelog entry with notes")
    return versions


def set_versions(root, versions):
    old = check(root)
    if old == versions:
        raise ValueError("No component version changed")
    version_path = root / VERSION_PATH
    version_text = version_path.read_text(encoding="utf-8")
    for name, value in (
        ("__version__", versions.api),
        ("FRONTEND_VERSION", versions.app),
        ("DESKTOP_VERSION", versions.desktop),
    ):
        version_text, count = re.subn(
            rf'^{name}[ \t]*=[ \t]*["\'][^"\']*["\'][ \t]*$',
            f'{name} = "{value}"',
            version_text,
            flags=re.MULTILINE,
        )
        if count != 1:
            raise ValueError(f"Cannot safely update {name}")
    readme_path = root / "README.md"
    readme = replace_readme_block(readme_path.read_text(encoding="utf-8"), versions)
    changelog_path = root / "CHANGELOG.md"
    changelog = changelog_path.read_text(encoding="utf-8")
    match, status, _ = changelog_status(changelog, old)
    heading = versions.heading("Unreleased")
    if status == "Unreleased":
        changelog = changelog[:match.start()] + heading + changelog[match.end():]
    else:
        changelog = changelog[:match.start()] + heading + "\n\n" + changelog[match.start():]
    version_path.write_text(version_text, encoding="utf-8")
    readme_path.write_text(readme, encoding="utf-8")
    changelog_path.write_text(changelog, encoding="utf-8")


def finalize(root, date):
    try:
        if datetime.date.fromisoformat(date).isoformat() != date:
            raise ValueError
    except ValueError as exc:
        raise ValueError(f"Invalid release date: {date!r}") from exc
    versions = check(root)
    path = root / "CHANGELOG.md"
    text = path.read_text(encoding="utf-8")
    match, status, body = changelog_status(text, versions)
    if status != "Unreleased" or not has_notes(body):
        raise ValueError("An unreleased changelog entry with notes is required")
    path.write_text(text[:match.start()] + versions.heading(date) + text[match.end():],
                    encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    check_parser = subparsers.add_parser("check")
    check_parser.add_argument("--release", action="store_true")
    set_parser = subparsers.add_parser("set")
    for component in ("api", "app", "desktop"):
        set_parser.add_argument(f"--{component}")
    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("--date", required=True, help="Release date in YYYY-MM-DD format")
    args = parser.parse_args()
    try:
        if args.command == "set":
            old = check()
            set_versions(ROOT, Versions(
                old.api if args.api is None else args.api,
                old.app if args.app is None else args.app,
                old.desktop if args.desktop is None else args.desktop,
            ))
        elif args.command == "finalize":
            finalize(ROOT, args.date)
        else:
            versions = check(require_release=args.release)
            print(f"Versions are consistent: {versions.tag}")
    except (OSError, SyntaxError, ValueError) as exc:
        parser.exit(1, f"Version check failed: {exc}\n")


if __name__ == "__main__":
    main()
