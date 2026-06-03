import unittest
from datetime import date
from types import SimpleNamespace

from wond.agent import audio_analysis_days, audio_analysis_lookback_days


class AgentAudioDaysTests(unittest.TestCase):
    def test_default_audio_days_include_yesterday_and_today(self):
        settings = SimpleNamespace(audio_analysis={})

        self.assertEqual(
            audio_analysis_days(settings, date(2026, 6, 1)),
            [date(2026, 5, 31), date(2026, 6, 1)],
        )

    def test_audio_days_can_disable_lookback(self):
        settings = SimpleNamespace(audio_analysis={"lookback_days": 0})

        self.assertEqual(audio_analysis_days(settings, date(2026, 6, 1)), [date(2026, 6, 1)])

    def test_invalid_lookback_uses_default(self):
        settings = SimpleNamespace(audio_analysis={"lookback_days": "bad"})

        self.assertEqual(audio_analysis_lookback_days(settings), 1)


if __name__ == "__main__":
    unittest.main()
