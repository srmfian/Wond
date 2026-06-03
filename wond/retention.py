from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .config import Settings
from .store import Store
from .timeutil import day_bounds, local_iso


@dataclass
class RetentionResult:
    dry_run: bool
    observation_cutoff: date
    activity_cutoff: date
    reports_cutoff: date
    collector_runs_cutoff: date
    deleted_observations: int = 0
    deleted_activity_samples: int = 0
    deleted_collector_runs: int = 0
    deleted_reports: int = 0
    trimmed_logs: int = 0
    skipped_days: list[str] = field(default_factory=list)
    vacuumed: bool = False

    def lines(self) -> list[str]:
        mode = "dry-run" if self.dry_run else "applied"
        rows = [
            f"Retention {mode}",
            f"- Raw observations before {self.observation_cutoff.isoformat()}: {self.deleted_observations}",
            f"- Activity samples before {self.activity_cutoff.isoformat()}: {self.deleted_activity_samples}",
            f"- Collector runs before {self.collector_runs_cutoff.isoformat()}: {self.deleted_collector_runs}",
            f"- Detailed reports before {self.reports_cutoff.isoformat()}: {self.deleted_reports}",
            f"- Trimmed log files: {self.trimmed_logs}",
        ]
        if self.skipped_days:
            rows.append("- Skipped days without daily summaries: " + ", ".join(self.skipped_days[:20]))
            if len(self.skipped_days) > 20:
                rows.append(f"- ... {len(self.skipped_days) - 20} more skipped days")
        if self.vacuumed:
            rows.append("- SQLite vacuum/checkpoint completed")
        return rows


def retention_int(settings: Settings, key: str, default: int) -> int:
    value = settings.retention.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def retention_bool(settings: Settings, key: str, default: bool) -> bool:
    value = settings.retention.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def daily_summary_exists(settings: Settings, day: str) -> bool:
    return (settings.summary_dir / "daily" / f"{day}.md").exists()


def report_day(path: Path) -> date | None:
    if path.suffix != ".md":
        return None
    try:
        return date.fromisoformat(path.stem)
    except ValueError:
        return None


def prune_table_days(
    settings: Settings,
    store: Store,
    days: list[str],
    dry_run: bool,
    table: str,
    require_summary: bool,
) -> tuple[int, list[str]]:
    deleted = 0
    skipped: list[str] = []
    for day in days:
        if require_summary and not daily_summary_exists(settings, day):
            skipped.append(day)
            continue
        if table == "observations":
            count = store.count_observations_for_day(day)
            if not dry_run:
                count = store.delete_observations_for_day(day)
        else:
            count = store.count_activity_for_day(day)
            if not dry_run:
                count = store.delete_activity_for_day(day)
        deleted += count
    return deleted, skipped


def prune_reports(settings: Settings, cutoff: date, dry_run: bool) -> int:
    deleted = 0
    if not settings.report_dir.exists():
        return 0
    for path in settings.report_dir.glob("*.md"):
        day = report_day(path)
        if not day or day >= cutoff:
            continue
        deleted += 1
        if not dry_run:
            path.unlink(missing_ok=True)
    return deleted


def trim_logs(settings: Settings, dry_run: bool) -> int:
    max_mb = retention_int(settings, "agent_logs_max_mb", 10)
    if max_mb <= 0:
        return 0
    max_bytes = max_mb * 1024 * 1024
    trimmed = 0
    for path in settings.log_dir.glob("*.log"):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size <= max_bytes:
            continue
        trimmed += 1
        if dry_run:
            continue
        keep_bytes = max_bytes // 2
        with path.open("rb") as handle:
            handle.seek(max(0, size - keep_bytes))
            tail = handle.read()
        path.write_bytes(b"[log trimmed by Wond retention]\n" + tail)
    return trimmed


def run_retention(settings: Settings, store: Store, today: date, dry_run: bool = False) -> RetentionResult:
    raw_days = retention_int(settings, "raw_observations_days", 180)
    activity_days = retention_int(settings, "activity_samples_days", 180)
    reports_days = retention_int(settings, "detailed_reports_days", 180)
    runs_days = retention_int(settings, "collector_runs_days", 45)
    require_summary = retention_bool(settings, "require_daily_summary_before_prune", True)

    observation_cutoff = today - timedelta(days=raw_days)
    activity_cutoff = today - timedelta(days=activity_days)
    reports_cutoff = today - timedelta(days=reports_days)
    runs_cutoff = today - timedelta(days=runs_days)

    result = RetentionResult(
        dry_run=dry_run,
        observation_cutoff=observation_cutoff,
        activity_cutoff=activity_cutoff,
        reports_cutoff=reports_cutoff,
        collector_runs_cutoff=runs_cutoff,
    )

    observation_days = store.observation_dates_before(observation_cutoff.isoformat())
    result.deleted_observations, skipped_obs = prune_table_days(
        settings, store, observation_days, dry_run, "observations", require_summary
    )

    activity_days_to_prune = store.activity_dates_before(activity_cutoff.isoformat())
    result.deleted_activity_samples, skipped_activity = prune_table_days(
        settings, store, activity_days_to_prune, dry_run, "activity", require_summary
    )
    result.skipped_days = sorted(set(skipped_obs + skipped_activity))

    cutoff_start, _ = day_bounds(runs_cutoff, settings.timezone)
    cutoff_iso = local_iso(cutoff_start)
    result.deleted_collector_runs = store.count_collector_runs_before(cutoff_iso)
    if not dry_run:
        result.deleted_collector_runs = store.delete_collector_runs_before(cutoff_iso)

    result.deleted_reports = prune_reports(settings, reports_cutoff, dry_run)
    result.trimmed_logs = trim_logs(settings, dry_run)

    rows_deleted = result.deleted_observations + result.deleted_activity_samples + result.deleted_collector_runs
    if not dry_run and rows_deleted and retention_bool(settings, "vacuum_after_prune", True):
        store.checkpoint_and_vacuum()
        result.vacuumed = True
    return result
