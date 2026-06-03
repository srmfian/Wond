from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .db_migrations import run_migrations
from .timeutil import utc_iso


AUTO_SPEAKER_NAME_SCHEME = "voice_id_v1"
AUTO_SPEAKER_NAME_PREFIX = "Voice"
AUTO_SPEAKER_NAME_RE = re.compile(
    r"(?i)^(?:speaker|spk|voice|person|unknown speaker)(?:[\s._:-]*(?:#?\d+|[a-z]))?$"
)


def canonical_speaker_display_name(speaker_id: int) -> str:
    return f"{AUTO_SPEAKER_NAME_PREFIX} {speaker_id:03d}"


def speaker_display_name_is_auto(value: str | None) -> bool:
    cleaned = " ".join(str(value or "").replace("_", " ").replace("-", " ").split())
    if not cleaned:
        return True
    if cleaned.isdigit():
        return True
    if len(cleaned) == 1 and cleaned.isalpha():
        return True
    return bool(AUTO_SPEAKER_NAME_RE.match(cleaned))


def json_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def auto_speaker_metadata(
    raw: Any,
    *,
    previous_name: str | None,
    local_label: str | None = None,
    named_at: str | None = None,
) -> dict[str, Any]:
    metadata = json_dict(raw)
    metadata["auto_generated_display_name"] = True
    metadata["auto_display_name_scheme"] = AUTO_SPEAKER_NAME_SCHEME
    if previous_name and previous_name != metadata.get("auto_display_name_previous"):
        metadata.setdefault("auto_display_name_previous", previous_name)
    if local_label:
        metadata.setdefault("initial_local_speaker_label", local_label)
    if named_at:
        metadata["auto_display_name_updated_at"] = named_at
    return metadata


@dataclass
class Observation:
    source: str
    kind: str
    source_key: str
    observed_at: str
    ended_at: str | None = None
    title: str | None = None
    subtitle: str | None = None
    body: str | None = None
    url: str | None = None
    location: str | None = None
    actor: str | None = None
    app: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class ActivitySample:
    sampled_at: str
    app: str
    window_title: str | None = None
    bundle_id: str | None = None
    metadata: dict[str, Any] | None = None


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.init()

    def close(self) -> None:
        self.conn.close()

    def init(self) -> None:
        run_migrations(self.conn)

    def upsert_observations(self, observations: Iterable[Observation]) -> int:
        rows = list(observations)
        if not rows:
            return 0
        captured_at = utc_iso()
        payload = []
        for obs in rows:
            data = asdict(obs)
            metadata = data.pop("metadata") or {}
            payload.append(
                (
                    data["source"],
                    data["kind"],
                    data["source_key"],
                    data["observed_at"],
                    data["ended_at"],
                    data["title"],
                    data["subtitle"],
                    data["body"],
                    data["url"],
                    data["location"],
                    data["actor"],
                    data["app"],
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    captured_at,
                )
            )
        self.conn.executemany(
            """
            INSERT INTO observations (
                source, kind, source_key, observed_at, ended_at, title,
                subtitle, body, url, location, actor, app, metadata, captured_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, kind, source_key) DO UPDATE SET
                observed_at=excluded.observed_at,
                ended_at=excluded.ended_at,
                title=excluded.title,
                subtitle=excluded.subtitle,
                body=excluded.body,
                url=excluded.url,
                location=excluded.location,
                actor=excluded.actor,
                app=excluded.app,
                metadata=excluded.metadata,
                captured_at=excluded.captured_at
            """,
            payload,
        )
        self.conn.commit()
        return len(rows)

    def observation_exists(self, source: str, kind: str, source_key: str) -> bool:
        cur = self.conn.execute(
            """
            SELECT 1
            FROM observations
            WHERE source = ?
              AND kind = ?
              AND source_key = ?
            LIMIT 1
            """,
            (source, kind, source_key),
        )
        return cur.fetchone() is not None

    def add_activity_sample(self, sample: ActivitySample) -> None:
        self.conn.execute(
            """
            INSERT INTO activity_samples (
                sampled_at, app, window_title, bundle_id, metadata, captured_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                sample.sampled_at,
                sample.app,
                sample.window_title,
                sample.bundle_id,
                json.dumps(sample.metadata or {}, ensure_ascii=False, sort_keys=True),
                utc_iso(),
            ),
        )
        self.conn.commit()

    def start_run(self, collector: str) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO collector_runs (collector, started_at, status)
            VALUES (?, ?, ?)
            """,
            (collector, utc_iso(), "running"),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, message: str = "") -> None:
        self.conn.execute(
            """
            UPDATE collector_runs
            SET finished_at = ?, status = ?, message = ?
            WHERE id = ?
            """,
            (utc_iso(), status, message, run_id),
        )
        self.conn.commit()

    def add_daily_feedback(
        self,
        *,
        feedback_date: str,
        category: str,
        note: str,
        source_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> sqlite3.Row:
        created_at = utc_iso()
        cur = self.conn.execute(
            """
            INSERT INTO daily_feedback (
                feedback_date, category, note, source_ref, created_at, metadata
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                feedback_date,
                category,
                note,
                source_ref,
                created_at,
                json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
            ),
        )
        self.conn.commit()
        row = self.conn.execute(
            """
            SELECT *
            FROM daily_feedback
            WHERE id = ?
            """,
            (int(cur.lastrowid),),
        ).fetchone()
        if row is None:
            raise RuntimeError("daily feedback row was not created")
        return row

    def daily_feedback_for_date(self, feedback_date: str) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            """
            SELECT *
            FROM daily_feedback
            WHERE feedback_date = ?
            ORDER BY created_at DESC, id DESC
            """,
            (feedback_date,),
        )
        return list(cur.fetchall())

    def insight_states_for_type(self, item_type: str) -> dict[str, sqlite3.Row]:
        cur = self.conn.execute(
            """
            SELECT *
            FROM insight_states
            WHERE item_type = ?
            """,
            (item_type,),
        )
        return {str(row["item_id"]): row for row in cur.fetchall()}

    def set_insight_state(
        self,
        *,
        item_id: str,
        item_type: str,
        status: str,
        pinned: bool | None = None,
        note: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> sqlite3.Row:
        updated_at = utc_iso()
        current = self.conn.execute(
            """
            SELECT *
            FROM insight_states
            WHERE item_id = ?
            """,
            (item_id,),
        ).fetchone()
        if current is None:
            pinned_value = 1 if pinned else 0
            merged_meta = metadata or {}
            self.conn.execute(
                """
                INSERT INTO insight_states (
                    item_id, item_type, status, pinned, note, updated_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    item_type,
                    status,
                    pinned_value,
                    note,
                    updated_at,
                    json.dumps(merged_meta, ensure_ascii=False, sort_keys=True),
                ),
            )
        else:
            pinned_value = int(current["pinned"]) if pinned is None else (1 if pinned else 0)
            note_value = current["note"] if note is None else note
            merged_meta = json_dict(current["metadata"])
            if metadata:
                merged_meta.update(metadata)
            self.conn.execute(
                """
                UPDATE insight_states
                SET item_type = ?, status = ?, pinned = ?, note = ?, updated_at = ?, metadata = ?
                WHERE item_id = ?
                """,
                (
                    item_type,
                    status,
                    pinned_value,
                    note_value,
                    updated_at,
                    json.dumps(merged_meta, ensure_ascii=False, sort_keys=True),
                    item_id,
                ),
            )
        self.conn.commit()
        row = self.conn.execute(
            """
            SELECT *
            FROM insight_states
            WHERE item_id = ?
            """,
            (item_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("insight state row was not created")
        return row

    def clear_collector_error(self, collector: str, day) -> None:
        self.conn.execute(
            """
            DELETE FROM observations
            WHERE source = 'system'
              AND kind = 'collector_error'
              AND source_key = ?
            """,
            (f"{collector}:{day}",),
        )
        self.conn.commit()

    def observations_between(self, start_iso: str, end_iso: str) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            """
            SELECT *
            FROM observations
            WHERE observed_at >= ? AND observed_at < ?
            ORDER BY observed_at ASC, source ASC
            """,
            (start_iso, end_iso),
        )
        return list(cur.fetchall())

    def mobile_audio_between(self, start_iso: str, end_iso: str) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            """
            SELECT *
            FROM observations
            WHERE source = 'mobile'
              AND kind = 'audio_segment'
              AND observed_at >= ?
              AND observed_at < ?
            ORDER BY observed_at ASC
            """,
            (start_iso, end_iso),
        )
        return list(cur.fetchall())

    def update_observation_analysis(
        self,
        observation_id: int,
        body: str | None,
        metadata: dict[str, Any],
    ) -> None:
        self.conn.execute(
            """
            UPDATE observations
            SET body = ?,
                metadata = ?,
                captured_at = ?
            WHERE id = ?
            """,
            (
                body,
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                utc_iso(),
                observation_id,
            ),
        )
        self.conn.commit()

    def get_speaker(self, speaker_id: int) -> sqlite3.Row | None:
        cur = self.conn.execute(
            """
            SELECT *
            FROM speakers
            WHERE id = ?
            """,
            (speaker_id,),
        )
        return cur.fetchone()

    def next_speaker_id(self) -> int:
        rows = self.conn.execute(
            """
            SELECT max(value) AS max_id
            FROM (
                SELECT max(id) AS value FROM speakers
                UNION ALL
                SELECT max(speaker_id) AS value FROM speaker_aliases
                UNION ALL
                SELECT max(speaker_id) AS value FROM speaker_samples
                UNION ALL
                SELECT max(speaker_id) AS value FROM speaker_embeddings
                UNION ALL
                SELECT max(source_speaker_id) AS value FROM speaker_match_decisions
                UNION ALL
                SELECT max(target_speaker_id) AS value FROM speaker_match_decisions
            )
            """
        ).fetchone()
        return int(rows["max_id"] or 0) + 1

    def ensure_speaker_for_alias(
        self,
        alias: str,
        *,
        default_name: str,
        label: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> sqlite3.Row:
        cur = self.conn.execute(
            """
            SELECT speakers.*
            FROM speaker_aliases
            JOIN speakers ON speakers.id = speaker_aliases.speaker_id
            WHERE speaker_aliases.alias = ?
            """,
            (alias,),
        )
        existing = cur.fetchone()
        if existing is not None:
            return existing

        now = utc_iso()
        for _attempt in range(3):
            speaker_id = self.next_speaker_id()
            try:
                self.conn.execute(
                    """
                    INSERT INTO speakers (id, display_name, created_at, updated_at, metadata)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        speaker_id,
                        default_name,
                        now,
                        now,
                        json.dumps({}, ensure_ascii=False, sort_keys=True),
                    ),
                )
                break
            except sqlite3.IntegrityError:
                speaker_id = 0
        if speaker_id <= 0:
            raise RuntimeError("could not allocate a new speaker id")
        if speaker_display_name_is_auto(default_name):
            display_name = canonical_speaker_display_name(speaker_id)
            self.conn.execute(
                """
                UPDATE speakers
                SET display_name = ?,
                    updated_at = ?,
                    metadata = ?
                WHERE id = ?
                """,
                (
                    display_name,
                    now,
                    json.dumps(
                        auto_speaker_metadata({}, previous_name=default_name, local_label=label, named_at=now),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    speaker_id,
                ),
            )
        self.conn.execute(
            """
            INSERT INTO speaker_aliases (speaker_id, alias, label, created_at, metadata)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                speaker_id,
                alias,
                label,
                now,
                json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
            ),
        )
        self.conn.commit()
        speaker = self.get_speaker(speaker_id)
        if speaker is None:
            raise RuntimeError(f"speaker {speaker_id} was not created")
        return speaker

    def relabel_auto_speaker_names(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, display_name, identity_status, metadata
            FROM speakers
            ORDER BY id ASC
            """
        ).fetchall()
        now = utc_iso()
        changed: list[dict[str, Any]] = []
        for row in rows:
            speaker_id = int(row["id"])
            old_name = str(row["display_name"] or "")
            if row["identity_status"] == "named" or not speaker_display_name_is_auto(old_name):
                continue
            new_name = canonical_speaker_display_name(speaker_id)
            if old_name == new_name:
                continue
            metadata = auto_speaker_metadata(
                row["metadata"],
                previous_name=old_name,
                named_at=now,
            )
            self.conn.execute(
                """
                UPDATE speakers
                SET display_name = ?,
                    updated_at = ?,
                    metadata = ?
                WHERE id = ?
                """,
                (
                    new_name,
                    now,
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    speaker_id,
                ),
            )
            changed.append(
                {
                    "speaker_id": speaker_id,
                    "old_display_name": old_name,
                    "new_display_name": new_name,
                    "identity_status": row["identity_status"],
                }
            )
        if changed:
            self.conn.commit()
        return changed

    def add_speaker_alias(
        self,
        speaker_id: int,
        alias: str,
        *,
        label: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO speaker_aliases (speaker_id, alias, label, created_at, metadata)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(alias) DO UPDATE SET
                speaker_id = excluded.speaker_id,
                label = excluded.label,
                metadata = excluded.metadata
            """,
            (
                speaker_id,
                alias,
                label,
                utc_iso(),
                json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
            ),
        )
        self.conn.commit()

    def add_speaker_sample(
        self,
        *,
        speaker_id: int,
        observation_id: int | None,
        source_key: str,
        media_path: str | None,
        sample_path: str | None,
        start_seconds: float | None,
        end_seconds: float | None,
        transcript: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> sqlite3.Row:
        now = utc_iso()
        self.conn.execute(
            """
            INSERT INTO speaker_samples (
                speaker_id, observation_id, source_key, media_path, sample_path,
                start_seconds, end_seconds, transcript, created_at, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_key) DO UPDATE SET
                speaker_id = excluded.speaker_id,
                observation_id = excluded.observation_id,
                media_path = excluded.media_path,
                sample_path = excluded.sample_path,
                start_seconds = excluded.start_seconds,
                end_seconds = excluded.end_seconds,
                transcript = excluded.transcript,
                metadata = excluded.metadata
            """,
            (
                speaker_id,
                observation_id,
                source_key,
                media_path,
                sample_path,
                start_seconds,
                end_seconds,
                transcript,
                now,
                json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
            ),
        )
        self.conn.commit()
        cur = self.conn.execute(
            """
            SELECT *
            FROM speaker_samples
            WHERE source_key = ?
            """,
            (source_key,),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(f"speaker sample {source_key} was not created")
        return row

    def list_speakers(self) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            """
            SELECT
                speakers.*,
                count(DISTINCT speaker_aliases.id) AS alias_count,
                count(DISTINCT speaker_samples.id) AS sample_count,
                max(speaker_samples.created_at) AS latest_sample_at
            FROM speakers
            LEFT JOIN speaker_aliases
                ON speaker_aliases.speaker_id = speakers.id
            LEFT JOIN speaker_samples
                ON speaker_samples.speaker_id = speakers.id
            GROUP BY speakers.id
            ORDER BY speakers.id ASC
            """
        )
        return list(cur.fetchall())

    def list_speakers_ready_for_review(self) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            """
            SELECT
                speakers.*,
                count(DISTINCT speaker_samples.id) AS sample_count,
                max(speaker_samples.created_at) AS latest_sample_at
            FROM speakers
            LEFT JOIN speaker_samples
                ON speaker_samples.speaker_id = speakers.id
            WHERE speakers.identity_status = 'ready_to_name'
            GROUP BY speakers.id
            ORDER BY speakers.confidence DESC, speakers.id ASC
            """
        )
        return list(cur.fetchall())

    def list_speaker_samples(self, speaker_id: int | None = None) -> list[sqlite3.Row]:
        if speaker_id is None:
            cur = self.conn.execute(
                """
                SELECT speaker_samples.*, speakers.display_name AS speaker_name
                FROM speaker_samples
                JOIN speakers ON speakers.id = speaker_samples.speaker_id
                ORDER BY speaker_samples.created_at DESC, speaker_samples.id DESC
                """
            )
        else:
            cur = self.conn.execute(
                """
                SELECT speaker_samples.*, speakers.display_name AS speaker_name
                FROM speaker_samples
                JOIN speakers ON speakers.id = speaker_samples.speaker_id
                WHERE speaker_samples.speaker_id = ?
                ORDER BY speaker_samples.created_at DESC, speaker_samples.id DESC
                """,
                (speaker_id,),
            )
        return list(cur.fetchall())

    def get_speaker_sample(self, sample_id: int) -> sqlite3.Row | None:
        cur = self.conn.execute(
            """
            SELECT speaker_samples.*, speakers.display_name AS speaker_name
            FROM speaker_samples
            JOIN speakers ON speakers.id = speaker_samples.speaker_id
            WHERE speaker_samples.id = ?
            """,
            (sample_id,),
        )
        return cur.fetchone()

    def delete_speaker_samples_for_observation(self, observation_id: int) -> int:
        rows = self.conn.execute(
            "SELECT id FROM speaker_samples WHERE observation_id = ?",
            (observation_id,),
        ).fetchall()
        ids = [int(row["id"]) for row in rows]
        if not ids:
            return 0
        self.conn.executemany(
            "DELETE FROM speaker_samples WHERE id = ?",
            [(sample_id,) for sample_id in ids],
        )
        self.conn.commit()
        return len(ids)

    def update_speaker_sample_path(self, sample_id: int, sample_path: str) -> None:
        self.conn.execute(
            """
            UPDATE speaker_samples
            SET sample_path = ?
            WHERE id = ?
            """,
            (sample_path, sample_id),
        )
        self.conn.commit()

    def speaker_sample_evidence_stats(self, speaker_id: int) -> sqlite3.Row:
        cur = self.conn.execute(
            """
            SELECT
                count(DISTINCT speaker_samples.id) AS sample_count,
                count(DISTINCT speaker_samples.observation_id) AS observation_count,
                count(DISTINCT substr(coalesce(observations.observed_at, speaker_samples.created_at), 1, 10)) AS day_count,
                min(coalesce(observations.observed_at, speaker_samples.created_at)) AS first_seen_at,
                max(coalesce(observations.observed_at, speaker_samples.created_at)) AS latest_seen_at
            FROM speaker_samples
            LEFT JOIN observations ON observations.id = speaker_samples.observation_id
            WHERE speaker_samples.speaker_id = ?
            """,
            (speaker_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(f"speaker {speaker_id} stats could not be loaded")
        return row

    def rename_speaker(self, speaker_id: int, display_name: str) -> bool:
        cur = self.conn.execute(
            """
            UPDATE speakers
            SET display_name = ?,
                identity_status = 'named',
                updated_at = ?
            WHERE id = ?
            """,
            (display_name, utc_iso(), speaker_id),
        )
        self.conn.commit()
        return bool(cur.rowcount)

    def merge_speakers(self, source_id: int, target_id: int) -> bool:
        if source_id == target_id:
            return False
        source = self.get_speaker(source_id)
        target = self.get_speaker(target_id)
        if source is None or target is None:
            return False
        now = utc_iso()
        preserve_source_name = source["identity_status"] == "named" and target["identity_status"] != "named"
        self.conn.execute(
            """
            UPDATE OR IGNORE speaker_aliases
            SET speaker_id = ?
            WHERE speaker_id = ?
            """,
            (target_id, source_id),
        )
        self.conn.execute(
            """
            UPDATE OR IGNORE speaker_samples
            SET speaker_id = ?
            WHERE speaker_id = ?
            """,
            (target_id, source_id),
        )
        self.conn.execute(
            """
            UPDATE OR IGNORE speaker_embeddings
            SET speaker_id = ?
            WHERE speaker_id = ?
            """,
            (target_id, source_id),
        )
        self.conn.execute(
            """
            UPDATE speakers
            SET display_name = CASE WHEN ? THEN ? ELSE display_name END,
                identity_status = CASE WHEN ? THEN 'named' ELSE identity_status END,
                updated_at = ?
            WHERE id = ?
            """,
            (
                1 if preserve_source_name else 0,
                source["display_name"],
                1 if preserve_source_name else 0,
                now,
                target_id,
            ),
        )
        self.conn.execute(
            """
            DELETE FROM speakers
            WHERE id = ?
            """,
            (source_id,),
        )
        self.conn.commit()
        return True

    def delete_speaker(self, speaker_id: int) -> bool:
        if self.get_speaker(speaker_id) is None:
            return False
        self.conn.execute(
            """
            DELETE FROM speaker_match_decisions
            WHERE source_speaker_id = ?
            """,
            (speaker_id,),
        )
        self.conn.execute(
            """
            UPDATE speaker_match_decisions
            SET target_speaker_id = NULL
            WHERE target_speaker_id = ?
            """,
            (speaker_id,),
        )
        cur = self.conn.execute(
            """
            DELETE FROM speakers
            WHERE id = ?
            """,
            (speaker_id,),
        )
        self.conn.commit()
        return bool(cur.rowcount)

    def speaker_names_for_observation(self, observation_id: int) -> dict[str, sqlite3.Row]:
        rows = self.conn.execute(
            """
            SELECT
                speaker_aliases.alias,
                speaker_aliases.label,
                speaker_aliases.metadata AS alias_metadata,
                speakers.id AS speaker_id,
                speakers.display_name AS display_name
            FROM speaker_aliases
            JOIN speakers ON speakers.id = speaker_aliases.speaker_id
            WHERE speaker_aliases.alias LIKE ?
            ORDER BY speakers.id ASC
            """,
            (f"observation:{observation_id}:%",),
        ).fetchall()
        label_counts: dict[str, int] = {}
        for row in rows:
            if row["label"] is None:
                continue
            label = str(row["label"])
            label_counts[label] = label_counts.get(label, 0) + 1

        names: dict[str, sqlite3.Row] = {}
        alias_prefix = f"observation:{observation_id}:"
        for row in rows:
            alias = str(row["alias"] or "")
            if alias.startswith(alias_prefix):
                names[alias[len(alias_prefix) :]] = row
            metadata = json_dict(row["alias_metadata"])
            label = str(row["label"]) if row["label"] is not None else ""
            scope = str(metadata.get("speaker_scope") or "").strip()
            if scope and label:
                names[f"{scope}:{label}"] = row
            if label and label_counts.get(label, 0) == 1:
                names[label] = row
        return names

    def add_speaker_embedding(
        self,
        *,
        speaker_id: int,
        sample_id: int | None,
        model: str,
        vector: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> sqlite3.Row:
        vector_json = json.dumps(vector, ensure_ascii=False)
        dimension = len(vector)
        now = utc_iso()
        self.conn.execute(
            """
            INSERT INTO speaker_embeddings (
                speaker_id, sample_id, model, vector, dimension, created_at, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sample_id, model) DO UPDATE SET
                speaker_id = excluded.speaker_id,
                vector = excluded.vector,
                dimension = excluded.dimension,
                metadata = excluded.metadata
            """,
            (
                speaker_id,
                sample_id,
                model,
                vector_json,
                dimension,
                now,
                json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
            ),
        )
        self.conn.commit()
        cur = self.conn.execute(
            """
            SELECT *
            FROM speaker_embeddings
            WHERE sample_id IS ?
              AND model = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (sample_id, model),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("speaker embedding was not created")
        return row

    def speaker_embedding_rows(
        self,
        *,
        model: str,
        exclude_speaker_id: int | None = None,
        speaker_id: int | None = None,
    ) -> list[sqlite3.Row]:
        clauses = ["speaker_embeddings.model = ?"]
        params: list[Any] = [model]
        if exclude_speaker_id is not None:
            clauses.append("speaker_embeddings.speaker_id != ?")
            params.append(exclude_speaker_id)
        if speaker_id is not None:
            clauses.append("speaker_embeddings.speaker_id = ?")
            params.append(speaker_id)
        where = " AND ".join(clauses)
        cur = self.conn.execute(
            f"""
            SELECT
                speaker_embeddings.*,
                speakers.display_name AS speaker_name,
                speakers.identity_status AS identity_status,
                speaker_samples.sample_path AS sample_path
            FROM speaker_embeddings
            JOIN speakers ON speakers.id = speaker_embeddings.speaker_id
            LEFT JOIN speaker_samples ON speaker_samples.id = speaker_embeddings.sample_id
            WHERE {where}
            ORDER BY speaker_embeddings.created_at ASC, speaker_embeddings.id ASC
            """,
            params,
        )
        return list(cur.fetchall())

    def record_speaker_match_decision(
        self,
        *,
        source_speaker_id: int,
        target_speaker_id: int | None,
        sample_id: int | None,
        model: str,
        score: float | None,
        threshold: float | None,
        status: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        source = self.get_speaker(source_speaker_id)
        target = self.get_speaker(target_speaker_id) if target_speaker_id is not None else None
        source_display_name = str(source["display_name"]) if source is not None else None
        target_display_name = str(target["display_name"]) if target is not None else None
        self.conn.execute(
            """
            INSERT INTO speaker_match_decisions (
                source_speaker_id, target_speaker_id, sample_id, model,
                score, threshold, status, created_at, metadata,
                source_display_name, target_display_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_speaker_id,
                target_speaker_id,
                sample_id,
                model,
                score,
                threshold,
                status,
                utc_iso(),
                json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                source_display_name,
                target_display_name,
            ),
        )
        self.conn.commit()

    def list_speaker_match_decisions(self, limit: int = 30) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            """
            SELECT
                speaker_match_decisions.*,
                CASE
                    WHEN source.id IS NOT NULL
                         AND source.created_at <= speaker_match_decisions.created_at
                    THEN source.display_name
                    WHEN speaker_match_decisions.source_display_name IS NOT NULL
                    THEN speaker_match_decisions.source_display_name
                    ELSE printf('Voice %03d (merged/deleted)', speaker_match_decisions.source_speaker_id)
                END AS source_name,
                CASE
                    WHEN speaker_match_decisions.target_speaker_id IS NULL
                    THEN NULL
                    WHEN target.id IS NOT NULL
                         AND target.created_at <= speaker_match_decisions.created_at
                    THEN target.display_name
                    WHEN speaker_match_decisions.target_display_name IS NOT NULL
                    THEN speaker_match_decisions.target_display_name
                    ELSE printf('Voice %03d (merged/deleted)', speaker_match_decisions.target_speaker_id)
                END AS target_name,
                CASE
                    WHEN source.id IS NOT NULL
                         AND source.created_at > speaker_match_decisions.created_at
                    THEN 1
                    ELSE 0
                END AS source_stale_reference,
                CASE
                    WHEN target.id IS NOT NULL
                         AND target.created_at > speaker_match_decisions.created_at
                    THEN 1
                    ELSE 0
                END AS target_stale_reference
            FROM speaker_match_decisions
            LEFT JOIN speakers AS source ON source.id = speaker_match_decisions.source_speaker_id
            LEFT JOIN speakers AS target ON target.id = speaker_match_decisions.target_speaker_id
            ORDER BY speaker_match_decisions.id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return list(cur.fetchall())

    def update_speaker_identity_status(
        self,
        speaker_id: int,
        *,
        status: str,
        confidence: float | None,
        touch_updated_at: bool = True,
    ) -> None:
        if touch_updated_at:
            self.conn.execute(
                """
                UPDATE speakers
                SET identity_status = CASE
                        WHEN identity_status = 'named' THEN identity_status
                        ELSE ?
                    END,
                    confidence = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (status, confidence, utc_iso(), speaker_id),
            )
        else:
            self.conn.execute(
                """
                UPDATE speakers
                SET identity_status = CASE
                        WHEN identity_status = 'named' THEN identity_status
                        ELSE ?
                    END,
                    confidence = ?
                WHERE id = ?
                """,
                (status, confidence, speaker_id),
            )
        self.conn.commit()

    def observations_exist(self, keys: Iterable[tuple[str, str, str]]) -> bool:
        rows = list(keys)
        if not rows:
            return False
        for source, kind, source_key in rows:
            cur = self.conn.execute(
                """
                SELECT 1
                FROM observations
                WHERE source = ?
                  AND kind = ?
                  AND source_key = ?
                LIMIT 1
                """,
                (source, kind, source_key),
            )
            if cur.fetchone() is None:
                return False
        return True

    def delete_observations(self, observation_ids: Iterable[int]) -> int:
        ids = [int(value) for value in observation_ids]
        if not ids:
            return 0
        self.conn.executemany(
            "DELETE FROM observations WHERE id = ?",
            [(value,) for value in ids],
        )
        self.conn.commit()
        return len(ids)

    def activity_between(self, start_iso: str, end_iso: str) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            """
            SELECT *
            FROM activity_samples
            WHERE sampled_at >= ? AND sampled_at < ?
            ORDER BY sampled_at ASC
            """,
            (start_iso, end_iso),
        )
        return list(cur.fetchall())

    def latest_runs(self, limit: int = 20) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            """
            SELECT *
            FROM collector_runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return list(cur.fetchall())

    def observation_dates_before(self, cutoff_day: str) -> list[str]:
        cur = self.conn.execute(
            """
            SELECT DISTINCT substr(observed_at, 1, 10) AS day
            FROM observations
            WHERE substr(observed_at, 1, 10) < ?
            ORDER BY day ASC
            """,
            (cutoff_day,),
        )
        return [row["day"] for row in cur.fetchall() if row["day"]]

    def activity_dates_before(self, cutoff_day: str) -> list[str]:
        cur = self.conn.execute(
            """
            SELECT DISTINCT substr(sampled_at, 1, 10) AS day
            FROM activity_samples
            WHERE substr(sampled_at, 1, 10) < ?
            ORDER BY day ASC
            """,
            (cutoff_day,),
        )
        return [row["day"] for row in cur.fetchall() if row["day"]]

    def count_observations_for_day(self, day: str) -> int:
        cur = self.conn.execute(
            "SELECT count(*) AS count FROM observations WHERE substr(observed_at, 1, 10) = ?",
            (day,),
        )
        return int(cur.fetchone()["count"])

    def count_activity_for_day(self, day: str) -> int:
        cur = self.conn.execute(
            "SELECT count(*) AS count FROM activity_samples WHERE substr(sampled_at, 1, 10) = ?",
            (day,),
        )
        return int(cur.fetchone()["count"])

    def delete_observations_for_day(self, day: str) -> int:
        cur = self.conn.execute(
            "DELETE FROM observations WHERE substr(observed_at, 1, 10) = ?",
            (day,),
        )
        self.conn.commit()
        return int(cur.rowcount if cur.rowcount is not None else 0)

    def delete_activity_for_day(self, day: str) -> int:
        cur = self.conn.execute(
            "DELETE FROM activity_samples WHERE substr(sampled_at, 1, 10) = ?",
            (day,),
        )
        self.conn.commit()
        return int(cur.rowcount if cur.rowcount is not None else 0)

    def count_collector_runs_before(self, cutoff_iso: str) -> int:
        cur = self.conn.execute(
            "SELECT count(*) AS count FROM collector_runs WHERE started_at < ?",
            (cutoff_iso,),
        )
        return int(cur.fetchone()["count"])

    def delete_collector_runs_before(self, cutoff_iso: str) -> int:
        cur = self.conn.execute(
            "DELETE FROM collector_runs WHERE started_at < ?",
            (cutoff_iso,),
        )
        self.conn.commit()
        return int(cur.rowcount if cur.rowcount is not None else 0)

    def checkpoint_and_vacuum(self) -> None:
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
        self.conn.commit()
        self.conn.execute("VACUUM")
        self.conn.commit()

    def email_delivery_success(self, delivery_key: str) -> bool:
        cur = self.conn.execute(
            """
            SELECT 1
            FROM email_deliveries
            WHERE delivery_key = ?
              AND status = 'sent'
            LIMIT 1
            """,
            (delivery_key,),
        )
        return cur.fetchone() is not None

    def latest_email_delivery_attempt(self, delivery_key: str) -> sqlite3.Row | None:
        cur = self.conn.execute(
            """
            SELECT *
            FROM email_deliveries
            WHERE delivery_key = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (delivery_key,),
        )
        return cur.fetchone()

    def record_email_delivery(
        self,
        delivery_key: str,
        period: str,
        target_key: str,
        scheduled_for: str,
        status: str,
        subject: str,
        message: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO email_deliveries (
                delivery_key, period, target_key, scheduled_for,
                attempted_at, status, subject, message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                delivery_key,
                period,
                target_key,
                scheduled_for,
                utc_iso(),
                status,
                subject,
                message,
            ),
        )
        self.conn.commit()
