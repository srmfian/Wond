from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .config import Settings
from .timeutil import utc_iso


@dataclass(frozen=True)
class RecycleMoveResult:
    moved: bool
    original_path: str
    trash_path: str | None = None
    manifest_path: str | None = None
    delete_after: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class RecycleRestoreResult:
    restored: bool
    trash_path: str
    restored_path: str | None = None
    error: str | None = None


@dataclass
class RecyclePurgeResult:
    deleted_files: int = 0
    deleted_manifests: int = 0
    deleted_dirs: int = 0
    freed_bytes: int = 0
    retained_files: int = 0
    errors: list[str] = field(default_factory=list)
    dry_run_files: list[dict[str, Any]] = field(default_factory=list)

    def lines(self, *, dry_run: bool) -> list[str]:
        prefix = "Would delete" if dry_run else "Deleted"
        lines = [
            f"{prefix} files: {self.deleted_files}",
            f"{prefix} manifests: {self.deleted_manifests}",
            f"{prefix} empty dirs: {self.deleted_dirs}",
            f"{prefix} bytes: {self.freed_bytes}",
            f"Retained files: {self.retained_files}",
        ]
        lines.extend(f"- {error}" for error in self.errors)
        return lines


def recycle_bin_enabled(settings: Settings) -> bool:
    value = settings.recycle_bin.get("enabled", True)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def recycle_bin_retention_hours(settings: Settings) -> float:
    try:
        return max(0.0, float(settings.recycle_bin.get("retention_hours", 24)))
    except (TypeError, ValueError):
        return 24.0


def recycle_bin_path(settings: Settings) -> Path:
    raw = settings.recycle_bin.get("dir", "recycle_bin")
    path = Path(str(raw)).expanduser()
    if path.is_absolute():
        return path
    return settings.data_dir / path


def recycle_bin_config(settings: Settings) -> dict[str, Any]:
    root = recycle_bin_path(settings)
    return {
        "enabled": recycle_bin_enabled(settings),
        "dir": str(root),
        "retention_hours": recycle_bin_retention_hours(settings),
        "purge_on_scan": recycle_bool(settings, "purge_on_scan", True),
        "purge_on_agent_maintenance": recycle_bool(settings, "purge_on_agent_maintenance", True),
    }


def recycle_bool(settings: Settings, key: str, default: bool) -> bool:
    value = settings.recycle_bin.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def move_to_recycle_bin(
    settings: Settings,
    path: Path,
    *,
    category: str,
    metadata: dict[str, Any] | None = None,
    now_dt: datetime | None = None,
) -> RecycleMoveResult:
    original = path.expanduser()
    if not recycle_bin_enabled(settings):
        return RecycleMoveResult(moved=False, original_path=str(original), error="recycle_bin_disabled")
    if original.is_symlink():
        return RecycleMoveResult(moved=False, original_path=str(original), error="source_not_regular_file")
    try:
        resolved = original.resolve(strict=True)
    except FileNotFoundError:
        return RecycleMoveResult(moved=False, original_path=str(original), error="source_missing")
    except OSError as exc:
        return RecycleMoveResult(moved=False, original_path=str(original), error=str(exc))

    if not resolved.is_file():
        return RecycleMoveResult(moved=False, original_path=str(resolved), error="source_not_regular_file")

    now_dt = now_dt or datetime.now().astimezone()
    delete_after_dt = now_dt + timedelta(hours=recycle_bin_retention_hours(settings))
    root = recycle_bin_path(settings)
    day_dir = root / now_dt.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    destination = unique_destination(day_dir, resolved, now_dt)
    manifest = destination.with_name(destination.name + ".json")
    size = safe_size(resolved)
    stat = resolved.stat()
    payload = {
        "schema_version": 1,
        "category": category,
        "original_path": str(resolved),
        "trash_path": str(destination),
        "manifest_path": str(manifest),
        "moved_at": utc_iso(now_dt),
        "delete_after": utc_iso(delete_after_dt),
        "size": size,
        "mtime": stat.st_mtime,
        "metadata": metadata or {},
    }
    try:
        shutil.move(str(resolved), str(destination))
    except OSError as exc:
        return RecycleMoveResult(moved=False, original_path=str(resolved), trash_path=str(destination), error=str(exc))
    try:
        write_json(manifest, payload)
    except OSError as exc:
        return RecycleMoveResult(
            moved=True,
            original_path=str(resolved),
            trash_path=str(destination),
            delete_after=payload["delete_after"],
            error=f"manifest_write_failed: {exc}",
        )
    return RecycleMoveResult(
        moved=True,
        original_path=str(resolved),
        trash_path=str(destination),
        manifest_path=str(manifest),
        delete_after=payload["delete_after"],
    )


def list_recycle_bin(settings: Settings) -> list[dict[str, Any]]:
    root = recycle_bin_path(settings)
    if not root.exists():
        return []
    entries: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for manifest in root.rglob("*.json"):
        data = read_json(manifest)
        if not isinstance(data, dict):
            continue
        trash_path = Path(str(data.get("trash_path") or manifest.with_suffix("")))
        if not trash_path.is_absolute():
            trash_path = manifest.parent / trash_path
        if not is_inside(trash_path, root):
            continue
        if trash_path.exists() and trash_path.is_file():
            seen.add(trash_path.resolve())
            entries.append(entry_payload(settings, trash_path, manifest, data))
        else:
            entries.append(orphan_manifest_payload(settings, manifest, data))

    for file_path in root.rglob("*"):
        if not file_path.is_file() or file_path.suffix == ".json":
            continue
        resolved = file_path.resolve()
        if resolved in seen:
            continue
        entries.append(entry_payload(settings, file_path, None, {}))

    entries.sort(key=lambda item: str(item.get("moved_at") or ""), reverse=True)
    return entries


def recycle_bin_summary(settings: Settings, entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    items = entries if entries is not None else list_recycle_bin(settings)
    now_ts = time.time()
    files = [item for item in items if item.get("exists", True)]
    due = [item for item in files if parse_iso_ts(item.get("delete_after")) is not None and parse_iso_ts(item.get("delete_after")) <= now_ts]
    return {
        "files": len(files),
        "manifests": sum(1 for item in items if item.get("manifest_path")),
        "orphan_manifests": sum(1 for item in items if not item.get("exists", True)),
        "total_bytes": sum(int(item.get("size") or 0) for item in files),
        "due_files": len(due),
        "next_delete_after": min((item.get("delete_after") for item in files if item.get("delete_after")), default=None),
    }


def purge_recycle_bin(
    settings: Settings,
    *,
    dry_run: bool = True,
    now_ts: float | None = None,
) -> RecyclePurgeResult:
    root = recycle_bin_path(settings)
    result = RecyclePurgeResult()
    if not root.exists():
        return result
    now_ts = time.time() if now_ts is None else now_ts
    retention_seconds = recycle_bin_retention_hours(settings) * 3600

    for entry in list_recycle_bin(settings):
        trash_raw = entry.get("trash_path")
        manifest_raw = entry.get("manifest_path")
        trash_path = Path(str(trash_raw)) if trash_raw else None
        manifest_path = Path(str(manifest_raw)) if manifest_raw else None
        if trash_path is not None and not is_inside(trash_path, root):
            result.errors.append(f"Skipped path outside recycle bin: {trash_path}")
            continue

        due_ts = parse_iso_ts(entry.get("delete_after"))
        if due_ts is None:
            moved_ts = parse_iso_ts(entry.get("moved_at"))
            if moved_ts is not None:
                due_ts = moved_ts + retention_seconds
            elif trash_path is not None and trash_path.exists():
                due_ts = trash_path.stat().st_mtime + retention_seconds
            else:
                due_ts = now_ts

        if due_ts > now_ts:
            if trash_path is not None and trash_path.exists():
                result.retained_files += 1
            continue

        size = int(entry.get("size") or 0)
        if trash_path is not None and trash_path.exists():
            result.deleted_files += 1
            result.freed_bytes += size or safe_size(trash_path)
            result.dry_run_files.append(entry)
            if not dry_run:
                try:
                    trash_path.unlink()
                except OSError as exc:
                    result.errors.append(f"Failed to delete {trash_path}: {exc}")
        if manifest_path is not None and manifest_path.exists() and is_inside(manifest_path, root):
            result.deleted_manifests += 1
            if not dry_run:
                try:
                    manifest_path.unlink()
                except OSError as exc:
                    result.errors.append(f"Failed to delete manifest {manifest_path}: {exc}")

    if not dry_run:
        result.deleted_dirs += prune_empty_dirs(root)
    else:
        result.deleted_dirs = count_empty_dirs(root)
    return result


def restore_recycle_entry(
    settings: Settings,
    trash_path: Path,
    *,
    restore_path: Path | None = None,
) -> RecycleRestoreResult:
    root = recycle_bin_path(settings)
    try:
        trash = trash_path.expanduser().resolve(strict=True)
    except FileNotFoundError:
        return RecycleRestoreResult(restored=False, trash_path=str(trash_path), error="trash_file_missing")
    except OSError as exc:
        return RecycleRestoreResult(restored=False, trash_path=str(trash_path), error=str(exc))
    if not is_inside(trash, root) or not trash.is_file() or trash.is_symlink():
        return RecycleRestoreResult(restored=False, trash_path=str(trash), error="invalid_trash_path")

    manifest = trash.with_name(trash.name + ".json")
    data = read_json(manifest) if manifest.exists() else {}
    target = restore_path.expanduser() if restore_path else Path(str(data.get("original_path") or trash.name)).expanduser()
    if not target.is_absolute():
        target = settings.path.parent / target
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target = unique_restore_path(target)
    try:
        shutil.move(str(trash), str(target))
        if manifest.exists():
            manifest.unlink()
        prune_empty_dirs(root)
    except OSError as exc:
        return RecycleRestoreResult(restored=False, trash_path=str(trash), error=str(exc))
    return RecycleRestoreResult(restored=True, trash_path=str(trash), restored_path=str(target))


def unique_destination(directory: Path, source: Path, now_dt: datetime) -> Path:
    stem = source.stem[:80] or "file"
    suffix = source.suffix[:20]
    digest = hashlib.sha256(str(source).encode("utf-8", errors="replace")).hexdigest()[:8]
    base = f"{now_dt.strftime('%H%M%S')}-{time.time_ns()}-{digest}-{stem}{suffix}"
    destination = directory / base
    counter = 1
    while destination.exists() or destination.with_name(destination.name + ".json").exists():
        destination = directory / f"{base}.{counter}"
        counter += 1
    return destination


def unique_restore_path(target: Path) -> Path:
    stamp = datetime.now().astimezone().strftime("%Y%m%d%H%M%S")
    candidate = target.with_name(f"{target.stem}.restored-{stamp}{target.suffix}")
    counter = 1
    while candidate.exists():
        candidate = target.with_name(f"{target.stem}.restored-{stamp}-{counter}{target.suffix}")
        counter += 1
    return candidate


def entry_payload(settings: Settings, trash_path: Path, manifest: Path | None, data: dict[str, Any]) -> dict[str, Any]:
    moved_at = str(data.get("moved_at") or "")
    delete_after = str(data.get("delete_after") or "")
    if not delete_after:
        moved_ts = parse_iso_ts(moved_at) or trash_path.stat().st_mtime
        delete_after = utc_iso(datetime.fromtimestamp(moved_ts).astimezone() + timedelta(hours=recycle_bin_retention_hours(settings)))
    stat_size = safe_size(trash_path)
    return {
        "category": data.get("category") or "unknown",
        "original_path": data.get("original_path") or "",
        "trash_path": str(trash_path),
        "manifest_path": str(manifest) if manifest else None,
        "moved_at": moved_at or utc_iso(datetime.fromtimestamp(trash_path.stat().st_mtime).astimezone()),
        "delete_after": delete_after,
        "size": int(data.get("size") or stat_size),
        "exists": trash_path.exists(),
        "name": trash_path.name,
        "metadata": data.get("metadata") or {},
    }


def orphan_manifest_payload(settings: Settings, manifest: Path, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "category": data.get("category") or "unknown",
        "original_path": data.get("original_path") or "",
        "trash_path": data.get("trash_path") or "",
        "manifest_path": str(manifest),
        "moved_at": data.get("moved_at") or "",
        "delete_after": data.get("delete_after") or "",
        "size": int(data.get("size") or 0),
        "exists": False,
        "name": Path(str(data.get("trash_path") or manifest.name)).name,
    }


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def parse_iso_ts(value: Any) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def prune_empty_dirs(root: Path) -> int:
    deleted = 0
    for path in sorted((item for item in root.rglob("*") if item.is_dir()), key=lambda item: len(item.parts), reverse=True):
        try:
            path.rmdir()
            deleted += 1
        except OSError:
            continue
    return deleted


def count_empty_dirs(root: Path) -> int:
    count = 0
    for path in root.rglob("*"):
        if path.is_dir():
            try:
                next(path.iterdir())
            except StopIteration:
                count += 1
            except OSError:
                continue
    return count
