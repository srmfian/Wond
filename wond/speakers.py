from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
import re
import subprocess
from pathlib import Path
from typing import Any

from .audio_preprocessing import audio_preprocessing_config, audio_quality, create_enhanced_sample_clip, create_overlap_candidate_clip
from .config import Settings
from .executables import find_executable
from .openai_analysis import parse_structured_transcript_text, transcript_text_from_segments
from .speaker_identity import embedding_model_key, parse_vector, refresh_identity_status, relocate_sample_after_merge, speaker_embedding, update_speaker_identity_for_sample
from .store import Store
from .timeutil import utc_iso


NON_SPEECH_MARKERS = {
    "silence",
    "music",
    "environmental sounds",
    "environmental sound",
    "unintelligible speech",
    "human sounds",
    "human sound",
    "speech",
    "noise",
    "background noise",
    "applause",
    "laughter",
    "lyric",
}


@dataclass
class SpeakerSampleRepairResult:
    scanned: int = 0
    repaired: int = 0
    skipped: int = 0
    deleted_samples: int = 0
    failed: int = 0
    messages: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        return [
            f"Scanned: {self.scanned}",
            f"Repaired: {self.repaired}",
            f"Skipped: {self.skipped}",
            f"Deleted old samples: {self.deleted_samples}",
            f"Failed: {self.failed}",
            *self.messages,
        ]


@dataclass
class VadChunkCollapseResult:
    scanned_groups: int = 0
    merge_groups: int = 0
    merged_speakers: int = 0
    skipped_groups: int = 0
    messages: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        return [
            f"Scanned groups: {self.scanned_groups}",
            f"Merge groups: {self.merge_groups}",
            f"Merged speakers: {self.merged_speakers}",
            f"Skipped groups: {self.skipped_groups}",
            *self.messages,
        ]


@dataclass
class SpeakerSampleTextRepairResult:
    scanned: int = 0
    repaired: int = 0
    skipped: int = 0
    failed: int = 0
    messages: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        return [
            f"Scanned: {self.scanned}",
            f"Repaired: {self.repaired}",
            f"Skipped: {self.skipped}",
            f"Failed: {self.failed}",
            *self.messages,
        ]


@dataclass
class SpeakerSampleClipRepairResult:
    scanned: int = 0
    repaired: int = 0
    reembedded: int = 0
    skipped: int = 0
    failed: int = 0
    source_key_conflicts: int = 0
    messages: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        return [
            f"Scanned: {self.scanned}",
            f"Repaired clips: {self.repaired}",
            f"Recomputed embeddings: {self.reembedded}",
            f"Skipped: {self.skipped}",
            f"Source-key conflicts: {self.source_key_conflicts}",
            f"Failed: {self.failed}",
            *self.messages,
        ]


@dataclass
class SpeakerSampleDetachResult:
    sample_id: int
    original_speaker_id: int | None = None
    new_speaker_id: int | None = None
    original_speaker_name: str | None = None
    new_speaker_name: str | None = None
    sample_path: str | None = None
    failed: bool = False
    messages: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        status = "Failed" if self.failed else "Detached"
        if self.original_speaker_id and self.new_speaker_id:
            head = (
                f"{status} sample {self.sample_id}: "
                f"{self.original_speaker_name or self.original_speaker_id} -> "
                f"{self.new_speaker_name or self.new_speaker_id}"
            )
        else:
            head = f"{status} sample {self.sample_id}"
        return [head, *self.messages]


@dataclass
class SpeakerSampleConfidenceRefreshResult:
    scanned_speakers: int = 0
    refreshed_speakers: int = 0
    updated_samples: int = 0
    skipped_samples: int = 0
    failed: int = 0
    messages: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        return [
            f"Scanned speakers: {self.scanned_speakers}",
            f"Refreshed speakers: {self.refreshed_speakers}",
            f"Updated samples: {self.updated_samples}",
            f"Skipped samples: {self.skipped_samples}",
            f"Failed speakers: {self.failed}",
            *self.messages,
        ]


@dataclass
class SpeakerAutoOrganizeResult:
    threshold: float
    scanned_pairs: int = 0
    merge_candidates: int = 0
    merged_speakers: int = 0
    hidden_speakers: int = 0
    moved_sample_files: int = 0
    refreshed_samples: int = 0
    failed: int = 0
    messages: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        return [
            f"Threshold: {self.threshold:.3f}",
            f"Scanned pairs: {self.scanned_pairs}",
            f"Merge candidates: {self.merge_candidates}",
            f"Merged speakers: {self.merged_speakers}",
            f"Hidden low-similarity speakers: {self.hidden_speakers}",
            f"Moved sample files: {self.moved_sample_files}",
            f"Refreshed samples: {self.refreshed_samples}",
            f"Failed: {self.failed}",
            *self.messages,
        ]


@dataclass
class SpeakerSampleRegroupResult:
    selected_samples: int = 0
    reset_samples: int = 0
    recut_samples: int = 0
    reembedded_samples: int = 0
    skipped_samples: int = 0
    deleted_empty_speakers: int = 0
    failed: int = 0
    organize: SpeakerAutoOrganizeResult | None = None
    messages: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        lines = [
            f"Selected samples: {self.selected_samples}",
            f"Reset to single-sample voices: {self.reset_samples}",
            f"Recut samples: {self.recut_samples}",
            f"Recomputed embeddings: {self.reembedded_samples}",
            f"Skipped samples: {self.skipped_samples}",
            f"Deleted empty old speakers: {self.deleted_empty_speakers}",
            f"Failed: {self.failed}",
        ]
        if self.organize is not None:
            lines.extend(
                [
                    f"Auto-organize threshold: {self.organize.threshold:.3f}",
                    f"Auto-organize merged speakers: {self.organize.merged_speakers}",
                    f"Auto-organize hidden speakers: {self.organize.hidden_speakers}",
                    f"Auto-organize refreshed samples: {self.organize.refreshed_samples}",
                ]
            )
        return [*lines, *self.messages]


@dataclass
class SpeakerReviewMarkResult:
    updated: int = 0
    missing: int = 0
    messages: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        return [
            f"Updated speakers: {self.updated}",
            f"Missing speakers: {self.missing}",
            *self.messages,
        ]


@dataclass
class SpeakerEmbeddingRepairResult:
    scanned_samples: int = 0
    repaired_samples: int = 0
    skipped_samples: int = 0
    failed_samples: int = 0
    messages: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        return [
            f"Scanned samples: {self.scanned_samples}",
            f"Repaired embeddings: {self.repaired_samples}",
            f"Skipped samples: {self.skipped_samples}",
            f"Failed samples: {self.failed_samples}",
            *self.messages,
        ]


@dataclass
class SpeakerRepresentativeRefreshResult:
    scanned_speakers: int = 0
    updated_speakers: int = 0
    representative_samples: int = 0
    messages: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        return [
            f"Scanned speakers: {self.scanned_speakers}",
            f"Updated speakers: {self.updated_speakers}",
            f"Representative samples: {self.representative_samples}",
            *self.messages,
        ]


@dataclass
class SpeakerHiddenRevivalResult:
    scanned_speakers: int = 0
    candidates: int = 0
    revived: int = 0
    messages: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        return [
            f"Scanned hidden speakers: {self.scanned_speakers}",
            f"Revival candidates: {self.candidates}",
            f"Revived speakers: {self.revived}",
            *self.messages,
        ]


@dataclass
class SpeakerMatchResolveResult:
    match_id: int
    action: str
    updated: bool = False
    merged: bool = False
    failed: bool = False
    messages: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        status = "Failed" if self.failed else "Resolved"
        return [f"{status} match {self.match_id}: {self.action}", *self.messages]


def process_speakers_for_observation(
    settings: Settings,
    store: Store,
    *,
    observation_id: int,
    source_key: str,
    media_path: Path | None,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    config = settings.speaker_recognition
    if not bool(config.get("enabled", True)):
        return metadata

    analysis = metadata.get("audio_analysis")
    if not isinstance(analysis, dict):
        return metadata
    timeline = analysis.get("audio_timeline")
    if not isinstance(timeline, dict):
        return metadata
    segments = timeline.get("speech_segments")
    if not isinstance(segments, list):
        return metadata

    by_label: dict[str, dict[str, Any]] = {}
    speech_like_count = 0
    unlabeled_speech_count = 0
    overlapped_speech_count = 0
    overlap_segments: list[dict[str, Any]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        if not segment_is_speech_like(segment):
            continue
        speech_like_count += 1
        if segment_is_overlapping_speech(segment):
            overlapped_speech_count += 1
            overlap_segments.append(segment)
            continue
        label = normalize_speaker_label(segment.get("speaker"))
        if not label:
            unlabeled_speech_count += 1
            continue
        scope = normalize_speaker_scope(segment.get("speaker_scope"))
        group_label = speaker_group_label(settings, label, scope)
        group = by_label.setdefault(
            group_label,
            {
                "label": label,
                "scope": scope if group_label != label else None,
                "scopes": [],
                "segments": [],
            },
        )
        if scope and scope not in group["scopes"]:
            group["scopes"].append(scope)
        group["segments"].append(segment)

    if not by_label:
        overlap_candidates = create_overlap_candidate_samples(
            settings,
            store,
            observation_id=observation_id,
            source_key=source_key,
            media_path=media_path,
            segments=overlap_segments,
            speaker_targets={},
            duration_seconds=parse_seconds(timeline.get("duration_seconds")),
        )
        analysis.pop("speakers", None)
        if overlap_candidates:
            analysis["speaker_overlap_candidates"] = overlap_candidates
        if overlapped_speech_count:
            analysis["speaker_processing"] = {
                "status": "skipped_overlapping_speech_segments",
                "processed_at": utc_iso(),
                "speech_like_segments": speech_like_count,
                "overlapped_speech_segments": overlapped_speech_count,
                "unlabeled_speech_segments": unlabeled_speech_count,
                "overlap_candidate_samples": count_ok_candidates(overlap_candidates),
                "note": "Speech-like segments had overlapping speaker labels, so they were kept for display but not used as speaker samples.",
            }
        elif speech_like_count:
            analysis["speaker_processing"] = {
                "status": "skipped_no_speaker_labels",
                "processed_at": utc_iso(),
                "speech_like_segments": speech_like_count,
                "unlabeled_speech_segments": unlabeled_speech_count,
                "note": "Speech-like segments were found, but the transcription backend did not emit speaker labels.",
            }
        else:
            analysis["speaker_processing"] = {
                "status": "skipped_no_speech_like_segments",
                "processed_at": utc_iso(),
                "speech_like_segments": 0,
                "note": "Only silence, music, lyrics, non-speech markers, or repeated hallucinated text was found.",
            }
        metadata["audio_analysis"] = analysis
        return metadata

    processed: list[dict[str, Any]] = []
    speaker_targets: dict[str, dict[str, Any]] = {}
    for group_label, group in sorted(by_label.items()):
        label = str(group["label"])
        scope = group.get("scope")
        scopes = list(group.get("scopes") or [])
        label_segments = group["segments"]
        alias = observation_speaker_alias(observation_id, group_label)
        speaker = store.ensure_speaker_for_alias(
            alias,
            default_name=default_speaker_name(label),
            label=label,
            metadata={
                "observation_id": observation_id,
                "source_key": source_key,
                "alias_type": "diarized_observation_speaker",
                "speaker_scope": scope,
                "speaker_scopes": scopes,
            },
        )
        speaker_id = int(speaker["id"])
        speaker_name = str(speaker["display_name"])
        for scoped_label in scoped_alias_labels(label, scopes, group_label):
            store.add_speaker_alias(
                speaker_id,
                observation_speaker_alias(observation_id, scoped_label),
                label=label,
                metadata={
                    "observation_id": observation_id,
                    "source_key": source_key,
                    "alias_type": "diarized_observation_speaker_scope",
                    "speaker_scope": scoped_label_scope(scoped_label),
                    "canonical_group_label": group_label,
                },
            )

        best = best_sample_segment(label_segments)
        sample = create_sample_for_segment(
            settings,
            store,
            speaker_id=speaker_id,
            observation_id=observation_id,
            source_key=source_key,
            label=group_label,
            media_path=media_path,
            segment=best,
            duration_seconds=parse_seconds(timeline.get("duration_seconds")),
        )
        identity = update_speaker_identity_for_sample(
            settings,
            store,
            speaker_id=speaker_id,
            sample_id=sample.get("sample_id"),
            sample_path=sample.get("sample_path"),
        )
        speaker_id = identity.speaker_id
        refreshed_speaker = store.get_speaker(speaker_id)
        if refreshed_speaker is not None:
            speaker_name = str(refreshed_speaker["display_name"])
        speaker_targets[label] = {
            "speaker_id": speaker_id,
            "speaker_name": speaker_name,
            "group_label": group_label,
            "scope": scope,
            "scopes": scopes,
        }
        speaker_targets[group_label] = speaker_targets[label]

        for segment in label_segments:
            segment["speaker_id"] = speaker_id
            segment["speaker_name"] = speaker_name
            segment["speaker_alias"] = alias
            segment["speaker_local_label"] = label
            segment["speaker_group_label"] = group_label
            segment["speaker_identity_status"] = identity.status
            if identity.score is not None:
                segment["speaker_identity_score"] = round(identity.score, 4)

        processed.append(
            {
                "speaker_id": speaker_id,
                "speaker_name": speaker_name,
                "local_label": label,
                "speaker_scope": scope,
                "speaker_scopes": scopes,
                "speaker_group_label": group_label,
                "alias": alias,
                "turn_count": len(label_segments),
                "sample_path": sample.get("sample_path"),
                "sample_start_seconds": sample.get("start_seconds"),
                "sample_end_seconds": sample.get("end_seconds"),
                "sample_status": sample.get("status"),
                "sample_error": sample.get("error"),
                "identity_status": identity.status,
                "identity_score": round(identity.score, 4) if identity.score is not None else None,
                "identity_confidence": (
                    round(identity.confidence, 4) if identity.confidence is not None else None
                ),
                "matched_speaker_id": identity.target_speaker_id,
                "identity_message": identity.message,
            }
        )

    overlap_candidates = create_overlap_candidate_samples(
        settings,
        store,
        observation_id=observation_id,
        source_key=source_key,
        media_path=media_path,
        segments=overlap_segments,
        speaker_targets=speaker_targets,
        duration_seconds=parse_seconds(timeline.get("duration_seconds")),
    )
    analysis["speakers"] = processed
    if overlap_candidates:
        analysis["speaker_overlap_candidates"] = overlap_candidates
    analysis["speaker_processing"] = {
        "status": "ok",
        "processed_at": utc_iso(),
        "overlapped_speech_segments": overlapped_speech_count,
        "overlap_candidate_samples": count_ok_candidates(overlap_candidates),
        "note": "Local diarization labels are only stable within one recording; speaker_name is the global voice id or user name.",
    }
    metadata["audio_analysis"] = analysis
    return metadata


def create_sample_for_segment(
    settings: Settings,
    store: Store,
    *,
    speaker_id: int,
    observation_id: int,
    source_key: str,
    label: str,
    media_path: Path | None,
    segment: dict[str, Any] | None,
    duration_seconds: float | None,
) -> dict[str, Any]:
    if segment is None:
        return {
            "status": "missing_segment",
            "sample_path": None,
            "start_seconds": None,
            "end_seconds": None,
        }

    start = parse_seconds(segment.get("start"))
    end = parse_seconds(segment.get("end"))
    full_transcript = text_value(segment.get("text"), limit=2000)
    clip = clip_bounds(
        start,
        end,
        duration_seconds=duration_seconds,
        sample_seconds=speaker_sample_seconds(settings),
        sample_min_seconds=speaker_sample_min_seconds(settings),
        boundary_guard_seconds=speaker_sample_boundary_guard_seconds(settings),
        long_segment_anchor=speaker_sample_long_segment_anchor(settings),
    )
    transcript = sample_transcript_for_clip(segment, clip)
    sample_source_key = speaker_sample_source_key(observation_id, label, clip[0] if clip else None, clip[1] if clip else None)

    sample_path = None
    status = "metadata_only"
    error = None
    preprocessing_metadata: dict[str, Any] | None = None
    quality: dict[str, Any] | None = None
    if clip and media_path is not None and media_path.exists():
        output = sample_output_path(settings, speaker_id, observation_id, label, clip[0], clip[1])
        extracted = False
        if cfg_bool(audio_preprocessing_config(settings), "speaker_samples_enabled", True):
            extracted, preprocessing_metadata = create_enhanced_sample_clip(settings, media_path, output, clip[0], clip[1])
        if not extracted:
            extracted = extract_audio_clip(media_path, output, clip[0], clip[1])
            if preprocessing_metadata is None:
                preprocessing_metadata = {"status": "disabled_or_unavailable"}
        if extracted:
            quality = audio_quality(settings, output, min_seconds=parse_seconds(settings.speaker_recognition.get("sample_min_seconds")) or 0.5)
            if quality.get("ok"):
                sample_path = str(output)
                status = "ok"
            else:
                output.unlink(missing_ok=True)
                status = "quality_rejected"
                error = str(quality.get("reason") or "quality_gate_failed")
        else:
            status = "sample_failed"
            error = "ffmpeg could not extract sample"
    elif media_path is None:
        status = "missing_media_path"
    elif not media_path.exists():
        status = "missing_file"
        error = str(media_path)

    row = store.add_speaker_sample(
        speaker_id=speaker_id,
        observation_id=observation_id,
        source_key=sample_source_key,
        media_path=str(media_path) if media_path is not None else None,
        sample_path=sample_path,
        start_seconds=clip[0] if clip else start,
        end_seconds=clip[1] if clip else end,
        transcript=transcript,
        metadata={
            "local_label": label,
            "status": status,
            "error": error,
            "audio_preprocessing": preprocessing_metadata,
            "quality": quality,
            "source_segment_transcript": full_transcript if full_transcript != transcript else None,
            "source_segment_start": start,
            "source_segment_end": end,
            "clip_start_seconds": clip[0] if clip else start,
            "clip_end_seconds": clip[1] if clip else end,
            "sample_transcript_mode": "clip_window_excerpt" if full_transcript != transcript else "full_segment",
            "boundary_policy": "inside_single_speaker_segment_only",
            "clip_strategy": {
                "long_segment_anchor": speaker_sample_long_segment_anchor(settings),
                "sample_seconds": speaker_sample_seconds(settings),
                "boundary_guard_seconds": speaker_sample_boundary_guard_seconds(settings),
            },
        },
    )
    return {
        "sample_id": row["id"],
        "status": status,
        "error": error,
        "sample_path": row["sample_path"],
        "start_seconds": row["start_seconds"],
        "end_seconds": row["end_seconds"],
    }


def create_overlap_candidate_samples(
    settings: Settings,
    store: Store,
    *,
    observation_id: int,
    source_key: str,
    media_path: Path | None,
    segments: list[dict[str, Any]],
    speaker_targets: dict[str, dict[str, Any]],
    duration_seconds: float | None,
) -> list[dict[str, Any]]:
    cfg = audio_preprocessing_config(settings)
    if not cfg_bool(cfg, "overlap_separation_enabled", True) or not segments:
        return []
    create_new = cfg_bool(cfg, "overlap_create_new_speakers", False)
    results: list[dict[str, Any]] = []
    for segment_index, segment in enumerate(segments, start=1):
        labels = normalized_overlap_labels(segment)
        if len(labels) < 2:
            continue
        start = parse_seconds(segment.get("start"))
        end = parse_seconds(segment.get("end"))
        clip = clip_bounds(
            start,
            end,
            duration_seconds=duration_seconds,
            sample_seconds=speaker_sample_seconds(settings),
            sample_min_seconds=speaker_sample_min_seconds(settings),
            boundary_guard_seconds=speaker_sample_boundary_guard_seconds(settings),
            long_segment_anchor=speaker_sample_long_segment_anchor(settings),
        )
        if clip is None:
            results.append({"status": "skipped_invalid_bounds", "labels": labels, "segment_index": segment_index})
            continue
        if media_path is None or not media_path.exists():
            results.append({"status": "skipped_missing_media", "labels": labels, "segment_index": segment_index})
            continue
        for label_index, label in enumerate(labels):
            target = speaker_targets.get(label)
            if target is None and create_new:
                target = ensure_overlap_speaker_target(
                    store,
                    observation_id=observation_id,
                    source_key=source_key,
                    label=label,
                )
            if target is None:
                results.append(
                    {
                        "status": "skipped_no_anchor_speaker",
                        "local_label": label,
                        "segment_index": segment_index,
                        "reason": "No clean speaker sample exists for this local label; overlap_create_new_speakers is disabled.",
                    }
                )
                continue

            speaker_id = int(target["speaker_id"])
            output = overlap_sample_output_path(settings, speaker_id, observation_id, label, clip[0], clip[1], label_index)
            separated, separation_metadata = create_overlap_candidate_clip(
                settings,
                media_path,
                output,
                clip[0],
                clip[1],
                stem_index=label_index,
            )
            quality = audio_quality(
                settings,
                output,
                min_seconds=parse_seconds(settings.speaker_recognition.get("sample_min_seconds")) or 0.5,
            ) if separated else None
            if not separated or not quality or not quality.get("ok"):
                output.unlink(missing_ok=True)
                results.append(
                    {
                        "status": "quality_rejected" if separated else "separation_failed",
                        "local_label": label,
                        "speaker_id": speaker_id,
                        "segment_index": segment_index,
                        "separation": separation_metadata,
                        "quality": quality,
                    }
                )
                continue

            sample_key = overlap_candidate_source_key(observation_id, label, clip[0], clip[1], label_index)
            row = store.add_speaker_sample(
                speaker_id=speaker_id,
                observation_id=observation_id,
                source_key=sample_key,
                media_path=str(media_path),
                sample_path=str(output),
                start_seconds=clip[0],
                end_seconds=clip[1],
                transcript=sample_transcript_for_clip(segment, clip),
                metadata={
                    "local_label": label,
                    "status": "overlap_separated_candidate",
                    "sample_role": "overlap_separated_candidate",
                    "overlap_speakers": labels,
                    "source_segment_start": start,
                    "source_segment_end": end,
                    "source_segment_transcript": text_value(segment.get("text"), limit=2000),
                    "sample_transcript_mode": "clip_window_excerpt",
                    "clip_strategy": {
                        "long_segment_anchor": speaker_sample_long_segment_anchor(settings),
                        "sample_seconds": speaker_sample_seconds(settings),
                        "boundary_guard_seconds": speaker_sample_boundary_guard_seconds(settings),
                    },
                    "separation": separation_metadata,
                    "quality": quality,
                },
            )
            identity = update_speaker_identity_for_sample(
                settings,
                store,
                speaker_id=speaker_id,
                sample_id=int(row["id"]),
                sample_path=str(output),
            )
            results.append(
                {
                    "status": "ok",
                    "local_label": label,
                    "speaker_id": identity.speaker_id,
                    "speaker_name": target.get("speaker_name"),
                    "sample_id": int(row["id"]),
                    "sample_path": str(output),
                    "start_seconds": clip[0],
                    "end_seconds": clip[1],
                    "identity_status": identity.status,
                    "identity_score": round(identity.score, 4) if identity.score is not None else None,
                    "matched_speaker_id": identity.target_speaker_id,
                    "segment_index": segment_index,
                    "separation": separation_metadata,
                    "quality": quality,
                }
            )
    return results


def ensure_overlap_speaker_target(
    store: Store,
    *,
    observation_id: int,
    source_key: str,
    label: str,
) -> dict[str, Any]:
    alias = observation_speaker_alias(observation_id, f"overlap:{label}")
    speaker = store.ensure_speaker_for_alias(
        alias,
        default_name=default_speaker_name(label),
        label=label,
        metadata={
            "observation_id": observation_id,
            "source_key": source_key,
            "alias_type": "overlap_separated_candidate_speaker",
        },
    )
    return {"speaker_id": int(speaker["id"]), "speaker_name": str(speaker["display_name"]), "group_label": label}


def normalized_overlap_labels(segment: dict[str, Any]) -> list[str]:
    raw = segment.get("overlap_speakers")
    if not isinstance(raw, list):
        return []
    labels: list[str] = []
    for item in raw:
        label = normalize_speaker_label(item)
        if label and label not in labels:
            labels.append(label)
    return labels


def count_ok_candidates(candidates: list[dict[str, Any]]) -> int:
    return sum(1 for item in candidates if isinstance(item, dict) and item.get("status") == "ok")


def repair_speaker_sample_text(
    settings: Settings,
    store: Store,
    *,
    apply: bool = False,
    limit: int | None = None,
) -> SpeakerSampleTextRepairResult:
    result = SpeakerSampleTextRepairResult()
    rows = store.conn.execute(
        """
        SELECT
            speaker_samples.*,
            observations.metadata AS observation_metadata
        FROM speaker_samples
        JOIN observations ON observations.id = speaker_samples.observation_id
        ORDER BY speaker_samples.created_at DESC, speaker_samples.id DESC
        """
    ).fetchall()
    for row in rows:
        if limit is not None and result.scanned >= limit:
            break
        result.scanned += 1
        try:
            metadata = json_object(row["metadata"])
            segment = best_segment_for_sample(row, row["observation_metadata"])
            if segment is None:
                result.skipped += 1
                continue
            clip = (parse_seconds(row["start_seconds"]), parse_seconds(row["end_seconds"]))
            if clip[0] is None or clip[1] is None:
                result.skipped += 1
                continue
            repaired = sample_transcript_for_clip(segment, (clip[0], clip[1]))
            if not repaired or repaired == (row["transcript"] or ""):
                result.skipped += 1
                continue
            full_transcript = text_value(segment.get("text"), limit=2000)
            result.repaired += 1
            if apply:
                metadata["source_segment_transcript"] = full_transcript
                metadata["sample_transcript_mode"] = "clip_window_excerpt"
                metadata["sample_text_repaired_at"] = utc_iso()
                store.conn.execute(
                    """
                    UPDATE speaker_samples
                    SET transcript = ?,
                        metadata = ?
                    WHERE id = ?
                    """,
                    (repaired, json.dumps(metadata, ensure_ascii=False, sort_keys=True), int(row["id"])),
                )
            if len(result.messages) < 40:
                verb = "Updated" if apply else "Would update"
                result.messages.append(f"- {verb} sample {row['id']}: {shorten_text(row['transcript'], 48)} -> {shorten_text(repaired, 48)}")
        except Exception as exc:
            result.failed += 1
            if len(result.messages) < 40:
                result.messages.append(f"- Failed sample {row['id']}: {exc}")
    if apply and result.repaired:
        store.conn.commit()
    return result


def repair_speaker_sample_clips(
    settings: Settings,
    store: Store,
    *,
    apply: bool = False,
    limit: int | None = None,
    speaker_ids: list[int] | None = None,
    sample_ids: list[int] | None = None,
) -> SpeakerSampleClipRepairResult:
    result = SpeakerSampleClipRepairResult()
    model = embedding_model_key(settings)
    run_at = utc_iso()
    speaker_filter = set(speaker_ids or [])
    sample_filter = set(sample_ids or [])
    rows = store.conn.execute(
        """
        SELECT
            speaker_samples.*,
            speakers.display_name AS speaker_name,
            observations.metadata AS observation_metadata
        FROM speaker_samples
        JOIN speakers ON speakers.id = speaker_samples.speaker_id
        LEFT JOIN observations ON observations.id = speaker_samples.observation_id
        ORDER BY speaker_samples.created_at DESC, speaker_samples.id DESC
        """
    ).fetchall()

    for row in rows:
        sample_id = int(row["id"])
        speaker_id = int(row["speaker_id"])
        if speaker_filter and speaker_id not in speaker_filter:
            continue
        if sample_filter and sample_id not in sample_filter:
            continue
        if limit is not None and result.scanned >= limit:
            break
        result.scanned += 1

        metadata = json_object(row["metadata"])
        if metadata.get("sample_role") in {"mixed_parent_archived", "overlap_separated_candidate"}:
            result.skipped += 1
            continue

        try:
            plan = speaker_sample_clip_plan(settings, row)
            if not plan.get("ok"):
                result.skipped += 1
                if len(result.messages) < 40:
                    result.messages.append(f"- Skipped sample {sample_id}: {plan.get('status')}")
                continue

            desired_clip = plan["clip"]
            desired_transcript = plan.get("transcript")
            desired_source_key = str(plan.get("source_key") or row["source_key"])
            source_key, source_key_conflict = source_key_for_sample_update(store, sample_id, row["source_key"], desired_source_key)
            if source_key_conflict:
                result.source_key_conflicts += 1

            window_changed = sample_clip_window_changed(row, desired_clip)
            transcript_changed = (desired_transcript or "") != (row["transcript"] or "")
            source_key_changed = source_key != row["source_key"]
            metadata_changed = sample_clip_metadata_needs_update(metadata, plan)
            if not any((window_changed, transcript_changed, source_key_changed, metadata_changed, source_key_conflict)):
                result.skipped += 1
                continue

            if window_changed and sample_source_audio_path(row, json_object(row["observation_metadata"])) is None:
                result.skipped += 1
                if len(result.messages) < 40:
                    result.messages.append(f"- Skipped sample {sample_id}: missing source audio for recut")
                continue

            if not apply:
                result.repaired += 1
                if len(result.messages) < 40:
                    result.messages.append(
                        "- Would repair sample "
                        f"{sample_id}: {format_sample_window(row)} -> {desired_clip[0]:.2f}-{desired_clip[1]:.2f}s"
                    )
                continue

            next_sample_path = str(row["sample_path"] or "").strip() or None
            next_start = desired_clip[0]
            next_end = desired_clip[1]
            next_transcript = desired_transcript
            recut_metadata: dict[str, Any] | None = None
            embedding_ready = False

            if window_changed:
                recut_result = recut_existing_speaker_sample(settings, row, new_speaker_id=speaker_id)
                recut_metadata = recut_result.metadata
                if not recut_result.ok or recut_result.sample_path is None:
                    result.failed += 1
                    if len(result.messages) < 40:
                        result.messages.append(f"- Failed sample {sample_id}: {recut_result.metadata.get('status')}")
                    continue
                next_sample_path = str(recut_result.sample_path)
                next_start = recut_result.start_seconds
                next_end = recut_result.end_seconds
                next_transcript = recut_result.transcript
                try:
                    vector = speaker_embedding(settings, recut_result.sample_path)
                    store.add_speaker_embedding(
                        speaker_id=speaker_id,
                        sample_id=sample_id,
                        model=model,
                        vector=vector,
                        metadata={
                            "sample_path": str(recut_result.sample_path),
                            "recomputed_at": run_at,
                            "reason": "sample_clip_repair_recut",
                        },
                    )
                    result.reembedded += 1
                    embedding_ready = True
                except Exception as exc:
                    store.conn.execute("DELETE FROM speaker_embeddings WHERE sample_id = ? AND model = ?", (sample_id, model))
                    metadata["sample_clip_repair_embedding_error"] = str(exc)
            else:
                embedding_ready = True

            metadata.update(
                repaired_sample_clip_metadata(
                    row,
                    plan,
                    run_at=run_at,
                    recut_metadata=recut_metadata,
                    source_key=source_key,
                    source_key_conflict=source_key_conflict,
                    embedding_ready=embedding_ready,
                )
            )
            store.conn.execute(
                """
                UPDATE speaker_samples
                SET source_key = ?,
                    sample_path = ?,
                    start_seconds = ?,
                    end_seconds = ?,
                    transcript = ?,
                    metadata = ?
                WHERE id = ?
                """,
                (
                    source_key,
                    next_sample_path,
                    next_start,
                    next_end,
                    next_transcript,
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    sample_id,
                ),
            )
            result.repaired += 1
            if len(result.messages) < 40:
                result.messages.append(
                    f"- Repaired sample {sample_id}: {format_sample_window(row)} -> {float(next_start):.2f}-{float(next_end):.2f}s"
                )
            if window_changed or result.reembedded:
                refresh_identity_status(settings, store, speaker_id, model)
        except Exception as exc:
            result.failed += 1
            if len(result.messages) < 40:
                result.messages.append(f"- Failed sample {sample_id}: {exc}")

    if apply and (result.repaired or result.reembedded or result.failed):
        store.conn.commit()
    return result


def detach_speaker_sample(
    settings: Settings,
    store: Store,
    *,
    sample_id: int,
    display_name: str | None = None,
) -> SpeakerSampleDetachResult:
    result = SpeakerSampleDetachResult(sample_id=sample_id)
    sample = store.get_speaker_sample(sample_id)
    if sample is None:
        result.failed = True
        result.messages.append(f"- Sample not found: {sample_id}")
        return result

    original_speaker_id = int(sample["speaker_id"])
    result.original_speaker_id = original_speaker_id
    result.original_speaker_name = str(sample["speaker_name"] or original_speaker_id)

    requested_name = str(display_name or "").strip()
    speaker = store.ensure_speaker_for_alias(
        f"manual-detached-sample:{sample_id}",
        default_name=requested_name or "Voice",
        label="manual_detached_sample",
        metadata={
            "alias_type": "manual_detached_sample",
            "sample_id": sample_id,
            "detached_from_speaker_id": original_speaker_id,
            "detached_from_speaker_name": result.original_speaker_name,
        },
    )
    new_speaker_id = int(speaker["id"])
    if requested_name:
        store.rename_speaker(new_speaker_id, requested_name)
        refreshed = store.get_speaker(new_speaker_id)
        if refreshed is not None:
            speaker = refreshed
    result.new_speaker_id = new_speaker_id
    result.new_speaker_name = str(speaker["display_name"] or new_speaker_id)

    if new_speaker_id == original_speaker_id:
        result.messages.append("- Sample was already detached to this speaker.")
        return result

    sample_path = str(sample["sample_path"] or "").strip()
    relocated_path: Path | None = None
    if sample_path:
        relocated_path = relocate_sample_after_merge(sample_path, new_speaker_id)
    next_sample_path = str(relocated_path) if relocated_path is not None else (sample_path or None)
    result.sample_path = next_sample_path

    metadata = json_object(sample["metadata"])
    detached_at = utc_iso()
    metadata.update(
        {
            "sample_role": "manual_detached_sample",
            "detached_at": detached_at,
            "detached_from_speaker_id": original_speaker_id,
            "detached_from_speaker_name": result.original_speaker_name,
            "detached_to_speaker_id": new_speaker_id,
            "detached_to_speaker_name": result.new_speaker_name,
        }
    )
    store.conn.execute(
        """
        UPDATE speaker_samples
        SET speaker_id = ?,
            sample_path = ?,
            metadata = ?
        WHERE id = ?
        """,
        (
            new_speaker_id,
            next_sample_path,
            json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            sample_id,
        ),
    )
    store.conn.execute(
        """
        UPDATE speaker_embeddings
        SET speaker_id = ?
        WHERE sample_id = ?
        """,
        (new_speaker_id, sample_id),
    )
    store.conn.commit()

    model = embedding_model_key(settings)
    for speaker_id in (original_speaker_id, new_speaker_id):
        try:
            refresh_identity_status(settings, store, speaker_id, model)
        except Exception as exc:
            result.messages.append(f"- Refreshed speaker {speaker_id} after detach but confidence update failed: {exc}")
    if relocated_path is not None:
        result.messages.append(f"- Moved sample file: {relocated_path}")
    return result


def refresh_speaker_sample_confidences(
    settings: Settings,
    store: Store,
    *,
    speaker_ids: list[int] | None = None,
) -> SpeakerSampleConfidenceRefreshResult:
    result = SpeakerSampleConfidenceRefreshResult()
    model = embedding_model_key(settings)
    if speaker_ids is None:
        target_ids = [int(row["id"]) for row in store.list_speakers()]
    else:
        target_ids = []
        for speaker_id in speaker_ids:
            if speaker_id > 0 and speaker_id not in target_ids:
                target_ids.append(int(speaker_id))
    result.scanned_speakers = len(target_ids)
    refreshed_at = utc_iso()

    for speaker_id in target_ids:
        try:
            before = store.get_speaker(speaker_id)
            old_confidence = before["confidence"] if before is not None else None
            rows = store.speaker_embedding_rows(model=model, speaker_id=speaker_id)
            vectors: list[tuple[int, list[float]]] = []
            for row in rows:
                sample_id = row["sample_id"]
                if sample_id is None:
                    result.skipped_samples += 1
                    continue
                parsed = parse_vector(row["vector"])
                if parsed is None:
                    result.skipped_samples += 1
                    continue
                vectors.append((int(sample_id), parsed))
            if not vectors:
                refresh_identity_status(settings, store, speaker_id, model, touch_updated_at=False)
                result.refreshed_speakers += 1
                continue

            for sample_id, vector in vectors:
                sample = store.get_speaker_sample(sample_id)
                if sample is None or int(sample["speaker_id"]) != speaker_id:
                    result.skipped_samples += 1
                    continue
                comparison_vectors = [other for other_id, other in vectors if other_id != sample_id]
                confidence = sample_confidence_for_vector(vector, comparison_vectors)
                if confidence is None:
                    result.skipped_samples += 1
                    continue
                metadata = json_object(sample["metadata"])
                metadata.update(
                    {
                        "sample_confidence": round(confidence, 4),
                        "sample_confidence_model": model,
                        "sample_confidence_basis": "leave_one_out_centroid" if comparison_vectors else "single_sample",
                        "sample_confidence_recalculated_at": refreshed_at,
                    }
                )
                store.conn.execute(
                    """
                    UPDATE speaker_samples
                    SET metadata = ?
                    WHERE id = ?
                    """,
                    (json.dumps(metadata, ensure_ascii=False, sort_keys=True), sample_id),
                )
                result.updated_samples += 1
            store.conn.commit()
            confidence = refresh_identity_status(settings, store, speaker_id, model, touch_updated_at=False)
            result.refreshed_speakers += 1
            if len(result.messages) < 30:
                result.messages.append(
                    f"- Refreshed speaker {speaker_id}: {len(vectors)} sample embedding(s), "
                    f"confidence {format_confidence(old_confidence)} -> {format_confidence(confidence)}."
                )
        except Exception as exc:
            result.failed += 1
            if len(result.messages) < 30:
                result.messages.append(f"- Failed speaker {speaker_id}: {exc}")
    return result


def repair_missing_speaker_embeddings(
    settings: Settings,
    store: Store,
    *,
    apply: bool = False,
    limit: int | None = None,
) -> SpeakerEmbeddingRepairResult:
    result = SpeakerEmbeddingRepairResult()
    model = embedding_model_key(settings)
    rows = store.conn.execute(
        """
        SELECT
            speaker_samples.*,
            speakers.display_name AS speaker_name
        FROM speaker_samples
        JOIN speakers ON speakers.id = speaker_samples.speaker_id
        LEFT JOIN speaker_embeddings
          ON speaker_embeddings.sample_id = speaker_samples.id
         AND speaker_embeddings.model = ?
        WHERE speaker_embeddings.id IS NULL
        ORDER BY speaker_samples.id ASC
        """,
        (model,),
    ).fetchall()
    for row in rows:
        if limit is not None and result.scanned_samples >= limit:
            break
        result.scanned_samples += 1
        sample_id = int(row["id"])
        sample_path = str(row["sample_path"] or "").strip()
        if not sample_path:
            result.skipped_samples += 1
            if len(result.messages) < 40:
                result.messages.append(f"- Skipped sample {sample_id}: no sample_path.")
            continue
        path = Path(sample_path).expanduser()
        if not path.exists():
            result.skipped_samples += 1
            if len(result.messages) < 40:
                result.messages.append(f"- Skipped sample {sample_id}: missing sample file {path}.")
            continue
        if not apply:
            result.repaired_samples += 1
            if len(result.messages) < 40:
                result.messages.append(f"- Would embed sample {sample_id}: {row['speaker_name']}.")
            continue
        try:
            vector = speaker_embedding(settings, path)
            store.add_speaker_embedding(
                speaker_id=int(row["speaker_id"]),
                sample_id=sample_id,
                model=model,
                vector=vector,
                metadata={"sample_path": sample_path, "repaired_at": utc_iso(), "repair": "missing_embedding"},
            )
            metadata = json_object(row["metadata"])
            metadata.update(
                {
                    "embedding_repair_status": "ok",
                    "embedding_repaired_at": utc_iso(),
                    "embedding_model": model,
                }
            )
            update_speaker_sample_metadata(store, sample_id, metadata)
            result.repaired_samples += 1
            if len(result.messages) < 40:
                result.messages.append(f"- Repaired embedding for sample {sample_id}: {row['speaker_name']}.")
        except Exception as exc:
            metadata = json_object(row["metadata"])
            metadata.update(
                {
                    "embedding_repair_status": "failed",
                    "embedding_repair_error": str(exc)[:500],
                    "embedding_repaired_at": utc_iso(),
                    "embedding_model": model,
                }
            )
            update_speaker_sample_metadata(store, sample_id, metadata)
            result.failed_samples += 1
            if len(result.messages) < 40:
                result.messages.append(f"- Failed sample {sample_id}: {exc}")
    if apply and result.repaired_samples:
        refresh = refresh_speaker_sample_confidences(settings, store)
        for line in refresh.messages[:8]:
            if len(result.messages) < 50:
                result.messages.append(line)
    return result


def refresh_representative_speaker_samples(
    store: Store,
    *,
    speaker_ids: list[int] | None = None,
    per_speaker: int = 3,
) -> SpeakerRepresentativeRefreshResult:
    result = SpeakerRepresentativeRefreshResult()
    if speaker_ids is None:
        target_ids = [int(row["id"]) for row in store.list_speakers()]
    else:
        target_ids = unique_positive_ints(speaker_ids)
    max_samples = max(1, int(per_speaker))
    for speaker_id in target_ids:
        row = store.get_speaker(speaker_id)
        if row is None:
            continue
        result.scanned_speakers += 1
        samples = [
            sample
            for sample in store.list_speaker_samples(speaker_id)
            if json_object(sample["metadata"]).get("sample_role") != "mixed_parent_archived"
        ]
        ranked = sorted(samples, key=representative_sample_sort_key)
        selected_ids = {int(sample["id"]) for sample in ranked[:max_samples]}
        changed = False
        for sample in samples:
            sample_id = int(sample["id"])
            metadata = json_object(sample["metadata"])
            before = (metadata.get("representative_sample") is True, metadata.get("representative_rank"))
            if sample_id in selected_ids:
                rank = [int(item["id"]) for item in ranked[:max_samples]].index(sample_id) + 1
                metadata.update(
                    {
                        "representative_sample": True,
                        "representative_rank": rank,
                        "representative_refreshed_at": utc_iso(),
                        "representative_score": round(representative_sample_score(sample), 4),
                    }
                )
                result.representative_samples += 1
            else:
                metadata.pop("representative_sample", None)
                metadata.pop("representative_rank", None)
                metadata.pop("representative_score", None)
            after = (metadata.get("representative_sample") is True, metadata.get("representative_rank"))
            if before != after:
                changed = True
                update_speaker_sample_metadata(store, sample_id, metadata)
        speaker_metadata = json_object(row["metadata"])
        speaker_metadata.update(
            {
                "representative_sample_ids": sorted(selected_ids),
                "representative_samples_refreshed_at": utc_iso(),
            }
        )
        update_speaker_metadata(store, speaker_id, speaker_metadata)
        if changed or selected_ids:
            result.updated_speakers += 1
            if len(result.messages) < 30:
                result.messages.append(
                    f"- Speaker {speaker_id}: selected {len(selected_ids)} representative sample(s)."
                )
    return result


def revive_hidden_speakers(
    store: Store,
    *,
    apply: bool = False,
    min_samples: int = 2,
    min_days: int = 2,
    min_embeddings: int = 2,
) -> SpeakerHiddenRevivalResult:
    result = SpeakerHiddenRevivalResult()
    rows = store.conn.execute(
        """
        SELECT
            speakers.*,
            count(DISTINCT speaker_samples.id) AS sample_count,
            count(DISTINCT speaker_embeddings.id) AS embedding_count,
            count(DISTINCT substr(coalesce(observations.observed_at, speaker_samples.created_at), 1, 10)) AS day_count,
            max(coalesce(observations.observed_at, speaker_samples.created_at)) AS latest_seen_at
        FROM speakers
        LEFT JOIN speaker_samples ON speaker_samples.speaker_id = speakers.id
        LEFT JOIN speaker_embeddings ON speaker_embeddings.speaker_id = speakers.id
        LEFT JOIN observations ON observations.id = speaker_samples.observation_id
        GROUP BY speakers.id
        ORDER BY latest_seen_at DESC, speakers.id DESC
        """
    ).fetchall()
    for row in rows:
        metadata = json_object(row["metadata"])
        hidden = metadata.get("speaker_hidden") is True or metadata.get("speaker_review_status") == "low_similarity_hidden"
        if not hidden:
            continue
        result.scanned_speakers += 1
        sample_count = int(row["sample_count"] or 0)
        day_count = int(row["day_count"] or 0)
        embedding_count = int(row["embedding_count"] or 0)
        reasons: list[str] = []
        if sample_count >= min_samples:
            reasons.append(f"{sample_count} samples")
        if day_count >= min_days:
            reasons.append(f"{day_count} days")
        if embedding_count >= min_embeddings:
            reasons.append(f"{embedding_count} embeddings")
        if not reasons:
            continue
        result.candidates += 1
        if apply:
            metadata.update(
                {
                    "speaker_review_status": "needs_review",
                    "speaker_hidden": False,
                    "revived_at": utc_iso(),
                    "revived_reason": ", ".join(reasons),
                }
            )
            update_speaker_metadata(store, int(row["id"]), metadata)
            result.revived += 1
            prefix = "Revived"
        else:
            prefix = "Would revive"
        if len(result.messages) < 40:
            result.messages.append(f"- {prefix} {speaker_label(row)}: {', '.join(reasons)}.")
    return result


def resolve_speaker_match_decision(
    settings: Settings,
    store: Store,
    *,
    match_id: int,
    action: str,
) -> SpeakerMatchResolveResult:
    normalized_action = str(action or "").strip().lower()
    result = SpeakerMatchResolveResult(match_id=match_id, action=normalized_action)
    if normalized_action not in {"accept", "reject"}:
        result.failed = True
        result.messages.append("- Unsupported action; use accept or reject.")
        return result
    row = store.conn.execute(
        "SELECT * FROM speaker_match_decisions WHERE id = ?",
        (match_id,),
    ).fetchone()
    if row is None:
        result.failed = True
        result.messages.append("- Match decision not found.")
        return result

    metadata = json_object(row["metadata"])
    metadata.update({"reviewed_at": utc_iso(), "review_action": normalized_action})
    source_id = int(row["source_speaker_id"])
    target_id = int(row["target_speaker_id"]) if row["target_speaker_id"] is not None else None
    if normalized_action == "accept":
        target_row = store.get_speaker(target_id) if target_id is not None else None
        source_row = store.get_speaker(source_id)
        if target_row is None:
            result.failed = True
            result.messages.append("- Target speaker is missing; cannot accept this match.")
            update_speaker_match_decision(store, match_id, "accept_failed", metadata)
            return result
        if source_row is not None and source_id != target_id:
            source_samples = store.list_speaker_samples(source_id)
            moved = relocate_speaker_sample_files_after_merge(store, source_samples, target_id)
            if store.merge_speakers(source_id, target_id):
                result.merged = True
                result.messages.append(f"- Merged source speaker {source_id} into {target_id}; moved {moved} sample file(s).")
        mark_speaker_review_status(store, speaker_ids=[target_id], status="confirmed")
        update_speaker_match_decision(store, match_id, "accepted", metadata)
        try:
            refresh_identity_status(settings, store, target_id, embedding_model_key(settings))
        except Exception as exc:
            result.messages.append(f"- Confidence refresh failed after accept: {exc}")
        result.updated = True
        return result

    metadata["rejection_note"] = "manual_reject"
    update_speaker_match_decision(store, match_id, "rejected", metadata)
    if store.get_speaker(source_id) is not None:
        source_metadata = json_object(store.get_speaker(source_id)["metadata"])
        source_metadata.update(
            {
                "speaker_review_status": "needs_review",
                "speaker_hidden": False,
                "match_rejected_at": utc_iso(),
                "rejected_match_id": match_id,
            }
        )
        update_speaker_metadata(store, source_id, source_metadata)
    result.updated = True
    result.messages.append("- Marked match as rejected.")
    return result


def speaker_confidence_summary(row: Any, *, sample_count: int, embedding_count: int) -> dict[str, Any]:
    confidence = row["confidence"] if "confidence" in row.keys() else None
    try:
        confidence_number = float(confidence)
    except (TypeError, ValueError):
        confidence_number = None
    review_status = speaker_review_status(row)
    if sample_count <= 0:
        level = "no_samples"
        label = "无样本"
        detail = "还没有可验证的声音样本。"
    elif embedding_count <= 0:
        level = "missing_embedding"
        label = "缺 embedding"
        detail = "有样本但无法参与自动匹配。"
    elif review_status == "confirmed":
        level = "confirmed"
        label = "已人工确认"
        if confidence_number is None:
            detail = "人物归属已人工确认；embedding 一致性尚未重算。"
        elif confidence_number < 0.68:
            detail = "人物归属已人工确认；当前数值只是 embedding 一致性诊断，可能受多语言、录音条件或短样本影响。"
        else:
            detail = "人物归属已人工确认；一致性分数仅用于后续质量监控。"
    elif sample_count == 1:
        level = "insufficient_evidence"
        label = "样本不足"
        detail = "单样本无法证明聚类稳定，不能当作 100% 一致性。"
    elif confidence_number is None:
        level = "unknown"
        label = "未计算"
        detail = "尚未重算聚类一致性。"
    elif confidence_number < 0.68:
        level = "low"
        label = "低一致性"
        detail = "样本之间 embedding 差异较大，可能是多语言、录音条件、短样本或重叠声音造成；未人工确认时建议复听。"
    else:
        level = "usable"
        label = "可用"
        detail = "有多个样本和 embedding，可用于审核。"
    return {
        "level": level,
        "label": label,
        "detail": detail,
        "value": round(confidence_number, 4) if confidence_number is not None else None,
        "sample_count": sample_count,
        "embedding_count": embedding_count,
    }


def speaker_profiles_payload(store: Store, *, limit: int = 24) -> list[dict[str, Any]]:
    rows = store.list_speakers()
    active = [
        row
        for row in rows
        if str(row["identity_status"] or "") == "named"
        or speaker_review_status(row) in {"confirmed", "auto_merged_pending_review", "needs_review"}
    ]
    active.sort(key=lambda row: (-int(row["sample_count"] or 0), int(row["id"])))
    return [
        speaker_profile_payload(store, int(row["id"]), sample_limit=3, timeline_limit=4)
        for row in active[:limit]
    ]


def speaker_profile_payload(store: Store, speaker_id: int, *, sample_limit: int = 8, timeline_limit: int = 12) -> dict[str, Any]:
    row = store.get_speaker(speaker_id)
    if row is None:
        return {"ok": False, "speaker_id": speaker_id, "error": "speaker_not_found"}
    stats = store.speaker_sample_evidence_stats(speaker_id)
    embedding_count = int(
        store.conn.execute("SELECT count(*) FROM speaker_embeddings WHERE speaker_id = ?", (speaker_id,)).fetchone()[0]
    )
    aliases = [
        {"alias": alias["alias"], "label": alias["label"], "metadata": json_object(alias["metadata"])}
        for alias in store.conn.execute(
            "SELECT alias, label, metadata FROM speaker_aliases WHERE speaker_id = ? ORDER BY id ASC LIMIT 50",
            (speaker_id,),
        ).fetchall()
    ]
    samples = [speaker_sample_payload(sample) for sample in store.list_speaker_samples(speaker_id)[:sample_limit]]
    representative = [
        sample
        for sample in samples
        if (sample.get("metadata") or {}).get("representative_sample") is True
    ]
    return {
        "ok": True,
        "speaker": speaker_payload(row),
        "stats": {key: stats[key] for key in stats.keys()},
        "aliases": aliases,
        "embedding_count": embedding_count,
        "confidence": speaker_confidence_summary(
            row,
            sample_count=int(stats["sample_count"] or 0),
            embedding_count=embedding_count,
        ),
        "representative_samples": representative or samples[:3],
        "samples": samples,
        "timeline": speaker_timeline_items(store, speaker_id, limit=timeline_limit),
    }


def speaker_timeline_items(store: Store, speaker_id: int, *, limit: int = 20) -> list[dict[str, Any]]:
    rows = store.conn.execute(
        """
        SELECT
            speaker_samples.id AS sample_id,
            speaker_samples.start_seconds,
            speaker_samples.end_seconds,
            speaker_samples.transcript,
            speaker_samples.metadata AS sample_metadata,
            observations.id AS observation_id,
            observations.observed_at,
            observations.title,
            observations.subtitle,
            observations.body,
            observations.source,
            observations.kind,
            observations.metadata AS observation_metadata
        FROM speaker_samples
        LEFT JOIN observations ON observations.id = speaker_samples.observation_id
        WHERE speaker_samples.speaker_id = ?
        ORDER BY coalesce(observations.observed_at, speaker_samples.created_at) DESC,
                 speaker_samples.id DESC
        LIMIT ?
        """,
        (speaker_id, limit),
    ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        observation_metadata = json_object(row["observation_metadata"])
        items.append(
            {
                "sample_id": row["sample_id"],
                "observation_id": row["observation_id"],
                "observed_at": row["observed_at"],
                "title": row["title"],
                "subtitle": row["subtitle"],
                "source": row["source"],
                "kind": row["kind"],
                "start_seconds": row["start_seconds"],
                "end_seconds": row["end_seconds"],
                "transcript": row["transcript"],
                "body": shorten_text(str(row["body"] or ""), 500),
                "sample_metadata": compact_speaker_sample_metadata(json_object(row["sample_metadata"])),
                "observation": compact_observation_metadata(observation_metadata),
            }
        )
    return items


def pending_speaker_match_groups(store: Store, *, limit: int = 50) -> list[dict[str, Any]]:
    rows = store.conn.execute(
        """
        SELECT
            speaker_match_decisions.*,
            source.display_name AS current_source_name,
            target.display_name AS current_target_name
        FROM speaker_match_decisions
        LEFT JOIN speakers AS source ON source.id = speaker_match_decisions.source_speaker_id
        LEFT JOIN speakers AS target ON target.id = speaker_match_decisions.target_speaker_id
        WHERE speaker_match_decisions.status IN ('auto_merged_pending_review', 'candidate')
        ORDER BY speaker_match_decisions.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        target_id = row["target_speaker_id"]
        key = str(target_id or "none")
        group = grouped.setdefault(
            key,
            {
                "target_speaker_id": target_id,
                "target_name": row["current_target_name"] or row["target_display_name"],
                "matches": [],
                "max_score": None,
            },
        )
        score = row["score"]
        group["matches"].append(
            {
                "id": row["id"],
                "source_speaker_id": row["source_speaker_id"],
                "target_speaker_id": target_id,
                "source_name": row["current_source_name"] or row["source_display_name"],
                "target_name": row["current_target_name"] or row["target_display_name"],
                "status": row["status"],
                "score": score,
                "threshold": row["threshold"],
                "created_at": row["created_at"],
                "metadata": json_object(row["metadata"]),
            }
        )
        if score is not None:
            group["max_score"] = max(float(score), float(group["max_score"] or 0.0))
    return sorted(grouped.values(), key=lambda item: (-(item["max_score"] or 0.0), str(item["target_name"] or "")))


def speaker_payload(row: Any) -> dict[str, Any]:
    payload = {key: row[key] for key in row.keys() if key != "metadata"}
    payload["metadata"] = compact_speaker_metadata(json_object(row["metadata"]))
    return payload


def speaker_sample_payload(row: Any) -> dict[str, Any]:
    payload = {key: row[key] for key in row.keys() if key != "metadata"}
    payload["metadata"] = compact_speaker_sample_metadata(json_object(row["metadata"]))
    return payload


def compact_speaker_sample_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in [
        "status",
        "error",
        "local_label",
        "sample_role",
        "sample_confidence",
        "sample_confidence_basis",
        "sample_confidence_model",
        "sample_confidence_recalculated_at",
        "sample_transcript_mode",
        "representative_sample",
        "representative_rank",
        "representative_score",
        "representative_refreshed_at",
        "embedding_repair_status",
        "embedding_model",
    ]:
        if key in metadata:
            compact[key] = metadata[key]
    quality = metadata.get("quality")
    if isinstance(quality, dict):
        compact["quality"] = {
            key: quality.get(key)
            for key in ["ok", "duration_seconds", "rms_dbfs", "peak_dbfs", "clipped_ratio", "reason"]
            if key in quality
        }
    preprocessing = metadata.get("audio_preprocessing")
    if isinstance(preprocessing, dict):
        compact["audio_preprocessing"] = {
            key: preprocessing.get(key)
            for key in ["status", "error"]
            if key in preprocessing
        }
    recutter = metadata.get("sample_recutter")
    if isinstance(recutter, dict):
        compact["sample_recutter"] = {
            key: recutter.get(key)
            for key in [
                "status",
                "boundary_policy",
                "clip_start_seconds",
                "clip_end_seconds",
                "source_segment_start",
                "source_segment_end",
            ]
            if key in recutter
        }
    return compact


def compact_speaker_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in [
        "speaker_review_status",
        "speaker_hidden",
        "confirmed_at",
        "hidden_at",
        "unhidden_at",
        "revived_at",
        "revived_reason",
        "hidden_threshold",
        "auto_merge_last_at",
        "auto_merge_last_score",
        "auto_merge_threshold",
        "representative_sample_ids",
        "representative_samples_refreshed_at",
        "auto_generated_display_name",
        "auto_display_name_previous",
    ]:
        if key in metadata:
            compact[key] = metadata[key]
    sources = metadata.get("auto_merge_sources")
    if isinstance(sources, list):
        compact["auto_merge_source_count"] = len(sources)
        compact["auto_merge_sources"] = sources[-5:]
    return compact


def compact_observation_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in ["status", "duration_seconds", "media_deleted_at", "media_recycled_at"]:
        if key in metadata:
            compact[key] = metadata[key]
    analysis = metadata.get("audio_analysis")
    if isinstance(analysis, dict):
        for key in ["status", "duration_seconds", "local_analysis_backend", "local_transcription_backend"]:
            if key in analysis:
                compact[f"audio_{key}"] = analysis[key]
        speaker_processing = analysis.get("speaker_processing")
        if isinstance(speaker_processing, dict):
            compact["speaker_processing_status"] = speaker_processing.get("status")
            compact["speaker_processing_note"] = speaker_processing.get("note")
    return compact


def representative_sample_sort_key(sample: Any) -> tuple[float, int]:
    return (-representative_sample_score(sample), int(sample["id"]))


def representative_sample_score(sample: Any) -> float:
    metadata = json_object(sample["metadata"])
    score = 0.0
    confidence = metadata.get("sample_confidence")
    try:
        score += float(confidence) * 10.0
    except (TypeError, ValueError):
        score += 1.0
    duration = 0.0
    try:
        if sample["start_seconds"] is not None and sample["end_seconds"] is not None:
            duration = max(0.0, float(sample["end_seconds"]) - float(sample["start_seconds"]))
    except (TypeError, ValueError):
        duration = 0.0
    score += min(duration, 8.0)
    transcript = str(sample["transcript"] or "").strip()
    if transcript:
        score += min(len(transcript) / 80.0, 3.0)
    if metadata.get("status") == "ok":
        score += 2.0
    if metadata.get("sample_role") == "manual_detached_sample":
        score -= 1.0
    if metadata.get("sample_role") == "overlap_separated_candidate":
        score -= 2.0
    if not str(sample["sample_path"] or "").strip():
        score -= 5.0
    return score


def update_speaker_sample_metadata(store: Store, sample_id: int, metadata: dict[str, Any]) -> None:
    store.conn.execute(
        """
        UPDATE speaker_samples
        SET metadata = ?
        WHERE id = ?
        """,
        (json.dumps(metadata, ensure_ascii=False, sort_keys=True), sample_id),
    )
    store.conn.commit()


def update_speaker_match_decision(store: Store, match_id: int, status: str, metadata: dict[str, Any]) -> None:
    store.conn.execute(
        """
        UPDATE speaker_match_decisions
        SET status = ?,
            metadata = ?
        WHERE id = ?
        """,
        (status, json.dumps(metadata, ensure_ascii=False, sort_keys=True), match_id),
    )
    store.conn.commit()


def reset_and_auto_group_speaker_samples(
    settings: Settings,
    store: Store,
    *,
    threshold: float | None = None,
    max_merges: int = 500,
    recut: bool = True,
    hide_unmatched: bool = True,
) -> SpeakerSampleRegroupResult:
    result = SpeakerSampleRegroupResult()
    model = embedding_model_key(settings)
    run_at = utc_iso()
    rows = store.conn.execute(
        """
        SELECT
            speaker_samples.*,
            speakers.display_name AS speaker_name,
            speakers.identity_status AS speaker_identity_status,
            speakers.metadata AS speaker_metadata,
            observations.metadata AS observation_metadata
        FROM speaker_samples
        JOIN speakers ON speakers.id = speaker_samples.speaker_id
        LEFT JOIN observations ON observations.id = speaker_samples.observation_id
        ORDER BY speaker_samples.id ASC
        """
    ).fetchall()
    target_rows = [row for row in rows if json_object(row["metadata"]).get("sample_role") != "mixed_parent_archived"]
    result.selected_samples = len(target_rows)
    old_speaker_ids = sorted({int(row["speaker_id"]) for row in target_rows})

    for row in target_rows:
        sample_id = int(row["id"])
        original_speaker_id = int(row["speaker_id"])
        original_speaker_name = str(row["speaker_name"] or original_speaker_id)
        try:
            speaker = store.ensure_speaker_for_alias(
                f"sample-regroup:{run_at}:{sample_id}",
                default_name="Voice",
                label="sample_regroup_singleton",
                metadata={
                    "alias_type": "sample_regroup_singleton",
                    "sample_id": sample_id,
                    "regrouped_at": run_at,
                    "original_speaker_id": original_speaker_id,
                    "original_speaker_name": original_speaker_name,
                },
            )
            new_speaker_id = int(speaker["id"])
            metadata = json_object(row["metadata"])
            previous_role = metadata.get("sample_role")
            metadata.update(
                {
                    "sample_regrouped_at": run_at,
                    "sample_regroup_status": "single_sample_voice",
                    "sample_regroup_original_speaker_id": original_speaker_id,
                    "sample_regroup_original_speaker_name": original_speaker_name,
                    "sample_regroup_original_identity_status": str(row["speaker_identity_status"] or ""),
                    "sample_regroup_new_speaker_id": new_speaker_id,
                }
            )
            if previous_role:
                metadata.setdefault("sample_regroup_previous_role", previous_role)

            next_sample_path = str(row["sample_path"] or "").strip() or None
            next_start = row["start_seconds"]
            next_end = row["end_seconds"]
            next_transcript = row["transcript"]
            next_source_key = str(row["source_key"] or "")
            reembedded = False

            if recut:
                recut_result = recut_existing_speaker_sample(settings, row, new_speaker_id=new_speaker_id)
                metadata["sample_recutter"] = recut_result.metadata
                if recut_result.ok:
                    next_sample_path = str(recut_result.sample_path)
                    next_start = recut_result.start_seconds
                    next_end = recut_result.end_seconds
                    next_transcript = recut_result.transcript
                    if recut_result.source_key:
                        next_source_key, conflict = source_key_for_sample_update(store, sample_id, next_source_key, recut_result.source_key)
                        if conflict:
                            metadata["sample_regroup_source_key_conflict"] = recut_result.source_key
                    result.recut_samples += 1
                    try:
                        vector = speaker_embedding(settings, recut_result.sample_path)
                        store.add_speaker_embedding(
                            speaker_id=new_speaker_id,
                            sample_id=sample_id,
                            model=model,
                            vector=vector,
                            metadata={
                                "sample_path": str(recut_result.sample_path),
                                "recomputed_at": run_at,
                                "reason": "sample_regroup_recut",
                            },
                        )
                        result.reembedded_samples += 1
                        reembedded = True
                    except Exception as exc:
                        result.skipped_samples += 1
                        metadata["sample_regroup_embedding_error"] = str(exc)
                else:
                    result.skipped_samples += 1
                    store.conn.execute("DELETE FROM speaker_embeddings WHERE sample_id = ?", (sample_id,))
            else:
                store.conn.execute(
                    """
                    UPDATE speaker_embeddings
                    SET speaker_id = ?
                    WHERE sample_id = ?
                    """,
                    (new_speaker_id, sample_id),
                )
                reembedded = True

            metadata["sample_regroup_embedding_ready"] = bool(reembedded)
            store.conn.execute(
                """
                UPDATE speaker_samples
                SET speaker_id = ?,
                    source_key = ?,
                    sample_path = ?,
                    start_seconds = ?,
                    end_seconds = ?,
                    transcript = ?,
                    metadata = ?
                WHERE id = ?
                """,
                (
                    new_speaker_id,
                    next_source_key,
                    next_sample_path,
                    next_start,
                    next_end,
                    next_transcript,
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    sample_id,
                ),
            )
            result.reset_samples += 1
            if len(result.messages) < 30:
                result.messages.append(
                    f"- Reset sample {sample_id}: {original_speaker_name} -> Voice {new_speaker_id}."
                )
        except Exception as exc:
            result.failed += 1
            if len(result.messages) < 40:
                result.messages.append(f"- Failed sample {sample_id}: {exc}")
    store.conn.commit()

    for speaker_id in old_speaker_ids:
        sample_count = store.conn.execute(
            "SELECT count(*) AS n FROM speaker_samples WHERE speaker_id = ?",
            (speaker_id,),
        ).fetchone()["n"]
        if int(sample_count or 0) > 0:
            continue
        store.conn.execute("DELETE FROM speakers WHERE id = ?", (speaker_id,))
        result.deleted_empty_speakers += 1
    store.conn.commit()

    result.organize = auto_organize_speakers(
        settings,
        store,
        threshold=threshold,
        max_merges=max_merges,
        hide_unmatched=hide_unmatched,
    )
    result.failed += result.organize.failed
    for line in result.organize.messages[:20]:
        if len(result.messages) < 60:
            result.messages.append(line)
    return result


@dataclass
class RecutSpeakerSampleResult:
    ok: bool
    sample_path: Path | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None
    transcript: str | None = None
    source_key: str | None = None
    label: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def recut_existing_speaker_sample(settings: Settings, sample: Any, *, new_speaker_id: int) -> RecutSpeakerSampleResult:
    observation_metadata = json_object(sample["observation_metadata"])
    plan = speaker_sample_clip_plan(settings, sample)
    if not plan.get("ok"):
        return RecutSpeakerSampleResult(ok=False, metadata={"status": plan.get("status") or "skipped_invalid_clip_plan"})

    media_path = sample_source_audio_path(sample, observation_metadata)
    if media_path is None:
        return RecutSpeakerSampleResult(ok=False, metadata={"status": "skipped_missing_source_audio"})

    clip = plan["clip"]
    start = plan["source_segment_start"]
    end = plan["source_segment_end"]
    label = str(plan["label"])
    output = sample_output_path(settings, new_speaker_id, int(sample["observation_id"] or 0), label, clip[0], clip[1])
    extracted = False
    preprocessing_metadata: dict[str, Any] | None = None
    if cfg_bool(audio_preprocessing_config(settings), "speaker_samples_enabled", True):
        extracted, preprocessing_metadata = create_enhanced_sample_clip(settings, media_path, output, clip[0], clip[1])
    if not extracted:
        extracted = extract_audio_clip(media_path, output, clip[0], clip[1])
        if preprocessing_metadata is None:
            preprocessing_metadata = {"status": "disabled_or_unavailable"}
    if not extracted:
        return RecutSpeakerSampleResult(
            ok=False,
            metadata={
                "status": "sample_failed",
                "clip_start_seconds": clip[0],
                "clip_end_seconds": clip[1],
                "source_audio": str(media_path),
                "audio_preprocessing": preprocessing_metadata,
                "source_key": plan.get("source_key"),
            },
        )

    quality = audio_quality(
        settings,
        output,
        min_seconds=speaker_sample_min_seconds(settings),
    )
    if not quality.get("ok"):
        output.unlink(missing_ok=True)
        return RecutSpeakerSampleResult(
            ok=False,
            metadata={
                "status": "quality_rejected",
                "quality": quality,
                "clip_start_seconds": clip[0],
                "clip_end_seconds": clip[1],
                "source_audio": str(media_path),
                "audio_preprocessing": preprocessing_metadata,
                "source_key": plan.get("source_key"),
            },
        )

    return RecutSpeakerSampleResult(
        ok=True,
        sample_path=output,
        start_seconds=clip[0],
        end_seconds=clip[1],
        transcript=plan.get("transcript"),
        source_key=str(plan.get("source_key") or ""),
        label=label,
        metadata={
            "status": "ok",
            "clip_start_seconds": clip[0],
            "clip_end_seconds": clip[1],
            "source_segment_start": start,
            "source_segment_end": end,
            "source_audio": str(media_path),
            "source_key": plan.get("source_key"),
            "source_segment_transcript": plan.get("source_segment_transcript"),
            "sample_transcript_mode": plan.get("sample_transcript_mode"),
            "audio_preprocessing": preprocessing_metadata,
            "quality": quality,
            "boundary_policy": "inside_single_speaker_segment_only",
            "clip_strategy": plan.get("clip_strategy"),
        },
    )


def sample_duration_seconds(observation_metadata: dict[str, Any]) -> float | None:
    analysis = observation_metadata.get("audio_analysis") if isinstance(observation_metadata.get("audio_analysis"), dict) else {}
    timeline = analysis.get("audio_timeline") if isinstance(analysis.get("audio_timeline"), dict) else {}
    return parse_seconds(timeline.get("duration_seconds"))


def speaker_sample_seconds(settings: Settings) -> float:
    return parse_seconds(settings.speaker_recognition.get("sample_seconds")) or 8.0


def speaker_sample_min_seconds(settings: Settings) -> float:
    return parse_seconds(settings.speaker_recognition.get("sample_min_seconds")) or 0.5


def speaker_sample_boundary_guard_seconds(settings: Settings) -> float:
    return parse_seconds(settings.speaker_recognition.get("sample_boundary_guard_seconds")) or 0.0


def speaker_sample_long_segment_anchor(settings: Settings) -> str:
    return normalize_clip_anchor(settings.speaker_recognition.get("sample_long_segment_anchor", "start"))


def normalize_clip_anchor(value: Any) -> str:
    anchor = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "begin": "start",
        "beginning": "start",
        "segment_start": "start",
        "front": "start",
        "middle": "center",
        "centre": "center",
        "segment_center": "center",
        "segment_middle": "center",
        "tail": "end",
        "segment_end": "end",
    }
    anchor = aliases.get(anchor, anchor)
    return anchor if anchor in {"start", "center", "end"} else "start"


def speaker_sample_clip_plan(settings: Settings, sample: Any) -> dict[str, Any]:
    observation_metadata = json_object(sample["observation_metadata"])
    segment = best_segment_for_sample(sample, observation_metadata)
    if segment is None:
        return {"ok": False, "status": "skipped_missing_matching_segment"}
    start = parse_seconds(segment.get("start"))
    end = parse_seconds(segment.get("end"))
    clip = clip_bounds(
        start,
        end,
        duration_seconds=sample_duration_seconds(observation_metadata),
        sample_seconds=speaker_sample_seconds(settings),
        sample_min_seconds=speaker_sample_min_seconds(settings),
        boundary_guard_seconds=speaker_sample_boundary_guard_seconds(settings),
        long_segment_anchor=speaker_sample_long_segment_anchor(settings),
    )
    if clip is None:
        return {"ok": False, "status": "skipped_invalid_clip_bounds"}
    label = speaker_sample_plan_label(sample, segment)
    full_transcript = text_value(segment.get("text"), limit=2000)
    transcript = sample_transcript_for_clip(segment, clip)
    return {
        "ok": True,
        "status": "ok",
        "clip": clip,
        "label": label,
        "transcript": transcript,
        "source_key": speaker_sample_source_key(int(sample["observation_id"] or 0), label, clip[0], clip[1]),
        "source_segment_start": start,
        "source_segment_end": end,
        "source_segment_transcript": full_transcript,
        "sample_transcript_mode": "clip_window_excerpt" if full_transcript != transcript else "full_segment",
        "clip_strategy": {
            "long_segment_anchor": speaker_sample_long_segment_anchor(settings),
            "sample_seconds": speaker_sample_seconds(settings),
            "boundary_guard_seconds": speaker_sample_boundary_guard_seconds(settings),
        },
    }


def speaker_sample_plan_label(sample: Any, segment: dict[str, Any]) -> str:
    sample_metadata = json_object(sample["metadata"])
    label = str(sample_metadata.get("local_label") or "").strip()
    if label:
        return label
    return (
        normalize_speaker_label(segment.get("speaker_local_label") or segment.get("local_label") or segment.get("speaker"))
        or f"sample-{sample['id']}"
    )


def sample_source_audio_path(sample: Any, observation_metadata: dict[str, Any]) -> Path | None:
    media_path = speaker_audio_source_path(observation_metadata)
    if media_path is not None:
        return media_path
    raw_media_path = str(sample["media_path"] or "").strip()
    candidate = Path(raw_media_path).expanduser() if raw_media_path else None
    if candidate is not None and candidate.exists() and candidate.is_file():
        return candidate
    return None


def sample_clip_window_changed(sample: Any, clip: tuple[float, float]) -> bool:
    start = parse_seconds(sample["start_seconds"])
    end = parse_seconds(sample["end_seconds"])
    if start is None or end is None:
        return True
    return abs(start - clip[0]) > 0.01 or abs(end - clip[1]) > 0.01


def sample_clip_metadata_needs_update(metadata: dict[str, Any], plan: dict[str, Any]) -> bool:
    strategy = metadata.get("clip_strategy") if isinstance(metadata.get("clip_strategy"), dict) else {}
    return (
        parse_seconds(metadata.get("source_segment_start")) != plan.get("source_segment_start")
        or parse_seconds(metadata.get("source_segment_end")) != plan.get("source_segment_end")
        or metadata.get("sample_transcript_mode") != plan.get("sample_transcript_mode")
        or normalize_clip_anchor(strategy.get("long_segment_anchor", "start")) != normalize_clip_anchor(plan["clip_strategy"].get("long_segment_anchor"))
    )


def repaired_sample_clip_metadata(
    sample: Any,
    plan: dict[str, Any],
    *,
    run_at: str,
    recut_metadata: dict[str, Any] | None,
    source_key: str,
    source_key_conflict: bool,
    embedding_ready: bool,
) -> dict[str, Any]:
    update = {
        "status": "ok",
        "clip_start_seconds": plan["clip"][0],
        "clip_end_seconds": plan["clip"][1],
        "source_segment_start": plan.get("source_segment_start"),
        "source_segment_end": plan.get("source_segment_end"),
        "source_segment_transcript": plan.get("source_segment_transcript"),
        "sample_transcript_mode": plan.get("sample_transcript_mode"),
        "boundary_policy": "inside_single_speaker_segment_only",
        "clip_strategy": plan.get("clip_strategy"),
        "sample_clip_repaired_at": run_at,
        "sample_clip_repair": {
            "repaired_at": run_at,
            "original_start_seconds": parse_seconds(sample["start_seconds"]),
            "original_end_seconds": parse_seconds(sample["end_seconds"]),
            "original_sample_path": str(sample["sample_path"] or ""),
            "original_source_key": str(sample["source_key"] or ""),
            "source_key": source_key,
            "source_key_conflict": source_key_conflict,
            "embedding_ready": embedding_ready,
            "anchor": normalize_clip_anchor(plan["clip_strategy"].get("long_segment_anchor")),
        },
    }
    if recut_metadata is not None:
        update["sample_recutter"] = recut_metadata
        if recut_metadata.get("audio_preprocessing") is not None:
            update["audio_preprocessing"] = recut_metadata.get("audio_preprocessing")
        if recut_metadata.get("quality") is not None:
            update["quality"] = recut_metadata.get("quality")
    if source_key_conflict:
        update["canonical_source_key"] = plan.get("source_key")
        update["source_key_repair_conflict"] = True
    return update


def source_key_for_sample_update(store: Store, sample_id: int, current_key: Any, desired_key: str) -> tuple[str, bool]:
    current = str(current_key or "")
    if not desired_key or desired_key == current:
        return current, False
    existing = store.conn.execute(
        "SELECT id FROM speaker_samples WHERE source_key = ? AND id != ?",
        (desired_key, sample_id),
    ).fetchone()
    if existing is not None:
        return current, True
    return desired_key, False


def format_sample_window(sample: Any) -> str:
    start = parse_seconds(sample["start_seconds"])
    end = parse_seconds(sample["end_seconds"])
    if start is None or end is None:
        return "unknown"
    return f"{start:.2f}-{end:.2f}s"


def auto_organize_speakers(
    settings: Settings,
    store: Store,
    *,
    threshold: float | None = None,
    max_merges: int = 50,
    hide_unmatched: bool = True,
) -> SpeakerAutoOrganizeResult:
    model = embedding_model_key(settings)
    merge_threshold = float(threshold if threshold is not None else settings.speaker_recognition.get("auto_merge_threshold", 0.68))
    result = SpeakerAutoOrganizeResult(threshold=merge_threshold)
    affected_speaker_ids: set[int] = set()

    for _ in range(max(0, max_merges)):
        rows = {int(row["id"]): row for row in store.list_speakers()}
        vectors_by_speaker = speaker_vectors_by_speaker(store, model=model)
        candidates = speaker_merge_candidates(rows, vectors_by_speaker, threshold=merge_threshold)
        result.scanned_pairs += speaker_pair_count(vectors_by_speaker)
        result.merge_candidates += len(candidates)
        if not candidates:
            break

        candidate = candidates[0]
        source_id, target_id = choose_auto_merge_direction(rows, int(candidate["left_id"]), int(candidate["right_id"]))
        source = rows[source_id]
        target = rows[target_id]
        source_samples = store.list_speaker_samples(source_id)
        try:
            store.record_speaker_match_decision(
                source_speaker_id=source_id,
                target_speaker_id=target_id,
                sample_id=None,
                model=model,
                score=float(candidate["score"]),
                threshold=merge_threshold,
                status="auto_merged_pending_review",
                metadata={
                    "decision": "existing_speaker_centroids_above_auto_merge_threshold",
                    "workflow": "auto_organize_speakers",
                    "left_speaker_id": candidate["left_id"],
                    "right_speaker_id": candidate["right_id"],
                    "source_sample_count": source["sample_count"],
                    "target_sample_count": target["sample_count"],
                },
            )
            moved_files = relocate_speaker_sample_files_after_merge(store, source_samples, target_id)
            if not store.merge_speakers(source_id, target_id):
                result.failed += 1
                result.messages.append(f"- Merge failed: {source_id} -> {target_id}.")
                break
            result.merged_speakers += 1
            result.moved_sample_files += moved_files
            affected_speaker_ids.add(target_id)
            mark_auto_merge_pending_review(
                store,
                target_id,
                source=source,
                target=target,
                score=float(candidate["score"]),
                threshold=merge_threshold,
            )
            if len(result.messages) < 40:
                result.messages.append(
                    "- Auto-merged "
                    f"{speaker_label(source)} -> {speaker_label(target)} "
                    f"score={candidate['score']:.3f}."
                )
        except Exception as exc:
            result.failed += 1
            result.messages.append(f"- Merge failed {source_id} -> {target_id}: {exc}")
            break

    if hide_unmatched:
        for row in store.list_speakers():
            speaker_id = int(row["id"])
            if speaker_id in affected_speaker_ids:
                continue
            if should_hide_unmatched_speaker(row):
                if mark_speaker_hidden(store, row, threshold=merge_threshold):
                    result.hidden_speakers += 1
                    if len(result.messages) < 40:
                        result.messages.append(f"- Hid low-similarity speaker {speaker_label(row)}.")

    refresh_ids = sorted(speaker_id for speaker_id in affected_speaker_ids if store.get_speaker(speaker_id) is not None)
    refresh = refresh_speaker_sample_confidences(settings, store, speaker_ids=refresh_ids or None)
    result.refreshed_samples = refresh.updated_samples
    result.failed += refresh.failed
    for line in refresh.messages[:8]:
        if len(result.messages) < 50:
            result.messages.append(line)
    if result.merged_speakers == 0 and result.hidden_speakers == 0:
        result.messages.append("- No speakers needed automatic merge or hiding.")
    return result


def mark_speaker_review_status(
    store: Store,
    *,
    speaker_ids: list[int],
    status: str,
) -> SpeakerReviewMarkResult:
    result = SpeakerReviewMarkResult()
    for speaker_id in unique_positive_ints(speaker_ids):
        row = store.get_speaker(speaker_id)
        if row is None:
            result.missing += 1
            result.messages.append(f"- Speaker not found: {speaker_id}.")
            continue
        metadata = json_object(row["metadata"])
        now = utc_iso()
        if status == "confirmed":
            metadata["speaker_review_status"] = "confirmed"
            metadata["speaker_hidden"] = False
            metadata["confirmed_at"] = now
        elif status == "unhidden":
            metadata["speaker_review_status"] = "needs_review"
            metadata["speaker_hidden"] = False
            metadata["unhidden_at"] = now
        elif status == "hidden":
            metadata["speaker_review_status"] = "low_similarity_hidden"
            metadata["speaker_hidden"] = True
            metadata["hidden_at"] = now
        else:
            raise ValueError(f"unsupported review status: {status}")
        update_speaker_metadata(store, speaker_id, metadata)
        result.updated += 1
        result.messages.append(f"- Updated speaker {speaker_id}: {status}.")
    return result


def speaker_vectors_by_speaker(store: Store, *, model: str) -> dict[int, list[list[float]]]:
    vectors: dict[int, list[list[float]]] = {}
    for row in store.speaker_embedding_rows(model=model):
        parsed = parse_vector(row["vector"])
        if parsed is None:
            continue
        vectors.setdefault(int(row["speaker_id"]), []).append(parsed)
    return vectors


def speaker_pair_count(vectors_by_speaker: dict[int, list[list[float]]]) -> int:
    count = len([speaker_id for speaker_id, vectors in vectors_by_speaker.items() if vectors])
    return max(0, (count * (count - 1)) // 2)


def speaker_merge_candidates(
    speaker_rows: dict[int, Any],
    vectors_by_speaker: dict[int, list[list[float]]],
    *,
    threshold: float,
) -> list[dict[str, Any]]:
    centroids = {
        speaker_id: centroid_vector(vectors)
        for speaker_id, vectors in vectors_by_speaker.items()
        if speaker_id in speaker_rows and vectors
    }
    candidates: list[dict[str, Any]] = []
    ids = sorted(centroids)
    for index, left_id in enumerate(ids):
        left = centroids[left_id]
        if left is None:
            continue
        for right_id in ids[index + 1 :]:
            right = centroids[right_id]
            if right is None or len(left) != len(right):
                continue
            if not auto_merge_pair_allowed(speaker_rows[left_id], speaker_rows[right_id]):
                continue
            score = clamp_similarity(cosine_similarity_values(left, right))
            if score >= threshold:
                candidates.append({"left_id": left_id, "right_id": right_id, "score": score})
    candidates.sort(key=lambda item: (-float(item["score"]), int(item["left_id"]), int(item["right_id"])))
    return candidates


def centroid_vector(vectors: list[list[float]]) -> list[float] | None:
    if not vectors:
        return None
    dimension = len(vectors[0])
    same_dimension = [vector for vector in vectors if len(vector) == dimension]
    if not same_dimension:
        return None
    return [sum(vector[index] for vector in same_dimension) / len(same_dimension) for index in range(dimension)]


def auto_merge_pair_allowed(left: Any, right: Any) -> bool:
    left_status = speaker_review_status(left)
    right_status = speaker_review_status(right)
    if left_status == "confirmed" and right_status == "confirmed":
        return False
    return True


def choose_auto_merge_direction(speaker_rows: dict[int, Any], left_id: int, right_id: int) -> tuple[int, int]:
    left = speaker_rows[left_id]
    right = speaker_rows[right_id]

    def rank(row: Any) -> tuple[int, int, int, int]:
        review = speaker_review_status(row)
        confirmed = 1 if review == "confirmed" else 0
        named = 1 if str(row["identity_status"] or "") == "named" else 0
        samples = int(row["sample_count"] or 0)
        return (confirmed, named, samples, -int(row["id"]))

    target = left if rank(left) >= rank(right) else right
    source = right if int(target["id"]) == left_id else left
    return int(source["id"]), int(target["id"])


def mark_auto_merge_pending_review(
    store: Store,
    speaker_id: int,
    *,
    source: Any,
    target: Any,
    score: float,
    threshold: float,
) -> None:
    row = store.get_speaker(speaker_id)
    if row is None:
        return
    metadata = json_object(row["metadata"])
    sources = metadata.get("auto_merge_sources")
    if not isinstance(sources, list):
        sources = []
    sources.append(
        {
            "source_speaker_id": int(source["id"]),
            "source_display_name": str(source["display_name"]),
            "target_speaker_id": int(target["id"]),
            "target_display_name": str(target["display_name"]),
            "score": round(score, 4),
            "threshold": round(threshold, 4),
            "merged_at": utc_iso(),
        }
    )
    metadata.update(
        {
            "speaker_review_status": "auto_merged_pending_review",
            "speaker_hidden": False,
            "auto_merge_threshold": round(threshold, 4),
            "auto_merge_last_score": round(score, 4),
            "auto_merge_last_at": utc_iso(),
            "auto_merge_sources": sources[-50:],
        }
    )
    update_speaker_metadata(store, speaker_id, metadata)


def should_hide_unmatched_speaker(row: Any) -> bool:
    if str(row["identity_status"] or "") == "named":
        return False
    status = speaker_review_status(row)
    if status in {"confirmed", "auto_merged_pending_review"}:
        return False
    return True


def mark_speaker_hidden(store: Store, row: Any, *, threshold: float) -> bool:
    speaker_id = int(row["id"])
    metadata = json_object(row["metadata"])
    if metadata.get("speaker_review_status") == "low_similarity_hidden" and metadata.get("speaker_hidden") is True:
        return False
    metadata.update(
        {
            "speaker_review_status": "low_similarity_hidden",
            "speaker_hidden": True,
            "hidden_reason": "no_auto_merge_candidate_above_threshold",
            "hidden_threshold": round(float(threshold), 4),
            "hidden_at": utc_iso(),
        }
    )
    update_speaker_metadata(store, speaker_id, metadata)
    return True


def update_speaker_metadata(store: Store, speaker_id: int, metadata: dict[str, Any]) -> None:
    store.conn.execute(
        """
        UPDATE speakers
        SET metadata = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (json.dumps(metadata, ensure_ascii=False, sort_keys=True), utc_iso(), speaker_id),
    )
    store.conn.commit()


def speaker_review_status(row: Any) -> str:
    metadata = json_object(row["metadata"])
    return str(metadata.get("speaker_review_status") or "").strip()


def speaker_label(row: Any) -> str:
    return f"#{row['id']} {row['display_name']}"


def relocate_speaker_sample_files_after_merge(store: Store, samples: list[Any], target_speaker_id: int) -> int:
    moved = 0
    for sample in samples:
        sample_path = str(sample["sample_path"] or "").strip()
        if not sample_path:
            continue
        relocated = relocate_sample_after_merge(sample_path, target_speaker_id)
        if relocated is None:
            continue
        store.update_speaker_sample_path(int(sample["id"]), str(relocated))
        moved += 1
    return moved


def unique_positive_ints(values: list[int]) -> list[int]:
    result: list[int] = []
    for value in values:
        item = int(value)
        if item > 0 and item not in result:
            result.append(item)
    return result


def format_confidence(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if not math.isfinite(number):
        return "n/a"
    return f"{number:.3f}"


def sample_confidence_for_vector(vector: list[float], comparison_vectors: list[list[float]]) -> float | None:
    if not vector:
        return None
    if not comparison_vectors:
        return 1.0
    same_dimension = [other for other in comparison_vectors if len(other) == len(vector)]
    if not same_dimension:
        return None
    centroid = [sum(other[index] for other in same_dimension) / len(same_dimension) for index in range(len(vector))]
    return clamp_similarity(cosine_similarity_values(vector, centroid))


def cosine_similarity_values(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = math.sqrt(sum(float(value) * float(value) for value in left))
    right_norm = math.sqrt(sum(float(value) * float(value) for value in right))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / (left_norm * right_norm)


def clamp_similarity(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, float(value)))


def collapse_vad_chunk_speakers(
    settings: Settings,
    store: Store,
    *,
    apply: bool = False,
    include_named: bool = False,
    limit: int | None = None,
) -> VadChunkCollapseResult:
    result = VadChunkCollapseResult()
    rows = store.conn.execute(
        """
        SELECT
            speaker_aliases.alias,
            speaker_aliases.label,
            speaker_aliases.metadata AS alias_metadata,
            speakers.id AS speaker_id,
            speakers.display_name,
            speakers.identity_status
        FROM speaker_aliases
        JOIN speakers ON speakers.id = speaker_aliases.speaker_id
        WHERE speaker_aliases.alias LIKE 'observation:%'
        ORDER BY speaker_aliases.alias ASC, speakers.id ASC
        """
    ).fetchall()
    sample_count_rows = store.conn.execute(
        """
        SELECT speaker_id, count(*) AS sample_count
        FROM speaker_samples
        GROUP BY speaker_id
        """
    ).fetchall()
    sample_counts = {int(row["speaker_id"]): int(row["sample_count"] or 0) for row in sample_count_rows}

    groups: dict[tuple[int, str], dict[int, Any]] = {}
    for row in rows:
        alias = str(row["alias"] or "")
        match = re.match(r"^observation:(\d+):(.+)$", alias)
        if not match:
            continue
        metadata = json_object(row["alias_metadata"])
        scope = normalize_speaker_scope(metadata.get("speaker_scope"))
        if not is_vad_chunk_scope(scope):
            continue
        label = normalize_speaker_label(row["label"])
        if not label:
            suffix = match.group(2)
            label = normalize_speaker_label(suffix.split(":", 1)[1] if ":" in suffix else suffix)
        if not label:
            continue
        observation_id = int(match.group(1))
        speaker_id = int(row["speaker_id"])
        groups.setdefault((observation_id, label), {})[speaker_id] = row

    result.scanned_groups = len(groups)
    model = embedding_model_key(settings)
    for (observation_id, label), speakers_by_id in sorted(groups.items()):
        if limit is not None and result.merge_groups >= limit:
            break
        speaker_rows = list(speakers_by_id.values())
        if len(speaker_rows) < 2:
            continue
        named = [row for row in speaker_rows if str(row["identity_status"] or "") == "named"]
        if named and len(named) > 1 and not include_named:
            result.skipped_groups += 1
            result.messages.append(
                f"- Skipped observation {observation_id} {label}: multiple named speakers "
                f"({', '.join(str(row['speaker_id']) for row in named)})."
            )
            continue
        if named:
            target = sorted(named, key=lambda row: int(row["speaker_id"]))[0]
        else:
            target = sorted(
                speaker_rows,
                key=lambda row: (-sample_counts.get(int(row["speaker_id"]), 0), int(row["speaker_id"])),
            )[0]
        target_id = int(target["speaker_id"])
        source_ids: list[int] = []
        for row in sorted(speaker_rows, key=lambda item: int(item["speaker_id"])):
            source_id = int(row["speaker_id"])
            if source_id == target_id:
                continue
            if str(row["identity_status"] or "") == "named" and not include_named:
                continue
            source_ids.append(source_id)
        if not source_ids:
            continue
        result.merge_groups += 1
        if not apply:
            result.messages.append(
                f"- Would merge observation {observation_id} {label}: "
                f"{', '.join(map(str, source_ids))} -> {target_id}."
            )
            continue
        merged: list[int] = []
        for source_id in source_ids:
            if store.merge_speakers(source_id, target_id):
                merged.append(source_id)
        if merged:
            result.merged_speakers += len(merged)
            try:
                refresh_identity_status(settings, store, target_id, model)
            except Exception as exc:
                result.messages.append(f"- Refreshed target {target_id} after merge but confidence update failed: {exc}")
            result.messages.append(
                f"- Merged observation {observation_id} {label}: "
                f"{', '.join(map(str, merged))} -> {target_id}."
            )
    return result


def overlap_sample_output_path(
    settings: Settings,
    speaker_id: int,
    observation_id: int,
    label: str,
    start: float,
    end: float,
    stem_index: int,
) -> Path:
    speaker_dir = settings.speaker_sample_dir / f"speaker-{speaker_id:06d}"
    speaker_dir.mkdir(parents=True, exist_ok=True)
    safe_label = safe_filename(label)
    filename = f"obs-{observation_id}-overlap-{safe_label}-stem{stem_index + 1}-{start:.2f}-{end:.2f}.m4a"
    return speaker_dir / filename


def overlap_candidate_source_key(
    observation_id: int,
    label: str,
    start: float,
    end: float,
    stem_index: int,
) -> str:
    return f"observation:{observation_id}:{label}:overlap:{stem_index}:{start:.3f}:{end:.3f}"


def repair_speaker_samples(
    settings: Settings,
    store: Store,
    *,
    limit: int | None = None,
    force: bool = False,
) -> SpeakerSampleRepairResult:
    result = SpeakerSampleRepairResult()
    rows = store.conn.execute(
        """
        SELECT *
        FROM observations
        WHERE source = 'mobile'
          AND kind = 'audio_segment'
          AND body IS NOT NULL
          AND body LIKE '[{%'
        ORDER BY observed_at DESC, id DESC
        """
    ).fetchall()
    for row in rows:
        if limit is not None and result.scanned >= limit:
            break
        result.scanned += 1
        metadata = json_object(row["metadata"])
        analysis = metadata.get("audio_analysis") if isinstance(metadata.get("audio_analysis"), dict) else {}
        timeline = analysis.get("audio_timeline") if isinstance(analysis.get("audio_timeline"), dict) else {}
        existing_segments = timeline.get("speech_segments") if isinstance(timeline.get("speech_segments"), list) else []
        needs_repair = force or timeline_needs_segment_repair(existing_segments)
        if not needs_repair:
            result.skipped += 1
            continue

        parsed_segments = [segment for segment in parse_structured_transcript_text(row["body"] or "") if isinstance(segment, dict)]
        segments = [segment for segment in parsed_segments if segment_is_speech_like(segment)]
        if not segments:
            deleted = store.delete_speaker_samples_for_observation(int(row["id"]))
            result.deleted_samples += deleted
            if parsed_segments:
                timeline = dict(timeline)
                timeline["speech_segments"] = parsed_segments
                timeline["speech_seconds"] = None
                timeline["segment_repair"] = {
                    "status": "no_speech_like_segments",
                    "repaired_at": utc_iso(),
                    "source": "body_jsonish_transcript",
                }
                analysis = dict(analysis)
                analysis["audio_timeline"] = timeline
                analysis.pop("speakers", None)
                analysis["speaker_processing"] = {
                    "status": "skipped_no_speech_like_segments",
                    "processed_at": utc_iso(),
                    "note": "Only silence, music, lyrics, non-speech markers, or repeated hallucinated text was found.",
                }
                metadata["audio_analysis"] = analysis
                store.update_observation_analysis(int(row["id"]), transcript_text_from_segments(parsed_segments), metadata)
                result.repaired += 1
                result.messages.append(f"- Repaired observation {row['id']}: no speech-like segments, {deleted} old samples removed.")
            else:
                timeline = dict(timeline)
                timeline["speech_segments"] = []
                timeline["speech_seconds"] = None
                timeline["segment_repair"] = {
                    "status": "unparseable_timestamped_transcript",
                    "repaired_at": utc_iso(),
                    "source": "body_jsonish_transcript",
                }
                analysis = dict(analysis)
                analysis["audio_timeline"] = timeline
                analysis.pop("speakers", None)
                analysis["speaker_processing"] = {
                    "status": "skipped_unparseable_transcript",
                    "processed_at": utc_iso(),
                    "note": "The transcript looked like timestamped JSON but could not be safely parsed into speech samples.",
                }
                metadata["audio_analysis"] = analysis
                store.update_observation_analysis(int(row["id"]), row["body"], metadata)
                result.repaired += 1
                result.messages.append(f"- Repaired observation {row['id']}: unparseable timestamped transcript, {deleted} old samples removed.")
            continue

        try:
            deleted = store.delete_speaker_samples_for_observation(int(row["id"]))
            result.deleted_samples += deleted
            timeline = dict(timeline)
            timeline["speech_segments"] = segments
            timeline["speech_seconds"] = round(sum(max(0.0, float(seg["end"]) - float(seg["start"])) for seg in segments), 3)
            timeline["segment_repair"] = {
                "status": "ok",
                "repaired_at": utc_iso(),
                "source": "body_jsonish_transcript",
            }
            analysis = dict(analysis)
            analysis["audio_timeline"] = timeline
            analysis.pop("speakers", None)
            analysis.pop("speaker_processing", None)
            metadata["audio_analysis"] = analysis

            media_path = speaker_audio_source_path(metadata)
            transcript = transcript_text_from_segments(segments)
            if media_path is None:
                analysis["speaker_processing"] = {
                    "status": "skipped_missing_media",
                    "processed_at": utc_iso(),
                    "note": "Transcript timestamps were repaired, but no source audio was available to cut new samples.",
                }
                metadata["audio_analysis"] = analysis
            else:
                metadata = process_speakers_for_observation(
                    settings,
                    store,
                    observation_id=int(row["id"]),
                    source_key=str(row["source_key"]),
                    media_path=media_path,
                    metadata=metadata,
                )
            store.update_observation_analysis(int(row["id"]), transcript, metadata)
            result.repaired += 1
            media_note = "new samples cut" if media_path is not None else "source audio missing; old samples removed"
            result.messages.append(f"- Repaired observation {row['id']}: {len(segments)} segments, {deleted} old samples removed, {media_note}.")
        except Exception as exc:
            result.failed += 1
            result.messages.append(f"- Failed observation {row['id']}: {exc}")
    return result


def timeline_needs_segment_repair(segments: list[Any]) -> bool:
    if not segments:
        return False
    if len(segments) != 1:
        return False
    segment = segments[0]
    if not isinstance(segment, dict):
        return False
    text = str(segment.get("text") or "").lstrip()
    return text.startswith('[{"Start"') or text.startswith("[{'Start'")


def speaker_audio_source_path(metadata: dict[str, Any]) -> Path | None:
    analysis = metadata.get("audio_analysis") if isinstance(metadata.get("audio_analysis"), dict) else {}
    candidates = [
        metadata.get("resolved_media_path"),
        analysis.get("resolved_media_path") if isinstance(analysis, dict) else None,
        metadata.get("media_path"),
        metadata.get("recycle_bin_path"),
        analysis.get("recycle_bin_path") if isinstance(analysis, dict) else None,
    ]
    for value in candidates:
        if not value:
            continue
        path = Path(str(value)).expanduser()
        if path.exists() and path.is_file():
            return path
    return None


def json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    import json

    try:
        data = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def normalize_speaker_label(value: Any) -> str | None:
    if value is None:
        return None
    label = str(value).strip()
    if re.fullmatch(r"\d+", label):
        return f"Speaker {int(label) + 1}"
    return label or None


def normalize_speaker_scope(value: Any) -> str | None:
    if value is None:
        return None
    scope = re.sub(r"\s+", "_", str(value).strip())
    return scope or None


def speaker_group_label(settings: Settings, label: str, scope: str | None) -> str:
    if should_collapse_speaker_scope(settings, scope):
        return label
    return scoped_speaker_label(label, scope)


def should_collapse_speaker_scope(settings: Settings, scope: str | None) -> bool:
    if not scope:
        return False
    config = getattr(settings, "speaker_recognition", {}) or {}
    if not bool(config.get("collapse_vad_chunk_scopes", False)):
        return False
    return is_vad_chunk_scope(scope)


def is_vad_chunk_scope(scope: str | None) -> bool:
    return bool(scope and re.fullmatch(r"vad_chunk_\d+", scope))


def scoped_speaker_label(label: str, scope: str | None) -> str:
    return f"{scope}:{label}" if scope else label


def scoped_alias_labels(label: str, scopes: list[str], group_label: str) -> list[str]:
    labels: list[str] = []
    for scope in scopes:
        scoped = scoped_speaker_label(label, scope)
        if scoped != group_label and scoped not in labels:
            labels.append(scoped)
    return labels


def scoped_label_scope(scoped_label: str) -> str | None:
    if ":" not in scoped_label:
        return None
    return scoped_label.split(":", 1)[0] or None


def observation_speaker_alias(observation_id: int, label: str) -> str:
    return f"observation:{observation_id}:{label}"


def default_speaker_name(label: str) -> str:
    cleaned = label.replace("_", " ").replace("-", " ").strip()
    match = re.search(r"(\d+)$", cleaned)
    if cleaned.lower().startswith("speaker") and match:
        number = int(match.group(1))
        if re.match(r"(?i)^speaker[_-]\d+$", label.strip()):
            number += 1
        elif number == 0:
            number = 1
        return f"Speaker {number}"
    if cleaned:
        return cleaned[:1].upper() + cleaned[1:]
    return "Unknown Speaker"


def best_sample_segment(segments: list[dict[str, Any]]) -> dict[str, Any] | None:
    scored: list[tuple[float, dict[str, Any]]] = []
    for segment in segments:
        if not segment_is_speech_like(segment):
            continue
        start = parse_seconds(segment.get("start"))
        end = parse_seconds(segment.get("end"))
        duration = max(0.0, (end or 0.0) - (start or 0.0)) if start is not None and end is not None else 0.0
        text = text_value(segment.get("text"), limit=500) or ""
        score = min(duration, 8.0) + min(len(text) / 80.0, 4.0)
        if text_repetition_ratio(text) > 0.65:
            score -= 6.0
        scored.append((score, segment))
    if not scored:
        return None
    return max(scored, key=lambda item: item[0])[1]


def sample_transcript_for_clip(segment: dict[str, Any], clip: tuple[float, float] | None) -> str | None:
    transcript = text_value(segment.get("text"), limit=1000)
    if not transcript or clip is None:
        return transcript
    segment_start = parse_seconds(segment.get("start"))
    segment_end = parse_seconds(segment.get("end"))
    if segment_start is None or segment_end is None:
        return transcript
    return transcript_excerpt_for_clip(transcript, segment_start, segment_end, clip[0], clip[1])


def transcript_excerpt_for_clip(
    transcript: str,
    segment_start: float,
    segment_end: float,
    clip_start: float,
    clip_end: float,
) -> str:
    text = transcript.strip()
    if not text:
        return text
    duration = max(0.0, segment_end - segment_start)
    if duration <= 0:
        return text
    clipped_start = max(segment_start, clip_start)
    clipped_end = min(segment_end, clip_end)
    if clipped_end <= clipped_start:
        return shorten_text(text, 160)
    if clipped_start <= segment_start + 0.25 and clipped_end >= segment_end - 0.25:
        return text

    start_ratio = min(1.0, max(0.0, (clipped_start - segment_start) / duration))
    end_ratio = min(1.0, max(start_ratio, (clipped_end - segment_start) / duration))
    start_index = int(len(text) * start_ratio)
    end_index = int(len(text) * end_ratio)
    min_chars = min(len(text), 48)
    if end_index - start_index < min_chars:
        if start_index <= 3:
            end_index = min(len(text), start_index + min_chars)
        elif end_index >= len(text) - 3:
            start_index = max(0, end_index - min_chars)
        else:
            missing = min_chars - (end_index - start_index)
            start_index = max(0, start_index - missing // 2)
            end_index = min(len(text), end_index + missing - missing // 2)
    end_index = min(len(text), max(end_index, start_index + 1))
    excerpt = text[start_index:end_index].strip()
    if not excerpt:
        return shorten_text(text, 160)
    if start_index > 0:
        excerpt = "..." + excerpt
    if end_index < len(text):
        excerpt = excerpt + "..."
    return excerpt


def best_segment_for_sample(sample: Any, observation_metadata: Any) -> dict[str, Any] | None:
    metadata = json_object(observation_metadata)
    analysis = metadata.get("audio_analysis") if isinstance(metadata.get("audio_analysis"), dict) else {}
    timeline = analysis.get("audio_timeline") if isinstance(analysis.get("audio_timeline"), dict) else {}
    segments = timeline.get("speech_segments") if isinstance(timeline.get("speech_segments"), list) else []
    if not segments:
        return None
    sample_metadata = json_object(sample["metadata"])
    scope, label = sample_label_scope_and_label(sample_metadata.get("local_label"))
    clip_start = parse_seconds(sample["start_seconds"])
    clip_end = parse_seconds(sample["end_seconds"])
    if clip_start is None or clip_end is None:
        return None
    best: tuple[float, dict[str, Any]] | None = None
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        start = parse_seconds(segment.get("start"))
        end = parse_seconds(segment.get("end"))
        if start is None or end is None or end <= start:
            continue
        overlap = max(0.0, min(clip_end, end) - max(clip_start, start))
        if overlap <= 0 and not (start <= clip_start <= end):
            continue
        score = overlap
        segment_label = normalize_speaker_label(
            segment.get("speaker_local_label") or segment.get("local_label") or segment.get("speaker")
        )
        segment_scope = normalize_speaker_scope(segment.get("speaker_scope"))
        if label and segment_label == label:
            score += 1000.0
        if scope and segment_scope == scope:
            score += 100.0
        if best is None or score > best[0]:
            best = (score, segment)
    return best[1] if best is not None else None


def sample_label_scope_and_label(value: Any) -> tuple[str | None, str | None]:
    raw = str(value or "").strip()
    if not raw:
        return None, None
    if ":" in raw:
        left, right = raw.split(":", 1)
        scope = normalize_speaker_scope(left)
        label = normalize_speaker_label(right)
        if scope:
            return scope, label
    return None, normalize_speaker_label(raw)


def segment_is_speech_like(segment: dict[str, Any]) -> bool:
    text = text_value(segment.get("text"), limit=500) or ""
    if not text:
        return False
    marker = text.strip().strip("[](){} ").lower()
    if marker in NON_SPEECH_MARKERS:
        return False
    if text.strip().lower().startswith(("[lyric]", "[music]", "[silence]", "[environmental", "[unintelligible")):
        return False
    if re.fullmatch(r"\[[^\]]+\]", text.strip()) and marker in NON_SPEECH_MARKERS:
        return False
    if text_repetition_ratio(text) > 0.82 and len(text) > 80:
        return False
    return True


def segment_is_overlapping_speech(segment: dict[str, Any]) -> bool:
    speakers = segment.get("overlap_speakers")
    return bool(segment.get("overlap") and isinstance(speakers, list) and len(speakers) > 1)


def text_repetition_ratio(text: str) -> float:
    tokens = re.findall(r"[\w\u3040-\u30ff\u3400-\u9fff]+", text)
    if not tokens:
        return 0.0
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    return max(counts.values()) / len(tokens)


def clip_bounds(
    start: float | None,
    end: float | None,
    *,
    duration_seconds: float | None,
    sample_seconds: float,
    sample_min_seconds: float,
    boundary_guard_seconds: float = 0.0,
    long_segment_anchor: str = "start",
) -> tuple[float, float] | None:
    if start is None or end is None or end <= start:
        return None
    max_len = max(0.25, sample_seconds)
    clip_start = max(0.0, start)
    clip_end = end
    if duration_seconds is not None:
        clip_end = min(clip_end, max(0.0, duration_seconds))
    if clip_end <= clip_start:
        return None

    guard = max(0.0, boundary_guard_seconds)
    current_len = clip_end - clip_start
    min_usable_len = max(0.05, min(max(0.05, sample_min_seconds), max_len, current_len))
    if guard > 0 and current_len > (guard * 2.0 + min_usable_len):
        clip_start += guard
        clip_end -= guard

    current_len = clip_end - clip_start
    if current_len > max_len:
        anchor = normalize_clip_anchor(long_segment_anchor)
        if anchor == "end":
            clip_start = clip_end - max_len
        elif anchor == "center":
            center = (clip_start + clip_end) / 2.0
            clip_start = max(clip_start, center - max_len / 2.0)
        clip_end = clip_start + max_len
        if duration_seconds is not None and clip_end > duration_seconds:
            clip_end = duration_seconds
            clip_start = max(start, clip_end - max_len)
    if clip_end <= clip_start:
        return None
    return (round(clip_start, 3), round(clip_end, 3))


def sample_output_path(
    settings: Settings,
    speaker_id: int,
    observation_id: int,
    label: str,
    start: float,
    end: float,
) -> Path:
    speaker_dir = settings.speaker_sample_dir / f"speaker-{speaker_id:06d}"
    speaker_dir.mkdir(parents=True, exist_ok=True)
    safe_label = safe_filename(label)
    filename = f"obs-{observation_id}-{safe_label}-{start:.2f}-{end:.2f}.m4a"
    return speaker_dir / filename


def extract_audio_clip(source: Path, output: Path, start: float, end: float) -> bool:
    ffmpeg = find_executable("ffmpeg")
    if not ffmpeg:
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    duration = max(0.01, end - start)
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{duration:.3f}",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            str(output),
        ],
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    return proc.returncode == 0 and output.exists() and output.stat().st_size > 0


def speaker_sample_source_key(
    observation_id: int,
    label: str,
    start: float | None,
    end: float | None,
) -> str:
    start_label = "na" if start is None else f"{start:.3f}"
    end_label = "na" if end is None else f"{end:.3f}"
    return f"observation:{observation_id}:{label}:sample:{start_label}:{end_label}"


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    cleaned = cleaned.strip(".-")
    return cleaned[:80] or "speaker"


def parse_seconds(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def text_value(value: Any, *, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:limit]


def shorten_text(value: Any, limit: int) -> str:
    text = str(value or "").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def cfg_bool(config: dict[str, Any], key: str, default: bool) -> bool:
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)
