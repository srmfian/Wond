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

    auto_threshold = float(settings.speaker_recognition.get("auto_merge_threshold", 0.68))
    candidate_threshold = float(settings.speaker_recognition.get("candidate_threshold", 0.68))
    best = best_existing_speaker_match(settings, store, model=model_key, speaker_id=speaker_id, vector=vector)
    if best is None:
        confidence = refresh_identity_status(settings, store, speaker_id, model_key)
        return IdentityMatchResult(speaker_id=speaker_id, status="new_identity", confidence=confidence)

    target_id = best.speaker_id
    score = best.score
    if score >= auto_threshold:
        store.record_speaker_match_decision(
            source_speaker_id=speaker_id,
            target_speaker_id=target_id,
            sample_id=sample_id,
            model=model_key,
            score=score,
            threshold=auto_threshold,
            status="auto_merged",
            metadata=speaker_match_metadata(best, "score_above_auto_merge_threshold"),
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
    store.record_speaker_match_decision(
        source_speaker_id=speaker_id,
        target_speaker_id=target_id,
        sample_id=sample_id,
        model=model_key,
        score=score,
        threshold=candidate_threshold if status == "candidate" else auto_threshold,
        status=status,
        metadata=speaker_match_metadata(best, "manual_review_required" if status == "candidate" else "kept_separate"),
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
    max_prototypes = int_config(config.get("confirmed_profile_max_prototypes"), 6, minimum=1, maximum=24)
    min_profile_samples = int_config(config.get("confirmed_profile_min_samples"), 2, minimum=1, maximum=24)
    target_eligibility_threshold = float_config(
        config.get("candidate_threshold", config.get("auto_merge_threshold")),
        0.68,
    )
    speaker_rows = {int(row["id"]): row for row in store.list_speakers()}
    source = np.array(vector, dtype=float)
    if source.size <= 0:
        return None

    centroids: dict[int, list[list[float]]] = {}
    for row in target_rows:
        parsed = parse_vector(row["vector"])
        if parsed is None:
            continue
        centroids.setdefault(int(row["speaker_id"]), []).append(parsed)

    best: ExistingSpeakerMatch | None = None
    for candidate_id, vectors in centroids.items():
        arrays = matching_embedding_arrays(vectors, dimension=source.size)
        if not arrays:
            continue
        row = speaker_rows.get(candidate_id)
        if not speaker_cluster_match_eligible(row, threshold=target_eligibility_threshold):
            continue
        confirmed = speaker_is_confirmed(row)
        if confirmed_profiles_enabled and confirmed and len(arrays) >= min_profile_samples:
            score, prototype_count = confirmed_profile_score(source, arrays, max_prototypes=max_prototypes)
            match = ExistingSpeakerMatch(
                speaker_id=candidate_id,
                score=score,
                matcher="confirmed_profile",
                prototype_count=prototype_count,
                confirmed_profile=True,
            )
        else:
            centroid = normalize_vector(np.mean(np.vstack(arrays), axis=0))
            match = ExistingSpeakerMatch(
                speaker_id=candidate_id,
                score=cosine_similarity(source, centroid),
                matcher="centroid",
                prototype_count=1,
                confirmed_profile=confirmed,
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


def speaker_cluster_match_eligible(row: Any, *, threshold: float) -> bool:
    if row is None:
        return False
    review_status = speaker_review_status(row)
    if review_status == "confirmed":
        return True
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


def confirmed_profile_score(
    source: np.ndarray,
    vectors: list[np.ndarray],
    *,
    max_prototypes: int,
) -> tuple[float, int]:
    prototypes = confirmed_profile_prototypes(vectors, max_prototypes=max_prototypes)
    if not prototypes:
        return -1.0, 0
    scores = [cosine_similarity(source, prototype) for prototype in prototypes]
    return float(max(scores)), len(prototypes)


def confirmed_profile_prototypes(vectors: list[np.ndarray], *, max_prototypes: int) -> list[np.ndarray]:
    if not vectors:
        return []
    matrix = np.vstack(vectors)
    centroid = normalize_vector(np.mean(matrix, axis=0))
    prototypes: list[np.ndarray] = [centroid]
    if max_prototypes <= 1:
        return prototypes

    selected: list[int] = []
    first_index = max(range(len(vectors)), key=lambda index: cosine_similarity(vectors[index], centroid))
    selected.append(first_index)
    prototypes.append(vectors[first_index])

    while len(prototypes) < max_prototypes and len(selected) < len(vectors):
        remaining = [index for index in range(len(vectors)) if index not in selected]
        next_index = min(
            remaining,
            key=lambda index: max(cosine_similarity(vectors[index], vectors[chosen]) for chosen in selected),
        )
        selected.append(next_index)
        prototypes.append(vectors[next_index])
    return prototypes


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
