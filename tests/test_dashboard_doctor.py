import json
import tempfile
import unittest
import urllib.error
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from wond.config import load_settings
from wond.dashboard import (
    DASHBOARD_HTML,
    action_speaker_auto_organize,
    action_speaker_confirm,
    action_speaker_delete_many,
    action_speaker_detach_sample,
    action_speaker_merge_many,
    action_speaker_refresh_sample_confidence,
    action_speaker_unhide,
    api_settings_update,
    data_quality_checks,
    http_check,
    is_local_http_permission_error,
    ollama_check,
)
from wond.store import Observation, Store


class DashboardDoctorTests(unittest.TestCase):
    def test_local_http_permission_errors_are_detected(self):
        exc = urllib.error.URLError(PermissionError(1, "Operation not permitted"))

        self.assertTrue(is_local_http_permission_error(exc))

    def test_http_check_marks_sandbox_block_as_warning(self):
        exc = urllib.error.URLError(PermissionError(1, "Operation not permitted"))
        with patch("wond.dashboard.http_json", side_effect=exc):
            check = http_check("sync", "Sync /health", "http://127.0.0.1:8765/health")

        self.assertEqual(check["status"], "warn")
        self.assertIn("blocked", check["message"])

    def test_ollama_check_marks_sandbox_block_as_warning(self):
        settings = SimpleNamespace(
            local_ai={
                "ollama_base_url": "http://127.0.0.1:11434",
                "text_model": "qwen3.5:35b",
                "vision_model": "qwen3.5:35b",
            },
            audio_analysis={},
        )
        exc = urllib.error.URLError(PermissionError(1, "Operation not permitted"))
        with patch("wond.dashboard.http_json", side_effect=exc):
            check = ollama_check(settings)

        self.assertEqual(check["status"], "warn")
        self.assertIn("blocked", check["message"])

    def test_data_quality_reports_collector_errors_and_stale_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = SimpleNamespace(db_path=root / "context.sqlite3")
            store = Store(settings.db_path)
            self.addCleanup(store.close)
            store.upsert_observations(
                [
                    Observation(
                        source="system",
                        kind="collector_error",
                        source_key="reminders:2026-06-02",
                        observed_at="2026-06-02T09:00:00+09:00",
                        title="reminders failed",
                        body="reminders timed out after 30s",
                        metadata={"collector": "reminders"},
                    )
                ]
            )
            store.conn.execute(
                "INSERT INTO collector_runs (collector, started_at, status) VALUES (?, ?, ?)",
                ("file_analysis", "1970-01-01T00:00:00+00:00", "running"),
            )
            store.conn.commit()

            checks = data_quality_checks(settings, store)
            by_name = {check["name"]: check for check in checks}

            self.assertEqual(by_name["Collector errors"]["status"], "warn")
            self.assertIn("reminders timed out", by_name["Collector errors"]["message"])
            self.assertEqual(by_name["Stale running collector runs"]["status"], "warn")
            self.assertIn("file_analysis", by_name["Stale running collector runs"]["message"])

    def test_dashboard_has_button_tooltip_runtime(self):
        self.assertIn("buttonTooltip", DASHBOARD_HTML)
        self.assertIn("function applyButtonTips", DASHBOARD_HTML)
        self.assertIn("const actionTips", DASHBOARD_HTML)

    def test_mobile_status_is_integrated_into_sync_tab(self):
        self.assertIn("['sync','手机同步']", DASHBOARD_HTML)
        self.assertIn("function canonicalSection", DASHBOARD_HTML)
        self.assertIn("id === 'mobile' ? 'sync'", DASHBOARD_HTML)
        self.assertNotIn("['mobile','手机状态']", DASHBOARD_HTML)

    def test_dashboard_has_record_maintenance_tab(self):
        self.assertIn("['maintenance','记录维护']", DASHBOARD_HTML)
        self.assertIn("async function maintenance", DASHBOARD_HTML)
        self.assertIn("/api/maintenance", DASHBOARD_HTML)
        self.assertIn("执行记录清理", DASHBOARD_HTML)

    def test_dashboard_nav_is_grouped_and_low_frequency_pages_are_utilities(self):
        self.assertIn("const utilitySections", DASHBOARD_HTML)
        self.assertIn("const sectionGroups", DASHBOARD_HTML)
        self.assertIn("const navParents", DASHBOARD_HTML)
        self.assertIn("section: 'today'", DASHBOARD_HTML)
        self.assertIn("['today','今天']", DASHBOARD_HTML)
        self.assertIn("['recycle','回收箱']", DASHBOARD_HTML)
        self.assertIn("maintenance:'settings'", DASHBOARD_HTML)
        self.assertIn("低频维护工具", DASHBOARD_HTML)

    def test_speakers_tab_has_review_workflow_controls(self):
        self.assertIn("speakerOperationPanel", DASHBOARD_HTML)
        self.assertIn("toggleSpeakerSelection", DASHBOARD_HTML)
        self.assertIn("selectVisibleSpeakers", DASHBOARD_HTML)
        self.assertIn("invertVisibleSpeakers", DASHBOARD_HTML)
        self.assertIn("bulkMergeSpeakers", DASHBOARD_HTML)
        self.assertIn("bulkDeleteSpeakers", DASHBOARD_HTML)
        self.assertIn("speaker_merge_many", DASHBOARD_HTML)
        self.assertIn("speaker_delete_many", DASHBOARD_HTML)
        self.assertIn("speaker_detach_sample", DASHBOARD_HTML)
        self.assertIn("speaker_refresh_sample_confidence", DASHBOARD_HTML)
        self.assertIn("speaker_auto_organize", DASHBOARD_HTML)
        self.assertIn("speaker_confirm", DASHBOARD_HTML)
        self.assertIn("speaker_unhide", DASHBOARD_HTML)
        self.assertIn("detachSpeakerSample", DASHBOARD_HTML)
        self.assertIn("refreshSpeakerSampleConfidence", DASHBOARD_HTML)
        self.assertIn("autoOrganizeSpeakers", DASHBOARD_HTML)
        self.assertIn("自动整理相似声音", DASHBOARD_HTML)
        self.assertIn("自动整理待确认", DASHBOARD_HTML)
        self.assertNotIn("合并审核", DASHBOARD_HTML)
        self.assertIn("隐藏低相似", DASHBOARD_HTML)
        self.assertIn("分离成新说话人", DASHBOARD_HTML)
        self.assertNotIn("speaker_split_sample", DASHBOARD_HTML)
        self.assertNotIn("splitSpeakerSample", DASHBOARD_HTML)
        self.assertNotIn("speakerSplitModal", DASHBOARD_HTML)
        self.assertNotIn("splitSpeakerAtCurrentTime", DASHBOARD_HTML)
        self.assertNotIn("submitSpeakerSplit", DASHBOARD_HTML)
        self.assertNotIn("按行输入片段", DASHBOARD_HTML)
        self.assertIn("合并选中", DASHBOARD_HTML)
        self.assertIn("删除选中", DASHBOARD_HTML)
        self.assertNotIn("设为重复", DASHBOARD_HTML)
        self.assertNotIn("设为保留", DASHBOARD_HTML)

    def test_speaker_bulk_actions_build_cli_commands(self):
        merge_cmd = action_speaker_merge_many(
            SimpleNamespace(),
            {"target_id": "9", "source_ids": ["1", "9", "2", "1"]},
        )
        delete_cmd = action_speaker_delete_many(SimpleNamespace(), {"speaker_ids": ["1", "2", "1"]})
        detach_cmd = action_speaker_detach_sample(
            SimpleNamespace(),
            {"sample_id": "12", "display_name": "Alice"},
        )
        refresh_cmd = action_speaker_refresh_sample_confidence(
            SimpleNamespace(),
            {"speaker_ids": ["4", "4", "5"]},
        )
        refresh_all_cmd = action_speaker_refresh_sample_confidence(SimpleNamespace(), {})
        organize_cmd = action_speaker_auto_organize(SimpleNamespace(), {"threshold": 0.68, "max_merges": 9})
        confirm_cmd = action_speaker_confirm(SimpleNamespace(), {"speaker_ids": ["4", "5"]})
        unhide_cmd = action_speaker_unhide(SimpleNamespace(), {"speaker_id": "6"})

        self.assertEqual(merge_cmd[-4:], ["merge-many", "9", "1", "2"])
        self.assertEqual(delete_cmd[-4:], ["delete-many", "1", "2", "--apply"])
        self.assertEqual(detach_cmd[-4:], ["detach-sample", "12", "--display-name", "Alice"])
        self.assertEqual(refresh_cmd[-3:], ["refresh-sample-confidence", "4", "5"])
        self.assertEqual(refresh_all_cmd[-1:], ["refresh-sample-confidence"])
        self.assertEqual(organize_cmd[-5:], ["--apply", "--max-merges", "9", "--threshold", "0.68"])
        self.assertEqual(confirm_cmd[-3:], ["confirm", "4", "5"])
        self.assertEqual(unhide_cmd[-2:], ["unhide", "6"])

    def test_settings_page_has_edit_controls(self):
        self.assertIn("settingsEditPanel", DASHBOARD_HTML)
        self.assertIn("saveSettingsGroup", DASHBOARD_HTML)
        self.assertIn("保存设置", DASHBOARD_HTML)
        self.assertIn("/api/settings',{method:'POST'", DASHBOARD_HTML)

    def test_settings_update_writes_allowlisted_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "data_dir": "data",
                        "timezone": "Asia/Tokyo",
                        "collectors": {"calendar": True},
                        "audio_analysis": {"auto_limit": 5},
                        "mobile_sync": {"token": "secret"},
                    }
                ),
                encoding="utf-8",
            )
            settings = load_settings(config_path)

            result, status = api_settings_update(
                settings,
                {
                    "updates": [
                        {"key": "collectors.calendar", "value": False},
                        {"key": "audio_analysis.auto_limit", "value": "7"},
                        {"key": "watch_paths", "value": ["~/Desktop", "~/Downloads"]},
                    ]
                },
            )

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(status, HTTPStatus.OK)
            self.assertEqual(result["changed_count"], 3)
            self.assertFalse(saved["collectors"]["calendar"])
            self.assertEqual(saved["audio_analysis"]["auto_limit"], 7)
            self.assertEqual(saved["watch_paths"], ["~/Desktop", "~/Downloads"])
            self.assertEqual(result["settings"]["mobile_sync"]["token"], "configured")

    def test_settings_update_rejects_sensitive_unknown_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(
                json.dumps({"data_dir": "data", "timezone": "Asia/Tokyo", "mobile_sync": {"token": "secret"}}),
                encoding="utf-8",
            )
            settings = load_settings(config_path)

            result, status = api_settings_update(settings, {"updates": [{"key": "mobile_sync.token", "value": "new"}]})

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(status, HTTPStatus.BAD_REQUEST)
            self.assertEqual(result["error"], "unsupported_setting:mobile_sync.token")
            self.assertEqual(saved["mobile_sync"]["token"], "secret")


if __name__ == "__main__":
    unittest.main()
