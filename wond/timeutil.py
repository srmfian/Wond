from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def now(tz_name: str) -> datetime:
    return datetime.now(ZoneInfo(tz_name))


def parse_day(value: str | None, tz_name: str) -> date:
    today = now(tz_name).date()
    if not value or value == "today":
        return today
    if value == "yesterday":
        return today - timedelta(days=1)
    return date.fromisoformat(value)


def day_bounds(day: date, tz_name: str) -> tuple[datetime, datetime]:
    tz = ZoneInfo(tz_name)
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    return start, end


def utc_iso(dt: datetime | None = None) -> str:
    if dt is None:
        dt = datetime.now().astimezone()
    return dt.astimezone().isoformat(timespec="seconds")


def local_iso(dt: datetime) -> str:
    return dt.astimezone().isoformat(timespec="seconds")


def parse_external_iso(value: str | None, tz_name: str) -> str | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(tz_name))
    return parsed.astimezone(ZoneInfo(tz_name)).isoformat(timespec="seconds")


def from_timestamp(ts: float, tz_name: str) -> datetime:
    return datetime.fromtimestamp(ts, ZoneInfo(tz_name))


def chrome_time_to_datetime(value: int, tz_name: str) -> datetime:
    unix_seconds = value / 1_000_000 - 11_644_473_600
    return from_timestamp(unix_seconds, tz_name)


def safari_time_to_datetime(value: float, tz_name: str) -> datetime:
    unix_seconds = value + 978_307_200
    return from_timestamp(unix_seconds, tz_name)


def apple_epoch_to_datetime(value: int | float, tz_name: str) -> datetime:
    raw = float(value)
    if raw > 10_000_000_000_000_000:
        seconds = raw / 1_000_000_000
    elif raw > 10_000_000_000_000:
        seconds = raw / 1_000_000
    elif raw > 10_000_000_000:
        seconds = raw / 1_000
    else:
        seconds = raw
    return from_timestamp(seconds + 978_307_200, tz_name)
