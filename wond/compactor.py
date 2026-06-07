from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import Settings
from .observation_filters import visible_observations
from .openai_analysis import local_text_model, summarize_text
from .personal_memory import personal_context_report_lines
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


def config_str(values: dict[str, Any], key: str, default: str = "") -> str:
    value = values.get(key, default)
    return str(value).strip() if value is not None else default


def clip_digest_source(settings: Settings, text: str) -> str:
    max_chars = config_int(settings.email_reports, "highlight_source_max_chars", 30000)
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n\n[Source clipped for the email highlight model.]"


def email_digest_timeout_seconds(settings: Settings) -> int | None:
    value = config_int(settings.email_reports, "ollama_timeout_seconds", 3600)
    return value if value > 0 else None


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


ASSISTANT_SAFETY_CONTRACT = (
    "Safety and evidence rules:\n"
    "- Do not diagnose health, infer private intent, or judge relationship quality without explicit evidence.\n"
    "- For relationship, mood, and health/life-rhythm reminders, use cautious phrasing appropriate to the output language.\n"
    "- Every proactive reminder should be grounded in a source signal: a person, conversation, file, calendar item, place, time, or repeated pattern.\n"
    "- If a section has no clear evidence, write only the configured no-evidence sentence for that language.\n"
    "- Keep suggestions small and actionable; avoid generic motivational advice.\n"
)


EMAIL_LANGUAGE_COPY: dict[str, dict[str, Any]] = {
    "en": {
        "name": "English",
        "cautious": "possibly, appears, worth confirming",
        "none": "No clear reminder.",
        "daily_title": "Daily Assistant Brief - {date}",
        "weekly_title": "Weekly Assistant Brief - {week_key}",
        "daily_sections": [
            ("Today's main thread", f"2 to {{item_count}} bullets, ranked by importance; include the most meaningful events, decisions, places, or work"),
            ("Proactive reminders", "1 to 3 bullets for the highest-leverage things the user should notice or do next"),
            ("Relationship reminders", "0 to 4 bullets about people to reply to, thank, comfort, clarify with, or follow up with; mention the evidence signal"),
            ("Health/life-rhythm reminders", "0 to 4 bullets about sleep, late work, rest, movement, meals, voice/fatigue, or stress signals; no medical claims"),
            ("Unfinished commitments and follow-ups", "0 to 4 bullets for promised actions, unresolved tasks, missing replies, deadlines, or open loops"),
            ("Tomorrow watchlist", "0 to 3 bullets for meetings, travel, preparation, likely conflicts, or things worth doing before tomorrow gets busy"),
            ("Ideas worth saving", "0 to 3 bullets for durable ideas, decisions, preferences, or questions worth remembering"),
            ("One-sentence advice", "Exactly one practical, specific recommendation for tomorrow"),
        ],
        "weekly_sections": [
            ("Week's main thread", "3 to {item_count} bullets, ranked by importance; focus on themes, decisions, people, and meaningful progress"),
            ("Proactive reminders", "1 to 4 bullets for the highest-leverage reminders or course corrections"),
            ("Relationship map", "0 to 6 bullets about important people, interaction changes, owed replies, appreciation, tension, or reconnection opportunities"),
            ("Health and rhythm trends", "0 to 5 bullets about sleep/late work, recovery, movement, meals, stress, fatigue, or repeated timing patterns; no medical claims"),
            ("Repeated stressors", "0 to 5 bullets for repeated projects, contexts, decisions, or situations that seem to drain attention"),
            ("Unfinished commitments and next-week follow-up", "0 to 6 bullets for promises, unresolved tasks, pending replies, deadlines, or preparation needs"),
            ("Important but neglected", "0 to 4 bullets for health, relationships, admin, learning, finance, maintenance, or long-term goals that got crowded out"),
            ("Next-week watchlist", "0 to 4 bullets for likely conflicts, deadlines, preparation, travel, or schedule risks"),
            ("One-sentence advice", "Exactly one practical, specific recommendation for next week"),
        ],
    },
    "zh": {
        "name": "Chinese",
        "cautious": "可能, 看起来, 值得确认",
        "none": "暂无明确提醒。",
        "daily_title": "每日主动简报 - {date}",
        "weekly_title": "每周主动简报 - {week_key}",
        "daily_sections": [
            ("今日主线", "2 到 {item_count} 条，按重要性排序；包括最有意义的事件、决定、地点或工作"),
            ("主动提醒", "1 到 3 条，提醒用户最值得注意或接下来要做的事"),
            ("关系提醒", "0 到 4 条，关于需要回复、感谢、安慰、澄清或跟进的人；说明证据信号"),
            ("健康/节律提醒", "0 到 4 条，关于睡眠、深夜工作、休息、运动、饮食、声音/疲劳或压力信号；不要做医学判断"),
            ("未完成承诺与待跟进", "0 到 4 条，关于已承诺事项、未解决任务、欠回复、截止日期或 open loop"),
            ("明日预警", "0 到 3 条，关于会议、出行、准备、潜在冲突或明天忙起来前值得先做的事"),
            ("值得保存的想法", "0 到 3 条，关于值得长期记住的想法、决定、偏好或问题"),
            ("一句话建议", "只能有一条，给明天的具体、实用建议"),
        ],
        "weekly_sections": [
            ("本周主线", "3 到 {item_count} 条，按重要性排序；聚焦主题、决定、人和有意义的进展"),
            ("主动提醒", "1 到 4 条，提醒用户最有杠杆的事项或需要修正的模式"),
            ("关系地图", "0 到 6 条，关于重要的人、互动变化、欠回复、感谢、紧张关系或重新联系机会"),
            ("健康与节律趋势", "0 到 5 条，关于睡眠/深夜工作、恢复、运动、饮食、压力、疲劳或重复时间模式；不要做医学判断"),
            ("反复出现的压力源", "0 到 5 条，关于反复消耗注意力的项目、场景、决定或处境"),
            ("未完成承诺与下周跟进", "0 到 6 条，关于承诺、未解决任务、待回复、截止日期或准备需求"),
            ("被忽略但重要的事", "0 到 4 条，关于被挤掉的健康、人际、行政、学习、财务、维护或长期目标"),
            ("下周预警", "0 到 4 条，关于潜在冲突、截止日期、准备、出行或日程风险"),
            ("一句话建议", "只能有一条，给下周的具体、实用建议"),
        ],
    },
    "ja": {
        "name": "Japanese",
        "cautious": "可能性があります, ように見えます, 確認するとよさそうです",
        "none": "明確なリマインダーはありません。",
        "daily_title": "デイリーアシスタントブリーフ - {date}",
        "weekly_title": "週間アシスタントブリーフ - {week_key}",
        "daily_sections": [
            ("今日の主軸", "重要度順に2から{item_count}項目。意味のある出来事、判断、場所、仕事を含める"),
            ("先回りリマインダー", "ユーザーが次に気づくべき、または行うべき重要事項を1から3項目"),
            ("人間関係のリマインダー", "返信、感謝、気遣い、確認、フォローが必要そうな相手を0から4項目。根拠となる信号も書く"),
            ("健康/生活リズムのリマインダー", "睡眠、夜遅い作業、休息、運動、食事、声/疲労、ストレスの信号を0から4項目。医学的判断はしない"),
            ("未完了の約束とフォローアップ", "約束した行動、未解決タスク、未返信、締切、オープンループを0から4項目"),
            ("明日の注意点", "会議、移動、準備、衝突しそうな予定、明日忙しくなる前にやるとよいことを0から3項目"),
            ("保存しておきたい考え", "長期的に残す価値のあるアイデア、判断、好み、問いを0から3項目"),
            ("一言アドバイス", "明日に向けた具体的で実用的な提案を1文だけ"),
        ],
        "weekly_sections": [
            ("今週の主軸", "重要度順に3から{item_count}項目。テーマ、判断、人、有意味な進展に集中する"),
            ("先回りリマインダー", "重要度の高いリマインダーや修正すべき流れを1から4項目"),
            ("人間関係マップ", "重要な人、接触頻度の変化、未返信、感謝、緊張、再接点の機会を0から6項目"),
            ("健康と生活リズムの傾向", "睡眠/夜遅い作業、回復、運動、食事、ストレス、疲労、繰り返す時間パターンを0から5項目。医学的判断はしない"),
            ("繰り返し現れたストレス源", "注意力を消耗していそうなプロジェクト、文脈、判断、状況を0から5項目"),
            ("未完了の約束と来週のフォロー", "約束、未解決タスク、未返信、締切、準備事項を0から6項目"),
            ("見落とされがちだが重要なこと", "健康、人間関係、事務、学習、財務、メンテナンス、長期目標を0から4項目"),
            ("来週の注意点", "衝突しそうな予定、締切、準備、移動、スケジュールリスクを0から4項目"),
            ("一言アドバイス", "来週に向けた具体的で実用的な提案を1文だけ"),
        ],
    },
    "ko": {
        "name": "Korean",
        "cautious": "가능성이 있습니다, 그렇게 보입니다, 확인해 볼 만합니다",
        "none": "명확한 알림은 없습니다.",
        "daily_title": "일일 어시스턴트 브리핑 - {date}",
        "weekly_title": "주간 어시스턴트 브리핑 - {week_key}",
        "daily_sections": [
            ("오늘의 핵심 흐름", "중요도순으로 2에서 {item_count}개 항목. 의미 있는 사건, 결정, 장소, 일을 포함"),
            ("선제 알림", "사용자가 다음에 알아차리거나 해야 할 핵심 사항 1에서 3개"),
            ("관계 알림", "답장, 감사, 위로, 확인, 후속 조치가 필요해 보이는 사람 0에서 4개. 근거 신호를 함께 언급"),
            ("건강/생활 리듬 알림", "수면, 늦은 작업, 휴식, 움직임, 식사, 목소리/피로, 스트레스 신호 0에서 4개. 의학적 판단은 하지 않음"),
            ("미완료 약속과 후속 조치", "약속한 행동, 미해결 작업, 미답장, 마감, 열린 루프 0에서 4개"),
            ("내일 주의할 점", "회의, 이동, 준비, 충돌 가능성, 내일 바빠지기 전에 할 일 0에서 3개"),
            ("저장할 만한 생각", "장기적으로 기억할 가치가 있는 아이디어, 결정, 선호, 질문 0에서 3개"),
            ("한 문장 조언", "내일을 위한 구체적이고 실용적인 제안 한 문장만"),
        ],
        "weekly_sections": [
            ("이번 주 핵심 흐름", "중요도순으로 3에서 {item_count}개 항목. 주제, 결정, 사람, 의미 있는 진전에 집중"),
            ("선제 알림", "가장 레버리지가 큰 알림이나 수정할 패턴 1에서 4개"),
            ("관계 지도", "중요한 사람, 상호작용 변화, 미답장, 감사, 긴장, 다시 연락할 기회 0에서 6개"),
            ("건강과 리듬 추세", "수면/늦은 작업, 회복, 움직임, 식사, 스트레스, 피로, 반복 시간 패턴 0에서 5개. 의학적 판단은 하지 않음"),
            ("반복된 스트레스 요인", "주의력을 소모하는 프로젝트, 맥락, 결정, 상황 0에서 5개"),
            ("미완료 약속과 다음 주 후속 조치", "약속, 미해결 작업, 미답장, 마감, 준비 필요 사항 0에서 6개"),
            ("놓쳤지만 중요한 것", "건강, 관계, 행정, 학습, 재정, 유지관리, 장기 목표 0에서 4개"),
            ("다음 주 주의할 점", "충돌 가능성, 마감, 준비, 이동, 일정 리스크 0에서 4개"),
            ("한 문장 조언", "다음 주를 위한 구체적이고 실용적인 제안 한 문장만"),
        ],
    },
}


def normalize_email_language(value: Any) -> str:
    lang = str(value or "").strip().lower()
    return lang if lang in EMAIL_LANGUAGE_COPY else "en"


def email_report_language(settings: Settings) -> str:
    for source in (getattr(settings, "dashboard", None), getattr(settings, "raw", {}).get("dashboard") if isinstance(getattr(settings, "raw", {}), dict) else None):
        if isinstance(source, dict):
            language = source.get("language")
            if language:
                return normalize_email_language(language)
    return "en"


def email_language_copy(language: str) -> dict[str, Any]:
    return EMAIL_LANGUAGE_COPY[normalize_email_language(language)]


def daily_email_title(day: date, language: str) -> str:
    copy = email_language_copy(language)
    return str(copy["daily_title"]).format(date=day.isoformat())


def weekly_email_title(week_key: str, language: str) -> str:
    copy = email_language_copy(language)
    return str(copy["weekly_title"]).format(week_key=week_key)


def email_digest_model(settings: Settings, period: str) -> str | None:
    specific = config_str(settings.email_reports, f"{period}_model")
    if specific:
        return specific
    shared = config_str(settings.email_reports, "model")
    return shared or None


def email_digest_fallback_model(settings: Settings, period: str) -> str | None:
    specific = config_str(settings.email_reports, f"{period}_fallback_model")
    if specific:
        return specific
    shared = config_str(settings.email_reports, "fallback_model")
    return shared or None


def email_digest_model_label(settings: Settings, model: str | None) -> str:
    if model:
        return model
    local_ai = getattr(settings, "local_ai", None)
    if isinstance(local_ai, dict):
        return str(local_ai.get("text_model") or "qwen3.5:35b")
    if local_ai is None:
        return "qwen3.5:35b"
    return local_text_model(settings)


def email_digest_model_candidates(settings: Settings, period: str) -> list[str | None]:
    candidates: list[str | None] = []
    seen: set[str] = set()

    def append(model: str | None) -> None:
        label = email_digest_model_label(settings, model)
        if label not in seen:
            candidates.append(model)
            seen.add(label)

    primary = email_digest_model(settings, period)
    append(primary)
    fallback = email_digest_fallback_model(settings, period)
    if fallback:
        append(fallback)
    elif primary:
        append(None)
    return candidates


def summarize_email_digest(
    settings: Settings,
    period: str,
    text: str,
    *,
    prompt: str,
    label: str,
) -> str:
    errors: list[str] = []
    for model in email_digest_model_candidates(settings, period):
        try:
            return summarize_text(
                settings,
                text,
                prompt=prompt,
                label=label,
                model=model,
                timeout_seconds=email_digest_timeout_seconds(settings),
            )
        except Exception as exc:
            errors.append(f"{email_digest_model_label(settings, model)}: {exc}")
    detail = " | ".join(errors) if errors else "no model attempts were made"
    raise RuntimeError(f"Email highlight generation failed after model attempts: {detail}")


def email_prompt_sections(sections: list[tuple[str, str]], item_count: int) -> str:
    lines: list[str] = []
    for heading, instruction in sections:
        lines.append(f"## {heading}")
        lines.append(f"- {instruction.format(item_count=item_count)}")
    return "\n".join(lines)


def daily_highlight_prompt(day: date, item_count: int, language: str = "en") -> str:
    copy = email_language_copy(language)
    title = daily_email_title(day, language)
    return (
        "You are preparing a concise proactive personal assistant email.\n"
        f"The source report covers {day.isoformat()}.\n"
        f"Write the entire email in {copy['name']}. Use the exact Markdown section headings provided below.\n"
        "Select only the previous day's most important, most interesting, or most worth-remembering items. "
        "Let the model decide what deserves attention; do not summarize every section.\n"
        "Ignore routine telemetry, repeated file/app/browser counts, and raw collection stats unless they explain why something mattered.\n"
        "Include concrete names, projects, decisions, places, times, or follow-ups when they are supported by the source.\n"
        "The goal is to feel like an assistant who notices what the user may need next, especially relationships, health/life rhythm, unresolved promises, and near-future risks.\n"
        "Do not invent details.\n\n"
        f"{ASSISTANT_SAFETY_CONTRACT}\n"
        f"In this language, cautious phrasing should sound like: {copy['cautious']}.\n"
        f"If a section has no clear evidence, write exactly one bullet with: {copy['none']}\n\n"
        "Write Markdown with this shape:\n"
        f"# {title}\n"
        f"{email_prompt_sections(copy['daily_sections'], item_count)}\n\n"
        f"If the day was mostly routine, still keep the fixed sections but use {copy['none']} where evidence is thin."
    )


def weekly_highlight_prompt(start_day: date, end_day: date, week_key: str, item_count: int, language: str = "en") -> str:
    copy = email_language_copy(language)
    title = weekly_email_title(week_key, language)
    return (
        "You are preparing a concise proactive personal assistant weekly email.\n"
        f"The source summaries cover {start_day.isoformat()} to {(end_day - timedelta(days=1)).isoformat()} ({week_key}).\n"
        f"Write the entire email in {copy['name']}. Use the exact Markdown section headings provided below.\n"
        "Select only the week's most important, most interesting, or most worth-remembering items. "
        "Let the model decide what deserves attention; do not summarize every day mechanically.\n"
        "Prefer themes, decisions, meaningful conversations, projects, places, creative sparks, and follow-ups. "
        "Ignore routine telemetry and repeated counts unless they reveal a meaningful pattern.\n"
        "The goal is to feel like an assistant who notices patterns the user may miss, especially relationships, health/life rhythm, repeated stressors, unresolved promises, and next-week risks.\n"
        "Do not invent details.\n\n"
        f"{ASSISTANT_SAFETY_CONTRACT}\n"
        f"In this language, cautious phrasing should sound like: {copy['cautious']}.\n"
        f"If a section has no clear evidence, write exactly one bullet with: {copy['none']}\n\n"
        "Write Markdown with this shape:\n"
        f"# {title}\n"
        f"{email_prompt_sections(copy['weekly_sections'], item_count)}\n\n"
        f"If the week was mostly routine, still keep the fixed sections but use {copy['none']} where evidence is thin."
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


FOLLOW_UP_KEYWORDS = (
    "follow up",
    "follow-up",
    "todo",
    "to do",
    "need to",
    "needs to",
    "should",
    "reply",
    "respond",
    "send",
    "confirm",
    "check",
    "review",
    "deadline",
    "due",
    "tomorrow",
    "next week",
    "待办",
    "需要",
    "应该",
    "回复",
    "回信",
    "跟进",
    "确认",
    "发送",
    "整理",
    "检查",
    "明天",
    "下周",
    "截止",
    "提醒",
)

HEALTH_RHYTHM_KEYWORDS = (
    "tired",
    "fatigue",
    "exhausted",
    "sleep",
    "slept",
    "late night",
    "stress",
    "stressed",
    "headache",
    "sick",
    "doctor",
    "hospital",
    "exercise",
    "workout",
    "walk",
    "meal",
    "疲",
    "累",
    "困",
    "睡",
    "熬夜",
    "压力",
    "焦虑",
    "头痛",
    "生病",
    "医院",
    "运动",
    "散步",
    "吃饭",
    "久坐",
)


def observation_signal_text(row) -> str:
    parts = [
        row["actor"],
        row["title"],
        row["subtitle"],
        row["body"],
        row["location"],
    ]
    metadata = parse_metadata(row)
    audio_analysis = metadata.get("audio_analysis") if isinstance(metadata.get("audio_analysis"), dict) else {}
    for key in ("summary", "local_summary", "openai_summary"):
        value = audio_analysis.get(key)
        if isinstance(value, str):
            parts.append(value)
    return " ".join(str(part) for part in parts if part)


def actor_signal_lines(observations, limit: int = 8) -> list[str]:
    actors = Counter()
    for row in observations:
        actor = row["actor"]
        if not actor or actor == "me":
            continue
        if row["source"] not in {"apple_mail", "messages"}:
            continue
        actors[actor] += 1
    if not actors:
        return []
    people = ", ".join(f"{compact_text(actor, 50)} ({count})" for actor, count in actors.most_common(limit))
    return [f"- Relationship candidates: {people}"]


def keyword_signal_lines(observations, keywords: tuple[str, ...], label: str, limit: int = 8) -> list[str]:
    matches: list[str] = []
    for row in observations:
        text = observation_signal_text(row)
        if not text:
            continue
        lowered = text.casefold()
        if not any(keyword in lowered for keyword in keywords):
            continue
        source = f"{row['source']}/{row['kind']}"
        matches.append(f"{time_label(row['observed_at'])} {source}: {compact_text(text, 120)}")
        if len(matches) >= limit:
            break
    if not matches:
        return []
    return [f"- {label}: " + "; ".join(matches)]


def rhythm_signal_lines(activity, limit: int = 2) -> list[str]:
    parsed = [parse_dt(row["sampled_at"]) for row in activity if row["sampled_at"]]
    times = [value for value in parsed if value is not None]
    if not times:
        return []

    hints: list[str] = []
    late = [value for value in times if value.hour >= 23 or value.hour < 5]
    if late:
        hints.append(
            f"app activity outside normal rest hours ({time_label(min(late).isoformat())}-{time_label(max(late).isoformat())})"
        )
    if len(times) >= 180:
        hints.append(f"high foreground-sample volume ({len(times)} samples)")
    if not hints:
        return []
    return ["- Rhythm hints: " + "; ".join(hints[:limit])]


def assistant_signal_lines(observations, activity) -> list[str]:
    lines: list[str] = []
    lines.extend(actor_signal_lines(observations))
    lines.extend(keyword_signal_lines(observations, FOLLOW_UP_KEYWORDS, "Possible follow-ups/commitments"))
    lines.extend(keyword_signal_lines(observations, HEALTH_RHYTHM_KEYWORDS, "Health/life-rhythm mentions"))
    lines.extend(rhythm_signal_lines(activity))
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

    assistant_signals = assistant_signal_lines(observations, activity)
    if assistant_signals:
        lines.append("## Assistant Signals")
        lines.extend(assistant_signals)
        lines.append("")

    personal_context = personal_context_report_lines(settings, store)
    if personal_context:
        lines.extend(personal_context)

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

    assistant_signals = assistant_signal_lines(observations, activity)
    if assistant_signals:
        lines.append("## Assistant Signals")
        lines.extend(assistant_signals)
        lines.append("")

    personal_context = personal_context_report_lines(settings, store)
    if personal_context:
        lines.extend(personal_context)

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
    language = email_report_language(settings)
    title = daily_email_title(day, language)
    try:
        digest = summarize_email_digest(
            settings,
            "daily",
            clip_digest_source(settings, source),
            prompt=daily_highlight_prompt(day, item_count, language=language),
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
    language = email_report_language(settings)
    title = weekly_email_title(key, language)
    try:
        source = build_weekly_email_source(settings, store, start, end, weekly_path)
        digest = summarize_email_digest(
            settings,
            "weekly",
            clip_digest_source(settings, source),
            prompt=weekly_highlight_prompt(start, end, key, item_count, language=language),
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
