from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import sys
import uuid
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from xml.etree import ElementTree

from .audio_preprocessing import prepare_audio_for_stage
from .config import Settings
from .executables import find_executable
from .store import Observation, Store
from .timeutil import from_timestamp, local_iso, utc_iso


OPENAI_BASE_URL = "https://api.openai.com/v1"
AUDIO_SUFFIXES = {".m4a", ".mp3", ".mp4", ".mpeg", ".mpga", ".wav", ".webm"}
TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".json", ".log", ".rtf", ".xml", ".html", ".htm"}
OPENAI_KEYCHAIN_ITEMS = (
    ("wond-openai", "OPENAI_API_KEY"),
    ("openai-api-key", "OPENAI_API_KEY"),
)
SPEAKER_DIARIZATION_BACKENDS = {"vibevoice", "vibevoice_mlx", "vibevoice_transformers"}
OVERLAP_SPEAKER_MIN_SECONDS = 0.2


@dataclass
class MediaAnalysisResult:
    analyzed: int = 0
    skipped: int = 0
    failed: int = 0
    observations: int = 0
    messages: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        return [
            f"Analyzed: {self.analyzed}",
            f"Observations written: {self.observations}",
            f"Skipped: {self.skipped}",
            f"Failed: {self.failed}",
            *self.messages,
        ]


@dataclass
class AudioOpenAIAnalysis:
    transcript: str | None
    summary: str | None
    metadata: dict[str, Any]


@dataclass
class TranscriptionResult:
    text: str
    segments: list[dict[str, Any]] = field(default_factory=list)
    duration_seconds: float | None = None
    raw: dict[str, Any] | str | None = None


def ai_provider(settings: Settings) -> str:
    provider = str(settings.ai_backend.get("provider") or "local").strip().lower()
    return provider or "local"


def use_local_ai(settings: Settings) -> bool:
    return ai_provider(settings) == "local"


def analysis_source_name(settings: Settings) -> str:
    return "local_ai" if use_local_ai(settings) else "openai"


def analysis_summary_key(settings: Settings) -> str:
    return "local_summary" if use_local_ai(settings) else "openai_summary"


def analyze_paths_with_openai(
    settings: Settings,
    store: Store,
    paths: list[Path],
    *,
    prompt: str | None = None,
    force: bool = False,
    observation_paths: Mapping[Path, Path] | None = None,
) -> MediaAnalysisResult:
    if use_local_ai(settings):
        return analyze_paths_with_local_ai(
            settings,
            store,
            paths,
            prompt=prompt,
            force=force,
            observation_paths=observation_paths,
        )
    result = MediaAnalysisResult()
    observations: list[Observation] = []
    for raw_path in paths:
        path = raw_path.expanduser().resolve()
        if not path.exists() or not path.is_file():
            result.failed += 1
            result.messages.append(f"- Missing file: {path}")
            continue
        try:
            analysis = analyze_file_with_openai(settings, path, prompt=prompt)
            observations.append(
                observation_for_file(
                    settings,
                    path,
                    analysis,
                    force=force,
                    source_path=observation_source_path(path, observation_paths),
                )
            )
            result.analyzed += 1
        except Exception as exc:
            result.failed += 1
            result.messages.append(f"- Failed {path}: {exc}")
    result.observations = store.upsert_observations(observations)
    return result


def analyze_file_with_openai(
    settings: Settings,
    path: Path,
    *,
    prompt: str | None = None,
) -> dict[str, Any]:
    if use_local_ai(settings):
        return analyze_file_with_local_ai(settings, path, prompt=prompt)
    mime = mime_type(path)
    suffix = path.suffix.lower()
    if suffix in AUDIO_SUFFIXES or mime.startswith("audio/"):
        audio = analyze_audio_with_openai(settings, path, prompt=prompt)
        return {
            "kind": "audio",
            "summary": audio.summary,
            "transcript": audio.transcript,
            "metadata": audio.metadata,
        }
    if mime.startswith("image/"):
        summary = analyze_image_with_openai(settings, path, prompt=prompt)
        return {
            "kind": "image",
            "summary": summary,
            "transcript": None,
            "metadata": {"mime_type": mime},
        }
    summary = analyze_document_with_openai(settings, path, prompt=prompt)
    return {
        "kind": "file",
        "summary": summary,
        "transcript": None,
        "metadata": {"mime_type": mime},
    }


def analyze_audio_with_openai(
    settings: Settings,
    path: Path,
    *,
    prompt: str | None = None,
) -> AudioOpenAIAnalysis:
    if use_local_ai(settings):
        return analyze_audio_with_local_ai(settings, path, prompt=prompt)
    max_audio_mb = float(settings.openai_analysis.get("max_audio_mb", 25))
    assert_size(path, max_audio_mb)
    transcription = transcribe_audio(settings, path, model=transcription_model(settings))
    transcript = transcription.text
    audio_timeline = build_audio_timeline(path, transcription)
    summary = summarize_text(
        settings,
        audio_analysis_context(transcript, audio_timeline),
        prompt=prompt or str(settings.openai_analysis.get("summary_prompt", "")),
        label=f"Audio file: {path.name}",
    )
    return AudioOpenAIAnalysis(
        transcript=transcript,
        summary=summary,
        metadata={
            "openai_transcription_model": transcription_model(settings),
            "openai_analysis_model": analysis_model(settings),
            "analyzed_at": utc_iso(),
            "audio_timeline": audio_timeline,
        },
    )


def analyze_image_with_openai(settings: Settings, path: Path, *, prompt: str | None = None) -> str:
    max_file_mb = float(settings.openai_analysis.get("max_file_mb", 20))
    assert_size(path, max_file_mb)
    content = [
        {"type": "input_text", "text": prompt or default_image_prompt(settings, path)},
        {
            "type": "input_image",
            "image_url": data_url(path),
            "detail": "auto",
        },
    ]
    return create_response(settings, content)


def analyze_document_with_openai(settings: Settings, path: Path, *, prompt: str | None = None) -> str:
    max_file_mb = float(settings.openai_analysis.get("max_file_mb", 20))
    assert_size(path, max_file_mb)
    content = [
        {
            "type": "input_file",
            "filename": path.name,
            "file_data": data_url(path),
        },
        {"type": "input_text", "text": prompt or default_file_prompt(settings, path)},
    ]
    return create_response(settings, content)


def summarize_text(
    settings: Settings,
    text: str,
    *,
    prompt: str,
    label: str,
    model: str | None = None,
    timeout_seconds: int | None = None,
) -> str:
    if use_local_ai(settings):
        return summarize_text_with_local_ai(
            settings,
            text,
            prompt=prompt,
            label=label,
            model=model,
            timeout_seconds=timeout_seconds,
        )
    content = [
        {
            "type": "input_text",
            "text": f"{prompt}\n\n{label}\n\nTranscript/content:\n{text}",
        }
    ]
    return create_response(settings, content)


def analyze_paths_with_local_ai(
    settings: Settings,
    store: Store,
    paths: list[Path],
    *,
    prompt: str | None = None,
    force: bool = False,
    observation_paths: Mapping[Path, Path] | None = None,
) -> MediaAnalysisResult:
    result = MediaAnalysisResult()
    observations: list[Observation] = []
    for raw_path in paths:
        path = raw_path.expanduser().resolve()
        if not path.exists() or not path.is_file():
            result.failed += 1
            result.messages.append(f"- Missing file: {path}")
            continue
        try:
            analysis = analyze_file_with_local_ai(settings, path, prompt=prompt)
            observations.append(
                observation_for_file(
                    settings,
                    path,
                    analysis,
                    force=force,
                    source_path=observation_source_path(path, observation_paths),
                )
            )
            result.analyzed += 1
        except Exception as exc:
            result.failed += 1
            result.messages.append(f"- Failed {path}: {exc}")
    result.observations = store.upsert_observations(observations)
    return result


def analyze_file_with_local_ai(
    settings: Settings,
    path: Path,
    *,
    prompt: str | None = None,
) -> dict[str, Any]:
    mime = mime_type(path)
    suffix = path.suffix.lower()
    if suffix in AUDIO_SUFFIXES or mime.startswith("audio/"):
        audio = analyze_audio_with_local_ai(settings, path, prompt=prompt)
        return {
            "kind": "audio",
            "summary": audio.summary,
            "transcript": audio.transcript,
            "metadata": audio.metadata,
        }
    if mime.startswith("image/"):
        summary = analyze_image_with_local_ai(settings, path, prompt=prompt)
        return {
            "kind": "image",
            "summary": summary,
            "transcript": None,
            "metadata": {
                "backend": "ollama",
                "model": local_vision_model(settings),
                "mime_type": mime,
            },
        }
    summary, metadata = analyze_document_with_local_ai(settings, path, prompt=prompt)
    return {
        "kind": "file",
        "summary": summary,
        "transcript": None,
        "metadata": metadata | {"mime_type": mime},
    }


def analyze_audio_with_local_ai(
    settings: Settings,
    path: Path,
    *,
    prompt: str | None = None,
) -> AudioOpenAIAnalysis:
    max_audio_mb = float(settings.local_ai.get("max_audio_mb", 1024))
    assert_size(path, max_audio_mb)
    asr_audio = prepare_audio_for_stage(settings, path, stage="asr")
    diarization_audio = None
    try:
        transcription = transcribe_audio_with_local_ai(settings, asr_audio.path)
        transcript = transcription.text
        audio_timeline = build_audio_timeline(path, transcription)
        audio_preprocessing = {
            "asr": asr_audio.metadata,
        }
        transcription_metadata = {
            "audio_preprocessing": audio_preprocessing
        }
        if isinstance(transcription.raw, dict) and transcription.raw.get("vad_presegmented"):
            transcription_metadata["local_transcription_vad"] = {
                "enabled": True,
                "speech_seconds": transcription.raw.get("speech_seconds"),
                "chunk_count": len(transcription.raw.get("chunks") or []),
            }
        if local_ai_bool(settings, "speaker_diarization_enabled", False):
            diarization_audio = prepare_audio_for_stage(settings, path, stage="diarization")
            audio_preprocessing["diarization"] = diarization_audio.metadata
            diarization_metadata = run_speaker_diarization(settings, diarization_audio.path, audio_timeline)
            if diarization_metadata:
                transcription_metadata["local_speaker_diarization"] = diarization_metadata
        else:
            audio_preprocessing["diarization"] = {
                "stage": "diarization",
                "status": "disabled",
                "reason": "speaker_diarization_disabled",
                "path": str(path),
            }
        summary = summarize_text_with_local_ai(
            settings,
            audio_analysis_context(transcript, audio_timeline),
            prompt=prompt or local_summary_prompt(settings),
            label=f"Audio file: {path.name}",
            model=audio_summary_model(settings),
        )
        return AudioOpenAIAnalysis(
            transcript=transcript,
            summary=summary,
            metadata={
                "analysis_backend": "local_ai",
                "local_transcription_backend": local_transcription_backend(settings),
                "local_transcription_model": local_transcription_model(settings),
                "local_analysis_backend": "ollama",
                "local_analysis_model": audio_summary_model(settings),
                "analyzed_at": utc_iso(),
                "audio_timeline": audio_timeline,
                **transcription_metadata,
            },
        )
    finally:
        asr_audio.close()
        if diarization_audio is not None:
            diarization_audio.close()


def analyze_image_with_local_ai(settings: Settings, path: Path, *, prompt: str | None = None) -> str:
    max_file_mb = float(settings.local_ai.get("max_file_mb", 50))
    assert_size(path, max_file_mb)
    image_prompt = prompt or (
        f"{local_summary_prompt(settings)}\n\n"
        f"Analyze this image for a personal memory timeline. File: {path.name}"
    )
    return ollama_chat(
        settings,
        model=local_vision_model(settings),
        prompt=image_prompt,
        images=[base64.b64encode(path.read_bytes()).decode("ascii")],
    )


def analyze_document_with_local_ai(
    settings: Settings,
    path: Path,
    *,
    prompt: str | None = None,
) -> tuple[str, dict[str, Any]]:
    max_file_mb = float(settings.local_ai.get("max_file_mb", 50))
    assert_size(path, max_file_mb)
    max_chars = int(settings.local_ai.get("max_text_chars", 30000))
    extracted = extract_text_for_local_ai(path, max_chars=max_chars)
    analysis_prompt = prompt or (
        f"{local_summary_prompt(settings)}\n\n"
        f"Analyze this file for a personal memory timeline. File: {path.name}"
    )
    summary = summarize_text_with_local_ai(
        settings,
        extracted["text"],
        prompt=analysis_prompt,
        label=f"File: {path.name}",
    )
    metadata = {
        "analysis_backend": "local_ai",
        "local_analysis_backend": "ollama",
        "local_analysis_model": local_text_model(settings),
        "text_extraction": extracted["method"],
        "text_truncated": extracted["truncated"],
    }
    return summary, metadata


def summarize_text_with_local_ai(
    settings: Settings,
    text: str,
    *,
    prompt: str,
    label: str,
    model: str | None = None,
    timeout_seconds: int | None = None,
) -> str:
    max_chars = int(settings.local_ai.get("max_text_chars", 30000))
    clipped = text[:max_chars]
    if len(text) > max_chars:
        clipped += "\n\n[Content truncated for local context window.]"
    return ollama_chat(
        settings,
        model=model or local_text_model(settings),
        prompt=f"{prompt}\n\n{label}\n\nTranscript/content:\n{clipped}",
        timeout_seconds=timeout_seconds,
    )


def transcribe_audio_with_local_ai(settings: Settings, path: Path) -> TranscriptionResult:
    backend = local_transcription_backend(settings)
    try:
        result = transcribe_audio_with_local_backend(
            settings,
            path,
            backend=backend,
            model=local_transcription_model(settings),
        )
        validate_transcription_quality(result)
        return result
    except RuntimeError as exc:
        fallback_backend = str(settings.local_ai.get("fallback_transcription_backend") or "").strip().lower()
        fallback_model = str(settings.local_ai.get("fallback_transcription_model") or "").strip()
        primary_model = local_transcription_model(settings)
        if not fallback_backend:
            raise
        if fallback_backend == backend and (not fallback_model or fallback_model == primary_model):
            raise
        try:
            result = transcribe_audio_with_local_backend(
                settings,
                path,
                backend=fallback_backend,
                model=fallback_model or None,
            )
            validate_transcription_quality(result)
        except RuntimeError as fallback_exc:
            raise RuntimeError(f"{exc}; fallback transcription failed: {fallback_exc}") from fallback_exc
        fallback_raw = result.raw
        result.raw = {
            "fallback_from_backend": backend,
            "fallback_error": str(exc),
            "fallback_raw": fallback_raw,
        }
        return result


def run_speaker_diarization(settings: Settings, path: Path, audio_timeline: dict[str, Any]) -> dict[str, Any] | None:
    if not local_ai_bool(settings, "speaker_diarization_enabled", False):
        return None
    backend = local_speaker_diarization_backend(settings)
    model = local_speaker_diarization_model(settings)
    try:
        result = transcribe_audio_with_local_backend(settings, path, backend=backend, model=model)
        validate_transcription_quality(result)
    except Exception as exc:
        fallback_backend = str(settings.local_ai.get("speaker_diarization_fallback_backend") or "").strip().lower()
        fallback_model = str(settings.local_ai.get("speaker_diarization_fallback_model") or "").strip()
        if not fallback_backend or fallback_backend == backend and (not fallback_model or fallback_model == model):
            return {
                "enabled": True,
                "status": "error",
                "backend": backend,
                "model": model,
                "error": str(exc),
            }
        try:
            result = transcribe_audio_with_local_backend(
                settings,
                path,
                backend=fallback_backend,
                model=fallback_model or None,
            )
            validate_transcription_quality(result)
        except Exception as fallback_exc:
            return {
                "enabled": True,
                "status": "error",
                "backend": backend,
                "model": model,
                "error": str(exc),
                "fallback_backend": fallback_backend,
                "fallback_model": fallback_model or None,
                "fallback_error": str(fallback_exc),
            }
        backend = fallback_backend
        model = fallback_model or local_transcription_model(settings)

    diarized_segments = [
        segment
        for segment in result.segments
        if isinstance(segment, dict) and normalize_transcript_speaker(segment.get("speaker"))
    ]
    overlay_stats = apply_diarization_to_timeline(audio_timeline, diarized_segments)
    metadata: dict[str, Any] = {
        "enabled": True,
        "status": "ok" if overlay_stats["applied_labels"] else "skipped_no_speaker_labels",
        "backend": backend,
        "model": model,
        "segment_count": len(result.segments),
        "speaker_labeled_segments": len(diarized_segments),
        **overlay_stats,
    }
    if isinstance(result.raw, dict) and result.raw.get("vad_presegmented"):
        metadata["vad"] = {
            "enabled": True,
            "speech_seconds": result.raw.get("speech_seconds"),
            "chunk_count": len(result.raw.get("chunks") or []),
        }
    if diarized_segments:
        audio_timeline["speaker_diarization_segments"] = diarized_segments[:1000]
    return metadata


def apply_diarization_to_timeline(timeline: dict[str, Any], diarized_segments: list[dict[str, Any]]) -> dict[str, int]:
    segments = timeline.get("speech_segments")
    if not isinstance(segments, list) or not diarized_segments:
        return {"applied_labels": 0, "overlap_segments": 0}
    applied = 0
    overlap_segments = 0
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        matches = speaker_overlaps_for_segment(segment, diarized_segments)
        if not matches:
            continue
        best = matches[0]["segment"]
        speaker = normalize_transcript_speaker(best.get("speaker"))
        if not speaker:
            continue
        overlap_speakers = simultaneous_speaker_labels(matches)
        segment["speaker"] = speaker
        segment["speaker_label_source"] = "local_speaker_diarization"
        if overlap_speakers:
            segment["overlap"] = True
            segment["overlap_speakers"] = overlap_speakers
            segment["speaker_display"] = " + ".join(overlap_speakers)
            overlap_segments += 1
        else:
            segment.pop("overlap", None)
            segment.pop("overlap_speakers", None)
            segment.pop("speaker_display", None)
        if best.get("speaker_scope"):
            segment["speaker_scope"] = best.get("speaker_scope")
        if best.get("speaker_local_label"):
            segment["speaker_local_label"] = best.get("speaker_local_label")
        applied += 1
    return {"applied_labels": applied, "overlap_segments": overlap_segments}


def best_overlapping_speaker_segment(segment: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    matches = speaker_overlaps_for_segment(segment, candidates)
    return matches[0]["segment"] if matches else None


def speaker_overlaps_for_segment(segment: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    start = parse_timestamp_seconds(segment.get("start"))
    end = parse_timestamp_seconds(segment.get("end"))
    if start is None or end is None or end <= start:
        return []
    matches: list[dict[str, Any]] = []
    midpoint = (start + end) / 2
    for candidate in candidates:
        candidate_start = parse_timestamp_seconds(candidate.get("start"))
        candidate_end = parse_timestamp_seconds(candidate.get("end"))
        if candidate_start is None or candidate_end is None or candidate_end <= candidate_start:
            continue
        speaker = normalize_transcript_speaker(candidate.get("speaker"))
        if not speaker:
            continue
        overlap = max(0.0, min(end, candidate_end) - max(start, candidate_start))
        if overlap <= 0 and not (candidate_start <= midpoint <= candidate_end):
            continue
        matches.append(
            {
                "segment": candidate,
                "speaker": speaker,
                "start": max(start, candidate_start),
                "end": min(end, candidate_end),
                "overlap": overlap or 0.001,
            }
        )
    matches.sort(key=lambda item: (-float(item["overlap"]), float(item["start"]), str(item["speaker"])))
    return matches


def simultaneous_speaker_labels(matches: list[dict[str, Any]]) -> list[str]:
    labels: list[str] = []
    for index, left in enumerate(matches):
        for right in matches[index + 1 :]:
            if left["speaker"] == right["speaker"]:
                continue
            overlap = max(0.0, min(float(left["end"]), float(right["end"])) - max(float(left["start"]), float(right["start"])))
            if overlap < OVERLAP_SPEAKER_MIN_SECONDS:
                continue
            for speaker in (str(left["speaker"]), str(right["speaker"])):
                if speaker not in labels:
                    labels.append(speaker)
    return labels


def transcribe_audio_with_local_backend(
    settings: Settings,
    path: Path,
    *,
    backend: str,
    model: str | None = None,
) -> TranscriptionResult:
    if should_vad_presegment_for_backend(settings, backend):
        chunked = transcribe_audio_with_vad_segments(settings, path, backend=backend, model=model)
        if chunked is not None:
            return chunked
    return transcribe_audio_with_backend(settings, path, backend=backend, model=model)


def should_vad_presegment_for_backend(settings: Settings, backend: str) -> bool:
    if not local_ai_bool(settings, "vad_presegment", True):
        return False
    if supports_speaker_diarization(backend):
        return local_ai_bool(settings, "vad_presegment_diarization", True)
    return True


def supports_speaker_diarization(backend: str) -> bool:
    return backend.strip().lower() in SPEAKER_DIARIZATION_BACKENDS


def vad_setting(settings: Settings, backend: str, key: str, default: Any) -> Any:
    if supports_speaker_diarization(backend):
        diarization_key = f"diarization_{key}"
        if diarization_key in settings.local_ai:
            return settings.local_ai.get(diarization_key)
    return settings.local_ai.get(key, default)


def transcribe_audio_with_backend(
    settings: Settings,
    path: Path,
    *,
    backend: str,
    model: str | None = None,
) -> TranscriptionResult:
    if backend == "vibevoice_mlx":
        return transcribe_with_vibevoice_mlx(settings, path, model=model)
    if backend in {"vibevoice", "vibevoice_transformers"}:
        return transcribe_with_vibevoice_transformers(settings, path, model=model)
    if backend == "mlx_audio":
        return transcribe_with_mlx_audio(settings, path, model=model)
    if backend == "mlx_whisper":
        return transcribe_with_mlx_whisper(settings, path, model=model)
    if backend == "command":
        return transcribe_with_command(settings, path)
    raise RuntimeError(
        f"Unsupported local transcription backend: {backend}. "
        "Use local_ai.transcription_backend=mlx_audio, mlx_whisper, vibevoice_mlx, vibevoice_transformers, or command."
    )


def transcribe_audio_with_vad_segments(
    settings: Settings,
    path: Path,
    *,
    backend: str,
    model: str | None = None,
) -> TranscriptionResult | None:
    ffmpeg = find_executable("ffmpeg")
    if not ffmpeg:
        return None
    duration = probe_duration_seconds(path)
    if duration is None or duration <= 0:
        return None
    intervals = detect_nonsilent_intervals(
        path,
        duration_seconds=duration,
        noise_db=float(vad_setting(settings, backend, "vad_silence_noise_db", -35)),
        min_silence_seconds=float(vad_setting(settings, backend, "vad_min_silence_seconds", 0.5)),
    )
    min_speech = float(vad_setting(settings, backend, "vad_min_speech_seconds", 0.45))
    intervals = [(start, end) for start, end in intervals if end - start >= min_speech]
    total_speech = sum(end - start for start, end in intervals)
    if total_speech < float(vad_setting(settings, backend, "vad_min_total_speech_seconds", 1.0)):
        raise RuntimeError("no recognizable speech after VAD pre-segmentation")

    diarization_backend = supports_speaker_diarization(backend)
    chunks = merge_speech_intervals(
        intervals,
        duration_seconds=duration,
        padding_seconds=float(vad_setting(settings, backend, "vad_padding_seconds", 0.25)),
        merge_gap_seconds=float(vad_setting(settings, backend, "vad_merge_gap_seconds", 1.5)),
        max_chunk_seconds=float(vad_setting(settings, backend, "vad_max_chunk_seconds", 45.0)),
    )
    max_chunks = max(1, int(vad_setting(settings, backend, "vad_max_chunks", 8)))
    max_merge_gap = vad_setting(
        settings,
        backend,
        "vad_max_count_merge_gap_seconds",
        8.0 if diarization_backend else None,
    )
    chunks = merge_intervals_to_max_count(
        chunks,
        max_chunks,
        max_gap_seconds=float(max_merge_gap) if max_merge_gap not in (None, "") else None,
    )
    if not chunks:
        raise RuntimeError("no recognizable speech after VAD pre-segmentation")

    segments: list[dict[str, Any]] = []
    text_parts: list[str] = []
    raw_chunks: list[dict[str, Any]] = []
    for index, (start, end) in enumerate(chunks, start=1):
        clip = extract_audio_slice_for_asr(
            path,
            start_seconds=start,
            end_seconds=end,
            sample_rate=local_asr_sample_rate_for_backend(backend),
        )
        try:
            try:
                chunk_result = transcribe_audio_with_backend(settings, clip, backend=backend, model=model)
                validate_transcription_quality(chunk_result)
            except RuntimeError as exc:
                if is_no_speech_like_local_transcription_error(exc):
                    raw_chunks.append(
                        {
                            "index": index,
                            "start": round(start, 3),
                            "end": round(end, 3),
                            "skipped": "no_text",
                            "error": str(exc),
                        }
                    )
                    continue
                raise
            raw_chunks.append(
                {
                    "index": index,
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "raw": chunk_result.raw,
                }
            )
            if chunk_result.segments:
                for item in chunk_result.segments:
                    segment = dict(item)
                    segment["start"] = max(start, start + float(segment["start"]))
                    segment["end"] = min(end, start + float(segment["end"]))
                    if diarization_backend and segment.get("speaker"):
                        segment.setdefault("speaker_local_label", segment.get("speaker"))
                        segment.setdefault("speaker_scope", f"vad_chunk_{index:03d}")
                    if segment["end"] > segment["start"]:
                        segments.append(segment)
            elif chunk_result.text.strip():
                segments.append(
                    {
                        "start": start,
                        "end": end,
                        "speaker": None,
                        "text": chunk_result.text.strip(),
                    }
                )
            if chunk_result.text.strip():
                text_parts.append(chunk_result.text.strip())
        finally:
            clip.unlink(missing_ok=True)

    segments = dedupe_segments(segments)
    text = transcript_text_from_segments(segments) if segments else "\n\n".join(text_parts).strip()
    if not text:
        raise RuntimeError("no recognizable speech after VAD pre-segmentation")
    return TranscriptionResult(
        text=text,
        segments=segments,
        duration_seconds=duration,
        raw={
            "vad_presegmented": True,
            "backend": backend,
            "model": model,
            "diarization_backend": diarization_backend,
            "speech_seconds": round(total_speech, 3),
            "chunks": raw_chunks,
        },
    )


def is_no_speech_like_local_transcription_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "returned no text" in text
        or "no recognizable speech" in text
        or "no speech" in text
        or "transcription looked pathological" in text
    )


def detect_nonsilent_intervals(
    path: Path,
    *,
    duration_seconds: float,
    noise_db: float,
    min_silence_seconds: float,
) -> list[tuple[float, float]]:
    ffmpeg = find_executable("ffmpeg")
    if not ffmpeg:
        return []
    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            f"silencedetect=noise={noise_db:g}dB:d={min_silence_seconds:g}",
            "-f",
            "null",
            "-",
        ],
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    output = f"{proc.stdout}\n{proc.stderr}"
    silence_ranges: list[tuple[float, float]] = []
    current_start: float | None = None
    for line in output.splitlines():
        start_match = re.search(r"silence_start:\s*([0-9.]+)", line)
        if start_match:
            current_start = parse_float(start_match.group(1))
        end_match = re.search(r"silence_end:\s*([0-9.]+)", line)
        if not end_match:
            continue
        silence_end = parse_float(end_match.group(1))
        silence_duration = parse_float(first_regex_group(r"silence_duration:\s*([0-9.]+)", line))
        if silence_end is None:
            continue
        silence_start = current_start
        if silence_start is None and silence_duration is not None:
            silence_start = max(0.0, silence_end - silence_duration)
        if silence_start is not None and silence_end > silence_start:
            silence_ranges.append((max(0.0, silence_start), min(duration_seconds, silence_end)))
        current_start = None
    if current_start is not None and duration_seconds > current_start:
        silence_ranges.append((max(0.0, current_start), duration_seconds))
    if proc.returncode != 0 and not silence_ranges:
        return []
    return nonsilent_gaps_from_silences(silence_ranges, duration_seconds=duration_seconds)


def nonsilent_gaps_from_silences(
    silence_ranges: list[tuple[float, float]],
    *,
    duration_seconds: float,
) -> list[tuple[float, float]]:
    intervals: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in sorted(silence_ranges):
        start = max(0.0, min(duration_seconds, start))
        end = max(start, min(duration_seconds, end))
        if start > cursor:
            intervals.append((cursor, start))
        cursor = max(cursor, end)
    if duration_seconds > cursor:
        intervals.append((cursor, duration_seconds))
    return intervals


def merge_speech_intervals(
    intervals: list[tuple[float, float]],
    *,
    duration_seconds: float,
    padding_seconds: float,
    merge_gap_seconds: float,
    max_chunk_seconds: float,
) -> list[tuple[float, float]]:
    chunks: list[tuple[float, float]] = []
    current: tuple[float, float] | None = None
    for raw_start, raw_end in intervals:
        start = max(0.0, raw_start - padding_seconds)
        end = min(duration_seconds, raw_end + padding_seconds)
        if current is None:
            current = (start, end)
            continue
        current_start, current_end = current
        if start - current_end <= merge_gap_seconds and end - current_start <= max_chunk_seconds:
            current = (current_start, max(current_end, end))
        else:
            chunks.extend(split_long_interval(current, max_chunk_seconds=max_chunk_seconds))
            current = (start, end)
    if current is not None:
        chunks.extend(split_long_interval(current, max_chunk_seconds=max_chunk_seconds))
    return chunks


def split_long_interval(interval: tuple[float, float], *, max_chunk_seconds: float) -> list[tuple[float, float]]:
    start, end = interval
    if max_chunk_seconds <= 0 or end - start <= max_chunk_seconds:
        return [(start, end)]
    chunks = []
    cursor = start
    while end - cursor > max_chunk_seconds:
        chunks.append((cursor, cursor + max_chunk_seconds))
        cursor += max_chunk_seconds
    if end > cursor:
        chunks.append((cursor, end))
    return chunks


def merge_intervals_to_max_count(
    intervals: list[tuple[float, float]],
    max_count: int,
    *,
    max_gap_seconds: float | None = None,
) -> list[tuple[float, float]]:
    chunks = list(intervals)
    while len(chunks) > max_count:
        candidates = [
            (idx, chunks[idx + 1][0] - chunks[idx][1])
            for idx in range(len(chunks) - 1)
            if max_gap_seconds is None or chunks[idx + 1][0] - chunks[idx][1] <= max_gap_seconds
        ]
        if not candidates:
            break
        best_index = min(candidates, key=lambda item: item[1])[0]
        merged = (chunks[best_index][0], chunks[best_index + 1][1])
        chunks[best_index : best_index + 2] = [merged]
    return chunks


def extract_audio_slice_for_asr(
    path: Path,
    *,
    start_seconds: float,
    end_seconds: float,
    sample_rate: int,
) -> Path:
    ffmpeg = find_executable("ffmpeg") or "ffmpeg"
    output = Path("/private/tmp") / f"wond-asr-chunk-{uuid.uuid4().hex}.wav"
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-nostats",
            "-ss",
            f"{start_seconds:.3f}",
            "-to",
            f"{end_seconds:.3f}",
            "-i",
            str(path),
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-vn",
            str(output),
        ],
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    if proc.returncode != 0 or not output.exists() or output.stat().st_size == 0:
        output.unlink(missing_ok=True)
        detail = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(f"ffmpeg audio chunk extraction failed: {detail}")
    return output


def local_asr_sample_rate_for_backend(backend: str) -> int:
    if backend in {"vibevoice", "vibevoice_mlx", "vibevoice_transformers"}:
        return 24000
    return 16000


def first_regex_group(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1) if match else None


def load_subprocess_json(stdout: str, *, stderr: str = "", label: str = "subprocess") -> Any:
    text = stdout.strip()
    if not text:
        detail = stderr.strip() or "empty stdout"
        raise RuntimeError(f"{label} returned invalid JSON: {detail}")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        for line in reversed(text.splitlines()):
            candidate = line.strip()
            if not candidate.startswith(("{", "[")):
                continue
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
        detail = stderr.strip() or str(exc)
        raise RuntimeError(f"{label} returned invalid JSON: {detail}") from exc


def transcribe_with_vibevoice_transformers(
    settings: Settings,
    path: Path,
    *,
    model: str | None = None,
) -> TranscriptionResult:
    model_id = model or local_transcription_model(settings)
    if model_id.lower().startswith("mlx-community/"):
        raise RuntimeError(
            "vibevoice_transformers requires a Hugging Face transformers model; "
            f"{model_id} is an MLX quantized model. Use microsoft/VibeVoice-ASR-HF."
        )
    prompt = str(settings.local_ai.get("vibevoice_prompt") or "Transcribe the audio with speaker labels and timestamps.")
    device_map = str(settings.local_ai.get("vibevoice_device_map") or "auto")
    prepared = prepare_audio_for_local_asr(path, sample_rate=24000)
    script = """
import json
import os
import sys

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from transformers import pipeline

audio_path = sys.argv[1]
model_id = sys.argv[2]
prompt = sys.argv[3]
device_map = sys.argv[4]

pipe = pipeline("any-to-any", model=model_id, device_map=device_map)
chat_template = [
    {
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "audio", "path": audio_path},
        ],
    }
]
outputs = pipe(text=chat_template, return_full_text=False)
generated = outputs[0].get("generated_text") if outputs and isinstance(outputs[0], dict) else str(outputs)
payload = {"generated_text": generated}
processor = getattr(pipe, "processor", None)
if processor is not None:
    try:
        payload["speaker_dict"] = processor.extract_speaker_dict(generated)
    except Exception as exc:
        payload["speaker_dict_error"] = str(exc)
    try:
        payload["transcription"] = processor.extract_transcription(generated)
    except Exception as exc:
        payload["transcription_error"] = str(exc)
print(json.dumps(payload, ensure_ascii=False, default=str))
""".strip()
    proc = subprocess.run(
        [sys.executable, "-c", script, str(prepared), model_id, prompt, device_map],
        text=True,
        capture_output=True,
        timeout=int(settings.local_ai.get("transcription_timeout_seconds", 3600)),
        check=False,
    )
    try:
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip()
            raise RuntimeError(f"vibevoice transformers failed: {detail}")
        return transcription_from_vibevoice_payload(
            load_subprocess_json(proc.stdout, stderr=proc.stderr, label="vibevoice transformers")
        )
    finally:
        if prepared != path:
            prepared.unlink(missing_ok=True)


def transcribe_with_vibevoice_mlx(
    settings: Settings,
    path: Path,
    *,
    model: str | None = None,
) -> TranscriptionResult:
    model = model or local_speaker_diarization_model(settings)
    prepared = prepare_audio_for_local_asr(path, sample_rate=24000)
    context = str(settings.local_ai.get("speaker_diarization_context") or "").strip()
    script = """
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from mlx_audio.stt.generate import generate_transcription
from mlx_audio.stt.utils import load_model

audio_path = sys.argv[1]
model_id = sys.argv[2]
context = sys.argv[3]
model = load_model(model_id)
kwargs = {
    "model": model,
    "audio": audio_path,
    "format": "json",
    "verbose": False,
}
if context:
    kwargs["context"] = context
with tempfile.TemporaryDirectory() as tmpdir:
    output_path = Path(tmpdir) / "diarization"
    kwargs["output_path"] = str(output_path)
    transcription = generate_transcription(**kwargs)
    text = getattr(transcription, "text", None)
    segments = getattr(transcription, "segments", None)
    output_file = output_path.with_suffix(".json")
    file_payload = None
    if output_file.exists():
        try:
            file_payload = json.loads(output_file.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            file_payload = None
    if not text and isinstance(file_payload, dict):
        text = file_payload.get("text")
    if segments is None and isinstance(file_payload, dict):
        segments = file_payload.get("segments") or file_payload.get("sentences")
    payload = {
        "text": text,
        "segments": segments,
        "duration": getattr(transcription, "duration", None),
        "model": model_id,
    }
    print(json.dumps(payload, ensure_ascii=False, default=str))
""".strip()
    proc = subprocess.run(
        [sys.executable, "-c", script, str(prepared), model, context],
        text=True,
        capture_output=True,
        timeout=int(settings.local_ai.get("speaker_diarization_timeout_seconds", 900)),
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(f"vibevoice mlx failed: {detail}")
    try:
        return transcription_from_payload(
            load_subprocess_json(proc.stdout, stderr=proc.stderr, label="vibevoice mlx"),
            "vibevoice mlx returned no text",
        )
    finally:
        if prepared != path:
            prepared.unlink(missing_ok=True)


def transcribe_with_mlx_audio(
    settings: Settings,
    path: Path,
    *,
    model: str | None = None,
) -> TranscriptionResult:
    model = model or local_transcription_model(settings)
    language = str(settings.local_ai.get("transcription_language") or "auto")
    prepared = prepare_audio_for_local_asr(path, sample_rate=16000)
    script = """
import json
import sys
import tempfile
from pathlib import Path

from mlx_audio.stt.generate import generate_transcription
from mlx_audio.stt.utils import load_model

audio_path = sys.argv[1]
model_id = sys.argv[2]
language = sys.argv[3]
model = load_model(model_id)
kwargs = {
    "model": model,
    "audio": audio_path,
    "format": "txt",
    "verbose": False,
}
if language and language != "auto":
    kwargs["language"] = language
with tempfile.TemporaryDirectory() as tmpdir:
    output_path = Path(tmpdir) / "transcript"
    kwargs["output_path"] = str(output_path)
    transcription = generate_transcription(**kwargs)
    text = getattr(transcription, "text", None)
    output_file = output_path.with_suffix(".txt")
    if not text and output_file.exists():
        text = output_file.read_text(encoding="utf-8", errors="replace")
    payload = {
        "text": text,
        "segments": getattr(transcription, "segments", None),
        "duration": getattr(transcription, "duration", None),
    }
    print(json.dumps(payload, ensure_ascii=False))
""".strip()
    proc = subprocess.run(
        [sys.executable, "-c", script, str(prepared), model, language],
        text=True,
        capture_output=True,
        timeout=int(settings.local_ai.get("transcription_timeout_seconds", 1800)),
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(f"mlx-audio failed: {detail}")
    try:
        return transcription_from_payload(
            load_subprocess_json(proc.stdout, stderr=proc.stderr, label="mlx-audio"),
            "mlx-audio returned no text",
        )
    finally:
        if prepared != path:
            prepared.unlink(missing_ok=True)


def transcribe_with_mlx_whisper(
    settings: Settings,
    path: Path,
    *,
    model: str | None = None,
) -> TranscriptionResult:
    model = model or local_transcription_model(settings)
    language = str(settings.local_ai.get("transcription_language") or "auto")
    script = """
import json
import sys
import mlx_whisper

audio_path = sys.argv[1]
model = sys.argv[2]
language = sys.argv[3]
kwargs = {"path_or_hf_repo": model}
if language and language != "auto":
    kwargs["language"] = language
result = mlx_whisper.transcribe(audio_path, **kwargs)
print(json.dumps(result, ensure_ascii=False))
""".strip()
    proc = subprocess.run(
        [sys.executable, "-c", script, str(path), model, language],
        text=True,
        capture_output=True,
        timeout=int(settings.local_ai.get("transcription_timeout_seconds", 1800)),
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(f"mlx-whisper failed: {detail}")
    return transcription_from_payload(json.loads(proc.stdout), "mlx-whisper returned no text")


def transcribe_with_command(settings: Settings, path: Path) -> TranscriptionResult:
    command = str(settings.local_ai.get("transcription_command") or "").strip()
    if not command:
        raise RuntimeError("local_ai.transcription_command is required when transcription_backend=command")
    rendered = (
        command.replace("{audio}", str(path))
        .replace("{model}", local_transcription_model(settings))
        .replace("{language}", str(settings.local_ai.get("transcription_language") or "auto"))
    )
    proc = subprocess.run(
        rendered,
        shell=True,
        text=True,
        capture_output=True,
        timeout=int(settings.local_ai.get("transcription_timeout_seconds", 1800)),
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"local transcription command failed: {(proc.stderr or proc.stdout).strip()}")
    raw = proc.stdout.strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        if raw:
            return TranscriptionResult(text=raw, raw=raw)
        raise RuntimeError("local transcription command returned no text")
    return transcription_from_payload(payload, "local transcription command returned no text")


def prepare_audio_for_local_asr(path: Path, *, sample_rate: int) -> Path:
    ffmpeg = find_executable("ffmpeg")
    if not ffmpeg:
        return path
    output = Path("/private/tmp") / f"wond-asr-{uuid.uuid4().hex}.wav"
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-vn",
            str(output),
        ],
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    if proc.returncode != 0 or not output.exists() or output.stat().st_size == 0:
        output.unlink(missing_ok=True)
        detail = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(f"ffmpeg audio conversion failed: {detail}")
    return output


def transcribe_audio(settings: Settings, path: Path, *, model: str) -> TranscriptionResult:
    boundary = f"----wond-{uuid.uuid4().hex}"
    fields = {
        "model": model,
        "response_format": transcription_response_format(settings, model),
    }
    if "diarize" in model:
        fields["chunking_strategy"] = "auto"
    body = multipart_body(
        boundary,
        fields=fields,
        files={
            "file": (path.name, path.read_bytes(), mime_type(path)),
        },
    )
    payload = openai_http(
        "/audio/transcriptions",
        data=body,
        content_type=f"multipart/form-data; boundary={boundary}",
        base_url=transcription_base_url(settings),
    )
    if isinstance(payload, dict):
        text = payload.get("text")
        if isinstance(text, str) and text.strip():
            return TranscriptionResult(
                text=text.strip(),
                segments=normalize_transcript_segments(payload.get("segments")),
                duration_seconds=parse_float(payload.get("duration")),
                raw=payload,
            )
    if isinstance(payload, str) and payload.strip():
        return TranscriptionResult(text=payload.strip(), raw=payload)
    raise RuntimeError("OpenAI transcription returned no text")


def create_response(settings: Settings, content: list[dict[str, Any]]) -> str:
    payload = {
        "model": analysis_model(settings),
        "input": [
            {
                "role": "user",
                "content": content,
            }
        ],
        "max_output_tokens": 1400,
    }
    response = openai_http(
        "/responses",
        data=json.dumps(payload).encode("utf-8"),
        content_type="application/json",
    )
    text = extract_response_text(response)
    if not text:
        raise RuntimeError("OpenAI response did not include text output")
    return text


def openai_http(
    path: str,
    *,
    data: bytes,
    content_type: str,
    base_url: str = OPENAI_BASE_URL,
) -> Any:
    api_key = openai_api_key()
    requires_key = base_url.rstrip("/") == OPENAI_BASE_URL
    if requires_key and not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    headers = {
        "Content-Type": content_type,
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
            content_type_header = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI HTTP {exc.code}: {raw}") from exc
    text = raw.decode("utf-8", errors="replace")
    if "application/json" in content_type_header:
        return json.loads(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def openai_api_key() -> str | None:
    value = os.environ.get("OPENAI_API_KEY")
    if value:
        return value
    for service, account in OPENAI_KEYCHAIN_ITEMS:
        try:
            proc = subprocess.run(
                ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    return None


def ollama_chat(
    settings: Settings,
    *,
    model: str,
    prompt: str,
    images: list[str] | None = None,
    timeout_seconds: int | None = None,
) -> str:
    disable_thinking = bool(settings.local_ai.get("disable_thinking", True))
    content = f"/no_think\n{prompt}" if disable_thinking else prompt
    message: dict[str, Any] = {"role": "user", "content": content}
    if images:
        message["images"] = images
    payload = {
        "model": model,
        "messages": [message],
        "stream": False,
        "think": False if disable_thinking else None,
        "options": {
            "temperature": float(settings.local_ai.get("temperature", 0.2)),
        },
    }
    if payload["think"] is None:
        payload.pop("think", None)
    raw = json.dumps(payload).encode("utf-8")
    base_url = str(settings.local_ai.get("ollama_base_url") or "http://127.0.0.1:11434").rstrip("/")
    request = urllib.request.Request(
        f"{base_url}/api/chat",
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout_seconds or int(settings.local_ai.get("ollama_timeout_seconds", 600)),
        ) as response:
            response_payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama is not reachable at {base_url}: {exc.reason}") from exc
    message_payload = response_payload.get("message") if isinstance(response_payload, dict) else None
    if isinstance(message_payload, dict):
        content = message_payload.get("content")
        if isinstance(content, str) and content.strip():
            return strip_thinking_output(content)
    response = response_payload.get("response") if isinstance(response_payload, dict) else None
    if isinstance(response, str) and response.strip():
        return strip_thinking_output(response)
    raise RuntimeError("Ollama response did not include text output")


def strip_thinking_output(text: str) -> str:
    cleaned = re.sub(r"(?is)<think>.*?</think>", "", text).strip()
    return cleaned or text.strip()


def extract_text_for_local_ai(path: Path, *, max_chars: int) -> dict[str, Any]:
    suffix = path.suffix.lower()
    mime = mime_type(path)
    if suffix in TEXT_SUFFIXES or mime.startswith("text/"):
        text = path.read_text(encoding="utf-8", errors="replace")
        return clipped_text(text, max_chars=max_chars, method="plain_text")
    if suffix == ".pdf":
        return extract_pdf_text(path, max_chars=max_chars)
    if suffix in {".docx", ".pptx", ".xlsx"}:
        return extract_office_openxml_text(path, max_chars=max_chars)
    raise RuntimeError(
        f"Local file analysis cannot extract text from {path.suffix or 'this file type'} yet. "
        "Supported local document types: txt, md, csv, json, xml/html, pdf, docx, pptx, xlsx."
    )


def clipped_text(text: str, *, max_chars: int, method: str) -> dict[str, Any]:
    return {
        "text": text[:max_chars],
        "method": method,
        "truncated": len(text) > max_chars,
    }


def extract_pdf_text(path: Path, *, max_chars: int) -> dict[str, Any]:
    pdftotext = find_executable("pdftotext")
    if pdftotext:
        proc = subprocess.run(
            [pdftotext, "-layout", str(path), "-"],
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return clipped_text(proc.stdout, max_chars=max_chars, method="pdftotext")
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise RuntimeError("PDF local analysis requires pdftotext or the pypdf Python package") from exc
    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
        if sum(len(item) for item in parts) >= max_chars:
            break
    return clipped_text("\n\n".join(parts), max_chars=max_chars, method="pypdf")


def extract_office_openxml_text(path: Path, *, max_chars: int) -> dict[str, Any]:
    prefixes = ("word/", "ppt/", "xl/")
    parts: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = sorted(
            name
            for name in archive.namelist()
            if name.endswith(".xml") and name.startswith(prefixes)
        )
        for name in names:
            try:
                root = ElementTree.fromstring(archive.read(name))
            except ElementTree.ParseError:
                continue
            texts = [node.text.strip() for node in root.iter() if node.text and node.text.strip()]
            if texts:
                parts.append("\n".join(texts))
            if sum(len(item) for item in parts) >= max_chars:
                break
    text = "\n\n".join(parts).strip()
    if not text:
        raise RuntimeError(f"No extractable text found in {path.name}")
    return clipped_text(text, max_chars=max_chars, method="office_openxml")


def transcription_from_payload(payload: Any, empty_message: str) -> TranscriptionResult:
    if isinstance(payload, dict):
        text = payload.get("text")
        if isinstance(text, str) and text.strip():
            text = text.strip()
            duration = parse_float(payload.get("duration"))
            segments_value = payload.get("segments")
            if segments_value is None:
                segments_value = payload.get("sentences")
            segments = normalize_transcript_segments(segments_value)
            text_segments = parse_structured_transcript_text(text)
            if text_segments:
                if not segments:
                    segments = text_segments
                text = transcript_text_from_segments(text_segments)
            return TranscriptionResult(
                text=text,
                segments=segments,
                duration_seconds=duration,
                raw=payload,
            )
    if isinstance(payload, str) and payload.strip():
        text = payload.strip()
        segments = parse_structured_transcript_text(text)
        if segments:
            text = transcript_text_from_segments(segments)
        return TranscriptionResult(text=text, segments=segments, raw=payload)
    raise RuntimeError(empty_message)


def transcription_from_vibevoice_payload(payload: dict[str, Any]) -> TranscriptionResult:
    transcription = payload.get("transcription")
    speaker_dict = payload.get("speaker_dict")
    generated = payload.get("generated_text")
    segments = normalize_vibevoice_segments(transcription)
    if not segments:
        segments = normalize_vibevoice_segments(speaker_dict)
    if not segments:
        segments = parse_vibevoice_text_segments(str(generated or ""))
    text = flatten_transcription_text(transcription)
    if not text:
        text = flatten_transcription_text(speaker_dict)
    if not text and segments:
        text = "\n".join(
            f"{item.get('speaker') or 'speaker'}: {item.get('text')}"
            for item in segments
            if item.get("text")
        )
    if not text and isinstance(generated, str):
        text = generated.strip()
    if not text:
        raise RuntimeError("VibeVoice returned no transcript text")
    duration = None
    if segments:
        duration = max((parse_timestamp_seconds(item.get("end")) or 0.0) for item in segments)
    return TranscriptionResult(text=text, segments=segments, duration_seconds=duration or None, raw=payload)


def validate_transcription_quality(result: TranscriptionResult) -> None:
    reason = pathological_transcript_repetition(result.text)
    if reason is not None:
        raise RuntimeError(f"transcription looked pathological: {reason}")


def pathological_transcript_repetition(text: str) -> str | None:
    tokens = re.findall(r"[\w\u3040-\u30ff\u3400-\u9fff]+", text)
    current = None
    run_length = 0
    for token in tokens:
        if token == current:
            run_length += 1
        else:
            current = token
            run_length = 1
        if run_length >= 40:
            preview = token[:20]
            return f"token {preview!r} repeated {run_length}+ times"

    repeated_word = re.search(r"([\w\u3040-\u30ff\u3400-\u9fff]{1,8})(?:[、,，\s]*\1){39,}", text)
    if repeated_word:
        preview = repeated_word.group(1)[:20]
        return f"phrase {preview!r} repeated excessively"

    repeated_char = re.search(r"([\u3040-\u30ff\u3400-\u9fffA-Za-z0-9])\1{79,}", text)
    if repeated_char:
        return f"character {repeated_char.group(1)!r} repeated excessively"
    return None


def parse_structured_transcript_text(text: str) -> list[dict[str, Any]]:
    stripped = text.strip()
    if stripped.startswith(("[", "{")):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
        if payload is not None:
            segments = normalize_vibevoice_segments(payload)
            if segments:
                return segments
            return normalize_transcript_segments(payload)
        jsonish_segments = parse_jsonish_transcript_segments(stripped)
        if jsonish_segments:
            return jsonish_segments
    return parse_vibevoice_text_segments(text)


def parse_jsonish_transcript_segments(text: str) -> list[dict[str, Any]]:
    if '"Start"' not in text or '"End"' not in text or '"Content"' not in text:
        return []
    starts = [match.start() for match in re.finditer(r"\{\s*\"Start\"\s*:", text)]
    if not starts:
        return []
    starts.append(len(text))
    segments: list[dict[str, Any]] = []
    for index, start_index in enumerate(starts[:-1]):
        raw = text[start_index : starts[index + 1]].strip()
        raw = raw.strip(" \n\r\t,[]")
        if not raw:
            continue
        segment = segment_from_jsonish_mapping(raw)
        if segment is not None:
            segments.append(segment)
    return dedupe_segments(segments)


def segment_from_jsonish_mapping(raw: str) -> dict[str, Any] | None:
    start = jsonish_field(raw, "Start")
    end = jsonish_field(raw, "End")
    text = jsonish_content_field(raw)
    if text is None:
        return None
    start_seconds = parse_timestamp_seconds(start)
    end_seconds = parse_timestamp_seconds(end)
    if start_seconds is None or end_seconds is None or end_seconds <= start_seconds:
        return None
    speaker_value = jsonish_field(raw, "Speaker")
    speaker = normalize_transcript_speaker(speaker_value)
    return {
        "start": start_seconds,
        "end": end_seconds,
        "speaker": speaker,
        "text": clean_jsonish_text(text),
    }


def jsonish_field(raw: str, key: str) -> str | None:
    match = re.search(
        rf'"{re.escape(key)}"\s*:\s*(?:"(?P<quoted>[^"]*)"|(?P<bare>-?\d+(?:\.\d+)?|null|true|false))',
        raw,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return match.group("quoted") if match.group("quoted") is not None else match.group("bare")


def jsonish_content_field(raw: str) -> str | None:
    match = re.search(r'"Content"\s*:\s*"', raw, flags=re.IGNORECASE)
    if not match:
        return None
    end_quote = raw.rfind('"')
    if end_quote < match.end():
        return None
    return raw[match.end() : end_quote]


def clean_jsonish_text(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\r", "\r")
        .replace("\\t", "\t")
        .replace('\\"', '"')
        .strip()
    )


def normalize_transcript_speaker(value: Any) -> str | None:
    if value in (None, "", "null"):
        return None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d+", text):
        return f"Speaker {int(text) + 1}"
    return text


def transcript_text_from_segments(segments: list[dict[str, Any]]) -> str:
    lines = []
    for item in segments:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        speaker = transcript_segment_speaker_display(item)
        start = parse_timestamp_seconds(item.get("start"))
        end = parse_timestamp_seconds(item.get("end"))
        if start is not None and end is not None:
            lines.append(f"{start:.2f}-{end:.2f} {speaker}: {text}")
        else:
            lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


def transcript_segment_speaker_display(segment: dict[str, Any]) -> str:
    overlap_speakers = segment.get("overlap_speakers")
    if segment.get("overlap") and isinstance(overlap_speakers, list):
        labels = [str(item).strip() for item in overlap_speakers if str(item or "").strip()]
        if labels:
            return " + ".join(labels)
    return str(segment.get("speaker") or "speaker")


def normalize_vibevoice_segments(value: Any) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    collect_vibevoice_segments(value, segments, speaker_hint=None)
    return dedupe_segments(segments)


def collect_vibevoice_segments(value: Any, segments: list[dict[str, Any]], *, speaker_hint: str | None) -> None:
    if isinstance(value, list):
        for item in value:
            collect_vibevoice_segments(item, segments, speaker_hint=speaker_hint)
        return
    if not isinstance(value, dict):
        return
    if looks_like_segment(value):
        segment = segment_from_mapping(value, speaker_hint=speaker_hint)
        if segment is not None:
            segments.append(segment)
            return
    for key, child in value.items():
        next_speaker = speaker_hint
        if isinstance(key, str) and key.strip().lower().startswith(("speaker", "spk")):
            next_speaker = key.strip()
        collect_vibevoice_segments(child, segments, speaker_hint=next_speaker)


def looks_like_segment(value: dict[str, Any]) -> bool:
    return mapping_has_any(value, "start", "start_time", "begin", "from") and mapping_has_any(
        value, "end", "end_time", "stop", "to"
    )


def segment_from_mapping(value: dict[str, Any], *, speaker_hint: str | None) -> dict[str, Any] | None:
    start = first_value(value, "start", "start_time", "begin", "from")
    end = first_value(value, "end", "end_time", "stop", "to")
    text = first_value(value, "text", "content", "transcript", "utterance")
    if text is None:
        return None
    start_seconds = parse_timestamp_seconds(start)
    end_seconds = parse_timestamp_seconds(end)
    if start_seconds is None or end_seconds is None or end_seconds <= start_seconds:
        return None
    speaker_value = first_value(value, "speaker", "speaker_id", "speaker_name", "who", "label")
    speaker = normalize_transcript_speaker(speaker_value if speaker_value not in (None, "") else speaker_hint)
    return {
        "start": start_seconds,
        "end": end_seconds,
        "speaker": speaker,
        "text": str(text).strip(),
    }


def first_value(value: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in value and value[key] not in (None, ""):
            return value[key]
    lower_keys = {str(key).lower(): key for key in value}
    for key in keys:
        actual = lower_keys.get(key.lower())
        if actual is not None and value[actual] not in (None, ""):
            return value[actual]
    return None


def mapping_has_any(value: dict[str, Any], *keys: str) -> bool:
    lower_keys = {str(key).lower() for key in value}
    return any(key in value or key.lower() in lower_keys for key in keys)


def dedupe_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[float, float, str | None, str]] = set()
    output: list[dict[str, Any]] = []
    for item in sorted(segments, key=lambda segment: (float(segment["start"]), float(segment["end"]))):
        key = (
            round(float(item["start"]), 3),
            round(float(item["end"]), 3),
            item.get("speaker"),
            str(item.get("text") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def flatten_transcription_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [flatten_transcription_text(item) for item in value]
        return "\n".join(item for item in parts if item)
    if isinstance(value, dict):
        segment = segment_from_mapping(value, speaker_hint=None)
        if segment is not None:
            speaker = f"{segment['speaker']}: " if segment.get("speaker") else ""
            return f"{speaker}{segment['text']}".strip()
        for key in ("text", "content", "transcript", "utterance"):
            text = value.get(key)
            if isinstance(text, str) and text.strip():
                return text.strip()
        parts = [flatten_transcription_text(item) for item in value.values()]
        return "\n".join(item for item in parts if item)
    return ""


def parse_vibevoice_text_segments(text: str) -> list[dict[str, Any]]:
    pattern = re.compile(
        r"(?P<start>\\d{1,2}:\\d{2}(?::\\d{2})?(?:\\.\\d+)?)\\s*"
        r"(?:-|–|—|-->|to)\\s*"
        r"(?P<end>\\d{1,2}:\\d{2}(?::\\d{2})?(?:\\.\\d+)?)"
        r"\\s*\\]?\\s*(?P<speaker>(?:Speaker|SPK|Spk)[\\w .:-]*)?[:：]?\\s*(?P<text>.+)"
    )
    segments: list[dict[str, Any]] = []
    for line in text.splitlines():
        match = pattern.search(line.strip())
        if not match:
            continue
        start = parse_timestamp_seconds(match.group("start"))
        end = parse_timestamp_seconds(match.group("end"))
        content = (match.group("text") or "").strip()
        if start is None or end is None or not content:
            continue
        speaker = (match.group("speaker") or "").strip() or None
        segments.append({"start": start, "end": end, "speaker": speaker, "text": content})
    return dedupe_segments(segments)


def extract_response_text(payload: Any) -> str | None:
    if isinstance(payload, dict):
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()
        parts: list[str] = []
        for item in payload.get("output", []) or []:
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []) or []:
                if not isinstance(content, dict):
                    continue
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        if parts:
            return "\n".join(parts)
    if isinstance(payload, str) and payload.strip():
        return payload.strip()
    return None


def normalize_transcript_segments(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    segments: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        start = parse_timestamp_seconds(first_value(item, "start", "start_time", "begin", "from"))
        end = parse_timestamp_seconds(first_value(item, "end", "end_time", "stop", "to"))
        text = first_value(item, "text", "content", "transcript", "utterance")
        if start is None or end is None or not isinstance(text, str):
            continue
        speaker_value = first_value(item, "speaker", "speaker_id", "speaker_name", "who", "label")
        speaker = normalize_transcript_speaker(speaker_value)
        segments.append(
            {
                "start": start,
                "end": end,
                "speaker": speaker,
                "text": text.strip(),
            }
        )
    return dedupe_segments(segments)


def build_audio_timeline(path: Path, transcription: TranscriptionResult) -> dict[str, Any]:
    duration = transcription.duration_seconds or probe_duration_seconds(path)
    speech_segments = transcription.segments
    if not speech_segments and transcription.text.strip() and duration is not None:
        speech_segments = [
            {
                "start": 0.0,
                "end": duration,
                "speaker": None,
                "text": transcription.text.strip(),
            }
        ]
    speech_seconds = sum(max(0.0, float(item["end"]) - float(item["start"])) for item in speech_segments)
    silence_seconds = detect_silence_seconds(path)
    active_non_speech_seconds = None
    if duration is not None:
        active_non_speech_seconds = max(0.0, duration - speech_seconds - (silence_seconds or 0.0))
    return {
        "duration_seconds": duration,
        "speech_seconds": round(speech_seconds, 3) if speech_segments else None,
        "silence_seconds": round(silence_seconds, 3) if silence_seconds is not None else None,
        "music_or_active_non_speech_seconds": (
            round(active_non_speech_seconds, 3) if active_non_speech_seconds is not None else None
        ),
        "speech_segments": speech_segments,
        "classification_note": (
            "music_or_active_non_speech_seconds is estimated as total duration minus transcribed speech "
            "minus detected silence; it may include music, TV, ambient sound, or other non-speech audio."
        ),
    }


def audio_analysis_context(transcript: str, timeline: dict[str, Any]) -> str:
    lines = ["Audio timeline:"]
    for key in ("duration_seconds", "speech_seconds", "silence_seconds", "music_or_active_non_speech_seconds"):
        value = timeline.get(key)
        if value is not None:
            lines.append(f"- {key}: {value}")
    segments = timeline.get("speech_segments") or []
    if segments:
        lines.append("")
        has_speakers = any(item.get("speaker") for item in segments if isinstance(item, dict))
        lines.append("Diarized dialogue:" if has_speakers else "Speech segments:")
        for item in segments:
            speaker = transcript_segment_speaker_display(item)
            lines.append(f"- {item['start']:.2f}-{item['end']:.2f} {speaker}: {item['text']}")
    lines.append("")
    lines.append("Transcript:")
    lines.append(transcript)
    return "\n".join(lines)


def probe_duration_seconds(path: Path) -> float | None:
    ffprobe = find_executable("ffprobe")
    if not ffprobe:
        return None
    proc = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return parse_float(proc.stdout.strip())


def detect_silence_seconds(path: Path) -> float | None:
    ffmpeg = find_executable("ffmpeg")
    if not ffmpeg:
        return None
    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            "silencedetect=noise=-35dB:d=0.5",
            "-f",
            "null",
            "-",
        ],
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    output = f"{proc.stdout}\n{proc.stderr}"
    durations = [parse_float(match) for match in re.findall(r"silence_duration:\s*([0-9.]+)", output)]
    values = [value for value in durations if value is not None]
    if not values and proc.returncode != 0:
        return None
    return float(sum(values))


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def parse_timestamp_seconds(value: Any) -> float | None:
    number = parse_float(value)
    if number is not None:
        return number
    if value is None:
        return None
    text = str(value).strip().strip("[]")
    if not text:
        return None
    parts = text.split(":")
    try:
        if len(parts) == 2:
            minutes, seconds = parts
            return int(minutes) * 60 + float(seconds)
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except ValueError:
        return None
    return None


def multipart_body(
    boundary: str,
    *,
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]],
) -> bytes:
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    for name, (filename, data, content_type) in files.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                (
                    f'Content-Disposition: form-data; name="{name}"; '
                    f'filename="{filename}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
                data,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks)


def observation_for_file(
    settings: Settings,
    path: Path,
    analysis: dict[str, Any],
    *,
    force: bool,
    source_path: Path | None = None,
) -> Observation:
    observed_path = source_path.expanduser().resolve() if source_path else path
    stat_path = observed_path if observed_path.exists() and observed_path.is_file() else path
    stat = stat_path.stat()
    observed_at = local_iso(from_timestamp(stat.st_mtime, settings.timezone))
    metadata = {
        "path": str(observed_path),
        "file_size": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
        "analysis_kind": analysis.get("kind"),
        "analysis_backend": analysis_source_name(settings),
        analysis_source_name(settings): analysis.get("metadata") or {},
        "force": force,
    }
    if observed_path != path:
        metadata["analysis_copy_path"] = str(path)
    body = analysis.get("summary")
    transcript = analysis.get("transcript")
    if transcript:
        metadata["transcript"] = transcript
    return Observation(
        source=analysis_source_name(settings),
        kind="media_analysis",
        source_key=file_source_key(observed_path, stat.st_mtime, stat.st_size),
        observed_at=observed_at,
        title=f"Analysis: {observed_path.name}",
        body=body,
        url=observed_path.as_uri(),
        metadata=metadata,
    )


def file_source_key(path: Path, mtime: float, size: int) -> str:
    raw = f"{path.resolve()}|{mtime}|{size}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def observation_source_path(path: Path, observation_paths: Mapping[Path, Path] | None) -> Path | None:
    if not observation_paths:
        return None
    return observation_paths.get(path) or observation_paths.get(path.resolve())


def data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type(path)};base64,{encoded}"


def mime_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed:
        return guessed
    suffix = path.suffix.lower()
    if suffix == ".m4a":
        return "audio/mp4"
    if suffix in (".md", ".txt"):
        return "text/plain"
    return "application/octet-stream"


def assert_size(path: Path, max_mb: float) -> None:
    size = path.stat().st_size
    max_bytes = int(max_mb * 1024 * 1024)
    if size > max_bytes:
        raise RuntimeError(f"{path.name} is {size} bytes, larger than configured {max_mb:g} MB limit")


def default_image_prompt(settings: Settings, path: Path) -> str:
    return (
        f"{summary_prompt(settings)}\n\n"
        f"Analyze this image for a personal memory timeline. File: {path.name}"
    )


def default_file_prompt(settings: Settings, path: Path) -> str:
    return (
        f"{summary_prompt(settings)}\n\n"
        f"Analyze this file for a personal memory timeline. File: {path.name}"
    )


def summary_prompt(settings: Settings) -> str:
    return local_summary_prompt(settings) if use_local_ai(settings) else str(settings.openai_analysis.get("summary_prompt", ""))


def local_summary_prompt(settings: Settings) -> str:
    return str(
        settings.local_ai.get("summary_prompt")
        or settings.openai_analysis.get("summary_prompt")
        or "Summarize the content for a personal memory timeline."
    )


def local_text_model(settings: Settings) -> str:
    return str(settings.local_ai.get("text_model") or "qwen3.5:35b")


def audio_summary_model(settings: Settings) -> str:
    value = str(settings.audio_analysis.get("summary_model") or "").strip()
    return value or local_text_model(settings)


def local_vision_model(settings: Settings) -> str:
    return str(settings.local_ai.get("vision_model") or local_text_model(settings))


def local_transcription_backend(settings: Settings) -> str:
    return str(settings.local_ai.get("transcription_backend") or "mlx_audio").strip().lower()


def local_transcription_model(settings: Settings) -> str:
    model = str(settings.local_ai.get("transcription_model") or "mlx-community/Qwen3-ASR-1.7B-8bit").strip()
    return model


def local_speaker_diarization_backend(settings: Settings) -> str:
    return str(settings.local_ai.get("speaker_diarization_backend") or "vibevoice_mlx").strip().lower()


def local_speaker_diarization_model(settings: Settings) -> str:
    model = str(settings.local_ai.get("speaker_diarization_model") or "mlx-community/VibeVoice-ASR-4bit").strip()
    aliases = {
        "VibeVoice-ASR-4bit": "mlx-community/VibeVoice-ASR-4bit",
        "vibevoice-asr-4bit": "mlx-community/VibeVoice-ASR-4bit",
        "VibeVoice-ASR-HF": "microsoft/VibeVoice-ASR-HF",
        "vibevoice-asr-hf": "microsoft/VibeVoice-ASR-HF",
    }
    return aliases.get(model, model)


def local_ai_bool(settings: Settings, key: str, default: bool) -> bool:
    value = settings.local_ai.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def analysis_model(settings: Settings) -> str:
    return str(settings.openai_analysis.get("analysis_model") or "gpt-5.5")


def transcription_model(settings: Settings) -> str:
    return str(settings.openai_analysis.get("transcription_model") or "gpt-4o-transcribe-diarize")


def transcription_response_format(settings: Settings, model: str) -> str:
    configured = str(settings.openai_analysis.get("transcription_response_format") or "").strip()
    if configured and configured != "auto":
        return configured
    if "diarize" in model:
        return "diarized_json"
    return "json"


def transcription_base_url(settings: Settings) -> str:
    configured = str(settings.openai_analysis.get("transcription_base_url") or "").strip()
    return configured or OPENAI_BASE_URL
