from __future__ import annotations

import email
import heapq
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
from collections.abc import Callable
from datetime import datetime
from email.policy import default
from pathlib import Path
from typing import Any

from .config import Settings, project_root
from .store import ActivitySample, Observation
from .timeutil import (
    apple_epoch_to_datetime,
    chrome_time_to_datetime,
    from_timestamp,
    local_iso,
    parse_external_iso,
    safari_time_to_datetime,
    utc_iso,
)


Collector = Callable[[Settings, datetime, datetime], list[Observation]]


def collector_exception_message(name: str, exc: Exception) -> str:
    if isinstance(exc, subprocess.TimeoutExpired):
        return f"{name} timed out after {exc.timeout:g}s"
    return str(exc)


def is_collector_error_result(name: str, observations: list[Observation]) -> bool:
    if len(observations) != 1:
        return False
    observation = observations[0]
    if observation.source != "system" or observation.kind != "collector_error":
        return False
    return str((observation.metadata or {}).get("collector") or "") == name


def clean_text(value: Any, limit: int = 500) -> str | None:
    if value is None:
        return None
    text = str(value)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    return text[:limit]


def run_command(args: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def limit_int(settings: Settings, key: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(settings.limits.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def sample_foreground_app(settings: Settings) -> ActivitySample | None:
    if not settings.collectors.get("foreground_app", True):
        return None
    script = r'''
    tell application "System Events"
      set frontApp to first application process whose frontmost is true
      set appName to name of frontApp
      set bundleId to bundle identifier of frontApp
      set winTitle to ""
      try
        set winTitle to name of front window of frontApp
      end try
      return appName & tab & bundleId & tab & winTitle
    end tell
    '''
    proc = run_command(["osascript", "-e", script], timeout=10)
    if proc.returncode != 0:
        return None
    parts = proc.stdout.rstrip("\n").split("\t")
    app = parts[0] if parts else "Unknown"
    bundle_id = parts[1] if len(parts) > 1 else None
    title = parts[2] if len(parts) > 2 else None
    return ActivitySample(
        sampled_at=utc_iso(),
        app=app,
        window_title=clean_text(title, 300),
        bundle_id=clean_text(bundle_id, 200),
    )


def collect_calendar(settings: Settings, start: datetime, end: datetime) -> list[Observation]:
    if not settings.collectors.get("calendar", True):
        return []
    script = r'''
    ObjC.import("stdlib");
    function safe(value) {
      try {
        if (value === undefined || value === null) return "";
        return String(value()).replace(/\s+/g, " ").trim();
      } catch (e) {
        try {
          if (value === undefined || value === null) return "";
          return String(value).replace(/\s+/g, " ").trim();
        } catch (ignored) {
          return "";
        }
      }
    }
    function iso(value) {
      try {
        var d = value();
        if (!d) return "";
        return d.toISOString();
      } catch (e) {
        return "";
      }
    }
    var start = new Date($.getenv("PC_START_ISO"));
    var end = new Date($.getenv("PC_END_ISO"));
    var out = [];
    var app = Application("Calendar");
    var calendars = app.calendars();
    for (var i = 0; i < calendars.length; i++) {
      var cal = calendars[i];
      var events = [];
      try {
        events = cal.events.whose({
          _and: [
            { startDate: { _lessThan: end } },
            { endDate: { _greaterThan: start } }
          ]
        })();
      } catch (e) {
        try { events = cal.events(); } catch (ignored) { events = []; }
      }
      for (var j = 0; j < events.length; j++) {
        var ev = events[j];
        var startIso = iso(ev.startDate);
        var endIso = iso(ev.endDate);
        if (!startIso) continue;
        var sd = new Date(startIso);
        var ed = endIso ? new Date(endIso) : sd;
        if (sd >= end || ed <= start) continue;
        out.push({
          calendar: safe(cal.name),
          uid: safe(ev.uid) || safe(ev.id) || String(i) + "-" + String(j) + "-" + startIso,
          title: safe(ev.summary),
          location: safe(ev.location),
          start: startIso,
          end: endIso,
          notes: safe(ev.description)
        });
      }
    }
    JSON.stringify(out);
    '''
    env = os.environ.copy()
    env["PC_START_ISO"] = start.isoformat()
    env["PC_END_ISO"] = end.isoformat()
    proc = subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", script],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
        env=env,
    )
    if proc.returncode != 0:
        return []
    try:
        rows = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []
    observations: list[Observation] = []
    for row in rows:
        observed_at = parse_external_iso(row.get("start"), settings.timezone) or local_iso(start)
        ended_at = parse_external_iso(row.get("end"), settings.timezone)
        observations.append(
            Observation(
                source="calendar",
                kind="event",
                source_key=clean_text(row.get("uid"), 300) or f"calendar-{len(observations)}",
                observed_at=observed_at,
                ended_at=ended_at,
                title=clean_text(row.get("title"), 300),
                subtitle=clean_text(row.get("calendar"), 200),
                body=clean_text(row.get("notes"), 1000),
                location=clean_text(row.get("location"), 300),
                metadata={"calendar": row.get("calendar")},
            )
        )
    return observations


def collect_reminders(settings: Settings, start: datetime, end: datetime) -> list[Observation]:
    if not settings.collectors.get("reminders", True):
        return []
    discovery_timeout = limit_int(settings, "reminders_discovery_timeout_seconds", 8, minimum=2, maximum=60)
    per_list_timeout = limit_int(settings, "reminders_list_timeout_seconds", 8, minimum=2, maximum=60)
    max_lists = limit_int(settings, "reminders_max_lists", 60, minimum=1, maximum=500)
    max_items_per_list = limit_int(settings, "reminders_items_per_list", 300, minimum=1, maximum=5000)
    list_script = r'''
    ObjC.import("stdlib");
    function safe(value) {
      try {
        if (value === undefined || value === null) return "";
        return String(value()).replace(/\s+/g, " ").trim();
      } catch (e) {
        try {
          if (value === undefined || value === null) return "";
          return String(value).replace(/\s+/g, " ").trim();
        } catch (ignored) {
          return "";
        }
      }
    }
    var out = [];
    var app = Application("Reminders");
    var lists = app.lists();
    for (var i = 0; i < lists.length; i++) {
      var list = lists[i];
      out.push({
        index: i,
        id: safe(list.id) || String(i),
        name: safe(list.name) || "List " + String(i + 1)
      });
    }
    JSON.stringify(out);
    '''
    env = os.environ.copy()
    list_proc = subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", list_script],
        text=True,
        capture_output=True,
        timeout=discovery_timeout,
        check=False,
        env=env,
    )
    if list_proc.returncode != 0:
        return []
    try:
        lists = json.loads(list_proc.stdout)
    except json.JSONDecodeError:
        return []
    if not isinstance(lists, list):
        return []
    item_script = r'''
    ObjC.import("stdlib");
    function safe(value) {
      try {
        if (value === undefined || value === null) return "";
        return String(value()).replace(/\s+/g, " ").trim();
      } catch (e) {
        try {
          if (value === undefined || value === null) return "";
          return String(value).replace(/\s+/g, " ").trim();
        } catch (ignored) {
          return "";
        }
      }
    }
    function iso(value) {
      try {
        var d = value();
        if (!d) return "";
        return d.toISOString();
      } catch (e) {
        return "";
      }
    }
    var end = new Date($.getenv("PC_END_ISO"));
    var listIndex = parseInt($.getenv("PC_REMINDERS_LIST_INDEX"), 10);
    var maxItems = parseInt($.getenv("PC_REMINDERS_MAX_ITEMS"), 10);
    var out = [];
    var app = Application("Reminders");
    var lists = app.lists();
    if (!isNaN(listIndex) && listIndex >= 0 && listIndex < lists.length) {
      var list = lists[listIndex];
      var listName = safe(list.name);
      var reminders = [];
      try {
        reminders = list.reminders.whose({ completed: false })();
      } catch (e) {
        try { reminders = list.reminders(); } catch (ignored) { reminders = []; }
      }
      for (var j = 0; j < reminders.length; j++) {
        var item = reminders[j];
        var due = iso(item.dueDate);
        var completed = false;
        try { completed = Boolean(item.completed()); } catch (ignored) {}
        if (completed) continue;
        if (due && new Date(due) >= end) continue;
        out.push({
          list: listName,
          id: safe(item.id) || String(listIndex) + "-" + String(j),
          title: safe(item.name),
          body: safe(item.body),
          due: due,
          priority: safe(item.priority)
        });
        if (out.length >= maxItems) break;
      }
    }
    JSON.stringify(out);
    '''
    env["PC_END_ISO"] = end.isoformat()
    observations: list[Observation] = []
    failures: list[str] = []
    successful_lists = 0
    for raw_list in lists[:max_lists]:
        if not isinstance(raw_list, dict):
            continue
        list_index = raw_list.get("index")
        list_name = clean_text(raw_list.get("name"), 200) or f"List {list_index}"
        env["PC_REMINDERS_LIST_INDEX"] = str(list_index)
        env["PC_REMINDERS_MAX_ITEMS"] = str(max_items_per_list)
        try:
            proc = subprocess.run(
                ["osascript", "-l", "JavaScript", "-e", item_script],
                text=True,
                capture_output=True,
                timeout=per_list_timeout,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired:
            failures.append(f"{list_name} timed out after {per_list_timeout}s")
            continue
        if proc.returncode != 0:
            failures.append(f"{list_name} returned exit {proc.returncode}")
            continue
        try:
            rows = json.loads(proc.stdout)
        except json.JSONDecodeError:
            failures.append(f"{list_name} returned invalid JSON")
            continue
        if not isinstance(rows, list):
            failures.append(f"{list_name} returned unexpected JSON")
            continue
        successful_lists += 1
        for row in rows:
            if not isinstance(row, dict):
                continue
            due = parse_external_iso(row.get("due"), settings.timezone) or local_iso(start)
            observations.append(
                Observation(
                    source="reminders",
                    kind="task",
                    source_key=clean_text(row.get("id"), 300) or f"reminder-{len(observations)}",
                    observed_at=due,
                    title=clean_text(row.get("title"), 300),
                    subtitle=clean_text(row.get("list"), 200),
                    body=clean_text(row.get("body"), 1000),
                    metadata={"priority": row.get("priority"), "list": row.get("list")},
                )
            )
    if failures and successful_lists == 0:
        raise RuntimeError("; ".join(failures[:3]))
    return observations


def copy_sqlite(src: Path) -> Path | None:
    if not src.exists():
        return None
    tmp_dir = Path(tempfile.mkdtemp(prefix="wond-"))
    dst = tmp_dir / src.name
    try:
        shutil.copy2(src, dst)
        wal = src.with_name(src.name + "-wal")
        shm = src.with_name(src.name + "-shm")
        if wal.exists():
            shutil.copy2(wal, dst.with_name(dst.name + "-wal"))
        if shm.exists():
            shutil.copy2(shm, dst.with_name(dst.name + "-shm"))
        return dst
    except OSError:
        return None


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def chrome_profiles() -> list[tuple[str, Path]]:
    bases = [
        ("chrome", Path("~/Library/Application Support/Google/Chrome").expanduser()),
        ("brave", Path("~/Library/Application Support/BraveSoftware/Brave-Browser").expanduser()),
        ("edge", Path("~/Library/Application Support/Microsoft Edge").expanduser()),
    ]
    profiles: list[tuple[str, Path]] = []
    for browser, base in bases:
        if not base.exists():
            continue
        for profile in [base / "Default", *sorted(base.glob("Profile *"))]:
            history = profile / "History"
            if history.exists():
                profiles.append((f"{browser}:{profile.name}", history))
    return profiles


def collect_chromium_history(
    settings: Settings, start: datetime, end: datetime
) -> list[Observation]:
    enabled = settings.browser_profiles
    if not settings.collectors.get("browsers", True):
        return []
    observations: list[Observation] = []
    limit = settings.limits.get("browser_visits", 500)
    for profile_name, history_path in chrome_profiles():
        browser = profile_name.split(":", 1)[0]
        if not enabled.get(browser, True):
            continue
        copied = copy_sqlite(history_path)
        if not copied:
            continue
        try:
            conn = sqlite3.connect(copied)
            cur = conn.execute(
                """
                SELECT urls.url, urls.title, visits.visit_time, visits.from_visit
                FROM visits
                JOIN urls ON urls.id = visits.url
                WHERE visits.visit_time >= ? AND visits.visit_time < ?
                ORDER BY visits.visit_time DESC
                LIMIT ?
                """,
                (
                    int((start.timestamp() + 11_644_473_600) * 1_000_000),
                    int((end.timestamp() + 11_644_473_600) * 1_000_000),
                    limit,
                ),
            )
            for url, title, visit_time, from_visit in cur.fetchall():
                visited_at = chrome_time_to_datetime(int(visit_time), settings.timezone)
                observations.append(
                    Observation(
                        source="browser",
                        kind="web_visit",
                        source_key=f"{profile_name}:{visit_time}:{url}",
                        observed_at=local_iso(visited_at),
                        title=clean_text(title, 300) or clean_text(url, 300),
                        url=clean_text(url, 1000),
                        app=profile_name,
                        metadata={"from_visit": from_visit, "history_path": str(history_path)},
                    )
                )
            conn.close()
        except sqlite3.Error:
            continue
    return observations


def collect_safari_history(settings: Settings, start: datetime, end: datetime) -> list[Observation]:
    if not settings.collectors.get("browsers", True):
        return []
    if not settings.browser_profiles.get("safari", True):
        return []
    history_path = Path("~/Library/Safari/History.db").expanduser()
    copied = copy_sqlite(history_path)
    if not copied:
        return []
    observations: list[Observation] = []
    limit = settings.limits.get("browser_visits", 500)
    try:
        conn = sqlite3.connect(copied)
        cur = conn.execute(
            """
            SELECT history_items.url, history_visits.title, history_visits.visit_time
            FROM history_visits
            JOIN history_items ON history_items.id = history_visits.history_item
            WHERE history_visits.visit_time >= ? AND history_visits.visit_time < ?
            ORDER BY history_visits.visit_time DESC
            LIMIT ?
            """,
            (start.timestamp() - 978_307_200, end.timestamp() - 978_307_200, limit),
        )
        for url, title, visit_time in cur.fetchall():
            visited_at = safari_time_to_datetime(float(visit_time), settings.timezone)
            observations.append(
                Observation(
                    source="browser",
                    kind="web_visit",
                    source_key=f"safari:{visit_time}:{url}",
                    observed_at=local_iso(visited_at),
                    title=clean_text(title, 300) or clean_text(url, 300),
                    url=clean_text(url, 1000),
                    app="safari",
                    metadata={"history_path": str(history_path)},
                )
            )
        conn.close()
    except sqlite3.Error:
        return []
    return observations


def collect_browser_history(settings: Settings, start: datetime, end: datetime) -> list[Observation]:
    return collect_chromium_history(settings, start, end) + collect_safari_history(settings, start, end)


def collect_recent_files(settings: Settings, start: datetime, end: datetime) -> list[Observation]:
    if not settings.collectors.get("recent_files", True):
        return []
    limit = settings.limits.get("recent_files", 500)
    max_checked = int(settings.limits.get("recent_files_scan_files", 12000))
    max_seconds = float(settings.limits.get("recent_files_scan_seconds", 20))
    deadline = time.monotonic() + max_seconds if max_seconds > 0 else None
    observations: list[Observation] = []
    seen: set[Path] = set()
    checked = 0
    skipped_dirs = {
        ".git",
        ".cache",
        "node_modules",
        "__pycache__",
        ".venv",
        "Library",
        ".Trash",
        "mobile_sync",
        "speaker_samples",
        "recycle_bin",
        "build",
        "DerivedData",
    }
    skip_roots = [settings.data_dir.resolve(), project_root().resolve()]
    for root in settings.watch_paths:
        if not root.exists():
            continue
        resolved_root = root.resolve()
        if any(is_relative_to(resolved_root, skip_root) for skip_root in skip_roots):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            if deadline is not None and time.monotonic() >= deadline:
                return observations
            base = Path(dirpath)
            dirnames[:] = [
                d
                for d in dirnames
                if d not in skipped_dirs
                and not d.startswith(".")
                and not any(is_relative_to((base / d).resolve(), skip_root) for skip_root in skip_roots)
            ]
            for filename in filenames:
                checked += 1
                if checked > max_checked:
                    return observations
                if deadline is not None and time.monotonic() >= deadline:
                    return observations
                path = Path(dirpath) / filename
                if path in seen or filename.startswith("."):
                    continue
                seen.add(path)
                try:
                    stat = path.stat()
                except OSError:
                    continue
                modified = from_timestamp(stat.st_mtime, settings.timezone)
                if not (start <= modified < end):
                    continue
                observations.append(
                    Observation(
                        source="filesystem",
                        kind="file_modified",
                        source_key=str(path),
                        observed_at=local_iso(modified),
                        title=path.name,
                        subtitle=str(path.parent),
                        metadata={"size": stat.st_size, "path": str(path)},
                    )
                )
                if len(observations) >= limit:
                    return observations
    return observations


def collect_messages(settings: Settings, start: datetime, end: datetime) -> list[Observation]:
    if not settings.collectors.get("messages", True):
        return []
    db_path = Path("~/Library/Messages/chat.db").expanduser()
    copied = copy_sqlite(db_path)
    if not copied:
        return []
    observations: list[Observation] = []
    limit = settings.limits.get("messages", 300)
    try:
        conn = sqlite3.connect(copied)
        cur = conn.execute(
            """
            SELECT
                message.ROWID,
                message.guid,
                message.text,
                message.date,
                message.is_from_me,
                message.service,
                handle.id
            FROM message
            LEFT JOIN handle ON handle.ROWID = message.handle_id
            WHERE message.date IS NOT NULL
            ORDER BY message.date DESC
            LIMIT ?
            """,
            (limit * 4,),
        )
        for rowid, guid, text, raw_date, is_from_me, service, handle in cur.fetchall():
            if raw_date is None:
                continue
            msg_at = apple_epoch_to_datetime(raw_date, settings.timezone)
            if not (start <= msg_at < end):
                continue
            actor = "me" if is_from_me else clean_text(handle, 200)
            observations.append(
                Observation(
                    source="messages",
                    kind="message",
                    source_key=guid or f"message-{rowid}",
                    observed_at=local_iso(msg_at),
                    title=clean_text(text, 300) or "(attachment or rich message)",
                    actor=actor,
                    app=clean_text(service, 100),
                    metadata={"is_from_me": bool(is_from_me), "handle": handle},
                )
            )
            if len(observations) >= limit:
                break
        conn.close()
    except sqlite3.Error:
        return []
    return observations


def strip_emlx_prefix(raw: bytes) -> bytes:
    first_newline = raw.find(b"\n")
    if first_newline == -1:
        return raw
    first = raw[:first_newline].strip()
    if first.isdigit():
        return raw[first_newline + 1 :]
    return raw


def collect_apple_mail(settings: Settings, start: datetime, end: datetime) -> list[Observation]:
    if not settings.collectors.get("apple_mail", True):
        return []
    mail_root = Path("~/Library/Mail").expanduser()
    if not mail_root.exists():
        return []
    limit = settings.limits.get("mail_messages", 250)
    candidates: list[tuple[float, Path]] = []
    for path in mail_root.rglob("*.emlx"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if start.timestamp() <= mtime < end.timestamp():
            if len(candidates) < limit:
                heapq.heappush(candidates, (mtime, path))
            else:
                heapq.heappushpop(candidates, (mtime, path))
    candidates = sorted(candidates, reverse=True)
    observations: list[Observation] = []
    for mtime, path in candidates[:limit]:
        try:
            raw = strip_emlx_prefix(path.read_bytes())
            msg = email.message_from_bytes(raw, policy=default)
        except (OSError, ValueError):
            continue
        observed = from_timestamp(mtime, settings.timezone)
        subject = clean_text(msg.get("subject"), 300)
        sender = clean_text(msg.get("from"), 300)
        to = clean_text(msg.get("to"), 300)
        body_preview = None
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    try:
                        body_preview = clean_text(part.get_content(), 500)
                        break
                    except Exception:
                        continue
        else:
            try:
                body_preview = clean_text(msg.get_content(), 500)
            except Exception:
                body_preview = None
        observations.append(
            Observation(
                source="apple_mail",
                kind="email",
                source_key=str(path),
                observed_at=local_iso(observed),
                title=subject or "(no subject)",
                body=body_preview,
                actor=sender,
                metadata={"to": to, "path": str(path)},
            )
        )
    return observations


def collect_photo_locations(settings: Settings, start: datetime, end: datetime) -> list[Observation]:
    if not settings.collectors.get("photo_locations", True):
        return []
    roots = [
        Path("~/Pictures").expanduser(),
        Path("~/Desktop").expanduser(),
        Path("~/Downloads").expanduser(),
    ]
    extensions = {".jpg", ".jpeg", ".heic", ".png"}
    skip_dirs = {
        ".git",
        "node_modules",
        "__pycache__",
        "Photos Library.photoslibrary",
        "iPhoto Library.photolibrary",
        "Photo Booth Library",
    }
    limit = settings.limits.get("photo_locations", 150)
    max_checked = max(limit * 50, 3_000)
    checked = 0
    observations: list[Observation] = []
    for root in roots:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [name for name in dirnames if name not in skip_dirs and not name.startswith(".")]
            for filename in filenames:
                if Path(filename).suffix.lower() not in extensions:
                    continue
                checked += 1
                if checked > max_checked:
                    return observations
                image_path = Path(dirpath) / filename
                try:
                    stat = image_path.stat()
                except OSError:
                    continue
                modified = from_timestamp(stat.st_mtime, settings.timezone)
                if not (start <= modified < end):
                    continue
                proc = run_command(
                    [
                        "mdls",
                        "-raw",
                        "-name",
                        "kMDItemLatitude",
                        "-name",
                        "kMDItemLongitude",
                        "-name",
                        "kMDItemContentCreationDate",
                        str(image_path),
                    ],
                    timeout=10,
                )
                if proc.returncode != 0:
                    continue
                lines = [line.strip() for line in proc.stdout.splitlines()]
                if len(lines) < 2 or "(null)" in lines[:2]:
                    continue
                lat, lon = lines[0], lines[1]
                location = f"{lat},{lon}"
                observations.append(
                    Observation(
                        source="photos",
                        kind="photo_location",
                        source_key=str(image_path),
                        observed_at=local_iso(modified),
                        title=image_path.name,
                        subtitle=str(image_path.parent),
                        location=location,
                        metadata={"path": str(image_path), "latitude": lat, "longitude": lon},
                    )
                )
                if len(observations) >= limit:
                    return observations
    return observations


COLLECTORS: dict[str, Collector] = {
    "calendar": collect_calendar,
    "reminders": collect_reminders,
    "browsers": collect_browser_history,
    "recent_files": collect_recent_files,
    "messages": collect_messages,
    "apple_mail": collect_apple_mail,
    "photo_locations": collect_photo_locations,
}


def collect_all(settings: Settings, start: datetime, end: datetime) -> dict[str, list[Observation]]:
    result: dict[str, list[Observation]] = {}
    for name, collector in COLLECTORS.items():
        if not settings.collectors.get(name, True):
            continue
        try:
            result[name] = collector(settings, start, end)
        except Exception as exc:
            message = collector_exception_message(name, exc)
            result[name] = [
                Observation(
                    source="system",
                    kind="collector_error",
                    source_key=f"{name}:{start.date()}",
                    observed_at=utc_iso(),
                    title=f"{name} failed",
                    body=clean_text(message, 800),
                    metadata={"collector": name},
                )
            ]
    return result
