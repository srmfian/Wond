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
    action_suggestions_payload,
    evidence_groups_payload,
    project_clusters_payload,
    repair_queue_payload,
    speaker_quality_payload,
)
from .observation_filters import visible_observations
from .recycle_bin import list_recycle_bin, purge_recycle_bin, recycle_bin_config, recycle_bin_summary
from .retention import run_retention
from .speakers import (
    speaker_confidence_summary,
    speaker_profiles_payload,
    speaker_sample_payload,
)
from .store import Observation, Store
from .sync_server import cleanup_mobile_sync_storage, mobile_status_payload
from .timeutil import day_bounds, local_iso, now, parse_day


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
        server_version = "WondDashboard/0.1"

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
            if parsed.path == "/api/repair-queue":
                self.send_json(repair_queue_payload(request_settings, query(parsed)))
                return
            if parsed.path == "/api/action-suggestions":
                self.send_json(action_suggestions_payload(request_settings, query(parsed)))
                return
            if parsed.path == "/api/project-clusters":
                self.send_json(project_clusters_payload(request_settings, query(parsed)))
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
    finally:
        store.close()
    context = build_answer_context(observations, reports, semantic.get("items", []))
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
        "citations": answer_citations(observations, reports, semantic.get("items", [])),
        "evidence_groups": evidence_groups_payload(observations, reports, semantic.get("items", [])),
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
    if item_type not in {"suggestion", "project"}:
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
                        ),
                    },
                )
            )
        matches = [row_dict(row) for row in store.list_speaker_match_decisions(50)]
        samples = [
            item
            for item in (speaker_sample_payload(row) for row in store.list_speaker_samples(None)[:300])
            if (item.get("metadata") or {}).get("sample_role") != "mixed_parent_archived"
        ][:240]
        return {
            "ok": True,
            "speakers": speakers,
            "matches": matches,
            "profiles": speaker_profiles_payload(store),
            "samples": samples,
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
        editable_field("speaker_recognition.enabled", "bool", "启用说话人识别"),
        editable_field("speaker_recognition.embedding_backend", "string", "Embedding backend"),
        editable_field("speaker_recognition.embedding_model", "string", "Embedding model"),
        editable_field("speaker_recognition.embedding_model_dir", "string", "Embedding 模型目录"),
        editable_field("speaker_recognition.embedding_sample_rate", "int", "Embedding 采样率", min=8000, max=96000),
        editable_field("speaker_recognition.sample_seconds", "float", "样本秒数", min=1, max=120, unit="s"),
        editable_field("speaker_recognition.sample_min_seconds", "float", "最短样本秒数", min=0.1, max=120, unit="s"),
        editable_field("speaker_recognition.sample_long_segment_anchor", "choice", "长段取样位置", options=["start", "center", "end"]),
        editable_field("speaker_recognition.sample_dir", "string", "样本目录"),
        editable_field("speaker_recognition.confirmed_profile_matching_enabled", "bool", "已确认 profile 匹配"),
        editable_field("speaker_recognition.confirmed_profile_max_prototypes", "int", "profile 原型上限", min=1, max=24),
        editable_field("speaker_recognition.confirmed_profile_min_samples", "int", "profile 最少样本", min=1, max=24),
        editable_field("speaker_recognition.auto_merge_threshold", "float", "自动合并阈值", min=0, max=1),
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
        editable_field("email_reports.daily_highlight_items", "int", "日报亮点数", min=1, max=50),
        editable_field("email_reports.weekly_highlight_items", "int", "周报亮点数", min=1, max=100),
        editable_field("email_reports.highlight_source_max_chars", "int", "亮点来源最大字符", min=1000, max=500000),
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


DASHBOARD_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Wond Dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --panel-2: #f0f3f6;
      --text: #16181d;
      --muted: #626b77;
      --line: #d9dee7;
      --ok: #127a4a;
      --warn: #a85f00;
      --fail: #b3261e;
      --info: #225a9b;
      --accent: #2457c5;
      --accent-2: #0f766e;
      --shadow: 0 12px 32px rgba(16, 24, 40, .08);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--text); overflow-x: hidden; }
    button, input, select, textarea { font: inherit; }
    .app { display: grid; grid-template-columns: 236px 1fr; min-height: 100vh; }
    aside { background: #10141b; color: #e5e7eb; padding: 18px 14px; position: sticky; top: 0; height: 100vh; overflow-y: auto; }
    .brand { display: flex; gap: 10px; align-items: center; padding: 6px 8px 16px; }
    .mark { width: 34px; height: 34px; border-radius: 8px; background: linear-gradient(135deg, #4f7cff, #0f766e); }
    .brand h1 { margin: 0; font-size: 17px; line-height: 1.2; }
    .brand span { display: block; color: #aeb7c5; font-size: 12px; margin-top: 3px; }
    nav { display: grid; gap: 12px; }
    .nav-group { display: grid; gap: 3px; }
    .nav-label { color: #7d8798; font-size: 11px; font-weight: 750; padding: 0 9px 2px; }
    nav button { display: flex; width: 100%; gap: 10px; align-items: center; border: 0; background: transparent; color: #cbd5e1; padding: 9px 10px; border-radius: 8px; text-align: left; cursor: pointer; font-weight: 650; }
    nav button.active, nav button:hover { background: rgba(255,255,255,.11); color: #fff; }
    main { padding: 22px 24px 28px; min-width: 0; }
    .topbar { display: flex; justify-content: space-between; align-items: flex-start; gap: 18px; margin-bottom: 18px; }
    h2 { margin: 0; font-size: 26px; letter-spacing: 0; }
    .subtitle { margin-top: 5px; color: var(--muted); }
    .toolbar { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }
    .btn { border: 1px solid var(--line); background: var(--panel); color: var(--text); padding: 8px 11px; border-radius: 8px; cursor: pointer; box-shadow: 0 1px 0 rgba(16,24,40,.04); }
    .btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
    .btn.danger { color: var(--fail); }
    .grid { display: grid; gap: 14px; }
    .grid.cols-4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .grid.cols-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .grid.cols-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .card { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; box-shadow: 0 1px 2px rgba(16, 24, 40, .06); padding: 15px; min-width: 0; overflow-wrap: anywhere; }
    .metric .label { color: var(--muted); font-size: 13px; }
    .metric .value { font-size: 30px; font-weight: 700; margin-top: 7px; }
    .metric .hint { color: var(--muted); font-size: 12px; margin-top: 5px; }
    .status { display: inline-flex; align-items: center; gap: 6px; border-radius: 999px; padding: 4px 9px; font-size: 12px; font-weight: 700; }
    .status.ok { background: #dff7ea; color: var(--ok); }
    .status.warn { background: #fff1d6; color: var(--warn); }
    .status.fail { background: #fde7e5; color: var(--fail); }
    .status.error { background: #fde7e5; color: var(--fail); }
    .status.missing_file { background: #fff1d6; color: var(--warn); }
    .status.unavailable, .status.empty, .status.keyword-fallback, .status.extractive { background: #fff1d6; color: var(--warn); }
    .status.semantic-rag, .status.ollama-keyword { background: #e0f2fe; color: #075985; }
    .status.processing { background: #e0f2fe; color: #075985; }
    .status.skipped { background: #edf2f7; color: #4b5563; }
    .status.observation { background: #e5eefb; color: var(--info); }
    .status.activity { background: #e8f4ef; color: var(--ok); }
    .status.reports, .status.daily, .status.weekly, .status.monthly, .status.email, .status.feedback { background: #edf2f7; color: #374151; }
    .status.provisional, .status.below_threshold { background: #fff1d6; color: var(--warn); }
    .status.auto_merged_pending_review { background: #fff1d6; color: var(--warn); }
    .status.low_similarity_hidden { background: #edf2f7; color: #4b5563; }
    .status.confirmed, .status.accepted, .status.named { background: #dff7ea; color: var(--ok); }
    .status.disabled { background: #edf2f7; color: #4b5563; }
    .status.info, .status.pending { background: #e5eefb; color: var(--info); }
    .status.high { background: #fde7e5; color: var(--fail); }
    .status.medium { background: #fff1d6; color: var(--warn); }
    .status.low { background: #edf2f7; color: #4b5563; }
    .status.open { background: #e5eefb; color: var(--info); }
    .status.snoozed { background: #fff1d6; color: var(--warn); }
    .status.done { background: #dff7ea; color: var(--ok); }
    .status.archived, .status.dismissed { background: #edf2f7; color: #4b5563; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { padding: 10px 8px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
    th { color: var(--muted); font-weight: 700; background: var(--panel-2); position: sticky; top: 0; z-index: 1; }
    .table-wrap { max-height: 560px; overflow: auto; border: 1px solid var(--line); border-radius: 8px; }
    .muted { color: var(--muted); }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    .split { display: grid; grid-template-columns: 360px 1fr; gap: 14px; align-items: start; }
    .list { display: grid; gap: 8px; }
    .item { border: 1px solid var(--line); border-radius: 8px; padding: 11px; background: var(--panel); cursor: pointer; }
    .item:hover { border-color: #aeb8c9; }
    .item-title { font-weight: 700; }
    .item-meta { color: var(--muted); font-size: 12px; margin-top: 3px; }
    pre { white-space: pre-wrap; word-break: break-word; background: #0b1020; color: #e5e7eb; padding: 14px; border-radius: 8px; overflow: auto; max-height: 620px; }
    .reports-layout { display: grid; grid-template-columns: 300px minmax(0, 1fr) 300px; gap: 14px; align-items: start; }
    .reports-layout > * { min-width: 0; }
    .reports-nav, .reports-side { display: grid; gap: 14px; }
    .reports-side { position: sticky; top: 24px; }
    .reports-controls { display: grid; gap: 8px; }
    .reports-list { display: grid; gap: 8px; max-height: calc(100vh - 300px); overflow: auto; padding-right: 2px; }
    .report-file-item { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: var(--panel); cursor: pointer; min-width: 0; }
    .report-file-item:hover, .report-file-item.active { border-color: var(--accent); background: #e9f0ff; }
    .report-file-title { font-weight: 750; overflow-wrap: anywhere; }
    .report-file-meta { color: var(--muted); font-size: 12px; margin-top: 4px; display: flex; flex-wrap: wrap; gap: 4px 8px; }
    .reports-metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .report-metric { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #fbfcfe; min-width: 0; }
    .report-metric .label { color: var(--muted); font-size: 12px; }
    .report-metric .value { font-size: 22px; font-weight: 750; margin-top: 4px; overflow-wrap: anywhere; }
    .report-reader { min-height: 720px; }
    .report-reader-header { border-bottom: 1px solid var(--line); margin: -2px 0 14px; padding-bottom: 12px; }
    .report-reader-title { font-size: 22px; font-weight: 800; line-height: 1.25; overflow-wrap: anywhere; }
    .report-reader-content { line-height: 1.65; color: var(--text); overflow-wrap: anywhere; word-break: break-word; max-height: min(720px, calc(100vh - 220px)); overflow: auto; padding-right: 2px; }
    .report-reader-content h1 { font-size: 24px; margin: 0 0 14px; line-height: 1.25; }
    .report-reader-content h2 { font-size: 18px; margin: 22px 0 8px; padding-top: 8px; border-top: 1px solid var(--line); }
    .report-reader-content h3 { font-size: 15px; margin: 16px 0 6px; }
    .report-reader-content p { margin: 8px 0; }
    .report-reader-content ul, .report-reader-content ol { margin: 8px 0 10px 20px; padding: 0; }
    .report-reader-content li { margin: 4px 0; }
    .report-reader-content code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; background: #edf2f7; border-radius: 5px; padding: 1px 4px; }
    .report-reader-content pre { max-height: none; margin: 10px 0; }
    .report-outline { display: grid; gap: 6px; }
    .report-outline-row { border-bottom: 1px solid var(--line); padding: 7px 0; color: var(--muted); overflow-wrap: anywhere; }
    .report-outline-row:last-child { border-bottom: 0; }
    .report-category-list { display: grid; gap: 4px; }
    .report-category-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; border: 1px solid transparent; border-bottom-color: var(--line); border-radius: 8px; padding: 9px 8px; cursor: pointer; }
    .report-category-row:hover, .report-category-row.active { border-color: var(--accent); background: #e9f0ff; }
    .report-category-row:last-child { border-bottom-color: transparent; }
    .searchbar { display: grid; grid-template-columns: minmax(0, 1fr) 170px auto auto; gap: 8px; margin-bottom: 12px; align-items: center; }
    .search-hero { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; }
    .search-main, .search-answer-layout { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; margin-top: 14px; }
    .search-main > *, .search-answer-layout > * { min-width: 0; }
    .search-side, .search-stack, .search-answer-side { display: grid; gap: 14px; }
    .search-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
    .search-actions .btn { min-width: 112px; }
    .search-source-pills { display: flex; flex-wrap: wrap; gap: 8px; }
    .search-index-grid, .search-metric-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .search-index-stat, .search-metric { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #fbfcfe; min-width: 0; }
    .search-index-stat .label, .search-metric .label { color: var(--muted); font-size: 12px; }
    .search-index-stat .value, .search-metric .value { font-size: 22px; font-weight: 750; margin-top: 4px; overflow-wrap: anywhere; }
    .search-index-stat .value.compact { font-size: 18px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .search-model-row, .citation-row { border-bottom: 1px solid var(--line); padding: 9px 0; }
    .search-model-row:last-child, .citation-row:last-child { border-bottom: 0; }
    .search-retrieval { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; align-items: start; margin-top: 14px; }
    .search-retrieval .section-title { margin-bottom: 0; }
    .search-error { color: var(--warn); margin-top: 8px; overflow-wrap: anywhere; }
    .search-list { display: grid; gap: 8px; }
    .search-result { border: 1px solid var(--line); border-radius: 8px; padding: 11px; background: var(--panel); min-width: 0; }
    .search-result.semantic { border-left: 4px solid var(--accent); }
    .search-result.observation { border-left: 4px solid var(--accent-2); }
    .search-result.report { border-left: 4px solid var(--warn); }
    .result-title { font-weight: 700; line-height: 1.35; overflow-wrap: anywhere; }
    .result-meta { display: flex; flex-wrap: wrap; gap: 4px 10px; color: var(--muted); font-size: 12px; margin-top: 4px; }
    .result-text { color: var(--muted); margin-top: 6px; line-height: 1.45; overflow-wrap: anywhere; word-break: break-word; display: -webkit-box; -webkit-line-clamp: 5; -webkit-box-orient: vertical; overflow: hidden; }
    .search-stack .result-text { -webkit-line-clamp: 4; }
    .answer-body { line-height: 1.65; overflow-wrap: anywhere; word-break: break-word; }
    .citation-list { display: grid; gap: 0; }
    .citation-type { font-weight: 750; }
    input, select, textarea { border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; background: #fff; color: var(--text); }
    textarea { min-height: 92px; width: 100%; resize: vertical; }
    .answer { line-height: 1.6; }
    .timeline { display: grid; gap: 8px; }
    .timeline-row { display: grid; grid-template-columns: 160px 130px 1fr; gap: 10px; padding: 10px 0; border-bottom: 1px solid var(--line); }
    .timeline-hero { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: stretch; }
    .timeline-toolbar { display: grid; grid-template-columns: 140px minmax(170px, 1fr) 145px 125px 70px; gap: 8px; align-items: center; }
    .timeline-toolbar .btn { width: 100%; }
    .timeline-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
    .timeline-stat { border: 1px solid var(--line); border-radius: 8px; padding: 11px; background: #fbfcfe; min-width: 0; }
    .timeline-stat .label { color: var(--muted); font-size: 12px; }
    .timeline-stat .value { font-size: 24px; font-weight: 750; margin-top: 4px; }
    .timeline-stat .hint { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .timeline-main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; margin-top: 14px; }
    .timeline-main > * { min-width: 0; }
    .timeline-side { display: grid; gap: 14px; }
    .timeline-section { display: grid; gap: 8px; margin-bottom: 16px; }
    .timeline-section-header { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 2px 2px 0; }
    .timeline-section-header h3 { margin: 0; font-size: 15px; }
    .timeline-feed { max-height: min(760px, calc(100vh - 220px)); overflow: auto; padding-right: 2px; }
    .timeline-list { display: grid; gap: 8px; }
    .timeline-event { display: grid; grid-template-columns: 72px 132px minmax(0, 1fr); gap: 10px; padding: 12px; border: 1px solid var(--line); border-left: 4px solid var(--accent); border-radius: 8px; background: var(--panel); min-width: 0; }
    .timeline-event.activity { border-left-color: var(--accent-2); }
    .timeline-event > * { min-width: 0; }
    .timeline-time { color: var(--muted); font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    .timeline-title { font-weight: 700; line-height: 1.35; overflow-wrap: anywhere; word-break: break-word; }
    .timeline-body { color: var(--muted); margin-top: 4px; line-height: 1.45; overflow-wrap: anywhere; word-break: break-word; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
    .timeline-meta { display: flex; flex-wrap: wrap; gap: 4px 10px; color: var(--muted); font-size: 12px; margin-top: 4px; }
    .timeline-breakdown { display: grid; gap: 4px; max-height: 360px; overflow: auto; padding-right: 2px; }
    .timeline-breakdown-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; border: 1px solid transparent; border-bottom-color: var(--line); padding: 9px 8px; border-radius: 8px; cursor: pointer; }
    .timeline-breakdown-row:hover, .timeline-breakdown-row.active { border-color: var(--accent); background: #e9f0ff; }
    .timeline-breakdown-row:last-child { border-bottom-color: transparent; }
    .sources-hero { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: stretch; }
    .source-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
    .source-kpi { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfe; min-width: 0; }
    .source-kpi .label { color: var(--muted); font-size: 12px; }
    .source-kpi .value { font-size: 25px; font-weight: 750; margin-top: 5px; }
    .source-kpi .value.compact { font-size: 20px; line-height: 1.15; }
    .source-kpi .hint { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .source-filters { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .source-action-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .source-action-grid .btn { width: 100%; text-align: left; }
    .sources-main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; margin-top: 14px; }
    .sources-main > * { min-width: 0; }
    .source-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
    .source-card { border: 1px solid var(--line); border-radius: 8px; background: var(--panel); padding: 13px; min-width: 0; border-left: 4px solid var(--accent); }
    .source-card.issue { border-left-color: var(--warn); }
    .source-card.disabled { border-left-color: #9aa4b2; }
    .source-card.error { border-left-color: var(--fail); }
    .source-card-top { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; }
    .source-name { font-weight: 800; font-size: 17px; line-height: 1.25; }
    .source-note-list, .source-issue-list, .source-side { display: grid; gap: 8px; }
    .source-note { border: 1px solid var(--line); border-radius: 8px; padding: 9px 10px; background: #fff8eb; color: var(--warn); line-height: 1.4; overflow-wrap: anywhere; }
    .source-run { color: var(--muted); font-size: 12px; margin-top: 8px; line-height: 1.45; overflow-wrap: anywhere; }
    .source-kind-list { display: grid; gap: 6px; margin-top: 11px; }
    .source-kind-row { display: grid; grid-template-columns: minmax(0, 1fr) 58px minmax(96px, .8fr); gap: 8px; align-items: center; border-top: 1px solid var(--line); padding-top: 7px; font-size: 12px; }
    .source-kind-row b { font-size: 13px; }
    .source-issue { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #fbfcfe; border-left: 4px solid var(--warn); min-width: 0; }
    .source-issue.fail { border-left-color: var(--fail); }
    .source-issue-title { font-weight: 750; }
    .source-issue-body { color: var(--muted); margin-top: 4px; line-height: 1.4; overflow-wrap: anywhere; }
    .speaker-workbench { display: grid; gap: 13px; }
    .speaker-command-row { display: grid; grid-template-columns: minmax(0, 1fr); gap: 14px; align-items: start; }
    .speaker-command-copy { min-width: 0; }
    .speaker-command-copy .section-title { margin-bottom: 5px; }
    .speaker-command-note { color: var(--muted); line-height: 1.45; max-width: 720px; margin: 0; }
    .speaker-kpis { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; background: #fbfcfe; }
    .speaker-kpi { border-right: 1px solid var(--line); padding: 10px 12px; min-width: 0; }
    .speaker-kpi:last-child { border-right: 0; }
    .speaker-kpi .label { color: var(--muted); font-size: 12px; }
    .speaker-kpi .value { font-size: 22px; font-weight: 750; margin-top: 4px; }
    .speaker-kpi .hint { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .speaker-filter-row { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 10px; align-items: center; }
    .speaker-filter-label { color: var(--muted); font-size: 12px; font-weight: 750; }
    .speaker-filters { display: flex; flex-wrap: wrap; gap: 8px; }
    .speaker-review-toolbar { display: grid; grid-template-columns: minmax(220px, 1fr) 154px auto; gap: 8px; align-items: center; }
    .speaker-review-layout { display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; }
    .speaker-panel { display: grid; gap: 10px; min-width: 0; }
    .speaker-panel-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
    .speaker-panel-head h3 { margin: 0; font-size: 16px; }
    .speaker-sample-toolbar { display: grid; grid-template-columns: minmax(220px, 1fr) 150px 150px auto; gap: 8px; align-items: center; }
    .speaker-sample-filters { display: flex; flex-wrap: wrap; gap: 8px; }
    .speaker-sample-summary { display: flex; flex-wrap: wrap; gap: 6px 10px; color: var(--muted); font-size: 12px; }
    .speaker-tools { display: grid; gap: 10px; }
    .speaker-tools > *, .speaker-tools select, .speaker-tools input, .speaker-tools .btn { min-width: 0; max-width: 100%; }
    .speaker-tools select, .speaker-tools input, .speaker-tools .btn { width: 100%; }
    .speaker-tool-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto; gap: 8px; align-items: center; }
    .speaker-action-group { border-top: 1px solid var(--line); padding-top: 10px; display: grid; gap: 8px; }
    .speaker-action-group:first-child { border-top: 0; padding-top: 0; }
    .speaker-action-title { color: var(--muted); font-size: 12px; font-weight: 750; }
    .speaker-context-card .empty-state { padding: 12px; }
    .speaker-context-summary { border: 1px solid var(--line); border-radius: 8px; background: #fbfcfe; padding: 10px; display: grid; gap: 6px; }
    .speaker-context-title { font-weight: 800; line-height: 1.3; overflow-wrap: anywhere; }
    .speaker-context-note { color: var(--muted); font-size: 12px; line-height: 1.4; overflow-wrap: anywhere; }
    .speaker-context-actions { display: grid; gap: 8px; }
    .speaker-context-actions .btn { text-align: left; }
    .speaker-bulk-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .speaker-bulk-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; align-items: center; }
    .speaker-danger-row { border-top: 1px solid var(--line); padding-top: 10px; }
    .speaker-tool-row .btn { white-space: nowrap; }
    .speaker-selection { border: 1px solid var(--line); border-radius: 8px; background: #fbfcfe; padding: 10px; display: grid; gap: 8px; }
    .speaker-selection-title { display: flex; justify-content: space-between; gap: 10px; font-weight: 750; }
    .speaker-selection-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .speaker-selection-chip { border: 1px solid var(--line); border-radius: 8px; padding: 8px; background: var(--panel); min-width: 0; }
    .speaker-selection-chip .label { color: var(--muted); font-size: 11px; }
    .speaker-selection-chip .value { font-weight: 750; overflow-wrap: anywhere; word-break: break-word; }
    .speakers-main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; margin-top: 14px; }
    .speakers-main > * { min-width: 0; }
    .speaker-content { display: grid; gap: 14px; align-content: start; min-width: 0; }
    .speaker-list-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; }
    .speaker-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
    .speaker-card { border: 1px solid var(--line); border-left: 4px solid var(--accent); border-radius: 8px; background: var(--panel); padding: 12px; min-width: 0; cursor: pointer; position: relative; display: grid; gap: 9px; }
    .speaker-card.review { border-left-color: var(--warn); }
    .speaker-card.empty { border-left-color: #9aa4b2; }
    .speaker-card.hidden-speaker { border-left-color: #9aa4b2; background: #f8fafc; }
    .speaker-card.selected { border-color: var(--accent); background: #e9f0ff; }
    .speaker-card:hover { border-color: var(--accent); background: #fbfcfe; }
    .speaker-check { position: absolute; right: 11px; top: 11px; width: 20px; height: 20px; }
    .speaker-card-top { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; padding-right: 28px; }
    .speaker-name { font-size: 17px; font-weight: 800; line-height: 1.25; overflow-wrap: anywhere; }
    .speaker-meta { display: flex; flex-wrap: wrap; gap: 4px 10px; color: var(--muted); font-size: 12px; margin-top: 5px; }
    .speaker-card-metrics { display: flex; flex-wrap: wrap; gap: 8px 12px; color: var(--muted); font-size: 12px; border-top: 1px solid var(--line); padding-top: 9px; }
    .speaker-card-metrics b { color: var(--text); font-size: 13px; }
    .speaker-card-actions { display: flex; flex-wrap: wrap; gap: 8px; }
    .speaker-side { display: grid; gap: 14px; }
    .speaker-match-list, .speaker-sample-list { display: grid; gap: 8px; }
    .speaker-sample-list.expanded { max-height: min(760px, calc(100vh - 220px)); }
    .speaker-match-card, .speaker-sample-card { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #fbfcfe; min-width: 0; }
    .speaker-sample-card { border-left: 4px solid #9aa4b2; display: grid; gap: 8px; }
    .speaker-sample-card.ok { border-left-color: var(--accent); }
    .speaker-sample-card.low-confidence, .speaker-sample-card.error { border-left-color: var(--warn); }
    .speaker-sample-card.representative { border-left-color: var(--accent-2); }
    .speaker-sample-card.missing-embedding { border-left-color: #9aa4b2; }
    .speaker-match-row { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; }
    .speaker-score { font-weight: 750; }
    .speaker-sample-card audio { width: 100%; }
    .speaker-sample-actions { display: flex; justify-content: flex-end; margin-top: 8px; }
    .speaker-sample-tags { display: flex; flex-wrap: wrap; gap: 6px; }
    .speaker-transcript { color: var(--muted); line-height: 1.45; margin-top: 6px; overflow-wrap: anywhere; word-break: break-word; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
    .files-hero { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: stretch; }
    .file-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
    .file-kpi { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfe; min-width: 0; }
    .file-kpi .label { color: var(--muted); font-size: 12px; }
    .file-kpi .value { font-size: 25px; font-weight: 750; margin-top: 5px; }
    .file-kpi .hint { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .file-filters { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .file-main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; margin-top: 14px; }
    .file-main > * { min-width: 0; }
    .file-side { display: grid; gap: 14px; }
    .file-toolbar { display: grid; grid-template-columns: minmax(220px, 1fr) auto; gap: 8px; align-items: center; margin-bottom: 10px; }
    .file-list, .file-path-list, .file-state-list { display: grid; gap: 8px; }
    .file-card { display: grid; grid-template-columns: 142px 104px minmax(0, 1fr); gap: 10px; border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: var(--panel); min-width: 0; border-left: 4px solid #9aa4b2; }
    .file-card > * { min-width: 0; }
    .file-card.analysis { border-left-color: var(--ok); }
    .file-card.filesystem { border-left-color: var(--info); }
    .file-time { color: var(--muted); font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; overflow-wrap: anywhere; }
    .file-title { font-weight: 750; line-height: 1.35; overflow-wrap: anywhere; word-break: break-word; }
    .file-meta { display: flex; flex-wrap: wrap; gap: 4px 10px; color: var(--muted); font-size: 12px; margin-top: 4px; }
    .file-body { color: var(--muted); margin-top: 5px; line-height: 1.45; overflow-wrap: anywhere; word-break: break-word; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
    .file-path-row, .file-state-row { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #fbfcfe; min-width: 0; }
    .file-path-title, .file-state-title { font-weight: 750; overflow-wrap: anywhere; word-break: break-word; }
    .file-chip-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
    .file-chip { display: inline-flex; align-items: center; border: 1px solid var(--line); border-radius: 999px; padding: 4px 8px; background: #f6f7f9; font-size: 12px; color: #374151; }
    .file-config-list { display: grid; gap: 8px; }
    .recycle-hero { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: stretch; }
    .recycle-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
    .recycle-kpi { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfe; min-width: 0; }
    .recycle-kpi .label { color: var(--muted); font-size: 12px; }
    .recycle-kpi .value { font-size: 25px; font-weight: 750; margin-top: 5px; }
    .recycle-kpi .hint { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .recycle-filters { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .recycle-main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; margin-top: 14px; }
    .recycle-main > * { min-width: 0; }
    .recycle-side { display: grid; gap: 14px; }
    .recycle-toolbar { display: grid; grid-template-columns: minmax(220px, 1fr) auto; gap: 8px; align-items: center; margin-bottom: 10px; }
    .recycle-list, .recycle-preview-list, .recycle-form, .recycle-category-list { display: grid; gap: 8px; }
    .recycle-card { display: grid; grid-template-columns: 132px 96px minmax(0, 1fr) auto; gap: 10px; border: 1px solid var(--line); border-left: 4px solid var(--accent-2); border-radius: 8px; padding: 12px; background: var(--panel); min-width: 0; }
    .recycle-card > * { min-width: 0; }
    .recycle-card.due { border-left-color: var(--warn); }
    .recycle-card.missing { border-left-color: var(--fail); }
    .recycle-card.unknown { border-left-color: #9aa4b2; }
    .recycle-card .btn { align-self: center; white-space: nowrap; }
    .recycle-time { color: var(--muted); font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; overflow-wrap: anywhere; }
    .recycle-title { font-weight: 750; line-height: 1.35; overflow-wrap: anywhere; word-break: break-word; }
    .recycle-meta { display: flex; flex-wrap: wrap; gap: 4px 10px; color: var(--muted); font-size: 12px; margin-top: 4px; }
    .recycle-path { color: var(--muted); margin-top: 5px; line-height: 1.4; overflow-wrap: anywhere; word-break: break-word; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .recycle-preview-row, .recycle-category-row { display: flex; justify-content: space-between; gap: 10px; border-bottom: 1px solid var(--line); padding: 8px 0; }
    .recycle-preview-row:last-child, .recycle-category-row:last-child { border-bottom: 0; }
    .recycle-form input { width: 100%; }
    .recycle-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .recycle-actions .btn { width: 100%; }
    .mobile-hero { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: stretch; }
    .mobile-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
    .mobile-kpi { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfe; min-width: 0; }
    .mobile-kpi .label { color: var(--muted); font-size: 12px; }
    .mobile-kpi .value { font-size: 25px; font-weight: 750; margin-top: 5px; }
    .mobile-kpi .value.compact { font-size: 20px; line-height: 1.15; }
    .mobile-kpi .hint { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .mobile-filters { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .mobile-main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; margin-top: 14px; }
    .mobile-main > * { min-width: 0; }
    .mobile-side { display: grid; gap: 14px; }
    .mobile-toolbar { display: grid; grid-template-columns: minmax(220px, 1fr) auto; gap: 8px; align-items: center; margin-bottom: 10px; }
    .mobile-event-list, .mobile-health-list, .mobile-storage-list, .mobile-cleanup-list, .mobile-config-list, .mobile-failure-list { display: grid; gap: 8px; }
    .mobile-event-card { display: grid; grid-template-columns: 142px 96px minmax(0, 1fr); gap: 10px; border: 1px solid var(--line); border-left: 4px solid var(--accent-2); border-radius: 8px; padding: 12px; background: var(--panel); min-width: 0; }
    .mobile-event-card > * { min-width: 0; }
    .mobile-event-card.audio { border-left-color: var(--info); }
    .mobile-time { color: var(--muted); font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; overflow-wrap: anywhere; }
    .mobile-title { font-weight: 750; line-height: 1.35; overflow-wrap: anywhere; word-break: break-word; }
    .mobile-meta { display: flex; flex-wrap: wrap; gap: 4px 10px; color: var(--muted); font-size: 12px; margin-top: 4px; }
    .mobile-row { display: flex; justify-content: space-between; gap: 10px; border-bottom: 1px solid var(--line); padding: 8px 0; }
    .mobile-row:last-child { border-bottom: 0; }
    .mobile-audio-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-top: 10px; }
    .mobile-audio-stat { border: 1px solid var(--line); border-radius: 8px; padding: 9px; background: #fbfcfe; }
    .mobile-audio-stat .label { color: var(--muted); font-size: 12px; }
    .mobile-audio-stat .value { font-weight: 750; margin-top: 3px; }
    .mobile-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .mobile-actions .btn { width: 100%; }
    .sync-hero { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: stretch; }
    .sync-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
    .sync-kpi { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfe; min-width: 0; }
    .sync-kpi .label { color: var(--muted); font-size: 12px; }
    .sync-kpi .value { font-size: 25px; font-weight: 750; margin-top: 5px; }
    .sync-kpi .value.compact { font-size: 20px; line-height: 1.15; }
    .sync-kpi .hint { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .sync-filters { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .sync-main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; margin-top: 14px; }
    .sync-main > * { min-width: 0; }
    .sync-side { display: grid; gap: 14px; }
    .sync-toolbar { display: grid; grid-template-columns: minmax(220px, 1fr) auto; gap: 8px; align-items: center; margin-bottom: 10px; }
    .sync-event-list, .sync-health-list, .sync-storage-list, .sync-cleanup-list, .sync-config-list { display: grid; gap: 8px; }
    .sync-event-card { display: grid; grid-template-columns: 142px 100px minmax(0, 1fr); gap: 10px; border: 1px solid var(--line); border-left: 4px solid var(--accent-2); border-radius: 8px; padding: 12px; background: var(--panel); min-width: 0; }
    .sync-event-card > * { min-width: 0; }
    .sync-event-card.audio { border-left-color: var(--info); }
    .sync-event-card.watch { border-left-color: var(--accent-2); }
    .sync-time { color: var(--muted); font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; overflow-wrap: anywhere; }
    .sync-title { font-weight: 750; line-height: 1.35; overflow-wrap: anywhere; word-break: break-word; }
    .sync-meta { display: flex; flex-wrap: wrap; gap: 4px 10px; color: var(--muted); font-size: 12px; margin-top: 4px; }
    .sync-body { color: var(--muted); margin-top: 5px; line-height: 1.45; overflow-wrap: anywhere; word-break: break-word; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .sync-row { display: flex; justify-content: space-between; gap: 10px; border-bottom: 1px solid var(--line); padding: 8px 0; }
    .sync-row:last-child { border-bottom: 0; }
    .sync-storage-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 10px; }
    .sync-storage-tile { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #fbfcfe; min-width: 0; }
    .sync-storage-tile .label { color: var(--muted); font-size: 12px; }
    .sync-storage-tile .value { font-size: 20px; font-weight: 750; margin-top: 4px; }
    .sync-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .sync-actions .btn { width: 100%; }
    .setup-hero { display: grid; grid-template-columns: minmax(0, 1fr) 380px; gap: 14px; align-items: stretch; }
    .setup-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
    .setup-kpi { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfe; min-width: 0; }
    .setup-kpi .label { color: var(--muted); font-size: 12px; }
    .setup-kpi .value { font-size: 25px; font-weight: 750; margin-top: 5px; overflow-wrap: anywhere; word-break: break-word; }
    .setup-kpi .hint { color: var(--muted); font-size: 12px; margin-top: 3px; overflow-wrap: anywhere; word-break: break-word; }
    .setup-main { display: grid; grid-template-columns: minmax(0, 1fr) 380px; gap: 14px; align-items: start; margin-top: 14px; }
    .setup-main > * { min-width: 0; }
    .setup-stack, .setup-side, .setup-step-list, .setup-service-list, .setup-url-list, .setup-copy-list { display: grid; gap: 10px; }
    .setup-step, .setup-service, .setup-url-row, .setup-copy-row { border: 1px solid var(--line); border-radius: 8px; padding: 11px; background: #fbfcfe; min-width: 0; }
    .setup-step, .setup-service { display: grid; grid-template-columns: 92px minmax(0, 1fr) auto; gap: 10px; align-items: start; }
    .setup-title { font-weight: 800; line-height: 1.3; overflow-wrap: anywhere; }
    .setup-detail { color: var(--muted); font-size: 12px; line-height: 1.45; margin-top: 3px; overflow-wrap: anywhere; word-break: break-word; }
    .setup-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .setup-actions .btn { width: 100%; text-align: left; }
    .setup-url-row { display: grid; grid-template-columns: 112px minmax(0, 1fr) auto; gap: 10px; align-items: center; }
    .setup-url { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; overflow-wrap: anywhere; word-break: break-word; }
    .setup-token-box { border: 1px solid var(--line); border-radius: 8px; padding: 11px; background: #f8fafc; display: grid; gap: 8px; }
    .setup-token-value { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-weight: 750; overflow-wrap: anywhere; word-break: break-word; }
    .setup-progress { height: 10px; background: #e5e7eb; border-radius: 999px; overflow: hidden; margin-top: 12px; }
    .setup-progress span { display: block; height: 100%; background: var(--accent-2); }
    .settings-hero { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; }
    .settings-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
    .settings-kpi { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfe; min-width: 0; }
    .settings-kpi .label { color: var(--muted); font-size: 12px; }
    .settings-kpi .value { font-size: 25px; font-weight: 750; margin-top: 5px; overflow-wrap: anywhere; word-break: break-word; }
    .settings-kpi .value.compact { font-size: 20px; line-height: 1.15; }
    .settings-kpi .hint { color: var(--muted); font-size: 12px; margin-top: 3px; overflow-wrap: anywhere; word-break: break-word; }
    .settings-main { display: grid; grid-template-columns: minmax(0, 1fr) 380px; gap: 14px; align-items: start; margin-top: 14px; }
    .settings-main > * { min-width: 0; }
    .settings-side { display: grid; gap: 14px; }
    .settings-toolbar { display: grid; grid-template-columns: minmax(220px, 1fr) auto; gap: 8px; align-items: center; margin-bottom: 10px; }
    .settings-group-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; max-height: min(620px, calc(100vh - 220px)); overflow: auto; padding-right: 2px; }
    .settings-group-card { font: inherit; color: var(--text); text-align: left; cursor: pointer; border: 1px solid var(--line); border-left: 4px solid var(--accent-2); border-radius: 8px; padding: 12px; background: var(--panel); min-width: 0; display: grid; gap: 7px; }
    .settings-group-card:hover, .settings-group-card.active { border-color: var(--accent); background: #e9f0ff; }
    .settings-group-card.ok { border-left-color: var(--ok); }
    .settings-group-card.warn { border-left-color: var(--warn); }
    .settings-group-card.disabled { border-left-color: #94a3b8; }
    .settings-group-card[hidden] { display: none; }
    .settings-group-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-width: 0; }
    .settings-group-title { font-weight: 750; overflow-wrap: anywhere; word-break: break-word; }
    .settings-group-summary { color: var(--muted); font-size: 13px; line-height: 1.42; overflow-wrap: anywhere; word-break: break-word; }
    .settings-chip-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
    .settings-chip { border: 1px solid var(--line); border-radius: 999px; padding: 4px 9px; background: #f8fafc; color: var(--muted); font-size: 12px; overflow-wrap: anywhere; word-break: break-word; }
    .settings-action-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .settings-action-grid .btn { width: 100%; text-align: left; }
    .settings-row-list { display: grid; gap: 0; }
    .settings-row { display: grid; grid-template-columns: 136px minmax(0, 1fr); gap: 10px; border-bottom: 1px solid var(--line); padding: 9px 0; min-width: 0; }
    .settings-row:last-child { border-bottom: 0; }
    .settings-row .label { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; word-break: break-word; }
    .settings-row .value { font-weight: 650; overflow-wrap: anywhere; word-break: break-word; }
    .settings-edit-list { display: grid; gap: 10px; max-height: min(560px, calc(100vh - 260px)); overflow: auto; padding-right: 2px; }
    .settings-edit-row { display: grid; grid-template-columns: 154px minmax(0, 1fr); gap: 10px; align-items: start; border-bottom: 1px solid var(--line); padding: 10px 0; min-width: 0; }
    .settings-edit-row:last-child { border-bottom: 0; }
    .settings-edit-label { display: grid; gap: 3px; min-width: 0; }
    .settings-edit-label b { font-size: 13px; overflow-wrap: anywhere; word-break: break-word; }
    .settings-edit-label span { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; word-break: break-word; }
    .settings-edit-control { min-width: 0; }
    .settings-edit-control input:not([type="checkbox"]), .settings-edit-control select, .settings-edit-control textarea { width: 100%; }
    .settings-edit-toggle { display: inline-flex; align-items: center; gap: 8px; min-height: 38px; font-weight: 700; }
    .settings-edit-toggle input { width: 18px; height: 18px; }
    .settings-edit-actions { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; margin-top: 12px; }
    .settings-edit-note { color: var(--muted); font-size: 12px; line-height: 1.45; margin-top: 8px; }
    .settings-detail-summary { color: var(--muted); line-height: 1.45; margin: -2px 0 8px; }
    .settings-json { margin-top: 10px; border-top: 1px solid var(--line); padding-top: 9px; }
    .settings-json summary { cursor: pointer; color: var(--muted); font-size: 13px; }
    .settings-pre { max-height: 320px; overflow: auto; margin: 9px 0 0; border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #f8fafc; white-space: pre-wrap; word-break: break-word; font-size: 12px; }
    .compact-details { border-top: 1px solid var(--line); padding-top: 10px; }
    .compact-details summary { cursor: pointer; color: var(--muted); font-size: 13px; font-weight: 750; }
    .compact-details-body { margin-top: 10px; display: grid; gap: 8px; }
    .maintenance-hero { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; }
    .maintenance-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
    .maintenance-kpi { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfe; min-width: 0; }
    .maintenance-kpi .label { color: var(--muted); font-size: 12px; }
    .maintenance-kpi .value { font-size: 25px; font-weight: 750; margin-top: 5px; overflow-wrap: anywhere; word-break: break-word; }
    .maintenance-kpi .value.compact { font-size: 20px; line-height: 1.15; }
    .maintenance-kpi .hint { color: var(--muted); font-size: 12px; margin-top: 3px; overflow-wrap: anywhere; word-break: break-word; }
    .maintenance-main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; margin-top: 14px; }
    .maintenance-main > * { min-width: 0; }
    .maintenance-side { display: grid; gap: 14px; }
    .maintenance-action-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .maintenance-action-grid .btn { width: 100%; text-align: left; }
    .maintenance-list, .maintenance-source-list, .maintenance-log-list { display: grid; gap: 8px; }
    .maintenance-line { display: flex; justify-content: space-between; gap: 10px; border-bottom: 1px solid var(--line); padding: 8px 0; }
    .maintenance-line:last-child { border-bottom: 0; }
    .maintenance-source-row, .maintenance-log-row { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #fbfcfe; min-width: 0; }
    .maintenance-source-title, .maintenance-log-title { font-weight: 750; overflow-wrap: anywhere; word-break: break-word; }
    .day-toolbar { display: grid; grid-template-columns: 160px 120px 120px minmax(220px, 1fr) auto; gap: 8px; align-items: center; }
    .today-controls { display: grid; gap: 10px; }
    .quickbar { display: flex; flex-wrap: wrap; gap: 8px; }
    .filter-pill {
      border: 1px solid var(--line);
      background: var(--panel-2);
      color: var(--text);
      border-radius: 999px;
      padding: 7px 11px;
      cursor: pointer;
      font-size: 13px;
    }
    .filter-pill:hover, .filter-pill.active { border-color: var(--accent); background: #e9f0ff; color: var(--accent); }
    .today-summary { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(280px, .65fr); gap: 14px; margin-top: 14px; align-items: stretch; }
    .today-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
    .today-stat { border: 1px solid var(--line); border-radius: 8px; padding: 11px; background: #fbfcfe; min-width: 0; }
    .today-stat .value { font-size: 24px; font-weight: 750; margin-top: 4px; }
    .today-stat .label { color: var(--muted); font-size: 12px; }
    .today-stat .hint { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .hour-bars { display: grid; grid-template-columns: repeat(24, minmax(4px, 1fr)); gap: 3px; align-items: end; height: 48px; margin-top: 16px; }
    .hour-bar { min-height: 5px; border-radius: 5px 5px 2px 2px; background: var(--accent); opacity: .15; }
    .hour-axis { display: flex; justify-content: space-between; color: var(--muted); font-size: 11px; margin-top: 6px; }
    .category-strip { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
    .category-chip { display: inline-flex; gap: 7px; align-items: center; }
    .chip-count { color: var(--muted); font-variant-numeric: tabular-nums; }
    .overview-hero { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: stretch; }
    .overview-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
    .overview-kpi { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfe; min-width: 0; }
    .overview-kpi .label { color: var(--muted); font-size: 12px; }
    .overview-kpi .value { font-size: 25px; font-weight: 750; margin-top: 5px; }
    .overview-kpi .hint { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .overview-main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; margin-top: 14px; }
    .overview-main > * { min-width: 0; }
    .overview-side { display: grid; gap: 14px; }
    .overview-health { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 12px; }
    .health-item { display: flex; align-items: center; justify-content: space-between; gap: 10px; border: 1px solid var(--line); border-radius: 8px; padding: 9px 10px; background: #fbfcfe; }
    .overview-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .overview-actions .btn { width: 100%; text-align: left; }
    .overview-queue { display: grid; gap: 8px; }
    .queue-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; border-bottom: 1px solid var(--line); padding: 9px 0; }
    .queue-row:last-child { border-bottom: 0; }
    .queue-value { font-weight: 750; }
    .doctor-hero { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: stretch; }
    .doctor-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
    .doctor-kpi { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfe; min-width: 0; }
    .doctor-kpi .label { color: var(--muted); font-size: 12px; }
    .doctor-kpi .value { font-size: 25px; font-weight: 750; margin-top: 5px; }
    .doctor-kpi .hint { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .doctor-main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; margin-top: 14px; }
    .doctor-main > * { min-width: 0; }
    .doctor-side { display: grid; gap: 14px; }
    .doctor-filters { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .issue-list, .check-list, .fix-list, .area-list { display: grid; gap: 8px; }
    .issue-item, .check-row, .fix-item, .area-row { border: 1px solid var(--line); border-radius: 8px; padding: 11px; background: #fbfcfe; min-width: 0; }
    .issue-item { border-left: 4px solid var(--warn); }
    .issue-item.fail { border-left-color: var(--fail); }
    .issue-item.warn { border-left-color: var(--warn); }
    .check-row { display: grid; grid-template-columns: 74px 120px minmax(0, 1fr); gap: 10px; align-items: start; }
    .check-title { font-weight: 700; line-height: 1.35; }
    .check-message, .fix-command { color: var(--muted); margin-top: 4px; line-height: 1.45; overflow-wrap: anywhere; word-break: break-word; }
    .fix-command { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; color: var(--text); }
    .area-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; cursor: pointer; }
    .area-row.active { border-color: var(--accent); background: #e9f0ff; }
    .area-counts { display: inline-flex; flex-wrap: wrap; justify-content: flex-end; gap: 4px; color: var(--muted); font-size: 12px; }
    .audio-hero { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: stretch; }
    .audio-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
    .audio-kpi { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfe; min-width: 0; }
    .audio-kpi .label { color: var(--muted); font-size: 12px; }
    .audio-kpi .value { font-size: 25px; font-weight: 750; margin-top: 5px; }
    .audio-kpi .hint { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .audio-main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; margin-top: 14px; }
    .audio-main > * { min-width: 0; }
    .audio-side { display: grid; gap: 14px; }
    .audio-filters { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .audio-list, .audio-priority, .status-breakdown { display: grid; gap: 8px; }
    .audio-card { display: grid; grid-template-columns: 150px 112px minmax(0, 1fr); gap: 10px; border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: var(--panel); min-width: 0; }
    .audio-card > * { min-width: 0; }
    .audio-card.error, .audio-card.pending, .audio-card.missing_file { border-left: 4px solid var(--warn); }
    .audio-card.error { border-left-color: var(--fail); }
    .audio-time { color: var(--muted); font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; overflow-wrap: anywhere; }
    .audio-title { font-weight: 700; line-height: 1.35; }
    .audio-body { color: var(--muted); margin-top: 4px; line-height: 1.45; overflow-wrap: anywhere; word-break: break-word; display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; }
    .audio-list .audio-body { -webkit-line-clamp: 3; }
    .audio-path { color: var(--muted); font-size: 12px; margin-top: 5px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; overflow-wrap: anywhere; word-break: break-word; }
    .status-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; border-bottom: 1px solid var(--line); padding: 9px 0; }
    .status-row:last-child { border-bottom: 0; }
    .action-hero { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(320px, .8fr); gap: 14px; align-items: stretch; margin-top: 14px; }
    .action-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; background: var(--panel); }
    .action-kpi { padding: 14px; border-right: 1px solid var(--line); min-width: 0; }
    .action-kpi:last-child { border-right: 0; }
    .action-kpi .value { font-size: 26px; font-weight: 800; line-height: 1.1; overflow-wrap: anywhere; }
    .action-toolbar { display: grid; grid-template-columns: minmax(0, 1fr) repeat(4, auto); gap: 8px; align-items: center; }
    .action-toolbar input { width: 100%; min-width: 0; }
    .action-main { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(320px, .75fr); gap: 14px; align-items: start; margin-top: 14px; }
    .action-stack, .action-side { display: grid; gap: 14px; min-width: 0; }
    .repair-list, .suggestion-list, .project-list, .quality-list, .quick-tag-list, .highlight-list { display: grid; gap: 8px; }
    .repair-card, .suggestion-card, .project-card, .quality-card, .quick-tag-card, .highlight-card { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: var(--panel); min-width: 0; }
    .repair-card.critical { border-left: 4px solid var(--fail); }
    .repair-card.warn { border-left: 4px solid var(--warn); }
    .repair-card.info { border-left: 4px solid #64748b; }
    .repair-top, .suggestion-top, .project-top, .quality-top, .highlight-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; min-width: 0; }
    .repair-title, .suggestion-title, .project-title, .quality-title, .highlight-title { font-weight: 800; line-height: 1.35; overflow-wrap: anywhere; }
    .repair-body, .suggestion-body, .project-body, .quality-body, .highlight-body { color: var(--muted); line-height: 1.45; margin-top: 5px; overflow-wrap: anywhere; word-break: break-word; }
    .repair-evidence, .project-evidence, .quality-issues { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; min-width: 0; }
    .evidence-chip { display: inline-flex; max-width: 100%; border: 1px solid var(--line); border-radius: 999px; padding: 3px 8px; color: var(--muted); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .project-keywords, .quick-tag-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
    .quality-meter { height: 8px; background: #e5e7eb; border-radius: 999px; overflow: hidden; margin-top: 8px; }
    .quality-meter span { display: block; height: 100%; background: #2f7d57; }
    .quality-meter.weak span { background: var(--fail); }
    .quality-meter.needs_work span { background: var(--warn); }
    .evidence-groups { display: grid; gap: 10px; }
    .evidence-group { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #fbfcfe; }
    .evidence-item { border-top: 1px solid var(--line); padding-top: 8px; margin-top: 8px; }
    .insight-hero { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: stretch; margin-top: 14px; }
    .insight-toolbar { display: grid; grid-template-columns: 142px minmax(180px, 1fr) 150px 150px auto; gap: 8px; align-items: center; }
    .insight-toolbar.projects { grid-template-columns: 142px minmax(180px, 1fr) 150px 150px auto; }
    .insight-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 12px; }
    .insight-kpi { border: 1px solid var(--line); border-radius: 8px; padding: 11px; background: #fbfcfe; min-width: 0; }
    .insight-kpi .label { color: var(--muted); font-size: 12px; }
    .insight-kpi .value { font-size: 24px; font-weight: 800; margin-top: 4px; overflow-wrap: anywhere; }
    .insight-kpi .hint { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .insight-main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; margin-top: 14px; }
    .insight-main > * { min-width: 0; }
    .insight-side { display: grid; gap: 14px; }
    .insight-list { display: grid; gap: 9px; max-height: min(760px, calc(100vh - 220px)); overflow: auto; padding-right: 2px; }
    .insight-card { border: 1px solid var(--line); border-left: 4px solid var(--accent); border-radius: 8px; padding: 12px; background: var(--panel); min-width: 0; }
    .insight-card.high { border-left-color: var(--fail); }
    .insight-card.medium { border-left-color: var(--warn); }
    .insight-card.project { border-left-color: var(--accent-2); }
    .insight-card.done, .insight-card.archived, .insight-card.dismissed { opacity: .72; }
    .insight-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; min-width: 0; }
    .insight-title { font-weight: 800; line-height: 1.35; overflow-wrap: anywhere; word-break: break-word; }
    .insight-body { color: var(--muted); line-height: 1.5; margin-top: 7px; overflow-wrap: anywhere; word-break: break-word; }
    .insight-chips, .insight-actions { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 9px; }
    .insight-actions .btn { min-width: 92px; }
    .insight-note { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; margin-top: 9px; align-items: start; }
    .insight-note textarea { min-height: 52px; }
    .insight-evidence { margin-top: 10px; border-top: 1px solid var(--line); padding-top: 8px; }
    .insight-evidence summary { cursor: pointer; color: var(--muted); font-weight: 750; font-size: 13px; }
    .insight-evidence-list { display: grid; gap: 8px; margin-top: 8px; }
    .insight-evidence-row { border: 1px solid var(--line); border-radius: 8px; padding: 9px; background: #fbfcfe; min-width: 0; }
    .insight-evidence-row b { overflow-wrap: anywhere; word-break: break-word; }
    .insight-state-list, .insight-breakdown { display: grid; gap: 8px; }
    .insight-state-row { display: flex; justify-content: space-between; align-items: center; gap: 10px; border-bottom: 1px solid var(--line); padding: 8px 0; }
    .insight-state-row:last-child { border-bottom: 0; }
    .evidence-item:first-of-type { border-top: 0; padding-top: 0; margin-top: 0; }
    .today-main { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 14px; align-items: start; margin-top: 14px; width: 100%; min-width: 0; max-width: 100%; overflow-x: hidden; }
    .today-main > *, .today-sidebar, .day-list, .day-section { min-width: 0; }
    .today-sidebar { display: grid; gap: 14px; position: sticky; top: 24px; }
    .day-section { display: grid; gap: 8px; margin-bottom: 16px; }
    .day-section-header { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 2px 2px 0; }
    .day-section-header h3 { margin: 0; font-size: 15px; }
    .day-feed { max-height: min(760px, calc(100vh - 220px)); overflow: auto; padding-right: 2px; }
    .day-list { display: grid; gap: 8px; }
    .day-event { display: grid; grid-template-columns: 74px 104px minmax(0, 1fr); gap: 10px; padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); max-width: 100%; overflow: hidden; }
    .day-event > * { min-width: 0; }
    .day-event:hover { border-color: #aeb8c9; }
    .event-time { color: var(--muted); font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; overflow-wrap: anywhere; word-break: break-word; }
    .event-title { font-weight: 700; line-height: 1.35; overflow-wrap: anywhere; word-break: break-word; }
    .event-body { color: var(--muted); margin-top: 4px; line-height: 1.45; overflow-wrap: anywhere; word-break: break-word; }
    .event-meta { display: flex; flex-wrap: wrap; gap: 4px 10px; color: var(--muted); font-size: 12px; margin-top: 4px; min-width: 0; max-width: 100%; overflow-wrap: anywhere; word-break: break-word; }
    .event-meta span { min-width: 0; max-width: 100%; overflow-wrap: anywhere; word-break: break-word; }
    .empty-state { border: 1px dashed var(--line); border-radius: 8px; padding: 18px; color: var(--muted); background: #fbfcfe; }
    .category { display: inline-flex; align-items: center; width: fit-content; border-radius: 999px; padding: 4px 9px; font-size: 12px; font-weight: 700; background: #edf2f7; color: #1f2937; }
    .category.audio { background:#e5eefb; color:#225a9b; }
    .category.app { background:#e8f4ef; color:#127a4a; }
    .category.chat { background:#f3e8ff; color:#6d28d9; }
    .category.file { background:#fff1d6; color:#a85f00; }
    .category.location { background:#e0f2fe; color:#075985; }
    .category.reminder, .category.calendar { background:#fde7e5; color:#b3261e; }
    .feedback-row { border-bottom: 1px solid var(--line); padding: 9px 0; }
    .feedback-row:last-child { border-bottom: 0; }
    .has-tip { position: relative; }
    .button-tooltip {
      position: fixed;
      display: none;
      max-width: min(340px, calc(100vw - 24px));
      padding: 8px 10px;
      border-radius: 8px;
      background: #111827;
      color: #fff;
      font-size: 12px;
      line-height: 1.45;
      box-shadow: var(--shadow);
      pointer-events: none;
      z-index: 30;
    }
    .button-tooltip.show { display: block; }
    .toast { position: fixed; right: 18px; bottom: 18px; background: #111827; color: #fff; padding: 12px 14px; border-radius: 8px; max-width: 560px; box-shadow: var(--shadow); display: none; white-space: pre-wrap; z-index: 10; }
    .toast.show { display: block; }
    .section-title { display:flex; justify-content:space-between; align-items:center; gap:10px; margin-bottom:10px; }
    .section-title h3 { margin:0; font-size:16px; }
    .repair-body, .suggestion-body, .project-body, .quality-issues, .highlight-body, .source-issue-body, .check-message {
      display: -webkit-box;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 4;
      overflow: hidden;
    }
    .project-body, .highlight-body, .source-issue-body, .check-message { -webkit-line-clamp: 3; }
    .repair-list, .suggestion-list, .project-list, .quality-list, .highlight-list, .issue-list, .fix-list, .area-list, .speaker-grid, .speaker-match-list, .speaker-sample-list, .audio-list, .file-list, .sync-event-list, .source-grid, .reports-list, .check-list {
      max-height: min(620px, calc(100vh - 220px));
      overflow: auto;
      padding-right: 2px;
    }
    .speaker-sample-list { max-height: 520px; }
    .speaker-match-list { max-height: 360px; }
    @media (max-width: 1080px) {
      .app { grid-template-columns: 1fr; }
      aside { position: static; height: auto; }
      nav { grid-template-columns: repeat(2, minmax(0,1fr)); }
      .grid.cols-4, .grid.cols-3, .grid.cols-2, .split, .reports-layout, .reports-metrics, .day-layout, .day-toolbar, .today-summary, .today-main, .today-stats, .action-hero, .action-main, .action-kpis, .action-toolbar, .insight-hero, .insight-main, .insight-kpis, .insight-toolbar, .overview-hero, .overview-main, .overview-kpis, .doctor-hero, .doctor-main, .doctor-kpis, .check-row, .audio-hero, .audio-main, .audio-kpis, .audio-card, .searchbar, .search-hero, .search-main, .search-answer-layout, .search-retrieval, .search-index-grid, .search-metric-grid, .timeline-hero, .timeline-toolbar, .timeline-stats, .timeline-main, .timeline-event, .sources-hero, .source-kpis, .source-action-grid, .sources-main, .source-grid, .source-kind-row, .speakers-hero, .speaker-command-row, .speaker-filter-row, .speaker-review-toolbar, .speaker-sample-toolbar, .speaker-selection-grid, .speaker-bulk-actions, .speaker-bulk-row, .speaker-tool-row, .speakers-main, .speaker-grid, .files-hero, .file-kpis, .file-main, .file-toolbar, .file-card, .recycle-hero, .recycle-kpis, .recycle-main, .recycle-toolbar, .recycle-card, .recycle-actions, .mobile-hero, .mobile-kpis, .mobile-main, .mobile-toolbar, .mobile-event-card, .mobile-audio-grid, .mobile-actions, .sync-hero, .sync-kpis, .sync-main, .sync-toolbar, .sync-event-card, .sync-storage-grid, .sync-actions, .setup-hero, .setup-kpis, .setup-main, .setup-step, .setup-service, .setup-actions, .setup-url-row, .settings-hero, .settings-kpis, .settings-main, .settings-toolbar, .settings-group-grid, .settings-action-grid, .settings-row, .settings-edit-row, .maintenance-hero, .maintenance-kpis, .maintenance-main, .maintenance-action-grid { grid-template-columns: 1fr; }
      .today-stats, .timeline-stats, .overview-kpis, .doctor-kpis, .audio-kpis, .source-kpis, .file-kpis, .sync-kpis, .setup-kpis, .settings-kpis, .maintenance-kpis, .action-kpis, .insight-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .action-kpi { border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); }
      .action-kpi:nth-child(2n) { border-right: 0; }
      .action-kpi:nth-last-child(-n+2) { border-bottom: 0; }
      .speaker-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .speaker-kpi:nth-child(2n) { border-right: 0; }
      .speaker-kpi:nth-child(-n+2) { border-bottom: 1px solid var(--line); }
      .searchbar { grid-template-columns: 1fr; }
      .day-event { grid-template-columns: 1fr; }
      .today-sidebar { position: static; }
      .overview-health, .overview-actions { grid-template-columns: 1fr; }
      .reports-side { position: static; }
    }
    @media (max-width: 720px) {
      main { padding: 14px; }
      aside { padding: 12px; }
      nav { grid-template-columns: 1fr; gap: 8px; }
      .brand { padding-bottom: 10px; }
      .topbar { display: grid; gap: 12px; margin-bottom: 12px; }
      h2 { font-size: 23px; }
      .toolbar { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); width: 100%; }
      .toolbar .btn { width: 100%; }
      .card { padding: 12px; }
      .section-title { align-items: flex-start; flex-wrap: wrap; }
      .section-title h3 { font-size: 15px; }
      .filter-pill { padding: 6px 9px; }
      .reports-layout { display: grid; }
      .report-reader { order: -1; min-height: 0; }
      .reports-nav { order: 0; }
      .reports-side { order: 1; }
      .day-feed, .timeline-feed, .repair-list, .suggestion-list, .project-list, .quality-list, .highlight-list, .insight-list, .issue-list, .fix-list, .area-list, .speaker-grid, .speaker-match-list, .speaker-sample-list, .audio-list, .file-list, .sync-event-list, .source-grid, .reports-list, .check-list, .report-reader-content, .settings-group-grid, .settings-edit-list {
        max-height: 460px;
      }
      .speaker-match-list { max-height: 320px; }
      .timeline-breakdown { max-height: 300px; }
    }
  </style>
</head>
<body>
<div class="app">
  <aside>
    <div class="brand"><div class="mark"></div><div><h1>Wond</h1><span>Local control center</span></div></div>
    <nav id="nav"></nav>
  </aside>
  <main>
    <div class="topbar">
      <div><h2 id="title">总览</h2><div id="subtitle" class="subtitle"></div></div>
      <div class="toolbar" id="toolbar"></div>
    </div>
    <div id="view"></div>
  </main>
</div>
<div id="toast" class="toast"></div>
<div id="buttonTooltip" class="button-tooltip" role="tooltip"></div>
<script>
const sections = [
  ['today','今天'], ['action','行动'], ['suggestions','行动建议'], ['projects','项目'], ['search','搜索问答'],
  ['audio','音频队列'], ['speakers','说话人'],
  ['files','文件'], ['sources','来源'], ['reports','报告'],
  ['setup','设置向导'], ['sync','手机同步'], ['doctor','Doctor'], ['settings','设置']
];
const utilitySections = [
  ['overview','总览'], ['timeline','时间线'], ['recycle','回收箱'], ['maintenance','记录维护']
];
const allSections = [...sections, ...utilitySections];
const sectionGroups = {
  today:'日常', action:'日常', suggestions:'日常', projects:'日常', search:'日常',
  audio:'音频', speakers:'音频',
  files:'资料', sources:'资料', reports:'资料',
  setup:'系统', sync:'系统', doctor:'系统', settings:'系统',
  overview:'低频维护工具', timeline:'低频维护工具', recycle:'低频维护工具', maintenance:'低频维护工具'
};
const navParents = {overview:'today', timeline:'today', recycle:'files', maintenance:'settings'};
const state = { section: 'today', setupToken: '', actionDate: 'today', actionView: 'repairs', suggestionDate: 'today', suggestionStatus: 'active', suggestionPriority: 'all', suggestionSource: 'all', suggestionQ: '', projectDate: 'today', projectStatus: 'active', projectSource: 'all', projectQ: '', reportPath: '', reportQ: '', reportCategory: 'all', audioStatus: '', sourceView: 'all', speakerView: 'active', speakerQ: '', speakerSort: 'review', speakerSelectedIds: [], speakerShownIds: [], speakerBulkTarget: '', speakerSamplesFor: 'visible', speakerSampleView: 'all', speakerSampleQ: '', speakerSampleSort: 'needs_work', speakerContextSource: 'idle', speakerSamples: [], fileView: 'all', fileQ: '', recycleView: 'all', recycleQ: '', syncView: 'all', syncQ: '', settingsGroup: 'collectors', settingsQ: '', timelineDate: 'today', timelineQ: '', timelineSource: 'all', timelineType: 'all', todayDate: 'today', todayQ: '', todayFrom: '', todayTo: '', todayCategory: 'all', doctorStatus: 'all', doctorArea: 'all', searchQ: '', searchSource: '', searchQuestion: '' };
const searchSources = [['','全部来源'], ['mobile','mobile'], ['local_ai','local_ai'], ['report','report'], ['filesystem','filesystem'], ['browser','browser'], ['apple_mail','apple_mail']];
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const escAttr = (s) => String(s ?? '').replace(/\\/g, '\\\\').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/'/g, "\\'").replace(/\n/g, ' ');
const jstr = (s) => JSON.stringify(String(s ?? ''));
const status = (s) => `<span class="status ${esc(s || 'info')}">${esc(s || 'info')}</span>`;
const sectionTips = {
  action: '把今天的重点、待修复项、行动建议、项目聚类和说话人质量收在一个工作台。',
  suggestions: '把录音、快速标注、日程和文件里检测出的待办集中处理。',
  projects: '按证据自动聚合今天的主题、项目和相关下一步。',
  today: '打开实时日内时间线，合并应用、录音、文件、位置和提醒。',
  overview: '查看系统数据量、健康状态、最近采集和维护入口。',
  doctor: '运行本机诊断，检查采集器、同步服务、本地 AI 和数据质量。',
  audio: '查看移动端录音分析队列，并手动触发转写和摘要。',
  search: '对本地记忆做关键词搜索、语义检索和本地问答。',
  timeline: '查看原始事件流，适合排查某一天的底层记录。',
  reports: '打开日报、长期摘要、邮件摘要和反馈记录。',
  sources: '检查各数据来源是否开启、最近是否采集，以及缺少哪些前置文件。',
  speakers: '查看说话人聚类、样本、重命名和合并入口。',
  files: '查看文件监控路径、分析状态，并手动扫描新文件。',
  recycle: '查看分析后暂存的回收文件，预览清理或恢复文件。',
  mobile: '已整合到手机同步页。',
  setup: '按当前机器状态完成首次配置、手机同步 token、Mac 服务和 iPhone 连接地址。',
  sync: '查看 Mac/手机连接、上传缓存、导入缓存、音频分析、去重和清理预览。',
  maintenance: '统一预览和执行数据库记录、运行日志、缓存和回收箱清理。',
  settings: '查看当前解析后的配置，敏感字段会被隐藏。'
};
const actionTips = {
  collect: '立即采集当天数据，并按配置刷新报告。',
  analyze_audio: '处理待分析录音，生成转写、摘要和说话人线索。',
  refresh_report: '重新生成今天的日报和摘要文件。',
  retention: '预览或执行长期保留策略，清理已压缩的旧数据。',
  email_due: '检查当前是否有到期的邮件摘要。',
  compact: '把当天资料压缩进长期日/周/月记忆。',
  install_agent: '安装或重载 Mac 后台采集 LaunchAgent。',
  install_sync_agent: '安装或重载手机上传接收服务。',
  install_dashboard_agent: '安装或重载桌面 dashboard 服务。',
  search_index: '重建本地语义搜索索引，供问答和相似检索使用。',
  speaker_rename: '把选中的说话人 ID 改成真实显示名。',
  speaker_normalize_names: '把自动生成的局部 Speaker 名整理成稳定的全局 Voice ID。',
  speaker_merge: '把一个说话人合并到另一个说话人。',
  speaker_merge_many: '把多个已勾选的说话人一次合并到同一个目标。',
  speaker_delete: '删除一个说话人及其托管样本记录。',
  speaker_delete_many: '一次删除多个已勾选的说话人及其托管样本记录。',
  speaker_detach_sample: '把这条样本从当前说话人中分离出来，单独新建一个 Voice。',
  speaker_refresh_sample_confidence: '重新计算说话人的 embedding 聚类一致性，并刷新每条样本相对当前聚类的一致性。',
  speaker_repair_sample_clips: '按当前裁剪策略重裁筛选出来的说话人样本，并重新计算变更样本的 embedding。',
  speaker_auto_organize: '按 0.68 自动合并相似声音，并隐藏低相似未命名 Voice。',
  speaker_confirm: '确认这些说话人整理结果正确，后续自动整理不会主动隐藏它们。',
  speaker_unhide: '把低相似隐藏 Voice 放回人工复查列表。',
  analyze_new_files: '扫描监控路径里的新文件，并用本地分析流程处理。',
  recycle_purge: '预览或执行回收箱到期清理。',
  recycle_restore: '把回收箱中的文件恢复到原路径或指定路径。',
  mobile_cleanup: '预览或执行移动端上传缓存和无引用导入目录清理。'
};
const labelTips = {
  '采集': '立即更新今天的资料，不等待后台定时采集。',
  '分析音频': '处理今天尚未完成的录音分析。',
  '刷新': '重新读取当前页面的数据。',
  '查找': '按日期、时间段和关键词筛选今天的事件。',
  '写入长期记忆': '把这条反馈保存到数据库、反馈摘要和本地检索资料里。',
  '采集并写报告': '采集今天的数据并刷新今天报告。',
  '刷新今日报告': '基于已有数据重新生成今天报告。',
  '生成新 token': '生成新的手机同步密钥并写入 config.json；旧 iPhone 配置需要同步更新。',
  '安装全部服务': '依次安装并加载同步、后台采集和 dashboard 服务。',
  '复制': '复制这一项到剪贴板。',
  '复制 token': '复制刚生成的新 token。',
  '复制 URL': '复制这个 Mac 同步地址。',
  'Run checks': '重新运行 Doctor 诊断。',
  'Run 5': '从音频队列中处理最多 5 条。',
  'Run 20': '从音频队列中处理最多 20 条。',
  '分析 5 条': '从音频队列中处理最多 5 条。',
  '分析 10 条': '从音频队列中处理最多 10 条。',
  '分析 20 条': '从音频队列中处理最多 20 条。',
  '分析 50 条': '从音频队列中处理最多 50 条。',
  '底层时间线': '打开原始事件流，用于排查某一天的底层记录。',
  'Refresh': '重新读取当前页面的数据。',
  'All': '清除当前筛选，显示全部记录。',
  'Index status': '刷新语义索引状态。',
  'Build semantic index': '重建本地 embedding 索引。',
  'Search': '搜索本地 observations、报告和语义索引。',
  'Ask local data': '用本地检索结果向本地模型提问。',
  'Load': '载入指定日期的数据。',
  'Refresh today': '重新生成今天的报告。',
  'Rename': '将指定说话人 ID 重命名。',
  '整理自动名': '把未人工命名的 Speaker 1/2/数字标签改成稳定的 Voice ID。',
  'Merge': '把重复说话人合并到保留 ID。',
  '清空选择': '清空当前勾选的说话人。',
  '选择当前筛选': '勾选当前筛选结果里显示的所有说话人。',
  '反选当前筛选': '切换当前筛选结果里的勾选状态。',
  '合并选中': '把所有已勾选说话人合并到指定目标。',
  '删除选中': '删除所有已勾选说话人、aliases、样本记录和托管样本文件。',
  'Scan now': '立即扫描并分析新文件。',
  'Purge dry-run': '只预览会清理哪些回收文件。',
  'Purge due now': '永久删除已到期的回收文件。',
  'Restore': '恢复选中的回收文件。',
  'Cleanup dry-run': '只预览移动端缓存清理结果。',
  'Apply cleanup': '执行移动端缓存清理。',
  '手机同步': '查看手机同步、Mac 在线状态、上传缓存和音频分析。',
  '记录维护': '统一清理旧事件、运行记录、日志、缓存和回收箱。',
  '记录预览': '预览按保留策略会清理哪些旧数据库记录、报告和日志。',
  '执行记录清理': '按保留策略实际删除旧数据库记录、报告并裁剪过大的日志。',
  '缓存预览': '预览移动端上传缓存和无引用导入目录清理。',
  '执行缓存清理': '执行移动端上传缓存和无引用导入目录清理。',
  '回收箱预览': '预览哪些回收箱文件已经到期。',
  '清理回收箱': '永久删除已经到期的回收箱文件。',
  'Doctor': '跳转到诊断页，检查配置关联的采集器、服务和模型。',
  '保留预览': '只预览长期保留策略会清理的内容。',
  '执行保留': '执行长期保留清理策略。',
  'Apply retention': '执行长期保留清理策略。',
  '保存设置': '把当前分组的可编辑配置写入 config.json。',
  '重载 Agent': '重新加载后台采集服务，让采集、音频、文件分析等配置生效。',
  '重载同步服务': '重新加载手机上传接收服务，让端口、上传限制和导入策略生效。',
  '重载 Dashboard': '重新加载桌面 dashboard 服务。'
};
let buttonTipObserver = null;
let activeTipButton = null;
function toast(msg){ const el=$('toast'); el.textContent=msg; el.classList.add('show'); setTimeout(()=>el.classList.remove('show'), 6500); }
async function api(path, opts){ const r=await fetch(path, opts); const j=await r.json(); if(!r.ok) throw new Error(j.error || r.statusText); return j; }
function canonicalSection(id){ return id === 'mobile' ? 'sync' : (id || 'today'); }
function isKnownSection(id){ return allSections.some(s=>s[0]===id); }
function nav(){
  const groups = [];
  sections.forEach(([id,label]) => {
    const group = sectionGroups[id] || '其他';
    let bucket = groups.find(item => item.name === group);
    if(!bucket){ bucket = {name: group, items: []}; groups.push(bucket); }
    bucket.items.push([id,label]);
  });
  $('nav').innerHTML = groups.map(group => `<div class="nav-group"><div class="nav-label">${esc(group.name)}</div>${group.items.map(([id,label]) => {
    const active = state.section === id || navParents[state.section] === id;
    return `<button class="${active?'active':''}" onclick="go('${id}')">${esc(label)}</button>`;
  }).join('')}</div>`).join('');
}
function setHeader(title, subtitle='', buttons=''){ hideButtonTip(); $('title').textContent=title; $('subtitle').textContent=subtitle; $('toolbar').innerHTML=buttons; nav(); }
async function action(name,args={}){ const j=await api('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,args})}); toast(`${j.ok?'OK':'FAILED'} ${name}\n${j.stdout || j.stderr || ''}`); render(); }
async function go(id){ state.section=canonicalSection(id); history.replaceState(null,'','#'+state.section); render(); }
function metrics(items){ return `<div class="grid cols-4">${items.map(x=>`<div class="card metric"><div class="label">${esc(x[0])}</div><div class="value">${esc(x[1])}</div><div class="hint">${esc(x[2]||'')}</div></div>`).join('')}</div>`; }
function startButtonTips(){
  applyButtonTips(document);
  document.addEventListener('mouseover', onTipEnter);
  document.addEventListener('focusin', onTipEnter);
  document.addEventListener('mousemove', onTipMove);
  document.addEventListener('mouseout', onTipLeave);
  document.addEventListener('focusout', onTipLeave);
  document.addEventListener('keydown', (event) => { if(event.key === 'Escape') hideButtonTip(); });
  if(window.MutationObserver && !buttonTipObserver){
    buttonTipObserver = new MutationObserver(() => applyButtonTips(document));
    buttonTipObserver.observe(document.body, { childList: true, subtree: true });
  }
}
function applyButtonTips(root=document){
  root.querySelectorAll('button').forEach(button => {
    const tip = button.dataset.tip || inferButtonTip(button);
    if(!tip) return;
    button.dataset.tip = tip;
    button.setAttribute('aria-label', `${buttonText(button)}：${tip}`);
    button.setAttribute('title', tip);
    button.classList.add('has-tip');
  });
}
function inferButtonTip(button){
  const explicit = button.getAttribute('data-tip');
  if(explicit) return explicit;
  const click = button.getAttribute('onclick') || '';
  const goMatch = click.match(/go\('([^']+)'\)/);
  if(goMatch && sectionTips[goMatch[1]]) return sectionTips[goMatch[1]];
  const actionMatch = click.match(/action\('([^']+)'/);
  if(actionMatch && actionTips[actionMatch[1]]) return actionTips[actionMatch[1]];
  if(click.includes('restoreRecycle')) return actionTips.recycle_restore;
  if(click.includes('refreshSpeakerSampleConfidence') || click.includes('refreshSelectedSpeakerSampleConfidence')) return actionTips.speaker_refresh_sample_confidence;
  if(click.includes('refreshVisibleSpeakerSampleConfidence')) return actionTips.speaker_refresh_sample_confidence;
  if(click.includes('refreshFocusedSampleSpeakerConfidence')) return actionTips.speaker_refresh_sample_confidence;
  if(click.includes('autoOrganizeSpeakers')) return actionTips.speaker_auto_organize;
  if(click.includes('confirmSelectedSpeakers')) return actionTips.speaker_confirm;
  if(click.includes('confirmVisibleSpeakers')) return actionTips.speaker_confirm;
  if(click.includes('unhideSelectedSpeakers')) return actionTips.speaker_unhide;
  if(click.includes('unhideVisibleSpeakers')) return actionTips.speaker_unhide;
  if(click.includes('submitFeedback')) return labelTips['写入长期记忆'];
  if(click.includes('doSearch')) return labelTips.Search;
  if(click.includes('doAsk')) return labelTips['Ask local data'];
  if(click.includes('refreshSearchIndex')) return labelTips['Index status'];
  if(click.includes('state.todayDate')) return labelTips['查找'];
  if(click.includes('state.timelineDate')) return labelTips.Load;
  if(click.includes('state.audioStatus')) return '按这个状态筛选音频队列。';
  const text = buttonText(button);
  return labelTips[text] || null;
}
function buttonText(button){ return button.textContent.replace(/\s+/g, ' ').trim(); }
function onTipEnter(event){
  const button = event.target.closest && event.target.closest('button[data-tip]');
  if(!button) return;
  activeTipButton = button;
  showButtonTip(button, event);
}
function onTipMove(event){
  if(!activeTipButton) return;
  positionButtonTip(event.clientX, event.clientY);
}
function onTipLeave(event){
  const button = event.target.closest && event.target.closest('button[data-tip]');
  if(!button || button !== activeTipButton) return;
  if(event.relatedTarget && button.contains(event.relatedTarget)) return;
  hideButtonTip();
}
function showButtonTip(button, event){
  const el = $('buttonTooltip');
  el.textContent = button.dataset.tip || '';
  if(!el.textContent) return;
  el.classList.add('show');
  const rect = button.getBoundingClientRect();
  positionButtonTip(event.clientX || rect.left + rect.width / 2, event.clientY || rect.bottom);
}
function hideButtonTip(){
  activeTipButton = null;
  const el = $('buttonTooltip');
  if(el) el.classList.remove('show');
}
function positionButtonTip(x, y){
  const el = $('buttonTooltip');
  if(!el || !el.classList.contains('show')) return;
  const margin = 12;
  const rect = el.getBoundingClientRect();
  let left = x + margin;
  let top = y + margin;
  if(left + rect.width > window.innerWidth - margin) left = Math.max(margin, window.innerWidth - rect.width - margin);
  if(top + rect.height > window.innerHeight - margin) top = Math.max(margin, y - rect.height - margin);
  el.style.left = `${left}px`;
  el.style.top = `${top}px`;
}
async function actionCenter(){
  const buttons = `<button class="btn" onclick="action('collect',{date:'today'})">采集</button><button class="btn" onclick="action('analyze_audio',{date:${jstr(state.actionDate || 'today')},limit:20})">分析音频</button><button class="btn" onclick="action('search_index',{limit:5000})">刷新索引</button><button class="btn primary" onclick="actionCenter()">刷新</button>`;
  setHeader('行动','读取中...', buttons);
  const [center, quality] = await Promise.all([
    api(`/api/action-center?date=${encodeURIComponent(state.actionDate || 'today')}`),
    api('/api/speaker-quality?view=needs_work')
  ]);
  const summary = center.summary || {};
  const qualitySummary = quality.summary || {};
  $('subtitle').textContent = `${center.date || ''} · ${summary.priority_repairs || 0} 待修复 · ${summary.suggestions || 0} 行动建议 · ${summary.projects || 0} 项目`;
  $('view').innerHTML = `
    <div class="action-hero">
      <section class="card">
        <div class="section-title"><h3>今天的操作台</h3><span class="muted">${esc(shortDateTime(center.generated_at || ''))}</span></div>
        <div class="action-toolbar">
          <input value="${escAttr(state.actionDate || 'today')}" onchange="state.actionDate=this.value || 'today'; actionCenter()" placeholder="today / yesterday / YYYY-MM-DD">
          <button class="filter-pill ${state.actionView==='all'?'active':''}" onclick="setActionView('all')">全部</button>
          <button class="filter-pill ${state.actionView==='repairs'?'active':''}" onclick="setActionView('repairs')">修复</button>
          <button class="filter-pill ${state.actionView==='suggestions'?'active':''}" onclick="setActionView('suggestions')">行动</button>
          <button class="filter-pill ${state.actionView==='projects'?'active':''}" onclick="setActionView('projects')">项目</button>
        </div>
        <div class="action-kpis" style="margin-top:12px">
          ${actionKpi('记录', summary.observations || 0, `${summary.activity_samples || 0} app samples`)}
          ${actionKpi('待修复', summary.priority_repairs || 0, 'critical / warn')}
          ${actionKpi('行动建议', summary.suggestions || 0, '从录音和记录提取')}
          ${actionKpi('Speaker', qualitySummary.needs_work || 0, `avg ${qualitySummary.average_score || 0}`)}
        </div>
      </section>
      <section class="card">
        <div class="section-title"><h3>快速流转</h3><span class="muted">可执行</span></div>
        <div class="overview-actions">
          <button class="btn primary" onclick="runFirstRepair()">执行第一条修复</button>
          <button class="btn" onclick="go('suggestions')">行动建议</button>
          <button class="btn" onclick="go('projects')">项目聚类</button>
          <button class="btn" onclick="go('search')">证据问答</button>
          <button class="btn" onclick="go('today')">今天时间线</button>
        </div>
        <div class="quick-tag-row">${quickTagChips(center.quick_tags || [])}</div>
      </section>
    </div>
    <div class="action-main">
      <div class="action-stack">
        <section class="card action-section" data-action-section="repairs">
          <div class="section-title"><h3>待修复队列</h3><span class="muted">${esc((center.repair_queue || []).length)} items</span></div>
          ${repairList(center.repair_queue || [])}
        </section>
        <section class="card action-section" data-action-section="suggestions">
          <div class="section-title"><h3>自动行动建议</h3><span class="muted">${esc((center.suggestions || []).length)} candidates</span></div>
          ${suggestionList(center.suggestions || [])}
        </section>
        <section class="card action-section" data-action-section="projects">
          <div class="section-title"><h3>项目 / 主题聚类</h3><span class="muted">${esc((center.projects || []).length)} clusters</span></div>
          ${projectList(center.projects || [])}
        </section>
      </div>
      <div class="action-side">
        <section class="card">
          <div class="section-title"><h3>今日重点</h3><span class="muted">${esc((center.highlights || []).length)} highlights</span></div>
          ${highlightList(center.highlights || [])}
        </section>
        <section class="card action-section" data-action-section="speakers">
          <div class="section-title"><h3>说话人质量</h3><span class="muted">${esc(qualitySummary.needs_work || 0)} need work</span></div>
          ${qualityList(quality.speakers || [])}
        </section>
      </div>
    </div>`;
  window.__actionCenterData = center;
  applyActionView();
}
function setActionView(value){
  state.actionView = value || 'all';
  applyActionView();
}
function applyActionView(){
  document.querySelectorAll('.action-section').forEach(section => {
    const key = section.dataset.actionSection || '';
    section.style.display = state.actionView === 'all' || state.actionView === key ? '' : 'none';
  });
}
function actionKpi(label, value, hint){
  return `<div class="action-kpi"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint || '')}</div></div>`;
}
function repairList(rows){
  if(!(rows || []).length) return '<div class="empty-state">没有需要处理的修复项</div>';
  return `<div class="repair-list">${rows.map(repairCard).join('')}</div>`;
}
function repairCard(item){
  const actionButton = item.action ? `<button class="btn primary" data-action="${escAttr(JSON.stringify(item.action))}" onclick="runCardAction(this)">${esc(item.action.label || '执行')}</button>` : '';
  return `<div class="repair-card ${esc(item.severity || 'info')}">
    <div class="repair-top"><div><div class="repair-title">${esc(item.title || item.id)}</div><div class="item-meta">${esc(item.area || '')}</div></div>${status(item.severity || 'info')}</div>
    <div class="repair-body">${esc(item.body || '')}</div>
    ${evidenceChips(item.evidence || [])}
    ${actionButton ? `<div class="search-actions" style="margin-top:10px">${actionButton}</div>` : ''}
  </div>`;
}
function suggestionList(rows){
  if(!(rows || []).length) return '<div class="empty-state">没有检测到新的行动建议</div>';
  return `<div class="suggestion-list">${rows.map(item => `<div class="suggestion-card">
    <div class="suggestion-top"><div><div class="suggestion-title">${esc(item.title)}</div><div class="item-meta">${esc(shortDateTime(item.observed_at || ''))} · ${esc(item.source || '')}/${esc(item.kind || '')}</div></div>${status(item.priority)}</div>
    <div class="suggestion-body">${esc(item.body || '')}</div>
    <div class="project-keywords"><span class="evidence-chip">${esc((item.recommended_action || {}).label || '稍后处理')}</span><span class="evidence-chip">${esc(item.reason || '')}</span></div>
  </div>`).join('')}</div>`;
}
function projectList(rows){
  if(!(rows || []).length) return '<div class="empty-state">今天还没有形成明显项目聚类</div>';
  return `<div class="project-list">${rows.map(item => `<div class="project-card">
    <div class="project-top"><div><div class="project-title">${esc(item.title)}</div><div class="item-meta">${esc(shortDateTime((item.time_span || {}).start || ''))} -> ${esc(shortDateTime((item.time_span || {}).end || ''))}</div></div><span class="status ok">${esc(Math.round(Number(item.confidence || 0) * 100))}%</span></div>
    <div class="project-body">${esc(item.summary || '')}</div>
    <div class="project-keywords">${(item.keywords || []).map(keyword => `<span class="evidence-chip">${esc(keyword)}</span>`).join('')}</div>
    ${evidenceChips(item.evidence || [])}
  </div>`).join('')}</div>`;
}
function qualityList(rows){
  if(!(rows || []).length) return '<div class="empty-state">说话人质量目前没有明显待处理项</div>';
  return `<div class="quality-list">${rows.slice(0, 6).map(item => `<div class="quality-card">
    <div class="quality-top"><div><div class="quality-title">${esc(item.display_name)}</div><div class="item-meta">${esc(item.sample_count)} samples · ${esc(item.day_count)} days · ${esc(item.identity_status)}</div></div><span class="status ${item.score >= 75 ? 'ok' : 'warn'}">${esc(item.score)}</span></div>
    <div class="quality-meter ${esc(item.grade)}"><span style="width:${Math.max(0, Math.min(100, Number(item.score || 0)))}%"></span></div>
    <div class="quality-issues">${(item.issues || []).map(issue => `<span class="evidence-chip">${esc(issue.label || issue.kind)}</span>`).join('') || '<span class="evidence-chip">无明显问题</span>'}</div>
    <div class="search-actions" style="margin-top:8px">${(item.recommendations || []).slice(0,2).map(rec => `<button class="btn" data-action="${escAttr(JSON.stringify({name:rec.action,args:rec.args || {},label:rec.label}))}" onclick="runCardAction(this)">${esc(rec.label)}</button>`).join('')}</div>
  </div>`).join('')}</div>`;
}
function highlightList(rows){
  if(!(rows || []).length) return '<div class="empty-state">今天还没有可展示重点</div>';
  return `<div class="highlight-list">${rows.slice(0, 10).map(item => `<div class="highlight-card">
    <div class="highlight-top"><div><div class="highlight-title">${esc(item.title || item.kind)}</div><div class="item-meta">${esc(shortDateTime(item.time || ''))} · ${esc(item.source || '')}/${esc(item.kind || '')}</div></div><span class="category ${esc(item.category || 'other')}">${esc(item.category || 'other')}</span></div>
    <div class="highlight-body">${esc(item.body || '')}</div>
  </div>`).join('')}</div>`;
}
function quickTagChips(rows){
  if(!(rows || []).length) return '<span class="evidence-chip">暂无手机快速标注</span>';
  return rows.slice(0, 10).map(item => `<span class="evidence-chip">${esc(item.tag || item.title)} · ${esc(shortDateTime(item.time || ''))}</span>`).join('');
}
function evidenceChips(rows){
  if(!(rows || []).length) return '';
  return `<div class="repair-evidence">${rows.slice(0, 6).map(item => `<span class="evidence-chip">${esc(item.title || item.time || item.path || item.id || item.status || 'evidence')}</span>`).join('')}</div>`;
}
async function runCardAction(button){
  const payload = JSON.parse(button.dataset.action || '{}');
  if(!payload.name) return;
  await action(payload.name, payload.args || {});
}
function runFirstRepair(){
  const rows = (window.__actionCenterData || {}).repair_queue || [];
  const item = rows.find(row => row.action);
  if(!item) return toast('没有可执行的修复项');
  action(item.action.name, item.action.args || {});
}
async function suggestionInbox(){
  const buttons = `<button class="btn" onclick="setSuggestionDate('today')">今天</button><button class="btn" onclick="setSuggestionDate('yesterday')">昨天</button><button class="btn" onclick="bulkInsightState('suggestion','done')">当前完成</button><button class="btn primary" onclick="suggestionInbox()">刷新</button>`;
  setHeader('行动建议','读取中...', buttons);
  const params = new URLSearchParams({date: state.suggestionDate || 'today', status: state.suggestionStatus || 'active'});
  if(state.suggestionQ) params.set('q', state.suggestionQ);
  if(state.suggestionPriority && state.suggestionPriority !== 'all') params.set('priority', state.suggestionPriority);
  if(state.suggestionSource && state.suggestionSource !== 'all') params.set('source', state.suggestionSource);
  const j = await api('/api/action-suggestions?' + params.toString());
  const summary = j.summary || {};
  const stateSummary = summary.state || {};
  const rows = j.suggestions || [];
  window.__suggestionItems = rows;
  $('subtitle').textContent = `${j.date || ''} · ${rows.length}/${summary.all || rows.length} 条 · ${insightStatusLabel(state.suggestionStatus)}`;
  $('view').innerHTML = `
    <div class="insight-hero">
      <section class="card">
        <div class="section-title"><h3>行动建议收件箱</h3><span class="muted">${esc(shortDateTime(j.generated_at || ''))}</span></div>
        <div class="insight-toolbar">
          <input id="suggestionDate" value="${escAttr(state.suggestionDate || 'today')}" aria-label="date">
          <input id="suggestionQ" value="${escAttr(state.suggestionQ || '')}" placeholder="搜索建议、来源、证据" onkeydown="suggestionKey(event)" aria-label="search">
          <select id="suggestionPriority">${suggestionPriorityOptions(state.suggestionPriority)}</select>
          <select id="suggestionSource">${insightSourceOptions(state.suggestionSource)}</select>
          <button class="btn primary" onclick="applySuggestionFilters()">查找</button>
        </div>
        <div class="quickbar" style="margin-top:10px">${insightStatusPills('suggestion', state.suggestionStatus, summary)}</div>
        <div class="insight-kpis">
          ${insightKpi('当前', rows.length, 'current filter')}
          ${insightKpi('未处理', stateSummary.open || 0, 'open')}
          ${insightKpi('高优先级', summary.high || 0, 'high')}
          ${insightKpi('置顶', stateSummary.pinned || summary.pinned || 0, 'pinned')}
        </div>
      </section>
      <section class="card">
        <div class="section-title"><h3>处理流</h3><span class="muted">stateful</span></div>
        <div class="overview-actions">
          <button class="btn" onclick="go('action')">行动中心</button>
          <button class="btn" onclick="go('projects')">项目聚类</button>
          <button class="btn" onclick="bulkInsightState('suggestion','snoozed')">当前稍后</button>
          <button class="btn danger" onclick="bulkInsightState('suggestion','dismissed')">当前忽略</button>
        </div>
        ${insightStateBreakdown(summary)}
      </section>
    </div>
    <div class="insight-main">
      <section class="card">
        <div class="section-title"><h3>建议列表</h3><span class="muted">${esc(rows.length)} shown</span></div>
        ${suggestionInboxList(rows)}
      </section>
      <aside class="insight-side">
        <section class="card">
          <div class="section-title"><h3>优先级</h3><span class="muted">${esc(state.suggestionPriority || 'all')}</span></div>
          <div class="quickbar">${suggestionPriorityPills(summary)}</div>
        </section>
        <section class="card">
          <div class="section-title"><h3>状态</h3></div>
          ${insightStateBreakdown(summary)}
        </section>
      </aside>
    </div>`;
}
function suggestionInboxList(rows){
  if(!(rows || []).length) return '<div class="empty-state">没有匹配的行动建议</div>';
  return `<div class="insight-list">${rows.map(suggestionInboxCard).join('')}</div>`;
}
function suggestionInboxCard(item){
  const stateInfo = item.state || {};
  const currentStatus = stateInfo.status || 'open';
  const pinned = !!stateInfo.pinned;
  return `<article class="insight-card ${esc(item.priority || 'low')} ${esc(currentStatus)}">
    <div class="insight-head">
      <div>
        <div class="insight-title">${pinned ? '★ ' : ''}${esc(item.title || '行动建议')}</div>
        <div class="item-meta">${esc(shortDateTime(item.observed_at || ''))} · ${esc(item.source || '')}/${esc(item.kind || '')} · ${esc(item.reason || '')}</div>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">${status(item.priority || 'low')}${status(currentStatus)}</div>
    </div>
    <div class="insight-body">${esc(item.body || '')}</div>
    <div class="insight-chips">
      <span class="evidence-chip">${esc((item.recommended_action || {}).label || '稍后处理')}</span>
      <span class="evidence-chip">${esc(item.evidence_ref || item.id)}</span>
    </div>
    <div class="insight-actions">
      <button class="btn primary" data-item-id="${escAttr(item.id)}" data-status="${escAttr(currentStatus)}" data-pinned="${escAttr(pinned)}" onclick="setInsightState(this,'suggestion','done')">完成</button>
      <button class="btn" data-item-id="${escAttr(item.id)}" data-status="${escAttr(currentStatus)}" data-pinned="${escAttr(pinned)}" onclick="setInsightState(this,'suggestion','snoozed')">稍后</button>
      <button class="btn" data-item-id="${escAttr(item.id)}" data-status="${escAttr(currentStatus)}" data-pinned="${escAttr(pinned)}" onclick="toggleInsightPin(this,'suggestion')">${pinned ? '取消置顶' : '置顶'}</button>
      <button class="btn" data-query="${escAttr(item.title || item.body || '')}" onclick="openInsightSearch(this)">问证据</button>
      <button class="btn danger" data-item-id="${escAttr(item.id)}" data-status="${escAttr(currentStatus)}" data-pinned="${escAttr(pinned)}" onclick="setInsightState(this,'suggestion','dismissed')">忽略</button>
    </div>
    <div class="insight-note">
      <textarea data-insight-note placeholder="处理备注">${esc(stateInfo.note || '')}</textarea>
      <button class="btn" data-item-id="${escAttr(item.id)}" data-status="${escAttr(currentStatus)}" data-pinned="${escAttr(pinned)}" onclick="saveInsightNote(this,'suggestion')">保存备注</button>
    </div>
    ${insightEvidenceDetails(item.evidence || [])}
  </article>`;
}
async function projectsWorkbench(){
  const buttons = `<button class="btn" onclick="setProjectDate('today')">今天</button><button class="btn" onclick="setProjectDate('yesterday')">昨天</button><button class="btn" onclick="bulkInsightState('project','archived')">当前归档</button><button class="btn primary" onclick="projectsWorkbench()">刷新</button>`;
  setHeader('项目','读取中...', buttons);
  const params = new URLSearchParams({date: state.projectDate || 'today', status: state.projectStatus || 'active'});
  if(state.projectQ) params.set('q', state.projectQ);
  if(state.projectSource && state.projectSource !== 'all') params.set('source', state.projectSource);
  const j = await api('/api/project-clusters?' + params.toString());
  const summary = j.summary || {};
  const stateSummary = summary.state || {};
  const rows = j.projects || [];
  window.__projectItems = rows;
  $('subtitle').textContent = `${j.date || ''} · ${rows.length}/${summary.all || rows.length} 个项目 · ${summary.events || 0} 条证据`;
  $('view').innerHTML = `
    <div class="insight-hero">
      <section class="card">
        <div class="section-title"><h3>项目 / 主题工作台</h3><span class="muted">${esc(shortDateTime(j.generated_at || ''))}</span></div>
        <div class="insight-toolbar projects">
          <input id="projectDate" value="${escAttr(state.projectDate || 'today')}" aria-label="date">
          <input id="projectQ" value="${escAttr(state.projectQ || '')}" placeholder="搜索项目、关键词、证据" onkeydown="projectKey(event)" aria-label="search">
          <select id="projectSource">${insightSourceOptions(state.projectSource)}</select>
          <select id="projectStatus">${insightStatusOptions(state.projectStatus)}</select>
          <button class="btn primary" onclick="applyProjectFilters()">查找</button>
        </div>
        <div class="quickbar" style="margin-top:10px">${insightStatusPills('project', state.projectStatus, summary)}</div>
        <div class="insight-kpis">
          ${insightKpi('项目', rows.length, 'current filter')}
          ${insightKpi('证据', summary.events || 0, 'events')}
          ${insightKpi('未处理', stateSummary.open || 0, 'open')}
          ${insightKpi('置顶', stateSummary.pinned || summary.pinned || 0, 'pinned')}
        </div>
      </section>
      <section class="card">
        <div class="section-title"><h3>项目动作</h3><span class="muted">curate</span></div>
        <div class="overview-actions">
          <button class="btn" onclick="go('suggestions')">行动建议</button>
          <button class="btn" onclick="go('timeline')">时间线</button>
          <button class="btn" onclick="bulkInsightState('project','snoozed')">当前稍后</button>
          <button class="btn danger" onclick="bulkInsightState('project','archived')">当前归档</button>
        </div>
        ${projectCategoryBreakdown(rows)}
      </section>
    </div>
    <div class="insight-main">
      <section class="card">
        <div class="section-title"><h3>项目列表</h3><span class="muted">${esc(rows.length)} shown</span></div>
        ${projectWorkbenchList(rows)}
      </section>
      <aside class="insight-side">
        <section class="card">
          <div class="section-title"><h3>来源构成</h3><span class="muted">${esc(state.projectSource || 'all')}</span></div>
          ${projectCategoryBreakdown(rows)}
        </section>
        <section class="card">
          <div class="section-title"><h3>状态</h3></div>
          ${insightStateBreakdown(summary)}
        </section>
      </aside>
    </div>`;
}
function projectWorkbenchList(rows){
  if(!(rows || []).length) return '<div class="empty-state">没有匹配的项目聚类</div>';
  return `<div class="insight-list">${rows.map(projectWorkbenchCard).join('')}</div>`;
}
function projectWorkbenchCard(item){
  const stateInfo = item.state || {};
  const currentStatus = stateInfo.status || 'open';
  const pinned = !!stateInfo.pinned;
  const confidence = Math.round(Number(item.confidence || 0) * 100);
  return `<article class="insight-card project ${esc(currentStatus)}">
    <div class="insight-head">
      <div>
        <div class="insight-title">${pinned ? '★ ' : ''}${esc(item.title || '未命名项目')}</div>
        <div class="item-meta">${esc(shortDateTime((item.time_span || {}).start || ''))} -> ${esc(shortDateTime((item.time_span || {}).end || ''))} · ${esc(item.event_count || 0)} 条证据</div>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end"><span class="status ok">${esc(confidence)}%</span>${status(currentStatus)}</div>
    </div>
    <div class="insight-body">${esc(item.summary || '')}</div>
    <div class="insight-chips">
      ${(item.keywords || []).map(keyword => `<span class="evidence-chip">${esc(keyword)}</span>`).join('')}
      ${Object.entries(item.categories || {}).map(([key, value]) => `<span class="evidence-chip">${esc(categoryLabel(key))} ${esc(value)}</span>`).join('')}
    </div>
    ${projectNextActions(item.next_actions || [])}
    <div class="insight-actions">
      <button class="btn primary" data-item-id="${escAttr(item.id)}" data-status="${escAttr(currentStatus)}" data-pinned="${escAttr(pinned)}" onclick="toggleInsightPin(this,'project')">${pinned ? '取消关注' : '关注'}</button>
      <button class="btn" data-item-id="${escAttr(item.id)}" data-status="${escAttr(currentStatus)}" data-pinned="${escAttr(pinned)}" onclick="setInsightState(this,'project','done')">完成</button>
      <button class="btn" data-item-id="${escAttr(item.id)}" data-status="${escAttr(currentStatus)}" data-pinned="${escAttr(pinned)}" onclick="setInsightState(this,'project','snoozed')">稍后</button>
      <button class="btn" data-query="${escAttr(item.title || item.summary || '')}" onclick="openInsightSearch(this)">问项目证据</button>
      <button class="btn danger" data-item-id="${escAttr(item.id)}" data-status="${escAttr(currentStatus)}" data-pinned="${escAttr(pinned)}" onclick="setInsightState(this,'project','archived')">归档</button>
    </div>
    <div class="insight-note">
      <textarea data-insight-note placeholder="项目备注">${esc(stateInfo.note || '')}</textarea>
      <button class="btn" data-item-id="${escAttr(item.id)}" data-status="${escAttr(currentStatus)}" data-pinned="${escAttr(pinned)}" onclick="saveInsightNote(this,'project')">保存备注</button>
    </div>
    ${insightEvidenceDetails(item.evidence || [])}
  </article>`;
}
function projectNextActions(rows){
  if(!(rows || []).length) return '';
  return `<div class="insight-chips">${rows.map(item => `<span class="evidence-chip">${esc(item.title || item.kind || 'next')}</span>`).join('')}</div>`;
}
function insightEvidenceDetails(rows){
  if(!(rows || []).length) return '';
  return `<details class="insight-evidence"><summary>证据 ${esc(rows.length)}</summary><div class="insight-evidence-list">${rows.map(evidence => `<div class="insight-evidence-row">
    <b>${esc(evidence.title || evidence.id || 'evidence')}</b>
    <div class="item-meta">${esc(shortDateTime(evidence.time || ''))} · ${esc(evidence.source || '')}/${esc(evidence.kind || '')}${evidence.category ? ' · ' + esc(categoryLabel(evidence.category)) : ''}</div>
    <div class="result-text">${esc(evidence.snippet || evidence.body || evidence.location || '')}</div>
  </div>`).join('')}</div></details>`;
}
function insightKpi(label, value, hint){
  return `<div class="insight-kpi"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint || '')}</div></div>`;
}
function insightStatusPills(itemType, current, summary){
  const stateSummary = (summary || {}).state || {};
  const total = Number((summary || {}).all || (summary || {}).total || (summary || {}).projects || 0);
  const rows = [
    ['active', '活跃', stateSummary.active ?? total],
    ['open', '未处理', stateSummary.open || 0],
    ['snoozed', '稍后', stateSummary.snoozed || 0],
    ['done', '已完成', stateSummary.done || 0],
    ['archived', '已归档', stateSummary.archived || 0],
    ['all', '全部', total],
  ];
  const fn = itemType === 'project' ? 'setProjectStatus' : 'setSuggestionStatus';
  return rows.map(([key, label, count]) => `<button class="filter-pill ${current===key?'active':''}" onclick="${fn}('${key}')">${esc(label)} <span class="chip-count">${esc(count)}</span></button>`).join('');
}
function insightStatusOptions(current){
  return ['active','open','snoozed','done','archived','all'].map(value => `<option value="${escAttr(value)}" ${current===value?'selected':''}>${esc(insightStatusLabel(value))}</option>`).join('');
}
function insightStatusLabel(value){
  return ({active:'活跃',open:'未处理',snoozed:'稍后',done:'已完成',archived:'已归档',dismissed:'已忽略',all:'全部'})[value] || value || '活跃';
}
function insightStateBreakdown(summary){
  const states = (summary || {}).state || {};
  const rows = [['open','未处理'], ['snoozed','稍后'], ['done','已完成'], ['archived','已归档'], ['dismissed','已忽略'], ['pinned','置顶']];
  return `<div class="insight-state-list" style="margin-top:12px">${rows.map(([key,label]) => `<div class="insight-state-row"><span>${esc(label)}</span><span class="queue-value">${esc(states[key] || 0)}</span></div>`).join('')}</div>`;
}
function suggestionPriorityOptions(current){
  return ['all','high','medium','low'].map(value => `<option value="${escAttr(value)}" ${current===value?'selected':''}>${esc(priorityLabel(value))}</option>`).join('');
}
function suggestionPriorityPills(summary){
  const rows = [['all','全部', (summary || {}).total || 0], ['high','高', (summary || {}).high || 0], ['medium','中', ''], ['low','低', '']];
  return rows.map(([key,label,count]) => `<button class="filter-pill ${state.suggestionPriority===key?'active':''}" onclick="setSuggestionPriority('${key}')">${esc(label)}${count !== '' ? ` <span class="chip-count">${esc(count)}</span>` : ''}</button>`).join('');
}
function priorityLabel(value){
  return ({all:'全部优先级',high:'高优先级',medium:'中优先级',low:'低优先级'})[value] || value || '全部优先级';
}
function insightSourceOptions(current){
  const values = [['all','全部来源'], ['mobile','mobile'], ['feedback','feedback'], ['audio','录音'], ['calendar','日程'], ['reminder','提醒'], ['files','文件'], ['location','位置'], ['app','App'], ['system','系统']];
  return values.map(([value,label]) => `<option value="${escAttr(value)}" ${current===value?'selected':''}>${esc(label)}</option>`).join('');
}
function applySuggestionFilters(){
  state.suggestionDate = $('suggestionDate').value || 'today';
  state.suggestionQ = $('suggestionQ').value;
  state.suggestionPriority = $('suggestionPriority').value || 'all';
  state.suggestionSource = $('suggestionSource').value || 'all';
  suggestionInbox();
}
function suggestionKey(event){
  if(event.key === 'Enter'){
    event.preventDefault();
    applySuggestionFilters();
  }
}
function setSuggestionDate(value){ state.suggestionDate = value || 'today'; suggestionInbox(); }
function setSuggestionStatus(value){ state.suggestionStatus = value || 'active'; suggestionInbox(); }
function setSuggestionPriority(value){ state.suggestionPriority = value || 'all'; suggestionInbox(); }
function applyProjectFilters(){
  state.projectDate = $('projectDate').value || 'today';
  state.projectQ = $('projectQ').value;
  state.projectSource = $('projectSource').value || 'all';
  state.projectStatus = $('projectStatus').value || 'active';
  projectsWorkbench();
}
function projectKey(event){
  if(event.key === 'Enter'){
    event.preventDefault();
    applyProjectFilters();
  }
}
function setProjectDate(value){ state.projectDate = value || 'today'; projectsWorkbench(); }
function setProjectStatus(value){ state.projectStatus = value || 'active'; projectsWorkbench(); }
async function setInsightState(button, itemType, statusValue, pinnedValue){
  const note = button.closest('.insight-card')?.querySelector('[data-insight-note]')?.value || '';
  const payload = {item_id: button.dataset.itemId, item_type: itemType, status: statusValue, note};
  if(pinnedValue !== undefined) payload.pinned = pinnedValue;
  const j = await api('/api/insight-state',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  toast(j.ok ? '已更新处理状态' : '状态更新失败');
  render();
}
function toggleInsightPin(button, itemType){
  const pinned = !(button.dataset.pinned === 'true');
  setInsightState(button, itemType, button.dataset.status || 'open', pinned);
}
function saveInsightNote(button, itemType){
  setInsightState(button, itemType, button.dataset.status || 'open', button.dataset.pinned === 'true');
}
async function bulkInsightState(itemType, statusValue){
  const items = itemType === 'project' ? (window.__projectItems || []) : (window.__suggestionItems || []);
  if(!items.length) return toast('当前列表为空');
  for(const item of items){
    await api('/api/insight-state',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({item_id:item.id,item_type:itemType,status:statusValue})});
  }
  toast(`已更新 ${items.length} 条`);
  render();
}
function openInsightSearch(button){
  const q = button.dataset.query || '';
  state.searchQ = q;
  state.searchQuestion = q ? `围绕这个事项给我证据和下一步：${q}` : state.searchQuestion;
  go('search');
}
function projectCategoryBreakdown(rows){
  const counts = {};
  (rows || []).forEach(project => {
    Object.entries(project.categories || {}).forEach(([key,value]) => { counts[key] = (counts[key] || 0) + Number(value || 0); });
  });
  const entries = Object.entries(counts).sort((a,b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  if(!entries.length) return '<div class="empty-state" style="margin-top:12px">当前筛选没有来源构成</div>';
  return `<div class="insight-breakdown" style="margin-top:12px">${entries.map(([key,value]) => `<div class="insight-state-row"><span>${esc(categoryLabel(key))}</span><span class="queue-value">${esc(value)}</span></div>`).join('')}</div>`;
}
async function render(){
  if(state.section==='setup') return setup();
  if(state.section==='action') return actionCenter();
  if(state.section==='suggestions') return suggestionInbox();
  if(state.section==='projects') return projectsWorkbench();
  if(state.section==='today') return today();
  if(state.section==='overview') return overview();
  if(state.section==='doctor') return doctor();
  if(state.section==='audio') return audio();
  if(state.section==='search') return search();
  if(state.section==='timeline') return timeline();
  if(state.section==='reports') return reports();
  if(state.section==='sources') return sources();
  if(state.section==='speakers') return speakers();
  if(state.section==='files') return files();
  if(state.section==='recycle') return recycle();
  if(state.section==='sync') return sync();
  if(state.section==='maintenance') return maintenance();
  if(state.section==='settings') return settings();
}
async function setup(){
  setHeader('设置向导','读取中...',
    `<button class="btn primary" onclick="setup()">刷新状态</button><button class="btn" onclick="go('sync')">手机同步</button><button class="btn" onclick="go('doctor')">Doctor</button><button class="btn" onclick="go('settings')">设置</button>`);
  const j = await api('/api/setup');
  const summary = j.summary || {};
  const syncInfo = j.sync || {};
  const cfg = j.config || {};
  $('subtitle').textContent = `${summary.complete || 0}/${summary.total || 0} 完成 · ${summary.percent || 0}% · ${j.generated_at || ''}`;
  $('view').innerHTML = `
    <div class="setup-hero">
      <section class="card">
        <div class="section-title"><h3>首次配置进度</h3>${status(summary.ready ? 'ok' : 'warn')}</div>
        <div class="setup-kpis">
          ${setupKpi('完成度', `${summary.percent || 0}%`, `${summary.complete || 0}/${summary.total || 0} steps`)}
          ${setupKpi('Token', syncInfo.token_configured ? '已配置' : '未配置', 'iPhone sync')}
          ${setupKpi('Sync Port', syncInfo.port || '-', syncInfo.host || '-')}
          ${setupKpi('Records', ((cfg.counts || {}).observations || 0), 'observations')}
        </div>
        <div class="setup-progress"><span style="width:${Math.max(0, Math.min(100, Number(summary.percent || 0)))}%"></span></div>
      </section>
      <section class="card">
        <div class="section-title"><h3>快捷操作</h3><span class="muted">setup</span></div>
        <div class="setup-actions">
          <button class="btn primary" onclick="setupGenerateToken()">生成新 token</button>
          <button class="btn" onclick="setupInstallAll()">安装全部服务</button>
          <button class="btn" onclick="action('install_sync_agent',{load:true})">安装同步服务</button>
          <button class="btn" onclick="action('install_agent',{load:true})">安装采集 Agent</button>
          <button class="btn" onclick="action('install_dashboard_agent',{load:true})">安装 Dashboard</button>
          <button class="btn" onclick="go('doctor')">查看诊断</button>
        </div>
      </section>
    </div>
    <div class="setup-main">
      <div class="setup-stack">
        <section class="card">
          <div class="section-title"><h3>检查清单</h3><span class="muted">${esc(summary.complete || 0)} ready</span></div>
          ${setupStepList(j.steps || [])}
        </section>
        <section class="card">
          <div class="section-title"><h3>iPhone 连接</h3><span class="muted">Mac sync URL</span></div>
          ${setupUrlList(syncInfo.upload_urls || [])}
          ${setupTokenPanel(syncInfo)}
        </section>
      </div>
      <aside class="setup-side">
        <section class="card">
          <div class="section-title"><h3>Mac 服务</h3><span class="muted">LaunchAgent</span></div>
          ${setupServiceList(j.services || [])}
        </section>
        <section class="card">
          <div class="section-title"><h3>本机路径</h3><span class="muted">${esc(cfg.timezone || '')}</span></div>
          <div class="settings-row-list">
            <div class="settings-row"><div class="label">config</div><div class="value">${esc(cfg.path || '')}</div></div>
            <div class="settings-row"><div class="label">database</div><div class="value">${esc(cfg.database || '')}</div></div>
            <div class="settings-row"><div class="label">data</div><div class="value">${esc(cfg.data_dir || '')}</div></div>
            <div class="settings-row"><div class="label">health</div><div class="value">${esc(syncInfo.health_url || '')}</div></div>
          </div>
        </section>
      </aside>
    </div>`;
}
function setupKpi(label, value, hint){
  return `<div class="setup-kpi"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint || '')}</div></div>`;
}
function setupStepList(rows){
  if(!(rows || []).length) return '<div class="empty-state">没有检查项</div>';
  return `<div class="setup-step-list">${rows.map(item => `<div class="setup-step">
    <div>${status(item.status || (item.ok ? 'ok' : 'warn'))}</div>
    <div><div class="setup-title">${esc(item.title || item.key)}</div><div class="setup-detail">${esc(item.detail || '')}</div></div>
    ${item.ok ? '<span class="muted">ready</span>' : '<span class="muted">todo</span>'}
  </div>`).join('')}</div>`;
}
function setupServiceList(rows){
  if(!(rows || []).length) return '<div class="empty-state">没有服务状态</div>';
  return `<div class="setup-service-list">${rows.map(row => `<div class="setup-service">
    <div>${status(row.status || 'warn')}</div>
    <div><div class="setup-title">${esc(row.title || row.key)}</div><div class="setup-detail">${esc(row.label || '')}<br>${esc(row.path || '')}<br>${esc(row.installed ? 'installed' : 'missing')}, ${esc(row.state || '')}</div></div>
    <button class="btn" onclick="action('${escAttr(row.action)}',{load:true})">安装</button>
  </div>`).join('')}</div>`;
}
function setupUrlList(rows){
  if(!(rows || []).length) return '<div class="empty-state">没有可用 URL；请确认同步端口配置。</div>';
  return `<div class="setup-url-list">${rows.map(row => `<div class="setup-url-row">
    <div class="muted">${esc(row.label || 'URL')}</div>
    <div class="setup-url">${esc(row.url || '')}</div>
    <button class="btn" data-copy="${escAttr(row.url || '')}" onclick="copyFromButton(this,'URL')">复制 URL</button>
  </div>`).join('')}</div>`;
}
function setupTokenPanel(syncInfo){
  const token = state.setupToken || '';
  return `<div class="setup-token-box" style="margin-top:12px">
    <div class="section-title"><h3>同步 Token</h3>${status(syncInfo.token_configured ? 'ok' : 'warn')}</div>
    ${token ? `<div class="setup-token-value">${esc(token)}</div><div class="setup-actions"><button class="btn primary" data-copy="${escAttr(token)}" onclick="copyFromButton(this,'token')">复制 token</button><button class="btn" onclick="state.setupToken=''; setup()">隐藏 token</button></div>` : `<div class="setup-detail">${syncInfo.token_configured ? '已有 token。为了安全，现有 token 不会明文显示；需要配置新手机时可以生成一个新的。' : '还没有 token。先生成 token，再把 URL 和 token 填到 iPhone 的 Wond 设置里。'}</div><button class="btn primary" onclick="setupGenerateToken()">生成新 token</button>`}
  </div>`;
}
async function setupGenerateToken(){
  const j = await api('/api/setup-token',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  state.setupToken = j.token || '';
  toast(state.setupToken ? '已生成并保存新 token' : 'token 生成失败');
  await setup();
}
async function setupInstallAll(){
  const actions = [
    ['install_sync_agent', {load:true}],
    ['install_agent', {load:true}],
    ['install_dashboard_agent', {load:true}],
  ];
  for(const [name, args] of actions){
    await action(name, args);
  }
  setup();
}
async function copyFromButton(button, label){
  await copyText(button.dataset.copy || '');
  toast(`已复制 ${label || ''}`);
}
async function copyText(text){
  if(!text) return;
  if(navigator.clipboard && navigator.clipboard.writeText){
    await navigator.clipboard.writeText(text);
    return;
  }
  const input = document.createElement('textarea');
  input.value = text;
  input.style.position = 'fixed';
  input.style.opacity = '0';
  document.body.appendChild(input);
  input.select();
  document.execCommand('copy');
  document.body.removeChild(input);
}
async function today(){
  setHeader('今天','读取中...',
    `<button class="btn" onclick="action('collect',{date:state.todayDate})">采集</button><button class="btn" onclick="action('analyze_audio',{limit:10})">分析 10 条</button><button class="btn" onclick="go('timeline')">底层时间线</button><button class="btn primary" onclick="today()">刷新</button>`);
  const params = new URLSearchParams({date: state.todayDate || 'today'});
  if(state.todayQ) params.set('q', state.todayQ);
  if(state.todayFrom) params.set('time_from', state.todayFrom);
  if(state.todayTo) params.set('time_to', state.todayTo);
  const j=await api('/api/today?'+params.toString());
  const counts = j.summary.by_category || {};
  const allEvents = j.events || [];
  const events = filterTodayEvents(allEvents);
  const shown = events.length;
  const total = Number(j.summary.total || allEvents.length || 0);
  $('subtitle').textContent = `${j.date} · ${shown}/${total} 条 · ${shortRange(j.summary.first, j.summary.last)}`;
  $('view').innerHTML = `
    <div class="card today-controls">
      <div class="day-toolbar">
        <input id="todayDate" value="${esc(state.todayDate)}" aria-label="date">
        <input id="todayFrom" value="${esc(state.todayFrom)}" placeholder="开始 HH:MM" aria-label="start time">
        <input id="todayTo" value="${esc(state.todayTo)}" placeholder="结束 HH:MM" aria-label="end time">
        <input id="todayQ" value="${esc(state.todayQ)}" placeholder="搜索时间、人物、应用、地点、摘要" aria-label="search">
        <button class="btn primary" onclick="applyTodaySearch()">查找</button>
      </div>
      <div class="quickbar">
        <button class="filter-pill ${state.todayDate==='today'?'active':''}" onclick="setTodayDate('today')">今天</button>
        <button class="filter-pill ${state.todayDate==='yesterday'?'active':''}" onclick="setTodayDate('yesterday')">昨天</button>
        <button class="filter-pill ${!state.todayFrom&&!state.todayTo?'active':''}" onclick="setTodayRange('','')">全天</button>
        <button class="filter-pill ${rangeActive('09:00','12:00')?'active':''}" onclick="setTodayRange('09:00','12:00')">上午</button>
        <button class="filter-pill ${rangeActive('12:00','18:00')?'active':''}" onclick="setTodayRange('12:00','18:00')">下午</button>
        <button class="filter-pill ${rangeActive('18:00','23:59')?'active':''}" onclick="setTodayRange('18:00','23:59')">晚上</button>
        <button class="filter-pill ${rangeActive('09:00','18:00')?'active':''}" onclick="setTodayRange('09:00','18:00')">工作时间</button>
      </div>
    </div>
    <div class="today-summary">
      <div class="card">
        <div class="section-title"><h3>日内概览</h3><span class="muted">${esc(shortRange(j.summary.first, j.summary.last))}</span></div>
        <div class="today-stats">
          ${todayStat('事件', total, `${shown} 条显示`)}
          ${todayStat('录音', counts.audio || 0, `${j.summary.pending_audio_today || 0} 待处理`)}
          ${todayStat('聊天', counts.chat || 0, 'metadata')}
          ${todayStat('文件/位置/提醒', `${counts.file||0}/${counts.location||0}/${counts.reminder||0}`, 'today')}
        </div>
        ${hourBars(allEvents)}
      </div>
      <div class="card">
        <div class="section-title"><h3>分类</h3><span class="muted">${esc(categoryLabel(state.todayCategory))}</span></div>
        ${categoryFilters(counts, total)}
      </div>
    </div>
    <div class="today-main">
      <div>
        <div class="section-title"><h3>事件流</h3><span class="muted">${esc(j.generated_at)}</span></div>
        <div class="day-feed">${eventSections(events)}</div>
      </div>
      <div class="today-sidebar">
        <div class="card">
          <div class="section-title"><h3>音频</h3>${status((j.summary.pending_audio_today||0) ? 'pending' : 'ok')}</div>
          <table><tbody>
            <tr><td>今天待处理</td><td>${esc(j.summary.pending_audio_today || 0)}</td></tr>
            <tr><td>全部 pending</td><td>${esc((j.summary.audio.statuses||{}).pending || 0)}</td></tr>
            <tr><td>已有摘要</td><td>${esc(j.summary.audio.with_summary || 0)}</td></tr>
            <tr><td>最近分析</td><td>${esc(j.summary.audio.latest_analyzed || '-')}</td></tr>
          </tbody></table>
        </div>
        <div class="card">
          <div class="section-title"><h3>每日反馈</h3></div>
          <select id="feedbackCategory">
            <option value="important">重要</option>
            <option value="unimportant">不重要</option>
            <option value="wrong">错了</option>
            <option value="correction">纠正</option>
          </select>
          <textarea id="feedbackNote" placeholder="写下哪些总结重要、不重要或需要修正" style="margin-top:8px"></textarea>
          <button class="btn primary" style="margin-top:8px" onclick="submitFeedback()">写入长期记忆</button>
          <div style="margin-top:12px">
            <div class="section-title"><h3>已记录</h3><span class="muted">${esc((j.feedback||[]).length)} 条</span></div>
            ${(j.feedback||[]).map(f=>`<div class="feedback-row"><b>${esc(feedbackLabel(f.category))}</b><div class="muted">${esc(f.created_at)} ${esc(f.source_ref||'')}</div><div>${esc(f.note)}</div></div>`).join('') || '<div class="muted">暂无反馈</div>'}
          </div>
        </div>
      </div>
    </div>`;
}
function applyTodaySearch(){
  state.todayDate = $('todayDate').value || 'today';
  state.todayFrom = $('todayFrom').value;
  state.todayTo = $('todayTo').value;
  state.todayQ = $('todayQ').value;
  state.todayCategory = 'all';
  today();
}
function setTodayDate(value){
  state.todayDate = value;
  state.todayCategory = 'all';
  today();
}
function setTodayRange(from, to){
  state.todayFrom = from;
  state.todayTo = to;
  today();
}
function setTodayCategory(value){
  state.todayCategory = value || 'all';
  today();
}
function rangeActive(from, to){ return state.todayFrom === from && state.todayTo === to; }
function filterTodayEvents(rows){
  if(!state.todayCategory || state.todayCategory === 'all') return rows || [];
  return (rows || []).filter(event => String(event.category || 'other') === state.todayCategory);
}
function todayStat(label, value, hint){
  return `<div class="today-stat"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint||'')}</div></div>`;
}
function categoryFilters(counts, total){
  const order = ['all','app','audio','chat','file','location','reminder','calendar','bookmark','mail','web','feedback','system','other'];
  const items = order.map(key => [key, key === 'all' ? total : Number(counts[key] || 0)]).filter(([key,count]) => key === 'all' || count > 0);
  return `<div class="category-strip">${items.map(([key,count]) => `<button class="filter-pill category-chip ${state.todayCategory===key?'active':''}" onclick="setTodayCategory('${key}')"><span>${esc(categoryLabel(key))}</span><span class="chip-count">${esc(count)}</span></button>`).join('')}</div>`;
}
function hourBars(rows){
  const buckets = Array.from({length: 24}, () => 0);
  (rows || []).forEach(event => {
    const minutes = minutesOfDay(event.time);
    if(minutes >= 0) buckets[Math.floor(minutes / 60)] += 1;
  });
  const max = Math.max(1, ...buckets);
  const bars = buckets.map((count, hour) => {
    const height = count ? Math.max(8, Math.round((count / max) * 48)) : 5;
    const opacity = count ? (0.28 + (count / max) * 0.62).toFixed(2) : 0.15;
    return `<div class="hour-bar" title="${String(hour).padStart(2,'0')}:00 · ${count}" style="height:${height}px;opacity:${opacity}"></div>`;
  }).join('');
  return `<div class="hour-bars">${bars}</div><div class="hour-axis"><span>00</span><span>06</span><span>12</span><span>18</span><span>24</span></div>`;
}
async function submitFeedback(){
  const note = $('feedbackNote').value.trim();
  if(!note) return toast('反馈内容为空');
  const payload = {date: state.todayDate || 'today', category: $('feedbackCategory').value, note};
  const j = await api('/api/daily-feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  toast(j.ok ? '已写入每日反馈' : '写入失败');
  today();
}
async function overview(){
  setHeader('总览','读取中...',
    `<button class="btn primary" onclick="action('collect',{date:'today'})">采集并写报告</button><button class="btn" onclick="action('refresh_report',{date:'today'})">刷新今日报告</button><button class="btn" onclick="go('doctor')">Doctor</button><button class="btn" onclick="render()">刷新</button>`);
  const j=await api('/api/overview');
  const health = j.health || {};
  const healthInfo = overviewHealthInfo(health);
  const reports = j.reports || {};
  const audioStatuses = (j.audio || {}).statuses || {};
  const latest = j.latest_observation || j.latest_activity || '-';
  $('subtitle').textContent = `${j.today || 'today'} · ${healthInfo.ok}/${healthInfo.total} health · latest ${latest}`;
  $('view').innerHTML = `
    <div class="overview-hero">
      <div class="card">
        <div class="section-title"><h3>运行状态</h3>${status(healthInfo.status)}</div>
        <div class="overview-kpis">
          ${overviewKpi('Observations', j.counts.observations, `latest ${j.latest_observation || '-'}`)}
          ${overviewKpi('Activity', j.counts.activity_samples, `latest ${j.latest_activity || '-'}`)}
          ${overviewKpi('Audio', `${audioStatuses.ok||0}/${(j.audio||{}).total||0}`, `${audioStatuses.pending||0} pending`)}
          ${overviewKpi('Speakers', j.counts.speakers, `${j.counts.speaker_samples} samples`)}
        </div>
        <div class="overview-health">
          ${overviewHealthItems(health)}
        </div>
      </div>
      <div class="card">
        <div class="section-title"><h3>待处理</h3><span class="muted">${esc(j.today || '')}</span></div>
        <div class="overview-queue">
          <div class="queue-row"><span>今日录音待处理</span><span class="queue-value">${esc(j.pending_audio_today || 0)}</span></div>
          <div class="queue-row"><span>全部 audio pending</span><span class="queue-value">${esc(audioStatuses.pending || 0)}</span></div>
          <div class="queue-row"><span>报告文件</span><span class="queue-value">${esc(reports.reports || 0)}</span></div>
          <div class="queue-row"><span>最近日报</span><span class="queue-value">${esc(shortPath(reports.latest_report || '-'))}</span></div>
        </div>
      </div>
    </div>
    <div class="overview-main">
      <div class="grid">
        <div class="card">
          <div class="section-title"><h3>Recent Collector Runs</h3><span class="muted">${esc((j.recent_runs||[]).length)} runs</span></div>
          ${runsTable(j.recent_runs || [])}
        </div>
        <div class="card">
          <div class="section-title"><h3>Observation Sources</h3><span class="muted">top sources</span></div>
          ${sourceCountTable((j.source_counts || []).slice(0, 12))}
        </div>
      </div>
      <div class="overview-side">
        <div class="card">
          <div class="section-title"><h3>快捷入口</h3></div>
          <div class="overview-actions">
            <button class="btn" onclick="go('today')">今天</button>
            <button class="btn" onclick="go('audio')">音频队列</button>
            <button class="btn" onclick="go('reports')">报告</button>
            <button class="btn" onclick="go('sync')">手机同步</button>
          </div>
        </div>
        <div class="card">
          <div class="section-title"><h3>维护</h3></div>
          <div class="overview-actions">
            <button class="btn" onclick="action('retention',{date:'today'})">Retention dry-run</button>
            <button class="btn" onclick="action('email_due',{})">Email due dry-run</button>
            <button class="btn" onclick="action('compact',{date:'today',period:'all'})">Compact</button>
            <button class="btn" onclick="go('maintenance')">记录维护</button>
          </div>
        </div>
        <div class="card">
          <div class="section-title"><h3>Reports</h3></div>
          <table><tbody>${Object.entries(reports).map(([k,v])=>`<tr><td>${esc(k)}</td><td>${esc(k==='latest_report' ? shortPath(v) : v)}</td></tr>`).join('')}</tbody></table>
        </div>
      </div>
    </div>`;
}
function overviewKpi(label, value, hint){
  return `<div class="overview-kpi"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint||'')}</div></div>`;
}
function overviewHealthInfo(health){
  const values = Object.values(health || {});
  const total = values.length;
  const ok = values.filter(Boolean).length;
  return { ok, total, status: total && ok < total ? 'warn' : 'ok' };
}
function overviewHealthItems(health){
  return Object.entries(health || {}).map(([key,value]) => `<div class="health-item"><span>${esc(healthLabel(key))}</span>${status(value?'ok':'warn')}</div>`).join('') || '<div class="muted">No health checks</div>';
}
function healthLabel(key){
  return ({sync:'Sync server',ollama:'Ollama',agent_plist:'Collector agent',sync_plist:'Sync agent',dashboard_plist:'Dashboard agent'})[key] || key;
}
async function doctor(){
  setHeader('Doctor','读取中...',
    `<button class="btn primary" onclick="doctor()">Run checks</button><button class="btn" onclick="go('sources')">来源</button><button class="btn" onclick="go('settings')">设置</button>`);
  const j=await api('/api/doctor');
  const checks = j.checks || [];
  const summary = doctorSummary(checks);
  const filtered = filterDoctorChecks(checks);
  const issues = checks.filter(c => c.status === 'fail' || c.status === 'warn');
  $('subtitle').textContent = `${j.overall} · ${summary.fail} fail / ${summary.warn} warn / ${summary.ok} ok · ${j.generated_at}`;
  $('view').innerHTML = `
    <div class="doctor-hero">
      <div class="card">
        <div class="section-title"><h3>诊断状态</h3>${status(j.overall)}</div>
        <div class="doctor-kpis">
          ${doctorKpi('Fail', summary.fail, 'needs action')}
          ${doctorKpi('Warn', summary.warn, 'degraded')}
          ${doctorKpi('OK', summary.ok, 'healthy')}
          ${doctorKpi('Areas', summary.areas, `${summary.total} checks`)}
        </div>
        <div class="doctor-filters">${doctorStatusFilters(summary)}</div>
      </div>
      <div class="card">
        <div class="section-title"><h3>修复入口</h3><span class="muted">LaunchAgents</span></div>
        <div class="overview-actions">
          <button class="btn" onclick="action('install_agent',{load:true})">Install Agent</button>
          <button class="btn" onclick="action('install_sync_agent',{load:true})">Install Sync Agent</button>
          <button class="btn" onclick="action('install_dashboard_agent',{load:true})">Install Dashboard</button>
          <button class="btn" onclick="go('sources')">来源状态</button>
        </div>
      </div>
    </div>
    <div class="doctor-main">
      <div class="grid">
        <div class="card">
          <div class="section-title"><h3>优先处理</h3><span class="muted">${esc(issues.length)} issues</span></div>
          ${doctorIssueList(issues)}
        </div>
        <div class="card">
          <div class="section-title"><h3>检查明细</h3><span class="muted">${esc(filtered.length)}/${esc(checks.length)} checks</span></div>
          ${doctorCheckList(filtered)}
        </div>
      </div>
      <div class="doctor-side">
        <details class="card compact-details">
          <summary>Area · ${esc(state.doctorArea)}</summary>
          <div class="compact-details-body">${doctorAreaList(checks)}</div>
        </details>
        <details class="card compact-details">
          <summary>Fix commands</summary>
          <div class="compact-details-body">${doctorFixList(issues)}</div>
        </details>
      </div>
    </div>`;
}
function doctorSummary(checks){
  const summary = {total:(checks||[]).length, ok:0, warn:0, fail:0, info:0, pending:0, areas:0};
  const areas = new Set();
  (checks||[]).forEach(c => {
    const key = c.status || 'info';
    summary[key] = (summary[key] || 0) + 1;
    if(c.area) areas.add(c.area);
  });
  summary.areas = areas.size;
  return summary;
}
function doctorKpi(label, value, hint){
  return `<div class="doctor-kpi"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint||'')}</div></div>`;
}
function doctorStatusFilters(summary){
  const items = [['all', summary.total], ['fail', summary.fail], ['warn', summary.warn], ['ok', summary.ok]];
  return items.map(([key,count]) => `<button class="filter-pill ${state.doctorStatus===key?'active':''}" onclick="setDoctorFilter('${key}',state.doctorArea)">${esc(key==='all'?'All':key)} <span class="chip-count">${esc(count)}</span></button>`).join('');
}
function setDoctorFilter(statusValue, areaValue){
  state.doctorStatus = statusValue || 'all';
  state.doctorArea = areaValue || 'all';
  doctor();
}
function filterDoctorChecks(checks){
  return (checks || []).filter(c => (state.doctorStatus === 'all' || c.status === state.doctorStatus) && (state.doctorArea === 'all' || c.area === state.doctorArea));
}
function doctorIssueList(checks){
  if(!(checks||[]).length) return '<div class="empty-state">No fail or warn checks</div>';
  return `<div class="issue-list">${checks.map(c => `<div class="issue-item ${esc(c.status)}"><div class="section-title"><div><div class="check-title">${esc(c.name)}</div><div class="item-meta">${esc(c.area)}</div></div>${status(c.status)}</div><div class="check-message">${esc(c.message)}</div>${c.fix?`<div class="fix-command">${esc(c.fix)}</div>`:''}</div>`).join('')}</div>`;
}
function doctorCheckList(checks){
  if(!(checks||[]).length) return '<div class="empty-state">No checks match this filter</div>';
  return `<div class="check-list">${checks.map(c => `<div class="check-row"><div>${status(c.status)}</div><div class="item-meta">${esc(c.area)}</div><div><div class="check-title">${esc(c.name)}</div><div class="check-message">${esc(c.message)}</div>${c.fix?`<div class="fix-command">${esc(c.fix)}</div>`:''}</div></div>`).join('')}</div>`;
}
function doctorAreaList(checks){
  const areaMap = {};
  (checks || []).forEach(c => {
    const area = c.area || 'other';
    areaMap[area] = areaMap[area] || {total:0, fail:0, warn:0, ok:0};
    areaMap[area].total += 1;
    areaMap[area][c.status] = (areaMap[area][c.status] || 0) + 1;
  });
  const rows = [['all', doctorSummary(checks)], ...Object.entries(areaMap).sort(([a],[b]) => a.localeCompare(b))];
  return `<div class="area-list">${rows.map(([area,counts]) => `<div class="area-row ${state.doctorArea===area?'active':''}" onclick="setDoctorFilter(state.doctorStatus,'${escAttr(area)}')"><b>${esc(area==='all'?'All':area)}</b><span class="area-counts"><span>${esc(counts.total)} total</span><span>${esc(counts.fail||0)} fail</span><span>${esc(counts.warn||0)} warn</span></span></div>`).join('')}</div>`;
}
function doctorFixList(checks){
  const fixes = (checks || []).filter(c => c.fix).slice(0, 8);
  if(!fixes.length) return '<div class="empty-state">No fix commands needed</div>';
  return `<div class="fix-list">${fixes.map(c => `<div class="fix-item"><div class="check-title">${esc(c.name)}</div><div class="item-meta">${esc(c.area)} · ${esc(c.status)}</div><div class="fix-command">${esc(c.fix)}</div></div>`).join('')}</div>`;
}
async function audio(){
  setHeader('音频队列','读取中...',
    `<button class="btn primary" onclick="action('analyze_audio',{limit:5})">分析 5 条</button><button class="btn" onclick="action('analyze_audio',{limit:20})">分析 20 条</button><button class="btn" onclick="go('speakers')">说话人</button><button class="btn" onclick="audio()">刷新</button>`);
  const qs = state.audioStatus ? `?status=${encodeURIComponent(state.audioStatus)}&limit=180` : '?limit=180';
  const j=await api('/api/audio'+qs);
  const summary = j.summary || {};
  const statuses = summary.statuses || {};
  const items = j.items || [];
  const selected = state.audioStatus || 'all';
  const pending = statuses.pending || 0;
  const errors = statuses.error || 0;
  const attention = audioAttentionCount(statuses);
  const coverage = summary.total ? Math.round((Number(summary.with_summary || 0) / Number(summary.total || 1)) * 100) : 0;
  const priority = items.filter(a => audioNeedsAttention(a.status)).slice(0, 8);
  $('subtitle').textContent = `${summary.total || 0} total · ${pending} pending · ${attention} attention · ${selected}`;
  $('view').innerHTML = `
    <div class="audio-hero">
      <div class="card">
        <div class="section-title"><h3>队列状态</h3>${status(errors ? 'error' : attention ? 'pending' : 'ok')}</div>
        <div class="audio-kpis">
          ${audioKpi('Total', summary.total || 0, 'mobile/audio_segment')}
          ${audioKpi('Pending', pending, 'waiting analysis')}
          ${audioKpi('Attention', attention, 'non-ok status')}
          ${audioKpi('Summary', `${summary.with_summary || 0}/${summary.total || 0}`, `${coverage}% covered`)}
        </div>
        <div class="audio-filters">${audioStatusFilters(statuses, summary.total || 0)}</div>
      </div>
      <div class="card">
        <div class="section-title"><h3>批处理</h3><span class="muted">${esc(summary.latest_analyzed || 'not analyzed')}</span></div>
        <div class="overview-actions">
          <button class="btn primary" onclick="action('analyze_audio',{limit:5})">分析 5 条</button>
          <button class="btn" onclick="action('analyze_audio',{limit:20})">分析 20 条</button>
          <button class="btn" onclick="action('analyze_audio',{limit:50})">分析 50 条</button>
          <button class="btn" onclick="go('sync')">手机同步</button>
        </div>
      </div>
    </div>
    <div class="audio-main">
      <div class="grid">
        ${priority.length ? `<div class="card">
          <div class="section-title"><h3>优先处理</h3><span class="muted">${esc(priority.length)} shown</span></div>
          ${audioPriorityList(priority)}
        </div>` : ''}
        <div class="card">
          <div class="section-title"><h3>队列明细</h3><span class="muted">${esc(items.length)} loaded</span></div>
          ${audioQueueList(items)}
        </div>
      </div>
      <div class="audio-side">
        <div class="card">
          <div class="section-title"><h3>状态分布</h3><span class="muted">${esc(selected)}</span></div>
          ${audioStatusBreakdown(statuses, summary.total || 0)}
        </div>
        <div class="card">
          <div class="section-title"><h3>覆盖率</h3></div>
          <div class="overview-queue">
            <div class="queue-row"><span>With summary</span><span class="queue-value">${esc(summary.with_summary || 0)}</span></div>
            <div class="queue-row"><span>With transcript/body</span><span class="queue-value">${esc(summary.with_body || 0)}</span></div>
            <div class="queue-row"><span>Latest analyzed</span><span class="queue-value">${esc(shortDateTime(summary.latest_analyzed || '-'))}</span></div>
          </div>
        </div>
      </div>
    </div>`;
}
function audioKpi(label, value, hint){
  return `<div class="audio-kpi"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint||'')}</div></div>`;
}
function audioStatusFilters(statuses, total){
  const keys = ['all', ...Object.keys(statuses || {}).sort((a,b) => audioStatusRank(a) - audioStatusRank(b) || a.localeCompare(b))];
  return keys.map(key => {
    const count = key === 'all' ? total : statuses[key];
    const active = (key === 'all' && !state.audioStatus) || state.audioStatus === key;
    const next = key === 'all' ? '' : key;
    return `<button class="filter-pill ${active?'active':''}" onclick="setAudioStatus('${escAttr(next)}')">${esc(key)} <span class="chip-count">${esc(count || 0)}</span></button>`;
  }).join('');
}
function setAudioStatus(value){
  state.audioStatus = value || '';
  audio();
}
function audioStatusRank(value){
  return ({error:0,missing_file:1,pending:2,processing:3,ok:4,skipped:5})[value] ?? 8;
}
function audioNeedsAttention(statusValue){
  const key = String(statusValue || 'pending');
  return !['ok','skipped'].includes(key);
}
function audioAttentionCount(statuses){
  return Object.entries(statuses || {}).reduce((total, [key, count]) => total + (audioNeedsAttention(key) ? Number(count || 0) : 0), 0);
}
function audioPriorityList(rows){
  return (rows || []).length ? `<div class="audio-priority">${rows.map(audioCard).join('')}</div>` : '<div class="empty-state">No non-ok audio in the current view</div>';
}
function audioQueueList(rows){
  return (rows || []).length ? `<div class="audio-list">${rows.map(audioCard).join('')}</div>` : '<div class="empty-state">No audio records match this filter</div>';
}
function audioCard(a){
  const text = a.error || a.summary || a.body_preview || 'No summary yet';
  const speakers = (a.speakers || []).length ? ` · ${a.speakers.join(' · ')}` : '';
  return `<div class="audio-card ${esc(a.status || 'pending')}">
    <div class="audio-time">${esc(shortDateTime(a.observed_at))}${a.captured_at?`<br><span class="muted">captured ${esc(shortDateTime(a.captured_at))}</span>`:''}</div>
    <div>${status(a.status || 'pending')}<div class="item-meta">${esc(formatSeconds(a.duration_seconds))}</div></div>
    <div><div class="audio-title">${esc(a.title || a.kind || 'Audio segment')}</div><div class="item-meta">${esc(a.source || '')}/${esc(a.kind || '')}${a.transcript_status?' · '+esc(a.transcript_status):''}${esc(speakers)}</div><div class="audio-body">${esc(text)}</div>${a.media_path?`<div class="audio-path">${esc(shortPath(a.media_path))}</div>`:''}</div>
  </div>`;
}
function audioStatusBreakdown(statuses, total){
  const keys = Object.keys(statuses || {}).sort((a,b) => audioStatusRank(a) - audioStatusRank(b) || a.localeCompare(b));
  if(!keys.length) return '<div class="empty-state">No audio statuses</div>';
  return `<div class="status-breakdown">${keys.map(key => `<div class="status-row"><span>${status(key)}</span><span class="queue-value">${esc(statuses[key])}</span></div>`).join('')}<div class="status-row"><span>Total</span><span class="queue-value">${esc(total)}</span></div></div>`;
}
function formatSeconds(value){
  const n = Number(value || 0);
  if(!Number.isFinite(n) || n <= 0) return '-';
  const total = Math.round(n);
  const min = Math.floor(total / 60);
  const sec = String(total % 60).padStart(2, '0');
  return `${min}:${sec}`;
}
async function search(){
  setHeader('搜索问答','本地检索、语义召回和证据问答', `<button class="btn" onclick="refreshSearchIndex()">索引状态</button><button class="btn primary" onclick="action('search_index',{limit:5000,force:true})">重建语义索引</button>`);
  $('view').innerHTML = `<div class="search-hero">
    <div class="card">
      <div class="section-title"><h3>工作台</h3>${status('info')}</div>
      <div class="searchbar">
        <input id="q" value="${esc(state.searchQ)}" placeholder="关键词或问题" oninput="state.searchQ=this.value" onkeydown="searchKey(event)" aria-label="search">
        <select id="src" onchange="setSearchSource(this.value)">${searchSourceOptions(state.searchSource)}</select>
        <button class="btn primary" onclick="doSearch()">搜索</button>
        <button class="btn" onclick="doAsk()">问答</button>
      </div>
      <textarea id="question" placeholder="向本地资料提问，例如：今天录音里有什么值得跟进？" oninput="state.searchQuestion=this.value">${esc(state.searchQuestion)}</textarea>
      <div class="search-actions">
        <button class="btn primary" onclick="doAsk()">问本地资料</button>
        <button class="btn" onclick="doSearch()">只搜索</button>
      </div>
    </div>
    <div class="search-side">
      <div class="card">
        <div class="section-title"><h3>语义索引</h3><span class="muted">local</span></div>
        <div id="indexStatus" class="muted">Loading...</div>
      </div>
      <div class="card">
        <div class="section-title"><h3>来源</h3><span id="searchSourceLabel" class="muted">${esc(searchSourceLabel(state.searchSource))}</span></div>
        ${searchSourcePills(state.searchSource)}
      </div>
    </div>
  </div>
  <div id="searchResults"></div>`;
  refreshSearchIndex();
}
async function refreshSearchIndex(){
  const j=await api('/api/search-index');
  const index=j.index || {};
  if(!$('indexStatus')) return;
  const models = index.models || [];
  const latest = models[0] || {};
  const coverage = index.coverage || {};
  const coveragePct = Math.round(Number(coverage.coverage || 0) * 100);
  const sourceRows = (coverage.by_source || []).slice(0, 8);
  $('indexStatus').innerHTML = `<div class="search-index-grid">
    <div class="search-index-stat"><div class="label">Vectors</div><div class="value">${esc(index.total_embeddings || 0)}</div></div>
    <div class="search-index-stat"><div class="label">Model</div><div class="value compact">${esc(shortModelName(latest.model || index.configured_model || '(auto)'))}</div></div>
    <div class="search-index-stat"><div class="label">Coverage</div><div class="value">${esc(coveragePct)}%</div></div>
    <div class="search-index-stat"><div class="label">Missing</div><div class="value">${esc(coverage.missing_observations || 0)}</div></div>
  </div>
  <div style="margin-top:10px">${sourceRows.map(row => `<div class="search-model-row"><div class="item-title">${esc(row.source)}/${esc(row.kind)}</div><div class="item-meta">${esc(row.indexed || 0)} / ${esc(row.total || 0)} indexed · priority ${esc(row.priority || 0)} · latest ${esc(shortDateTime(row.latest_observed || ''))}</div></div>`).join('') || '<div class="empty-state">No source coverage</div>'}</div>
  <div style="margin-top:10px">${models.map(m => `<div class="search-model-row"><div class="item-title">${esc(m.model)}</div><div class="item-meta">${esc(m.count)} vectors · ${esc(shortDateTime(m.latest || ''))}</div></div>`).join('') || '<div class="empty-state">No vectors</div>'}</div>
  <div class="item-meta">limit ${esc(index.index_limit || '-')} · auto ${esc(index.auto_index_limit || 0)} · candidates ${(index.candidate_models || []).slice(0, 3).map(esc).join(', ')}</div>`;
}
async function doSearch(){
  syncSearchState();
  const q=state.searchQ, src=state.searchSource;
  $('searchResults').innerHTML = searchLoading('Searching local memory...');
  const j=await api(`/api/search?q=${encodeURIComponent(q)}&source=${encodeURIComponent(src)}&limit=80`);
  $('searchResults').innerHTML = `${searchRetrievalCard(j)}
    <div class="search-main">
      <div class="card">
        <div class="section-title"><h3>语义结果</h3><span class="muted">${esc((j.semantic || []).length)} matches</span></div>
        ${searchSemanticList(j.semantic)}
      </div>
      <div class="search-stack">
        <div class="card">
          <div class="section-title"><h3>关键词记录</h3><span class="muted">${esc((j.observations || []).length)} records</span></div>
          ${searchObservationList(j.observations)}
        </div>
        <div class="card">
          <div class="section-title"><h3>报告</h3><span class="muted">${esc((j.reports || []).length)} files</span></div>
          ${searchReportList(j.reports)}
        </div>
      </div>
    </div>`;
}
async function doAsk(){
  syncSearchState();
  const question=(state.searchQuestion || state.searchQ || '').trim();
  if(!question){
    $('searchResults').innerHTML = `<div class="card" style="margin-top:14px"><div class="empty-state">No question yet</div></div>`;
    return;
  }
  $('searchResults').innerHTML = searchLoading('Retrieving evidence and asking the local model...');
  const j=await api('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question})});
  state.searchQuestion = question;
  $('searchResults').innerHTML = `<div class="search-answer-layout">
    <div class="card answer">
      <div class="section-title"><h3>答案</h3>${status(j.mode)}</div>
      <div class="result-meta"><span>retrieval ${esc((j.retrieval||{}).status||'')}</span><span>model ${esc((j.retrieval||{}).model||'')}</span>${(j.time_context||{}).now?`<span>${esc(shortDateTime(j.time_context.now))}</span>`:''}</div>
      <div class="answer-body" style="margin-top:12px">${esc(j.answer).replace(/\n/g,'<br>')}</div>
    </div>
    <div class="search-answer-side">
      <div class="card">
        <div class="section-title"><h3>检索</h3>${status((j.retrieval||{}).status||'keyword')}</div>
        <div class="search-metric-grid">
          ${searchMetric('Mode', (j.retrieval||{}).mode || j.mode || '-')}
          ${searchMetric('Indexed', (j.retrieval||{}).indexed || 0)}
        </div>
        ${(j.retrieval||{}).error?`<div class="search-error">${esc((j.retrieval||{}).error)}</div>`:''}
      </div>
      <div class="card">
        <div class="section-title"><h3>引用</h3><span class="muted">${esc((j.citations || []).length)} items</span></div>
        ${citationList(j.citations)}
      </div>
      <div class="card">
        <div class="section-title"><h3>证据分组</h3><span class="muted">${esc(evidenceGroupTotal(j.evidence_groups))} items</span></div>
        ${evidenceGroupsPanel(j.evidence_groups)}
      </div>
    </div>
  </div>`;
}
function syncSearchState(){
  if($('q')) state.searchQ = $('q').value;
  if($('src')) state.searchSource = $('src').value;
  if($('question')) state.searchQuestion = $('question').value;
}
function searchKey(event){
  if(event.key === 'Enter'){
    event.preventDefault();
    doSearch();
  }
}
function searchSourceOptions(selected){
  return searchSources.map(([value, label]) => `<option value="${escAttr(value)}" ${selected===value?'selected':''}>${esc(label)}</option>`).join('');
}
function searchSourcePills(selected){
  return `<div class="search-source-pills">${searchSources.map(([value, label]) => `<button data-search-source="${escAttr(value)}" class="filter-pill ${selected===value?'active':''}" onclick="setSearchSource('${escAttr(value)}')">${esc(label)}</button>`).join('')}</div>`;
}
function setSearchSource(value){
  state.searchSource = value || '';
  if($('src')) $('src').value = state.searchSource;
  if($('searchSourceLabel')) $('searchSourceLabel').textContent = searchSourceLabel(state.searchSource);
  document.querySelectorAll('[data-search-source]').forEach(btn => btn.classList.toggle('active', (btn.getAttribute('data-search-source') || '') === state.searchSource));
}
function searchSourceLabel(value){
  const found = searchSources.find(([source]) => source === value);
  return found ? found[1] : value || '全部来源';
}
function searchLoading(text){
  return `<div class="card" style="margin-top:14px"><div class="empty-state">${esc(text)}</div></div>`;
}
function searchRetrievalCard(j){
  const retrieval = j.retrieval || {};
  return `<div class="card search-retrieval">
    <div>
      <div class="section-title"><h3>检索概览</h3>${status(retrieval.status || 'keyword')}</div>
      <div class="result-meta">
        <span>query ${esc(j.query || state.searchQ || '-')}</span>
        <span>source ${esc(searchSourceLabel(state.searchSource))}</span>
        <span>mode ${esc(retrieval.mode || '-')}</span>
        <span>model ${esc(retrieval.model || '-')}</span>
      </div>
      ${retrieval.error ? `<div class="search-error">${esc(retrieval.error)}</div>` : ''}
    </div>
    <div class="search-metric-grid">
      ${searchMetric('Semantic', (j.semantic || []).length)}
      ${searchMetric('Keyword', (j.observations || []).length)}
      ${searchMetric('Reports', (j.reports || []).length)}
      ${searchMetric('Indexed', retrieval.indexed || 0)}
    </div>
  </div>`;
}
function searchMetric(label, value){
  return `<div class="search-metric"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div></div>`;
}
function searchSemanticList(rows){
  if(!(rows || []).length) return '<div class="empty-state">No semantic matches</div>';
  return `<div class="search-list">${rows.map(r => `<div class="search-result semantic">
    <div class="result-title">${esc(r.title || r.key || 'Semantic match')}</div>
    <div class="result-meta"><span>score ${esc(formatScore(r.score))}</span><span>${esc(shortDateTime(r.observed_at || ''))}</span><span>${esc(r.source || '')}/${esc(r.kind || '')}</span></div>
    <div class="result-text">${esc(r.text || '')}</div>
  </div>`).join('')}</div>`;
}
function searchObservationList(rows){
  if(!(rows || []).length) return '<div class="empty-state">No keyword records</div>';
  return `<div class="search-list">${rows.map(o => `<div class="search-result observation">
    <div class="result-title">${esc(o.title || o.subtitle || o.kind || o.name || 'Record')}</div>
    <div class="result-meta"><span>${esc(shortDateTime(o.observed_at || o.modified_at || ''))}</span><span>${esc(o.source || o.category || '')}/${esc(o.kind || '')}</span></div>
    <div class="result-text">${esc(o.body || o.summary || o.snippet || '')}</div>
  </div>`).join('')}</div>`;
}
function searchReportList(rows){
  if(!(rows || []).length) return '<div class="empty-state">No reports</div>';
  return `<div class="search-list">${rows.map(r => `<div class="search-result report">
    <div class="result-title">${esc(r.name || 'Report')}</div>
    <div class="result-meta"><span>${esc(r.category || '')}</span><span>${esc(shortDateTime(r.modified_at || ''))}</span></div>
    <div class="result-text">${esc(r.snippet || '')}</div>
  </div>`).join('')}</div>`;
}
function citationList(rows){
  if(!(rows || []).length) return '<div class="empty-state">No citations</div>';
  return `<div class="citation-list">${rows.map(c => `<div class="citation-row">
    <div class="citation-type">${esc(c.type || 'evidence')}</div>
    <div class="item-meta">${citationMeta(c).map(esc).join(' · ')}</div>
    <div class="result-text">${esc(c.name || c.path || c.key || c.id || '')}</div>
  </div>`).join('')}</div>`;
}
function citationMeta(c){
  const parts = [];
  if(c.time) parts.push(shortDateTime(c.time));
  if(c.source || c.kind) parts.push(`${c.source || ''}/${c.kind || ''}`);
  if(c.score !== undefined && c.score !== null) parts.push(`score ${formatScore(c.score)}`);
  if(c.date_context) parts.push(c.date_context);
  return parts;
}
function evidenceGroupTotal(payload){
  const counts = (payload || {}).counts || {};
  return Object.values(counts).reduce((sum, value) => sum + Number(value || 0), 0);
}
function evidenceGroupsPanel(payload){
  const groups = (payload || {}).groups || {};
  const keys = Object.keys(groups);
  if(!keys.length) return '<div class="empty-state">No grouped evidence</div>';
  return `<div class="evidence-groups">${keys.map(key => `<div class="evidence-group">
    <div class="section-title"><h3>${esc(evidenceGroupLabel(key))}</h3><span class="muted">${esc((groups[key] || []).length)}</span></div>
    ${(groups[key] || []).slice(0, 5).map(evidenceItem).join('')}
  </div>`).join('')}</div>`;
}
function evidenceItem(item){
  return `<div class="evidence-item">
    <div class="result-title">${esc(item.title || item.id || 'Evidence')}</div>
    <div class="result-meta"><span>${esc(shortDateTime(item.time || ''))}</span><span>${esc(item.source || '')}/${esc(item.kind || '')}</span>${item.score !== undefined && item.score !== null ? `<span>score ${esc(formatScore(item.score))}</span>` : ''}</div>
    <div class="result-text">${esc(item.snippet || item.location || item.path || '')}</div>
  </div>`;
}
function evidenceGroupLabel(key){
  return ({timeline:'时间线',audio:'录音',location:'位置',files:'文件',reports:'报告',semantic:'语义',feedback:'反馈'})[key] || key;
}
function formatScore(value){
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(3) : (value ?? '-');
}
function shortModelName(value){
  const text = String(value || '');
  return text.endsWith(':latest') ? text.slice(0, -7) : text;
}
async function timeline(){
  setHeader('时间线','按日期查看本地事件流', `<button class="btn" onclick="setTimelineDate('today')">今天</button><button class="btn" onclick="setTimelineDate('yesterday')">昨天</button><button class="btn primary" onclick="timeline()">Refresh</button>`);
  const j=await api(`/api/timeline?date=${encodeURIComponent(state.timelineDate)}`);
  const allEvents = j.events || [];
  const events = filterTimelineEvents(allEvents);
  const sourceCounts = countBy(allEvents, event => event.source || 'unknown');
  const typeCounts = countBy(allEvents, event => event.type || 'unknown');
  const statusCounts = countBy(allEvents.filter(event => event.status), event => event.status || 'unknown');
  const sources = Object.keys(sourceCounts).sort((a,b) => sourceCounts[b] - sourceCounts[a] || a.localeCompare(b));
  const types = Object.keys(typeCounts).sort((a,b) => typeCounts[b] - typeCounts[a] || a.localeCompare(b));
  const range = shortRange(allEvents[0]?.time, allEvents[allEvents.length - 1]?.time);
  $('subtitle').textContent = `${j.date} · ${events.length}/${allEvents.length} 条 · ${range}`;
  $('view').innerHTML = `
    <div class="timeline-hero">
      <div class="card">
        <div class="section-title"><h3>筛选</h3><span class="muted">${esc(j.date)}</span></div>
        <div class="timeline-toolbar">
          <input id="tlDate" value="${esc(state.timelineDate)}" aria-label="date">
          <input id="tlQ" value="${esc(state.timelineQ)}" placeholder="筛选标题、正文、source/kind" aria-label="search" onkeydown="timelineKey(event)">
          <select id="tlSource">${timelineSourceOptions(sources)}</select>
          <select id="tlType">${timelineTypeOptions(types)}</select>
          <button class="btn primary" onclick="applyTimelineFilters()">查找</button>
        </div>
        <div class="quickbar" style="margin-top:10px">
          <button class="filter-pill ${state.timelineDate==='today'?'active':''}" onclick="setTimelineDate('today')">今天</button>
          <button class="filter-pill ${state.timelineDate==='yesterday'?'active':''}" onclick="setTimelineDate('yesterday')">昨天</button>
          <button class="filter-pill ${!state.timelineQ && state.timelineSource==='all' && state.timelineType==='all'?'active':''}" onclick="resetTimelineFilters()">全部事件</button>
          <button class="filter-pill ${state.timelineType==='observation'?'active':''}" onclick="setTimelineType('observation')">Observation</button>
          <button class="filter-pill ${state.timelineType==='activity'?'active':''}" onclick="setTimelineType('activity')">Activity</button>
        </div>
        <div class="timeline-stats">
          ${timelineStat('事件', allEvents.length, `${events.length} 条显示`)}
          ${timelineStat('Observation', typeCounts.observation || 0, 'records')}
          ${timelineStat('Activity', typeCounts.activity || 0, 'foreground app')}
          ${timelineStat('来源', sources.length, range)}
        </div>
        ${hourBars(allEvents)}
      </div>
      <div class="card">
        <div class="section-title"><h3>来源</h3><span class="muted">${esc(state.timelineSource === 'all' ? '全部来源' : state.timelineSource)}</span></div>
        ${timelineBreakdown(sourceCounts, state.timelineSource, 'source')}
      </div>
    </div>
    <div class="timeline-main">
      <div>
        <div class="section-title"><h3>事件流</h3><span class="muted">${esc(events.length)} shown</span></div>
        <div class="timeline-feed">${timelineSections(events)}</div>
      </div>
      <div class="timeline-side">
        <div class="card">
          <div class="section-title"><h3>类型</h3><span class="muted">${esc(state.timelineType)}</span></div>
          ${timelineBreakdown(typeCounts, state.timelineType, 'type')}
        </div>
        <div class="card">
          <div class="section-title"><h3>状态</h3><span class="muted">${esc(Object.keys(statusCounts).length || 0)}</span></div>
          ${Object.keys(statusCounts).length ? timelineBreakdown(statusCounts, 'all', 'status') : '<div class="empty-state">No status tags</div>'}
        </div>
        <div class="card">
          <div class="section-title"><h3>当前筛选</h3></div>
          <div class="overview-queue">
            <div class="queue-row"><span>Date</span><span class="queue-value">${esc(j.date)}</span></div>
            <div class="queue-row"><span>Source</span><span class="queue-value">${esc(state.timelineSource)}</span></div>
            <div class="queue-row"><span>Type</span><span class="queue-value">${esc(state.timelineType)}</span></div>
            <div class="queue-row"><span>Query</span><span class="queue-value">${esc(state.timelineQ || '-')}</span></div>
          </div>
        </div>
      </div>
    </div>`;
}
function applyTimelineFilters(){
  state.timelineDate = $('tlDate').value || 'today';
  state.timelineQ = $('tlQ').value;
  state.timelineSource = $('tlSource').value || 'all';
  state.timelineType = $('tlType').value || 'all';
  timeline();
}
function timelineKey(event){
  if(event.key === 'Enter'){
    event.preventDefault();
    applyTimelineFilters();
  }
}
function setTimelineDate(value){
  state.timelineDate = value || 'today';
  timeline();
}
function setTimelineSource(value){
  state.timelineSource = value || 'all';
  timeline();
}
function setTimelineType(value){
  state.timelineType = value || 'all';
  timeline();
}
function resetTimelineFilters(){
  state.timelineQ = '';
  state.timelineSource = 'all';
  state.timelineType = 'all';
  timeline();
}
function filterTimelineEvents(rows){
  const q = String(state.timelineQ || '').trim().toLowerCase();
  return (rows || []).filter(event => {
    if(state.timelineSource && state.timelineSource !== 'all' && event.source !== state.timelineSource) return false;
    if(state.timelineType && state.timelineType !== 'all' && event.type !== state.timelineType) return false;
    if(!q) return true;
    const haystack = [event.time, event.type, event.source, event.kind, event.title, event.body, event.status].map(value => String(value || '').toLowerCase()).join(' ');
    return haystack.includes(q);
  });
}
function timelineSourceOptions(sources){
  const values = ['all', ...sources];
  if(state.timelineSource && !values.includes(state.timelineSource)) values.push(state.timelineSource);
  return values.map(value => `<option value="${escAttr(value)}" ${state.timelineSource===value?'selected':''}>${esc(value === 'all' ? '全部来源' : value)}</option>`).join('');
}
function timelineTypeOptions(types){
  const values = ['all', ...types];
  if(state.timelineType && !values.includes(state.timelineType)) values.push(state.timelineType);
  return values.map(value => `<option value="${escAttr(value)}" ${state.timelineType===value?'selected':''}>${esc(value === 'all' ? '全部类型' : value)}</option>`).join('');
}
function timelineStat(label, value, hint){
  return `<div class="timeline-stat"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint || '')}</div></div>`;
}
function countBy(rows, keyFn){
  return (rows || []).reduce((acc, row) => {
    const key = String(keyFn(row) || 'unknown');
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
}
function timelineBreakdown(counts, active, kind){
  const rows = Object.entries(counts || {}).sort(([,a],[,b]) => Number(b||0) - Number(a||0));
  if(!rows.length) return '<div class="empty-state">No records</div>';
  const total = rows.reduce((sum, [,count]) => sum + Number(count || 0), 0);
  const allActive = !active || active === 'all';
  const allClick = kind === 'source' ? "setTimelineSource('all')" : kind === 'type' ? "setTimelineType('all')" : '';
  return `<div class="timeline-breakdown">
    ${kind === 'status' ? '' : `<div class="timeline-breakdown-row ${allActive?'active':''}" onclick="${allClick}"><span>全部</span><span class="queue-value">${esc(total)}</span></div>`}
    ${rows.map(([key,count]) => {
      const click = kind === 'source' ? `setTimelineSource('${escAttr(key)}')` : kind === 'type' ? `setTimelineType('${escAttr(key)}')` : '';
      return `<div class="timeline-breakdown-row ${active===key?'active':''}" ${click?`onclick="${click}"`:''}><span>${esc(key)}</span><span class="queue-value">${esc(count)}</span></div>`;
    }).join('')}
  </div>`;
}
function timelineSections(rows){
  if(!(rows || []).length) return '<div class="empty-state">No timeline events match this filter</div>';
  const groups = {late: [], morning: [], afternoon: [], evening: [], night: []};
  (rows || []).forEach(event => groups[dayPartKey(event.time)].push(event));
  return ['late','morning','afternoon','evening','night']
    .filter(key => groups[key].length)
    .map(key => `<section class="timeline-section"><div class="timeline-section-header"><h3>${esc(dayPartLabel(key))}</h3><span class="muted">${groups[key].length} 条 · ${esc(shortRange(groups[key][0].time, groups[key][groups[key].length - 1].time))}</span></div><div class="timeline-list">${groups[key].map(timelineEventCard).join('')}</div></section>`)
    .join('');
}
function timelineEventCard(e){
  return `<div class="timeline-event ${esc(e.type || 'observation')}">
    <div class="timeline-time">${esc(shortTime(e.time))}</div>
    <div>${status(e.type || 'event')}${e.status?`<div style="margin-top:6px">${status(e.status)}</div>`:''}</div>
    <div><div class="timeline-title">${esc(e.title || e.kind || 'Event')}</div><div class="timeline-meta"><span>${esc(e.source || '')}/${esc(e.kind || '')}</span><span>${esc(shortDateTime(e.time))}</span></div>${e.body?`<div class="timeline-body">${esc(e.body)}</div>`:''}</div>
  </div>`;
}
async function reports(){
  setHeader('报告','日报、长期摘要、邮件摘要和反馈记录', `<button class="btn primary" onclick="action('refresh_report',{date:'today'})">刷新今日报告</button><button class="btn" onclick="action('compact',{date:'today',period:'all'})">压缩摘要</button><button class="btn" onclick="go('today')">今天</button><button class="btn" onclick="reports()">刷新</button>`);
  const suffix = state.reportPath ? `?path=${encodeURIComponent(state.reportPath)}` : '';
  const j=await api('/api/reports'+suffix);
  const files = j.files || [];
  const selectedPath = j.selected || state.reportPath || (files[0] || {}).path || '';
  if(selectedPath && state.reportPath !== selectedPath) state.reportPath = selectedPath;
  const selectedFile = files.find(file => file.path === selectedPath) || files[0] || {};
  const filteredFiles = filterReportFiles(files);
  const categoryCounts = countBy(files, file => file.category || 'reports');
  const headings = reportHeadings(j.content || '');
  const stats = reportStats(j.content || '');
  $('subtitle').textContent = selectedFile.name ? `${selectedFile.name} · ${escText(reportCategoryLabel(selectedFile.category))} · ${bytes(selectedFile.size || 0)}` : `${files.length} files`;
  $('view').innerHTML = `<div class="reports-layout">
    <div class="reports-nav">
      <div class="card reports-controls">
        <div class="section-title"><h3>报告库</h3><span class="muted">${esc(filteredFiles.length)}/${esc(files.length)}</span></div>
        <input id="reportQ" value="${esc(state.reportQ)}" placeholder="搜索文件名、分类、路径" onkeydown="reportSearchKey(event)" aria-label="report search">
        <button class="btn primary" onclick="applyReportSearch()">查找</button>
      </div>
      <div class="card">
        <div class="section-title"><h3>文件</h3><span class="muted">${esc(reportCategoryLabel(state.reportCategory))}</span></div>
        ${reportFileList(filteredFiles, selectedPath)}
      </div>
    </div>
    <div class="card report-reader">
      ${reportReader(selectedFile, j.content || '')}
    </div>
    <div class="reports-side">
      <div class="card">
        <div class="section-title"><h3>当前文件</h3>${selectedFile.category?reportCategoryBadge(selectedFile.category):status('empty')}</div>
        <div class="reports-metrics">
          ${reportMetric('Size', bytes(selectedFile.size || 0))}
          ${reportMetric('Lines', stats.lines)}
          ${reportMetric('Headings', headings.length)}
          ${reportMetric('Words', stats.words)}
        </div>
        <div class="item-meta" style="margin-top:10px">${esc(shortDateTime(selectedFile.modified_at || ''))}</div>
        <div class="item-meta">${esc(selectedFile.path || '')}</div>
      </div>
      <div class="card">
        <div class="section-title"><h3>分类</h3><span class="muted">${esc(reportCategoryLabel(state.reportCategory))}</span></div>
        ${reportCategoryBreakdown(categoryCounts, files.length)}
      </div>
      <div class="card">
        <div class="section-title"><h3>大纲</h3><span class="muted">${esc(headings.length)} headings</span></div>
        ${reportOutline(headings)}
      </div>
    </div>
  </div>`;
}
function applyReportSearch(){
  state.reportQ = $('reportQ').value;
  reports();
}
function reportSearchKey(event){
  if(event.key === 'Enter'){
    event.preventDefault();
    applyReportSearch();
  }
}
function setReportPath(path){
  state.reportPath = path || '';
  reports();
}
function setReportCategory(category){
  state.reportCategory = category || 'all';
  reports();
}
function filterReportFiles(files){
  const q = String(state.reportQ || '').trim().toLowerCase();
  return (files || []).filter(file => {
    if(state.reportCategory && state.reportCategory !== 'all' && file.category !== state.reportCategory) return false;
    if(!q) return true;
    const haystack = [file.name, file.category, file.path, file.modified_at].map(value => String(value || '').toLowerCase()).join(' ');
    return haystack.includes(q);
  });
}
function reportFileList(files, selectedPath){
  if(!(files || []).length) return '<div class="empty-state">No reports match this filter</div>';
  return `<div class="reports-list">${files.map(file => `<div class="report-file-item ${file.path===selectedPath?'active':''}" onclick="setReportPath('${escAttr(file.path)}')">
    <div class="report-file-title">${esc(file.name)}</div>
    <div class="report-file-meta"><span>${esc(reportCategoryLabel(file.category))}</span><span>${esc(bytes(file.size || 0))}</span><span>${esc(shortDateTime(file.modified_at || ''))}</span></div>
  </div>`).join('')}</div>`;
}
function reportCategoryBreakdown(counts, total){
  const order = ['all','reports','daily','weekly','monthly','email','feedback'];
  const keys = [...order, ...Object.keys(counts || {}).filter(key => !order.includes(key)).sort()];
  return `<div class="report-category-list">${keys.map(key => {
    const count = key === 'all' ? total : Number((counts || {})[key] || 0);
    if(key !== 'all' && count <= 0) return '';
    return `<div class="report-category-row ${state.reportCategory===key?'active':''}" onclick="setReportCategory('${escAttr(key)}')"><span>${esc(reportCategoryLabel(key))}</span><span class="queue-value">${esc(count)}</span></div>`;
  }).join('')}</div>`;
}
function reportReader(file, content){
  if(!content) return '<div class="empty-state">No report content</div>';
  return `<div class="report-reader-header">
    <div class="report-reader-title">${esc(file.name || 'Report')}</div>
    <div class="result-meta"><span>${esc(reportCategoryLabel(file.category))}</span><span>${esc(shortDateTime(file.modified_at || ''))}</span><span>${esc(bytes(file.size || 0))}</span></div>
  </div>
  <div class="report-reader-content">${renderReportMarkdown(content)}</div>`;
}
function reportMetric(label, value){
  return `<div class="report-metric"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div></div>`;
}
function reportCategoryBadge(value){
  return `<span class="status ${esc(value || 'info')}">${esc(reportCategoryLabel(value))}</span>`;
}
function reportStats(content){
  const text = String(content || '');
  return {
    lines: text ? text.split(/\n/).length : 0,
    words: text.trim() ? text.trim().split(/\s+/).length : 0
  };
}
function reportHeadings(content){
  return String(content || '').split(/\n/).map(line => {
    const match = line.match(/^(#{1,4})\s+(.+)$/);
    return match ? {level: match[1].length, text: match[2].trim()} : null;
  }).filter(Boolean);
}
function reportOutline(headings){
  if(!(headings || []).length) return '<div class="empty-state">No headings</div>';
  return `<div class="report-outline">${headings.slice(0, 18).map(h => `<div class="report-outline-row" style="padding-left:${Math.max(0, h.level - 1) * 10}px">${esc(h.text)}</div>`).join('')}</div>`;
}
function renderReportMarkdown(content){
  const lines = String(content || '').split(/\n/);
  const html = [];
  let inList = false;
  let inCode = false;
  const closeList = () => { if(inList){ html.push('</ul>'); inList = false; } };
  lines.forEach(line => {
    if(line.trim().startsWith('```')){
      if(inCode){ html.push('</code></pre>'); inCode = false; }
      else { closeList(); html.push('<pre><code>'); inCode = true; }
      return;
    }
    if(inCode){
      html.push(esc(line) + '\n');
      return;
    }
    if(!line.trim()){
      closeList();
      return;
    }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if(heading){
      closeList();
      const level = Math.min(4, heading[1].length);
      html.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      return;
    }
    const bullet = line.match(/^\s*[-*]\s+(.+)$/);
    if(bullet){
      if(!inList){ html.push('<ul>'); inList = true; }
      html.push(`<li>${inlineMarkdown(bullet[1])}</li>`);
      return;
    }
    closeList();
    html.push(`<p>${inlineMarkdown(line)}</p>`);
  });
  closeList();
  if(inCode) html.push('</code></pre>');
  return html.join('');
}
function inlineMarkdown(text){
  let value = esc(text);
  value = value.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  value = value.replace(/`([^`]+)`/g, '<code>$1</code>');
  return value;
}
function reportCategoryLabel(value){
  return ({all:'全部',reports:'日报',daily:'日摘要',weekly:'周摘要',monthly:'月摘要',email:'邮件摘要',feedback:'反馈'})[value] || value || '报告';
}
function escText(value){ return String(value ?? ''); }
async function sources(){
  setHeader('来源','采集器、数据来源和前置条件',
    `<button class="btn primary" onclick="action('collect',{date:'today'})">采集一次</button><button class="btn" onclick="go('doctor')">Doctor</button><button class="btn" onclick="sources()">刷新</button>`);
  const j=await api('/api/sources');
  const rows = j.sources || [];
  const shown = filterSourceRows(rows);
  const enabled = rows.filter(s => s.enabled).length;
  const issueRows = sourceIssues(rows);
  const totalRecords = rows.reduce((sum, source) => sum + sourceTotalCount(source), 0);
  const latest = sourceLatest(rows);
  $('subtitle').textContent = `${rows.length} 个来源 · ${enabled} 启用 · ${issueRows.length} 个问题 · ${totalRecords} 条记录`;
  $('view').innerHTML = `<div class="sources-hero">
    <div class="card">
      <div class="section-title"><h3>来源总览</h3>${status(issueRows.length ? 'warn' : 'ok')}</div>
      <div class="source-kpis">
        ${sourceKpi('来源', rows.length, `${enabled} 启用`)}
        ${sourceKpi('记录', totalRecords, 'observations')}
        ${sourceKpi('问题', issueRows.length, issueRows.length ? '需要处理' : '正常')}
        ${sourceKpi('最近', shortDateTime(latest || '-'), '最近记录')}
      </div>
      ${sourceViewFilters(rows, issueRows.length)}
    </div>
    <div class="card">
      <div class="section-title"><h3>来源动作</h3><span class="muted">采集与排查</span></div>
      <div class="source-action-grid">
        <button class="btn primary" onclick="action('collect',{date:'today'})">采集一次</button>
        <button class="btn" onclick="go('timeline')">时间线</button>
        <button class="btn" onclick="go('doctor')">Doctor</button>
      </div>
    </div>
  </div>
  <div class="sources-main">
    <div>
      <div class="section-title"><h3>来源明细</h3><span class="muted">${esc(shown.length)} shown</span></div>
      <div class="source-grid">${shown.map(sourceCard).join('') || '<div class="empty-state">No sources match this filter</div>'}</div>
    </div>
    <div class="source-side">
      <div class="card">
        <div class="section-title"><h3>需要处理</h3><span class="muted">${esc(issueRows.length)} 项</span></div>
        ${sourceIssueList(issueRows)}
      </div>
      <div class="card">
        <div class="section-title"><h3>记录分布</h3><span class="muted">按记录数</span></div>
        ${sourceDistribution(rows)}
      </div>
    </div>
  </div>`;
}
function filterSourceRows(rows){
  return (rows || []).filter(source => {
    const group = sourceGroup(source.source);
    if(state.sourceView === 'all') return true;
    if(state.sourceView === 'issues') return sourceHasIssue(source);
    if(state.sourceView === 'enabled') return !!source.enabled;
    if(state.sourceView === 'disabled') return !source.enabled;
    return group === state.sourceView;
  });
}
function setSourceView(value){
  state.sourceView = value || 'all';
  sources();
}
function sourceViewFilters(rows, issueCount){
  const groupCounts = countBy(rows || [], row => sourceGroup(row.source));
  const filters = [
    ['all', '全部', (rows || []).length],
    ['issues', '需要处理', issueCount],
    ['enabled', '启用', (rows || []).filter(row => row.enabled).length],
    ['disabled', '停用', (rows || []).filter(row => !row.enabled).length],
    ['chat', '聊天', groupCounts.chat || 0],
    ['device', '设备', groupCounts.device || 0],
    ['local', '本机', groupCounts.local || 0],
    ['ai', '本地 AI', groupCounts.ai || 0],
  ];
  return `<div class="source-filters">${filters.filter(([key, , count]) => count > 0 || ['all','issues'].includes(key)).map(([key,label,count]) => `<button class="filter-pill ${state.sourceView===key?'active':''}" onclick="setSourceView('${escAttr(key)}')">${esc(label)} <span class="chip-count">${esc(count)}</span></button>`).join('')}</div>`;
}
function sourceGroup(source){
  if(['messages','apple_mail'].includes(source)) return 'chat';
  if(['mobile'].includes(source)) return 'device';
  if(['calendar','reminders','browser','filesystem'].includes(source)) return 'local';
  if(['local_ai'].includes(source)) return 'ai';
  return 'other';
}
function sourceKpi(label, value, hint){
  return `<div class="source-kpi"><div class="label">${esc(label)}</div><div class="value ${String(value ?? '').length > 10 ? 'compact' : ''}">${esc(value)}</div><div class="hint">${esc(hint || '')}</div></div>`;
}
function sourceTotalCount(source){
  return (source.counts || []).reduce((sum, row) => sum + Number(row.count || 0), 0);
}
function sourceLatest(rows){
  const values = [];
  (rows || []).forEach(source => (source.counts || []).forEach(row => row.last && values.push(row.last)));
  values.sort();
  return values[values.length - 1] || '';
}
function sourceHasIssue(source){
  return !source.enabled || (source.notes || []).length > 0 || ((source.latest_run || {}).status && (source.latest_run || {}).status !== 'ok');
}
function sourceHealth(source){
  if(!source.enabled) return 'disabled';
  if((source.latest_run || {}).status && (source.latest_run || {}).status !== 'ok') return 'error';
  if((source.notes || []).length) return 'warn';
  return 'ok';
}
function sourceCard(source){
  const health = sourceHealth(source);
  const run = source.latest_run || {};
  return `<div class="source-card ${health === 'ok' ? '' : health === 'error' ? 'error' : health}">
    <div class="source-card-top">
      <div>
        <div class="source-name">${esc(source.source)}</div>
        <div class="item-meta">${esc(sourceGroupLabel(sourceGroup(source.source)))} · ${esc(sourceTotalCount(source))} records</div>
      </div>
      ${status(health)}
    </div>
    ${(source.notes || []).length ? `<div class="source-note-list" style="margin-top:10px">${source.notes.map(note => `<div class="source-note">${esc(note)}</div>`).join('')}</div>` : ''}
    <div class="source-run">${sourceRunSummary(source)}</div>
    ${sourceKindRows(source.counts)}
  </div>`;
}
function sourceGroupLabel(group){
  return ({chat:'聊天/通信',device:'设备同步',local:'本机采集',ai:'本地 AI',other:'其他'})[group] || group;
}
function sourceRunSummary(source){
  const run = source.latest_run || {};
  if(!run.id) return 'No collector run recorded';
  return `${run.status || '-'} · ${shortDateTime(run.started_at || '')}${run.message ? ' · ' + run.message : ''}`;
}
function sourceKindRows(counts){
  if(!(counts || []).length) return '<div class="empty-state" style="margin-top:10px">No observations yet</div>';
  return `<div class="source-kind-list">${counts.slice(0, 4).map(row => `<div class="source-kind-row"><b>${esc(row.kind)}</b><span>${esc(row.count)}</span><span>${esc(shortDateTime(row.last || ''))}</span></div>`).join('')}</div>`;
}
function sourceIssues(rows){
  return (rows || []).filter(sourceHasIssue);
}
function sourceIssueList(rows){
  if(!(rows || []).length) return '<div class="empty-state">No source issues</div>';
  return `<div class="source-issue-list">${rows.map(source => {
    const health = sourceHealth(source);
    const run = source.latest_run || {};
    const notes = (source.notes || []).join(' · ');
    const message = notes || run.message || (!source.enabled ? 'Disabled in collectors config' : 'Needs attention');
    return `<div class="source-issue ${health === 'error' ? 'fail' : ''}"><div class="source-issue-title">${esc(source.source)} ${status(health)}</div><div class="source-issue-body">${esc(message)}</div></div>`;
  }).join('')}</div>`;
}
function sourceDistribution(rows){
  const sorted = [...(rows || [])].sort((a,b) => sourceTotalCount(b) - sourceTotalCount(a));
  return `<div class="timeline-breakdown">${sorted.map(source => `<div class="timeline-breakdown-row" onclick="setSourceView('${escAttr(sourceGroup(source.source))}')"><span>${esc(source.source)}</span><span class="queue-value">${esc(sourceTotalCount(source))}</span></div>`).join('')}</div>`;
}
async function speakers(){
  setHeader('说话人','自动整理、人工确认、样本快速筛选', `<button class="btn" onclick="go('audio')">音频队列</button><button class="btn primary" onclick="speakers()">刷新</button>`);
  const [j, quality] = await Promise.all([api('/api/speakers'), api('/api/speaker-quality?view=needs_work')]);
  const speakerRows = j.speakers || [];
  const sampleRows = j.samples || [];
  const matchRows = j.matches || [];
  const profiles = j.profiles || [];
  state.speakers = speakerRows;
  state.speakerSamples = sampleRows;
  state.speakerProfiles = profiles;
  const shownSpeakers = sortSpeakers(filterSpeakers(speakerRows));
  state.speakerShownIds = shownSpeakers.map(s => String(s.id));
  state.speakerSelectedIds = speakerSelectedIds().filter(id => speakerRows.some(s => String(s.id) === String(id)));
  const selectedSet = new Set(state.speakerSelectedIds.map(String));
  const selectedRows = speakerRows.filter(s => selectedSet.has(String(s.id)));
  if(state.speakerBulkTarget && !speakerRows.some(s => String(s.id) === String(state.speakerBulkTarget))) state.speakerBulkTarget = '';
  const shownSet = new Set(state.speakerShownIds);
  const scopedSamples = speakerSampleScopeRows(sampleRows, selectedSet, shownSet);
  const focusedSamples = sortSpeakerSamples(filterSpeakerSamples(scopedSamples));
  state.speakerFocusedSampleSpeakerIds = [...new Set(focusedSamples.map(row => String(row.speaker_id || '')).filter(Boolean))];
  state.speakerFocusedSampleIds = focusedSamples.map(row => String(row.id || '')).filter(Boolean);
  const sampleFilterCounts = speakerSampleFilterCounts(scopedSamples);
  const provisional = speakerRows.filter(s => String(s.identity_status || '') === 'provisional').length;
  const noSamples = speakerRows.filter(s => Number(s.sample_count || 0) <= 0).length;
  const lowConfidence = speakerRows.filter(s => speakerHasLowConfidence(s)).length;
  const pendingAuto = speakerRows.filter(speakerIsAutoPending).length;
  const hidden = speakerRows.filter(speakerIsHidden).length;
  const missingEmbeddings = sampleRows.filter(sampleMissingEmbedding).length;
  const representativeSamples = sampleRows.filter(sampleIsRepresentative).length;
  const activeRows = speakerRows.filter(s => !speakerIsHidden(s));
  const confirmed = speakerRows.filter(s => speakerReviewStatus(s) === 'confirmed').length;
  const totalSamples = speakerRows.reduce((sum, s) => sum + Number(s.sample_count || 0), 0);
  const avgConfidence = activeRows.length ? Math.round((activeRows.reduce((sum, s) => sum + Number(s.confidence || 0), 0) / activeRows.length) * 100) : 0;
  $('subtitle').textContent = `${activeRows.length} 活跃 · ${pendingAuto} 自动整理待确认 · ${hidden} 已隐藏 · ${totalSamples} 样本`;
  $('view').innerHTML = `<div class="speakers-main">
    <div class="speaker-content">
      <div class="card speaker-workbench">
        <div class="speaker-command-row">
          <div class="speaker-command-copy">
            <div class="section-title"><h3>整理队列</h3>${speakerStatusBadge(pendingAuto ? 'auto_merged_pending_review' : hidden ? 'low_similarity_hidden' : 'ok')}</div>
            <p class="speaker-command-note">先用队列筛说话人；点卡片后下方样本会立刻切到选中说话人。批量确认、恢复和重算在右侧一次完成。</p>
          </div>
        </div>
        <div class="speaker-kpis">
          ${speakerKpi('活跃说话人', activeRows.length, `${confirmed} 已确认`)}
          ${speakerKpi('自动整理待确认', pendingAuto, '合并后需确认')}
          ${speakerKpi('隐藏低相似', hidden, '默认不再打扰')}
          ${speakerKpi('缺 embedding', missingEmbeddings, '样本无法匹配')}
          ${speakerKpi('代表样本', representativeSamples, '人物档案锚点')}
        </div>
      </div>
      <div class="speaker-review-layout">
        <section class="speaker-panel">
          <div class="speaker-panel-head">
            <div><h3>${esc(speakerViewLabel(state.speakerView))}</h3><div class="item-meta">${esc(shownSpeakers.length)} / ${esc(speakerRows.length)} 显示 · ${esc(selectedRows.length)} 已选</div></div>
            <span class="muted">点击卡片选择</span>
          </div>
          <div class="speaker-filter-row">
            <div class="speaker-filter-label">队列</div>
            <div class="speaker-filters">
              ${speakerFilter('active','活跃',activeRows.length)}
              ${speakerFilter('pending_auto','整理待确认',pendingAuto)}
              ${speakerFilter('low_confidence','低一致性',lowConfidence)}
              ${speakerFilter('review','人工复查',speakerRows.filter(s => !speakerIsHidden(s) && speakerNeedsReview(s)).length)}
              ${speakerFilter('hidden','隐藏',hidden)}
              ${speakerFilter('all','全部',speakerRows.length)}
            </div>
          </div>
          <div class="speaker-review-toolbar">
            <input id="speakerQ" value="${escAttr(state.speakerQ)}" placeholder="搜索 ID、名字、状态、来源、一致性" onkeydown="speakerSearchKey(event)" aria-label="speaker search">
            <select id="speakerSort" onchange="setSpeakerSort(this.value)">${speakerSortOptions()}</select>
            <button class="btn primary" onclick="applySpeakerSearch()">筛选</button>
          </div>
          <div class="speaker-grid">${shownSpeakers.map(speakerCard).join('') || '<div class="empty-state">No speakers match this filter</div>'}</div>
        </section>
        <section class="speaker-panel speaker-sample-panel">
          <div class="speaker-panel-head">
            <div>
              <h3>样本浏览</h3>
              <div class="speaker-sample-summary"><span>${esc(speakerSampleScopeLabel(selectedRows, shownSpeakers))}</span><span>${esc(focusedSamples.length)} / ${esc(scopedSamples.length)} 显示</span></div>
            </div>
            <span class="muted">${esc(sampleRows.length)} total</span>
          </div>
          <div class="speaker-sample-filters">
            ${speakerSampleFilter('all','全部',sampleFilterCounts.all)}
            ${speakerSampleFilter('needs_work','需处理',sampleFilterCounts.needs_work)}
            ${speakerSampleFilter('low_confidence','低一致性',sampleFilterCounts.low_confidence)}
            ${speakerSampleFilter('missing_embedding','缺 embedding',sampleFilterCounts.missing_embedding)}
            ${speakerSampleFilter('representative','代表',sampleFilterCounts.representative)}
            ${speakerSampleFilter('playable','可播放',sampleFilterCounts.playable)}
            ${speakerSampleFilter('detached','已分离',sampleFilterCounts.detached)}
          </div>
          <div class="speaker-sample-toolbar">
            <input id="speakerSampleQ" value="${escAttr(state.speakerSampleQ)}" placeholder="搜样本：说话人、obs、转写、状态" onkeydown="speakerSampleSearchKey(event)" aria-label="speaker sample search">
            <select id="speakerSamplesFor" onchange="setSpeakerSamplesFor(this.value)">${speakerSampleScopeOptions()}</select>
            <select id="speakerSampleSort" onchange="setSpeakerSampleSort(this.value)">${speakerSampleSortOptions()}</select>
            <button class="btn primary" onclick="applySpeakerSampleSearch()">筛选</button>
          </div>
          <div class="speaker-sample-list expanded">${speakerSampleList(focusedSamples, {limit: 80, expanded: true})}</div>
        </section>
      </div>
    </div>
    <div class="speaker-side">
      ${speakerOperationPanel(speakerRows, selectedRows)}
      <div class="card">
        <div class="section-title"><h3>质量中心</h3><span class="muted">${esc((quality.summary || {}).needs_work || 0)} need work</span></div>
        ${qualityList(quality.speakers || [])}
      </div>
      ${speakerProfilePanel(selectedRows, profiles)}
      <details class="card compact-details">
        <summary>近期匹配记录 ${esc(matchRows.length)} 条</summary>
        <div class="compact-details-body">${speakerMatchList(matchRows)}</div>
      </details>
    </div>
  </div>`;
}
function applySpeakerSearch(){
  state.speakerQ = $('speakerQ').value;
  state.speakerContextSource = String(state.speakerQ || '').trim() ? 'queue' : 'idle';
  speakers();
}
function speakerSearchKey(event){
  if(event.key === 'Enter'){
    event.preventDefault();
    applySpeakerSearch();
  }
}
function setSpeakerView(value){
  state.speakerView = value || 'all';
  state.speakerContextSource = state.speakerView === 'active' && !String(state.speakerQ || '').trim() ? 'idle' : 'queue';
  speakers();
}
function setSpeakerSort(value){
  state.speakerSort = value || 'review';
  speakers();
}
function setSpeakerSamplesFor(value){
  state.speakerSamplesFor = value || 'visible';
  state.speakerContextSource = state.speakerSamplesFor === 'visible' && state.speakerSampleView === 'all' && !String(state.speakerSampleQ || '').trim() ? 'idle' : 'samples';
  speakers();
}
function setSpeakerSampleView(value){
  state.speakerSampleView = value || 'all';
  state.speakerContextSource = state.speakerSampleView === 'all' && state.speakerSamplesFor === 'visible' && !String(state.speakerSampleQ || '').trim() ? 'idle' : 'samples';
  speakers();
}
function setSpeakerSampleSort(value){
  state.speakerSampleSort = value || 'needs_work';
  speakers();
}
function applySpeakerSampleSearch(){
  state.speakerSampleQ = $('speakerSampleQ').value;
  state.speakerContextSource = String(state.speakerSampleQ || '').trim() || state.speakerSampleView !== 'all' || state.speakerSamplesFor !== 'visible' ? 'samples' : 'idle';
  speakers();
}
function speakerSampleSearchKey(event){
  if(event.key === 'Enter'){
    event.preventDefault();
    applySpeakerSampleSearch();
  }
}
function filterSpeakers(rows){
  const q = String(state.speakerQ || '').trim().toLowerCase();
  return (rows || []).filter(s => {
    if(state.speakerView !== 'hidden' && state.speakerView !== 'all' && speakerIsHidden(s)) return false;
    if(state.speakerView === 'active' && speakerIsHidden(s)) return false;
    if(state.speakerView === 'pending_auto' && !speakerIsAutoPending(s)) return false;
    if(state.speakerView === 'review' && (speakerIsHidden(s) || !speakerNeedsReview(s))) return false;
    if(state.speakerView === 'provisional' && String(s.identity_status || '') !== 'provisional') return false;
    if(state.speakerView === 'low_confidence' && (speakerIsHidden(s) || !speakerHasLowConfidence(s))) return false;
    if(state.speakerView === 'samples' && Number(s.sample_count || 0) <= 0) return false;
    if(state.speakerView === 'empty' && Number(s.sample_count || 0) > 0) return false;
    if(state.speakerView === 'named' && speakerNeedsReview(s)) return false;
    if(state.speakerView === 'hidden' && !speakerIsHidden(s)) return false;
    if(!q) return true;
    const evidence = s.evidence || {};
    const metadata = s.metadata || {};
    const sourceNames = (metadata.auto_merge_sources || []).map(item => `${item.source_display_name || ''} ${item.source_speaker_id || ''}`).join(' ');
    const haystack = [s.id, s.display_name, s.identity_status, speakerReviewStatus(s), sourceNames, s.confidence, s.sample_count, s.alias_count, evidence.day_count, evidence.latest_seen_at].map(value => String(value || '').toLowerCase()).join(' ');
    return haystack.includes(q);
  });
}
function sortSpeakers(rows){
  const list = [...(rows || [])];
  const reviewScore = s => (speakerIsAutoPending(s) ? 2000 : 0) + (speakerNeedsReview(s) ? 1000 : 0) + (Number(s.sample_count || 0) <= 0 ? 200 : 0) + (speakerHasLowConfidence(s) ? 100 : 0);
  const latestTs = s => Date.parse(speakerVisibleTime(s) || '') || 0;
  const confidence = s => Number.isFinite(Number(s.confidence)) ? Number(s.confidence) : -1;
  if(state.speakerSort === 'samples') list.sort((a,b) => Number(b.sample_count || 0) - Number(a.sample_count || 0) || Number(a.id) - Number(b.id));
  else if(state.speakerSort === 'confidence') list.sort((a,b) => confidence(b) - confidence(a) || Number(a.id) - Number(b.id));
  else if(state.speakerSort === 'recent') list.sort((a,b) => latestTs(b) - latestTs(a) || Number(a.id) - Number(b.id));
  else if(state.speakerSort === 'id') list.sort((a,b) => Number(a.id) - Number(b.id));
  else list.sort((a,b) => reviewScore(b) - reviewScore(a) || latestTs(b) - latestTs(a) || Number(a.id) - Number(b.id));
  return list;
}
function speakerNeedsReview(s){
  const name = String(s.display_name || '');
  if(speakerIsAutoPending(s)) return true;
  if(speakerReviewStatus(s) === 'confirmed') return false;
  return String(s.identity_status || '') === 'provisional' || /^speaker\s*\d+$/i.test(name) || /^\d+$/.test(name) || Number(s.sample_count || 0) <= 0;
}
function speakerHasLowConfidence(s){
  if(speakerReviewStatus(s) === 'confirmed') return false;
  const confidence = Number(s.confidence);
  return Number.isFinite(confidence) && confidence > 0 && confidence < 0.68;
}
function sampleConfidenceValue(sample){
  const n = Number((sample.metadata || {}).sample_confidence);
  return Number.isFinite(n) ? n : null;
}
function sampleHasLowConfidence(sample){
  const confidence = sampleConfidenceValue(sample);
  return confidence !== null && confidence > 0 && confidence < 0.68;
}
function sampleHasError(sample){
  const metadata = sample.metadata || {};
  const statusText = String(metadata.status || '').toLowerCase();
  return !!metadata.error || ['error','fail','failed'].includes(statusText);
}
function sampleMissingEmbedding(sample){
  const metadata = sample.metadata || {};
  return !metadata.sample_confidence_model && !metadata.embedding_model && metadata.embedding_repair_status !== 'ok';
}
function sampleIsRepresentative(sample){
  return (sample.metadata || {}).representative_sample === true;
}
function sampleIsDetached(sample){
  return String((sample.metadata || {}).sample_role || '').includes('detached');
}
function speakerConfidenceSummary(s){
  return s.confidence_summary || {label: formatPercent(s.confidence), level: 'unknown', detail: ''};
}
function speakerConfidenceText(s){
  const summary = speakerConfidenceSummary(s);
  if(summary.value == null || summary.level === 'insufficient_evidence' || summary.level === 'missing_embedding' || summary.level === 'no_samples'){
    return summary.label || '-';
  }
  return `${summary.label || ''} ${formatPercent(summary.value)}`.trim();
}
function speakerReviewStatus(s){
  return String((s.metadata || {}).speaker_review_status || '');
}
function speakerIsAutoPending(s){
  return speakerReviewStatus(s) === 'auto_merged_pending_review';
}
function speakerIsHidden(s){
  const metadata = s.metadata || {};
  return metadata.speaker_hidden === true || speakerReviewStatus(s) === 'low_similarity_hidden';
}
function speakerViewLabel(value){
  return ({active:'活跃说话人', pending_auto:'自动整理待确认', review:'人工复查', low_confidence:'低一致性说话人', hidden:'隐藏低相似 Voice', all:'全部说话人'})[value || 'active'] || '说话人列表';
}
function speakerVisibleTime(s){
  const evidence = s.evidence || {};
  return evidence.latest_seen_at || s.latest_sample_at || s.created_at || '';
}
function sortSpeakerSamples(rows){
  const list = [...(rows || [])];
  const sampleConfidence = sample => sampleConfidenceValue(sample);
  const created = sample => Date.parse(sample.created_at || '') || 0;
  const duration = sample => Math.max(0, Number(sample.end_seconds || 0) - Number(sample.start_seconds || 0));
  const reviewScore = sample => (sampleMissingEmbedding(sample) ? 3000 : 0) + (sampleHasLowConfidence(sample) ? 2000 : 0) + (sampleHasError(sample) ? 1000 : 0);
  if(state.speakerSampleSort === 'recent') return list.sort((a,b) => created(b) - created(a) || Number(b.id || 0) - Number(a.id || 0));
  if(state.speakerSampleSort === 'speaker') return list.sort((a,b) => String(a.speaker_name || a.speaker_id || '').localeCompare(String(b.speaker_name || b.speaker_id || '')) || Number(a.id || 0) - Number(b.id || 0));
  if(state.speakerSampleSort === 'duration') return list.sort((a,b) => duration(b) - duration(a) || Number(b.id || 0) - Number(a.id || 0));
  return list.sort((a,b) => {
    const ar = reviewScore(a);
    const br = reviewScore(b);
    if(ar !== br) return br - ar;
    const av = sampleConfidence(a);
    const bv = sampleConfidence(b);
    const afin = Number.isFinite(av);
    const bfin = Number.isFinite(bv);
    if(afin && bfin && av !== bv) return av - bv;
    if(afin !== bfin) return afin ? -1 : 1;
    return Number(b.id || 0) - Number(a.id || 0);
  });
}
function speakerSampleScopeRows(rows, selectedSet, shownSet){
  const scope = state.speakerSamplesFor || 'visible';
  if(scope === 'selected') return selectedSet.size ? (rows || []).filter(row => selectedSet.has(String(row.speaker_id || ''))) : [];
  if(scope === 'all') return rows || [];
  return shownSet.size ? (rows || []).filter(row => shownSet.has(String(row.speaker_id || ''))) : [];
}
function filterSpeakerSamples(rows){
  const q = String(state.speakerSampleQ || '').trim().toLowerCase();
  return (rows || []).filter(sample => {
    if(state.speakerSampleView === 'needs_work' && !(sampleHasLowConfidence(sample) || sampleMissingEmbedding(sample) || sampleHasError(sample))) return false;
    if(state.speakerSampleView === 'low_confidence' && !sampleHasLowConfidence(sample)) return false;
    if(state.speakerSampleView === 'missing_embedding' && !sampleMissingEmbedding(sample)) return false;
    if(state.speakerSampleView === 'representative' && !sampleIsRepresentative(sample)) return false;
    if(state.speakerSampleView === 'playable' && !sample.sample_path) return false;
    if(state.speakerSampleView === 'detached' && !sampleIsDetached(sample)) return false;
    if(!q) return true;
    const metadata = sample.metadata || {};
    const haystack = [
      sample.id,
      sample.speaker_id,
      sample.speaker_name,
      sample.observation_id,
      sample.source_key,
      sample.transcript,
      sample.created_at,
      metadata.status,
      metadata.error,
      metadata.local_label,
      metadata.sample_role,
      metadata.sample_confidence,
      metadata.embedding_repair_status,
    ].map(value => String(value || '').toLowerCase()).join(' ');
    return haystack.includes(q);
  });
}
function speakerSampleFilterCounts(rows){
  const list = rows || [];
  return {
    all: list.length,
    needs_work: list.filter(sample => sampleHasLowConfidence(sample) || sampleMissingEmbedding(sample) || sampleHasError(sample)).length,
    low_confidence: list.filter(sampleHasLowConfidence).length,
    missing_embedding: list.filter(sampleMissingEmbedding).length,
    representative: list.filter(sampleIsRepresentative).length,
    playable: list.filter(sample => !!sample.sample_path).length,
    detached: list.filter(sampleIsDetached).length,
  };
}
function speakerFilter(key, label, count){
  return `<button class="filter-pill ${state.speakerView===key?'active':''}" onclick="setSpeakerView('${escAttr(key)}')">${esc(label)} <span class="chip-count">${esc(count)}</span></button>`;
}
function speakerSampleFilter(key, label, count){
  return `<button class="filter-pill ${state.speakerSampleView===key?'active':''}" onclick="setSpeakerSampleView('${escAttr(key)}')">${esc(label)} <span class="chip-count">${esc(count)}</span></button>`;
}
function speakerSortOptions(){
  const options = [['review','优先待清洗'], ['recent','最近出现'], ['samples','样本最多'], ['confidence','一致性最高'], ['id','ID 顺序']];
  return options.map(([value,label]) => `<option value="${escAttr(value)}" ${state.speakerSort===value?'selected':''}>${esc(label)}</option>`).join('');
}
function speakerSampleScopeOptions(){
  const options = [['visible','当前队列样本'], ['selected','选中说话人样本'], ['all','全部样本']];
  return options.map(([value,label]) => `<option value="${escAttr(value)}" ${state.speakerSamplesFor===value?'selected':''}>${esc(label)}</option>`).join('');
}
function speakerSampleSortOptions(){
  const options = [['needs_work','问题优先'], ['recent','最新样本'], ['speaker','按说话人'], ['duration','时长最长']];
  return options.map(([value,label]) => `<option value="${escAttr(value)}" ${state.speakerSampleSort===value?'selected':''}>${esc(label)}</option>`).join('');
}
function speakerSampleScopeLabel(selectedRows, shownRows){
  if(state.speakerSamplesFor === 'selected') return selectedRows.length ? `选中 ${selectedRows.length} 个说话人` : '未选择说话人';
  if(state.speakerSamplesFor === 'all') return '全部样本';
  return `当前队列 ${shownRows.length} 个说话人`;
}
function speakerKpi(label, value, hint){
  return `<div class="speaker-kpi"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint || '')}</div></div>`;
}
function speakerStatusBadge(value){
  const key = String(value || 'info');
  const label = ({provisional:'待确认',ok:'正常',confirmed:'已确认',accepted:'已接受',below_threshold:'低一致性',auto_merged_pending_review:'整理待确认',low_similarity_hidden:'已隐藏',needs_review:'待复查',info:'info'})[key] || key;
  return `<span class="status ${esc(key)}">${esc(label)}</span>`;
}
function speakerOperationPanel(rows, selectedRows){
  const selectedCount = selectedRows.length;
  const selectedSamples = selectedRows.reduce((sum, row) => sum + Number(row.sample_count || 0), 0);
  const single = selectedRows.length === 1 ? selectedRows[0] : null;
  const renameId = single ? String(single.id) : '';
  const renameName = single ? String(single.display_name || '') : '';
  const mergeTarget = state.speakerBulkTarget || preferredSpeakerMergeTarget(selectedRows);
  const visibleRows = visibleSpeakerRows(rows);
  const context = speakerContextState(selectedRows, visibleRows);
  return `<div class="card speaker-context-card">
    <div class="section-title"><h3>下一步</h3><span class="muted">${esc(context.badge)}</span></div>
    <div class="speaker-tools">
      ${speakerContextSummary(context, selectedCount, selectedSamples, mergeTarget, rows)}
      ${speakerContextActions(context)}
      ${selectedCount >= 2 ? `<div class="speaker-action-group">
        <div class="speaker-action-title">合并选中</div>
        <div class="speaker-bulk-row">
          <select id="bulkMergeTarget" onchange="state.speakerBulkTarget=this.value; speakers()">${speakerBulkTargetOptions(rows, mergeTarget)}</select>
          <button class="btn primary" onclick="bulkMergeSpeakers()">合并</button>
        </div>
      </div>` : ''}
      ${single ? `<div class="speaker-action-group">
        <div class="speaker-action-title">重命名</div>
        <div class="speaker-tool-row">
          <select id="renameId" onchange="selectSpeakerForRename(this.value)">${speakerSelectOptions(rows, renameId, '选择说话人')}</select>
          <input id="renameName" value="${escAttr(renameName)}" placeholder="显示名">
          <button class="btn primary" onclick="renameSelectedSpeaker()">保存</button>
        </div>
      </div>` : ''}
      <details class="compact-details">
        <summary>维护工具</summary>
        <div class="compact-details-body">
          <button class="btn" onclick="autoOrganizeSpeakers()">自动整理相似声音</button>
          <button class="btn" onclick="refreshSpeakerSampleConfidence()">重算全部一致性</button>
          <button class="btn" onclick="repairSpeakerEmbeddings()">补 embedding</button>
          <button class="btn" onclick="refreshRepresentativeSamples()">刷新代表样本</button>
          <button class="btn" onclick="reviveHiddenSpeakers()">复活隐藏队列</button>
          <button class="btn" onclick="action('speaker_normalize_names',{})">整理自动名</button>
          <button class="btn" onclick="action('analyze_audio',{limit:5})">分析 5 条音频</button>
        </div>
      </details>
      ${selectedCount ? `<details class="compact-details speaker-danger-row">
        <summary>危险操作</summary>
        <div class="compact-details-body">
          <button class="btn danger" onclick="bulkDeleteSpeakers()">删除选中</button>
        </div>
      </details>` : ''}
    </div>
  </div>`;
}
function visibleSpeakerRows(rows){
  const ids = new Set(visibleSpeakerIds());
  return (rows || []).filter(row => ids.has(String(row.id)));
}
function speakerContextState(selectedRows, visibleRows){
  const selectedCount = selectedRows.length;
  const sampleContext = state.speakerSampleView !== 'all' || !!String(state.speakerSampleQ || '').trim() || state.speakerSamplesFor !== 'visible';
  const queueContext = state.speakerView !== 'active' || !!String(state.speakerQ || '').trim();
  if(selectedCount){
    return {
      type: 'selection',
      title: selectedCount === 1 ? selectedRows[0].display_name || `Speaker ${selectedRows[0].id}` : `${selectedCount} 个说话人`,
      note: selectedCount === 1 ? '正在查看这个说话人的样本和可用动作。' : '多选后只显示批量相关动作。',
      badge: `${selectedCount} 已选`,
      rows: selectedRows,
    };
  }
  if(state.speakerContextSource === 'queue' && queueContext){
    return {
      type: 'queue',
      title: speakerViewLabel(state.speakerView),
      note: '当前队列筛选后，只显示适合这批说话人的动作。',
      badge: `${visibleRows.length} in queue`,
      rows: visibleRows,
    };
  }
  if(state.speakerContextSource === 'samples' && sampleContext){
    return {
      type: 'samples',
      title: speakerSampleContextLabel(),
      note: '当前 sample 筛选会决定这里显示哪些修复或聚类动作。',
      badge: `${focusedSampleSpeakerIds().length} 个说话人`,
      rows: visibleRows,
    };
  }
  if(queueContext){
    return {
      type: 'queue',
      title: speakerViewLabel(state.speakerView),
      note: '当前队列筛选后，只显示适合这批说话人的动作。',
      badge: `${visibleRows.length} in queue`,
      rows: visibleRows,
    };
  }
  return {
    type: 'idle',
    title: '选择一个说话人或筛选队列',
    note: '这里会自动出现和当前上下文相关的按钮，其它按钮保持隐藏。',
    badge: '待选择',
    rows: visibleRows,
  };
}
function speakerFallbackContextSource(){
  if(state.speakerView !== 'active' || String(state.speakerQ || '').trim()) return 'queue';
  if(state.speakerSampleView !== 'all' || state.speakerSamplesFor !== 'visible' || String(state.speakerSampleQ || '').trim()) return 'samples';
  return 'idle';
}
function speakerContextSummary(context, selectedCount, selectedSamples, mergeTarget, rows){
  const chips = [];
  if(context.type === 'selection'){
    chips.push(speakerSelectionChip('已选说话人', `${selectedCount} 个`));
    chips.push(speakerSelectionChip('样本记录', `${selectedSamples} 个`));
    if(selectedCount >= 2) chips.push(speakerSelectionChip('合并到', mergeTarget ? speakerCompactLabel(speakerById(rows, mergeTarget)) : '默认第一个已选'));
  } else if(context.type === 'queue'){
    chips.push(speakerSelectionChip('当前队列', speakerViewLabel(state.speakerView)));
    chips.push(speakerSelectionChip('显示说话人', `${context.rows.length} 个`));
  } else if(context.type === 'samples'){
    chips.push(speakerSelectionChip('样本筛选', speakerSampleContextLabel()));
    chips.push(speakerSelectionChip('涉及说话人', `${focusedSampleSpeakerIds().length} 个`));
  }
  const chipGrid = chips.length ? `<div class="speaker-selection-grid">${chips.join('')}</div>` : '';
  return `<div class="speaker-context-summary">
    <div class="speaker-context-title">${esc(context.title)}</div>
    <div class="speaker-context-note">${esc(context.note)}</div>
    ${chipGrid}
  </div>`;
}
function speakerContextActions(context){
  const buttons = speakerContextButtons(context);
  if(!buttons.length) return '<div class="empty-state">点击一个说话人、队列筛选或 sample 筛选后，相关按钮会自动出现。</div>';
  return `<div class="speaker-context-actions">${buttons.join('')}</div>`;
}
function speakerContextButtons(context){
  const buttons = [];
  if(context.type === 'selection'){
    const rows = context.rows || [];
    const hasHidden = rows.some(speakerIsHidden);
    const hasVisible = rows.some(row => !speakerIsHidden(row));
    if(hasVisible) buttons.push('<button class="btn primary" onclick="confirmSelectedSpeakers()">确认选中</button>');
    if(hasHidden) buttons.push('<button class="btn primary" onclick="unhideSelectedSpeakers()">取消隐藏</button>');
    buttons.push('<button class="btn" onclick="refreshSelectedSpeakerSampleConfidence()">重算选中一致性</button>');
    buttons.push('<button class="btn" onclick="clearSpeakerSelection()">清空选择</button>');
    return buttons;
  }
  if(context.type === 'queue'){
    const count = (context.rows || []).length;
    if(!count) return buttons;
    if(state.speakerView === 'pending_auto' || state.speakerView === 'review') buttons.push('<button class="btn primary" onclick="confirmVisibleSpeakers()">确认当前队列</button>');
    if(state.speakerView === 'hidden') buttons.push('<button class="btn primary" onclick="unhideVisibleSpeakers()">取消隐藏当前队列</button>');
    if(state.speakerView === 'low_confidence' || state.speakerView === 'review' || state.speakerQ) buttons.push('<button class="btn" onclick="refreshVisibleSpeakerSampleConfidence()">重算当前队列</button>');
    buttons.push('<button class="btn" onclick="selectVisibleSpeakers()">选择当前队列</button>');
    return buttons;
  }
  if(context.type === 'samples'){
    const ids = focusedSampleSpeakerIds();
    if(!ids.length) return buttons;
    if(state.speakerSampleView === 'missing_embedding') buttons.push('<button class="btn primary" onclick="repairSpeakerEmbeddings()">补 embedding</button>');
    if(state.speakerSampleView === 'representative') buttons.push('<button class="btn primary" onclick="refreshFocusedRepresentativeSamples()">刷新这些代表样本</button>');
    if(state.speakerSampleView === 'low_confidence' || state.speakerSampleView === 'needs_work' || state.speakerSampleQ) buttons.push('<button class="btn primary" onclick="refreshFocusedSampleSpeakerConfidence()">重算相关说话人</button>');
    buttons.push('<button class="btn" onclick="repairFocusedSampleClips()">重裁这些样本</button>');
    buttons.push('<button class="btn" onclick="selectFocusedSampleSpeakers()">选择这些样本所属说话人</button>');
    return buttons;
  }
  return buttons;
}
function speakerSampleContextLabel(){
  const viewLabel = ({all:'全部样本', needs_work:'需处理样本', low_confidence:'低一致性样本', missing_embedding:'缺 embedding 样本', representative:'代表样本', playable:'可播放样本', detached:'已分离样本'})[state.speakerSampleView || 'all'] || state.speakerSampleView || '样本';
  const scopeLabel = ({visible:'当前队列', selected:'选中说话人', all:'全部说话人'})[state.speakerSamplesFor || 'visible'] || '当前队列';
  const q = String(state.speakerSampleQ || '').trim();
  return q ? `${scopeLabel} · ${viewLabel} · "${q}"` : `${scopeLabel} · ${viewLabel}`;
}
function speakerSelectionChip(label, value='-'){
  return `<div class="speaker-selection-chip"><div class="label">${esc(label)}</div><div class="value">${esc(value || '-')}</div></div>`;
}
function speakerSelectOptions(rows, selected, placeholder){
  const head = `<option value="">${esc(placeholder || '选择说话人')}</option>`;
  return head + (rows || []).map(row => `<option value="${escAttr(row.id)}" ${String(selected || '')===String(row.id)?'selected':''}>${esc(speakerCompactLabel(row))}</option>`).join('');
}
function speakerBulkTargetOptions(rows, selected){
  const head = `<option value="">默认第一个已选</option>`;
  return head + (rows || []).map(row => `<option value="${escAttr(row.id)}" ${String(selected || '')===String(row.id)?'selected':''}>${esc(speakerCompactLabel(row))}</option>`).join('');
}
function speakerCompactLabel(s){
  if(!s) return '-';
  return `#${s.id} ${s.display_name || 'Speaker'} · ${s.sample_count || 0} samples · ${speakerConfidenceText(s)}`;
}
function preferredSpeakerMergeTarget(rows){
  const named = (rows || []).find(row => String(row.identity_status || '') === 'named');
  if(named) return String(named.id || '');
  return rows && rows.length ? String(rows[0].id || '') : '';
}
function speakerById(rows, id){
  if(!id) return null;
  return (rows || []).find(row => String(row.id) === String(id)) || null;
}
function speakerCard(s){
  const evidence = s.evidence || {};
  const review = speakerNeedsReview(s);
  const empty = Number(s.sample_count || 0) <= 0;
  const selected = speakerIsSelected(s.id);
  const reviewStatus = speakerReviewStatus(s);
  const confidence = speakerConfidenceSummary(s);
  return `<div class="speaker-card ${empty?'empty':review?'review':''} ${speakerIsHidden(s)?'hidden-speaker':''} ${selected?'selected':''}" onclick="toggleSpeakerSelection('${escAttr(s.id)}')">
    <input class="speaker-check" type="checkbox" ${selected?'checked':''} onclick="event.stopPropagation(); setSpeakerChecked('${escAttr(s.id)}', this.checked)" aria-label="select speaker ${escAttr(s.id)}">
    <div class="speaker-card-top">
      <div><div class="speaker-name">${esc(s.display_name || `Speaker ${s.id}`)}</div><div class="speaker-meta"><span>ID ${esc(s.id)}</span><span>${esc(shortDateTime(speakerVisibleTime(s)) || '-')}</span></div></div>
      ${speakerStatusBadge(reviewStatus || s.identity_status || 'info')}
    </div>
    ${speakerMergeSourceSummary(s)}
    <div class="speaker-card-metrics">
      <span><b>${esc(s.sample_count || 0)}</b> 样本</span>
      <span><b>${esc(evidence.day_count || 0)}</b> 天</span>
      <span title="${escAttr(confidence.detail || '')}"><b>${esc(speakerConfidenceText(s))}</b></span>
      <span>embedding ${esc(s.embedding_count || 0)}</span>
      <span>别名 ${esc(s.alias_count || 0)}</span>
      <span>最近 ${esc(shortDateTime(evidence.latest_seen_at || s.latest_sample_at || '-') || '-')}</span>
    </div>
  </div>`;
}
function speakerMergeSourceSummary(s){
  const sources = ((s.metadata || {}).auto_merge_sources || []).slice(-3).reverse();
  if(!sources.length && !speakerIsHidden(s)) return '';
  if(speakerIsHidden(s)) return `<div class="speaker-meta"><span>低相似自动隐藏</span><span>threshold ${esc(formatScore((s.metadata || {}).hidden_threshold))}</span></div>`;
  return `<div class="speaker-meta"><span>自动合并 ${esc((s.metadata || {}).auto_merge_sources.length)} 个来源</span><span>${sources.map(item => esc(`#${item.source_speaker_id || '-'} ${item.source_display_name || ''} ${formatScore(item.score)}`)).join(' · ')}</span></div>`;
}
function speakerSelectedIds(){
  if(!Array.isArray(state.speakerSelectedIds)) state.speakerSelectedIds = [];
  return state.speakerSelectedIds.map(String).filter(Boolean);
}
function speakerIsSelected(id){
  return speakerSelectedIds().includes(String(id));
}
function setSpeakerSelectedIds(ids){
  state.speakerSelectedIds = [...new Set((ids || []).map(id => String(id)).filter(Boolean))];
}
function toggleSpeakerSelection(id){
  const key = String(id || '');
  if(!key) return;
  const ids = speakerSelectedIds();
  if(ids.length === 1 && ids[0] === key){
    setSpeakerSelectedIds([]);
    state.speakerSamplesFor = 'visible';
    state.speakerContextSource = speakerFallbackContextSource();
  } else {
    setSpeakerSelectedIds([key]);
    state.speakerSamplesFor = 'selected';
    state.speakerContextSource = 'selection';
  }
  speakers();
}
function setSpeakerChecked(id, checked){
  const key = String(id || '');
  const ids = speakerSelectedIds();
  setSpeakerSelectedIds(checked ? [...ids, key] : ids.filter(item => item !== key));
  state.speakerSamplesFor = 'selected';
  state.speakerContextSource = 'selection';
  speakers();
}
function selectSpeakerForRename(id){
  setSpeakerSelectedIds(id ? [id] : []);
  state.speakerSamplesFor = 'selected';
  state.speakerContextSource = id ? 'selection' : speakerFallbackContextSource();
  speakers();
}
function selectVisibleSpeakers(){
  setSpeakerSelectedIds(state.speakerShownIds || []);
  state.speakerSamplesFor = 'selected';
  state.speakerContextSource = 'selection';
  speakers();
}
function invertVisibleSpeakers(){
  const shown = (state.speakerShownIds || []).map(String);
  const selected = new Set(speakerSelectedIds());
  shown.forEach(id => selected.has(id) ? selected.delete(id) : selected.add(id));
  setSpeakerSelectedIds([...selected]);
  state.speakerSamplesFor = 'selected';
  state.speakerContextSource = selected.size ? 'selection' : speakerFallbackContextSource();
  speakers();
}
function clearSpeakerSelection(){
  state.speakerSelectedIds = [];
  state.speakerBulkTarget = '';
  state.speakerSamplesFor = 'visible';
  state.speakerContextSource = speakerFallbackContextSource();
  speakers();
}
function renameSelectedSpeaker(){
  const speakerId = $('renameId')?.value || speakerSelectedIds()[0];
  const displayName = $('renameName')?.value || '';
  if(!speakerId || !displayName.trim()){
    toast('请选择说话人并输入显示名');
    return;
  }
  action('speaker_rename',{speaker_id:speakerId,display_name:displayName});
}
function autoOrganizeSpeakers(){
  if(confirm('自动整理相似声音：按 0.68 自动合并相似声音，并把低相似未命名 Voice 隐藏到单独筛选里？')){
    action('speaker_auto_organize',{threshold:0.68});
  }
}
function confirmSelectedSpeakers(){
  const ids = speakerSelectedIds();
  if(!ids.length){
    toast('请先勾选要确认的说话人');
    return;
  }
  action('speaker_confirm',{speaker_ids:ids});
}
function unhideSelectedSpeakers(){
  const ids = speakerSelectedIds();
  if(!ids.length){
    toast('请先勾选要取消隐藏的说话人');
    return;
  }
  action('speaker_unhide',{speaker_ids:ids});
}
function visibleSpeakerIds(){
  return (state.speakerShownIds || []).map(String).filter(Boolean);
}
function confirmVisibleSpeakers(){
  const ids = visibleSpeakerIds();
  if(!ids.length){
    toast('当前队列没有可处理的说话人');
    return;
  }
  if(confirm(`确认当前队列里的 ${ids.length} 个说话人？`)) action('speaker_confirm',{speaker_ids:ids});
}
function unhideVisibleSpeakers(){
  const ids = visibleSpeakerIds();
  if(!ids.length){
    toast('当前队列没有可处理的说话人');
    return;
  }
  if(confirm(`取消隐藏当前队列里的 ${ids.length} 个说话人？`)) action('speaker_unhide',{speaker_ids:ids});
}
function refreshVisibleSpeakerSampleConfidence(){
  const ids = visibleSpeakerIds();
  if(!ids.length){
    toast('当前队列没有可处理的说话人');
    return;
  }
  refreshSpeakerSampleConfidence(ids);
}
function focusedSampleSpeakerIds(){
  return (state.speakerFocusedSampleSpeakerIds || []).map(String).filter(Boolean);
}
function focusedSampleIds(){
  return (state.speakerFocusedSampleIds || []).map(String).filter(Boolean);
}
function selectFocusedSampleSpeakers(){
  const ids = focusedSampleSpeakerIds();
  if(!ids.length){
    toast('当前样本筛选没有关联说话人');
    return;
  }
  setSpeakerSelectedIds(ids);
  state.speakerSamplesFor = 'selected';
  state.speakerContextSource = 'selection';
  speakers();
}
function refreshFocusedSampleSpeakerConfidence(){
  const ids = focusedSampleSpeakerIds();
  if(!ids.length){
    toast('当前样本筛选没有关联说话人');
    return;
  }
  refreshSpeakerSampleConfidence(ids);
}
function refreshFocusedRepresentativeSamples(){
  const ids = focusedSampleSpeakerIds();
  if(!ids.length){
    toast('当前样本筛选没有关联说话人');
    return;
  }
  action('speaker_refresh_representatives',{speaker_ids:ids, per_speaker:3});
}
function repairFocusedSampleClips(){
  const ids = focusedSampleIds();
  if(!ids.length){
    toast('当前样本筛选没有可处理的样本');
    return;
  }
  if(confirm(`按当前裁剪策略重裁 ${ids.length} 个样本？只会处理能找到源音频的样本，已确认说话人不会被重新分组。`)){
    action('speaker_repair_sample_clips',{sample_ids:ids, apply:true});
  }
}
function bulkMergeSpeakers(){
  const ids = speakerSelectedIds();
  const selectedRows = (state.speakers || []).filter(row => ids.includes(String(row.id)));
  const targetId = $('bulkMergeTarget')?.value || state.speakerBulkTarget || preferredSpeakerMergeTarget(selectedRows) || ids[0] || '';
  const sourceIds = ids.filter(id => String(id) !== String(targetId));
  if(!targetId || sourceIds.length < 1){
    toast('至少勾选两个说话人，或选择一个合并目标');
    return;
  }
  if(confirm(`把 ${sourceIds.length} 个说话人合并到 ${targetId}？`)) action('speaker_merge_many',{target_id:targetId,source_ids:sourceIds});
}
function refreshSpeakerSampleConfidence(speakerIds=[]){
  const ids = (speakerIds || []).map(String).filter(Boolean);
  action('speaker_refresh_sample_confidence', ids.length ? {speaker_ids:ids} : {});
}
function refreshSelectedSpeakerSampleConfidence(){
  const ids = speakerSelectedIds();
  if(!ids.length){
    toast('未选择说话人，将重算全部说话人一致性');
  }
  refreshSpeakerSampleConfidence(ids);
}
function repairSpeakerEmbeddings(){
  if(confirm('为已有样本补齐缺失的 speaker embedding？这会调用本地 SpeechBrain 模型，可能需要一点时间。')){
    action('speaker_repair_embeddings',{apply:true});
  }
}
function refreshRepresentativeSamples(){
  const ids = speakerSelectedIds();
  action('speaker_refresh_representatives', ids.length ? {speaker_ids:ids, per_speaker:3} : {per_speaker:3});
}
function reviveHiddenSpeakers(){
  if(confirm('把隐藏队列里已经积累足够证据的 Voice 放回人工复查？')){
    action('speaker_revive_hidden',{apply:true,min_samples:2,min_days:2,min_embeddings:2});
  }
}
function bulkDeleteSpeakers(){
  const ids = speakerSelectedIds();
  if(!ids.length){
    toast('请先勾选要删除的说话人');
    return;
  }
  if(confirm(`删除 ${ids.length} 个说话人及其托管样本记录？这个操作不能撤销。`)) action('speaker_delete_many',{speaker_ids:ids});
}
function fillSpeakerRename(id, name){
  setSpeakerSelectedIds(id ? [id] : []);
  state.speakerSamplesFor = id ? 'selected' : 'visible';
  state.speakerContextSource = id ? 'selection' : speakerFallbackContextSource();
  if($('renameId')) $('renameId').value = id || '';
  if($('renameName')) $('renameName').value = name || '';
  toast(`已填入说话人 ${id}`);
}
function speakerProfilePanel(selectedRows, profiles){
  const selectedId = selectedRows.length === 1 ? String(selectedRows[0].id) : '';
  const profile = (profiles || []).find(item => String((item.speaker || {}).id) === selectedId) || (profiles || [])[0];
  if(!profile || profile.ok === false) return `<details class="card compact-details"><summary>人物档案</summary><div class="compact-details-body"><div class="empty-state">No active speaker profile</div></div></details>`;
  const speaker = profile.speaker || {};
  const confidence = profile.confidence || {};
  const stats = profile.stats || {};
  return `<details class="card compact-details">
    <summary>人物档案 · ${esc(speaker.display_name || `Speaker ${speaker.id}`)} · ${esc(confidence.label || '-')}</summary>
    <div class="compact-details-body">
    <div class="speaker-profile-head">
      <div class="speaker-name">${esc(speaker.display_name || `Speaker ${speaker.id}`)}</div>
      <div class="item-meta">ID ${esc(speaker.id)} · ${esc(stats.day_count || 0)} 天 · ${esc(profile.embedding_count || 0)} embeddings · ${speakerStatusBadge((speaker.metadata || {}).speaker_review_status || speaker.identity_status || 'info')}</div>
    </div>
    <div class="speaker-profile-note">${esc(confidence.detail || '')}</div>
    <div class="speaker-profile-block">
      <div class="speaker-action-title">代表样本</div>
      ${speakerSampleList(profile.representative_samples || [])}
    </div>
    <div class="speaker-profile-block">
      <div class="speaker-action-title">说话人时间线</div>
      ${speakerTimelineList(profile.timeline || [])}
    </div>
    </div>
  </details>`;
}
function speakerTimelineList(rows){
  if(!(rows || []).length) return '<div class="empty-state">No speaker timeline yet</div>';
  return `<div class="speaker-match-list">${rows.slice(0, 8).map(item => `<div class="speaker-match-card">
    <div class="speaker-match-row"><div><b>${esc(shortDateTime(item.observed_at || '') || '-')}</b><div class="item-meta">${esc(item.source || '')}/${esc(item.kind || '')} · ${esc(formatSecondsRange(item.start_seconds, item.end_seconds))}</div></div></div>
    <div class="speaker-transcript">${esc(item.transcript || item.body || '')}</div>
  </div>`).join('')}</div>`;
}
function speakerSampleList(rows, options={}){
  if(!(rows || []).length) return '<div class="empty-state">No speaker samples yet</div>';
  const limit = Number(options.limit || 6);
  const shown = rows.slice(0, limit);
  const more = rows.length > limit ? `<div class="empty-state">还有 ${esc(rows.length - limit)} 个样本，可继续缩小筛选条件。</div>` : '';
  const body = `${shown.map(sample => {
    const sampleConfidence = sampleConfidenceText(sample);
    const rep = sampleIsRepresentative(sample) ? ' · 代表样本' : '';
    const cardClass = speakerSampleCardClass(sample);
    const badges = speakerSampleBadges(sample);
    return `<div class="speaker-sample-card ${cardClass}">
    <div class="speaker-match-row"><div><b>${esc(sample.speaker_name || sample.speaker_id)}</b><div class="item-meta">sample ${esc(sample.id || '-')} · ${esc(formatSecondsRange(sample.start_seconds, sample.end_seconds))} · obs ${esc(sample.observation_id || '-')}${sampleConfidence ? ` · ${sampleConfidence}` : ''}${esc(rep)}</div></div>${status((sample.metadata || {}).status || 'info')}</div>
    ${badges ? `<div class="speaker-sample-tags">${badges}</div>` : ''}
    <div class="speaker-transcript">${esc(sample.transcript || '')}</div>
    ${sample.sample_path ? `<audio controls preload="metadata"><source src="/api/speaker-sample/${escAttr(sample.id)}" type="audio/mp4"></audio>` : ''}
    <div class="speaker-sample-actions"><button class="btn" onclick="detachSpeakerSample('${escAttr(sample.id)}')">分离成新说话人</button></div>
  </div>`;
  }).join('')}${more}`;
  return options.expanded ? body : `<div class="speaker-sample-list">${body}</div>`;
}
function sampleConfidenceText(sample){
  const n = sampleConfidenceValue(sample);
  return Number.isFinite(n) ? `样本一致性 ${formatPercent(n)}` : '';
}
function speakerSampleCardClass(sample){
  if(sampleHasError(sample)) return 'error';
  if(sampleHasLowConfidence(sample)) return 'low-confidence';
  if(sampleIsRepresentative(sample)) return 'representative';
  if(sampleMissingEmbedding(sample)) return 'missing-embedding';
  return 'ok';
}
function speakerSampleBadges(sample){
  const metadata = sample.metadata || {};
  const badges = [];
  if(sampleHasLowConfidence(sample)) badges.push(speakerStatusBadge('below_threshold'));
  if(sampleMissingEmbedding(sample)) badges.push('<span class="status skipped">缺 embedding</span>');
  if(sampleIsRepresentative(sample)) badges.push('<span class="status accepted">代表样本</span>');
  if(sampleIsDetached(sample)) badges.push('<span class="status info">已分离</span>');
  if(sample.sample_path) badges.push('<span class="status observation">可播放</span>');
  if(metadata.sample_role && !sampleIsDetached(sample)) badges.push(`<span class="status info">${esc(metadata.sample_role)}</span>`);
  return badges.join('');
}
function detachSpeakerSample(sampleId){
  const sample = (state.speakerSamples || []).find(row => String(row.id) === String(sampleId));
  const current = sample ? (sample.speaker_name || sample.speaker_id || '当前说话人') : '当前说话人';
  if(confirm(`把这个样本从 ${current} 分离出来，并单独新建一个 Voice？`)){
    action('speaker_detach_sample', {sample_id: sampleId});
  }
}
function speakerMatchList(rows){
  if(!(rows || []).length) return '<div class="empty-state">No match decisions</div>';
  return `<div class="speaker-match-list">${rows.slice(0, 12).map(match => `<div class="speaker-match-card">
    <div class="speaker-match-row"><div><b>${esc(match.source_name || match.source_speaker_id)}</b><div class="item-meta">to ${esc(match.target_name || match.target_speaker_id || '-')}</div></div>${speakerStatusBadge(match.status || 'info')}</div>
    <div class="speaker-meta"><span>${esc(shortDateTime(match.created_at || ''))}</span><span class="speaker-score">score ${esc(formatScore(match.score))}</span><span>threshold ${esc(formatScore(match.threshold))}</span></div>
    ${match.source_speaker_id && match.target_speaker_id ? `<div style="margin-top:8px"><button class="btn" onclick="selectSpeakerMatchGroup('${escAttr(match.source_speaker_id)}','${escAttr(match.target_speaker_id)}')">勾选这组</button></div>` : ''}
  </div>`).join('')}</div>`;
}
function selectSpeakerMatchGroup(sourceId, targetId){
  setSpeakerSelectedIds([sourceId, targetId]);
  state.speakerBulkTarget = targetId || '';
  state.speakerSamplesFor = 'selected';
  speakers();
}
function formatPercent(value){
  const n = Number(value);
  return Number.isFinite(n) ? `${Math.round(n * 100)}%` : '-';
}
function formatSecondsRange(start, end){
  const a = Number(start);
  const b = Number(end);
  if(!Number.isFinite(a) || !Number.isFinite(b)) return '-';
  return `${a.toFixed(1)}s-${b.toFixed(1)}s`;
}
async function files(){
  setHeader('文件','读取中...', `<button class="btn primary" onclick="action('analyze_new_files',{})">扫描新文件</button><button class="btn" onclick="go('recycle')">回收箱</button><button class="btn" onclick="files()">刷新</button>`);
  const j=await api('/api/files');
  const cfg = j.file_analysis || {};
  const rows = j.recent || [];
  const shown = filterFileRecords(rows);
  const fileState = j.state || {};
  const stateData = fileState.data || {};
  const processedCount = Object.keys(stateData.processed_keys || {}).length;
  $('subtitle').textContent = `${(j.watch_paths || []).length} 个路径 · ${escText(j.media_analysis_count || 0)} 个分析 · ${shown.length}/${rows.length} 条记录`;
  $('view').innerHTML = `
    <div class="files-hero">
      <div class="card">
        <div class="section-title"><h3>分析状态</h3>${status(cfg.enabled ? 'ok' : 'disabled')}</div>
        <div class="file-kpis">
          ${fileKpi('文件分析', cfg.enabled ? '开启' : '关闭', `${cfg.scan_interval_seconds ?? '-'} 秒扫描`)}
          ${fileKpi('已分析', j.media_analysis_count || 0, 'local_ai/media_analysis')}
          ${fileKpi('监控路径', (j.watch_paths || []).length, `${cfg.max_files_per_scan ?? '-'} 个/轮`)}
          ${fileKpi('已处理', processedCount, `上次 ${formatEpoch(stateData.last_scan_ts)}`)}
        </div>
        ${fileFilterPills(rows)}
      </div>
      <div class="card">
        <div class="section-title"><h3>扫描控制</h3><span class="muted">${esc(formatBool(cfg.delete_after_analysis))}</span></div>
        ${fileConfigRows(cfg)}
        <div class="overview-actions" style="margin-top:12px">
          <button class="btn primary" onclick="action('analyze_new_files',{})">扫描新文件</button>
          <button class="btn" onclick="go('recycle')">查看回收箱</button>
        </div>
      </div>
    </div>
    <div class="file-main">
      <div>
        <div class="section-title"><h3>最近文件记录</h3><span class="muted">${esc(shown.length)} shown</span></div>
        <div class="file-toolbar">
          <input id="fileQ" value="${esc(state.fileQ)}" placeholder="搜索文件名、路径、正文、source/kind" aria-label="file search" onkeydown="fileSearchKey(event)">
          <button class="btn primary" onclick="applyFileSearch()">查找</button>
        </div>
        ${fileRecordList(shown)}
      </div>
      <div class="file-side">
        <div class="card">
          <div class="section-title"><h3>监控路径</h3><span class="muted">${esc((j.watch_paths || []).length)} paths</span></div>
          ${filePathList(j.watch_paths || [])}
        </div>
        <div class="card">
          <div class="section-title"><h3>格式规则</h3><span class="muted">${esc((cfg.include_suffixes || []).length)} include</span></div>
          ${fileRulePanel(cfg)}
        </div>
        <div class="card">
          <div class="section-title"><h3>状态文件</h3>${status(fileState.exists ? 'ok' : 'missing_file')}</div>
          ${fileStatePanel(fileState)}
        </div>
      </div>
    </div>`;
}
function applyFileSearch(){
  state.fileQ = $('fileQ').value;
  files();
}
function fileSearchKey(event){
  if(event.key === 'Enter'){
    event.preventDefault();
    applyFileSearch();
  }
}
function setFileView(value){
  state.fileView = value || 'all';
  files();
}
function filterFileRecords(rows){
  const q = String(state.fileQ || '').trim().toLowerCase();
  return (rows || []).filter(row => {
    if(!fileViewMatch(row, state.fileView)) return false;
    if(!q) return true;
    const haystack = [row.title, row.subtitle, row.source, row.kind, row.body, row.summary, row.snippet, row.source_key, fileRecordPath(row)].map(value => String(value || '').toLowerCase()).join(' ');
    return haystack.includes(q);
  });
}
function fileViewMatch(row, view){
  if(!view || view === 'all') return true;
  if(view === 'filesystem') return row.source === 'filesystem';
  if(view === 'analysis') return fileIsAnalysis(row);
  if(view === 'with_body') return Boolean(row.body || row.summary || row.snippet);
  if(view === 'large') return fileRecordSize(row) >= 10 * 1024 * 1024;
  return true;
}
function fileFilterPills(rows){
  const views = [
    ['all', '全部', (rows || []).length],
    ['filesystem', '文件事件', (rows || []).filter(row => row.source === 'filesystem').length],
    ['analysis', '已有分析', (rows || []).filter(fileIsAnalysis).length],
    ['with_body', '有正文', (rows || []).filter(row => row.body || row.summary || row.snippet).length],
    ['large', '大文件', (rows || []).filter(row => fileRecordSize(row) >= 10 * 1024 * 1024).length],
  ];
  return `<div class="file-filters">${views.map(([key,label,count]) => `<button class="filter-pill ${state.fileView===key?'active':''}" onclick="setFileView('${escAttr(key)}')">${esc(label)} ${esc(count)}</button>`).join('')}</div>`;
}
function fileKpi(label, value, hint){
  return `<div class="file-kpi"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint || '')}</div></div>`;
}
function fileConfigRows(cfg){
  const rows = [
    ['扫描间隔', `${cfg.scan_interval_seconds ?? '-'} 秒`],
    ['稳定等待', `${cfg.stability_seconds ?? '-'} 秒`],
    ['每轮上限', cfg.max_files_per_scan ?? '-'],
    ['分析后删除', formatBool(cfg.delete_after_analysis)],
    ['工作区', cfg.analysis_copy_dir || '-'],
  ];
  return `<div class="file-config-list">${rows.map(([label,value]) => `<div class="queue-row"><span>${esc(label)}</span><span class="queue-value">${esc(value)}</span></div>`).join('')}</div>`;
}
function fileRecordList(rows){
  if(!(rows || []).length) return '<div class="empty-state">No file records match this filter</div>';
  return `<div class="file-list">${rows.slice(0, 80).map(fileRecordCard).join('')}</div>`;
}
function fileRecordCard(row){
  const path = fileRecordPath(row);
  const size = fileRecordSize(row);
  return `<div class="file-card ${esc(fileRecordClass(row))}">
    <div class="file-time">${esc(shortDateTime(row.observed_at || row.captured_at || ''))}${row.captured_at?`<br><span class="muted">captured ${esc(shortDateTime(row.captured_at))}</span>`:''}</div>
    <div>${fileRecordBadge(row)}<div class="item-meta" style="margin-top:6px">ID ${esc(row.id || '-')}</div></div>
    <div>
      <div class="file-title">${esc(row.title || row.kind || 'File record')}</div>
      <div class="file-meta"><span>${esc(row.source || '')}/${esc(row.kind || '')}</span>${size?`<span>${esc(bytes(size))}</span>`:''}${path?`<span>${esc(shortPath(path))}</span>`:''}</div>
      <div class="file-body">${esc(row.body || row.summary || row.snippet || path || '文件变更记录')}</div>
    </div>
  </div>`;
}
function fileRecordBadge(row){
  if(fileIsAnalysis(row)) return '<span class="status ok">分析</span>';
  if(row.source === 'filesystem') return '<span class="status observation">文件事件</span>';
  return `<span class="status skipped">${esc(row.source || 'record')}</span>`;
}
function fileRecordClass(row){
  if(fileIsAnalysis(row)) return 'analysis';
  if(row.source === 'filesystem') return 'filesystem';
  return 'other';
}
function fileIsAnalysis(row){
  return row.source === 'local_ai' || row.source === 'openai' || row.kind === 'media_analysis';
}
function fileRecordPath(row){
  const meta = row.metadata || {};
  return meta.path || meta.file_path || meta.resolved_media_path || row.source_key || row.subtitle || '';
}
function fileRecordSize(row){
  const meta = row.metadata || {};
  return Number(meta.size || meta.file_size || meta.bytes || 0);
}
function filePathList(paths){
  if(!(paths || []).length) return '<div class="empty-state">No watch paths configured</div>';
  return `<div class="file-path-list">${paths.map(path => `<div class="file-path-row"><div class="file-path-title">${esc(shortPath(path) || path)}</div><div class="item-meta">${esc(path)}</div></div>`).join('')}</div>`;
}
function fileRulePanel(cfg){
  return `<div>
    <div class="item-meta">支持格式</div>
    ${fileChipList(cfg.include_suffixes || [])}
    <div class="item-meta" style="margin-top:12px">跳过格式</div>
    ${fileChipList(cfg.exclude_suffixes || [])}
    <div class="item-meta" style="margin-top:12px">跳过目录</div>
    ${fileChipList(cfg.exclude_dirs || [])}
  </div>`;
}
function fileChipList(items){
  if(!(items || []).length) return '<div class="muted">-</div>';
  return `<div class="file-chip-row">${items.map(item => `<span class="file-chip">${esc(item)}</span>`).join('')}</div>`;
}
function fileStatePanel(fileState){
  if(!fileState || !fileState.exists) return '<div class="empty-state">No file analysis state yet</div>';
  const data = fileState.data || {};
  const processed = Object.keys(data.processed_keys || {}).length;
  const rows = [
    ['文件', shortPath(fileState.path || '-')],
    ['last_scan_ts', formatEpoch(data.last_scan_ts)],
    ['watermark', formatEpoch(data.watermark)],
    ['processed_keys', processed],
  ];
  return `<div class="file-state-list">${rows.map(([label,value]) => `<div class="file-state-row"><div class="file-state-title">${esc(label)}</div><div class="item-meta">${esc(value)}</div></div>`).join('')}</div>`;
}
function formatBool(value){
  return value ? '开启' : '关闭';
}
function formatEpoch(value){
  const n = Number(value);
  if(!Number.isFinite(n) || n <= 0) return '-';
  return new Date(n * 1000).toLocaleString('zh-CN', {hour12: false});
}
async function recycle(){
  setHeader('回收箱','读取中...',
    `<button class="btn" onclick="go('files')">文件</button><button class="btn" onclick="action('recycle_purge',{})">预览清理</button><button class="btn danger" onclick="confirm('永久删除已到期的回收箱文件？') && action('recycle_purge',{apply:true})">清理到期</button><button class="btn primary" onclick="recycle()">刷新</button>`);
  const j=await api('/api/recycle-bin');
  const entries = j.entries || [];
  const shown = filterRecycleEntries(entries);
  const summary = j.summary || {};
  const config = j.config || {};
  const preview = j.purge_preview || {};
  const nextDelete = summary.next_delete_after ? shortDateTime(summary.next_delete_after) : '-';
  $('subtitle').textContent = `${summary.files || 0} 个文件 · ${bytes(summary.total_bytes || 0)} · ${summary.due_files || 0} 到期 · 下次 ${nextDelete}`;
  $('view').innerHTML = `
    <div class="recycle-hero">
      <div class="card">
        <div class="section-title"><h3>暂存概览</h3>${status(config.enabled ? 'ok' : 'disabled')}</div>
        <div class="recycle-kpis">
          ${recycleKpi('暂存文件', summary.files || 0, `${summary.manifests || 0} manifests`)}
          ${recycleKpi('占用空间', bytes(summary.total_bytes || 0), `${summary.orphan_manifests || 0} orphan`)}
          ${recycleKpi('到期可删', summary.due_files || 0, `${bytes(preview.freed_bytes || 0)} 可释放`)}
          ${recycleKpi('保留期', `${config.retention_hours ?? 24}h`, `下次 ${nextDelete}`)}
        </div>
        ${recycleFilterPills(entries)}
      </div>
      <div class="card">
        <div class="section-title"><h3>清理预览</h3><span class="muted">${esc(preview.deleted_files || 0)} files</span></div>
        ${recyclePreviewPanel(preview)}
        <div class="recycle-actions" style="margin-top:12px">
          <button class="btn" onclick="action('recycle_purge',{})">预览清理</button>
          <button class="btn danger" onclick="confirm('永久删除已到期的回收箱文件？') && action('recycle_purge',{apply:true})">清理到期</button>
        </div>
      </div>
    </div>
    <div class="recycle-main">
      <div>
        <div class="section-title"><h3>回收文件</h3><span class="muted">${esc(shown.length)} shown</span></div>
        <div class="recycle-toolbar">
          <input id="recycleQ" value="${esc(state.recycleQ)}" placeholder="搜索文件名、原路径、回收路径、分类" aria-label="recycle search" onkeydown="recycleSearchKey(event)">
          <button class="btn primary" onclick="applyRecycleSearch()">查找</button>
        </div>
        ${recycleEntryList(shown)}
      </div>
      <div class="recycle-side">
        <div class="card">
          <div class="section-title"><h3>恢复</h3><span class="muted">${esc(shortPath(config.dir || ''))}</span></div>
          ${recycleRestorePanel()}
        </div>
        <div class="card">
          <div class="section-title"><h3>分类</h3><span class="muted">${esc(entries.length)} entries</span></div>
          ${recycleCategoryBreakdown(entries)}
        </div>
        <div class="card">
          <div class="section-title"><h3>配置</h3>${status(config.enabled ? 'ok' : 'disabled')}</div>
          ${recycleConfigPanel(config)}
        </div>
      </div>
    </div>`;
}
function applyRecycleSearch(){
  state.recycleQ = $('recycleQ').value;
  recycle();
}
function recycleSearchKey(event){
  if(event.key === 'Enter'){
    event.preventDefault();
    applyRecycleSearch();
  }
}
function setRecycleView(value){
  state.recycleView = value || 'all';
  recycle();
}
function filterRecycleEntries(entries){
  const q = String(state.recycleQ || '').trim().toLowerCase();
  return (entries || []).filter(entry => {
    if(!recycleViewMatch(entry, state.recycleView)) return false;
    if(!q) return true;
    const metadata = entry.metadata || {};
    const haystack = [entry.name, entry.category, entry.original_path, entry.trash_path, entry.moved_at, entry.delete_after, metadata.reason, metadata.import_root].map(value => String(value || '').toLowerCase()).join(' ');
    return haystack.includes(q);
  });
}
function recycleViewMatch(entry, view){
  if(!view || view === 'all') return true;
  if(view === 'due') return recycleIsDue(entry);
  if(view === 'retained') return entry.exists !== false && !recycleIsDue(entry);
  if(view === 'missing') return entry.exists === false;
  if(view === 'mobile') return recycleIsMobile(entry);
  if(view === 'unknown') return String(entry.category || 'unknown') === 'unknown';
  return true;
}
function recycleFilterPills(entries){
  const rows = [
    ['all', '全部', (entries || []).length],
    ['due', '到期', (entries || []).filter(recycleIsDue).length],
    ['retained', '保留中', (entries || []).filter(entry => entry.exists !== false && !recycleIsDue(entry)).length],
    ['mobile', '手机音频', (entries || []).filter(recycleIsMobile).length],
    ['missing', '缺失', (entries || []).filter(entry => entry.exists === false).length],
    ['unknown', '未知', (entries || []).filter(entry => String(entry.category || 'unknown') === 'unknown').length],
  ];
  return `<div class="recycle-filters">${rows.map(([key,label,count]) => `<button class="filter-pill ${state.recycleView===key?'active':''}" onclick="setRecycleView('${escAttr(key)}')">${esc(label)} ${esc(count)}</button>`).join('')}</div>`;
}
function recycleKpi(label, value, hint){
  return `<div class="recycle-kpi"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint || '')}</div></div>`;
}
function recycleEntryList(entries){
  if(!(entries || []).length) return '<div class="empty-state">No recycled files match this filter</div>';
  return `<div class="recycle-list">${entries.slice(0, 120).map(recycleEntryCard).join('')}</div>`;
}
function recycleEntryCard(entry){
  const original = entry.original_path || '';
  const trash = entry.trash_path || '';
  return `<div class="recycle-card ${esc(recycleCardClass(entry))}">
    <div class="recycle-time">${esc(shortDateTime(entry.moved_at || ''))}<br><span class="muted">${esc(shortDateTime(entry.delete_after || ''))}</span></div>
    <div>${recycleStatusBadge(entry)}<div class="item-meta" style="margin-top:6px">${esc(bytes(entry.size || 0))}</div></div>
    <div>
      <div class="recycle-title">${esc(entry.name || shortPath(trash) || 'Recycled file')}</div>
      <div class="recycle-meta"><span>${esc(recycleCategoryLabel(entry.category))}</span><span>${esc(recycleTimeLeft(entry))}</span>${entry.manifest_path?'<span>manifest</span>':'<span>no manifest</span>'}</div>
      <div class="recycle-path">${esc(original || '原路径未知')}<br>${esc(trash)}</div>
    </div>
    <button class="btn" onclick="fillRecycleRestore('${escAttr(trash)}','${escAttr(original)}')">填入</button>
  </div>`;
}
function recycleStatusBadge(entry){
  if(entry.exists === false) return '<span class="status missing_file">缺失</span>';
  if(recycleIsDue(entry)) return '<span class="status warn">到期</span>';
  return '<span class="status ok">保留中</span>';
}
function recycleCardClass(entry){
  if(entry.exists === false) return 'missing';
  if(recycleIsDue(entry)) return 'due';
  if(String(entry.category || 'unknown') === 'unknown') return 'unknown';
  return 'retained';
}
function recycleIsDue(entry){
  const ts = Date.parse(entry.delete_after || '');
  return Number.isFinite(ts) && ts <= Date.now();
}
function recycleIsMobile(entry){
  const category = String(entry.category || '');
  return category.startsWith('mobile') || String(entry.original_path || '').includes('/mobile_sync/');
}
function recycleTimeLeft(entry){
  const ts = Date.parse(entry.delete_after || '');
  if(!Number.isFinite(ts)) return '无到期时间';
  const diff = ts - Date.now();
  if(diff <= 0) return '已到期';
  return `${formatDuration(diff)} 后到期`;
}
function recyclePreviewPanel(preview){
  const rows = [
    ['删除文件', preview.deleted_files || 0],
    ['删除 manifest', preview.deleted_manifests || 0],
    ['空目录', preview.deleted_dirs || 0],
    ['可释放', bytes(preview.freed_bytes || 0)],
    ['保留文件', preview.retained_files || 0],
  ];
  return `<div class="recycle-preview-list">${rows.map(([label,value]) => `<div class="recycle-preview-row"><span>${esc(label)}</span><span class="queue-value">${esc(value)}</span></div>`).join('')}</div>`;
}
function recycleRestorePanel(){
  return `<div class="recycle-form">
    <input id="trashPath" placeholder="回收文件路径">
    <input id="restoreTo" placeholder="恢复到指定路径，可留空">
    <button class="btn primary" onclick="restoreRecycle($('trashPath').value,$('restoreTo').value)">恢复</button>
  </div>`;
}
function fillRecycleRestore(trashPath, originalPath=''){
  if($('trashPath')) $('trashPath').value = trashPath || '';
  if($('restoreTo')) $('restoreTo').value = originalPath || '';
  toast('已填入恢复路径');
}
function recycleCategoryBreakdown(entries){
  const counts = countBy(entries || [], entry => recycleCategoryLabel(entry.category));
  const rows = Object.entries(counts).sort(([,a],[,b]) => Number(b || 0) - Number(a || 0));
  if(!rows.length) return '<div class="empty-state">No recycle categories</div>';
  return `<div class="recycle-category-list">${rows.map(([label,count]) => `<div class="recycle-category-row"><span>${esc(label)}</span><span class="queue-value">${esc(count)}</span></div>`).join('')}</div>`;
}
function recycleConfigPanel(config){
  const rows = [
    ['路径', shortPath(config.dir || '-')],
    ['保留期', `${config.retention_hours ?? 24}h`],
    ['扫描清理', formatBool(config.purge_on_scan)],
    ['维护清理', formatBool(config.purge_on_agent_maintenance)],
  ];
  return `<div class="file-config-list">${rows.map(([label,value]) => `<div class="queue-row"><span>${esc(label)}</span><span class="queue-value">${esc(value)}</span></div>`).join('')}</div>`;
}
function recycleCategoryLabel(value){
  return ({mobile_audio_analysis:'手机音频分析', file_analysis:'文件分析', unknown:'未知'})[value] || value || '未知';
}
function formatDuration(ms){
  const totalMinutes = Math.max(0, Math.round(Number(ms || 0) / 60000));
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if(hours >= 24) return `${Math.floor(hours / 24)}天${hours % 24}小时`;
  if(hours > 0) return `${hours}小时${minutes}分`;
  return `${minutes}分`;
}
function restoreRecycle(trashPath, to=''){
  if(!trashPath) return toast('Missing trash path');
  action('recycle_restore',{trash_path:trashPath,to});
}
function mobileKindLabel(kind){
  return ({audio_segment:'录音片段', status:'状态', upload:'上传'})[kind] || kind || '手机事件';
}
function mobileAudioPanel(audio){
  const statuses = audio.statuses || {};
  const statusRows = Object.entries(statuses).sort(([,a],[,b]) => Number(b || 0) - Number(a || 0));
  return `<div>
    <div class="mobile-audio-grid">
      ${mobileAudioStat('总数', audio.total || 0)}
      ${mobileAudioStat('Pending', audio.pending || 0)}
      ${mobileAudioStat('Error', audio.errors || 0)}
    </div>
    <div class="mobile-storage-list" style="margin-top:10px">
      <div class="mobile-row"><span>Latest analyzed</span><span class="queue-value">${esc(shortDateTime(audio.latest_analyzed || '-'))}</span></div>
      ${statusRows.map(([key,count]) => `<div class="mobile-row"><span>${esc(key)}</span><span class="queue-value">${esc(count)}</span></div>`).join('')}
    </div>
  </div>`;
}
function mobileAudioStat(label, value){
  return `<div class="mobile-audio-stat"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div></div>`;
}
function mobileStoragePanel(storage){
  const rows = [
    ['Inbox files', storage.inbox_files || 0],
    ['Inbox size', bytes(storage.inbox_size || 0)],
    ['Import dirs', storage.import_dirs || 0],
    ['Imports size', bytes(storage.imports_size || 0)],
    ['Latest inbox', shortDateTime(storage.latest_inbox_at || '-')],
    ['Latest import', shortDateTime(storage.latest_import_at || '-')],
  ];
  return `<div class="mobile-storage-list">${rows.map(([label,value]) => `<div class="mobile-row"><span>${esc(label)}</span><span class="queue-value">${esc(value)}</span></div>`).join('')}</div>`;
}
function mobileCleanupPanel(cleanup){
  if(!cleanup) return '<div class="empty-state">No cleanup preview</div>';
  const rows = [
    ['删除文件', cleanup.deleted_files || 0],
    ['删除目录', cleanup.deleted_dirs || 0],
    ['可释放', bytes(cleanup.freed_bytes || 0)],
    ['保留 import', cleanup.retained_import_dirs || 0],
  ];
  return `<div class="mobile-cleanup-list">${rows.map(([label,value]) => `<div class="mobile-row"><span>${esc(label)}</span><span class="queue-value">${esc(value)}</span></div>`).join('')}</div>`;
}
function mobileFailureList(rows){
  if(!(rows || []).length) return '<div class="empty-state">No audio failures</div>';
  return `<div class="mobile-failure-list">${rows.map(row => `<div class="source-issue fail"><div class="source-issue-title">${esc(row.title || 'Audio failure')}</div><div class="source-issue-body">${esc(shortDateTime(row.observed_at || ''))} · ${esc(row.error || '')}</div></div>`).join('')}</div>`;
}
function mobileConfigPanel(config){
  const rows = [
    ['Host', config.host || '-'],
    ['Port', config.port || '-'],
    ['Max upload', `${config.max_upload_mb || '-'} MB`],
    ['Write reports', formatBool(config.write_reports)],
    ['Analyze after import', formatBool(config.analyze_after_import)],
    ['Delete uploads', formatBool(config.delete_uploads_after_import)],
    ['Delete analyzed audio', formatBool(config.delete_audio_after_analysis)],
  ];
  return `<div class="mobile-config-list">${rows.map(([label,value]) => `<div class="mobile-row"><span>${esc(label)}</span><span class="queue-value">${esc(value)}</span></div>`).join('')}</div>`;
}
async function sync(){
  setHeader('手机同步','读取中...', `<button class="btn" onclick="action('analyze_audio',{limit:20})">分析音频</button><button class="btn" onclick="action('install_sync_agent',{})">重载服务</button><button class="btn primary" onclick="sync()">刷新</button>`);
  const j=await api('/api/sync');
  const health = j.health || j.sync_health || {};
  const syncOk = !!j.mac_online && health.ok !== false && !health.error;
  const audio = j.audio || {};
  const storage = j.storage || {};
  const cleanup = j.cleanup_preview || {};
  const rows = j.recent_mobile || [];
  const shown = filterSyncEvents(rows);
  const lastObserved = j.last_mobile_observed_at || '-';
  const lastCaptured = j.last_mobile_captured_at || '-';
  $('subtitle').textContent = `${syncOk ? '在线' : '需检查'} · latest ${shortDateTime(lastCaptured)} · ${shown.length}/${rows.length} 条`;
  $('view').innerHTML = `
    <div class="sync-hero">
      <div class="card">
        <div class="section-title"><h3>连接与导入</h3>${status(syncOk?'ok':'warn')}</div>
        <div class="sync-kpis">
          ${syncKpi('Mac', syncOk ? '在线' : '需检查', syncEndpoint(j))}
          ${syncKpi('上次捕获', shortDateTime(lastCaptured), `observed ${shortDateTime(lastObserved)}`)}
          ${syncKpi('待导入', j.pending_server_import_files || 0, `${bytes(storage.inbox_size || 0)} inbox`)}
          ${syncKpi('音频分析', audio.complete ? '完成' : '待处理', `${audio.pending || 0} pending / ${audio.errors || 0} error`)}
        </div>
        ${syncFilterPills(rows)}
      </div>
      <div class="card">
        <div class="section-title"><h3>服务与操作</h3>${status(syncOk?'ok':'warn')}</div>
        <div class="sync-actions" style="margin-top:12px">
          <button class="btn primary" onclick="sync()">刷新</button>
          <button class="btn" onclick="action('analyze_audio',{limit:20})">分析音频</button>
          <button class="btn" onclick="action('install_sync_agent',{})">重载服务</button>
          <button class="btn" onclick="go('doctor')">Doctor</button>
        </div>
        <details class="compact-details" style="margin-top:12px">
          <summary>服务详情</summary>
          <div class="compact-details-body">${syncHealthPanel(j)}</div>
        </details>
      </div>
    </div>
    <div class="sync-main">
      <div>
        <div class="section-title"><h3>最近移动端记录</h3><span class="muted">${esc(shown.length)} shown</span></div>
        <div class="sync-toolbar">
          <input id="syncQ" value="${esc(state.syncQ)}" placeholder="搜索时间、设备、正文、source key" aria-label="sync search" onkeydown="syncSearchKey(event)">
          <button class="btn primary" onclick="applySyncSearch()">查找</button>
        </div>
        ${syncEventList(shown)}
      </div>
      <div class="sync-side">
        <div class="card">
          <div class="section-title"><h3>音频分析</h3>${status(audio.complete ? 'ok' : 'warn')}</div>
          ${mobileAudioPanel(audio)}
        </div>
        <details class="card compact-details">
          <summary>上传与导入缓存 · ${esc(bytes((storage.inbox_size || 0) + (storage.imports_size || 0)))}</summary>
          <div class="compact-details-body">${syncStoragePanel(storage)}</div>
        </details>
        <details class="card compact-details">
          <summary>清理预览 · ${esc(bytes(cleanup.freed_bytes || 0))}</summary>
          <div class="compact-details-body">
            ${syncCleanupPanel(cleanup)}
            <div class="sync-actions" style="margin-top:12px">
              <button class="btn" onclick="action('mobile_cleanup',{})">清理预览</button>
              <button class="btn danger" onclick="confirm('执行移动端缓存清理？') && action('mobile_cleanup',{apply:true})">执行清理</button>
            </div>
          </div>
        </details>
        ${(j.failures || []).length ? `<div class="card">
          <div class="section-title"><h3>失败原因</h3><span class="muted">${esc((j.failures || []).length)}</span></div>
          ${mobileFailureList(j.failures || [])}
        </div>` : ''}
        <details class="card compact-details">
          <summary>导入策略 · ${esc((j.config || {}).service_name || 'Wond')}</summary>
          <div class="compact-details-body">${syncConfigPanel(j.config || {})}</div>
        </details>
      </div>
    </div>`;
}
function applySyncSearch(){
  state.syncQ = $('syncQ').value;
  sync();
}
function syncSearchKey(event){
  if(event.key === 'Enter'){
    event.preventDefault();
    applySyncSearch();
  }
}
function setSyncView(value){
  state.syncView = value || 'all';
  sync();
}
function filterSyncEvents(rows){
  const q = String(state.syncQ || '').trim().toLowerCase();
  return (rows || []).filter(row => {
    if(!syncViewMatch(row, state.syncView)) return false;
    if(!q) return true;
    const haystack = [row.observed_at, row.captured_at, row.kind, row.title, row.subtitle, row.body, row.source_key, row.location].map(value => String(value || '').toLowerCase()).join(' ');
    return haystack.includes(q);
  });
}
function syncViewMatch(row, view){
  if(!view || view === 'all') return true;
  if(view === 'audio') return row.kind === 'audio_segment';
  if(view === 'watch') return syncIsWatch(row);
  if(view === 'iphone') return syncIsIphone(row);
  if(view === 'recent') return Date.now() - Date.parse(row.captured_at || row.observed_at || '') <= 24 * 60 * 60 * 1000;
  if(view === 'text') return Boolean(row.body || row.summary || row.snippet);
  return true;
}
function syncFilterPills(rows){
  const values = [
    ['all', '全部', (rows || []).length],
    ['audio', '录音', (rows || []).filter(row => row.kind === 'audio_segment').length],
    ['iphone', 'iPhone', (rows || []).filter(syncIsIphone).length],
    ['watch', 'Watch', (rows || []).filter(syncIsWatch).length],
    ['recent', '24小时', (rows || []).filter(row => syncViewMatch(row, 'recent')).length],
    ['text', '有正文', (rows || []).filter(row => row.body || row.summary || row.snippet).length],
  ];
  return `<div class="sync-filters">${values.map(([key,label,count]) => `<button class="filter-pill ${state.syncView===key?'active':''}" onclick="setSyncView('${escAttr(key)}')">${esc(label)} ${esc(count)}</button>`).join('')}</div>`;
}
function syncKpi(label, value, hint){
  const compact = String(value ?? '').length > 10;
  return `<div class="sync-kpi"><div class="label">${esc(label)}</div><div class="value ${compact?'compact':''}">${esc(value)}</div><div class="hint">${esc(hint || '')}</div></div>`;
}
function syncEndpoint(j){
  const health = j.health || {};
  const config = j.config || {};
  if(health.url) return health.url.replace('http://', '');
  return `port ${config.port || 8765}`;
}
function syncHealthPanel(j){
  const health = j.health || {};
  const config = j.config || {};
  const rows = [
    ['Service', health.service || config.service_name || '-'],
    ['Health', health.ok && !health.error ? 'OK' : (health.error || 'Issue')],
    ['URL', health.url || `http://127.0.0.1:${config.port || 8765}/health`],
    ['Host', config.host || '-'],
    ['Token', config.token ? 'configured' : 'empty'],
  ];
  return `<div class="sync-health-list">${rows.map(([label,value]) => `<div class="sync-row"><span>${esc(label)}</span><span class="queue-value">${esc(value)}</span></div>`).join('')}</div>`;
}
function syncEventList(rows){
  if(!(rows || []).length) return '<div class="empty-state">No mobile sync records match this filter</div>';
  return `<div class="sync-event-list">${rows.slice(0, 80).map(syncEventCard).join('')}</div>`;
}
function syncEventCard(row){
  const device = syncDeviceLabel(row);
  return `<div class="sync-event-card ${esc(syncEventClass(row))}">
    <div class="sync-time">${esc(shortDateTime(row.observed_at || ''))}${row.ended_at?`<br><span class="muted">${esc(shortDateTime(row.ended_at))}</span>`:''}</div>
    <div>${syncKindBadge(row)}<div class="item-meta" style="margin-top:6px">${esc(device)}</div></div>
    <div>
      <div class="sync-title">${esc(row.title || mobileKindLabel(row.kind))}</div>
      <div class="sync-meta"><span>${esc(row.source_key || row.kind || '')}</span><span>${esc(row.captured_at ? `captured ${shortDateTime(row.captured_at)}` : '')}</span></div>
      <div class="sync-body">${esc(row.body || row.location || row.subtitle || '')}</div>
    </div>
  </div>`;
}
function syncKindBadge(row){
  if(row.kind === 'audio_segment') return '<span class="status observation">录音</span>';
  return `<span class="status skipped">${esc(mobileKindLabel(row.kind))}</span>`;
}
function syncEventClass(row){
  if(syncIsWatch(row)) return 'watch';
  if(row.kind === 'audio_segment') return 'audio';
  return 'other';
}
function syncDeviceLabel(row){
  if(syncIsWatch(row)) return 'Apple Watch';
  if(syncIsIphone(row)) return 'iPhone';
  return row.subtitle || 'mobile';
}
function syncIsWatch(row){
  const text = `${row.subtitle || ''} ${row.source_key || ''}`.toLowerCase();
  return text.includes('watch');
}
function syncIsIphone(row){
  const text = `${row.subtitle || ''} ${row.source_key || ''}`.toLowerCase();
  return text.includes('iphone') || text.includes('ios-');
}
function syncStoragePanel(storage){
  return `<div>
    <div class="sync-storage-grid">
      ${syncStorageTile('Inbox files', storage.inbox_files || 0, bytes(storage.inbox_size || 0))}
      ${syncStorageTile('Import dirs', storage.import_dirs || 0, bytes(storage.imports_size || 0))}
      ${syncStorageTile('Retained', storage.retained_import_dirs || 0, 'import dirs')}
      ${syncStorageTile('Total', bytes((storage.inbox_size || 0) + (storage.imports_size || 0)), 'cache size')}
    </div>
  </div>`;
}
function syncStorageTile(label, value, hint){
  return `<div class="sync-storage-tile"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint || '')}</div></div>`;
}
function syncCleanupPanel(cleanup){
  if(!cleanup) return '<div class="empty-state">No cleanup preview</div>';
  const rows = [
    ['删除文件', cleanup.deleted_files || 0],
    ['删除目录', cleanup.deleted_dirs || 0],
    ['可释放', bytes(cleanup.freed_bytes || 0)],
    ['保留 import', cleanup.retained_import_dirs || 0],
  ];
  return `<div class="sync-cleanup-list">${rows.map(([label,value]) => `<div class="sync-row"><span>${esc(label)}</span><span class="queue-value">${esc(value)}</span></div>`).join('')}</div>`;
}
function syncConfigPanel(config){
  const rows = [
    ['Max upload', `${config.max_upload_mb || '-'} MB`],
    ['Skip existing', formatBool(config.skip_existing_uploads)],
    ['Write reports', formatBool(config.write_reports)],
    ['Analyze after import', formatBool(config.analyze_after_import)],
    ['Analyze limit', config.analyze_limit || '-'],
    ['Delete uploads', formatBool(config.delete_uploads_after_import)],
    ['Delete imports', formatBool(config.delete_unreferenced_imports)],
    ['Delete analyzed audio', formatBool(config.delete_audio_after_analysis)],
  ];
  return `<div class="sync-config-list">${rows.map(([label,value]) => `<div class="sync-row"><span>${esc(label)}</span><span class="queue-value">${esc(value)}</span></div>`).join('')}</div>`;
}
async function maintenance(){
  const buttons = `<button class="btn" onclick="action('retention',{date:'today'})">记录预览</button><button class="btn danger" onclick="confirm('按保留策略删除旧记录、旧运行日志和旧详细报告？') && action('retention',{date:'today',apply:true})">执行记录清理</button><button class="btn" onclick="action('mobile_cleanup',{})">缓存预览</button><button class="btn" onclick="action('recycle_purge',{})">回收箱预览</button><button class="btn primary" onclick="maintenance()">刷新</button>`;
  setHeader('记录维护','读取中...', buttons);
  const j=await api('/api/maintenance');
  const counts = j.counts || {};
  const retention = j.retention_preview || {};
  const mobile = j.mobile_cleanup_preview || {};
  const recycle = j.recycle_purge_preview || {};
  const logs = j.log_files || {};
  const db = j.database || {};
  const recordRows = Number(retention.deleted_observations || 0) + Number(retention.deleted_activity_samples || 0) + Number(retention.deleted_collector_runs || 0);
  const reclaimBytes = Number(mobile.freed_bytes || 0) + Number(recycle.freed_bytes || 0);
  $('subtitle').textContent = `${j.generated_at || ''} · preview ${recordRows} records · ${bytes(reclaimBytes)} cache/recycle`;
  $('view').innerHTML = `
    <div class="maintenance-hero">
      <section class="card">
        <div class="section-title"><h3>记录体量</h3><span class="muted">${esc(shortPath(db.path || ''))}</span></div>
        <div class="maintenance-kpis">
          ${maintenanceKpi('Observations', counts.observations || 0, '今天/时间线/来源/搜索')}
          ${maintenanceKpi('Activity samples', counts.activity_samples || 0, 'foreground app samples')}
          ${maintenanceKpi('Collector runs', counts.collector_runs || 0, '运行记录')}
          ${maintenanceKpi('Log files', logs.count || 0, bytes(logs.total_size || 0))}
        </div>
      </section>
      <section class="card">
        <div class="section-title"><h3>清理动作</h3><span class="muted">先预览，再执行</span></div>
        <div class="maintenance-action-grid">
          <button class="btn" onclick="action('retention',{date:'today'})">记录预览</button>
          <button class="btn danger" onclick="confirm('按保留策略删除旧记录、旧运行日志和旧详细报告？') && action('retention',{date:'today',apply:true})">执行记录清理</button>
          <button class="btn" onclick="action('mobile_cleanup',{})">缓存预览</button>
          <button class="btn danger" onclick="confirm('执行移动端缓存清理？') && action('mobile_cleanup',{apply:true})">执行缓存清理</button>
          <button class="btn" onclick="action('recycle_purge',{})">回收箱预览</button>
          <button class="btn danger" onclick="confirm('永久删除已到期的回收箱文件？') && action('recycle_purge',{apply:true})">清理回收箱</button>
        </div>
      </section>
    </div>
    <div class="maintenance-main">
      <div class="grid">
        <section class="card">
          <div class="section-title"><h3>按保留策略清理记录</h3><span class="muted">${esc(maintenanceRetentionMode(j.retention))}</span></div>
          ${maintenanceRetentionPanel(retention)}
        </section>
        <section class="card">
          <div class="section-title"><h3>缓存与回收箱</h3><span class="muted">${esc(bytes(reclaimBytes))}</span></div>
          ${maintenanceCachePanel(mobile, recycle)}
        </section>
        <section class="card">
          <div class="section-title"><h3>增长来源</h3><span class="muted">top source/kind</span></div>
          ${maintenanceSourcePanel(j.source_counts || [])}
        </section>
      </div>
      <div class="maintenance-side">
        <section class="card">
          <div class="section-title"><h3>数据库</h3><span class="muted">${esc(bytes(db.size || 0))}</span></div>
          ${maintenanceDbPanel(db, counts)}
        </section>
        <section class="card">
          <div class="section-title"><h3>日志文件</h3><span class="muted">${esc(bytes(logs.total_size || 0))}</span></div>
          ${maintenanceLogPanel(logs)}
        </section>
      </div>
    </div>`;
}
function maintenanceKpi(label, value, hint){
  const compact = String(value ?? '').length > 10;
  return `<div class="maintenance-kpi"><div class="label">${esc(label)}</div><div class="value ${compact?'compact':''}">${esc(value)}</div><div class="hint">${esc(hint || '')}</div></div>`;
}
function maintenanceRetentionMode(config){
  if(!config) return 'retention';
  return `raw ${config.raw_observations_days || '-'}d / runs ${config.collector_runs_days || '-'}d`;
}
function maintenanceRetentionPanel(preview){
  const rows = [
    ['Raw observations', preview.deleted_observations || 0, `before ${preview.observation_cutoff || '-'}`],
    ['Activity samples', preview.deleted_activity_samples || 0, `before ${preview.activity_cutoff || '-'}`],
    ['Collector runs', preview.deleted_collector_runs || 0, `before ${preview.collector_runs_cutoff || '-'}`],
    ['Detailed reports', preview.deleted_reports || 0, `before ${preview.reports_cutoff || '-'}`],
    ['Trimmed logs', preview.trimmed_logs || 0, 'oversized .log files'],
  ];
  const skipped = (preview.skipped_days || []).length;
  return `<div class="maintenance-list">
    ${rows.map(([label,value,hint]) => maintenanceLine(label, value, hint)).join('')}
    ${skipped ? maintenanceLine('Skipped days', skipped, 'missing daily summaries') : ''}
    <details class="settings-json">
      <summary>查看 retention dry-run 输出</summary>
      <pre class="settings-pre">${esc((preview.lines || []).join('\\n') || 'No retention preview')}</pre>
    </details>
  </div>`;
}
function maintenanceCachePanel(mobile, recycle){
  const rows = [
    ['Mobile cached files', mobile.deleted_files || 0, bytes(mobile.freed_bytes || 0)],
    ['Mobile import dirs', mobile.deleted_dirs || 0, `${mobile.retained_import_dirs || 0} retained`],
    ['Recycle files due', recycle.deleted_files || 0, bytes(recycle.freed_bytes || 0)],
    ['Recycle manifests', recycle.deleted_manifests || 0, `${recycle.deleted_dirs || 0} empty dirs`],
  ];
  return `<div class="maintenance-list">${rows.map(([label,value,hint]) => maintenanceLine(label, value, hint)).join('')}</div>`;
}
function maintenanceDbPanel(db, counts){
  const rows = [
    ['Path', shortPath(db.path || '-')],
    ['Size', bytes(db.size || 0)],
    ['Modified', shortDateTime(db.modified_at || '-')],
    ['Total rows', Number(counts.observations || 0) + Number(counts.activity_samples || 0) + Number(counts.collector_runs || 0)],
  ];
  return `<div class="maintenance-list">${rows.map(([label,value]) => maintenanceLine(label, value)).join('')}</div>`;
}
function maintenanceSourcePanel(rows){
  if(!(rows || []).length) return '<div class="empty-state">No source records</div>';
  return `<div class="maintenance-source-list">${rows.slice(0, 16).map(row => `<div class="maintenance-source-row"><div class="maintenance-source-title">${esc(row.source || '-')}/${esc(row.kind || '-')}</div><div class="item-meta">${esc(row.first || '-')} -> ${esc(row.last || '-')}</div><div class="queue-value">${esc(row.count || 0)}</div></div>`).join('')}</div>`;
}
function maintenanceLogPanel(logs){
  const files = logs.files || [];
  if(!files.length) return '<div class="empty-state">No log files</div>';
  return `<div class="maintenance-log-list">${files.map(file => `<div class="maintenance-log-row"><div class="maintenance-log-title">${esc(shortPath(file.path || '-'))}</div><div class="item-meta">${esc(shortDateTime(file.modified_at || '-'))}</div><div class="queue-value">${esc(bytes(file.size || 0))}</div></div>`).join('')}</div>`;
}
function maintenanceLine(label, value, hint=''){
  return `<div class="maintenance-line"><span>${esc(label)}</span><span><b>${esc(value)}</b>${hint?`<br><span class="muted">${esc(hint)}</span>`:''}</span></div>`;
}
async function settings(){
  const buttons = `<button class="btn" onclick="go('doctor')">Doctor</button><button class="btn" onclick="go('maintenance')">记录维护</button><button class="btn primary" onclick="settings()">刷新</button>`;
  setHeader('设置','读取中...', buttons);
  const j=await api('/api/settings');
  const cfg = j.settings || {};
  const editable = j.editable || [];
  const groups = settingsGroups(cfg);
  if(!groups.some(group => group.key === state.settingsGroup)) state.settingsGroup = groups[0]?.key || '';
  const selected = groups.find(group => group.key === state.settingsGroup) || groups[0];
  const shown = filterSettingsGroups(groups);
  const collectors = cfg.collectors || {};
  const collectorTotal = Object.keys(collectors).length;
  const collectorEnabled = Object.values(collectors).filter(Boolean).length;
  const provider = (cfg.ai_backend || {}).provider || 'local';
  const localAi = cfg.local_ai || {};
  const mobile = cfg.mobile_sync || {};
  const file = cfg.file_analysis || {};
  const audio = cfg.audio_analysis || {};
  const watchPaths = Array.isArray(cfg.watch_paths) ? cfg.watch_paths : [];
  setHeader('设置',`${editable.length} 项可直接调整；敏感字段已隐藏`, buttons);
  $('view').innerHTML = `
    <div class="settings-hero">
      <section class="card">
        <div class="section-title"><h3>配置总览</h3><span class="muted">${esc(shortPath(j.config_path || ''))}</span></div>
        <div class="settings-kpis">
          ${settingsKpi('采集器', `${collectorEnabled}/${collectorTotal || 0}`, '当前开启数量')}
          ${settingsKpi('AI provider', String(provider).toUpperCase(), localAi.text_model || localAi.model || '-')}
          ${settingsKpi('移动同步', mobile.enabled === false ? '关闭' : '开启', mobile.port ? `port ${mobile.port}` : '-')}
          ${settingsKpi('监控路径', watchPaths.length, watchPaths.map(shortPath).join(' / ') || '-')}
        </div>
        <div class="settings-chip-row">
          <span class="settings-chip">时区 ${esc(cfg.timezone || '-')}</span>
          <span class="settings-chip">文件分析 ${esc(formatBool(file.enabled !== false))}</span>
          <span class="settings-chip">分析后删除 ${esc(formatBool(file.delete_after_analysis))}</span>
          <span class="settings-chip">音频连续队列 ${esc(formatBool(audio.continuous_queue))}</span>
          <span class="settings-chip">Token ${esc(mobile.token || '-')}</span>
        </div>
      </section>
      ${settingsMaintenancePanel(cfg)}
    </div>
    <div class="settings-main">
      <section class="card">
        <div class="section-title"><h3>配置分组</h3><span id="settingsShownCount" class="muted">${shown.length} / ${groups.length} 组</span></div>
        <div class="settings-toolbar">
          <input id="settingsSearch" value="${escAttr(state.settingsQ)}" oninput="applySettingsSearch(this.value)" placeholder="筛选分组、字段或值">
          <button class="btn" onclick="state.settingsQ=''; settings()">All</button>
        </div>
        <div class="settings-group-grid">${settingsGroupGrid(groups)}</div>
        <div id="settingsEmpty" class="empty-state" style="${shown.length ? 'display:none' : ''}">没有匹配的配置分组</div>
      </section>
      <div class="settings-side">
        <section class="card">${settingsEditPanel(selected, cfg, editable)}</section>
        <details class="card compact-details">
          <summary>当前分组详情</summary>
          <div class="compact-details-body">${settingsDetailPanel(selected)}</div>
        </details>
        <details class="card compact-details">
          <summary>路径和安全</summary>
          <div class="compact-details-body">${settingsPathPanel(j, cfg)}</div>
        </details>
      </div>
    </div>`;
  applySettingsSearch(state.settingsQ);
}
function settingsKpi(label, value, hint){
  const compact = String(value ?? '').length > 12 ? ' compact' : '';
  return `<div class="settings-kpi"><div class="label">${esc(label)}</div><div class="value${compact}">${esc(value ?? '-')}</div><div class="hint">${esc(hint || '')}</div></div>`;
}
function settingsEditPanel(group, cfg, editable){
  if(!group) return '<div class="empty-state">No settings selected</div>';
  const fields = settingsEditableForGroup(group.key, editable);
  if(!fields.length){
    return `<div>
      <div class="section-title"><h3>可编辑设置</h3><span class="status disabled">只读</span></div>
      <div class="empty-state">这个分组暂时没有开放直接编辑。敏感字段和高风险命令类配置仍保留为只读。</div>
    </div>`;
  }
  return `<form id="settingsEditForm" onsubmit="saveSettingsGroup(event, '${escAttr(group.key)}')">
    <div class="section-title"><h3>可编辑设置</h3><span class="status ok">${esc(fields.length)} 项</span></div>
    <div class="settings-edit-list">${fields.map(field => settingsEditRow(field, cfg)).join('')}</div>
    <div class="settings-edit-actions">
      <button class="btn primary" type="submit">保存设置</button>
      <button class="btn" type="button" onclick="action('install_agent',{load:true})">重载 Agent</button>
      <button class="btn" type="button" onclick="action('install_sync_agent',{load:true})">重载同步服务</button>
      <button class="btn" type="button" onclick="action('install_dashboard_agent',{load:true})">重载 Dashboard</button>
    </div>
    <div class="settings-edit-note">保存会立即写入 config.json；后台采集或同步进程通常需要重载后才会使用新配置。</div>
  </form>`;
}
function settingsEditableForGroup(key, editable){
  return (editable || []).filter(field => field.group === key || field.key === key);
}
function settingsEditRow(field, cfg){
  const value = settingValueAt(cfg, field.path || []);
  const meta = settingsFieldMeta(field);
  return `<label class="settings-edit-row">
    <div class="settings-edit-label"><b>${esc(field.label || field.key)}</b><span>${esc(meta || field.key)}</span></div>
    <div class="settings-edit-control">${settingsEditControl(field, value)}</div>
  </label>`;
}
function settingsEditControl(field, value){
  const key = escAttr(field.key);
  const type = escAttr(field.type);
  const base = `data-setting-key="${key}" data-setting-type="${type}"`;
  const placeholder = field.placeholder ? ` placeholder="${escAttr(field.placeholder)}"` : '';
  if(field.type === 'bool'){
    return `<span class="settings-edit-toggle"><input ${base} type="checkbox" ${value ? 'checked' : ''}>${esc(value ? '开启' : '关闭')}</span>`;
  }
  if(field.type === 'choice'){
    const options = (field.options || []).map(option => `<option value="${escAttr(option)}" ${String(value ?? '')===String(option)?'selected':''}>${esc(option)}</option>`).join('');
    return `<select ${base}>${options}</select>`;
  }
  if(field.type === 'list_string'){
    const text = Array.isArray(value) ? value.join('\n') : String(value ?? '');
    const rows = Number(field.rows || 4);
    return `<textarea ${base} rows="${escAttr(rows)}"${placeholder}>${esc(text)}</textarea>`;
  }
  if(field.type === 'text'){
    const rows = Number(field.rows || 4);
    return `<textarea ${base} rows="${escAttr(rows)}"${placeholder}>${esc(value ?? '')}</textarea>`;
  }
  if(field.type === 'int' || field.type === 'float'){
    const step = field.type === 'int' ? '1' : 'any';
    const min = field.min !== undefined ? ` min="${escAttr(field.min)}"` : '';
    const max = field.max !== undefined ? ` max="${escAttr(field.max)}"` : '';
    return `<input ${base} type="number" step="${step}" value="${escAttr(value ?? '')}"${min}${max}${placeholder}>`;
  }
  return `<input ${base} value="${escAttr(value ?? '')}"${placeholder}>`;
}
function settingsFieldMeta(field){
  const parts = [field.key];
  if(field.min !== undefined || field.max !== undefined){
    const range = `${field.min !== undefined ? field.min : '-'}..${field.max !== undefined ? field.max : '-'}`;
    parts.push(range);
  }
  if(field.unit) parts.push(field.unit);
  return parts.join(' · ');
}
function settingValueAt(cfg, path){
  let current = cfg;
  for(const part of (path || [])){
    if(!current || typeof current !== 'object') return '';
    current = current[part];
  }
  return current;
}
async function saveSettingsGroup(event, groupKey){
  event.preventDefault();
  const form = event.currentTarget;
  const controls = Array.from(form.querySelectorAll('[data-setting-key]'));
  const updates = controls.map(control => ({key: control.dataset.settingKey, value: settingControlValue(control)}));
  const j = await api('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({updates})});
  toast(`OK settings\n${j.changed_count || 0} changed`);
  settings().catch(e => toast(String(e)));
}
function settingControlValue(control){
  if(control.dataset.settingType === 'bool') return control.checked;
  if(control.dataset.settingType === 'list_string') return control.value.split('\n').map(item => item.trim()).filter(Boolean);
  return control.value;
}
function settingsMaintenancePanel(cfg){
  const retention = cfg.retention || {};
  const recycle = cfg.recycle_bin || {};
  const mobile = cfg.mobile_sync || {};
  const rows = [
    ['长期保留', retention.enabled === false ? '关闭' : '按配置启用'],
    ['回收箱', recycle.enabled === false ? '关闭' : `保留 ${recycle.retention_hours || 24}h`],
    ['同步上传上限', mobile.max_upload_mb ? `${mobile.max_upload_mb} MB` : '-'],
    ['同步清理', formatBool(mobile.delete_unreferenced_imports)],
  ];
  return `<details class="card compact-details">
    <summary>维护动作</summary>
    <div class="compact-details-body">
    <div class="settings-action-grid">
      <button class="btn" onclick="action('retention',{date:'today'})">保留预览</button>
      <button class="btn danger" onclick="confirm('执行长期保留清理？') && action('retention',{date:'today',apply:true})">执行保留</button>
      <button class="btn" onclick="go('files')">文件</button>
      <button class="btn" onclick="go('sync')">手机同步</button>
      <button class="btn" onclick="go('maintenance')">记录维护</button>
      <button class="btn" onclick="go('recycle')">回收箱</button>
    </div>
    <div class="settings-row-list" style="margin-top:10px">${rows.map(([label,value]) => `<div class="settings-row"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div></div>`).join('')}</div>
    </div>
  </details>`;
}
function settingsGroups(cfg){
  const groups = [];
  const collectors = cfg.collectors || {};
  const collectorEntries = Object.entries(collectors);
  const collectorEnabled = collectorEntries.filter(([,enabled]) => !!enabled).length;
  const collectorOff = collectorEntries.filter(([,enabled]) => !enabled).map(([key]) => key);
  groups.push(settingsGroup('collectors', collectors, {
    label: '采集器',
    status: `${collectorEnabled}/${collectorEntries.length || 0} 开启`,
    statusClass: collectorEnabled ? 'ok' : 'warn',
    tone: collectorEnabled ? 'ok' : 'warn',
    summary: 'Mac 端数据来源开关，决定后台会采集哪些本机信号。',
    items: [['开启', `${collectorEnabled}/${collectorEntries.length || 0}`], ['关闭', collectorOff.join(', ') || '-']],
  }));
  groups.push(settingsGroup('ai_backend', cfg.ai_backend || {}, {
    label: 'AI 路由',
    status: (cfg.ai_backend || {}).provider || 'local',
    statusClass: 'info',
    summary: '决定分析和问答优先走本地模型还是外部 provider。',
    items: [['provider', (cfg.ai_backend || {}).provider || '-'], ['fallback', (cfg.ai_backend || {}).fallback_provider || '-']],
  }));
  groups.push(settingsGroup('local_ai', cfg.local_ai || {}, {
    label: '本地 AI',
    status: (cfg.ai_backend || {}).provider === 'local' ? '使用中' : '备用',
    statusClass: (cfg.ai_backend || {}).provider === 'local' ? 'ok' : 'info',
    tone: (cfg.ai_backend || {}).provider === 'local' ? 'ok' : '',
    summary: 'Ollama、转写后端和本地模型配置。',
    items: [['text_model', (cfg.local_ai || {}).text_model || '-'], ['vision_model', (cfg.local_ai || {}).vision_model || '-'], ['transcription', (cfg.local_ai || {}).transcription_backend || '-']],
  }));
  groups.push(settingsGroup('openai_analysis', cfg.openai_analysis || {}, {
    label: 'OpenAI 备用',
    status: (cfg.openai_analysis || {}).enabled ? '开启' : '关闭',
    statusClass: (cfg.openai_analysis || {}).enabled ? 'ok' : 'disabled',
    tone: (cfg.openai_analysis || {}).enabled ? 'ok' : 'disabled',
    summary: '外部 OpenAI 分析配置；敏感字段在这里不会明文显示。',
  }));
  groups.push(settingsGroup('audio_analysis', cfg.audio_analysis || {}, {
    label: '音频分析',
    status: (cfg.audio_analysis || {}).enabled === false ? '关闭' : '开启',
    statusClass: (cfg.audio_analysis || {}).enabled === false ? 'disabled' : 'ok',
    tone: (cfg.audio_analysis || {}).enabled === false ? 'disabled' : 'ok',
    summary: '移动录音转写、摘要、队列处理和音频清理策略。',
    items: [['continuous_queue', formatBool((cfg.audio_analysis || {}).continuous_queue)], ['summary_model', (cfg.audio_analysis || {}).summary_model || '-'], ['auto_limit', (cfg.audio_analysis || {}).auto_limit ?? '-']],
  }));
  groups.push(settingsGroup('audio_preprocessing', cfg.audio_preprocessing || {}, {
    label: '音频预处理',
    status: (cfg.audio_preprocessing || {}).enabled === false ? '关闭' : '开启',
    statusClass: (cfg.audio_preprocessing || {}).enabled === false ? 'disabled' : 'ok',
    tone: (cfg.audio_preprocessing || {}).enabled === false ? 'disabled' : 'ok',
    summary: 'ASR/diarization 前的人声增强、speaker sample 增强和重叠说话候选分离。',
    items: [['ASR', formatBool((cfg.audio_preprocessing || {}).asr_enabled)], ['Diarization', formatBool((cfg.audio_preprocessing || {}).diarization_enabled)], ['Overlap', (cfg.audio_preprocessing || {}).overlap_separation_backend || '-']],
  }));
  groups.push(settingsGroup('speaker_recognition', cfg.speaker_recognition || {}, {
    label: '说话人',
    status: (cfg.speaker_recognition || {}).enabled === false ? '关闭' : '开启',
    statusClass: (cfg.speaker_recognition || {}).enabled === false ? 'disabled' : 'ok',
    tone: (cfg.speaker_recognition || {}).enabled === false ? 'disabled' : 'ok',
    summary: '说话人聚类、样本和后续重命名合并的识别参数。',
  }));
  groups.push(settingsGroup('mobile_sync', cfg.mobile_sync || {}, {
    label: '手机同步',
    status: (cfg.mobile_sync || {}).enabled === false ? '关闭' : `port ${(cfg.mobile_sync || {}).port || '-'}`,
    statusClass: (cfg.mobile_sync || {}).enabled === false ? 'disabled' : 'ok',
    tone: (cfg.mobile_sync || {}).enabled === false ? 'disabled' : 'ok',
    summary: 'iPhone / Watch 上传入口、去重、导入后分析和缓存清理。',
    items: [['port', (cfg.mobile_sync || {}).port || '-'], ['token', (cfg.mobile_sync || {}).token || '-'], ['delete_uploads', formatBool((cfg.mobile_sync || {}).delete_uploads_after_import)]],
  }));
  groups.push(settingsGroup('file_analysis', cfg.file_analysis || {}, {
    label: '文件分析',
    status: (cfg.file_analysis || {}).enabled === false ? '关闭' : '开启',
    statusClass: (cfg.file_analysis || {}).enabled === false ? 'disabled' : 'ok',
    tone: (cfg.file_analysis || {}).enabled === false ? 'disabled' : 'ok',
    summary: '监控文件、分析副本、include/exclude 后缀和分析后移动策略。',
    items: [['copy_dir', (cfg.file_analysis || {}).analysis_copy_dir || '-'], ['delete_after_analysis', formatBool((cfg.file_analysis || {}).delete_after_analysis)], ['suffixes', Array.isArray((cfg.file_analysis || {}).include_suffixes) ? `${cfg.file_analysis.include_suffixes.length} 项` : '-']],
  }));
  groups.push(settingsGroup('recycle_bin', cfg.recycle_bin || {}, {
    label: '回收箱',
    status: (cfg.recycle_bin || {}).enabled === false ? '关闭' : '开启',
    statusClass: (cfg.recycle_bin || {}).enabled === false ? 'disabled' : 'ok',
    tone: (cfg.recycle_bin || {}).enabled === false ? 'disabled' : 'ok',
    summary: '分析后暂存文件的保留时间、清理和恢复边界。',
  }));
  groups.push(settingsGroup('retention', cfg.retention || {}, { label: '长期保留', summary: '日报、周报、月报和旧记录清理窗口。' }));
  groups.push(settingsGroup('email_reports', cfg.email_reports || {}, { label: '邮件报告', summary: '摘要邮件发送时间、SMTP 和 Keychain 配置。' }));
  groups.push(settingsGroup('watch_paths', cfg.watch_paths || [], {
    label: '监控路径',
    status: `${Array.isArray(cfg.watch_paths) ? cfg.watch_paths.length : 0} 条`,
    statusClass: Array.isArray(cfg.watch_paths) && cfg.watch_paths.length ? 'ok' : 'warn',
    tone: Array.isArray(cfg.watch_paths) && cfg.watch_paths.length ? 'ok' : 'warn',
    summary: '文件分析会扫描的桌面端目录。',
  }));
  groups.push(settingsGroup('browser_profiles', cfg.browser_profiles || {}, { label: '浏览器资料', summary: '浏览器历史或书签采集所需的 profile 路径。' }));
  groups.push(settingsGroup('limits', cfg.limits || {}, { label: '限制', summary: '单次采集、分析或导入的安全上限。' }));
  groups.push(settingsGroup('agent', cfg.agent || {}, { label: '后台 Agent', summary: 'LaunchAgent、采集频率和后台运行参数。' }));
  const known = new Set(groups.map(group => group.key));
  Object.keys(cfg || {}).sort().forEach(key => {
    if(!known.has(key)) groups.push(settingsGroup(key, cfg[key]));
  });
  return groups;
}
function settingsGroup(key, value, opts={}){
  return {
    key,
    value,
    label: opts.label || settingsGroupLabel(key),
    summary: opts.summary || settingsValueSummary(value),
    status: opts.status || settingsStatusText(value),
    statusClass: opts.statusClass || settingsStatusClass(value),
    tone: opts.tone ?? settingsTone(value),
    items: opts.items || settingsPreviewItems(value),
  };
}
function settingsGroupGrid(groups){
  const q = String(state.settingsQ || '').trim().toLowerCase();
  return (groups || []).map(group => {
    const hidden = q && !settingsGroupMatches(group, q);
    return `<button type="button" class="settings-group-card ${state.settingsGroup===group.key?'active':''} ${esc(group.tone || '')}" data-search="${escAttr(settingsSearchKey(group))}" ${hidden?'hidden':''} onclick="setSettingsGroup('${escAttr(group.key)}')">
      <div class="settings-group-head"><div class="settings-group-title">${esc(group.label)}</div>${settingsStatusBadge(group)}</div>
      <div class="settings-group-summary">${esc(group.summary || '')}</div>
      ${settingsMiniItems(group.items)}
    </button>`;
  }).join('');
}
function settingsMiniItems(items){
  const shown = (items || []).slice(0, 3);
  if(!shown.length) return '';
  return `<div class="settings-chip-row">${shown.map(([label,value]) => `<span class="settings-chip">${esc(label)}: ${esc(settingsValueShort(value, 34))}</span>`).join('')}</div>`;
}
function settingsStatusBadge(group){
  return `<span class="status ${esc(group.statusClass || 'info')}">${esc(group.status || '配置')}</span>`;
}
function settingsDetailPanel(group){
  if(!group) return '<div class="empty-state">No settings</div>';
  return `<div>
    <div class="section-title"><h3>${esc(group.label)}</h3>${settingsStatusBadge(group)}</div>
    <div class="settings-detail-summary">${esc(group.summary || '')}</div>
    <div class="settings-row-list">${settingsRows(group.value, 16)}</div>
    <details class="settings-json">
      <summary>查看该分组原始 JSON</summary>
      <pre class="settings-pre">${esc(JSON.stringify(group.value, null, 2))}</pre>
    </details>
  </div>`;
}
function settingsPathPanel(j, cfg){
  const file = cfg.file_analysis || {};
  const recycle = cfg.recycle_bin || {};
  const rows = [
    ['配置文件', j.config_path || '-'],
    ['数据目录', j.data_dir || '-'],
    ['监控路径', cfg.watch_paths || []],
    ['分析副本目录', file.analysis_copy_dir || '-'],
    ['回收箱目录', recycle.path || recycle.base_dir || '-'],
    ['脱敏状态', 'secret/token/key 已隐藏或显示为 configured'],
  ];
  return `<div>
    <div class="section-title"><h3>路径和安全</h3><span class="status ok">受控写入</span></div>
    <div class="settings-row-list">${rows.map(([label,value]) => `<div class="settings-row"><div class="label">${esc(label)}</div><div class="value">${settingsDisplayValue(value)}</div></div>`).join('')}</div>
  </div>`;
}
function settingsRows(value, maxRows=14){
  const entries = settingsEntries(value);
  if(!entries.length) return '<div class="empty-state">No settings in this group</div>';
  const shown = entries.slice(0, maxRows).map(([label,item]) => `<div class="settings-row"><div class="label">${esc(label)}</div><div class="value">${settingsDisplayValue(item)}</div></div>`).join('');
  const extra = entries.length > maxRows ? `<div class="settings-row"><div class="label">...</div><div class="value">${esc(entries.length - maxRows)} more fields</div></div>` : '';
  return shown + extra;
}
function settingsEntries(value){
  if(Array.isArray(value)) return value.map((item, index) => [`#${index + 1}`, item]);
  if(value && typeof value === 'object') return Object.entries(value);
  if(value === undefined || value === null || value === '') return [];
  return [['value', value]];
}
function settingsDisplayValue(value){
  if(Array.isArray(value)){
    if(!value.length) return '<span class="muted">-</span>';
    return `<div class="settings-chip-row" style="margin-top:0">${value.slice(0, 12).map(item => `<span class="settings-chip">${esc(settingsValueShort(item, 42))}</span>`).join('')}${value.length > 12 ? `<span class="settings-chip">+${esc(value.length - 12)}</span>` : ''}</div>`;
  }
  if(value && typeof value === 'object') return `<span class="muted">${Object.keys(value).length} fields</span>`;
  if(typeof value === 'boolean') return esc(formatBool(value));
  if(value === undefined || value === null || value === '') return '<span class="muted">-</span>';
  return esc(settingsValueShort(value, 160));
}
function settingsPreviewItems(value){
  return settingsEntries(value).slice(0, 3).map(([label,item]) => [label, settingsValueShort(item, 42)]);
}
function settingsStatusText(value){
  const enabled = settingsEnabled(value);
  if(enabled !== null) return formatBool(enabled);
  if(Array.isArray(value)) return `${value.length} 项`;
  if(value && typeof value === 'object') return `${Object.keys(value).length} 项`;
  if(typeof value === 'boolean') return formatBool(value);
  if(value === undefined || value === null || value === '') return '-';
  return settingsValueShort(value, 24);
}
function settingsStatusClass(value){
  const enabled = settingsEnabled(value);
  if(enabled === true) return 'ok';
  if(enabled === false) return 'disabled';
  if(Array.isArray(value)) return value.length ? 'ok' : 'disabled';
  if(value && typeof value === 'object') return Object.keys(value).length ? 'info' : 'disabled';
  if(typeof value === 'boolean') return value ? 'ok' : 'disabled';
  return value ? 'info' : 'disabled';
}
function settingsTone(value){
  const cls = settingsStatusClass(value);
  return cls === 'ok' || cls === 'warn' || cls === 'disabled' ? cls : '';
}
function settingsEnabled(value){
  if(value && typeof value === 'object' && !Array.isArray(value) && Object.prototype.hasOwnProperty.call(value, 'enabled')) return !!value.enabled;
  return null;
}
function settingsValueSummary(value){
  if(Array.isArray(value)) return value.length ? value.slice(0, 4).map(item => settingsValueShort(item, 28)).join(' / ') : '没有配置项';
  if(value && typeof value === 'object'){
    const keys = Object.keys(value);
    return keys.length ? keys.slice(0, 5).join(' / ') : '空配置';
  }
  if(typeof value === 'boolean') return formatBool(value);
  return settingsValueShort(value || '-', 80);
}
function settingsValueShort(value, limit=80){
  let text;
  if(Array.isArray(value)) text = value.length ? value.slice(0, 4).map(item => settingsValueShort(item, 24)).join(', ') : '-';
  else if(value && typeof value === 'object') text = `${Object.keys(value).length} fields`;
  else if(typeof value === 'boolean') text = formatBool(value);
  else text = String(value ?? '-');
  return text.length > limit ? `${text.slice(0, Math.max(0, limit - 3))}...` : text;
}
function settingsGroupLabel(key){
  return ({
    collectors:'采集器',
    agent:'后台 Agent',
    retention:'长期保留',
    email_reports:'邮件报告',
    file_analysis:'文件分析',
    recycle_bin:'回收箱',
    audio_analysis:'音频分析',
    speaker_recognition:'说话人',
    ai_backend:'AI 路由',
    local_ai:'本地 AI',
    openai_analysis:'OpenAI 备用',
    mobile_sync:'手机同步',
    watch_paths:'监控路径',
    browser_profiles:'浏览器资料',
    limits:'限制',
    data_dir:'数据目录',
    timezone:'时区',
  })[key] || key;
}
function settingsSearchKey(group){
  return [group.key, group.label, group.status, group.summary, JSON.stringify(group.value || '')].join(' ').toLowerCase();
}
function settingsGroupMatches(group, q){
  return settingsSearchKey(group).includes(String(q || '').toLowerCase());
}
function filterSettingsGroups(groups){
  const q = String(state.settingsQ || '').trim().toLowerCase();
  return q ? (groups || []).filter(group => settingsGroupMatches(group, q)) : (groups || []);
}
function applySettingsSearch(value){
  state.settingsQ = value || '';
  const q = String(state.settingsQ || '').trim().toLowerCase();
  const cards = Array.from(document.querySelectorAll('.settings-group-card'));
  let shown = 0;
  cards.forEach(card => {
    const hit = !q || String(card.dataset.search || '').includes(q);
    card.hidden = !hit;
    if(hit) shown += 1;
  });
  const count = $('settingsShownCount');
  if(count) count.textContent = `${shown} / ${cards.length} 组`;
  const empty = $('settingsEmpty');
  if(empty) empty.style.display = shown ? 'none' : '';
}
function setSettingsGroup(key){
  state.settingsGroup = key;
  settings().catch(e => toast(String(e)));
}
function runsTable(rows){ return `<div class="table-wrap"><table><thead><tr><th>Started</th><th>Collector</th><th>Status</th><th>Message</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.started_at)}</td><td>${esc(r.collector)}</td><td>${status(r.status)}</td><td>${esc(r.message||'')}</td></tr>`).join('')}</tbody></table></div>`; }
function sourceCountTable(rows){ return `<div class="table-wrap"><table><thead><tr><th>Source</th><th>Kind</th><th>Count</th><th>Latest</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.source||'')}</td><td>${esc(r.kind)}</td><td>${esc(r.count)}</td><td>${esc(r.last||'')}</td></tr>`).join('')}</tbody></table></div>`; }
function obsList(rows){ return `<div class="list">${(rows||[]).map(o=>`<div class="item"><div class="item-title">${esc(o.title||o.subtitle||o.kind||o.name)}</div><div class="item-meta">${esc(o.observed_at||o.modified_at||'')} · ${esc(o.source||o.category||'')}/${esc(o.kind||'')}</div><div>${esc(o.body||o.summary||o.snippet||'')}</div></div>`).join('') || '<div class="muted">No records</div>'}</div>`; }
function eventList(rows){
  return `<div class="day-list">${(rows||[]).map(eventCard).join('') || '<div class="empty-state">No records</div>'}</div>`;
}
function eventSections(rows){
  if(!(rows||[]).length) return '<div class="empty-state">No records</div>';
  const groups = {late: [], morning: [], afternoon: [], evening: [], night: []};
  (rows || []).forEach(event => groups[dayPartKey(event.time)].push(event));
  return ['late','morning','afternoon','evening','night']
    .filter(key => groups[key].length)
    .map(key => `<section class="day-section"><div class="day-section-header"><h3>${esc(dayPartLabel(key))}</h3><span class="muted">${groups[key].length} 条</span></div><div class="day-list">${groups[key].map(eventCard).join('')}</div></section>`)
    .join('');
}
function eventCard(e){
  return `<div class="day-event">
    <div class="event-time">${esc(shortTime(e.time))}${e.end?`<br><span class="muted">${esc(shortTime(e.end))}</span>`:''}</div>
    <div>${categoryBadge(e.category)}${e.status?`<div style="margin-top:6px">${status(e.status)}</div>`:''}</div>
    <div><div class="event-title">${esc(e.title||e.kind)}</div><div class="event-meta">${eventMeta(e).map(part=>`<span>${esc(part)}</span>`).join('')}</div>${e.body?`<div class="event-body">${esc(e.body)}</div>`:''}</div>
  </div>`;
}
function eventMeta(e){
  const parts = [];
  if(e.source || e.kind) parts.push(`${e.source || ''}/${e.kind || ''}`);
  if((e.speakers || []).length) parts.push((e.speakers || []).join(' · '));
  if(e.actor) parts.push(e.actor);
  if(e.location) parts.push(e.location);
  if(e.app && e.app !== e.title) parts.push(e.app);
  return parts;
}
function categoryBadge(value){ const key=String(value||'other'); return `<span class="category ${esc(key)}">${esc(categoryLabel(key))}</span>`; }
function categoryLabel(value){
  return ({all:'全部',app:'App',audio:'录音',file:'文件',files:'文件',chat:'聊天',location:'位置',reminder:'提醒',calendar:'日程',bookmark:'标记',mail:'邮件',web:'网页',feedback:'反馈',system:'系统',other:'其他'})[value] || value;
}
function feedbackLabel(value){ return ({important:'重要',unimportant:'不重要',wrong:'错了',correction:'纠正'})[value] || value; }
function shortTime(value){ const text=String(value||''); const idx=text.indexOf('T'); return idx>=0 ? text.slice(idx+1, idx+6) : text; }
function shortDateTime(value){
  const text = String(value || '');
  const idx = text.indexOf('T');
  if(idx < 0) return text;
  return `${text.slice(0, idx)} ${text.slice(idx + 1, idx + 6)}`;
}
function shortRange(first, last){
  if(!first) return '无事件';
  const start = shortTime(first);
  const end = shortTime(last || first);
  return start === end ? start : `${start} → ${end}`;
}
function minutesOfDay(value){
  const time = shortTime(value).slice(0, 5);
  const parts = time.split(':');
  if(parts.length < 2) return -1;
  const hour = Number(parts[0]);
  const minute = Number(parts[1]);
  if(!Number.isFinite(hour) || !Number.isFinite(minute)) return -1;
  return hour * 60 + minute;
}
function dayPartKey(value){
  const minutes = minutesOfDay(value);
  if(minutes < 0 || minutes < 6 * 60) return 'late';
  if(minutes < 12 * 60) return 'morning';
  if(minutes < 18 * 60) return 'afternoon';
  if(minutes < 22 * 60) return 'evening';
  return 'night';
}
function dayPartLabel(value){
  return ({late:'凌晨',morning:'上午',afternoon:'下午',evening:'晚上',night:'深夜'})[value] || value;
}
function failureList(rows){
  return `<div class="list">${(rows||[]).map(f=>`<div class="item"><div class="item-title">${esc(f.title||'Audio failure')}</div><div class="item-meta">${esc(f.observed_at||'')}</div><div>${esc(f.error||'')}</div></div>`).join('') || '<div class="muted">No failures</div>'}</div>`;
}
function simpleMobileList(rows){
  return `<div class="list">${(rows||[]).map(r=>`<div class="item"><div class="item-title">${esc(r.title||r.kind)}</div><div class="item-meta">${esc(r.observed_at||'')} · ${esc(r.kind||'')} · captured ${esc(r.captured_at||'')}</div></div>`).join('') || '<div class="muted">No mobile records</div>'}</div>`;
}
function reportList(rows){ return `<div class="list">${(rows||[]).map(r=>`<div class="item"><div class="item-title">${esc(r.name)}</div><div class="item-meta">${esc(r.category)} · ${esc(r.modified_at)}</div><div>${esc(r.snippet||'')}</div></div>`).join('') || '<div class="muted">No reports</div>'}</div>`; }
function semanticList(rows){ return `<div class="list">${(rows||[]).map(r=>`<div class="item"><div class="item-title">${esc(r.title||r.key)}</div><div class="item-meta">score ${esc(r.score)} · ${esc(r.observed_at||'')} · ${esc(r.source||'')}/${esc(r.kind||'')}</div><div>${esc(r.text||'')}</div></div>`).join('') || '<div class="muted">No semantic matches yet. Build the index or check Ollama.</div>'}</div>`; }
function shortPath(value){ const text=String(value||''); if(!text || text === '-') return '-'; const parts=text.split('/').filter(Boolean); return parts.slice(-2).join('/') || text; }
function bytes(n){ n=Number(n||0); const units=['B','KB','MB','GB']; let i=0; while(n>=1024&&i<units.length-1){n/=1024;i++;} return `${n.toFixed(i?1:0)} ${units[i]}`; }
function routeHash(){
  const raw = location.hash.slice(1);
  const hash = canonicalSection(raw);
  if(isKnownSection(hash)){
    if(raw !== hash) history.replaceState(null,'','#'+hash);
    if(state.section !== hash){
      state.section = hash;
      render().catch(e=>toast(String(e)));
    }
  }
}
window.addEventListener('hashchange', routeHash);
window.addEventListener('load',()=>{ const raw=location.hash.slice(1); const hash=canonicalSection(raw); if(isKnownSection(hash)){ state.section=hash; if(raw && raw !== hash) history.replaceState(null,'','#'+hash); } nav(); startButtonTips(); render().catch(e=>toast(String(e))); });
</script>
</body>
</html>"""
