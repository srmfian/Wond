from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Settings
from .store import Observation, Store
from .timeutil import parse_external_iso


MOBILE_SOURCE = "mobile"


@dataclass
class MobileIngestResult:
    imported: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def ingest_mobile_export(settings: Settings, store: Store, path: Path) -> MobileIngestResult:
    result = MobileIngestResult()
    events = load_mobile_events(path)
    observations: list[Observation] = []
    base_dir = path.parent
    for index, event in enumerate(events):
        try:
            observations.append(event_to_observation(settings, event, index, base_dir))
        except ValueError as exc:
            result.skipped += 1
            result.errors.append(f"event {index}: {exc}")
    result.imported = store.upsert_observations(observations)
    return result


def load_mobile_events(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        raw_events = payload
    elif isinstance(payload, dict):
        raw_events = (
            payload.get("events")
            or payload.get("observations")
            or payload.get("records")
            or payload.get("items")
        )
        if raw_events is None:
            raw_events = [payload]
    else:
        raise ValueError("mobile export must be a JSON object or array")
    if not isinstance(raw_events, list):
        raise ValueError("mobile export event container must be an array")
    events: list[dict[str, Any]] = []
    for index, item in enumerate(raw_events):
        if not isinstance(item, dict):
            raise ValueError(f"event {index} must be a JSON object")
        events.append(item)
    return events


def event_to_observation(
    settings: Settings,
    event: dict[str, Any],
    index: int,
    base_dir: Path,
) -> Observation:
    kind = normalize_kind(text_value(event.get("kind") or event.get("type")) or "event")
    observed_at = parse_external_iso(
        text_value(event.get("observed_at") or event.get("started_at") or event.get("timestamp")),
        settings.timezone,
    )
    if not observed_at:
        raise ValueError("missing or invalid observed_at")
    ended_at = parse_external_iso(
        text_value(event.get("ended_at") or event.get("finished_at") or event.get("stopped_at")),
        settings.timezone,
    )
    metadata = build_metadata(event, base_dir)
    source_key = (
        text_value(event.get("source_key"))
        or text_value(event.get("id"))
        or stable_source_key(kind, observed_at, ended_at, metadata, index)
    )
    return Observation(
        source=MOBILE_SOURCE,
        kind=kind,
        source_key=source_key,
        observed_at=observed_at,
        ended_at=ended_at,
        title=title_for_event(kind, event),
        subtitle=text_value(event.get("device") or event.get("device_name")),
        body=body_for_event(event),
        url=text_value(event.get("media_url") or event.get("url")),
        location=location_label(event.get("location") or event),
        app=text_value(event.get("app")),
        metadata=metadata,
    )


def normalize_kind(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "audio": "audio_segment",
        "recording": "audio_segment",
        "audio_recording": "audio_segment",
        "voice": "audio_segment",
        "transcript": "transcript_segment",
        "location": "location_sample",
        "gps": "location_sample",
        "marker": "bookmark",
        "note": "bookmark",
        "quicktag": "quick_tag",
        "quick_tag": "quick_tag",
        "tag": "quick_tag",
    }
    return aliases.get(normalized, normalized)


def build_metadata(event: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    metadata = dict(event.get("metadata") or {})
    for key in (
        "duration_seconds",
        "media_path",
        "media_url",
        "sample_rate",
        "channels",
        "codec",
        "file_size",
        "battery_level",
        "recording_session_id",
        "tag",
        "source_ref",
        "related_event_id",
    ):
        if key in event and event[key] is not None:
            metadata[key] = event[key]
    if "location" in event:
        metadata["location"] = event["location"]
    else:
        location_keys = (
            "latitude",
            "longitude",
            "altitude",
            "horizontal_accuracy",
            "vertical_accuracy",
            "speed",
            "course",
            "address",
            "formatted_address",
            "place_name",
            "name",
            "locality",
            "administrative_area",
            "sub_administrative_area",
            "sub_locality",
            "thoroughfare",
            "sub_thoroughfare",
            "iso_country_code",
            "country",
        )
        location = {key: event[key] for key in location_keys if key in event and event[key] is not None}
        if location:
            metadata["location"] = location
    media_path = text_value(event.get("media_path"))
    if media_path:
        path = Path(media_path).expanduser()
        if not path.is_absolute():
            path = base_dir / path
        metadata["resolved_media_path"] = str(path.resolve())
    return metadata


def title_for_event(kind: str, event: dict[str, Any]) -> str:
    title = text_value(event.get("title"))
    if title:
        return title
    if kind == "audio_segment":
        return "Audio segment"
    if kind == "transcript_segment":
        return "Transcript segment"
    if kind == "location_sample":
        return "Location sample"
    if kind == "bookmark":
        return "Mobile bookmark"
    if kind == "quick_tag":
        tag = text_value(event.get("tag") or event.get("title"))
        return f"Quick tag: {tag}" if tag else "Quick tag"
    return "Mobile event"


def body_for_event(event: dict[str, Any]) -> str | None:
    return text_value(
        event.get("body")
        or event.get("transcript")
        or event.get("note")
        or event.get("notes"),
        limit=4000,
    )


def location_label(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("address", "formatted_address", "place_name", "name"):
            label = text_value(value.get(key))
            if label:
                return label
        component_label = location_component_label(value)
        if component_label:
            return component_label
        lat = value.get("latitude") or value.get("lat")
        lon = value.get("longitude") or value.get("lon") or value.get("lng")
        if lat is None or lon is None:
            return None
        label = f"{lat},{lon}"
        accuracy = value.get("horizontal_accuracy") or value.get("accuracy")
        if accuracy is not None:
            label += f" +/- {accuracy}m"
        return label
    lat = value.get("latitude") if hasattr(value, "get") else None
    lon = value.get("longitude") if hasattr(value, "get") else None
    if lat is not None and lon is not None:
        return f"{lat},{lon}"
    return None


def location_component_label(value: dict[str, Any]) -> str | None:
    country_code = text_value(value.get("iso_country_code") or value.get("country_code"))
    compact = country_code and country_code.upper() in {"CN", "HK", "JP", "MO", "TW"}
    keys = (
        "administrative_area",
        "sub_administrative_area",
        "locality",
        "sub_locality",
        "thoroughfare",
        "sub_thoroughfare",
    )
    parts: list[str] = []
    for key in keys:
        part = text_value(value.get(key))
        if not part or part in parts:
            continue
        if parts and part.startswith(parts[-1]):
            parts[-1] = part
            continue
        if parts and parts[-1].startswith(part):
            continue
        parts.append(part)
    if not parts:
        return None
    separator = "" if compact else ", "
    return text_value(separator.join(parts))


def stable_source_key(
    kind: str,
    observed_at: str,
    ended_at: str | None,
    metadata: dict[str, Any],
    index: int,
) -> str:
    raw = json.dumps(
        {
            "kind": kind,
            "observed_at": observed_at,
            "ended_at": ended_at,
            "media_path": metadata.get("media_path"),
            "resolved_media_path": metadata.get("resolved_media_path"),
            "location": metadata.get("location"),
            "index": index,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"{kind}-{digest}"


def text_value(value: Any, limit: int = 500) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:limit]
