from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from .agent import (
    dashboard_launch_agent_label,
    dashboard_launch_agent_path,
    install_dashboard_launch_agent,
    install_launch_agent,
    install_sync_launch_agent,
    launch_agent_label,
    launch_agent_path,
    run_monitor,
    sync_launch_agent_label,
    sync_launch_agent_path,
)
from .audio_analysis import analyze_audio_for_day
from .compactor import (
    write_all_compact_summaries,
    write_daily_compact_summary,
    write_monthly_summary,
    write_weekly_summary,
)
from .collectors import collect_all, is_collector_error_result, sample_foreground_app
from .config import ensure_config, load_settings
from .dashboard import api_doctor, create_dashboard_server, doctor_text
from .dashboard_search import rebuild_search_index
from .email_reports import manual_email_task, send_due_email_reports, send_task
from .file_analysis import analyze_new_files, initialize_state
from .mobile import ingest_mobile_export
from .openai_analysis import analyze_paths_with_openai
from .recycle_bin import (
    list_recycle_bin,
    purge_recycle_bin,
    recycle_bin_config,
    recycle_bin_summary,
    restore_recycle_entry,
)
from .retention import run_retention
from .release_audit import (
    format_release_privacy_audit,
    release_audit_exit_code,
    release_privacy_audit,
)
from .speakers import (
    auto_organize_speakers,
    collapse_vad_chunk_speakers,
    detach_speaker_sample,
    mark_speaker_audio_protection,
    mark_speaker_review_status,
    mark_speaker_sample_audio_protection,
    pending_speaker_match_groups,
    prune_speaker_sample_audio,
    refresh_speaker_sample_confidences,
    refresh_representative_speaker_samples,
    representative_min_sample_confidence,
    repair_missing_speaker_embeddings,
    repair_speaker_sample_clips,
    repair_speaker_sample_text,
    repair_speaker_samples,
    resolve_speaker_match_decision,
    revive_hidden_speakers,
    reset_and_auto_group_speaker_samples,
    split_speaker_sample,
    speaker_profile_payload,
)
from .store import Store
from .summarizer import write_daily_report
from .sync_server import cleanup_mobile_sync_storage, run_sync_server
from .timeutil import day_bounds, local_iso, parse_day
from .version import __version__


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config.json. Defaults to ./config.json.",
    )


def command_init(args: argparse.Namespace) -> int:
    path = ensure_config(args.config)
    settings = load_settings(path)
    Store(settings.db_path).close()
    print(f"Config: {path}")
    print(f"Database: {settings.db_path}")
    print(f"Reports: {settings.report_dir}")
    return 0


def command_collect(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    store = Store(settings.db_path)
    day = parse_day(args.date, settings.timezone)
    start, end = day_bounds(day, settings.timezone)
    totals: dict[str, int] = {}
    for name, observations in collect_all(settings, start, end).items():
        run_id = store.start_run(name)
        try:
            count = store.upsert_observations(observations)
            if is_collector_error_result(name, observations):
                store.finish_run(run_id, "error", observations[0].body or observations[0].title or "collector_error")
                totals[name] = -1
                continue
            else:
                store.clear_collector_error(name, start.date())
            store.finish_run(run_id, "ok", f"{count} observations")
            totals[name] = count
        except Exception as exc:
            store.finish_run(run_id, "error", str(exc))
            totals[name] = -1
    if not args.no_report:
        report_path = write_daily_report(settings, store, day)
        print(f"Report: {report_path}")
    for name, count in totals.items():
        print(f"{name}: {count}")
    store.close()
    return 0


def command_sample(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    store = Store(settings.db_path)
    sample = sample_foreground_app(settings)
    if not sample:
        print("No foreground sample captured. macOS Accessibility permission may be needed.")
        return 1
    store.add_activity_sample(sample)
    print(f"{sample.sampled_at} {sample.app} {sample.window_title or ''}")
    store.close()
    return 0


def command_summarize(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    store = Store(settings.db_path)
    day = parse_day(args.date, settings.timezone)
    path = write_daily_report(settings, store, day)
    print(path)
    store.close()
    return 0


def command_compact(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    store = Store(settings.db_path)
    day = parse_day(args.date, settings.timezone)
    if args.period == "daily":
        paths = [write_daily_compact_summary(settings, store, day)]
    elif args.period == "weekly":
        paths = [write_weekly_summary(settings, store, day)]
    elif args.period == "monthly":
        paths = [write_monthly_summary(settings, store, day)]
    else:
        paths = write_all_compact_summaries(settings, store, day)
    for path in paths:
        print(path)
    store.close()
    return 0


def command_retention(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    store = Store(settings.db_path)
    day = parse_day(args.date, settings.timezone)
    result = run_retention(settings, store, day, dry_run=not args.apply)
    for line in result.lines():
        print(line)
    store.close()
    return 0


def command_email_summary(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    store = Store(settings.db_path)
    try:
        day = parse_day(args.date, settings.timezone)
        task = manual_email_task(settings, store, args.period, day)
        if args.print_body:
            print(task.body_path.read_text(encoding="utf-8"))
        result = send_task(settings, store, task, dry_run=not args.send)
        print(f"{result.status}: {result.task.subject}")
        print(result.message)
        return 0 if result.status in {"sent", "dry-run"} else 1
    finally:
        store.close()


def command_email_due(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    store = Store(settings.db_path)
    try:
        results = send_due_email_reports(settings, store, dry_run=not args.send)
        if not results:
            print("No email reports due.")
        for result in results:
            print(f"{result.status}: {result.task.subject}")
            print(result.message)
        return 0 if all(result.status in {"sent", "dry-run"} for result in results) else 1
    finally:
        store.close()


def command_analyze_audio(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    store = Store(settings.db_path)
    try:
        day = parse_day(args.date, settings.timezone)
        result = analyze_audio_for_day(
            settings,
            store,
            day,
            limit=args.limit,
            force=args.force,
        )
        for line in result.lines():
            print(line)
        if not args.no_report:
            report_path = write_daily_report(settings, store, day)
            print(f"Report: {report_path}")
        return 1 if result.failed else 0
    finally:
        store.close()


def command_analyze_media(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    store = Store(settings.db_path)
    try:
        result = analyze_paths_with_openai(
            settings,
            store,
            args.paths,
            prompt=args.prompt,
            force=args.force,
        )
        for line in result.lines():
            print(line)
        if args.report_date:
            day = parse_day(args.report_date, settings.timezone)
            report_path = write_daily_report(settings, store, day)
            print(f"Report: {report_path}")
        return 1 if result.failed else 0
    finally:
        store.close()


def command_analyze_new_files(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    store = Store(settings.db_path)
    try:
        if args.reset_baseline:
            initialize_state(settings, time.time())
            print("New-file analysis baseline reset to now.")
            return 0
        result = analyze_new_files(settings, store, force_scan=True)
        for line in result.lines():
            print(line)
        if result.analyzed and not args.no_report:
            report_path = write_daily_report(settings, store, parse_day("today", settings.timezone))
            print(f"Report: {report_path}")
        return 1 if result.failed else 0
    finally:
        store.close()


def command_ingest_mobile(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    store = Store(settings.db_path)
    try:
        result = ingest_mobile_export(settings, store, args.path)
        if args.report_date:
            day = parse_day(args.report_date, settings.timezone)
            report_path = write_daily_report(settings, store, day)
            print(f"Report: {report_path}")
        print(f"Imported: {result.imported}")
        print(f"Skipped: {result.skipped}")
        for error in result.errors[:20]:
            print(f"- {error}", file=sys.stderr)
    except (OSError, ValueError) as exc:
        print(f"Mobile ingest failed: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()
    return 1 if result.imported == 0 and result.skipped > 0 else 0


def command_sync_server(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    run_sync_server(settings, host=args.host, port=args.port)
    return 0


def command_mobile_sync_cleanup(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    store = Store(settings.db_path)
    try:
        result = cleanup_mobile_sync_storage(
            settings,
            store,
            dry_run=not args.apply,
            clean_inbox=not args.keep_inbox,
            clean_imports=not args.keep_imports,
        )
        for line in result.lines(dry_run=not args.apply):
            print(line)
        if not args.apply:
            print("Dry run only. Re-run with --apply to delete these cached files.")
        return 0
    finally:
        store.close()


def command_recycle_bin(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    if args.recycle_command == "list":
        entries = list_recycle_bin(settings)
        summary = recycle_bin_summary(settings, entries)
        if args.json:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "config": recycle_bin_config(settings),
                        "summary": summary,
                        "entries": entries,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        print(f"Recycle bin: {recycle_bin_config(settings)['dir']}")
        print(f"Files: {summary['files']}")
        print(f"Bytes: {summary['total_bytes']}")
        print(f"Due now: {summary['due_files']}")
        if not entries:
            print("No recycled files.")
            return 0
        for entry in entries[: args.limit]:
            marker = "missing" if not entry.get("exists", True) else "file"
            print(
                f"- [{marker}] {entry.get('moved_at') or '-'} -> {entry.get('delete_after') or '-'} "
                f"{entry.get('size') or 0} bytes {entry.get('category') or 'unknown'}"
            )
            print(f"  original: {entry.get('original_path') or '-'}")
            print(f"  trash: {entry.get('trash_path') or '-'}")
        return 0

    if args.recycle_command == "purge":
        result = purge_recycle_bin(settings, dry_run=not args.apply)
        for line in result.lines(dry_run=not args.apply):
            print(line)
        if not args.apply:
            print("Dry run only. Re-run with --apply to permanently delete due files.")
        return 1 if result.errors else 0

    if args.recycle_command == "restore":
        result = restore_recycle_entry(settings, args.trash_path, restore_path=args.to)
        if result.restored:
            print(f"Restored: {result.trash_path} -> {result.restored_path}")
            return 0
        print(f"Restore failed: {result.error}", file=sys.stderr)
        return 1

    print("Unknown recycle-bin command.", file=sys.stderr)
    return 1


def command_doctor(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    payload = api_doctor(settings)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(doctor_text(settings))
    return 1 if args.strict and payload.get("overall") == "fail" else 0


def command_dashboard(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    server = create_dashboard_server(settings, host=args.host, port=args.port)
    print(f"Dashboard: {server.url}", flush=True)
    if args.open:
        webbrowser.open(server.url)
    try:
        server.httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        server.httpd.server_close()
    return 0


def command_search_index(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    try:
        result = rebuild_search_index(
            settings,
            limit=args.limit,
            force=args.force,
            source=args.source or "",
        )
    except Exception as exc:
        print(f"Search index failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_speakers(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    store = Store(settings.db_path)
    try:
        if args.speaker_command == "list":
            rows = store.list_speakers()
            if not rows:
                print("No speakers recorded yet.")
                return 0
            for row in rows:
                latest = f" latest_sample={row['latest_sample_at']}" if row["latest_sample_at"] else ""
                confidence = f" confidence={float(row['confidence']):.3f}" if row["confidence"] is not None else ""
                print(
                    f"{row['id']}: {row['display_name']} [{row['identity_status']}] "
                    f"(aliases={row['alias_count']}, samples={row['sample_count']}{confidence}{latest})"
                )
            return 0

        if args.speaker_command == "review":
            rows = store.list_speakers_ready_for_review()
            if not rows:
                print("No speakers are ready for naming yet.")
                return 0
            for row in rows:
                confidence = f"{float(row['confidence']):.3f}" if row["confidence"] is not None else "n/a"
                print(
                    f"{row['id']}: {row['display_name']} "
                    f"(confidence={confidence}, samples={row['sample_count']})"
                )
                samples = store.list_speaker_samples(int(row["id"]))[: args.samples]
                for sample in samples:
                    sample_path = sample["sample_path"] or "(no audio sample)"
                    transcript = f" :: {sample['transcript'][:100]}" if sample["transcript"] else ""
                    print(f"  - {sample_path}{transcript}")
            return 0

        if args.speaker_command == "rename":
            display_name = " ".join(args.display_name).strip()
            if not display_name:
                print("Display name cannot be empty.", file=sys.stderr)
                return 1
            if not store.rename_speaker(args.speaker_id, display_name):
                print(f"Speaker not found: {args.speaker_id}", file=sys.stderr)
                return 1
            print(f"Renamed speaker {args.speaker_id}: {display_name}")
            return 0

        if args.speaker_command == "normalize-names":
            changes = store.relabel_auto_speaker_names()
            if not changes:
                print("No automatic speaker names needed normalization.")
                return 0
            for item in changes:
                print(
                    f"{item['speaker_id']}: {item['old_display_name']} -> "
                    f"{item['new_display_name']} [{item['identity_status']}]"
                )
            print(f"Normalized {len(changes)} automatic speaker names.")
            return 0

        if args.speaker_command == "merge":
            if not store.merge_speakers(args.source_id, args.target_id):
                print("Merge failed. Check that both speaker ids exist and are different.", file=sys.stderr)
                return 1
            print(f"Merged speaker {args.source_id} into speaker {args.target_id}.")
            return 0

        if args.speaker_command == "merge-many":
            target = store.get_speaker(args.target_id)
            if target is None:
                print(f"Target speaker not found: {args.target_id}", file=sys.stderr)
                return 1
            source_ids = unique_ints(args.source_ids)
            source_ids = [speaker_id for speaker_id in source_ids if speaker_id != args.target_id]
            if not source_ids:
                print("No source speaker ids to merge.", file=sys.stderr)
                return 1
            merged: list[int] = []
            failed: list[int] = []
            for source_id in source_ids:
                if store.merge_speakers(source_id, args.target_id):
                    merged.append(source_id)
                else:
                    failed.append(source_id)
            if merged:
                print(f"Merged {len(merged)} speaker(s) into {args.target_id}: {', '.join(map(str, merged))}.")
            if failed:
                print(f"Merge failed for: {', '.join(map(str, failed))}.", file=sys.stderr)
            return 1 if failed else 0

        if args.speaker_command == "auto-organize":
            if not args.apply:
                print("Dry run is not implemented for auto-organize yet. Re-run with --apply.", file=sys.stderr)
                return 1
            max_merges = args.max_merges
            if max_merges is None:
                max_merges = int(settings.speaker_recognition.get("auto_merge_max_merges", 5000))
            result = auto_organize_speakers(
                settings,
                store,
                threshold=args.threshold,
                max_merges=max_merges,
                hide_unmatched=not args.keep_unmatched_visible,
                allow_pending_review=args.continue_pending_review,
            )
            for line in result.lines():
                print(line)
            return 1 if result.failed else 0

        if args.speaker_command == "reset-regroup-samples":
            if not args.apply:
                sample_count = len(store.list_speaker_samples(None))
                print(
                    f"Would reset {sample_count} speaker sample(s) into single-sample voices, "
                    "recut clean in-segment audio, recompute embeddings, then auto-organize."
                )
                print("Dry run only. Re-run with --apply to rewrite speaker sample grouping.")
                return 0
            result = reset_and_auto_group_speaker_samples(
                settings,
                store,
                threshold=args.threshold,
                max_merges=args.max_merges,
                recut=not args.no_recut,
                hide_unmatched=not args.keep_unmatched_visible,
                exclude_speaker_ids=args.exclude_speaker_id,
            )
            for line in result.lines():
                print(line)
            return 1 if result.failed else 0

        if args.speaker_command == "confirm":
            result = mark_speaker_review_status(store, speaker_ids=args.speaker_ids, status="confirmed")
            for line in result.lines():
                print(line)
            return 1 if result.missing else 0

        if args.speaker_command == "unhide":
            result = mark_speaker_review_status(store, speaker_ids=args.speaker_ids, status="unhidden")
            for line in result.lines():
                print(line)
            return 1 if result.missing else 0

        if args.speaker_command == "delete":
            speaker = store.get_speaker(args.speaker_id)
            if speaker is None:
                print(f"Speaker not found: {args.speaker_id}", file=sys.stderr)
                return 1
            samples = store.list_speaker_samples(args.speaker_id)
            if not args.apply:
                print(
                    f"Would delete speaker {args.speaker_id}: {speaker['display_name']} "
                    f"({len(samples)} samples). Re-run with --apply to delete."
                )
                return 0
            sample_paths = [row["sample_path"] for row in samples if row["sample_path"]]
            if not store.delete_speaker(args.speaker_id):
                print(f"Speaker not found: {args.speaker_id}", file=sys.stderr)
                return 1
            deleted_files = delete_speaker_sample_files(settings, sample_paths)
            print(f"Deleted speaker {args.speaker_id}: {speaker['display_name']} ({deleted_files} sample files).")
            return 0

        if args.speaker_command == "delete-many":
            speaker_ids = unique_ints(args.speaker_ids)
            existing = [(speaker_id, store.get_speaker(speaker_id)) for speaker_id in speaker_ids]
            missing = [speaker_id for speaker_id, speaker in existing if speaker is None]
            rows = [(speaker_id, speaker) for speaker_id, speaker in existing if speaker is not None]
            if not rows:
                print("No matching speakers found.", file=sys.stderr)
                return 1
            if not args.apply:
                sample_count = sum(len(store.list_speaker_samples(speaker_id)) for speaker_id, _speaker in rows)
                print(
                    f"Would delete {len(rows)} speaker(s), {sample_count} sample record(s). "
                    "Re-run with --apply to delete."
                )
                if missing:
                    print(f"Missing speaker ids: {', '.join(map(str, missing))}.", file=sys.stderr)
                return 1 if missing else 0
            deleted = 0
            deleted_files = 0
            for speaker_id, speaker in rows:
                samples = store.list_speaker_samples(speaker_id)
                sample_paths = [row["sample_path"] for row in samples if row["sample_path"]]
                if store.delete_speaker(speaker_id):
                    deleted += 1
                    deleted_files += delete_speaker_sample_files(settings, sample_paths)
                    print(f"Deleted speaker {speaker_id}: {speaker['display_name']} ({len(samples)} sample records).")
            if missing:
                print(f"Missing speaker ids: {', '.join(map(str, missing))}.", file=sys.stderr)
            print(f"Deleted {deleted} speaker(s), {deleted_files} sample file(s).")
            return 1 if missing else 0

        if args.speaker_command == "samples":
            rows = store.list_speaker_samples(args.speaker_id)
            if not rows:
                print("No speaker samples recorded yet.")
                return 0
            for row in rows:
                sample_path = row["sample_path"] or "(no audio sample)"
                span = ""
                if row["start_seconds"] is not None and row["end_seconds"] is not None:
                    span = f" {float(row['start_seconds']):.2f}-{float(row['end_seconds']):.2f}s"
                transcript = f" :: {row['transcript'][:120]}" if row["transcript"] else ""
                print(f"{row['speaker_id']}: {row['speaker_name']}{span} {sample_path}{transcript}")
            return 0

        if args.speaker_command == "prune-sample-audio":
            day = parse_day(args.date, settings.timezone)
            result = prune_speaker_sample_audio(
                settings,
                store,
                today=day,
                dry_run=not args.apply,
                older_than_days=args.older_than_days,
                limit=args.limit,
            )
            for line in result.lines():
                print(line)
            return 1 if result.failed else 0

        if args.speaker_command == "protect-sample":
            result = mark_speaker_sample_audio_protection(
                store,
                sample_ids=args.sample_ids,
                protected=not args.unprotect,
            )
            for line in result.lines():
                print(line)
            return 1 if result.missing else 0

        if args.speaker_command == "protect-speaker-audio":
            result = mark_speaker_audio_protection(
                store,
                speaker_ids=args.speaker_ids,
                protected=not args.unprotect,
            )
            for line in result.lines():
                print(line)
            return 1 if result.missing else 0

        if args.speaker_command == "detach-sample":
            result = detach_speaker_sample(
                settings,
                store,
                sample_id=args.sample_id,
                display_name=args.display_name,
            )
            for line in result.lines():
                print(line)
            return 1 if result.failed else 0

        if args.speaker_command == "split-sample":
            result = split_speaker_sample(
                settings,
                store,
                sample_id=args.sample_id,
                cut_points=parse_float_list(args.cuts),
                separate_speakers=not args.keep_speaker,
                archive_parent=not args.keep_parent_active,
            )
            for line in result.lines():
                print(line)
            return 1 if result.failed else 0

        if args.speaker_command == "refresh-sample-confidence":
            result = refresh_speaker_sample_confidences(
                settings,
                store,
                speaker_ids=args.speaker_ids or None,
            )
            for line in result.lines():
                print(line)
            return 1 if result.failed else 0

        if args.speaker_command == "repair-embeddings":
            result = repair_missing_speaker_embeddings(
                settings,
                store,
                apply=args.apply,
                limit=args.limit,
            )
            for line in result.lines():
                print(line)
            if not args.apply and result.repaired_samples:
                print("Dry run only. Re-run with --apply to compute missing embeddings.")
            return 1 if result.failed_samples else 0

        if args.speaker_command == "refresh-representatives":
            result = refresh_representative_speaker_samples(
                store,
                speaker_ids=args.speaker_ids or None,
                per_speaker=args.per_speaker,
                min_confidence=(
                    args.min_confidence
                    if args.min_confidence is not None
                    else representative_min_sample_confidence(settings.speaker_recognition)
                ),
            )
            for line in result.lines():
                print(line)
            return 0

        if args.speaker_command == "revive-hidden":
            result = revive_hidden_speakers(
                store,
                apply=args.apply,
                min_samples=args.min_samples,
                min_days=args.min_days,
                min_embeddings=args.min_embeddings,
            )
            for line in result.lines():
                print(line)
            if not args.apply and result.candidates:
                print("Dry run only. Re-run with --apply to return these speakers to review.")
            return 0

        if args.speaker_command == "review-merges":
            groups = pending_speaker_match_groups(store, limit=args.limit)
            if not groups:
                print("No pending speaker match groups.")
                return 0
            for group in groups:
                target = group.get("target_name") or group.get("target_speaker_id") or "(none)"
                print(f"Target {target}: {len(group['matches'])} pending match(es)")
                for match in group["matches"][: args.matches_per_group]:
                    score = f"{float(match['score']):.3f}" if match.get("score") is not None else "n/a"
                    print(
                        f"  #{match['id']} {match['status']}: "
                        f"{match.get('source_name') or match.get('source_speaker_id')} -> "
                        f"{match.get('target_name') or match.get('target_speaker_id') or '(none)'} "
                        f"score={score}"
                    )
            return 0

        if args.speaker_command == "resolve-match":
            result = resolve_speaker_match_decision(
                settings,
                store,
                match_id=args.match_id,
                action=args.action,
            )
            for line in result.lines():
                print(line)
            return 1 if result.failed else 0

        if args.speaker_command == "profile":
            payload = speaker_profile_payload(store, args.speaker_id)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload.get("ok") else 1

        if args.speaker_command == "matches":
            rows = store.list_speaker_match_decisions(limit=args.limit)
            if not rows:
                print("No speaker match decisions recorded yet.")
                return 0
            for row in rows:
                source = row["source_name"] or row["source_speaker_id"]
                target = row["target_name"] or row["target_speaker_id"] or "(none)"
                score = f"{float(row['score']):.3f}" if row["score"] is not None else "n/a"
                threshold = f"{float(row['threshold']):.3f}" if row["threshold"] is not None else "n/a"
                print(
                    f"{row['created_at']} {row['status']}: "
                    f"{source} -> {target} score={score} threshold={threshold}"
                )
            return 0

        if args.speaker_command == "repair-samples":
            result = repair_speaker_samples(
                settings,
                store,
                limit=args.limit,
                force=args.force,
            )
            for line in result.lines():
                print(line)
            return 1 if result.failed else 0

        if args.speaker_command == "repair-sample-text":
            result = repair_speaker_sample_text(
                settings,
                store,
                apply=args.apply,
                limit=args.limit,
            )
            for line in result.lines():
                print(line)
            if not args.apply and result.repaired:
                print("Dry run only. Re-run with --apply to update speaker sample text.")
            return 1 if result.failed else 0

        if args.speaker_command == "repair-sample-clips":
            result = repair_speaker_sample_clips(
                settings,
                store,
                apply=args.apply,
                limit=args.limit,
                speaker_ids=args.speaker_ids or None,
                sample_ids=args.sample_ids or None,
            )
            for line in result.lines():
                print(line)
            if not args.apply and result.repaired:
                print("Dry run only. Re-run with --apply to recut speaker sample clips.")
            return 1 if result.failed else 0

        if args.speaker_command == "collapse-vad-chunks":
            result = collapse_vad_chunk_speakers(
                settings,
                store,
                apply=args.apply,
                include_named=args.include_named,
                limit=args.limit,
            )
            for line in result.lines():
                print(line)
            if not args.apply and result.merge_groups:
                print("Dry run only. Re-run with --apply to merge these chunk-local voices.")
            return 0
    finally:
        store.close()
    print(f"Unknown speakers command: {args.speaker_command}", file=sys.stderr)
    return 1


def unique_ints(values: list[int]) -> list[int]:
    unique: list[int] = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique


def parse_float_list(value: str) -> list[float]:
    return [float(item) for item in str(value or "").replace(",", " ").split()]


def delete_speaker_sample_files(settings, sample_paths: list[str]) -> int:
    root = settings.speaker_sample_dir.resolve()
    deleted = 0
    for raw_path in sample_paths:
        try:
            path = Path(str(raw_path)).expanduser().resolve()
            path.relative_to(root)
        except (OSError, ValueError):
            continue
        if not path.exists() or not path.is_file():
            continue
        path.unlink()
        deleted += 1
        parent = path.parent
        try:
            parent.relative_to(root)
            parent.rmdir()
        except (OSError, ValueError):
            pass
    return deleted


def command_monitor(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    store = Store(settings.db_path)
    run_monitor(settings, store, once=args.once)
    store.close()
    return 0


def command_install_agent(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    path = install_launch_agent(settings)
    if args.load:
        proc = load_launch_agent(path, launch_agent_label())
        if proc != 0:
            print(f"LaunchAgent written but launchctl load failed: {path}", file=sys.stderr)
            return proc
    print(path)
    return 0


def command_install_sync_agent(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    path = install_sync_launch_agent(settings)
    if args.load:
        proc = load_launch_agent(path, sync_launch_agent_label())
        if proc != 0:
            print(f"LaunchAgent written but launchctl load failed: {path}", file=sys.stderr)
            return proc
    print(path)
    return 0


def command_install_dashboard_agent(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    path = install_dashboard_launch_agent(settings)
    if args.load:
        proc = load_launch_agent(path, dashboard_launch_agent_label())
        if proc != 0:
            print(f"LaunchAgent written but launchctl load failed: {path}", file=sys.stderr)
            return proc
    print(path)
    return 0


def load_launch_agent(path: Path, label: str) -> int:
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", f"{domain}/{label}"], check=False, capture_output=True)
    subprocess.run(["launchctl", "bootout", domain, str(path)], check=False, capture_output=True)
    proc = subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=False)
    if proc.returncode != 0:
        proc = subprocess.run(["launchctl", "load", str(path)], check=False)
    if proc.returncode != 0:
        return int(proc.returncode)
    subprocess.run(
        ["launchctl", "kickstart", "-k", f"{domain}/{label}"],
        check=False,
        capture_output=True,
    )
    return 0


def launch_agent_state() -> str:
    return launch_agent_state_for_label(launch_agent_label())


def sync_launch_agent_state() -> str:
    return launch_agent_state_for_label(sync_launch_agent_label())


def dashboard_launch_agent_state() -> str:
    return launch_agent_state_for_label(dashboard_launch_agent_label())


def launch_agent_state_for_label(label: str) -> str:
    proc = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return "not loaded"
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("state = "):
            return line.replace("state = ", "", 1)
    return "loaded"


def command_status(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    store = Store(settings.db_path)
    print(f"Config: {settings.path}")
    print(f"Database: {settings.db_path}")
    installed = "installed" if launch_agent_path().exists() else "not installed"
    print(f"LaunchAgent: {launch_agent_path()} ({installed}, {launch_agent_state()})")
    print(f"Label: {launch_agent_label()}")
    sync_installed = "installed" if sync_launch_agent_path().exists() else "not installed"
    print(f"Sync LaunchAgent: {sync_launch_agent_path()} ({sync_installed}, {sync_launch_agent_state()})")
    print(f"Sync Label: {sync_launch_agent_label()}")
    dashboard_installed = "installed" if dashboard_launch_agent_path().exists() else "not installed"
    print(
        f"Dashboard LaunchAgent: {dashboard_launch_agent_path()} "
        f"({dashboard_installed}, {dashboard_launch_agent_state()})"
    )
    print(f"Dashboard Label: {dashboard_launch_agent_label()}")
    print("Recent collector runs:")
    for row in store.latest_runs():
        print(
            f"- {row['started_at']} {row['collector']} {row['status']} "
            f"{row['message'] or ''}"
        )
    store.close()
    return 0


def command_release_audit(args: argparse.Namespace) -> int:
    root = args.root or Path.cwd()
    payload = release_privacy_audit(
        root,
        include_history=not args.no_history,
        max_history_commits=args.max_history_commits,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_release_privacy_audit(payload))
    return release_audit_exit_code(payload, fail_on_warn=args.fail_on_warn)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wond",
        description="Wond local memory assistant.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create config and database.")
    add_common_args(p_init)
    p_init.set_defaults(func=command_init)

    p_collect = sub.add_parser("collect", help="Collect context for a day.")
    add_common_args(p_collect)
    p_collect.add_argument("--date", default="today", help="today, yesterday, or YYYY-MM-DD")
    p_collect.add_argument("--no-report", action="store_true")
    p_collect.set_defaults(func=command_collect)

    p_sample = sub.add_parser("sample", help="Capture one foreground app sample.")
    add_common_args(p_sample)
    p_sample.set_defaults(func=command_sample)

    p_summarize = sub.add_parser("summarize", help="Write a daily report.")
    add_common_args(p_summarize)
    p_summarize.add_argument("--date", default="today", help="today, yesterday, or YYYY-MM-DD")
    p_summarize.set_defaults(func=command_summarize)

    p_compact = sub.add_parser("compact", help="Write long-term daily/weekly/monthly summaries.")
    add_common_args(p_compact)
    p_compact.add_argument("--date", default="today", help="today, yesterday, or YYYY-MM-DD")
    p_compact.add_argument(
        "--period",
        choices=["all", "daily", "weekly", "monthly"],
        default="all",
        help="Which long-term summary to write.",
    )
    p_compact.set_defaults(func=command_compact)

    p_retention = sub.add_parser("retention", help="Apply or preview long-term retention cleanup.")
    add_common_args(p_retention)
    p_retention.add_argument("--date", default="today", help="today, yesterday, or YYYY-MM-DD")
    p_retention.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete expired detailed data. Without this, the command is a dry run.",
    )
    p_retention.set_defaults(func=command_retention)

    p_email = sub.add_parser("email-summary", help="Preview or send a daily/weekly summary email.")
    add_common_args(p_email)
    p_email.add_argument("--date", default="yesterday", help="today, yesterday, or YYYY-MM-DD")
    p_email.add_argument("--period", choices=["daily", "weekly"], default="daily")
    p_email.add_argument("--send", action="store_true", help="Actually send email. Defaults to dry-run.")
    p_email.add_argument("--print-body", action="store_true", help="Print the email body.")
    p_email.set_defaults(func=command_email_summary)

    p_email_due = sub.add_parser("email-due", help="Preview or send email reports currently due by schedule.")
    add_common_args(p_email_due)
    p_email_due.add_argument("--send", action="store_true", help="Actually send due emails. Defaults to dry-run.")
    p_email_due.set_defaults(func=command_email_due)

    p_analyze_audio = sub.add_parser(
        "analyze-audio",
        help="Transcribe and summarize imported mobile audio segments with the configured AI backend.",
    )
    add_common_args(p_analyze_audio)
    p_analyze_audio.add_argument("--date", default="today", help="today, yesterday, or YYYY-MM-DD")
    p_analyze_audio.add_argument("--limit", type=int, default=None, help="Max segments to analyze.")
    p_analyze_audio.add_argument("--force", action="store_true", help="Re-run analysis even if results already exist.")
    p_analyze_audio.add_argument("--no-report", action="store_true", help="Do not refresh the daily report.")
    p_analyze_audio.set_defaults(func=command_analyze_audio)

    p_analyze_media = sub.add_parser(
        "analyze-media",
        help="Analyze image, audio, PDF, document, text, or spreadsheet files with the configured AI backend.",
    )
    add_common_args(p_analyze_media)
    p_analyze_media.add_argument("paths", nargs="+", type=Path, help="Files to analyze.")
    p_analyze_media.add_argument("--prompt", default=None, help="Optional custom analysis prompt.")
    p_analyze_media.add_argument("--force", action="store_true", help="Record that this was a forced reanalysis.")
    p_analyze_media.add_argument(
        "--report-date",
        default=None,
        help="Optionally refresh a report after analysis: today, yesterday, or YYYY-MM-DD.",
    )
    p_analyze_media.set_defaults(func=command_analyze_media)

    p_analyze_new = sub.add_parser(
        "analyze-new-files",
        help="Scan watch_paths for new stable files and analyze them once.",
    )
    add_common_args(p_analyze_new)
    p_analyze_new.add_argument(
        "--reset-baseline",
        action="store_true",
        help="Treat files currently on disk as already seen and start from now.",
    )
    p_analyze_new.add_argument(
        "--no-report",
        action="store_true",
        help="Do not refresh today's report after successful analysis.",
    )
    p_analyze_new.set_defaults(func=command_analyze_new_files)

    p_ingest_mobile = sub.add_parser("ingest-mobile", help="Import iOS/watchOS capture export JSON.")
    add_common_args(p_ingest_mobile)
    p_ingest_mobile.add_argument("path", type=Path, help="Path to a mobile export JSON file.")
    p_ingest_mobile.add_argument(
        "--report-date",
        default=None,
        help="Optionally refresh a report after ingesting: today, yesterday, or YYYY-MM-DD.",
    )
    p_ingest_mobile.set_defaults(func=command_ingest_mobile)

    p_sync_server = sub.add_parser(
        "sync-server",
        help="Run the Mac-side local upload server for iPhone automatic sync.",
    )
    add_common_args(p_sync_server)
    p_sync_server.add_argument("--host", default=None, help="Bind host. Defaults to mobile_sync.host.")
    p_sync_server.add_argument("--port", type=int, default=None, help="Bind port. Defaults to mobile_sync.port.")
    p_sync_server.set_defaults(func=command_sync_server)

    p_mobile_cleanup = sub.add_parser(
        "mobile-sync-cleanup",
        help="Preview or delete cached mobile sync upload files and unreferenced imports.",
    )
    add_common_args(p_mobile_cleanup)
    p_mobile_cleanup.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete cached files. Without this, only prints a dry run.",
    )
    p_mobile_cleanup.add_argument("--keep-inbox", action="store_true", help="Do not clean inbox .pcsync/.zip caches.")
    p_mobile_cleanup.add_argument("--keep-imports", action="store_true", help="Do not clean unreferenced import dirs.")
    p_mobile_cleanup.set_defaults(func=command_mobile_sync_cleanup)

    p_recycle = sub.add_parser("recycle-bin", help="List, purge, or restore files staged for delayed deletion.")
    add_common_args(p_recycle)
    recycle_sub = p_recycle.add_subparsers(dest="recycle_command", required=True)

    p_recycle_list = recycle_sub.add_parser("list", help="Show files currently in the delayed-deletion recycle bin.")
    p_recycle_list.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    p_recycle_list.add_argument("--limit", type=int, default=80, help="Maximum entries to print.")
    p_recycle_list.set_defaults(func=command_recycle_bin)

    p_recycle_purge = recycle_sub.add_parser("purge", help="Permanently delete recycle-bin files whose retention window has expired.")
    p_recycle_purge.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete due files. Without this, the command is a dry run.",
    )
    p_recycle_purge.set_defaults(func=command_recycle_bin)

    p_recycle_restore = recycle_sub.add_parser("restore", help="Restore one file from the recycle bin.")
    p_recycle_restore.add_argument("trash_path", type=Path, help="Recycle-bin file path to restore.")
    p_recycle_restore.add_argument("--to", type=Path, default=None, help="Optional restore destination.")
    p_recycle_restore.set_defaults(func=command_recycle_bin)

    p_doctor = sub.add_parser("doctor", help="Run live diagnostics for collectors, sync, local AI, audio, and sources.")
    add_common_args(p_doctor)
    p_doctor.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    p_doctor.add_argument("--strict", action="store_true", help="Exit non-zero if a failing check is found.")
    p_doctor.set_defaults(func=command_doctor)

    p_dashboard = sub.add_parser("dashboard", help="Run the local desktop dashboard web app.")
    add_common_args(p_dashboard)
    p_dashboard.add_argument("--host", default="127.0.0.1", help="Bind host. Defaults to localhost only.")
    p_dashboard.add_argument("--port", type=int, default=8787, help="Bind port. Use 0 to choose a free port.")
    p_dashboard.add_argument("--open", action="store_true", help="Open the dashboard in the default browser.")
    p_dashboard.set_defaults(func=command_dashboard)

    p_search_index = sub.add_parser("search-index", help="Build or refresh the local semantic search index with Ollama embeddings.")
    add_common_args(p_search_index)
    p_search_index.add_argument("--limit", type=int, default=None, help="Maximum records/chunks to index.")
    p_search_index.add_argument("--source", default="", help="Optional source filter, for example mobile, apple_mail, or report.")
    p_search_index.add_argument("--force", action="store_true", help="Rebuild embeddings even when content hashes are unchanged.")
    p_search_index.set_defaults(func=command_search_index)

    p_speakers = sub.add_parser("speakers", help="List, rename, merge, and inspect diarized speakers.")
    add_common_args(p_speakers)
    speaker_sub = p_speakers.add_subparsers(dest="speaker_command", required=True)

    p_speakers_list = speaker_sub.add_parser("list", help="Show remembered speakers.")
    p_speakers_list.set_defaults(func=command_speakers)

    p_speakers_review = speaker_sub.add_parser("review", help="Show high-confidence speakers ready for naming.")
    p_speakers_review.add_argument("--samples", type=int, default=3, help="Samples to show per speaker.")
    p_speakers_review.set_defaults(func=command_speakers)

    p_speakers_rename = speaker_sub.add_parser("rename", help="Edit a speaker display name.")
    p_speakers_rename.add_argument("speaker_id", type=int)
    p_speakers_rename.add_argument("display_name", nargs="+")
    p_speakers_rename.set_defaults(func=command_speakers)

    p_speakers_normalize = speaker_sub.add_parser(
        "normalize-names",
        help="Rename automatic local diarization labels to stable global voice ids.",
    )
    p_speakers_normalize.set_defaults(func=command_speakers)

    p_speakers_merge = speaker_sub.add_parser("merge", help="Merge a duplicate speaker into another speaker.")
    p_speakers_merge.add_argument("source_id", type=int, help="Duplicate speaker id to remove.")
    p_speakers_merge.add_argument("target_id", type=int, help="Speaker id to keep.")
    p_speakers_merge.set_defaults(func=command_speakers)

    p_speakers_merge_many = speaker_sub.add_parser("merge-many", help="Merge multiple speakers into one target speaker.")
    p_speakers_merge_many.add_argument("target_id", type=int, help="Speaker id to keep.")
    p_speakers_merge_many.add_argument("source_ids", type=int, nargs="+", help="Speaker ids to merge into the target.")
    p_speakers_merge_many.set_defaults(func=command_speakers)

    p_speakers_auto_organize = speaker_sub.add_parser(
        "auto-organize",
        help="Automatically merge similar voices and hide low-similarity auto voices.",
    )
    p_speakers_auto_organize.add_argument("--threshold", type=float, default=None, help="Auto-merge threshold. Defaults to config.")
    p_speakers_auto_organize.add_argument("--max-merges", type=int, default=None, help="Maximum merges to apply in one run. Defaults to config.")
    p_speakers_auto_organize.add_argument("--keep-unmatched-visible", action="store_true", help="Do not hide auto voices that cannot be merged.")
    p_speakers_auto_organize.add_argument(
        "--continue-pending-review",
        action="store_true",
        help="Allow auto-merged pending-review voices to keep merging when cluster stability remains high.",
    )
    p_speakers_auto_organize.add_argument("--apply", action="store_true", help="Actually organize speakers.")
    p_speakers_auto_organize.set_defaults(func=command_speakers)

    p_speakers_reset_regroup = speaker_sub.add_parser(
        "reset-regroup-samples",
        help="Reset samples to one voice each, recut clean in-segment clips, recompute embeddings, and auto-group.",
    )
    p_speakers_reset_regroup.add_argument("--threshold", type=float, default=None, help="Auto-merge threshold. Defaults to config.")
    p_speakers_reset_regroup.add_argument("--max-merges", type=int, default=500, help="Maximum merges to apply after reset.")
    p_speakers_reset_regroup.add_argument("--keep-unmatched-visible", action="store_true", help="Do not hide voices that cannot be merged.")
    p_speakers_reset_regroup.add_argument("--no-recut", action="store_true", help="Reuse current sample files and embeddings instead of recutting source audio.")
    p_speakers_reset_regroup.add_argument(
        "--exclude-speaker-id",
        type=int,
        action="append",
        default=[],
        help="Speaker id to leave untouched during reset/regroup. Can be passed more than once.",
    )
    p_speakers_reset_regroup.add_argument("--apply", action="store_true", help="Actually rewrite sample grouping.")
    p_speakers_reset_regroup.set_defaults(func=command_speakers)

    p_speakers_confirm = speaker_sub.add_parser("confirm", help="Mark speakers as manually confirmed.")
    p_speakers_confirm.add_argument("speaker_ids", type=int, nargs="+")
    p_speakers_confirm.set_defaults(func=command_speakers)

    p_speakers_unhide = speaker_sub.add_parser("unhide", help="Return hidden low-similarity speakers to review.")
    p_speakers_unhide.add_argument("speaker_ids", type=int, nargs="+")
    p_speakers_unhide.set_defaults(func=command_speakers)

    p_speakers_delete = speaker_sub.add_parser("delete", help="Delete a speaker and its local sample records.")
    p_speakers_delete.add_argument("speaker_id", type=int)
    p_speakers_delete.add_argument("--apply", action="store_true", help="Actually delete the speaker. Without this, only prints a preview.")
    p_speakers_delete.set_defaults(func=command_speakers)

    p_speakers_delete_many = speaker_sub.add_parser("delete-many", help="Delete multiple speakers and their local sample records.")
    p_speakers_delete_many.add_argument("speaker_ids", type=int, nargs="+")
    p_speakers_delete_many.add_argument("--apply", action="store_true", help="Actually delete the speakers. Without this, only prints a preview.")
    p_speakers_delete_many.set_defaults(func=command_speakers)

    p_speakers_samples = speaker_sub.add_parser("samples", help="Show speaker sample audio files.")
    p_speakers_samples.add_argument("speaker_id", type=int, nargs="?", default=None)
    p_speakers_samples.set_defaults(func=command_speakers)

    p_speakers_prune_sample_audio = speaker_sub.add_parser(
        "prune-sample-audio",
        help="Remove old speaker sample audio files while keeping transcripts and embeddings.",
    )
    p_speakers_prune_sample_audio.add_argument("--date", default="today", help="today, yesterday, or YYYY-MM-DD")
    p_speakers_prune_sample_audio.add_argument(
        "--older-than-days",
        type=int,
        default=None,
        help="Only prune sample audio created before this many days ago. Defaults to config.",
    )
    p_speakers_prune_sample_audio.add_argument("--limit", type=int, default=None, help="Maximum candidate files to prune.")
    p_speakers_prune_sample_audio.add_argument("--apply", action="store_true", help="Actually move files to recycle bin.")
    p_speakers_prune_sample_audio.set_defaults(func=command_speakers)

    p_speakers_protect_sample = speaker_sub.add_parser(
        "protect-sample",
        help="Protect speaker sample audio from automatic pruning.",
    )
    p_speakers_protect_sample.add_argument("sample_ids", type=int, nargs="+")
    p_speakers_protect_sample.add_argument("--unprotect", action="store_true", help="Remove audio protection.")
    p_speakers_protect_sample.set_defaults(func=command_speakers)

    p_speakers_protect_speaker_audio = speaker_sub.add_parser(
        "protect-speaker-audio",
        help="Protect all sample audio under a speaker from automatic pruning.",
    )
    p_speakers_protect_speaker_audio.add_argument("speaker_ids", type=int, nargs="+")
    p_speakers_protect_speaker_audio.add_argument("--unprotect", action="store_true", help="Remove speaker-level audio protection.")
    p_speakers_protect_speaker_audio.set_defaults(func=command_speakers)

    p_speakers_detach_sample = speaker_sub.add_parser("detach-sample", help="Detach one sample into its own new speaker.")
    p_speakers_detach_sample.add_argument("sample_id", type=int)
    p_speakers_detach_sample.add_argument("--display-name", default=None, help="Optional name for the new speaker.")
    p_speakers_detach_sample.set_defaults(func=command_speakers)

    p_speakers_split_sample = speaker_sub.add_parser("split-sample", help="Split one speaker sample into manual child samples.")
    p_speakers_split_sample.add_argument("sample_id", type=int)
    p_speakers_split_sample.add_argument("--cuts", required=True, help="Relative cut points in seconds, comma or space separated.")
    p_speakers_split_sample.add_argument("--keep-speaker", action="store_true", help="Keep child samples on the current speaker instead of new voices.")
    p_speakers_split_sample.add_argument("--keep-parent-active", action="store_true", help="Do not archive the original parent sample.")
    p_speakers_split_sample.set_defaults(func=command_speakers)

    p_speakers_refresh_sample_confidence = speaker_sub.add_parser(
        "refresh-sample-confidence",
        help="Recalculate speaker and per-sample confidence for current speaker clusters.",
    )
    p_speakers_refresh_sample_confidence.add_argument(
        "speaker_ids",
        type=int,
        nargs="*",
        help="Optional speaker ids to refresh. Defaults to all speakers.",
    )
    p_speakers_refresh_sample_confidence.set_defaults(func=command_speakers)

    p_speakers_repair_embeddings = speaker_sub.add_parser(
        "repair-embeddings",
        help="Compute missing speaker embeddings for samples that already have audio clips.",
    )
    p_speakers_repair_embeddings.add_argument("--limit", type=int, default=None, help="Maximum missing samples to scan.")
    p_speakers_repair_embeddings.add_argument("--apply", action="store_true", help="Actually compute embeddings. Without this, only prints a preview.")
    p_speakers_repair_embeddings.set_defaults(func=command_speakers)

    p_speakers_representatives = speaker_sub.add_parser(
        "refresh-representatives",
        help="Pick high-quality representative samples for each speaker profile.",
    )
    p_speakers_representatives.add_argument("speaker_ids", type=int, nargs="*", help="Optional speaker ids. Defaults to all speakers.")
    p_speakers_representatives.add_argument("--per-speaker", type=int, default=3, help="Representative samples per speaker.")
    p_speakers_representatives.add_argument(
        "--min-confidence",
        type=float,
        default=None,
        help="Minimum sample confidence required to mark a representative sample.",
    )
    p_speakers_representatives.set_defaults(func=command_speakers)

    p_speakers_revive_hidden = speaker_sub.add_parser(
        "revive-hidden",
        help="Return hidden speakers with enough evidence back to the review queue.",
    )
    p_speakers_revive_hidden.add_argument("--min-samples", type=int, default=2)
    p_speakers_revive_hidden.add_argument("--min-days", type=int, default=2)
    p_speakers_revive_hidden.add_argument("--min-embeddings", type=int, default=2)
    p_speakers_revive_hidden.add_argument("--apply", action="store_true", help="Actually unhide matching speakers.")
    p_speakers_revive_hidden.set_defaults(func=command_speakers)

    p_speakers_review_merges = speaker_sub.add_parser(
        "review-merges",
        help="Show pending automatic/candidate speaker merge groups.",
    )
    p_speakers_review_merges.add_argument("--limit", type=int, default=50)
    p_speakers_review_merges.add_argument("--matches-per-group", type=int, default=8)
    p_speakers_review_merges.set_defaults(func=command_speakers)

    p_speakers_resolve_match = speaker_sub.add_parser(
        "resolve-match",
        help="Accept or reject one speaker match decision.",
    )
    p_speakers_resolve_match.add_argument("match_id", type=int)
    p_speakers_resolve_match.add_argument("action", choices=["accept", "reject"])
    p_speakers_resolve_match.set_defaults(func=command_speakers)

    p_speakers_profile = speaker_sub.add_parser("profile", help="Show one speaker profile with samples and timeline.")
    p_speakers_profile.add_argument("speaker_id", type=int)
    p_speakers_profile.set_defaults(func=command_speakers)

    p_speakers_matches = speaker_sub.add_parser("matches", help="Show recent automatic speaker match decisions.")
    p_speakers_matches.add_argument("--limit", type=int, default=30)
    p_speakers_matches.set_defaults(func=command_speakers)

    p_speakers_repair = speaker_sub.add_parser(
        "repair-samples",
        help="Rebuild speaker samples when transcript timestamps were parsed incorrectly.",
    )
    p_speakers_repair.add_argument("--limit", type=int, default=None, help="Maximum observations to scan.")
    p_speakers_repair.add_argument("--force", action="store_true", help="Rebuild even if the timeline does not look broken.")
    p_speakers_repair.set_defaults(func=command_speakers)

    p_speakers_repair_text = speaker_sub.add_parser(
        "repair-sample-text",
        help="Replace full-segment speaker sample text with clip-window excerpts.",
    )
    p_speakers_repair_text.add_argument("--limit", type=int, default=None, help="Maximum sample rows to scan.")
    p_speakers_repair_text.add_argument("--apply", action="store_true", help="Actually update sample text. Without this, only prints a preview.")
    p_speakers_repair_text.set_defaults(func=command_speakers)

    p_speakers_repair_clips = speaker_sub.add_parser(
        "repair-sample-clips",
        help="Recut speaker sample audio to the current clip-window policy.",
    )
    p_speakers_repair_clips.add_argument("--limit", type=int, default=None, help="Maximum sample rows to scan.")
    p_speakers_repair_clips.add_argument(
        "--speaker-id",
        dest="speaker_ids",
        action="append",
        type=int,
        default=[],
        help="Only repair this speaker id. Repeatable.",
    )
    p_speakers_repair_clips.add_argument(
        "--sample-id",
        dest="sample_ids",
        action="append",
        type=int,
        default=[],
        help="Only repair this sample id. Repeatable.",
    )
    p_speakers_repair_clips.add_argument(
        "--apply",
        action="store_true",
        help="Actually recut sample files and update embeddings. Without this, only prints a preview.",
    )
    p_speakers_repair_clips.set_defaults(func=command_speakers)

    p_speakers_collapse = speaker_sub.add_parser(
        "collapse-vad-chunks",
        help="Merge duplicate Voice rows created by VAD chunk scoped labels within the same observation.",
    )
    p_speakers_collapse.add_argument("--limit", type=int, default=None, help="Maximum merge groups to process.")
    p_speakers_collapse.add_argument("--apply", action="store_true", help="Actually merge speakers. Without this, only prints a preview.")
    p_speakers_collapse.add_argument("--include-named", action="store_true", help="Allow named speakers to be merged too.")
    p_speakers_collapse.set_defaults(func=command_speakers)

    p_monitor = sub.add_parser("monitor", help="Run the background monitor loop.")
    add_common_args(p_monitor)
    p_monitor.add_argument("--once", action="store_true", help="Run one loop, useful for smoke tests.")
    p_monitor.set_defaults(func=command_monitor)

    p_agent = sub.add_parser("install-agent", help="Install a macOS LaunchAgent.")
    add_common_args(p_agent)
    p_agent.add_argument("--load", action="store_true", help="Load the agent with launchctl after writing it.")
    p_agent.set_defaults(func=command_install_agent)

    p_sync_agent = sub.add_parser("install-sync-agent", help="Install the Mac sync-server LaunchAgent.")
    add_common_args(p_sync_agent)
    p_sync_agent.add_argument("--load", action="store_true", help="Load the sync agent with launchctl after writing it.")
    p_sync_agent.set_defaults(func=command_install_sync_agent)

    p_dashboard_agent = sub.add_parser("install-dashboard-agent", help="Install the dashboard LaunchAgent.")
    add_common_args(p_dashboard_agent)
    p_dashboard_agent.add_argument(
        "--load",
        action="store_true",
        help="Load the dashboard agent with launchctl after writing it.",
    )
    p_dashboard_agent.set_defaults(func=command_install_dashboard_agent)

    p_status = sub.add_parser("status", help="Show local status.")
    add_common_args(p_status)
    p_status.set_defaults(func=command_status)

    p_release_audit = sub.add_parser(
        "release-audit",
        aliases=["privacy-audit"],
        help="Audit the repo for release-blocking privacy leaks.",
    )
    p_release_audit.add_argument("--root", type=Path, default=None, help="Repository root to audit. Defaults to cwd/git root.")
    p_release_audit.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    p_release_audit.add_argument("--no-history", action="store_true", help="Skip Git history scanning.")
    p_release_audit.add_argument(
        "--max-history-commits",
        type=int,
        default=100,
        help="Maximum recent commits to scan when history scanning is enabled.",
    )
    p_release_audit.add_argument(
        "--fail-on-warn",
        action="store_true",
        help="Return a non-zero exit code when warnings are present.",
    )
    p_release_audit.set_defaults(func=command_release_audit)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
