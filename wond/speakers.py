from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
import re
import subprocess
from pathlib import Path
from typing import Any

from .audio_preprocessing import audio_preprocessing_config, audio_quality, create_enhanced_sample_clip, create_overlap_candidate_clip
from .config import Settings
from .executables import find_executable
from .openai_analysis import parse_structured_transcript_text, transcript_text_from_segments
from .recycle_bin import move_to_recycle_bin
from .speaker_identity import (
    embedding_model_key,
    float_config,
    parse_vector,
    refresh_identity_status,
    relocate_sample_after_merge,
    sample_confidence_value,
    speaker_cluster_match_eligible,
    speaker_embedding,
    speaker_profile_max_prototypes,
    speaker_profile_outlier_min_similarity,
    speaker_voice_profile_core_score,
    speaker_voice_profile_from_vectors,
    speaker_voice_profile_score,
    speaker_voice_profiles_similarity,
    update_speaker_identity_for_sample,
)
from .store import Store
from .timeutil import day_bounds, local_iso, utc_iso


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

DEFAULT_SPEAKER_CONFIDENCE_THRESHOLD = 0.68
SPEAKER_SAMPLE_DEFAULT_SECONDS = 16.0
SPEAKER_SAMPLE_MAX_SECONDS = 16.0
SPEAKER_SAMPLE_DEFAULT_MAX_PER_SPEAKER_OBSERVATION = 200
SPEAKER_SAMPLE_CONFIDENCE_EXACT_LIMIT = 32


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
class SpeakerSampleSplitResult:
    sample_id: int
    child_sample_ids: list[int] = field(default_factory=list)
    child_speaker_ids: list[int] = field(default_factory=list)
    archived_parent: bool = False
    failed: bool = False
    failed_embeddings: int = 0
    messages: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        status = "Failed" if self.failed else "Split"
        return [
            f"{status} sample {self.sample_id}",
            f"Child samples: {', '.join(map(str, self.child_sample_ids)) if self.child_sample_ids else '-'}",
            f"Child speakers: {', '.join(map(str, sorted(set(self.child_speaker_ids)))) if self.child_speaker_ids else '-'}",
            f"Archived parent: {self.archived_parent}",
            f"Failed embeddings: {self.failed_embeddings}",
            *self.messages,
        ]


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
    review_candidates: int = 0
    merge_rounds: int = 0
    merged_speakers: int = 0
    unstable_merge_candidates: int = 0
    evidence_review_speakers: int = 0
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
            f"Manual review candidates: {self.review_candidates}",
            f"Merge rounds: {self.merge_rounds}",
            f"Merged speakers: {self.merged_speakers}",
            f"Skipped unstable merge candidates: {self.unstable_merge_candidates}",
            f"Evidence-rich speakers queued for review: {self.evidence_review_speakers}",
            f"Hidden low-similarity speakers: {self.hidden_speakers}",
            f"Moved sample files: {self.moved_sample_files}",
            f"Refreshed samples: {self.refreshed_samples}",
            f"Failed: {self.failed}",
            *self.messages,
        ]


@dataclass
class SpeakerSampleAudioPruneResult:
    dry_run: bool
    retention_days: int
    cutoff_iso: str
    scanned_samples: int = 0
    candidate_samples: int = 0
    pruned_samples: int = 0
    protected_samples: int = 0
    missing_embedding_samples: int = 0
    missing_file_samples: int = 0
    outside_sample_dir_samples: int = 0
    failed: int = 0
    freed_bytes: int = 0
    messages: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        prefix = "Would prune" if self.dry_run else "Pruned"
        return [
            f"Speaker sample audio retention days: {self.retention_days}",
            f"Cutoff: {self.cutoff_iso}",
            f"Scanned samples: {self.scanned_samples}",
            f"Candidate samples: {self.candidate_samples}",
            f"{prefix} sample audio files: {self.pruned_samples}",
            f"Protected samples: {self.protected_samples}",
            f"Skipped without embeddings: {self.missing_embedding_samples}",
            f"Missing files: {self.missing_file_samples}",
            f"Skipped outside sample dir: {self.outside_sample_dir_samples}",
            f"Freed bytes: {self.freed_bytes}",
            f"Failed: {self.failed}",
            *self.messages,
        ]


@dataclass
class SpeakerAudioProtectionResult:
    updated: int = 0
    missing: int = 0
    messages: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        return [
            f"Updated: {self.updated}",
            f"Missing: {self.missing}",
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
    timeline_segments = timeline.get("speech_segments")
    if not isinstance(timeline_segments, list):
        return metadata
    segments, sample_segment_source = speaker_sample_source_segments(settings, timeline)

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
            if not cfg_bool(config, "sample_unlabeled_speech", True):
                continue
            label = "Unlabeled speech"
            segment["speaker"] = label
            segment["speaker_unlabeled"] = True
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
                "sample_segment_source": sample_segment_source,
                "overlap_candidate_samples": count_ok_candidates(overlap_candidates),
                "note": "Speech-like segments had overlapping speaker labels, so they were kept for display but not used as speaker samples.",
            }
        elif speech_like_count:
            analysis["speaker_processing"] = {
                "status": "skipped_no_speaker_labels",
                "processed_at": utc_iso(),
                "speech_like_segments": speech_like_count,
                "unlabeled_speech_segments": unlabeled_speech_count,
                "sample_segment_source": sample_segment_source,
                "note": "Speech-like segments were found, but the transcription backend did not emit speaker labels.",
            }
        else:
            analysis["speaker_processing"] = {
                "status": "skipped_no_speech_like_segments",
                "processed_at": utc_iso(),
                "speech_like_segments": 0,
                "sample_segment_source": sample_segment_source,
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

        duration_seconds = parse_seconds(timeline.get("duration_seconds"))
        sample_plans = speaker_sample_plans_for_segments(settings, label_segments, duration_seconds)
        samples: list[dict[str, Any]] = []
        identity = None
        if not sample_plans:
            sample_plans = [(None, None)]
        for sample_index, (segment, clip) in enumerate(sample_plans, start=1):
            sample = create_sample_for_segment(
                settings,
                store,
                speaker_id=speaker_id,
                observation_id=observation_id,
                source_key=source_key,
                label=group_label,
                media_path=media_path,
                segment=segment,
                duration_seconds=duration_seconds,
                clip=clip,
                sample_index=sample_index,
                sample_count=len(sample_plans),
            )
            samples.append(sample)
            if sample.get("sample_id") is None:
                continue
            identity = update_speaker_identity_for_sample(
                settings,
                store,
                speaker_id=speaker_id,
                sample_id=sample.get("sample_id"),
                sample_path=sample.get("sample_path"),
            )
            speaker_id = identity.speaker_id
        if identity is None:
            store.conn.execute("DELETE FROM speaker_aliases WHERE speaker_id = ?", (speaker_id,))
            store.conn.execute(
                "DELETE FROM speakers WHERE id = ? AND id NOT IN (SELECT DISTINCT speaker_id FROM speaker_samples WHERE speaker_id IS NOT NULL)",
                (speaker_id,),
            )
            store.conn.commit()
            continue
        speaker_id = identity.speaker_id
        refreshed_speaker = store.get_speaker(speaker_id)
        if refreshed_speaker is not None:
            speaker_name = str(refreshed_speaker["display_name"])
        first_sample = samples[0] if samples else {}
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
                "sample_count": len(samples),
                "sample_path": first_sample.get("sample_path"),
                "sample_start_seconds": first_sample.get("start_seconds"),
                "sample_end_seconds": first_sample.get("end_seconds"),
                "sample_status": first_sample.get("status"),
                "sample_error": first_sample.get("error"),
                "sample_windows": [
                    {
                        "sample_id": item.get("sample_id"),
                        "status": item.get("status"),
                        "start_seconds": item.get("start_seconds"),
                        "end_seconds": item.get("end_seconds"),
                    }
                    for item in samples
                ],
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
        "speech_like_segments": speech_like_count,
        "overlapped_speech_segments": overlapped_speech_count,
        "unlabeled_speech_segments": unlabeled_speech_count,
        "sample_segment_source": sample_segment_source,
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
    clip: tuple[float, float] | None = None,
    sample_index: int | None = None,
    sample_count: int | None = None,
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
    segment_score = speaker_sample_segment_score(segment)
    source_mixed_speaker_risk = speaker_sample_segment_mixed_speaker_risk(segment)
    fine_window = speaker_sample_segment_uses_fine_windows(settings, segment)
    sample_window_seconds = speaker_sample_window_seconds(settings, segment)
    sample_stride_seconds = speaker_sample_window_stride_seconds(settings, segment, sample_window_seconds)
    if clip is None:
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
    quality_recovery: dict[str, Any] | None = None
    if clip and media_path is not None and media_path.exists():
        output = sample_output_path(settings, speaker_id, observation_id, label, clip[0], clip[1])
        attempt = extract_quality_checked_sample_clip(settings, media_path, output, clip[0], clip[1])
        preprocessing_metadata = attempt.get("audio_preprocessing")
        quality = attempt.get("quality")
        sample_path = attempt.get("sample_path")
        status = str(attempt.get("status") or "sample_failed")
        error = attempt.get("error")
        if status == "quality_rejected" and speaker_sample_should_retry_quality(settings, segment, clip, quality):
            original_quality = quality
            retry_attempts: list[dict[str, Any]] = []
            for retry_clip in speaker_sample_quality_retry_clips(settings, segment, clip, duration_seconds):
                if abs(retry_clip[0] - clip[0]) <= 0.01 and abs(retry_clip[1] - clip[1]) <= 0.01:
                    continue
                retry_output = sample_output_path(settings, speaker_id, observation_id, label, retry_clip[0], retry_clip[1])
                retry = extract_quality_checked_sample_clip(settings, media_path, retry_output, retry_clip[0], retry_clip[1])
                retry_quality = retry.get("quality") if isinstance(retry.get("quality"), dict) else {}
                retry_attempts.append(
                    {
                        "start_seconds": retry_clip[0],
                        "end_seconds": retry_clip[1],
                        "status": retry.get("status"),
                        "reason": retry_quality.get("reason") or retry.get("error"),
                    }
                )
                if retry.get("status") != "ok":
                    continue
                clip = retry_clip
                transcript = sample_transcript_for_clip(segment, clip)
                sample_source_key = speaker_sample_source_key(observation_id, label, clip[0], clip[1])
                preprocessing_metadata = retry.get("audio_preprocessing")
                quality = retry.get("quality")
                sample_path = retry.get("sample_path")
                status = "ok"
                error = None
                quality_recovery = {
                    "status": "recovered_with_shorter_window",
                    "original_start_seconds": attempt.get("start_seconds"),
                    "original_end_seconds": attempt.get("end_seconds"),
                    "original_reason": (
                        original_quality.get("reason")
                        if isinstance(original_quality, dict)
                        else attempt.get("error")
                    ),
                    "attempts": retry_attempts[:12],
                }
                break
    elif media_path is None:
        status = "missing_media_path"
    elif not media_path.exists():
        status = "missing_file"
        error = str(media_path)

    if status in {"quality_rejected", "sample_failed", "missing_file"}:
        return {
            "sample_id": None,
            "status": status,
            "error": error,
            "sample_path": None,
            "start_seconds": clip[0] if clip else start,
            "end_seconds": clip[1] if clip else end,
            "quality": quality,
            "rejected_before_library": True,
        }

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
            "sample_segment_score": round(segment_score, 4) if segment_score is not None else None,
            "sample_segment_mixed_speaker_risk": source_mixed_speaker_risk and not fine_window,
            "source_segment_mixed_speaker_risk": source_mixed_speaker_risk,
            "sample_fine_window": fine_window,
            "speaker_sample_source": segment.get("speaker_sample_source"),
            "speaker_sample_source_index": segment.get("speaker_sample_source_index"),
            "sample_window_index": sample_index,
            "sample_window_count": sample_count,
            "quality_recovery": quality_recovery,
            "boundary_policy": "inside_single_speaker_segment_only",
            "clip_strategy": {
                "long_segment_anchor": speaker_sample_long_segment_anchor(settings),
                "sample_seconds": sample_window_seconds,
                "sample_stride_seconds": sample_stride_seconds,
                "boundary_guard_seconds": speaker_sample_boundary_guard_seconds(settings),
                "fine_window": fine_window,
                "sample_source": segment.get("speaker_sample_source"),
                "quality_recovery_window": bool(quality_recovery),
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


def extract_quality_checked_sample_clip(
    settings: Settings,
    media_path: Path,
    output: Path,
    start: float,
    end: float,
) -> dict[str, Any]:
    preprocessing_metadata: dict[str, Any] | None = None
    extracted = False
    if cfg_bool(audio_preprocessing_config(settings), "speaker_samples_enabled", True):
        extracted, preprocessing_metadata = create_enhanced_sample_clip(settings, media_path, output, start, end)
    if not extracted:
        extracted = extract_audio_clip(media_path, output, start, end)
        if preprocessing_metadata is None:
            preprocessing_metadata = {"status": "disabled_or_unavailable"}
    if not extracted:
        return {
            "status": "sample_failed",
            "error": "ffmpeg could not extract sample",
            "sample_path": None,
            "audio_preprocessing": preprocessing_metadata,
            "quality": None,
            "start_seconds": start,
            "end_seconds": end,
        }

    quality = audio_quality(
        settings,
        output,
        min_seconds=parse_seconds(settings.speaker_recognition.get("sample_min_seconds")) or 0.5,
    )
    if quality.get("ok"):
        return {
            "status": "ok",
            "error": None,
            "sample_path": str(output),
            "audio_preprocessing": preprocessing_metadata,
            "quality": quality,
            "start_seconds": start,
            "end_seconds": end,
        }

    output.unlink(missing_ok=True)
    return {
        "status": "quality_rejected",
        "error": str(quality.get("reason") or "quality_gate_failed"),
        "sample_path": None,
        "audio_preprocessing": preprocessing_metadata,
        "quality": quality,
        "start_seconds": start,
        "end_seconds": end,
    }


def speaker_sample_should_retry_quality(
    settings: Settings,
    segment: dict[str, Any],
    clip: tuple[float, float],
    quality: dict[str, Any] | None,
) -> bool:
    if not quality or quality.get("ok"):
        return False
    if str(quality.get("reason") or "") not in {"noisy_background", "low_speech_activity"}:
        return False
    if speaker_sample_segment_uses_fine_windows(settings, segment):
        return False
    clip_duration = max(0.0, clip[1] - clip[0])
    return clip_duration >= max(4.0, speaker_sample_fine_window_seconds(settings) + 0.5)


def speaker_sample_quality_retry_clips(
    settings: Settings,
    segment: dict[str, Any],
    clip: tuple[float, float],
    duration_seconds: float | None,
) -> list[tuple[float, float]]:
    clip_start = max(0.0, clip[0])
    clip_end = clip[1]
    if duration_seconds is not None:
        clip_end = min(clip_end, duration_seconds)
    available = max(0.0, clip_end - clip_start)
    min_seconds = speaker_sample_min_seconds(settings)
    if available < max(4.0, min_seconds):
        return []

    raw_lengths = [
        min(8.0, available),
        min(6.0, available),
        min(5.0, available),
        min(4.0, available),
        min(speaker_sample_fine_window_seconds(settings), available),
    ]
    lengths: list[float] = []
    for length in raw_lengths:
        rounded = round(float(length), 3)
        if rounded >= min_seconds and rounded < available - 0.01 and rounded not in lengths:
            lengths.append(rounded)
    lengths.sort(reverse=True)

    clips: list[tuple[float, float]] = []
    max_attempts = int(settings.speaker_recognition.get("sample_quality_retry_max_attempts", 12) or 12)
    for length in lengths:
        stride = max(0.5, min(length / 2.0, speaker_sample_fine_stride_seconds(settings)))
        last_start = max(clip_start, clip_end - length)
        cursor = clip_start
        while cursor <= last_start + 0.01 and len(clips) < max_attempts:
            candidate = (round(cursor, 3), round(cursor + length, 3))
            if candidate not in clips:
                clips.append(candidate)
            cursor += stride
        tail = (round(last_start, 3), round(last_start + length, 3))
        if len(clips) < max_attempts and tail not in clips:
            clips.append(tail)
        if len(clips) >= max_attempts:
            break
    return clips


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


def split_speaker_sample(
    settings: Settings,
    store: Store,
    *,
    sample_id: int,
    cut_points: list[float],
    separate_speakers: bool = True,
    archive_parent: bool = True,
) -> SpeakerSampleSplitResult:
    result = SpeakerSampleSplitResult(sample_id=sample_id)
    sample = store.get_speaker_sample(sample_id)
    if sample is None:
        result.failed = True
        result.messages.append(f"- Sample not found: {sample_id}")
        return result

    sample_path = str(sample["sample_path"] or "").strip()
    if not sample_path:
        result.failed = True
        result.messages.append("- Sample has no audio file to split.")
        return result
    source_path = Path(sample_path).expanduser()
    if not source_path.exists() or not source_path.is_file():
        result.failed = True
        result.messages.append(f"- Sample audio file is missing: {source_path}")
        return result

    start = parse_seconds(sample["start_seconds"])
    end = parse_seconds(sample["end_seconds"])
    if start is None or end is None or end <= start:
        result.failed = True
        result.messages.append("- Sample needs valid start/end seconds before it can be split.")
        return result
    duration = end - start
    min_seconds = speaker_sample_min_seconds(settings)
    bounds = normalized_sample_split_bounds(cut_points, duration, min_seconds=min_seconds)
    if bounds is None:
        result.failed = True
        result.messages.append(
            f"- Invalid cut points. Use seconds inside 0-{duration:.2f}s and keep every piece at least {min_seconds:.2f}s."
        )
        return result

    original_speaker_id = int(sample["speaker_id"])
    original_speaker_name = str(sample["speaker_name"] or original_speaker_id)
    parent_metadata = json_object(sample["metadata"])
    parent_transcript = str(sample["transcript"] or "")
    run_at = utc_iso()
    model = embedding_model_key(settings)
    created_speaker_ids: list[int] = []
    created_sample_ids: list[int] = []

    for index, (relative_start, relative_end) in enumerate(bounds, start=1):
        absolute_start = round(start + relative_start, 3)
        absolute_end = round(start + relative_end, 3)
        if separate_speakers:
            speaker = store.ensure_speaker_for_alias(
                f"manual-split-sample:{sample_id}:{index}:{run_at}",
                default_name="Voice",
                label="manual_split_sample",
                metadata={
                    "alias_type": "manual_split_sample",
                    "parent_sample_id": sample_id,
                    "parent_speaker_id": original_speaker_id,
                    "parent_speaker_name": original_speaker_name,
                    "split_index": index,
                    "split_count": len(bounds),
                    "split_at": run_at,
                },
            )
            target_speaker_id = int(speaker["id"])
        else:
            target_speaker_id = original_speaker_id
        created_speaker_ids.append(target_speaker_id)

        output = sample_output_path(
            settings,
            target_speaker_id,
            int(sample["observation_id"] or 0),
            f"manual-split-{sample_id}-{index}",
            absolute_start,
            absolute_end,
        )
        attempt = extract_quality_checked_sample_clip(
            settings,
            source_path,
            output,
            relative_start,
            relative_end,
        )
        if attempt.get("status") != "ok":
            result.failed = True
            result.messages.append(
                f"- Split {index} failed {relative_start:.2f}-{relative_end:.2f}s: "
                f"{attempt.get('error') or attempt.get('status')}"
            )
            for child_id in created_sample_ids:
                store.conn.execute("DELETE FROM speaker_embeddings WHERE sample_id = ?", (child_id,))
                store.conn.execute("DELETE FROM speaker_samples WHERE id = ?", (child_id,))
            store.conn.commit()
            return result

        transcript = transcript_excerpt_for_clip(
            parent_transcript,
            start,
            end,
            absolute_start,
            absolute_end,
        )
        source_key = f"manual-split:{sample_id}:{index}:{relative_start:.3f}:{relative_end:.3f}:{run_at}"
        child = store.add_speaker_sample(
            speaker_id=target_speaker_id,
            observation_id=int(sample["observation_id"]) if sample["observation_id"] is not None else None,
            source_key=source_key,
            media_path=str(sample["media_path"] or sample_path),
            sample_path=str(attempt.get("sample_path") or output),
            start_seconds=absolute_start,
            end_seconds=absolute_end,
            transcript=transcript,
            metadata={
                "local_label": f"manual_split:{index}",
                "status": "ok",
                "sample_role": "manual_split_child",
                "manual_split_parent_sample_id": sample_id,
                "manual_split_parent_speaker_id": original_speaker_id,
                "manual_split_parent_speaker_name": original_speaker_name,
                "manual_split_index": index,
                "manual_split_count": len(bounds),
                "manual_split_relative_start_seconds": relative_start,
                "manual_split_relative_end_seconds": relative_end,
                "manual_split_at": run_at,
                "source_segment_start": start,
                "source_segment_end": end,
                "source_segment_transcript": parent_metadata.get("source_segment_transcript") or parent_transcript,
                "sample_transcript_mode": "manual_split_excerpt",
                "audio_preprocessing": attempt.get("audio_preprocessing"),
                "quality": attempt.get("quality"),
                "boundary_policy": "manual_sample_split",
            },
        )
        child_id = int(child["id"])
        created_sample_ids.append(child_id)
        result.child_sample_ids.append(child_id)
        result.child_speaker_ids.append(target_speaker_id)

        try:
            vector = speaker_embedding(settings, Path(str(child["sample_path"])))
            store.add_speaker_embedding(
                speaker_id=target_speaker_id,
                sample_id=child_id,
                model=model,
                vector=vector,
                metadata={
                    "sample_path": str(child["sample_path"]),
                    "created_at": run_at,
                    "reason": "manual_sample_split",
                    "parent_sample_id": sample_id,
                },
            )
        except Exception as exc:
            result.failed_embeddings += 1
            child_metadata = json_object(child["metadata"])
            child_metadata.update(
                {
                    "embedding_repair_status": "failed",
                    "embedding_repair_error": str(exc)[:500],
                    "embedding_repaired_at": utc_iso(),
                    "embedding_model": model,
                }
            )
            update_speaker_sample_metadata(store, child_id, child_metadata)

    if archive_parent:
        parent_metadata.update(
            {
                "sample_role": "mixed_parent_archived",
                "status": "archived",
                "manual_split_archived_at": run_at,
                "manual_split_child_sample_ids": created_sample_ids,
                "manual_split_child_speaker_ids": created_speaker_ids,
                "manual_split_cut_points": sorted(float(point) for point in cut_points),
                "manual_split_mode": "separate_speakers" if separate_speakers else "keep_speaker",
            }
        )
        store.conn.execute(
            """
            UPDATE speaker_samples
            SET metadata = ?
            WHERE id = ?
            """,
            (json.dumps(parent_metadata, ensure_ascii=False, sort_keys=True), sample_id),
        )
        store.conn.execute("DELETE FROM speaker_embeddings WHERE sample_id = ?", (sample_id,))
        result.archived_parent = True

    store.conn.commit()
    for speaker_id in sorted(set([original_speaker_id, *created_speaker_ids])):
        if store.get_speaker(speaker_id) is None:
            continue
        try:
            refresh_identity_status(settings, store, speaker_id, model)
        except Exception as exc:
            result.messages.append(f"- Refreshed speaker {speaker_id} after split but confidence update failed: {exc}")
    result.messages.append(f"- Created {len(created_sample_ids)} split sample(s).")
    return result


def normalized_sample_split_bounds(
    cut_points: list[float],
    duration_seconds: float,
    *,
    min_seconds: float,
) -> list[tuple[float, float]] | None:
    if duration_seconds <= 0:
        return None
    cleaned: list[float] = []
    for point in cut_points:
        try:
            value = float(point)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value) or value <= 0 or value >= duration_seconds:
            return None
        rounded = round(value, 3)
        if rounded not in cleaned:
            cleaned.append(rounded)
    if not cleaned:
        return None
    points = [0.0, *sorted(cleaned), round(duration_seconds, 3)]
    bounds = [(points[index], points[index + 1]) for index in range(len(points) - 1)]
    if any(end - start < min_seconds for start, end in bounds):
        return None
    return bounds


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

            sample_confidences = sample_confidences_for_vectors(vectors)
            for sample_id, vector in vectors:
                sample = store.get_speaker_sample(sample_id)
                if sample is None or int(sample["speaker_id"]) != speaker_id:
                    result.skipped_samples += 1
                    continue
                confidence_info = sample_confidences.get(sample_id)
                if confidence_info is None:
                    result.skipped_samples += 1
                    continue
                confidence, basis = confidence_info
                metadata = json_object(sample["metadata"])
                metadata.update(
                    {
                        "sample_confidence": round(confidence, 4),
                        "sample_confidence_model": model,
                        "sample_confidence_basis": basis,
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
    min_confidence: float = 0.55,
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
        ranked = [
            sample
            for sample in sorted(samples, key=representative_sample_sort_key)
            if representative_sample_eligible(sample, min_confidence=min_confidence)
        ]
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


def speaker_confidence_summary(
    row: Any,
    *,
    sample_count: int,
    embedding_count: int,
    confidence_threshold: float | None = None,
) -> dict[str, Any]:
    threshold = speaker_confidence_threshold_value(confidence_threshold)
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
        elif confidence_number < threshold:
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
    elif confidence_number < threshold:
        level = "low"
        label = "低一致性"
        detail = f"样本之间 embedding 差异较大，低于当前阈值 {threshold:.3f}；未人工确认时建议复听。"
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
        "threshold": round(threshold, 4),
    }


def speaker_confidence_threshold_value(value: float | None) -> float:
    try:
        threshold = float(value if value is not None else DEFAULT_SPEAKER_CONFIDENCE_THRESHOLD)
    except (TypeError, ValueError):
        return DEFAULT_SPEAKER_CONFIDENCE_THRESHOLD
    if threshold <= 0 or threshold > 1:
        return DEFAULT_SPEAKER_CONFIDENCE_THRESHOLD
    return threshold


def speaker_review_confidence_threshold(settings: Settings) -> float:
    return speaker_recognition_threshold(settings, "candidate_threshold", DEFAULT_SPEAKER_CONFIDENCE_THRESHOLD)


def speaker_threshold_config(settings: Settings) -> dict[str, dict[str, Any]]:
    try:
        auto_merge_max_merges = int(settings.speaker_recognition.get("auto_merge_max_merges", 100))
    except (TypeError, ValueError):
        auto_merge_max_merges = 100
    return {
        "speaker_recognition": {
            "auto_merge_threshold": speaker_recognition_threshold(settings, "auto_merge_threshold", 0.68),
            "auto_merge_max_merges": max(1, min(auto_merge_max_merges, 5000)),
            "candidate_threshold": speaker_recognition_threshold(
                settings,
                "candidate_threshold",
                DEFAULT_SPEAKER_CONFIDENCE_THRESHOLD,
            ),
            "auto_merge_min_sample_confidence": speaker_recognition_threshold(
                settings,
                "auto_merge_min_sample_confidence",
                auto_merge_min_sample_confidence(settings.speaker_recognition),
            ),
            "representative_min_sample_confidence": speaker_recognition_threshold(
                settings,
                "representative_min_sample_confidence",
                representative_min_sample_confidence(settings.speaker_recognition),
            ),
            "review_min_confidence": speaker_recognition_threshold(settings, "review_min_confidence", 0.90),
        }
    }


def speaker_recognition_threshold(settings: Settings, key: str, default: float) -> float:
    config = getattr(settings, "speaker_recognition", {}) or {}
    try:
        value = float(config.get(key, default))
    except (TypeError, ValueError):
        return default
    if value <= 0 or value > 1:
        return default
    return value


def speaker_profiles_payload(
    store: Store,
    *,
    limit: int = 24,
    confidence_threshold: float | None = None,
) -> list[dict[str, Any]]:
    rows = store.list_speakers()
    active = [
        row
        for row in rows
        if str(row["identity_status"] or "") == "named"
        or speaker_review_status(row) in {"confirmed", "auto_merged_pending_review", "needs_review"}
    ]
    active.sort(key=lambda row: (-int(row["sample_count"] or 0), int(row["id"])))
    return [
        speaker_profile_payload(
            store,
            int(row["id"]),
            sample_limit=3,
            timeline_limit=4,
            confidence_threshold=confidence_threshold,
        )
        for row in active[:limit]
    ]


def speaker_profile_payload(
    store: Store,
    speaker_id: int,
    *,
    sample_limit: int = 8,
    timeline_limit: int = 12,
    confidence_threshold: float | None = None,
) -> dict[str, Any]:
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
            confidence_threshold=confidence_threshold,
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
        "audio_protected",
        "audio_protected_at",
        "audio_unprotected_at",
        "audio_pruned_at",
        "audio_pruned_reason",
        "audio_pruned_retention_days",
        "audio_recycle_path",
        "audio_recycle_delete_after",
        "voiceprint_retained",
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
    confidence = sample_confidence_value(metadata)
    if confidence is None:
        score -= 5.0
    else:
        score += confidence * 10.0
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


def representative_sample_eligible(sample: Any, *, min_confidence: float) -> bool:
    metadata = json_object(sample["metadata"])
    confidence = sample_confidence_value(metadata)
    return confidence is not None and confidence >= min_confidence


def representative_min_sample_confidence(config: dict[str, Any] | None) -> float:
    if not isinstance(config, dict):
        config = {}
    fallback = float_config(config.get("confirmed_profile_min_sample_confidence"), 0.55)
    return float_config(config.get("representative_min_sample_confidence"), fallback)


def auto_merge_min_sample_confidence(config: dict[str, Any] | None) -> float:
    if not isinstance(config, dict):
        config = {}
    fallback = float_config(config.get("confirmed_profile_min_sample_confidence"), 0.55)
    return float_config(config.get("auto_merge_min_sample_confidence"), fallback)


def sample_confidence_allows_automatic_merge(metadata: dict[str, Any], *, min_confidence: float) -> bool:
    confidence = sample_confidence_value(metadata)
    if confidence is None:
        return True
    return confidence >= min_confidence


def speaker_sample_audio_cleanup_enabled(config: dict[str, Any] | None) -> bool:
    if not isinstance(config, dict):
        return False
    value = config.get("sample_audio_cleanup_enabled", False)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def speaker_sample_audio_retention_days(config: dict[str, Any] | None) -> int:
    if not isinstance(config, dict):
        config = {}
    try:
        value = int(config.get("sample_audio_retention_days", 30))
    except (TypeError, ValueError):
        return 30
    return max(1, value)


def speaker_sample_audio_require_embedding(config: dict[str, Any] | None) -> bool:
    if not isinstance(config, dict):
        return True
    value = config.get("sample_audio_cleanup_require_embedding", True)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def audio_protected_metadata(metadata: dict[str, Any]) -> bool:
    for key in [
        "audio_protected",
        "protected_audio",
        "recording_protected",
        "speaker_sample_audio_protected",
    ]:
        if metadata.get(key) is True:
            return True
    return False


def speaker_sample_audio_protected(row: Any) -> bool:
    return (
        audio_protected_metadata(json_object(row["metadata"]))
        or audio_protected_metadata(json_object(row["speaker_metadata"] if "speaker_metadata" in row.keys() else None))
        or audio_protected_metadata(json_object(row["observation_metadata"] if "observation_metadata" in row.keys() else None))
    )


def path_inside_directory(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
    except (OSError, ValueError):
        return False
    return True


def speaker_sample_audio_prune_rows(store: Store) -> list[Any]:
    rows = store.conn.execute(
        """
        SELECT
            speaker_samples.*,
            speakers.display_name AS speaker_name,
            speakers.metadata AS speaker_metadata,
            observations.metadata AS observation_metadata,
            count(speaker_embeddings.id) AS embedding_count
        FROM speaker_samples
        JOIN speakers ON speakers.id = speaker_samples.speaker_id
        LEFT JOIN observations ON observations.id = speaker_samples.observation_id
        LEFT JOIN speaker_embeddings ON speaker_embeddings.sample_id = speaker_samples.id
        WHERE speaker_samples.sample_path IS NOT NULL
          AND trim(speaker_samples.sample_path) != ''
        GROUP BY speaker_samples.id
        ORDER BY speaker_samples.created_at ASC, speaker_samples.id ASC
        """
    ).fetchall()
    return list(rows)


def prune_speaker_sample_audio(
    settings: Settings,
    store: Store,
    *,
    today: date,
    dry_run: bool = True,
    older_than_days: int | None = None,
    limit: int | None = None,
) -> SpeakerSampleAudioPruneResult:
    config = settings.speaker_recognition if isinstance(settings.speaker_recognition, dict) else {}
    retention_days = max(1, int(older_than_days or speaker_sample_audio_retention_days(config)))
    cutoff_start, _ = day_bounds(today - timedelta(days=retention_days), settings.timezone)
    cutoff_iso = local_iso(cutoff_start)
    require_embedding = speaker_sample_audio_require_embedding(config)
    result = SpeakerSampleAudioPruneResult(dry_run=dry_run, retention_days=retention_days, cutoff_iso=cutoff_iso)
    sample_root = settings.speaker_sample_dir.expanduser().resolve()

    for row in speaker_sample_audio_prune_rows(store):
        if limit is not None and result.candidate_samples >= limit:
            break
        result.scanned_samples += 1
        created_at = str(row["created_at"] or "")
        if created_at >= cutoff_iso:
            continue
        if speaker_sample_audio_protected(row):
            result.protected_samples += 1
            continue
        if require_embedding and int(row["embedding_count"] or 0) <= 0:
            result.missing_embedding_samples += 1
            continue
        sample_path = Path(str(row["sample_path"] or "")).expanduser()
        if not sample_path.exists():
            result.missing_file_samples += 1
            continue
        if not sample_path.is_file() or sample_path.is_symlink():
            result.failed += 1
            if len(result.messages) < 40:
                result.messages.append(f"- Skipped sample {row['id']}: path is not a regular file.")
            continue
        if not path_inside_directory(sample_path, sample_root):
            result.outside_sample_dir_samples += 1
            continue
        size = 0
        try:
            size = sample_path.stat().st_size
        except OSError:
            size = 0
        result.candidate_samples += 1
        result.freed_bytes += size
        if dry_run:
            if len(result.messages) < 40:
                result.messages.append(f"- Would prune sample {row['id']}: {sample_path}")
            continue
        try:
            recycled = move_to_recycle_bin(
                settings,
                sample_path,
                category="speaker_sample_audio",
                metadata={
                    "reason": "speaker_sample_audio_retention",
                    "speaker_id": int(row["speaker_id"]),
                    "sample_id": int(row["id"]),
                    "sample_created_at": created_at,
                    "retention_days": retention_days,
                },
            )
            if not recycled.moved:
                raise OSError(recycled.error or "recycle move failed")
            metadata = json_object(row["metadata"])
            metadata.update(
                {
                    "audio_pruned_at": utc_iso(),
                    "audio_pruned_reason": "speaker_sample_audio_retention",
                    "audio_pruned_retention_days": retention_days,
                    "audio_original_sample_path": str(sample_path),
                    "audio_recycle_path": recycled.trash_path,
                    "audio_recycle_delete_after": recycled.delete_after,
                    "voiceprint_retained": True,
                }
            )
            store.conn.execute(
                """
                UPDATE speaker_samples
                SET sample_path = NULL,
                    metadata = ?
                WHERE id = ?
                """,
                (json.dumps(metadata, ensure_ascii=False, sort_keys=True), int(row["id"])),
            )
            store.conn.commit()
            result.pruned_samples += 1
            if len(result.messages) < 40:
                result.messages.append(f"- Pruned sample {row['id']}: moved to recycle bin {recycled.trash_path}.")
        except Exception as exc:
            result.failed += 1
            if len(result.messages) < 40:
                result.messages.append(f"- Failed sample {row['id']}: {exc}")
    return result


def mark_speaker_sample_audio_protection(
    store: Store,
    *,
    sample_ids: list[int],
    protected: bool = True,
) -> SpeakerAudioProtectionResult:
    result = SpeakerAudioProtectionResult()
    for sample_id in unique_positive_ints(sample_ids):
        row = store.get_speaker_sample(sample_id)
        if row is None:
            result.missing += 1
            result.messages.append(f"- Sample not found: {sample_id}.")
            continue
        metadata = json_object(row["metadata"])
        if protected:
            metadata["audio_protected"] = True
            metadata["audio_protected_at"] = utc_iso()
        else:
            metadata["audio_protected"] = False
            metadata["audio_unprotected_at"] = utc_iso()
        update_speaker_sample_metadata(store, sample_id, metadata)
        result.updated += 1
        verb = "Protected" if protected else "Unprotected"
        result.messages.append(f"- {verb} sample audio {sample_id}.")
    return result


def mark_speaker_audio_protection(
    store: Store,
    *,
    speaker_ids: list[int],
    protected: bool = True,
) -> SpeakerAudioProtectionResult:
    result = SpeakerAudioProtectionResult()
    for speaker_id in unique_positive_ints(speaker_ids):
        row = store.get_speaker(speaker_id)
        if row is None:
            result.missing += 1
            result.messages.append(f"- Speaker not found: {speaker_id}.")
            continue
        metadata = json_object(row["metadata"])
        if protected:
            metadata["audio_protected"] = True
            metadata["audio_protected_at"] = utc_iso()
        else:
            metadata["audio_protected"] = False
            metadata["audio_unprotected_at"] = utc_iso()
        update_speaker_metadata(store, speaker_id, metadata)
        result.updated += 1
        verb = "Protected" if protected else "Unprotected"
        result.messages.append(f"- {verb} speaker audio {speaker_id}.")
    return result


REGROUP_SAMPLE_SCORING_METADATA_KEYS = {
    "sample_confidence",
    "sample_confidence_basis",
    "sample_confidence_model",
    "sample_confidence_recalculated_at",
    "representative_sample",
    "representative_rank",
    "representative_score",
    "representative_refreshed_at",
}


def clear_regroup_sample_scoring_metadata(metadata: dict[str, Any]) -> None:
    previous_confidence = metadata.get("sample_confidence")
    previous_representative = metadata.get("representative_sample")
    for key in REGROUP_SAMPLE_SCORING_METADATA_KEYS:
        metadata.pop(key, None)
    if previous_confidence is not None:
        metadata.setdefault("sample_regroup_previous_confidence", previous_confidence)
    if previous_representative is not None:
        metadata.setdefault("sample_regroup_previous_representative_sample", previous_representative)


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
    exclude_speaker_ids: list[int] | None = None,
) -> SpeakerSampleRegroupResult:
    result = SpeakerSampleRegroupResult()
    model = embedding_model_key(settings)
    run_at = utc_iso()
    excluded_ids = set(unique_positive_ints(exclude_speaker_ids or []))
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
    target_rows = [
        row
        for row in rows
        if int(row["speaker_id"]) not in excluded_ids
        and json_object(row["metadata"]).get("sample_role") != "mixed_parent_archived"
    ]
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
            clear_regroup_sample_scoring_metadata(metadata)
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
    seconds = parse_seconds(settings.speaker_recognition.get("sample_seconds"))
    if seconds is None:
        seconds = SPEAKER_SAMPLE_DEFAULT_SECONDS
    return min(max(0.25, seconds), SPEAKER_SAMPLE_MAX_SECONDS)


def speaker_sample_stride_seconds(settings: Settings) -> float:
    stride = parse_seconds(settings.speaker_recognition.get("sample_stride_seconds"))
    if stride is None or stride <= 0:
        return speaker_sample_seconds(settings)
    return max(speaker_sample_min_seconds(settings), stride)


def speaker_sample_fine_window_seconds(settings: Settings) -> float:
    seconds = parse_seconds(settings.speaker_recognition.get("sample_fine_window_seconds"))
    if seconds is None:
        seconds = 3.0
    return min(speaker_sample_seconds(settings), max(speaker_sample_min_seconds(settings), seconds))


def speaker_sample_fine_stride_seconds(settings: Settings) -> float:
    stride = parse_seconds(settings.speaker_recognition.get("sample_fine_stride_seconds"))
    if stride is None or stride <= 0:
        return speaker_sample_fine_window_seconds(settings)
    return max(speaker_sample_min_seconds(settings), min(speaker_sample_fine_window_seconds(settings), stride))


def speaker_sample_segment_uses_fine_windows(settings: Settings, segment: dict[str, Any]) -> bool:
    if speaker_sample_segment_mixed_speaker_risk(segment):
        return True
    start = parse_seconds(segment.get("start"))
    end = parse_seconds(segment.get("end"))
    if start is None or end is None or end <= start:
        return False
    return (end - start) > speaker_sample_seconds(settings) + 0.01


def speaker_sample_window_seconds(settings: Settings, segment: dict[str, Any]) -> float:
    if speaker_sample_segment_uses_fine_windows(settings, segment):
        return speaker_sample_fine_window_seconds(settings)
    return speaker_sample_seconds(settings)


def speaker_sample_window_stride_seconds(settings: Settings, segment: dict[str, Any], window_seconds: float | None = None) -> float:
    if speaker_sample_segment_uses_fine_windows(settings, segment):
        return speaker_sample_fine_stride_seconds(settings)
    return speaker_sample_stride_seconds(settings)


def speaker_samples_per_speaker_per_observation(settings: Settings) -> int:
    raw = settings.speaker_recognition.get("samples_per_speaker_per_observation")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = SPEAKER_SAMPLE_DEFAULT_MAX_PER_SPEAKER_OBSERVATION
    return min(200, max(1, value))


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
    sample_seconds = speaker_sample_seconds(settings)
    existing_clip = existing_sample_clip(sample)
    if existing_clip and clip_within_segment(existing_clip, start, end) and sample_clip_duration(existing_clip) <= sample_seconds + 0.01:
        clip = existing_clip
    else:
        clip = clip_bounds(
            start,
            end,
            duration_seconds=sample_duration_seconds(observation_metadata),
            sample_seconds=sample_seconds,
            sample_min_seconds=speaker_sample_min_seconds(settings),
            boundary_guard_seconds=speaker_sample_boundary_guard_seconds(settings),
            long_segment_anchor=speaker_sample_long_segment_anchor(settings),
        )
    if clip is None:
        return {"ok": False, "status": "skipped_invalid_clip_bounds"}
    label = speaker_sample_plan_label(sample, segment)
    full_transcript = text_value(segment.get("text"), limit=2000)
    transcript = sample_transcript_for_clip(segment, clip)
    segment_score = speaker_sample_segment_score(segment)
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
        "sample_segment_score": round(segment_score, 4) if segment_score is not None else None,
        "sample_segment_mixed_speaker_risk": speaker_sample_segment_mixed_speaker_risk(segment),
        "clip_strategy": {
            "long_segment_anchor": speaker_sample_long_segment_anchor(settings),
            "sample_seconds": sample_seconds,
            "boundary_guard_seconds": speaker_sample_boundary_guard_seconds(settings),
        },
    }


def existing_sample_clip(sample: Any) -> tuple[float, float] | None:
    start = parse_seconds(sample["start_seconds"])
    end = parse_seconds(sample["end_seconds"])
    if start is None or end is None or end <= start:
        return None
    return (start, end)


def sample_clip_duration(clip: tuple[float, float]) -> float:
    return max(0.0, clip[1] - clip[0])


def clip_within_segment(clip: tuple[float, float], start: float | None, end: float | None) -> bool:
    if start is None or end is None or end <= start:
        return False
    return clip[0] >= max(0.0, start) - 0.01 and clip[1] <= end + 0.01


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
        "sample_segment_score": plan.get("sample_segment_score"),
        "sample_segment_mixed_speaker_risk": plan.get("sample_segment_mixed_speaker_risk"),
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
    allow_pending_review: bool = False,
) -> SpeakerAutoOrganizeResult:
    model = embedding_model_key(settings)
    config = settings.speaker_recognition if isinstance(settings.speaker_recognition, dict) else {}
    merge_threshold = float(threshold if threshold is not None else settings.speaker_recognition.get("auto_merge_threshold", 0.68))
    min_sample_confidence = auto_merge_min_sample_confidence(config)
    max_profile_prototypes = speaker_profile_max_prototypes(config)
    profile_outlier_min_similarity = speaker_profile_outlier_min_similarity(config)
    result = SpeakerAutoOrganizeResult(threshold=merge_threshold)
    affected_speaker_ids: set[int] = set()
    review_candidate_speaker_ids: set[int] = set()
    pending_auto_merge_sources: dict[int, list[dict[str, Any]]] = {}
    merge_budget = max(0, int(max_merges))
    min_cluster_confidence = max(min_sample_confidence, merge_threshold)
    try:
        min_review_samples = int(config.get("review_min_samples", 5))
    except (TypeError, ValueError):
        min_review_samples = 5
    min_review_samples = max(1, min_review_samples)

    while result.merged_speakers < merge_budget:
        rows = {int(row["id"]): row for row in store.list_speakers()}
        vectors_by_speaker = speaker_vectors_by_speaker(
            store,
            model=model,
            min_sample_confidence=min_sample_confidence,
        )
        stability_vectors_by_speaker = speaker_vectors_by_speaker(
            store,
            model=model,
            min_sample_confidence=None,
        )
        candidates = speaker_merge_candidates(
            rows,
            vectors_by_speaker,
            threshold=merge_threshold,
            max_prototypes=max_profile_prototypes,
            outlier_min_similarity=profile_outlier_min_similarity,
            allow_pending_review=allow_pending_review,
        )
        result.scanned_pairs += speaker_pair_count(vectors_by_speaker)
        result.merge_candidates += len(candidates)
        if not candidates:
            break
        selected_candidates, unstable_skipped = stable_disjoint_speaker_merge_candidates(
            candidates,
            vectors_by_speaker=stability_vectors_by_speaker,
            min_cluster_confidence=min_cluster_confidence,
            max_pairs=len(candidates),
        )
        result.unstable_merge_candidates += unstable_skipped
        if unstable_skipped and len(result.messages) < 40:
            result.messages.append(
                f"- Merge round {result.merge_rounds + 1}: skipped {unstable_skipped} unstable candidate pair(s)."
            )
        if not selected_candidates:
            break
        result.merge_rounds += 1
        if len(result.messages) < 40:
            result.messages.append(
                f"- Merge round {result.merge_rounds}: selected {len(selected_candidates)} "
                f"of {len(candidates)} candidate pair(s)."
            )

        round_failed = False
        round_merges = 0
        for candidate in selected_candidates:
            if result.merged_speakers >= merge_budget:
                break
            source_id, target_id = choose_auto_merge_direction(rows, int(candidate["left_id"]), int(candidate["right_id"]))
            source = rows[source_id]
            target = rows[target_id]
            source_samples = store.list_speaker_samples(source_id)
            try:
                combined_stability = candidate.get("cluster_stability")
                if combined_stability is None:
                    combined_stability = cluster_min_leave_one_out_similarity(
                        [
                            *(stability_vectors_by_speaker.get(source_id) or []),
                            *(stability_vectors_by_speaker.get(target_id) or []),
                        ]
                    )
                if combined_stability is None or combined_stability < min_cluster_confidence:
                    result.unstable_merge_candidates += 1
                    if len(result.messages) < 40:
                        score_text = format_confidence(combined_stability)
                        result.messages.append(
                            "- Skipped unstable merge "
                            f"{speaker_label(source)} -> {speaker_label(target)} "
                            f"cluster_min={score_text} required={min_cluster_confidence:.3f}."
                        )
                    continue
                if auto_merge_requires_manual_review(source, target, allow_pending_review=allow_pending_review):
                    recorded = record_auto_merge_candidate_for_review(
                        store,
                        source_id=source_id,
                        target_id=target_id,
                        model=model,
                        candidate=candidate,
                        threshold=merge_threshold,
                        merge_round=result.merge_rounds,
                        source=source,
                        target=target,
                    )
                    review_candidate_speaker_ids.update({source_id, target_id})
                    if recorded:
                        result.review_candidates += 1
                        if len(result.messages) < 40:
                            result.messages.append(
                                "- Queued manual review candidate "
                                f"{speaker_label(source)} -> {speaker_label(target)} "
                                f"score={candidate['score']:.3f}."
                            )
                    continue
                store.record_speaker_match_decision(
                    source_speaker_id=source_id,
                    target_speaker_id=target_id,
                    sample_id=None,
                    model=model,
                    score=float(candidate["score"]),
                    threshold=merge_threshold,
                    status="auto_merged_pending_review",
                    metadata={
                        "decision": "existing_speaker_profiles_above_auto_merge_threshold",
                        "workflow": "auto_organize_speakers",
                        "matcher": candidate.get("matcher", "speaker_profile"),
                        "left_profile_prototype_count": candidate.get("left_prototype_count"),
                        "right_profile_prototype_count": candidate.get("right_prototype_count"),
                        "merge_round": result.merge_rounds,
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
                    round_failed = True
                    break
                target_sources = pending_auto_merge_sources.pop(target_id, auto_merge_sources_from_metadata(target))
                source_sources = pending_auto_merge_sources.pop(source_id, auto_merge_sources_from_metadata(source))
                pending_auto_merge_sources[target_id] = [
                    *target_sources,
                    *source_sources,
                    auto_merge_source_entry(
                        source=source,
                        target=target,
                        score=float(candidate["score"]),
                        threshold=merge_threshold,
                    ),
                ][-50:]
                store.update_speaker_identity_status(
                    target_id,
                    status="provisional",
                    confidence=round(float(combined_stability), 12),
                )
                result.merged_speakers += 1
                round_merges += 1
                result.moved_sample_files += moved_files
                affected_speaker_ids.add(target_id)
                if len(result.messages) < 40:
                    result.messages.append(
                        "- Auto-merged "
                        f"{speaker_label(source)} -> {speaker_label(target)} "
                        f"score={candidate['score']:.3f} cluster_min={combined_stability:.3f}."
                    )
            except Exception as exc:
                result.failed += 1
                result.messages.append(f"- Merge failed {source_id} -> {target_id}: {exc}")
                round_failed = True
                break
        if round_failed:
            break
        if round_merges == 0:
            break

    for speaker_id, sources in sorted(pending_auto_merge_sources.items()):
        if store.get_speaker(speaker_id) is None:
            continue
        last_score = None
        if sources:
            try:
                last_score = float(sources[-1].get("score"))
            except (TypeError, ValueError):
                last_score = None
        mark_auto_merge_pending_review(
            store,
            speaker_id,
            score=last_score if last_score is not None else merge_threshold,
            threshold=merge_threshold,
            sources=sources,
        )

    if hide_unmatched:
        for row in store.list_speakers():
            speaker_id = int(row["id"])
            if speaker_id in affected_speaker_ids:
                continue
            if speaker_id in review_candidate_speaker_ids:
                continue
            if should_queue_unmatched_speaker_for_review(row, min_samples=min_review_samples):
                if mark_unmatched_speaker_needs_review(store, row, min_samples=min_review_samples, threshold=merge_threshold):
                    result.evidence_review_speakers += 1
                    if len(result.messages) < 40:
                        result.messages.append(
                            f"- Queued evidence-rich speaker {speaker_label(row)} for review "
                            f"(samples={int(row['sample_count'] or 0)})."
                        )
                continue
            if should_hide_unmatched_speaker(row):
                if mark_speaker_hidden(store, row, threshold=merge_threshold):
                    result.hidden_speakers += 1
                    if len(result.messages) < 40:
                        result.messages.append(f"- Hid low-similarity speaker {speaker_label(row)}.")

    refresh_ids = sorted(speaker_id for speaker_id in affected_speaker_ids if store.get_speaker(speaker_id) is not None)
    if refresh_ids:
        refresh = refresh_speaker_sample_confidences(settings, store, speaker_ids=refresh_ids)
        result.refreshed_samples = refresh.updated_samples
        result.failed += refresh.failed
        for line in refresh.messages[:8]:
            if len(result.messages) < 50:
                result.messages.append(line)
    if (
        result.merged_speakers == 0
        and result.hidden_speakers == 0
        and result.review_candidates == 0
        and result.evidence_review_speakers == 0
    ):
        result.messages.append("- No speakers needed automatic merge or hiding.")
    return result


def disjoint_speaker_merge_candidates(candidates: list[dict[str, Any]], *, max_pairs: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    used_speaker_ids: set[int] = set()
    if max_pairs <= 0:
        return selected
    for candidate in candidates:
        left_id = int(candidate["left_id"])
        right_id = int(candidate["right_id"])
        if left_id in used_speaker_ids or right_id in used_speaker_ids:
            continue
        selected.append(candidate)
        used_speaker_ids.update({left_id, right_id})
        if len(selected) >= max_pairs:
            break
    return selected


def stable_disjoint_speaker_merge_candidates(
    candidates: list[dict[str, Any]],
    *,
    vectors_by_speaker: dict[int, list[list[float]]],
    min_cluster_confidence: float,
    max_pairs: int,
) -> tuple[list[dict[str, Any]], int]:
    selected: list[dict[str, Any]] = []
    used_speaker_ids: set[int] = set()
    unstable_skipped = 0
    if max_pairs <= 0:
        return selected, unstable_skipped
    for candidate in candidates:
        left_id = int(candidate["left_id"])
        right_id = int(candidate["right_id"])
        if left_id in used_speaker_ids or right_id in used_speaker_ids:
            continue
        stability = cluster_min_leave_one_out_similarity(
            [
                *(vectors_by_speaker.get(left_id) or []),
                *(vectors_by_speaker.get(right_id) or []),
            ]
        )
        if stability is None or stability < min_cluster_confidence:
            unstable_skipped += 1
            continue
        selected_candidate = dict(candidate)
        selected_candidate["cluster_stability"] = stability
        selected.append(selected_candidate)
        used_speaker_ids.update({left_id, right_id})
        if len(selected) >= max_pairs:
            break
    return selected, unstable_skipped


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


def speaker_vectors_by_speaker(
    store: Store,
    *,
    model: str,
    min_sample_confidence: float | None = None,
) -> dict[int, list[list[float]]]:
    vectors: dict[int, list[list[float]]] = {}
    for row in store.speaker_embedding_rows(model=model):
        parsed = parse_vector(row["vector"])
        if parsed is None:
            continue
        if min_sample_confidence is not None:
            metadata = json_object(row["sample_metadata"] if "sample_metadata" in row.keys() else None)
            if not sample_confidence_allows_automatic_merge(metadata, min_confidence=min_sample_confidence):
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
    max_prototypes: int = 6,
    outlier_min_similarity: float = 0.55,
    allow_pending_review: bool = False,
) -> list[dict[str, Any]]:
    profiles = {
        speaker_id: speaker_voice_profile_from_vectors(
            vectors,
            max_prototypes=max_prototypes,
            outlier_min_similarity=outlier_min_similarity,
        )
        for speaker_id, vectors in vectors_by_speaker.items()
        if speaker_id in speaker_rows and vectors
    }
    candidates: list[dict[str, Any]] = []
    ids = sorted(profiles)
    for index, left_id in enumerate(ids):
        left = profiles[left_id]
        if left is None:
            continue
        if not speaker_auto_organize_match_eligible(
            speaker_rows[left_id],
            threshold=threshold,
            allow_pending_review=allow_pending_review,
        ):
            continue
        for right_id in ids[index + 1 :]:
            right = profiles[right_id]
            if right is None:
                continue
            if not speaker_auto_organize_match_eligible(
                speaker_rows[right_id],
                threshold=threshold,
                allow_pending_review=allow_pending_review,
            ):
                continue
            if not auto_merge_pair_allowed(speaker_rows[left_id], speaker_rows[right_id]):
                continue
            score = clamp_similarity(speaker_voice_profiles_similarity(left, right))
            if score >= threshold:
                candidates.append(
                    {
                        "left_id": left_id,
                        "right_id": right_id,
                        "score": score,
                        "matcher": "speaker_profile",
                        "left_prototype_count": left.prototype_count,
                        "right_prototype_count": right.prototype_count,
                        "left_profile_outliers": left.outlier_count,
                        "right_profile_outliers": right.outlier_count,
                    }
                )
    candidates.sort(key=lambda item: (-float(item["score"]), int(item["left_id"]), int(item["right_id"])))
    return candidates


def speaker_auto_organize_match_eligible(row: Any, *, threshold: float, allow_pending_review: bool = False) -> bool:
    if row is None:
        return False
    review_status = speaker_review_status(row)
    if review_status == "confirmed":
        return speaker_cluster_match_eligible(row, threshold=threshold)
    if review_status in {"low_similarity_hidden", "needs_review"}:
        return False
    if review_status == "auto_merged_pending_review" and not allow_pending_review:
        return False
    identity_status = str(row["identity_status"] or "").strip()
    if identity_status in {"named", "confirmed", "accepted"}:
        return False
    return True


def auto_merge_pair_allowed(left: Any, right: Any) -> bool:
    left_status = speaker_review_status(left)
    right_status = speaker_review_status(right)
    if left_status == "confirmed" and right_status == "confirmed":
        return False
    return True


def auto_merge_requires_manual_review(left: Any, right: Any, *, allow_pending_review: bool = False) -> bool:
    return speaker_protected_from_auto_merge(
        left,
        allow_pending_review=allow_pending_review,
    ) or speaker_protected_from_auto_merge(
        right,
        allow_pending_review=allow_pending_review,
    )


def speaker_protected_from_auto_merge(row: Any, *, allow_pending_review: bool = False) -> bool:
    review_status = speaker_review_status(row)
    identity_status = str(row["identity_status"] or "").strip()
    protected_review_statuses = {"confirmed", "needs_review"}
    if not allow_pending_review:
        protected_review_statuses.add("auto_merged_pending_review")
    return review_status in protected_review_statuses or identity_status in {
        "named",
        "confirmed",
        "accepted",
    }


def record_auto_merge_candidate_for_review(
    store: Store,
    *,
    source_id: int,
    target_id: int,
    model: str,
    candidate: dict[str, Any],
    threshold: float,
    merge_round: int,
    source: Any,
    target: Any,
) -> bool:
    existing = store.conn.execute(
        """
        SELECT id
        FROM speaker_match_decisions
        WHERE status IN ('candidate', 'auto_merged_pending_review')
          AND (
            (source_speaker_id = ? AND target_speaker_id = ?)
            OR (source_speaker_id = ? AND target_speaker_id = ?)
          )
        LIMIT 1
        """,
        (source_id, target_id, target_id, source_id),
    ).fetchone()
    if existing is not None:
        return False
    store.record_speaker_match_decision(
        source_speaker_id=source_id,
        target_speaker_id=target_id,
        sample_id=None,
        model=model,
        score=float(candidate["score"]),
        threshold=threshold,
        status="candidate",
        metadata={
            "decision": "manual_review_required_for_named_or_confirmed_speaker",
            "workflow": "auto_organize_speakers",
            "matcher": candidate.get("matcher", "speaker_profile"),
            "left_profile_prototype_count": candidate.get("left_prototype_count"),
            "right_profile_prototype_count": candidate.get("right_prototype_count"),
            "merge_round": merge_round,
            "left_speaker_id": candidate["left_id"],
            "right_speaker_id": candidate["right_id"],
            "source_sample_count": source["sample_count"],
            "target_sample_count": target["sample_count"],
        },
    )
    return True


def auto_merge_sources_from_metadata(row: Any) -> list[dict[str, Any]]:
    metadata = json_object(row["metadata"])
    sources = metadata.get("auto_merge_sources")
    if not isinstance(sources, list):
        return []
    return [source for source in sources if isinstance(source, dict)]


def auto_merge_source_entry(
    *,
    source: Any,
    target: Any,
    score: float,
    threshold: float,
) -> dict[str, Any]:
    return {
        "source_speaker_id": int(source["id"]),
        "source_display_name": str(source["display_name"]),
        "target_speaker_id": int(target["id"]),
        "target_display_name": str(target["display_name"]),
        "score": round(score, 4),
        "threshold": round(threshold, 4),
        "merged_at": utc_iso(),
    }


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
    score: float,
    threshold: float,
    source: Any | None = None,
    target: Any | None = None,
    sources: list[dict[str, Any]] | None = None,
) -> None:
    row = store.get_speaker(speaker_id)
    if row is None:
        return
    metadata = json_object(row["metadata"])
    if sources is None:
        sources = auto_merge_sources_from_metadata(row)
        if source is not None and target is not None:
            sources.append(auto_merge_source_entry(source=source, target=target, score=score, threshold=threshold))
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
    if status in {"confirmed", "auto_merged_pending_review", "needs_review"}:
        return False
    return True


def should_queue_unmatched_speaker_for_review(row: Any, *, min_samples: int) -> bool:
    if row is None:
        return False
    if str(row["identity_status"] or "") == "named":
        return False
    status = speaker_review_status(row)
    if status in {"confirmed", "auto_merged_pending_review", "needs_review", "low_similarity_hidden"}:
        return False
    try:
        sample_count = int(row["sample_count"] or 0)
    except (TypeError, ValueError):
        sample_count = 0
    return sample_count >= max(1, int(min_samples))


def mark_unmatched_speaker_needs_review(store: Store, row: Any, *, min_samples: int, threshold: float) -> bool:
    speaker_id = int(row["id"])
    metadata = json_object(row["metadata"])
    if metadata.get("speaker_review_status") == "needs_review" and metadata.get("speaker_hidden") is False:
        return False
    metadata.update(
        {
            "speaker_review_status": "needs_review",
            "speaker_hidden": False,
            "needs_review_at": utc_iso(),
            "needs_review_reason": "sample_count_above_review_minimum",
            "needs_review_min_samples": int(min_samples),
            "needs_review_sample_count": int(row["sample_count"] or 0),
            "needs_review_auto_merge_threshold": round(float(threshold), 4),
        }
    )
    update_speaker_metadata(store, speaker_id, metadata)
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
    profile = speaker_voice_profile_from_vectors(same_dimension)
    if profile is None:
        return None
    return clamp_similarity(speaker_voice_profile_core_score(vector, profile))


def sample_confidences_for_vectors(vectors: list[tuple[int, list[float]]]) -> dict[int, tuple[float, str]]:
    if not vectors:
        return {}
    dimension = len(vectors[0][1])
    same_dimension = [(sample_id, vector) for sample_id, vector in vectors if len(vector) == dimension]
    if not same_dimension:
        return {}
    if len(same_dimension) == 1:
        sample_id, _vector = same_dimension[0]
        return {sample_id: (1.0, "single_sample")}
    if len(same_dimension) <= SPEAKER_SAMPLE_CONFIDENCE_EXACT_LIMIT:
        results: dict[int, tuple[float, str]] = {}
        for sample_id, vector in same_dimension:
            comparison = [other for other_id, other in same_dimension if other_id != sample_id]
            score = sample_confidence_for_vector(vector, comparison)
            if score is not None:
                results[sample_id] = (score, "leave_one_out_robust_profile")
        return results

    profile = speaker_voice_profile_from_vectors([vector for _sample_id, vector in same_dimension])
    if profile is None:
        return {}
    return {
        sample_id: (clamp_similarity(speaker_voice_profile_core_score(vector, profile)), "cluster_robust_profile")
        for sample_id, vector in same_dimension
    }


def cluster_min_leave_one_out_similarity(vectors: list[list[float]]) -> float | None:
    if not vectors:
        return None
    dimension = len(vectors[0])
    same_dimension = [vector for vector in vectors if len(vector) == dimension]
    if len(same_dimension) <= 1:
        return 1.0
    scores: list[float] = []
    for index, vector in enumerate(same_dimension):
        comparison = same_dimension[:index] + same_dimension[index + 1 :]
        score = sample_confidence_for_vector(vector, comparison)
        if score is None:
            return None
        scores.append(score)
    return min(scores) if scores else None


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
        score = speaker_sample_segment_score(segment)
        if score is None:
            continue
        scored.append((score, segment))
    if not scored:
        return None
    return max(scored, key=lambda item: item[0])[1]


def speaker_sample_plans_for_segments(
    settings: Settings,
    segments: list[dict[str, Any]],
    duration_seconds: float | None,
) -> list[tuple[dict[str, Any], tuple[float, float]]]:
    limit = speaker_samples_per_speaker_per_observation(settings)
    ordered = sorted(
        (
            segment
            for segment in segments
            if isinstance(segment, dict)
            and segment_is_speech_like(segment)
        ),
        key=lambda segment: parse_seconds(segment.get("start")) or 0.0,
    )
    if not ordered or limit <= 0:
        return []

    clip_groups: list[tuple[dict[str, Any], list[tuple[float, float]]]] = []
    for segment in ordered:
        clips = speaker_sample_clips_for_segment(settings, segment, duration_seconds, limit=limit)
        if clips:
            clip_groups.append((segment, clips))
    if not clip_groups:
        return []

    selected_indices = evenly_spaced_indices(len(clip_groups), limit)
    selected_groups = [clip_groups[index] for index in selected_indices]
    plans: list[tuple[dict[str, Any], tuple[float, float]]] = []
    for segment, clips in selected_groups:
        plans.append((segment, clips[0]))
        if len(plans) >= limit:
            return plans

    extra_index = 1
    while len(plans) < limit:
        added = False
        for segment, clips in selected_groups:
            if extra_index >= len(clips):
                continue
            plans.append((segment, clips[extra_index]))
            added = True
            if len(plans) >= limit:
                break
        if not added:
            break
        extra_index += 1
    return plans


def evenly_spaced_indices(count: int, limit: int) -> list[int]:
    if count <= 0 or limit <= 0:
        return []
    if count <= limit:
        return list(range(count))
    if limit == 1:
        return [0]
    indices: list[int] = []
    for index in range(limit):
        selected = int(round(index * (count - 1) / (limit - 1)))
        if selected not in indices:
            indices.append(selected)
    if len(indices) < limit:
        for selected in range(count):
            if selected not in indices:
                indices.append(selected)
                if len(indices) >= limit:
                    break
    return sorted(indices[:limit])


def speaker_sample_clips_for_segment(
    settings: Settings,
    segment: dict[str, Any],
    duration_seconds: float | None,
    *,
    limit: int,
) -> list[tuple[float, float]]:
    if limit <= 0:
        return []
    start = parse_seconds(segment.get("start"))
    end = parse_seconds(segment.get("end"))
    if start is None or end is None or end <= start:
        return []

    sample_seconds = speaker_sample_window_seconds(settings, segment)
    min_seconds = speaker_sample_min_seconds(settings)
    boundary_guard = speaker_sample_boundary_guard_seconds(settings)
    fallback = clip_bounds(
        start,
        end,
        duration_seconds=duration_seconds,
        sample_seconds=sample_seconds,
        sample_min_seconds=min_seconds,
        boundary_guard_seconds=boundary_guard,
        long_segment_anchor=speaker_sample_long_segment_anchor(settings),
    )
    if fallback is None:
        return []

    segment_duration = end - start
    if segment_duration <= sample_seconds + 0.01 or limit == 1:
        return [fallback]

    clip_start = max(0.0, start)
    clip_end = end
    if duration_seconds is not None:
        clip_end = min(clip_end, duration_seconds)
    guarded_start = clip_start
    guarded_end = clip_end
    if clip_end - clip_start > boundary_guard * 2 + min_seconds:
        guarded_start += boundary_guard
        guarded_end -= boundary_guard
    available = guarded_end - guarded_start
    if available < min_seconds:
        return [fallback]

    window_len = min(sample_seconds, available)
    stride = speaker_sample_window_stride_seconds(settings, segment, sample_seconds)
    last_start = max(guarded_start, guarded_end - window_len)
    clips: list[tuple[float, float]] = []
    cursor = guarded_start
    while cursor <= last_start + 0.01 and len(clips) < limit:
        clips.append((round(cursor, 3), round(cursor + window_len, 3)))
        cursor += stride

    tail = (round(last_start, 3), round(last_start + window_len, 3))
    if len(clips) < limit and tail not in clips:
        if not clips or tail[0] - clips[-1][0] >= max(min_seconds, window_len * 0.5):
            clips.append(tail)
    return clips or [fallback]


def speaker_sample_source_segments(settings: Settings, timeline: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    diarized = timeline.get("speaker_diarization_segments")
    if isinstance(diarized, list):
        segments: list[dict[str, Any]] = []
        for index, segment in enumerate(diarized, start=1):
            if not isinstance(segment, dict):
                continue
            start = parse_seconds(segment.get("start"))
            end = parse_seconds(segment.get("end"))
            speaker = normalize_speaker_label(segment.get("speaker"))
            text = text_value(segment.get("text"), limit=2000)
            if start is None or end is None or end <= start or not speaker or not text:
                continue
            item = dict(segment)
            item["start"] = start
            item["end"] = end
            item["speaker"] = speaker
            item.setdefault("speaker_local_label", normalize_speaker_label(segment.get("speaker_local_label")) or speaker)
            item["speaker_label_source"] = "speaker_diarization_segments"
            item["speaker_sample_source"] = "speaker_diarization_segments"
            item["speaker_sample_source_index"] = index
            if segment_is_speech_like(item):
                segments.append(item)
        if segments:
            return segments, "speaker_diarization_segments"
    if cfg_bool(settings.speaker_recognition, "sample_require_diarization_segments", False):
        return [], "missing_speaker_diarization_segments"

    speech_segments = timeline.get("speech_segments")
    if isinstance(speech_segments, list):
        return speech_segments, "speech_segments"
    return [], "none"


def speaker_sample_segment_score(segment: dict[str, Any]) -> float | None:
    if not segment_is_speech_like(segment):
        return None
    start = parse_seconds(segment.get("start"))
    end = parse_seconds(segment.get("end"))
    duration = max(0.0, (end or 0.0) - (start or 0.0)) if start is not None and end is not None else 0.0
    text = text_value(segment.get("text"), limit=800) or ""
    score = min(duration, 4.0) + min(len(text) / 100.0, 2.0)
    if duration < 0.7:
        score -= 2.0
    if duration > 5.0:
        score -= (duration - 5.0) * 0.9
    if duration > 12.0:
        score -= 4.0
    if len(text.strip()) < 8:
        score -= 1.0
    if text_repetition_ratio(text) > 0.65:
        score -= 6.0
    if speaker_sample_segment_mixed_speaker_risk(segment):
        score -= 12.0
    return score


def speaker_sample_segment_mixed_speaker_risk(segment: dict[str, Any]) -> bool:
    if segment_is_overlapping_speech(segment):
        return True
    start = parse_seconds(segment.get("start"))
    end = parse_seconds(segment.get("end"))
    duration = max(0.0, (end or 0.0) - (start or 0.0)) if start is not None and end is not None else 0.0
    if duration < 4.0:
        return False
    text = text_value(segment.get("text"), limit=1200) or ""
    if not text.strip():
        return False
    signals = transcript_turn_signals(text)
    if duration >= 5.0 and signals["speaker_prefixes"] >= 2:
        return True
    if duration >= 5.0 and signals["questions"] >= 2 and signals["short_parts"] >= 2:
        return True
    if duration >= 6.0 and signals["quote_marks"] >= 2 and signals["questions"] >= 1:
        return True
    if duration >= 8.0 and signals["sentence_parts"] >= 6 and signals["short_parts"] >= 4 and signals["questions"] >= 1:
        return True
    return False


def transcript_turn_signals(text: str) -> dict[str, int]:
    cleaned = text.strip()
    parts = [part.strip() for part in re.split(r"[。.!！？?…]+", cleaned) if part.strip()]
    return {
        "questions": len(re.findall(r"[?？]", cleaned)),
        "quote_marks": len(re.findall(r"[\"'“”‘’「」『』]", cleaned)),
        "speaker_prefixes": len(
            re.findall(
                r"(?:^|[\n。.!！？?])\s*(?:speaker\s*\d+|話者\s*\d+|発話者\s*\d+|说话人\s*\d+)[:：]",
                cleaned,
                re.IGNORECASE,
            )
        ),
        "sentence_parts": len(parts),
        "short_parts": sum(1 for part in parts if 1 <= len(re.sub(r"\s+", "", part)) <= 12),
    }


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
        segment_quality = speaker_sample_segment_score(segment)
        if segment_quality is None:
            continue
        start = parse_seconds(segment.get("start"))
        end = parse_seconds(segment.get("end"))
        if start is None or end is None or end <= start:
            continue
        overlap = max(0.0, min(clip_end, end) - max(clip_start, start))
        overlaps_current_window = overlap > 0 or (start <= clip_start <= end)
        if not overlaps_current_window:
            continue
        segment_label = normalize_speaker_label(
            segment.get("speaker_local_label") or segment.get("local_label") or segment.get("speaker")
        )
        segment_scope = normalize_speaker_scope(segment.get("speaker_scope"))
        score = min(overlap, 12.0) + (segment_quality * 10.0)
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
