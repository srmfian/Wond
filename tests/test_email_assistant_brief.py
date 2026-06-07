import tempfile
import unittest
from datetime import date
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from wond.compactor import (
    build_daily_compact_summary,
    daily_email_title,
    email_digest_model,
    email_digest_model_candidates,
    daily_highlight_prompt,
    email_report_language,
    weekly_email_title,
    weekly_highlight_prompt,
    write_daily_email_digest,
    write_weekly_email_digest,
)
from wond.config import load_settings
from wond.dashboard import api_settings_update
from wond.store import ActivitySample, Observation, Store


def settings_for(root: Path) -> SimpleNamespace:
    data_dir = root / "data"
    return SimpleNamespace(
        db_path=data_dir / "context.sqlite3",
        timezone="Asia/Tokyo",
        data_dir=data_dir,
        summary_dir=data_dir / "summaries",
        report_dir=data_dir / "reports",
        log_dir=data_dir / "logs",
        recycle_bin_dir=data_dir / "recycle_bin",
        speaker_sample_dir=data_dir / "speaker_samples",
    )


class EmailAssistantBriefTests(unittest.TestCase):
    def test_daily_prompt_requests_proactive_assistant_sections_and_safety(self):
        prompt = daily_highlight_prompt(date(2026, 6, 4), 6, language="zh")

        self.assertIn("每日主动简报 - 2026-06-04", prompt)
        self.assertIn("关系提醒", prompt)
        self.assertIn("健康/节律提醒", prompt)
        self.assertIn("未完成承诺与待跟进", prompt)
        self.assertIn("明日预警", prompt)
        self.assertIn("一句话建议", prompt)
        self.assertIn("Do not diagnose health", prompt)
        self.assertIn("暂无明确提醒", prompt)

    def test_weekly_prompt_uses_dashboard_language_sections(self):
        prompt = weekly_highlight_prompt(date(2026, 6, 1), date(2026, 6, 8), "2026-W23", 10, language="ja")

        self.assertIn("週間アシスタントブリーフ - 2026-W23", prompt)
        self.assertIn("人間関係マップ", prompt)
        self.assertIn("健康と生活リズムの傾向", prompt)
        self.assertIn("繰り返し現れたストレス源", prompt)
        self.assertIn("見落とされがちだが重要なこと", prompt)
        self.assertIn("来週の注意点", prompt)
        self.assertIn("Every proactive reminder should be grounded", prompt)

    def test_email_titles_and_language_follow_dashboard_config(self):
        settings = SimpleNamespace(dashboard={"language": "ko"}, raw={})

        self.assertEqual(email_report_language(settings), "ko")
        self.assertEqual(daily_email_title(date(2026, 6, 4), email_report_language(settings)), "일일 어시스턴트 브리핑 - 2026-06-04")
        self.assertEqual(weekly_email_title("2026-W23", email_report_language(settings)), "주간 어시스턴트 브리핑 - 2026-W23")

    def test_email_language_falls_back_to_raw_dashboard_config(self):
        settings = SimpleNamespace(raw={"dashboard": {"language": "zh"}})

        self.assertEqual(email_report_language(settings), "zh")

    def test_email_digest_model_prefers_period_specific_model(self):
        settings = SimpleNamespace(email_reports={"model": "qwen2.5:7b", "daily_model": "qwen3.5:35b"})

        self.assertEqual(email_digest_model(settings, "daily"), "qwen3.5:35b")
        self.assertEqual(email_digest_model(settings, "weekly"), "qwen2.5:7b")

    def test_email_digest_model_candidates_include_fallback_model(self):
        settings = SimpleNamespace(
            email_reports={"daily_model": "qwen3.5:35b-mlx", "fallback_model": "qwen3.5:35b"},
            local_ai={"text_model": "qwen3.5:35b"},
        )

        self.assertEqual(email_digest_model_candidates(settings, "daily"), ["qwen3.5:35b-mlx", "qwen3.5:35b"])

    def test_email_digest_model_candidates_fall_back_to_local_text_model(self):
        settings = SimpleNamespace(email_reports={"weekly_model": "qwen3.5:35b-mlx"}, local_ai={"text_model": "qwen3.5:35b"})

        self.assertEqual(email_digest_model_candidates(settings, "weekly"), ["qwen3.5:35b-mlx", None])

    def test_dashboard_language_setting_api_accepts_supported_languages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.json"
            config_path.write_text('{"data_dir":"data"}\n', encoding="utf-8")
            settings = load_settings(config_path)

            payload, status = api_settings_update(settings, {"updates": [{"key": "dashboard.language", "value": "ja"}]})

            self.assertEqual(status, HTTPStatus.OK)
            self.assertEqual(payload["settings"]["dashboard"]["language"], "ja")

    def test_compact_summary_adds_assistant_signals_for_weekly_email_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = settings_for(root)
            store = Store(settings.db_path)
            try:
                store.upsert_observations(
                    [
                        Observation(
                            source="messages",
                            kind="message",
                            source_key="message-1",
                            observed_at="2026-06-04T21:10:00+09:00",
                            title="明天需要回复签证材料",
                            body="Remember to follow up and confirm the document list tomorrow.",
                            actor="Alice",
                        ),
                        Observation(
                            source="mobile",
                            kind="audio_segment",
                            source_key="audio-1",
                            observed_at="2026-06-04T22:30:00+09:00",
                            title="Evening note",
                            body="今天有点累，晚上还在检查安装问题。",
                            metadata={"audio_analysis": {"status": "ok", "summary": "今天有点累，压力主要来自安装验证。"}},
                        ),
                    ]
                )
                store.add_activity_sample(
                    ActivitySample(
                        sampled_at="2026-06-04T23:40:00+09:00",
                        app="Terminal",
                        window_title="Wond install verification",
                    )
                )

                summary = build_daily_compact_summary(settings, store, date(2026, 6, 4))
            finally:
                store.close()

        self.assertIn("## Assistant Signals", summary)
        self.assertIn("Relationship candidates: Alice", summary)
        self.assertIn("Possible follow-ups/commitments", summary)
        self.assertIn("Health/life-rhythm mentions", summary)
        self.assertIn("Rhythm hints", summary)

    def test_daily_email_digest_passes_configured_daily_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = settings_for(root)
            settings.email_reports = {
                "ai_highlights": True,
                "daily_model": "qwen3.5:35b",
                "daily_highlight_items": 6,
                "highlight_source_max_chars": 30000,
                "ollama_timeout_seconds": 1800,
            }
            settings.dashboard = {"language": "en"}
            settings.raw = {"dashboard": {"language": "en"}}
            source_path = root / "report.md"
            source_path.write_text("# Source\n\nNeed to reply tomorrow.", encoding="utf-8")
            store = Store(settings.db_path)
            try:
                with patch("wond.compactor.summarize_text", return_value="# Daily Assistant Brief - 2026-06-04\n") as mock:
                    path = write_daily_email_digest(settings, store, date(2026, 6, 4), source_path=source_path)
                    self.assertTrue(path.exists())
                    self.assertEqual(mock.call_args.kwargs["model"], "qwen3.5:35b")
                    self.assertEqual(mock.call_args.kwargs["timeout_seconds"], 1800)
            finally:
                store.close()

    def test_daily_email_digest_falls_back_after_primary_model_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = settings_for(root)
            settings.email_reports = {
                "ai_highlights": True,
                "daily_model": "qwen3.5:35b-mlx",
                "fallback_model": "qwen3.5:35b",
                "daily_highlight_items": 6,
                "highlight_source_max_chars": 30000,
                "ollama_timeout_seconds": 2400,
            }
            settings.dashboard = {"language": "en"}
            settings.raw = {"dashboard": {"language": "en"}}
            settings.local_ai = {"text_model": "qwen3.5:35b"}
            source_path = root / "report.md"
            source_path.write_text("# Source\n\nNeed to reply tomorrow.", encoding="utf-8")
            store = Store(settings.db_path)
            try:
                with patch(
                    "wond.compactor.summarize_text",
                    side_effect=[RuntimeError("gpu timeout"), "# Daily Assistant Brief - 2026-06-04\n\n## Key Signals\n- Recovered."],
                ) as mock:
                    path = write_daily_email_digest(settings, store, date(2026, 6, 4), source_path=source_path)
                    self.assertTrue(path.exists())
                    self.assertEqual(
                        [call.kwargs["model"] for call in mock.call_args_list],
                        ["qwen3.5:35b-mlx", "qwen3.5:35b"],
                    )
                    self.assertEqual([call.kwargs["timeout_seconds"] for call in mock.call_args_list], [2400, 2400])
                    self.assertIn("Recovered", path.read_text(encoding="utf-8"))
            finally:
                store.close()

    def test_weekly_email_digest_passes_configured_weekly_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = settings_for(root)
            settings.email_reports = {
                "ai_highlights": True,
                "model": "qwen2.5:7b",
                "weekly_model": "qwen3.5:35b",
                "weekly_highlight_items": 10,
                "highlight_source_max_chars": 30000,
            }
            settings.dashboard = {"language": "en"}
            settings.raw = {"dashboard": {"language": "en"}}
            weekly_path = root / "weekly.md"
            weekly_path.write_text("# Weekly source\n", encoding="utf-8")
            store = Store(settings.db_path)
            try:
                with patch("wond.compactor.summarize_text", return_value="# Weekly Assistant Brief - 2026-W23\n") as mock:
                    path = write_weekly_email_digest(settings, store, date(2026, 6, 4), source_path=weekly_path)
                    self.assertTrue(path.exists())
                    self.assertEqual(mock.call_args.kwargs["model"], "qwen3.5:35b")
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
