#!/usr/bin/env python3
"""Cross-platform Anki sync, extraction, export, validation, and Git publish."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterator

try:
    from .platform_support import default_anki_profile, default_config_file
except ImportError:
    from platform_support import default_anki_profile, default_config_file


REPO_DIR = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-sync", action="store_true")
    parser.add_argument("--no-push", action="store_true")
    parser.add_argument("--config-file", type=Path)
    return parser.parse_args()


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise RuntimeError(f"Invalid config line {number} in {path}")
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if value[:1] in {'\"', "'"} and value[-1:] == value[:1]:
            value = value[1:-1]
        value = os.path.expanduser(os.path.expandvars(value))
        os.environ[name] = value


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(command))
    return subprocess.run(command, cwd=REPO_DIR, text=True, check=check)


def python_command() -> str:
    return sys.executable


@contextlib.contextmanager
def publisher_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    if path.stat().st_size == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("Another Nihongo Sensei publisher run is active") from exc
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError("Another Nihongo Sensei publisher run is active") from exc
        acquired = True
        yield
    finally:
        if acquired and os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        elif acquired:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def main() -> int:
    args = parse_args()
    configured_path = args.config_file or Path(
        os.environ.get("NIHONGO_CONFIG_FILE", default_config_file())
    )
    load_env_file(configured_path.expanduser())

    profile = Path(
        os.environ.get("NIHONGO_ANKI_PROFILE", str(default_anki_profile()))
    ).expanduser()
    deck_root = os.environ.get("NIHONGO_DECK_ROOT", "日本語")
    remote = os.environ.get("NIHONGO_GIT_REMOTE", "origin")
    branch = os.environ.get("NIHONGO_GIT_BRANCH", "main")
    work_dir = REPO_DIR / "work/current-session"
    public_dir = REPO_DIR / "tutor-data/current"
    work_dir.mkdir(parents=True, exist_ok=True)
    public_dir.mkdir(parents=True, exist_ok=True)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

    with publisher_lock(REPO_DIR / "work/publisher.lock"):
        if not args.no_push:
            run(["git", "pull", "--rebase", "--autostash", remote, branch])
        if not args.no_sync:
            run([python_command(), "scripts/sync_anki.py"])
        run(
            [
                python_command(),
                ".agents/skills/nihongo-sensei/scripts/build_session.py",
                "--profile",
                str(profile),
                "--deck-root",
                deck_root,
                "--inclusion-mode",
                "historical",
                "--output-dir",
                str(work_dir),
            ]
        )
        run(
            [
                python_command(),
                "scripts/export_tutor_bundle.py",
                "--corpus",
                str(work_dir / "corpus.json"),
                "--output",
                str(public_dir),
            ]
        )
        run([python_command(), "-m", "unittest", "discover", "-s", "tests", "-v"])

        if args.no_push:
            print("Tutor bundle generated locally; --no-push requested.")
            return 0
        run(["git", "add", "tutor-data/current"])
        staged = run(["git", "diff", "--cached", "--quiet"], check=False)
        if staged.returncode == 0:
            print("Tutor data is already current; nothing to publish.")
            return 0
        if staged.returncode != 1:
            raise RuntimeError("Could not inspect staged tutor-data changes")
        stamp = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        run(["git", "commit", "-m", f"Update public tutor context {stamp}"])
        run(["git", "push", remote, branch])
        print(f"Published fresh tutor context to {remote}/{branch}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Nihongo Sensei publishing failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
