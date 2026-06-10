from __future__ import annotations

import json
import mimetypes
import os
import secrets
import shutil
import socket
import subprocess
import time
import urllib.error
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .agent import (
    dashboard_launch_agent_label,
    dashboard_launch_agent_path,
    launch_agent_label,
    launch_agent_path,
    sync_launch_agent_label,
    sync_launch_agent_path,
)
from .audio_analysis import pending_audio_count_for_day
from .config import DEFAULT_CONFIG, Settings, load_settings
from .dashboard_search import (
    DEFAULT_SEARCH_EMBEDDING_CANDIDATES,
    SEARCH_INDEX_SOURCE_DEFAULT_PRIORITY,
    SEARCH_INDEX_SOURCE_PRIORITIES,
    SearchDocument,
    answer_citations,
    build_answer_context,
    chunk_text,
    cleanup_internal_search_embeddings,
    content_hash,
    cosine_similarity,
    ensure_search_schema,
    fallback_answer,
    index_search_documents,
    latest_reports,
    normalize_vector,
    observation_search_document,
    ollama_embed,
    ollama_generate,
    ollama_legacy_embedding,
    ollama_model_names,
    rebuild_search_index,
    report_search_documents,
    search_auto_index_limit,
    search_chunk_chars,
    search_document_fetch_limit,
    search_document_priority,
    search_documents,
    search_embedding_candidates,
    search_embedding_model_config,
    search_index_active_model,
    search_index_limit,
    search_index_source_coverage,
    search_index_status,
    search_indexed_keys,
    search_observation_priority_sql,
    search_observations,
    search_reports,
    select_search_embedding_model,
    semantic_item_payload,
    semantic_search,
    sort_search_documents_for_indexing,
)
from .dashboard_html import DASHBOARD_HTML
from .dashboard_shared import (
    clamp,
    compact,
    count_dirs,
    count_files,
    dir_size,
    http_json,
    http_json_or_error,
    http_ok,
    json_file,
    json_object,
    latest_file,
    parse_int,
    path_count,
    redact_config,
    redact_secrets,
    report_file_payload,
    row_dict,
    row_payload,
    safe_report_path,
    scalar,
    search_keywords,
    sync_health_url,
)
from .executables import find_executable
from .insights import (
    action_center_payload,
    action_inbox_payload,
    action_suggestions_payload,
    evidence_groups_payload,
    project_clusters_payload,
    repair_queue_payload,
    speaker_quality_payload,
)
from .observation_filters import visible_observations
from .personal_memory import personal_context_semantic_items, personal_memory_payload, personal_memory_post
from .project_memory import meeting_mode_payload, meeting_mode_post, project_memory_payload, project_memory_post
from .privacy import privacy_center_payload
from .recycle_bin import list_recycle_bin, purge_recycle_bin, recycle_bin_config, recycle_bin_summary
from .retention import run_retention
from .speaker_training import speaker_training_payload
from .speakers import (
    speaker_confidence_summary,
    speaker_profiles_payload,
    speaker_review_confidence_threshold,
    speaker_sample_payload,
    speaker_threshold_config,
)
from .store import Observation, Store
from .sync_server import cleanup_mobile_sync_storage, mobile_status_payload
from .timeutil import day_bounds, local_iso, now, parse_day
from .version import __version__


MAX_JSON_BYTES = 256 * 1024


@dataclass(frozen=True)
class DashboardServer:
    httpd: ThreadingHTTPServer
    url: str


@dataclass(frozen=True)
class AskClock:
    current: datetime
    timezone: str

    @property
    def today(self) -> date:
        return self.current.date()

    @property
    def yesterday(self) -> date:
        return self.today - timedelta(days=1)

    @property
    def tomorrow(self) -> date:
        return self.today + timedelta(days=1)


def run_dashboard(settings: Settings, host: str = "127.0.0.1", port: int = 8787) -> None:
    server = create_dashboard_server(settings, host=host, port=port)
    print(f"Dashboard: {server.url}", flush=True)
    try:
        server.httpd.serve_forever()
    finally:
        server.httpd.server_close()


def create_dashboard_server(settings: Settings, host: str, port: int) -> DashboardServer:
    handler = make_handler(settings)
    httpd = ThreadingHTTPServer((host, port), handler)
    actual_host, actual_port = httpd.server_address[:2]
    return DashboardServer(httpd=httpd, url=f"http://{actual_host}:{actual_port}")


def make_handler(settings: Settings):
    def current_settings() -> Settings:
        try:
            return load_settings(settings.path)
        except Exception:
            return settings

    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = f"WondDashboard/{__version__}"

        def do_GET(self) -> None:
            request_settings = current_settings()
            parsed = urlparse(self.path)
            if parsed.path in {"/", "/dashboard"}:
                self.send_html(DASHBOARD_HTML)
                return
            if parsed.path == "/api/overview":
                self.send_json(api_overview(request_settings))
                return
            if parsed.path == "/api/setup":
                self.send_json(api_setup(request_settings))
                return
            if parsed.path == "/api/action-center":
                self.send_json(action_center_payload(request_settings, query(parsed)))
                return
            if parsed.path == "/api/action-inbox":
                self.send_json(action_inbox_payload(request_settings, query(parsed)))
                return
            if parsed.path == "/api/repair-queue":
                self.send_json(repair_queue_payload(request_settings, query(parsed)))
                return
            if parsed.path == "/api/action-suggestions":
                self.send_json(action_suggestions_payload(request_settings, query(parsed)))
                return
            if parsed.path == "/api/project-clusters":
                self.send_json(project_clusters_payload(request_settings, query(parsed)))
                return
            if parsed.path == "/api/project-memory":
                self.send_json(project_memory_payload(request_settings, query(parsed)))
                return
            if parsed.path == "/api/personal-memory":
                self.send_json(personal_memory_payload(request_settings, query(parsed)))
                return
            if parsed.path == "/api/meeting-mode":
                self.send_json(meeting_mode_payload(request_settings, query(parsed)))
                return
            if parsed.path == "/api/privacy":
                self.send_json(privacy_center_payload(request_settings, query(parsed)))
                return
            if parsed.path == "/api/speaker-quality":
                self.send_json(speaker_quality_payload(request_settings, query(parsed)))
                return
            if parsed.path == "/api/today":
                self.send_json(api_today(request_settings, query(parsed)))
                return
            if parsed.path == "/api/doctor":
                self.send_json(api_doctor(request_settings))
                return
            if parsed.path == "/api/audio":
                self.send_json(api_audio(request_settings, query(parsed)))
                return
            if parsed.path == "/api/search":
                self.send_json(api_search(request_settings, query(parsed)))
                return
            if parsed.path == "/api/search-index":
                self.send_json(api_search_index(request_settings))
                return
            if parsed.path == "/api/timeline":
                self.send_json(api_timeline(request_settings, query(parsed)))
                return
            if parsed.path == "/api/daily-feedback":
                self.send_json(api_daily_feedback(request_settings, query(parsed)))
                return
            if parsed.path == "/api/reports":
                self.send_json(api_reports(request_settings, query(parsed)))
                return
            if parsed.path == "/api/sources":
                self.send_json(api_sources(request_settings))
                return
            if parsed.path == "/api/speakers":
                self.send_json(api_speakers(request_settings))
                return
            if parsed.path == "/api/speaker-training":
                self.send_json(speaker_training_payload(request_settings, query(parsed)))
                return
            if parsed.path == "/api/files":
                self.send_json(api_files(request_settings))
                return
            if parsed.path == "/api/recycle-bin":
                self.send_json(api_recycle_bin(request_settings))
                return
            if parsed.path == "/api/sync":
                self.send_json(api_sync(request_settings))
                return
            if parsed.path == "/api/mobile-status":
                self.send_json(api_mobile_status(request_settings))
                return
            if parsed.path == "/api/settings":
                self.send_json(api_settings(request_settings))
                return
            if parsed.path == "/api/maintenance":
                self.send_json(api_maintenance(request_settings))
                return
            if parsed.path.startswith("/api/speaker-sample/"):
                sample_id = parse_int(parsed.path.rsplit("/", 1)[-1])
                if sample_id is None:
                    self.send_json({"ok": False, "error": "invalid_sample_id"}, HTTPStatus.BAD_REQUEST)
                    return
                self.send_speaker_sample(sample_id)
                return
            self.send_json({"ok": False, "error": "not_found"}, HTTPStatus.NOT_FOUND)

        def do_HEAD(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/speaker-sample/"):
                sample_id = parse_int(parsed.path.rsplit("/", 1)[-1])
                if sample_id is None:
                    self.send_response(int(HTTPStatus.BAD_REQUEST))
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_speaker_sample(sample_id, include_body=False)
                return
            self.send_response(int(HTTPStatus.METHOD_NOT_ALLOWED))
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self) -> None:
            request_settings = current_settings()
            parsed = urlparse(self.path)
            try:
                payload = self.read_payload()
                if parsed.path == "/api/ask":
                    self.send_json(api_ask(request_settings, payload))
                    return
                if parsed.path == "/api/setup-token":
                    result, status = api_setup_token(request_settings)
                    self.send_json(result, status)
                    return
                if parsed.path == "/api/action":
                    result, status = api_action(request_settings, payload)
                    self.send_json(result, status)
                    return
                if parsed.path == "/api/settings":
                    result, status = api_settings_update(request_settings, payload)
                    self.send_json(result, status)
                    return
                if parsed.path == "/api/daily-feedback":
                    result, status = api_daily_feedback_post(request_settings, payload)
                    self.send_json(result, status)
                    return
                if parsed.path == "/api/project-memory":
                    result, status = project_memory_post(request_settings, payload)
                    self.send_json(result, status)
                    return
                if parsed.path == "/api/personal-memory":
                    result, status = personal_memory_post(request_settings, payload)
                    self.send_json(result, status)
                    return
                if parsed.path == "/api/meeting-mode":
                    result, status = meeting_mode_post(request_settings, payload)
                    self.send_json(result, status)
                    return
                if parsed.path == "/api/insight-state":
                    result, status = api_insight_state_post(request_settings, payload)
                    self.send_json(result, status)
                    return
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                self.send_json({"ok": False, "error": str(exc) or "invalid_json"}, HTTPStatus.BAD_REQUEST)
                return
            self.send_json({"ok": False, "error": "not_found"}, HTTPStatus.NOT_FOUND)

        def send_speaker_sample(self, sample_id: int, *, include_body: bool = True) -> None:
            request_settings = current_settings()
            store = Store(request_settings.db_path)
            try:
                row = store.get_speaker_sample(sample_id)
            finally:
                store.close()
            if row is None or not row["sample_path"]:
                self.send_json({"ok": False, "error": "sample_not_found"}, HTTPStatus.NOT_FOUND)
                return
            try:
                root = request_settings.speaker_sample_dir.resolve()
                sample = Path(str(row["sample_path"])).resolve(strict=True)
                sample.relative_to(root)
            except (FileNotFoundError, ValueError):
                self.send_json({"ok": False, "error": "sample_unavailable"}, HTTPStatus.NOT_FOUND)
                return
            self.send_file(sample, sample_content_type(sample), include_body=include_body)

        def send_file(self, path: Path, content_type: str, *, include_body: bool = True) -> None:
            size = path.stat().st_size
            byte_range = parse_range_header(self.headers.get("Range"), size)
            if byte_range == "invalid":
                self.send_response(int(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE))
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            start = 0
            end = size - 1
            status = HTTPStatus.OK
            if byte_range is not None:
                start, end = byte_range
                status = HTTPStatus.PARTIAL_CONTENT

            length = max(0, end - start + 1)
            self.send_response(int(status))
            self.send_header("Content-Type", content_type)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            if status == HTTPStatus.PARTIAL_CONTENT:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if not include_body or length <= 0:
                return
            with path.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = handle.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def read_payload(self) -> dict[str, Any]:
            length = parse_int(self.headers.get("Content-Length")) or 0
            if length <= 0:
                return {}
            if length > MAX_JSON_BYTES:
                raise ValueError("request_too_large")
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))

        def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(int(status))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def send_html(self, text: str) -> None:
            data = text.encode("utf-8")
            self.send_response(int(HTTPStatus.OK))
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt: str, *args) -> None:
            print(f"{self.address_string()} - {fmt % args}", flush=True)

    return DashboardHandler


def sample_content_type(path: Path) -> str:
    if path.suffix.lower() in {".m4a", ".mp4"}:
        return "audio/mp4"
    if path.suffix.lower() == ".mp3":
        return "audio/mpeg"
    if path.suffix.lower() == ".wav":
        return "audio/wav"
    guessed, _encoding = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def parse_range_header(value: str | None, size: int) -> tuple[int, int] | str | None:
    if not value:
        return None
    value = value.strip()
    if not value.startswith("bytes=") or "," in value:
        return "invalid"
    raw_start, separator, raw_end = value[6:].partition("-")
    if separator != "-":
        return "invalid"
    try:
        if raw_start == "":
            suffix_length = int(raw_end)
            if suffix_length <= 0:
                return "invalid"
            start = max(0, size - suffix_length)
            end = size - 1
        else:
            start = int(raw_start)
            end = int(raw_end) if raw_end else size - 1
    except ValueError:
        return "invalid"
    if start < 0 or end < start or start >= size:
        return "invalid"
    return (start, min(end, size - 1))


def query(parsed) -> dict[str, str]:
    values = parse_qs(parsed.query)
    return {key: items[-1] for key, items in values.items() if items}


def api_overview(settings: Settings) -> dict[str, Any]:
    store = Store(settings.db_path)
    try:
        today = now(settings.timezone).date()
        counts = table_counts(store)
        source_counts = source_kind_counts(store)
        audio = audio_summary(store)
        recent_runs = [row_dict(row) for row in store.latest_runs(12)]
        latest_activity = scalar(store.conn, "SELECT max(sampled_at) FROM activity_samples")
        latest_observation = scalar(store.conn, "SELECT max(observed_at) FROM observations")
        reports = report_summary(settings)
        return {
            "ok": True,
            "today": today.isoformat(),
            "counts": counts,
            "source_counts": source_counts,
            "audio": audio,
            "pending_audio_today": pending_audio_count_for_day(settings, store, today),
            "recent_runs": recent_runs,
            "latest_activity": latest_activity,
            "latest_observation": latest_observation,
            "reports": reports,
            "health": compact_health(settings),
        }
    finally:
        store.close()


def api_setup(settings: Settings) -> dict[str, Any]:
    store = Store(settings.db_path)
    try:
        counts = table_counts(store)
    finally:
        store.close()
    token_configured = bool(str(settings.mobile_sync.get("token") or "").strip())
    sync_port = int(settings.mobile_sync.get("port") or 8765)
    dashboard_port = 8787
    service_rows = setup_service_rows()
    steps = [
        setup_step("config", "配置文件", settings.path.exists(), str(settings.path)),
        setup_step("database", "本地数据库", settings.db_path.exists(), str(settings.db_path)),
        setup_step("token", "手机同步 token", token_configured, "已配置" if token_configured else "需要生成"),
        setup_step("sync", "同步服务", service_ready(service_rows, "sync"), service_message(service_rows, "sync")),
        setup_step("agent", "后台采集", service_ready(service_rows, "agent"), service_message(service_rows, "agent")),
        setup_step("dashboard", "Dashboard 服务", service_ready(service_rows, "dashboard"), service_message(service_rows, "dashboard")),
    ]
    complete = sum(1 for item in steps if item["ok"])
    return {
        "ok": True,
        "generated_at": now(settings.timezone).isoformat(timespec="seconds"),
        "summary": {
            "complete": complete,
            "total": len(steps),
            "percent": round(complete / max(1, len(steps)) * 100),
            "ready": complete == len(steps),
        },
        "steps": steps,
        "services": service_rows,
        "config": {
            "path": str(settings.path),
            "data_dir": str(settings.data_dir),
            "database": str(settings.db_path),
            "timezone": settings.timezone,
            "counts": counts,
        },
        "sync": {
            "host": str(settings.mobile_sync.get("host") or "0.0.0.0"),
            "port": sync_port,
            "token_configured": token_configured,
            "health_url": sync_health_url(settings),
            "upload_urls": setup_upload_urls(sync_port),
            "lan_addresses": lan_ip_candidates(),
        },
        "dashboard": {
            "local_url": f"http://127.0.0.1:{dashboard_port}",
            "port": dashboard_port,
        },
    }


def api_setup_token(settings: Settings) -> tuple[dict[str, Any], HTTPStatus]:
    token = secrets.token_urlsafe(32)
    try:
        document = load_config_document(settings.path)
        set_config_path(document, ["mobile_sync", "token"], token)
        save_config_document(settings.path, document)
        refreshed = load_settings(settings.path)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR
    payload = api_setup(refreshed)
    payload.update({"token": token, "token_preview": f"{token[:8]}...{token[-6:]}"})
    return payload, HTTPStatus.OK


def setup_step(key: str, title: str, ok: bool, detail: str) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "ok": bool(ok),
        "status": "ok" if ok else "warn",
        "detail": detail,
    }


def setup_service_rows() -> list[dict[str, Any]]:
    rows = []
    for key, title, label, path, action_name in [
        ("agent", "后台采集", launch_agent_label(), launch_agent_path(), "install_agent"),
        ("sync", "手机同步", sync_launch_agent_label(), sync_launch_agent_path(), "install_sync_agent"),
        ("dashboard", "Dashboard", dashboard_launch_agent_label(), dashboard_launch_agent_path(), "install_dashboard_agent"),
    ]:
        state = launchctl_state(label)
        installed = path.exists()
        loaded = state != "not loaded"
        rows.append(
            {
                "key": key,
                "title": title,
                "label": label,
                "path": str(path),
                "installed": installed,
                "state": state,
                "loaded": loaded,
                "ready": installed and loaded,
                "status": "ok" if installed and loaded else "warn" if installed else "fail",
                "action": action_name,
            }
        )
    return rows


def service_ready(rows: list[dict[str, Any]], key: str) -> bool:
    return any(row["key"] == key and row["ready"] for row in rows)


def service_message(rows: list[dict[str, Any]], key: str) -> str:
    for row in rows:
        if row["key"] == key:
            installed = "installed" if row["installed"] else "missing"
            return f"{installed}, {row['state']}"
    return "missing"


def setup_upload_urls(port: int) -> list[dict[str, str]]:
    candidates = [{"label": "本机测试", "url": f"http://127.0.0.1:{port}/upload"}]
    addresses = lan_ip_candidates()
    for address in addresses:
        candidates.append({"label": "iPhone Wi-Fi", "url": f"http://{address}:{port}/upload"})
    if not addresses:
        candidates.append({"label": "手动 Wi-Fi", "url": f"http://<Mac-LAN-IP>:{port}/upload"})
    return candidates


def lan_ip_candidates() -> list[str]:
    candidates: list[str] = []
    for interface in ("en0", "en1", "bridge100"):
        try:
            proc = subprocess.run(
                ["ipconfig", "getifaddr", interface],
                text=True,
                capture_output=True,
                check=False,
                timeout=1,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode == 0:
            add_lan_candidate(candidates, proc.stdout.strip())
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(1)
            sock.connect(("8.8.8.8", 80))
            add_lan_candidate(candidates, sock.getsockname()[0])
    except OSError:
        pass
    try:
        _hostname, _aliases, addresses = socket.gethostbyname_ex(socket.gethostname())
        for address in addresses:
            add_lan_candidate(candidates, address)
    except OSError:
        pass
    return candidates


def add_lan_candidate(candidates: list[str], value: str) -> None:
    if not is_private_ipv4(value):
        return
    if value not in candidates:
        candidates.append(value)


def is_private_ipv4(value: str) -> bool:
    parts = value.split(".")
    if len(parts) != 4:
        return False
    try:
        nums = [int(part) for part in parts]
    except ValueError:
        return False
    if any(num < 0 or num > 255 for num in nums):
        return False
    if nums[0] == 10:
        return True
    if nums[0] == 172 and 16 <= nums[1] <= 31:
        return True
    if nums[0] == 192 and nums[1] == 168:
        return True
    return False


def api_doctor(settings: Settings) -> dict[str, Any]:
    checks = doctor_checks(settings)
    severity_order = {"fail": 3, "warn": 2, "ok": 1, "info": 0}
    overall = "ok"
    if any(item["status"] == "fail" for item in checks):
        overall = "fail"
    elif any(item["status"] == "warn" for item in checks):
        overall = "warn"
    return {
        "ok": True,
        "overall": overall,
        "checks": sorted(checks, key=lambda item: (-severity_order.get(item["status"], 0), item["area"], item["name"])),
        "generated_at": now(settings.timezone).isoformat(timespec="seconds"),
    }


def doctor_text(settings: Settings) -> str:
    payload = api_doctor(settings)
    lines = [f"Doctor: {payload['overall']} ({payload['generated_at']})"]
    for item in payload["checks"]:
        lines.append(f"[{item['status'].upper()}] {item['area']} / {item['name']}: {item['message']}")
        if item.get("fix"):
            lines.append(f"  fix: {item['fix']}")
    return "\n".join(lines)


def doctor_checks(settings: Settings) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    store = Store(settings.db_path)
    try:
        checks.append(path_check("config", "Config file", settings.path, required=True))
        checks.append(path_check("database", "SQLite database", settings.db_path, required=True))
        checks.append(path_check("reports", "Report directory", settings.report_dir, required=True))
        checks.extend(launch_agent_checks())
        checks.append(http_check("sync", "Sync /health", sync_health_url(settings), expect_key="service", fix="Run python3 -m wond install-sync-agent --load."))
        checks.append(ollama_check(settings))
        checks.extend(executable_checks())
        checks.extend(data_quality_checks(settings, store))
        checks.extend(storage_checks(settings))
    finally:
        store.close()
    return checks


def api_audio(settings: Settings, params: dict[str, str]) -> dict[str, Any]:
    limit = clamp(parse_int(params.get("limit")) or 80, 1, 500)
    status_filter = params.get("status") or ""
    store = Store(settings.db_path)
    try:
        rows = audio_rows(store, limit=limit, status=status_filter)
        return {
            "ok": True,
            "summary": audio_summary(store),
            "items": rows,
        }
    finally:
        store.close()


def api_search(settings: Settings, params: dict[str, str]) -> dict[str, Any]:
    term = (params.get("q") or "").strip()
    source = (params.get("source") or "").strip()
    limit = clamp(parse_int(params.get("limit")) or 50, 1, 200)
    store = Store(settings.db_path)
    try:
        observations = search_observations(settings, store, term, source=source, limit=limit)
        reports = search_reports(settings, term, limit=20) if term else latest_reports(settings, limit=20)
        semantic = semantic_search(settings, store, term, source=source, limit=min(30, limit), auto_index=True)
        return {
            "ok": True,
            "query": term,
            "observations": observations,
            "reports": reports,
            "semantic": semantic["items"],
            "retrieval": {key: value for key, value in semantic.items() if key != "items"},
        }
    finally:
        store.close()


def api_search_index(settings: Settings) -> dict[str, Any]:
    store = Store(settings.db_path)
    try:
        ensure_search_schema(store)
        cleaned = cleanup_internal_search_embeddings(settings, store)
        return {"ok": True, "cleaned": cleaned, "index": search_index_status(settings, store)}
    finally:
        store.close()


def api_ask(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    question = str(payload.get("question") or "").strip()
    if not question:
        return {"ok": False, "error": "missing_question"}
    clock = ask_clock(settings)
    relative_days = relative_day_references(question, clock)
    wants_location = is_location_question(question)
    store = Store(settings.db_path)
    try:
        semantic = semantic_search(settings, store, question, limit=20, auto_index=True)
        if relative_days:
            semantic["items"] = semantic_items_for_relative_days(semantic.get("items", []), relative_days)
        day_observations = observations_for_relative_days(settings, store, relative_days)
        location_observations = (
            location_observations_for_relative_days(settings, store, relative_days)
            if wants_location and relative_days
            else []
        )
        if wants_location and location_observations:
            semantic["items"] = location_semantic_items(semantic.get("items", []))
        observations = merge_observation_results(
            location_observations,
            day_observations,
            search_observations(settings, store, question, limit=12),
            limit=24,
        )
        reports = merge_report_results(
            reports_for_relative_days(settings, relative_days),
            search_reports(settings, question, limit=5),
            limit=8,
        )
        personal_items = personal_context_semantic_items(settings, store, question)
    finally:
        store.close()
    semantic_items = [*personal_items, *semantic.get("items", [])]
    context = build_answer_context(observations, reports, semantic_items)
    if not context.strip():
        resolved = relative_days_summary(relative_days)
        if resolved:
            return {
                "ok": True,
                "answer": f"按当前提问时间 {clock.current.isoformat(timespec='seconds')}（{clock.timezone}），{resolved}。没有找到这些日期的本地记录。",
                "citations": [],
                "evidence_groups": evidence_groups_payload([], [], []),
                "retrieval": {key: value for key, value in semantic.items() if key != "items"},
                "time_context": ask_time_context(clock),
                "mode": "empty",
            }
        return {
            "ok": True,
            "answer": "没有找到足够相关的本地记录。建议扩大日期范围或换关键词。",
            "citations": [],
            "evidence_groups": evidence_groups_payload([], [], []),
            "retrieval": {key: value for key, value in semantic.items() if key != "items"},
            "time_context": ask_time_context(clock),
            "mode": "empty",
        }
    prompt = (
        "你是一个本地个人记忆系统的问答助手。只根据当前时间和给定本地上下文回答，不要编造。"
        "用中文，答案要简洁。最后列出用到的 evidence id。"
        "如果问题出现“今天、昨天、明天、today、yesterday、tomorrow”等相对日期，必须按下面的当前时间解释，不要按模型训练日期猜。\n\n"
        f"当前时间：\n{ask_time_context_text(clock)}\n\n"
        f"问题：{question}\n\n本地上下文：\n{context}"
    )
    try:
        answer = ollama_generate(settings, prompt, model=str(settings.audio_analysis.get("summary_model") or settings.local_ai.get("text_model") or "qwen2.5:7b"))
        mode = "semantic-rag" if semantic.get("status") == "ok" else "ollama-keyword"
    except Exception as exc:
        answer = fallback_answer(question, observations, reports, exc)
        mode = "extractive"
    return {
        "ok": True,
        "answer": answer,
        "citations": answer_citations(observations, reports, semantic_items),
        "evidence_groups": evidence_groups_payload(observations, reports, semantic_items),
        "retrieval": {key: value for key, value in semantic.items() if key != "items"},
        "time_context": ask_time_context(clock),
        "mode": mode,
    }


WEEKDAYS_ZH = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def ask_clock(settings: Settings) -> AskClock:
    return AskClock(current=now(settings.timezone), timezone=settings.timezone)


def ask_time_context(clock: AskClock) -> dict[str, str]:
    return {
        "now": clock.current.isoformat(timespec="seconds"),
        "timezone": clock.timezone,
        "today": format_prompt_day(clock.today),
        "yesterday": format_prompt_day(clock.yesterday),
        "tomorrow": format_prompt_day(clock.tomorrow),
    }


def ask_time_context_text(clock: AskClock) -> str:
    context = ask_time_context(clock)
    return "\n".join(
        [
            f"现在 = {context['now']}",
            f"时区 = {context['timezone']}",
            f"今天 = {context['today']}",
            f"昨天 = {context['yesterday']}",
            f"明天 = {context['tomorrow']}",
        ]
    )


def format_prompt_day(day: date) -> str:
    return f"{day.isoformat()} ({WEEKDAYS_ZH[day.weekday()]})"


def relative_day_references(question: str, clock: AskClock) -> list[tuple[str, date]]:
    text = question.lower()
    references: list[tuple[str, date]] = []
    seen: set[date] = set()

    def add(label: str, day: date) -> None:
        if day in seen:
            return
        seen.add(day)
        references.append((label, day))

    if contains_any(text, ("今天", "今日", "今晚", "今早", "今晨", "today")):
        add("今天", clock.today)
    if contains_any(text, ("昨天", "昨日", "昨晚", "yesterday")):
        add("昨天", clock.yesterday)
    if contains_any(text, ("前天", "day before yesterday")):
        add("前天", clock.today - timedelta(days=2))
    if contains_any(text, ("明天", "明日", "tomorrow")):
        add("明天", clock.tomorrow)
    return references


def contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def is_location_question(question: str) -> bool:
    text = question.lower()
    return contains_any(
        text,
        (
            "哪里",
            "哪儿",
            "去哪",
            "去了",
            "到过",
            "位置",
            "定位",
            "地点",
            "地方",
            "where",
            "location",
            "place",
        ),
    )


def semantic_items_for_relative_days(
    items: list[dict[str, Any]],
    relative_days: list[tuple[str, date]],
) -> list[dict[str, Any]]:
    day_keys = {day.isoformat() for _label, day in relative_days}
    filtered = []
    for item in items:
        observed_day = str(item.get("observed_at") or "")[:10]
        path = str(item.get("path") or "")
        title = str(item.get("title") or "")
        if observed_day in day_keys or any(day_key in path or day_key in title for day_key in day_keys):
            filtered.append(item)
    return filtered


def location_semantic_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered = []
    for item in items:
        kind = str(item.get("kind") or "")
        source = str(item.get("source") or "")
        text = str(item.get("text") or "").lower()
        if kind in {"location_sample", "photo_location"}:
            filtered.append(item)
        elif source == "report" and ("location sample" in text or "photo location" in text or "位置" in text):
            filtered.append(item)
    return filtered


def observations_for_relative_days(
    settings: Settings,
    store: Store,
    relative_days: list[tuple[str, date]],
    *,
    limit_per_day: int = 40,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for label, day in relative_days:
        start, end = day_bounds(day, settings.timezone)
        marker = f"{label}={day.isoformat()}"
        rows = visible_observations(settings, store.observations_between(local_iso(start), local_iso(end)))
        for row in rows[:limit_per_day]:
            observations.append(row_payload(row, extra={"date_context": marker}))
    return observations


def location_observations_for_relative_days(
    settings: Settings,
    store: Store,
    relative_days: list[tuple[str, date]],
    *,
    limit_per_day: int = 60,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for label, day in relative_days:
        start, end = day_bounds(day, settings.timezone)
        marker = f"{label}={day.isoformat()}"
        rows = store.conn.execute(
            """
            SELECT *
            FROM observations
            WHERE observed_at >= ?
              AND observed_at < ?
              AND (
                kind IN ('location_sample', 'photo_location')
                OR coalesce(location, '') != ''
              )
            ORDER BY
              CASE WHEN kind IN ('location_sample', 'photo_location') THEN 0 ELSE 1 END,
              observed_at ASC,
              id ASC
            LIMIT ?
            """,
            (local_iso(start), local_iso(end), limit_per_day),
        )
        for row in rows:
            observations.append(row_payload(row, extra={"date_context": marker}))
    return observations


def reports_for_relative_days(settings: Settings, relative_days: list[tuple[str, date]]) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    seen: set[str] = set()
    for label, day in relative_days:
        marker = f"{label}={day.isoformat()}"
        day_key = day.isoformat()
        candidates = [
            settings.report_dir / f"{day_key}.md",
            settings.summary_dir / "daily" / f"{day_key}.md",
            settings.summary_dir / "email" / f"daily-{day_key}.md",
            settings.summary_dir / "feedback" / f"{day_key}.md",
        ]
        for path in candidates:
            if not path.exists() or str(path) in seen:
                continue
            seen.add(str(path))
            item = report_file_payload(settings, path)
            item["date_context"] = marker
            item["snippet"] = compact(path.read_text(encoding="utf-8", errors="replace"), 700)
            reports.append(item)
    return reports


def merge_observation_results(*groups: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[Any] = set()
    for group in groups:
        for item in group:
            key = item.get("id") or (item.get("source"), item.get("kind"), item.get("source_key"))
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= limit:
                return merged
    return merged


def merge_report_results(*groups: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            key = str(item.get("path") or item.get("name") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= limit:
                return merged
    return merged


def relative_days_summary(relative_days: list[tuple[str, date]]) -> str:
    return "、".join(f"{label}={format_prompt_day(day)}" for label, day in relative_days)


def api_today(settings: Settings, params: dict[str, str]) -> dict[str, Any]:
    target = parse_day(params.get("date") or "today", settings.timezone)
    start, end = day_bounds(target, settings.timezone)
    term = (params.get("q") or "").strip()
    time_from = parse_clock_minutes(params.get("time_from"))
    time_to = parse_clock_minutes(params.get("time_to"))
    store = Store(settings.db_path)
    try:
        events: list[dict[str, Any]] = []
        observations = visible_observations(settings, store.observations_between(local_iso(start), local_iso(end)))
        for row in observations:
            event = today_event_from_observation(row, store)
            if event is not None:
                events.append(event)
        events.extend(app_activity_events(store.activity_between(local_iso(start), local_iso(end))))
        events = [event for event in events if event_in_filters(event, term=term, time_from=time_from, time_to=time_to)]
        events.sort(key=lambda item: (str(item.get("time") or ""), int(item.get("rank") or 50), str(item.get("id") or "")))
        by_category: dict[str, int] = {}
        for event in events:
            category = str(event.get("category") or "other")
            by_category[category] = by_category.get(category, 0) + 1
        feedback = [feedback_payload(row) for row in store.daily_feedback_for_date(target.isoformat())]
        return {
            "ok": True,
            "date": target.isoformat(),
            "generated_at": now(settings.timezone).isoformat(timespec="seconds"),
            "filters": {
                "q": term,
                "time_from": params.get("time_from") or "",
                "time_to": params.get("time_to") or "",
            },
            "summary": {
                "total": len(events),
                "by_category": by_category,
                "first": events[0]["time"] if events else None,
                "last": events[-1]["time"] if events else None,
                "audio": audio_summary(store),
                "pending_audio_today": pending_audio_count_for_day(settings, store, target),
            },
            "events": events[:1500],
            "feedback": feedback,
        }
    finally:
        store.close()


def api_timeline(settings: Settings, params: dict[str, str]) -> dict[str, Any]:
    target = parse_day(params.get("date") or "today", settings.timezone)
    start, end = day_bounds(target, settings.timezone)
    store = Store(settings.db_path)
    try:
        observations = visible_observations(settings, store.observations_between(local_iso(start), local_iso(end)))
        activity = store.activity_between(local_iso(start), local_iso(end))
        events = []
        for row in observations:
            meta = json_object(row["metadata"])
            events.append(
                {
                    "time": row["observed_at"],
                    "type": "observation",
                    "source": row["source"],
                    "kind": row["kind"],
                    "title": row["title"] or row["subtitle"] or row["actor"] or row["kind"],
                    "body": compact(row["body"], 240),
                    "status": meta.get("audio_analysis", {}).get("status") if isinstance(meta.get("audio_analysis"), dict) else None,
                }
            )
        for row in activity:
            events.append(
                {
                    "time": row["sampled_at"],
                    "type": "activity",
                    "source": "activity",
                    "kind": "foreground_app",
                    "title": row["app"],
                    "body": compact(row["window_title"], 180),
                }
            )
        events.sort(key=lambda item: item["time"])
        return {"ok": True, "date": target.isoformat(), "events": events[:1200]}
    finally:
        store.close()


def api_daily_feedback(settings: Settings, params: dict[str, str]) -> dict[str, Any]:
    target = parse_day(params.get("date") or "today", settings.timezone)
    store = Store(settings.db_path)
    try:
        return {
            "ok": True,
            "date": target.isoformat(),
            "items": [feedback_payload(row) for row in store.daily_feedback_for_date(target.isoformat())],
        }
    finally:
        store.close()


def api_daily_feedback_post(settings: Settings, payload: dict[str, Any]) -> tuple[dict[str, Any], HTTPStatus]:
    target = parse_day(str(payload.get("date") or "today"), settings.timezone)
    category = str(payload.get("category") or "").strip().lower()
    allowed = {"important", "unimportant", "wrong", "correction"}
    if category not in allowed:
        return {"ok": False, "error": "invalid_category"}, HTTPStatus.BAD_REQUEST
    note = str(payload.get("note") or "").strip()
    if not note:
        return {"ok": False, "error": "missing_note"}, HTTPStatus.BAD_REQUEST
    source_ref = str(payload.get("source_ref") or "").strip() or None
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    store = Store(settings.db_path)
    try:
        row = store.add_daily_feedback(
            feedback_date=target.isoformat(),
            category=category,
            note=note,
            source_ref=source_ref,
            metadata=metadata,
        )
        feedback = feedback_payload(row)
        store.upsert_observations(
            [
                Observation(
                    source="feedback",
                    kind="daily_feedback",
                    source_key=f"daily-feedback:{feedback['id']}",
                    observed_at=feedback["created_at"],
                    title=feedback_title(category, target.isoformat()),
                    subtitle=target.isoformat(),
                    body=note,
                    metadata={
                        "feedback_date": target.isoformat(),
                        "category": category,
                        "source_ref": source_ref,
                        **metadata,
                    },
                )
            ]
        )
        write_feedback_markdown(settings, target.isoformat(), store.daily_feedback_for_date(target.isoformat()))
        return {"ok": True, "feedback": feedback}, HTTPStatus.OK
    finally:
        store.close()


def api_insight_state_post(settings: Settings, payload: dict[str, Any]) -> tuple[dict[str, Any], HTTPStatus]:
    item_id = str(payload.get("item_id") or "").strip()
    item_type = str(payload.get("item_type") or "").strip()
    status_value = str(payload.get("status") or "open").strip()
    if not item_id:
        return {"ok": False, "error": "item_id_required"}, HTTPStatus.BAD_REQUEST
    if item_type not in {"suggestion", "project", "repair", "quick_tag", "speaker"}:
        return {"ok": False, "error": "invalid_item_type"}, HTTPStatus.BAD_REQUEST
    if status_value not in {"open", "snoozed", "done", "archived", "dismissed"}:
        return {"ok": False, "error": "invalid_status"}, HTTPStatus.BAD_REQUEST
    pinned_raw = payload.get("pinned")
    pinned = None if pinned_raw is None else bool(pinned_raw)
    note = payload.get("note")
    if note is not None:
        note = str(note).strip()
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    store = Store(settings.db_path)
    try:
        row = store.set_insight_state(
            item_id=item_id,
            item_type=item_type,
            status=status_value,
            pinned=pinned,
            note=note,
            metadata=metadata,
        )
        return {"ok": True, "state": insight_state_payload(row)}, HTTPStatus.OK
    finally:
        store.close()


def insight_state_payload(row) -> dict[str, Any]:
    return {
        "item_id": row["item_id"],
        "item_type": row["item_type"],
        "status": row["status"],
        "pinned": bool(row["pinned"]),
        "note": row["note"] or "",
        "updated_at": row["updated_at"],
    }


def today_event_from_observation(row, store: Store | None = None) -> dict[str, Any] | None:
    source = str(row["source"] or "")
    kind = str(row["kind"] or "")
    meta = json_object(row["metadata"])
    analysis = meta.get("audio_analysis") if isinstance(meta.get("audio_analysis"), dict) else {}
    category = observation_category(source, kind)
    title = row["title"] or row["subtitle"] or row["actor"] or f"{source}/{kind}"
    body = row["body"] or ""
    status_value = None
    if source == "mobile" and kind == "audio_segment":
        status_value = analysis.get("status") or "pending"
        title = audio_event_title(row, analysis)
        body = analysis.get("summary") or analysis.get("local_summary") or analysis.get("openai_summary") or body
        if not body and status_value == "pending":
            body = "等待 Mac 端转写/摘要"
        if not body and analysis.get("error"):
            body = str(analysis.get("error"))
    elif category == "location":
        body = row["location"] or location_from_metadata(meta) or body
    elif category == "file":
        body = body or str(meta.get("path") or meta.get("file_path") or meta.get("resolved_media_path") or "")
    elif source == "feedback":
        status_value = meta.get("category")

    payload = {
        "id": f"obs-{row['id']}",
        "time": row["observed_at"],
        "end": row["ended_at"],
        "category": category,
        "source": source,
        "kind": kind,
        "title": compact(title, 180),
        "body": compact(body, 700),
        "status": status_value,
        "location": row["location"],
        "actor": row["actor"],
        "app": row["app"],
        "rank": category_rank(category),
    }
    speaker_names = store.speaker_names_for_observation(int(row["id"])) if store is not None else None
    speakers = audio_speaker_labels(analysis, speaker_names)
    if speakers:
        payload["speakers"] = speakers
    return payload


def audio_event_title(row, analysis: dict[str, Any]) -> str:
    duration = analysis.get("duration_seconds")
    if duration is None:
        meta = json_object(row["metadata"])
        duration = meta.get("duration_seconds")
    suffix = f" · {format_duration_seconds(duration)}" if duration else ""
    return f"录音 {clock_label(row['observed_at'])}{suffix}"


def audio_speaker_labels(analysis: dict[str, Any], latest: dict[str, Any] | None = None) -> list[str]:
    labels: list[str] = []
    timeline = analysis.get("audio_timeline") if isinstance(analysis.get("audio_timeline"), dict) else {}
    segments = timeline.get("speech_segments") if isinstance(timeline.get("speech_segments"), list) else []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        overlap_speakers = segment.get("overlap_speakers")
        if segment.get("overlap") and isinstance(overlap_speakers, list):
            display = " + ".join(
                speaker_display_from_latest(latest, segment, item) for item in overlap_speakers if str(item or "").strip()
            )
            if display and display not in labels:
                labels.append(display)

    speakers = analysis.get("speakers")
    if isinstance(speakers, list):
        for item in speakers:
            if not isinstance(item, dict):
                continue
            mapped = mapped_speaker_row(latest, item)
            label = mapped["display_name"] if mapped is not None else item.get("speaker_name") or item.get("local_label")
            if isinstance(label, str) and label.strip() and label.strip() not in labels:
                labels.append(label.strip())

    if labels:
        return labels[:6]
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        mapped = mapped_speaker_row(latest, segment)
        label = mapped["display_name"] if mapped is not None else segment.get("speaker_name") or segment.get("speaker")
        if isinstance(label, str) and label.strip() and label.strip() not in labels:
            labels.append(label.strip())
    return labels[:6]


def speaker_display_from_latest(latest: dict[str, Any] | None, item: dict[str, Any], label: Any) -> str:
    if latest:
        mapped = latest.get(speaker_lookup_key(item, label)) or latest.get(str(label))
        if mapped is not None and mapped["display_name"]:
            return str(mapped["display_name"]).strip()
    return str(label).strip()


def mapped_speaker_row(latest: dict[str, Any] | None, item: dict[str, Any]):
    if not latest:
        return None
    for key in speaker_lookup_keys(item):
        mapped = latest.get(key)
        if mapped is not None:
            return mapped
    return None


def speaker_lookup_keys(item: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for raw in (item.get("speaker_group_label"), item.get("speaker_local_label"), item.get("local_label"), item.get("speaker")):
        if raw is not None:
            value = str(raw)
            if value and value not in keys:
                keys.append(value)
    scoped = speaker_lookup_key(item, item.get("speaker_local_label") or item.get("local_label") or item.get("speaker"))
    if scoped and scoped not in keys:
        keys.insert(0, scoped)
    return keys


def speaker_lookup_key(item: dict[str, Any], label: Any) -> str:
    scope = str(item.get("speaker_scope") or "").strip()
    raw = str(label or "").strip()
    return f"{scope}:{raw}" if scope and raw else raw


def observation_category(source: str, kind: str) -> str:
    if source == "feedback":
        return "feedback"
    if source == "mobile" and kind == "audio_segment":
        return "audio"
    if kind in {"location_sample", "photo_location"}:
        return "location"
    if source == "messages" or kind == "message":
        return "chat"
    if source == "reminders" or kind == "task":
        return "reminder"
    if source == "calendar" or kind == "event":
        return "calendar"
    if source in {"filesystem", "local_ai", "openai"} or kind in {"file_modified", "media_analysis"}:
        return "file"
    if source in {"browser"} or kind == "web_visit":
        return "web"
    if source == "apple_mail" or kind == "email":
        return "mail"
    if source == "system" or kind == "collector_error":
        return "system"
    if kind == "bookmark":
        return "bookmark"
    return "other"


def category_rank(category: str) -> int:
    ranks = {
        "calendar": 5,
        "reminder": 8,
        "app": 10,
        "audio": 20,
        "chat": 30,
        "file": 40,
        "location": 50,
        "bookmark": 55,
        "mail": 60,
        "web": 70,
        "feedback": 80,
        "system": 90,
    }
    return ranks.get(category, 75)


def app_activity_events(rows) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    previous_at: datetime | None = None
    for row in rows:
        sampled_at = parse_iso_datetime(row["sampled_at"])
        app = str(row["app"] or "Unknown")
        title = str(row["window_title"] or "")
        start_new = current is None or current.get("app") != app
        if current is not None and sampled_at is not None and previous_at is not None:
            start_new = start_new or (sampled_at - previous_at).total_seconds() > 20 * 60
        if start_new:
            if current is not None:
                events.append(finalize_app_event(current))
            current = {
                "id": f"app-{row['id']}",
                "time": row["sampled_at"],
                "end": row["sampled_at"],
                "app": app,
                "title_text": title,
                "samples": 1,
            }
        else:
            current["end"] = row["sampled_at"]
            current["samples"] = int(current.get("samples") or 0) + 1
            if title:
                current["title_text"] = title
        previous_at = sampled_at
    if current is not None:
        events.append(finalize_app_event(current))
    return events


def finalize_app_event(raw: dict[str, Any]) -> dict[str, Any]:
    start_dt = parse_iso_datetime(raw.get("time"))
    end_dt = parse_iso_datetime(raw.get("end"))
    minutes = None
    if start_dt is not None and end_dt is not None:
        minutes = max(0, int(round((end_dt - start_dt).total_seconds() / 60)))
    body = compact(raw.get("title_text") or "", 420)
    if minutes and minutes >= 2:
        body = compact(f"{body} · 约 {minutes} 分钟", 420) if body else f"约 {minutes} 分钟"
    return {
        "id": raw["id"],
        "time": raw["time"],
        "end": raw["end"] if raw["end"] != raw["time"] else None,
        "category": "app",
        "source": "activity",
        "kind": "foreground_app",
        "title": raw["app"],
        "body": body,
        "status": None,
        "location": None,
        "actor": None,
        "app": raw["app"],
        "rank": category_rank("app"),
    }


def event_in_filters(event: dict[str, Any], *, term: str, time_from: int | None, time_to: int | None) -> bool:
    if time_from is not None or time_to is not None:
        event_minutes = minutes_from_iso(event.get("time"))
        if event_minutes is None:
            return False
        if time_from is not None and time_to is not None:
            if time_from <= time_to:
                if not (time_from <= event_minutes <= time_to):
                    return False
            elif not (event_minutes >= time_from or event_minutes <= time_to):
                return False
        elif time_from is not None and event_minutes < time_from:
            return False
        elif time_to is not None and event_minutes > time_to:
            return False
    if not term:
        return True
    haystack = " ".join(
        str(event.get(key) or "")
        for key in ("time", "category", "source", "kind", "title", "body", "status", "location", "actor", "app", "speakers")
    ).lower()
    return all(keyword.lower() in haystack for keyword in search_keywords(term))


def parse_clock_minutes(value: Any) -> int | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    parts = raw.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except (TypeError, ValueError):
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return hour * 60 + minute


def minutes_from_iso(value: Any) -> int | None:
    text = str(value or "")
    marker = text.find("T")
    if marker < 0 or len(text) < marker + 6:
        return None
    return parse_clock_minutes(text[marker + 1 : marker + 6])


def parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def clock_label(value: Any) -> str:
    text = str(value or "")
    marker = text.find("T")
    if marker >= 0 and len(text) >= marker + 6:
        return text[marker + 1 : marker + 6]
    return text


def format_duration_seconds(value: Any) -> str:
    try:
        seconds = int(round(float(value)))
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def location_from_metadata(meta: dict[str, Any]) -> str:
    location = meta.get("location")
    if isinstance(location, dict):
        for key in ("address", "formatted_address", "place_name", "name"):
            value = location.get(key)
            if value:
                return str(value)
        lat = location.get("latitude")
        lon = location.get("longitude")
        if lat is not None and lon is not None:
            return f"{lat},{lon}"
    return ""


def feedback_title(category: str, feedback_date: str) -> str:
    labels = {
        "important": "重要总结反馈",
        "unimportant": "不重要总结反馈",
        "wrong": "错误总结反馈",
        "correction": "纠正反馈",
    }
    return f"{labels.get(category, '每日反馈')} · {feedback_date}"


def feedback_payload(row) -> dict[str, Any]:
    payload = row_dict(row)
    payload["metadata"] = json_object(payload.get("metadata"))
    return payload


def write_feedback_markdown(settings: Settings, feedback_date: str, rows) -> Path:
    root = settings.summary_dir / "feedback"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{feedback_date}.md"
    lines = [f"# Daily Feedback {feedback_date}", ""]
    for row in sorted(rows, key=lambda item: str(item["created_at"])):
        created = clock_label(row["created_at"])
        source_ref = f" [{row['source_ref']}]" if row["source_ref"] else ""
        lines.append(f"- {created} {row['category']}{source_ref}: {row['note']}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def api_reports(settings: Settings, params: dict[str, str]) -> dict[str, Any]:
    selected = params.get("path")
    files = latest_reports(settings, limit=200)
    content = ""
    selected_path = ""
    path = None
    if selected:
        path = safe_report_path(settings, selected)
    if (path is None or not path.exists()) and files:
        path = safe_report_path(settings, files[0]["path"])
    if path and path.exists():
        content = path.read_text(encoding="utf-8", errors="replace")
        selected_path = str(path.relative_to(settings.path.parent))
    return {"ok": True, "files": files, "content": content, "selected": selected_path}


def api_sources(settings: Settings) -> dict[str, Any]:
    store = Store(settings.db_path)
    try:
        rows = source_status_rows(settings, store)
        return {"ok": True, "sources": rows}
    finally:
        store.close()


def api_speakers(settings: Settings) -> dict[str, Any]:
    thresholds = speaker_threshold_config(settings)
    confidence_threshold = speaker_review_confidence_threshold(settings)
    store = Store(settings.db_path)
    try:
        speakers = []
        for row in store.list_speakers():
            stats = store.speaker_sample_evidence_stats(int(row["id"]))
            embedding_count = int(
                scalar(store.conn, "SELECT count(*) FROM speaker_embeddings WHERE speaker_id = ?", (int(row["id"]),)) or 0
            )
            speakers.append(
                row_payload(
                    row,
                    extra={
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
        matches = [row_dict(row) for row in store.list_speaker_match_decisions(50)]
        samples = [
            item
            for item in (speaker_sample_payload(row) for row in store.list_speaker_samples(None))
            if (item.get("metadata") or {}).get("sample_role") != "mixed_parent_archived"
        ]
        return {
            "ok": True,
            "speakers": speakers,
            "matches": matches,
            "profiles": speaker_profiles_payload(store, confidence_threshold=confidence_threshold),
            "samples": samples,
            "config": thresholds,
        }
    finally:
        store.close()


def api_files(settings: Settings) -> dict[str, Any]:
    store = Store(settings.db_path)
    try:
        media_count = scalar(store.conn, "SELECT count(*) FROM observations WHERE source = 'local_ai' AND kind = 'media_analysis'")
        recent = [
            row_payload(row)
            for row in store.conn.execute(
                """
                SELECT *
                FROM observations
                WHERE source IN ('filesystem', 'local_ai', 'openai')
                ORDER BY observed_at DESC
                LIMIT 120
                """
            )
        ]
        return {
            "ok": True,
            "watch_paths": [str(path) for path in settings.watch_paths],
            "file_analysis": redact_config(settings.file_analysis),
            "media_analysis_count": media_count,
            "state": json_file(settings.data_dir / "file_analysis_state.json"),
            "recent": recent,
        }
    finally:
        store.close()


def api_recycle_bin(settings: Settings) -> dict[str, Any]:
    entries = list_recycle_bin(settings)
    purge_preview = purge_recycle_bin(settings, dry_run=True)
    return {
        "ok": True,
        "config": recycle_bin_config(settings),
        "summary": recycle_bin_summary(settings, entries),
        "entries": entries[:200],
        "purge_preview": {
            "deleted_files": purge_preview.deleted_files,
            "deleted_manifests": purge_preview.deleted_manifests,
            "deleted_dirs": purge_preview.deleted_dirs,
            "freed_bytes": purge_preview.freed_bytes,
            "retained_files": purge_preview.retained_files,
            "lines": purge_preview.lines(dry_run=True),
            "errors": purge_preview.errors,
        },
    }


def api_sync(settings: Settings) -> dict[str, Any]:
    store = Store(settings.db_path)
    try:
        health = http_json_or_error(sync_health_url(settings), timeout=2)
        sync_online = bool(health.get("ok") and not health.get("error"))
        payload = mobile_status_payload(settings, store=store, mac_online=sync_online)
        cleanup_preview = cleanup_mobile_sync_storage(
            settings,
            store,
            dry_run=True,
            clean_inbox=True,
            clean_imports=True,
        )
        storage = dict(payload.get("storage") or {})
        storage.update(mobile_sync_storage(settings, store))
        payload.update(
            {
                "ok": True,
                "health": health,
                "sync_health": health,
                "config": redact_config(settings.mobile_sync),
                "storage": storage,
                "pending_server_import_files": storage.get("inbox_files", 0),
                "cleanup_preview": {
                    "deleted_files": cleanup_preview.deleted_files,
                    "deleted_dirs": cleanup_preview.deleted_dirs,
                    "freed_bytes": cleanup_preview.freed_bytes,
                    "retained_import_dirs": cleanup_preview.retained_import_dirs,
                    "lines": cleanup_preview.lines(dry_run=True),
                },
                "recent_mobile": [
                    row_payload(row)
                    for row in store.conn.execute(
                        """
                        SELECT *
                        FROM observations
                        WHERE source = 'mobile'
                        ORDER BY captured_at DESC
                        LIMIT 80
                        """
                    )
                ],
            }
        )
        return payload
    finally:
        store.close()


def api_mobile_status(settings: Settings) -> dict[str, Any]:
    store = Store(settings.db_path)
    try:
        payload = mobile_status_payload(settings, store=store, mac_online=http_ok(sync_health_url(settings)))
        payload["sync_health"] = http_json_or_error(sync_health_url(settings), timeout=2)
        payload["config"] = redact_config(settings.mobile_sync)
        cleanup_preview = cleanup_mobile_sync_storage(
            settings,
            store,
            dry_run=True,
            clean_inbox=True,
            clean_imports=True,
        )
        payload["cleanup_preview"] = {
            "deleted_files": cleanup_preview.deleted_files,
            "deleted_dirs": cleanup_preview.deleted_dirs,
            "freed_bytes": cleanup_preview.freed_bytes,
            "retained_import_dirs": cleanup_preview.retained_import_dirs,
            "lines": cleanup_preview.lines(dry_run=True),
        }
        return payload
    finally:
        store.close()


def api_settings(settings: Settings) -> dict[str, Any]:
    raw = redact_secrets(settings.raw)
    return {
        "ok": True,
        "config_path": str(settings.path),
        "data_dir": str(settings.data_dir),
        "settings": raw,
        "editable": editable_settings_schema(),
    }


def api_settings_update(settings: Settings, payload: dict[str, Any]) -> tuple[dict[str, Any], HTTPStatus]:
    updates = payload.get("updates")
    if not isinstance(updates, list) or not updates:
        return {"ok": False, "error": "updates_required"}, HTTPStatus.BAD_REQUEST
    fields = {field["key"]: field for field in editable_settings_schema()}
    document = load_config_document(settings.path)
    merged = deep_merge_config(DEFAULT_CONFIG, document)
    changed = []
    for item in updates:
        if not isinstance(item, dict):
            return {"ok": False, "error": "invalid_update"}, HTTPStatus.BAD_REQUEST
        key = str(item.get("key") or item.get("path") or "").strip()
        field = fields.get(key)
        if field is None:
            return {"ok": False, "error": f"unsupported_setting:{key}"}, HTTPStatus.BAD_REQUEST
        try:
            value = normalize_setting_value(field, item.get("value"))
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "field": key}, HTTPStatus.BAD_REQUEST
        before = get_config_path(merged, field["path"])
        if before != value:
            set_config_path(document, field["path"], value)
            set_config_path(merged, field["path"], value)
            changed.append(
                {
                    "key": key,
                    "label": field["label"],
                    "before": redact_secrets(before, key),
                    "after": redact_secrets(value, key),
                }
            )
    if changed:
        save_config_document(settings.path, document)
    refreshed = load_settings(settings.path)
    result = api_settings(refreshed)
    result.update({"changed": changed, "changed_count": len(changed)})
    return result, HTTPStatus.OK


def editable_field(path: str, field_type: str, label: str, **extra: Any) -> dict[str, Any]:
    parts = path.split(".")
    field = {
        "key": path,
        "path": parts,
        "group": extra.pop("group", parts[0]),
        "type": field_type,
        "label": label,
    }
    field.update(extra)
    return field


def editable_settings_schema() -> list[dict[str, Any]]:
    return [
        editable_field("dashboard.language", "choice", "界面语言", options=["en", "zh", "ja", "ko"]),
        editable_field("timezone", "string", "时区", format="timezone", placeholder="Asia/Tokyo"),
        editable_field("collectors.foreground_app", "bool", "采集前台 App"),
        editable_field("collectors.calendar", "bool", "采集日历"),
        editable_field("collectors.reminders", "bool", "采集提醒事项"),
        editable_field("collectors.browsers", "bool", "采集浏览器"),
        editable_field("collectors.recent_files", "bool", "采集最近文件"),
        editable_field("collectors.messages", "bool", "采集 Messages"),
        editable_field("collectors.apple_mail", "bool", "采集 Apple Mail"),
        editable_field("collectors.photo_locations", "bool", "采集照片位置"),
        editable_field("browser_profiles.chrome", "bool", "Chrome"),
        editable_field("browser_profiles.brave", "bool", "Brave"),
        editable_field("browser_profiles.edge", "bool", "Edge"),
        editable_field("browser_profiles.safari", "bool", "Safari"),
        editable_field("watch_paths", "list_string", "监控路径", rows=4, placeholder="~/Desktop\n~/Documents\n~/Downloads"),
        editable_field("agent.sample_interval_seconds", "int", "App 采样间隔", min=5, max=3600, unit="s"),
        editable_field("agent.collect_every_seconds", "int", "采集间隔", min=30, max=86400, unit="s"),
        editable_field("agent.summary_every_seconds", "int", "摘要间隔", min=60, max=86400, unit="s"),
        editable_field("agent.compaction_every_seconds", "int", "长期记忆间隔", min=300, max=604800, unit="s"),
        editable_field("agent.retention_every_seconds", "int", "保留清理间隔", min=3600, max=604800, unit="s"),
        editable_field("limits.browser_visits", "int", "浏览器记录上限", min=0, max=50000),
        editable_field("limits.recent_files", "int", "最近文件记录上限", min=0, max=50000),
        editable_field("limits.recent_files_scan_files", "int", "最近文件扫描文件数", min=100, max=500000),
        editable_field("limits.recent_files_scan_seconds", "int", "最近文件扫描秒数", min=1, max=600, unit="s"),
        editable_field("limits.messages", "int", "Messages 上限", min=0, max=50000),
        editable_field("limits.mail_messages", "int", "邮件上限", min=0, max=50000),
        editable_field("limits.photo_locations", "int", "照片位置上限", min=0, max=50000),
        editable_field("retention.enabled", "bool", "启用长期保留"),
        editable_field("retention.raw_observations_days", "int", "原始事件保留天数", min=1, max=3650, unit="d"),
        editable_field("retention.activity_samples_days", "int", "App 样本保留天数", min=1, max=3650, unit="d"),
        editable_field("retention.detailed_reports_days", "int", "详细报告保留天数", min=1, max=3650, unit="d"),
        editable_field("retention.collector_runs_days", "int", "运行记录保留天数", min=1, max=3650, unit="d"),
        editable_field("retention.agent_logs_max_mb", "int", "单个日志最大体积", min=1, max=1024, unit="MB"),
        editable_field("retention.require_daily_summary_before_prune", "bool", "清理前要求日报存在"),
        editable_field("retention.vacuum_after_prune", "bool", "清理后压缩数据库"),
        editable_field("personal_memory.enabled", "bool", "启用个人记忆"),
        editable_field("personal_memory.candidate_sources", "list_string", "候选提取来源", rows=6, placeholder="mobile\napple_mail\nmessages"),
        editable_field("personal_memory.max_candidates_per_day", "int", "每日候选上限", min=1, max=80),
        editable_field("personal_memory.qa_include_confirmed", "bool", "问答读取确认记忆"),
        editable_field("personal_memory.qa_include_profile", "bool", "问答读取个人档案"),
        editable_field("personal_memory.qa_memory_limit", "int", "问答记忆上限", min=1, max=40),
        editable_field("personal_memory.high_sensitivity_requires_confirmation", "bool", "高敏必须确认"),
        editable_field("personal_memory.auto_link_speakers", "bool", "自动链接说话人"),
        editable_field("file_analysis.enabled", "bool", "启用文件分析"),
        editable_field("file_analysis.scan_interval_seconds", "int", "扫描间隔", min=10, max=86400, unit="s"),
        editable_field("file_analysis.stability_seconds", "int", "文件稳定等待", min=0, max=3600, unit="s"),
        editable_field("file_analysis.max_files_per_scan", "int", "每次最多分析文件", min=1, max=200),
        editable_field("file_analysis.retry_after_seconds", "int", "失败重试间隔", min=0, max=86400, unit="s"),
        editable_field("file_analysis.lock_stale_seconds", "int", "锁过期时间", min=60, max=86400, unit="s"),
        editable_field("file_analysis.run_stale_seconds", "int", "运行记录过期", min=60, max=86400, unit="s"),
        editable_field("file_analysis.analysis_copy_dir", "string", "分析副本目录"),
        editable_field("file_analysis.delete_after_analysis", "bool", "分析后清理托管文件"),
        editable_field("file_analysis.include_suffixes", "list_string", "包含后缀", rows=6, placeholder=".pdf\n.docx\n.m4a"),
        editable_field("file_analysis.exclude_suffixes", "list_string", "排除后缀", rows=4, placeholder=".tmp\n.part"),
        editable_field("file_analysis.exclude_dirs", "list_string", "排除目录", rows=5, placeholder=".git\nnode_modules"),
        editable_field("recycle_bin.enabled", "bool", "启用回收箱"),
        editable_field("recycle_bin.dir", "string", "回收箱目录"),
        editable_field("recycle_bin.retention_hours", "int", "回收箱保留小时", min=1, max=8760, unit="h"),
        editable_field("recycle_bin.purge_on_scan", "bool", "文件扫描时清理到期项"),
        editable_field("recycle_bin.purge_on_agent_maintenance", "bool", "维护时清理到期项"),
        editable_field("audio_analysis.enabled", "bool", "启用音频分析"),
        editable_field("audio_analysis.scan_interval_seconds", "int", "音频扫描间隔", min=5, max=86400, unit="s"),
        editable_field("audio_analysis.continuous_queue", "bool", "连续处理队列"),
        editable_field("audio_analysis.busy_pause_seconds", "float", "队列繁忙暂停", min=0, max=60, unit="s"),
        editable_field("audio_analysis.lookback_days", "int", "音频回看天数", min=0, max=30, unit="d"),
        editable_field("audio_analysis.auto_limit", "int", "每批处理数量", min=1, max=100),
        editable_field("audio_analysis.summary_model", "string", "音频摘要模型"),
        editable_field("audio_analysis.delete_missing_audio_records", "bool", "清理缺失音频记录"),
        editable_field("audio_analysis.max_segments", "int", "最大音频片段", min=1, max=500),
        editable_field("audio_preprocessing.quality_min_speech_seconds", "float", "样本最少语音秒数", min=0, max=16, unit="s"),
        editable_field("audio_preprocessing.quality_min_speech_ratio", "float", "样本最少语音占比", min=0, max=1),
        editable_field("audio_preprocessing.quality_noise_gate_enabled", "bool", "启用样本噪音门"),
        editable_field("audio_preprocessing.quality_max_noise_floor_dbfs", "float", "最大噪音底", min=-80, max=0, unit="dBFS"),
        editable_field("audio_preprocessing.quality_min_speech_noise_margin_db", "float", "语音噪音最小差值", min=0, max=40, unit="dB"),
        editable_field("speaker_recognition.enabled", "bool", "启用说话人识别"),
        editable_field("speaker_recognition.embedding_backend", "string", "Embedding backend"),
        editable_field("speaker_recognition.embedding_model", "string", "Embedding model"),
        editable_field("speaker_recognition.embedding_model_dir", "string", "Embedding 模型目录"),
        editable_field("speaker_recognition.embedding_sample_rate", "int", "Embedding 采样率", min=8000, max=96000),
        editable_field("speaker_recognition.sample_seconds", "float", "样本秒数", min=1, max=16, unit="s"),
        editable_field("speaker_recognition.sample_min_seconds", "float", "最短样本秒数", min=0.1, max=16, unit="s"),
        editable_field("speaker_recognition.sample_stride_seconds", "float", "样本窗口步长", min=1, max=120, unit="s"),
        editable_field("speaker_recognition.sample_fine_window_seconds", "float", "细切窗口秒数", min=0.5, max=16, unit="s"),
        editable_field("speaker_recognition.sample_fine_stride_seconds", "float", "细切窗口步长", min=0.25, max=16, unit="s"),
        editable_field("speaker_recognition.samples_per_speaker_per_observation", "int", "每段录音每人最多样本", min=1, max=200),
        editable_field("speaker_recognition.sample_unlabeled_speech", "bool", "未标注语音也生成样本"),
        editable_field("speaker_recognition.sample_require_diarization_segments", "bool", "只使用分离模型边界"),
        editable_field("speaker_recognition.sample_long_segment_anchor", "choice", "长段取样位置", options=["start", "center", "end"]),
        editable_field("speaker_recognition.sample_dir", "string", "样本目录"),
        editable_field("speaker_recognition.sample_audio_cleanup_enabled", "bool", "自动清理旧样本音频"),
        editable_field("speaker_recognition.sample_audio_retention_days", "int", "样本音频保留天数", min=1, max=3650, unit="d"),
        editable_field("speaker_recognition.sample_audio_cleanup_require_embedding", "bool", "清理前要求声纹存在"),
        editable_field("speaker_recognition.speaker_profile_max_prototypes", "int", "声纹 profile 原型上限", min=1, max=24),
        editable_field("speaker_recognition.speaker_profile_outlier_min_similarity", "float", "声纹离群过滤阈值", min=0, max=1),
        editable_field("speaker_recognition.confirmed_profile_matching_enabled", "bool", "已确认 profile 匹配"),
        editable_field("speaker_recognition.confirmed_profile_max_prototypes", "int", "profile 原型上限", min=1, max=24),
        editable_field("speaker_recognition.confirmed_profile_min_samples", "int", "profile 最少样本", min=1, max=24),
        editable_field("speaker_recognition.confirmed_profile_min_sample_confidence", "float", "profile 样本最低一致性", min=0, max=1),
        editable_field("speaker_recognition.confirmed_profile_auto_merge_enabled", "bool", "确认 profile 自动学习"),
        editable_field("speaker_recognition.confirmed_profile_auto_merge_threshold", "float", "确认 profile 自动学习阈值", min=0, max=1),
        editable_field("speaker_recognition.confirmed_profile_source_min_confidence", "float", "确认 profile 源簇最低一致性", min=0, max=1),
        editable_field("speaker_recognition.auto_merge_min_sample_confidence", "float", "自动合并样本最低一致性", min=0, max=1),
        editable_field("speaker_recognition.representative_min_sample_confidence", "float", "代表样本最低一致性", min=0, max=1),
        editable_field("speaker_recognition.auto_merge_threshold", "float", "自动合并阈值", min=0, max=1),
        editable_field("speaker_recognition.auto_merge_max_merges", "int", "单次自动合并上限", min=1, max=5000),
        editable_field("speaker_recognition.candidate_threshold", "float", "候选阈值", min=0, max=1),
        editable_field("speaker_recognition.review_min_samples", "int", "审核最少样本", min=1, max=100),
        editable_field("speaker_recognition.review_min_observations", "int", "审核最少记录", min=1, max=100),
        editable_field("speaker_recognition.review_min_days", "int", "审核最少天数", min=1, max=365),
        editable_field("speaker_recognition.review_min_confidence", "float", "自动审核一致性阈值", min=0, max=1),
        editable_field("ai_backend.provider", "choice", "AI provider", options=["local", "openai"]),
        editable_field("local_ai.ollama_base_url", "string", "Ollama URL"),
        editable_field("local_ai.text_model", "string", "文本模型"),
        editable_field("local_ai.vision_model", "string", "视觉模型"),
        editable_field("local_ai.search_embedding_model", "string", "搜索 embedding 模型"),
        editable_field("local_ai.search_embedding_candidates", "list_string", "搜索 embedding 候选", rows=5),
        editable_field("local_ai.search_index_limit", "int", "搜索索引上限", min=100, max=50000),
        editable_field("local_ai.search_auto_index_limit", "int", "自动索引上限", min=0, max=5000),
        editable_field("local_ai.search_chunk_chars", "int", "搜索分块字符数", min=300, max=4000),
        editable_field("local_ai.search_top_k", "int", "搜索返回数量", min=1, max=100),
        editable_field("local_ai.disable_thinking", "bool", "关闭 thinking"),
        editable_field("local_ai.temperature", "float", "Temperature", min=0, max=2),
        editable_field("local_ai.max_text_chars", "int", "最大文本字符", min=1000, max=500000),
        editable_field("local_ai.max_file_mb", "int", "最大文件 MB", min=1, max=2048, unit="MB"),
        editable_field("local_ai.max_audio_mb", "int", "最大音频 MB", min=1, max=4096, unit="MB"),
        editable_field("local_ai.summary_prompt", "text", "总结 Prompt", rows=5),
        editable_field("local_ai.transcription_backend", "string", "转写 backend"),
        editable_field("local_ai.transcription_model", "string", "转写模型"),
        editable_field("local_ai.fallback_transcription_backend", "string", "备用转写 backend"),
        editable_field("local_ai.fallback_transcription_model", "string", "备用转写模型"),
        editable_field("local_ai.speaker_diarization_enabled", "bool", "启用本地说话人分离"),
        editable_field("local_ai.speaker_diarization_backend", "string", "说话人分离 backend"),
        editable_field("local_ai.speaker_diarization_model", "string", "说话人分离模型"),
        editable_field("local_ai.speaker_diarization_timeout_seconds", "int", "说话人分离超时", min=30, max=7200, unit="s"),
        editable_field("local_ai.speaker_diarization_context", "text", "说话人分离上下文", rows=4),
        editable_field("local_ai.transcription_language", "string", "转写语言"),
        editable_field("local_ai.vad_presegment", "bool", "转写前 VAD 分段"),
        editable_field("local_ai.vad_presegment_diarization", "bool", "分离前 VAD 分段"),
        editable_field("local_ai.vad_silence_noise_db", "float", "VAD 静音噪声 dB", min=-120, max=0),
        editable_field("local_ai.vad_min_silence_seconds", "float", "VAD 最短静音", min=0, max=10, unit="s"),
        editable_field("local_ai.vad_min_speech_seconds", "float", "VAD 最短语音", min=0, max=10, unit="s"),
        editable_field("local_ai.vad_min_total_speech_seconds", "float", "VAD 总语音下限", min=0, max=60, unit="s"),
        editable_field("local_ai.vad_padding_seconds", "float", "VAD padding", min=0, max=10, unit="s"),
        editable_field("local_ai.vad_merge_gap_seconds", "float", "VAD 合并间隔", min=0, max=60, unit="s"),
        editable_field("local_ai.vad_max_chunk_seconds", "float", "VAD 最大片段秒数", min=1, max=3600, unit="s"),
        editable_field("local_ai.vad_max_chunks", "int", "VAD 最大片段数", min=1, max=500),
        editable_field("local_ai.diarization_vad_merge_gap_seconds", "float", "分离 VAD 合并间隔", min=0, max=120, unit="s"),
        editable_field("local_ai.diarization_vad_max_chunk_seconds", "float", "分离 VAD 最大片段秒数", min=1, max=7200, unit="s"),
        editable_field("local_ai.diarization_vad_max_chunks", "int", "分离 VAD 最大片段数", min=1, max=1000),
        editable_field("local_ai.diarization_vad_max_count_merge_gap_seconds", "float", "超量分段合并间隔", min=0, max=300, unit="s"),
        editable_field("local_ai.vibevoice_prompt", "text", "VibeVoice Prompt", rows=4),
        editable_field("local_ai.vibevoice_device_map", "string", "VibeVoice device map"),
        editable_field("openai_analysis.analysis_model", "string", "OpenAI 分析模型"),
        editable_field("openai_analysis.transcription_model", "string", "OpenAI 转写模型"),
        editable_field("openai_analysis.transcription_response_format", "string", "转写响应格式"),
        editable_field("openai_analysis.transcription_base_url", "string", "转写 base URL"),
        editable_field("openai_analysis.max_file_mb", "int", "OpenAI 最大文件 MB", min=1, max=512, unit="MB"),
        editable_field("openai_analysis.max_audio_mb", "int", "OpenAI 最大音频 MB", min=1, max=512, unit="MB"),
        editable_field("openai_analysis.summary_prompt", "text", "OpenAI 总结 Prompt", rows=5),
        editable_field("mobile_sync.host", "string", "同步 Host"),
        editable_field("mobile_sync.port", "int", "同步 Port", min=1, max=65535),
        editable_field("mobile_sync.service_name", "string", "服务名"),
        editable_field("mobile_sync.max_upload_mb", "int", "最大上传 MB", min=1, max=10000, unit="MB"),
        editable_field("mobile_sync.write_reports", "bool", "导入后写报告"),
        editable_field("mobile_sync.skip_existing_uploads", "bool", "跳过重复上传"),
        editable_field("mobile_sync.analyze_after_import", "bool", "导入后分析"),
        editable_field("mobile_sync.analyze_limit", "int", "导入后分析数量", min=1, max=500),
        editable_field("mobile_sync.delete_uploads_after_import", "bool", "导入后删除上传包"),
        editable_field("mobile_sync.delete_unreferenced_imports", "bool", "删除无引用导入目录"),
        editable_field("mobile_sync.delete_audio_after_analysis", "bool", "分析后清理音频"),
        editable_field("mobile_sync.delete_audio_after_analysis_repair_window_hours", "float", "音频修复保留窗口", min=0, max=720, unit="h"),
        editable_field("email_reports.enabled", "bool", "启用邮件报告"),
        editable_field("email_reports.from", "string", "发件人"),
        editable_field("email_reports.to", "list_string", "收件人", rows=3),
        editable_field("email_reports.daily", "bool", "发送日报"),
        editable_field("email_reports.weekly", "bool", "发送周报"),
        editable_field("email_reports.daily_send_time", "string", "日报时间", format="time", placeholder="07:00"),
        editable_field("email_reports.weekly_send_time", "string", "周报时间", format="time", placeholder="06:30"),
        editable_field("email_reports.smtp_host", "string", "SMTP host"),
        editable_field("email_reports.smtp_port", "int", "SMTP port", min=1, max=65535),
        editable_field("email_reports.smtp_username", "string", "SMTP username"),
        editable_field("email_reports.password_env", "string", "密码环境变量"),
        editable_field("email_reports.keychain_service", "string", "Keychain service"),
        editable_field("email_reports.keychain_account", "string", "Keychain account"),
        editable_field("email_reports.retry_after_seconds", "int", "重试间隔", min=60, max=86400, unit="s"),
        editable_field("email_reports.send_window_seconds", "int", "发送窗口", min=60, max=86400, unit="s"),
        editable_field("email_reports.ai_highlights", "bool", "AI 亮点"),
        editable_field("email_reports.model", "string", "邮件摘要模型", placeholder="qwen3.5:35b"),
        editable_field("email_reports.fallback_model", "string", "邮件备用模型", placeholder="qwen3.5:35b"),
        editable_field("email_reports.daily_model", "string", "日报模型", placeholder="qwen3.5:35b"),
        editable_field("email_reports.weekly_model", "string", "周报模型", placeholder="qwen3.5:35b"),
        editable_field("email_reports.daily_highlight_items", "int", "日报亮点数", min=1, max=50),
        editable_field("email_reports.weekly_highlight_items", "int", "周报亮点数", min=1, max=100),
        editable_field("email_reports.highlight_source_max_chars", "int", "亮点来源最大字符", min=1000, max=500000),
        editable_field("email_reports.ollama_timeout_seconds", "int", "邮件 Ollama 超时", min=60, max=21600, unit="s"),
    ]


def load_config_document(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config_root_must_be_object")
    return data


def save_config_document(path: Path, data: dict[str, Any]) -> None:
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def deep_merge_config(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = deep_merge_config(merged.get(key), value)
        return merged
    return override if override is not None else base


def get_config_path(data: dict[str, Any], path: list[str]) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def set_config_path(data: dict[str, Any], path: list[str], value: Any) -> None:
    current = data
    for key in path[:-1]:
        child = current.get(key)
        if not isinstance(child, dict):
            child = {}
            current[key] = child
        current = child
    current[path[-1]] = value


def normalize_setting_value(field: dict[str, Any], value: Any) -> Any:
    field_type = field["type"]
    key = field["key"]
    if field_type == "bool":
        return normalize_bool(value, key)
    if field_type == "int":
        normalized = normalize_int(value, key)
        check_numeric_bounds(field, normalized)
        return normalized
    if field_type == "float":
        normalized = normalize_float(value, key)
        check_numeric_bounds(field, normalized)
        return normalized
    if field_type in {"string", "text"}:
        normalized = "" if value is None else str(value)
        check_string_format(field, normalized)
        return normalized
    if field_type == "choice":
        normalized = "" if value is None else str(value).strip()
        options = [str(item) for item in field.get("options", [])]
        if normalized not in options:
            raise ValueError(f"{key} must be one of: {', '.join(options)}")
        return normalized
    if field_type == "list_string":
        return normalize_string_list(value)
    raise ValueError(f"unsupported_type:{field_type}")


def normalize_bool(value: Any, key: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on", "开启"}:
            return True
        if lowered in {"false", "0", "no", "off", "关闭"}:
            return False
    raise ValueError(f"{key} must be boolean")


def normalize_int(value: Any, key: str) -> int:
    try:
        if isinstance(value, bool):
            raise ValueError
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be an integer")


def normalize_float(value: Any, key: str) -> float:
    try:
        if isinstance(value, bool):
            raise ValueError
        return float(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be a number")


def normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    elif isinstance(value, str):
        raw_items = value.splitlines() if "\n" in value else value.split(",")
    elif value is None:
        raw_items = []
    else:
        raise ValueError("list_string must be a list or text")
    return [str(item).strip() for item in raw_items if str(item).strip()]


def check_numeric_bounds(field: dict[str, Any], value: int | float) -> None:
    if "min" in field and value < field["min"]:
        raise ValueError(f"{field['key']} must be >= {field['min']}")
    if "max" in field and value > field["max"]:
        raise ValueError(f"{field['key']} must be <= {field['max']}")


def check_string_format(field: dict[str, Any], value: str) -> None:
    if field.get("format") == "timezone":
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise ValueError(f"{field['key']} must be a valid timezone")
    if field.get("format") == "time" and value:
        parts = value.split(":")
        if len(parts) != 2:
            raise ValueError(f"{field['key']} must look like HH:MM")
        hour = normalize_int(parts[0], field["key"])
        minute = normalize_int(parts[1], field["key"])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(f"{field['key']} must look like HH:MM")


def api_maintenance(settings: Settings) -> dict[str, Any]:
    store = Store(settings.db_path)
    try:
        today = now(settings.timezone).date()
        retention_preview = run_retention(settings, store, today, dry_run=True)
        mobile_preview = cleanup_mobile_sync_storage(settings, store, dry_run=True, clean_inbox=True, clean_imports=True)
        recycle_preview = purge_recycle_bin(settings, dry_run=True)
        return {
            "ok": True,
            "generated_at": now(settings.timezone).isoformat(timespec="seconds"),
            "counts": table_counts(store),
            "database": file_info(settings.db_path),
            "retention": redact_config(settings.retention),
            "retention_preview": retention_result_payload(retention_preview),
            "mobile_cleanup_preview": {
                "deleted_files": mobile_preview.deleted_files,
                "deleted_dirs": mobile_preview.deleted_dirs,
                "freed_bytes": mobile_preview.freed_bytes,
                "retained_import_dirs": mobile_preview.retained_import_dirs,
                "lines": mobile_preview.lines(dry_run=True),
            },
            "recycle_purge_preview": {
                "deleted_files": recycle_preview.deleted_files,
                "deleted_manifests": recycle_preview.deleted_manifests,
                "deleted_dirs": recycle_preview.deleted_dirs,
                "freed_bytes": recycle_preview.freed_bytes,
                "retained_files": recycle_preview.retained_files,
                "lines": recycle_preview.lines(dry_run=True),
                "errors": recycle_preview.errors,
            },
            "source_counts": source_kind_counts(store)[:16],
            "log_files": log_file_summary(settings),
        }
    finally:
        store.close()


def retention_result_payload(result) -> dict[str, Any]:
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
        "trimmed_logs": result.trimmed_logs,
        "skipped_days": result.skipped_days,
        "vacuumed": result.vacuumed,
        "lines": result.lines(),
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


def log_file_summary(settings: Settings) -> dict[str, Any]:
    files = []
    total_size = 0
    if settings.log_dir.exists():
        for path in sorted(settings.log_dir.glob("*.log"), key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True):
            info = file_info(path)
            total_size += int(info.get("size") or 0)
            files.append(info)
    return {"dir": str(settings.log_dir), "count": len(files), "total_size": total_size, "files": files[:12]}


def api_action(settings: Settings, payload: dict[str, Any]) -> tuple[dict[str, Any], HTTPStatus]:
    name = str(payload.get("name") or "").strip()
    args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
    if name not in ACTIONS:
        return {"ok": False, "error": "unsupported_action"}, HTTPStatus.BAD_REQUEST
    try:
        command = ACTIONS[name](settings, args)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST
    started = time.time()
    try:
        proc = subprocess.run(
            command,
            cwd=str(settings.path.parent),
            text=True,
            capture_output=True,
            timeout=ACTION_TIMEOUTS.get(name, 120),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "action": name,
            "command": command,
            "returncode": None,
            "duration_seconds": round(time.time() - started, 2),
            "stdout": compact(exc.stdout, 12000),
            "stderr": compact(exc.stderr, 12000),
            "error": "timeout",
        }, HTTPStatus.OK
    except OSError as exc:
        return {
            "ok": False,
            "action": name,
            "command": command,
            "returncode": None,
            "duration_seconds": round(time.time() - started, 2),
            "stdout": "",
            "stderr": str(exc),
            "error": "spawn_failed",
        }, HTTPStatus.OK
    return {
        "ok": proc.returncode == 0,
        "action": name,
        "command": command,
        "returncode": proc.returncode,
        "duration_seconds": round(time.time() - started, 2),
        "stdout": proc.stdout[-12000:],
        "stderr": proc.stderr[-12000:],
    }, HTTPStatus.OK


def action_analyze_audio(settings: Settings, args: dict[str, Any]) -> list[str]:
    day = str(args.get("date") or "today")
    limit = clamp(parse_int(str(args.get("limit"))) or int(settings.audio_analysis.get("auto_limit", 5)), 1, 50)
    return [sys_executable(), "-m", "wond", "analyze-audio", "--date", day, "--limit", str(limit), "--no-report"]


def action_analyze_new_files(settings: Settings, args: dict[str, Any]) -> list[str]:
    return [sys_executable(), "-m", "wond", "analyze-new-files", "--no-report"]


def action_search_index(settings: Settings, args: dict[str, Any]) -> list[str]:
    command = [sys_executable(), "-m", "wond", "search-index"]
    limit = parse_int(args.get("limit"))
    if limit is not None:
        command.extend(["--limit", str(clamp(limit, 1, 50000))])
    source = str(args.get("source") or "").strip()
    if source:
        command.extend(["--source", source])
    if bool(args.get("force")):
        command.append("--force")
    return command


def action_refresh_report(settings: Settings, args: dict[str, Any]) -> list[str]:
    day = str(args.get("date") or "today")
    return [sys_executable(), "-m", "wond", "summarize", "--date", day]


def action_mobile_cleanup(settings: Settings, args: dict[str, Any]) -> list[str]:
    command = [sys_executable(), "-m", "wond", "mobile-sync-cleanup"]
    if bool(args.get("apply")):
        command.append("--apply")
    return command


def action_recycle_purge(settings: Settings, args: dict[str, Any]) -> list[str]:
    command = [sys_executable(), "-m", "wond", "recycle-bin", "purge"]
    if bool(args.get("apply")):
        command.append("--apply")
    return command


def action_recycle_restore(settings: Settings, args: dict[str, Any]) -> list[str]:
    trash_path = str(args.get("trash_path") or "").strip()
    if not trash_path:
        raise ValueError("missing_trash_path")
    command = [sys_executable(), "-m", "wond", "recycle-bin", "restore", trash_path]
    restore_to = str(args.get("to") or "").strip()
    if restore_to:
        command.extend(["--to", restore_to])
    return command


def action_collect(settings: Settings, args: dict[str, Any]) -> list[str]:
    command = [sys_executable(), "-m", "wond", "collect", "--date", str(args.get("date") or "today")]
    if bool(args.get("no_report")):
        command.append("--no-report")
    return command


def action_compact(settings: Settings, args: dict[str, Any]) -> list[str]:
    return [sys_executable(), "-m", "wond", "compact", "--date", str(args.get("date") or "today"), "--period", str(args.get("period") or "all")]


def action_retention(settings: Settings, args: dict[str, Any]) -> list[str]:
    command = [sys_executable(), "-m", "wond", "retention", "--date", str(args.get("date") or "today")]
    if bool(args.get("apply")):
        command.append("--apply")
    return command


def action_email_due(settings: Settings, args: dict[str, Any]) -> list[str]:
    command = [sys_executable(), "-m", "wond", "email-due"]
    if bool(args.get("send")):
        command.append("--send")
    return command


def action_install_agent(settings: Settings, args: dict[str, Any]) -> list[str]:
    command = [sys_executable(), "-m", "wond", "install-agent"]
    if bool(args.get("load", True)):
        command.append("--load")
    return command


def action_install_sync_agent(settings: Settings, args: dict[str, Any]) -> list[str]:
    command = [sys_executable(), "-m", "wond", "install-sync-agent"]
    if bool(args.get("load", True)):
        command.append("--load")
    return command


def action_install_dashboard_agent(settings: Settings, args: dict[str, Any]) -> list[str]:
    command = [sys_executable(), "-m", "wond", "install-dashboard-agent"]
    if bool(args.get("load", True)):
        command.append("--load")
    return command


def action_speaker_rename(settings: Settings, args: dict[str, Any]) -> list[str]:
    speaker_id = parse_int(args.get("speaker_id"))
    display_name = str(args.get("display_name") or "").strip()
    if speaker_id is None or speaker_id <= 0:
        raise ValueError("invalid_speaker_id")
    if not display_name:
        raise ValueError("missing_display_name")
    return [sys_executable(), "-m", "wond", "speakers", "rename", str(speaker_id), display_name]


def action_speaker_normalize_names(settings: Settings, args: dict[str, Any]) -> list[str]:
    return [sys_executable(), "-m", "wond", "speakers", "normalize-names"]


def action_speaker_merge(settings: Settings, args: dict[str, Any]) -> list[str]:
    source_id = parse_int(args.get("source_id"))
    target_id = parse_int(args.get("target_id"))
    if source_id is None or target_id is None or source_id <= 0 or target_id <= 0 or source_id == target_id:
        raise ValueError("invalid_speaker_ids")
    return [sys_executable(), "-m", "wond", "speakers", "merge", str(source_id), str(target_id)]


def speaker_id_list(value: Any) -> list[int]:
    raw_items = value if isinstance(value, list) else str(value or "").replace(",", " ").split()
    ids: list[int] = []
    for item in raw_items:
        speaker_id = parse_int(item)
        if speaker_id is None or speaker_id <= 0:
            raise ValueError("invalid_speaker_ids")
        if speaker_id not in ids:
            ids.append(speaker_id)
    return ids


def action_speaker_merge_many(settings: Settings, args: dict[str, Any]) -> list[str]:
    target_id = parse_int(args.get("target_id"))
    source_ids = speaker_id_list(args.get("source_ids") or args.get("speaker_ids"))
    if target_id is None or target_id <= 0:
        raise ValueError("invalid_target_speaker_id")
    source_ids = [speaker_id for speaker_id in source_ids if speaker_id != target_id]
    if not source_ids:
        raise ValueError("missing_source_speaker_ids")
    return [
        sys_executable(),
        "-m",
        "wond",
        "speakers",
        "merge-many",
        str(target_id),
        *[str(speaker_id) for speaker_id in source_ids],
    ]


def action_speaker_delete(settings: Settings, args: dict[str, Any]) -> list[str]:
    speaker_id = parse_int(args.get("speaker_id"))
    if speaker_id is None or speaker_id <= 0:
        raise ValueError("invalid_speaker_id")
    return [sys_executable(), "-m", "wond", "speakers", "delete", str(speaker_id), "--apply"]


def action_speaker_delete_many(settings: Settings, args: dict[str, Any]) -> list[str]:
    speaker_ids = speaker_id_list(args.get("speaker_ids") or args.get("ids"))
    if not speaker_ids:
        raise ValueError("missing_speaker_ids")
    return [
        sys_executable(),
        "-m",
        "wond",
        "speakers",
        "delete-many",
        *[str(speaker_id) for speaker_id in speaker_ids],
        "--apply",
    ]


def action_speaker_detach_sample(settings: Settings, args: dict[str, Any]) -> list[str]:
    sample_id = parse_int(args.get("sample_id"))
    if sample_id is None or sample_id <= 0:
        raise ValueError("invalid_sample_id")
    command = [sys_executable(), "-m", "wond", "speakers", "detach-sample", str(sample_id)]
    display_name = str(args.get("display_name") or args.get("name") or "").strip()
    if display_name:
        command.extend(["--display-name", display_name])
    return command


def action_speaker_protect_sample(settings: Settings, args: dict[str, Any]) -> list[str]:
    sample_ids = speaker_id_list(args.get("sample_ids") or args.get("sample_id") or args.get("ids"))
    if not sample_ids:
        raise ValueError("missing_sample_ids")
    command = [sys_executable(), "-m", "wond", "speakers", "protect-sample", *[str(sample_id) for sample_id in sample_ids]]
    if bool(args.get("unprotect")):
        command.append("--unprotect")
    return command


def action_speaker_prune_sample_audio(settings: Settings, args: dict[str, Any]) -> list[str]:
    command = [sys_executable(), "-m", "wond", "speakers", "prune-sample-audio"]
    date_value = str(args.get("date") or "").strip()
    if date_value:
        command.extend(["--date", date_value])
    older_than_days = parse_int(args.get("older_than_days"))
    if older_than_days is not None and older_than_days > 0:
        command.extend(["--older-than-days", str(older_than_days)])
    limit = parse_int(args.get("limit"))
    if limit is not None and limit > 0:
        command.extend(["--limit", str(limit)])
    if bool(args.get("apply")):
        command.append("--apply")
    return command


def action_speaker_split_sample(settings: Settings, args: dict[str, Any]) -> list[str]:
    sample_id = parse_int(args.get("sample_id"))
    if sample_id is None or sample_id <= 0:
        raise ValueError("invalid_sample_id")
    cuts = str(args.get("cuts") or args.get("cut_points") or "").strip()
    if not cuts:
        raise ValueError("missing_cut_points")
    command = [sys_executable(), "-m", "wond", "speakers", "split-sample", str(sample_id), "--cuts", cuts]
    if bool(args.get("keep_speaker")):
        command.append("--keep-speaker")
    if bool(args.get("keep_parent_active")):
        command.append("--keep-parent-active")
    return command


def action_speaker_refresh_sample_confidence(settings: Settings, args: dict[str, Any]) -> list[str]:
    raw_ids = args.get("speaker_ids") or args.get("speaker_id") or args.get("ids")
    speaker_ids = speaker_id_list(raw_ids) if raw_ids else []
    return [
        sys_executable(),
        "-m",
        "wond",
        "speakers",
        "refresh-sample-confidence",
        *[str(speaker_id) for speaker_id in speaker_ids],
    ]


def action_speaker_repair_embeddings(settings: Settings, args: dict[str, Any]) -> list[str]:
    command = [sys_executable(), "-m", "wond", "speakers", "repair-embeddings"]
    limit = parse_int(args.get("limit"))
    if limit is not None and limit > 0:
        command.extend(["--limit", str(clamp(limit, 1, 1000))])
    if bool(args.get("apply", True)):
        command.append("--apply")
    return command


def action_speaker_repair_sample_clips(settings: Settings, args: dict[str, Any]) -> list[str]:
    command = [sys_executable(), "-m", "wond", "speakers", "repair-sample-clips"]
    sample_ids = speaker_id_list(args.get("sample_ids") or args.get("sample_id") or []) if (args.get("sample_ids") or args.get("sample_id")) else []
    speaker_ids = speaker_id_list(args.get("speaker_ids") or args.get("speaker_id") or []) if (args.get("speaker_ids") or args.get("speaker_id")) else []
    for sample_id in sample_ids[:1000]:
        command.extend(["--sample-id", str(sample_id)])
    for speaker_id in speaker_ids[:1000]:
        command.extend(["--speaker-id", str(speaker_id)])
    limit = parse_int(args.get("limit"))
    if limit is not None and limit > 0:
        command.extend(["--limit", str(clamp(limit, 1, 1000))])
    if bool(args.get("apply", True)):
        command.append("--apply")
    return command


def action_speaker_refresh_representatives(settings: Settings, args: dict[str, Any]) -> list[str]:
    raw_ids = args.get("speaker_ids") or args.get("speaker_id") or args.get("ids")
    speaker_ids = speaker_id_list(raw_ids) if raw_ids else []
    command = [
        sys_executable(),
        "-m",
        "wond",
        "speakers",
        "refresh-representatives",
        *[str(speaker_id) for speaker_id in speaker_ids],
    ]
    per_speaker = parse_int(args.get("per_speaker"))
    if per_speaker is not None and per_speaker > 0:
        command.extend(["--per-speaker", str(clamp(per_speaker, 1, 10))])
    return command


def action_speaker_revive_hidden(settings: Settings, args: dict[str, Any]) -> list[str]:
    command = [sys_executable(), "-m", "wond", "speakers", "revive-hidden"]
    for key, flag in (
        ("min_samples", "--min-samples"),
        ("min_days", "--min-days"),
        ("min_embeddings", "--min-embeddings"),
    ):
        value = parse_int(args.get(key))
        if value is not None and value > 0:
            command.extend([flag, str(clamp(value, 1, 100))])
    if bool(args.get("apply", True)):
        command.append("--apply")
    return command


def action_speaker_auto_organize(settings: Settings, args: dict[str, Any]) -> list[str]:
    command = [sys_executable(), "-m", "wond", "speakers", "auto-organize", "--apply"]
    max_merges = parse_int(args.get("max_merges"))
    if max_merges is not None and max_merges > 0:
        command.extend(["--max-merges", str(max_merges)])
    threshold = args.get("threshold")
    if threshold not in (None, ""):
        command.extend(["--threshold", str(threshold)])
    return command


def action_speaker_confirm(settings: Settings, args: dict[str, Any]) -> list[str]:
    speaker_ids = speaker_id_list(args.get("speaker_ids") or args.get("speaker_id") or args.get("ids"))
    if not speaker_ids:
        raise ValueError("missing_speaker_ids")
    return [sys_executable(), "-m", "wond", "speakers", "confirm", *[str(speaker_id) for speaker_id in speaker_ids]]


def action_speaker_unhide(settings: Settings, args: dict[str, Any]) -> list[str]:
    speaker_ids = speaker_id_list(args.get("speaker_ids") or args.get("speaker_id") or args.get("ids"))
    if not speaker_ids:
        raise ValueError("missing_speaker_ids")
    return [sys_executable(), "-m", "wond", "speakers", "unhide", *[str(speaker_id) for speaker_id in speaker_ids]]


ACTIONS = {
    "analyze_audio": action_analyze_audio,
    "analyze_new_files": action_analyze_new_files,
    "search_index": action_search_index,
    "refresh_report": action_refresh_report,
    "mobile_cleanup": action_mobile_cleanup,
    "recycle_purge": action_recycle_purge,
    "recycle_restore": action_recycle_restore,
    "collect": action_collect,
    "compact": action_compact,
    "retention": action_retention,
    "email_due": action_email_due,
    "install_agent": action_install_agent,
    "install_sync_agent": action_install_sync_agent,
    "install_dashboard_agent": action_install_dashboard_agent,
    "speaker_rename": action_speaker_rename,
    "speaker_normalize_names": action_speaker_normalize_names,
    "speaker_merge": action_speaker_merge,
    "speaker_merge_many": action_speaker_merge_many,
    "speaker_delete": action_speaker_delete,
    "speaker_delete_many": action_speaker_delete_many,
    "speaker_detach_sample": action_speaker_detach_sample,
    "speaker_protect_sample": action_speaker_protect_sample,
    "speaker_prune_sample_audio": action_speaker_prune_sample_audio,
    "speaker_split_sample": action_speaker_split_sample,
    "speaker_refresh_sample_confidence": action_speaker_refresh_sample_confidence,
    "speaker_repair_embeddings": action_speaker_repair_embeddings,
    "speaker_repair_sample_clips": action_speaker_repair_sample_clips,
    "speaker_refresh_representatives": action_speaker_refresh_representatives,
    "speaker_revive_hidden": action_speaker_revive_hidden,
    "speaker_auto_organize": action_speaker_auto_organize,
    "speaker_confirm": action_speaker_confirm,
    "speaker_unhide": action_speaker_unhide,
}

ACTION_TIMEOUTS = {
    "analyze_audio": 1800,
    "analyze_new_files": 600,
    "search_index": 3600,
    "refresh_report": 120,
    "mobile_cleanup": 120,
    "recycle_purge": 120,
    "recycle_restore": 120,
    "collect": 900,
    "compact": 240,
    "retention": 300,
    "email_due": 180,
    "install_agent": 120,
    "install_sync_agent": 120,
    "install_dashboard_agent": 120,
    "speaker_rename": 60,
    "speaker_normalize_names": 60,
    "speaker_merge": 60,
    "speaker_merge_many": 120,
    "speaker_delete": 60,
    "speaker_delete_many": 120,
    "speaker_detach_sample": 120,
    "speaker_protect_sample": 60,
    "speaker_prune_sample_audio": 180,
    "speaker_split_sample": 180,
    "speaker_refresh_sample_confidence": 300,
    "speaker_repair_embeddings": 1800,
    "speaker_repair_sample_clips": 1800,
    "speaker_refresh_representatives": 120,
    "speaker_revive_hidden": 120,
    "speaker_auto_organize": 600,
    "speaker_confirm": 60,
    "speaker_unhide": 60,
}


def sys_executable() -> str:
    import sys

    return str(Path(sys.executable).resolve())


def table_counts(store: Store) -> dict[str, int]:
    return {
        "observations": int(scalar(store.conn, "SELECT count(*) FROM observations") or 0),
        "activity_samples": int(scalar(store.conn, "SELECT count(*) FROM activity_samples") or 0),
        "collector_runs": int(scalar(store.conn, "SELECT count(*) FROM collector_runs") or 0),
        "speakers": int(scalar(store.conn, "SELECT count(*) FROM speakers") or 0),
        "speaker_samples": int(scalar(store.conn, "SELECT count(*) FROM speaker_samples") or 0),
    }


def source_kind_counts(store: Store) -> list[dict[str, Any]]:
    return [
        {"source": row["source"], "kind": row["kind"], "count": row["n"], "first": row["first"], "last": row["last"]}
        for row in store.conn.execute(
            """
            SELECT source, kind, count(*) AS n, min(observed_at) AS first, max(observed_at) AS last
            FROM observations
            GROUP BY source, kind
            ORDER BY n DESC
            """
        )
    ]


def audio_summary(store: Store) -> dict[str, Any]:
    statuses = {}
    for row in store.conn.execute(
        """
        SELECT coalesce(json_extract(metadata, '$.audio_analysis.status'), 'pending') AS status,
               count(*) AS n
        FROM observations
        WHERE source = 'mobile' AND kind = 'audio_segment'
        GROUP BY status
        """
    ):
        statuses[row["status"]] = int(row["n"])
    return {
        "statuses": statuses,
        "total": sum(statuses.values()),
        "with_body": int(scalar(store.conn, "SELECT count(*) FROM observations WHERE source='mobile' AND kind='audio_segment' AND body IS NOT NULL AND length(body)>0") or 0),
        "with_summary": int(scalar(store.conn, "SELECT count(*) FROM observations WHERE source='mobile' AND kind='audio_segment' AND json_extract(metadata, '$.audio_analysis.summary') IS NOT NULL") or 0),
        "latest_analyzed": scalar(store.conn, "SELECT max(json_extract(metadata, '$.audio_analysis.analyzed_at')) FROM observations WHERE source='mobile' AND kind='audio_segment'"),
    }


def audio_rows(store: Store, *, limit: int, status: str) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = "source='mobile' AND kind='audio_segment'"
    if status:
        where += " AND coalesce(json_extract(metadata, '$.audio_analysis.status'), 'pending') = ?"
        params.append(status)
    params.append(limit)
    rows = store.conn.execute(
        f"""
        SELECT *
        FROM observations
        WHERE {where}
        ORDER BY observed_at DESC, id DESC
        LIMIT ?
        """,
        params,
    )
    items = []
    for row in rows:
        meta = json_object(row["metadata"])
        analysis = meta.get("audio_analysis") if isinstance(meta.get("audio_analysis"), dict) else {}
        items.append(
            row_payload(
                row,
                extra={
                    "status": analysis.get("status", "pending"),
                    "transcript_status": analysis.get("transcript_status"),
                    "duration_seconds": analysis.get("duration_seconds") or meta.get("duration_seconds"),
                    "summary": analysis.get("summary") or analysis.get("local_summary") or analysis.get("openai_summary"),
                    "error": compact(analysis.get("error") or analysis.get("transcription_error"), 400),
                    "media_path": meta.get("resolved_media_path") or meta.get("media_path"),
                    "body_preview": compact(row["body"], 600),
                    "speakers": audio_speaker_labels(analysis, store.speaker_names_for_observation(int(row["id"]))),
                },
            )
        )
    return items


def report_summary(settings: Settings) -> dict[str, Any]:
    return {
        "reports": path_count(settings.report_dir, "*.md"),
        "daily": path_count(settings.summary_dir / "daily", "*.md"),
        "weekly": path_count(settings.summary_dir / "weekly", "*.md"),
        "monthly": path_count(settings.summary_dir / "monthly", "*.md"),
        "email": path_count(settings.summary_dir / "email", "*.md"),
        "feedback": path_count(settings.summary_dir / "feedback", "*.md"),
        "latest_report": latest_file(settings.report_dir, "*.md"),
    }


def compact_health(settings: Settings) -> dict[str, Any]:
    return {
        "sync": http_ok(sync_health_url(settings)),
        "ollama": http_ok(str(settings.local_ai.get("ollama_base_url", "http://127.0.0.1:11434")).rstrip("/") + "/api/tags"),
        "agent_plist": launch_agent_path().exists(),
        "sync_plist": sync_launch_agent_path().exists(),
        "dashboard_plist": dashboard_launch_agent_path().exists(),
    }


def launch_agent_checks() -> list[dict[str, Any]]:
    checks = []
    for area, label, path in [
        ("agent", launch_agent_label(), launch_agent_path()),
        ("sync", sync_launch_agent_label(), sync_launch_agent_path()),
        ("dashboard", dashboard_launch_agent_label(), dashboard_launch_agent_path()),
    ]:
        state = launchctl_state(label)
        active_label = label
        plist_present = path.exists()
        status = "ok" if state == "running" else "fail" if state == "not loaded" else "warn"
        checks.append(
            {
                "area": area,
                "name": active_label,
                "status": status,
                "message": f"{state}; plist={'present' if plist_present else 'missing'}",
                "fix": launch_agent_fix(area),
            }
        )
    return checks


def launch_agent_fix(area: str) -> str:
    if area == "sync":
        return "python3 -m wond install-sync-agent --load"
    if area == "dashboard":
        return "python3 -m wond install-dashboard-agent --load"
    return "python3 -m wond install-agent --load"


def launchctl_state(label: str) -> str:
    proc = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
        text=True,
        capture_output=True,
        check=False,
        timeout=5,
    )
    if proc.returncode != 0:
        return "not loaded"
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("state = "):
            return line.replace("state = ", "", 1)
    return "loaded"


def path_check(area: str, name: str, path: Path, *, required: bool, fix: str | None = None) -> dict[str, Any]:
    exists = path.exists()
    status = "ok" if exists else "fail" if required else "warn"
    return {
        "area": area,
        "name": name,
        "status": status,
        "message": str(path) if exists else f"missing: {path}",
        "fix": fix,
    }


def http_check(area: str, name: str, url: str, *, expect_key: str | None = None, fix: str | None = None) -> dict[str, Any]:
    try:
        payload = http_json(url, timeout=2)
        ok = bool(payload) and (expect_key is None or expect_key in payload)
        return {"area": area, "name": name, "status": "ok" if ok else "warn", "message": json.dumps(payload, ensure_ascii=False)[:300], "fix": fix}
    except Exception as exc:
        if is_local_http_permission_error(exc):
            return {
                "area": area,
                "name": name,
                "status": "warn",
                "message": f"local HTTP probe blocked by current execution environment: {exc}",
                "fix": "Verify from a normal shell or check the matching LaunchAgent/port; this is not proof the service is down.",
            }
        return {"area": area, "name": name, "status": "fail", "message": str(exc), "fix": fix}


def ollama_check(settings: Settings) -> dict[str, Any]:
    url = str(settings.local_ai.get("ollama_base_url") or "http://127.0.0.1:11434").rstrip("/") + "/api/tags"
    try:
        payload = http_json(url, timeout=3)
        names = [item.get("name") for item in payload.get("models", []) if isinstance(item, dict)]
        expected = [settings.local_ai.get("text_model"), settings.local_ai.get("vision_model"), settings.audio_analysis.get("summary_model")]
        embedding_configured = search_embedding_model_config(settings)
        embedding_candidates = search_embedding_candidates(settings)
        embedding_available = embedding_configured in names if embedding_configured else any(
            candidate in names or candidate.replace(":latest", "") in {str(name).replace(":latest", "") for name in names}
            for candidate in embedding_candidates
        )
        missing = [item for item in expected if item and item not in names]
        if embedding_configured and not embedding_available:
            missing.append(embedding_configured)
        return {
            "area": "ai",
            "name": "Ollama models",
            "status": "warn" if missing or not embedding_available else "ok",
            "message": f"available={', '.join(names[:8])}; embedding={'ok' if embedding_available else 'missing'}" + (f"; missing={missing}" if missing else ""),
            "fix": "ollama pull bge-m3" if not embedding_available else "ollama pull <model>" if missing else None,
        }
    except Exception as exc:
        if is_local_http_permission_error(exc):
            return {
                "area": "ai",
                "name": "Ollama",
                "status": "warn",
                "message": f"local Ollama probe blocked by current execution environment: {exc}",
                "fix": "Verify from a normal shell with `ollama list` or check whether Ollama is listening on localhost.",
            }
        return {"area": "ai", "name": "Ollama", "status": "fail", "message": str(exc), "fix": "Start Ollama before AI analysis or ask/answer."}


def is_local_http_permission_error(exc: Exception) -> bool:
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else None
    if isinstance(reason, PermissionError):
        return True
    return "Operation not permitted" in str(exc)


def executable_checks() -> list[dict[str, Any]]:
    required = {
        "ffmpeg": "Audio conversion and speaker samples",
        "ffprobe": "Audio duration/codec probing",
        "pdftotext": "Better local PDF extraction",
    }
    checks = []
    for name, purpose in required.items():
        found = find_executable(name)
        checks.append(
            {
                "area": "tools",
                "name": name,
                "status": "ok" if found else "warn",
                "message": found or f"not found; {purpose} may be degraded",
                "fix": f"Install {name} or ensure /opt/homebrew/bin is in LaunchAgent PATH.",
            }
        )
    return checks


def stale_collector_runs(store: Store, *, stale_seconds: int = 3600) -> list[dict[str, Any]]:
    rows = store.conn.execute(
        """
        SELECT *
        FROM collector_runs
        WHERE status = 'running'
        ORDER BY started_at DESC, id DESC
        """
    ).fetchall()
    now_ts = time.time()
    stale: list[dict[str, Any]] = []
    for row in rows:
        try:
            started = datetime.fromisoformat(str(row["started_at"]))
        except (TypeError, ValueError):
            continue
        age_seconds = int(now_ts - started.timestamp())
        if age_seconds < stale_seconds:
            continue
        item = row_dict(row)
        item["age_seconds"] = age_seconds
        stale.append(item)
    return stale


def collector_error_collector(row: Any) -> str:
    metadata = json_object(row["metadata"])
    collector = str(metadata.get("collector") or "").strip()
    if collector:
        return collector
    source_key = str(row["source_key"] or "")
    return source_key.split(":", 1)[0] if ":" in source_key else ""


def data_quality_checks(settings: Settings, store: Store) -> list[dict[str, Any]]:
    audio = audio_summary(store)
    pending = int(audio["statuses"].get("pending", 0))
    errors = int(audio["statuses"].get("error", 0))
    checks = [
        {
            "area": "audio",
            "name": "Audio queue",
            "status": "warn" if pending or errors else "ok",
            "message": f"total={audio['total']}, ok={audio['statuses'].get('ok', 0)}, pending={pending}, error={errors}",
            "fix": "Use Audio Queue -> Run batch or inspect repeated ASR errors.",
        }
    ]
    error_rows = store.conn.execute(
        """
        SELECT source_key, title, body, observed_at, metadata
        FROM observations
        WHERE source = 'system'
          AND kind = 'collector_error'
        ORDER BY observed_at DESC, id DESC
        LIMIT 20
        """
    ).fetchall()
    latest_runs: dict[str, Any] = {}
    for run in store.conn.execute("SELECT collector, started_at, status FROM collector_runs ORDER BY id ASC"):
        latest_runs[str(run["collector"])] = run
    active_error_rows = []
    for row in error_rows:
        collector = collector_error_collector(row)
        latest_run = latest_runs.get(collector)
        if latest_run is None or latest_run["status"] != "ok" or str(latest_run["started_at"] or "") <= str(row["observed_at"] or ""):
            active_error_rows.append(row)
    if active_error_rows:
        latest = active_error_rows[0]
        details = latest["body"] or latest["title"] or "collector_error"
        checks.append(
            {
                "area": "collectors",
                "name": "Collector errors",
                "status": "warn",
                "message": f"{len(active_error_rows)} active collector_error row(s); latest={details}",
                "fix": "Run the failing collector from a normal shell and inspect collector_runs/observations.",
            }
        )
    else:
        checks.append(
            {
                "area": "collectors",
                "name": "Collector errors",
                "status": "ok",
                "message": "no active collector_error rows",
                "fix": None,
            }
        )
    stale_runs = stale_collector_runs(store)
    if stale_runs:
        latest = stale_runs[0]
        checks.append(
            {
                "area": "collectors",
                "name": "Stale running collector runs",
                "status": "warn",
                "message": f"{len(stale_runs)} stale run(s); latest={latest['collector']} age={latest['age_seconds']}s",
                "fix": "Restart the agent or rerun the affected maintenance command; file_analysis now auto-marks stale runs on the next scan.",
            }
        )
    else:
        checks.append(
            {
                "area": "collectors",
                "name": "Stale running collector runs",
                "status": "ok",
                "message": "no stale running collector runs",
                "fix": None,
            }
        )
    media_count = scalar(store.conn, "SELECT count(*) FROM observations WHERE source='local_ai' AND kind='media_analysis'")
    checks.append(
        {
            "area": "files",
            "name": "Local file analyses",
            "status": "ok" if media_count else "info",
            "message": f"local_ai/media_analysis={media_count}",
            "fix": "Drop a supported file into watch_paths or run analyze-media on a file." if not media_count else None,
        }
    )
    return checks


def storage_checks(settings: Settings) -> list[dict[str, Any]]:
    usage = shutil.disk_usage(settings.data_dir)
    free_gb = usage.free / (1024**3)
    return [
        {
            "area": "storage",
            "name": "Data volume free space",
            "status": "warn" if free_gb < 10 else "ok",
            "message": f"{free_gb:.1f} GB free at {settings.data_dir}",
            "fix": "Use Sync -> Cleanup or retention cleanup if disk space is low.",
        }
    ]


def source_status_rows(settings: Settings, store: Store) -> list[dict[str, Any]]:
    source_names = ["calendar", "reminders", "browser", "filesystem", "messages", "apple_mail", "mobile", "local_ai"]
    rows = []
    for source in source_names:
        counts = [
            {"kind": row["kind"], "count": row["n"], "last": row["last"]}
            for row in store.conn.execute(
                "SELECT kind, count(*) AS n, max(observed_at) AS last FROM observations WHERE source=? GROUP BY kind ORDER BY n DESC",
                (source,),
            )
        ]
        latest_run = store.conn.execute(
            "SELECT * FROM collector_runs WHERE collector=? ORDER BY id DESC LIMIT 1",
            (source if source not in {"browser", "filesystem"} else "browsers" if source == "browser" else "recent_files",),
        ).fetchone()
        rows.append(
            {
                "source": source,
                "enabled": source_enabled(settings, source),
                "counts": counts,
                "latest_run": row_dict(latest_run) if latest_run else None,
                "notes": source_notes(settings, source),
            }
        )
    return rows


def source_enabled(settings: Settings, source: str) -> bool:
    mapping = {"browser": "browsers", "filesystem": "recent_files", "local_ai": "file_analysis", "mobile": "mobile_sync"}
    key = mapping.get(source, source)
    if key == "file_analysis":
        return bool(settings.file_analysis.get("enabled", True))
    if key == "mobile_sync":
        return True
    return bool(settings.collectors.get(key, True))


def source_notes(settings: Settings, source: str) -> list[str]:
    return []


def mobile_sync_storage(settings: Settings, store: Store) -> dict[str, Any]:
    inbox = settings.data_dir / "mobile_sync" / "inbox"
    imports = settings.data_dir / "mobile_sync" / "imports"
    return {
        "inbox_files": count_files(inbox),
        "import_dirs": count_dirs(imports),
        "retained_import_dirs": count_dirs(imports),
        "inbox_size": dir_size(inbox),
        "imports_size": dir_size(imports),
    }
