import sqlite3
import tempfile
import unittest
from pathlib import Path

from wond.db_migrations import LATEST_SCHEMA_VERSION
from wond.store import Store


class StoreMigrationTests(unittest.TestCase):
    def test_store_records_schema_migrations_and_user_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "context.sqlite3")
            try:
                rows = store.conn.execute(
                    "SELECT version, name FROM schema_migrations ORDER BY version"
                ).fetchall()
                user_version = store.conn.execute("PRAGMA user_version").fetchone()[0]
            finally:
                store.close()

        self.assertEqual(user_version, LATEST_SCHEMA_VERSION)
        self.assertEqual([row["version"] for row in rows], [1, 2, 3, 4])
        self.assertEqual(rows[-1]["name"], "personal_memory_schema")

    def test_store_migrations_repair_legacy_speaker_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "legacy.sqlite3"
            conn = sqlite3.connect(db_path)
            try:
                conn.executescript(
                    """
                    CREATE TABLE speakers (
                        id INTEGER PRIMARY KEY,
                        display_name TEXT NOT NULL,
                        notes TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        metadata TEXT
                    );
                    CREATE TABLE speaker_match_decisions (
                        id INTEGER PRIMARY KEY,
                        source_speaker_id INTEGER NOT NULL,
                        target_speaker_id INTEGER,
                        sample_id INTEGER,
                        model TEXT NOT NULL,
                        score REAL,
                        threshold REAL,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        metadata TEXT
                    );
                    """
                )
                conn.commit()
            finally:
                conn.close()

            store = Store(db_path)
            try:
                speaker_columns = {row["name"] for row in store.conn.execute("PRAGMA table_info(speakers)")}
                match_columns = {
                    row["name"]
                    for row in store.conn.execute("PRAGMA table_info(speaker_match_decisions)")
                }
                memory_columns = {
                    row["name"]
                    for row in store.conn.execute("PRAGMA table_info(personal_memories)")
                }
                user_version = store.conn.execute("PRAGMA user_version").fetchone()[0]
            finally:
                store.close()

        self.assertEqual(user_version, LATEST_SCHEMA_VERSION)
        self.assertIn("identity_status", speaker_columns)
        self.assertIn("confidence", speaker_columns)
        self.assertIn("source_display_name", match_columns)
        self.assertIn("target_display_name", match_columns)
        self.assertIn("memory_type", memory_columns)
        self.assertIn("status", memory_columns)


if __name__ == "__main__":
    unittest.main()
