from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_NAME = "config.json"


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_config_path() -> Path:
    return project_root() / DEFAULT_CONFIG_NAME


def expand_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


DEFAULT_CONFIG: dict[str, Any] = {
    "data_dir": "data",
    "timezone": "Asia/Tokyo",
    "collectors": {
        "foreground_app": True,
        "calendar": True,
        "reminders": True,
        "browsers": True,
        "recent_files": True,
        "messages": True,
        "apple_mail": True,
        "photo_locations": True,
    },
    "watch_paths": [
        "~/Desktop",
        "~/Documents",
        "~/Downloads",
    ],
    "browser_profiles": {
        "chrome": True,
        "brave": True,
        "edge": True,
        "safari": True,
    },
    "limits": {
        "browser_visits": 500,
        "recent_files": 500,
        "recent_files_scan_files": 12000,
        "recent_files_scan_seconds": 20,
        "messages": 300,
        "mail_messages": 250,
        "photo_locations": 150,
        "reminders_discovery_timeout_seconds": 8,
        "reminders_list_timeout_seconds": 8,
        "reminders_max_lists": 60,
        "reminders_items_per_list": 300,
    },
    "agent": {
        "sample_interval_seconds": 60,
        "collect_every_seconds": 900,
        "summary_every_seconds": 1800,
        "compaction_every_seconds": 3600,
        "retention_every_seconds": 86400,
    },
    "retention": {
        "enabled": True,
        "raw_observations_days": 180,
        "activity_samples_days": 180,
        "detailed_reports_days": 180,
        "collector_runs_days": 45,
        "agent_logs_max_mb": 10,
        "require_daily_summary_before_prune": True,
        "vacuum_after_prune": True,
    },
    "email_reports": {
        "enabled": False,
        "from": "sender@example.com",
        "to": ["recipient@example.com"],
        "daily": True,
        "weekly": True,
        "send_time": "07:00",
        "daily_send_time": "07:00",
        "weekly_send_time": "06:30",
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_username": "sender@example.com",
        "password_env": "WOND_SMTP_PASSWORD",
        "keychain_service": "wond-smtp",
        "keychain_account": "sender@example.com",
        "retry_after_seconds": 3600,
        "send_window_seconds": 7200,
        "ai_highlights": True,
        "daily_highlight_items": 6,
        "weekly_highlight_items": 10,
        "highlight_source_max_chars": 30000,
    },
    "file_analysis": {
        "enabled": False,
        "scan_interval_seconds": 60,
        "stability_seconds": 30,
        "max_files_per_scan": 3,
        "retry_after_seconds": 3600,
        "lock_stale_seconds": 1800,
        "run_stale_seconds": 3600,
        "analysis_copy_dir": "file_analysis_workspace",
        "delete_after_analysis": False,
        "include_suffixes": [
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".webp",
            ".heic",
            ".pdf",
            ".txt",
            ".md",
            ".csv",
            ".json",
            ".docx",
            ".xlsx",
            ".pptx",
            ".m4a",
            ".mp3",
            ".mp4",
            ".wav",
            ".webm",
        ],
        "exclude_suffixes": [
            ".crdownload",
            ".download",
            ".part",
            ".tmp",
        ],
        "exclude_dirs": [
            ".git",
            ".venv",
            "__pycache__",
            "node_modules",
            "Library",
            ".Trash",
        ],
    },
    "recycle_bin": {
        "enabled": True,
        "dir": "recycle_bin",
        "retention_hours": 24,
        "purge_on_scan": True,
        "purge_on_agent_maintenance": True,
    },
    "audio_analysis": {
        "enabled": True,
        "scan_interval_seconds": 60,
        "continuous_queue": True,
        "busy_pause_seconds": 1,
        "lookback_days": 1,
        "auto_limit": 3,
        "summary_model": "",
        "delete_missing_audio_records": False,
        "max_segments": 20,
    },
    "audio_preprocessing": {
        "enabled": True,
        "asr_enabled": True,
        "diarization_enabled": True,
        "speaker_samples_enabled": True,
        "speech_filter": "highpass=f=80,lowpass=f=7800,afftdn=nf=-25,dynaudnorm=f=150:g=15,loudnorm=I=-18:TP=-1.5:LRA=11",
        "sample_rate": 16000,
        "asr_sample_rate": 16000,
        "diarization_sample_rate": 24000,
        "speaker_sample_rate": 16000,
        "speaker_sample_bitrate": "96k",
        "quality_min_seconds": 0.8,
        "quality_min_rms_dbfs": -45,
        "quality_max_clipped_ratio": 0.02,
        "quality_min_speech_seconds": 2.0,
        "quality_min_speech_ratio": 0.22,
        "quality_speech_activity_margin_db": 6.0,
        "quality_speech_activity_min_dbfs": -42.0,
        "quality_speech_activity_max_zcr": 0.35,
        "quality_noise_gate_enabled": True,
        "quality_max_noise_floor_dbfs": -28.0,
        "quality_min_speech_noise_margin_db": 9.0,
        "keep_intermediate": False,
        "overlap_separation_enabled": True,
        "overlap_separation_backend": "speechbrain_sepformer",
        "overlap_separation_fallback_enabled": True,
        "overlap_separation_fallback_backend": "ffmpeg_bandpass",
        "overlap_separation_timeout_seconds": 900,
        "overlap_sepformer_model": "speechbrain/sepformer-whamr16k",
        "overlap_sepformer_model_dir": "models/speechbrain_sepformer",
        "overlap_sepformer_device": "",
        "overlap_sepformer_input_filter": "highpass=f=80,lowpass=f=7800,loudnorm=I=-18:TP=-1.5:LRA=11",
        "overlap_sepformer_post_filter": "dynaudnorm=f=150:g=15,loudnorm=I=-18:TP=-1.5:LRA=11",
        "overlap_create_new_speakers": False,
        "overlap_stem_filters": [
            "highpass=f=80,lowpass=f=1800",
            "highpass=f=500,lowpass=f=7800",
        ],
    },
    "speaker_recognition": {
        "enabled": True,
        "embedding_backend": "speechbrain_ecapa",
        "embedding_model": "speechbrain/spkrec-ecapa-voxceleb",
        "embedding_model_dir": "models/speechbrain",
        "embedding_sample_rate": 16000,
        "sample_seconds": 16,
        "sample_min_seconds": 0.5,
        "sample_boundary_guard_seconds": 0.08,
        "sample_stride_seconds": 16,
        "sample_fine_window_seconds": 3,
        "sample_fine_stride_seconds": 2.5,
        "samples_per_speaker_per_observation": 200,
        "sample_unlabeled_speech": True,
        "sample_require_diarization_segments": True,
        "sample_long_segment_anchor": "start",
        "sample_dir": "speaker_samples",
        "collapse_vad_chunk_scopes": False,
        "confirmed_profile_matching_enabled": True,
        "confirmed_profile_max_prototypes": 6,
        "confirmed_profile_min_samples": 2,
        "auto_merge_threshold": 0.68,
        "auto_merge_max_merges": 5000,
        "candidate_threshold": 0.68,
        "review_min_samples": 5,
        "review_min_observations": 3,
        "review_min_days": 2,
        "review_min_confidence": 0.90,
    },
    "ai_backend": {
        "provider": "local",
    },
    "local_ai": {
        "ollama_base_url": "http://127.0.0.1:11434",
        "text_model": "qwen3.5:35b",
        "vision_model": "qwen3.5:35b",
        "search_embedding_model": "",
        "search_embedding_candidates": [
            "bge-m3:latest",
            "bge-m3",
            "qwen3-embedding:4b",
            "nomic-embed-text:latest",
            "mxbai-embed-large:latest",
        ],
        "search_index_limit": 5000,
        "search_auto_index_limit": 400,
        "search_chunk_chars": 1400,
        "search_top_k": 18,
        "disable_thinking": True,
        "temperature": 0.2,
        "max_text_chars": 30000,
        "max_file_mb": 50,
        "max_audio_mb": 1024,
        "summary_prompt": "Summarize the content for a personal memory timeline. Include key people, decisions, tasks, places, times, and anything that may need follow-up. Keep it concise.",
        "transcription_backend": "mlx_audio",
        "transcription_model": "mlx-community/Qwen3-ASR-1.7B-8bit",
        "fallback_transcription_backend": "",
        "fallback_transcription_model": "",
        "speaker_diarization_enabled": True,
        "speaker_diarization_backend": "vibevoice_mlx",
        "speaker_diarization_model": "mlx-community/VibeVoice-ASR-4bit",
        "speaker_diarization_fallback_backend": "",
        "speaker_diarization_fallback_model": "",
        "speaker_diarization_timeout_seconds": 900,
        "speaker_diarization_context": (
            "Return timestamped transcript segments with distinct speaker labels. "
            "Split aggressively at every speaker turn, including very short replies, backchannels, and interruptions. "
            "Do not merge multiple speakers into one segment."
        ),
        "transcription_language": "auto",
        "transcription_command": "",
        "vad_presegment": True,
        "vad_presegment_diarization": True,
        "vad_silence_noise_db": -35,
        "vad_min_silence_seconds": 0.5,
        "vad_min_speech_seconds": 0.45,
        "vad_min_total_speech_seconds": 1.0,
        "vad_padding_seconds": 0.25,
        "vad_merge_gap_seconds": 1.5,
        "vad_max_chunk_seconds": 45,
        "vad_max_chunks": 16,
        "diarization_vad_merge_gap_seconds": 3.0,
        "diarization_vad_max_chunk_seconds": 120,
        "diarization_vad_max_chunks": 32,
        "diarization_vad_max_count_merge_gap_seconds": 8.0,
        "vibevoice_prompt": (
            "Transcribe the audio with timestamps and distinct speaker labels such as Speaker 1 and Speaker 2. "
            "Split aggressively at every speaker turn, including very short replies, backchannels, and interruptions. "
            "Preserve the spoken language and code switching."
        ),
        "vibevoice_device_map": "auto",
    },
    "openai_analysis": {
        "analysis_model": "gpt-5.5",
        "transcription_model": "gpt-4o-transcribe-diarize",
        "transcription_response_format": "auto",
        "transcription_base_url": "",
        "max_file_mb": 20,
        "max_audio_mb": 25,
        "summary_prompt": "Summarize the content for a personal memory timeline. Include key people, decisions, tasks, places, times, and anything that may need follow-up. Keep it concise.",
    },
    "mobile_sync": {
        "host": "0.0.0.0",
        "port": 8765,
        "service_name": "Wond",
        "token": "",
        "max_upload_mb": 2048,
        "require_encrypted_uploads": True,
        "write_reports": True,
        "skip_existing_uploads": True,
        "analyze_after_import": False,
        "analyze_limit": 20,
        "delete_uploads_after_import": True,
        "delete_unreferenced_imports": True,
        "delete_audio_after_analysis": False,
        "delete_audio_after_analysis_repair_window_hours": 24,
    },
}


@dataclass(frozen=True)
class Settings:
    path: Path
    data_dir: Path
    timezone: str
    collectors: dict[str, bool] = field(default_factory=dict)
    watch_paths: list[Path] = field(default_factory=list)
    browser_profiles: dict[str, bool] = field(default_factory=dict)
    limits: dict[str, int] = field(default_factory=dict)
    agent: dict[str, int] = field(default_factory=dict)
    retention: dict[str, Any] = field(default_factory=dict)
    email_reports: dict[str, Any] = field(default_factory=dict)
    file_analysis: dict[str, Any] = field(default_factory=dict)
    recycle_bin: dict[str, Any] = field(default_factory=dict)
    audio_analysis: dict[str, Any] = field(default_factory=dict)
    audio_preprocessing: dict[str, Any] = field(default_factory=dict)
    speaker_recognition: dict[str, Any] = field(default_factory=dict)
    ai_backend: dict[str, Any] = field(default_factory=dict)
    local_ai: dict[str, Any] = field(default_factory=dict)
    openai_analysis: dict[str, Any] = field(default_factory=dict)
    mobile_sync: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        configured = self.raw.get("database_path")
        if configured:
            path = Path(str(configured)).expanduser()
            if path.is_absolute():
                return path
            return self.path.parent / path
        return self.data_dir / "wond.sqlite3"

    @property
    def report_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def summary_dir(self) -> Path:
        return self.data_dir / "summaries"

    @property
    def recycle_bin_dir(self) -> Path:
        raw_dir = self.recycle_bin.get("dir", "recycle_bin")
        bin_dir = Path(str(raw_dir)).expanduser()
        if bin_dir.is_absolute():
            return bin_dir
        return self.data_dir / bin_dir

    @property
    def speaker_sample_dir(self) -> Path:
        raw_dir = self.speaker_recognition.get("sample_dir", "speaker_samples")
        sample_dir = Path(str(raw_dir)).expanduser()
        if sample_dir.is_absolute():
            return sample_dir
        return self.data_dir / sample_dir

    @property
    def speaker_embedding_model_dir(self) -> Path:
        raw_dir = self.speaker_recognition.get("embedding_model_dir", "models/speechbrain")
        model_dir = Path(str(raw_dir)).expanduser()
        if model_dir.is_absolute():
            return model_dir
        return self.data_dir / model_dir


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def ensure_config(path: Path | None = None) -> Path:
    config_path = path or default_config_path()
    if not config_path.exists():
        config_path.write_text(
            json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return config_path


def load_settings(path: Path | None = None) -> Settings:
    config_path = ensure_config(path)
    loaded = json.loads(config_path.read_text(encoding="utf-8"))
    raw = deep_merge(DEFAULT_CONFIG, loaded)
    base_dir = config_path.parent
    data_dir = Path(raw["data_dir"]).expanduser()
    if not data_dir.is_absolute():
        data_dir = base_dir / data_dir
    watch_paths = [expand_path(item) for item in raw.get("watch_paths", [])]
    settings = Settings(
        path=config_path,
        data_dir=data_dir.resolve(),
        timezone=raw.get("timezone", "Asia/Tokyo"),
        collectors=dict(raw.get("collectors", {})),
        watch_paths=watch_paths,
        browser_profiles=dict(raw.get("browser_profiles", {})),
        limits={key: int(value) for key, value in raw.get("limits", {}).items()},
        agent={key: int(value) for key, value in raw.get("agent", {}).items()},
        retention=dict(raw.get("retention", {})),
        email_reports=dict(raw.get("email_reports", {})),
        file_analysis=dict(raw.get("file_analysis", {})),
        recycle_bin=dict(raw.get("recycle_bin", {})),
        audio_analysis=dict(raw.get("audio_analysis", {})),
        audio_preprocessing=dict(raw.get("audio_preprocessing", {})),
        speaker_recognition=dict(raw.get("speaker_recognition", {})),
        ai_backend=dict(raw.get("ai_backend", {})),
        local_ai=dict(raw.get("local_ai", {})),
        openai_analysis=dict(raw.get("openai_analysis", {})),
        mobile_sync=dict(raw.get("mobile_sync", {})),
        raw=raw,
    )
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.report_dir.mkdir(parents=True, exist_ok=True)
    settings.summary_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    settings.recycle_bin_dir.mkdir(parents=True, exist_ok=True)
    settings.speaker_sample_dir.mkdir(parents=True, exist_ok=True)
    settings.speaker_embedding_model_dir.mkdir(parents=True, exist_ok=True)
    return settings
