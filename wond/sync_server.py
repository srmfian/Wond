from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import shutil
import time
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .audio_analysis import analyze_audio_for_day
from .config import Settings
from .dashboard_shared import row_dict, row_payload
from .mobile import event_to_observation, ingest_mobile_export, load_mobile_events
from .speakers import (
    speaker_confidence_summary,
    speaker_review_confidence_threshold,
    speaker_sample_payload as full_speaker_sample_payload,
    speaker_threshold_config,
)
from .store import Store
from .summarizer import write_daily_report
from .timeutil import utc_iso
from .version import __version__


DEFAULT_MOBILE_SPEAKER_LIMIT = 160
MOBILE_SPEAKER_MAX_LIMIT = 500
DEFAULT_MOBILE_SPEAKER_SAMPLE_LIMIT = 40
MOBILE_SPEAKER_MAX_SAMPLE_LIMIT = 200
MOBILE_SPEAKER_AUTO_MERGE_SOURCE_LIMIT = 5


@dataclass
class SyncImportResult:
    imported: int = 0
    skipped: int = 0
    reports: list[str] = field(default_factory=list)
    analyzed: list[str] = field(default_factory=list)
    cleaned: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class MobileSyncCleanupResult:
    deleted_files: int = 0
    deleted_dirs: int = 0
    freed_bytes: int = 0
    retained_import_dirs: int = 0
    messages: list[str] = field(default_factory=list)

    def extend(self, other: "MobileSyncCleanupResult") -> None:
        self.deleted_files += other.deleted_files
        self.deleted_dirs += other.deleted_dirs
        self.freed_bytes += other.freed_bytes
        self.retained_import_dirs += other.retained_import_dirs
        self.messages.extend(other.messages)

    def summary(self, *, dry_run: bool = False) -> str:
        verb = "Would delete" if dry_run else "Deleted"
        return (
            f"{verb}: files={self.deleted_files}, dirs={self.deleted_dirs}, "
            f"freed={format_bytes(self.freed_bytes)}, retained_import_dirs={self.retained_import_dirs}"
        )

    def lines(self, *, dry_run: bool = False) -> list[str]:
        return [self.summary(dry_run=dry_run), *self.messages]


@dataclass(frozen=True)
class AuthResult:
    ok: bool
    status: HTTPStatus = HTTPStatus.UNAUTHORIZED
    error: str = "unauthorized"


def run_sync_server(settings: Settings, host: str | None = None, port: int | None = None) -> None:
    sync_config = settings.mobile_sync
    bind_host = host or str(sync_config.get("host") or "0.0.0.0")
    bind_port = int(port if port is not None else sync_config.get("port", 8765))
    server = ThreadingHTTPServer((bind_host, bind_port), make_handler(settings))
    actual_port = int(server.server_address[1])
    token = str(sync_config.get("token") or "")
    print(f"Sync server: http://{bind_host}:{actual_port}/upload", flush=True)
    if not token:
        print("Warning: mobile_sync.token is empty; uploads and authenticated API calls will be rejected.", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def make_handler(settings: Settings):
    class SyncRequestHandler(BaseHTTPRequestHandler):
        server_version = f"WondSync/{__version__}"

        def do_GET(self) -> None:
            if self.path == "/health":
                self.send_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "service": "wond-sync",
                    },
                )
                return
            parsed = urlsplit(self.path)
            path = parsed.path
            if path == "/status":
                if not verify_api_auth(settings, self.headers, "GET", self.path, b""):
                    self.send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
                    return
                self.send_json(HTTPStatus.OK, mobile_status_payload(settings, mac_online=True))
                return
            if path == "/speakers":
                if not verify_api_auth(settings, self.headers, "GET", self.path, b""):
                    self.send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
                    return
                self.send_json(HTTPStatus.OK, mobile_speakers_payload(settings, parse_qs(parsed.query)))
                return
            if path.startswith("/speaker-sample/"):
                if not verify_api_auth(settings, self.headers, "GET", self.path, b""):
                    self.send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
                    return
                sample_id = parse_int(path.rsplit("/", 1)[-1])
                if sample_id is None:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_sample_id"})
                    return
                self.send_speaker_sample(sample_id)
                return
            if path == "/speaker-review":
                if not verify_api_auth(settings, self.headers, "GET", self.path, b""):
                    self.send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
                    return
                self.send_json(HTTPStatus.OK, speaker_review_payload(settings))
                return
            if path.startswith("/speaker-review/sample/"):
                if not verify_api_auth(settings, self.headers, "GET", self.path, b""):
                    self.send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
                    return
                sample_id = parse_int(path.rsplit("/", 1)[-1])
                if sample_id is None:
                    self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_sample_id"})
                    return
                self.send_speaker_sample(sample_id)
                return
            self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/ask":
                self.handle_ask()
                return
            if path == "/speaker-review/name":
                self.handle_name_speaker()
                return
            if path != "/upload":
                self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
                return
            length = parse_int(self.headers.get("Content-Length"))
            if length is None or length <= 0:
                self.send_json(HTTPStatus.LENGTH_REQUIRED, {"ok": False, "error": "missing_content_length"})
                return
            max_upload_mb = float(settings.mobile_sync.get("max_upload_mb", 2048))
            max_bytes = int(max_upload_mb * 1024 * 1024)
            if length > max_bytes:
                self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"ok": False, "error": "upload_too_large"})
                return
            encrypted = self.headers.get("X-Wond-Encrypted") == "AESGCM-v1"
            auth = upload_auth_preflight(settings, self.headers, encrypted)
            if not auth.ok:
                self.send_auth_error(auth)
                return
            upload_path: Path | None = None
            zip_path: Path | None = None
            try:
                upload_path = save_upload_stream(settings, self.rfile, length, self.headers.get("X-Filename"), encrypted)
                auth = verify_upload_auth(settings, upload_path, self.headers, encrypted)
                if not auth.ok:
                    cleanup_upload_artifacts(settings, upload_path)
                    self.send_auth_error(auth)
                    return
                zip_path = decrypt_upload_if_needed(settings, upload_path, encrypted)
                result = import_upload_zip(settings, zip_path)
                cleanup = cleanup_uploaded_files_after_import(settings, upload_path, zip_path)
                if cleanup.deleted_files:
                    result.cleaned.append(cleanup.summary())
                self.send_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "zip_path": str(zip_path),
                        "imported": result.imported,
                        "skipped": result.skipped,
                        "reports": result.reports,
                        "analyzed": result.analyzed,
                        "cleaned": result.cleaned,
                        "errors": result.errors,
                    },
                )
            except Exception as exc:
                cleanup_upload_artifacts(settings, upload_path, zip_path)
                self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})

        def handle_ask(self) -> None:
            length = parse_int(self.headers.get("Content-Length")) or 0
            if length > 64 * 1024:
                self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"ok": False, "error": "request_too_large"})
                return
            body = self.rfile.read(length) if length else b""
            if not verify_api_auth(settings, self.headers, "POST", self.path, body):
                self.send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
                return
            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"})
                return
            if not isinstance(payload, dict):
                self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"})
                return
            try:
                from .dashboard import api_ask

                result = api_ask(settings, payload)
            except Exception as exc:
                self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": str(exc)})
                return
            status = HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST
            self.send_json(status, result)

        def handle_name_speaker(self) -> None:
            length = parse_int(self.headers.get("Content-Length")) or 0
            if length > 16 * 1024:
                self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"ok": False, "error": "request_too_large"})
                return
            body = self.rfile.read(length) if length else b""
            if not verify_api_auth(settings, self.headers, "POST", self.path, body):
                self.send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
                return
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"})
                return
            speaker_id = payload.get("speaker_id")
            display_name = str(payload.get("display_name") or "").strip()
            if not isinstance(speaker_id, int) or speaker_id <= 0:
                self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_speaker_id"})
                return
            if not display_name:
                self.send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing_display_name"})
                return
            store = Store(settings.db_path)
            try:
                if not store.rename_speaker(speaker_id, display_name):
                    self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "speaker_not_found"})
                    return
            finally:
                store.close()
            self.send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "speaker_id": speaker_id,
                    "display_name": display_name,
                },
            )

        def send_speaker_sample(self, sample_id: int) -> None:
            store = Store(settings.db_path)
            try:
                row = store.get_speaker_sample(sample_id)
            finally:
                store.close()
            if row is None:
                self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "sample_not_found"})
                return
            sample_path = row["sample_path"]
            if not sample_path:
                self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "sample_audio_not_available"})
                return
            try:
                root = settings.speaker_sample_dir.resolve()
                resolved = Path(str(sample_path)).resolve(strict=True)
                resolved.relative_to(root)
            except FileNotFoundError:
                self.send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "sample_audio_missing"})
                return
            except ValueError:
                self.send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "sample_path_forbidden"})
                return
            data = resolved.read_bytes()
            self.send_response(int(HTTPStatus.OK))
            self.send_header("Content-Type", content_type_for_audio(resolved))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(int(status))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def send_auth_error(self, result: AuthResult) -> None:
            self.send_json(result.status, {"ok": False, "error": result.error})

        def log_message(self, format: str, *args) -> None:
            print(f"{self.address_string()} - {format % args}")

    return SyncRequestHandler


def mobile_speakers_payload(settings: Settings, query: dict[str, list[str]] | None = None) -> dict[str, Any]:
    query = query or {}
    speaker_filter = query_value(query, "speaker_filter", "active")
    speaker_sort = query_value(query, "speaker_sort", "review")
    speaker_search = query_value(query, "speaker_search", "")
    speaker_limit = mobile_query_limit(query, "speaker_limit", DEFAULT_MOBILE_SPEAKER_LIMIT, MOBILE_SPEAKER_MAX_LIMIT)
    sample_scope = query_value(query, "sample_scope", "visible")
    sample_filter = query_value(query, "sample_filter", "needsWork")
    sample_sort = query_value(query, "sample_sort", "needsWork")
    sample_search = query_value(query, "sample_search", "")
    selected_speaker_ids = parse_id_set(query_value(query, "selected_speaker_ids", ""))
    sample_limit = mobile_query_limit(
        query,
        "sample_limit",
        DEFAULT_MOBILE_SPEAKER_SAMPLE_LIMIT,
        MOBILE_SPEAKER_MAX_SAMPLE_LIMIT,
    )
    thresholds = speaker_threshold_config(settings)
    threshold_config = thresholds.get("speaker_recognition") if isinstance(thresholds, dict) else {}
    candidate_threshold = float((threshold_config or {}).get("candidate_threshold") or 0.68)
    confidence_threshold = speaker_review_confidence_threshold(settings)
    store = Store(settings.db_path)
    try:
        all_speakers = []
        for row in store.list_speakers():
            speaker_id = int(row["id"])
            stats = store.speaker_sample_evidence_stats(speaker_id)
            embedding_count = int(
                scalar(store, "SELECT count(*) FROM speaker_embeddings WHERE speaker_id = ?", (speaker_id,)) or 0
            )
            all_speakers.append(
                row_payload(
                    row,
                    extra={
                        "metadata": compact_mobile_speaker_metadata(row["metadata"]),
                        "sample_count": row["sample_count"],
                        "alias_count": row["alias_count"],
                        "latest_sample_at": row["latest_sample_at"],
                        "evidence": row_dict(stats),
                        "embedding_count": embedding_count,
                        "confidence_summary": speaker_confidence_summary(
                            row,
                            sample_count=int(stats["sample_count"] or 0),
                            embedding_count=embedding_count,
                            confidence_threshold=confidence_threshold,
                        ),
                    },
                )
            )

        filtered_speakers = filter_mobile_speakers(
            all_speakers,
            speaker_filter=speaker_filter,
            speaker_search=speaker_search,
            candidate_threshold=candidate_threshold,
        )
        sorted_speakers = sort_mobile_speakers(filtered_speakers, speaker_sort, candidate_threshold)
        speaker_rows = sorted_speakers[:speaker_limit]
        filtered_speaker_ids = {int(row["id"]) for row in filtered_speakers}

        all_samples = []
        for row in store.list_speaker_samples(None):
            item = full_speaker_sample_payload(row)
            if (item.get("metadata") or {}).get("sample_role") == "mixed_parent_archived":
                continue
            all_samples.append(item)

        scoped_samples = scope_mobile_samples(
            all_samples,
            sample_scope=sample_scope,
            selected_speaker_ids=selected_speaker_ids,
            visible_speaker_ids=filtered_speaker_ids,
        )
        filtered_samples = filter_mobile_samples(
            scoped_samples,
            sample_filter=sample_filter,
            sample_search=sample_search,
            candidate_threshold=candidate_threshold,
        )
        sample_rows = sort_mobile_samples(filtered_samples, sample_sort, candidate_threshold)[:sample_limit]
        return {
            "ok": True,
            "speakers": speaker_rows,
            "samples": sample_rows,
            "summary": {
                "active_speakers": mobile_speaker_count(all_speakers, "active", candidate_threshold),
                "confirmed_speakers": sum(1 for row in all_speakers if speaker_review_status(row) == "confirmed"),
                "pending_auto": mobile_speaker_count(all_speakers, "pendingAuto", candidate_threshold),
                "hidden_speakers": mobile_speaker_count(all_speakers, "hidden", candidate_threshold),
                "samples": len(all_samples),
            },
            "speaker_counts": {
                key: mobile_speaker_count(all_speakers, key, candidate_threshold)
                for key in ["active", "pendingAuto", "lowConfidence", "review", "hidden", "all"]
            },
            "speaker_total": len(filtered_speakers),
            "speakers_truncated": len(filtered_speakers) > len(speaker_rows),
            "sample_counts": {
                key: mobile_sample_count(scoped_samples, key, candidate_threshold)
                for key in ["all", "needsWork", "lowConfidence", "missingEmbedding", "representative", "playable", "detached"]
            },
            "sample_total": len(all_samples),
            "sample_scope_total": len(scoped_samples),
            "sample_filtered_total": len(filtered_samples),
            "samples_truncated": len(filtered_samples) > len(sample_rows),
            "config": thresholds,
        }
    finally:
        store.close()


def query_value(query: dict[str, list[str]], key: str, default: str = "") -> str:
    values = query.get(key) or []
    if not values:
        return default
    return str(values[0] or default)


def mobile_query_limit(query: dict[str, list[str]], key: str, default: int, maximum: int) -> int:
    raw = (query.get(key) or [None])[0]
    value = parse_int(raw) if raw is not None else None
    if value is None:
        value = default
    return max(0, min(value, maximum))


def parse_id_set(raw: str) -> set[int]:
    ids: set[int] = set()
    for item in str(raw or "").split(","):
        value = parse_int(item.strip())
        if value is not None and value > 0:
            ids.add(value)
    return ids


def mobile_key(value: str) -> str:
    return re.sub(r"[\s_-]+", "", str(value or "")).lower()


def speaker_review_status(speaker: dict[str, Any]) -> str:
    metadata = speaker.get("metadata") if isinstance(speaker.get("metadata"), dict) else {}
    return str((metadata or {}).get("speaker_review_status") or "").strip()


def speaker_is_auto_pending(speaker: dict[str, Any]) -> bool:
    return speaker_review_status(speaker) == "auto_merged_pending_review"


def speaker_is_hidden(speaker: dict[str, Any]) -> bool:
    metadata = speaker.get("metadata") if isinstance(speaker.get("metadata"), dict) else {}
    return bool((metadata or {}).get("speaker_hidden")) or speaker_review_status(speaker) == "low_similarity_hidden"


def speaker_needs_review(speaker: dict[str, Any]) -> bool:
    if speaker_is_auto_pending(speaker):
        return True
    if speaker_review_status(speaker) == "confirmed":
        return False
    if speaker.get("identity_status") == "provisional" or int(speaker.get("sample_count") or 0) <= 0:
        return True
    name = str(speaker.get("display_name") or "").strip()
    if not name:
        return True
    if parse_int(name) is not None:
        return True
    return bool(re.match(r"(?i)^speaker\s*\d+$", name))


def speaker_has_low_confidence(speaker: dict[str, Any], candidate_threshold: float) -> bool:
    if speaker_review_status(speaker) == "confirmed":
        return False
    confidence = parse_float(speaker.get("confidence"))
    return confidence is not None and 0 < confidence < candidate_threshold


def filter_mobile_speakers(
    rows: list[dict[str, Any]],
    *,
    speaker_filter: str,
    speaker_search: str,
    candidate_threshold: float,
) -> list[dict[str, Any]]:
    mode = mobile_key(speaker_filter)
    query = str(speaker_search or "").strip().lower()
    result = []
    for speaker in rows:
        if mode not in {"hidden", "all"} and speaker_is_hidden(speaker):
            continue
        if mode == "active" and speaker_is_hidden(speaker):
            continue
        if mode == "pendingauto" and not speaker_is_auto_pending(speaker):
            continue
        if mode == "review" and (speaker_is_hidden(speaker) or not speaker_needs_review(speaker)):
            continue
        if mode == "lowconfidence" and (speaker_is_hidden(speaker) or not speaker_has_low_confidence(speaker, candidate_threshold)):
            continue
        if mode == "hidden" and not speaker_is_hidden(speaker):
            continue
        if query and query not in mobile_speaker_search_text(speaker):
            continue
        result.append(speaker)
    return result


def mobile_speaker_search_text(speaker: dict[str, Any]) -> str:
    metadata = speaker.get("metadata") if isinstance(speaker.get("metadata"), dict) else {}
    sources = metadata.get("auto_merge_sources") if isinstance(metadata, dict) else []
    source_text = " ".join(
        f"{source.get('source_display_name') or ''} {source.get('source_speaker_id') or ''}"
        for source in sources
        if isinstance(source, dict)
    )
    evidence = speaker.get("evidence") if isinstance(speaker.get("evidence"), dict) else {}
    values = [
        speaker.get("id"),
        speaker.get("display_name"),
        speaker.get("identity_status"),
        speaker_review_status(speaker),
        source_text,
        speaker.get("confidence"),
        speaker.get("sample_count"),
        speaker.get("alias_count"),
        evidence.get("day_count") if isinstance(evidence, dict) else "",
        evidence.get("latest_seen_at") if isinstance(evidence, dict) else "",
    ]
    return " ".join(str(value or "") for value in values).lower()


def sort_mobile_speakers(rows: list[dict[str, Any]], speaker_sort: str, candidate_threshold: float) -> list[dict[str, Any]]:
    mode = mobile_key(speaker_sort)
    if mode == "samples":
        return sorted(rows, key=lambda row: (-int(row.get("sample_count") or 0), int(row.get("id") or 0)))
    if mode == "confidence":
        return sorted(rows, key=lambda row: (-(parse_float(row.get("confidence")) or -1), int(row.get("id") or 0)))
    if mode == "recent":
        return sorted(rows, key=lambda row: (speaker_visible_time(row) or "", -int(row.get("id") or 0)), reverse=True)
    if mode == "id":
        return sorted(rows, key=lambda row: int(row.get("id") or 0))
    return sorted(
        rows,
        key=lambda row: (
            speaker_review_score(row, candidate_threshold),
            speaker_visible_time(row) or "",
            -int(row.get("id") or 0),
        ),
        reverse=True,
    )


def speaker_review_score(speaker: dict[str, Any], candidate_threshold: float) -> int:
    return (
        (2000 if speaker_is_auto_pending(speaker) else 0)
        + (1000 if speaker_needs_review(speaker) else 0)
        + (200 if int(speaker.get("sample_count") or 0) <= 0 else 0)
        + (100 if speaker_has_low_confidence(speaker, candidate_threshold) else 0)
    )


def speaker_visible_time(speaker: dict[str, Any]) -> str:
    evidence = speaker.get("evidence") if isinstance(speaker.get("evidence"), dict) else {}
    return str(
        (evidence or {}).get("latest_seen_at")
        or speaker.get("latest_sample_at")
        or speaker.get("created_at")
        or ""
    )


def mobile_speaker_count(rows: list[dict[str, Any]], speaker_filter: str, candidate_threshold: float) -> int:
    return len(
        filter_mobile_speakers(
            rows,
            speaker_filter=speaker_filter,
            speaker_search="",
            candidate_threshold=candidate_threshold,
        )
    )


def scope_mobile_samples(
    rows: list[dict[str, Any]],
    *,
    sample_scope: str,
    selected_speaker_ids: set[int],
    visible_speaker_ids: set[int],
) -> list[dict[str, Any]]:
    mode = mobile_key(sample_scope)
    if mode == "selected":
        if not selected_speaker_ids:
            return []
        return [row for row in rows if sample_speaker_id(row) in selected_speaker_ids]
    if mode == "all":
        return rows
    return [row for row in rows if sample_speaker_id(row) in visible_speaker_ids]


def filter_mobile_samples(
    rows: list[dict[str, Any]],
    *,
    sample_filter: str,
    sample_search: str,
    candidate_threshold: float,
) -> list[dict[str, Any]]:
    mode = mobile_key(sample_filter)
    query = str(sample_search or "").strip().lower()
    result = []
    for sample in rows:
        if mode == "needswork" and not (
            sample_has_low_confidence(sample, candidate_threshold)
            or sample_missing_embedding(sample)
            or sample_has_error(sample)
        ):
            continue
        if mode == "lowconfidence" and not sample_has_low_confidence(sample, candidate_threshold):
            continue
        if mode == "missingembedding" and not sample_missing_embedding(sample):
            continue
        if mode == "representative" and not sample_is_representative(sample):
            continue
        if mode == "playable" and not sample.get("sample_path"):
            continue
        if mode == "detached" and not sample_is_detached(sample):
            continue
        if query and query not in mobile_sample_search_text(sample):
            continue
        result.append(sample)
    return result


def sort_mobile_samples(rows: list[dict[str, Any]], sample_sort: str, candidate_threshold: float) -> list[dict[str, Any]]:
    mode = mobile_key(sample_sort)
    if mode == "recent":
        return sorted(rows, key=lambda row: (str(row.get("created_at") or ""), int(row.get("id") or 0)), reverse=True)
    if mode == "speaker":
        return sorted(rows, key=lambda row: (str(row.get("speaker_name") or row.get("speaker_id") or ""), int(row.get("id") or 0)))
    if mode == "duration":
        return sorted(rows, key=lambda row: (-sample_duration(row), -int(row.get("id") or 0)))
    return sorted(rows, key=lambda row: sample_needs_work_sort_key(row, candidate_threshold))


def sample_needs_work_sort_key(sample: dict[str, Any], candidate_threshold: float) -> tuple[Any, ...]:
    confidence = sample_confidence_value(sample)
    has_confidence = confidence is not None
    return (
        -sample_review_score(sample, candidate_threshold),
        confidence if has_confidence else 2.0,
        0 if has_confidence else 1,
        -int(sample.get("id") or 0),
    )


def mobile_sample_count(rows: list[dict[str, Any]], sample_filter: str, candidate_threshold: float) -> int:
    return len(
        filter_mobile_samples(
            rows,
            sample_filter=sample_filter,
            sample_search="",
            candidate_threshold=candidate_threshold,
        )
    )


def sample_speaker_id(sample: dict[str, Any]) -> int | None:
    return parse_int(sample.get("speaker_id"))


def sample_metadata(sample: dict[str, Any]) -> dict[str, Any]:
    metadata = sample.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def sample_confidence_value(sample: dict[str, Any]) -> float | None:
    return parse_float(sample_metadata(sample).get("sample_confidence"))


def sample_has_low_confidence(sample: dict[str, Any], candidate_threshold: float) -> bool:
    confidence = sample_confidence_value(sample)
    return confidence is not None and 0 < confidence < candidate_threshold


def sample_has_error(sample: dict[str, Any]) -> bool:
    metadata = sample_metadata(sample)
    status = str(metadata.get("status") or "").lower()
    return bool(metadata.get("error")) or status in {"error", "fail", "failed"}


def sample_missing_embedding(sample: dict[str, Any]) -> bool:
    metadata = sample_metadata(sample)
    return (
        metadata.get("sample_confidence_model") is None
        and metadata.get("embedding_model") is None
        and metadata.get("embedding_repair_status") != "ok"
    )


def sample_is_representative(sample: dict[str, Any]) -> bool:
    return bool(sample_metadata(sample).get("representative_sample"))


def sample_is_detached(sample: dict[str, Any]) -> bool:
    return "detached" in str(sample_metadata(sample).get("sample_role") or "")


def sample_review_score(sample: dict[str, Any], candidate_threshold: float) -> int:
    return (
        (3000 if sample_missing_embedding(sample) else 0)
        + (2000 if sample_has_low_confidence(sample, candidate_threshold) else 0)
        + (1000 if sample_has_error(sample) else 0)
    )


def sample_duration(sample: dict[str, Any]) -> float:
    start = parse_float(sample.get("start_seconds")) or 0.0
    end = parse_float(sample.get("end_seconds")) or 0.0
    return max(0.0, end - start)


def mobile_sample_search_text(sample: dict[str, Any]) -> str:
    metadata = sample_metadata(sample)
    values = [
        sample.get("id"),
        sample.get("speaker_id"),
        sample.get("speaker_name"),
        sample.get("observation_id"),
        sample.get("source_key"),
        sample.get("transcript"),
        sample.get("created_at"),
        metadata.get("status"),
        metadata.get("error"),
        metadata.get("local_label"),
        metadata.get("sample_role"),
        metadata.get("sample_confidence"),
        metadata.get("embedding_repair_status"),
    ]
    return " ".join(str(value or "") for value in values).lower()


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compact_mobile_speaker_metadata(raw: Any) -> dict[str, Any]:
    metadata = json_object(raw)
    compact: dict[str, Any] = {}
    for key in ["speaker_review_status", "speaker_hidden", "hidden_threshold"]:
        if key in metadata:
            compact[key] = metadata[key]
    sources = metadata.get("auto_merge_sources")
    if isinstance(sources, list):
        compact["auto_merge_source_count"] = len(sources)
        compact["auto_merge_sources"] = [
            source
            for source in sources[-MOBILE_SPEAKER_AUTO_MERGE_SOURCE_LIMIT:]
            if isinstance(source, dict)
        ]
    return compact


def speaker_review_payload(settings: Settings) -> dict[str, Any]:
    store = Store(settings.db_path)
    try:
        speakers = []
        for row in store.list_speakers_ready_for_review():
            speaker_id = int(row["id"])
            stats = store.speaker_sample_evidence_stats(speaker_id)
            samples = [speaker_sample_payload(sample) for sample in store.list_speaker_samples(speaker_id)[:5]]
            speakers.append(
                {
                    "id": speaker_id,
                    "display_name": row["display_name"],
                    "identity_status": row["identity_status"],
                    "confidence": row["confidence"],
                    "sample_count": stats["sample_count"],
                    "observation_count": stats["observation_count"],
                    "day_count": stats["day_count"],
                    "first_seen_at": stats["first_seen_at"],
                    "latest_seen_at": stats["latest_seen_at"],
                    "latest_sample_at": row["latest_sample_at"],
                    "samples": samples,
                }
            )
        return {"ok": True, "speakers": speakers}
    finally:
        store.close()


def speaker_sample_payload(row) -> dict[str, Any]:
    start = row["start_seconds"]
    end = row["end_seconds"]
    duration = None
    if start is not None and end is not None:
        duration = max(0.0, float(end) - float(start))
    return {
        "id": int(row["id"]),
        "created_at": row["created_at"],
        "start_seconds": start,
        "end_seconds": end,
        "duration_seconds": duration,
        "transcript": row["transcript"],
        "has_audio": bool(row["sample_path"]),
    }


def content_type_for_audio(path: Path) -> str:
    if path.suffix.lower() == ".m4a":
        return "audio/mp4"
    if path.suffix.lower() == ".wav":
        return "audio/wav"
    return "application/octet-stream"

def save_upload(settings: Settings, body: bytes, filename: str | None) -> Path:
    inbox = settings.data_dir / "mobile_sync" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    safe = sanitize_filename(filename or f"mobile-upload-{time.strftime('%Y%m%d-%H%M%S')}.zip")
    if not safe.endswith(".zip"):
        safe = f"{safe}.zip"
    path = inbox / unique_name(inbox, safe)
    path.write_bytes(body)
    return path


def save_upload_stream(settings: Settings, source, length: int, filename: str | None, encrypted: bool = False) -> Path:
    inbox = settings.data_dir / "mobile_sync" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    safe = sanitize_filename(filename or f"mobile-upload-{time.strftime('%Y%m%d-%H%M%S')}.zip")
    wanted_suffix = ".pcsync" if encrypted else ".zip"
    if not safe.endswith(wanted_suffix):
        safe = f"{safe}{wanted_suffix}"
    path = inbox / unique_name(inbox, safe)
    remaining = length
    try:
        with path.open("wb") as out:
            while remaining > 0:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("upload ended before Content-Length bytes were received")
                out.write(chunk)
                remaining -= len(chunk)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def decrypt_upload_if_needed(settings: Settings, upload_path: Path, encrypted: bool) -> Path:
    if not encrypted:
        return upload_path
    token = str(settings.mobile_sync.get("token") or "")
    if not token:
        raise ValueError("encrypted upload requires mobile_sync.token")
    payload = json.loads(upload_path.read_text(encoding="utf-8"))
    if payload.get("version") != 1 or payload.get("algorithm") != "AES-256-GCM":
        raise ValueError("unsupported encrypted upload envelope")
    salt = base64_decode(payload.get("salt"))
    nonce = base64_decode(payload.get("nonce"))
    ciphertext = base64_decode(payload.get("ciphertext"))
    plaintext = decrypt_aes_gcm(token, salt, nonce, ciphertext)
    zip_path = upload_path.with_suffix(".zip")
    try:
        zip_path.write_bytes(plaintext)
    except Exception:
        zip_path.unlink(missing_ok=True)
        raise
    return zip_path


def upload_auth_preflight(settings: Settings, headers, encrypted: bool) -> AuthResult:
    token = str(settings.mobile_sync.get("token") or "")
    if not token:
        return AuthResult(False, HTTPStatus.SERVICE_UNAVAILABLE, "sync_token_required")
    if mobile_sync_bool(settings, "require_encrypted_uploads", True) and not encrypted:
        return AuthResult(False, HTTPStatus.BAD_REQUEST, "encrypted_upload_required")
    timestamp = headers.get("X-Wond-Timestamp")
    body_hash = headers.get("X-Wond-Body-SHA256")
    signature = headers.get("X-Wond-Signature")
    if not timestamp or not body_hash or not signature:
        return AuthResult(False)
    try:
        sent_at = int(timestamp)
    except ValueError:
        return AuthResult(False)
    max_skew_seconds = 900
    if abs(int(time.time()) - sent_at) > max_skew_seconds:
        return AuthResult(False)
    if not is_sha256_hex(body_hash):
        return AuthResult(False)
    return AuthResult(True, HTTPStatus.OK, "")


def verify_upload_auth(settings: Settings, upload_path: Path, headers, encrypted: bool) -> AuthResult:
    preflight = upload_auth_preflight(settings, headers, encrypted)
    if not preflight.ok:
        return preflight
    token = str(settings.mobile_sync.get("token") or "")
    timestamp = str(headers.get("X-Wond-Timestamp"))
    body_hash = str(headers.get("X-Wond-Body-SHA256"))
    signature = str(headers.get("X-Wond-Signature"))
    actual_hash = sha256_file(upload_path)
    if not hmac.compare_digest(actual_hash, body_hash):
        return AuthResult(False)
    message = f"{timestamp}\n{body_hash}".encode("utf-8")
    expected = base64.b64encode(hmac.new(token.encode("utf-8"), message, hashlib.sha256).digest()).decode("ascii")
    if not hmac.compare_digest(expected, signature):
        return AuthResult(False)
    return AuthResult(True, HTTPStatus.OK, "")


def verify_api_auth(settings: Settings, headers, method: str, request_target: str, body: bytes) -> bool:
    token = str(settings.mobile_sync.get("token") or "")
    if not token:
        return False
    timestamp = headers.get("X-Wond-Timestamp")
    body_hash = headers.get("X-Wond-Body-SHA256")
    signature = headers.get("X-Wond-Signature")
    if not timestamp or not body_hash or not signature:
        return False
    if not is_sha256_hex(body_hash):
        return False
    try:
        sent_at = int(timestamp)
    except ValueError:
        return False
    max_skew_seconds = 900
    if abs(int(time.time()) - sent_at) > max_skew_seconds:
        return False
    actual_hash = sha256_bytes(body)
    if not hmac.compare_digest(actual_hash, body_hash):
        return False
    message = f"{timestamp}\n{method.upper()}\n{request_target}\n{body_hash}".encode("utf-8")
    expected = base64.b64encode(hmac.new(token.encode("utf-8"), message, hashlib.sha256).digest()).decode("ascii")
    return hmac.compare_digest(expected, signature)


def cleanup_upload_artifacts(settings: Settings, *paths: Path | None) -> None:
    inbox = mobile_sync_inbox(settings)
    seen: set[Path] = set()
    for path in paths:
        if path is None:
            continue
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            if resolved.is_file() and is_relative_to(resolved, inbox):
                resolved.unlink()
        except OSError:
            pass


def is_sha256_hex(value: str) -> bool:
    if len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def decrypt_aes_gcm(token: str, salt: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes
    except ImportError as exc:
        raise RuntimeError("cryptography is required for encrypted mobile sync") from exc
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=200_000,
    )
    key = kdf.derive(token.encode("utf-8"))
    return AESGCM(key).decrypt(nonce, ciphertext, b"WondSyncV1")


def base64_decode(value: Any) -> bytes:
    if not isinstance(value, str):
        raise ValueError("invalid encrypted upload field")
    return base64.b64decode(value)


def import_upload_zip(settings: Settings, zip_path: Path) -> SyncImportResult:
    import_root = settings.data_dir / "mobile_sync" / "imports" / zip_path.stem
    import_root.mkdir(parents=True, exist_ok=True)
    try:
        extract_zip_safely(zip_path, import_root)
    except Exception:
        shutil.rmtree(import_root, ignore_errors=True)
        raise
    json_path = find_mobile_export(import_root)
    result = SyncImportResult()
    if not json_path:
        result.errors.append("mobile-export.json not found")
        return result
    events = load_mobile_events(json_path)
    report_days = dates_from_events(events)
    store = Store(settings.db_path)
    try:
        if settings.mobile_sync.get("skip_existing_uploads", True) and all_mobile_events_exist(
            settings,
            store,
            events,
            json_path.parent,
        ):
            result.skipped = len(events)
            cleanup = cleanup_import_root(import_root)
            if cleanup.deleted_dirs:
                result.cleaned.append(cleanup.summary())
            stale = cleanup_unreferenced_import_dirs(settings, store)
            if stale.deleted_dirs:
                result.cleaned.append(stale.summary())
            return result
        ingest = ingest_mobile_export(settings, store, json_path)
        result.imported = ingest.imported
        result.skipped = ingest.skipped
        result.errors.extend(ingest.errors)
        if settings.mobile_sync.get("analyze_after_import", False):
            for day in sorted(report_days):
                analysis = analyze_audio_for_day(
                    settings,
                    store,
                    day,
                    limit=int(settings.mobile_sync.get("analyze_limit", 20)),
                )
                result.analyzed.append(
                    f"{day.isoformat()}: updated={analysis.updated}, transcribed={analysis.transcribed}, failed={analysis.failed}"
                )
        if settings.mobile_sync.get("write_reports", True):
            for day in sorted(report_days):
                report = write_daily_report(settings, store, day)
                result.reports.append(str(report))
        stale = cleanup_unreferenced_import_dirs(settings, store)
        if stale.deleted_dirs:
            result.cleaned.append(stale.summary())
    finally:
        store.close()
    return result


def cleanup_mobile_sync_storage(
    settings: Settings,
    store: Store,
    *,
    dry_run: bool = True,
    clean_inbox: bool = True,
    clean_imports: bool = True,
) -> MobileSyncCleanupResult:
    result = MobileSyncCleanupResult()
    if clean_inbox:
        result.extend(clean_inbox_uploads(settings, dry_run=dry_run))
    if clean_imports:
        result.extend(cleanup_unreferenced_import_dirs(settings, store, dry_run=dry_run, respect_config=False))
    return result


def mobile_status_payload(settings: Settings, *, store: Store | None = None, mac_online: bool = True) -> dict[str, Any]:
    own_store = store is None
    db = store or Store(settings.db_path)
    try:
        audio = mobile_audio_status(db)
        storage = mobile_sync_storage_status(settings)
        return {
            "ok": True,
            "service": "wond-sync",
            "mac_online": mac_online,
            "generated_at": utc_iso(),
            "last_mobile_observed_at": scalar(db, "SELECT max(observed_at) FROM observations WHERE source = 'mobile'"),
            "last_mobile_captured_at": scalar(db, "SELECT max(captured_at) FROM observations WHERE source = 'mobile'"),
            "pending_server_import_files": storage["inbox_files"],
            "storage": storage,
            "audio": audio,
            "failures": mobile_failure_rows(db),
            "recent_mobile": recent_mobile_rows(db),
        }
    finally:
        if own_store:
            db.close()


def mobile_audio_status(store: Store) -> dict[str, Any]:
    statuses: dict[str, int] = {}
    for row in store.conn.execute(
        """
        SELECT coalesce(json_extract(metadata, '$.audio_analysis.status'), 'pending') AS status,
               count(*) AS n
        FROM observations
        WHERE source = 'mobile' AND kind = 'audio_segment'
        GROUP BY status
        """
    ):
        statuses[str(row["status"])] = int(row["n"])
    pending = int(statuses.get("pending", 0))
    errors = int(statuses.get("error", 0))
    return {
        "total": sum(statuses.values()),
        "statuses": statuses,
        "pending": pending,
        "errors": errors,
        "complete": pending == 0 and errors == 0,
        "latest_analyzed": scalar(
            store,
            "SELECT max(json_extract(metadata, '$.audio_analysis.analyzed_at')) FROM observations WHERE source='mobile' AND kind='audio_segment'",
        ),
    }


def mobile_failure_rows(store: Store) -> list[dict[str, Any]]:
    rows = store.conn.execute(
        """
        SELECT observed_at, title, metadata
        FROM observations
        WHERE source = 'mobile'
          AND kind = 'audio_segment'
          AND coalesce(json_extract(metadata, '$.audio_analysis.status'), 'pending') = 'error'
        ORDER BY captured_at DESC
        LIMIT 8
        """
    ).fetchall()
    failures = []
    for row in rows:
        meta = json_object(row["metadata"])
        analysis = meta.get("audio_analysis") if isinstance(meta.get("audio_analysis"), dict) else {}
        failures.append(
            {
                "observed_at": row["observed_at"],
                "title": row["title"],
                "error": str(analysis.get("error") or analysis.get("transcription_error") or "audio analysis failed")[:500],
            }
        )
    return failures


def recent_mobile_rows(store: Store) -> list[dict[str, Any]]:
    rows = store.conn.execute(
        """
        SELECT observed_at, kind, title, captured_at
        FROM observations
        WHERE source = 'mobile'
        ORDER BY captured_at DESC
        LIMIT 20
        """
    ).fetchall()
    return [
        {
            "observed_at": row["observed_at"],
            "kind": row["kind"],
            "title": row["title"],
            "captured_at": row["captured_at"],
        }
        for row in rows
    ]


def mobile_sync_storage_status(settings: Settings) -> dict[str, Any]:
    inbox = mobile_sync_inbox(settings)
    imports = mobile_sync_imports(settings)
    return {
        "inbox_files": count_files(inbox),
        "import_dirs": count_dirs(imports),
        "inbox_size": path_size(inbox) if inbox.exists() else 0,
        "imports_size": path_size(imports) if imports.exists() else 0,
        "latest_inbox_at": latest_path_mtime(inbox),
        "latest_import_at": latest_path_mtime(imports),
    }


def count_files(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(1 for path in root.rglob("*") if path.is_file() and not path.name.startswith("."))


def count_dirs(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(1 for path in root.iterdir() if path.is_dir() and not path.name.startswith("."))


def latest_path_mtime(root: Path) -> str | None:
    if not root.exists():
        return None
    latest: float | None = None
    for path in root.rglob("*"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        latest = mtime if latest is None else max(latest, mtime)
    if latest is None:
        return None
    return datetime.fromtimestamp(latest).astimezone().isoformat(timespec="seconds")


def scalar(store: Store, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = store.conn.execute(sql, params).fetchone()
    return row[0] if row else None


def cleanup_uploaded_files_after_import(settings: Settings, *paths: Path) -> MobileSyncCleanupResult:
    if not mobile_sync_bool(settings, "delete_uploads_after_import", True):
        return MobileSyncCleanupResult()
    inbox = mobile_sync_inbox(settings)
    result = MobileSyncCleanupResult()
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if not is_relative_to(resolved, inbox):
            result.messages.append(f"- Not deleting upload outside inbox: {path}")
            continue
        cleanup_file(resolved, result, dry_run=False)
    return result


def clean_inbox_uploads(settings: Settings, *, dry_run: bool) -> MobileSyncCleanupResult:
    inbox = mobile_sync_inbox(settings)
    result = MobileSyncCleanupResult()
    if not inbox.exists():
        return result
    for path in sorted(inbox.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() not in {".pcsync", ".zip"}:
            continue
        cleanup_file(path, result, dry_run=dry_run)
    return result


def cleanup_import_root(import_root: Path, *, dry_run: bool = False) -> MobileSyncCleanupResult:
    result = MobileSyncCleanupResult()
    try:
        size = path_size(import_root)
    except OSError as exc:
        result.messages.append(f"- Could not inspect import dir {import_root}: {exc}")
        return result
    if dry_run:
        result.deleted_dirs += 1
        result.freed_bytes += size
        result.messages.append(f"- Would delete import dir: {import_root} ({format_bytes(size)})")
        return result
    try:
        shutil.rmtree(import_root)
        result.deleted_dirs += 1
        result.freed_bytes += size
    except OSError as exc:
        result.messages.append(f"- Failed to delete import dir {import_root}: {exc}")
    return result


def cleanup_unreferenced_import_dirs(
    settings: Settings,
    store: Store,
    *,
    dry_run: bool = False,
    respect_config: bool = True,
) -> MobileSyncCleanupResult:
    if respect_config and not mobile_sync_bool(settings, "delete_unreferenced_imports", True):
        return MobileSyncCleanupResult()
    imports = mobile_sync_imports(settings)
    result = MobileSyncCleanupResult()
    if not imports.exists():
        return result
    referenced = referenced_import_roots(settings, store)
    for child in sorted(imports.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        resolved = child.resolve()
        if resolved in referenced:
            result.retained_import_dirs += 1
            continue
        result.extend(cleanup_import_root(resolved, dry_run=dry_run))
    return result


def referenced_import_roots(settings: Settings, store: Store) -> set[Path]:
    imports = mobile_sync_imports(settings)
    referenced: set[Path] = set()

    def add_path(value: Any) -> None:
        if not value:
            return
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            return
        try:
            resolved = path.resolve()
            if not resolved.exists():
                return
            relative = resolved.relative_to(imports)
        except (OSError, ValueError):
            return
        if relative.parts:
            referenced.add((imports / relative.parts[0]).resolve())

    for row in store.conn.execute("SELECT metadata FROM observations WHERE source = 'mobile'"):
        metadata = json_object(row["metadata"])
        for value in metadata_values(metadata):
            add_path(value)
    for row in store.conn.execute("SELECT media_path, sample_path FROM speaker_samples"):
        add_path(row["media_path"])
        add_path(row["sample_path"])
    return referenced


def metadata_values(value: Any):
    if isinstance(value, dict):
        for item in value.values():
            yield from metadata_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from metadata_values(item)
    elif isinstance(value, str):
        yield value


def json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        data = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def cleanup_file(path: Path, result: MobileSyncCleanupResult, *, dry_run: bool) -> None:
    try:
        size = path.stat().st_size
    except OSError as exc:
        result.messages.append(f"- Could not inspect file {path}: {exc}")
        return
    if dry_run:
        result.deleted_files += 1
        result.freed_bytes += size
        if len(result.messages) < 20:
            result.messages.append(f"- Would delete file: {path} ({format_bytes(size)})")
        return
    try:
        path.unlink()
        result.deleted_files += 1
        result.freed_bytes += size
    except OSError as exc:
        result.messages.append(f"- Failed to delete file {path}: {exc}")


def mobile_sync_bool(settings: Settings, key: str, default: bool) -> bool:
    value = settings.mobile_sync.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def mobile_sync_inbox(settings: Settings) -> Path:
    return (settings.data_dir / "mobile_sync" / "inbox").resolve()


def mobile_sync_imports(settings: Settings) -> Path:
    return (settings.data_dir / "mobile_sync" / "imports").resolve()


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve())
        return True
    except ValueError:
        return False


def path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
    return total


def format_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if amount < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(amount)} B"
            return f"{amount:.1f} {unit}"
        amount /= 1024


def all_mobile_events_exist(
    settings: Settings,
    store: Store,
    events: list[dict[str, Any]],
    base_dir: Path,
) -> bool:
    if not events:
        return False
    observations = []
    for index, event in enumerate(events):
        try:
            observations.append(event_to_observation(settings, event, index, base_dir))
        except ValueError:
            return False
    keys = [(item.source, item.kind, item.source_key) for item in observations]
    return store.observations_exist(keys)


def extract_zip_safely(zip_path: Path, destination: Path) -> None:
    root = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        targets = []
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                raise ValueError(f"unsafe zip path: {member.filename}")
            targets.append((member, target))
        for member, target in targets:
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)


def find_mobile_export(root: Path) -> Path | None:
    direct = root / "mobile-export.json"
    if direct.exists():
        return direct
    matches = sorted(root.rglob("mobile-export.json"))
    return matches[0] if matches else None


def dates_from_events(events: list[dict[str, Any]]) -> set[date]:
    days: set[date] = set()
    for event in events:
        value = event.get("observed_at") or event.get("started_at") or event.get("timestamp")
        if not isinstance(value, str) or len(value) < 10:
            continue
        try:
            days.add(date.fromisoformat(value[:10]))
        except ValueError:
            continue
    if not days:
        days.add(date.today())
    return days


def parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def sanitize_filename(value: str) -> str:
    name = Path(value).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    return name or "mobile-upload.zip"


def unique_name(folder: Path, filename: str) -> str:
    candidate = filename
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    index = 1
    while (folder / candidate).exists():
        candidate = f"{stem}-{index}{suffix}"
        index += 1
    return candidate
