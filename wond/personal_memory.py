from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import date
from http import HTTPStatus
from typing import Any

from .dashboard_shared import compact, parse_int, row_payload, search_keywords
from .observation_filters import visible_observations
from .store import Store, json_dict
from .timeutil import day_bounds, local_iso, now, parse_day, utc_iso


PROFILE_SECTIONS = ("identity", "work", "preferences", "boundaries", "rhythm", "focus")
MEMORY_TYPES = ("fact", "preference", "decision", "commitment", "relationship", "rhythm", "boundary", "project", "note")
MEMORY_STATUSES = ("candidate", "confirmed", "ignored", "archived")
PERSON_STATUSES = ("active", "hidden", "archived")
SENSITIVITY_LEVELS = ("normal", "private", "high")
CONFLICT_TYPES = {"fact", "preference", "boundary", "relationship", "project"}

FOLLOW_UP_TERMS = (
    "follow up",
    "todo",
    "need to",
    "needs to",
    "should",
    "reply",
    "respond",
    "send",
    "confirm",
    "deadline",
    "due",
    "tomorrow",
    "next week",
    "待办",
    "需要",
    "应该",
    "回复",
    "跟进",
    "确认",
    "发送",
    "明天",
    "下周",
    "截止",
)
PREFERENCE_TERMS = (
    "prefer",
    "preference",
    "like to",
    "don't like",
    "do not like",
    "always use",
    "never use",
    "喜欢",
    "偏好",
    "习惯",
    "不要",
    "不喜欢",
    "希望",
)
BOUNDARY_TERMS = (
    "do not",
    "don't",
    "never",
    "private",
    "sensitive",
    "不要",
    "别",
    "隐私",
    "敏感",
    "边界",
)
DECISION_TERMS = (
    "decided",
    "decision",
    "agreed",
    "confirmed",
    "选择",
    "决定",
    "确认",
    "同意",
)
RHYTHM_TERMS = (
    "sleep",
    "tired",
    "fatigue",
    "stress",
    "exercise",
    "meal",
    "熬夜",
    "睡",
    "累",
    "疲",
    "压力",
    "运动",
    "吃饭",
)


def personal_memory_payload(settings: Any, params: dict[str, str]) -> dict[str, Any]:
    target = parse_day(params.get("date") or "today", settings.timezone)
    store = Store(settings.db_path)
    try:
        profile = profile_payload(store, params)
        people = people_payload(store, params)
        memories = memory_rows_payload(store, params)
        suggested = suggested_memory_candidates(settings, store, target, limit=personal_memory_limit(settings))
        conflicts = conflict_rows_payload(store, params)
        return {
            "ok": True,
            "date": target.isoformat(),
            "generated_at": now(settings.timezone).isoformat(timespec="seconds"),
            "summary": personal_memory_summary(store, memories, suggested, conflicts),
            "profile": profile,
            "people": people,
            "memories": memories,
            "suggested_candidates": suggested,
            "conflicts": conflicts,
            "privacy": personal_memory_privacy_summary(store),
        }
    finally:
        store.close()


def personal_memory_post(settings: Any, payload: dict[str, Any]) -> tuple[dict[str, Any], HTTPStatus]:
    action = str(payload.get("action") or "").strip() or "create_memory"
    store = Store(settings.db_path)
    try:
        if action == "upsert_profile":
            entry = upsert_profile_entry(store, payload)
            return {"ok": True, "entry": profile_entry_payload(entry)}, HTTPStatus.OK
        if action == "delete_profile":
            entry_id = require_text(payload, "id")
            store.conn.execute("DELETE FROM personal_profile_entries WHERE id = ?", (entry_id,))
            store.conn.commit()
            return {"ok": True, "deleted": entry_id}, HTTPStatus.OK
        if action == "create_person":
            person = upsert_person(store, payload)
            return {"ok": True, "person": person_payload(store, person)}, HTTPStatus.CREATED
        if action == "update_person":
            person_id = require_text(payload, "person_id", "id")
            person = upsert_person(store, payload, person_id=person_id)
            return {"ok": True, "person": person_payload(store, person)}, HTTPStatus.OK
        if action == "add_alias":
            person_id = require_text(payload, "person_id")
            alias = require_text(payload, "alias")
            add_person_alias(store, person_id, alias, label=str(payload.get("label") or "").strip())
            person = fetch_person(store, person_id)
            return {"ok": True, "person": person_payload(store, person)}, HTTPStatus.OK
        if action == "link_speaker":
            person_id = require_text(payload, "person_id")
            speaker_id = parse_int(payload.get("speaker_id"))
            if speaker_id is None or speaker_id <= 0:
                return {"ok": False, "error": "invalid_speaker_id"}, HTTPStatus.BAD_REQUEST
            link_person_speaker(store, person_id, speaker_id, payload)
            person = fetch_person(store, person_id)
            return {"ok": True, "person": person_payload(store, person)}, HTTPStatus.OK
        if action == "create_memory":
            memory = upsert_memory_from_payload(store, payload, default_status=str(payload.get("status") or "confirmed"))
            return {"ok": True, "memory": memory_payload(store, memory)}, HTTPStatus.CREATED
        if action == "generate_candidates":
            target = parse_day(payload.get("date") or "today", settings.timezone)
            created = materialize_memory_candidates(settings, store, target, limit=personal_memory_limit(settings))
            return {"ok": True, "created": len(created), "memories": [memory_payload(store, row) for row in created]}, HTTPStatus.OK
        if action in {"confirm_memory", "ignore_memory", "archive_memory"}:
            memory_id = require_text(payload, "memory_id", "id")
            status = {"confirm_memory": "confirmed", "ignore_memory": "ignored", "archive_memory": "archived"}[action]
            memory = update_memory_status(store, memory_id, status)
            return {"ok": True, "memory": memory_payload(store, memory)}, HTTPStatus.OK
        if action == "update_memory":
            memory_id = require_text(payload, "memory_id", "id")
            memory = upsert_memory_from_payload(store, payload, memory_id=memory_id, default_status="")
            return {"ok": True, "memory": memory_payload(store, memory)}, HTTPStatus.OK
        if action == "delete_memory":
            memory_id = require_text(payload, "memory_id", "id")
            hard_delete_memory(store, memory_id)
            return {"ok": True, "deleted": memory_id}, HTTPStatus.OK
        if action == "resolve_conflict":
            conflict_id = require_text(payload, "conflict_id", "id")
            resolved = resolve_conflict(store, conflict_id, str(payload.get("resolution") or "resolved"))
            return {"ok": True, "conflict": conflict_payload(store, resolved)}, HTTPStatus.OK
        return {"ok": False, "error": "invalid_action"}, HTTPStatus.BAD_REQUEST
    except KeyError as exc:
        return {"ok": False, "error": str(exc).strip("'")}, HTTPStatus.BAD_REQUEST
    finally:
        store.close()


def profile_payload(store: Store, params: dict[str, str]) -> dict[str, Any]:
    rows = store.conn.execute(
        """
        SELECT *
        FROM personal_profile_entries
        WHERE status = 'active'
        ORDER BY section ASC, updated_at DESC, label ASC
        """
    ).fetchall()
    sections: dict[str, list[dict[str, Any]]] = {section: [] for section in PROFILE_SECTIONS}
    for row in rows:
        section = str(row["section"] or "identity")
        sections.setdefault(section, []).append(profile_entry_payload(row))
    return {
        "sections": [{"id": key, "label": profile_section_label(key), "entries": value} for key, value in sections.items()],
        "entry_count": len(rows),
    }


def profile_entry_payload(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "section": row["section"],
        "label": row["label"],
        "value": row["value"] or "",
        "sensitivity": row["sensitivity"] or "normal",
        "status": row["status"] or "active",
        "source": row["source"] or "manual",
        "confidence": row["confidence"],
        "updated_at": row["updated_at"],
        "reviewed_at": row["reviewed_at"],
        "metadata": json_dict(row["metadata"]),
    }


def upsert_profile_entry(store: Store, payload: dict[str, Any]) -> Any:
    section = clean_choice(payload.get("section"), PROFILE_SECTIONS, "identity")
    label = require_text(payload, "label")
    value = str(payload.get("value") or "").strip()
    if not value:
        raise KeyError("value_required")
    entry_id = str(payload.get("id") or stable_id("profile", section, label))
    now_iso = utc_iso()
    store.conn.execute(
        """
        INSERT INTO personal_profile_entries (
            id, section, label, value, sensitivity, status, source, confidence,
            created_at, updated_at, reviewed_at, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            section = excluded.section,
            label = excluded.label,
            value = excluded.value,
            sensitivity = excluded.sensitivity,
            status = excluded.status,
            source = excluded.source,
            confidence = excluded.confidence,
            updated_at = excluded.updated_at,
            reviewed_at = excluded.reviewed_at,
            metadata = excluded.metadata
        """,
        (
            entry_id,
            section,
            label,
            value,
            clean_choice(payload.get("sensitivity"), SENSITIVITY_LEVELS, "normal"),
            str(payload.get("status") or "active"),
            str(payload.get("source") or "manual"),
            parse_float(payload.get("confidence"), default=1.0),
            now_iso,
            now_iso,
            now_iso,
            json_dumps(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}),
        ),
    )
    store.conn.commit()
    return store.conn.execute("SELECT * FROM personal_profile_entries WHERE id = ?", (entry_id,)).fetchone()


def people_payload(store: Store, params: dict[str, str]) -> list[dict[str, Any]]:
    status = str(params.get("person_status") or "active")
    q = str(params.get("q") or "").strip()
    where = "1=1"
    values: list[Any] = []
    if status != "all":
        where += " AND status = ?"
        values.append(clean_choice(status, PERSON_STATUSES, "active"))
    rows = store.conn.execute(
        f"""
        SELECT *
        FROM personal_people
        WHERE {where}
        ORDER BY coalesce(last_seen_at, updated_at) DESC, display_name ASC
        LIMIT 200
        """,
        values,
    ).fetchall()
    payloads = [person_payload(store, row) for row in rows]
    if q:
        lowered = q.casefold()
        payloads = [row for row in payloads if lowered in person_search_text(row).casefold()]
    return payloads


def upsert_person(store: Store, payload: dict[str, Any], *, person_id: str | None = None) -> Any:
    display_name = require_text(payload, "display_name", "name")
    person_id = person_id or str(payload.get("id") or stable_id("person", display_name))
    existing = fetch_person(store, person_id, required=False)
    now_iso = utc_iso()
    store.conn.execute(
        """
        INSERT INTO personal_people (
            id, display_name, status, relationship, organization, notes, sensitivity,
            created_at, updated_at, last_seen_at, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            display_name = excluded.display_name,
            status = excluded.status,
            relationship = excluded.relationship,
            organization = excluded.organization,
            notes = excluded.notes,
            sensitivity = excluded.sensitivity,
            updated_at = excluded.updated_at,
            last_seen_at = coalesce(excluded.last_seen_at, personal_people.last_seen_at),
            metadata = excluded.metadata
        """,
        (
            person_id,
            display_name,
            clean_choice(payload.get("status"), PERSON_STATUSES, existing["status"] if existing else "active"),
            str(payload.get("relationship") or (existing["relationship"] if existing else "") or "").strip(),
            str(payload.get("organization") or (existing["organization"] if existing else "") or "").strip(),
            str(payload.get("notes") or (existing["notes"] if existing else "") or "").strip(),
            clean_choice(payload.get("sensitivity"), SENSITIVITY_LEVELS, existing["sensitivity"] if existing else "normal"),
            now_iso if existing is None else existing["created_at"],
            now_iso,
            payload.get("last_seen_at") or (existing["last_seen_at"] if existing else None),
            json_dumps(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else json_dict(existing["metadata"]) if existing else {}),
        ),
    )
    aliases = split_values(payload.get("aliases"))
    for alias in aliases:
        add_person_alias(store, person_id, alias)
    store.conn.commit()
    return fetch_person(store, person_id)


def fetch_person(store: Store, person_id: str, *, required: bool = True) -> Any:
    row = store.conn.execute("SELECT * FROM personal_people WHERE id = ?", (person_id,)).fetchone()
    if row is None and required:
        raise KeyError("person_not_found")
    return row


def add_person_alias(store: Store, person_id: str, alias: str, *, label: str = "") -> None:
    if fetch_person(store, person_id, required=False) is None:
        raise KeyError("person_not_found")
    alias = alias.strip()
    if not alias:
        raise KeyError("alias_required")
    store.conn.execute(
        """
        INSERT OR IGNORE INTO personal_person_aliases (
            person_id, alias, label, source_ref, created_at, metadata
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (person_id, alias, label, "", utc_iso(), "{}"),
    )
    store.conn.commit()


def link_person_speaker(store: Store, person_id: str, speaker_id: int, payload: dict[str, Any]) -> None:
    if fetch_person(store, person_id, required=False) is None:
        raise KeyError("person_not_found")
    speaker = store.conn.execute("SELECT id FROM speakers WHERE id = ?", (speaker_id,)).fetchone()
    if speaker is None:
        raise KeyError("speaker_not_found")
    now_iso = utc_iso()
    store.conn.execute(
        """
        INSERT INTO personal_person_speaker_links (
            person_id, speaker_id, status, confidence, created_at, updated_at, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(person_id, speaker_id) DO UPDATE SET
            status = excluded.status,
            confidence = excluded.confidence,
            updated_at = excluded.updated_at,
            metadata = excluded.metadata
        """,
        (
            person_id,
            speaker_id,
            str(payload.get("status") or "confirmed"),
            parse_float(payload.get("confidence"), default=1.0),
            now_iso,
            now_iso,
            json_dumps(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}),
        ),
    )
    store.conn.commit()


def person_payload(store: Store, row: Any) -> dict[str, Any]:
    aliases = [
        {"id": alias["id"], "alias": alias["alias"], "label": alias["label"] or "", "source_ref": alias["source_ref"] or ""}
        for alias in store.conn.execute(
            "SELECT * FROM personal_person_aliases WHERE person_id = ? ORDER BY alias ASC",
            (row["id"],),
        ).fetchall()
    ]
    speaker_links = [
        {
            "id": link["id"],
            "speaker_id": link["speaker_id"],
            "speaker_name": link["speaker_name"] or f"Speaker {link['speaker_id']}",
            "status": link["status"],
            "confidence": link["confidence"],
            "updated_at": link["updated_at"],
        }
        for link in store.conn.execute(
            """
            SELECT l.*, s.display_name AS speaker_name
            FROM personal_person_speaker_links l
            LEFT JOIN speakers s ON s.id = l.speaker_id
            WHERE l.person_id = ?
            ORDER BY l.status = 'confirmed' DESC, l.updated_at DESC
            """,
            (row["id"],),
        ).fetchall()
    ]
    memories = store.conn.execute(
        """
        SELECT count(*) AS total,
               sum(CASE WHEN status = 'confirmed' THEN 1 ELSE 0 END) AS confirmed
        FROM personal_memories
        WHERE person_id = ?
          AND status != 'ignored'
        """,
        (row["id"],),
    ).fetchone()
    return {
        "id": row["id"],
        "display_name": row["display_name"],
        "status": row["status"],
        "relationship": row["relationship"] or "",
        "organization": row["organization"] or "",
        "notes": row["notes"] or "",
        "sensitivity": row["sensitivity"] or "normal",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_seen_at": row["last_seen_at"],
        "aliases": aliases,
        "speaker_links": speaker_links,
        "memory_count": int(memories["total"] or 0),
        "confirmed_memory_count": int(memories["confirmed"] or 0),
        "metadata": json_dict(row["metadata"]),
    }


def memory_rows_payload(store: Store, params: dict[str, str]) -> list[dict[str, Any]]:
    status = str(params.get("status") or "confirmed")
    memory_type = str(params.get("type") or "all")
    q = str(params.get("q") or "").strip()
    where = "1=1"
    values: list[Any] = []
    if status != "all":
        where += " AND status = ?"
        values.append(clean_choice(status, MEMORY_STATUSES, "confirmed"))
    if memory_type != "all":
        where += " AND memory_type = ?"
        values.append(clean_choice(memory_type, MEMORY_TYPES, "note"))
    if q:
        keywords = search_keywords(q)
        clauses = []
        for keyword in keywords:
            like = f"%{keyword}%"
            clauses.append("(coalesce(title,'') LIKE ? OR coalesce(body,'') LIKE ? OR coalesce(subject,'') LIKE ?)")
            values.extend([like, like, like])
        if clauses:
            where += " AND " + " AND ".join(clauses)
    rows = store.conn.execute(
        f"""
        SELECT *
        FROM personal_memories
        WHERE {where}
        ORDER BY
          CASE status WHEN 'candidate' THEN 0 WHEN 'confirmed' THEN 1 WHEN 'archived' THEN 2 ELSE 3 END,
          updated_at DESC
        LIMIT 300
        """,
        values,
    ).fetchall()
    return [memory_payload(store, row) for row in rows]


def memory_payload(store: Store, row: Any) -> dict[str, Any]:
    person = fetch_person(store, row["person_id"], required=False) if row["person_id"] else None
    evidence = evidence_payload(store, row["id"])
    conflicts = store.conn.execute(
        """
        SELECT count(*) AS n
        FROM personal_memory_conflicts
        WHERE status = 'open'
          AND (memory_id = ? OR conflicting_memory_id = ?)
        """,
        (row["id"], row["id"]),
    ).fetchone()
    return {
        "id": row["id"],
        "memory_type": row["memory_type"],
        "status": row["status"],
        "title": row["title"],
        "body": row["body"] or "",
        "subject": row["subject"] or "",
        "person_id": row["person_id"],
        "person_name": person["display_name"] if person is not None else "",
        "sensitivity": row["sensitivity"] or "normal",
        "confidence": row["confidence"],
        "source": row["source"] or "manual",
        "valid_from": row["valid_from"],
        "valid_until": row["valid_until"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_seen_at": row["last_seen_at"],
        "reviewed_at": row["reviewed_at"],
        "evidence_count": len(evidence),
        "evidence": evidence,
        "open_conflicts": int(conflicts["n"] or 0),
        "metadata": json_dict(row["metadata"]),
    }


def upsert_memory_from_payload(
    store: Store,
    payload: dict[str, Any],
    *,
    memory_id: str | None = None,
    default_status: str = "candidate",
    replace_existing: bool = True,
) -> Any:
    memory_type = clean_choice(payload.get("memory_type") or payload.get("type"), MEMORY_TYPES, "note")
    title = require_text(payload, "title")
    body = str(payload.get("body") or payload.get("summary") or "").strip()
    subject = str(payload.get("subject") or "").strip()
    person_id = str(payload.get("person_id") or "").strip() or None
    if person_id and fetch_person(store, person_id, required=False) is None:
        person_id = None
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), list) else []
    first_evidence = evidence[0] if evidence else {}
    evidence_key = str((first_evidence or {}).get("source_ref") or payload.get("source_ref") or "")
    memory_id = memory_id or str(payload.get("id") or stable_id("pmem", memory_type, subject, title, body, evidence_key))
    status = str(payload.get("status") or default_status or "").strip()
    existing = fetch_memory(store, memory_id, required=False)
    if existing is not None and not replace_existing:
        return existing
    if not status:
        status = existing["status"] if existing is not None else "candidate"
    now_iso = utc_iso()
    reviewed_at = now_iso if status == "confirmed" else (existing["reviewed_at"] if existing is not None else None)
    store.conn.execute(
        """
        INSERT INTO personal_memories (
            id, memory_type, status, title, body, subject, person_id, sensitivity,
            confidence, source, valid_from, valid_until, created_at, updated_at,
            last_seen_at, reviewed_at, supersedes_id, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            memory_type = excluded.memory_type,
            status = excluded.status,
            title = excluded.title,
            body = excluded.body,
            subject = excluded.subject,
            person_id = excluded.person_id,
            sensitivity = excluded.sensitivity,
            confidence = excluded.confidence,
            source = excluded.source,
            valid_from = excluded.valid_from,
            valid_until = excluded.valid_until,
            updated_at = excluded.updated_at,
            last_seen_at = excluded.last_seen_at,
            reviewed_at = excluded.reviewed_at,
            supersedes_id = excluded.supersedes_id,
            metadata = excluded.metadata
        """,
        (
            memory_id,
            memory_type,
            clean_choice(status, MEMORY_STATUSES, "candidate"),
            title,
            body,
            subject,
            person_id,
            clean_choice(payload.get("sensitivity"), SENSITIVITY_LEVELS, sensitivity_for_text(memory_type, title + " " + body)),
            parse_float(payload.get("confidence"), default=0.65 if status == "candidate" else 1.0),
            str(payload.get("source") or "manual"),
            payload.get("valid_from") or None,
            payload.get("valid_until") or None,
            existing["created_at"] if existing is not None else now_iso,
            now_iso,
            payload.get("last_seen_at") or evidence_observed_at(evidence) or (existing["last_seen_at"] if existing is not None else None),
            reviewed_at,
            payload.get("supersedes_id") or None,
            json_dumps(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}),
        ),
    )
    for item in evidence:
        add_memory_evidence(store, memory_id, item)
    row = fetch_memory(store, memory_id)
    detect_memory_conflicts(store, row)
    store.conn.commit()
    return row


def fetch_memory(store: Store, memory_id: str, *, required: bool = True) -> Any:
    row = store.conn.execute("SELECT * FROM personal_memories WHERE id = ?", (memory_id,)).fetchone()
    if row is None and required:
        raise KeyError("memory_not_found")
    return row


def add_memory_evidence(store: Store, memory_id: str, item: dict[str, Any]) -> None:
    source_ref = str(item.get("source_ref") or item.get("id") or "").strip()
    if not source_ref:
        return
    store.conn.execute(
        """
        INSERT OR IGNORE INTO personal_memory_evidence (
            memory_id, source_ref, source_type, title, snippet, observed_at, url, created_at, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            memory_id,
            source_ref,
            str(item.get("source_type") or item.get("source") or ""),
            str(item.get("title") or "")[:240],
            compact(item.get("snippet") or item.get("body") or "", 1000),
            item.get("observed_at") or item.get("time"),
            item.get("url"),
            utc_iso(),
            json_dumps(item.get("metadata") if isinstance(item.get("metadata"), dict) else {}),
        ),
    )


def evidence_payload(store: Store, memory_id: str) -> list[dict[str, Any]]:
    rows = store.conn.execute(
        """
        SELECT *
        FROM personal_memory_evidence
        WHERE memory_id = ?
        ORDER BY observed_at DESC, id DESC
        LIMIT 20
        """,
        (memory_id,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "source_ref": row["source_ref"],
            "source_type": row["source_type"] or "",
            "title": row["title"] or "",
            "snippet": row["snippet"] or "",
            "observed_at": row["observed_at"],
            "url": row["url"],
            "metadata": json_dict(row["metadata"]),
        }
        for row in rows
    ]


def update_memory_status(store: Store, memory_id: str, status: str) -> Any:
    if fetch_memory(store, memory_id, required=False) is None:
        raise KeyError("memory_not_found")
    now_iso = utc_iso()
    reviewed_at = now_iso if status == "confirmed" else None
    store.conn.execute(
        """
        UPDATE personal_memories
        SET status = ?,
            updated_at = ?,
            reviewed_at = coalesce(?, reviewed_at)
        WHERE id = ?
        """,
        (clean_choice(status, MEMORY_STATUSES, "candidate"), now_iso, reviewed_at, memory_id),
    )
    row = fetch_memory(store, memory_id)
    if status == "confirmed":
        detect_memory_conflicts(store, row)
    store.conn.commit()
    return row


def hard_delete_memory(store: Store, memory_id: str) -> None:
    if table_exists(store, "search_embeddings"):
        store.conn.execute(
            "DELETE FROM search_embeddings WHERE record_type = 'personal_memory' AND record_key = ?",
            (memory_id,),
        )
    store.conn.execute("DELETE FROM personal_memory_conflicts WHERE memory_id = ? OR conflicting_memory_id = ?", (memory_id, memory_id))
    store.conn.execute("DELETE FROM personal_memories WHERE id = ?", (memory_id,))
    store.conn.commit()


def table_exists(store: Store, name: str) -> bool:
    row = store.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def detect_memory_conflicts(store: Store, row: Any) -> None:
    if row["memory_type"] not in CONFLICT_TYPES or row["status"] not in {"candidate", "confirmed"}:
        return
    subject = normalized_subject(row)
    if not subject:
        return
    candidates = store.conn.execute(
        """
        SELECT *
        FROM personal_memories
        WHERE id != ?
          AND memory_type = ?
          AND status IN ('candidate', 'confirmed')
        ORDER BY updated_at DESC
        LIMIT 100
        """,
        (row["id"], row["memory_type"]),
    ).fetchall()
    left_text = normalized_memory_text(row)
    for other in candidates:
        if normalized_subject(other) != subject:
            continue
        right_text = normalized_memory_text(other)
        if not left_text or not right_text or left_text == right_text:
            continue
        conflict_id = stable_id("pconflict", *sorted([row["id"], other["id"]]))
        store.conn.execute(
            """
            INSERT OR IGNORE INTO personal_memory_conflicts (
                id, memory_id, conflicting_memory_id, status, reason, created_at, metadata
            ) VALUES (?, ?, ?, 'open', ?, ?, ?)
            """,
            (
                conflict_id,
                row["id"],
                other["id"],
                "same subject has different remembered details",
                utc_iso(),
                json_dumps({"subject": subject, "memory_type": row["memory_type"]}),
            ),
        )


def conflict_rows_payload(store: Store, params: dict[str, str]) -> list[dict[str, Any]]:
    status = str(params.get("conflict_status") or "open")
    rows = store.conn.execute(
        """
        SELECT *
        FROM personal_memory_conflicts
        WHERE (? = 'all' OR status = ?)
        ORDER BY created_at DESC
        LIMIT 100
        """,
        (status, status),
    ).fetchall()
    return [conflict_payload(store, row) for row in rows]


def conflict_payload(store: Store, row: Any) -> dict[str, Any]:
    memory = fetch_memory(store, row["memory_id"], required=False)
    other = fetch_memory(store, row["conflicting_memory_id"], required=False) if row["conflicting_memory_id"] else None
    return {
        "id": row["id"],
        "status": row["status"],
        "reason": row["reason"] or "",
        "created_at": row["created_at"],
        "resolved_at": row["resolved_at"],
        "memory": memory_payload(store, memory) if memory is not None else None,
        "conflicting_memory": memory_payload(store, other) if other is not None else None,
        "metadata": json_dict(row["metadata"]),
    }


def resolve_conflict(store: Store, conflict_id: str, resolution: str) -> Any:
    row = store.conn.execute("SELECT * FROM personal_memory_conflicts WHERE id = ?", (conflict_id,)).fetchone()
    if row is None:
        raise KeyError("conflict_not_found")
    metadata = json_dict(row["metadata"])
    metadata["resolution"] = resolution
    store.conn.execute(
        """
        UPDATE personal_memory_conflicts
        SET status = 'resolved',
            resolved_at = ?,
            metadata = ?
        WHERE id = ?
        """,
        (utc_iso(), json_dumps(metadata), conflict_id),
    )
    store.conn.commit()
    return store.conn.execute("SELECT * FROM personal_memory_conflicts WHERE id = ?", (conflict_id,)).fetchone()


def suggested_memory_candidates(settings: Any, store: Store, target: date, *, limit: int) -> list[dict[str, Any]]:
    candidates = candidate_dicts_for_day(settings, store, target, limit=limit)
    rows = []
    for candidate in candidates:
        memory_id = str(candidate["id"])
        existing = fetch_memory(store, memory_id, required=False)
        payload = dict(candidate)
        payload["existing_status"] = existing["status"] if existing is not None else ""
        payload["already_saved"] = existing is not None
        rows.append(payload)
    return rows


def materialize_memory_candidates(settings: Any, store: Store, target: date, *, limit: int) -> list[Any]:
    created: list[Any] = []
    for candidate in candidate_dicts_for_day(settings, store, target, limit=limit):
        if fetch_memory(store, candidate["id"], required=False) is not None:
            continue
        row = upsert_memory_from_payload(store, candidate, default_status="candidate", replace_existing=False)
        created.append(row)
    return created


def candidate_dicts_for_day(settings: Any, store: Store, target: date, *, limit: int) -> list[dict[str, Any]]:
    start, end = day_bounds(target, settings.timezone)
    configured_sources = personal_memory_sources(settings)
    rows = store.observations_between(local_iso(start), local_iso(end))
    observations = [
        row
        for row in visible_observations(settings, rows)
        if not configured_sources or str(row["source"] or "") in configured_sources
    ]
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in sorted(observations, key=lambda item: item["observed_at"] or "", reverse=True):
        for candidate in candidates_for_observation(row):
            if candidate["id"] in seen:
                continue
            seen.add(candidate["id"])
            candidates.append(candidate)
            if len(candidates) >= limit:
                return candidates
    return candidates


def candidates_for_observation(row: Any) -> list[dict[str, Any]]:
    text = observation_text(row)
    if len(text) < 12:
        return []
    lowered = text.casefold()
    base_evidence = {
        "source_ref": f"observation:{row['id']}",
        "source_type": f"{row['source']}/{row['kind']}",
        "title": row["title"] or row["subtitle"] or row["actor"] or row["kind"],
        "snippet": compact(text, 700),
        "observed_at": row["observed_at"],
        "url": row["url"],
    }
    rows: list[dict[str, Any]] = []

    def add(memory_type: str, title: str, subject: str, confidence: float = 0.62) -> None:
        sensitivity = sensitivity_for_text(memory_type, text)
        memory_id = stable_id("pmem", memory_type, subject, title, compact(text, 240), base_evidence["source_ref"])
        rows.append(
            {
                "id": memory_id,
                "memory_type": memory_type,
                "status": "candidate",
                "title": title,
                "body": compact(text, 700),
                "subject": subject,
                "sensitivity": sensitivity,
                "confidence": confidence,
                "source": "auto_candidate",
                "last_seen_at": row["observed_at"],
                "evidence": [base_evidence],
                "metadata": {"extractor": "heuristic_v1", "source": row["source"], "kind": row["kind"]},
            }
        )

    actor = str(row["actor"] or "").strip()
    if actor and actor.casefold() != "me":
        add("relationship", f"与 {actor} 的互动值得确认", actor, confidence=0.58)
    if contains_term(lowered, PREFERENCE_TERMS):
        add("preference", "可能的新偏好", subject_from_text(text, fallback="preference"), confidence=0.66)
    if contains_term(lowered, BOUNDARY_TERMS):
        add("boundary", "可能的个人边界", subject_from_text(text, fallback="boundary"), confidence=0.66)
    if contains_term(lowered, DECISION_TERMS):
        add("decision", "可能的决定", subject_from_text(text, fallback="decision"), confidence=0.64)
    if contains_term(lowered, FOLLOW_UP_TERMS):
        add("commitment", "可能的承诺或待跟进", subject_from_text(text, fallback="commitment"), confidence=0.62)
    if contains_term(lowered, RHYTHM_TERMS):
        add("rhythm", "可能的健康/节律信号", "health-rhythm", confidence=0.58)
    return rows[:3]


def personal_context_semantic_items(settings: Any, store: Store, question: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    config = personal_memory_config(settings)
    if not bool_config(config.get("qa_include_confirmed"), True):
        return []
    limit = limit or personal_memory_qa_limit(settings)
    keywords = search_keywords(question)
    rows = store.conn.execute(
        """
        SELECT *
        FROM personal_memories
        WHERE status = 'confirmed'
          AND (valid_until IS NULL OR valid_until = '' OR valid_until >= date('now'))
        ORDER BY updated_at DESC
        LIMIT 300
        """
    ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        text = memory_search_text(row)
        score = keyword_score(text, keywords)
        if keywords and score <= 0:
            continue
        items.append(personal_memory_semantic_item(store, row, score or 0.25))
    if bool_config(config.get("qa_include_profile"), True):
        for row in store.conn.execute(
            """
            SELECT *
            FROM personal_profile_entries
            WHERE status = 'active'
            ORDER BY updated_at DESC
            LIMIT 120
            """
        ).fetchall():
            text = f"{row['section']} {row['label']} {row['value']}"
            score = keyword_score(text, keywords)
            if keywords and score <= 0:
                continue
            items.append(
                {
                    "type": "personal_profile",
                    "key": row["id"],
                    "score": round(score or 0.2, 4),
                    "title": f"个人档案: {row['label']}",
                    "text": compact(text, 700),
                    "observed_at": row["updated_at"],
                    "source": "personal_profile",
                    "kind": row["section"],
                    "path": None,
                    "payload": profile_entry_payload(row),
                }
            )
    items.sort(key=lambda item: (float(item.get("score") or 0), item.get("observed_at") or ""), reverse=True)
    return items[:limit]


def personal_memory_semantic_item(store: Store, row: Any, score: float = 1.0) -> dict[str, Any]:
    evidence = evidence_payload(store, row["id"])
    text = "\n".join(
        part
        for part in (
            row["title"],
            row["subject"],
            row["body"],
            "Evidence: " + "; ".join(compact(item.get("snippet"), 140) for item in evidence[:3]) if evidence else "",
        )
        if part
    )
    return {
        "type": "personal_memory",
        "key": row["id"],
        "score": round(score, 4),
        "title": row["title"],
        "text": compact(text, 900),
        "observed_at": row["updated_at"],
        "source": "personal_memory",
        "kind": row["memory_type"],
        "path": None,
        "payload": memory_payload(store, row),
    }


def personal_context_report_lines(settings: Any, store: Store, *, limit: int = 16) -> list[str]:
    if not bool_config(personal_memory_config(settings).get("enabled"), True):
        return []
    lines: list[str] = []
    profile_rows = store.conn.execute(
        """
        SELECT *
        FROM personal_profile_entries
        WHERE status = 'active'
        ORDER BY section ASC, updated_at DESC
        LIMIT 24
        """
    ).fetchall()
    if profile_rows:
        lines.append("## Personal Profile Context")
        for row in profile_rows[:8]:
            lines.append(f"- {profile_section_label(row['section'])} / {row['label']}: {compact(row['value'], 180)}")
        lines.append("")
    memory_rows = store.conn.execute(
        """
        SELECT *
        FROM personal_memories
        WHERE status = 'confirmed'
        ORDER BY
          CASE memory_type
            WHEN 'boundary' THEN 0
            WHEN 'preference' THEN 1
            WHEN 'relationship' THEN 2
            WHEN 'commitment' THEN 3
            ELSE 4
          END,
          updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    if memory_rows:
        lines.append("## Confirmed Personal Memory Context")
        for row in memory_rows:
            subject = f" [{row['subject']}]" if row["subject"] else ""
            sensitivity = f" ({row['sensitivity']})" if row["sensitivity"] != "normal" else ""
            lines.append(f"- {row['memory_type']}{subject}{sensitivity}: {compact(row['title'] + ' ' + (row['body'] or ''), 240)}")
        lines.append("")
    return lines


def personal_memory_search_rows(store: Store, *, limit: int) -> list[Any]:
    return store.conn.execute(
        """
        SELECT *
        FROM personal_memories
        WHERE status = 'confirmed'
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def personal_memory_summary(
    store: Store,
    memories: list[dict[str, Any]],
    suggested: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
) -> dict[str, Any]:
    status_counts = Counter(
        row["status"]
        for row in store.conn.execute("SELECT status FROM personal_memories").fetchall()
    )
    people_count = store.conn.execute("SELECT count(*) AS n FROM personal_people WHERE status = 'active'").fetchone()["n"]
    profile_count = store.conn.execute("SELECT count(*) AS n FROM personal_profile_entries WHERE status = 'active'").fetchone()["n"]
    return {
        "shown": len(memories),
        "profile_entries": int(profile_count or 0),
        "people": int(people_count or 0),
        "candidate": int(status_counts["candidate"]),
        "confirmed": int(status_counts["confirmed"]),
        "ignored": int(status_counts["ignored"]),
        "archived": int(status_counts["archived"]),
        "suggested": len([row for row in suggested if not row.get("already_saved")]),
        "open_conflicts": len([row for row in conflicts if row.get("status") == "open"]),
    }


def personal_memory_privacy_summary(store: Store) -> dict[str, Any]:
    sensitivity_rows = store.conn.execute(
        """
        SELECT sensitivity, count(*) AS n
        FROM personal_memories
        GROUP BY sensitivity
        """
    ).fetchall()
    source_rows = store.conn.execute(
        """
        SELECT source, count(*) AS n
        FROM personal_memories
        GROUP BY source
        ORDER BY n DESC
        """
    ).fetchall()
    return {
        "by_sensitivity": {str(row["sensitivity"] or "normal"): int(row["n"] or 0) for row in sensitivity_rows},
        "by_source": [{"source": row["source"] or "manual", "count": int(row["n"] or 0)} for row in source_rows],
        "hard_delete_supported": True,
        "high_sensitivity_confirmation": True,
    }


def observation_text(row: Any) -> str:
    metadata = json_dict(row["metadata"])
    analysis = metadata.get("audio_analysis") if isinstance(metadata.get("audio_analysis"), dict) else {}
    parts = [
        row["actor"],
        row["title"],
        row["subtitle"],
        row["body"],
        row["location"],
        analysis.get("summary") if isinstance(analysis, dict) else "",
        analysis.get("local_summary") if isinstance(analysis, dict) else "",
    ]
    return " ".join(str(part).strip() for part in parts if str(part or "").strip())


def memory_search_text(row: Any) -> str:
    return " ".join(str(row[key] or "") for key in ("memory_type", "title", "body", "subject", "sensitivity", "source"))


def normalized_subject(row: Any) -> str:
    return normalize_text(row["subject"] or row["title"])


def normalized_memory_text(row: Any) -> str:
    return normalize_text(f"{row['title']} {row['body'] or ''}")


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold()).strip()


def contains_term(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def subject_from_text(text: str, *, fallback: str) -> str:
    keywords = [word for word in search_keywords(text) if len(word) >= 2]
    return " ".join(keywords[:4]) if keywords else fallback


def sensitivity_for_text(memory_type: str, text: str) -> str:
    lowered = text.casefold()
    if memory_type in {"rhythm", "boundary"}:
        return "private"
    if any(term in lowered for term in ("health", "doctor", "hospital", "medical", "病", "医院", "隐私", "敏感")):
        return "high"
    if any(term in lowered for term in ("relationship", "family", "mail", "message", "关系", "家庭", "邮件", "聊天")):
        return "private"
    return "normal"


def keyword_score(text: str, keywords: list[str]) -> float:
    if not keywords:
        return 0.0
    lowered = text.casefold()
    hits = sum(1 for keyword in keywords if keyword.casefold() in lowered)
    return hits / max(1, len(keywords))


def evidence_observed_at(evidence: list[dict[str, Any]]) -> str | None:
    for item in evidence:
        value = item.get("observed_at") or item.get("time")
        if value:
            return str(value)
    return None


def require_text(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    raise KeyError(f"{keys[0]}_required")


def split_values(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = value
    else:
        raw = re.split(r"[,，\n]", str(value or ""))
    values = []
    for item in raw:
        cleaned = str(item or "").strip()
        if cleaned and cleaned not in values:
            values.append(cleaned)
    return values


def clean_choice(value: Any, choices: tuple[str, ...], default: str) -> str:
    text = str(value or "").strip()
    return text if text in choices else default


def parse_float(value: Any, *, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def bool_config(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if value is None:
        return default
    return bool(value)


def personal_memory_limit(settings: Any) -> int:
    return max(1, min(80, parse_int(personal_memory_config(settings).get("max_candidates_per_day")) or 24))


def personal_memory_qa_limit(settings: Any) -> int:
    return max(1, min(40, parse_int(personal_memory_config(settings).get("qa_memory_limit")) or 12))


def personal_memory_sources(settings: Any) -> set[str]:
    raw = personal_memory_config(settings).get("candidate_sources") or []
    if isinstance(raw, str):
        return {item.strip() for item in raw.split(",") if item.strip()}
    if isinstance(raw, list):
        return {str(item).strip() for item in raw if str(item).strip()}
    return set()


def personal_memory_config(settings: Any) -> dict[str, Any]:
    raw = getattr(settings, "personal_memory", None)
    return dict(raw) if isinstance(raw, dict) else {}


def profile_section_label(section: str) -> str:
    return {
        "identity": "身份",
        "work": "工作/学习",
        "preferences": "偏好",
        "boundaries": "边界",
        "rhythm": "节律",
        "focus": "当前重点",
    }.get(section, section)


def person_search_text(row: dict[str, Any]) -> str:
    aliases = " ".join(alias.get("alias", "") for alias in row.get("aliases", []))
    return " ".join(
        str(part)
        for part in (
            row.get("display_name"),
            row.get("relationship"),
            row.get("organization"),
            row.get("notes"),
            aliases,
        )
        if part
    )


def stable_id(prefix: str, *parts: Any) -> str:
    text = "|".join(normalize_text(part) for part in parts if str(part or "").strip())
    digest = hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def json_dumps(value: Any) -> str:
    return json.dumps(value if isinstance(value, dict) else {}, ensure_ascii=False, sort_keys=True)
