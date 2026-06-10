from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np

from .config import Settings
from .executables import find_executable
from .store import Store, json_dict


@dataclass
class IdentityMatchResult:
    speaker_id: int
    status: str
    score: float | None = None
    target_speaker_id: int | None = None
    confidence: float | None = None
    message: str | None = None


@dataclass
class ExistingSpeakerMatch:
    speaker_id: int
    score: float
    matcher: str
    prototype_count: int = 1
    confirmed_profile: bool = False
    trusted_profile: bool = False
    trusted_sample_count: int = 0


@dataclass
class SpeakerVoicePrototype:
    vector: np.ndarray
    kind: str
    support: int = 1
    weight: float = 1.0


@dataclass
class SpeakerVoiceProfile:
    prototypes: list[SpeakerVoicePrototype]
    sample_count: int
    trusted_sample_count: int
    outlier_count: int
    method: str = "robust_multi_prototype"

    @property
    def prototype_count(self) -> int:
        return len(self.prototypes)


_SPEECHBRAIN_MODEL: Any | None = None
_SPEECHBRAIN_SOURCE: str | None = None
_SPEECHBRAIN_SAVEDIR: str | None = None


def update_speaker_identity_for_sample(
    settings: Settings,
    store: Store,
    *,
    speaker_id: int,
    sample_id: int | None,
    sample_path: str | None,
) -> IdentityMatchResult:
    if not sample_path:
        return IdentityMatchResult(speaker_id=speaker_id, status="no_sample_path")
    path = Path(sample_path)
    if not path.exists():
        return IdentityMatchResult(speaker_id=speaker_id, status="missing_sample")

    model_key = embedding_model_key(settings)
    try:
        vector = speaker_embedding(settings, path)
    except RuntimeError as exc:
        store.record_speaker_match_decision(
            source_speaker_id=speaker_id,
            target_speaker_id=None,
            sample_id=sample_id,
            model=model_key,
            score=None,
            threshold=None,
            status="embedding_unavailable",
            metadata={"error": str(exc)},
        )
        return IdentityMatchResult(speaker_id=speaker_id, status="embedding_unavailable", message=str(exc))

    store.add_speaker_embedding(
        speaker_id=speaker_id,
        sample_id=sample_id,
        model=model_key,
        vector=vector,
        metadata={"sample_path": sample_path},
    )

    config = settings.speaker_recognition if isinstance(settings.speaker_recognition, dict) else {}
    auto_threshold = float_config(config.get("auto_merge_threshold"), 0.68)
    candidate_threshold = float_config(config.get("candidate_threshold"), 0.68)
    confirmed_auto_threshold = float_config(
        config.get("confirmed_profile_auto_merge_threshold"),
        max(auto_threshold, 0.78),
    )
    min_auto_sample_confidence = float_config(
        config.get("auto_merge_min_sample_confidence"),
        float_config(config.get("confirmed_profile_min_sample_confidence"), 0.55),
    )
    best = best_existing_speaker_match(settings, store, model=model_key, speaker_id=speaker_id, vector=vector)
    if best is None:
        confidence = refresh_identity_status(settings, store, speaker_id, model_key)
        return IdentityMatchResult(speaker_id=speaker_id, status="new_identity", confidence=confidence)

    target_id = best.speaker_id
    score = best.score
    source_row = speaker_stats_row(store, speaker_id)
    target_row = speaker_stats_row(store, target_id)
    protected_target = speaker_match_requires_manual_review(target_row)
    effective_auto_threshold = confirmed_auto_threshold if best.confirmed_profile and protected_target else auto_threshold
    source_sample_row = store.get_speaker_sample(sample_id) if sample_id is not None else None
    source_sample_auto_merge_safe = source_sample_safe_for_auto_merge(
        source_sample_row,
        threshold=min_auto_sample_confidence,
    )
    if score >= effective_auto_threshold and speaker_match_auto_merge_allowed(
        best,
        source_row=source_row,
        target_row=target_row,
        config=config,
        source_confidence_threshold=candidate_threshold,
    ) and source_sample_auto_merge_safe:
        decision = (
            "trusted_confirmed_profile_above_auto_learn_threshold"
            if best.confirmed_profile
            else "score_above_auto_merge_threshold"
        )
        store.record_speaker_match_decision(
            source_speaker_id=speaker_id,
            target_speaker_id=target_id,
            sample_id=sample_id,
            model=model_key,
            score=score,
            threshold=effective_auto_threshold,
            status="auto_merged",
            metadata=speaker_match_metadata(best, decision),
        )
        store.merge_speakers(speaker_id, target_id)
        if sample_id is not None:
            relocated = relocate_sample_after_merge(sample_path, target_id)
            if relocated is not None:
                store.update_speaker_sample_path(sample_id, str(relocated))
        confidence = refresh_identity_status(settings, store, target_id, model_key)
        return IdentityMatchResult(
            speaker_id=target_id,
            target_speaker_id=target_id,
            status="auto_merged",
            score=score,
            confidence=confidence,
        )

    status = "candidate" if score >= candidate_threshold else "below_threshold"
    if status == "candidate" and not source_sample_auto_merge_safe:
        decision = "manual_review_required_for_low_confidence_sample"
    elif status == "candidate" and protected_target:
        decision = "manual_review_required_for_protected_speaker"
    elif status == "candidate":
        decision = "manual_review_required"
    else:
        decision = "kept_separate"
    store.record_speaker_match_decision(
        source_speaker_id=speaker_id,
        target_speaker_id=target_id,
        sample_id=sample_id,
        model=model_key,
        score=score,
        threshold=candidate_threshold if status == "candidate" else auto_threshold,
        status=status,
        metadata=speaker_match_metadata(best, decision),
    )
    confidence = refresh_identity_status(settings, store, speaker_id, model_key)
    return IdentityMatchResult(
        speaker_id=speaker_id,
        target_speaker_id=target_id,
        status=status,
        score=score,
        confidence=confidence,
    )


def embedding_model_key(settings: Settings) -> str:
    backend = settings.speaker_recognition.get("embedding_backend", "speechbrain_ecapa")
    model = settings.speaker_recognition.get("embedding_model", "speechbrain/spkrec-ecapa-voxceleb")
    return f"{backend}:{model}"


def speaker_embedding(settings: Settings, path: Path) -> list[float]:
    backend = settings.speaker_recognition.get("embedding_backend", "speechbrain_ecapa")
    if backend == "speechbrain_ecapa":
        return speechbrain_ecapa_embedding(settings, path)
    raise RuntimeError(f"unsupported speaker embedding backend: {backend}")


def speechbrain_ecapa_embedding(settings: Settings, path: Path) -> list[float]:
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("torch is required for SpeechBrain speaker embeddings") from exc

    classifier = load_speechbrain_classifier(settings)
    sample_rate = int(settings.speaker_recognition.get("embedding_sample_rate", 16000))
    signal = load_audio_tensor(path, torch, sample_rate=sample_rate)

    with torch.no_grad():
        embedding = classifier.encode_batch(signal)
    vector = embedding.detach().cpu().numpy().reshape(-1).astype(float)
    return normalize_vector(vector).tolist()


def load_speechbrain_classifier(settings: Settings):
    global _SPEECHBRAIN_MODEL, _SPEECHBRAIN_SOURCE, _SPEECHBRAIN_SAVEDIR
    source = str(settings.speaker_recognition.get("embedding_model", "speechbrain/spkrec-ecapa-voxceleb"))
    savedir = str(settings.speaker_embedding_model_dir / source.replace("/", "__"))
    if _SPEECHBRAIN_MODEL is not None and _SPEECHBRAIN_SOURCE == source and _SPEECHBRAIN_SAVEDIR == savedir:
        return _SPEECHBRAIN_MODEL
    try:
        try:
            from speechbrain.inference.speaker import EncoderClassifier
        except ImportError:
            from speechbrain.pretrained import EncoderClassifier
    except ImportError as exc:
        raise RuntimeError("speechbrain is required for SpeechBrain speaker embeddings") from exc

    _SPEECHBRAIN_MODEL = EncoderClassifier.from_hparams(source=source, savedir=savedir)
    _SPEECHBRAIN_SOURCE = source
    _SPEECHBRAIN_SAVEDIR = savedir
    return _SPEECHBRAIN_MODEL


def load_audio_tensor(path: Path, torch_module, *, sample_rate: int):
    ffmpeg = find_executable("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to decode speaker sample audio")
    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_f32le",
            "-f",
            "f32le",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace").strip() or "ffmpeg audio decode failed")
    waveform = np.frombuffer(proc.stdout, dtype=np.float32).copy()
    if waveform.size == 0:
        raise RuntimeError("ffmpeg decoded empty audio")
    return torch_module.from_numpy(waveform).unsqueeze(0)


def relocate_sample_after_merge(sample_path: str, target_speaker_id: int) -> Path | None:
    source = Path(sample_path)
    if not source.exists():
        return None
    parent = source.parent
    if not parent.name.startswith("speaker-"):
        return None
    target_dir = parent.parent / f"speaker-{target_speaker_id:06d}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(target_dir / source.name)
    if target == source:
        return source
    shutil.move(str(source), str(target))
    return target


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(1, 1000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not find unique path for {path}")


def best_existing_speaker_match(
    settings: Settings | None,
    store: Store,
    *,
    model: str,
    speaker_id: int,
    vector: list[float],
) -> ExistingSpeakerMatch | None:
    target_rows = store.speaker_embedding_rows(model=model, exclude_speaker_id=speaker_id)
    if not target_rows:
        return None

    config = getattr(settings, "speaker_recognition", {}) if settings is not None else {}
    if not isinstance(config, dict):
        config = {}
    confirmed_profiles_enabled = bool_config(config.get("confirmed_profile_matching_enabled"), True)
    max_prototypes = speaker_profile_max_prototypes(config)
    confirmed_max_prototypes = int_config(
        config.get("confirmed_profile_max_prototypes"),
        max_prototypes,
        minimum=1,
        maximum=24,
    )
    outlier_min_similarity = speaker_profile_outlier_min_similarity(config)
    min_profile_samples = int_config(config.get("confirmed_profile_min_samples"), 2, minimum=1, maximum=24)
    min_profile_sample_confidence = float_config(config.get("confirmed_profile_min_sample_confidence"), 0.55)
    min_auto_sample_confidence = float_config(
        config.get("auto_merge_min_sample_confidence"),
        min_profile_sample_confidence,
    )
    target_eligibility_threshold = float_config(
        config.get("candidate_threshold", config.get("auto_merge_threshold")),
        0.68,
    )
    speaker_rows = {int(row["id"]): row for row in store.list_speakers()}
    source = np.array(vector, dtype=float)
    if source.size <= 0:
        return None

    entries_by_speaker: dict[int, list[tuple[list[float], dict[str, Any]]]] = {}
    for row in target_rows:
        parsed = parse_vector(row["vector"])
        if parsed is None:
            continue
        sample_metadata = json_dict(row["sample_metadata"] if "sample_metadata" in row.keys() else None)
        entries_by_speaker.setdefault(int(row["speaker_id"]), []).append((parsed, sample_metadata))

    best: ExistingSpeakerMatch | None = None
    for candidate_id, entries in entries_by_speaker.items():
        vectors = [vector for vector, _metadata in entries]
        arrays = matching_embedding_arrays(vectors, dimension=source.size)
        if not arrays:
            continue
        row = speaker_rows.get(candidate_id)
        confirmed = speaker_is_confirmed(row)
        if confirmed_profiles_enabled and confirmed and len(arrays) >= min_profile_samples:
            trusted_entries = trusted_confirmed_profile_entries(
                entries,
                dimension=source.size,
                min_confidence=min_profile_sample_confidence,
            )
            if len(trusted_entries) < min_profile_samples:
                continue
            profile = speaker_voice_profile_from_entries(
                trusted_entries,
                dimension=source.size,
                max_prototypes=confirmed_max_prototypes,
                outlier_min_similarity=outlier_min_similarity,
            )
            if profile is None:
                continue
            match = ExistingSpeakerMatch(
                speaker_id=candidate_id,
                score=speaker_voice_profile_score(source, profile),
                matcher="confirmed_profile",
                prototype_count=profile.prototype_count,
                confirmed_profile=True,
                trusted_profile=True,
                trusted_sample_count=profile.trusted_sample_count,
            )
        else:
            if not speaker_cluster_match_eligible(row, threshold=target_eligibility_threshold):
                continue
            profile_entries = [
                (vector, metadata)
                for vector, metadata in entries
                if sample_allows_profile_match(metadata, threshold=min_auto_sample_confidence)
            ]
            profile = speaker_voice_profile_from_entries(
                profile_entries,
                dimension=source.size,
                max_prototypes=max_prototypes,
                outlier_min_similarity=outlier_min_similarity,
            )
            if profile is None:
                continue
            match = ExistingSpeakerMatch(
                speaker_id=candidate_id,
                score=speaker_voice_profile_score(source, profile),
                matcher="speaker_profile",
                prototype_count=profile.prototype_count,
                confirmed_profile=confirmed,
                trusted_sample_count=profile.trusted_sample_count,
            )
        if best is None or speaker_match_rank(match) > speaker_match_rank(best):
            best = match
    return best


def speaker_match_metadata(match: ExistingSpeakerMatch, decision: str) -> dict[str, Any]:
    metadata = {
        "decision": decision,
        "matcher": match.matcher,
        "profile_prototype_count": match.prototype_count,
    }
    if match.confirmed_profile:
        metadata["confirmed_profile"] = True
    if match.trusted_profile:
        metadata["trusted_profile"] = True
        metadata["trusted_sample_count"] = match.trusted_sample_count
    return metadata


def speaker_match_rank(match: ExistingSpeakerMatch) -> tuple[float, int, int, int]:
    return (
        float(match.score),
        1 if match.confirmed_profile else 0,
        int(match.prototype_count),
        -int(match.speaker_id),
    )


def speaker_is_confirmed(row: Any) -> bool:
    if row is None:
        return False
    metadata = json_dict(row["metadata"] if "metadata" in row.keys() else None)
    return str(metadata.get("speaker_review_status") or "").strip() == "confirmed"


def speaker_match_requires_manual_review(row: Any) -> bool:
    if row is None:
        return False
    metadata = json_dict(row["metadata"] if "metadata" in row.keys() else None)
    review_status = str(metadata.get("speaker_review_status") or "").strip()
    identity_status = str(row["identity_status"] or "").strip()
    return review_status in {"confirmed", "auto_merged_pending_review", "needs_review"} or identity_status in {
        "named",
        "confirmed",
        "accepted",
    }


def speaker_match_auto_merge_allowed(
    match: ExistingSpeakerMatch,
    *,
    source_row: Any,
    target_row: Any,
    config: dict[str, Any],
    source_confidence_threshold: float,
) -> bool:
    if speaker_match_requires_manual_review(source_row):
        return False
    if not speaker_match_requires_manual_review(target_row):
        return True
    if not bool_config(config.get("confirmed_profile_auto_merge_enabled"), True):
        return False
    if not (match.confirmed_profile and match.trusted_profile):
        return False
    return source_speaker_safe_for_confirmed_profile_auto_merge(
        source_row,
        threshold=float_config(config.get("confirmed_profile_source_min_confidence"), source_confidence_threshold),
    )


def source_speaker_safe_for_confirmed_profile_auto_merge(row: Any, *, threshold: float) -> bool:
    if row is None:
        return True
    review_status = speaker_review_status(row)
    if review_status in {"confirmed", "auto_merged_pending_review", "needs_review", "low_similarity_hidden"}:
        return False
    sample_count = speaker_sample_count(row)
    if sample_count <= 1:
        return True
    confidence = speaker_confidence_value(row)
    return confidence is not None and confidence >= threshold


def source_sample_safe_for_auto_merge(row: Any, *, threshold: float) -> bool:
    if row is None:
        return True
    metadata = json_dict(row["metadata"] if "metadata" in row.keys() else None)
    confidence = sample_confidence_value(metadata)
    if confidence is None:
        return True
    return confidence >= threshold


def speaker_stats_row(store: Store, speaker_id: int) -> Any:
    for row in store.list_speakers():
        if int(row["id"]) == int(speaker_id):
            return row
    return store.get_speaker(speaker_id)


def speaker_cluster_match_eligible(row: Any, *, threshold: float) -> bool:
    if row is None:
        return False
    review_status = speaker_review_status(row)
    if review_status == "confirmed":
        return speaker_confirmed_profile_match_eligible(row, threshold=threshold)
    if review_status in {"auto_merged_pending_review", "low_similarity_hidden", "needs_review"}:
        return False
    identity_status = str(row["identity_status"] or "").strip()
    if identity_status in {"named", "confirmed", "accepted"}:
        return False

    sample_count = speaker_sample_count(row)
    confidence = speaker_confidence_value(row)
    if sample_count >= 2:
        if confidence is None:
            return False
        return confidence >= threshold
    return True


def speaker_confirmed_profile_match_eligible(row: Any, *, threshold: float) -> bool:
    sample_count = speaker_sample_count(row)
    if sample_count < 2:
        return False
    confidence = speaker_confidence_value(row)
    if confidence is None:
        return False
    return confidence >= threshold


def speaker_review_status(row: Any) -> str:
    metadata = json_dict(row["metadata"] if "metadata" in row.keys() else None)
    return str(metadata.get("speaker_review_status") or "").strip()


def speaker_sample_count(row: Any) -> int:
    if "sample_count" not in row.keys():
        return 0
    try:
        return max(0, int(row["sample_count"] or 0))
    except (TypeError, ValueError):
        return 0


def speaker_confidence_value(row: Any) -> float | None:
    if "confidence" not in row.keys():
        return None
    try:
        value = float(row["confidence"])
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def float_config(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def matching_embedding_arrays(vectors: list[list[float]], *, dimension: int) -> list[np.ndarray]:
    arrays: list[np.ndarray] = []
    for vector in vectors:
        if len(vector) != dimension:
            continue
        array = normalize_vector(np.array(vector, dtype=float))
        if array.size == dimension:
            arrays.append(array)
    return arrays


def speaker_profile_max_prototypes(config: dict[str, Any] | None) -> int:
    if not isinstance(config, dict):
        config = {}
    fallback = int_config(config.get("confirmed_profile_max_prototypes"), 6, minimum=1, maximum=24)
    return int_config(config.get("speaker_profile_max_prototypes"), fallback, minimum=1, maximum=24)


def speaker_profile_outlier_min_similarity(config: dict[str, Any] | None) -> float:
    if not isinstance(config, dict):
        config = {}
    return float_config(config.get("speaker_profile_outlier_min_similarity"), 0.55)


def confirmed_profile_score(
    source: np.ndarray,
    vectors: list[np.ndarray],
    *,
    max_prototypes: int,
) -> tuple[float, int]:
    profile = speaker_voice_profile_from_arrays(vectors, max_prototypes=max_prototypes)
    if profile is None:
        return -1.0, 0
    return speaker_voice_profile_score(source, profile), profile.prototype_count


def trusted_confirmed_profile_entries(
    entries: list[tuple[list[float], dict[str, Any]]],
    *,
    dimension: int,
    min_confidence: float,
) -> list[tuple[list[float], dict[str, Any]]]:
    trusted_entries: list[tuple[list[float], dict[str, Any]]] = []
    fallback_entries: list[tuple[list[float], dict[str, Any]]] = []
    for vector, metadata in entries:
        if len(vector) != dimension:
            continue
        sample_confidence = sample_confidence_value(metadata)
        if sample_confidence is None or sample_confidence < min_confidence:
            continue
        if metadata.get("representative_sample") is True:
            trusted_entries.append((vector, metadata))
        else:
            fallback_entries.append((vector, metadata))
    return trusted_entries or fallback_entries


def sample_confidence_value(metadata: dict[str, Any]) -> float | None:
    try:
        value = float(metadata.get("sample_confidence"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def sample_allows_profile_match(metadata: dict[str, Any], *, threshold: float) -> bool:
    confidence = sample_confidence_value(metadata)
    if confidence is None:
        return True
    return confidence >= threshold


def sample_allows_centroid_match(metadata: dict[str, Any], *, threshold: float) -> bool:
    return sample_allows_profile_match(metadata, threshold=threshold)


def confirmed_profile_prototypes(vectors: list[np.ndarray], *, max_prototypes: int) -> list[np.ndarray]:
    profile = speaker_voice_profile_from_arrays(vectors, max_prototypes=max_prototypes)
    if profile is None:
        return []
    return [prototype.vector for prototype in profile.prototypes]


def speaker_voice_profile_from_vectors(
    vectors: list[list[float]],
    *,
    max_prototypes: int = 6,
    outlier_min_similarity: float = 0.55,
) -> SpeakerVoiceProfile | None:
    if not vectors:
        return None
    dimension = len(vectors[0])
    entries = [(vector, {}) for vector in vectors if len(vector) == dimension]
    return speaker_voice_profile_from_entries(
        entries,
        dimension=dimension,
        max_prototypes=max_prototypes,
        outlier_min_similarity=outlier_min_similarity,
    )


def speaker_voice_profile_from_arrays(
    vectors: list[np.ndarray],
    *,
    max_prototypes: int = 6,
    outlier_min_similarity: float = 0.55,
) -> SpeakerVoiceProfile | None:
    if not vectors:
        return None
    dimension = int(vectors[0].size)
    entries = [(vector.astype(float).tolist(), {}) for vector in vectors if int(vector.size) == dimension]
    return speaker_voice_profile_from_entries(
        entries,
        dimension=dimension,
        max_prototypes=max_prototypes,
        outlier_min_similarity=outlier_min_similarity,
    )


def speaker_voice_profile_from_entries(
    entries: list[tuple[list[float], dict[str, Any]]],
    *,
    dimension: int,
    max_prototypes: int = 6,
    outlier_min_similarity: float = 0.55,
) -> SpeakerVoiceProfile | None:
    normalized_entries: list[tuple[np.ndarray, dict[str, Any]]] = []
    for vector, metadata in entries:
        if len(vector) != dimension:
            continue
        array = normalize_vector(np.array(vector, dtype=float))
        if array.size != dimension:
            continue
        normalized_entries.append((array, metadata))
    if not normalized_entries:
        return None

    arrays = [array for array, _metadata in normalized_entries]
    metadata_rows = [metadata for _array, metadata in normalized_entries]
    centralities = speaker_profile_centralities(arrays)
    keep_indices = speaker_profile_keep_indices(
        centralities,
        metadata_rows,
        outlier_min_similarity=outlier_min_similarity,
    )
    if not keep_indices:
        keep_indices = [max(range(len(arrays)), key=lambda index: centralities[index])]
    outlier_count = max(0, len(arrays) - len(keep_indices))
    weights = [
        speaker_profile_sample_weight(metadata_rows[index], centrality=centralities[index])
        for index in keep_indices
    ]
    kept_arrays = [arrays[index] for index in keep_indices]
    centroid = weighted_normalized_vector(kept_arrays, weights)
    if centroid.size != dimension:
        return None

    prototypes: list[SpeakerVoicePrototype] = [
        SpeakerVoicePrototype(
            vector=centroid,
            kind="robust_weighted_centroid",
            support=len(kept_arrays),
            weight=sum(weights),
        )
    ]
    if max_prototypes <= 1:
        return SpeakerVoiceProfile(
            prototypes=prototypes[:max_prototypes],
            sample_count=len(arrays),
            trusted_sample_count=len(keep_indices),
            outlier_count=outlier_count,
        )

    selected_indices: list[int] = []
    first_index = max(
        keep_indices,
        key=lambda index: (
            cosine_similarity(arrays[index], centroid),
            speaker_profile_sample_weight(metadata_rows[index], centrality=centralities[index]),
            -index,
        ),
    )
    selected_indices.append(first_index)
    prototypes.append(
        SpeakerVoicePrototype(
            vector=arrays[first_index],
            kind="central_medoid",
            support=speaker_profile_support(
                arrays[first_index],
                kept_arrays,
                outlier_min_similarity=outlier_min_similarity,
            ),
            weight=speaker_profile_sample_weight(metadata_rows[first_index], centrality=centralities[first_index]),
        )
    )

    while len(prototypes) < max_prototypes and len(selected_indices) < len(keep_indices):
        remaining = [index for index in keep_indices if index not in selected_indices]
        next_index = max(
            remaining,
            key=lambda index: speaker_profile_diversity_rank(
                arrays[index],
                [arrays[selected] for selected in selected_indices],
                metadata_rows[index],
                centrality=centralities[index],
            ),
        )
        if max(cosine_similarity(arrays[next_index], prototype.vector) for prototype in prototypes) >= 0.995:
            selected_indices.append(next_index)
            continue
        selected_indices.append(next_index)
        prototypes.append(
            SpeakerVoicePrototype(
                vector=arrays[next_index],
                kind="diverse_medoid",
                support=speaker_profile_support(
                    arrays[next_index],
                    kept_arrays,
                    outlier_min_similarity=outlier_min_similarity,
                ),
                weight=speaker_profile_sample_weight(metadata_rows[next_index], centrality=centralities[next_index]),
            )
        )
    return SpeakerVoiceProfile(
        prototypes=prototypes[:max_prototypes],
        sample_count=len(arrays),
        trusted_sample_count=len(keep_indices),
        outlier_count=outlier_count,
    )


def speaker_profile_centralities(arrays: list[np.ndarray]) -> list[float]:
    if len(arrays) <= 1:
        return [1.0 for _array in arrays]
    centralities: list[float] = []
    support_count = 1 if len(arrays) <= 3 else 2
    for index, vector in enumerate(arrays):
        scores = [
            cosine_similarity(vector, other)
            for other_index, other in enumerate(arrays)
            if other_index != index
        ]
        scores.sort(reverse=True)
        centralities.append(float(sum(scores[:support_count]) / max(1, min(support_count, len(scores)))))
    return centralities


def speaker_profile_keep_indices(
    centralities: list[float],
    metadata_rows: list[dict[str, Any]],
    *,
    outlier_min_similarity: float,
) -> list[int]:
    if len(centralities) <= 2:
        return list(range(len(centralities)))
    keep: list[int] = []
    for index, centrality in enumerate(centralities):
        metadata = metadata_rows[index]
        confidence = sample_confidence_value(metadata)
        representative = metadata.get("representative_sample") is True
        if centrality >= outlier_min_similarity:
            keep.append(index)
        elif representative and confidence is not None and confidence >= outlier_min_similarity:
            keep.append(index)
    return keep


def speaker_profile_sample_weight(metadata: dict[str, Any], *, centrality: float) -> float:
    confidence = sample_confidence_value(metadata)
    weight = 1.0 if confidence is None else max(0.05, min(1.0, confidence))
    if metadata.get("representative_sample") is True:
        weight += 0.35
    if metadata.get("status") == "ok":
        weight += 0.1
    role = str(metadata.get("sample_role") or "")
    if role in {"manual_detached_sample", "overlap_separated_candidate"}:
        weight *= 0.8
    return max(0.01, weight * max(0.05, centrality))


def speaker_profile_diversity_rank(
    vector: np.ndarray,
    selected_vectors: list[np.ndarray],
    metadata: dict[str, Any],
    *,
    centrality: float,
) -> tuple[float, float, float]:
    if not selected_vectors:
        diversity = 1.0
    else:
        diversity = 1.0 - max(cosine_similarity(vector, selected) for selected in selected_vectors)
    quality = speaker_profile_sample_weight(metadata, centrality=centrality)
    return (diversity * quality, quality, centrality)


def speaker_profile_support(
    vector: np.ndarray,
    arrays: list[np.ndarray],
    *,
    outlier_min_similarity: float,
) -> int:
    return sum(1 for other in arrays if cosine_similarity(vector, other) >= outlier_min_similarity)


def weighted_normalized_vector(arrays: list[np.ndarray], weights: list[float]) -> np.ndarray:
    if not arrays:
        return np.array([], dtype=float)
    matrix = np.vstack(arrays)
    weight_array = np.array(weights, dtype=float)
    if weight_array.size != len(arrays) or float(np.sum(weight_array)) <= 0:
        weight_array = np.ones(len(arrays), dtype=float)
    return normalize_vector(np.average(matrix, axis=0, weights=weight_array))


def speaker_voice_profile_score(source: np.ndarray | list[float], profile: SpeakerVoiceProfile) -> float:
    source_array = normalize_vector(np.array(source, dtype=float))
    if source_array.size <= 0 or not profile.prototypes:
        return -1.0
    return float(max(cosine_similarity(source_array, prototype.vector) for prototype in profile.prototypes))


def speaker_voice_profile_core_score(source: np.ndarray | list[float], profile: SpeakerVoiceProfile) -> float:
    source_array = normalize_vector(np.array(source, dtype=float))
    if source_array.size <= 0 or not profile.prototypes:
        return -1.0
    return float(cosine_similarity(source_array, profile.prototypes[0].vector))


def speaker_voice_profiles_similarity(left: SpeakerVoiceProfile, right: SpeakerVoiceProfile) -> float:
    if not left.prototypes or not right.prototypes:
        return -1.0
    return float(
        max(
            cosine_similarity(left_prototype.vector, right_prototype.vector)
            for left_prototype in left.prototypes
            for right_prototype in right.prototypes
        )
    )


def bool_config(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if value is None:
        return default
    return bool(value)


def int_config(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def refresh_identity_status(
    settings: Settings,
    store: Store,
    speaker_id: int,
    model: str,
    *,
    touch_updated_at: bool = True,
) -> float | None:
    rows = store.speaker_embedding_rows(model=model, speaker_id=speaker_id)
    vectors = [parse_vector(row["vector"]) for row in rows]
    vectors = [vector for vector in vectors if vector is not None]
    if not vectors:
        store.update_speaker_identity_status(
            speaker_id,
            status="provisional",
            confidence=None,
            touch_updated_at=touch_updated_at,
        )
        return None

    confidence = speaker_cluster_confidence(vectors)
    stats = store.speaker_sample_evidence_stats(speaker_id)
    sample_count = int(stats["sample_count"] or 0)
    observation_count = int(stats["observation_count"] or 0)
    day_count = int(stats["day_count"] or 0)
    min_samples = int(settings.speaker_recognition.get("review_min_samples", 3))
    min_observations = int(settings.speaker_recognition.get("review_min_observations", 1))
    min_days = int(settings.speaker_recognition.get("review_min_days", 1))
    min_confidence = float(settings.speaker_recognition.get("review_min_confidence", 0.86))
    ready = (
        sample_count >= min_samples
        and observation_count >= min_observations
        and day_count >= min_days
        and confidence >= min_confidence
    )
    status = "ready_to_name" if ready else "provisional"
    store.update_speaker_identity_status(
        speaker_id,
        status=status,
        confidence=confidence,
        touch_updated_at=touch_updated_at,
    )
    return confidence


def speaker_cluster_confidence(vectors: list[list[float]]) -> float:
    if len(vectors) == 1:
        return 1.0
    scores: list[float] = []
    for i, left in enumerate(vectors):
        for right in vectors[i + 1 :]:
            scores.append(cosine_similarity(np.array(left, dtype=float), np.array(right, dtype=float)))
    if not scores:
        return 1.0
    # Penalize clusters whose weakest evidence is poor, but keep the average signal visible.
    return float((min(scores) * 0.55) + (sum(scores) / len(scores) * 0.45))


def parse_vector(value: Any) -> list[float] | None:
    if not isinstance(value, str):
        return None
    try:
        raw = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, list):
        return None
    try:
        return [float(item) for item in raw]
    except (TypeError, ValueError):
        return None


def normalize_vector(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if not math.isfinite(norm) or norm <= 0:
        return vector.astype(float)
    return (vector / norm).astype(float)


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    left_norm = normalize_vector(left)
    right_norm = normalize_vector(right)
    return float(np.dot(left_norm, right_norm))
