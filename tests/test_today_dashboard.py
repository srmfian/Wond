import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace

from wond.dashboard import api_daily_feedback_post, api_today
from wond.store import ActivitySample, Observation, Store


def settings_for(root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        db_path=root / "context.sqlite3",
        timezone="Asia/Tokyo",
        summary_dir=root / "summaries",
        data_dir=root / "data",
        audio_analysis={},
        speaker_recognition={},
        speaker_sample_dir=root / "speaker_samples",
    )


class TodayDashboardTests(unittest.TestCase):
    def test_today_combines_activity_audio_and_time_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = settings_for(root)
            store = Store(settings.db_path)
            try:
                store.upsert_observations(
                    [
                        Observation(
                            source="mobile",
                            kind="audio_segment",
                            source_key="audio-1",
                            observed_at="2026-06-01T09:10:00+09:00",
                            title="Audio segment",
                            body="raw transcript",
                            metadata={"audio_analysis": {"status": "ok", "summary": "morning standup summary"}},
                        ),
                    ]
                )
                store.add_activity_sample(
                    ActivitySample(
                        sampled_at="2026-06-01T09:12:00+09:00",
                        app="Notes",
                        window_title="Planning",
                    )
                )
            finally:
                store.close()

            payload = api_today(settings, {"date": "2026-06-01", "time_from": "09:00", "time_to": "10:00"})

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["summary"]["by_category"]["audio"], 1)
            self.assertEqual(payload["summary"]["by_category"]["app"], 1)
            self.assertNotIn("chat", payload["summary"]["by_category"])
            self.assertIn("morning standup summary", "\n".join(event["body"] for event in payload["events"]))

    def test_today_skips_internal_file_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = settings_for(root)
            internal = settings.data_dir / "wond.sqlite3-wal"
            external = root / "notes.txt"
            store = Store(settings.db_path)
            try:
                store.upsert_observations(
                    [
                        Observation(
                            source="filesystem",
                            kind="file_modified",
                            source_key=str(internal),
                            observed_at="2026-06-01T09:00:00+09:00",
                            title=internal.name,
                            subtitle=str(internal.parent),
                            metadata={"path": str(internal)},
                        ),
                        Observation(
                            source="filesystem",
                            kind="file_modified",
                            source_key=str(external),
                            observed_at="2026-06-01T09:05:00+09:00",
                            title=external.name,
                            subtitle=str(external.parent),
                            metadata={"path": str(external)},
                        ),
                    ]
                )
            finally:
                store.close()

            payload = api_today(settings, {"date": "2026-06-01"})

            self.assertEqual(payload["summary"]["by_category"], {"file": 1})
            self.assertEqual([event["title"] for event in payload["events"]], ["notes.txt"])

    def test_daily_feedback_is_stored_as_long_term_observation_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = settings_for(root)
            Store(settings.db_path).close()

            payload, status = api_daily_feedback_post(
                settings,
                {
                    "date": "2026-06-01",
                    "category": "wrong",
                    "note": "The summary misread the meeting outcome.",
                },
            )

            self.assertEqual(status, HTTPStatus.OK)
            self.assertTrue(payload["ok"])
            store = Store(settings.db_path)
            try:
                feedback_count = store.conn.execute("SELECT count(*) FROM daily_feedback").fetchone()[0]
                observation = store.conn.execute(
                    "SELECT source, kind, body FROM observations WHERE source='feedback'"
                ).fetchone()
            finally:
                store.close()
            self.assertEqual(feedback_count, 1)
            self.assertEqual(observation["kind"], "daily_feedback")
            self.assertIn("misread", observation["body"])
            self.assertIn("misread", (settings.summary_dir / "feedback" / "2026-06-01.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
