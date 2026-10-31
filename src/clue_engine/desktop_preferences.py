"""Persistent preferences for the desktop application."""

import json
import os
import tempfile
import threading
from pathlib import Path

from .setup_profiles import validate_setup_profile


class DesktopPreferences:
    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._path = directory / "theme.txt"
        self._profiles_path = directory / "setup-profiles.json"
        self._lock = threading.Lock()

    def get_theme(self) -> str | None:
        with self._lock:
            try:
                theme = self._path.read_text(encoding="utf-8").strip()
            except FileNotFoundError:
                return None
            if theme not in {"light", "dark"}:
                raise ValueError(f"Invalid desktop theme in {self._path}")
            return theme

    def set_theme(self, theme: str) -> None:
        if theme not in {"light", "dark"}:
            raise ValueError("Theme must be light or dark.")
        with self._lock:
            self._directory.mkdir(parents=True, exist_ok=True)
            temporary_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=self._directory, delete=False
                ) as temporary:
                    temporary_path = Path(temporary.name)
                    temporary.write(theme)
                os.replace(temporary_path, self._path)
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)

    def get_profiles(self) -> dict[str, dict]:
        with self._lock:
            try:
                data = json.loads(self._profiles_path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return {}
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid setup profiles in {self._profiles_path}") from exc
            return self._validate_profiles(data)

    def set_profiles(self, profiles: dict[str, dict]) -> None:
        data = {"version": 1, "profiles": profiles}
        self._validate_profiles(data)
        with self._lock:
            self._directory.mkdir(parents=True, exist_ok=True)
            temporary_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=self._directory, delete=False
                ) as temporary:
                    temporary_path = Path(temporary.name)
                    json.dump(data, temporary, ensure_ascii=True)
                os.replace(temporary_path, self._profiles_path)
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _validate_profiles(data: object) -> dict[str, dict]:
        if not isinstance(data, dict) or set(data) != {"version", "profiles"}:
            raise ValueError("Invalid setup profile file.")
        if type(data["version"]) is not int or data["version"] != 1:
            raise ValueError("Unsupported setup profile version.")
        profiles = data["profiles"]
        if not isinstance(profiles, dict) or len(profiles) > 100:
            raise ValueError("Setup profiles must be an object with at most 100 entries.")
        for name, profile in profiles.items():
            if not isinstance(name, str) or not name.strip() or len(name) > 80:
                raise ValueError("Profile names must be between 1 and 80 characters.")
            try:
                validate_setup_profile(profile)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid setup profile {name!r}: {exc}") from exc
        return profiles
