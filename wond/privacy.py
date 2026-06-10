from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Settings
from .dashboard_shared import dir_size, redact_config, scalar
from .recycle_bin import purge_recycle_bin, recycle_bin_summary
from .retention import run_retention
from .store import Store
from .sync_server import cleanup_mobile_sync_storage
from .timeutil import now


SENSITIVE_SOURCE_ROWS: list[dict[str, Any]] = [
    {
        "id": "messages",
        "source": "messages",
        "kind": "message",
        "setting": "collectors.messages",
        "label": "Messages",
        "sensitivity": "high",
        "note": "Stores message text in the title field plus sender metadata.",
    },
    {
        "id": "apple_mail",
        "source": "apple_mail",
        "kind": "email",
        "setting": "collectors.apple_mail",
        "label": "Apple Mail",
        "sensitivity": "high",
        "note": "Stores subject, sender, recipients, and a body preview.",
    },
    {
        "id": "browser",
        "source": "browser",
        "kind": "web_visit",
        "setting": "collectors.browsers",
        "label": "Browser history",
        "sensitivity": "high",
        "note": "Stores visited page titles and URLs from enabled browser profiles.",
    },
    {
        "id": "photos",
        "source": "photos",
        "kind": "photo_location",
        "setting": "collectors.photo_locations",
        "label": "Photo locations",
        "sensitivity": "high",
        "note": "Stores photo location samples when Photos access is available.",
    },
    {
        "id": "mobile_audio",
        "source": "mobile",
        "kind": "audio_segment",
        "setting": "audio_analysis.enabled",
        "label": "Mobile audio",
        "sensitivity": "high",
        "note": "Stores imported audio metadata, transcripts, summaries, and speaker clues.",
    },
    {
        "id": "mobile_location",
        "source": "mobile",
        "kind": "location_sample",
        "setting": "",
        "label": "Mobile location",
        "sensitivity": "high",
        "note": "Stores location samples sent by the mobile capture app.",
    },
    {
        "id": "filesystem",
        "source": "filesystem",
        "kind": "file_modified",
        "setting": "collectors.recent_files",
        "label": "Recent files",
        "sensitivity": "medium",
        "note": "Stores file path and modified-file metadata.",
    },
    {
        "id": "file_analysis",
        "source": "local_ai",
        "kind": "media_analysis",
        "setting": "file_analysis.enabled",
        "label": "File analysis",
        "sensitivity": "medium",
        "note": "Stores local AI summaries for copied workspace files.",
    },
    {
        "id": "calendar",
        "source": "calendar",
        "kind": "event",
        "setting": "collectors.calendar",
        "label": "Calendar",
        "sensitivity": "medium",
        "note": "Stores event titles, participants, and schedule metadata.",
    },
    {
        "id": "reminders",
        "source": "reminders",
        "kind": "task",
        "setting": "collectors.reminders",
        "label": "Reminders",
        "sensitivity": "medium",
        "note": "Stores reminder titles, due times, and list metadata.",
    },
]


def privacy_center_payload(settings: Settings, params: dict[str, str] | None = None) -> dict[str, Any]:
    today = now(settings.timezone).date()
    store = Store(settings.db_path)
    try:
        retention_preview = run_retention(settings, store, today, dry_run=True)
        mobile_preview = cleanup_mobile_sync_storage(settings, store, dry_run=True, clean_inbox=True, clean_imports=True)
        recycle_entries = recycle_bin_summary(settings)
        recycle_preview = purge_recycle_bin(settings, dry_run=True)
        sources = privacy_source_rows(settings, store)
        checks = privacy_checks(settings, store, sources)
        cleanup_bytes = int(mobile_preview.freed_bytes or 0) + int(recycle_preview.freed_bytes or 0)
        retention_rows = (
            int(retention_preview.deleted_observations or 0)
            + int(retention_preview.deleted_activity_samples or 0)
            + int(retention_preview.deleted_collector_runs or 0)
        )
        high_enabled = sum(1 for row in sources if row["sensitivity"] == "high" and row["enabled"])
        warn_checks = sum(1 for row in checks if row["status"] in {"warn", "fail"})
        return {
            "ok": True,
            "generated_at": now(settings.timezone).isoformat(timespec="seconds"),
            "summary": {
                "total_records": total_record_count(store),
                "high_sensitivity_enabled": high_enabled,
                "retention_candidate_rows": retention_rows,
                "cleanup_candidate_bytes": cleanup_bytes,
                "warn_checks": warn_checks,
                "local_only": settings.ai_backend.get("provider", "local") != "openai",
            },
            "storage": storage_payload(settings, store),
            "sources": sources,
            "checks": checks,
            "retention": {
                "config": redact_config(settings.retention),
                "preview": retention_result_payload(retention_preview),
            },
            "cleanup": {
                "mobile": {
                    "deleted_files": mobile_preview.deleted_files,
                    "deleted_dirs": mobile_preview.deleted_dirs,
                    "freed_bytes": mobile_preview.freed_bytes,
                    "retained_import_dirs": mobile_preview.retained_import_dirs,
                    "lines": mobile_preview.lines(dry_run=True),
                },
                "recycle": {
                    "summary": recycle_entries,
                    "deleted_files": recycle_preview.deleted_files,
                    "deleted_manifests": recycle_preview.deleted_manifests,
                    "deleted_dirs": recycle_preview.deleted_dirs,
                    "freed_bytes": recycle_preview.freed_bytes,
                    "retained_files": recycle_preview.retained_files,
                    "errors": recycle_preview.errors,
                    "lines": recycle_preview.lines(dry_run=True),
                },
            },
            "config": privacy_config_snapshot(settings),
            "publication": publication_payload(settings),
        }
    finally:
        store.close()


def retention_result_payload(result: Any) -> dict[str, Any]:
    return {
        "dry_run": result.dry_run,
        "observation_cutoff": result.observation_cutoff.isoformat(),
        "activity_cutoff": result.activity_cutoff.isoformat(),
        "reports_cutoff": result.reports_cutoff.isoformat(),
        "collector_runs_cutoff": result.collector_runs_cutoff.isoformat(),
        "deleted_observations": result.deleted_observations,
        "deleted_activity_samples": result.deleted_activity_samples,
        "deleted_collector_runs": result.deleted_collector_runs,
        "deleted_reports": result.deleted_reports,
        "pruned_speaker_sample_audio": getattr(result, "pruned_speaker_sample_audio", 0),
        "speaker_sample_audio_candidate_bytes": getattr(result, "speaker_sample_audio_candidate_bytes", 0),
        "trimmed_logs": result.trimmed_logs,
        "skipped_days": result.skipped_days,
        "vacuumed": result.vacuumed,
        "lines": result.lines(),
    }


def privacy_source_rows(settings: Settings, store: Store) -> list[dict[str, Any]]:
    rows = []
    for spec in SENSITIVE_SOURCE_ROWS:
        source = spec["source"]
        kind = spec["kind"]
        count_row = store.conn.execute(
            """
            SELECT count(*) AS n,
                   sum(CASE WHEN body IS NOT NULL AND length(body) > 0 THEN 1 ELSE 0 END) AS body_rows,
                   min(observed_at) AS first,
                   max(observed_at) AS last
            FROM observations
            WHERE source = ? AND kind = ?
            """,
            (source, kind),
        ).fetchone()
        count = int(count_row["n"] or 0)
        body_rows = int(count_row["body_rows"] or 0)
        rows.append(
            {
                **spec,
                "enabled": privacy_setting_enabled(settings, spec.get("setting", "")),
                "count": count,
                "body_rows": body_rows,
                "first": count_row["first"],
                "last": count_row["last"],
                "retains_text": body_rows > 0 or source in {"messages", "browser"},
                "risk": source_risk(spec["sensitivity"], count, body_rows, privacy_setting_enabled(settings, spec.get("setting", ""))),
            }
        )
    return rows


def privacy_setting_enabled(settings: Settings, setting_key: str) -> bool:
    if not setting_key:
        return True
    value: Any = settings.raw
    for part in setting_key.split("."):
        if not isinstance(value, dict) or part not in value:
            return True
        value = value[part]
    return bool(value)


def source_risk(sensitivity: str, count: int, body_rows: int, enabled: bool) -> str:
    if not enabled and count == 0:
        return "low"
    if sensitivity == "high" and (enabled or count or body_rows):
        return "high"
    if count or body_rows or enabled:
        return "medium"
    return "low"


def privacy_checks(settings: Settings, store: Store, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    provider = str(settings.ai_backend.get("provider") or "local")
    checks.append(
        {
            "id": "ai_provider",
            "status": "warn" if provider == "openai" else "ok",
            "title": "AI provider",
            "detail": "OpenAI provider can send analysis content out of this Mac." if provider == "openai" else "Current provider is local.",
            "action": "Use Settings -> AI provider if you want local-only analysis.",
        }
    )
    mobile_host = str(settings.mobile_sync.get("host") or "")
    token_configured = bool(settings.mobile_sync.get("token"))
    checks.append(
        {
            "id": "mobile_sync_token",
            "status": "warn" if mobile_host in {"0.0.0.0", "::"} and not token_configured else "ok",
            "title": "Mobile sync token",
            "detail": f"host={mobile_host or '-'}; token={'configured' if token_configured else 'missing'}",
            "action": "Generate a sync token in the setup wizard when exposing the upload server on LAN.",
        }
    )
    tracked = tracked_private_files(settings)
    checks.append(
        {
            "id": "tracked_private_files",
            "status": "warn" if tracked else "ok",
            "title": "Tracked private files",
            "detail": ", ".join(tracked[:8]) if tracked else "config.json, data/, and local database paths are not tracked by git.",
            "action": "Remove tracked private files from git before publishing." if tracked else "",
        }
    )
    mail = next((row for row in sources if row["id"] == "apple_mail"), None)
    if mail:
        checks.append(
            {
                "id": "mail_body_preview",
                "status": "warn" if mail["body_rows"] else "ok",
                "title": "Mail body previews",
                "detail": f"{mail['body_rows']} Apple Mail rows contain body preview text.",
                "action": "Disable Apple Mail collector or shorten retention if this is too invasive.",
            }
        )
    chat_body_rows = chat_text_rows(store)
    checks.append(
        {
            "id": "chat_text_boundary",
            "status": "warn" if chat_body_rows else "ok",
            "title": "Chat text boundary",
            "detail": f"{chat_body_rows} chat-like rows contain body text." if chat_body_rows else "No chat-like body column records detected.",
            "action": "Prefer activity metadata for chat imports when full text is not needed.",
        }
    )
    file_copy_dir = file_analysis_workspace(settings)
    file_copy_size = dir_size(file_copy_dir)
    checks.append(
        {
            "id": "file_analysis_workspace",
            "status": "warn" if file_copy_size and not settings.file_analysis.get("delete_after_analysis", False) else "ok",
            "title": "File analysis workspace",
            "detail": f"{file_copy_dir} uses {file_copy_size} bytes.",
            "action": "Enable file_analysis.delete_after_analysis or clean managed copies if needed.",
        }
    )
    return checks


def tracked_private_files(settings: Settings) -> list[str]:
    root = settings.path.parent
    if not (root / ".git").exists():
        return []
    candidates = ["config.json", "data", "*.sqlite3", "*.db"]
    try:
        proc = subprocess.run(
            ["git", "ls-files", "--", *candidates],
            cwd=str(root),
            text=True,
            capture_output=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def chat_text_rows(store: Store) -> int:
    return int(
        scalar(
            store.conn,
            """
            SELECT count(*)
            FROM observations
            WHERE (
                lower(source) IN ('line', 'wechat', 'messages')
                OR lower(kind) IN ('chat_message', 'message')
            )
              AND body IS NOT NULL
              AND length(body) > 0
            """,
        )
        or 0
    )


def storage_payload(settings: Settings, store: Store) -> dict[str, Any]:
    return {
        "database": file_info(settings.db_path),
        "directories": [
            dir_info("data", settings.data_dir),
            dir_info("reports", settings.report_dir),
            dir_info("summaries", settings.summary_dir),
            dir_info("logs", settings.log_dir),
            dir_info("recycle_bin", settings.recycle_bin_dir),
            dir_info("speaker_samples", settings.speaker_sample_dir),
            dir_info("file_analysis_workspace", file_analysis_workspace(settings)),
            dir_info("mobile_sync_inbox", settings.data_dir / "mobile_sync" / "inbox"),
            dir_info("mobile_sync_imports", settings.data_dir / "mobile_sync" / "imports"),
        ],
        "tables": table_counts(store),
    }


def file_info(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
    except OSError:
        return {"path": str(path), "exists": False, "size": 0, "modified_at": None}
    return {
        "path": str(path),
        "exists": True,
        "size": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }


def dir_info(name: str, path: Path) -> dict[str, Any]:
    return {"name": name, "path": str(path), "exists": path.exists(), "size": dir_size(path)}


def file_analysis_workspace(settings: Settings) -> Path:
    raw_dir = settings.file_analysis.get("analysis_copy_dir", "file_analysis_workspace")
    path = Path(str(raw_dir)).expanduser()
    if path.is_absolute():
        return path
    return settings.data_dir / path


def table_counts(store: Store) -> dict[str, int]:
    tables = [
        "observations",
        "activity_samples",
        "collector_runs",
        "daily_feedback",
        "speakers",
        "speaker_samples",
        "speaker_embeddings",
        "project_memories",
        "project_memory_events",
        "meeting_sessions",
        "search_embeddings",
    ]
    counts: dict[str, int] = {}
    existing = existing_tables(store)
    for table in tables:
        counts[table] = int(scalar(store.conn, f"SELECT count(*) FROM {table}") or 0) if table in existing else 0
    return counts


def existing_tables(store: Store) -> set[str]:
    return {
        str(row["name"])
        for row in store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if row["name"]
    }


def total_record_count(store: Store) -> int:
    counts = table_counts(store)
    return sum(counts.get(key, 0) for key in ("observations", "activity_samples", "collector_runs", "daily_feedback"))


def privacy_config_snapshot(settings: Settings) -> dict[str, Any]:
    return {
        "collectors": redact_config(settings.collectors),
        "browser_profiles": redact_config(settings.browser_profiles),
        "watch_paths": [str(path) for path in settings.watch_paths],
        "limits": redact_config(settings.limits),
        "file_analysis": redact_config(settings.file_analysis),
        "audio_analysis": redact_config(settings.audio_analysis),
        "mobile_sync": redact_config(settings.mobile_sync),
        "email_reports": redact_config(settings.email_reports),
        "ai_backend": redact_config(settings.ai_backend),
    }


def publication_payload(settings: Settings) -> dict[str, Any]:
    gitignore = settings.path.parent / ".gitignore"
    ignore_text = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    required = ["config.json", "data/", "*.sqlite3", ".env"]
    return {
        "gitignore_path": str(gitignore),
        "gitignore_exists": gitignore.exists(),
        "ignored_patterns": [{"pattern": pattern, "present": pattern in ignore_text} for pattern in required],
        "tracked_private_files": tracked_private_files(settings),
    }
