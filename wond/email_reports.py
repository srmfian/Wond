from __future__ import annotations

import os
import smtplib
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

from .collectors import collect_all, is_collector_error_result
from .compactor import (
    iso_week_bounds,
    write_daily_compact_summary,
    write_daily_email_digest,
    write_weekly_email_digest,
    write_weekly_summary,
)
from .config import Settings
from .store import Store
from .summarizer import write_daily_report
from .timeutil import day_bounds


@dataclass
class EmailTask:
    period: str
    target_key: str
    summary_date: date
    scheduled_for: datetime
    subject: str
    body_path: Path

    @property
    def delivery_key(self) -> str:
        return f"{self.period}:{self.target_key}"


@dataclass
class EmailResult:
    task: EmailTask
    status: str
    message: str


def email_config_bool(settings: Settings, key: str, default: bool) -> bool:
    value = settings.email_reports.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def email_config_int(settings: Settings, key: str, default: int) -> int:
    try:
        return int(settings.email_reports.get(key, default))
    except (TypeError, ValueError):
        return default


def parse_send_time(value: str) -> time:
    hour_text, minute_text = value.split(":", 1)
    return time(hour=int(hour_text), minute=int(minute_text))


def scheduled_for_period(settings: Settings, now_dt: datetime, period: str) -> datetime | None:
    fallback = str(settings.email_reports.get("send_time", "00:00"))
    send_at = parse_send_time(str(settings.email_reports.get(f"{period}_send_time", fallback)))
    scheduled_today = datetime.combine(now_dt.date(), send_at, tzinfo=now_dt.tzinfo)
    if now_dt < scheduled_today:
        return None
    send_window = email_config_int(settings, "send_window_seconds", 7200)
    if send_window > 0 and (now_dt - scheduled_today).total_seconds() > send_window:
        return None
    return scheduled_today


def recipients(settings: Settings) -> list[str]:
    raw = settings.email_reports.get("to", [])
    if isinstance(raw, str):
        return [item.strip() for item in raw.split(",") if item.strip()]
    return [str(item).strip() for item in raw if str(item).strip()]


def get_smtp_password(settings: Settings) -> str:
    env_name = str(settings.email_reports.get("password_env", "WOND_SMTP_PASSWORD"))
    value = os.environ.get(env_name)
    if value:
        return value.replace(" ", "")

    configured_service = str(settings.email_reports.get("keychain_service", "wond-smtp"))
    account = str(settings.email_reports.get("keychain_account", settings.email_reports.get("smtp_username", "")))
    if not account:
        raise RuntimeError("SMTP account is not configured")

    service_candidates = [
        configured_service,
        str(settings.email_reports.get("smtp_host", "smtp.gmail.com")),
        "smtp.gmail.com",
        "gmail",
        "Gmail",
        account,
    ]
    tried: list[str] = []
    for service in dict.fromkeys(item for item in service_candidates if item):
        tried.append(service)
        proc = subprocess.run(
            ["security", "find-generic-password", "-w", "-s", service, "-a", account],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        if proc.returncode == 0:
            password = proc.stdout.strip().replace(" ", "")
            if password:
                return password
        proc = subprocess.run(
            ["security", "find-internet-password", "-w", "-s", service, "-a", account],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        if proc.returncode == 0:
            password = proc.stdout.strip().replace(" ", "")
            if password:
                return password
    raise RuntimeError(
        f"SMTP password not found in env {env_name} or Keychain services={tried} account={account}"
    )


def send_email(settings: Settings, subject: str, body: str) -> None:
    sender = str(settings.email_reports.get("from", ""))
    username = str(settings.email_reports.get("smtp_username", sender))
    to_addrs = recipients(settings)
    if not sender or not username or not to_addrs:
        raise RuntimeError("Email sender, SMTP username, or recipients are not configured")

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = subject
    msg.set_content(body)

    host = str(settings.email_reports.get("smtp_host", "smtp.gmail.com"))
    port = email_config_int(settings, "smtp_port", 587)
    password = get_smtp_password(settings)
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(username, password)
        smtp.send_message(msg)


def collect_day(settings: Settings, store: Store, target_day: date) -> None:
    start, end = day_bounds(target_day, settings.timezone)
    for name, observations in collect_all(settings, start, end).items():
        run_id = store.start_run(f"email_prepare:{name}")
        try:
            count = store.upsert_observations(observations)
            if is_collector_error_result(name, observations):
                store.finish_run(run_id, "error", observations[0].body or observations[0].title or "collector_error")
                continue
            else:
                store.clear_collector_error(name, target_day)
            store.finish_run(run_id, "ok", f"{count} observations")
        except Exception as exc:
            store.finish_run(run_id, "error", str(exc))


def prepare_daily_task(settings: Settings, store: Store, summary_day: date, scheduled_for: datetime) -> EmailTask:
    collect_day(settings, store, summary_day)
    report_path = write_daily_report(settings, store, summary_day)
    write_daily_compact_summary(settings, store, summary_day)
    body_path = write_daily_email_digest(settings, store, summary_day, source_path=report_path)
    subject = f"[Wond] Daily Highlights - {summary_day.isoformat()}"
    return EmailTask("daily", summary_day.isoformat(), summary_day, scheduled_for, subject, body_path)


def prepare_weekly_task(settings: Settings, store: Store, week_day: date, scheduled_for: datetime) -> EmailTask:
    _start, _end, week_key = iso_week_bounds(week_day)
    weekly_path = write_weekly_summary(settings, store, week_day)
    body_path = write_weekly_email_digest(settings, store, week_day, source_path=weekly_path)
    subject = f"[Wond] Weekly Highlights - {week_key}"
    return EmailTask("weekly", week_key, week_day, scheduled_for, subject, body_path)


def should_retry(settings: Settings, store: Store, delivery_key: str, now_dt: datetime) -> bool:
    if store.email_delivery_success(delivery_key):
        return False
    latest = store.latest_email_delivery_attempt(delivery_key)
    if not latest:
        return True
    retry_after = email_config_int(settings, "retry_after_seconds", 3600)
    try:
        attempted_at = datetime.fromisoformat(latest["attempted_at"])
    except ValueError:
        return True
    if attempted_at.tzinfo is None:
        attempted_at = attempted_at.replace(tzinfo=now_dt.tzinfo)
    return (now_dt - attempted_at).total_seconds() >= retry_after


def due_tasks(settings: Settings, store: Store, now_dt: datetime) -> list[EmailTask]:
    if not email_config_bool(settings, "enabled", True):
        return []

    tasks: list[EmailTask] = []
    if email_config_bool(settings, "daily", True):
        scheduled_daily = scheduled_for_period(settings, now_dt, "daily")
        if scheduled_daily:
            summary_day = now_dt.date() - timedelta(days=1)
            key = f"daily:{summary_day.isoformat()}"
            if should_retry(settings, store, key, now_dt):
                tasks.append(prepare_daily_task(settings, store, summary_day, scheduled_daily))

    if email_config_bool(settings, "weekly", True) and now_dt.weekday() == 0:
        scheduled_weekly = scheduled_for_period(settings, now_dt, "weekly")
        if scheduled_weekly:
            week_day = now_dt.date() - timedelta(days=1)
            _start, _end, week_key = iso_week_bounds(week_day)
            key = f"weekly:{week_key}"
            if should_retry(settings, store, key, now_dt):
                tasks.append(prepare_weekly_task(settings, store, week_day, scheduled_weekly))
    return tasks


def send_task(settings: Settings, store: Store, task: EmailTask, dry_run: bool = False) -> EmailResult:
    body = task.body_path.read_text(encoding="utf-8")
    if dry_run:
        return EmailResult(task, "dry-run", f"Would send {task.body_path}")
    try:
        send_email(settings, task.subject, body)
        status = "sent"
        message = f"Sent {task.body_path}"
    except Exception as exc:
        status = "error"
        message = str(exc)
    store.record_email_delivery(
        task.delivery_key,
        task.period,
        task.target_key,
        task.scheduled_for.isoformat(timespec="seconds"),
        status,
        task.subject,
        message,
    )
    return EmailResult(task, status, message)


def send_due_email_reports(
    settings: Settings,
    store: Store,
    now_dt: datetime | None = None,
    dry_run: bool = False,
) -> list[EmailResult]:
    if now_dt is None:
        now_dt = datetime.now(ZoneInfo(settings.timezone))
    return [send_task(settings, store, task, dry_run=dry_run) for task in due_tasks(settings, store, now_dt)]


def manual_email_task(settings: Settings, store: Store, period: str, target_day: date) -> EmailTask:
    scheduled_for = datetime.now(ZoneInfo(settings.timezone))
    if period == "daily":
        return prepare_daily_task(settings, store, target_day, scheduled_for)
    if period == "weekly":
        return prepare_weekly_task(settings, store, target_day, scheduled_for)
    raise ValueError(f"Unsupported email period: {period}")
