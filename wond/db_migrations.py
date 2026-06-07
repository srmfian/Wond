from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable

from .timeutil import utc_iso


LATEST_SCHEMA_VERSION = 4


BASE_SCHEMA_SQL = """
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY,
                source TEXT NOT NULL,
                kind TEXT NOT NULL,
                source_key TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                ended_at TEXT,
                title TEXT,
                subtitle TEXT,
                body TEXT,
                url TEXT,
                location TEXT,
                actor TEXT,
                app TEXT,
                metadata TEXT,
                captured_at TEXT NOT NULL,
                UNIQUE(source, kind, source_key)
            );
            CREATE INDEX IF NOT EXISTS idx_observations_time
                ON observations(observed_at);
            CREATE INDEX IF NOT EXISTS idx_observations_source
                ON observations(source, kind);

            CREATE TABLE IF NOT EXISTS activity_samples (
                id INTEGER PRIMARY KEY,
                sampled_at TEXT NOT NULL,
                app TEXT NOT NULL,
                window_title TEXT,
                bundle_id TEXT,
                metadata TEXT,
                captured_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_activity_samples_time
                ON activity_samples(sampled_at);

            CREATE TABLE IF NOT EXISTS collector_runs (
                id INTEGER PRIMARY KEY,
                collector TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                message TEXT
            );

            CREATE TABLE IF NOT EXISTS email_deliveries (
                id INTEGER PRIMARY KEY,
                delivery_key TEXT NOT NULL,
                period TEXT NOT NULL,
                target_key TEXT NOT NULL,
                scheduled_for TEXT NOT NULL,
                attempted_at TEXT NOT NULL,
                status TEXT NOT NULL,
                subject TEXT,
                message TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_email_deliveries_key
                ON email_deliveries(delivery_key, status);
            CREATE INDEX IF NOT EXISTS idx_email_deliveries_attempted
                ON email_deliveries(attempted_at);

            CREATE TABLE IF NOT EXISTS daily_feedback (
                id INTEGER PRIMARY KEY,
                feedback_date TEXT NOT NULL,
                category TEXT NOT NULL,
                note TEXT NOT NULL,
                source_ref TEXT,
                created_at TEXT NOT NULL,
                metadata TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_daily_feedback_date
                ON daily_feedback(feedback_date, created_at);
            CREATE INDEX IF NOT EXISTS idx_daily_feedback_category
                ON daily_feedback(category);

            CREATE TABLE IF NOT EXISTS speakers (
                id INTEGER PRIMARY KEY,
                display_name TEXT NOT NULL,
                identity_status TEXT NOT NULL DEFAULT 'provisional',
                confidence REAL,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT
            );

            CREATE TABLE IF NOT EXISTS speaker_aliases (
                id INTEGER PRIMARY KEY,
                speaker_id INTEGER NOT NULL,
                alias TEXT NOT NULL UNIQUE,
                label TEXT,
                created_at TEXT NOT NULL,
                metadata TEXT,
                FOREIGN KEY(speaker_id) REFERENCES speakers(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_speaker_aliases_speaker
                ON speaker_aliases(speaker_id);

            CREATE TABLE IF NOT EXISTS speaker_samples (
                id INTEGER PRIMARY KEY,
                speaker_id INTEGER NOT NULL,
                observation_id INTEGER,
                source_key TEXT NOT NULL UNIQUE,
                media_path TEXT,
                sample_path TEXT,
                start_seconds REAL,
                end_seconds REAL,
                transcript TEXT,
                created_at TEXT NOT NULL,
                metadata TEXT,
                FOREIGN KEY(speaker_id) REFERENCES speakers(id) ON DELETE CASCADE,
                FOREIGN KEY(observation_id) REFERENCES observations(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_speaker_samples_speaker
                ON speaker_samples(speaker_id);
            CREATE INDEX IF NOT EXISTS idx_speaker_samples_observation
                ON speaker_samples(observation_id);

            CREATE TABLE IF NOT EXISTS speaker_embeddings (
                id INTEGER PRIMARY KEY,
                speaker_id INTEGER NOT NULL,
                sample_id INTEGER,
                model TEXT NOT NULL,
                vector TEXT NOT NULL,
                dimension INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                metadata TEXT,
                UNIQUE(sample_id, model),
                FOREIGN KEY(speaker_id) REFERENCES speakers(id) ON DELETE CASCADE,
                FOREIGN KEY(sample_id) REFERENCES speaker_samples(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_speaker_embeddings_speaker
                ON speaker_embeddings(speaker_id);
            CREATE INDEX IF NOT EXISTS idx_speaker_embeddings_model
                ON speaker_embeddings(model);

            CREATE TABLE IF NOT EXISTS speaker_match_decisions (
                id INTEGER PRIMARY KEY,
                source_speaker_id INTEGER NOT NULL,
                target_speaker_id INTEGER,
                sample_id INTEGER,
                model TEXT NOT NULL,
                score REAL,
                threshold REAL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                metadata TEXT,
                FOREIGN KEY(target_speaker_id) REFERENCES speakers(id) ON DELETE SET NULL,
                FOREIGN KEY(sample_id) REFERENCES speaker_samples(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_speaker_match_decisions_source
                ON speaker_match_decisions(source_speaker_id);
            CREATE INDEX IF NOT EXISTS idx_speaker_match_decisions_target
                ON speaker_match_decisions(target_speaker_id);
            CREATE INDEX IF NOT EXISTS idx_speaker_match_decisions_status
                ON speaker_match_decisions(status);

            CREATE TABLE IF NOT EXISTS insight_states (
                item_id TEXT PRIMARY KEY,
                item_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                pinned INTEGER NOT NULL DEFAULT 0,
                note TEXT,
                updated_at TEXT NOT NULL,
                metadata TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_insight_states_type_status
                ON insight_states(item_type, status);

            CREATE TABLE IF NOT EXISTS project_memories (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                summary TEXT,
                keywords TEXT,
                people TEXT,
                next_actions TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_seen_at TEXT,
                evidence_count INTEGER NOT NULL DEFAULT 0,
                metadata TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_project_memories_status
                ON project_memories(status, updated_at);
            CREATE INDEX IF NOT EXISTS idx_project_memories_last_seen
                ON project_memories(last_seen_at);

            CREATE TABLE IF NOT EXISTS project_memory_events (
                id INTEGER PRIMARY KEY,
                project_id TEXT NOT NULL,
                event_date TEXT NOT NULL,
                source_ref TEXT NOT NULL,
                title TEXT,
                summary TEXT,
                observed_at TEXT,
                created_at TEXT NOT NULL,
                metadata TEXT,
                UNIQUE(project_id, source_ref),
                FOREIGN KEY(project_id) REFERENCES project_memories(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_project_memory_events_project
                ON project_memory_events(project_id, observed_at);

            CREATE TABLE IF NOT EXISTS meeting_sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                project_id TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                started_at TEXT NOT NULL,
                ended_at TEXT,
                participants TEXT,
                agenda TEXT,
                notes TEXT,
                summary TEXT,
                action_items TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT,
                FOREIGN KEY(project_id) REFERENCES project_memories(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_meeting_sessions_status
                ON meeting_sessions(status, started_at);
            CREATE INDEX IF NOT EXISTS idx_meeting_sessions_project
                ON meeting_sessions(project_id, started_at);
            
"""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]


def apply_base_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(BASE_SCHEMA_SQL)


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def ensure_column(conn: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
    if column_exists(conn, table, column):
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def apply_speaker_identity_columns(conn: sqlite3.Connection) -> None:
    ensure_column(conn, "speakers", "identity_status", "TEXT NOT NULL DEFAULT 'provisional'")
    ensure_column(conn, "speakers", "confidence", "REAL")


def apply_speaker_match_display_names(conn: sqlite3.Connection) -> None:
    ensure_column(conn, "speaker_match_decisions", "source_display_name", "TEXT")
    ensure_column(conn, "speaker_match_decisions", "target_display_name", "TEXT")


def apply_personal_memory_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS personal_profile_entries (
            id TEXT PRIMARY KEY,
            section TEXT NOT NULL,
            label TEXT NOT NULL,
            value TEXT,
            sensitivity TEXT NOT NULL DEFAULT 'normal',
            status TEXT NOT NULL DEFAULT 'active',
            source TEXT NOT NULL DEFAULT 'manual',
            confidence REAL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            reviewed_at TEXT,
            metadata TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_personal_profile_section
            ON personal_profile_entries(section, status, updated_at);

        CREATE TABLE IF NOT EXISTS personal_people (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            relationship TEXT,
            organization TEXT,
            notes TEXT,
            sensitivity TEXT NOT NULL DEFAULT 'normal',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_seen_at TEXT,
            metadata TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_personal_people_status
            ON personal_people(status, updated_at);
        CREATE INDEX IF NOT EXISTS idx_personal_people_last_seen
            ON personal_people(last_seen_at);

        CREATE TABLE IF NOT EXISTS personal_person_aliases (
            id INTEGER PRIMARY KEY,
            person_id TEXT NOT NULL,
            alias TEXT NOT NULL,
            label TEXT,
            source_ref TEXT,
            created_at TEXT NOT NULL,
            metadata TEXT,
            UNIQUE(person_id, alias),
            FOREIGN KEY(person_id) REFERENCES personal_people(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_personal_person_aliases_person
            ON personal_person_aliases(person_id);

        CREATE TABLE IF NOT EXISTS personal_person_speaker_links (
            id INTEGER PRIMARY KEY,
            person_id TEXT NOT NULL,
            speaker_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'candidate',
            confidence REAL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            metadata TEXT,
            UNIQUE(person_id, speaker_id),
            FOREIGN KEY(person_id) REFERENCES personal_people(id) ON DELETE CASCADE,
            FOREIGN KEY(speaker_id) REFERENCES speakers(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_personal_person_speaker_links_person
            ON personal_person_speaker_links(person_id);
        CREATE INDEX IF NOT EXISTS idx_personal_person_speaker_links_speaker
            ON personal_person_speaker_links(speaker_id);

        CREATE TABLE IF NOT EXISTS personal_memories (
            id TEXT PRIMARY KEY,
            memory_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'candidate',
            title TEXT NOT NULL,
            body TEXT,
            subject TEXT,
            person_id TEXT,
            sensitivity TEXT NOT NULL DEFAULT 'normal',
            confidence REAL,
            source TEXT NOT NULL DEFAULT 'manual',
            valid_from TEXT,
            valid_until TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_seen_at TEXT,
            reviewed_at TEXT,
            supersedes_id TEXT,
            metadata TEXT,
            FOREIGN KEY(person_id) REFERENCES personal_people(id) ON DELETE SET NULL,
            FOREIGN KEY(supersedes_id) REFERENCES personal_memories(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_personal_memories_type_status
            ON personal_memories(memory_type, status, updated_at);
        CREATE INDEX IF NOT EXISTS idx_personal_memories_subject
            ON personal_memories(subject, status);
        CREATE INDEX IF NOT EXISTS idx_personal_memories_person
            ON personal_memories(person_id, status);

        CREATE TABLE IF NOT EXISTS personal_memory_evidence (
            id INTEGER PRIMARY KEY,
            memory_id TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            source_type TEXT,
            title TEXT,
            snippet TEXT,
            observed_at TEXT,
            url TEXT,
            created_at TEXT NOT NULL,
            metadata TEXT,
            UNIQUE(memory_id, source_ref),
            FOREIGN KEY(memory_id) REFERENCES personal_memories(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_personal_memory_evidence_memory
            ON personal_memory_evidence(memory_id, observed_at);

        CREATE TABLE IF NOT EXISTS personal_memory_conflicts (
            id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            conflicting_memory_id TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            reason TEXT,
            created_at TEXT NOT NULL,
            resolved_at TEXT,
            metadata TEXT,
            FOREIGN KEY(memory_id) REFERENCES personal_memories(id) ON DELETE CASCADE,
            FOREIGN KEY(conflicting_memory_id) REFERENCES personal_memories(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_personal_memory_conflicts_status
            ON personal_memory_conflicts(status, created_at);
        """
    )


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "base_schema", apply_base_schema),
    Migration(2, "speaker_identity_columns", apply_speaker_identity_columns),
    Migration(3, "speaker_match_display_names", apply_speaker_match_display_names),
    Migration(4, "personal_memory_schema", apply_personal_memory_schema),
)


def run_migrations(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    applied = {int(row[0]) for row in conn.execute("SELECT version FROM schema_migrations")}
    for migration in MIGRATIONS:
        if migration.version in applied:
            continue
        migration.apply(conn)
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (migration.version, migration.name, utc_iso()),
        )
    conn.execute(f"PRAGMA user_version = {LATEST_SCHEMA_VERSION}")
    conn.commit()
