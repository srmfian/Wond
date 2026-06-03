import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from wond.openai_analysis import (
    TranscriptionResult,
    analyze_audio_with_local_ai,
    apply_diarization_to_timeline,
    build_audio_timeline,
    load_subprocess_json,
    merge_intervals_to_max_count,
    run_speaker_diarization,
    should_vad_presegment_for_backend,
    transcribe_audio_with_local_backend,
)


class LocalTranscriptionBackendTests(unittest.TestCase):
    def settings(self, **local_ai):
        return SimpleNamespace(local_ai=local_ai)

    def test_vibevoice_uses_vad_gate_by_default(self):
        settings = self.settings(vad_presegment=True)
        result = TranscriptionResult(
            text="Speaker 1: hello",
            segments=[{"start": 0.0, "end": 1.0, "speaker": "Speaker 1", "text": "hello"}],
        )

        with (
            patch("wond.openai_analysis.transcribe_audio_with_vad_segments", return_value=result) as vad,
            patch("wond.openai_analysis.transcribe_audio_with_backend") as backend,
        ):
            actual = transcribe_audio_with_local_backend(
                settings,
                Path("sample.m4a"),
                backend="vibevoice_transformers",
                model="microsoft/VibeVoice-ASR-HF",
            )

        self.assertIs(actual, result)
        vad.assert_called_once()
        backend.assert_not_called()

    def test_mlx_audio_still_uses_vad_presegmentation(self):
        settings = self.settings(vad_presegment=True)
        self.assertTrue(should_vad_presegment_for_backend(settings, "mlx_audio"))

    def test_diarization_backend_can_disable_vad_presegmentation(self):
        settings = self.settings(vad_presegment=True, vad_presegment_diarization=False)
        self.assertFalse(should_vad_presegment_for_backend(settings, "vibevoice_transformers"))

    def test_diarization_chunk_merge_does_not_swallow_long_silence(self):
        chunks = merge_intervals_to_max_count([(0.0, 3.0), (30.0, 33.0)], 1, max_gap_seconds=8.0)
        self.assertEqual(chunks, [(0.0, 3.0), (30.0, 33.0)])

    def test_fast_asr_transcript_is_kept_while_diarization_labels_speakers(self):
        settings = SimpleNamespace(
            local_ai={
                "speaker_diarization_enabled": True,
                "speaker_diarization_backend": "vibevoice_mlx",
                "speaker_diarization_model": "mlx-community/VibeVoice-ASR-4bit",
            },
            openai_analysis={},
            audio_analysis={},
        )
        fast = TranscriptionResult(
            text="fast transcript",
            segments=[{"start": 0.0, "end": 3.0, "speaker": None, "text": "fast transcript"}],
            duration_seconds=3.0,
        )
        diarized = TranscriptionResult(
            text="Speaker 1: diarized transcript",
            segments=[{"start": 0.0, "end": 3.0, "speaker": "Speaker 1", "text": "diarized transcript"}],
            duration_seconds=3.0,
        )

        with (
            patch("wond.openai_analysis.assert_size"),
            patch("wond.openai_analysis.transcribe_audio_with_local_ai", return_value=fast),
            patch("wond.openai_analysis.transcribe_audio_with_local_backend", return_value=diarized),
            patch("wond.openai_analysis.detect_silence_seconds", return_value=0.0),
            patch("wond.openai_analysis.summarize_text_with_local_ai", return_value="summary"),
        ):
            result = analyze_audio_with_local_ai(settings, Path("sample.m4a"))

        self.assertEqual(result.transcript, "fast transcript")
        segment = result.metadata["audio_timeline"]["speech_segments"][0]
        self.assertEqual(segment["text"], "fast transcript")
        self.assertEqual(segment["speaker"], "Speaker 1")
        self.assertEqual(segment["speaker_label_source"], "local_speaker_diarization")
        self.assertEqual(result.metadata["local_speaker_diarization"]["backend"], "vibevoice_mlx")
        self.assertEqual(result.metadata["local_speaker_diarization"]["status"], "ok")

    def test_diarization_failure_does_not_fail_fast_asr_result(self):
        settings = SimpleNamespace(
            local_ai={
                "speaker_diarization_enabled": True,
                "speaker_diarization_backend": "vibevoice_mlx",
                "speaker_diarization_model": "mlx-community/VibeVoice-ASR-4bit",
            }
        )
        timeline = {"speech_segments": [{"start": 0.0, "end": 2.0, "speaker": None, "text": "hello"}]}

        with patch(
            "wond.openai_analysis.transcribe_audio_with_local_backend",
            side_effect=RuntimeError("Metal unavailable"),
        ):
            metadata = run_speaker_diarization(settings, Path("sample.m4a"), timeline)

        self.assertEqual(metadata["status"], "error")
        self.assertIn("Metal unavailable", metadata["error"])
        self.assertIsNone(timeline["speech_segments"][0]["speaker"])

    def test_diarization_marks_simultaneous_speaker_overlap(self):
        timeline = {
            "speech_segments": [
                {"start": 0.0, "end": 4.0, "speaker": None, "text": "mixed voices"},
            ]
        }
        diarized = [
            {"start": 0.0, "end": 3.0, "speaker": "Speaker 1", "text": "one"},
            {"start": 1.0, "end": 4.0, "speaker": "Speaker 2", "text": "two"},
        ]

        stats = apply_diarization_to_timeline(timeline, diarized)
        segment = timeline["speech_segments"][0]

        self.assertEqual(stats["applied_labels"], 1)
        self.assertEqual(stats["overlap_segments"], 1)
        self.assertTrue(segment["overlap"])
        self.assertEqual(segment["overlap_speakers"], ["Speaker 1", "Speaker 2"])
        self.assertEqual(segment["speaker_display"], "Speaker 1 + Speaker 2")

    def test_diarization_does_not_mark_sequential_speakers_as_overlap(self):
        timeline = {
            "speech_segments": [
                {"start": 0.0, "end": 4.0, "speaker": None, "text": "two turns"},
            ]
        }
        diarized = [
            {"start": 0.0, "end": 2.0, "speaker": "Speaker 1", "text": "one"},
            {"start": 2.0, "end": 4.0, "speaker": "Speaker 2", "text": "two"},
        ]

        stats = apply_diarization_to_timeline(timeline, diarized)
        segment = timeline["speech_segments"][0]

        self.assertEqual(stats["applied_labels"], 1)
        self.assertEqual(stats["overlap_segments"], 0)
        self.assertNotIn("overlap", segment)
        self.assertNotIn("overlap_speakers", segment)

    def test_plain_fast_asr_timeline_does_not_invent_speaker_label(self):
        transcription = TranscriptionResult(text="plain transcript", duration_seconds=2.0)

        with patch("wond.openai_analysis.probe_duration_seconds", return_value=2.0):
            timeline = build_audio_timeline(Path("sample.m4a"), transcription)

        self.assertIsNone(timeline["speech_segments"][0]["speaker"])

    def test_subprocess_json_loader_tolerates_warning_lines(self):
        payload = load_subprocess_json('warning: warmup\n{"text": "hello"}\n', label="test")

        self.assertEqual(payload["text"], "hello")


if __name__ == "__main__":
    unittest.main()
