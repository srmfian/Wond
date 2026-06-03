from __future__ import annotations

import json
import fcntl
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import Settings
from .executables import find_executable
from .audio_preprocessing import prepare_audio_for_stage
from .openai_analysis import (
    analyze_audio_with_openai,
    analysis_summary_key,
    is_no_speech_like_local_transcription_error,
    run_speaker_diarization,
    summarize_text,
    summary_prompt,
)
from .recycle_bin import move_to_recycle_bin
from .speakers import process_speakers_for_observation
from .store import Store
from .timeutil import day_bounds, local_iso, utc_iso


NO_SPEECH_TRANSCRIPT = "[No recognizable speech]"
NO_SPEECH_SUMMARY = "Audio was too short or contained no recognizable speech; no transcript was generated."


@dataclass
class AudioAnalysisResult:
    scanned: int = 0
    updated: int = 0
    skipped: int = 0
    missing: int = 0
    transcribed: int = 0
    failed: int = 0
    deleted: int = 0
    deleted_records: int = 0
    messages: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        return [
            f"Scanned: {self.scanned}",
            f"Updated: {self.updated}",
            f"Skipped: {self.skipped}",
            f"Missing files: {self.missing}",
            f"Transcribed: {self.transcribed}",
            f"Failed: {self.failed}",
            f"Deleted audio: {self.deleted}",
            f"Deleted records: {self.deleted_records}",
            *self.messages,
        ]


def analyze_audio_for_day(
    settings: Settings,
    store: Store,
    day: date,
    *,
    limit: int | None = None,
    force: bool = False,
) -> AudioAnalysisResult:
    lock = AudioAnalysisProcessLock(settings)
    if not lock.acquire():
        result = AudioAnalysisResult()
        result.messages.append("- Skipped: another audio analysis process is already running.")
        return result
    try:
        return analyze_audio_for_day_unlocked(settings, store, day, limit=limit, force=force)
    finally:
        lock.release()


def pending_audio_count_for_day(settings: Settings, store: Store, day: date) -> int:
    start, end = day_bounds(day, settings.timezone)
    rows = store.mobile_audio_between(local_iso(start), local_iso(end))
    pending = 0
    for row in rows:
        metadata = row_metadata(row)
        prior_analysis = metadata.get("audio_analysis") if isinstance(metadata.get("audio_analysis"), dict) else {}
        retryable_error = audio_analysis_needs_retry(prior_analysis)
        if prior_analysis.get("status") in {"missing_file", "missing_media_path"}:
            if should_delete_missing_audio_record(settings, row, metadata):
                pending += 1
            continue
        if existing_summary(prior_analysis) and (row["body"] or prior_analysis.get("transcript_status") == "no_speech"):
            if (
                not retryable_error
                and not needs_speaker_registry(settings, prior_analysis)
                and not needs_processed_audio_cleanup(settings, metadata)
            ):
                continue
        media_path = resolve_media_path(metadata)
        if media_path is not None and media_path.exists():
            pending += 1
        elif should_delete_missing_audio_record(settings, row, metadata):
            pending += 1
    return pending


def analyze_audio_for_day_unlocked(
    settings: Settings,
    store: Store,
    day: date,
    *,
    limit: int | None = None,
    force: bool = False,
) -> AudioAnalysisResult:
    start, end = day_bounds(day, settings.timezone)
    rows = store.mobile_audio_between(local_iso(start), local_iso(end))
    result = AudioAnalysisResult(scanned=len(rows))
    max_segments = limit if limit is not None else int(settings.audio_analysis.get("max_segments", 20))

    for row in rows:
        if result.updated >= max_segments:
            result.skipped += 1
            continue
        metadata = row_metadata(row)
        prior_analysis = metadata.get("audio_analysis") if isinstance(metadata.get("audio_analysis"), dict) else {}
        retryable_error = audio_analysis_needs_retry(prior_analysis)
        needs_speaker_processing = needs_speaker_registry(settings, prior_analysis)
        cleanup_only = (
            needs_processed_audio_cleanup(settings, metadata)
            and existing_summary(prior_analysis)
            and not needs_speaker_processing
            and not force
        )
        if prior_analysis.get("status") in {"missing_file", "missing_media_path"} and not force:
            if should_delete_missing_audio_record(settings, row, metadata):
                store.delete_observations([int(row["id"])])
                result.deleted_records += 1
                result.messages.append(f"- Deleted missing audio record: {row['source_key']}")
                continue
            result.skipped += 1
            continue
        if (
            existing_summary(prior_analysis)
            and not force
            and row["body"]
            and not retryable_error
            and not needs_speaker_processing
            and not cleanup_only
        ):
            result.skipped += 1
            continue

        media_path = resolve_media_path(metadata)
        analysis: dict[str, Any] = dict(prior_analysis)
        analysis["analyzed_at"] = utc_iso()

        if media_path is None:
            analysis["status"] = "missing_media_path"
            analysis.pop("error", None)
            metadata["audio_analysis"] = analysis
            if should_delete_missing_audio_record(settings, row, metadata):
                store.delete_observations([int(row["id"])])
                result.deleted_records += 1
                result.messages.append(f"- Deleted missing audio record: {row['source_key']}")
                continue
            store.update_observation_analysis(int(row["id"]), row["body"], metadata)
            result.missing += 1
            result.updated += 1
            result.messages.append(f"- Missing media_path: {row['source_key']}")
            continue

        if not media_path.exists():
            analysis["status"] = "missing_file"
            analysis["resolved_media_path"] = str(media_path)
            analysis.pop("error", None)
            metadata["audio_analysis"] = analysis
            if should_delete_missing_audio_record(settings, row, metadata):
                store.delete_observations([int(row["id"])])
                result.deleted_records += 1
                result.messages.append(f"- Deleted missing audio record: {row['source_key']}")
                continue
            store.update_observation_analysis(int(row["id"]), row["body"], metadata)
            result.missing += 1
            result.updated += 1
            result.messages.append(f"- Missing file: {media_path}")
            continue

        try:
            info = probe_audio(media_path)
            analysis.update(info)
            analysis["status"] = "ok"
            analysis["resolved_media_path"] = str(media_path)
            analysis.pop("error", None)
            transcript = row["body"]
            if cleanup_only:
                analysis["transcript_status"] = analysis.get("transcript_status") or "existing_transcript"
            elif needs_speaker_processing and not force and transcript:
                analysis["transcript_status"] = analysis.get("transcript_status") or "existing_transcript"
                maybe_run_speaker_diarization_repair(settings, media_path, analysis)
            elif force or retryable_error or not transcript:
                try:
                    openai_audio = analyze_audio_with_openai(settings, media_path)
                    transcript = openai_audio.transcript
                    analysis.update(openai_audio.metadata)
                    analysis[analysis_summary_key(settings)] = openai_audio.summary
                    analysis["summary"] = openai_audio.summary
                    analysis["transcript_status"] = analysis_summary_key(settings).replace("_summary", "")
                    if transcript:
                        result.transcribed += 1
                except Exception as exc:
                    if not is_no_speech_transcription_error(exc):
                        raise
                    transcript = NO_SPEECH_TRANSCRIPT
                    analysis[analysis_summary_key(settings)] = NO_SPEECH_SUMMARY
                    analysis["summary"] = NO_SPEECH_SUMMARY
                    analysis["transcript_status"] = "no_speech"
                    analysis["transcription_error"] = str(exc)
            elif transcript:
                summary = summarize_text(
                    settings,
                    transcript,
                    prompt=summary_prompt(settings),
                    label=f"Audio segment: {row['source_key']}",
                )
                analysis[analysis_summary_key(settings)] = summary
                analysis["summary"] = summary
                analysis["transcript_status"] = "existing_transcript"
            else:
                analysis["transcript_status"] = "empty"
            metadata["audio_analysis"] = analysis
            if not cleanup_only:
                metadata = process_speakers_for_observation(
                    settings,
                    store,
                    observation_id=int(row["id"]),
                    source_key=str(row["source_key"]),
                    media_path=media_path,
                    metadata=metadata,
                )
            deleted, delete_message = delete_processed_mobile_audio(settings, metadata, media_path)
            if deleted:
                result.deleted += 1
            if delete_message:
                result.messages.append(f"- {delete_message}")
            store.update_observation_analysis(int(row["id"]), transcript, metadata)
            result.updated += 1
        except Exception as exc:
            analysis["status"] = "error"
            analysis["error"] = str(exc)
            analysis["resolved_media_path"] = str(media_path)
            metadata["audio_analysis"] = analysis
            store.update_observation_analysis(int(row["id"]), row["body"], metadata)
            result.failed += 1
            result.updated += 1
            result.messages.append(f"- Failed {media_path}: {exc}")

    return result


def is_no_speech_transcription_error(exc: Exception) -> bool:
    text = str(exc)
    marker = "; fallback transcription failed:"
    if marker in text:
        primary, fallback = text.split(marker, 1)
        return is_no_speech_transcription_text(primary) and is_no_speech_transcription_text(fallback)
    return is_no_speech_transcription_text(text)


def is_no_speech_transcription_text(text: str) -> bool:
    return (
        "Spatial dimensions of input after padding cannot be smaller than weight spatial dimensions" in text
        or is_no_speech_like_local_transcription_error(RuntimeError(text))
        or "no recognizable speech" in text.lower()
        or "no speech" in text.lower()
    )


class AudioAnalysisProcessLock:
    def __init__(self, settings: Settings) -> None:
        self.path = settings.data_dir / "audio_analysis.lock"
        self.handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("w")
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.handle.close()
            self.handle = None
            return False
        self.handle.write(utc_iso())
        self.handle.flush()
        return True

    def release(self) -> None:
        if self.handle is None:
            return
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


def delete_processed_mobile_audio(
    settings: Settings,
    metadata: dict[str, Any],
    media_path: Path,
) -> tuple[bool, str | None]:
    if not mobile_sync_bool(settings, "delete_audio_after_analysis", False):
        return False, None
    defer_reason = processed_audio_delete_defer_reason(settings, metadata)
    if defer_reason is not None:
        cleanup = metadata.setdefault("cleanup", {})
        if isinstance(cleanup, dict):
            cleanup["delete_audio_deferred"] = defer_reason
        analysis = metadata.get("audio_analysis")
        if isinstance(analysis, dict):
            analysis["delete_audio_deferred"] = defer_reason
        reason = str(defer_reason.get("reason") or "not_ready")
        until = defer_reason.get("available_after")
        suffix = f" until {until}" if until else ""
        return False, f"Deferred processed audio delete for speaker repair window ({reason}){suffix}: {media_path}"
    import_root = mobile_import_root_for_path(settings, media_path)
    if import_root is None:
        return False, None
    if not media_path.exists() or not media_path.is_file() or media_path.is_symlink():
        return False, None
    try:
        recycled = move_to_recycle_bin(
            settings,
            media_path,
            category="mobile_audio_analysis",
            metadata={"reason": "delete_audio_after_analysis", "import_root": str(import_root)},
        )
        if not recycled.moved:
            raise OSError(recycled.error or "recycle move failed")
        prune_empty_parents(media_path.parent, stop=import_root)
    except OSError as exc:
        cleanup = metadata.setdefault("cleanup", {})
        if isinstance(cleanup, dict):
            cleanup["delete_audio_error"] = str(exc)
        return False, f"Failed to delete processed audio {media_path}: {exc}"

    recycled_at = utc_iso()
    metadata["media_deleted_at"] = recycled_at
    metadata["media_recycled_at"] = recycled_at
    metadata["deleted_media_path"] = str(media_path)
    metadata["recycle_bin_path"] = recycled.trash_path
    metadata["recycle_bin_delete_after"] = recycled.delete_after
    analysis = metadata.get("audio_analysis")
    if isinstance(analysis, dict):
        analysis["media_deleted_at"] = recycled_at
        analysis["media_recycled_at"] = recycled_at
        analysis["recycle_bin_path"] = recycled.trash_path
        analysis["recycle_bin_delete_after"] = recycled.delete_after
    warning = f"; warning: {recycled.error}" if recycled.error else ""
    return True, f"Moved processed audio to recycle bin: {media_path} -> {recycled.trash_path}{warning}"


def needs_processed_audio_cleanup(settings: Settings, metadata: dict[str, Any]) -> bool:
    if not mobile_sync_bool(settings, "delete_audio_after_analysis", False):
        return False
    if metadata.get("media_deleted_at") or metadata.get("media_recycled_at") or metadata.get("recycle_bin_path"):
        return False
    analysis = metadata.get("audio_analysis")
    if not isinstance(analysis, dict):
        return False
    if analysis.get("status") != "ok":
        return False
    if not (existing_summary(analysis) or analysis.get("transcript_status") in {"no_speech", "empty", "existing_transcript"}):
        return False
    return processed_audio_delete_defer_reason(settings, metadata) is None


def processed_audio_delete_defer_reason(settings: Settings, metadata: dict[str, Any]) -> dict[str, Any] | None:
    analysis = metadata.get("audio_analysis")
    if not isinstance(analysis, dict):
        return {"reason": "analysis_missing"}
    if analysis.get("status") != "ok":
        return {"reason": "analysis_not_ok", "status": analysis.get("status")}
    if not bool(settings.speaker_recognition.get("enabled", True)):
        return None

    timeline = analysis.get("audio_timeline")
    if not isinstance(timeline, dict):
        return None
    segments = timeline.get("speech_segments")
    if not isinstance(segments, list) or not segments:
        return None

    speaker_processing = analysis.get("speaker_processing")
    if not isinstance(speaker_processing, dict):
        return {"reason": "speaker_processing_pending"}
    status = str(speaker_processing.get("status") or "")
    if status in {"ok", "skipped_no_speech_like_segments", "skipped_unparseable_transcript"}:
        return None

    window_hours = mobile_sync_float(settings, "delete_audio_after_analysis_repair_window_hours", 24.0)
    if window_hours <= 0:
        return None
    base = parse_iso_datetime(
        str(speaker_processing.get("processed_at") or analysis.get("analyzed_at") or "")
    )
    if base is None:
        return {
            "reason": "speaker_repair_window_pending",
            "speaker_status": status,
            "repair_window_hours": window_hours,
        }
    available_after = base + timedelta(hours=window_hours)
    current = datetime.now().astimezone(available_after.tzinfo)
    if current >= available_after:
        return None
    return {
        "reason": "speaker_repair_window_pending",
        "speaker_status": status,
        "repair_window_hours": window_hours,
        "available_after": available_after.isoformat(timespec="seconds"),
    }


def mobile_sync_bool(settings: Settings, key: str, default: bool) -> bool:
    config = getattr(settings, "mobile_sync", {}) or {}
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def mobile_sync_float(settings: Settings, key: str, default: float) -> float:
    config = getattr(settings, "mobile_sync", {}) or {}
    value = config.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def audio_analysis_needs_retry(analysis: dict[str, Any]) -> bool:
    return (
        str(analysis.get("status") or "") in {"error", "processing"}
        or str(analysis.get("transcript_status") or "") == "transcription_error"
    )


def parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def mobile_import_root_for_path(settings: Settings, path: Path) -> Path | None:
    imports = (settings.data_dir / "mobile_sync" / "imports").resolve()
    try:
        relative = path.resolve().relative_to(imports)
    except ValueError:
        return None
    if not relative.parts:
        return None
    return imports / relative.parts[0]


def prune_empty_parents(path: Path, *, stop: Path) -> None:
    current = path.resolve()
    stop = stop.resolve()
    while current != stop and current.is_dir():
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def needs_speaker_registry(settings: Settings, analysis: dict[str, Any]) -> bool:
    if not bool(settings.speaker_recognition.get("enabled", True)):
        return False
    timeline = analysis.get("audio_timeline")
    if not isinstance(timeline, dict):
        return False
    segments = timeline.get("speech_segments")
    if not isinstance(segments, list) or not any(isinstance(item, dict) for item in segments):
        return False
    if needs_speaker_diarization_repair(settings, analysis):
        return True
    return not isinstance(analysis.get("speaker_processing"), dict)


def maybe_run_speaker_diarization_repair(settings: Settings, media_path: Path, analysis: dict[str, Any]) -> None:
    if not needs_speaker_diarization_repair(settings, analysis):
        return
    timeline = analysis.get("audio_timeline")
    if not isinstance(timeline, dict):
        return
    prepared = prepare_audio_for_stage(settings, media_path, stage="diarization")
    try:
        metadata = run_speaker_diarization(settings, prepared.path, timeline)
    finally:
        prepared.close()
    if metadata:
        analysis["local_speaker_diarization"] = metadata
        analysis.setdefault("audio_preprocessing", {})["diarization_repair"] = prepared.metadata
        analysis["audio_timeline"] = timeline
    if timeline_has_speaker_labels(timeline):
        analysis.pop("speaker_processing", None)


def needs_speaker_diarization_repair(settings: Settings, analysis: dict[str, Any]) -> bool:
    if not local_ai_bool(settings, "speaker_diarization_enabled", False):
        return False
    timeline = analysis.get("audio_timeline")
    if not isinstance(timeline, dict) or timeline_has_speaker_labels(timeline):
        return False
    diarization = analysis.get("local_speaker_diarization")
    if isinstance(diarization, dict) and diarization.get("status"):
        return False
    return True


def timeline_has_speaker_labels(timeline: dict[str, Any]) -> bool:
    segments = timeline.get("speech_segments")
    if not isinstance(segments, list):
        return False
    return any(
        isinstance(item, dict)
        and str(item.get("speaker") or "").strip()
        and item.get("speaker_label_source") not in {"assumed_single_speaker"}
        for item in segments
    )


def local_ai_bool(settings: Settings, key: str, default: bool) -> bool:
    config = getattr(settings, "local_ai", {}) or {}
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def should_delete_missing_audio_record(settings: Settings, row, metadata: dict[str, Any]) -> bool:
    if not audio_analysis_bool(settings, "delete_missing_audio_records", False):
        return False
    if row["body"]:
        return False
    media_path = resolve_media_path(metadata)
    if media_path is None:
        return True
    if media_path.exists():
        return False
    return mobile_import_root_for_path(settings, media_path) is not None


def audio_analysis_bool(settings: Settings, key: str, default: bool) -> bool:
    value = settings.audio_analysis.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def existing_summary(analysis: dict[str, Any]) -> str | None:
    for key in ("summary", "local_summary", "openai_summary"):
        value = analysis.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def row_metadata(row) -> dict[str, Any]:
    raw = row["metadata"]
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def resolve_media_path(metadata: dict[str, Any]) -> Path | None:
    analysis = metadata.get("audio_analysis") if isinstance(metadata.get("audio_analysis"), dict) else {}
    candidates = [
        metadata.get("resolved_media_path"),
        analysis.get("resolved_media_path") if isinstance(analysis, dict) else None,
        metadata.get("media_path"),
        metadata.get("recycle_bin_path"),
        analysis.get("recycle_bin_path") if isinstance(analysis, dict) else None,
        metadata.get("deleted_media_path"),
    ]
    fallback: Path | None = None
    for value in candidates:
        if not value:
            continue
        path = Path(str(value)).expanduser().resolve()
        if fallback is None:
            fallback = path
        if path.exists():
            return path
    return fallback


def probe_audio(path: Path) -> dict[str, Any]:
    if find_executable("ffprobe"):
        return probe_with_ffprobe(path)
    if find_executable("afinfo"):
        return probe_with_afinfo(path)
    size = path.stat().st_size
    return {
        "file_size": size,
        "probe": "stat",
    }


def probe_with_ffprobe(path: Path) -> dict[str, Any]:
    ffprobe = find_executable("ffprobe") or "ffprobe"
    proc = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "ffprobe failed")
    payload = json.loads(proc.stdout or "{}")
    streams = payload.get("streams") or []
    audio_stream = next((item for item in streams if item.get("codec_type") == "audio"), {})
    format_info = payload.get("format") or {}
    info: dict[str, Any] = {
        "probe": "ffprobe",
        "file_size": path.stat().st_size,
        "format": format_info.get("format_name"),
        "codec": audio_stream.get("codec_name"),
        "sample_rate": parse_number(audio_stream.get("sample_rate")),
        "channels": audio_stream.get("channels"),
        "bit_rate": parse_number(audio_stream.get("bit_rate") or format_info.get("bit_rate")),
        "duration_seconds": parse_number(format_info.get("duration") or audio_stream.get("duration")),
    }
    return {key: value for key, value in info.items() if value is not None}


def probe_with_afinfo(path: Path) -> dict[str, Any]:
    afinfo = find_executable("afinfo") or "afinfo"
    proc = subprocess.run(
        [afinfo, str(path)],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "afinfo failed")
    info: dict[str, Any] = {
        "probe": "afinfo",
        "file_size": path.stat().st_size,
    }
    for raw_line in proc.stdout.splitlines():
        line = raw_line.strip()
        if line.startswith("estimated duration:"):
            info["duration_seconds"] = parse_number(line.split(":", 1)[1].strip().split(" ", 1)[0])
        elif line.startswith("audio bytes:"):
            info["audio_bytes"] = parse_number(line.split(":", 1)[1].strip())
        elif line.startswith("bit rate:"):
            info["bit_rate"] = parse_number(line.split(":", 1)[1].strip())
        elif line.startswith("format list:"):
            info["format"] = line.split(":", 1)[1].strip()
    return info


def parse_number(value: Any) -> int | float | None:
    if value is None:
        return None
    try:
        number = float(str(value).strip())
    except ValueError:
        return None
    if number.is_integer():
        return int(number)
    return number
