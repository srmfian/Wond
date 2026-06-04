from __future__ import annotations

import json
import math
import os
import shlex
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .config import Settings
from .executables import find_executable


DEFAULT_SPEECH_FILTER = (
    "highpass=f=80,"
    "lowpass=f=7800,"
    "afftdn=nf=-25,"
    "dynaudnorm=f=150:g=15,"
    "loudnorm=I=-18:TP=-1.5:LRA=11"
)

DEFAULT_OVERLAP_STEM_FILTERS = [
    "highpass=f=80,lowpass=f=1800",
    "highpass=f=500,lowpass=f=7800",
]

DEFAULT_SEPFORMER_INPUT_FILTER = "highpass=f=80,lowpass=f=7800,loudnorm=I=-18:TP=-1.5:LRA=11"
DEFAULT_SEPFORMER_POST_FILTER = "dynaudnorm=f=150:g=15,loudnorm=I=-18:TP=-1.5:LRA=11"


@dataclass
class PreparedAudio:
    path: Path
    metadata: dict[str, Any]
    cleanup: bool = False

    def close(self) -> None:
        if self.cleanup:
            self.path.unlink(missing_ok=True)


def audio_preprocessing_config(settings: Settings) -> dict[str, Any]:
    return getattr(settings, "audio_preprocessing", {}) or {}


def preprocessing_enabled(settings: Settings, key: str, default: bool = True) -> bool:
    cfg = audio_preprocessing_config(settings)
    return cfg_bool(cfg, key, default) and cfg_bool(cfg, "enabled", True)


def prepare_audio_for_stage(settings: Settings, source: Path, *, stage: str) -> PreparedAudio:
    if not preprocessing_enabled(settings, f"{stage}_enabled", True):
        return PreparedAudio(
            path=source,
            metadata={"stage": stage, "status": "disabled", "path": str(source)},
            cleanup=False,
        )
    ffmpeg = find_executable("ffmpeg")
    if not ffmpeg:
        return PreparedAudio(
            path=source,
            metadata={"stage": stage, "status": "skipped_missing_ffmpeg", "path": str(source)},
            cleanup=False,
        )

    cfg = audio_preprocessing_config(settings)
    sample_rate = int(cfg.get(f"{stage}_sample_rate") or cfg.get("sample_rate") or 16000)
    filter_chain = str(cfg.get(f"{stage}_filter") or cfg.get("speech_filter") or DEFAULT_SPEECH_FILTER)
    output = temp_audio_path(f"wond-{stage}-enhanced")
    ok, detail = run_ffmpeg_filter(
        source,
        output,
        filter_chain=filter_chain,
        sample_rate=sample_rate,
        codec="pcm_s16le",
        timeout=int(cfg.get("enhance_timeout_seconds", 180)),
    )
    if not ok:
        output.unlink(missing_ok=True)
        return PreparedAudio(
            path=source,
            metadata={
                "stage": stage,
                "status": "enhance_failed",
                "path": str(source),
                "error": detail,
            },
            cleanup=False,
        )
    return PreparedAudio(
        path=output,
        metadata={
            "stage": stage,
            "status": "enhanced",
            "source_path": str(source),
            "filter": filter_chain,
            "sample_rate": sample_rate,
        },
        cleanup=not cfg_bool(cfg, "keep_intermediate", False),
    )


def create_enhanced_sample_clip(
    settings: Settings,
    source: Path,
    output: Path,
    start: float,
    end: float,
) -> tuple[bool, dict[str, Any]]:
    cfg = audio_preprocessing_config(settings)
    if not preprocessing_enabled(settings, "speaker_samples_enabled", True):
        return False, {"status": "disabled"}
    filter_chain = str(cfg.get("speaker_sample_filter") or cfg.get("speech_filter") or DEFAULT_SPEECH_FILTER)
    ok, detail = run_ffmpeg_filter(
        source,
        output,
        filter_chain=filter_chain,
        start=start,
        duration=max(0.01, end - start),
        sample_rate=int(cfg.get("speaker_sample_rate") or cfg.get("sample_rate") or 16000),
        codec="aac",
        bitrate=str(cfg.get("speaker_sample_bitrate") or "96k"),
        timeout=int(cfg.get("sample_timeout_seconds", 120)),
    )
    metadata = {
        "status": "enhanced" if ok else "enhance_failed",
        "filter": filter_chain,
        "error": None if ok else detail,
    }
    return ok, metadata


def create_overlap_candidate_clip(
    settings: Settings,
    source: Path,
    output: Path,
    start: float,
    end: float,
    *,
    stem_index: int,
) -> tuple[bool, dict[str, Any]]:
    cfg = audio_preprocessing_config(settings)
    if not cfg_bool(cfg, "overlap_separation_enabled", True):
        return False, {"status": "disabled"}
    backend = str(cfg.get("overlap_separation_backend") or "ffmpeg_bandpass").strip().lower()
    if backend in {"speechbrain_sepformer", "sepformer"}:
        ok, metadata = create_overlap_candidate_with_speechbrain(
            settings,
            source,
            output,
            start,
            end,
            stem_index=stem_index,
        )
        if ok or not cfg_bool(cfg, "overlap_separation_fallback_enabled", True):
            return ok, metadata
        fallback_backend = str(cfg.get("overlap_separation_fallback_backend") or "ffmpeg_bandpass").strip().lower()
        if fallback_backend in {"ffmpeg_bandpass", "bandpass", "auto"}:
            fallback_ok, fallback_metadata = create_overlap_candidate_with_bandpass(
                settings,
                source,
                output,
                start,
                end,
                stem_index=stem_index,
            )
            fallback_metadata["fallback_from"] = metadata
            return fallback_ok, fallback_metadata
        metadata["fallback_backend"] = fallback_backend
        return ok, metadata
    if backend == "command":
        return create_overlap_candidate_with_command(settings, source, output, start, end, stem_index=stem_index)
    if backend not in {"ffmpeg_bandpass", "bandpass", "auto"}:
        return False, {"status": "unsupported_backend", "backend": backend}
    return create_overlap_candidate_with_bandpass(settings, source, output, start, end, stem_index=stem_index)


def create_overlap_candidate_with_bandpass(
    settings: Settings,
    source: Path,
    output: Path,
    start: float,
    end: float,
    *,
    stem_index: int,
) -> tuple[bool, dict[str, Any]]:
    cfg = audio_preprocessing_config(settings)
    stem_filters = cfg.get("overlap_stem_filters")
    if not isinstance(stem_filters, list) or not stem_filters:
        stem_filters = DEFAULT_OVERLAP_STEM_FILTERS
    stem_filter = str(stem_filters[stem_index % len(stem_filters)])
    base_filter = str(cfg.get("overlap_base_filter") or cfg.get("speech_filter") or DEFAULT_SPEECH_FILTER)
    filter_chain = ",".join(part for part in [base_filter, stem_filter] if part)
    ok, detail = run_ffmpeg_filter(
        source,
        output,
        filter_chain=filter_chain,
        start=start,
        duration=max(0.01, end - start),
        sample_rate=int(cfg.get("speaker_sample_rate") or cfg.get("sample_rate") or 16000),
        codec="aac",
        bitrate=str(cfg.get("speaker_sample_bitrate") or "96k"),
        timeout=int(cfg.get("sample_timeout_seconds", 120)),
    )
    return ok, {
        "status": "separated" if ok else "separation_failed",
        "backend": "ffmpeg_bandpass",
        "filter": filter_chain,
        "stem_index": stem_index,
        "error": None if ok else detail,
    }


def create_overlap_candidate_with_speechbrain(
    settings: Settings,
    source: Path,
    output: Path,
    start: float,
    end: float,
    *,
    stem_index: int,
) -> tuple[bool, dict[str, Any]]:
    cfg = audio_preprocessing_config(settings)
    model = str(cfg.get("overlap_sepformer_model") or "speechbrain/sepformer-whamr16k").strip()
    model_dir = sepformer_model_dir(settings, model)
    sample_rate = int(cfg.get("overlap_sepformer_sample_rate") or cfg.get("speaker_sample_rate") or 16000)
    clip = temp_audio_path("wond-sepformer-input")
    stem_wav = temp_audio_path("wond-sepformer-stem")
    input_filter = str(cfg.get("overlap_sepformer_input_filter") or DEFAULT_SEPFORMER_INPUT_FILTER)
    ok, detail = run_ffmpeg_filter(
        source,
        clip,
        filter_chain=input_filter,
        start=start,
        duration=max(0.01, end - start),
        sample_rate=sample_rate,
        codec="pcm_s16le",
        timeout=int(cfg.get("sample_timeout_seconds", 120)),
    )
    if not ok:
        clip.unlink(missing_ok=True)
        stem_wav.unlink(missing_ok=True)
        return False, {
            "status": "sepformer_input_failed",
            "backend": "speechbrain_sepformer",
            "model": model,
            "error": detail,
        }

    script = """
import json
import os
import sys

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")

audio_path = sys.argv[1]
output_path = sys.argv[2]
model = sys.argv[3]
savedir = sys.argv[4]
stem_index = int(sys.argv[5])
device = sys.argv[6]

try:
    from speechbrain.inference.separation import SepformerSeparation
except Exception:
    from speechbrain.pretrained import SepformerSeparation

import soundfile as sf
import torch

run_opts = {"device": device} if device else {}
separator = SepformerSeparation.from_hparams(source=model, savedir=savedir, run_opts=run_opts)
sources = separator.separate_file(audio_path)
if sources.ndim == 3:
    num_sources = int(sources.shape[-1])
    selected = sources[0, :, stem_index % num_sources]
elif sources.ndim == 2:
    num_sources = int(sources.shape[-1])
    selected = sources[:, stem_index % num_sources]
else:
    raise RuntimeError(f"unexpected SepFormer output shape: {tuple(sources.shape)}")
sample_rate = int(getattr(separator.hparams, "sample_rate", 16000))
waveform = selected.detach().cpu().float().unsqueeze(0)
peak = torch.max(torch.abs(waveform)).item()
if peak > 0:
    waveform = waveform / max(peak, 1.0)
sf.write(output_path, waveform.squeeze(0).numpy(), sample_rate)
print(json.dumps({"num_sources": num_sources, "sample_rate": sample_rate}, ensure_ascii=False))
""".strip()
    env = os.environ.copy()
    env.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    env.setdefault("OMP_NUM_THREADS", "1")
    device = str(cfg.get("overlap_sepformer_device") or "").strip()
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script, str(clip), str(stem_wav), model, str(model_dir), str(stem_index), device],
            text=True,
            capture_output=True,
            timeout=int(cfg.get("overlap_separation_timeout_seconds", 900)),
            check=False,
            env=env,
        )
        if proc.returncode != 0 or not stem_wav.exists() or stem_wav.stat().st_size == 0:
            return False, {
                "status": "sepformer_failed",
                "backend": "speechbrain_sepformer",
                "model": model,
                "model_dir": str(model_dir),
                "stem_index": stem_index,
                "error": (proc.stderr or proc.stdout).strip() or "SepFormer did not write output",
            }
        payload = last_json_object(proc.stdout)
        post_filter = str(cfg.get("overlap_sepformer_post_filter") or DEFAULT_SEPFORMER_POST_FILTER)
        encoded, encode_error = run_ffmpeg_filter(
            stem_wav,
            output,
            filter_chain=post_filter,
            sample_rate=int(cfg.get("speaker_sample_rate") or cfg.get("sample_rate") or 16000),
            codec="aac",
            bitrate=str(cfg.get("speaker_sample_bitrate") or "96k"),
            timeout=int(cfg.get("sample_timeout_seconds", 120)),
        )
        if not encoded:
            return False, {
                "status": "sepformer_encode_failed",
                "backend": "speechbrain_sepformer",
                "model": model,
                "model_dir": str(model_dir),
                "stem_index": stem_index,
                "sepformer": payload,
                "error": encode_error,
            }
        return True, {
            "status": "separated",
            "backend": "speechbrain_sepformer",
            "model": model,
            "model_dir": str(model_dir),
            "stem_index": stem_index,
            "sepformer": payload,
            "input_filter": input_filter,
            "post_filter": post_filter,
            "error": None,
        }
    finally:
        clip.unlink(missing_ok=True)
        stem_wav.unlink(missing_ok=True)


def create_overlap_candidate_with_command(
    settings: Settings,
    source: Path,
    output: Path,
    start: float,
    end: float,
    *,
    stem_index: int,
) -> tuple[bool, dict[str, Any]]:
    cfg = audio_preprocessing_config(settings)
    command_template = str(cfg.get("overlap_separation_command") or "").strip()
    if not command_template:
        return False, {"status": "missing_command", "backend": "command"}
    clip = temp_audio_path("wond-overlap-source")
    ok, detail = run_ffmpeg_filter(
        source,
        clip,
        filter_chain=str(cfg.get("overlap_command_input_filter") or cfg.get("speech_filter") or DEFAULT_SPEECH_FILTER),
        start=start,
        duration=max(0.01, end - start),
        sample_rate=int(cfg.get("speaker_sample_rate") or cfg.get("sample_rate") or 16000),
        codec="pcm_s16le",
        timeout=int(cfg.get("sample_timeout_seconds", 120)),
    )
    if not ok:
        clip.unlink(missing_ok=True)
        return False, {"status": "command_input_failed", "backend": "command", "error": detail}
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        command = command_template.format(input=str(clip), output=str(output), stem_index=stem_index)
        proc = subprocess.run(
            shlex.split(command),
            text=True,
            capture_output=True,
            timeout=int(cfg.get("overlap_separation_timeout_seconds", 300)),
            check=False,
        )
        if proc.returncode != 0 or not output.exists() or output.stat().st_size == 0:
            detail = (proc.stderr or proc.stdout).strip() or "overlap separation command did not write output"
            return False, {"status": "command_failed", "backend": "command", "error": detail}
        return True, {"status": "separated", "backend": "command", "stem_index": stem_index}
    finally:
        clip.unlink(missing_ok=True)


def audio_quality(settings: Settings, path: Path, *, min_seconds: float | None = None) -> dict[str, Any]:
    cfg = audio_preprocessing_config(settings)
    sample_rate = int(cfg.get("quality_sample_rate") or 16000)
    waveform = decode_audio(path, sample_rate=sample_rate)
    if waveform.size == 0:
        return {"ok": False, "reason": "empty_audio", "duration_seconds": 0.0}
    duration = waveform.size / sample_rate
    rms = float(np.sqrt(np.mean(np.square(waveform), dtype=np.float64)))
    peak = float(np.max(np.abs(waveform)))
    rms_dbfs = 20 * math.log10(max(rms, 1e-8))
    peak_dbfs = 20 * math.log10(max(peak, 1e-8))
    clipped_ratio = float(np.mean(np.abs(waveform) >= 0.999))
    min_duration = min_seconds
    if min_duration is None:
        min_duration = float(cfg.get("quality_min_seconds") or 0.8)
    min_rms = float(cfg.get("quality_min_rms_dbfs") or -45.0)
    max_clip = float(cfg.get("quality_max_clipped_ratio") or 0.02)
    speech_activity = speech_activity_stats(waveform, sample_rate=sample_rate, config=cfg)
    min_speech_seconds = max(0.0, float(cfg.get("quality_min_speech_seconds") or 2.0))
    min_speech_seconds = min(min_speech_seconds, max(0.25, duration * 0.45))
    min_speech_ratio = max(0.0, float(cfg.get("quality_min_speech_ratio") or 0.22))
    speech_ok = (
        float(speech_activity["active_seconds"]) >= min_speech_seconds
        and float(speech_activity["active_ratio"]) >= min_speech_ratio
    )
    noise_gate_enabled = cfg_bool(cfg, "quality_noise_gate_enabled", True)
    max_noise_floor = float(cfg.get("quality_max_noise_floor_dbfs") if cfg.get("quality_max_noise_floor_dbfs") not in (None, "") else -28.0)
    min_noise_margin = float(
        cfg.get("quality_min_speech_noise_margin_db")
        if cfg.get("quality_min_speech_noise_margin_db") not in (None, "")
        else 9.0
    )
    noise_ok = (
        not noise_gate_enabled
        or (
            float(speech_activity["noise_floor_dbfs"]) <= max_noise_floor
            and float(speech_activity["speech_noise_margin_db"]) >= min_noise_margin
        )
    )
    ok = duration >= min_duration and rms_dbfs >= min_rms and clipped_ratio <= max_clip and speech_ok and noise_ok
    reason = None
    if duration < min_duration:
        reason = "too_short"
    elif rms_dbfs < min_rms:
        reason = "too_quiet"
    elif clipped_ratio > max_clip:
        reason = "clipped"
    elif not speech_ok:
        reason = "low_speech_activity"
    elif not noise_ok:
        reason = "noisy_background"
    return {
        "ok": ok,
        "reason": reason,
        "duration_seconds": round(duration, 3),
        "rms_dbfs": round(rms_dbfs, 2),
        "peak_dbfs": round(peak_dbfs, 2),
        "clipped_ratio": round(clipped_ratio, 5),
        "speech_activity": {
            **speech_activity,
            "min_active_seconds": round(min_speech_seconds, 3),
            "min_active_ratio": round(min_speech_ratio, 3),
            "max_noise_floor_dbfs": round(max_noise_floor, 2),
            "min_speech_noise_margin_db": round(min_noise_margin, 2),
        },
    }


def speech_activity_stats(waveform: np.ndarray, *, sample_rate: int, config: dict[str, Any]) -> dict[str, float]:
    frame_size = max(1, int(sample_rate * 0.025))
    hop_size = max(1, int(sample_rate * 0.010))
    if waveform.size < frame_size:
        return {
            "active_ratio": 0.0,
            "active_seconds": 0.0,
            "noise_floor_dbfs": -120.0,
            "threshold_dbfs": -120.0,
        }

    rms_values: list[float] = []
    zcr_values: list[float] = []
    for offset in range(0, waveform.size - frame_size + 1, hop_size):
        frame = waveform[offset : offset + frame_size]
        rms = float(np.sqrt(np.mean(np.square(frame), dtype=np.float64)))
        rms_values.append(20 * math.log10(max(rms, 1e-8)))
        zcr_values.append(float(np.mean(np.abs(np.diff(np.signbit(frame))))))

    if not rms_values:
        return {
            "active_ratio": 0.0,
            "active_seconds": 0.0,
            "noise_floor_dbfs": -120.0,
            "threshold_dbfs": -120.0,
        }

    rms_array = np.array(rms_values, dtype=float)
    zcr_array = np.array(zcr_values, dtype=float)
    noise_floor = float(np.percentile(rms_array, 20))
    margin_db = float(config.get("quality_speech_activity_margin_db") or 6.0)
    min_dbfs = float(config.get("quality_speech_activity_min_dbfs") or -42.0)
    max_zcr = float(config.get("quality_speech_activity_max_zcr") or 0.35)
    threshold = max(noise_floor + margin_db, min_dbfs)
    active = (rms_array > threshold) & (zcr_array < max_zcr)
    active_ratio = float(np.mean(active))
    active_seconds = float(np.sum(active) * hop_size / sample_rate)
    active_values = rms_array[active]
    inactive_values = rms_array[~active]
    active_median = float(np.median(active_values)) if active_values.size else -120.0
    inactive_median = float(np.median(inactive_values)) if inactive_values.size else noise_floor
    speech_noise_margin = max(0.0, active_median - noise_floor) if active_values.size else 0.0
    return {
        "active_ratio": round(active_ratio, 4),
        "active_seconds": round(active_seconds, 3),
        "noise_floor_dbfs": round(noise_floor, 2),
        "threshold_dbfs": round(threshold, 2),
        "active_median_dbfs": round(active_median, 2),
        "inactive_median_dbfs": round(inactive_median, 2),
        "speech_noise_margin_db": round(speech_noise_margin, 2),
    }


def decode_audio(path: Path, *, sample_rate: int) -> np.ndarray:
    ffmpeg = find_executable("ffmpeg")
    if not ffmpeg:
        return np.array([], dtype=np.float32)
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
        timeout=120,
    )
    if proc.returncode != 0:
        return np.array([], dtype=np.float32)
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


def run_ffmpeg_filter(
    source: Path,
    output: Path,
    *,
    filter_chain: str,
    sample_rate: int,
    codec: str,
    start: float | None = None,
    duration: float | None = None,
    bitrate: str | None = None,
    timeout: int,
) -> tuple[bool, str | None]:
    ffmpeg = find_executable("ffmpeg")
    if not ffmpeg:
        return False, "ffmpeg not found"
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    if start is not None:
        command.extend(["-ss", f"{start:.3f}"])
    if duration is not None:
        command.extend(["-t", f"{duration:.3f}"])
    command.extend(
        [
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-af",
            filter_chain,
            "-c:a",
            codec,
        ]
    )
    if bitrate:
        command.extend(["-b:a", bitrate])
    command.append(str(output))
    proc = subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)
    if proc.returncode != 0 or not output.exists() or output.stat().st_size == 0:
        output.unlink(missing_ok=True)
        return False, (proc.stderr or proc.stdout).strip() or "ffmpeg filter failed"
    return True, None


def temp_audio_path(prefix: str) -> Path:
    return Path("/private/tmp") / f"{prefix}-{uuid.uuid4().hex}.wav"


def sepformer_model_dir(settings: Settings, model: str) -> Path:
    cfg = audio_preprocessing_config(settings)
    raw = str(cfg.get("overlap_sepformer_model_dir") or "models/speechbrain_sepformer")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = settings.data_dir / path
    model_part = model.replace("/", "__")
    target = path / model_part
    target.mkdir(parents=True, exist_ok=True)
    return target


def last_json_object(text: str) -> dict[str, Any]:
    for line in reversed((text or "").splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def cfg_bool(config: dict[str, Any], key: str, default: bool) -> bool:
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)
