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
    action_speaker_split_sample,
    action_speaker_unhide,
    api_speakers,
    api_insight_state_post,
    api_setup,
    api_setup_token,
    api_settings_update,
    data_quality_checks,
    editable_settings_schema,
    http_check,
    is_local_http_permission_error,
    ollama_check,
)
from wond.speaker_training import speaker_training_payload
from wond.privacy import privacy_center_payload
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
        self.assertIn("data-tip-source", DASHBOARD_HTML)
        self.assertIn("button.dataset.tipSource", DASHBOARD_HTML)
        self.assertIn("Refresh semantic index status.", DASHBOARD_HTML)

    def test_dashboard_has_multilingual_ui_runtime(self):
        self.assertIn('<html lang="en">', DASHBOARD_HTML)
        self.assertIn("const supportedLanguages", DASHBOARD_HTML)
        self.assertIn("['en', 'English']", DASHBOARD_HTML)
        self.assertIn("['zh', '中文']", DASHBOARD_HTML)
        self.assertIn("['ja', '日本語']", DASHBOARD_HTML)
        self.assertIn("['ko', '한국어']", DASHBOARD_HTML)
        self.assertIn("languageStorageKey = 'wond.dashboard.language'", DASHBOARD_HTML)
        self.assertIn("function setLanguage", DASHBOARD_HTML)
        self.assertIn("function startLocalization", DASHBOARD_HTML)
        self.assertIn("settingsLanguagePanel", DASHBOARD_HTML)
        self.assertIn("const i18nAttributeNames = ['placeholder', 'title', 'aria-label']", DASHBOARD_HTML)
        self.assertIn("function askConfirm", DASHBOARD_HTML)
        self.assertIn("['关键词或问题','Keyword or question'", DASHBOARD_HTML)
        self.assertIn("['索引状态','Index status'", DASHBOARD_HTML)
        self.assertIn("['向本地资料提问，例如：今天录音里有什么值得跟进？','Ask local knowledge", DASHBOARD_HTML)

    def test_mobile_status_is_integrated_into_sync_tab(self):
        self.assertIn("['sync','手机同步']", DASHBOARD_HTML)
        self.assertIn("function canonicalSection", DASHBOARD_HTML)
        self.assertIn("id === 'mobile' ? 'sync'", DASHBOARD_HTML)
        self.assertNotIn("['mobile','手机状态']", DASHBOARD_HTML)

    def test_dashboard_has_setup_wizard(self):
        self.assertIn("['setup','系统']", DASHBOARD_HTML)
        self.assertIn("['setup','启动向导']", DASHBOARD_HTML)
        self.assertIn("/api/setup", DASHBOARD_HTML)
        self.assertIn("async function setup", DASHBOARD_HTML)
        self.assertIn("setupGenerateToken", DASHBOARD_HTML)
        self.assertIn("安装全部服务", DASHBOARD_HTML)
        self.assertIn("copyFromButton", DASHBOARD_HTML)

    def test_dashboard_has_action_inbox_and_daily_workbench(self):
        self.assertIn("['action','行动']", DASHBOARD_HTML)
        self.assertIn("['action','行动总览']", DASHBOARD_HTML)
        self.assertIn("['inbox','处理队列']", DASHBOARD_HTML)
        self.assertIn("/api/action-inbox", DASHBOARD_HTML)
        self.assertIn("async function actionInbox", DASHBOARD_HTML)
        self.assertIn("function inboxCard", DASHBOARD_HTML)
        self.assertIn("state.inboxDate", DASHBOARD_HTML)

    def test_dashboard_has_project_memory_and_meeting_mode(self):
        self.assertIn("['memory','项目记忆']", DASHBOARD_HTML)
        self.assertIn("['meeting','会议']", DASHBOARD_HTML)
        self.assertIn("/api/project-memory", DASHBOARD_HTML)
        self.assertIn("/api/meeting-mode", DASHBOARD_HTML)
        self.assertIn("async function projectMemory", DASHBOARD_HTML)
        self.assertIn("async function meetingMode", DASHBOARD_HTML)
        self.assertIn("写入项目记忆", DASHBOARD_HTML)

    def test_dashboard_has_personal_memory_workspace(self):
        self.assertIn("['personal','个人档案']", DASHBOARD_HTML)
        self.assertIn("/api/personal-memory", DASHBOARD_HTML)
        self.assertIn("async function personalMemory", DASHBOARD_HTML)
        self.assertIn("记忆收件箱", DASHBOARD_HTML)
        self.assertIn("联系人档案", DASHBOARD_HTML)
        self.assertIn("冲突队列", DASHBOARD_HTML)

    def test_dashboard_has_privacy_retention_center(self):
        self.assertIn("['privacy','隐私与保留']", DASHBOARD_HTML)
        self.assertIn("/api/privacy", DASHBOARD_HTML)
        self.assertIn("async function privacyCenter", DASHBOARD_HTML)
        self.assertIn("privacySetBool", DASHBOARD_HTML)
        self.assertIn("privacyQuickRetention", DASHBOARD_HTML)
        self.assertIn("执行保留", DASHBOARD_HTML)

    def test_dashboard_has_speaker_training_loop(self):
        self.assertIn("['speaker-training','Speaker 训练']", DASHBOARD_HTML)
        self.assertIn("/api/speaker-training", DASHBOARD_HTML)
        self.assertIn("async function speakerTraining", DASHBOARD_HTML)
        self.assertIn("runSpeakerTrainingCycle", DASHBOARD_HTML)
        self.assertIn("setSpeakerTrainingView", DASHBOARD_HTML)
        self.assertIn("speaker_repair_embeddings", DASHBOARD_HTML)
        self.assertIn("speaker_refresh_sample_confidence", DASHBOARD_HTML)
        self.assertIn("speaker_refresh_representatives", DASHBOARD_HTML)
        self.assertIn("自动整理后复查", DASHBOARD_HTML)

    def test_speaker_training_empty_install_is_not_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(
                json.dumps({"data_dir": "data", "timezone": "Asia/Tokyo"}),
                encoding="utf-8",
            )
            settings = load_settings(config_path)

            payload = speaker_training_payload(settings, {})

        self.assertEqual(payload["summary"]["training_status"], "empty")
        self.assertEqual(payload["summary"]["training_score"], 0)
        self.assertEqual(payload["summary"]["blocked_stages"], 0)
        self.assertFalse(any(stage["status"] == "blocked" for stage in payload["stages"]))
        self.assertEqual(payload["stages"][0]["status"], "empty")
        self.assertIn("empty:'未开始'", DASHBOARD_HTML)
        self.assertIn("emptyTraining ? '未开始'", DASHBOARD_HTML)

    def test_speaker_training_payload_reports_loop_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "data_dir": "data",
                        "timezone": "Asia/Tokyo",
                        "speaker_recognition": {
                            "embedding_backend": "fixture",
                            "embedding_model": "test-model",
                            "auto_merge_threshold": 0.73,
                            "candidate_threshold": 0.74,
                        },
                    }
                ),
                encoding="utf-8",
            )
            settings = load_settings(config_path)
            store = Store(settings.db_path)
            try:
                alice = store.ensure_speaker_for_alias("fixture:alice", default_name="Alice", label="Alice")
                bob = store.ensure_speaker_for_alias("fixture:bob", default_name="Speaker 2", label="Speaker 2")
                store.conn.execute(
                    "UPDATE speakers SET identity_status = ?, confidence = ?, metadata = ? WHERE id = ?",
                    (
                        "named",
                        0.92,
                        json.dumps({"speaker_review_status": "confirmed"}, ensure_ascii=False),
                        int(alice["id"]),
                    ),
                )
                alice_sample = store.add_speaker_sample(
                    speaker_id=int(alice["id"]),
                    observation_id=None,
                    source_key="sample:alice",
                    media_path="alice-full.m4a",
                    sample_path="alice-sample.m4a",
                    start_seconds=1.0,
                    end_seconds=3.0,
                    transcript="hello from alice",
                    metadata={"sample_confidence": 0.91, "representative_sample": True},
                )
                bob_sample = store.add_speaker_sample(
                    speaker_id=int(bob["id"]),
                    observation_id=None,
                    source_key="sample:bob",
                    media_path="bob-full.m4a",
                    sample_path="bob-sample.m4a",
                    start_seconds=4.0,
                    end_seconds=6.0,
                    transcript="bob voice",
                    metadata={"sample_confidence": 0.2},
                )
                store.add_speaker_embedding(
                    speaker_id=int(alice["id"]),
                    sample_id=int(alice_sample["id"]),
                    model="fixture:test-model",
                    vector=[0.1, 0.2, 0.3],
                )
                store.record_speaker_match_decision(
                    source_speaker_id=int(bob["id"]),
                    target_speaker_id=int(alice["id"]),
                    sample_id=int(bob_sample["id"]),
                    model="fixture:test-model",
                    score=0.57,
                    threshold=0.68,
                    status="candidate",
                )
            finally:
                store.close()

            payload = speaker_training_payload(settings, {})

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["model"]["embedding_model"], "fixture:test-model")
        self.assertAlmostEqual(payload["model"]["auto_merge_threshold"], 0.73)
        self.assertAlmostEqual(payload["model"]["candidate_threshold"], 0.74)
        self.assertEqual(payload["summary"]["speakers"], 2)
        self.assertEqual(payload["summary"]["stable_speakers"], 1)
        self.assertEqual(payload["summary"]["missing_embeddings"], 1)
        self.assertEqual(payload["summary"]["low_confidence_samples"], 1)
        self.assertEqual(payload["summary"]["representative_samples"], 1)
        by_stage = {stage["key"]: stage for stage in payload["stages"]}
        self.assertEqual(by_stage["embedding"]["status"], "blocked")
        self.assertEqual(by_stage["organize"]["action"]["args"], {})
        self.assertIn("threshold 0.730", by_stage["organize"]["detail"])
        self.assertTrue(any(row["training_state"] == "confirmed" for row in payload["speakers"]))
        self.assertTrue(any("missing_embedding" in row["issues"] for row in payload["sample_queue"]))
        self.assertEqual(payload["recent_matches"][0]["status"], "candidate")

    def test_speakers_payload_uses_configured_thresholds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "data_dir": "data",
                        "timezone": "Asia/Tokyo",
                        "speaker_recognition": {
                            "embedding_backend": "fixture",
                            "embedding_model": "test-model",
                            "auto_merge_threshold": 0.82,
                            "auto_merge_max_merges": 123,
                            "candidate_threshold": 0.75,
                        },
                    }
                ),
                encoding="utf-8",
            )
            settings = load_settings(config_path)
            store = Store(settings.db_path)
            try:
                speaker = store.ensure_speaker_for_alias("fixture:voice", default_name="Voice 1", label="Voice 1")
                speaker_id = int(speaker["id"])
                store.conn.execute(
                    "UPDATE speakers SET confidence = ? WHERE id = ?",
                    (0.72, speaker_id),
                )
                for index, vector in enumerate(([1.0, 0.0], [0.72, 0.28]), start=1):
                    sample = store.add_speaker_sample(
                        speaker_id=speaker_id,
                        observation_id=None,
                        source_key=f"sample:{index}",
                        media_path=None,
                        sample_path=f"sample-{index}.m4a",
                        start_seconds=0.0,
                        end_seconds=1.0,
                        transcript=f"sample {index}",
                        metadata={"sample_confidence": 0.72},
                    )
                    store.add_speaker_embedding(
                        speaker_id=speaker_id,
                        sample_id=int(sample["id"]),
                        model="fixture:test-model",
                        vector=vector,
                    )
            finally:
                store.close()

            payload = api_speakers(settings)

        thresholds = payload["config"]["speaker_recognition"]
        self.assertAlmostEqual(thresholds["auto_merge_threshold"], 0.82)
        self.assertEqual(thresholds["auto_merge_max_merges"], 123)
        self.assertAlmostEqual(thresholds["candidate_threshold"], 0.75)
        self.assertEqual(payload["speakers"][0]["confidence_summary"]["level"], "low")
        self.assertIn("0.750", payload["speakers"][0]["confidence_summary"]["detail"])

    def test_speakers_payload_returns_all_samples_for_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.json"
            config_path.write_text(json.dumps({"data_dir": "data", "timezone": "Asia/Tokyo"}), encoding="utf-8")
            settings = load_settings(config_path)
            store = Store(settings.db_path)
            try:
                speaker = store.ensure_speaker_for_alias("fixture:voice", default_name="Voice 1", label="Voice 1")
                for index in range(305):
                    store.add_speaker_sample(
                        speaker_id=int(speaker["id"]),
                        observation_id=None,
                        source_key=f"sample:{index}",
                        media_path=None,
                        sample_path=f"sample-{index}.m4a",
                        start_seconds=float(index),
                        end_seconds=float(index + 1),
                        transcript=f"sample {index}",
                        metadata={},
                    )
            finally:
                store.close()

            payload = api_speakers(settings)

        self.assertEqual(len(payload["samples"]), 305)
        self.assertEqual(payload["speakers"][0]["sample_count"], 305)

    def test_privacy_payload_reports_sensitive_sources_and_retention(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "data_dir": "data",
                        "timezone": "Asia/Tokyo",
                        "collectors": {"messages": True, "apple_mail": True},
                        "retention": {"require_daily_summary_before_prune": False, "raw_observations_days": 30},
                    }
                ),
                encoding="utf-8",
            )
            settings = load_settings(config_path)
            store = Store(settings.db_path)
            try:
                store.upsert_observations(
                    [
                        Observation(
                            source="messages",
                            kind="message",
                            source_key="m1",
                            observed_at="2025-01-01T09:00:00+09:00",
                            title="private message text",
                        ),
                        Observation(
                            source="apple_mail",
                            kind="email",
                            source_key="mail1",
                            observed_at="2025-01-01T10:00:00+09:00",
                            title="private subject",
                            body="private body preview",
                        ),
                    ]
                )
            finally:
                store.close()

            payload = privacy_center_payload(settings, {})
            by_id = {row["id"]: row for row in payload["sources"]}
            checks = {row["id"]: row for row in payload["checks"]}

            self.assertTrue(payload["ok"])
            self.assertEqual(by_id["messages"]["count"], 1)
            self.assertEqual(by_id["apple_mail"]["body_rows"], 1)
            self.assertGreaterEqual(payload["summary"]["high_sensitivity_enabled"], 2)
            self.assertIn("preview", payload["retention"])
            self.assertIn("mobile", payload["cleanup"])
            self.assertEqual(checks["mail_body_preview"]["status"], "warn")
            self.assertIn("publication", payload)

    def test_insight_state_accepts_action_inbox_item_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(json.dumps({"data_dir": "data", "timezone": "Asia/Tokyo"}), encoding="utf-8")
            settings = load_settings(config_path)

            for item_type in ("repair", "quick_tag", "speaker"):
                result, status = api_insight_state_post(
                    settings,
                    {"item_id": f"{item_type}:1", "item_type": item_type, "status": "done", "pinned": True},
                )

                self.assertEqual(status, HTTPStatus.OK)
                self.assertEqual(result["state"]["item_type"], item_type)
                self.assertEqual(result["state"]["status"], "done")

    def test_setup_payload_reports_config_token_and_services(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "data_dir": "data",
                        "timezone": "Asia/Tokyo",
                        "mobile_sync": {"token": "secret-token", "port": 9876},
                    }
                ),
                encoding="utf-8",
            )
            settings = load_settings(config_path)

            payload = api_setup(settings)

            self.assertTrue(payload["ok"])
            self.assertTrue(payload["sync"]["token_configured"])
            self.assertEqual(payload["sync"]["port"], 9876)
            self.assertIn("summary", payload)
            self.assertIn("services", payload)
            self.assertTrue(any(row["key"] == "sync" for row in payload["services"]))
            self.assertTrue(any(row["url"].endswith(":9876/upload") for row in payload["sync"]["upload_urls"]))

    def test_setup_token_generation_writes_config_and_returns_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(
                json.dumps({"data_dir": "data", "timezone": "Asia/Tokyo", "mobile_sync": {"port": 8765}}),
                encoding="utf-8",
            )
            settings = load_settings(config_path)

            payload, status = api_setup_token(settings)

            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(status, HTTPStatus.OK)
            self.assertTrue(payload["token"])
            self.assertEqual(saved["mobile_sync"]["token"], payload["token"])
            self.assertTrue(payload["sync"]["token_configured"])

    def test_dashboard_has_record_maintenance_tab(self):
        self.assertIn("['maintenance','记录维护']", DASHBOARD_HTML)
        self.assertIn("async function maintenance", DASHBOARD_HTML)
        self.assertIn("/api/maintenance", DASHBOARD_HTML)
        self.assertIn("执行记录清理", DASHBOARD_HTML)

    def test_dashboard_nav_is_grouped_into_five_workspaces(self):
        self.assertIn("const utilitySections", DASHBOARD_HTML)
        self.assertIn("const childSections", DASHBOARD_HTML)
        self.assertIn("const sectionGroups", DASHBOARD_HTML)
        self.assertIn("const navParents", DASHBOARD_HTML)
        self.assertIn("const sectionTabs", DASHBOARD_HTML)
        self.assertIn("function sectionNav", DASHBOARD_HTML)
        self.assertIn("section: 'today'", DASHBOARD_HTML)
        self.assertIn("const sections = [\n  ['today','今天'], ['action','行动'], ['search','资料'], ['audio','音频'], ['setup','系统']\n];", DASHBOARD_HTML)
        self.assertIn("['today','今天']", DASHBOARD_HTML)
        self.assertIn("['recycle','回收箱']", DASHBOARD_HTML)
        self.assertIn("inbox:'action'", DASHBOARD_HTML)
        self.assertIn("projects:'action'", DASHBOARD_HTML)
        self.assertIn("memory:'action'", DASHBOARD_HTML)
        self.assertIn("'speaker-training':'audio'", DASHBOARD_HTML)
        self.assertIn("files:'search'", DASHBOARD_HTML)
        self.assertIn("privacy:'setup'", DASHBOARD_HTML)
        self.assertIn("maintenance:'setup'", DASHBOARD_HTML)
        self.assertIn("overview:'setup'", DASHBOARD_HTML)

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
        self.assertIn("speaker_split_sample", DASHBOARD_HTML)
        self.assertIn("speaker_refresh_sample_confidence", DASHBOARD_HTML)
        self.assertIn("speaker_auto_organize", DASHBOARD_HTML)
        self.assertIn("speaker_confirm", DASHBOARD_HTML)
        self.assertIn("speaker_unhide", DASHBOARD_HTML)
        self.assertIn("detachSpeakerSample", DASHBOARD_HTML)
        self.assertIn("refreshSpeakerSampleConfidence", DASHBOARD_HTML)
        self.assertIn("autoOrganizeSpeakers", DASHBOARD_HTML)
        self.assertIn("自动整理相似声音", DASHBOARD_HTML)
        self.assertIn("speakerAutoMergeThreshold", DASHBOARD_HTML)
        self.assertNotIn("{threshold:0.68}", DASHBOARD_HTML)
        self.assertIn('preload="none"', DASHBOARD_HTML)
        self.assertNotIn('preload="metadata"', DASHBOARD_HTML)
        self.assertIn("自动整理待确认", DASHBOARD_HTML)
        self.assertNotIn("合并审核", DASHBOARD_HTML)
        self.assertIn("隐藏低相似", DASHBOARD_HTML)
        self.assertIn("分离成新说话人", DASHBOARD_HTML)
        self.assertIn("手动切分样本", DASHBOARD_HTML)
        self.assertIn("splitSpeakerSample", DASHBOARD_HTML)
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
        split_cmd = action_speaker_split_sample(
            SimpleNamespace(),
            {"sample_id": "12", "cuts": "3.2, 7.8", "keep_speaker": True},
        )
        refresh_cmd = action_speaker_refresh_sample_confidence(
            SimpleNamespace(),
            {"speaker_ids": ["4", "4", "5"]},
        )
        refresh_all_cmd = action_speaker_refresh_sample_confidence(SimpleNamespace(), {})
        organize_default_cmd = action_speaker_auto_organize(SimpleNamespace(), {})
        organize_cmd = action_speaker_auto_organize(SimpleNamespace(), {"threshold": 0.68, "max_merges": 9})
        confirm_cmd = action_speaker_confirm(SimpleNamespace(), {"speaker_ids": ["4", "5"]})
        unhide_cmd = action_speaker_unhide(SimpleNamespace(), {"speaker_id": "6"})

        self.assertEqual(merge_cmd[-4:], ["merge-many", "9", "1", "2"])
        self.assertEqual(delete_cmd[-4:], ["delete-many", "1", "2", "--apply"])
        self.assertEqual(detach_cmd[-4:], ["detach-sample", "12", "--display-name", "Alice"])
        self.assertEqual(split_cmd[-5:], ["split-sample", "12", "--cuts", "3.2, 7.8", "--keep-speaker"])
        self.assertEqual(refresh_cmd[-3:], ["refresh-sample-confidence", "4", "5"])
        self.assertEqual(refresh_all_cmd[-1:], ["refresh-sample-confidence"])
        self.assertNotIn("--threshold", organize_default_cmd)
        self.assertEqual(organize_cmd[-5:], ["--apply", "--max-merges", "9", "--threshold", "0.68"])
        self.assertEqual(confirm_cmd[-3:], ["confirm", "4", "5"])
        self.assertEqual(unhide_cmd[-2:], ["unhide", "6"])

    def test_settings_page_has_edit_controls(self):
        self.assertIn("settingsEditPanel", DASHBOARD_HTML)
        self.assertIn("saveSettingsGroup", DASHBOARD_HTML)
        self.assertIn("保存设置", DASHBOARD_HTML)
        self.assertIn("/api/settings',{method:'POST'", DASHBOARD_HTML)

    def test_speaker_sample_seconds_setting_is_limited_to_sixteen_seconds(self):
        fields = {field["key"]: field for field in editable_settings_schema()}

        self.assertEqual(fields["speaker_recognition.sample_seconds"]["max"], 16)
        self.assertEqual(fields["speaker_recognition.sample_min_seconds"]["max"], 16)
        self.assertEqual(fields["speaker_recognition.sample_stride_seconds"]["max"], 120)
        self.assertEqual(fields["speaker_recognition.samples_per_speaker_per_observation"]["max"], 200)
        self.assertEqual(fields["speaker_recognition.sample_unlabeled_speech"]["type"], "bool")
        self.assertEqual(fields["speaker_recognition.auto_merge_max_merges"]["max"], 5000)
        self.assertEqual(fields["audio_preprocessing.quality_min_speech_seconds"]["max"], 16)
        self.assertEqual(fields["audio_preprocessing.quality_min_speech_ratio"]["max"], 1)

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
