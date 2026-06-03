import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from wond.speaker_identity import best_existing_speaker_match
from wond.speakers import (
    auto_organize_speakers,
    collapse_vad_chunk_speakers,
    clip_bounds,
    detach_speaker_sample,
    mark_speaker_review_status,
    pending_speaker_match_groups,
    process_speakers_for_observation,
    refresh_speaker_sample_confidences,
    refresh_representative_speaker_samples,
    repair_missing_speaker_embeddings,
    repair_speaker_sample_clips,
    repair_speaker_sample_text,
    resolve_speaker_match_decision,
    reset_and_auto_group_speaker_samples,
    revive_hidden_speakers,
    speaker_confidence_summary,
    speaker_profile_payload,
)
from wond.store import Observation, Store


class SpeakerProcessingTests(unittest.TestCase):
    def test_auto_speaker_names_are_unique_global_voice_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "context.sqlite3")
            try:
                first = store.ensure_speaker_for_alias(
                    "observation:1:Speaker 1",
                    default_name="Speaker 1",
                    label="Speaker 1",
                )
                second = store.ensure_speaker_for_alias(
                    "observation:2:Speaker 1",
                    default_name="1",
                    label="Speaker 1",
                )
                third = store.ensure_speaker_for_alias(
                    "observation:3:Alice",
                    default_name="Alice",
                    label="Alice",
                )
            finally:
                store.close()

        self.assertEqual(first["display_name"], "Voice 001")
        self.assertEqual(second["display_name"], "Voice 002")
        self.assertEqual(third["display_name"], "Alice")

    def test_auto_name_normalization_keeps_named_speakers(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "context.sqlite3")
            now = "2026-06-01T10:00:00+09:00"
            try:
                store.conn.executemany(
                    """
                    INSERT INTO speakers (display_name, identity_status, created_at, updated_at, metadata)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        ("Speaker 1", "named", now, now, "{}"),
                        ("Speaker 1", "provisional", now, now, "{}"),
                        ("Alice", "provisional", now, now, "{}"),
                    ],
                )
                store.conn.commit()
                changes = store.relabel_auto_speaker_names()
                rows = store.list_speakers()
            finally:
                store.close()

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["old_display_name"], "Speaker 1")
        self.assertEqual(changes[0]["new_display_name"], "Voice 002")
        self.assertEqual([row["display_name"] for row in rows], ["Speaker 1", "Voice 002", "Alice"])
        self.assertEqual(rows[1]["identity_status"], "provisional")

    def test_speaker_ids_are_not_reused_after_merge_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "context.sqlite3")
            try:
                target = store.ensure_speaker_for_alias("obs:1:target", default_name="Speaker 1", label="Speaker 1")
                source = store.ensure_speaker_for_alias("obs:1:source", default_name="Speaker 2", label="Speaker 2")
                store.record_speaker_match_decision(
                    source_speaker_id=int(source["id"]),
                    target_speaker_id=int(target["id"]),
                    sample_id=None,
                    model="test-model",
                    score=0.91,
                    threshold=0.88,
                    status="auto_merged",
                )
                self.assertTrue(store.merge_speakers(int(source["id"]), int(target["id"])))

                fresh = store.ensure_speaker_for_alias("obs:2:fresh", default_name="Speaker 1", label="Speaker 1")
                matches = store.list_speaker_match_decisions()
            finally:
                store.close()

        self.assertEqual(int(fresh["id"]), 3)
        self.assertEqual(matches[0]["source_name"], "Voice 002")
        self.assertEqual(matches[0]["target_name"], "Voice 001")

    def test_merge_preserves_user_named_source_when_target_is_auto(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "context.sqlite3")
            try:
                target = store.ensure_speaker_for_alias("obs:1:auto", default_name="Speaker 1", label="Speaker 1")
                source = store.ensure_speaker_for_alias("obs:1:named", default_name="Speaker 2", label="Speaker 2")
                store.rename_speaker(int(source["id"]), "Alice")

                self.assertTrue(store.merge_speakers(int(source["id"]), int(target["id"])))
                merged = store.get_speaker(int(target["id"]))
            finally:
                store.close()

        self.assertIsNotNone(merged)
        self.assertEqual(merged["display_name"], "Alice")
        self.assertEqual(merged["identity_status"], "named")

    def test_merge_keeps_named_target_when_source_is_auto(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "context.sqlite3")
            try:
                target = store.ensure_speaker_for_alias("obs:1:named", default_name="Speaker 1", label="Speaker 1")
                source = store.ensure_speaker_for_alias("obs:1:auto", default_name="Speaker 2", label="Speaker 2")
                store.rename_speaker(int(target["id"]), "Bob")

                self.assertTrue(store.merge_speakers(int(source["id"]), int(target["id"])))
                merged = store.get_speaker(int(target["id"]))
            finally:
                store.close()

        self.assertIsNotNone(merged)
        self.assertEqual(merged["display_name"], "Bob")
        self.assertEqual(merged["identity_status"], "named")

    def test_named_speaker_confidence_can_be_refreshed_without_renaming_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "context.sqlite3")
            try:
                speaker = store.ensure_speaker_for_alias("obs:1:named", default_name="Speaker 1", label="Speaker 1")
                speaker_id = int(speaker["id"])
                store.rename_speaker(speaker_id, "Alice")
                store.update_speaker_identity_status(speaker_id, status="provisional", confidence=0.42)
                refreshed = store.get_speaker(speaker_id)
            finally:
                store.close()

        self.assertEqual(refreshed["display_name"], "Alice")
        self.assertEqual(refreshed["identity_status"], "named")
        self.assertAlmostEqual(float(refreshed["confidence"]), 0.42, places=3)

    def test_match_decision_does_not_join_reused_future_speaker_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "context.sqlite3")
            try:
                store.conn.execute(
                    """
                    INSERT INTO speakers (id, display_name, identity_status, created_at, updated_at, metadata)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (10, "Wrong reused row", "provisional", "2026-06-01T12:00:00+09:00", "2026-06-01T12:00:00+09:00", "{}"),
                )
                store.conn.execute(
                    """
                    INSERT INTO speaker_match_decisions (
                        source_speaker_id, target_speaker_id, sample_id, model,
                        score, threshold, status, created_at, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (10, None, None, "test-model", 0.91, 0.88, "auto_merged", "2026-06-01T11:00:00+09:00", "{}"),
                )
                store.conn.commit()
                row = store.list_speaker_match_decisions()[0]
            finally:
                store.close()

        self.assertEqual(row["source_name"], "Voice 010 (merged/deleted)")
        self.assertEqual(row["source_stale_reference"], 1)

    def test_scoped_speaker_name_mapping_does_not_collapse_duplicate_local_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "context.sqlite3")
            try:
                store.ensure_speaker_for_alias(
                    "observation:99:vad_chunk_001:Speaker 1",
                    default_name="Speaker 1",
                    label="Speaker 1",
                    metadata={"speaker_scope": "vad_chunk_001"},
                )
                store.ensure_speaker_for_alias(
                    "observation:99:vad_chunk_002:Speaker 1",
                    default_name="Speaker 1",
                    label="Speaker 1",
                    metadata={"speaker_scope": "vad_chunk_002"},
                )
                names = store.speaker_names_for_observation(99)
            finally:
                store.close()

        self.assertNotIn("Speaker 1", names)
        self.assertEqual(names["vad_chunk_001:Speaker 1"]["display_name"], "Voice 001")
        self.assertEqual(names["vad_chunk_002:Speaker 1"]["display_name"], "Voice 002")

    def test_unlabeled_speech_segments_record_explicit_status(self):
        settings = SimpleNamespace(
            speaker_recognition={"enabled": True},
            speaker_sample_dir=Path("/tmp/speaker_samples"),
        )
        store = SimpleNamespace()
        metadata = {
            "audio_analysis": {
                "audio_timeline": {
                    "duration_seconds": 10.0,
                    "speech_segments": [
                        {"start": 1.0, "end": 4.0, "speaker": None, "text": "hello without a label"}
                    ],
                }
            }
        }

        result = process_speakers_for_observation(
            settings,
            store,
            observation_id=1,
            source_key="audio-1",
            media_path=None,
            metadata=metadata,
        )

        processing = result["audio_analysis"]["speaker_processing"]
        self.assertEqual(processing["status"], "skipped_no_speaker_labels")
        self.assertEqual(processing["speech_like_segments"], 1)
        self.assertEqual(processing["unlabeled_speech_segments"], 1)

    def test_delete_speaker_removes_related_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = Store(root / "test.sqlite3")
            try:
                source = store.ensure_speaker_for_alias("obs:1:s1", default_name="Speaker 1", label="Speaker 1")
                target = store.ensure_speaker_for_alias("obs:1:s2", default_name="Speaker 2", label="Speaker 2")
                sample = store.add_speaker_sample(
                    speaker_id=int(source["id"]),
                    observation_id=None,
                    source_key="sample-source",
                    media_path=None,
                    sample_path=str(root / "speaker_samples" / "speaker-000001" / "sample.m4a"),
                    start_seconds=0.0,
                    end_seconds=2.0,
                    transcript="hello",
                    metadata={},
                )
                store.add_speaker_embedding(
                    speaker_id=int(source["id"]),
                    sample_id=int(sample["id"]),
                    model="test-model",
                    vector=[0.1, 0.2],
                    metadata={},
                )
                store.record_speaker_match_decision(
                    source_speaker_id=int(source["id"]),
                    target_speaker_id=int(target["id"]),
                    sample_id=int(sample["id"]),
                    model="test-model",
                    score=0.8,
                    threshold=0.7,
                    status="candidate",
                )

                self.assertTrue(store.delete_speaker(int(source["id"])))

                self.assertIsNone(store.get_speaker(int(source["id"])))
                self.assertEqual(store.list_speaker_samples(int(source["id"])), [])
                self.assertEqual(store.speaker_embedding_rows(model="test-model", speaker_id=int(source["id"])), [])
                self.assertEqual(store.list_speaker_match_decisions(), [])
            finally:
                store.close()

    def test_detach_speaker_sample_moves_sample_to_new_speaker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(
                speaker_recognition={},
                speaker_sample_dir=root / "speaker_samples",
            )
            store = Store(root / "test.sqlite3")
            try:
                source = store.ensure_speaker_for_alias("obs:1:s1", default_name="Speaker 1", label="Speaker 1")
                source_id = int(source["id"])
                sample_dir = root / "speaker_samples" / f"speaker-{source_id:06d}"
                sample_dir.mkdir(parents=True)
                sample_file = sample_dir / "sample.m4a"
                sample_file.write_bytes(b"audio")
                sample = store.add_speaker_sample(
                    speaker_id=source_id,
                    observation_id=None,
                    source_key="sample-source",
                    media_path=None,
                    sample_path=str(sample_file),
                    start_seconds=0.0,
                    end_seconds=2.0,
                    transcript="hello",
                    metadata={"status": "ok"},
                )
                model = "speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb"
                store.add_speaker_embedding(
                    speaker_id=source_id,
                    sample_id=int(sample["id"]),
                    model=model,
                    vector=[0.1, 0.2],
                    metadata={},
                )

                result = detach_speaker_sample(settings, store, sample_id=int(sample["id"]))
                detached = store.get_speaker_sample(int(sample["id"]))
                detached_metadata = json.loads(detached["metadata"])
                new_id = int(detached["speaker_id"])
                old_embeddings = store.speaker_embedding_rows(model=model, speaker_id=source_id)
                new_embeddings = store.speaker_embedding_rows(model=model, speaker_id=new_id)
            finally:
                store.close()

            self.assertFalse(result.failed)
            self.assertNotEqual(source_id, new_id)
            self.assertEqual(detached_metadata["sample_role"], "manual_detached_sample")
            self.assertEqual(detached_metadata["detached_from_speaker_id"], source_id)
            self.assertEqual(result.new_speaker_id, new_id)
            self.assertEqual(len(old_embeddings), 0)
            self.assertEqual(len(new_embeddings), 1)
            self.assertIn(f"speaker-{new_id:06d}", detached["sample_path"])
            self.assertFalse(sample_file.exists())
            self.assertTrue(Path(detached["sample_path"]).exists())

    def test_refresh_speaker_sample_confidences_updates_sample_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(
                speaker_recognition={},
                speaker_sample_dir=root / "speaker_samples",
            )
            store = Store(root / "test.sqlite3")
            try:
                speaker = store.ensure_speaker_for_alias("obs:1:s1", default_name="Speaker 1", label="Speaker 1")
                speaker_id = int(speaker["id"])
                first = store.add_speaker_sample(
                    speaker_id=speaker_id,
                    observation_id=None,
                    source_key="sample-1",
                    media_path=None,
                    sample_path=None,
                    start_seconds=0.0,
                    end_seconds=2.0,
                    transcript="first",
                    metadata={},
                )
                second = store.add_speaker_sample(
                    speaker_id=speaker_id,
                    observation_id=None,
                    source_key="sample-2",
                    media_path=None,
                    sample_path=None,
                    start_seconds=2.0,
                    end_seconds=4.0,
                    transcript="second",
                    metadata={},
                )
                model = "speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb"
                store.add_speaker_embedding(
                    speaker_id=speaker_id,
                    sample_id=int(first["id"]),
                    model=model,
                    vector=[1.0, 0.0],
                    metadata={},
                )
                store.add_speaker_embedding(
                    speaker_id=speaker_id,
                    sample_id=int(second["id"]),
                    model=model,
                    vector=[0.8, 0.6],
                    metadata={},
                )
                stable_updated_at = "2026-06-01T10:00:00+09:00"
                store.conn.execute(
                    "UPDATE speakers SET updated_at = ? WHERE id = ?",
                    (stable_updated_at, speaker_id),
                )
                store.conn.commit()
                before_first = store.get_speaker_sample(int(first["id"]))
                before_second = store.get_speaker_sample(int(second["id"]))

                result = refresh_speaker_sample_confidences(settings, store, speaker_ids=[speaker_id])
                after_first = store.get_speaker_sample(int(first["id"]))
                after_second = store.get_speaker_sample(int(second["id"]))
                first_metadata = json.loads(after_first["metadata"])
                second_metadata = json.loads(after_second["metadata"])
                refreshed = store.get_speaker(speaker_id)
            finally:
                store.close()

        self.assertEqual(result.scanned_speakers, 1)
        self.assertEqual(result.refreshed_speakers, 1)
        self.assertEqual(result.updated_samples, 2)
        self.assertAlmostEqual(first_metadata["sample_confidence"], 0.8, places=3)
        self.assertAlmostEqual(second_metadata["sample_confidence"], 0.8, places=3)
        self.assertEqual(first_metadata["sample_confidence_basis"], "leave_one_out_centroid")
        self.assertEqual(first_metadata["sample_confidence_model"], model)
        self.assertAlmostEqual(float(refreshed["confidence"]), 0.8, places=3)
        self.assertEqual(refreshed["updated_at"], stable_updated_at)
        for before, after in ((before_first, after_first), (before_second, after_second)):
            self.assertEqual(after["created_at"], before["created_at"])
            self.assertEqual(after["start_seconds"], before["start_seconds"])
            self.assertEqual(after["end_seconds"], before["end_seconds"])

    def test_confirmed_speaker_confidence_summary_keeps_manual_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "context.sqlite3")
            try:
                store.conn.execute(
                    """
                    INSERT INTO speakers (id, display_name, identity_status, confidence, created_at, updated_at, metadata)
                    VALUES (
                        1,
                        'Multi Language Speaker',
                        'named',
                        0.2,
                        '2026-06-03T09:00:00+09:00',
                        '2026-06-03T09:00:00+09:00',
                        '{"speaker_review_status":"confirmed"}'
                    )
                    """
                )
                store.conn.commit()
                row = store.get_speaker(1)
                summary = speaker_confidence_summary(row, sample_count=3, embedding_count=3)
            finally:
                store.close()

        self.assertEqual(summary["level"], "confirmed")
        self.assertEqual(summary["label"], "已人工确认")
        self.assertIn("一致性诊断", summary["detail"])

    def test_confirmed_profile_match_uses_multiple_voice_prototypes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "context.sqlite3")
            model = "speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb"
            try:
                speaker = store.ensure_speaker_for_alias("obs:1:s1", default_name="Speaker 1", label="Speaker 1")
                speaker_id = int(speaker["id"])
                first = store.add_speaker_sample(
                    speaker_id=speaker_id,
                    observation_id=None,
                    source_key="sample-voice-a",
                    media_path=None,
                    sample_path=None,
                    start_seconds=0.0,
                    end_seconds=2.0,
                    transcript="voice a",
                    metadata={},
                )
                second = store.add_speaker_sample(
                    speaker_id=speaker_id,
                    observation_id=None,
                    source_key="sample-voice-b",
                    media_path=None,
                    sample_path=None,
                    start_seconds=2.0,
                    end_seconds=4.0,
                    transcript="voice b",
                    metadata={},
                )
                store.add_speaker_embedding(
                    speaker_id=speaker_id,
                    sample_id=int(first["id"]),
                    model=model,
                    vector=[1.0, 0.0],
                    metadata={},
                )
                store.add_speaker_embedding(
                    speaker_id=speaker_id,
                    sample_id=int(second["id"]),
                    model=model,
                    vector=[0.0, 1.0],
                    metadata={},
                )
                mark_speaker_review_status(store, speaker_ids=[speaker_id], status="confirmed")
                profile_settings = SimpleNamespace(
                    speaker_recognition={
                        "confirmed_profile_matching_enabled": True,
                        "confirmed_profile_max_prototypes": 4,
                        "confirmed_profile_min_samples": 2,
                    }
                )
                centroid_settings = SimpleNamespace(
                    speaker_recognition={
                        "confirmed_profile_matching_enabled": False,
                    }
                )

                profile_match = best_existing_speaker_match(
                    profile_settings,
                    store,
                    model=model,
                    speaker_id=999,
                    vector=[1.0, 0.0],
                )
                centroid_match = best_existing_speaker_match(
                    centroid_settings,
                    store,
                    model=model,
                    speaker_id=999,
                    vector=[1.0, 0.0],
                )
            finally:
                store.close()

        self.assertIsNotNone(profile_match)
        self.assertIsNotNone(centroid_match)
        assert profile_match is not None
        assert centroid_match is not None
        self.assertEqual(profile_match.speaker_id, speaker_id)
        self.assertEqual(profile_match.matcher, "confirmed_profile")
        self.assertGreater(profile_match.score, 0.99)
        self.assertGreater(profile_match.prototype_count, 1)
        self.assertEqual(centroid_match.matcher, "centroid")
        self.assertLess(centroid_match.score, 0.8)

    def test_repair_missing_speaker_embeddings_supports_preview_and_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample_dir = root / "speaker_samples" / "speaker-000001"
            sample_dir.mkdir(parents=True)
            sample_file = sample_dir / "sample.m4a"
            sample_file.write_bytes(b"audio")
            settings = SimpleNamespace(
                speaker_recognition={},
                speaker_sample_dir=root / "speaker_samples",
            )
            store = Store(root / "test.sqlite3")
            try:
                speaker = store.ensure_speaker_for_alias("obs:1:s1", default_name="Speaker 1", label="Speaker 1")
                speaker_id = int(speaker["id"])
                sample = store.add_speaker_sample(
                    speaker_id=speaker_id,
                    observation_id=None,
                    source_key="sample-needs-embedding",
                    media_path=None,
                    sample_path=str(sample_file),
                    start_seconds=0.0,
                    end_seconds=2.0,
                    transcript="hello",
                    metadata={},
                )
                sample_id = int(sample["id"])
                model = "speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb"

                with patch("wond.speakers.speaker_embedding", return_value=[1.0, 0.0]) as embed:
                    preview = repair_missing_speaker_embeddings(settings, store, limit=1)
                    preview_embeddings = store.speaker_embedding_rows(model=model, speaker_id=speaker_id)
                    applied = repair_missing_speaker_embeddings(settings, store, apply=True, limit=1)
                    applied_embeddings = store.speaker_embedding_rows(model=model, speaker_id=speaker_id)
                    repaired_sample = store.get_speaker_sample(sample_id)
            finally:
                store.close()

        repaired_metadata = json.loads(repaired_sample["metadata"])
        self.assertEqual(preview.scanned_samples, 1)
        self.assertEqual(preview.repaired_samples, 1)
        self.assertEqual(preview_embeddings, [])
        self.assertEqual(applied.repaired_samples, 1)
        self.assertEqual(len(applied_embeddings), 1)
        self.assertEqual(applied_embeddings[0]["sample_id"], sample_id)
        self.assertEqual(repaired_metadata["embedding_repair_status"], "ok")
        self.assertEqual(repaired_metadata["embedding_model"], model)
        self.assertEqual(embed.call_count, 1)

    def test_refresh_representative_samples_marks_best_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = Store(root / "test.sqlite3")
            try:
                speaker = store.ensure_speaker_for_alias("obs:1:s1", default_name="Speaker 1", label="Speaker 1")
                speaker_id = int(speaker["id"])
                low = store.add_speaker_sample(
                    speaker_id=speaker_id,
                    observation_id=None,
                    source_key="sample-low",
                    media_path=None,
                    sample_path=None,
                    start_seconds=0.0,
                    end_seconds=4.0,
                    transcript="low confidence",
                    metadata={"sample_confidence": 0.1, "status": "ok"},
                )
                high = store.add_speaker_sample(
                    speaker_id=speaker_id,
                    observation_id=None,
                    source_key="sample-high",
                    media_path=None,
                    sample_path=None,
                    start_seconds=4.0,
                    end_seconds=8.0,
                    transcript="high confidence",
                    metadata={"sample_confidence": 0.9, "status": "ok"},
                )
                mid = store.add_speaker_sample(
                    speaker_id=speaker_id,
                    observation_id=None,
                    source_key="sample-mid",
                    media_path=None,
                    sample_path=None,
                    start_seconds=8.0,
                    end_seconds=12.0,
                    transcript="middle confidence",
                    metadata={"sample_confidence": 0.5, "status": "ok"},
                )

                result = refresh_representative_speaker_samples(store, speaker_ids=[speaker_id], per_speaker=2)
                high_metadata = json.loads(store.get_speaker_sample(int(high["id"]))["metadata"])
                mid_metadata = json.loads(store.get_speaker_sample(int(mid["id"]))["metadata"])
                low_metadata = json.loads(store.get_speaker_sample(int(low["id"]))["metadata"])
                speaker_metadata = json.loads(store.get_speaker(speaker_id)["metadata"])
            finally:
                store.close()

        self.assertEqual(result.scanned_speakers, 1)
        self.assertEqual(result.updated_speakers, 1)
        self.assertEqual(result.representative_samples, 2)
        self.assertTrue(high_metadata["representative_sample"])
        self.assertEqual(high_metadata["representative_rank"], 1)
        self.assertTrue(mid_metadata["representative_sample"])
        self.assertEqual(mid_metadata["representative_rank"], 2)
        self.assertNotIn("representative_sample", low_metadata)
        self.assertEqual(speaker_metadata["representative_sample_ids"], [int(high["id"]), int(mid["id"])])

    def test_revive_hidden_speakers_returns_evidence_to_review_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = Store(root / "test.sqlite3")
            try:
                speaker = store.ensure_speaker_for_alias("obs:1:s1", default_name="Speaker 1", label="Speaker 1")
                speaker_id = int(speaker["id"])
                first = store.add_speaker_sample(
                    speaker_id=speaker_id,
                    observation_id=None,
                    source_key="hidden-sample-1",
                    media_path=None,
                    sample_path=None,
                    start_seconds=0.0,
                    end_seconds=2.0,
                    transcript="first",
                    metadata={},
                )
                second = store.add_speaker_sample(
                    speaker_id=speaker_id,
                    observation_id=None,
                    source_key="hidden-sample-2",
                    media_path=None,
                    sample_path=None,
                    start_seconds=2.0,
                    end_seconds=4.0,
                    transcript="second",
                    metadata={},
                )
                model = "speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb"
                store.add_speaker_embedding(speaker_id=speaker_id, sample_id=int(first["id"]), model=model, vector=[1.0, 0.0], metadata={})
                store.add_speaker_embedding(speaker_id=speaker_id, sample_id=int(second["id"]), model=model, vector=[0.9, 0.1], metadata={})
                mark_speaker_review_status(store, speaker_ids=[speaker_id], status="hidden")

                preview = revive_hidden_speakers(store, min_samples=2)
                applied = revive_hidden_speakers(store, apply=True, min_samples=2)
                metadata = json.loads(store.get_speaker(speaker_id)["metadata"])
            finally:
                store.close()

        self.assertEqual(preview.candidates, 1)
        self.assertEqual(preview.revived, 0)
        self.assertEqual(applied.revived, 1)
        self.assertEqual(metadata["speaker_review_status"], "needs_review")
        self.assertFalse(metadata["speaker_hidden"])
        self.assertIn("revived_at", metadata)

    def test_resolve_match_accept_merges_and_confirms_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(
                speaker_recognition={},
                speaker_sample_dir=root / "speaker_samples",
            )
            store = Store(root / "test.sqlite3")
            try:
                target = store.ensure_speaker_for_alias("obs:1:target", default_name="Speaker 1", label="Speaker 1")
                source = store.ensure_speaker_for_alias("obs:1:source", default_name="Speaker 2", label="Speaker 2")
                target_id = int(target["id"])
                source_id = int(source["id"])
                target_sample = store.add_speaker_sample(
                    speaker_id=target_id,
                    observation_id=None,
                    source_key="target-sample",
                    media_path=None,
                    sample_path=None,
                    start_seconds=0.0,
                    end_seconds=2.0,
                    transcript="target",
                    metadata={},
                )
                source_sample = store.add_speaker_sample(
                    speaker_id=source_id,
                    observation_id=None,
                    source_key="source-sample",
                    media_path=None,
                    sample_path=None,
                    start_seconds=2.0,
                    end_seconds=4.0,
                    transcript="source",
                    metadata={},
                )
                model = "speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb"
                store.add_speaker_embedding(speaker_id=target_id, sample_id=int(target_sample["id"]), model=model, vector=[1.0, 0.0], metadata={})
                store.add_speaker_embedding(speaker_id=source_id, sample_id=int(source_sample["id"]), model=model, vector=[0.99, 0.01], metadata={})
                store.record_speaker_match_decision(
                    source_speaker_id=source_id,
                    target_speaker_id=target_id,
                    sample_id=int(source_sample["id"]),
                    model=model,
                    score=0.95,
                    threshold=0.68,
                    status="candidate",
                )
                match_id = int(store.list_speaker_match_decisions()[0]["id"])

                result = resolve_speaker_match_decision(settings, store, match_id=match_id, action="accept")
                target_after = store.get_speaker(target_id)
                source_after = store.get_speaker(source_id)
                source_sample_after = store.get_speaker_sample(int(source_sample["id"]))
                match_after = store.list_speaker_match_decisions()[0]
                pending = pending_speaker_match_groups(store)
            finally:
                store.close()

        target_metadata = json.loads(target_after["metadata"])
        self.assertTrue(result.updated)
        self.assertTrue(result.merged)
        self.assertIsNone(source_after)
        self.assertEqual(source_sample_after["speaker_id"], target_id)
        self.assertEqual(target_metadata["speaker_review_status"], "confirmed")
        self.assertEqual(match_after["status"], "accepted")
        self.assertEqual(pending, [])

    def test_resolve_match_reject_keeps_source_visible_for_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(
                speaker_recognition={},
                speaker_sample_dir=root / "speaker_samples",
            )
            store = Store(root / "test.sqlite3")
            try:
                target = store.ensure_speaker_for_alias("obs:1:target", default_name="Speaker 1", label="Speaker 1")
                source = store.ensure_speaker_for_alias("obs:1:source", default_name="Speaker 2", label="Speaker 2")
                target_id = int(target["id"])
                source_id = int(source["id"])
                store.record_speaker_match_decision(
                    source_speaker_id=source_id,
                    target_speaker_id=target_id,
                    sample_id=None,
                    model="test-model",
                    score=0.7,
                    threshold=0.68,
                    status="candidate",
                )
                match_id = int(store.list_speaker_match_decisions()[0]["id"])

                result = resolve_speaker_match_decision(settings, store, match_id=match_id, action="reject")
                source_after = store.get_speaker(source_id)
                match_after = store.list_speaker_match_decisions()[0]
            finally:
                store.close()

        source_metadata = json.loads(source_after["metadata"])
        self.assertTrue(result.updated)
        self.assertFalse(result.merged)
        self.assertEqual(match_after["status"], "rejected")
        self.assertEqual(source_metadata["speaker_review_status"], "needs_review")
        self.assertFalse(source_metadata["speaker_hidden"])
        self.assertEqual(source_metadata["rejected_match_id"], match_id)

    def test_speaker_profile_payload_includes_representatives_and_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = Store(root / "test.sqlite3")
            try:
                store.upsert_observations(
                    [
                        Observation(
                            source="mobile",
                            kind="audio_segment",
                            source_key="profile-audio",
                            observed_at="2026-06-01T10:00:00+09:00",
                            title="Profile audio",
                            body="full transcript",
                            metadata={},
                        )
                    ]
                )
                observation_id = int(store.conn.execute("SELECT id FROM observations WHERE source_key = ?", ("profile-audio",)).fetchone()["id"])
                speaker = store.ensure_speaker_for_alias("obs:1:s1", default_name="Speaker 1", label="Speaker 1")
                speaker_id = int(speaker["id"])
                sample = store.add_speaker_sample(
                    speaker_id=speaker_id,
                    observation_id=observation_id,
                    source_key="profile-sample",
                    media_path=None,
                    sample_path=None,
                    start_seconds=1.0,
                    end_seconds=3.0,
                    transcript="profile sample",
                    metadata={"sample_confidence": 0.8, "status": "ok"},
                )
                store.add_speaker_embedding(
                    speaker_id=speaker_id,
                    sample_id=int(sample["id"]),
                    model="speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb",
                    vector=[1.0, 0.0],
                    metadata={},
                )
                refresh_representative_speaker_samples(store, speaker_ids=[speaker_id], per_speaker=1)

                profile = speaker_profile_payload(store, speaker_id, sample_limit=3, timeline_limit=3)
            finally:
                store.close()

        self.assertTrue(profile["ok"])
        self.assertEqual(profile["speaker"]["id"], speaker_id)
        self.assertEqual(profile["embedding_count"], 1)
        self.assertEqual(profile["confidence"]["level"], "insufficient_evidence")
        self.assertEqual(profile["representative_samples"][0]["id"], int(sample["id"]))
        self.assertEqual(profile["timeline"][0]["title"], "Profile audio")
        self.assertEqual(profile["timeline"][0]["transcript"], "profile sample")

    def test_auto_organize_merges_similar_and_hides_unmatched_auto_voices(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(
                speaker_recognition={"auto_merge_threshold": 0.68},
                speaker_sample_dir=root / "speaker_samples",
            )
            store = Store(root / "test.sqlite3")
            try:
                target = store.ensure_speaker_for_alias("obs:1:target", default_name="Speaker 1", label="Speaker 1")
                source = store.ensure_speaker_for_alias("obs:1:source", default_name="Speaker 2", label="Speaker 2")
                hidden = store.ensure_speaker_for_alias("obs:1:hidden", default_name="Speaker 3", label="Speaker 3")
                named_singleton = store.ensure_speaker_for_alias("obs:1:named", default_name="Speaker 4", label="Speaker 4")
                target_id = int(target["id"])
                source_id = int(source["id"])
                hidden_id = int(hidden["id"])
                named_id = int(named_singleton["id"])
                store.rename_speaker(target_id, "Alice")
                store.rename_speaker(named_id, "Bob")
                for speaker_id, key in [
                    (target_id, "target"),
                    (source_id, "source"),
                    (hidden_id, "hidden"),
                    (named_id, "named"),
                ]:
                    sample = store.add_speaker_sample(
                        speaker_id=speaker_id,
                        observation_id=None,
                        source_key=f"sample-{key}",
                        media_path=None,
                        sample_path=None,
                        start_seconds=0.0,
                        end_seconds=1.0,
                        transcript=key,
                        metadata={},
                    )
                    vector = {
                        "target": [1.0, 0.0],
                        "source": [0.9, 0.1],
                        "hidden": [0.0, 1.0],
                        "named": [0.0, -1.0],
                    }[key]
                    store.add_speaker_embedding(
                        speaker_id=speaker_id,
                        sample_id=int(sample["id"]),
                        model="speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb",
                        vector=vector,
                        metadata={},
                    )

                result = auto_organize_speakers(settings, store, threshold=0.68)
                merged = store.get_speaker(target_id)
                merged_metadata = json.loads(merged["metadata"])
                hidden_row = store.get_speaker(hidden_id)
                hidden_metadata = json.loads(hidden_row["metadata"])
                named_row = store.get_speaker(named_id)
                named_metadata = json.loads(named_row["metadata"])
                source_after = store.get_speaker(source_id)
                matches = store.list_speaker_match_decisions()
            finally:
                store.close()

        self.assertEqual(result.merged_speakers, 1)
        self.assertEqual(result.hidden_speakers, 1)
        self.assertIsNone(source_after)
        self.assertEqual(merged["display_name"], "Alice")
        self.assertEqual(merged_metadata["speaker_review_status"], "auto_merged_pending_review")
        self.assertEqual(merged_metadata["auto_merge_sources"][-1]["source_speaker_id"], source_id)
        self.assertEqual(hidden_metadata["speaker_review_status"], "low_similarity_hidden")
        self.assertTrue(hidden_metadata["speaker_hidden"])
        self.assertNotEqual(named_metadata.get("speaker_review_status"), "low_similarity_hidden")
        self.assertEqual(matches[0]["status"], "auto_merged_pending_review")

    def test_mark_speaker_review_status_confirms_and_unhides(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")
            try:
                speaker = store.ensure_speaker_for_alias("obs:1:s1", default_name="Speaker 1", label="Speaker 1")
                speaker_id = int(speaker["id"])
                hidden = mark_speaker_review_status(store, speaker_ids=[speaker_id], status="hidden")
                unhidden = mark_speaker_review_status(store, speaker_ids=[speaker_id], status="unhidden")
                confirmed = mark_speaker_review_status(store, speaker_ids=[speaker_id], status="confirmed")
                row = store.get_speaker(speaker_id)
                metadata = json.loads(row["metadata"])
            finally:
                store.close()

        self.assertEqual(hidden.updated, 1)
        self.assertEqual(unhidden.updated, 1)
        self.assertEqual(confirmed.updated, 1)
        self.assertEqual(metadata["speaker_review_status"], "confirmed")
        self.assertFalse(metadata["speaker_hidden"])

    def test_clip_bounds_stays_inside_single_speaker_segment(self):
        clip = clip_bounds(
            10.0,
            12.0,
            duration_seconds=30.0,
            sample_seconds=8.0,
            sample_min_seconds=0.5,
            boundary_guard_seconds=0.08,
        )
        self.assertEqual(clip, (10.08, 11.92))

        short_clip = clip_bounds(
            10.0,
            10.3,
            duration_seconds=30.0,
            sample_seconds=8.0,
            sample_min_seconds=0.5,
            boundary_guard_seconds=0.2,
        )
        self.assertEqual(short_clip, (10.0, 10.3))

        long_clip = clip_bounds(
            10.0,
            30.0,
            duration_seconds=40.0,
            sample_seconds=8.0,
            sample_min_seconds=0.5,
            boundary_guard_seconds=0.08,
        )
        self.assertIsNotNone(long_clip)
        assert long_clip is not None
        self.assertEqual(long_clip, (10.08, 18.08))
        self.assertAlmostEqual(long_clip[1] - long_clip[0], 8.0, places=3)

        centered_clip = clip_bounds(
            10.0,
            30.0,
            duration_seconds=40.0,
            sample_seconds=8.0,
            sample_min_seconds=0.5,
            boundary_guard_seconds=0.08,
            long_segment_anchor="center",
        )
        self.assertEqual(centered_clip, (16.0, 24.0))

    def test_reset_regroup_samples_detaches_then_auto_groups(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(
                speaker_recognition={
                    "embedding_backend": "speechbrain_ecapa",
                    "embedding_model": "speechbrain/spkrec-ecapa-voxceleb",
                    "auto_merge_threshold": 0.68,
                    "candidate_threshold": 0.68,
                    "sample_seconds": 8,
                    "sample_min_seconds": 0.5,
                },
                speaker_sample_dir=root / "speaker_samples",
            )
            store = Store(root / "context.sqlite3")
            try:
                speaker = store.ensure_speaker_for_alias("observation:1:Speaker 1", default_name="Speaker 1", label="Speaker 1")
                speaker_id = int(speaker["id"])
                store.rename_speaker(speaker_id, "Alice")
                first = store.add_speaker_sample(
                    speaker_id=speaker_id,
                    observation_id=None,
                    source_key="sample:1",
                    media_path=None,
                    sample_path=None,
                    start_seconds=1.0,
                    end_seconds=2.0,
                    transcript="first",
                    metadata={},
                )
                second = store.add_speaker_sample(
                    speaker_id=speaker_id,
                    observation_id=None,
                    source_key="sample:2",
                    media_path=None,
                    sample_path=None,
                    start_seconds=3.0,
                    end_seconds=4.0,
                    transcript="second",
                    metadata={},
                )
                model = "speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb"
                store.add_speaker_embedding(speaker_id=speaker_id, sample_id=int(first["id"]), model=model, vector=[1.0, 0.0], metadata={})
                store.add_speaker_embedding(speaker_id=speaker_id, sample_id=int(second["id"]), model=model, vector=[0.99, 0.01], metadata={})

                result = reset_and_auto_group_speaker_samples(
                    settings,
                    store,
                    threshold=0.68,
                    max_merges=10,
                    recut=False,
                    hide_unmatched=True,
                )
                speakers = store.list_speakers()
                samples = store.list_speaker_samples(None)
            finally:
                store.close()

        self.assertEqual(result.selected_samples, 2)
        self.assertEqual(result.reset_samples, 2)
        self.assertIsNotNone(result.organize)
        assert result.organize is not None
        self.assertEqual(result.organize.merged_speakers, 1)
        self.assertEqual(len(speakers), 1)
        self.assertEqual(len(samples), 2)
        self.assertNotEqual(int(samples[0]["speaker_id"]), speaker_id)

    def test_overlapping_speech_segments_are_not_used_for_samples(self):
        settings = SimpleNamespace(
            speaker_recognition={"enabled": True},
            speaker_sample_dir=Path("/tmp/speaker_samples"),
        )
        store = SimpleNamespace()
        metadata = {
            "audio_analysis": {
                "audio_timeline": {
                    "duration_seconds": 10.0,
                    "speech_segments": [
                        {
                            "start": 1.0,
                            "end": 4.0,
                            "speaker": "Speaker 1",
                            "overlap": True,
                            "overlap_speakers": ["Speaker 1", "Speaker 2"],
                            "text": "two people talking",
                        }
                    ],
                }
            }
        }

        result = process_speakers_for_observation(
            settings,
            store,
            observation_id=1,
            source_key="audio-1",
            media_path=None,
            metadata=metadata,
        )

        processing = result["audio_analysis"]["speaker_processing"]
        self.assertEqual(processing["status"], "skipped_overlapping_speech_segments")
        self.assertEqual(processing["overlapped_speech_segments"], 1)
        self.assertNotIn("speakers", result["audio_analysis"])

    def test_vad_chunk_speaker_labels_stay_scoped_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(
                speaker_recognition={"enabled": True},
                speaker_sample_dir=root / "speaker_samples",
            )
            store = Store(root / "context.sqlite3")
            try:
                store.upsert_observations(
                    [
                        Observation(
                            source="mobile",
                            kind="audio_segment",
                            source_key="audio-7",
                            observed_at="2026-06-01T10:00:00+09:00",
                            title="Audio segment",
                            body="transcript",
                            metadata={},
                        )
                    ]
                )
                observation_id = int(
                    store.conn.execute(
                        "SELECT id FROM observations WHERE source_key = ?",
                        ("audio-7",),
                    ).fetchone()["id"]
                )
                metadata = {
                    "audio_analysis": {
                        "audio_timeline": {
                            "duration_seconds": 20.0,
                            "speech_segments": [
                                {
                                    "start": 0.0,
                                    "end": 3.0,
                                    "speaker": "Speaker 1",
                                    "speaker_scope": "vad_chunk_001",
                                    "text": "hello from the first chunk",
                                },
                                {
                                    "start": 10.0,
                                    "end": 13.0,
                                    "speaker": "Speaker 1",
                                    "speaker_scope": "vad_chunk_002",
                                    "text": "hello from the second chunk",
                                },
                            ],
                        }
                    }
                }

                result = process_speakers_for_observation(
                    settings,
                    store,
                    observation_id=observation_id,
                    source_key="audio-7",
                    media_path=None,
                    metadata=metadata,
                )

                speakers = result["audio_analysis"]["speakers"]
                samples = store.list_speaker_samples(None)
                names = store.speaker_names_for_observation(observation_id)
            finally:
                store.close()

        self.assertEqual(len(speakers), 2)
        self.assertEqual(len(samples), 2)
        self.assertEqual({item["local_label"] for item in speakers}, {"Speaker 1"})
        self.assertEqual({item["speaker_scope"] for item in speakers}, {"vad_chunk_001", "vad_chunk_002"})
        self.assertNotIn("Speaker 1", names)
        self.assertEqual(names["vad_chunk_001:Speaker 1"]["display_name"], "Voice 001")
        self.assertEqual(names["vad_chunk_002:Speaker 1"]["display_name"], "Voice 002")

    def test_collapse_vad_chunk_speakers_merges_existing_chunk_local_voices(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(
                speaker_recognition={"collapse_vad_chunk_scopes": True},
                speaker_sample_dir=root / "speaker_samples",
                speaker_embedding_model_dir=root / "models",
            )
            store = Store(root / "context.sqlite3")
            try:
                first = store.ensure_speaker_for_alias(
                    "observation:99:vad_chunk_001:Speaker 1",
                    default_name="Speaker 1",
                    label="Speaker 1",
                    metadata={"speaker_scope": "vad_chunk_001"},
                )
                second = store.ensure_speaker_for_alias(
                    "observation:99:vad_chunk_002:Speaker 1",
                    default_name="Speaker 1",
                    label="Speaker 1",
                    metadata={"speaker_scope": "vad_chunk_002"},
                )
                store.add_speaker_sample(
                    speaker_id=int(first["id"]),
                    observation_id=None,
                    source_key="observation:99:vad_chunk_001:Speaker 1:sample:0.000:2.000",
                    media_path=None,
                    sample_path=None,
                    start_seconds=0.0,
                    end_seconds=2.0,
                    transcript="first",
                    metadata={"local_label": "vad_chunk_001:Speaker 1"},
                )
                store.add_speaker_sample(
                    speaker_id=int(second["id"]),
                    observation_id=None,
                    source_key="observation:99:vad_chunk_002:Speaker 1:sample:4.000:6.000",
                    media_path=None,
                    sample_path=None,
                    start_seconds=4.0,
                    end_seconds=6.0,
                    transcript="second",
                    metadata={"local_label": "vad_chunk_002:Speaker 1"},
                )

                preview = collapse_vad_chunk_speakers(settings, store)
                applied = collapse_vad_chunk_speakers(settings, store, apply=True)
                speakers = store.list_speakers()
                samples = store.list_speaker_samples(None)
                names = store.speaker_names_for_observation(99)
            finally:
                store.close()

        self.assertEqual(preview.merge_groups, 1)
        self.assertEqual(applied.merged_speakers, 1)
        self.assertEqual(len(speakers), 1)
        self.assertEqual(len(samples), 2)
        self.assertEqual(names["vad_chunk_001:Speaker 1"]["speaker_id"], names["vad_chunk_002:Speaker 1"]["speaker_id"])

    def test_speaker_sample_text_is_clipped_to_sample_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(
                speaker_recognition={"enabled": True, "sample_seconds": 8, "sample_min_seconds": 0.5},
                speaker_sample_dir=root / "speaker_samples",
            )
            store = Store(root / "context.sqlite3")
            long_text = " ".join(f"word{i:02d}" for i in range(40))
            try:
                store.upsert_observations(
                    [
                        Observation(
                            source="mobile",
                            kind="audio_segment",
                            source_key="audio-clip-text",
                            observed_at="2026-06-01T10:00:00+09:00",
                            title="Audio segment",
                            body="transcript",
                            metadata={},
                        )
                    ]
                )
                observation_id = int(store.conn.execute("SELECT id FROM observations WHERE source_key = ?", ("audio-clip-text",)).fetchone()["id"])
                metadata = {
                    "audio_analysis": {
                        "audio_timeline": {
                            "duration_seconds": 45.0,
                            "speech_segments": [
                                {"start": 0.0, "end": 45.0, "speaker": "Speaker 1", "text": long_text},
                            ],
                        }
                    }
                }

                process_speakers_for_observation(
                    settings,
                    store,
                    observation_id=observation_id,
                    source_key="audio-clip-text",
                    media_path=None,
                    metadata=metadata,
                )
                sample = store.list_speaker_samples(None)[0]
                sample_metadata = json.loads(sample["metadata"])
            finally:
                store.close()

        self.assertLess(len(sample["transcript"]), len(long_text))
        self.assertTrue(sample["transcript"].startswith("word00"))
        self.assertTrue(sample["transcript"].endswith("..."))
        self.assertNotIn("word39", sample["transcript"])
        self.assertEqual(sample_metadata["sample_transcript_mode"], "clip_window_excerpt")
        self.assertEqual(sample_metadata["source_segment_start"], 0.0)
        self.assertEqual(sample_metadata["source_segment_end"], 45.0)
        self.assertEqual(sample_metadata["clip_strategy"]["long_segment_anchor"], "start")

    def test_repair_speaker_sample_text_updates_existing_full_segment_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(
                speaker_recognition={"collapse_vad_chunk_scopes": True},
                speaker_sample_dir=root / "speaker_samples",
            )
            store = Store(root / "context.sqlite3")
            long_text = " ".join(f"token{i:02d}" for i in range(40))
            try:
                store.upsert_observations(
                    [
                        Observation(
                            source="mobile",
                            kind="audio_segment",
                            source_key="audio-repair-text",
                            observed_at="2026-06-01T10:00:00+09:00",
                            title="Audio segment",
                            body="transcript",
                            metadata={
                                "audio_analysis": {
                                    "audio_timeline": {
                                        "speech_segments": [
                                            {
                                                "start": 0.0,
                                                "end": 40.0,
                                                "speaker": "Speaker 1",
                                                "speaker_scope": "vad_chunk_001",
                                                "text": long_text,
                                            }
                                        ]
                                    }
                                }
                            },
                        )
                    ]
                )
                speaker = store.ensure_speaker_for_alias("observation:1:vad_chunk_001:Speaker 1", default_name="Speaker 1", label="Speaker 1", metadata={"speaker_scope": "vad_chunk_001"})
                observation_id = int(store.conn.execute("SELECT id FROM observations WHERE source_key = ?", ("audio-repair-text",)).fetchone()["id"])
                store.add_speaker_sample(
                    speaker_id=int(speaker["id"]),
                    observation_id=observation_id,
                    source_key="sample-repair-text",
                    media_path=None,
                    sample_path=None,
                    start_seconds=0.0,
                    end_seconds=8.0,
                    transcript=long_text,
                    metadata={"local_label": "vad_chunk_001:Speaker 1"},
                )
                preview = repair_speaker_sample_text(settings, store)
                applied = repair_speaker_sample_text(settings, store, apply=True)
                sample = store.list_speaker_samples(None)[0]
            finally:
                store.close()

        self.assertEqual(preview.repaired, 1)
        self.assertEqual(applied.repaired, 1)
        self.assertLess(len(sample["transcript"]), len(long_text))
        self.assertTrue(sample["transcript"].endswith("..."))

    def test_repair_speaker_sample_clips_recuts_long_segment_to_start_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "audio.m4a"
            source.write_bytes(b"audio")
            settings = SimpleNamespace(
                speaker_recognition={
                    "embedding_backend": "speechbrain_ecapa",
                    "embedding_model": "test-model",
                    "sample_seconds": 8,
                    "sample_min_seconds": 0.5,
                    "sample_boundary_guard_seconds": 0.08,
                    "sample_long_segment_anchor": "start",
                    "review_min_samples": 1,
                    "review_min_observations": 1,
                    "review_min_days": 1,
                    "review_min_confidence": 0.0,
                },
                audio_preprocessing={"enabled": True, "speaker_samples_enabled": True},
                speaker_sample_dir=root / "speaker_samples",
            )
            store = Store(root / "context.sqlite3")
            long_text = " ".join(f"word{i:02d}" for i in range(40))

            def fake_enhanced(_settings, _source, output, _start, _end):
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"sample")
                return True, {"status": "enhanced"}

            try:
                store.upsert_observations(
                    [
                        Observation(
                            source="mobile",
                            kind="audio_segment",
                            source_key="audio-repair-clips",
                            observed_at="2026-06-01T10:00:00+09:00",
                            title="Audio segment",
                            body="transcript",
                            metadata={
                                "resolved_media_path": str(source),
                                "audio_analysis": {
                                    "audio_timeline": {
                                        "duration_seconds": 45.0,
                                        "speech_segments": [
                                            {
                                                "start": 0.0,
                                                "end": 45.0,
                                                "speaker": "Speaker 1",
                                                "text": long_text,
                                            }
                                        ],
                                    }
                                },
                            },
                        )
                    ]
                )
                observation_id = int(store.conn.execute("SELECT id FROM observations WHERE source_key = ?", ("audio-repair-clips",)).fetchone()["id"])
                speaker = store.ensure_speaker_for_alias("observation:1:Speaker 1", default_name="Speaker 1", label="Speaker 1")
                sample = store.add_speaker_sample(
                    speaker_id=int(speaker["id"]),
                    observation_id=observation_id,
                    source_key="observation:1:Speaker 1:sample:18.500:26.500",
                    media_path=str(source),
                    sample_path=str(root / "old.m4a"),
                    start_seconds=18.5,
                    end_seconds=26.5,
                    transcript="middle words",
                    metadata={"local_label": "Speaker 1"},
                )
                with (
                    patch("wond.speakers.create_enhanced_sample_clip", side_effect=fake_enhanced),
                    patch("wond.speakers.audio_quality", return_value={"ok": True, "duration_seconds": 8.0}),
                    patch("wond.speakers.speaker_embedding", return_value=[1.0, 0.0]),
                ):
                    preview = repair_speaker_sample_clips(settings, store)
                    applied = repair_speaker_sample_clips(settings, store, apply=True)
                updated = store.get_speaker_sample(int(sample["id"]))
                updated_metadata = json.loads(updated["metadata"])
                embedding_rows = store.speaker_embedding_rows(
                    model="speechbrain_ecapa:test-model",
                    speaker_id=int(speaker["id"]),
                )
            finally:
                store.close()

        self.assertEqual(preview.repaired, 1)
        self.assertEqual(applied.repaired, 1)
        self.assertEqual(applied.reembedded, 1)
        self.assertEqual(float(updated["start_seconds"]), 0.08)
        self.assertEqual(float(updated["end_seconds"]), 8.08)
        self.assertEqual(updated["source_key"], f"observation:{observation_id}:Speaker 1:sample:0.080:8.080")
        self.assertTrue(updated["transcript"].startswith("word00"))
        self.assertEqual(updated_metadata["sample_clip_repair"]["anchor"], "start")
        self.assertEqual(len(embedding_rows), 1)

    def test_clean_speaker_sample_uses_enhanced_audio_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "audio.m4a"
            source.write_bytes(b"audio")
            settings = SimpleNamespace(
                speaker_recognition={"enabled": True, "sample_dir": "speaker_samples"},
                audio_preprocessing={"enabled": True, "speaker_samples_enabled": True},
                speaker_sample_dir=root / "speaker_samples",
            )
            store = Store(root / "context.sqlite3")
            try:
                store.upsert_observations(
                    [
                        Observation(
                            source="mobile",
                            kind="audio_segment",
                            source_key="audio-8",
                            observed_at="2026-06-01T10:00:00+09:00",
                            title="Audio segment",
                            body="transcript",
                            metadata={},
                        )
                    ]
                )
                observation_id = int(store.conn.execute("SELECT id FROM observations WHERE source_key = ?", ("audio-8",)).fetchone()["id"])
                metadata = {
                    "audio_analysis": {
                        "audio_timeline": {
                            "duration_seconds": 5.0,
                            "speech_segments": [
                                {"start": 0.0, "end": 3.0, "speaker": "Speaker 1", "text": "clean voice"},
                            ],
                        }
                    }
                }
                with (
                    patch("wond.speakers.create_enhanced_sample_clip", return_value=(True, {"status": "enhanced"})),
                    patch("wond.speakers.audio_quality", return_value={"ok": True, "duration_seconds": 3.0}),
                ):
                    process_speakers_for_observation(
                        settings,
                        store,
                        observation_id=observation_id,
                        source_key="audio-8",
                        media_path=source,
                        metadata=metadata,
                    )
                sample = store.list_speaker_samples(None)[0]
                sample_metadata = json.loads(sample["metadata"])
            finally:
                store.close()

        self.assertEqual(sample_metadata["status"], "ok")
        self.assertEqual(sample_metadata["audio_preprocessing"]["status"], "enhanced")

    def test_overlap_candidate_sample_uses_separation_and_quality_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "audio.m4a"
            source.write_bytes(b"audio")
            settings = SimpleNamespace(
                speaker_recognition={"enabled": True, "sample_dir": "speaker_samples"},
                audio_preprocessing={
                    "enabled": True,
                    "speaker_samples_enabled": True,
                    "overlap_separation_enabled": True,
                },
                speaker_sample_dir=root / "speaker_samples",
            )
            store = Store(root / "context.sqlite3")
            try:
                store.upsert_observations(
                    [
                        Observation(
                            source="mobile",
                            kind="audio_segment",
                            source_key="audio-9",
                            observed_at="2026-06-01T10:00:00+09:00",
                            title="Audio segment",
                            body="transcript",
                            metadata={},
                        )
                    ]
                )
                observation_id = int(store.conn.execute("SELECT id FROM observations WHERE source_key = ?", ("audio-9",)).fetchone()["id"])
                metadata = {
                    "audio_analysis": {
                        "audio_timeline": {
                            "duration_seconds": 8.0,
                            "speech_segments": [
                                {"start": 0.0, "end": 2.0, "speaker": "Speaker 1", "text": "clean anchor"},
                                {
                                    "start": 2.0,
                                    "end": 5.0,
                                    "speaker": "Speaker 1",
                                    "overlap": True,
                                    "overlap_speakers": ["Speaker 1", "Speaker 2"],
                                    "text": "overlap voices",
                                },
                            ],
                        }
                    }
                }
                with (
                    patch("wond.speakers.create_enhanced_sample_clip", return_value=(True, {"status": "enhanced"})),
                    patch("wond.speakers.create_overlap_candidate_clip", return_value=(True, {"status": "separated", "backend": "test"})),
                    patch("wond.speakers.audio_quality", return_value={"ok": True, "duration_seconds": 3.0}),
                ):
                    result = process_speakers_for_observation(
                        settings,
                        store,
                        observation_id=observation_id,
                        source_key="audio-9",
                        media_path=source,
                        metadata=metadata,
                    )
                candidates = result["audio_analysis"]["speaker_overlap_candidates"]
                samples = store.list_speaker_samples(None)
                sample_metadatas = [json.loads(sample["metadata"]) for sample in samples]
            finally:
                store.close()

        self.assertEqual(candidates[0]["status"], "ok")
        self.assertTrue(any(item.get("sample_role") == "overlap_separated_candidate" for item in sample_metadatas))


if __name__ == "__main__":
    unittest.main()
