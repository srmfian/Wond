from __future__ import annotations

import json
import re
from collections import Counter
from http import HTTPStatus
from typing import Any

from .insights import (
    action_sentences,
    compact_text,
    day_window,
    project_clusters_from_rows,
    recommended_action,
    stable_short_key,
    suggestion_title,
    visible_observations,
)
from .store import Observation, Store, json_dict
from .timeutil import now, utc_iso


PROJECT_STATUSES = {"active", "focused", "paused", "archived"}
MEETING_STATUSES = {"active", "ended"}


def project_memory_payload(settings: Any, params: dict[str, str]) -> dict[str, Any]:
    window = day_window(settings, params.get("date") or "today")
    store = Store(settings.db_path)
    try:
        memories = project_memory_rows(store, params)
        observations = visible_observations(settings, store.observations_between(window.start_iso, window.end_iso))
        activity = list(store.activity_between(window.start_iso, window.end_iso))
        suggested_projects = project_clusters_from_rows(settings, observations, activity, window.target, limit=18)
        return {
            "ok": True,
            "date": window.target.isoformat(),
            "generated_at": now(settings.timezone).isoformat(timespec="seconds"),
            "summary": project_memory_summary(store, memories, suggested_projects),
            "memories": [project_memory_row_payload(row, store=store) for row in memories],
            "suggested_projects": suggested_projects,
        }
    finally:
        store.close()


def project_memory_post(settings: Any, payload: dict[str, Any]) -> tuple[dict[str, Any], HTTPStatus]:
    action = str(payload.get("action") or "").strip() or ("save_project" if isinstance(payload.get("project"), dict) else "create")
    store = Store(settings.db_path)
    try:
        if action == "save_project":
            project = payload.get("project") if isinstance(payload.get("project"), dict) else {}
            if not project:
                return {"ok": False, "error": "project_required"}, HTTPStatus.BAD_REQUEST
            memory = save_project_cluster(store, project, event_date=str(payload.get("date") or ""))
            return {"ok": True, "memory": project_memory_row_payload(memory, store=store)}, HTTPStatus.OK
        if action == "create":
            title = str(payload.get("title") or "").strip()
            if not title:
                return {"ok": False, "error": "title_required"}, HTTPStatus.BAD_REQUEST
            memory = create_project_memory(
                store,
                title=title,
                summary=str(payload.get("summary") or "").strip(),
                keywords=split_values(payload.get("keywords")),
                people=split_values(payload.get("people")),
                next_actions=manual_next_actions(payload.get("next_actions")),
            )
            return {"ok": True, "memory": project_memory_row_payload(memory, store=store)}, HTTPStatus.CREATED
        if action == "update":
            project_id = str(payload.get("project_id") or payload.get("id") or "").strip()
            if not project_id:
                return {"ok": False, "error": "project_id_required"}, HTTPStatus.BAD_REQUEST
            if store.conn.execute("SELECT 1 FROM project_memories WHERE id = ?", (project_id,)).fetchone() is None:
                return {"ok": False, "error": "project_not_found"}, HTTPStatus.NOT_FOUND
            status = str(payload.get("status") or "").strip()
            if status and status not in PROJECT_STATUSES:
                return {"ok": False, "error": "invalid_status"}, HTTPStatus.BAD_REQUEST
            update_project_memory(store, project_id, payload)
            row = store.conn.execute("SELECT * FROM project_memories WHERE id = ?", (project_id,)).fetchone()
            return {"ok": True, "memory": project_memory_row_payload(row, store=store)}, HTTPStatus.OK
        return {"ok": False, "error": "invalid_action"}, HTTPStatus.BAD_REQUEST
    finally:
        store.close()


def meeting_mode_payload(settings: Any, params: dict[str, str] | None = None) -> dict[str, Any]:
    params = params or {}
    store = Store(settings.db_path)
    try:
        active = store.conn.execute(
            """
            SELECT *
            FROM meeting_sessions
            WHERE status = 'active'
            ORDER BY started_at DESC
            LIMIT 1
            """
        ).fetchone()
        recent = store.conn.execute(
            """
            SELECT *
            FROM meeting_sessions
            ORDER BY started_at DESC
            LIMIT 20
            """
        ).fetchall()
        projects = project_memory_rows(store, {"status": "active"})
        return {
            "ok": True,
            "generated_at": now(settings.timezone).isoformat(timespec="seconds"),
            "summary": {
                "active": 1 if active is not None else 0,
                "recent": len(recent),
                "projects": len(projects),
                "ended": sum(1 for row in recent if row["status"] == "ended"),
            },
            "active_meeting": meeting_row_payload(active, store=store) if active is not None else None,
            "recent_meetings": [meeting_row_payload(row, store=store) for row in recent],
            "projects": [project_memory_row_payload(row, store=store, include_events=False) for row in projects],
        }
    finally:
        store.close()


def meeting_mode_post(settings: Any, payload: dict[str, Any]) -> tuple[dict[str, Any], HTTPStatus]:
    action = str(payload.get("action") or "").strip()
    store = Store(settings.db_path)
    try:
        if action == "start":
            result, status = start_meeting(settings, store, payload)
        elif action == "note":
            result, status = add_meeting_note(settings, store, payload)
        elif action == "end":
            result, status = end_meeting(settings, store, payload)
        else:
            result, status = {"ok": False, "error": "invalid_action"}, HTTPStatus.BAD_REQUEST
        return result, status
    finally:
        store.close()


def project_memory_rows(store: Store, params: dict[str, str]) -> list[Any]:
    status_filter = str(params.get("status") or "active").strip()
    rows = store.conn.execute(
        """
        SELECT *
        FROM project_memories
        ORDER BY
          CASE status WHEN 'focused' THEN 0 WHEN 'active' THEN 1 WHEN 'paused' THEN 2 ELSE 3 END,
          COALESCE(last_seen_at, updated_at) DESC,
          title ASC
        """
    ).fetchall()
    if status_filter == "active":
        rows = [row for row in rows if row["status"] != "archived"]
    elif status_filter and status_filter != "all":
        rows = [row for row in rows if row["status"] == status_filter]
    q = str(params.get("q") or "").strip().lower()
    if q:
        rows = [row for row in rows if q in project_memory_search_text(row)]
    return rows


def save_project_cluster(store: Store, project: dict[str, Any], *, event_date: str = "") -> Any:
    title = str(project.get("title") or "未命名项目").strip()
    keywords = [str(item).strip() for item in project.get("keywords") or [] if str(item).strip()]
    project_id = project_memory_id(title, keywords)
    summary = str(project.get("summary") or "").strip()
    next_actions = project.get("next_actions") if isinstance(project.get("next_actions"), list) else []
    evidence = project.get("evidence") if isinstance(project.get("evidence"), list) else []
    span = project.get("time_span") if isinstance(project.get("time_span"), dict) else {}
    observed_at = str(span.get("end") or span.get("start") or "")
    now_iso = utc_iso()
    existing = store.conn.execute("SELECT * FROM project_memories WHERE id = ?", (project_id,)).fetchone()
    if existing is None:
        store.conn.execute(
            """
            INSERT INTO project_memories (
                id, title, status, summary, keywords, people, next_actions,
                created_at, updated_at, last_seen_at, evidence_count, metadata
            ) VALUES (?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                project_id,
                title,
                summary,
                json_dump(keywords),
                json_dump([]),
                json_dump(next_actions),
                now_iso,
                now_iso,
                observed_at or now_iso,
                json_dump({"source": "project_cluster", "last_project_id": project.get("id")}),
            ),
        )
    else:
        merged_keywords = merge_values(json_list(existing["keywords"]), keywords)
        merged_actions = merge_action_items(json_list(existing["next_actions"]), next_actions)
        store.conn.execute(
            """
            UPDATE project_memories
            SET title = ?,
                summary = ?,
                keywords = ?,
                next_actions = ?,
                updated_at = ?,
                last_seen_at = COALESCE(?, last_seen_at),
                metadata = ?
            WHERE id = ?
            """,
            (
                title,
                summary or existing["summary"],
                json_dump(merged_keywords),
                json_dump(merged_actions),
                now_iso,
                observed_at or None,
                json_dump({**json_dict(existing["metadata"]), "last_project_id": project.get("id")}),
                project_id,
            ),
        )
    add_project_memory_event(
        store,
        project_id=project_id,
        event_date=event_date or date_from_iso(observed_at) or "",
        source_ref=str(project.get("id") or stable_short_key(title + summary)),
        title=title,
        summary=summary,
        observed_at=observed_at or now_iso,
        metadata={"kind": "project_cluster", "evidence": evidence[:12], "categories": project.get("categories") or {}},
    )
    store.conn.commit()
    return store.conn.execute("SELECT * FROM project_memories WHERE id = ?", (project_id,)).fetchone()


def create_project_memory(
    store: Store,
    *,
    title: str,
    summary: str = "",
    keywords: list[str] | None = None,
    people: list[str] | None = None,
    next_actions: list[dict[str, Any]] | None = None,
) -> Any:
    keywords = keywords or []
    people = people or []
    project_id = project_memory_id(title, keywords)
    now_iso = utc_iso()
    store.conn.execute(
        """
        INSERT INTO project_memories (
            id, title, status, summary, keywords, people, next_actions,
            created_at, updated_at, last_seen_at, evidence_count, metadata
        ) VALUES (?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, 0, ?)
        ON CONFLICT(id) DO UPDATE SET
            title = excluded.title,
            summary = excluded.summary,
            keywords = excluded.keywords,
            people = excluded.people,
            next_actions = excluded.next_actions,
            status = 'active',
            updated_at = excluded.updated_at,
            last_seen_at = excluded.last_seen_at
        """,
        (
            project_id,
            title,
            summary,
            json_dump(keywords),
            json_dump(people),
            json_dump(next_actions or []),
            now_iso,
            now_iso,
            now_iso,
            json_dump({"source": "manual"}),
        ),
    )
    store.conn.commit()
    return store.conn.execute("SELECT * FROM project_memories WHERE id = ?", (project_id,)).fetchone()


def update_project_memory(store: Store, project_id: str, payload: dict[str, Any]) -> None:
    row = store.conn.execute("SELECT * FROM project_memories WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        return
    status = str(payload.get("status") or row["status"]).strip()
    summary = str(payload.get("summary") if payload.get("summary") is not None else row["summary"] or "").strip()
    keywords = split_values(payload.get("keywords")) if "keywords" in payload else json_list(row["keywords"])
    people = split_values(payload.get("people")) if "people" in payload else json_list(row["people"])
    next_actions = manual_next_actions(payload.get("next_actions")) if "next_actions" in payload else json_list(row["next_actions"])
    metadata = json_dict(row["metadata"])
    if isinstance(payload.get("metadata"), dict):
        metadata.update(payload["metadata"])
    store.conn.execute(
        """
        UPDATE project_memories
        SET status = ?, summary = ?, keywords = ?, people = ?, next_actions = ?, updated_at = ?, metadata = ?
        WHERE id = ?
        """,
        (status, summary, json_dump(keywords), json_dump(people), json_dump(next_actions), utc_iso(), json_dump(metadata), project_id),
    )
    store.conn.commit()


def add_project_memory_event(
    store: Store,
    *,
    project_id: str,
    event_date: str,
    source_ref: str,
    title: str,
    summary: str,
    observed_at: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    now_iso = utc_iso()
    store.conn.execute(
        """
        INSERT INTO project_memory_events (
            project_id, event_date, source_ref, title, summary, observed_at, created_at, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(project_id, source_ref) DO UPDATE SET
            event_date = excluded.event_date,
            title = excluded.title,
            summary = excluded.summary,
            observed_at = excluded.observed_at,
            metadata = excluded.metadata
        """,
        (project_id, event_date, source_ref, title, summary, observed_at, now_iso, json_dump(metadata or {})),
    )
    count = store.conn.execute("SELECT count(*) FROM project_memory_events WHERE project_id = ?", (project_id,)).fetchone()[0]
    store.conn.execute(
        """
        UPDATE project_memories
        SET evidence_count = ?, last_seen_at = COALESCE(?, last_seen_at), updated_at = ?
        WHERE id = ?
        """,
        (int(count or 0), observed_at or None, now_iso, project_id),
    )


def start_meeting(settings: Any, store: Store, payload: dict[str, Any]) -> tuple[dict[str, Any], HTTPStatus]:
    title = str(payload.get("title") or "").strip()
    if not title:
        return {"ok": False, "error": "title_required"}, HTTPStatus.BAD_REQUEST
    project_id = str(payload.get("project_id") or "").strip() or None
    if project_id and store.conn.execute("SELECT 1 FROM project_memories WHERE id = ?", (project_id,)).fetchone() is None:
        return {"ok": False, "error": "project_not_found"}, HTTPStatus.NOT_FOUND
    started_at = now(settings.timezone).isoformat(timespec="seconds")
    meeting_id = f"meeting:{started_at}:{stable_short_key(title)}"
    participants = split_values(payload.get("participants"))
    agenda = str(payload.get("agenda") or "").strip()
    store.conn.execute(
        """
        INSERT INTO meeting_sessions (
            id, title, project_id, status, started_at, participants, agenda, notes,
            summary, action_items, created_at, updated_at, metadata
        ) VALUES (?, ?, ?, 'active', ?, ?, ?, '', '', ?, ?, ?, ?)
        """,
        (
            meeting_id,
            title,
            project_id,
            started_at,
            json_dump(participants),
            agenda,
            json_dump([]),
            utc_iso(),
            utc_iso(),
            json_dump({"source": "meeting_mode"}),
        ),
    )
    write_meeting_observation(
        settings,
        store,
        meeting_id=meeting_id,
        kind="meeting_session",
        observed_at=started_at,
        title=title,
        body=agenda,
        project_id=project_id,
        metadata={"participants": participants, "status": "active"},
    )
    store.conn.commit()
    row = store.conn.execute("SELECT * FROM meeting_sessions WHERE id = ?", (meeting_id,)).fetchone()
    return {"ok": True, "meeting": meeting_row_payload(row, store=store)}, HTTPStatus.CREATED


def add_meeting_note(settings: Any, store: Store, payload: dict[str, Any]) -> tuple[dict[str, Any], HTTPStatus]:
    meeting_id = str(payload.get("meeting_id") or "").strip()
    note = str(payload.get("note") or "").strip()
    if not meeting_id:
        return {"ok": False, "error": "meeting_id_required"}, HTTPStatus.BAD_REQUEST
    if not note:
        return {"ok": False, "error": "note_required"}, HTTPStatus.BAD_REQUEST
    row = store.conn.execute("SELECT * FROM meeting_sessions WHERE id = ?", (meeting_id,)).fetchone()
    if row is None:
        return {"ok": False, "error": "meeting_not_found"}, HTTPStatus.NOT_FOUND
    stamped_note = f"[{now(settings.timezone).isoformat(timespec='seconds')}] {note}"
    notes = "\n".join(part for part in (row["notes"] or "", stamped_note) if part)
    actions = meeting_action_items(notes)
    updated_at = utc_iso()
    store.conn.execute(
        """
        UPDATE meeting_sessions
        SET notes = ?, action_items = ?, updated_at = ?
        WHERE id = ?
        """,
        (notes, json_dump(actions), updated_at, meeting_id),
    )
    observed_at = now(settings.timezone).isoformat(timespec="seconds")
    write_meeting_observation(
        settings,
        store,
        meeting_id=meeting_id,
        kind="meeting_note",
        observed_at=observed_at,
        title=f"Meeting note: {row['title']}",
        body=note,
        project_id=row["project_id"],
        metadata={"status": row["status"]},
    )
    store.conn.commit()
    updated = store.conn.execute("SELECT * FROM meeting_sessions WHERE id = ?", (meeting_id,)).fetchone()
    return {"ok": True, "meeting": meeting_row_payload(updated, store=store)}, HTTPStatus.OK


def end_meeting(settings: Any, store: Store, payload: dict[str, Any]) -> tuple[dict[str, Any], HTTPStatus]:
    meeting_id = str(payload.get("meeting_id") or "").strip()
    if not meeting_id:
        return {"ok": False, "error": "meeting_id_required"}, HTTPStatus.BAD_REQUEST
    row = store.conn.execute("SELECT * FROM meeting_sessions WHERE id = ?", (meeting_id,)).fetchone()
    if row is None:
        return {"ok": False, "error": "meeting_not_found"}, HTTPStatus.NOT_FOUND
    extra_note = str(payload.get("note") or "").strip()
    if extra_note:
        add_meeting_note(settings, store, {"meeting_id": meeting_id, "note": extra_note})
        row = store.conn.execute("SELECT * FROM meeting_sessions WHERE id = ?", (meeting_id,)).fetchone()
    ended_at = now(settings.timezone).isoformat(timespec="seconds")
    notes = row["notes"] or ""
    actions = meeting_action_items(notes)
    summary = meeting_summary(row["title"], row["agenda"], notes, actions)
    store.conn.execute(
        """
        UPDATE meeting_sessions
        SET status = 'ended', ended_at = ?, summary = ?, action_items = ?, updated_at = ?
        WHERE id = ?
        """,
        (ended_at, summary, json_dump(actions), utc_iso(), meeting_id),
    )
    project_id = row["project_id"]
    write_meeting_observation(
        settings,
        store,
        meeting_id=meeting_id,
        kind="meeting_summary",
        observed_at=ended_at,
        title=f"Meeting summary: {row['title']}",
        body=summary,
        project_id=project_id,
        metadata={"status": "ended", "action_items": actions},
    )
    if project_id:
        add_project_memory_event(
            store,
            project_id=project_id,
            event_date=date_from_iso(ended_at) or "",
            source_ref=meeting_id,
            title=row["title"],
            summary=summary,
            observed_at=ended_at,
            metadata={"kind": "meeting", "action_items": actions},
        )
        merge_project_actions(store, project_id, actions)
    store.conn.commit()
    updated = store.conn.execute("SELECT * FROM meeting_sessions WHERE id = ?", (meeting_id,)).fetchone()
    return {"ok": True, "meeting": meeting_row_payload(updated, store=store)}, HTTPStatus.OK


def write_meeting_observation(
    settings: Any,
    store: Store,
    *,
    meeting_id: str,
    kind: str,
    observed_at: str,
    title: str,
    body: str,
    project_id: str | None,
    metadata: dict[str, Any] | None = None,
) -> None:
    meta = {"meeting_id": meeting_id, "project_id": project_id}
    if metadata:
        meta.update(metadata)
    source_key = f"{meeting_id}:{kind}:{stable_short_key(observed_at + title + body)}"
    store.upsert_observations(
        [
            Observation(
                source="meeting",
                kind=kind,
                source_key=source_key,
                observed_at=observed_at,
                title=title,
                body=body,
                metadata=meta,
            )
        ]
    )


def project_memory_row_payload(row: Any, *, store: Store, include_events: bool = True) -> dict[str, Any]:
    events = []
    if include_events:
        event_rows = store.conn.execute(
            """
            SELECT *
            FROM project_memory_events
            WHERE project_id = ?
            ORDER BY observed_at DESC, id DESC
            LIMIT 12
            """,
            (row["id"],),
        ).fetchall()
        events = [project_event_payload(event) for event in event_rows]
    return {
        "id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "summary": row["summary"] or "",
        "keywords": json_list(row["keywords"]),
        "people": json_list(row["people"]),
        "next_actions": json_list(row["next_actions"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_seen_at": row["last_seen_at"],
        "evidence_count": int(row["evidence_count"] or 0),
        "metadata": json_dict(row["metadata"]),
        "events": events,
    }


def project_event_payload(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "event_date": row["event_date"],
        "source_ref": row["source_ref"],
        "title": row["title"],
        "summary": row["summary"],
        "observed_at": row["observed_at"],
        "created_at": row["created_at"],
        "metadata": json_dict(row["metadata"]),
    }


def meeting_row_payload(row: Any, *, store: Store) -> dict[str, Any]:
    project = None
    if row["project_id"]:
        project_row = store.conn.execute("SELECT * FROM project_memories WHERE id = ?", (row["project_id"],)).fetchone()
        if project_row is not None:
            project = project_memory_row_payload(project_row, store=store, include_events=False)
    return {
        "id": row["id"],
        "title": row["title"],
        "project_id": row["project_id"],
        "project": project,
        "status": row["status"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "participants": json_list(row["participants"]),
        "agenda": row["agenda"] or "",
        "notes": row["notes"] or "",
        "summary": row["summary"] or "",
        "action_items": json_list(row["action_items"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "metadata": json_dict(row["metadata"]),
    }


def project_memory_summary(store: Store, memories: list[Any], suggested_projects: list[dict[str, Any]]) -> dict[str, Any]:
    all_rows = store.conn.execute("SELECT status FROM project_memories").fetchall()
    statuses = Counter(row["status"] for row in all_rows)
    active_meeting = store.conn.execute("SELECT count(*) FROM meeting_sessions WHERE status = 'active'").fetchone()[0]
    return {
        "total": len(all_rows),
        "shown": len(memories),
        "active": sum(count for status, count in statuses.items() if status != "archived"),
        "focused": statuses.get("focused", 0),
        "archived": statuses.get("archived", 0),
        "suggested": len(suggested_projects),
        "active_meeting": int(active_meeting or 0),
    }


def project_memory_search_text(row: Any) -> str:
    values = [
        row["id"],
        row["title"],
        row["status"],
        row["summary"],
        " ".join(json_list(row["keywords"])),
        " ".join(json_list(row["people"])),
        " ".join(str(item.get("title") or item.get("body") or "") for item in json_list(row["next_actions"]) if isinstance(item, dict)),
    ]
    return " ".join(str(value or "") for value in values).lower()


def meeting_action_items(text: str) -> list[dict[str, Any]]:
    items = []
    for sentence in action_sentences(text):
        items.append(
            {
                "id": f"meeting-action:{stable_short_key(sentence)}",
                "title": suggestion_title(sentence),
                "body": compact_text(sentence, 360),
                "recommended_action": recommended_action(sentence),
            }
        )
    return merge_action_items([], items)[:12]


def meeting_summary(title: str, agenda: str | None, notes: str, actions: list[dict[str, Any]]) -> str:
    lines = [f"会议：{title}"]
    if agenda:
        lines.append(f"议程：{compact_text(agenda, 260)}")
    if notes:
        lines.append(f"记录：{compact_text(notes, 800)}")
    if actions:
        lines.append("行动项：" + "；".join(str(item.get("title") or item.get("body")) for item in actions[:6]))
    return "\n".join(lines)


def merge_project_actions(store: Store, project_id: str, actions: list[dict[str, Any]]) -> None:
    row = store.conn.execute("SELECT * FROM project_memories WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        return
    merged = merge_action_items(json_list(row["next_actions"]), actions)
    store.conn.execute(
        "UPDATE project_memories SET next_actions = ?, updated_at = ? WHERE id = ?",
        (json_dump(merged), utc_iso(), project_id),
    )


def manual_next_actions(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    text = str(value or "").strip()
    if not text:
        return []
    actions = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            actions.append({"id": f"manual-action:{stable_short_key(line)}", "title": line, "body": line})
    return actions


def project_memory_id(title: str, keywords: list[str] | None = None) -> str:
    values = [normalize_key(title), *[normalize_key(item) for item in (keywords or [])[:6]]]
    return f"project:{stable_short_key('|'.join(value for value in values if value))}"


def normalize_key(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def split_values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r"[,，\n、]+", text) if part.strip()]


def merge_values(left: list[Any], right: list[Any], limit: int = 24) -> list[Any]:
    result = []
    seen = set()
    for value in [*left, *right]:
        key = normalize_key(str(value))
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value)
        if len(result) >= limit:
            break
    return result


def merge_action_items(left: list[Any], right: list[Any], limit: int = 20) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen = set()
    for item in [*left, *right]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("body") or "").strip()
        key = str(item.get("id") or stable_short_key(title))
        if not title or key in seen:
            continue
        copy = dict(item)
        copy.setdefault("id", key)
        copy.setdefault("body", title)
        seen.add(key)
        result.append(copy)
        if len(result) >= limit:
            break
    return result


def json_list(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return list(raw)
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except ValueError:
        return []
    return parsed if isinstance(parsed, list) else []


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def date_from_iso(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value)
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return None
