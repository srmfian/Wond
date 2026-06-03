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

from .audio_analysis import analyze_audio_for_day
from .config import Settings
from .mobile import event_to_observation, ingest_mobile_export, load_mobile_events
from .store import Store
from .summarizer import write_daily_report
from .timeutil import utc_iso
from .version import __version__


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


def run_sync_server(settings: Settings, host: str | None = None, port: int | None = None) -> None:
    sync_config = settings.mobile_sync
    bind_host = host or str(sync_config.get("host") or "0.0.0.0")
    bind_port = int(port if port is not None else sync_config.get("port", 8765))
    server = ThreadingHTTPServer((bind_host, bind_port), make_handler(settings))
    actual_port = int(server.server_address[1])
    token = str(sync_config.get("token") or "")
    print(f"Sync server: http://{bind_host}:{actual_port}/upload", flush=True)
    if not token:
        print("Warning: mobile_sync.token is empty; local network uploads are accepted without a token.", flush=True)
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
            path = self.path.split("?", 1)[0]
            if path == "/status":
                if not verify_api_auth(settings, self.headers, "GET", self.path, b""):
                    self.send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
                    return
                self.send_json(HTTPStatus.OK, mobile_status_payload(settings, mac_online=True))
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
            try:
                encrypted = self.headers.get("X-Wond-Encrypted") == "AESGCM-v1"
                upload_path = save_upload_stream(settings, self.rfile, length, self.headers.get("X-Filename"), encrypted)
                if not verify_upload_auth(settings, upload_path, self.headers, encrypted):
                    self.send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
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

        def log_message(self, format: str, *args) -> None:
            print(f"{self.address_string()} - {format % args}")

    return SyncRequestHandler


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
    with path.open("wb") as out:
        while remaining > 0:
            chunk = source.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("upload ended before Content-Length bytes were received")
            out.write(chunk)
            remaining -= len(chunk)
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
    zip_path.write_bytes(plaintext)
    return zip_path


def verify_upload_auth(settings: Settings, upload_path: Path, headers, encrypted: bool) -> bool:
    token = str(settings.mobile_sync.get("token") or "")
    if not token:
        return not encrypted
    timestamp = headers.get("X-Wond-Timestamp")
    body_hash = headers.get("X-Wond-Body-SHA256")
    signature = headers.get("X-Wond-Signature")
    if not timestamp or not body_hash or not signature:
        return False
    try:
        sent_at = int(timestamp)
    except ValueError:
        return False
    max_skew_seconds = 900
    if abs(int(time.time()) - sent_at) > max_skew_seconds:
        return False
    actual_hash = sha256_file(upload_path)
    if not hmac.compare_digest(actual_hash, body_hash):
        return False
    message = f"{timestamp}\n{body_hash}".encode("utf-8")
    expected = base64.b64encode(hmac.new(token.encode("utf-8"), message, hashlib.sha256).digest()).decode("ascii")
    return hmac.compare_digest(expected, signature)


def verify_api_auth(settings: Settings, headers, method: str, request_target: str, body: bytes) -> bool:
    token = str(settings.mobile_sync.get("token") or "")
    if not token:
        return False
    timestamp = headers.get("X-Wond-Timestamp")
    body_hash = headers.get("X-Wond-Body-SHA256")
    signature = headers.get("X-Wond-Signature")
    if not timestamp or not body_hash or not signature:
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
    extract_zip_safely(zip_path, import_root)
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


def json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        value = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


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


def json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
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
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if not str(target).startswith(str(destination.resolve())):
                raise ValueError(f"unsafe zip path: {member.filename}")
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
