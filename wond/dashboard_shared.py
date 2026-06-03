from __future__ import annotations

import json
import sqlite3
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Settings


def http_json(url: str, timeout: int = 2) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def http_json_or_error(url: str, timeout: int = 2) -> dict[str, Any]:
    try:
        payload = http_json(url, timeout=timeout)
        return payload if isinstance(payload, dict) else {"ok": False, "error": "non_object_response"}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "url": url}


def http_ok(url: str) -> bool:
    try:
        http_json(url, timeout=2)
        return True
    except Exception:
        return False


def scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def row_dict(row) -> dict[str, Any]:
    if row is None:
        return {}
    return {key: row[key] for key in row.keys()}


def row_payload(row, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = row_dict(row)
    if "metadata" in payload:
        payload["metadata"] = json_object(payload.get("metadata"))
    if "body" in payload:
        payload["body"] = compact(payload.get("body"), 1000)
    if extra:
        payload.update(extra)
    return payload


def json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        data = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "path": str(path)}
    try:
        return {"exists": True, "path": str(path), "data": json.loads(path.read_text(encoding="utf-8"))}
    except Exception as exc:
        return {"exists": True, "path": str(path), "error": str(exc)}


def redact_config(values: dict[str, Any]) -> dict[str, Any]:
    return redact_secrets(values)


def redact_secrets(value: Any, key_hint: str = "") -> Any:
    lower_key = key_hint.lower()
    sensitive = (
        "token" in lower_key
        or "password" in lower_key
        or "secret" in lower_key
        or lower_key in {"key", "api_key", "openai_api_key"}
        or lower_key.endswith("_api_key")
    )
    if sensitive:
        return "configured" if value else ""
    if isinstance(value, dict):
        return {str(key): redact_secrets(item, str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_secrets(item, key_hint) for item in value]
    return value


def report_file_payload(settings: Settings, path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": path.name,
        "path": str(path.relative_to(settings.path.parent)),
        "size": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
        "category": path.parent.name,
    }


def safe_report_path(settings: Settings, value: str) -> Path | None:
    base = settings.path.parent.resolve()
    path = Path(value)
    if not path.is_absolute():
        path = base / path
    try:
        resolved = path.resolve()
        resolved.relative_to(base)
    except ValueError:
        return None
    if resolved.suffix.lower() != ".md":
        return None
    return resolved


def compact(value: Any, limit: int = 220) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "."


def path_count(root: Path, pattern: str) -> int:
    return len(list(root.glob(pattern))) if root.exists() else 0


def latest_file(root: Path, pattern: str) -> str | None:
    if not root.exists():
        return None
    files = sorted(root.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    return str(files[0]) if files else None


def count_files(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(1 for path in root.rglob("*") if path.is_file() and not path.name.startswith("."))


def count_dirs(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(1 for path in root.iterdir() if path.is_dir() and not path.name.startswith("."))


def dir_size(root: Path) -> int:
    if not root.exists():
        return 0
    total = 0
    for path in root.rglob("*"):
        if path.is_file():
            try:
                total += path.stat().st_size
            except OSError:
                pass
    return total


def sync_health_url(settings: Settings) -> str:
    port = int(settings.mobile_sync.get("port", 8765))
    return f"http://127.0.0.1:{port}/health"


def search_keywords(term: str) -> list[str]:
    raw = " ".join(term.replace("？", " ").replace("?", " ").replace("，", " ").replace(",", " ").split())
    if not raw:
        return []
    tokens = [item for item in raw.split(" ") if len(item) >= 2]
    if len(raw) <= 24 and raw not in tokens:
        tokens.insert(0, raw)
    stopwords = {
        "what",
        "when",
        "where",
        "which",
        "about",
        "please",
        "今天",
        "昨天",
        "什么",
        "哪些",
        "有没有",
        "帮我",
    }
    unique: list[str] = []
    for token in tokens:
        normalized = token.strip()
        if not normalized or normalized.lower() in stopwords or normalized in unique:
            continue
        unique.append(normalized)
        if len(unique) >= 6:
            break
    return unique or [raw[:24]]


def parse_int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))
