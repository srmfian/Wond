import json
import unittest
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from wond.config import Settings
from wond.file_analysis import analyze_new_files, lock_path, save_state, should_include_file
from wond.openai_analysis import MediaAnalysisResult
from wond.store import Store


class FileAnalysisTests(unittest.TestCase):
    def test_skips_office_lock_files(self):
        self.assertFalse(should_include_file(Path("~$Externalities_models_welfare_final.pptx"), {".pptx"}, set()))

    def test_includes_regular_supported_file(self):
        self.assertTrue(should_include_file(Path("Externalities_models_welfare_final.pptx"), {".pptx"}, set()))

    def test_user_file_analysis_uses_copy_and_keeps_original(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            downloads = tmp / "Downloads"
            downloads.mkdir()
            original = downloads / "deck.pptx"
            original.write_bytes(b"pptx-ish")
            data_dir = tmp / "wond" / "data"
            settings = Settings(
                path=tmp / "wond" / "config.json",
                data_dir=data_dir,
                timezone="Asia/Tokyo",
                watch_paths=[downloads],
                file_analysis={
                    "enabled": True,
                    "scan_interval_seconds": 0,
                    "stability_seconds": 0,
                    "max_files_per_scan": 1,
                    "delete_after_analysis": True,
                    "analysis_copy_dir": "file_analysis_workspace",
                    "include_suffixes": [".pptx"],
                    "exclude_suffixes": [],
                    "exclude_dirs": [],
                },
                recycle_bin={
                    "enabled": True,
                    "dir": "recycle_bin",
                    "retention_hours": 24,
                    "purge_on_scan": False,
                },
            )
            store = Store(data_dir / "test.sqlite3")
            self.addCleanup(store.close)
            save_state(settings, {"watermark": 1, "last_scan_ts": 0, "processed_keys": {}})

            seen: dict[str, object] = {}

            def fake_analyze(_settings, _store, paths, **kwargs):
                seen["path"] = paths[0]
                seen["observation_paths"] = kwargs.get("observation_paths")
                return MediaAnalysisResult(analyzed=1)

            with patch("wond.file_analysis.analyze_paths_with_openai", side_effect=fake_analyze):
                result = analyze_new_files(settings, store, now_ts=time.time() + 100, force_scan=True)

            self.assertEqual(result.analyzed, 1)
            self.assertTrue(original.exists())
            analysis_path = seen["path"]
            self.assertIsInstance(analysis_path, Path)
            self.assertFalse(analysis_path.exists())
            self.assertIn((data_dir / "file_analysis_workspace").resolve(), analysis_path.parents)
            self.assertEqual(seen["observation_paths"], {analysis_path: original.resolve()})
            recycled = list((data_dir / "recycle_bin").rglob("*.pptx"))
            self.assertEqual(len(recycled), 1)
            self.assertEqual(recycled[0].read_bytes(), b"pptx-ish")

    def test_failed_file_analysis_uses_retry_backoff_without_recopying(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            downloads = tmp / "Downloads"
            downloads.mkdir()
            original = downloads / "deck.pdf"
            original.write_bytes(b"pdf-ish")
            data_dir = tmp / "wond" / "data"
            settings = Settings(
                path=tmp / "wond" / "config.json",
                data_dir=data_dir,
                timezone="Asia/Tokyo",
                watch_paths=[downloads],
                file_analysis={
                    "enabled": True,
                    "scan_interval_seconds": 0,
                    "stability_seconds": 0,
                    "max_files_per_scan": 1,
                    "retry_after_seconds": 3600,
                    "analysis_copy_dir": "file_analysis_workspace",
                    "include_suffixes": [".pdf"],
                    "exclude_suffixes": [],
                    "exclude_dirs": [],
                },
                recycle_bin={
                    "enabled": True,
                    "dir": "recycle_bin",
                    "retention_hours": 24,
                    "purge_on_scan": False,
                },
            )
            store = Store(data_dir / "test.sqlite3")
            self.addCleanup(store.close)
            save_state(settings, {"watermark": 1, "last_scan_ts": 0, "processed_keys": {}})

            calls = 0

            def fake_analyze(_settings, _store, paths, **kwargs):
                nonlocal calls
                calls += 1
                self.assertIn((data_dir / "file_analysis_workspace").resolve(), paths[0].parents)
                raise RuntimeError("local analysis unavailable")

            now_ts = time.time() + 100
            with patch("wond.file_analysis.analyze_paths_with_openai", side_effect=fake_analyze):
                first = analyze_new_files(settings, store, now_ts=now_ts, force_scan=True)
                second = analyze_new_files(settings, store, now_ts=now_ts + 10, force_scan=True)

            self.assertEqual(first.failed, 1)
            self.assertEqual(second.skipped, 1)
            self.assertEqual(calls, 1)
            state = json.loads((data_dir / "file_analysis_state.json").read_text(encoding="utf-8"))
            self.assertEqual(len(state["failed_keys"]), 1)
            recycled = list((data_dir / "recycle_bin").rglob("*.pdf"))
            self.assertEqual(len(recycled), 1)

    def test_file_analysis_lock_skips_concurrent_run(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            downloads = tmp / "Downloads"
            downloads.mkdir()
            (downloads / "deck.pdf").write_bytes(b"pdf-ish")
            data_dir = tmp / "wond" / "data"
            settings = Settings(
                path=tmp / "wond" / "config.json",
                data_dir=data_dir,
                timezone="Asia/Tokyo",
                watch_paths=[downloads],
                file_analysis={
                    "enabled": True,
                    "scan_interval_seconds": 0,
                    "stability_seconds": 0,
                    "lock_stale_seconds": 3600,
                    "include_suffixes": [".pdf"],
                    "exclude_suffixes": [],
                    "exclude_dirs": [],
                },
                recycle_bin={"enabled": True, "purge_on_scan": False},
            )
            store = Store(data_dir / "test.sqlite3")
            self.addCleanup(store.close)
            save_state(settings, {"watermark": 1, "last_scan_ts": 0, "processed_keys": {}})
            lock = lock_path(settings)
            lock.parent.mkdir(parents=True, exist_ok=True)
            lock.write_text("held", encoding="utf-8")

            with patch("wond.file_analysis.analyze_paths_with_openai") as analyze:
                result = analyze_new_files(settings, store, now_ts=time.time() + 100, force_scan=True)

            self.assertEqual(result.skipped, 1)
            self.assertTrue(lock.exists())
            analyze.assert_not_called()

    def test_file_analysis_marks_stale_running_runs(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            data_dir = tmp / "wond" / "data"
            downloads = tmp / "Downloads"
            downloads.mkdir()
            settings = Settings(
                path=tmp / "wond" / "config.json",
                data_dir=data_dir,
                timezone="Asia/Tokyo",
                watch_paths=[downloads],
                file_analysis={
                    "enabled": True,
                    "scan_interval_seconds": 0,
                    "stability_seconds": 0,
                    "run_stale_seconds": 60,
                    "include_suffixes": [".pdf"],
                    "exclude_suffixes": [],
                    "exclude_dirs": [],
                },
                recycle_bin={"enabled": True, "purge_on_scan": False},
            )
            store = Store(data_dir / "test.sqlite3")
            self.addCleanup(store.close)
            save_state(settings, {"watermark": 1, "last_scan_ts": 0, "processed_keys": {}})
            store.conn.execute(
                "INSERT INTO collector_runs (collector, started_at, status) VALUES (?, ?, ?)",
                ("file_analysis", "1970-01-01T00:00:00+00:00", "running"),
            )
            store.conn.commit()

            result = analyze_new_files(settings, store, now_ts=time.time() + 100, force_scan=True)

            self.assertIn("stale file_analysis", "\n".join(result.messages))
            row = store.conn.execute("SELECT status FROM collector_runs WHERE collector='file_analysis'").fetchone()
            self.assertEqual(row["status"], "error")


if __name__ == "__main__":
    unittest.main()
