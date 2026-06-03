import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from wond.audio_preprocessing import create_overlap_candidate_clip, sepformer_model_dir


class AudioPreprocessingTests(unittest.TestCase):
    def test_overlap_backend_prefers_speechbrain_sepformer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(
                data_dir=root,
                audio_preprocessing={
                    "enabled": True,
                    "overlap_separation_backend": "speechbrain_sepformer",
                },
            )
            with (
                patch(
                    "wond.audio_preprocessing.create_overlap_candidate_with_speechbrain",
                    return_value=(True, {"status": "separated", "backend": "speechbrain_sepformer"}),
                ) as sepformer,
                patch("wond.audio_preprocessing.create_overlap_candidate_with_bandpass") as bandpass,
            ):
                ok, metadata = create_overlap_candidate_clip(
                    settings,
                    root / "input.wav",
                    root / "output.m4a",
                    0.0,
                    2.0,
                    stem_index=0,
                )

        self.assertTrue(ok)
        self.assertEqual(metadata["backend"], "speechbrain_sepformer")
        sepformer.assert_called_once()
        bandpass.assert_not_called()

    def test_overlap_backend_falls_back_to_bandpass_when_sepformer_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(
                data_dir=root,
                audio_preprocessing={
                    "enabled": True,
                    "overlap_separation_backend": "speechbrain_sepformer",
                    "overlap_separation_fallback_enabled": True,
                    "overlap_separation_fallback_backend": "ffmpeg_bandpass",
                },
            )
            with (
                patch(
                    "wond.audio_preprocessing.create_overlap_candidate_with_speechbrain",
                    return_value=(False, {"status": "sepformer_failed", "backend": "speechbrain_sepformer"}),
                ),
                patch(
                    "wond.audio_preprocessing.create_overlap_candidate_with_bandpass",
                    return_value=(True, {"status": "separated", "backend": "ffmpeg_bandpass"}),
                ) as bandpass,
            ):
                ok, metadata = create_overlap_candidate_clip(
                    settings,
                    root / "input.wav",
                    root / "output.m4a",
                    0.0,
                    2.0,
                    stem_index=1,
                )

        self.assertTrue(ok)
        self.assertEqual(metadata["backend"], "ffmpeg_bandpass")
        self.assertEqual(metadata["fallback_from"]["backend"], "speechbrain_sepformer")
        bandpass.assert_called_once()

    def test_sepformer_model_dir_is_under_data_dir_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(
                data_dir=root,
                audio_preprocessing={},
            )
            path = sepformer_model_dir(settings, "speechbrain/sepformer-whamr16k")

        self.assertEqual(path.name, "speechbrain__sepformer-whamr16k")


if __name__ == "__main__":
    unittest.main()
