from __future__ import annotations

import argparse
import json
import math
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
import torch
import torchaudio.compliance.kaldi as kaldi

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wond.config import load_settings
from wond.speaker_identity import embedding_model_key, parse_vector
from wond.store import Store, json_dict


DEFAULT_MODEL_NAME = "Wespeaker/wespeaker-voxceleb-resnet34-LM"
MODEL_PATH = Path("data/models/wespeaker/wespeaker-voxceleb-resnet34-LM/voxceleb_resnet34_LM.onnx")


@dataclass
class SampleEmbedding:
    sample_id: int
    speaker_id: int
    speaker_name: str
    sample_path: str
    vector: np.ndarray


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a WeSpeaker ONNX model on confirmed speaker samples.")
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--result-key", default="wespeaker_resnet34")
    parser.add_argument("--model", type=Path, default=MODEL_PATH)
    parser.add_argument("--limit-per-speaker", type=int, default=0)
    parser.add_argument("--output", type=Path, default=Path("data/reports/wespeaker_resnet34_eval.json"))
    args = parser.parse_args()

    settings = load_settings()
    store = Store(settings.db_path)
    try:
        samples = confirmed_samples(store, limit_per_speaker=args.limit_per_speaker)
        if not samples:
            raise SystemExit("No confirmed speaker samples with files found.")

        session = ort.InferenceSession(str(args.model), providers=["CPUExecutionProvider"])
        start = time.perf_counter()
        embeddings = []
        failed: list[dict[str, Any]] = []
        for sample in samples:
            try:
                vector = wespeaker_embedding(session, Path(sample["sample_path"]))
            except Exception as exc:
                failed.append(
                    {
                        "sample_id": int(sample["sample_id"]),
                        "speaker_id": int(sample["speaker_id"]),
                        "speaker_name": sample["speaker_name"],
                        "error": str(exc)[:500],
                    }
                )
                continue
            embeddings.append(
                SampleEmbedding(
                    sample_id=int(sample["sample_id"]),
                    speaker_id=int(sample["speaker_id"]),
                    speaker_name=str(sample["speaker_name"]),
                    sample_path=str(sample["sample_path"]),
                    vector=vector,
                )
            )
        elapsed = time.perf_counter() - start

        wespeaker_eval = leave_one_out_eval(embeddings)
        current_eval = current_speechbrain_eval(store, embeddings)
        report = {
            "model": args.model_name,
            "model_path": str(args.model),
            "sample_count": len(samples),
            "embedded_count": len(embeddings),
            "failed_count": len(failed),
            "seconds": round(elapsed, 3),
            "seconds_per_sample": round(elapsed / len(embeddings), 3) if embeddings else None,
            args.result_key: wespeaker_eval,
            "current_speechbrain_ecapa": current_eval,
            "failed": failed[:20],
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    finally:
        store.close()


def confirmed_samples(store: Store, *, limit_per_speaker: int = 0) -> list[sqlite3.Row]:
    rows = store.conn.execute(
        """
        SELECT
            speaker_samples.id AS sample_id,
            speaker_samples.speaker_id AS speaker_id,
            speaker_samples.sample_path AS sample_path,
            speakers.display_name AS speaker_name,
            speakers.metadata AS speaker_metadata
        FROM speaker_samples
        JOIN speakers ON speakers.id = speaker_samples.speaker_id
        WHERE speaker_samples.sample_path IS NOT NULL
        ORDER BY speaker_samples.speaker_id ASC, speaker_samples.id ASC
        """
    ).fetchall()
    grouped: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        if json_dict(row["speaker_metadata"]).get("speaker_review_status") != "confirmed":
            continue
        path = Path(str(row["sample_path"]))
        if not path.exists():
            continue
        grouped.setdefault(int(row["speaker_id"]), []).append(row)

    selected: list[sqlite3.Row] = []
    for speaker_id in sorted(grouped):
        rows_for_speaker = grouped[speaker_id]
        if limit_per_speaker > 0:
            rows_for_speaker = rows_for_speaker[:limit_per_speaker]
        selected.extend(rows_for_speaker)
    return selected


def wespeaker_embedding(session: ort.InferenceSession, path: Path) -> np.ndarray:
    waveform = decode_audio(path, sample_rate=16000)
    feats = kaldi.fbank(
        waveform,
        num_mel_bins=80,
        frame_length=25,
        frame_shift=10,
        dither=0.0,
        sample_frequency=16000,
    )
    feats = feats - torch.mean(feats, dim=0, keepdim=True)
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name
    output = session.run([output_name], {input_name: feats.unsqueeze(0).numpy().astype(np.float32)})[0][0]
    return normalize(np.asarray(output, dtype=np.float32))


def decode_audio(path: Path, *, sample_rate: int) -> torch.Tensor:
    proc = subprocess.run(
        [
            "ffmpeg",
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
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace").strip() or "ffmpeg decode failed")
    waveform = np.frombuffer(proc.stdout, dtype=np.float32).copy()
    if waveform.size <= 0:
        raise RuntimeError("ffmpeg decoded empty audio")
    return torch.from_numpy(waveform).unsqueeze(0)


def leave_one_out_eval(embeddings: list[SampleEmbedding]) -> dict[str, Any]:
    return evaluate_vectors(embeddings, {item.sample_id: item.vector for item in embeddings})


def current_speechbrain_eval(store: Store, samples: list[SampleEmbedding]) -> dict[str, Any]:
    model = embedding_model_key(load_settings())
    rows = store.speaker_embedding_rows(model=model)
    vectors_by_sample: dict[int, np.ndarray] = {}
    for row in rows:
        sample_id = row["sample_id"]
        if sample_id is None:
            continue
        parsed = parse_vector(row["vector"])
        if parsed is None:
            continue
        vectors_by_sample[int(sample_id)] = normalize(np.asarray(parsed, dtype=np.float32))
    eligible = [item for item in samples if item.sample_id in vectors_by_sample]
    return evaluate_vectors(eligible, vectors_by_sample)


def evaluate_vectors(samples: list[SampleEmbedding], vectors_by_sample: dict[int, np.ndarray]) -> dict[str, Any]:
    attempts = 0
    correct = 0
    margins: list[float] = []
    scores: list[float] = []
    misses: list[dict[str, Any]] = []
    by_speaker: dict[int, dict[str, Any]] = {}

    for sample in samples:
        source = vectors_by_sample.get(sample.sample_id)
        if source is None:
            continue
        candidates = [item for item in samples if item.sample_id != sample.sample_id and item.sample_id in vectors_by_sample]
        best = best_match(source, candidates, vectors_by_sample)
        same_speaker_best = best_match(
            source,
            [item for item in candidates if item.speaker_id == sample.speaker_id],
            vectors_by_sample,
        )
        if best is None:
            continue
        attempts += 1
        predicted, score = best
        same_score = same_speaker_best[1] if same_speaker_best is not None else None
        second_other = best_match(
            source,
            [item for item in candidates if item.speaker_id != sample.speaker_id],
            vectors_by_sample,
        )
        other_score = second_other[1] if second_other is not None else None
        if same_score is not None and other_score is not None:
            margins.append(same_score - other_score)
        scores.append(score)
        speaker_stats = by_speaker.setdefault(
            sample.speaker_id,
            {"speaker_name": sample.speaker_name, "attempts": 0, "correct": 0, "misses": 0},
        )
        speaker_stats["attempts"] += 1
        if predicted.speaker_id == sample.speaker_id:
            correct += 1
            speaker_stats["correct"] += 1
        else:
            speaker_stats["misses"] += 1
            misses.append(
                {
                    "sample_id": sample.sample_id,
                    "speaker": sample.speaker_name,
                    "predicted": predicted.speaker_name,
                    "score": round(score, 4),
                    "same_speaker_score": round(same_score, 4) if same_score is not None else None,
                    "other_speaker_score": round(other_score, 4) if other_score is not None else None,
                    "margin": round((same_score - other_score), 4)
                    if same_score is not None and other_score is not None
                    else None,
                }
            )

    speaker_rows = []
    for speaker_id, stats in sorted(by_speaker.items()):
        attempts_for_speaker = int(stats["attempts"])
        speaker_rows.append(
            {
                "speaker_id": speaker_id,
                "speaker_name": stats["speaker_name"],
                "attempts": attempts_for_speaker,
                "correct": int(stats["correct"]),
                "misses": int(stats["misses"]),
                "accuracy": round(float(stats["correct"]) / attempts_for_speaker, 4)
                if attempts_for_speaker
                else None,
            }
        )
    return {
        "attempts": attempts,
        "correct": correct,
        "accuracy": round(correct / attempts, 4) if attempts else None,
        "avg_top_score": round(float(np.mean(scores)), 4) if scores else None,
        "avg_margin": round(float(np.mean(margins)), 4) if margins else None,
        "median_margin": round(float(np.median(margins)), 4) if margins else None,
        "speakers": speaker_rows,
        "misses": misses[:30],
    }


def best_match(
    source: np.ndarray,
    candidates: list[SampleEmbedding],
    vectors_by_sample: dict[int, np.ndarray],
) -> tuple[SampleEmbedding, float] | None:
    best: tuple[SampleEmbedding, float] | None = None
    for item in candidates:
        candidate = vectors_by_sample[item.sample_id]
        score = cosine(source, candidate)
        if best is None or score > best[1]:
            best = (item, score)
    return best


def normalize(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if not math.isfinite(norm) or norm <= 0:
        return vector.astype(np.float32)
    return (vector / norm).astype(np.float32)


def cosine(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.dot(normalize(left), normalize(right)))


if __name__ == "__main__":
    main()
