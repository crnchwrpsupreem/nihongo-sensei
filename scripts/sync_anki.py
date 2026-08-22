#!/usr/bin/env python3
"""Synchronize Anki through a local AnkiConnect instance, then close Anki."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    from .platform_support import default_anki_command
except ImportError:
    from platform_support import default_anki_command


ANKI_CONNECT_URL = os.environ.get(
    "NIHONGO_ANKI_CONNECT_URL", "http://127.0.0.1:8765"
)
TIMEOUT_SECONDS = int(os.environ.get("NIHONGO_SYNC_TIMEOUT", "300"))
PROFILE_NAME = os.environ.get("NIHONGO_ANKI_PROFILE_NAME", "User 1")
ANKI_BASE = os.environ.get("NIHONGO_ANKI_BASE", "")


class SyncError(RuntimeError):
    pass


def anki_action(action: str, **params: Any) -> Any:
    body = json.dumps(
        {"action": action, "version": 6, "params": params},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        ANKI_CONNECT_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("error"):
        raise SyncError(f"AnkiConnect {action!r} failed: {payload['error']}")
    return payload.get("result")


def is_ready() -> bool:
    try:
        return int(anki_action("version")) >= 6
    except (OSError, ValueError, TypeError, urllib.error.URLError, SyncError):
        return False


def start_anki() -> subprocess.Popen[bytes]:
    configured = os.environ.get("NIHONGO_ANKI_COMMAND", default_anki_command())
    expanded = str(Path(configured).expanduser())
    if Path(expanded).is_file():
        command = [expanded]
    else:
        command = shlex.split(configured, posix=os.name != "nt")
    if not command:
        raise SyncError("NIHONGO_ANKI_COMMAND is empty")
    if os.name != "nt" and not os.environ.get("DISPLAY") and shutil.which("xvfb-run"):
        command = ["xvfb-run", "-a", *command]
    if ANKI_BASE:
        command.extend(["-b", str(Path(ANKI_BASE).expanduser())])
    command.extend(["-p", PROFILE_NAME])
    try:
        return subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise SyncError(f"Could not start Anki: {exc}") from exc


def wait_until_ready(process: subprocess.Popen[bytes] | None) -> None:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if is_ready():
            return
        if process and process.poll() is not None and os.name != "nt":
            raise SyncError(f"Anki exited before AnkiConnect became ready ({process.returncode})")
        time.sleep(1)
    raise SyncError(
        "Timed out waiting for AnkiConnect. Install add-on 2055492159 and confirm "
        "that Anki can open this profile."
    )


def run_custom_sync(command_text: str) -> None:
    expanded = str(Path(command_text).expanduser())
    command = (
        [expanded]
        if Path(expanded).is_file()
        else shlex.split(command_text, posix=os.name != "nt")
    )
    if not command:
        raise SyncError("NIHONGO_SYNC_COMMAND is empty")
    result = subprocess.run(command, check=False, timeout=TIMEOUT_SECONDS)
    if result.returncode:
        raise SyncError(f"Custom sync command exited with {result.returncode}")


def request_windows_clean_close(platform_name: str | None = None) -> bool:
    """Ask Anki's main Windows window to close without terminating the process."""
    if (platform_name or os.name) != "nt":
        return False
    script = (
        "$closed = $false; "
        "Get-Process -Name anki -ErrorAction SilentlyContinue | ForEach-Object { "
        "if ($_.CloseMainWindow()) { $closed = $true } }; "
        "if ($closed) { exit 0 } else { exit 1 }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def wait_until_closed(timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while is_ready() and time.monotonic() < deadline:
        time.sleep(0.5)
    return not is_ready()


def main() -> int:
    custom = os.environ.get("NIHONGO_SYNC_COMMAND")
    if custom:
        run_custom_sync(custom)
        print("Custom Anki sync command completed.")
        return 0

    process: subprocess.Popen[bytes] | None = None
    if not is_ready():
        process = start_anki()
    wait_until_ready(process)
    print("Anki is ready; starting AnkiWeb sync.")
    anki_action("sync")
    print("AnkiWeb sync completed.")

    should_close = os.environ.get("NIHONGO_CLOSE_ANKI_AFTER_SYNC", "true").lower()
    if should_close not in {"0", "false", "no"}:
        try:
            anki_action("guiExitAnki")
        except (ConnectionError, urllib.error.URLError):
            # Anki may close its local HTTP server before the response completes.
            pass
        closed = wait_until_closed(10)
        if not closed and request_windows_clean_close():
            closed = wait_until_closed(30)
        if not closed:
            raise SyncError("AnkiConnect is still reachable; Anki did not close")
        print("Anki closed cleanly.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, SyncError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"Anki synchronization failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
