import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import wond.dashboard as dashboard
from wond.dashboard import api_ask
from wond.store import Observation, Store


def settings_for(root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        path=root / "config.json",
        db_path=root / "context.sqlite3",
        timezone="Asia/Tokyo",
        data_dir=root / "data",
        report_dir=root / "data" / "reports",
        summary_dir=root / "data" / "summaries",
        local_ai={},
        audio_analysis={},
    )


class DashboardAskTimeContextTests(unittest.TestCase):
    def setUp(self):
        self.original_now = dashboard.now
        self.original_semantic_search = dashboard.semantic_search
        self.original_ollama_generate = dashboard.ollama_generate
        dashboard.now = lambda tz: datetime(2026, 6, 1, 12, 34, 56, tzinfo=ZoneInfo(tz))
        dashboard.semantic_search = lambda *args, **kwargs: {
            "status": "unavailable",
            "mode": "test",
            "model": "",
            "items": [],
            "indexed": 0,
        }

    def tearDown(self):
        dashboard.now = self.original_now
        dashboard.semantic_search = self.original_semantic_search
        dashboard.ollama_generate = self.original_ollama_generate

    def test_ask_injects_current_time_and_resolves_yesterday_for_retrieval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = settings_for(root)
            settings.report_dir.mkdir(parents=True)
            (settings.summary_dir / "daily").mkdir(parents=True)
            store = Store(settings.db_path)
            try:
                store.upsert_observations(
                    [
                        Observation(
                            source="mobile",
                            kind="audio_segment",
                            source_key="today",
                            observed_at="2026-06-01T09:00:00+09:00",
                            title="today item",
                            body="today-only note",
                        ),
                        Observation(
                            source="mobile",
                            kind="audio_segment",
                            source_key="yesterday",
                            observed_at="2026-05-31T09:00:00+09:00",
                            title="yesterday item",
                            body="yesterday-only note",
                        ),
                    ]
                )
            finally:
                store.close()

            captured = {}

            def fake_generate(_settings, prompt, *, model):
                captured["prompt"] = prompt
                captured["model"] = model
                return "ok"

            dashboard.ollama_generate = fake_generate

            payload = api_ask(settings, {"question": "昨天我做了什么？"})

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["answer"], "ok")
            self.assertIn("今天 = 2026-06-01", captured["prompt"])
            self.assertIn("昨天 = 2026-05-31", captured["prompt"])
            self.assertIn("yesterday-only note", captured["prompt"])
            self.assertNotIn("today-only note", captured["prompt"])
            self.assertEqual(payload["time_context"]["today"], "2026-06-01 (周一)")
            self.assertEqual(payload["citations"][0]["date_context"], "昨天=2026-05-31")

    def test_empty_relative_question_reports_resolved_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = settings_for(root)
            settings.report_dir.mkdir(parents=True)
            (settings.summary_dir / "daily").mkdir(parents=True)
            Store(settings.db_path).close()

            payload = api_ask(settings, {"question": "昨天有什么记录？"})

            self.assertTrue(payload["ok"])
            self.assertIn("昨天=2026-05-31", payload["answer"])
            self.assertIn("没有找到这些日期的本地记录", payload["answer"])
            self.assertEqual(payload["time_context"]["now"], "2026-06-01T12:34:56+09:00")

    def test_location_question_prioritizes_location_rows_for_relative_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = settings_for(root)
            settings.report_dir.mkdir(parents=True)
            (settings.summary_dir / "daily").mkdir(parents=True)
            store = Store(settings.db_path)
            try:
                rows = [
                    Observation(
                        source="filesystem",
                        kind="file_modified",
                        source_key=f"file-{index}",
                        observed_at=f"2026-06-01T00:{index:02d}:00+09:00",
                        title=f"file {index}",
                    )
                    for index in range(45)
                ]
                rows.append(
                    Observation(
                        source="mobile",
                        kind="location_sample",
                        source_key="late-location",
                        observed_at="2026-06-01T12:00:00+09:00",
                        title="Location sample",
                        body="Shibaura late location",
                        location="Tokyo Minato Shibaura",
                    )
                )
                store.upsert_observations(rows)
            finally:
                store.close()

            captured = {}

            def fake_generate(_settings, prompt, *, model):
                captured["prompt"] = prompt
                return "ok"

            dashboard.ollama_generate = fake_generate

            payload = api_ask(settings, {"question": "今天去了哪里？"})

            self.assertTrue(payload["ok"])
            self.assertIn("Tokyo Minato Shibaura", captured["prompt"])
            self.assertIn("@ Tokyo Minato Shibaura", captured["prompt"])
            self.assertEqual(payload["citations"][0]["kind"], "location_sample")
            self.assertEqual(payload["citations"][0]["date_context"], "今天=2026-06-01")


if __name__ == "__main__":
    unittest.main()
