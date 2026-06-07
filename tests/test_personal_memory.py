import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace

from wond.personal_memory import personal_context_semantic_items, personal_memory_payload, personal_memory_post
from wond.store import Observation, Store


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
        personal_memory={
            "enabled": True,
            "candidate_sources": ["mobile", "messages", "apple_mail"],
            "max_candidates_per_day": 24,
            "qa_include_confirmed": True,
            "qa_include_profile": True,
            "qa_memory_limit": 12,
        },
    )


class PersonalMemoryTests(unittest.TestCase):
    def test_profile_memory_and_candidate_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(Path(tmp))
            profile, profile_status = personal_memory_post(
                settings,
                {
                    "action": "upsert_profile",
                    "section": "preferences",
                    "label": "回答语言",
                    "value": "默认用中文回答。",
                },
            )

            store = Store(settings.db_path)
            try:
                store.upsert_observations(
                    [
                        Observation(
                            source="mobile",
                            kind="audio_segment",
                            source_key="audio-1",
                            observed_at="2026-06-07T10:00:00+09:00",
                            title="Meeting note",
                            body="我希望日报默认用中文，需要明天跟进学生反馈。",
                        )
                    ]
                )
            finally:
                store.close()

            generated, generated_status = personal_memory_post(
                settings,
                {"action": "generate_candidates", "date": "2026-06-07"},
            )
            payload = personal_memory_payload(settings, {"status": "candidate", "date": "2026-06-07"})
            candidate_id = payload["memories"][0]["id"]
            confirmed, confirm_status = personal_memory_post(
                settings,
                {"action": "confirm_memory", "memory_id": candidate_id},
            )

            store = Store(settings.db_path)
            try:
                items = personal_context_semantic_items(settings, store, "日报 中文")
            finally:
                store.close()

        self.assertEqual(profile_status, HTTPStatus.OK)
        self.assertTrue(profile["ok"])
        self.assertEqual(generated_status, HTTPStatus.OK)
        self.assertGreaterEqual(generated["created"], 1)
        self.assertEqual(confirm_status, HTTPStatus.OK)
        self.assertEqual(confirmed["memory"]["status"], "confirmed")
        self.assertTrue(any(item["type"] in {"personal_memory", "personal_profile"} for item in items))

    def test_conflict_detection_and_hard_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(Path(tmp))
            first, first_status = personal_memory_post(
                settings,
                {
                    "action": "create_memory",
                    "memory_type": "preference",
                    "title": "报告偏好",
                    "subject": "report-language",
                    "body": "报告默认用中文。",
                },
            )
            second, second_status = personal_memory_post(
                settings,
                {
                    "action": "create_memory",
                    "memory_type": "preference",
                    "title": "报告偏好",
                    "subject": "report-language",
                    "body": "报告默认用英文。",
                },
            )
            payload = personal_memory_payload(settings, {"status": "all", "conflict_status": "open"})
            personal_memory_post(settings, {"action": "delete_memory", "memory_id": first["memory"]["id"]})
            after_delete = personal_memory_payload(settings, {"status": "all", "conflict_status": "open"})

        self.assertEqual(first_status, HTTPStatus.CREATED)
        self.assertEqual(second_status, HTTPStatus.CREATED)
        self.assertGreaterEqual(payload["summary"]["open_conflicts"], 1)
        self.assertFalse(any(row["id"] == first["memory"]["id"] for row in after_delete["memories"]))
        self.assertTrue(second["memory"]["id"])


if __name__ == "__main__":
    unittest.main()
