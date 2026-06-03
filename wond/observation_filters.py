from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable

from .config import Settings, project_root
from .store import json_dict


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolved_path(value: Any) -> Path | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return Path(os.path.abspath(Path(text).expanduser()))
    except (OSError, RuntimeError):
        return None


def row_value(row: Any, key: str) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return getattr(row, key, None)


def observation_metadata(row: Any) -> dict[str, Any]:
    return json_dict(row_value(row, "metadata"))


def project_owned_roots(settings: Settings) -> list[Path]:
    roots: list[Path] = []
    for value in (
        getattr(settings, "data_dir", None),
        getattr(settings, "summary_dir", None),
        getattr(settings, "report_dir", None),
        getattr(settings, "log_dir", None),
        getattr(settings, "recycle_bin_dir", None),
        getattr(settings, "speaker_sample_dir", None),
        project_root(),
    ):
        path = resolved_path(value)
        if path is not None and path not in roots:
            roots.append(path)
    return roots


def observation_file_path(row: Any) -> Path | None:
    metadata = observation_metadata(row)
    for raw in (
        metadata.get("path"),
        metadata.get("file_path"),
        metadata.get("resolved_media_path"),
        row_value(row, "source_key"),
    ):
        path = resolved_path(raw)
        if path is not None:
            return path
    subtitle = row_value(row, "subtitle")
    title = row_value(row, "title")
    if subtitle and title:
        return resolved_path(Path(str(subtitle)) / str(title))
    return None


def is_project_owned_path(settings: Settings, path: Path | None) -> bool:
    if path is None:
        return False
    return any(is_relative_to(path, root) for root in project_owned_roots(settings))


def is_internal_file_observation(settings: Settings, row: Any) -> bool:
    if row_value(row, "source") != "filesystem" or row_value(row, "kind") != "file_modified":
        return False
    return is_project_owned_path(settings, observation_file_path(row))


def visible_observations(settings: Settings, rows: Iterable[Any]) -> list[Any]:
    return [row for row in rows if not is_internal_file_observation(settings, row)]
