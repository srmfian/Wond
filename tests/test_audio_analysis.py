import unittest
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from wond.audio_analysis import (
    analyze_audio_for_day_unlocked,
    audio_analysis_needs_retry,
    is_no_speech_transcription_error,
    maybe_run_speaker_diarization_repair,
    needs_processed_audio_cleanup,
    needs_speaker_registry,
    processed_audio_delete_defer_reason,
    resolve_media_path,
)
from wond.openai_analysis import AudioOpenAIAnalysis
from wond.store import Observation, Store


class AudioAnalysisTests(unittest.TestCase):
    def test_empty_local_transcription_is_no_speech(self):
        self.assertTrue(is_no_speech_transcription_error(RuntimeError("mlx-audio returned no text")))

    def test_pathological_local_transcription_is_no_speech(self):
        self.assertTrue(
            is_no_speech_transcription_error(
                RuntimeError("transcription looked pathological: phrase '我我我我我我我我' repeated excessively")
            )
        )

    def test_regular_transcription_failure_is_not_no_speech(self):
        self.assertFalse(is_no_speech_transcription_error(RuntimeError("mlx-audio failed: permission denied")))

    def test_retryable_error_status_is_not_treated_as_done(self):
        self.assertTrue(audio_analysis_needs_retry({"status": "error", "summary": "already summarized"}))
        self.assertTrue(audio_analysis_needs_retry({"status": "ok", "transcript_status": "transcription_error"}))
        self.assertFalse(audio_analysis_needs_retry({"status": "ok", "transcript_status": "no_speech"}))

    def test_resolve_media_path_prefers_existing_recycle_bin_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing_original = root / "imports" / "audio.m4a"
            recycled = root / "recycle_bin" / "audio.m4a"
            recycled.parent.mkdir()
            recycled.write_bytes(b"audio")

            resolved = resolve_media_path(
                {
                    "resolved_media_path": str(missing_original),
                    "audio_analysis": {"recycle_bin_path": str(recycled)},
                }
            )

            self.assertEqual(resolved, recycled.resolve())

    def test_error_record_with_body_and_summary_is_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio_path = root / "audio.m4a"
            audio_path.write_bytes(b"audio")
            settings = SimpleNamespace(
                timezone="Asia/Tokyo",
                audio_analysis={"max_segments": 20},
                speaker_recognition={"enabled": False},
                mobile_sync={"delete_audio_after_analysis": False},
                ai_backend={"provider": "local"},
            )
            store = Store(root / "context.sqlite3")
            try:
                store.upsert_observations(
                    [
                        Observation(
                            source="mobile",
                            kind="audio_segment",
                            source_key="audio-error",
                            observed_at="2026-06-01T09:00:00+09:00",
                            body="existing body",
                            metadata={
                                "resolved_media_path": str(audio_path),
                                "audio_analysis": {
                                    "status": "error",
                                    "summary": "existing summary",
                                    "error": "model failed",
                                },
                            },
                        )
                    ]
                )

                with (
                    patch(
                        "wond.audio_analysis.probe_audio",
                        return_value={"duration_seconds": 1.0, "probe": "test"},
                    ),
                    patch(
                        "wond.audio_analysis.analyze_audio_with_openai",
                        return_value=AudioOpenAIAnalysis(
                            transcript="new transcript",
                            summary="new summary",
                            metadata={"audio_timeline": {"duration_seconds": 1.0, "speech_segments": []}},
                        ),
                    ),
                ):
                    result = analyze_audio_for_day_unlocked(settings, store, datetime(2026, 6, 1).date())

                row = store.conn.execute("SELECT body, metadata FROM observations WHERE source_key='audio-error'").fetchone()
            finally:
                store.close()

            self.assertEqual(result.updated, 1)
            self.assertEqual(row["body"], "new transcript")
            self.assertIn('"status": "ok"', row["metadata"])

    def test_fallback_no_speech_does_not_hide_primary_model_load_failure(self):
        self.assertFalse(
            is_no_speech_transcription_error(
                RuntimeError(
                    "vibevoice transformers failed: ValueError: Could not load model "
                    "microsoft/VibeVoice-ASR-HF; fallback transcription failed: "
                    "no recognizable speech after VAD pre-segmentation"
                )
            )
        )

    def test_combined_primary_and_fallback_no_speech_is_no_speech(self):
        self.assertTrue(
            is_no_speech_transcription_error(
                RuntimeError(
                    "no recognizable speech after VAD pre-segmentation; "
                    "fallback transcription failed: mlx-audio returned no text"
                )
            )
        )

    def test_unlabeled_speech_segments_still_need_speaker_processing_status(self):
        settings = SimpleNamespace(speaker_recognition={"enabled": True})
        analysis = {
            "audio_timeline": {
                "speech_segments": [
                    {"start": 0.0, "end": 2.0, "speaker": None, "text": "hello"},
                ]
            }
        }

        self.assertTrue(needs_speaker_registry(settings, analysis))

    def test_skipped_unlabeled_segments_need_one_diarization_repair_attempt(self):
        settings = SimpleNamespace(
            speaker_recognition={"enabled": True},
            local_ai={"speaker_diarization_enabled": True},
        )
        analysis = {
            "audio_timeline": {
                "speech_segments": [
                    {"start": 0.0, "end": 2.0, "speaker": None, "text": "hello"},
                ]
            },
            "speaker_processing": {"status": "skipped_no_speaker_labels"},
        }

        self.assertTrue(needs_speaker_registry(settings, analysis))

    def test_diarization_repair_does_not_loop_after_attempt(self):
        settings = SimpleNamespace(
            speaker_recognition={"enabled": True},
            local_ai={"speaker_diarization_enabled": True},
        )
        analysis = {
            "audio_timeline": {
                "speech_segments": [
                    {"start": 0.0, "end": 2.0, "speaker": None, "text": "hello"},
                ]
            },
            "speaker_processing": {"status": "skipped_no_speaker_labels"},
            "local_speaker_diarization": {"status": "skipped_no_speaker_labels"},
        }

        self.assertFalse(needs_speaker_registry(settings, analysis))

    def test_diarization_repair_overlay_clears_stale_speaker_processing(self):
        settings = SimpleNamespace(
            speaker_recognition={"enabled": True},
            local_ai={"speaker_diarization_enabled": True},
        )
        analysis = {
            "audio_timeline": {
                "speech_segments": [
                    {"start": 0.0, "end": 2.0, "speaker": None, "text": "hello"},
                ]
            },
            "speaker_processing": {"status": "skipped_no_speaker_labels"},
        }

        def fake_diarization(_settings, _path, timeline):
            timeline["speech_segments"][0]["speaker"] = "Speaker 1"
            timeline["speech_segments"][0]["speaker_label_source"] = "local_speaker_diarization"
            return {"status": "ok", "applied_labels": 1}

        with patch("wond.audio_analysis.run_speaker_diarization", side_effect=fake_diarization):
            maybe_run_speaker_diarization_repair(settings, Path("sample.m4a"), analysis)

        self.assertEqual(analysis["local_speaker_diarization"]["status"], "ok")
        self.assertEqual(analysis["audio_timeline"]["speech_segments"][0]["speaker"], "Speaker 1")
        self.assertNotIn("speaker_processing", analysis)

    def test_unlabeled_speaker_processing_defers_audio_cleanup_during_repair_window(self):
        processed_at = datetime.now().astimezone().isoformat(timespec="seconds")
        settings = SimpleNamespace(
            mobile_sync={
                "delete_audio_after_analysis": True,
                "delete_audio_after_analysis_repair_window_hours": 24,
            },
            speaker_recognition={"enabled": True},
        )
        metadata = {
            "audio_analysis": {
                "status": "ok",
                "summary": "summary",
                "analyzed_at": processed_at,
                "audio_timeline": {
                    "speech_segments": [
                        {"start": 0.0, "end": 2.0, "speaker": None, "text": "hello"},
                    ]
                },
                "speaker_processing": {
                    "status": "skipped_no_speaker_labels",
                    "processed_at": processed_at,
                },
            }
        }

        reason = processed_audio_delete_defer_reason(settings, metadata)

        self.assertIsNotNone(reason)
        self.assertEqual(reason["reason"], "speaker_repair_window_pending")
        self.assertFalse(needs_processed_audio_cleanup(settings, metadata))

    def test_unlabeled_speaker_processing_allows_cleanup_after_repair_window(self):
        processed_at = (datetime.now().astimezone() - timedelta(hours=25)).isoformat(timespec="seconds")
        settings = SimpleNamespace(
            mobile_sync={
                "delete_audio_after_analysis": True,
                "delete_audio_after_analysis_repair_window_hours": 24,
            },
            speaker_recognition={"enabled": True},
        )
        metadata = {
            "audio_analysis": {
                "status": "ok",
                "summary": "summary",
                "analyzed_at": processed_at,
                "audio_timeline": {
                    "speech_segments": [
                        {"start": 0.0, "end": 2.0, "speaker": None, "text": "hello"},
                    ]
                },
                "speaker_processing": {
                    "status": "skipped_no_speaker_labels",
                    "processed_at": processed_at,
                },
            }
        }

        self.assertIsNone(processed_audio_delete_defer_reason(settings, metadata))
        self.assertTrue(needs_processed_audio_cleanup(settings, metadata))


if __name__ == "__main__":
    unittest.main()
