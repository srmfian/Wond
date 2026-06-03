import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace

from wond.project_memory import meeting_mode_payload, meeting_mode_post, project_memory_payload, project_memory_post
from wond.store import Store


def settings_for(root: Path) -> SimpleNamespace:
    data_dir = root / "data"
    return SimpleNamespace(
        path=root / "config.json",
        db_path=data_dir / "context.sqlite3",
        timezone="Asia/Tokyo",
        data_dir=data_dir,
        log_dir=data_dir / "logs",
        summary_dir=data_dir / "summaries",
        report_dir=data_dir / "reports",
        recycle_bin_dir=data_dir / "recycle_bin",
        speaker_sample_dir=data_dir / "speaker_samples",
        mobile_sync={"port": 1},
    )


class ProjectMemoryTests(unittest.TestCase):
    def test_project_cluster_can_be_saved_as_long_lived_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(Path(tmp))
            project = {
                "id": "project:2026-06-03:launch",
                "title": "Launch Plan",
                "summary": "3 条记录围绕 launch plan，主要来自 audio。",
                "keywords": ["launch", "plan"],
                "event_count": 3,
                "confidence": 0.82,
                "time_span": {"start": "2026-06-03T10:00:00+09:00", "end": "2026-06-03T11:00:00+09:00"},
                "categories": {"audio": 2, "files": 1},
                "evidence": [{"id": "observation:1", "title": "Launch recording", "time": "2026-06-03T10:00:00+09:00"}],
                "next_actions": [{"title": "Confirm launch owner", "body": "Confirm launch owner"}],
            }

            result, status = project_memory_post(settings, {"action": "save_project", "date": "2026-06-03", "project": project})
            payload = project_memory_payload(settings, {"date": "2026-06-03"})

        self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(result["ok"])
        self.assertEqual(result["memory"]["title"], "Launch Plan")
        self.assertEqual(result["memory"]["evidence_count"], 1)
        self.assertTrue(any(memory["title"] == "Launch Plan" for memory in payload["memories"]))
        self.assertEqual(payload["summary"]["active"], 1)

    def test_meeting_mode_writes_notes_summary_and_project_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = settings_for(root)
            created, create_status = project_memory_post(
                settings,
                {"action": "create", "title": "Research Sprint", "summary": "Ongoing research work", "keywords": "research,sprint"},
            )
            project_id = created["memory"]["id"]

            started, start_status = meeting_mode_post(
                settings,
                {
                    "action": "start",
                    "title": "Research sync",
                    "project_id": project_id,
                    "participants": "Alice, Bob",
                    "agenda": "Review model results",
                },
            )
            meeting_id = started["meeting"]["id"]
            noted, note_status = meeting_mode_post(
                settings,
                {
                    "action": "note",
                    "meeting_id": meeting_id,
                    "note": "Need to confirm the evaluation owner tomorrow.",
                },
            )
            ended, end_status = meeting_mode_post(settings, {"action": "end", "meeting_id": meeting_id})
            mode = meeting_mode_payload(settings)
            memory = project_memory_payload(settings, {"status": "all"})["memories"][0]

            store = Store(settings.db_path)
            try:
                meeting_observations = store.conn.execute("SELECT count(*) FROM observations WHERE source = 'meeting'").fetchone()[0]
                project_events = store.conn.execute("SELECT count(*) FROM project_memory_events WHERE project_id = ?", (project_id,)).fetchone()[0]
            finally:
                store.close()

        self.assertEqual(create_status, HTTPStatus.CREATED)
        self.assertEqual(start_status, HTTPStatus.CREATED)
        self.assertEqual(note_status, HTTPStatus.OK)
        self.assertEqual(end_status, HTTPStatus.OK)
        self.assertTrue(noted["meeting"]["action_items"])
        self.assertEqual(ended["meeting"]["status"], "ended")
        self.assertIsNone(mode["active_meeting"])
        self.assertGreaterEqual(meeting_observations, 3)
        self.assertEqual(project_events, 1)
        self.assertTrue(memory["next_actions"])


if __name__ == "__main__":
    unittest.main()
