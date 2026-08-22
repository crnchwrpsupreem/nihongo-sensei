"""Platform-specific defaults shared by the Nihongo Sensei publisher."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Mapping


def default_anki_profile(
    platform: str = sys.platform,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    env = os.environ if environ is None else environ
    user_home = Path.home() if home is None else home
    if platform.startswith("win"):
        appdata = Path(env.get("APPDATA", user_home / "AppData/Roaming"))
        return appdata / "Anki2/User 1"
    if platform.startswith("linux"):
        data_home = Path(env.get("XDG_DATA_HOME", user_home / ".local/share"))
        return data_home / "Anki2/User 1"
    return user_home / "Library/Application Support/Anki2/User 1"


def default_config_file(
    platform: str = sys.platform,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    env = os.environ if environ is None else environ
    user_home = Path.home() if home is None else home
    if platform.startswith("win"):
        appdata = Path(env.get("APPDATA", user_home / "AppData/Roaming"))
        return appdata / "nihongo-sensei/config.env"
    return user_home / ".config/nihongo-sensei/config.env"


def windows_anki_candidates(
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> list[Path]:
    env = os.environ if environ is None else environ
    user_home = Path.home() if home is None else home
    local = Path(env.get("LOCALAPPDATA", user_home / "AppData/Local"))
    return [
        local / "Programs/Anki/anki.exe",
        local / "AnkiProgramFiles/.venv/Scripts/anki.exe",
    ]


def default_anki_command(
    platform: str = sys.platform,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> str:
    if platform.startswith("win"):
        for candidate in windows_anki_candidates(environ, home):
            if candidate.is_file():
                return str(candidate)
        return shutil.which("anki.exe") or shutil.which("anki") or "anki.exe"
    return shutil.which("anki") or "anki"
