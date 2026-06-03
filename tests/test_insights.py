import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from wond.insights import action_center_payload, action_suggestions_payload, project_clusters_payload, speaker_quality_payload
from wond.mobile import event_to_observation
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
    )


class InsightProductTests(unittest.TestCase):
    def test_action_center_combines_quick_tags_suggestions_and_projects(self):
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
                            observed_at="2026-06-03T09:00:00+09:00",
                            title="Strategy recording",
                            body="We need to send the strategy report tomorrow.",
                            metadata={"audio_analysis": {"status": "ok", "summary": "Need to send the strategy report tomorrow."}},
                        ),
                        Observation(
                            source="mobile",
                            kind="quick_tag",
                            source_key="tag-1",
                            observed_at="2026-06-03T09:05:00+09:00",
                            title="Quick tag: To Do",
                            body="Marked as follow-up on mobile",
                            metadata={"tag": "todo", "source_ref": "audio-1"},
                        ),
                        Observation(
                            source="filesystem",
                            kind="file_modified",
                            source_key=str(root / "strategy_report.pdf"),
                            observed_at="2026-06-03T09:10:00+09:00",
                            title="strategy_report.pdf",
                            body="Strategy report draft",
                            metadata={"path": str(root / "strategy_report.pdf")},
                        ),
                    ]
                )
                store.add_activity_sample(
                    SimpleNamespace(
                        sampled_at="2026-06-03T09:12:00+09:00",
                        app="Notes",
                        window_title="Strategy report",
                        bundle_id=None,
                        metadata={},
                    )
                )
            finally:
                store.close()

            payload = action_center_payload(settings, {"date": "2026-06-03"})

            self.assertTrue(payload["ok"])
            self.assertGreaterEqual(payload["summary"]["suggestions"], 1)
            self.assertEqual(payload["summary"]["quick_tags"], 1)
            self.assertTrue(any("strategy" in project["title"].lower() for project in payload["projects"]))
            self.assertTrue(any(item["tag"] == "todo" for item in payload["quick_tags"]))

    def test_mobile_quick_tag_ingests_as_structured_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = settings_for(root)
            event = {
                "id": "quick-tag-1",
                "kind": "quick_tag",
                "observed_at": "2026-06-03T10:00:00+09:00",
                "tag": "important",
                "title": "Important",
                "note": "Marked important on mobile",
                "source_ref": "audio-1",
            }

            obs = event_to_observation(settings, event, 0, root)

            self.assertEqual(obs.kind, "quick_tag")
            self.assertEqual(obs.title, "Important")
            self.assertIn("important", obs.metadata["tag"])
            self.assertEqual(obs.metadata["source_ref"], "audio-1")

    def test_insight_state_filters_suggestions_and_projects(self):
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
                            source_key="audio-2",
                            observed_at="2026-06-03T11:00:00+09:00",
                            title="Research notes",
                            body="Need to confirm the model result tomorrow.",
                            metadata={"audio_analysis": {"status": "ok", "summary": "Need to confirm the model result tomorrow."}},
                        ),
                        Observation(
                            source="filesystem",
                            kind="file_modified",
                            source_key=str(root / "model_result.md"),
                            observed_at="2026-06-03T11:03:00+09:00",
                            title="model_result.md",
                            body="Model result follow up",
                            metadata={"path": str(root / "model_result.md")},
                        ),
                    ]
                )
            finally:
                store.close()

            suggestions = action_suggestions_payload(settings, {"date": "2026-06-03"})
            projects = project_clusters_payload(settings, {"date": "2026-06-03"})
            self.assertGreaterEqual(suggestions["summary"]["total"], 1)
            self.assertGreaterEqual(projects["summary"]["projects"], 1)

            store = Store(settings.db_path)
            try:
                store.set_insight_state(
                    item_id=suggestions["suggestions"][0]["id"],
                    item_type="suggestion",
                    status="done",
                )
                store.set_insight_state(
                    item_id=projects["projects"][0]["id"],
                    item_type="project",
                    status="archived",
                    pinned=True,
                )
            finally:
                store.close()

            active_suggestions = action_suggestions_payload(settings, {"date": "2026-06-03"})
            all_suggestions = action_suggestions_payload(settings, {"date": "2026-06-03", "status": "all"})
            active_projects = project_clusters_payload(settings, {"date": "2026-06-03"})
            all_projects = project_clusters_payload(settings, {"date": "2026-06-03", "status": "all"})

            self.assertEqual(active_suggestions["summary"]["state"]["done"], 1)
            self.assertFalse(any(item["state"]["status"] == "done" for item in active_suggestions["suggestions"]))
            self.assertTrue(any(item["state"]["status"] == "done" for item in all_suggestions["suggestions"]))
            self.assertFalse(any(item["state"]["status"] == "archived" for item in active_projects["projects"]))
            self.assertTrue(any(item["state"]["pinned"] for item in all_projects["projects"]))

    def test_speaker_quality_scores_weak_auto_speaker_and_recommends_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = settings_for(root)
            store = Store(settings.db_path)
            try:
                store.conn.execute(
                    """
                    INSERT INTO speakers (id, display_name, identity_status, confidence, created_at, updated_at, metadata)
                    VALUES (1, 'Voice 001', 'provisional', 0.4, '2026-06-03T09:00:00+09:00', '2026-06-03T09:00:00+09:00', '{}')
                    """
                )
                store.conn.execute(
                    """
                    INSERT INTO speaker_samples (
                        speaker_id, observation_id, source_key, media_path, sample_path,
                        start_seconds, end_seconds, transcript, created_at, metadata
                    ) VALUES (1, NULL, 'sample-1', NULL, NULL, 0, 4, 'hello', '2026-06-03T09:01:00+09:00', '{}')
                    """
                )
                store.conn.commit()
            finally:
                store.close()

            payload = speaker_quality_payload(settings, {"view": "needs_work"})

            self.assertEqual(payload["summary"]["needs_work"], 1)
            speaker = payload["speakers"][0]
            self.assertLess(speaker["score"], 75)
            self.assertTrue(any(issue["kind"] == "low_sample_count" for issue in speaker["issues"]))
            self.assertTrue(any(rec["action"] == "speaker_confirm" for rec in speaker["recommendations"]))

    def test_speaker_quality_does_not_flag_confirmed_low_sample_consistency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = settings_for(root)
            store = Store(settings.db_path)
            try:
                store.conn.execute(
                    """
                    INSERT INTO speakers (id, display_name, identity_status, confidence, created_at, updated_at, metadata)
                    VALUES (
                        1,
                        'Confirmed Speaker',
                        'named',
                        0.2,
                        '2026-06-03T09:00:00+09:00',
                        '2026-06-03T09:00:00+09:00',
                        '{"speaker_review_status":"confirmed"}'
                    )
                    """
                )
                store.conn.executemany(
                    """
                    INSERT INTO speaker_samples (
                        speaker_id, observation_id, source_key, media_path, sample_path,
                        start_seconds, end_seconds, transcript, created_at, metadata
                    ) VALUES (1, NULL, ?, NULL, NULL, 0, 4, ?, '2026-06-03T09:01:00+09:00', ?)
                    """,
                    [
                        ("sample-1", "hello", '{"sample_confidence":0.2}'),
                        ("sample-2", "hola", '{"sample_confidence":0.3}'),
                    ],
                )
                store.conn.executemany(
                    """
                    INSERT INTO speaker_embeddings (speaker_id, sample_id, model, vector, dimension, created_at, metadata)
                    VALUES (1, ?, 'test', '[1,0]', 2, '2026-06-03T09:01:00+09:00', '{}')
                    """,
                    [(1,), (2,)],
                )
                store.conn.commit()
            finally:
                store.close()

            payload = speaker_quality_payload(settings, {"view": "all"})

        speaker = payload["speakers"][0]
        self.assertFalse(any(issue["kind"] == "low_sample_confidence" for issue in speaker["issues"]))

    def test_speaker_quality_needs_work_omits_hidden_low_similarity_speakers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = settings_for(root)
            store = Store(settings.db_path)
            try:
                store.conn.execute(
                    """
                    INSERT INTO speakers (id, display_name, identity_status, confidence, created_at, updated_at, metadata)
                    VALUES (
                        1,
                        'Voice 001',
                        'provisional',
                        1.0,
                        '2026-06-03T09:00:00+09:00',
                        '2026-06-03T09:00:00+09:00',
                        '{"speaker_review_status":"low_similarity_hidden","speaker_hidden":true}'
                    )
                    """
                )
                store.conn.commit()
            finally:
                store.close()

            needs_work = speaker_quality_payload(settings, {"view": "needs_work"})
            all_items = speaker_quality_payload(settings, {"view": "all"})

        self.assertEqual(needs_work["summary"]["needs_work"], 0)
        self.assertEqual(len(needs_work["speakers"]), 0)
        self.assertEqual(all_items["speakers"][0]["review_status"], "low_similarity_hidden")
        self.assertTrue(any(issue["kind"] == "hidden_low_similarity" for issue in all_items["speakers"][0]["issues"]))


if __name__ == "__main__":
    unittest.main()
