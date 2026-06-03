from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Settings, project_root
from .openai_analysis import analyze_paths_with_openai, analysis_source_name, file_source_key
from .recycle_bin import move_to_recycle_bin, purge_recycle_bin, recycle_bool
from .store import Store
from .timeutil import utc_iso


@dataclass(frozen=True)
class FileCandidate:
    path: Path
    changed_at: float
    mtime: float
    size: int


@dataclass
class AutoFileAnalysisResult:
    discovered: int = 0
    analyzed: int = 0
    skipped: int = 0
    failed: int = 0
    deleted: int = 0
    recycled: int = 0
    purged_from_recycle_bin: int = 0
    messages: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        return [
            f"Discovered: {self.discovered}",
            f"Analyzed: {self.analyzed}",
            f"Skipped: {self.skipped}",
            f"Failed: {self.failed}",
            f"Deleted: {self.deleted}",
            f"Recycled: {self.recycled}",
            f"Purged from recycle bin: {self.purged_from_recycle_bin}",
            *self.messages,
        ]


@dataclass(frozen=True)
class FileAnalysisLock:
    path: Path
    fd: int
    replaced_stale: bool = False


def file_analysis_bool(settings: Settings, key: str, default: bool) -> bool:
    value = settings.file_analysis.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def file_analysis_int(settings: Settings, key: str, default: int) -> int:
    try:
        return int(settings.file_analysis.get(key, default))
    except (TypeError, ValueError):
        return default


def suffixes(settings: Settings, key: str) -> set[str]:
    raw = settings.file_analysis.get(key, [])
    if isinstance(raw, str):
        values = [item.strip() for item in raw.split(",")]
    else:
        values = [str(item).strip() for item in raw]
    return {item.lower() if item.startswith(".") else f".{item.lower()}" for item in values if item}


def excluded_dir_names(settings: Settings) -> set[str]:
    raw = settings.file_analysis.get("exclude_dirs", [])
    if isinstance(raw, str):
        return {item.strip() for item in raw.split(",") if item.strip()}
    return {str(item).strip() for item in raw if str(item).strip()}


def state_path(settings: Settings) -> Path:
    return settings.data_dir / "file_analysis_state.json"


def lock_path(settings: Settings) -> Path:
    return settings.data_dir / "file_analysis.lock"


def analysis_copy_root(settings: Settings) -> Path:
    raw = str(settings.file_analysis.get("analysis_copy_dir") or "file_analysis_workspace")
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    return settings.data_dir / path


def load_state(settings: Settings) -> dict[str, Any]:
    path = state_path(settings)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(settings: Settings, state: dict[str, Any]) -> None:
    path = state_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def acquire_file_analysis_lock(settings: Settings, now_ts: float) -> FileAnalysisLock | None:
    path = lock_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    stale_seconds = max(60, file_analysis_int(settings, "lock_stale_seconds", 1800))
    replaced_stale = False
    for _attempt in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            payload = {
                "pid": os.getpid(),
                "acquired_at": utc_iso(),
            }
            os.write(fd, json.dumps(payload, sort_keys=True).encode("utf-8"))
            return FileAnalysisLock(path=path, fd=fd, replaced_stale=replaced_stale)
        except FileExistsError:
            try:
                stat = path.stat()
            except OSError:
                continue
            if now_ts - stat.st_mtime < stale_seconds:
                return None
            try:
                path.unlink()
                replaced_stale = True
            except OSError:
                return None
    return None


def release_file_analysis_lock(lock: FileAnalysisLock) -> None:
    try:
        os.close(lock.fd)
    except OSError:
        pass
    try:
        lock.path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def parse_state_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_failed_keys(raw: Any) -> dict[str, dict[str, Any]]:
    failed: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, dict):
        return failed
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        failed_at = parse_state_float(value.get("failed_at"))
        if failed_at is None:
            continue
        attempts = int(parse_state_float(value.get("attempts")) or 1)
        failed[str(key)] = {
            "failed_at": failed_at,
            "attempts": max(1, attempts),
            "error": str(value.get("error") or "")[:500],
        }
    return failed


def pruned_failed_keys(failed_keys: dict[str, dict[str, Any]], limit: int = 1000) -> dict[str, dict[str, Any]]:
    items = sorted(failed_keys.items(), key=lambda item: float(item[1].get("failed_at") or 0), reverse=True)[:limit]
    return dict(items)


def record_failed_key(failed_keys: dict[str, dict[str, Any]], source_key: str, now_ts: float, message: str) -> None:
    previous = failed_keys.get(source_key, {})
    attempts = int(parse_state_float(previous.get("attempts")) or 0) + 1
    failed_keys[source_key] = {
        "failed_at": now_ts,
        "attempts": attempts,
        "error": message[:500],
    }


def finish_stale_file_analysis_runs(settings: Settings, store: Store, now_ts: float) -> int:
    stale_seconds = max(60, file_analysis_int(settings, "run_stale_seconds", 3600))
    rows = store.conn.execute(
        """
        SELECT id, started_at
        FROM collector_runs
        WHERE collector = 'file_analysis'
          AND status = 'running'
        """
    ).fetchall()
    stale_count = 0
    for row in rows:
        try:
            started = datetime.fromisoformat(str(row["started_at"]))
        except (TypeError, ValueError):
            continue
        if now_ts - started.timestamp() < stale_seconds:
            continue
        store.finish_run(
            int(row["id"]),
            "error",
            f"Marked stale after {stale_seconds}s without completion.",
        )
        stale_count += 1
    return stale_count


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def changed_timestamp(stat: os.stat_result) -> float:
    values = [stat.st_mtime, stat.st_ctime]
    birth = getattr(stat, "st_birthtime", None)
    if birth is not None:
        values.append(float(birth))
    return max(values)


def should_skip_dir(path: Path, names: set[str], roots: list[Path]) -> bool:
    name = path.name
    if name in names or name.startswith("."):
        return True
    resolved = path.resolve()
    return any(is_relative_to(resolved, root) for root in roots)


def should_include_file(path: Path, include: set[str], exclude: set[str]) -> bool:
    name = path.name
    if name.startswith(".") or name.startswith("~$") or path.is_symlink():
        return False
    lower_name = name.lower()
    if any(lower_name.endswith(item) for item in exclude):
        return False
    if include and path.suffix.lower() not in include:
        return False
    return True


def discover_new_file_candidates(
    settings: Settings,
    *,
    watermark: float,
    now_ts: float,
) -> list[FileCandidate]:
    include = suffixes(settings, "include_suffixes")
    exclude = suffixes(settings, "exclude_suffixes")
    skip_names = excluded_dir_names(settings)
    skip_roots = [settings.data_dir.resolve(), project_root().resolve()]
    stability_seconds = file_analysis_int(settings, "stability_seconds", 30)
    candidates: list[FileCandidate] = []

    for root in settings.watch_paths:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            base = Path(dirpath)
            dirnames[:] = [
                name
                for name in dirnames
                if not should_skip_dir(base / name, skip_names, skip_roots)
            ]
            for filename in filenames:
                path = base / filename
                if not should_include_file(path, include, exclude):
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                changed_at = changed_timestamp(stat)
                if changed_at <= watermark:
                    continue
                if now_ts - changed_at < stability_seconds:
                    continue
                if not path.is_file():
                    continue
                candidates.append(
                    FileCandidate(
                        path=path.resolve(),
                        changed_at=changed_at,
                        mtime=stat.st_mtime,
                        size=stat.st_size,
                    )
                )
    candidates.sort(key=lambda item: (item.changed_at, str(item.path)))
    return candidates


def pruned_processed_keys(processed_keys: dict[str, float], limit: int = 5000) -> dict[str, float]:
    items = sorted(processed_keys.items(), key=lambda item: item[1], reverse=True)[:limit]
    return dict(items)


def mobile_sync_root(settings: Settings) -> Path:
    return (settings.data_dir / "mobile_sync").resolve()


def can_recycle_original(settings: Settings, path: Path) -> bool:
    return is_relative_to(path.expanduser().resolve(), mobile_sync_root(settings))


def analysis_copy_destination(settings: Settings, source: Path, now_ts: float) -> Path:
    now_dt = datetime.fromtimestamp(now_ts).astimezone()
    day_dir = analysis_copy_root(settings) / now_dt.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    stem = source.stem[:80] or "file"
    suffix = source.suffix[:20]
    stat = source.stat()
    digest = file_source_key(source, stat.st_mtime, stat.st_size)[:8]
    base = f"{now_dt.strftime('%H%M%S')}-{time.time_ns()}-{digest}-{stem}{suffix}"
    destination = day_dir / base
    counter = 1
    while destination.exists():
        destination = day_dir / f"{base}.{counter}"
        counter += 1
    return destination


def copy_for_analysis(settings: Settings, candidate: FileCandidate, now_ts: float) -> Path:
    destination = analysis_copy_destination(settings, candidate.path, now_ts)
    shutil.copy2(candidate.path, destination)
    return destination.resolve()


def initialize_state(settings: Settings, now_ts: float) -> dict[str, Any]:
    state = {
        "initialized_at": utc_iso(),
        "last_scan_ts": now_ts,
        "watermark": now_ts,
        "processed_keys": {},
    }
    save_state(settings, state)
    return state


def delete_processed_file(
    settings: Settings,
    result: AutoFileAnalysisResult,
    path: Path,
    *,
    original_path: Path | None = None,
    reason: str = "delete_after_analysis",
    category: str = "file_analysis",
) -> None:
    if original_path is None and not file_analysis_bool(settings, "delete_after_analysis", False):
        return
    try:
        if not path.exists():
            return
        if not path.is_file() or path.is_symlink():
            result.messages.append(f"- Not deleted because it is not a regular file: {path}")
            return
        metadata: dict[str, Any] = {"reason": reason}
        if original_path is not None:
            metadata["original_user_path"] = str(original_path)
            metadata["analysis_copy"] = True
        recycled = move_to_recycle_bin(
            settings,
            path,
            category=category,
            metadata=metadata,
        )
        if not recycled.moved:
            raise OSError(recycled.error or "recycle move failed")
        result.deleted += 1
        result.recycled += 1
        warning = f"; warning: {recycled.error}" if recycled.error else ""
        label = "processed analysis copy" if original_path is not None else "processed file"
        result.messages.append(
            f"- Moved {label} to recycle bin: {path} -> {recycled.trash_path} "
            f"(permanent delete after {recycled.delete_after}{warning})"
        )
    except OSError as exc:
        result.failed += 1
        result.messages.append(f"- Failed to recycle processed file {path}: {exc}")


def analyze_new_files(
    settings: Settings,
    store: Store,
    *,
    now_ts: float | None = None,
    force_scan: bool = False,
) -> AutoFileAnalysisResult:
    result = AutoFileAnalysisResult()
    if not file_analysis_bool(settings, "enabled", True):
        return result

    now_ts = now_ts if now_ts is not None else time.time()
    stale_runs = finish_stale_file_analysis_runs(settings, store, now_ts)
    lock = acquire_file_analysis_lock(settings, now_ts)
    if lock is None:
        result.skipped += 1
        if stale_runs:
            result.messages.append(f"- Marked {stale_runs} stale file_analysis run(s) as error.")
        result.messages.append(f"- Skipped file analysis because {lock_path(settings)} is held by another process.")
        return result
    try:
        result = _analyze_new_files_unlocked(settings, store, now_ts=now_ts, force_scan=force_scan)
        if stale_runs:
            result.messages.insert(0, f"- Marked {stale_runs} stale file_analysis run(s) as error.")
        if lock.replaced_stale:
            result.messages.insert(0, f"- Replaced stale file analysis lock: {lock.path}")
        return result
    finally:
        release_file_analysis_lock(lock)


def _analyze_new_files_unlocked(
    settings: Settings,
    store: Store,
    *,
    now_ts: float,
    force_scan: bool = False,
) -> AutoFileAnalysisResult:
    result = AutoFileAnalysisResult()
    if not file_analysis_bool(settings, "enabled", True):
        return result

    if recycle_bool(settings, "purge_on_scan", True):
        purge = purge_recycle_bin(settings, dry_run=False, now_ts=now_ts)
        result.purged_from_recycle_bin = purge.deleted_files
        if purge.deleted_files or purge.errors:
            result.messages.extend(f"- Recycle bin: {line}" for line in purge.lines(dry_run=False))

    state = load_state(settings)
    if "watermark" not in state:
        initialize_state(settings, now_ts)
        result.messages.append("Initialized new-file analysis watermark.")
        return result

    scan_interval = file_analysis_int(settings, "scan_interval_seconds", 60)
    last_scan = float(state.get("last_scan_ts") or 0)
    if not force_scan and now_ts - last_scan < scan_interval:
        return result

    watermark = float(state.get("watermark") or now_ts)
    processed_keys_raw = state.get("processed_keys", {})
    processed_keys: dict[str, float] = {}
    if isinstance(processed_keys_raw, dict):
        for key, value in processed_keys_raw.items():
            try:
                processed_keys[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
    failed_keys = load_failed_keys(state.get("failed_keys"))
    retry_after = max(0, file_analysis_int(settings, "retry_after_seconds", 3600))
    candidates = discover_new_file_candidates(settings, watermark=watermark, now_ts=now_ts)
    result.discovered = len(candidates)

    max_files = max(1, file_analysis_int(settings, "max_files_per_scan", 3))
    processed_this_scan = 0
    remaining_unprocessed = False

    for candidate in candidates:
        source_key = file_source_key(candidate.path, candidate.mtime, candidate.size)
        if source_key in processed_keys or store.observation_exists(
            analysis_source_name(settings),
            "media_analysis",
            source_key,
        ):
            result.skipped += 1
            processed_keys[source_key] = candidate.changed_at
            failed_keys.pop(source_key, None)
            if can_recycle_original(settings, candidate.path):
                delete_processed_file(settings, result, candidate.path)
            continue
        failed_entry = failed_keys.get(source_key)
        if failed_entry is not None:
            failed_at = float(failed_entry.get("failed_at") or 0)
            remaining = retry_after - (now_ts - failed_at)
            if remaining > 0:
                result.skipped += 1
                remaining_unprocessed = True
                result.messages.append(
                    f"- Skipped {candidate.path}: retry backoff active for {int(remaining)}s "
                    f"after {int(failed_entry.get('attempts') or 1)} failed attempt(s)."
                )
                continue
        if processed_this_scan >= max_files:
            remaining_unprocessed = True
            break

        run_id = store.start_run("file_analysis")
        processed_this_scan += 1
        analysis_path = candidate.path
        observation_paths: dict[Path, Path] | None = None
        copied_for_analysis = False
        try:
            if not can_recycle_original(settings, candidate.path):
                analysis_path = copy_for_analysis(settings, candidate, now_ts)
                observation_paths = {analysis_path: candidate.path}
                copied_for_analysis = True
                result.messages.append(f"- Copied for analysis: {candidate.path} -> {analysis_path}")
            file_result = analyze_paths_with_openai(
                settings,
                store,
                [analysis_path],
                observation_paths=observation_paths,
            )
        except Exception as exc:
            result.failed += 1
            message = f"Failed {candidate.path}: {exc}"
            result.messages.append(f"- {message}")
            if copied_for_analysis:
                delete_processed_file(
                    settings,
                    result,
                    analysis_path,
                    original_path=candidate.path,
                    reason="analysis_copy_after_error",
                    category="file_analysis_copy",
                )
            record_failed_key(failed_keys, source_key, now_ts, message)
            store.finish_run(run_id, "error", message[:1000])
            remaining_unprocessed = True
            continue

        result.analyzed += file_result.analyzed
        result.skipped += file_result.skipped
        result.failed += file_result.failed
        result.messages.extend(file_result.messages)

        if file_result.failed:
            message = "; ".join(file_result.messages) or f"Failed {candidate.path}"
            if copied_for_analysis:
                delete_processed_file(
                    settings,
                    result,
                    analysis_path,
                    original_path=candidate.path,
                    reason="analysis_copy_after_error",
                    category="file_analysis_copy",
                )
            record_failed_key(failed_keys, source_key, now_ts, message)
            store.finish_run(run_id, "error", message[:1000])
            remaining_unprocessed = True
        else:
            processed_keys[source_key] = candidate.changed_at
            failed_keys.pop(source_key, None)
            if copied_for_analysis:
                delete_processed_file(
                    settings,
                    result,
                    analysis_path,
                    original_path=candidate.path,
                    reason="analysis_copy_after_success",
                    category="file_analysis_copy",
                )
            elif can_recycle_original(settings, candidate.path):
                delete_processed_file(settings, result, candidate.path)
            store.finish_run(run_id, "ok", f"Analyzed {candidate.path}")

    if candidates and not remaining_unprocessed:
        watermark = max(watermark, max(candidate.changed_at for candidate in candidates))

    state["last_scan_ts"] = now_ts
    state["watermark"] = watermark
    state["processed_keys"] = pruned_processed_keys(processed_keys)
    state["failed_keys"] = pruned_failed_keys(failed_keys)
    save_state(settings, state)
    return result
