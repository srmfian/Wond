from __future__ import annotations

import plistlib
import signal
import sys
import threading
import time
from datetime import date, timedelta
from pathlib import Path

from .audio_analysis import analyze_audio_for_day, pending_audio_count_for_day
from .collectors import collect_all, is_collector_error_result, sample_foreground_app
from .config import Settings
from .store import Store
from .compactor import write_all_compact_summaries
from .email_reports import send_due_email_reports
from .file_analysis import analyze_new_files
from .recycle_bin import purge_recycle_bin, recycle_bool
from .retention import run_retention
from .summarizer import write_daily_report
from .sync_server import cleanup_mobile_sync_storage
from .timeutil import day_bounds, local_iso, now


def run_monitor(settings: Settings, store: Store, once: bool = False) -> None:
    interval = settings.agent.get("sample_interval_seconds", 60)
    collect_every = settings.agent.get("collect_every_seconds", 900)
    summary_every = settings.agent.get("summary_every_seconds", 1800)
    compaction_every = settings.agent.get("compaction_every_seconds", 3600)
    retention_every = settings.agent.get("retention_every_seconds", 86400)
    stopping = False
    audio_stop = threading.Event()
    audio_thread = None

    def stop(_signum, _frame) -> None:
        nonlocal stopping
        stopping = True
        audio_stop.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    if audio_analysis_enabled(settings) and not once:
        audio_thread = threading.Thread(
            target=run_audio_analysis_loop,
            args=(settings, audio_stop),
            name="wond-audio-analysis",
            daemon=True,
        )
        audio_thread.start()

    last_collect = 0.0
    last_summary = 0.0
    last_compaction = 0.0
    last_retention = 0.0
    try:
        while not stopping:
            sample = sample_foreground_app(settings)
            if sample:
                store.add_activity_sample(sample)

            current_time = time.time()
            current_day = now(settings.timezone).date()
            start, end = day_bounds(current_day, settings.timezone)
            audio_days = audio_analysis_days(settings, current_day)
            skip_collectors = (
                not once
                and audio_analysis_enabled(settings)
                and any(pending_audio_count_for_day(settings, store, audio_day) > 0 for audio_day in audio_days)
            )

            if once and audio_analysis_enabled(settings):
                if run_audio_analysis_cycle(settings, store, current_day):
                    break

            if not skip_collectors and current_time - last_collect >= collect_every:
                for name, observations in collect_all(settings, start, end).items():
                    run_id = store.start_run(name)
                    try:
                        count = store.upsert_observations(observations)
                        if is_collector_error_result(name, observations):
                            store.finish_run(run_id, "error", observations[0].body or observations[0].title or "collector_error")
                            continue
                        else:
                            store.clear_collector_error(name, start.date())
                        store.finish_run(run_id, "ok", f"{count} observations")
                    except Exception as exc:
                        store.finish_run(run_id, "error", str(exc))
                last_collect = current_time

            if current_time - last_summary >= summary_every:
                write_daily_report(settings, store, current_day)
                last_summary = current_time

            if current_time - last_compaction >= compaction_every:
                write_all_compact_summaries(settings, store, current_day)
                last_compaction = current_time

            if settings.retention.get("enabled", True) and current_time - last_retention >= retention_every:
                run_retention(settings, store, current_day, dry_run=False)
                if recycle_bool(settings, "purge_on_agent_maintenance", True):
                    purge_recycle_bin(settings, dry_run=False, now_ts=current_time)
                last_retention = current_time

            file_result = analyze_new_files(settings, store, now_ts=current_time)
            if file_result.analyzed:
                write_daily_report(settings, store, current_day)

            send_due_email_reports(settings, store)

            if once:
                break
            time.sleep(max(5, interval))
    finally:
        audio_stop.set()
        if audio_thread is not None:
            audio_thread.join(timeout=5)


def audio_analysis_enabled(settings: Settings) -> bool:
    return bool(settings.audio_analysis.get("enabled", True))


def audio_analysis_limit(settings: Settings) -> int:
    return int(settings.audio_analysis.get("auto_limit") or settings.audio_analysis.get("max_segments", 20))


def audio_analysis_lookback_days(settings: Settings) -> int:
    try:
        value = int(settings.audio_analysis.get("lookback_days", 1))
    except (TypeError, ValueError):
        value = 1
    return min(30, max(0, value))


def audio_analysis_days(settings: Settings, current_day: date) -> list[date]:
    lookback_days = audio_analysis_lookback_days(settings)
    return [current_day - timedelta(days=offset) for offset in range(lookback_days, -1, -1)]


def run_audio_analysis_cycle(settings: Settings, store: Store, current_day: date) -> bool:
    did_work = False
    for audio_day in audio_analysis_days(settings, current_day):
        did_work = run_audio_analysis_iteration(settings, store, audio_day) or did_work
    return did_work


def run_audio_analysis_iteration(settings: Settings, store: Store, current_day: date) -> bool:
    if recycle_bool(settings, "purge_on_scan", True):
        purge_recycle_bin(settings, dry_run=False)
    audio_result = analyze_audio_for_day(settings, store, current_day, limit=audio_analysis_limit(settings))
    did_work = bool(
        audio_result.updated
        or audio_result.deleted
        or audio_result.transcribed
        or audio_result.deleted_records
    )
    if did_work:
        cleanup_mobile_sync_storage(settings, store, dry_run=False, clean_inbox=True, clean_imports=True)
        write_daily_report(settings, store, current_day)
    return did_work


def run_audio_analysis_loop(settings: Settings, stop_event: threading.Event) -> None:
    store = Store(settings.db_path)
    interval = max(5, int(settings.audio_analysis.get("scan_interval_seconds", 300)))
    continuous_queue = bool(settings.audio_analysis.get("continuous_queue", True))
    busy_pause = max(0.0, float(settings.audio_analysis.get("busy_pause_seconds", 1)))
    try:
        while not stop_event.is_set():
            current_day = now(settings.timezone).date()
            did_work = run_audio_analysis_cycle(settings, store, current_day)
            if continuous_queue and did_work:
                stop_event.wait(busy_pause)
                continue
            stop_event.wait(interval)
    finally:
        store.close()


def launch_agent_label() -> str:
    return "com.local.wond-agent"


def sync_launch_agent_label() -> str:
    return "com.local.wond-sync"


def dashboard_launch_agent_label() -> str:
    return "com.local.wond-dashboard"


def launch_agent_path() -> Path:
    return Path("~/Library/LaunchAgents").expanduser() / f"{launch_agent_label()}.plist"


def sync_launch_agent_path() -> Path:
    return Path("~/Library/LaunchAgents").expanduser() / f"{sync_launch_agent_label()}.plist"


def dashboard_launch_agent_path() -> Path:
    return Path("~/Library/LaunchAgents").expanduser() / f"{dashboard_launch_agent_label()}.plist"


def build_launch_agent_plist(settings: Settings) -> dict:
    python = str(Path(sys.executable).resolve())
    project_root = Path(__file__).resolve().parents[1]
    return {
        "Label": launch_agent_label(),
        "ProgramArguments": [
            python,
            "-m",
            "wond",
            "monitor",
            "--config",
            str(settings.path),
        ],
        "WorkingDirectory": str(project_root),
        "RunAtLoad": True,
        "KeepAlive": True,
        "EnvironmentVariables": launch_agent_environment(),
    }


def build_sync_launch_agent_plist(settings: Settings) -> dict:
    python = str(Path(sys.executable).resolve())
    project_root = Path(__file__).resolve().parents[1]
    return {
        "Label": sync_launch_agent_label(),
        "ProgramArguments": [
            python,
            "-m",
            "wond",
            "sync-server",
            "--config",
            str(settings.path),
        ],
        "WorkingDirectory": str(project_root),
        "RunAtLoad": True,
        "KeepAlive": True,
        "EnvironmentVariables": launch_agent_environment(),
    }


def build_dashboard_launch_agent_plist(settings: Settings) -> dict:
    python = str(Path(sys.executable).resolve())
    project_root = Path(__file__).resolve().parents[1]
    return {
        "Label": dashboard_launch_agent_label(),
        "ProgramArguments": [
            python,
            "-m",
            "wond",
            "dashboard",
            "--config",
            str(settings.path),
            "--host",
            "127.0.0.1",
            "--port",
            "8787",
        ],
        "WorkingDirectory": str(project_root),
        "RunAtLoad": True,
        "KeepAlive": True,
        "EnvironmentVariables": launch_agent_environment(),
    }


def launch_agent_environment() -> dict[str, str]:
    return {
        "PYTHONUNBUFFERED": "1",
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
    }


def install_launch_agent(settings: Settings) -> Path:
    path = launch_agent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    plist = build_launch_agent_plist(settings)
    path.write_bytes(plistlib.dumps(plist, sort_keys=False))
    return path


def install_sync_launch_agent(settings: Settings) -> Path:
    path = sync_launch_agent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    plist = build_sync_launch_agent_plist(settings)
    path.write_bytes(plistlib.dumps(plist, sort_keys=False))
    return path


def install_dashboard_launch_agent(settings: Settings) -> Path:
    path = dashboard_launch_agent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    plist = build_dashboard_launch_agent_plist(settings)
    path.write_bytes(plistlib.dumps(plist, sort_keys=False))
    return path
