from __future__ import annotations

from typing import Any

from .dashboard_shared import scalar
from .speaker_identity import embedding_model_key
from .speakers import speaker_confidence_summary, speaker_review_status, speaker_sample_payload
from .store import Store, json_dict, speaker_display_name_is_auto
from .timeutil import now


CONFIDENCE_THRESHOLD = 0.68


def speaker_training_payload(settings: Any, params: dict[str, str] | None = None) -> dict[str, Any]:
    store = Store(settings.db_path)
    try:
        speakers = list(store.list_speakers())
        samples = list(store.list_speaker_samples(None))
        model = embedding_model_key(settings)
        embedding_count = count_embeddings(store, model=model)
        sample_items = [training_sample_item(store, sample, model=model) for sample in samples]
        speaker_items = [training_speaker_item(store, speaker, model=model) for speaker in speakers]
        stages = training_stages(speaker_items, sample_items)
        summary = training_summary(speaker_items, sample_items, embedding_count=embedding_count, stages=stages)
        return {
            "ok": True,
            "generated_at": now(settings.timezone).isoformat(timespec="seconds"),
            "model": {
                "embedding_model": model,
                "threshold": CONFIDENCE_THRESHOLD,
                "auto_merge_threshold": float(settings.speaker_recognition.get("auto_merge_threshold", CONFIDENCE_THRESHOLD)),
                "candidate_threshold": float(settings.speaker_recognition.get("candidate_threshold", CONFIDENCE_THRESHOLD)),
                "review_min_samples": int(settings.speaker_recognition.get("review_min_samples", 5)),
                "review_min_observations": int(settings.speaker_recognition.get("review_min_observations", 3)),
                "review_min_days": int(settings.speaker_recognition.get("review_min_days", 2)),
            },
            "summary": summary,
            "stages": stages,
            "speakers": speaker_items,
            "sample_queue": sorted(sample_items, key=sample_queue_sort_key)[:120],
            "recent_matches": recent_training_matches(store),
        }
    finally:
        store.close()


def training_summary(
    speakers: list[dict[str, Any]],
    samples: list[dict[str, Any]],
    *,
    embedding_count: int,
    stages: list[dict[str, Any]],
) -> dict[str, Any]:
    total = len(speakers)
    stable = sum(1 for row in speakers if row["training_state"] in {"confirmed", "stable"})
    needs_work = sum(1 for row in speakers if row["training_state"] not in {"confirmed", "stable", "empty"})
    missing_embeddings = sum(1 for row in samples if "missing_embedding" in row["issues"])
    low_confidence = sum(1 for row in samples if "low_confidence" in row["issues"])
    representative = sum(1 for row in samples if row["representative"])
    blocked = sum(1 for stage in stages if stage["status"] == "blocked")
    ready = sum(1 for stage in stages if stage["status"] == "ready")
    stage_score = 100 - blocked * 18 - ready * 8
    coverage = int((stable / total) * 100) if total else 0
    sample_health = 100
    if samples:
        sample_health -= int((missing_embeddings / len(samples)) * 35)
        sample_health -= int((low_confidence / len(samples)) * 25)
        sample_health -= 0 if representative else 10
    score = max(0, min(100, round((coverage + stage_score + sample_health) / 3)))
    return {
        "speakers": total,
        "stable_speakers": stable,
        "needs_work_speakers": needs_work,
        "samples": len(samples),
        "embeddings": embedding_count,
        "missing_embeddings": missing_embeddings,
        "low_confidence_samples": low_confidence,
        "representative_samples": representative,
        "training_score": score,
        "blocked_stages": blocked,
        "ready_stages": ready,
    }


def training_stages(speakers: list[dict[str, Any]], samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    speaker_count = len(speakers)
    sample_count = len(samples)
    playable = sum(1 for row in samples if row["has_audio"])
    missing_embeddings = [row for row in samples if "missing_embedding" in row["issues"]]
    stale_confidence = [row for row in samples if "missing_confidence" in row["issues"]]
    low_confidence = [row for row in samples if "low_confidence" in row["issues"]]
    missing_representatives = [row for row in speakers if "missing_representative" in row["issues"]]
    review_needed = [row for row in speakers if row["training_state"] in {"review_needed", "pending_auto"}]
    hidden = [row for row in speakers if row["training_state"] == "hidden"]
    stable = [row for row in speakers if row["training_state"] in {"stable", "confirmed"}]
    return [
        stage(
            "sample_bank",
            "样本库",
            "blocked" if speaker_count and sample_count == 0 else "ready" if sample_count < max(2, speaker_count) else "ok",
            f"{sample_count} samples / {playable} playable",
            {"name": "analyze_audio", "args": {"date": "today", "limit": 20}, "label": "分析音频"},
        ),
        stage(
            "embedding",
            "Embedding",
            "blocked" if missing_embeddings else "ok",
            f"{len(missing_embeddings)} missing",
            {"name": "speaker_repair_embeddings", "args": {"apply": True}, "label": "补 embedding"},
        ),
        stage(
            "confidence",
            "一致性",
            "ready" if stale_confidence or low_confidence else "ok",
            f"{len(stale_confidence)} unscored / {len(low_confidence)} low",
            {"name": "speaker_refresh_sample_confidence", "args": {}, "label": "重算一致性"},
        ),
        stage(
            "representatives",
            "代表样本",
            "ready" if missing_representatives else "ok",
            f"{len(missing_representatives)} speakers missing anchors",
            {"name": "speaker_refresh_representatives", "args": {"per_speaker": 3}, "label": "刷新代表样本"},
        ),
        stage(
            "organize",
            "自动整理",
            "ready" if hidden or review_needed else "ok",
            f"{len(review_needed)} review / {len(hidden)} hidden",
            {"name": "speaker_auto_organize", "args": {"threshold": CONFIDENCE_THRESHOLD}, "label": "自动整理后复查"},
        ),
        stage(
            "review",
            "人工确认",
            "ready" if review_needed else "ok" if stable else "blocked",
            f"{len(stable)} stable / {len(review_needed)} needs review",
            None,
        ),
    ]


def stage(key: str, label: str, status: str, detail: str, action: dict[str, Any] | None) -> dict[str, Any]:
    return {"key": key, "label": label, "status": status, "detail": detail, "action": action}


def training_speaker_item(store: Store, row: Any, *, model: str) -> dict[str, Any]:
    speaker_id = int(row["id"])
    stats = store.speaker_sample_evidence_stats(speaker_id)
    sample_count = int(stats["sample_count"] or 0)
    embedding_count = int(scalar(store.conn, "SELECT count(*) FROM speaker_embeddings WHERE speaker_id = ?", (speaker_id,)) or 0)
    samples = store.list_speaker_samples(speaker_id)
    review_status = speaker_review_status(row)
    confidence = safe_float(row["confidence"])
    issues: list[str] = []
    if sample_count <= 0:
        issues.append("no_samples")
    if sample_count == 1:
        issues.append("single_sample")
    if embedding_count < sample_count:
        issues.append("missing_embedding")
    if confidence is None:
        issues.append("missing_confidence")
    elif confidence < CONFIDENCE_THRESHOLD and review_status != "confirmed":
        issues.append("low_confidence")
    if not any(sample_metadata(sample).get("representative_sample") for sample in samples) and sample_count:
        issues.append("missing_representative")
    if speaker_display_name_is_auto(row["display_name"]) and review_status != "confirmed":
        issues.append("auto_name")
    state = speaker_training_state(row, sample_count=sample_count, embedding_count=embedding_count, confidence=confidence, issues=issues)
    confidence_summary = speaker_confidence_summary(row, sample_count=sample_count, embedding_count=embedding_count)
    return {
        "id": speaker_id,
        "display_name": row["display_name"],
        "identity_status": row["identity_status"],
        "review_status": review_status,
        "training_state": state,
        "confidence": confidence,
        "confidence_summary": confidence_summary,
        "sample_count": sample_count,
        "embedding_count": embedding_count,
        "day_count": int(stats["day_count"] or 0),
        "observation_count": int(stats["observation_count"] or 0),
        "latest_seen_at": stats["latest_seen_at"],
        "latest_sample_at": row["latest_sample_at"],
        "issues": issues,
        "recommended_action": speaker_recommended_action(state, speaker_id),
    }


def speaker_training_state(
    row: Any,
    *,
    sample_count: int,
    embedding_count: int,
    confidence: float | None,
    issues: list[str],
) -> str:
    review_status = speaker_review_status(row)
    identity_status = str(row["identity_status"] or "")
    if review_status == "confirmed" or identity_status in {"named", "confirmed", "accepted"}:
        return "confirmed"
    if review_status == "low_similarity_hidden" or "speaker_hidden" in json_dict(row["metadata"]):
        metadata = json_dict(row["metadata"])
        if metadata.get("speaker_hidden") is True or review_status == "low_similarity_hidden":
            return "hidden"
    if review_status in {"auto_merged_pending_review", "needs_review"} or identity_status == "auto_merged_pending_review":
        return "pending_auto" if review_status == "auto_merged_pending_review" or identity_status == "auto_merged_pending_review" else "review_needed"
    if sample_count <= 0:
        return "empty"
    if embedding_count < sample_count:
        return "missing_embedding"
    if confidence is None:
        return "needs_scoring"
    if confidence < CONFIDENCE_THRESHOLD:
        return "low_confidence"
    if any(issue in issues for issue in ("single_sample", "missing_representative", "auto_name")):
        return "review_needed"
    return "stable"


def speaker_recommended_action(state: str, speaker_id: int) -> dict[str, Any] | None:
    if state == "missing_embedding":
        return {"name": "speaker_repair_embeddings", "args": {"apply": True}, "label": "补 embedding"}
    if state in {"needs_scoring", "low_confidence"}:
        return {"name": "speaker_refresh_sample_confidence", "args": {"speaker_ids": [speaker_id]}, "label": "重算一致性"}
    if state in {"review_needed", "pending_auto"}:
        return {"name": "speaker_confirm", "args": {"speaker_ids": [speaker_id]}, "label": "确认"}
    if state == "hidden":
        return {"name": "speaker_unhide", "args": {"speaker_ids": [speaker_id]}, "label": "放回复查"}
    return None


def training_sample_item(store: Store, row: Any, *, model: str) -> dict[str, Any]:
    metadata = sample_metadata(row)
    confidence = safe_float(metadata.get("sample_confidence"))
    sample_id = int(row["id"])
    speaker_id = int(row["speaker_id"])
    has_embedding = bool(
        scalar(
            store.conn,
            "SELECT 1 FROM speaker_embeddings WHERE sample_id = ? AND model = ? LIMIT 1",
            (sample_id, model),
        )
    )
    issues: list[str] = []
    if not row["sample_path"]:
        issues.append("no_audio")
    if not has_embedding:
        issues.append("missing_embedding")
    if confidence is None:
        issues.append("missing_confidence")
    elif confidence < CONFIDENCE_THRESHOLD:
        issues.append("low_confidence")
    if metadata.get("status") not in {None, "ok", "overlap_separated_candidate"}:
        issues.append(str(metadata.get("status")))
    payload = speaker_sample_payload(row)
    payload.update(
        {
            "speaker_id": speaker_id,
            "speaker_name": row["speaker_name"],
            "sample_confidence": confidence,
            "has_embedding": has_embedding,
            "has_audio": bool(row["sample_path"]),
            "representative": metadata.get("representative_sample") is True,
            "issues": issues,
            "recommended_action": sample_recommended_action(issues, speaker_id, sample_id),
        }
    )
    return payload


def sample_recommended_action(issues: list[str], speaker_id: int, sample_id: int) -> dict[str, Any] | None:
    if "missing_embedding" in issues:
        return {"name": "speaker_repair_embeddings", "args": {"apply": True}, "label": "补 embedding"}
    if "low_confidence" in issues or "missing_confidence" in issues:
        return {"name": "speaker_refresh_sample_confidence", "args": {"speaker_ids": [speaker_id]}, "label": "重算相关说话人"}
    if "no_audio" in issues:
        return {"name": "speaker_repair_sample_clips", "args": {"sample_ids": [sample_id], "apply": True}, "label": "重裁样本"}
    return None


def sample_queue_sort_key(row: dict[str, Any]) -> tuple[int, str, int]:
    priority = 0
    if "missing_embedding" in row["issues"]:
        priority -= 30
    if "low_confidence" in row["issues"]:
        priority -= 20
    if "no_audio" in row["issues"]:
        priority -= 10
    if row["representative"]:
        priority += 5
    return (priority, str(row.get("created_at") or ""), -int(row.get("id") or 0))


def recent_training_matches(store: Store) -> list[dict[str, Any]]:
    rows = []
    for row in store.list_speaker_match_decisions(40):
        rows.append(
            {
                "id": row["id"],
                "source_speaker_id": row["source_speaker_id"],
                "target_speaker_id": row["target_speaker_id"],
                "source_name": row["source_name"],
                "target_name": row["target_name"],
                "score": row["score"],
                "threshold": row["threshold"],
                "status": row["status"],
                "created_at": row["created_at"],
            }
        )
    return rows


def count_embeddings(store: Store, *, model: str) -> int:
    return int(scalar(store.conn, "SELECT count(*) FROM speaker_embeddings WHERE model = ?", (model,)) or 0)


def sample_metadata(row: Any) -> dict[str, Any]:
    return json_dict(row["metadata"])


def safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
