import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from wond.collectors import COLLECTORS, collect_all, collect_recent_files, collect_reminders


class RecentFileCollectorTests(unittest.TestCase):
    def test_recent_files_skip_project_owned_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            watch_root = root / "Documents"
            project = watch_root / "wond"
            data_dir = project / "data"
            build_dir = project / "ios" / "Wond" / "build"
            external = watch_root / "notes.txt"
            for path in [data_dir / "wond.sqlite3-wal", build_dir / "artifact.o", project / "README.md", external]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("changed", encoding="utf-8")
            settings = SimpleNamespace(
                collectors={"recent_files": True},
                limits={"recent_files": 50, "recent_files_scan_files": 1000, "recent_files_scan_seconds": 5},
                watch_paths=[watch_root],
                data_dir=data_dir,
                timezone="Asia/Tokyo",
            )
            now = datetime.now(ZoneInfo("Asia/Tokyo"))

            with patch("wond.collectors.project_root", return_value=project):
                rows = collect_recent_files(settings, now - timedelta(minutes=5), now + timedelta(minutes=5))

        self.assertEqual([row.title for row in rows], ["notes.txt"])
        self.assertEqual(rows[0].source_key, str(external))


class ReminderCollectorTests(unittest.TestCase):
    def reminder_settings(self, limits=None):
        return SimpleNamespace(
            collectors={"reminders": True},
            limits=limits or {},
            timezone="Asia/Tokyo",
        )

    def test_collect_reminders_skips_one_timed_out_list(self):
        start = datetime(2026, 6, 3, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
        end = start + timedelta(days=1)
        settings = self.reminder_settings(
            {
                "reminders_discovery_timeout_seconds": 5,
                "reminders_list_timeout_seconds": 7,
                "reminders_max_lists": 5,
                "reminders_items_per_list": 25,
            }
        )
        calls = []

        def fake_run(args, *, text, capture_output, timeout, check, env):
            calls.append((timeout, dict(env)))
            if len(calls) == 1:
                return subprocess.CompletedProcess(
                    args,
                    0,
                    stdout=json.dumps(
                        [
                            {"index": 0, "id": "slow", "name": "Slow list"},
                            {"index": 1, "id": "ok", "name": "OK list"},
                        ]
                    ),
                    stderr="",
                )
            if env["PC_REMINDERS_LIST_INDEX"] == "0":
                raise subprocess.TimeoutExpired(args, timeout)
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=json.dumps(
                    [
                        {
                            "list": "OK list",
                            "id": "reminder-1",
                            "title": "Submit form",
                            "body": "Bring signed copy",
                            "due": "2026-06-03T01:00:00.000Z",
                            "priority": "5",
                        }
                    ]
                ),
                stderr="",
            )

        with patch("wond.collectors.subprocess.run", side_effect=fake_run):
            rows = collect_reminders(settings, start, end)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].source, "reminders")
        self.assertEqual(rows[0].kind, "task")
        self.assertEqual(rows[0].source_key, "reminder-1")
        self.assertEqual(rows[0].title, "Submit form")
        self.assertEqual(rows[0].subtitle, "OK list")
        self.assertEqual(rows[0].metadata["priority"], "5")
        self.assertEqual([call[0] for call in calls], [5, 7, 7])

    def test_collect_all_reports_reminders_discovery_timeout(self):
        start = datetime(2026, 6, 3, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
        end = start + timedelta(days=1)
        collectors = {name: False for name in COLLECTORS}
        collectors["reminders"] = True
        settings = SimpleNamespace(
            collectors=collectors,
            limits={"reminders_discovery_timeout_seconds": 6},
            timezone="Asia/Tokyo",
        )

        with patch(
            "wond.collectors.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["osascript"], 6),
        ):
            result = collect_all(settings, start, end)

        rows = result["reminders"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].source, "system")
        self.assertEqual(rows[0].kind, "collector_error")
        self.assertEqual(rows[0].title, "reminders failed")
        self.assertIn("reminders timed out after 6s", rows[0].body)
        self.assertEqual(rows[0].metadata["collector"], "reminders")


if __name__ == "__main__":
    unittest.main()
