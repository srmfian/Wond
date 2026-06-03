import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from wond.dashboard_search import (
    cleanup_internal_search_embeddings,
    ensure_search_schema,
    search_documents,
    search_index_status,
    search_observations,
)
from wond.store import Observation, Store


def settings_for(root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        path=root / "config.json",
        db_path=root / "context.sqlite3",
        timezone="Asia/Tokyo",
        data_dir=root / "wond" / "data",
        report_dir=root / "wond" / "data" / "reports",
        summary_dir=root / "wond" / "data" / "summaries",
        log_dir=root / "wond" / "data" / "logs",
        recycle_bin_dir=root / "wond" / "data" / "recycle_bin",
        speaker_sample_dir=root / "wond" / "data" / "speaker_samples",
        local_ai={},
    )


class SearchFilterTests(unittest.TestCase):
    def test_keyword_search_hides_internal_filesystem_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = settings_for(root)
            store = Store(settings.db_path)
            self.addCleanup(store.close)
            internal_path = settings.data_dir / "mobile-export.json"
            store.upsert_observations(
                [
                    Observation(
                        source="filesystem",
                        kind="file_modified",
                        source_key=str(internal_path),
                        observed_at="2026-06-02T09:00:00+09:00",
                        title="needle internal Wond file",
                        metadata={"path": str(internal_path)},
                    ),
                    Observation(
                        source="mobile",
                        kind="audio_segment",
                        source_key="external",
                        observed_at="2026-06-02T08:00:00+09:00",
                        title="external note",
                        body="needle external memory",
                    ),
                ]
            )

            rows = search_observations(settings, store, "needle", limit=10)

            self.assertEqual([row["source"] for row in rows], ["mobile"])
            self.assertIn("needle external", rows[0]["body"])

    def test_search_documents_skip_internal_filesystem_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = settings_for(root)
            store = Store(settings.db_path)
            self.addCleanup(store.close)
            internal_path = settings.data_dir / "wond.sqlite3-wal"
            store.upsert_observations(
                [
                    Observation(
                        source="filesystem",
                        kind="file_modified",
                        source_key=str(internal_path),
                        observed_at="2026-06-02T09:00:00+09:00",
                        title="internal Wond db",
                        body="should not be indexed",
                        metadata={"path": str(internal_path)},
                    ),
                    Observation(
                        source="mobile",
                        kind="audio_segment",
                        source_key="external",
                        observed_at="2026-06-02T08:00:00+09:00",
                        title="external note",
                        body="should be indexed",
                    ),
                ]
            )

            docs = search_documents(settings, store, limit=10)

            self.assertEqual([doc.source for doc in docs], ["mobile"])
            self.assertIn("external note", docs[0].text)
            self.assertIn("should be indexed", docs[0].text)

    def test_cleanup_internal_search_embeddings_deletes_polluted_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = settings_for(root)
            store = Store(settings.db_path)
            self.addCleanup(store.close)
            ensure_search_schema(store)
            internal_text = f"Changed Wond cache at {settings.data_dir / 'mobile-export.json'}"
            external_text = "Changed user document at /Users/example/Downloads/deck.pdf"
            for key, text in (("internal", internal_text), ("external", external_text)):
                store.conn.execute(
                    """
                    INSERT INTO search_embeddings (
                        record_type, record_key, content_hash, model, vector, dimension,
                        title, text, observed_at, source, kind, path, metadata, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "observation",
                        key,
                        key,
                        "test",
                        json.dumps([1.0]),
                        1,
                        key,
                        text,
                        "2026-06-02T09:00:00+09:00",
                        "filesystem",
                        "file_modified",
                        "",
                        "{}",
                        "2026-06-02T09:00:00+09:00",
                    ),
                )
            store.conn.commit()

            deleted = cleanup_internal_search_embeddings(settings, store)
            remaining = store.conn.execute("SELECT record_key FROM search_embeddings").fetchall()

            self.assertEqual(deleted, 1)
            self.assertEqual([row["record_key"] for row in remaining], ["external"])

    def test_search_documents_prioritize_missing_embeddings_by_source_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = settings_for(root)
            store = Store(settings.db_path)
            self.addCleanup(store.close)
            ensure_search_schema(store)
            store.upsert_observations(
                [
                    Observation(
                        source="browser",
                        kind="web_visit",
                        source_key="browser-newer",
                        observed_at="2026-06-03T12:00:00+09:00",
                        title="Browser page",
                        body="newer lower value context",
                    ),
                    Observation(
                        source="mobile",
                        kind="audio_segment",
                        source_key="audio-indexed",
                        observed_at="2026-06-03T11:00:00+09:00",
                        title="Audio memory",
                        body="already indexed high value memory",
                    ),
                    Observation(
                        source="apple_mail",
                        kind="email",
                        source_key="mail-missing",
                        observed_at="2026-06-03T10:00:00+09:00",
                        title="Important mail",
                        body="missing high value context",
                    ),
                ]
            )
            audio = store.conn.execute("SELECT id FROM observations WHERE source='mobile'").fetchone()
            store.conn.execute(
                """
                INSERT INTO search_embeddings (
                    record_type, record_key, content_hash, model, vector, dimension,
                    title, text, observed_at, source, kind, path, metadata, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "observation",
                    str(audio["id"]),
                    "audio",
                    "test-model",
                    json.dumps([1.0]),
                    1,
                    "Audio memory",
                    "already indexed high value memory",
                    "2026-06-03T11:00:00+09:00",
                    "mobile",
                    "audio_segment",
                    None,
                    "{}",
                    "2026-06-03T11:00:00+09:00",
                ),
            )
            store.conn.commit()

            docs = search_documents(settings, store, limit=3, model="test-model")
            status = search_index_status(settings, store)
            mail_coverage = next(
                row for row in status["coverage"]["by_source"] if row["source"] == "apple_mail" and row["kind"] == "email"
            )

            self.assertEqual([doc.source for doc in docs], ["apple_mail", "browser", "mobile"])
            self.assertEqual(mail_coverage["indexed"], 0)
            self.assertEqual(mail_coverage["missing"], 1)
            self.assertEqual(status["coverage"]["indexed_observations"], 1)


if __name__ == "__main__":
    unittest.main()
