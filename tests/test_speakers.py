import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from datetime import date

from wond.speaker_identity import best_existing_speaker_match, update_speaker_identity_for_sample
from wond.speakers import (
    auto_organize_speakers,
    best_sample_segment,
    collapse_vad_chunk_speakers,
    clip_bounds,
    detach_speaker_sample,
    mark_speaker_review_status,
    mark_speaker_audio_protection,
    mark_speaker_sample_audio_protection,
    pending_speaker_match_groups,
    prune_speaker_sample_audio,
    process_speakers_for_observation,
    refresh_speaker_sample_confidences,
    refresh_representative_speaker_samples,
    repair_missing_speaker_embeddings,
    repair_speaker_sample_clips,
    repair_speaker_sample_text,
    resolve_speaker_match_decision,
    reset_and_auto_group_speaker_samples,
    revive_hidden_speakers,
    split_speaker_sample,
    speaker_sample_clip_plan,
    speaker_sample_plans_for_segments,
    speaker_sample_seconds,
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
            speaker_recognition={"enabled": True, "sample_unlabeled_speech": False},
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

    def test_split_speaker_sample_creates_child_samples_and_archives_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(
                speaker_recognition={"sample_min_seconds": 0.5},
                audio_preprocessing={"enabled": True, "speaker_samples_enabled": True},
                speaker_sample_dir=root / "speaker_samples",
            )
            store = Store(root / "test.sqlite3")

            def fake_extract(_settings, _source, output, start, end):
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(f"{start}-{end}".encode())
                return {
                    "status": "ok",
                    "error": None,
                    "sample_path": str(output),
                    "audio_preprocessing": {"status": "enhanced"},
                    "quality": {"ok": True, "duration_seconds": end - start},
                }

            try:
                speaker = store.ensure_speaker_for_alias("obs:1:s1", default_name="Speaker 1", label="Speaker 1")
                speaker_id = int(speaker["id"])
                sample_dir = root / "speaker_samples" / f"speaker-{speaker_id:06d}"
                sample_dir.mkdir(parents=True)
                sample_file = sample_dir / "mixed.m4a"
                sample_file.write_bytes(b"mixed audio")
                sample = store.add_speaker_sample(
                    speaker_id=speaker_id,
                    observation_id=None,
                    source_key="mixed-sample",
                    media_path=None,
                    sample_path=str(sample_file),
                    start_seconds=10.0,
                    end_seconds=16.0,
                    transcript="first speaker then second speaker",
                    metadata={"status": "ok"},
                )
                store.add_speaker_embedding(
                    speaker_id=speaker_id,
                    sample_id=int(sample["id"]),
                    model="speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb",
                    vector=[0.1, 0.2],
                    metadata={},
                )

                with (
                    patch("wond.speakers.extract_quality_checked_sample_clip", side_effect=fake_extract),
                    patch("wond.speakers.speaker_embedding", side_effect=[[1.0, 0.0], [0.0, 1.0]]),
                ):
                    result = split_speaker_sample(settings, store, sample_id=int(sample["id"]), cut_points=[3.0])
                parent = store.get_speaker_sample(int(sample["id"]))
                parent_metadata = json.loads(parent["metadata"])
                children = [store.get_speaker_sample(child_id) for child_id in result.child_sample_ids]
                child_metadatas = [json.loads(child["metadata"]) for child in children]
                parent_embeddings = store.conn.execute(
                    "SELECT * FROM speaker_embeddings WHERE sample_id = ?",
                    (int(sample["id"]),),
                ).fetchall()
                child_speaker_ids = {int(child["speaker_id"]) for child in children}
                child_files_exist = all(Path(child["sample_path"]).exists() for child in children)
            finally:
                store.close()

        self.assertFalse(result.failed)
        self.assertEqual(len(result.child_sample_ids), 2)
        self.assertEqual(len(child_speaker_ids), 2)
        self.assertEqual(parent_metadata["sample_role"], "mixed_parent_archived")
        self.assertEqual(parent_metadata["manual_split_child_sample_ids"], result.child_sample_ids)
        self.assertEqual(parent_embeddings, [])
        self.assertEqual([float(child["start_seconds"]) for child in children], [10.0, 13.0])
        self.assertEqual([float(child["end_seconds"]) for child in children], [13.0, 16.0])
        self.assertTrue(child_files_exist)
        self.assertEqual({metadata["sample_role"] for metadata in child_metadatas}, {"manual_split_child"})

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
        self.assertEqual(first_metadata["sample_confidence_basis"], "leave_one_out_robust_profile")
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
                    metadata={"sample_confidence": 0.95, "representative_sample": True},
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
                    metadata={"sample_confidence": 0.95, "representative_sample": True},
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
                store.update_speaker_identity_status(speaker_id, status="provisional", confidence=0.95)
                profile_settings = SimpleNamespace(
                    speaker_recognition={
                        "confirmed_profile_matching_enabled": True,
                        "confirmed_profile_max_prototypes": 4,
                        "confirmed_profile_min_samples": 2,
                    }
                )
                generic_profile_settings = SimpleNamespace(
                    speaker_recognition={
                        "confirmed_profile_matching_enabled": False,
                        "speaker_profile_max_prototypes": 4,
                    }
                )

                profile_match = best_existing_speaker_match(
                    profile_settings,
                    store,
                    model=model,
                    speaker_id=999,
                    vector=[1.0, 0.0],
                )
                generic_profile_match = best_existing_speaker_match(
                    generic_profile_settings,
                    store,
                    model=model,
                    speaker_id=999,
                    vector=[1.0, 0.0],
                )
            finally:
                store.close()

        self.assertIsNotNone(profile_match)
        self.assertIsNotNone(generic_profile_match)
        assert profile_match is not None
        assert generic_profile_match is not None
        self.assertEqual(profile_match.speaker_id, speaker_id)
        self.assertEqual(profile_match.matcher, "confirmed_profile")
        self.assertGreater(profile_match.score, 0.99)
        self.assertGreater(profile_match.prototype_count, 1)
        self.assertEqual(generic_profile_match.matcher, "speaker_profile")
        self.assertGreater(generic_profile_match.score, 0.99)
        self.assertGreater(generic_profile_match.prototype_count, 1)

    def test_speaker_profile_match_ignores_outlier_embedding(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "context.sqlite3")
            model = "speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb"
            try:
                speaker = store.ensure_speaker_for_alias("obs:1:s1", default_name="Speaker 1", label="Speaker 1")
                speaker_id = int(speaker["id"])
                for index, vector in enumerate(([1.0, 0.0], [0.999, 0.001], [0.0, 1.0]), start=1):
                    sample = store.add_speaker_sample(
                        speaker_id=speaker_id,
                        observation_id=None,
                        source_key=f"sample-profile-{index}",
                        media_path=None,
                        sample_path=None,
                        start_seconds=float(index),
                        end_seconds=float(index) + 1.0,
                        transcript=f"voice {index}",
                        metadata={},
                    )
                    store.add_speaker_embedding(
                        speaker_id=speaker_id,
                        sample_id=int(sample["id"]),
                        model=model,
                        vector=vector,
                        metadata={},
                    )
                store.update_speaker_identity_status(speaker_id, status="provisional", confidence=0.95)
                settings = SimpleNamespace(
                    speaker_recognition={
                        "auto_merge_threshold": 0.68,
                        "candidate_threshold": 0.68,
                        "speaker_profile_max_prototypes": 4,
                        "speaker_profile_outlier_min_similarity": 0.55,
                    }
                )

                match = best_existing_speaker_match(
                    settings,
                    store,
                    model=model,
                    speaker_id=999,
                    vector=[1.0, 0.0],
                )
            finally:
                store.close()

        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.speaker_id, speaker_id)
        self.assertEqual(match.matcher, "speaker_profile")
        self.assertGreater(match.score, 0.99)
        self.assertGreater(match.prototype_count, 1)
        self.assertEqual(match.trusted_sample_count, 2)

    def test_confirmed_profile_match_skips_low_consistency_speaker(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "context.sqlite3")
            model = "speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb"
            try:
                speaker = store.ensure_speaker_for_alias("obs:1:s1", default_name="Speaker 1", label="Speaker 1")
                speaker_id = int(speaker["id"])
                for index, vector in enumerate(([1.0, 0.0], [0.99, 0.01]), start=1):
                    sample = store.add_speaker_sample(
                        speaker_id=speaker_id,
                        observation_id=None,
                        source_key=f"sample-{index}",
                        media_path=None,
                        sample_path=None,
                        start_seconds=float(index),
                        end_seconds=float(index) + 1.0,
                        transcript=f"voice {index}",
                        metadata={},
                    )
                    store.add_speaker_embedding(
                        speaker_id=speaker_id,
                        sample_id=int(sample["id"]),
                        model=model,
                        vector=vector,
                        metadata={},
                    )
                mark_speaker_review_status(store, speaker_ids=[speaker_id], status="confirmed")
                store.update_speaker_identity_status(speaker_id, status="provisional", confidence=0.2)
                settings = SimpleNamespace(
                    speaker_recognition={
                        "auto_merge_threshold": 0.6,
                        "candidate_threshold": 0.6,
                        "confirmed_profile_matching_enabled": True,
                    }
                )

                match = best_existing_speaker_match(
                    settings,
                    store,
                    model=model,
                    speaker_id=999,
                    vector=[1.0, 0.0],
                )
            finally:
                store.close()

        self.assertIsNone(match)

    def test_existing_match_skips_needs_review_named_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "test.sqlite3")
            try:
                target = store.ensure_speaker_for_alias("obs:1:target", default_name="Speaker 1", label="Speaker 1")
                target_id = int(target["id"])
                store.rename_speaker(target_id, "Alice")
                sample = store.add_speaker_sample(
                    speaker_id=target_id,
                    observation_id=None,
                    source_key="target-sample",
                    media_path=None,
                    sample_path=None,
                    start_seconds=0.0,
                    end_seconds=1.0,
                    transcript="target",
                    metadata={},
                )
                model = "speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb"
                store.add_speaker_embedding(
                    speaker_id=target_id,
                    sample_id=int(sample["id"]),
                    model=model,
                    vector=[1.0, 0.0],
                    metadata={},
                )
                mark_speaker_review_status(store, speaker_ids=[target_id], status="unhidden")
                settings = SimpleNamespace(speaker_recognition={"candidate_threshold": 0.68})

                match = best_existing_speaker_match(settings, store, model=model, speaker_id=999, vector=[1.0, 0.0])
            finally:
                store.close()

        self.assertIsNone(match)

    def test_identity_update_does_not_auto_merge_into_needs_review_named_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample_dir = root / "speaker_samples" / "speaker-000002"
            sample_dir.mkdir(parents=True)
            sample_file = sample_dir / "sample.m4a"
            sample_file.write_bytes(b"audio")
            settings = SimpleNamespace(
                speaker_recognition={
                    "auto_merge_threshold": 0.68,
                    "candidate_threshold": 0.68,
                },
                speaker_sample_dir=root / "speaker_samples",
            )
            store = Store(root / "test.sqlite3")
            try:
                target = store.ensure_speaker_for_alias("obs:1:target", default_name="Speaker 1", label="Speaker 1")
                source = store.ensure_speaker_for_alias("obs:1:source", default_name="Speaker 2", label="Speaker 2")
                target_id = int(target["id"])
                source_id = int(source["id"])
                store.rename_speaker(target_id, "Alice")
                target_sample = store.add_speaker_sample(
                    speaker_id=target_id,
                    observation_id=None,
                    source_key="target-sample",
                    media_path=None,
                    sample_path=None,
                    start_seconds=0.0,
                    end_seconds=1.0,
                    transcript="target",
                    metadata={},
                )
                source_sample = store.add_speaker_sample(
                    speaker_id=source_id,
                    observation_id=None,
                    source_key="source-sample",
                    media_path=None,
                    sample_path=str(sample_file),
                    start_seconds=0.0,
                    end_seconds=1.0,
                    transcript="source",
                    metadata={},
                )
                model = "speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb"
                store.add_speaker_embedding(
                    speaker_id=target_id,
                    sample_id=int(target_sample["id"]),
                    model=model,
                    vector=[1.0, 0.0],
                    metadata={},
                )
                mark_speaker_review_status(store, speaker_ids=[target_id], status="unhidden")

                with patch("wond.speaker_identity.speaker_embedding", return_value=[1.0, 0.0]):
                    result = update_speaker_identity_for_sample(
                        settings,
                        store,
                        speaker_id=source_id,
                        sample_id=int(source_sample["id"]),
                        sample_path=str(sample_file),
                    )
                source_after = store.get_speaker(source_id)
                target_after = store.get_speaker(target_id)
                matches = store.list_speaker_match_decisions()
            finally:
                store.close()

        self.assertEqual(result.status, "new_identity")
        self.assertIsNotNone(source_after)
        self.assertIsNotNone(target_after)
        self.assertEqual(len(matches), 0)

    def test_identity_update_auto_learns_trusted_confirmed_profile_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample_dir = root / "speaker_samples" / "speaker-000002"
            sample_dir.mkdir(parents=True)
            sample_file = sample_dir / "sample.m4a"
            sample_file.write_bytes(b"audio")
            settings = SimpleNamespace(
                speaker_recognition={
                    "auto_merge_threshold": 0.6,
                    "candidate_threshold": 0.6,
                    "confirmed_profile_matching_enabled": True,
                    "confirmed_profile_min_samples": 2,
                    "confirmed_profile_auto_merge_threshold": 0.78,
                },
                speaker_sample_dir=root / "speaker_samples",
            )
            store = Store(root / "test.sqlite3")
            try:
                target = store.ensure_speaker_for_alias("obs:1:target", default_name="Speaker 1", label="Speaker 1")
                source = store.ensure_speaker_for_alias("obs:1:source", default_name="Speaker 2", label="Speaker 2")
                target_id = int(target["id"])
                source_id = int(source["id"])
                store.rename_speaker(target_id, "Alice")
                target_samples = [
                    store.add_speaker_sample(
                        speaker_id=target_id,
                        observation_id=None,
                        source_key=f"target-sample-{index}",
                        media_path=None,
                        sample_path=None,
                        start_seconds=float(index),
                        end_seconds=float(index) + 1.0,
                        transcript=f"target {index}",
                        metadata={"sample_confidence": 0.95, "representative_sample": True},
                    )
                    for index in range(2)
                ]
                source_sample = store.add_speaker_sample(
                    speaker_id=source_id,
                    observation_id=None,
                    source_key="source-sample",
                    media_path=None,
                    sample_path=str(sample_file),
                    start_seconds=0.0,
                    end_seconds=1.0,
                    transcript="source",
                    metadata={},
                )
                model = "speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb"
                for sample, vector in zip(target_samples, ([1.0, 0.0], [0.99, 0.01])):
                    store.add_speaker_embedding(
                        speaker_id=target_id,
                        sample_id=int(sample["id"]),
                        model=model,
                        vector=vector,
                        metadata={},
                    )
                mark_speaker_review_status(store, speaker_ids=[target_id], status="confirmed")
                store.update_speaker_identity_status(target_id, status="provisional", confidence=0.95)

                with patch("wond.speaker_identity.speaker_embedding", return_value=[1.0, 0.0]):
                    result = update_speaker_identity_for_sample(
                        settings,
                        store,
                        speaker_id=source_id,
                        sample_id=int(source_sample["id"]),
                        sample_path=str(sample_file),
                    )
                source_after = store.get_speaker(source_id)
                target_after = store.get_speaker(target_id)
                source_sample_after = store.get_speaker_sample(int(source_sample["id"]))
                matches = store.list_speaker_match_decisions()
                speaker_counts = {int(row["id"]): int(row["sample_count"] or 0) for row in store.list_speakers()}
            finally:
                store.close()

        self.assertEqual(result.status, "auto_merged")
        self.assertEqual(result.target_speaker_id, target_id)
        self.assertIsNone(source_after)
        self.assertIsNotNone(target_after)
        self.assertEqual(source_sample_after["speaker_id"], target_id)
        self.assertEqual(speaker_counts[target_id], 3)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["status"], "auto_merged")
        metadata = json.loads(matches[0]["metadata"])
        self.assertEqual(metadata["decision"], "trusted_confirmed_profile_above_auto_learn_threshold")
        self.assertTrue(metadata["confirmed_profile"])
        self.assertTrue(metadata["trusted_profile"])

    def test_identity_update_does_not_auto_merge_low_confidence_source_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample_dir = root / "speaker_samples" / "speaker-000002"
            sample_dir.mkdir(parents=True)
            sample_file = sample_dir / "sample.m4a"
            sample_file.write_bytes(b"audio")
            settings = SimpleNamespace(
                speaker_recognition={
                    "auto_merge_threshold": 0.6,
                    "candidate_threshold": 0.6,
                    "auto_merge_min_sample_confidence": 0.55,
                },
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
                    end_seconds=1.0,
                    transcript="target",
                    metadata={},
                )
                source_sample = store.add_speaker_sample(
                    speaker_id=source_id,
                    observation_id=None,
                    source_key="source-sample",
                    media_path=None,
                    sample_path=str(sample_file),
                    start_seconds=0.0,
                    end_seconds=1.0,
                    transcript="source",
                    metadata={"sample_confidence": 0.2},
                )
                model = "speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb"
                store.add_speaker_embedding(
                    speaker_id=target_id,
                    sample_id=int(target_sample["id"]),
                    model=model,
                    vector=[1.0, 0.0],
                    metadata={},
                )

                with patch("wond.speaker_identity.speaker_embedding", return_value=[1.0, 0.0]):
                    result = update_speaker_identity_for_sample(
                        settings,
                        store,
                        speaker_id=source_id,
                        sample_id=int(source_sample["id"]),
                        sample_path=str(sample_file),
                    )
                source_after = store.get_speaker(source_id)
                target_after = store.get_speaker(target_id)
                matches = store.list_speaker_match_decisions()
            finally:
                store.close()

        self.assertEqual(result.status, "candidate")
        self.assertIsNotNone(source_after)
        self.assertIsNotNone(target_after)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["status"], "candidate")
        metadata = json.loads(matches[0]["metadata"])
        self.assertEqual(metadata["decision"], "manual_review_required_for_low_confidence_sample")

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
        self.assertEqual(result.representative_samples, 1)
        self.assertTrue(high_metadata["representative_sample"])
        self.assertEqual(high_metadata["representative_rank"], 1)
        self.assertNotIn("representative_sample", mid_metadata)
        self.assertNotIn("representative_sample", low_metadata)
        self.assertEqual(speaker_metadata["representative_sample_ids"], [int(high["id"])])

    def test_refresh_representative_samples_clears_existing_low_confidence_representatives(self):
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
                    metadata={
                        "sample_confidence": 0.2,
                        "status": "ok",
                        "representative_sample": True,
                        "representative_rank": 1,
                    },
                )

                result = refresh_representative_speaker_samples(store, speaker_ids=[speaker_id], per_speaker=3)
                low_metadata = json.loads(store.get_speaker_sample(int(low["id"]))["metadata"])
                speaker_metadata = json.loads(store.get_speaker(speaker_id)["metadata"])
            finally:
                store.close()

        self.assertEqual(result.representative_samples, 0)
        self.assertNotIn("representative_sample", low_metadata)
        self.assertNotIn("representative_rank", low_metadata)
        self.assertEqual(speaker_metadata["representative_sample_ids"], [])

    def test_prune_speaker_sample_audio_keeps_voiceprint_and_recycles_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            sample_dir = data_dir / "speaker_samples" / "speaker-000001"
            sample_dir.mkdir(parents=True)
            sample_file = sample_dir / "sample.m4a"
            sample_file.write_bytes(b"audio")
            settings = SimpleNamespace(
                data_dir=data_dir,
                recycle_bin={"enabled": True, "dir": "recycle_bin", "retention_hours": 24},
                speaker_recognition={
                    "sample_audio_retention_days": 30,
                    "sample_audio_cleanup_require_embedding": True,
                },
                speaker_sample_dir=data_dir / "speaker_samples",
                timezone="Asia/Tokyo",
            )
            store = Store(root / "context.sqlite3")
            try:
                speaker = store.ensure_speaker_for_alias("obs:1:s1", default_name="Speaker 1", label="Speaker 1")
                speaker_id = int(speaker["id"])
                sample = store.add_speaker_sample(
                    speaker_id=speaker_id,
                    observation_id=None,
                    source_key="sample:old",
                    media_path=None,
                    sample_path=str(sample_file),
                    start_seconds=0.0,
                    end_seconds=1.0,
                    transcript="old sample",
                    metadata={},
                )
                sample_id = int(sample["id"])
                store.add_speaker_embedding(
                    speaker_id=speaker_id,
                    sample_id=sample_id,
                    model="speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb",
                    vector=[1.0, 0.0],
                    metadata={},
                )
                store.conn.execute(
                    "UPDATE speaker_samples SET created_at = ? WHERE id = ?",
                    ("2026-01-01T00:00:00+09:00", sample_id),
                )
                store.conn.commit()

                preview = prune_speaker_sample_audio(
                    settings,
                    store,
                    today=date(2026, 6, 9),
                    dry_run=True,
                    older_than_days=30,
                )
                applied = prune_speaker_sample_audio(
                    settings,
                    store,
                    today=date(2026, 6, 9),
                    dry_run=False,
                    older_than_days=30,
                )
                sample_after = store.get_speaker_sample(sample_id)
                metadata_after = json.loads(sample_after["metadata"])
                embeddings = store.speaker_embedding_rows(
                    model="speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb",
                    speaker_id=speaker_id,
                )
                sample_file_exists_after_apply = sample_file.exists()
                recycled_files = [path for path in (data_dir / "recycle_bin").rglob("*") if path.is_file() and path.suffix != ".json"]
                recycled_contents = recycled_files[0].read_bytes() if recycled_files else None
            finally:
                store.close()

        self.assertEqual(preview.candidate_samples, 1)
        self.assertEqual(preview.pruned_samples, 0)
        self.assertEqual(applied.pruned_samples, 1)
        self.assertFalse(sample_file_exists_after_apply)
        self.assertIsNone(sample_after["sample_path"])
        self.assertTrue(metadata_after["voiceprint_retained"])
        self.assertEqual(metadata_after["audio_pruned_reason"], "speaker_sample_audio_retention")
        self.assertEqual(len(embeddings), 1)
        self.assertEqual(len(recycled_files), 1)
        self.assertEqual(recycled_contents, b"audio")

    def test_prune_speaker_sample_audio_respects_sample_and_speaker_protection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            sample_root = data_dir / "speaker_samples"
            settings = SimpleNamespace(
                data_dir=data_dir,
                recycle_bin={"enabled": True, "dir": "recycle_bin", "retention_hours": 24},
                speaker_recognition={
                    "sample_audio_retention_days": 30,
                    "sample_audio_cleanup_require_embedding": True,
                },
                speaker_sample_dir=sample_root,
                timezone="Asia/Tokyo",
            )
            store = Store(root / "context.sqlite3")
            try:
                sample_ids = []
                speaker_ids = []
                for index in range(2):
                    speaker = store.ensure_speaker_for_alias(
                        f"obs:1:s{index}",
                        default_name=f"Speaker {index + 1}",
                        label=f"Speaker {index + 1}",
                    )
                    speaker_id = int(speaker["id"])
                    speaker_ids.append(speaker_id)
                    sample_dir = sample_root / f"speaker-{speaker_id:06d}"
                    sample_dir.mkdir(parents=True)
                    sample_file = sample_dir / f"sample-{index}.m4a"
                    sample_file.write_bytes(f"audio-{index}".encode())
                    sample = store.add_speaker_sample(
                        speaker_id=speaker_id,
                        observation_id=None,
                        source_key=f"sample:protected:{index}",
                        media_path=None,
                        sample_path=str(sample_file),
                        start_seconds=0.0,
                        end_seconds=1.0,
                        transcript=f"protected {index}",
                        metadata={},
                    )
                    sample_id = int(sample["id"])
                    sample_ids.append(sample_id)
                    store.add_speaker_embedding(
                        speaker_id=speaker_id,
                        sample_id=sample_id,
                        model="speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb",
                        vector=[1.0, float(index)],
                        metadata={},
                    )
                    store.conn.execute(
                        "UPDATE speaker_samples SET created_at = ? WHERE id = ?",
                        ("2026-01-01T00:00:00+09:00", sample_id),
                    )
                store.conn.commit()
                sample_protect = mark_speaker_sample_audio_protection(store, sample_ids=[sample_ids[0]], protected=True)
                speaker_protect = mark_speaker_audio_protection(store, speaker_ids=[speaker_ids[1]], protected=True)

                result = prune_speaker_sample_audio(
                    settings,
                    store,
                    today=date(2026, 6, 9),
                    dry_run=False,
                    older_than_days=30,
                )
                samples_after = [store.get_speaker_sample(sample_id) for sample_id in sample_ids]
            finally:
                store.close()

        self.assertEqual(sample_protect.updated, 1)
        self.assertEqual(speaker_protect.updated, 1)
        self.assertEqual(result.protected_samples, 2)
        self.assertEqual(result.pruned_samples, 0)
        self.assertTrue(all(sample["sample_path"] for sample in samples_after))

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
                target_name = str(target["display_name"])
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
        self.assertEqual(merged["display_name"], target_name)
        self.assertEqual(merged_metadata["speaker_review_status"], "auto_merged_pending_review")
        self.assertEqual(merged_metadata["auto_merge_sources"][-1]["source_speaker_id"], source_id)
        self.assertEqual(hidden_metadata["speaker_review_status"], "low_similarity_hidden")
        self.assertTrue(hidden_metadata["speaker_hidden"])
        self.assertNotEqual(named_metadata.get("speaker_review_status"), "low_similarity_hidden")
        self.assertEqual(matches[0]["status"], "auto_merged_pending_review")

    def test_auto_organize_queues_high_sample_unmatched_speaker_for_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(
                speaker_recognition={"auto_merge_threshold": 0.68, "review_min_samples": 3},
                speaker_sample_dir=root / "speaker_samples",
            )
            store = Store(root / "test.sqlite3")
            try:
                high_evidence = store.ensure_speaker_for_alias(
                    "obs:1:high-evidence",
                    default_name="Speaker 1",
                    label="Speaker 1",
                )
                low_evidence = store.ensure_speaker_for_alias(
                    "obs:1:low-evidence",
                    default_name="Speaker 2",
                    label="Speaker 2",
                )
                high_id = int(high_evidence["id"])
                low_id = int(low_evidence["id"])
                for index in range(3):
                    store.add_speaker_sample(
                        speaker_id=high_id,
                        observation_id=None,
                        source_key=f"high-sample-{index}",
                        media_path=None,
                        sample_path=None,
                        start_seconds=float(index),
                        end_seconds=float(index) + 1.0,
                        transcript=f"high {index}",
                        metadata={},
                    )
                store.add_speaker_sample(
                    speaker_id=low_id,
                    observation_id=None,
                    source_key="low-sample",
                    media_path=None,
                    sample_path=None,
                    start_seconds=0.0,
                    end_seconds=1.0,
                    transcript="low",
                    metadata={},
                )

                result = auto_organize_speakers(settings, store, threshold=0.68)
                high_after = store.get_speaker(high_id)
                low_after = store.get_speaker(low_id)
                high_metadata = json.loads(high_after["metadata"])
                low_metadata = json.loads(low_after["metadata"])
            finally:
                store.close()

        self.assertEqual(result.evidence_review_speakers, 1)
        self.assertEqual(result.hidden_speakers, 1)
        self.assertEqual(high_metadata["speaker_review_status"], "needs_review")
        self.assertFalse(high_metadata["speaker_hidden"])
        self.assertEqual(high_metadata["needs_review_sample_count"], 3)
        self.assertEqual(high_metadata["needs_review_min_samples"], 3)
        self.assertEqual(low_metadata["speaker_review_status"], "low_similarity_hidden")
        self.assertTrue(low_metadata["speaker_hidden"])

    def test_auto_organize_allows_stable_chain_before_pending_review_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(
                speaker_recognition={"auto_merge_threshold": 0.68},
                speaker_sample_dir=root / "speaker_samples",
            )
            store = Store(root / "test.sqlite3")
            try:
                model = "speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb"
                speaker_ids = []
                for key, vector in [
                    ("a", [1.0, 0.0]),
                    ("b", [0.96, 0.28]),
                    ("c", [0.92, 0.392]),
                ]:
                    speaker = store.ensure_speaker_for_alias(
                        f"obs:1:{key}",
                        default_name="Speaker",
                        label=f"Speaker {key}",
                    )
                    speaker_id = int(speaker["id"])
                    speaker_ids.append(speaker_id)
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
                    store.add_speaker_embedding(
                        speaker_id=speaker_id,
                        sample_id=int(sample["id"]),
                        model=model,
                        vector=vector,
                        metadata={},
                    )

                result = auto_organize_speakers(settings, store, threshold=0.68, hide_unmatched=False)
                speakers = store.list_speakers()
                survivor = speakers[0]
                survivor_metadata = json.loads(survivor["metadata"])
                samples = store.list_speaker_samples(int(survivor["id"]))
                matches = store.list_speaker_match_decisions(limit=10)
            finally:
                store.close()

        self.assertEqual(result.merged_speakers, 2)
        self.assertEqual(result.unstable_merge_candidates, 0)
        self.assertEqual(len(speakers), 1)
        self.assertEqual(len(samples), 3)
        self.assertEqual(survivor_metadata["speaker_review_status"], "auto_merged_pending_review")
        self.assertEqual(len(survivor_metadata["auto_merge_sources"]), 2)
        self.assertEqual(len([row for row in matches if row["status"] == "auto_merged_pending_review"]), 2)
        self.assertTrue(int(survivor["id"]) in set(speaker_ids))

    def test_auto_organize_skips_candidate_that_would_lower_cluster_stability(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(
                speaker_recognition={"auto_merge_threshold": 0.68},
                speaker_sample_dir=root / "speaker_samples",
            )
            store = Store(root / "test.sqlite3")
            try:
                model = "speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb"
                cluster = store.ensure_speaker_for_alias("obs:1:cluster", default_name="Speaker 1", label="Speaker 1")
                source = store.ensure_speaker_for_alias("obs:1:source", default_name="Speaker 2", label="Speaker 2")
                cluster_id = int(cluster["id"])
                source_id = int(source["id"])
                for index, vector in enumerate([[1.0, 0.0], [0.8, 0.6]], start=1):
                    sample = store.add_speaker_sample(
                        speaker_id=cluster_id,
                        observation_id=None,
                        source_key=f"cluster-{index}",
                        media_path=None,
                        sample_path=None,
                        start_seconds=0.0,
                        end_seconds=1.0,
                        transcript=f"cluster {index}",
                        metadata={},
                    )
                    store.add_speaker_embedding(
                        speaker_id=cluster_id,
                        sample_id=int(sample["id"]),
                        model=model,
                        vector=vector,
                        metadata={},
                    )
                store.update_speaker_identity_status(cluster_id, status="provisional", confidence=0.8)
                source_sample = store.add_speaker_sample(
                    speaker_id=source_id,
                    observation_id=None,
                    source_key="source",
                    media_path=None,
                    sample_path=None,
                    start_seconds=0.0,
                    end_seconds=1.0,
                    transcript="source",
                    metadata={},
                )
                store.add_speaker_embedding(
                    speaker_id=source_id,
                    sample_id=int(source_sample["id"]),
                    model=model,
                    vector=[0.5, 0.866],
                    metadata={},
                )

                result = auto_organize_speakers(settings, store, threshold=0.68, hide_unmatched=False)
                cluster_after = store.get_speaker(cluster_id)
                source_after = store.get_speaker(source_id)
                matches = store.list_speaker_match_decisions()
            finally:
                store.close()

        self.assertEqual(result.merge_candidates, 1)
        self.assertEqual(result.unstable_merge_candidates, 1)
        self.assertEqual(result.merged_speakers, 0)
        self.assertIsNotNone(cluster_after)
        self.assertIsNotNone(source_after)
        self.assertEqual(matches, [])

    def test_auto_organize_can_continue_pending_review_clusters_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(
                speaker_recognition={"auto_merge_threshold": 0.68},
                speaker_sample_dir=root / "speaker_samples",
            )
            store = Store(root / "test.sqlite3")
            try:
                model = "speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb"
                cluster_ids = []
                for cluster_index, vectors in enumerate(
                    [
                        [[1.0, 0.0], [0.96, 0.28]],
                        [[0.98, 0.18], [0.94, 0.34]],
                    ],
                    start=1,
                ):
                    speaker = store.ensure_speaker_for_alias(
                        f"obs:1:cluster-{cluster_index}",
                        default_name=f"Speaker {cluster_index}",
                        label=f"Speaker {cluster_index}",
                    )
                    speaker_id = int(speaker["id"])
                    cluster_ids.append(speaker_id)
                    for sample_index, vector in enumerate(vectors, start=1):
                        sample = store.add_speaker_sample(
                            speaker_id=speaker_id,
                            observation_id=None,
                            source_key=f"cluster-{cluster_index}-{sample_index}",
                            media_path=None,
                            sample_path=None,
                            start_seconds=0.0,
                            end_seconds=1.0,
                            transcript=f"cluster {cluster_index} sample {sample_index}",
                            metadata={},
                        )
                        store.add_speaker_embedding(
                            speaker_id=speaker_id,
                            sample_id=int(sample["id"]),
                            model=model,
                            vector=vector,
                            metadata={},
                        )
                    store.update_speaker_identity_status(speaker_id, status="provisional", confidence=0.96)
                    mark_speaker_review_status(store, speaker_ids=[speaker_id], status="unhidden")
                    row = store.get_speaker(speaker_id)
                    metadata = json.loads(row["metadata"])
                    metadata["speaker_review_status"] = "auto_merged_pending_review"
                    store.conn.execute(
                        "UPDATE speakers SET metadata = ? WHERE id = ?",
                        (json.dumps(metadata, ensure_ascii=False, sort_keys=True), speaker_id),
                    )
                    store.conn.commit()

                locked = auto_organize_speakers(settings, store, threshold=0.68, hide_unmatched=False)
                continued = auto_organize_speakers(
                    settings,
                    store,
                    threshold=0.68,
                    hide_unmatched=False,
                    allow_pending_review=True,
                )
                speakers = store.list_speakers()
                samples = store.list_speaker_samples(int(speakers[0]["id"]))
            finally:
                store.close()

        self.assertEqual(locked.merged_speakers, 0)
        self.assertEqual(continued.merged_speakers, 1)
        self.assertEqual(len(speakers), 1)
        self.assertEqual(len(samples), 4)

    def test_auto_organize_stability_checks_low_confidence_outlier_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(
                speaker_recognition={"auto_merge_threshold": 0.68, "auto_merge_min_sample_confidence": 0.55},
                speaker_sample_dir=root / "speaker_samples",
            )
            store = Store(root / "test.sqlite3")
            try:
                model = "speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb"
                mixed = store.ensure_speaker_for_alias("obs:1:mixed", default_name="Speaker 1", label="Speaker 1")
                source = store.ensure_speaker_for_alias("obs:1:source", default_name="Speaker 2", label="Speaker 2")
                mixed_id = int(mixed["id"])
                source_id = int(source["id"])
                for key, vector, confidence in [
                    ("good", [1.0, 0.0], 0.95),
                    ("outlier", [0.0, 1.0], 0.2),
                ]:
                    sample = store.add_speaker_sample(
                        speaker_id=mixed_id,
                        observation_id=None,
                        source_key=f"mixed-{key}",
                        media_path=None,
                        sample_path=None,
                        start_seconds=0.0,
                        end_seconds=1.0,
                        transcript=key,
                        metadata={"sample_confidence": confidence},
                    )
                    store.add_speaker_embedding(
                        speaker_id=mixed_id,
                        sample_id=int(sample["id"]),
                        model=model,
                        vector=vector,
                        metadata={},
                    )
                source_sample = store.add_speaker_sample(
                    speaker_id=source_id,
                    observation_id=None,
                    source_key="source",
                    media_path=None,
                    sample_path=None,
                    start_seconds=0.0,
                    end_seconds=1.0,
                    transcript="source",
                    metadata={"sample_confidence": 0.95},
                )
                store.add_speaker_embedding(
                    speaker_id=source_id,
                    sample_id=int(source_sample["id"]),
                    model=model,
                    vector=[1.0, 0.0],
                    metadata={},
                )
                for speaker_id in [mixed_id, source_id]:
                    store.update_speaker_identity_status(speaker_id, status="provisional", confidence=0.95)
                    mark_speaker_review_status(store, speaker_ids=[speaker_id], status="unhidden")
                    row = store.get_speaker(speaker_id)
                    metadata = json.loads(row["metadata"])
                    metadata["speaker_review_status"] = "auto_merged_pending_review"
                    store.conn.execute(
                        "UPDATE speakers SET metadata = ? WHERE id = ?",
                        (json.dumps(metadata, ensure_ascii=False, sort_keys=True), speaker_id),
                    )
                    store.conn.commit()

                result = auto_organize_speakers(
                    settings,
                    store,
                    threshold=0.68,
                    hide_unmatched=False,
                    allow_pending_review=True,
                )
                mixed_after = store.get_speaker(mixed_id)
                source_after = store.get_speaker(source_id)
            finally:
                store.close()

        self.assertEqual(result.merge_candidates, 1)
        self.assertEqual(result.unstable_merge_candidates, 1)
        self.assertEqual(result.merged_speakers, 0)
        self.assertIsNotNone(mixed_after)
        self.assertIsNotNone(source_after)

    def test_auto_organize_skips_unconfirmed_named_speaker_match(self):
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
                target_id = int(target["id"])
                source_id = int(source["id"])
                store.rename_speaker(target_id, "Alice")
                for speaker_id, key in [(target_id, "target"), (source_id, "source")]:
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
                    vector = {"target": [1.0, 0.0], "source": [0.9, 0.1]}[key]
                    store.add_speaker_embedding(
                        speaker_id=speaker_id,
                        sample_id=int(sample["id"]),
                        model="speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb",
                        vector=vector,
                        metadata={},
                    )

                result = auto_organize_speakers(settings, store, threshold=0.68, hide_unmatched=False)
                target_after = store.get_speaker(target_id)
                source_after = store.get_speaker(source_id)
                target_metadata = json.loads(target_after["metadata"])
                source_metadata = json.loads(source_after["metadata"])
                matches = store.list_speaker_match_decisions()
                speaker_counts = {int(row["id"]): int(row["sample_count"] or 0) for row in store.list_speakers()}
            finally:
                store.close()

        self.assertEqual(result.merged_speakers, 0)
        self.assertEqual(result.review_candidates, 0)
        self.assertEqual(result.hidden_speakers, 0)
        self.assertIsNotNone(source_after)
        self.assertEqual(speaker_counts[target_id], 1)
        self.assertEqual(speaker_counts[source_id], 1)
        self.assertNotEqual(target_metadata.get("speaker_review_status"), "auto_merged_pending_review")
        self.assertNotEqual(source_metadata.get("speaker_review_status"), "low_similarity_hidden")
        self.assertEqual(matches, [])

    def test_auto_organize_skips_low_confidence_mixed_cluster_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(
                speaker_recognition={"auto_merge_threshold": 0.68, "candidate_threshold": 0.68},
                speaker_sample_dir=root / "speaker_samples",
            )
            store = Store(root / "test.sqlite3")
            try:
                mixed = store.ensure_speaker_for_alias("obs:1:mixed", default_name="Speaker 1", label="Speaker 1")
                source = store.ensure_speaker_for_alias("obs:1:source", default_name="Speaker 2", label="Speaker 2")
                mixed_id = int(mixed["id"])
                source_id = int(source["id"])
                model = "speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb"
                for index, vector in enumerate([[1.0, 0.0], [0.0, 1.0]], start=1):
                    sample = store.add_speaker_sample(
                        speaker_id=mixed_id,
                        observation_id=None,
                        source_key=f"mixed-{index}",
                        media_path=None,
                        sample_path=None,
                        start_seconds=0.0,
                        end_seconds=1.0,
                        transcript=f"mixed {index}",
                        metadata={},
                    )
                    store.add_speaker_embedding(
                        speaker_id=mixed_id,
                        sample_id=int(sample["id"]),
                        model=model,
                        vector=vector,
                        metadata={},
                    )
                store.update_speaker_identity_status(mixed_id, status="provisional", confidence=0.1)
                source_sample = store.add_speaker_sample(
                    speaker_id=source_id,
                    observation_id=None,
                    source_key="source",
                    media_path=None,
                    sample_path=None,
                    start_seconds=0.0,
                    end_seconds=1.0,
                    transcript="source",
                    metadata={},
                )
                store.add_speaker_embedding(
                    speaker_id=source_id,
                    sample_id=int(source_sample["id"]),
                    model=model,
                    vector=[1.0, 0.0],
                    metadata={},
                )

                result = auto_organize_speakers(settings, store, threshold=0.68, hide_unmatched=False)
                mixed_after = store.get_speaker(mixed_id)
                source_after = store.get_speaker(source_id)
                matches = store.list_speaker_match_decisions()
            finally:
                store.close()

        self.assertEqual(result.merge_candidates, 1)
        self.assertEqual(result.unstable_merge_candidates, 1)
        self.assertEqual(result.review_candidates, 0)
        self.assertEqual(result.merged_speakers, 0)
        self.assertIsNotNone(mixed_after)
        self.assertIsNotNone(source_after)
        self.assertEqual(matches, [])

    def test_auto_organize_ignores_low_confidence_sample_embeddings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(
                speaker_recognition={
                    "auto_merge_threshold": 0.68,
                    "candidate_threshold": 0.68,
                    "auto_merge_min_sample_confidence": 0.55,
                },
                speaker_sample_dir=root / "speaker_samples",
            )
            store = Store(root / "test.sqlite3")
            try:
                target = store.ensure_speaker_for_alias("obs:1:target", default_name="Speaker 1", label="Speaker 1")
                source = store.ensure_speaker_for_alias("obs:1:source", default_name="Speaker 2", label="Speaker 2")
                target_id = int(target["id"])
                source_id = int(source["id"])
                model = "speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb"
                target_sample = store.add_speaker_sample(
                    speaker_id=target_id,
                    observation_id=None,
                    source_key="target",
                    media_path=None,
                    sample_path=None,
                    start_seconds=0.0,
                    end_seconds=1.0,
                    transcript="target",
                    metadata={"sample_confidence": 0.2},
                )
                source_sample = store.add_speaker_sample(
                    speaker_id=source_id,
                    observation_id=None,
                    source_key="source",
                    media_path=None,
                    sample_path=None,
                    start_seconds=0.0,
                    end_seconds=1.0,
                    transcript="source",
                    metadata={},
                )
                for speaker_id, sample, vector in (
                    (target_id, target_sample, [1.0, 0.0]),
                    (source_id, source_sample, [1.0, 0.0]),
                ):
                    store.add_speaker_embedding(
                        speaker_id=speaker_id,
                        sample_id=int(sample["id"]),
                        model=model,
                        vector=vector,
                        metadata={},
                    )

                result = auto_organize_speakers(settings, store, threshold=0.68, hide_unmatched=False)
                target_after = store.get_speaker(target_id)
                source_after = store.get_speaker(source_id)
                matches = store.list_speaker_match_decisions()
            finally:
                store.close()

        self.assertEqual(result.merge_candidates, 0)
        self.assertEqual(result.merged_speakers, 0)
        self.assertIsNotNone(target_after)
        self.assertIsNotNone(source_after)
        self.assertEqual(matches, [])

    def test_auto_organize_uses_merge_budget_across_disjoint_pairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(
                speaker_recognition={"auto_merge_threshold": 0.9},
                speaker_sample_dir=root / "speaker_samples",
            )
            store = Store(root / "test.sqlite3")
            try:
                vectors = [
                    ("a1", [1.0, 0.0, 0.0]),
                    ("a2", [0.999, 0.001, 0.0]),
                    ("a3", [0.998, 0.002, 0.0]),
                    ("b1", [0.0, 1.0, 0.0]),
                    ("b2", [0.001, 0.999, 0.0]),
                ]
                for label, vector in vectors:
                    speaker = store.ensure_speaker_for_alias(f"obs:1:{label}", default_name=label, label=label)
                    speaker_id = int(speaker["id"])
                    sample = store.add_speaker_sample(
                        speaker_id=speaker_id,
                        observation_id=None,
                        source_key=f"sample-{label}",
                        media_path=None,
                        sample_path=None,
                        start_seconds=0.0,
                        end_seconds=1.0,
                        transcript=label,
                        metadata={},
                    )
                    store.add_speaker_embedding(
                        speaker_id=speaker_id,
                        sample_id=int(sample["id"]),
                        model="speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb",
                        vector=vector,
                        metadata={},
                    )

                result = auto_organize_speakers(settings, store, threshold=0.9, max_merges=2)
                sample_counts = sorted(int(row["sample_count"] or 0) for row in store.list_speakers())
            finally:
                store.close()

        self.assertEqual(result.merged_speakers, 2)
        self.assertEqual(sample_counts, [1, 2, 2])

    def test_auto_organize_cascades_stable_pending_review_merges_in_same_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(
                speaker_recognition={"auto_merge_threshold": 0.96},
                speaker_sample_dir=root / "speaker_samples",
            )
            store = Store(root / "test.sqlite3")
            try:
                vectors = [
                    ("a1", [1.0, 0.0]),
                    ("a2", [0.9848, 0.1736]),
                    ("a3", [0.9397, 0.3420]),
                ]
                for label, vector in vectors:
                    speaker = store.ensure_speaker_for_alias(f"obs:1:{label}", default_name=label, label=label)
                    speaker_id = int(speaker["id"])
                    sample = store.add_speaker_sample(
                        speaker_id=speaker_id,
                        observation_id=None,
                        source_key=f"sample-{label}",
                        media_path=None,
                        sample_path=None,
                        start_seconds=0.0,
                        end_seconds=1.0,
                        transcript=label,
                        metadata={},
                    )
                    store.add_speaker_embedding(
                        speaker_id=speaker_id,
                        sample_id=int(sample["id"]),
                        model="speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb",
                        vector=vector,
                        metadata={},
                    )

                result = auto_organize_speakers(
                    settings,
                    store,
                    threshold=0.96,
                    max_merges=10,
                    hide_unmatched=False,
                )
                sample_counts = sorted(int(row["sample_count"] or 0) for row in store.list_speakers())
            finally:
                store.close()

        self.assertEqual(result.merge_rounds, 2)
        self.assertEqual(result.merged_speakers, 2)
        self.assertEqual(result.review_candidates, 0)
        self.assertEqual(sample_counts, [3])

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

    def test_reset_regroup_samples_preserves_excluded_speaker(self):
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
                protected = store.ensure_speaker_for_alias(
                    "observation:1:protected",
                    default_name="Speaker 1",
                    label="Speaker 1",
                )
                protected_id = int(protected["id"])
                store.rename_speaker(protected_id, "Yutsuki Yomura")
                mark_speaker_review_status(store, speaker_ids=[protected_id], status="confirmed")
                source = store.ensure_speaker_for_alias(
                    "observation:1:source",
                    default_name="Speaker 2",
                    label="Speaker 2",
                )
                source_id = int(source["id"])
                protected_sample = store.add_speaker_sample(
                    speaker_id=protected_id,
                    observation_id=None,
                    source_key="sample:protected",
                    media_path=None,
                    sample_path="protected.m4a",
                    start_seconds=1.0,
                    end_seconds=2.0,
                    transcript="protected",
                    metadata={"sample_confidence": 0.9, "representative_sample": True},
                )
                source_sample = store.add_speaker_sample(
                    speaker_id=source_id,
                    observation_id=None,
                    source_key="sample:source",
                    media_path=None,
                    sample_path=None,
                    start_seconds=3.0,
                    end_seconds=4.0,
                    transcript="source",
                    metadata={},
                )
                model = "speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb"
                store.add_speaker_embedding(
                    speaker_id=protected_id,
                    sample_id=int(protected_sample["id"]),
                    model=model,
                    vector=[0.0, 1.0],
                    metadata={},
                )
                store.add_speaker_embedding(
                    speaker_id=source_id,
                    sample_id=int(source_sample["id"]),
                    model=model,
                    vector=[1.0, 0.0],
                    metadata={},
                )
                protected_before = store.get_speaker(protected_id)
                protected_sample_before = store.get_speaker_sample(int(protected_sample["id"]))

                result = reset_and_auto_group_speaker_samples(
                    settings,
                    store,
                    threshold=0.68,
                    max_merges=10,
                    recut=False,
                    hide_unmatched=False,
                    exclude_speaker_ids=[protected_id],
                )
                protected_after = store.get_speaker(protected_id)
                protected_sample_after = store.get_speaker_sample(int(protected_sample["id"]))
                protected_embeddings = store.speaker_embedding_rows(model=model, speaker_id=protected_id)
            finally:
                store.close()

        self.assertEqual(result.selected_samples, 1)
        self.assertEqual(result.reset_samples, 1)
        self.assertIsNotNone(protected_after)
        self.assertEqual(protected_after["display_name"], protected_before["display_name"])
        self.assertEqual(protected_sample_after["speaker_id"], protected_id)
        self.assertEqual(protected_sample_after["sample_path"], protected_sample_before["sample_path"])
        self.assertEqual(len(protected_embeddings), 1)

    def test_reset_regroup_samples_clears_stale_sample_scoring_metadata(self):
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
                speaker = store.ensure_speaker_for_alias(
                    "observation:1:source",
                    default_name="Speaker 1",
                    label="Speaker 1",
                )
                speaker_id = int(speaker["id"])
                sample = store.add_speaker_sample(
                    speaker_id=speaker_id,
                    observation_id=None,
                    source_key="sample:source",
                    media_path=None,
                    sample_path=None,
                    start_seconds=3.0,
                    end_seconds=4.0,
                    transcript="source",
                    metadata={
                        "sample_confidence": 0.2,
                        "sample_confidence_basis": "leave_one_out_centroid",
                        "sample_confidence_model": "old-model",
                        "sample_confidence_recalculated_at": "2026-01-01T00:00:00Z",
                        "representative_sample": True,
                        "representative_rank": 1,
                        "representative_score": 3.0,
                        "representative_refreshed_at": "2026-01-01T00:00:00Z",
                    },
                )
                store.add_speaker_embedding(
                    speaker_id=speaker_id,
                    sample_id=int(sample["id"]),
                    model="speechbrain_ecapa:speechbrain/spkrec-ecapa-voxceleb",
                    vector=[1.0, 0.0],
                    metadata={},
                )

                result = reset_and_auto_group_speaker_samples(
                    settings,
                    store,
                    threshold=0.68,
                    max_merges=0,
                    recut=False,
                    hide_unmatched=False,
                )
                sample_after = store.get_speaker_sample(int(sample["id"]))
                sample_metadata = json.loads(sample_after["metadata"])
            finally:
                store.close()

        self.assertEqual(result.selected_samples, 1)
        self.assertEqual(result.reset_samples, 1)
        self.assertNotIn("sample_confidence", sample_metadata)
        self.assertNotIn("sample_confidence_basis", sample_metadata)
        self.assertNotIn("sample_confidence_model", sample_metadata)
        self.assertNotIn("sample_confidence_recalculated_at", sample_metadata)
        self.assertNotIn("representative_sample", sample_metadata)
        self.assertNotIn("representative_rank", sample_metadata)
        self.assertNotIn("representative_score", sample_metadata)
        self.assertNotIn("representative_refreshed_at", sample_metadata)
        self.assertEqual(sample_metadata["sample_regroup_previous_confidence"], 0.2)
        self.assertTrue(sample_metadata["sample_regroup_previous_representative_sample"])

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
        self.assertGreaterEqual(len(samples), 2)
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
                speaker_recognition={
                    "enabled": True,
                    "sample_seconds": 8,
                    "sample_min_seconds": 0.5,
                    "samples_per_speaker_per_observation": 1,
                },
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

    def test_quality_rejected_sample_is_not_added_to_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "audio.m4a"
            source.write_bytes(b"audio")
            settings = SimpleNamespace(
                speaker_recognition={
                    "enabled": True,
                    "sample_seconds": 3,
                    "sample_min_seconds": 0.5,
                    "samples_per_speaker_per_observation": 1,
                },
                audio_preprocessing={"enabled": True, "speaker_samples_enabled": True},
                speaker_sample_dir=root / "speaker_samples",
            )
            store = Store(root / "context.sqlite3")

            def fake_clip(_settings, _source, output, _start, _end):
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"bad sample")
                return True, {"status": "enhanced"}

            try:
                store.upsert_observations(
                    [
                        Observation(
                            source="mobile",
                            kind="audio_segment",
                            source_key="audio-noisy-sample",
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
                        ("audio-noisy-sample",),
                    ).fetchone()["id"]
                )
                metadata = {
                    "audio_analysis": {
                        "audio_timeline": {
                            "duration_seconds": 4.0,
                            "speech_segments": [
                                {"start": 0.0, "end": 4.0, "speaker": "Speaker 1", "text": "noisy speech sample"},
                            ],
                        }
                    }
                }

                with (
                    patch("wond.speakers.create_enhanced_sample_clip", side_effect=fake_clip),
                    patch(
                        "wond.speakers.audio_quality",
                        return_value={"ok": False, "reason": "noisy_background"},
                    ),
                ):
                    result = process_speakers_for_observation(
                        settings,
                        store,
                        observation_id=observation_id,
                        source_key="audio-noisy-sample",
                        media_path=source,
                        metadata=metadata,
                    )
                samples = store.list_speaker_samples(None)
                speakers = store.list_speakers()
            finally:
                store.close()

        self.assertEqual(samples, [])
        self.assertEqual(speakers, [])
        self.assertEqual(result["audio_analysis"]["speaker_processing"]["status"], "ok")

    def test_noisy_long_sample_retries_clean_shorter_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "audio.m4a"
            source.write_bytes(b"audio")
            settings = SimpleNamespace(
                speaker_recognition={
                    "enabled": True,
                    "sample_seconds": 16,
                    "sample_min_seconds": 0.5,
                    "sample_fine_window_seconds": 3,
                    "sample_fine_stride_seconds": 2.5,
                    "samples_per_speaker_per_observation": 1,
                },
                audio_preprocessing={"enabled": True, "speaker_samples_enabled": True},
                speaker_sample_dir=root / "speaker_samples",
            )
            store = Store(root / "context.sqlite3")

            def fake_clip(_settings, _source, output, _start, _end):
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"sample")
                return True, {"status": "enhanced"}

            def fake_quality(_settings, path, *, min_seconds):
                name = Path(path).name
                if name.endswith("-0.00-12.00.m4a"):
                    return {"ok": False, "reason": "noisy_background"}
                return {"ok": True, "reason": None, "duration_seconds": 8.0}

            try:
                store.upsert_observations(
                    [
                        Observation(
                            source="mobile",
                            kind="audio_segment",
                            source_key="audio-noisy-long-sample",
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
                        ("audio-noisy-long-sample",),
                    ).fetchone()["id"]
                )
                metadata = {
                    "audio_analysis": {
                        "audio_timeline": {
                            "duration_seconds": 12.0,
                            "speech_segments": [
                                {
                                    "start": 0.0,
                                    "end": 12.0,
                                    "speaker": "Speaker 1",
                                    "text": "a long single speaker turn that has a clean subsection",
                                },
                            ],
                        }
                    }
                }

                with (
                    patch("wond.speakers.create_enhanced_sample_clip", side_effect=fake_clip),
                    patch("wond.speakers.audio_quality", side_effect=fake_quality),
                    patch(
                        "wond.speakers.update_speaker_identity_for_sample",
                        side_effect=lambda _settings, _store, *, speaker_id, sample_id, sample_path: SimpleNamespace(
                            speaker_id=speaker_id,
                            status="new_identity",
                            score=None,
                            target_speaker_id=None,
                            confidence=None,
                            message=None,
                        ),
                    ),
                ):
                    process_speakers_for_observation(
                        settings,
                        store,
                        observation_id=observation_id,
                        source_key="audio-noisy-long-sample",
                        media_path=source,
                        metadata=metadata,
                    )
                samples = store.list_speaker_samples(None)
                sample_metadata = json.loads(samples[0]["metadata"])
            finally:
                store.close()

        self.assertEqual(len(samples), 1)
        self.assertEqual(float(samples[0]["start_seconds"]), 0.0)
        self.assertEqual(float(samples[0]["end_seconds"]), 8.0)
        self.assertEqual(sample_metadata["quality_recovery"]["status"], "recovered_with_shorter_window")
        self.assertTrue(sample_metadata["clip_strategy"]["quality_recovery_window"])

    def test_long_speaker_segment_creates_multiple_window_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(
                speaker_recognition={
                    "enabled": True,
                    "sample_seconds": 16,
                    "sample_min_seconds": 0.5,
                    "sample_boundary_guard_seconds": 0.08,
                    "sample_stride_seconds": 16,
                    "samples_per_speaker_per_observation": 4,
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
                            source_key="audio-windowed-samples",
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
                        ("audio-windowed-samples",),
                    ).fetchone()["id"]
                )
                metadata = {
                    "audio_analysis": {
                        "audio_timeline": {
                            "duration_seconds": 50.0,
                            "speech_segments": [
                                {
                                    "start": 0.0,
                                    "end": 50.0,
                                    "speaker": "Speaker 1",
                                    "text": " ".join(f"word{i:02d}" for i in range(80)),
                                },
                            ],
                        }
                    }
                }

                result = process_speakers_for_observation(
                    settings,
                    store,
                    observation_id=observation_id,
                    source_key="audio-windowed-samples",
                    media_path=None,
                    metadata=metadata,
                )
                samples = sorted(store.list_speaker_samples(None), key=lambda row: float(row["start_seconds"]))
                sample_metadatas = [json.loads(sample["metadata"]) for sample in samples]
            finally:
                store.close()

        self.assertGreaterEqual(len(samples), 3)
        self.assertEqual(result["audio_analysis"]["speakers"][0]["sample_count"], len(samples))
        self.assertEqual([item["sample_window_index"] for item in sample_metadatas], list(range(1, len(samples) + 1)))
        self.assertEqual(float(samples[0]["start_seconds"]), 0.08)
        self.assertLessEqual(max(float(sample["end_seconds"]) for sample in samples), 50.0)
        self.assertEqual(len({sample["source_key"] for sample in samples}), len(samples))

    def test_unlabeled_speech_can_create_window_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(
                speaker_recognition={
                    "enabled": True,
                    "sample_seconds": 16,
                    "sample_min_seconds": 0.5,
                    "sample_unlabeled_speech": True,
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
                            source_key="audio-unlabeled-speech",
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
                        ("audio-unlabeled-speech",),
                    ).fetchone()["id"]
                )
                metadata = {
                    "audio_analysis": {
                        "audio_timeline": {
                            "duration_seconds": 40.0,
                            "speech_segments": [
                                {"start": 0.0, "end": 40.0, "speaker": None, "text": "unlabeled but spoken text"},
                            ],
                        }
                    }
                }

                result = process_speakers_for_observation(
                    settings,
                    store,
                    observation_id=observation_id,
                    source_key="audio-unlabeled-speech",
                    media_path=None,
                    metadata=metadata,
                )
                samples = store.list_speaker_samples(None)
                sample_metadata = json.loads(samples[0]["metadata"])
            finally:
                store.close()

        self.assertEqual(result["audio_analysis"]["speaker_processing"]["status"], "ok")
        self.assertEqual(result["audio_analysis"]["speaker_processing"]["unlabeled_speech_segments"], 1)
        self.assertEqual(result["audio_analysis"]["speakers"][0]["local_label"], "Unlabeled speech")
        self.assertGreaterEqual(len(samples), 2)
        self.assertEqual(sample_metadata["local_label"], "Unlabeled speech")

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

    def test_best_sample_segment_prefers_clean_single_turn_over_mixed_long_segment(self):
        mixed = {
            "start": 0.0,
            "end": 12.0,
            "speaker": "Speaker 1",
            "text": 'Where is the guest? Ah, there? He said: "I am fine." You asked again?',
        }
        clean = {
            "start": 20.0,
            "end": 23.0,
            "speaker": "Speaker 1",
            "text": "The schedule is ready for tomorrow morning.",
        }

        self.assertIs(best_sample_segment([mixed, clean]), clean)

    def test_speaker_sample_seconds_is_capped_at_sixteen_seconds(self):
        settings = SimpleNamespace(speaker_recognition={"sample_seconds": 120})

        self.assertEqual(speaker_sample_seconds(settings), 16.0)

    def test_speaker_sample_plans_fine_cut_mixed_speaker_risk(self):
        settings = SimpleNamespace(
            speaker_recognition={
                "sample_seconds": 16,
                "sample_min_seconds": 0.5,
                "sample_boundary_guard_seconds": 0.08,
                "sample_fine_window_seconds": 3,
                "sample_fine_stride_seconds": 3,
                "sample_long_segment_anchor": "start",
                "samples_per_speaker_per_observation": 4,
            }
        )
        mixed = {
            "start": 0.0,
            "end": 12.0,
            "speaker": "Speaker 1",
            "text": 'Where is the guest? Ah, there? He said: "I am fine." You asked again?',
        }

        plans = speaker_sample_plans_for_segments(settings, [mixed], 30.0)

        self.assertGreater(len(plans), 1)
        self.assertTrue(all(plan[0] is mixed for plan in plans))
        self.assertTrue(all((clip[1] - clip[0]) <= 3.01 for _, clip in plans))

    def test_sample_plans_spread_across_segments_when_limited(self):
        settings = SimpleNamespace(
            speaker_recognition={
                "sample_seconds": 16,
                "sample_min_seconds": 0.5,
                "samples_per_speaker_per_observation": 3,
            }
        )
        segments = [
            {
                "start": index * 10.0,
                "end": index * 10.0 + 2.0,
                "speaker": "Speaker 1",
                "text": f"segment {index}",
            }
            for index in range(6)
        ]

        plans = speaker_sample_plans_for_segments(settings, segments, 80.0)

        self.assertEqual([plan[0]["text"] for plan in plans], ["segment 0", "segment 2", "segment 5"])

    def test_sample_plans_cover_segments_before_extra_windows(self):
        settings = SimpleNamespace(
            speaker_recognition={
                "sample_seconds": 3,
                "sample_min_seconds": 0.5,
                "sample_stride_seconds": 3,
                "samples_per_speaker_per_observation": 3,
            }
        )
        first = {
            "start": 0.0,
            "end": 12.0,
            "speaker": "Speaker 1",
            "text": " ".join(f"first{i}" for i in range(30)),
        }
        second = {
            "start": 20.0,
            "end": 32.0,
            "speaker": "Speaker 1",
            "text": " ".join(f"second{i}" for i in range(30)),
        }

        plans = speaker_sample_plans_for_segments(settings, [first, second], 40.0)

        self.assertEqual(plans[0][0], first)
        self.assertEqual(plans[1][0], second)
        self.assertEqual(plans[2][0], first)

    def test_speaker_samples_use_diarization_segments_before_broad_transcript_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(
                speaker_recognition={
                    "enabled": True,
                    "sample_seconds": 16,
                    "sample_min_seconds": 0.5,
                    "sample_boundary_guard_seconds": 0.08,
                    "sample_fine_window_seconds": 3,
                    "sample_fine_stride_seconds": 3,
                    "samples_per_speaker_per_observation": 4,
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
                            source_key="audio-diarization-sample-source",
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
                        ("audio-diarization-sample-source",),
                    ).fetchone()["id"]
                )
                metadata = {
                    "audio_analysis": {
                        "audio_timeline": {
                            "duration_seconds": 20.0,
                            "speech_segments": [
                                {
                                    "start": 0.0,
                                    "end": 20.0,
                                    "speaker": "Speaker 1",
                                    "text": "broad transcript segment that should not drive speaker samples",
                                },
                            ],
                            "speaker_diarization_segments": [
                                {
                                    "start": 0.0,
                                    "end": 1.2,
                                    "speaker": "Speaker 1",
                                    "speaker_scope": "turn_001",
                                    "text": "short first voice",
                                },
                                {
                                    "start": 1.35,
                                    "end": 2.1,
                                    "speaker": "Speaker 2",
                                    "speaker_scope": "turn_002",
                                    "text": "short second voice",
                                },
                            ],
                        }
                    }
                }

                result = process_speakers_for_observation(
                    settings,
                    store,
                    observation_id=observation_id,
                    source_key="audio-diarization-sample-source",
                    media_path=None,
                    metadata=metadata,
                )
                samples = sorted(store.list_speaker_samples(None), key=lambda row: float(row["start_seconds"]))
                sample_metadatas = [json.loads(sample["metadata"]) for sample in samples]
            finally:
                store.close()

        self.assertEqual(len(samples), 2)
        self.assertEqual(result["audio_analysis"]["speaker_processing"]["sample_segment_source"], "speaker_diarization_segments")
        self.assertEqual([float(sample["start_seconds"]) for sample in samples], [0.08, 1.43])
        self.assertEqual([round(float(sample["end_seconds"]), 2) for sample in samples], [1.12, 2.02])
        self.assertEqual({metadata["speaker_sample_source"] for metadata in sample_metadatas}, {"speaker_diarization_segments"})
        self.assertFalse(any(metadata["sample_fine_window"] for metadata in sample_metadatas))

    def test_repair_speaker_sample_clips_preserves_current_window_even_with_clean_alternative(self):
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
                            source_key="audio-repair-mixed-clips",
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
                                                "end": 12.0,
                                                "speaker": "Speaker 1",
                                                "speaker_scope": "vad_chunk_001",
                                                "text": 'Where is the guest? Ah, there? He said: "I am fine." You asked again?',
                                            },
                                            {
                                                "start": 20.0,
                                                "end": 23.0,
                                                "speaker": "Speaker 1",
                                                "speaker_scope": "vad_chunk_001",
                                                "text": "The schedule is ready for tomorrow morning.",
                                            },
                                        ],
                                    }
                                },
                            },
                        )
                    ]
                )
                observation_id = int(
                    store.conn.execute(
                        "SELECT id FROM observations WHERE source_key = ?",
                        ("audio-repair-mixed-clips",),
                    ).fetchone()["id"]
                )
                speaker = store.ensure_speaker_for_alias(
                    f"observation:{observation_id}:vad_chunk_001:Speaker 1",
                    default_name="Speaker 1",
                    label="Speaker 1",
                    metadata={"speaker_scope": "vad_chunk_001"},
                )
                sample = store.add_speaker_sample(
                    speaker_id=int(speaker["id"]),
                    observation_id=observation_id,
                    source_key=f"observation:{observation_id}:vad_chunk_001:Speaker 1:sample:0.080:8.080",
                    media_path=str(source),
                    sample_path=str(root / "old.m4a"),
                    start_seconds=0.08,
                    end_seconds=8.08,
                    transcript="mixed window",
                    metadata={"local_label": "vad_chunk_001:Speaker 1"},
                )
                with (
                    patch("wond.speakers.create_enhanced_sample_clip", side_effect=fake_enhanced),
                    patch("wond.speakers.audio_quality", return_value={"ok": True, "duration_seconds": 2.84}),
                    patch("wond.speakers.speaker_embedding", return_value=[1.0, 0.0]),
                ):
                    preview = repair_speaker_sample_clips(settings, store)
                    applied = repair_speaker_sample_clips(settings, store, apply=True)
                updated = store.get_speaker_sample(int(sample["id"]))
                updated_metadata = json.loads(updated["metadata"])
            finally:
                store.close()

        self.assertEqual(preview.repaired, 1)
        self.assertEqual(applied.repaired, 1)
        self.assertEqual(applied.reembedded, 0)
        self.assertAlmostEqual(float(updated["start_seconds"]), 0.08, places=2)
        self.assertAlmostEqual(float(updated["end_seconds"]), 8.08, places=2)
        self.assertEqual(updated_metadata["source_segment_start"], 0.0)
        self.assertTrue(updated_metadata["sample_segment_mixed_speaker_risk"])

    def test_sample_clip_plan_keeps_current_window_when_only_other_candidates_are_mixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(
                speaker_recognition={
                    "sample_seconds": 8,
                    "sample_min_seconds": 0.5,
                    "sample_boundary_guard_seconds": 0.08,
                    "sample_long_segment_anchor": "start",
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
                            source_key="audio-risky-alternatives",
                            observed_at="2026-06-01T10:00:00+09:00",
                            title="Audio segment",
                            body="transcript",
                            metadata={
                                "audio_analysis": {
                                    "audio_timeline": {
                                        "duration_seconds": 90.0,
                                        "speech_segments": [
                                            {
                                                "start": 0.0,
                                                "end": 45.0,
                                                "speaker": "Speaker 1",
                                                "speaker_scope": "vad_chunk_001",
                                                "text": 'Where now? There? He said: "I am fine." You asked again?',
                                            },
                                            {
                                                "start": 45.0,
                                                "end": 75.0,
                                                "speaker": "Speaker 1",
                                                "speaker_scope": "vad_chunk_001",
                                                "text": 'What next? Which one? She said: "Use that." Then what?',
                                            },
                                        ],
                                    }
                                },
                            },
                        )
                    ]
                )
                observation_id = int(
                    store.conn.execute(
                        "SELECT id FROM observations WHERE source_key = ?",
                        ("audio-risky-alternatives",),
                    ).fetchone()["id"]
                )
                speaker = store.ensure_speaker_for_alias(
                    f"observation:{observation_id}:vad_chunk_001:Speaker 1",
                    default_name="Speaker 1",
                    label="Speaker 1",
                    metadata={"speaker_scope": "vad_chunk_001"},
                )
                sample = store.add_speaker_sample(
                    speaker_id=int(speaker["id"]),
                    observation_id=observation_id,
                    source_key=f"observation:{observation_id}:vad_chunk_001:Speaker 1:sample:0.080:8.080",
                    media_path=None,
                    sample_path=None,
                    start_seconds=0.08,
                    end_seconds=8.08,
                    transcript="current risky window",
                    metadata={"local_label": "vad_chunk_001:Speaker 1"},
                )
                row = store.conn.execute(
                    """
                    SELECT speaker_samples.*, observations.metadata AS observation_metadata
                    FROM speaker_samples
                    LEFT JOIN observations ON observations.id = speaker_samples.observation_id
                    WHERE speaker_samples.id = ?
                    """,
                    (int(sample["id"]),),
                ).fetchone()
                plan = speaker_sample_clip_plan(settings, row)
            finally:
                store.close()

        self.assertEqual(plan["clip"], (0.08, 8.08))
        self.assertTrue(plan["sample_segment_mixed_speaker_risk"])

    def test_repair_speaker_sample_clips_preserves_existing_window_in_long_segment(self):
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
        self.assertEqual(applied.reembedded, 0)
        self.assertEqual(float(updated["start_seconds"]), 18.5)
        self.assertEqual(float(updated["end_seconds"]), 26.5)
        self.assertEqual(updated["source_key"], f"observation:{observation_id}:Speaker 1:sample:18.500:26.500")
        self.assertNotEqual(updated["transcript"], "middle words")
        self.assertFalse(updated["transcript"].startswith("word00"))
        self.assertEqual(updated_metadata["sample_clip_repair"]["anchor"], "start")
        self.assertEqual(len(embedding_rows), 0)

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
