from __future__ import annotations

import json
import hashlib
import math
import re
import sqlite3
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from .speakers import speaker_review_status
from .store import Store, json_dict, speaker_display_name_is_auto
from .timeutil import day_bounds, local_iso, now, parse_day


ACTION_KEYWORDS = (
    "todo",
    "action item",
    "follow up",
    "send",
    "reply",
    "email",
    "call",
    "remind",
    "deadline",
    "due",
    "need to",
    "should",
    "要",
    "需要",
    "待办",
    "提醒",
    "发给",
    "回复",
    "联系",
    "确认",
    "截止",
    "明天",
    "下周",
)

STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "today",
    "about",
    "into",
    "your",
    "you",
    "are",
    "was",
    "were",
    "will",
    "todo",
    "need",
    "should",
    "personal",
    "context",
    "mobile",
    "audio",
    "segment",
    "recording",
    "summary",
    "file",
    "report",
    "activity",
    "null",
    "none",
    "osascript",
    "今天",
    "昨天",
    "明天",
    "录音",
    "摘要",
    "文件",
    "活动",
}


@dataclass
class DayWindow:
    target: date
    start_iso: str
    end_iso: str


def action_center_payload(settings: Any, params: dict[str, str]) -> dict[str, Any]:
    window = day_window(settings, params.get("date") or "today")
    store = Store(settings.db_path)
    try:
        observations = visible_observations(settings, store.observations_between(window.start_iso, window.end_iso))
        activity = list(store.activity_between(window.start_iso, window.end_iso))
        categories = category_counts(observations, activity)
        highlights = day_highlights(observations, activity)
        suggestions = apply_insight_states(
            action_suggestions_from_rows(settings, observations, activity, window.target),
            store.insight_states_for_type("suggestion"),
            {"status": "active"},
        )
        projects = apply_insight_states(
            project_clusters_from_rows(settings, observations, activity, window.target),
            store.insight_states_for_type("project"),
            {"status": "active"},
        )
        repairs = repair_queue_items(settings, store, target_day=window.target, limit=12)
        quick_tags = quick_tag_items(observations)
        return {
            "ok": True,
            "date": window.target.isoformat(),
            "generated_at": now(settings.timezone).isoformat(timespec="seconds"),
            "summary": {
                "observations": len(observations),
                "activity_samples": len(activity),
                "categories": categories,
                "priority_repairs": sum(1 for item in repairs if item.get("severity") in {"critical", "warn"}),
                "suggestions": len(suggestions),
                "projects": len(projects),
                "quick_tags": len(quick_tags),
                "first": min_time(observations, activity),
                "last": max_time(observations, activity),
            },
            "highlights": highlights,
            "repair_queue": repairs,
            "suggestions": suggestions,
            "projects": projects,
            "quick_tags": quick_tags,
        }
    finally:
        store.close()


def action_inbox_payload(settings: Any, params: dict[str, str]) -> dict[str, Any]:
    window = day_window(settings, params.get("date") or "today")
    store = Store(settings.db_path)
    try:
        observations = visible_observations(settings, store.observations_between(window.start_iso, window.end_iso))
        activity = list(store.activity_between(window.start_iso, window.end_iso))
        suggestions = action_suggestions_from_rows(settings, observations, activity, window.target, limit=50)
        projects = project_clusters_from_rows(settings, observations, activity, window.target, limit=24)
        repairs = repair_queue_items(settings, store, target_day=window.target, limit=80)
        quick_tags = quick_tag_items(observations)
        speakers = speaker_inbox_candidates(settings, store)
        raw_items: list[dict[str, Any]] = []
        raw_items.extend(inbox_item_from_suggestion(item) for item in suggestions)
        raw_items.extend(inbox_item_from_quick_tag(item) for item in quick_tags)
        raw_items.extend(inbox_item_from_repair(item) for item in repairs)
        raw_items.extend(inbox_item_from_project(item) for item in projects)
        raw_items.extend(inbox_item_from_speaker(item) for item in speakers)
        states = inbox_state_maps(store, raw_items)
        items = apply_inbox_states(raw_items, states, params)
        by_type_all = Counter(str(item.get("inbox_type") or "other") for item in raw_items)
        by_type = Counter(str(item.get("inbox_type") or "other") for item in items)
        by_priority = Counter(str(item.get("priority") or "low") for item in items)
        return {
            "ok": True,
            "date": window.target.isoformat(),
            "generated_at": now(settings.timezone).isoformat(timespec="seconds"),
            "summary": {
                "total": len(items),
                "all": len(raw_items),
                "high": by_priority.get("high", 0),
                "medium": by_priority.get("medium", 0),
                "low": by_priority.get("low", 0),
                "pinned": sum(1 for item in items if (item.get("state") or {}).get("pinned")),
                "ready_actions": sum(1 for item in items if item.get("action")),
                "by_type": dict(sorted(by_type.items())),
                "by_type_all": dict(sorted(by_type_all.items())),
                "state": inbox_state_summary(raw_items, states),
            },
            "items": items,
        }
    finally:
        store.close()


def repair_queue_payload(settings: Any, params: dict[str, str] | None = None) -> dict[str, Any]:
    params = params or {}
    target = parse_day(params.get("date") or "today", settings.timezone)
    store = Store(settings.db_path)
    try:
        items = repair_queue_items(settings, store, target_day=target, limit=80)
        counts = Counter(str(item.get("severity") or "info") for item in items)
        return {
            "ok": True,
            "date": target.isoformat(),
            "generated_at": now(settings.timezone).isoformat(timespec="seconds"),
            "summary": {
                "total": len(items),
                "critical": counts.get("critical", 0),
                "warn": counts.get("warn", 0),
                "info": counts.get("info", 0),
                "ready_actions": sum(1 for item in items if item.get("action")),
            },
            "items": items,
        }
    finally:
        store.close()


def action_suggestions_payload(settings: Any, params: dict[str, str]) -> dict[str, Any]:
    window = day_window(settings, params.get("date") or "today")
    store = Store(settings.db_path)
    try:
        observations = visible_observations(settings, store.observations_between(window.start_iso, window.end_iso))
        activity = list(store.activity_between(window.start_iso, window.end_iso))
        states = store.insight_states_for_type("suggestion")
        raw_suggestions = action_suggestions_from_rows(settings, observations, activity, window.target)
        suggestions = apply_insight_states(raw_suggestions, states, params)
        return {
            "ok": True,
            "date": window.target.isoformat(),
            "generated_at": now(settings.timezone).isoformat(timespec="seconds"),
            "summary": {
                "total": len(suggestions),
                "all": len(raw_suggestions),
                "high": sum(1 for item in suggestions if item["priority"] == "high"),
                "pinned": sum(1 for item in suggestions if (item.get("state") or {}).get("pinned")),
                "state": insight_state_summary(raw_suggestions, states),
            },
            "suggestions": suggestions,
        }
    finally:
        store.close()


def project_clusters_payload(settings: Any, params: dict[str, str]) -> dict[str, Any]:
    window = day_window(settings, params.get("date") or "today")
    store = Store(settings.db_path)
    try:
        observations = visible_observations(settings, store.observations_between(window.start_iso, window.end_iso))
        activity = list(store.activity_between(window.start_iso, window.end_iso))
        states = store.insight_states_for_type("project")
        raw_projects = project_clusters_from_rows(settings, observations, activity, window.target)
        projects = apply_insight_states(raw_projects, states, params)
        return {
            "ok": True,
            "date": window.target.isoformat(),
            "generated_at": now(settings.timezone).isoformat(timespec="seconds"),
            "summary": {
                "projects": len(projects),
                "all": len(raw_projects),
                "events": sum(int(project.get("event_count") or 0) for project in projects),
                "pinned": sum(1 for item in projects if (item.get("state") or {}).get("pinned")),
                "state": insight_state_summary(raw_projects, states),
            },
            "projects": projects,
        }
    finally:
        store.close()


def speaker_quality_payload(settings: Any, params: dict[str, str] | None = None) -> dict[str, Any]:
    params = params or {}
    store = Store(settings.db_path)
    try:
        rows = store.list_speakers()
        speakers = [speaker_quality_item(settings, store, row) for row in rows]
        view = str(params.get("view") or "all").strip()
        if view == "needs_work":
            speakers = [
                item
                for item in speakers
                if item.get("review_status") != "low_similarity_hidden" and (item["score"] < 75 or item["issues"])
            ]
        elif view == "ready":
            speakers = [item for item in speakers if item["score"] >= 75 and not item["issues"]]
        speakers.sort(key=lambda item: (item["score"], -len(item["issues"]), item["display_name"]))
        score_values = [item["score"] for item in speakers]
        return {
            "ok": True,
            "generated_at": now(settings.timezone).isoformat(timespec="seconds"),
            "summary": {
                "total": len(speakers),
                "needs_work": sum(1 for item in speakers if item["score"] < 75 or item["issues"]),
                "excellent": sum(1 for item in speakers if item["score"] >= 90 and not item["issues"]),
                "average_score": round(sum(score_values) / len(score_values), 1) if score_values else 0,
            },
            "speakers": speakers[:300],
        }
    finally:
        store.close()


def evidence_groups_payload(
    observations: list[dict[str, Any]],
    reports: list[dict[str, Any]],
    semantic_items: list[dict[str, Any]],
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {
        "timeline": [],
        "audio": [],
        "location": [],
        "files": [],
        "reports": [],
        "semantic": [],
        "feedback": [],
    }
    for index, item in enumerate(observations, start=1):
        source = str(item.get("source") or "")
        kind = str(item.get("kind") or "")
        category = category_for(source, kind)
        evidence = {
            "id": item.get("id") or f"obs-{index}",
            "time": item.get("observed_at") or item.get("time"),
            "source": source,
            "kind": kind,
            "title": item.get("title") or item.get("subtitle") or kind,
            "snippet": compact_text(item.get("body") or item.get("snippet") or item.get("summary"), 420),
            "location": item.get("location"),
        }
        groups["timeline"].append(evidence)
        if category in groups:
            groups[category].append(evidence)
    for index, item in enumerate(reports, start=1):
        groups["reports"].append(
            {
                "id": item.get("id") or f"report-{index}",
                "time": item.get("date") or item.get("path"),
                "source": "report",
                "kind": item.get("kind") or "report",
                "title": item.get("title") or item.get("path") or "Report",
                "snippet": compact_text(item.get("snippet") or item.get("body") or item.get("content"), 520),
                "path": item.get("path"),
            }
        )
    for index, item in enumerate(semantic_items, start=1):
        groups["semantic"].append(
            {
                "id": item.get("id") or item.get("record_key") or f"semantic-{index}",
                "time": item.get("observed_at"),
                "source": item.get("source") or "semantic",
                "kind": item.get("kind") or item.get("record_type"),
                "title": item.get("title") or item.get("record_key") or "Semantic match",
                "snippet": compact_text(item.get("text") or item.get("snippet"), 520),
                "score": item.get("score"),
            }
        )
    return {
        "counts": {key: len(value) for key, value in groups.items()},
        "groups": {key: value[:20] for key, value in groups.items() if value},
    }


def day_window(settings: Any, value: str | None) -> DayWindow:
    target = parse_day(value, settings.timezone)
    start, end = day_bounds(target, settings.timezone)
    return DayWindow(target=target, start_iso=local_iso(start), end_iso=local_iso(end))


def visible_observations(settings: Any, rows: Iterable[sqlite3.Row]) -> list[sqlite3.Row]:
    return [row for row in rows if not is_internal_observation(settings, row)]


def is_internal_observation(settings: Any, row: sqlite3.Row) -> bool:
    if str(row["source"] or "") != "filesystem":
        return False
    meta = json_dict(row["metadata"])
    raw_path = meta.get("path") or row["source_key"] or row["subtitle"] or ""
    if not raw_path:
        return False
    try:
        path = Path(str(raw_path)).expanduser().resolve()
    except OSError:
        return False
    internal_roots = [
        getattr(settings, "data_dir", None),
        getattr(settings, "log_dir", None),
        getattr(settings, "summary_dir", None),
        getattr(settings, "report_dir", None),
        getattr(settings, "recycle_bin_dir", None),
        getattr(settings, "speaker_sample_dir", None),
    ]
    for root in internal_roots:
        if root and is_relative_to(path, Path(root).expanduser().resolve()):
            return True
    return False


def category_counts(observations: list[sqlite3.Row], activity: list[sqlite3.Row]) -> dict[str, int]:
    counts: dict[str, int] = Counter()
    for row in observations:
        counts[category_for(str(row["source"] or ""), str(row["kind"] or ""))] += 1
    if activity:
        counts["app"] += len(activity)
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def category_for(source: str, kind: str) -> str:
    if kind == "audio_segment":
        return "audio"
    if kind in {"location_sample", "photo_location"}:
        return "location"
    if kind in {"bookmark", "quick_tag"}:
        return "feedback"
    if "calendar" in source or kind == "calendar_event":
        return "calendar"
    if "reminder" in source or kind == "reminder":
        return "reminder"
    if source in {"filesystem", "local_ai", "openai"} or "file" in kind or "media" in kind:
        return "files"
    if source == "messages" or "message" in kind:
        return "chat"
    if source == "feedback":
        return "feedback"
    if source == "system":
        return "system"
    return "other"


def day_highlights(observations: list[sqlite3.Row], activity: list[sqlite3.Row], limit: int = 12) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in observations:
        meta = json_dict(row["metadata"])
        analysis = meta.get("audio_analysis") if isinstance(meta.get("audio_analysis"), dict) else {}
        text = (
            analysis.get("summary")
            or row["body"]
            or row["title"]
            or row["subtitle"]
            or row["kind"]
        )
        category = category_for(str(row["source"] or ""), str(row["kind"] or ""))
        score = highlight_score(category, text, meta)
        candidates.append(
            {
                "id": f"observation:{row['id']}",
                "time": row["observed_at"],
                "category": category,
                "title": row["title"] or row["subtitle"] or row["kind"],
                "body": compact_text(text, 360),
                "source": row["source"],
                "kind": row["kind"],
                "score": score,
            }
        )
    activity_windows = activity_summary_items(activity)
    candidates.extend(activity_windows)
    candidates.sort(key=lambda item: (-float(item.get("score") or 0), str(item.get("time") or "")))
    return candidates[:limit]


def highlight_score(category: str, text: Any, meta: dict[str, Any]) -> float:
    value = 20.0
    if category in {"audio", "calendar", "reminder", "feedback"}:
        value += 30
    if category in {"files", "location"}:
        value += 15
    raw = str(text or "")
    if len(raw) > 80:
        value += 15
    if contains_action_keyword(raw):
        value += 20
    analysis = meta.get("audio_analysis") if isinstance(meta.get("audio_analysis"), dict) else {}
    if analysis.get("status") == "ok":
        value += 8
    if analysis.get("status") in {"error", "pending", "missing_file"}:
        value -= 12
    return value


def activity_summary_items(activity: list[sqlite3.Row]) -> list[dict[str, Any]]:
    if not activity:
        return []
    by_app: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in activity:
        by_app[str(row["app"] or "Unknown")].append(row)
    items = []
    for app, rows in by_app.items():
        titles = Counter(compact_text(row["window_title"], 80) for row in rows if row["window_title"])
        top_title = titles.most_common(1)[0][0] if titles else ""
        items.append(
            {
                "id": f"activity:{slug(app)}",
                "time": rows[0]["sampled_at"],
                "category": "app",
                "title": app,
                "body": top_title or f"{len(rows)} samples",
                "source": "activity",
                "kind": "foreground_app",
                "score": min(70, 25 + len(rows)),
            }
        )
    return items


def quick_tag_items(observations: list[sqlite3.Row]) -> list[dict[str, Any]]:
    items = []
    for row in observations:
        if str(row["kind"] or "") != "quick_tag":
            continue
        meta = json_dict(row["metadata"])
        items.append(
            {
                "id": row["id"],
                "time": row["observed_at"],
                "tag": meta.get("tag") or row["title"] or "tag",
                "title": row["title"] or meta.get("tag") or "Quick tag",
                "note": row["body"] or meta.get("note"),
                "source_ref": meta.get("source_ref"),
                "location": row["location"],
            }
        )
    return items


def action_suggestions_from_rows(
    settings: Any,
    observations: list[sqlite3.Row],
    activity: list[sqlite3.Row],
    target: date,
    limit: int = 24,
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in observations:
        if str(row["source"] or "") == "system" or str(row["kind"] or "") == "collector_error":
            continue
        meta = json_dict(row["metadata"])
        analysis = meta.get("audio_analysis") if isinstance(meta.get("audio_analysis"), dict) else {}
        text = "\n".join(
            str(value)
            for value in (row["title"], row["subtitle"], row["body"], analysis.get("summary"), analysis.get("transcript"))
            if value
        )
        for sentence in action_sentences(text):
            key = content_key(sentence)
            if key in seen:
                continue
            seen.add(key)
            priority = suggestion_priority(sentence, row)
            suggestions.append(
                {
                    "id": f"suggestion:{row['id']}:{stable_short_key(sentence)}",
                    "priority": priority,
                    "title": suggestion_title(sentence),
                    "body": compact_text(sentence, 420),
                    "reason": suggestion_reason(sentence, row),
                    "source": row["source"],
                    "kind": row["kind"],
                    "category": category_for(str(row["source"] or ""), str(row["kind"] or "")),
                    "observed_at": row["observed_at"],
                    "evidence_ref": f"observation:{row['id']}",
                    "evidence": [
                        {
                            "id": f"observation:{row['id']}",
                            "time": row["observed_at"],
                            "title": row["title"] or row["subtitle"] or row["kind"],
                            "snippet": compact_text(text, 360),
                            "source": row["source"],
                            "kind": row["kind"],
                            "category": category_for(str(row["source"] or ""), str(row["kind"] or "")),
                        }
                    ],
                    "recommended_action": recommended_action(sentence),
                    "metadata": {"date": target.isoformat()},
                }
            )
    for item in suggestions:
        item["score"] = {"high": 3, "medium": 2, "low": 1}.get(item["priority"], 1)
    suggestions.sort(key=lambda item: (-item["score"], str(item["observed_at"]), item["title"]))
    return suggestions[:limit]


def action_sentences(text: str) -> list[str]:
    if not text.strip():
        return []
    raw_parts = re.split(r"[\n。！？!?；;]+", text)
    result = []
    for part in raw_parts:
        sentence = " ".join(part.strip().split())
        if len(sentence) < 6:
            continue
        if contains_action_keyword(sentence):
            result.append(sentence)
    return result[:8]


def contains_action_keyword(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in ACTION_KEYWORDS)


def suggestion_priority(sentence: str, row: sqlite3.Row) -> str:
    lowered = sentence.lower()
    if any(term in lowered for term in ("deadline", "due", "截止", "明天", "today", "urgent", "紧急")):
        return "high"
    if str(row["kind"] or "") in {"calendar_event", "reminder", "bookmark", "quick_tag"}:
        return "high"
    if any(term in lowered for term in ("follow up", "reply", "回复", "确认", "联系")):
        return "medium"
    return "low"


def suggestion_title(sentence: str) -> str:
    text = compact_text(sentence, 80)
    for prefix in ("todo:", "action item:", "待办：", "需要", "要"):
        if text.lower().startswith(prefix.lower()):
            return text
    return text


def suggestion_reason(sentence: str, row: sqlite3.Row) -> str:
    category = category_for(str(row["source"] or ""), str(row["kind"] or ""))
    if category == "audio":
        return "从录音转写或摘要中检测到行动语句"
    if category == "feedback":
        return "来自你手动标注的重点"
    if category in {"calendar", "reminder"}:
        return "来自日程/提醒事项记录"
    return "从本地记录中检测到行动语句"


def recommended_action(sentence: str) -> dict[str, Any]:
    lowered = sentence.lower()
    if any(term in lowered for term in ("email", "发邮件", "邮件")):
        return {"kind": "draft_email", "label": "准备邮件"}
    if any(term in lowered for term in ("remind", "提醒", "deadline", "due", "截止")):
        return {"kind": "create_reminder", "label": "创建提醒"}
    if any(term in lowered for term in ("reply", "回复")):
        return {"kind": "reply", "label": "准备回复"}
    return {"kind": "review", "label": "稍后处理"}


def project_clusters_from_rows(
    settings: Any,
    observations: list[sqlite3.Row],
    activity: list[sqlite3.Row],
    target: date,
    limit: int = 12,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for row in observations:
        text = " ".join(str(value) for value in (row["title"], row["subtitle"], row["body"], row["app"], row["actor"], row["location"]) if value)
        tokens = topic_tokens(text)
        if not tokens:
            continue
        events.append(
            {
                "id": f"observation:{row['id']}",
                "time": row["observed_at"],
                "title": row["title"] or row["subtitle"] or row["kind"],
                "snippet": compact_text(row["body"], 240),
                "category": category_for(str(row["source"] or ""), str(row["kind"] or "")),
                "tokens": tokens,
                "source": row["source"],
                "kind": row["kind"],
            }
        )
    for item in activity_summary_items(activity):
        text = " ".join(str(value) for value in (item.get("title"), item.get("body")) if value)
        tokens = topic_tokens(text)
        if not tokens:
            continue
        events.append(
            {
                "id": str(item["id"]),
                "time": item["time"],
                "title": item["title"],
                "snippet": compact_text(item["body"], 200),
                "category": "app",
                "tokens": tokens,
                "source": "activity",
                "kind": "foreground_app",
            }
        )
    clusters: list[dict[str, Any]] = []
    for event in events:
        best_index = None
        best_score = 0.0
        event_tokens = set(event["tokens"])
        for index, cluster in enumerate(clusters):
            cluster_tokens = set(cluster["_tokens"])
            score = len(event_tokens & cluster_tokens) / max(1, math.sqrt(len(event_tokens) * len(cluster_tokens)))
            if score > best_score:
                best_index = index
                best_score = score
        if best_index is not None and best_score >= 0.34:
            clusters[best_index]["events"].append(event)
            clusters[best_index]["_tokens"].extend(event["tokens"])
        else:
            clusters.append({"events": [event], "_tokens": list(event["tokens"])})
    projects = []
    for index, cluster in enumerate(clusters, start=1):
        cluster_events = sorted(cluster["events"], key=lambda item: str(item["time"] or ""))
        token_counts = Counter(cluster["_tokens"])
        top_tokens = [token for token, _count in token_counts.most_common(5)]
        categories = Counter(event["category"] for event in cluster_events)
        if len(cluster_events) < 2 and categories.most_common(1)[0][0] not in {"calendar", "audio", "files", "feedback"}:
            continue
        project_key = "|".join(top_tokens) + "|" + "|".join(str(event["id"]) for event in cluster_events[:8])
        projects.append(
            {
                "id": f"project:{target.isoformat()}:{stable_short_key(project_key)}",
                "title": project_title(top_tokens, cluster_events),
                "summary": project_summary(cluster_events, top_tokens),
                "confidence": project_confidence(cluster_events, top_tokens),
                "event_count": len(cluster_events),
                "categories": dict(categories),
                "time_span": {"start": cluster_events[0]["time"], "end": cluster_events[-1]["time"]},
                "keywords": top_tokens,
                "evidence": [{key: event[key] for key in ("id", "time", "title", "snippet", "category", "source", "kind")} for event in cluster_events[:12]],
                "next_actions": cluster_next_actions(cluster_events),
            }
        )
    projects.sort(key=lambda item: (-int(item["event_count"]), -float(item["confidence"]), item["title"]))
    return projects[:limit]


def apply_insight_states(
    items: list[dict[str, Any]],
    states: dict[str, sqlite3.Row],
    params: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    params = params or {}
    enriched: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        copy = dict(item)
        copy["state"] = insight_state_for(copy["id"], states)
        copy["_order"] = index
        if insight_matches_filters(copy, params):
            enriched.append(copy)
    enriched.sort(key=lambda item: (not bool((item.get("state") or {}).get("pinned")), insight_status_rank(item), int(item.get("_order") or 0)))
    for item in enriched:
        item.pop("_order", None)
    return enriched


def speaker_inbox_candidates(settings: Any, store: Store, limit: int = 12) -> list[dict[str, Any]]:
    speakers = [speaker_quality_item(settings, store, row) for row in store.list_speakers()]
    items = [
        item
        for item in speakers
        if item.get("review_status") != "low_similarity_hidden" and (int(item.get("score") or 0) < 75 or item.get("issues"))
    ]
    items.sort(key=lambda item: (int(item.get("score") or 100), -len(item.get("issues") or []), str(item.get("display_name") or "")))
    return items[:limit]


def inbox_item_from_suggestion(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "item_type": "suggestion",
        "inbox_type": "suggestion",
        "priority": item.get("priority") or "low",
        "title": item.get("title") or "行动建议",
        "body": item.get("body") or "",
        "reason": item.get("reason") or "从本地记录中检测到行动语句",
        "time": item.get("observed_at"),
        "source": item.get("source"),
        "kind": item.get("kind"),
        "category": item.get("category") or "other",
        "evidence": item.get("evidence") or [],
        "action": None,
        "recommended_action": item.get("recommended_action"),
        "source_item": item,
    }


def inbox_item_from_quick_tag(item: dict[str, Any]) -> dict[str, Any]:
    tag = str(item.get("tag") or item.get("title") or "tag")
    lowered = tag.lower()
    priority = "high" if any(term in lowered for term in ("todo", "important", "urgent", "待办", "重要", "紧急")) else "medium"
    return {
        "id": f"quick_tag:{item.get('id')}",
        "item_type": "quick_tag",
        "inbox_type": "quick_tag",
        "priority": priority,
        "title": item.get("title") or f"Quick tag: {tag}",
        "body": item.get("note") or "来自手机端快速标注",
        "reason": "来自你在移动端打的快速标注",
        "time": item.get("time"),
        "source": "mobile",
        "kind": "quick_tag",
        "category": "feedback",
        "evidence": [
            {
                "id": item.get("source_ref") or item.get("id"),
                "time": item.get("time"),
                "title": item.get("title") or tag,
                "snippet": item.get("note") or "",
                "source": "mobile",
                "kind": "quick_tag",
                "category": "feedback",
            }
        ],
        "action": None,
        "recommended_action": {"kind": "review", "label": "处理标注"},
        "source_item": item,
    }


def inbox_item_from_repair(item: dict[str, Any]) -> dict[str, Any]:
    severity = str(item.get("severity") or "info")
    priority = {"critical": "high", "warn": "medium", "info": "low"}.get(severity, "low")
    return {
        "id": f"repair:{item.get('id')}",
        "item_type": "repair",
        "inbox_type": "repair",
        "priority": priority,
        "severity": severity,
        "title": item.get("title") or item.get("id") or "待修复项",
        "body": item.get("body") or "",
        "reason": f"{item.get('area') or 'system'} repair",
        "time": None,
        "source": item.get("area") or "system",
        "kind": "repair",
        "category": item.get("area") or "system",
        "evidence": item.get("evidence") or [],
        "action": item.get("action"),
        "recommended_action": {"kind": "repair", "label": (item.get("action") or {}).get("label") or "检查修复"},
        "source_item": item,
    }


def inbox_item_from_project(item: dict[str, Any]) -> dict[str, Any]:
    next_actions = item.get("next_actions") or []
    priority = "medium" if next_actions or int(item.get("event_count") or 0) >= 3 else "low"
    span = item.get("time_span") if isinstance(item.get("time_span"), dict) else {}
    return {
        "id": item["id"],
        "item_type": "project",
        "inbox_type": "project",
        "priority": priority,
        "title": item.get("title") or "项目 / 主题",
        "body": item.get("summary") or "",
        "reason": f"{item.get('event_count') or 0} 条记录聚成一个主题",
        "time": span.get("end") or span.get("start"),
        "source": "project",
        "kind": "project_cluster",
        "category": "project",
        "categories": item.get("categories") or {},
        "evidence": item.get("evidence") or [],
        "action": None,
        "recommended_action": {"kind": "review_project", "label": "打开项目"},
        "next_actions": next_actions,
        "source_item": item,
    }


def inbox_item_from_speaker(item: dict[str, Any]) -> dict[str, Any]:
    recommendations = item.get("recommendations") or []
    action = None
    if recommendations:
        first = recommendations[0]
        action = {"name": first.get("action"), "args": first.get("args") or {}, "label": first.get("label") or "处理"}
    score = int(item.get("score") or 0)
    priority = "high" if score < 55 else "medium"
    issues = item.get("issues") or []
    return {
        "id": f"speaker:{item.get('id')}",
        "item_type": "speaker",
        "inbox_type": "speaker",
        "priority": priority,
        "title": f"说话人待确认：{item.get('display_name') or item.get('id')}",
        "body": "、".join(str(issue.get("label") or issue.get("kind")) for issue in issues) or "需要复查说话人证据",
        "reason": f"speaker quality {score}",
        "time": item.get("latest_sample_at") or item.get("latest_seen_at") or item.get("first_seen_at"),
        "source": "speakers",
        "kind": "speaker_quality",
        "category": "speakers",
        "evidence": (item.get("evidence") or {}).get("samples") or [],
        "action": action,
        "recommended_action": {"kind": "speaker_review", "label": (action or {}).get("label") or "打开说话人"},
        "source_item": item,
    }


def inbox_state_maps(store: Store, items: list[dict[str, Any]]) -> dict[str, dict[str, sqlite3.Row]]:
    item_types = sorted({str(item.get("item_type") or "") for item in items if item.get("item_type")})
    return {item_type: store.insight_states_for_type(item_type) for item_type in item_types}


def apply_inbox_states(
    items: list[dict[str, Any]],
    states_by_type: dict[str, dict[str, sqlite3.Row]],
    params: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    params = params or {}
    type_filter = str(params.get("type") or params.get("inbox_type") or "all").strip()
    enriched: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        copy = dict(item)
        item_type = str(copy.get("item_type") or "")
        copy["state"] = insight_state_for(copy["id"], states_by_type.get(item_type, {}))
        copy["_order"] = index
        if type_filter and type_filter != "all" and type_filter not in {str(copy.get("inbox_type") or ""), item_type}:
            continue
        if insight_matches_filters(copy, params):
            enriched.append(copy)
    enriched.sort(key=inbox_sort_key)
    for item in enriched:
        item.pop("_order", None)
    return enriched


def inbox_state_summary(items: list[dict[str, Any]], states_by_type: dict[str, dict[str, sqlite3.Row]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    pinned = 0
    for item in items:
        item_type = str(item.get("item_type") or "")
        state = insight_state_for(str(item.get("id") or ""), states_by_type.get(item_type, {}))
        counts[str(state.get("status") or "open")] += 1
        if state.get("pinned"):
            pinned += 1
    result = {key: int(value) for key, value in sorted(counts.items())}
    result.setdefault("open", 0)
    result["active"] = sum(value for key, value in result.items() if key not in {"done", "archived", "dismissed", "pinned"})
    result["pinned"] = pinned
    return result


def inbox_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    state = item.get("state") or {}
    timestamp = parse_iso(item.get("time"))
    return (
        not bool(state.get("pinned")),
        insight_status_rank(item),
        -inbox_priority_value(item),
        -(timestamp.timestamp() if timestamp else 0),
        int(item.get("_order") or 0),
        str(item.get("title") or ""),
    )


def inbox_priority_value(item: dict[str, Any]) -> int:
    priority = str(item.get("priority") or "")
    severity = str(item.get("severity") or "")
    if priority == "high" or severity == "critical":
        return 3
    if priority == "medium" or severity == "warn":
        return 2
    return 1


def insight_state_for(item_id: str, states: dict[str, sqlite3.Row]) -> dict[str, Any]:
    row = states.get(str(item_id))
    if row is None:
        return {"status": "open", "pinned": False, "note": "", "updated_at": None}
    return {
        "status": row["status"] or "open",
        "pinned": bool(row["pinned"]),
        "note": row["note"] or "",
        "updated_at": row["updated_at"],
        "metadata": json_dict(row["metadata"]),
    }


def insight_matches_filters(item: dict[str, Any], params: dict[str, str]) -> bool:
    status_filter = str(params.get("status") or "active").strip()
    state = item.get("state") or {}
    item_status = str(state.get("status") or "open")
    if status_filter == "active":
        if item_status in {"done", "archived", "dismissed"}:
            return False
    elif status_filter and status_filter != "all" and item_status != status_filter:
        return False
    if str(params.get("pinned") or "").lower() in {"1", "true", "yes"} and not state.get("pinned"):
        return False
    priority = str(params.get("priority") or "").strip()
    if priority and priority != "all" and str(item.get("priority") or "") != priority:
        return False
    source = str(params.get("source") or "").strip()
    if source and source != "all":
        categories = item.get("categories") if isinstance(item.get("categories"), dict) else {}
        source_values = {str(item.get("source") or ""), str(item.get("category") or ""), *[str(key) for key in categories.keys()]}
        if source not in source_values:
            return False
    q = str(params.get("q") or "").strip().lower()
    if q and q not in insight_search_text(item):
        return False
    return True


def insight_search_text(item: dict[str, Any]) -> str:
    values: list[str] = []
    for key in ("id", "title", "body", "summary", "reason", "source", "kind", "priority"):
        values.append(str(item.get(key) or ""))
    values.extend(str(keyword) for keyword in item.get("keywords") or [])
    for evidence in item.get("evidence") or []:
        if isinstance(evidence, dict):
            values.extend(str(evidence.get(key) or "") for key in ("title", "snippet", "source", "kind", "category"))
    for action in item.get("next_actions") or []:
        if isinstance(action, dict):
            values.extend(str(action.get(key) or "") for key in ("title", "kind", "source_ref"))
    state = item.get("state") or {}
    values.append(str(state.get("note") or ""))
    return " ".join(values).lower()


def insight_state_summary(items: list[dict[str, Any]], states: dict[str, sqlite3.Row]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    pinned = 0
    for item in items:
        state = insight_state_for(str(item.get("id") or ""), states)
        counts[str(state.get("status") or "open")] += 1
        if state.get("pinned"):
            pinned += 1
    result = {key: int(value) for key, value in sorted(counts.items())}
    result.setdefault("open", 0)
    result["active"] = sum(value for key, value in result.items() if key not in {"done", "archived", "dismissed", "pinned"})
    result["pinned"] = pinned
    return result


def insight_status_rank(item: dict[str, Any]) -> int:
    status = str((item.get("state") or {}).get("status") or "open")
    return {"open": 0, "snoozed": 1, "done": 2, "archived": 3, "dismissed": 4}.get(status, 9)


def repair_queue_items(settings: Any, store: Store, *, target_day: date, limit: int = 80) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    items.extend(collector_error_repairs(store))
    items.extend(stale_run_repairs(store))
    items.extend(audio_repairs(settings, store, target_day))
    items.extend(speaker_repairs(store))
    items.extend(search_repairs(store))
    items.extend(mobile_sync_repairs(settings))
    items.extend(file_analysis_repairs(settings))
    items.sort(key=lambda item: (severity_rank(item.get("severity")), area_rank(item.get("area")), str(item.get("id"))))
    return items[:limit]


def collector_error_repairs(store: Store) -> list[dict[str, Any]]:
    rows = store.conn.execute(
        """
        SELECT *
        FROM observations
        WHERE source = 'system'
          AND kind = 'collector_error'
        ORDER BY observed_at DESC
        LIMIT 20
        """
    ).fetchall()
    items = []
    for row in rows:
        collector = str(row["source_key"] or "").split(":", 1)[0] or "collector"
        items.append(
            repair_item(
                f"collector:{row['id']}",
                "warn",
                "sources",
                f"{collector} 采集失败",
                compact_text(row["body"] or row["title"], 420),
                evidence=[{"time": row["observed_at"], "title": row["title"], "body": compact_text(row["body"], 240)}],
                action={"name": "collect", "args": {"date": "today", "no_report": True}, "label": "重新采集"},
            )
        )
    return items


def stale_run_repairs(store: Store) -> list[dict[str, Any]]:
    cutoff = now("Asia/Tokyo") - timedelta(seconds=3600)
    rows = store.conn.execute(
        """
        SELECT *
        FROM collector_runs
        WHERE status = 'running'
        ORDER BY started_at ASC
        LIMIT 20
        """
    ).fetchall()
    items = []
    for row in rows:
        started = parse_iso(row["started_at"])
        if started and started > cutoff.astimezone(started.tzinfo):
            continue
        items.append(
            repair_item(
                f"stale-run:{row['id']}",
                "warn",
                "runtime",
                f"{row['collector']} 运行记录疑似卡住",
                f"Started at {row['started_at']} but never finished.",
                evidence=[{"time": row["started_at"], "status": row["status"], "message": row["message"]}],
                action={"name": "install_agent", "args": {"load": True}, "label": "重载后台 Agent"},
            )
        )
    return items


def audio_repairs(settings: Any, store: Store, target_day: date) -> list[dict[str, Any]]:
    start, end = day_bounds(target_day, settings.timezone)
    rows = store.mobile_audio_between(local_iso(start), local_iso(end))
    pending = []
    errors = []
    missing = []
    speaker_skipped = []
    for row in rows:
        meta = json_dict(row["metadata"])
        analysis = meta.get("audio_analysis") if isinstance(meta.get("audio_analysis"), dict) else {}
        status = str(analysis.get("status") or "pending")
        transcript_status = str(analysis.get("transcript_status") or "")
        speaker_status = str((analysis.get("speaker_processing") or {}).get("status") or "")
        if status in {"pending", "processing"}:
            pending.append(row)
        if status == "missing_file":
            missing.append(row)
        if status == "error" or transcript_status == "transcription_error":
            errors.append(row)
        if speaker_status == "skipped_no_speaker_labels":
            speaker_skipped.append(row)
    items = []
    if errors:
        items.append(
            repair_item(
                "audio:errors",
                "critical",
                "audio",
                f"{len(errors)} 条今日录音转写失败",
                "这些条目不会进入可靠摘要，需要检查模型/音频文件后重跑。",
                evidence=audio_evidence(errors[:5]),
                action={"name": "analyze_audio", "args": {"date": target_day.isoformat(), "limit": min(20, len(errors))}, "label": "重跑失败录音"},
            )
        )
    if missing:
        items.append(
            repair_item(
                "audio:missing",
                "warn",
                "audio",
                f"{len(missing)} 条录音缺少原始文件",
                "数据库里有记录，但对应媒体文件不可用。",
                evidence=audio_evidence(missing[:5]),
            )
        )
    if pending:
        items.append(
            repair_item(
                "audio:pending",
                "warn",
                "audio",
                f"{len(pending)} 条今日录音待分析",
                "处理后才会进入今天行动中心、speaker review 和搜索。",
                evidence=audio_evidence(pending[:5]),
                action={"name": "analyze_audio", "args": {"date": target_day.isoformat(), "limit": min(20, len(pending))}, "label": "分析今日录音"},
            )
        )
    if speaker_skipped:
        items.append(
            repair_item(
                "audio:speaker-skipped",
                "info",
                "speakers",
                f"{len(speaker_skipped)} 条录音缺少说话人标签",
                "正文可用，但 speaker 证据需要更好的 diarization 后修复。",
                evidence=audio_evidence(speaker_skipped[:5]),
                action={"name": "analyze_audio", "args": {"date": target_day.isoformat(), "limit": min(20, len(speaker_skipped))}, "label": "重试 speaker 处理"},
            )
        )
    return items


def speaker_repairs(store: Store) -> list[dict[str, Any]]:
    rows = store.list_speakers()
    pending = []
    low_sample = []
    hidden = []
    for row in rows:
        sample_count = int(row["sample_count"] or 0)
        status = str(row["identity_status"] or "")
        if status in {"auto_merged_pending_review", "ready_to_name", "needs_review", "provisional"}:
            pending.append(row)
        if sample_count < 2:
            low_sample.append(row)
        if status == "low_similarity_hidden":
            hidden.append(row)
    items = []
    if pending:
        items.append(
            repair_item(
                "speakers:pending",
                "warn",
                "speakers",
                f"{len(pending)} 个说话人需要确认/命名",
                "这些声音会影响按人回顾和 speaker 证据质量。",
                evidence=speaker_evidence(pending[:6]),
                action={"name": "speaker_auto_organize", "args": {"threshold": 0.68}, "label": "自动整理后复查"},
            )
        )
    if low_sample:
        items.append(
            repair_item(
                "speakers:low-sample",
                "info",
                "speakers",
                f"{len(low_sample)} 个说话人样本不足",
                "样本少时声纹稳定性较低，建议补样本或合并重复项。",
                evidence=speaker_evidence(low_sample[:6]),
                action={"name": "speaker_refresh_sample_confidence", "args": {}, "label": "刷新样本置信度"},
            )
        )
    if hidden:
        items.append(
            repair_item(
                "speakers:hidden",
                "info",
                "speakers",
                f"{len(hidden)} 个低相似 Voice 已隐藏",
                "它们不会污染主列表，但仍可在 speaker queue 里复查。",
                evidence=speaker_evidence(hidden[:6]),
            )
        )
    return items


def search_repairs(store: Store) -> list[dict[str, Any]]:
    if not table_exists(store.conn, "search_embeddings"):
        return [
            repair_item(
                "search:no-index",
                "warn",
                "search",
                "语义搜索索引还没有建立",
                "搜索问答会降级到关键词证据，建议建立本地 embedding 索引。",
                action={"name": "search_index", "args": {"limit": 5000}, "label": "建立语义索引"},
            )
        ]
    count = int(scalar(store.conn, "SELECT count(*) FROM search_embeddings") or 0)
    if count == 0:
        return [
            repair_item(
                "search:empty-index",
                "warn",
                "search",
                "语义搜索索引为空",
                "问答无法使用语义相似证据。",
                action={"name": "search_index", "args": {"limit": 5000}, "label": "建立语义索引"},
            )
        ]
    return []


def mobile_sync_repairs(settings: Any) -> list[dict[str, Any]]:
    items = []
    inbox = Path(settings.data_dir) / "mobile_sync" / "inbox"
    pending_files = safe_count_files(inbox)
    if pending_files:
        items.append(
            repair_item(
                "sync:pending-inbox",
                "warn",
                "sync",
                f"{pending_files} 个手机上传包还在 inbox",
                "上传包已落盘但还需要导入/清理。",
                action={"name": "mobile_cleanup", "args": {}, "label": "预览同步缓存"},
            )
        )
    health = sync_health(settings)
    if health.get("error"):
        items.append(
            repair_item(
                "sync:offline",
                "warn",
                "sync",
                "手机同步服务不可达",
                str(health.get("error")),
                evidence=[health],
                action={"name": "install_sync_agent", "args": {"load": True}, "label": "重载同步服务"},
            )
        )
    return items


def file_analysis_repairs(settings: Any) -> list[dict[str, Any]]:
    state_path = Path(settings.data_dir) / "file_analysis_state.json"
    state = json_file(state_path)
    failed = state.get("failed_keys") if isinstance(state.get("failed_keys"), dict) else {}
    if not failed:
        return []
    return [
        repair_item(
            "files:failed-analysis",
            "warn",
            "files",
            f"{len(failed)} 个文件分析失败项在退避等待",
            "这些文件暂时不会重试，直到 retry_after_seconds 到期。",
            evidence=[{"path": key, "error": value.get("error")} for key, value in list(failed.items())[:6] if isinstance(value, dict)],
            action={"name": "analyze_new_files", "args": {}, "label": "扫描新文件"},
        )
    ]


def speaker_quality_item(settings: Any, store: Store, row: sqlite3.Row) -> dict[str, Any]:
    speaker_id = int(row["id"])
    stats = store.speaker_sample_evidence_stats(speaker_id)
    samples = store.list_speaker_samples(speaker_id)
    embedding_count = int(scalar(store.conn, "SELECT count(*) FROM speaker_embeddings WHERE speaker_id = ?", (speaker_id,)) or 0)
    sample_count = int(stats["sample_count"] or 0)
    day_count = int(stats["day_count"] or 0)
    observation_count = int(stats["observation_count"] or 0)
    confidence = row["confidence"]
    review_status = speaker_review_status(row)
    issues: list[dict[str, str]] = []
    recommendations: list[dict[str, Any]] = []
    score = 30
    score += min(25, sample_count * 5)
    score += min(15, day_count * 5)
    score += min(10, observation_count * 2)
    score += min(10, embedding_count * 2)
    if confidence is not None:
        score += max(0, min(10, int(float(confidence) * 10)))
    status = str(row["identity_status"] or "provisional")
    if status in {"named", "confirmed", "accepted"} or review_status == "confirmed":
        score += 10
    if speaker_display_name_is_auto(row["display_name"]):
        score -= 8
        issues.append({"kind": "auto_name", "label": "尚未人工命名"})
    if sample_count < 2:
        score -= 18
        issues.append({"kind": "low_sample_count", "label": "样本不足"})
    if embedding_count < max(1, sample_count):
        score -= 8
        issues.append({"kind": "missing_embeddings", "label": "部分样本缺少 embedding"})
        recommendations.append({"action": "speaker_refresh_sample_confidence", "label": "刷新样本置信度", "args": {"speaker_ids": [speaker_id]}})
    if review_status != "low_similarity_hidden" and (
        status in {"auto_merged_pending_review", "needs_review", "ready_to_name", "provisional"}
        or review_status in {"auto_merged_pending_review", "needs_review"}
    ):
        score -= 10
        issues.append({"kind": "needs_review", "label": "需要人工确认"})
        recommendations.append({"action": "speaker_confirm", "label": "确认整理结果", "args": {"speaker_ids": [speaker_id]}})
    if status == "low_similarity_hidden" or review_status == "low_similarity_hidden":
        score -= 16
        issues.append({"kind": "hidden_low_similarity", "label": "低相似隐藏"})
        recommendations.append({"action": "speaker_unhide", "label": "放回复查列表", "args": {"speaker_ids": [speaker_id]}})
    sample_confidences = sample_confidence_values(samples)
    if sample_confidences:
        average_sample_confidence = sum(sample_confidences) / len(sample_confidences)
        if average_sample_confidence < 0.55 and review_status != "confirmed":
            score -= 12
            issues.append({"kind": "low_sample_confidence", "label": "样本与聚类中心相似度偏低"})
    else:
        average_sample_confidence = None
    score = max(0, min(100, score))
    return {
        "id": speaker_id,
        "display_name": row["display_name"],
        "identity_status": status,
        "review_status": review_status,
        "score": score,
        "grade": quality_grade(score),
        "confidence": confidence,
        "sample_count": sample_count,
        "embedding_count": embedding_count,
        "observation_count": observation_count,
        "day_count": day_count,
        "first_seen_at": stats["first_seen_at"],
        "latest_seen_at": stats["latest_seen_at"],
        "latest_sample_at": row["latest_sample_at"],
        "average_sample_confidence": round(average_sample_confidence, 3) if average_sample_confidence is not None else None,
        "issues": issues,
        "recommendations": dedupe_recommendations(recommendations),
        "evidence": {
            "samples": [
                {
                    "id": sample["id"],
                    "created_at": sample["created_at"],
                    "transcript": compact_text(sample["transcript"], 160),
                    "has_audio": bool(sample["sample_path"]),
                }
                for sample in samples[:6]
            ]
        },
    }


def repair_item(
    item_id: str,
    severity: str,
    area: str,
    title: str,
    body: str,
    *,
    evidence: list[dict[str, Any]] | None = None,
    action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "severity": severity,
        "area": area,
        "title": title,
        "body": body,
        "evidence": evidence or [],
        "action": action,
    }


def audio_evidence(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    evidence = []
    for row in rows:
        meta = json_dict(row["metadata"])
        analysis = meta.get("audio_analysis") if isinstance(meta.get("audio_analysis"), dict) else {}
        evidence.append(
            {
                "id": row["id"],
                "time": row["observed_at"],
                "title": row["title"],
                "status": analysis.get("status") or "pending",
                "error": compact_text(analysis.get("error") or analysis.get("transcription_error"), 240),
            }
        )
    return evidence


def speaker_evidence(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [
        {
            "id": int(row["id"]),
            "title": row["display_name"],
            "status": row["identity_status"],
            "sample_count": int(row["sample_count"] or 0),
            "latest_sample_at": row["latest_sample_at"],
        }
        for row in rows
    ]


def project_title(tokens: list[str], events: list[dict[str, Any]]) -> str:
    if tokens:
        return " / ".join(tokens[:3])
    return str(events[0].get("title") or "未命名项目")


def project_summary(events: list[dict[str, Any]], tokens: list[str]) -> str:
    categories = Counter(event["category"] for event in events)
    top_category = categories.most_common(1)[0][0] if categories else "event"
    return f"{len(events)} 条记录围绕 {', '.join(tokens[:4]) or top_category}，主要来自 {top_category}。"


def project_confidence(events: list[dict[str, Any]], tokens: list[str]) -> float:
    category_bonus = len(set(event["category"] for event in events)) * 0.08
    count_bonus = min(0.45, len(events) * 0.08)
    keyword_bonus = min(0.25, len(tokens) * 0.05)
    return round(min(0.98, 0.25 + category_bonus + count_bonus + keyword_bonus), 2)


def cluster_next_actions(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions = []
    for event in events:
        for sentence in action_sentences(" ".join(str(event.get(key) or "") for key in ("title", "snippet"))):
            actions.append({"title": suggestion_title(sentence), "source_ref": event["id"], "kind": recommended_action(sentence)["kind"]})
            if len(actions) >= 3:
                return actions
    return actions


def topic_tokens(text: str) -> list[str]:
    if not text.strip():
        return []
    latin = re.findall(r"[A-Za-z][A-Za-z0-9_+#.-]{2,}", text.lower())
    cjk = re.findall(r"[\u3040-\u30ff\u3400-\u9fff]{2,}", text)
    tokens = [token.strip("._-").lower() for token in latin + cjk]
    cleaned = []
    for token in tokens:
        if len(token) < 2 or token in STOP_WORDS:
            continue
        if token.isdigit():
            continue
        cleaned.append(token[:32])
    return cleaned[:16]


def min_time(observations: list[sqlite3.Row], activity: list[sqlite3.Row]) -> str | None:
    values = [str(row["observed_at"]) for row in observations if row["observed_at"]]
    values.extend(str(row["sampled_at"]) for row in activity if row["sampled_at"])
    return min(values) if values else None


def max_time(observations: list[sqlite3.Row], activity: list[sqlite3.Row]) -> str | None:
    values = [str(row["observed_at"]) for row in observations if row["observed_at"]]
    values.extend(str(row["sampled_at"]) for row in activity if row["sampled_at"])
    return max(values) if values else None


def severity_rank(value: Any) -> int:
    return {"critical": 0, "warn": 1, "info": 2, "ok": 3}.get(str(value), 4)


def area_rank(value: Any) -> int:
    return {"runtime": 0, "sources": 1, "sync": 2, "audio": 3, "speakers": 4, "search": 5, "files": 6}.get(str(value), 9)


def sample_confidence_values(samples: list[sqlite3.Row]) -> list[float]:
    values = []
    for sample in samples:
        meta = json_dict(sample["metadata"])
        for key in ("sample_confidence", "cluster_confidence", "confidence", "similarity"):
            raw = meta.get(key)
            if isinstance(raw, (int, float)):
                values.append(float(raw))
                break
    return values


def quality_grade(score: int) -> str:
    if score >= 90:
        return "excellent"
    if score >= 75:
        return "good"
    if score >= 55:
        return "needs_work"
    return "weak"


def dedupe_recommendations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for item in items:
        key = (item.get("action"), item.get("label"))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def compact_text(value: Any, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def content_key(value: str) -> str:
    return re.sub(r"\W+", "", value.lower())[:120]


def stable_short_key(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8", "ignore")).hexdigest()[:12]


def slug(value: str) -> str:
    raw = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return raw or "item"


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table,)).fetchone()
    return row is not None


def scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def json_file(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
    except (OSError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def safe_count_files(path: Path) -> int:
    try:
        return sum(1 for item in path.iterdir() if item.is_file())
    except OSError:
        return 0


def sync_health(settings: Any) -> dict[str, Any]:
    cfg = getattr(settings, "mobile_sync", {}) or {}
    port = int(cfg.get("port") or 8765)
    url = f"http://127.0.0.1:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=1.5) as response:
            raw = response.read().decode("utf-8", errors="replace")
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {"ok": False, "error": "non_object_response", "url": url}
    except (OSError, urllib.error.URLError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "url": url}


def parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
