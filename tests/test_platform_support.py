from __future__ import annotations

import importlib.util
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts import platform_support, publish_update


class PlatformSupportTests(unittest.TestCase):
    def test_windows_profile_and_config_defaults(self) -> None:
        env = {
            "APPDATA": "C:/Users/test/AppData/Roaming",
            "LOCALAPPDATA": "C:/Users/test/AppData/Local",
        }
        self.assertEqual(
            platform_support.default_anki_profile("win32", env, Path("C:/Users/test")),
            Path("C:/Users/test/AppData/Roaming/Anki2/User 1"),
        )
        self.assertEqual(
            platform_support.default_config_file("win32", env, Path("C:/Users/test")),
            Path("C:/Users/test/AppData/Roaming/nihongo-sensei/config.env"),
        )

    def test_linux_xdg_profile_default(self) -> None:
        self.assertEqual(
            platform_support.default_anki_profile(
                "linux", {"XDG_DATA_HOME": "/srv/data"}, Path("/home/test")
            ),
            Path("/srv/data/Anki2/User 1"),
        )

    def test_windows_anki_executable_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            local = Path(temporary)
            executable = local / "Programs/Anki/anki.exe"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"")
            actual = platform_support.default_anki_command(
                "win32", {"LOCALAPPDATA": str(local)}, local / "home"
            )
            self.assertEqual(actual, str(executable))

    def test_config_loader_accepts_windows_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "config.env"
            config.write_text(
                'NIHONGO_ANKI_PROFILE="C:/Users/test/AppData/Roaming/Anki2/User 1"\n'
                'NIHONGO_DECK_ROOT="日本語"\n',
                encoding="utf-8",
            )
            old_profile = os.environ.get("NIHONGO_ANKI_PROFILE")
            old_deck = os.environ.get("NIHONGO_DECK_ROOT")
            try:
                publish_update.load_env_file(config)
                self.assertEqual(
                    os.environ["NIHONGO_ANKI_PROFILE"],
                    "C:/Users/test/AppData/Roaming/Anki2/User 1",
                )
                self.assertEqual(os.environ["NIHONGO_DECK_ROOT"], "日本語")
            finally:
                if old_profile is None:
                    os.environ.pop("NIHONGO_ANKI_PROFILE", None)
                else:
                    os.environ["NIHONGO_ANKI_PROFILE"] = old_profile
                if old_deck is None:
                    os.environ.pop("NIHONGO_DECK_ROOT", None)
                else:
                    os.environ["NIHONGO_DECK_ROOT"] = old_deck

    @unittest.skipIf(os.name == "nt", "POSIX lock behavior is tested on POSIX")
    def test_publisher_lock_rejects_overlapping_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock = Path(temporary) / "publisher.lock"
            with publish_update.publisher_lock(lock):
                with self.assertRaisesRegex(RuntimeError, "run is active"):
                    with publish_update.publisher_lock(lock):
                        self.fail("overlapping lock unexpectedly succeeded")

    def test_extractor_has_same_windows_default(self) -> None:
        path = (
            Path(__file__).resolve().parents[1]
            / ".agents/skills/nihongo-sensei/scripts/build_session.py"
        )
        spec = importlib.util.spec_from_file_location("build_session_for_test", path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        actual = module.default_profile_path(
            "win32",
            {"APPDATA": "C:/Users/test/AppData/Roaming"},
            Path("C:/Users/test"),
        )
        self.assertEqual(actual, Path("C:/Users/test/AppData/Roaming/Anki2/User 1"))

        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "collection with space.anki2"
            writable = sqlite3.connect(database)
            writable.execute("CREATE TABLE sample(value TEXT)")
            writable.execute("INSERT INTO sample VALUES ('ok')")
            writable.commit()
            writable.close()
            readonly = module.connect_read_only(database)
            try:
                self.assertEqual(readonly.execute("SELECT value FROM sample").fetchone()[0], "ok")
                with self.assertRaises(sqlite3.OperationalError):
                    readonly.execute("INSERT INTO sample VALUES ('no')")
            finally:
                readonly.close()

    def test_windows_task_and_wrapper_are_present(self) -> None:
        root = Path(__file__).resolve().parents[1]
        task = (root / "scripts/install_windows_task.ps1").read_text(encoding="utf-8")
        wrapper = (root / "scripts/publish_update.ps1").read_text(encoding="utf-8")
        self.assertIn("New-ScheduledTaskTrigger", task)
        self.assertIn("-RepetitionDuration", task)
        self.assertIn("-LogonType Interactive", task)
        self.assertIn("publish_update.py", wrapper)


if __name__ == "__main__":
    unittest.main()
