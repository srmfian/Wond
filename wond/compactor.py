from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import Settings
from .observation_filters import visible_observations
from .openai_analysis import summarize_text
from .store import Store
from .timeutil import day_bounds, local_iso


def parse_metadata(row) -> dict:
    raw = row["metadata"]
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def parse_dt(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def time_label(value: str) -> str:
    parsed = parse_dt(value)
    if not parsed:
        return value[:16]
    return parsed.strftime("%H:%M")


def compact_text(value: str | None, limit: int = 120) -> str:
    if not value:
        return ""
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "."


def domain_from_url(url: str | None) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    return parsed.netloc or parsed.path.split("/", 1)[0]


def iso_week_bounds(day: date) -> tuple[date, date, str]:
    iso = day.isocalendar()
    start = day - timedelta(days=day.weekday())
    end = start + timedelta(days=7)
    return start, end, f"{iso.year}-W{iso.week:02d}"


def month_bounds(day: date) -> tuple[date, date, str]:
    start = day.replace(day=1)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end, f"{start.year}-{start.month:02d}"


def summary_path(settings: Settings, period: str, key: str) -> Path:
    folder = settings.summary_dir / period
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{key}.md"


def email_digest_path(settings: Settings, period: str, key: str) -> Path:
    folder = settings.summary_dir / "email"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{period}-{key}.md"


def config_bool(values: dict[str, Any], key: str, default: bool) -> bool:
    value = values.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def config_int(values: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(values.get(key, default))
    except (TypeError, ValueError):
        return default


def clip_digest_source(settings: Settings, text: str) -> str:
    max_chars = config_int(settings.email_reports, "highlight_source_max_chars", 30000)
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n\n[Source clipped for the email highlight model.]"


def clean_ai_digest(text: str, fallback_title: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return f"# {fallback_title}\n\n- No highlights were generated."
    return cleaned


def ai_error_digest(title: str, source_path: Path | None, exc: Exception) -> str:
    source_line = f"\n- Source report: {source_path}" if source_path else ""
    return (
        f"# {title}\n\n"
        "- AI highlight generation failed, so this email is not sending the full raw summary.\n"
        f"- Error: {exc}"
        f"{source_line}\n"
    )


def daily_highlight_prompt(day: date, item_count: int) -> str:
    return (
        "You are preparing a concise personal daily email in Chinese.\n"
        f"The source report covers {day.isoformat()}.\n"
        "Select only the previous day's most important, most interesting, or most worth-remembering items. "
        "Let the model decide what deserves attention; do not summarize every section.\n"
        "Ignore routine telemetry, repeated file/app/browser counts, and raw collection stats unless they explain why something mattered.\n"
        "Include concrete names, projects, decisions, places, times, or follow-ups when they are supported by the source.\n"
        "Do not invent details.\n\n"
        "Write Markdown with this shape:\n"
        f"# Daily Highlights - {day.isoformat()}\n"
        "## 最重要\n"
        f"- 3 to {item_count} bullets, ranked by importance\n"
        "## 精彩/值得回看\n"
        "- 0 to 4 bullets for notable conversations, discoveries, media, ideas, or moments\n"
        "## 可能需要跟进\n"
        "- 0 to 4 bullets, only if the source implies action or unresolved work\n\n"
        "If the day was mostly routine, say that briefly and keep the whole email short."
    )


def weekly_highlight_prompt(start_day: date, end_day: date, week_key: str, item_count: int) -> str:
    return (
        "You are preparing a concise personal weekly email in Chinese.\n"
        f"The source summaries cover {start_day.isoformat()} to {(end_day - timedelta(days=1)).isoformat()} ({week_key}).\n"
        "Select only the week's most important, most interesting, or most worth-remembering items. "
        "Let the model decide what deserves attention; do not summarize every day mechanically.\n"
        "Prefer themes, decisions, meaningful conversations, projects, places, creative sparks, and follow-ups. "
        "Ignore routine telemetry and repeated counts unless they reveal a meaningful pattern.\n"
        "Do not invent details.\n\n"
        "Write Markdown with this shape:\n"
        f"# Weekly Highlights - {week_key}\n"
        "## 本周最重要\n"
        f"- 4 to {item_count} bullets, ranked by importance\n"
        "## 精彩/值得回看\n"
        "- 0 to 6 bullets for notable conversations, discoveries, media, ideas, or moments\n"
        "## 下周可跟进\n"
        "- 0 to 6 bullets, only if the source implies action or unresolved work\n\n"
        "If the week was mostly routine, say that briefly and keep the whole email short."
    )


def rows_for_days(settings: Settings, store: Store, start_day: date, end_day: date):
    start, _ = day_bounds(start_day, settings.timezone)
    end, _ = day_bounds(end_day, settings.timezone)
    return (
        visible_observations(settings, store.observations_between(local_iso(start), local_iso(end))),
        store.activity_between(local_iso(start), local_iso(end)),
    )


def rows_for_day(settings: Settings, store: Store, day: date):
    start, end = day_bounds(day, settings.timezone)
    return (
        visible_observations(settings, store.observations_between(local_iso(start), local_iso(end))),
        store.activity_between(local_iso(start), local_iso(end)),
    )


def group_by_source_kind(observations) -> dict[tuple[str, str], list]:
    grouped: dict[tuple[str, str], list] = defaultdict(list)
    for row in observations:
        grouped[(row["source"], row["kind"])].append(row)
    return grouped


def activity_lines(activity, limit: int = 8) -> list[str]:
    app_counts = Counter(row["app"] for row in activity if row["app"])
    lines: list[str] = []
    if app_counts:
        lines.append("- Top apps: " + ", ".join(f"{app} ({count})" for app, count in app_counts.most_common(limit)))
    title_counts = Counter(
        compact_text(row["window_title"], 70)
        for row in activity
        if row["window_title"] and row["window_title"] != row["app"]
    )
    if title_counts:
        lines.append("- Frequent windows: " + ", ".join(f"{title} ({count})" for title, count in title_counts.most_common(5)))
    return lines


def web_lines(grouped, limit: int = 8) -> list[str]:
    domains = Counter(domain_from_url(row["url"]) for row in grouped[("browser", "web_visit")])
    domains.pop("", None)
    if not domains:
        return []
    return ["- Top web domains: " + ", ".join(f"{domain} ({count})" for domain, count in domains.most_common(limit))]


def event_lines(rows, limit: int = 12) -> list[str]:
    lines: list[str] = []
    for row in rows[:limit]:
        location = f" @ {row['location']}" if row["location"] else ""
        lines.append(f"- {time_label(row['observed_at'])} {compact_text(row['title'] or '(untitled)', 120)}{location}")
    if len(rows) > limit:
        lines.append(f"- ... {len(rows) - limit} more")
    return lines


def communication_lines(grouped) -> list[str]:
    lines: list[str] = []
    counts = {
        "Mail": len(grouped[("apple_mail", "email")]),
        "iMessage": len(grouped[("messages", "message")]),
        "Mobile audio": len(grouped[("mobile", "audio_segment")]),
        "Mobile bookmarks": len(grouped[("mobile", "bookmark")]),
    }
    active = [f"{name} ({count})" for name, count in counts.items() if count]
    if active:
        lines.append("- Communication/activity counts: " + ", ".join(active))

    actors = Counter()
    for row in grouped[("apple_mail", "email")]:
        if row["actor"]:
            actors[row["actor"]] += 1
    for row in grouped[("messages", "message")]:
        if row["actor"] and row["actor"] != "me":
            actors[row["actor"]] += 1
    if actors:
        lines.append("- Frequent people/senders: " + ", ".join(f"{compact_text(actor, 50)} ({count})" for actor, count in actors.most_common(8)))
    return lines


def artifact_lines(grouped, limit: int = 10) -> list[str]:
    lines: list[str] = []
    files = grouped[("filesystem", "file_modified")]
    if files:
        lines.append("- Files changed: " + ", ".join(compact_text(row["title"], 50) for row in files[:limit]))
    return lines


def mobile_lines(grouped, limit: int = 8) -> list[str]:
    lines: list[str] = []
    bookmarks = grouped[("mobile", "bookmark")]
    transcripts = grouped[("mobile", "transcript_segment")]
    audio = grouped[("mobile", "audio_segment")]
    locations = grouped[("mobile", "location_sample")]
    if audio:
        lines.append(f"- Audio segments captured: {len(audio)}")
    if bookmarks:
        lines.append("- Bookmarks: " + ", ".join(compact_text(row["title"] or row["body"], 70) for row in bookmarks[:limit]))
    if transcripts:
        lines.append("- Transcript hints: " + ", ".join(compact_text(row["body"] or row["title"], 90) for row in transcripts[:limit]))
    if locations:
        location_counts = Counter(row["location"] for row in locations if row["location"])
        if location_counts:
            lines.append("- Location hints: " + ", ".join(f"{loc} ({count})" for loc, count in location_counts.most_common(limit)))
    return lines


def source_count_line(observations, activity) -> str:
    source_counts = Counter(row["source"] for row in observations)
    parts = [f"{source} ({count})" for source, count in source_counts.most_common()]
    if activity:
        parts.append(f"app_samples ({len(activity)})")
    return "- Sources: " + (", ".join(parts) if parts else "none")


def build_daily_compact_summary(settings: Settings, store: Store, day: date) -> str:
    observations, activity = rows_for_day(settings, store, day)
    grouped = group_by_source_kind(observations)
    lines = [
        f"# Daily Long-Term Summary - {day.isoformat()}",
        "",
        "## Snapshot",
        source_count_line(observations, activity),
    ]
    lines.extend(activity_lines(activity))
    lines.extend(web_lines(grouped))
    lines.append("")

    calendar = grouped[("calendar", "event")]
    if calendar:
        lines.append("## Calendar")
        lines.extend(event_lines(calendar, 10))
        lines.append("")

    comms = communication_lines(grouped)
    if comms:
        lines.append("## Communication")
        lines.extend(comms)
        lines.append("")

    artifacts = artifact_lines(grouped)
    if artifacts:
        lines.append("## Artifacts")
        lines.extend(artifacts)
        lines.append("")

    mobile = mobile_lines(grouped)
    if mobile:
        lines.append("## Mobile")
        lines.extend(mobile)
        lines.append("")

    errors = grouped[("system", "collector_error")]
    if errors:
        lines.append("## Gaps")
        for row in errors[:8]:
            lines.append(f"- {row['title']}: {compact_text(row['body'], 160)}")
        lines.append("")

    lines.append("## Long-Term Memory")
    lines.append("- Keep this as the compact index for the day; use the detailed report or SQLite only when more detail is needed.")
    lines.append("")
    return "\n".join(lines)


def build_period_summary(settings: Settings, store: Store, start_day: date, end_day: date, label: str) -> str:
    observations, activity = rows_for_days(settings, store, start_day, end_day)
    grouped = group_by_source_kind(observations)
    by_day = Counter()
    for row in observations:
        parsed = parse_dt(row["observed_at"])
        if parsed:
            by_day[parsed.date().isoformat()] += 1
    lines = [
        f"# {label} Long-Term Summary - {start_day.isoformat()} to {(end_day - timedelta(days=1)).isoformat()}",
        "",
        "## Snapshot",
        source_count_line(observations, activity),
    ]
    if by_day:
        lines.append("- Daily volume: " + ", ".join(f"{day} ({count})" for day, count in sorted(by_day.items())))
    lines.extend(activity_lines(activity, 10))
    lines.extend(web_lines(grouped, 10))
    lines.append("")

    calendar = grouped[("calendar", "event")]
    if calendar:
        lines.append("## Calendar")
        lines.extend(event_lines(calendar, 20))
        lines.append("")

    comms = communication_lines(grouped)
    if comms:
        lines.append("## Communication")
        lines.extend(comms)
        lines.append("")

    artifacts = artifact_lines(grouped, 15)
    if artifacts:
        lines.append("## Outputs And Artifacts")
        lines.extend(artifacts)
        lines.append("")

    mobile = mobile_lines(grouped, 12)
    if mobile:
        lines.append("## Mobile")
        lines.extend(mobile)
        lines.append("")

    lines.append("## Long-Term Memory")
    lines.append("- This period summary intentionally omits raw logs and repetitive files; use it to recover themes, people, projects, and activity clusters.")
    lines.append("")
    return "\n".join(lines)


def write_daily_compact_summary(settings: Settings, store: Store, day: date) -> Path:
    path = summary_path(settings, "daily", day.isoformat())
    path.write_text(build_daily_compact_summary(settings, store, day), encoding="utf-8")
    return path


def write_weekly_summary(settings: Settings, store: Store, day: date) -> Path:
    start, end, key = iso_week_bounds(day)
    path = summary_path(settings, "weekly", key)
    path.write_text(build_period_summary(settings, store, start, end, "Weekly"), encoding="utf-8")
    return path


def build_weekly_email_source(settings: Settings, store: Store, start_day: date, end_day: date, weekly_path: Path) -> str:
    parts = [weekly_path.read_text(encoding="utf-8")]
    current = start_day
    while current < end_day:
        daily_path = summary_path(settings, "daily", current.isoformat())
        if not daily_path.exists():
            daily_path.write_text(build_daily_compact_summary(settings, store, current), encoding="utf-8")
        parts.append(daily_path.read_text(encoding="utf-8"))
        current += timedelta(days=1)
    return "\n\n---\n\n".join(parts)


def write_daily_email_digest(
    settings: Settings,
    store: Store,
    day: date,
    *,
    source_path: Path | None = None,
) -> Path:
    if not config_bool(settings.email_reports, "ai_highlights", True):
        return write_daily_compact_summary(settings, store, day)

    path = email_digest_path(settings, "daily", day.isoformat())
    source = source_path.read_text(encoding="utf-8") if source_path and source_path.exists() else build_daily_compact_summary(settings, store, day)
    item_count = config_int(settings.email_reports, "daily_highlight_items", 6)
    title = f"Daily Highlights - {day.isoformat()}"
    try:
        digest = summarize_text(
            settings,
            clip_digest_source(settings, source),
            prompt=daily_highlight_prompt(day, item_count),
            label=f"Source daily report for {day.isoformat()}",
        )
        path.write_text(clean_ai_digest(digest, title), encoding="utf-8")
    except Exception as exc:
        path.write_text(ai_error_digest(title, source_path, exc), encoding="utf-8")
    return path


def write_weekly_email_digest(
    settings: Settings,
    store: Store,
    day: date,
    *,
    source_path: Path | None = None,
) -> Path:
    if not config_bool(settings.email_reports, "ai_highlights", True):
        return write_weekly_summary(settings, store, day)

    start, end, key = iso_week_bounds(day)
    weekly_path = source_path or write_weekly_summary(settings, store, day)
    path = email_digest_path(settings, "weekly", key)
    item_count = config_int(settings.email_reports, "weekly_highlight_items", 10)
    title = f"Weekly Highlights - {key}"
    try:
        source = build_weekly_email_source(settings, store, start, end, weekly_path)
        digest = summarize_text(
            settings,
            clip_digest_source(settings, source),
            prompt=weekly_highlight_prompt(start, end, key, item_count),
            label=f"Source weekly summaries for {key}",
        )
        path.write_text(clean_ai_digest(digest, title), encoding="utf-8")
    except Exception as exc:
        path.write_text(ai_error_digest(title, weekly_path, exc), encoding="utf-8")
    return path


def write_monthly_summary(settings: Settings, store: Store, day: date) -> Path:
    start, end, key = month_bounds(day)
    path = summary_path(settings, "monthly", key)
    path.write_text(build_period_summary(settings, store, start, end, "Monthly"), encoding="utf-8")
    return path


def write_all_compact_summaries(settings: Settings, store: Store, day: date) -> list[Path]:
    return [
        write_daily_compact_summary(settings, store, day),
        write_weekly_summary(settings, store, day),
        write_monthly_summary(settings, store, day),
    ]
