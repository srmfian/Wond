from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .config import Settings
from .observation_filters import visible_observations
from .personal_memory import personal_context_report_lines
from .store import Store
from .timeutil import day_bounds, local_iso


def time_label(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%H:%M")
    except ValueError:
        return value[:16]


def row_metadata(row) -> dict:
    raw = row["metadata"]
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def compact_url(url: str | None) -> str:
    if not url:
        return ""
    return url.split("?", 1)[0][:120]


def compact_text(value: str | None, limit: int = 220) -> str:
    if not value:
        return ""
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "."


def seconds_value(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def row_duration_seconds(row) -> float | None:
    metadata = row_metadata(row)
    explicit = seconds_value(metadata.get("duration_seconds"))
    if explicit is not None:
        return explicit
    if not row["ended_at"]:
        return None
    try:
        start = datetime.fromisoformat(row["observed_at"])
        end = datetime.fromisoformat(row["ended_at"])
    except ValueError:
        return None
    return max(0.0, (end - start).total_seconds())


def duration_label(seconds: float | None) -> str:
    if seconds is None:
        return ""
    rounded = int(seconds)
    hours, remainder = divmod(rounded, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def audio_speaker_names(store: Store, row, audio_analysis: dict) -> list[str]:
    latest = store.speaker_names_for_observation(int(row["id"]))
    names: list[str] = []
    speakers = audio_analysis.get("speakers")
    if isinstance(speakers, list):
        for item in speakers:
            if not isinstance(item, dict):
                continue
            mapped = mapped_speaker(latest, item)
            label = item.get("local_label")
            name = mapped["display_name"] if mapped is not None else item.get("speaker_name")
            if isinstance(name, str) and name.strip() and name not in names:
                names.append(name.strip())

    timeline = audio_analysis.get("audio_timeline") if isinstance(audio_analysis.get("audio_timeline"), dict) else {}
    segments = timeline.get("speech_segments") or []
    for item in segments:
        if not isinstance(item, dict):
            continue
        if item.get("overlap") and isinstance(item.get("overlap_speakers"), list):
            overlap_names = []
            for label in item.get("overlap_speakers") or []:
                mapped = latest.get(speaker_lookup_key(item, label))
                if mapped is None:
                    mapped = latest.get(str(label))
                name = mapped["display_name"] if mapped is not None else label
                if isinstance(name, str) and name.strip():
                    overlap_names.append(name.strip())
            display = " + ".join(overlap_names)
            if display and display not in names:
                names.append(display)
            continue
        if names:
            continue
        mapped = mapped_speaker(latest, item)
        label = item.get("speaker")
        name = mapped["display_name"] if mapped is not None else item.get("speaker_name") or label
        if isinstance(name, str) and name.strip() and name not in names:
            names.append(name.strip())
    return names


def audio_speaker_samples(store: Store, row, audio_analysis: dict) -> list[tuple[str, str]]:
    speakers = audio_analysis.get("speakers")
    if not isinstance(speakers, list):
        return []
    latest = store.speaker_names_for_observation(int(row["id"]))
    samples: list[tuple[str, str]] = []
    for item in speakers:
        if not isinstance(item, dict):
            continue
        mapped = mapped_speaker(latest, item)
        label = item.get("local_label")
        name = mapped["display_name"] if mapped is not None else item.get("speaker_name") or label or "Speaker"
        sample_path = item.get("sample_path")
        if isinstance(sample_path, str) and sample_path.strip():
            samples.append((str(name), sample_path))
    return samples


def mapped_speaker(latest: dict[str, Any], item: dict[str, Any]):
    for key in speaker_lookup_keys(item):
        mapped = latest.get(key)
        if mapped is not None:
            return mapped
    return None


def speaker_lookup_keys(item: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for raw in (item.get("speaker_group_label"), item.get("speaker_local_label"), item.get("local_label"), item.get("speaker")):
        if raw is not None:
            value = str(raw)
            if value and value not in keys:
                keys.append(value)
    scoped = speaker_lookup_key(item, item.get("speaker_local_label") or item.get("local_label") or item.get("speaker"))
    if scoped and scoped not in keys:
        keys.insert(0, scoped)
    return keys


def speaker_lookup_key(item: dict[str, Any], label: Any) -> str:
    scope = str(item.get("speaker_scope") or "").strip()
    raw = str(label or "").strip()
    return f"{scope}:{raw}" if scope and raw else raw


def build_daily_report(settings: Settings, store: Store, day: date) -> str:
    start, end = day_bounds(day, settings.timezone)
    observations = visible_observations(settings, store.observations_between(local_iso(start), local_iso(end)))
    activity = store.activity_between(local_iso(start), local_iso(end))

    by_kind = defaultdict(list)
    for row in observations:
        by_kind[(row["source"], row["kind"])].append(row)

    app_counts = Counter(row["app"] for row in activity if row["app"])
    web_domains = Counter()
    for row in by_kind[("browser", "web_visit")]:
        url = row["url"] or ""
        domain = url.split("/")[2] if "://" in url and len(url.split("/")) > 2 else url
        if domain:
            web_domains[domain] += 1

    lines: list[str] = []
    lines.append(f"# Daily Context - {day.isoformat()}")
    lines.append("")
    lines.append("## Snapshot")
    lines.append(f"- Observations captured: {len(observations)}")
    lines.append(f"- Foreground samples: {len(activity)}")
    if app_counts:
        top_apps = ", ".join(f"{app} ({count})" for app, count in app_counts.most_common(8))
        lines.append(f"- Top apps: {top_apps}")
    if web_domains:
        top_domains = ", ".join(f"{domain} ({count})" for domain, count in web_domains.most_common(8))
        lines.append(f"- Top web domains: {top_domains}")
    lines.append("")

    personal_context = personal_context_report_lines(settings, store)
    if personal_context:
        lines.extend(personal_context)

    if activity:
        lines.append("## App Timeline")
        last_app = None
        first_time = None
        last_time = None
        last_title = None
        for row in activity:
            app = row["app"]
            if app != last_app:
                if last_app:
                    title = f" - {last_title}" if last_title else ""
                    lines.append(f"- {time_label(first_time)}-{time_label(last_time)} {last_app}{title}")
                last_app = app
                first_time = row["sampled_at"]
            last_time = row["sampled_at"]
            last_title = row["window_title"]
        if last_app:
            title = f" - {last_title}" if last_title else ""
            lines.append(f"- {time_label(first_time)}-{time_label(last_time)} {last_app}{title}")
        lines.append("")

    calendar_rows = by_kind[("calendar", "event")]
    if calendar_rows:
        lines.append("## Calendar")
        for row in calendar_rows:
            location = f" @ {row['location']}" if row["location"] else ""
            lines.append(
                f"- {time_label(row['observed_at'])} {row['title'] or '(untitled)'}{location}"
            )
        lines.append("")

    reminder_rows = by_kind[("reminders", "task")]
    if reminder_rows:
        lines.append("## Due Or Open Reminders")
        for row in reminder_rows[:30]:
            list_name = f" [{row['subtitle']}]" if row["subtitle"] else ""
            lines.append(f"- {time_label(row['observed_at'])}{list_name} {row['title']}")
        lines.append("")

    message_rows = by_kind[("messages", "message")]
    if message_rows:
        lines.append("## Messages")
        for row in message_rows[:40]:
            actor = row["actor"] or "unknown"
            direction = "sent" if actor == "me" else f"from {actor}"
            lines.append(f"- {time_label(row['observed_at'])} {direction}: {row['title']}")
        lines.append("")

    mail_rows = by_kind[("apple_mail", "email")]
    if mail_rows:
        lines.append("## Mail")
        for row in mail_rows[:40]:
            actor = f" from {row['actor']}" if row["actor"] else ""
            lines.append(f"- {time_label(row['observed_at'])}{actor}: {row['title']}")
        lines.append("")

    file_rows = by_kind[("filesystem", "file_modified")]
    if file_rows:
        lines.append("## Files Changed")
        for row in file_rows[:60]:
            lines.append(f"- {time_label(row['observed_at'])} {row['title']} ({row['subtitle']})")
        lines.append("")

    web_rows = by_kind[("browser", "web_visit")]
    if web_rows:
        lines.append("## Web Activity")
        for row in web_rows[:80]:
            title = row["title"] or compact_url(row["url"])
            lines.append(f"- {time_label(row['observed_at'])} {title} - {compact_url(row['url'])}")
        lines.append("")

    photo_rows = by_kind[("photos", "photo_location")]
    if photo_rows:
        lines.append("## Photo Location Hints")
        for row in photo_rows[:30]:
            lines.append(f"- {time_label(row['observed_at'])} {row['title']} @ {row['location']}")
        lines.append("")

    audio_rows = by_kind[("mobile", "audio_segment")]
    transcript_rows = by_kind[("mobile", "transcript_segment")]
    location_rows = by_kind[("mobile", "location_sample")]
    bookmark_rows = by_kind[("mobile", "bookmark")]
    if audio_rows or transcript_rows or location_rows or bookmark_rows:
        lines.append("## Mobile Capture")
        if audio_rows:
            total_seconds = sum(row_duration_seconds(row) or 0 for row in audio_rows)
            total = f" ({duration_label(total_seconds)} total)" if total_seconds else ""
            lines.append(f"- Audio segments: {len(audio_rows)}{total}")
            for row in audio_rows[:60]:
                metadata = row_metadata(row)
                audio_analysis = metadata.get("audio_analysis") if isinstance(metadata.get("audio_analysis"), dict) else {}
                duration = duration_label(row_duration_seconds(row))
                label = time_label(row["observed_at"])
                if row["ended_at"]:
                    label += f"-{time_label(row['ended_at'])}"
                if duration:
                    label += f" ({duration})"
                location = f" @ {row['location']}" if row["location"] else ""
                timeline = audio_analysis.get("audio_timeline") if isinstance(audio_analysis.get("audio_timeline"), dict) else {}
                timeline_bits = []
                speech_seconds = seconds_value(timeline.get("speech_seconds"))
                music_seconds = seconds_value(timeline.get("music_or_active_non_speech_seconds"))
                if speech_seconds is not None:
                    timeline_bits.append(f"speech {duration_label(speech_seconds)}")
                if music_seconds is not None and music_seconds > 0:
                    timeline_bits.append(f"music/ambient {duration_label(music_seconds)}")
                speakers = audio_speaker_names(store, row, audio_analysis)
                if speakers:
                    timeline_bits.append(f"speakers {', '.join(speakers[:5])}")
                timeline_label = f" [{', '.join(timeline_bits)}]" if timeline_bits else ""
                summary = audio_analysis.get("summary") or audio_analysis.get("local_summary") or audio_analysis.get("openai_summary")
                if isinstance(summary, str) and summary.strip():
                    detail = f" - Summary: {summary[:220]}"
                elif row["body"]:
                    detail = f" - Transcript: {row['body'][:160]}"
                else:
                    detail = ""
                lines.append(f"  - {label} {row['title'] or 'Audio segment'}{location}{timeline_label}{detail}")
                for speaker_name, sample_path in audio_speaker_samples(store, row, audio_analysis)[:5]:
                    lines.append(f"    - {speaker_name} sample: {sample_path}")
            if len(audio_rows) > 60:
                lines.append(f"  - ... {len(audio_rows) - 60} more audio segments")
        if transcript_rows:
            lines.append(f"- Transcript-only segments: {len(transcript_rows)}")
            for row in transcript_rows[:30]:
                body = f": {row['body'][:180]}" if row["body"] else ""
                lines.append(f"  - {time_label(row['observed_at'])} {row['title'] or 'Transcript'}{body}")
        if bookmark_rows:
            lines.append(f"- Mobile bookmarks: {len(bookmark_rows)}")
            for row in bookmark_rows[:30]:
                location = f" @ {row['location']}" if row["location"] else ""
                body = f": {row['body'][:180]}" if row["body"] else ""
                lines.append(f"  - {time_label(row['observed_at'])} {row['title'] or 'Bookmark'}{location}{body}")
        if location_rows:
            lines.append(f"- Location samples: {len(location_rows)}")
            for row in location_rows[:30]:
                lines.append(f"  - {time_label(row['observed_at'])} {row['location'] or row['title']}")
            if len(location_rows) > 30:
                lines.append(f"  - ... {len(location_rows) - 30} more location samples")
        lines.append("")

    ready_speakers = store.list_speakers_ready_for_review()
    if ready_speakers:
        lines.append("## Speaker Naming Review")
        for speaker in ready_speakers[:8]:
            stats = store.speaker_sample_evidence_stats(int(speaker["id"]))
            confidence = "" if speaker["confidence"] is None else f", confidence {speaker['confidence']:.2f}"
            lines.append(
                f"- Speaker {speaker['id']}: {speaker['display_name']} "
                f"({stats['sample_count']} samples, {stats['observation_count']} recordings, "
                f"{stats['day_count']} days{confidence})"
            )
            for sample in store.list_speaker_samples(int(speaker["id"]))[:3]:
                transcript = f" :: {sample['transcript'][:120]}" if sample["transcript"] else ""
                lines.append(f"  - {sample['sample_path'] or '(no sample)'}{transcript}")
        if len(ready_speakers) > 8:
            lines.append(f"- ... {len(ready_speakers) - 8} more speakers ready for naming")
        lines.append("")

    media_rows = sorted(
        [*by_kind[("local_ai", "media_analysis")], *by_kind[("openai", "media_analysis")]],
        key=lambda row: row["observed_at"],
    )
    if media_rows:
        lines.append("## AI Media Analysis")
        for row in media_rows[:40]:
            metadata = row_metadata(row)
            kind = metadata.get("analysis_kind") or "file"
            backend = metadata.get("analysis_backend") or row["source"]
            path = metadata.get("path") or compact_url(row["url"])
            body = f": {row['body'][:260]}" if row["body"] else ""
            lines.append(f"- {time_label(row['observed_at'])} [{backend}/{kind}] {row['title'] or path}{body}")
        if len(media_rows) > 40:
            lines.append(f"- ... {len(media_rows) - 40} more analyzed files")
        lines.append("")

    error_rows = by_kind[("system", "collector_error")]
    if error_rows:
        lines.append("## Collector Notes")
        for row in error_rows:
            lines.append(f"- {row['title']}: {row['body']}")
        lines.append("")

    lines.append("## Assistant-Ready Handoff")
    lines.append(
        "Use this report as the compact memory for the day: infer what mattered, "
        "ask only about ambiguous gaps, and turn unresolved items into follow-ups."
    )
    lines.append("")
    return "\n".join(lines)


def write_daily_report(settings: Settings, store: Store, day: date) -> Path:
    report = build_daily_report(settings, store, day)
    path = settings.report_dir / f"{day.isoformat()}.md"
    path.write_text(report, encoding="utf-8")
    return path
