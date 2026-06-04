from __future__ import annotations

import fnmatch
import json
import re
import subprocess
from pathlib import Path
from typing import Any


PRIVATE_PATH_PATTERNS = [
    "config.json",
    "data",
    "data/*",
    ".env",
    ".env.*",
    ".pcsync",
    ".pcsync/",
    ".pcsync/*",
    "*.sqlite",
    "*.sqlite3",
    "*.db",
    "*.m4a",
    "*.wav",
    "*.mp4",
    "*.mov",
    "*.mobileprovision",
    "*.p12",
    "*.pem",
    "*.key",
    "*.p8",
    "ios/Wond/Config/Signing.local.xcconfig",
    "ios/Wond/build/*",
    "ios/Wond/DerivedData/*",
    "xcuserdata/*",
]

REQUIRED_GITIGNORE_PATTERNS = [
    "config.json",
    "data/",
    ".env",
    ".env.*",
    ".pcsync/",
    "*.sqlite",
    "*.sqlite3",
    "*.db",
    ".venv/",
    "dist/",
    ".release/",
    "*.m4a",
    "*.wav",
    "*.mp4",
    "*.mov",
    "ios/Wond/Config/Signing.local.xcconfig",
    "*.mobileprovision",
    "*.p12",
    "*.pem",
    "*.key",
    "ios/Wond/build/",
    "ios/Wond/DerivedData/",
    "xcuserdata/",
]

SECRET_PATTERNS = [
    ("openai_api_key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("github_token", re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}")),
    ("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    (
        "literal_secret",
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret|password|token)\b[\"']?\s*[:=]\s*[\"']"
            r"(?!change-this|example|placeholder|configured|missing|redacted|new|test\b|secret\b|secret-token\b|sync-secret\b)"
            r"[A-Za-z0-9_./+=:-]{16,}[\"']"
        ),
    ),
]

LOCAL_PATH_PATTERN = re.compile(r"/Users/[A-Za-z0-9._-]+/[^\s\"'<>)]{4,}")
MAX_TEXT_SCAN_BYTES = 1024 * 1024


def release_privacy_audit(
    root: Path | str | None = None,
    *,
    include_history: bool = True,
    max_history_commits: int = 100,
) -> dict[str, Any]:
    repo_root = resolve_repo_root(Path(root or ".").expanduser().resolve())
    tracked = git_lines(repo_root, ["ls-files"])
    checks = [
        tracked_private_file_check(tracked),
        gitignore_check(repo_root),
        content_secret_check(repo_root, tracked),
        local_path_check(repo_root, tracked),
    ]
    if include_history:
        checks.append(history_check(repo_root, max_history_commits=max_history_commits))
    summary = summarize_checks(checks)
    return {
        "ok": summary["fail"] == 0,
        "root": str(repo_root),
        "summary": summary,
        "checks": checks,
    }


def resolve_repo_root(path: Path) -> Path:
    proc = run_git(path, ["rev-parse", "--show-toplevel"], timeout=3)
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip()).resolve()
    return path


def tracked_private_file_check(tracked: list[str]) -> dict[str, Any]:
    findings = []
    for path in tracked:
        pattern = private_path_pattern(path)
        if pattern:
            findings.append({"path": path, "pattern": pattern})
    return check(
        "tracked_private_files",
        "fail" if findings else "ok",
        "Tracked private/runtime files",
        findings=findings,
        detail=(
            f"{len(findings)} tracked private/runtime path(s) matched."
            if findings
            else "No tracked config/data/database/media/signing artifacts matched release-blocking patterns."
        ),
    )


def private_path_pattern(path: str) -> str | None:
    normalized = path.replace("\\", "/").lstrip("./")
    for pattern in PRIVATE_PATH_PATTERNS:
        if fnmatch.fnmatch(normalized, pattern):
            return pattern
    return None


def gitignore_check(root: Path) -> dict[str, Any]:
    gitignore = root / ".gitignore"
    text = gitignore.read_text(encoding="utf-8", errors="replace") if gitignore.exists() else ""
    present = {line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")}
    missing = [pattern for pattern in REQUIRED_GITIGNORE_PATTERNS if pattern not in present]
    return check(
        "gitignore_release_coverage",
        "warn" if missing else "ok",
        ".gitignore release coverage",
        findings=[{"pattern": pattern} for pattern in missing],
        detail=(
            f"{len(missing)} recommended ignore pattern(s) are missing."
            if missing
            else "Recommended local data, signing, build, and release artifact patterns are ignored."
        ),
    )


def content_secret_check(root: Path, tracked: list[str]) -> dict[str, Any]:
    findings = []
    for path in tracked:
        for line_number, line in tracked_text_lines(root, path):
            for name, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append(
                        {
                            "path": path,
                            "line": line_number,
                            "pattern": name,
                            "excerpt": redact_excerpt(line),
                        }
                    )
                    break
            if len(findings) >= 50:
                break
        if len(findings) >= 50:
            break
    return check(
        "tracked_secret_literals",
        "fail" if findings else "ok",
        "Secret-like literals in tracked files",
        findings=findings,
        detail=(
            f"{len(findings)} tracked line(s) contain secret-like literals."
            if findings
            else "No obvious API keys, private keys, or long literal secrets found in tracked text files."
        ),
    )


def local_path_check(root: Path, tracked: list[str]) -> dict[str, Any]:
    findings = []
    for path in tracked:
        for line_number, line in tracked_text_lines(root, path):
            match = LOCAL_PATH_PATTERN.search(line)
            if match:
                findings.append(
                    {
                        "path": path,
                        "line": line_number,
                        "excerpt": redact_local_path(line),
                    }
                )
                break
        if len(findings) >= 50:
            break
    return check(
        "tracked_local_absolute_paths",
        "warn" if findings else "ok",
        "Local absolute paths in tracked files",
        findings=findings,
        detail=(
            f"{len(findings)} tracked file(s) mention local /Users/... paths."
            if findings
            else "No local /Users/... absolute paths found in tracked text files."
        ),
    )


def history_check(root: Path, *, max_history_commits: int) -> dict[str, Any]:
    findings = []
    path_proc = run_git(
        root,
        [
            "log",
            "--all",
            f"-n{max(1, int(max_history_commits))}",
            "--name-only",
            "--pretty=format:%H",
            "--",
            "config.json",
            "data",
            ".env",
            ".env.*",
            ".pcsync",
            "*.sqlite",
            "*.sqlite3",
            "*.db",
        ],
        timeout=10,
    )
    if path_proc.returncode == 0:
        current_commit = ""
        seen = set()
        for raw_line in path_proc.stdout.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if re.fullmatch(r"[0-9a-f]{40}", line):
                current_commit = line
                continue
            key = (current_commit, line)
            if current_commit and key not in seen:
                seen.add(key)
                findings.append({"commit": current_commit[:12], "path": line, "reason": "private_path_in_history"})
                if len(findings) >= 25:
                    break
    for name, pattern in SECRET_PATTERNS[:4]:
        proc = run_git(
            root,
            ["log", "--all", f"-n{max(1, int(max_history_commits))}", "--regexp-ignore-case", "-G", pattern.pattern, "--format=%H"],
            timeout=10,
        )
        if proc.returncode != 0:
            continue
        for commit in unique_lines(proc.stdout):
            findings.append({"commit": commit[:12], "pattern": name, "reason": "secret_like_history_match"})
            if len(findings) >= 50:
                break
        if len(findings) >= 50:
            break
    return check(
        "git_history_privacy",
        "warn" if findings else "ok",
        f"Git history privacy scan ({max_history_commits} commits)",
        findings=findings,
        detail=(
            f"{len(findings)} history finding(s) need review."
            if findings
            else "No private path or obvious secret-like matches found in the scanned history window."
        ),
    )


def tracked_text_lines(root: Path, rel_path: str) -> list[tuple[int, str]]:
    path = root / rel_path
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    if not raw or b"\0" in raw or len(raw) > MAX_TEXT_SCAN_BYTES:
        return []
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw.decode("utf-8", errors="replace")
        except UnicodeDecodeError:
            return []
    return list(enumerate(text.splitlines(), start=1))


def summarize_checks(checks: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "ok": sum(1 for item in checks if item["status"] == "ok"),
        "warn": sum(1 for item in checks if item["status"] == "warn"),
        "fail": sum(1 for item in checks if item["status"] == "fail"),
    }


def check(
    check_id: str,
    status: str,
    title: str,
    *,
    detail: str,
    findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": status,
        "title": title,
        "detail": detail,
        "findings": findings or [],
    }


def format_release_privacy_audit(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        f"Release/privacy audit: {payload['root']}",
        f"Status: {overall_status(payload).upper()} ({summary['fail']} fail, {summary['warn']} warn, {summary['ok']} ok)",
        "",
    ]
    for item in payload["checks"]:
        lines.append(f"[{item['status'].upper()}] {item['title']}")
        lines.append(f"  {item['detail']}")
        for finding in item.get("findings", [])[:8]:
            lines.append(f"  - {format_finding(finding)}")
        extra = len(item.get("findings", [])) - 8
        if extra > 0:
            lines.append(f"  - ... {extra} more")
        lines.append("")
    return "\n".join(lines).rstrip()


def format_finding(finding: dict[str, Any]) -> str:
    if "path" in finding and "line" in finding:
        return f"{finding['path']}:{finding['line']} {finding.get('pattern', '')} {finding.get('excerpt', '')}".strip()
    if "path" in finding and "pattern" in finding:
        return f"{finding['path']} matches {finding['pattern']}"
    if "path" in finding and "commit" in finding:
        return f"{finding['commit']} {finding['path']} ({finding.get('reason', 'history')})"
    if "commit" in finding:
        return f"{finding['commit']} {finding.get('pattern', '')} ({finding.get('reason', 'history')})"
    if "pattern" in finding:
        return f"missing {finding['pattern']}"
    return json.dumps(finding, ensure_ascii=False, sort_keys=True)


def overall_status(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    if summary["fail"]:
        return "fail"
    if summary["warn"]:
        return "warn"
    return "ok"


def release_audit_exit_code(payload: dict[str, Any], *, fail_on_warn: bool = False) -> int:
    status = overall_status(payload)
    if status == "fail" or (status == "warn" and fail_on_warn):
        return 1
    return 0


def redact_excerpt(line: str) -> str:
    text = line.strip()
    text = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "sk-...[redacted]", text)
    text = re.sub(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{8,}", "gh...redacted", text)
    text = re.sub(r"github_pat_[A-Za-z0-9_]{8,}", "github_pat_...redacted", text)
    text = re.sub(r"xox[baprs]-[A-Za-z0-9-]{8,}", "xox...redacted", text)
    text = re.sub(
        r"(?i)(\b(?:api[_-]?key|secret|password|token)\b[\"']?\s*[:=]\s*[\"'])[^\"']+([\"'])",
        r"\1...[redacted]\2",
        text,
    )
    return text[:160]


def redact_local_path(line: str) -> str:
    return LOCAL_PATH_PATTERN.sub("/Users/.../[redacted]", line.strip())[:160]


def run_git(root: Path, args: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(root),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(["git", *args], 1, "", str(exc))


def git_lines(root: Path, args: list[str]) -> list[str]:
    proc = run_git(root, args, timeout=5)
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def unique_lines(text: str) -> list[str]:
    seen = set()
    result = []
    for line in text.splitlines():
        value = line.strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
