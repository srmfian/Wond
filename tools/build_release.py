from __future__ import annotations

import argparse
import ast
import hashlib
import shutil
import stat
import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"
STAGING_DIR = ROOT / ".release"

UPDATE_MANAGED_DIRS = ("wond", "ios", "docs", "tests", "tools")
UPDATE_MANAGED_FILES = (
    "README.md",
    "LICENSE",
    "pyproject.toml",
    "config.example.json",
    "install.command",
    "Start Wond Dashboard.command",
    "Install Wond Services.command",
    "Run Wond Doctor.command",
    "Stop Wond Services.command",
)


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )


def package_version() -> str:
    tree = ast.parse((ROOT / "wond" / "version.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__version__":
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        return node.value.value
    raise RuntimeError("Could not find wond.version.__version__")


def tracked_files() -> list[Path]:
    proc = run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"])
    return [Path(item) for item in proc.stdout.split("\0") if item]


def copy_tracked_files(dest: Path) -> None:
    for rel_path in tracked_files():
        src = ROOT / rel_path
        if not src.is_file():
            continue
        target = dest / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)


def write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def install_command(version: str) -> str:
    return f"""#!/bin/bash
set -euo pipefail

VERSION="{version}"
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
SYSTEM_INSTALL_DIR="/Applications/Wond"
LEGACY_INSTALL_DIR="$HOME/Applications/Wond"
INSTALL_DIR="${{WOND_INSTALL_DIR:-}}"
SOURCE_REAL="$(cd "$SOURCE_DIR" && pwd -P)"

if [ -z "$INSTALL_DIR" ]; then
  if [ -d "$LEGACY_INSTALL_DIR/wond" ] && [ ! -d "$SYSTEM_INSTALL_DIR/wond" ]; then
    INSTALL_DIR="$LEGACY_INSTALL_DIR"
    echo "Found existing Wond install at $INSTALL_DIR; reusing it."
  else
    INSTALL_DIR="$SYSTEM_INSTALL_DIR"
  fi
fi

echo "Installing Wond $VERSION"
echo "Source: $SOURCE_DIR"
echo "Install directory: $INSTALL_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required. Install Python 3.11 or newer first."
  exit 1
fi

if ! mkdir -p "$INSTALL_DIR" 2>/dev/null || [ ! -w "$INSTALL_DIR" ]; then
  if [ -z "${{WOND_INSTALL_DIR:-}}" ] && [ "$INSTALL_DIR" = "$SYSTEM_INSTALL_DIR" ]; then
    echo "Unable to write $SYSTEM_INSTALL_DIR; falling back to $LEGACY_INSTALL_DIR."
    INSTALL_DIR="$LEGACY_INSTALL_DIR"
    if ! mkdir -p "$INSTALL_DIR" 2>/dev/null || [ ! -w "$INSTALL_DIR" ]; then
      echo "Could not create a writable Wond install directory at $INSTALL_DIR."
      exit 1
    fi
  else
    echo "Could not create a writable Wond install directory at $INSTALL_DIR."
    exit 1
  fi
fi
INSTALL_REAL="$(cd "$INSTALL_DIR" && pwd -P)"

if [ "$SOURCE_REAL" != "$INSTALL_REAL" ]; then
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete \\
      --exclude ".git/" \\
      --exclude ".release/" \\
      --exclude ".venv/" \\
      --exclude "config.json" \\
      --exclude "data/" \\
      "$SOURCE_DIR/" "$INSTALL_DIR/"
  else
    ditto "$SOURCE_DIR" "$INSTALL_DIR"
  fi
fi

cd "$INSTALL_DIR"

python3 -m venv "$INSTALL_DIR/.venv"
PYTHON="$INSTALL_DIR/.venv/bin/python"

"$PYTHON" -m pip install --upgrade pip setuptools wheel
"$PYTHON" -m pip install -e "$INSTALL_DIR"
"$PYTHON" -m wond init

chmod +x "$INSTALL_DIR"/*.command 2>/dev/null || true

if [ -z "${{WOND_INSTALL_DIR:-}}" ] && [ "$INSTALL_DIR" = "$LEGACY_INSTALL_DIR" ] && [ ! -e "$SYSTEM_INSTALL_DIR" ]; then
  if ln -s "$INSTALL_REAL" "$SYSTEM_INSTALL_DIR" 2>/dev/null; then
    echo "Applications link: $SYSTEM_INSTALL_DIR -> $INSTALL_REAL"
  else
    echo "Skipped Applications link; Wond is installed at $INSTALL_DIR."
  fi
fi

echo
echo "Wond is installed."
echo "Config: $INSTALL_DIR/config.json"
echo "Dashboard command: $INSTALL_DIR/Start Wond Dashboard.command"
echo

LOAD_SERVICES="n"
if [ -t 0 ]; then
  read -r -p "Load Wond background services now? [y/N] " LOAD_SERVICES
fi
case "$LOAD_SERVICES" in
  y|Y|yes|YES)
    "$PYTHON" -m wond install-dashboard-agent --load
    "$PYTHON" -m wond install-sync-agent --load
    "$PYTHON" -m wond install-agent --load
    echo "Background services loaded."
    open "http://127.0.0.1:8787" >/dev/null 2>&1 || true
    ;;
  *)
    echo "Skipped background services. Run 'Install Wond Services.command' later if needed."
    ;;
esac

echo
echo "Done. You can close this window."
"""


def update_command(version: str) -> str:
    managed_dirs = " ".join(UPDATE_MANAGED_DIRS)
    managed_files = "".join(f'  "{name}"\n' for name in UPDATE_MANAGED_FILES)
    return f"""#!/bin/bash
set -euo pipefail

VERSION="{version}"
PACKAGE_DIR="$(cd "$(dirname "$0")" && pwd)"
PAYLOAD_DIR="$PACKAGE_DIR/payload"
SYSTEM_INSTALL_DIR="/Applications/Wond"
LEGACY_INSTALL_DIR="$HOME/Applications/Wond"
INSTALL_DIR="${{WOND_INSTALL_DIR:-}}"

if [ -z "$INSTALL_DIR" ]; then
  if [ -d "$SYSTEM_INSTALL_DIR/wond" ]; then
    INSTALL_DIR="$SYSTEM_INSTALL_DIR"
  elif [ -d "$LEGACY_INSTALL_DIR/wond" ]; then
    INSTALL_DIR="$LEGACY_INSTALL_DIR"
  else
    INSTALL_DIR="$SYSTEM_INSTALL_DIR"
  fi
fi

echo "Updating Wond to $VERSION"
echo "Update package: $PACKAGE_DIR"
echo "Install directory: $INSTALL_DIR"

if [ ! -d "$PAYLOAD_DIR/wond" ]; then
  echo "This update package is incomplete: missing payload/wond."
  exit 1
fi

if [ ! -d "$INSTALL_DIR" ] || [ ! -d "$INSTALL_DIR/wond" ]; then
  echo "No existing Wond installation was found at $INSTALL_DIR."
  echo "Run install.command first, or set WOND_INSTALL_DIR to the existing Wond directory."
  echo "Checked default locations: $SYSTEM_INSTALL_DIR and $LEGACY_INSTALL_DIR."
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required. Install Python 3.11 or newer first."
  exit 1
fi

if ! command -v rsync >/dev/null 2>&1; then
  echo "rsync is required for safe updates on macOS."
  exit 1
fi

mkdir -p "$INSTALL_DIR"

MANAGED_DIRS=({managed_dirs})
MANAGED_FILES=(
{managed_files})
RSYNC_EXCLUDES=(
  --exclude ".DS_Store"
  --exclude "__pycache__/"
  --exclude "*.pyc"
  --exclude "build/"
  --exclude "DerivedData/"
  --exclude "xcuserdata/"
  --exclude "*.xcuserstate"
  --exclude "Signing.local.xcconfig"
)

for dir in "${{MANAGED_DIRS[@]}}"; do
  if [ -d "$PAYLOAD_DIR/$dir" ]; then
    mkdir -p "$INSTALL_DIR/$dir"
    rsync -a --delete "${{RSYNC_EXCLUDES[@]}}" "$PAYLOAD_DIR/$dir/" "$INSTALL_DIR/$dir/"
  fi
done

for file in "${{MANAGED_FILES[@]}}"; do
  if [ -f "$PAYLOAD_DIR/$file" ]; then
    rsync -a "$PAYLOAD_DIR/$file" "$INSTALL_DIR/$file"
  fi
done

chmod +x "$INSTALL_DIR"/*.command 2>/dev/null || true

if [ ! -x "$INSTALL_DIR/.venv/bin/python" ]; then
  python3 -m venv "$INSTALL_DIR/.venv"
fi
PYTHON="$INSTALL_DIR/.venv/bin/python"

"$PYTHON" -m pip install --upgrade pip setuptools wheel
"$PYTHON" -m pip install -e "$INSTALL_DIR"
"$PYTHON" -m wond init

reload_failed=0
if [ -f "$HOME/Library/LaunchAgents/com.local.wond-dashboard.plist" ]; then
  "$PYTHON" -m wond install-dashboard-agent --load || reload_failed=1
fi
if [ -f "$HOME/Library/LaunchAgents/com.local.wond-sync.plist" ]; then
  "$PYTHON" -m wond install-sync-agent --load || reload_failed=1
fi
if [ -f "$HOME/Library/LaunchAgents/com.local.wond-agent.plist" ]; then
  "$PYTHON" -m wond install-agent --load || reload_failed=1
fi

echo
"$PYTHON" -m wond --version
echo "Wond has been updated."
echo "Protected local files were not replaced: config.json, data/, and machine-local LaunchAgent state."
echo "The existing .venv was reused; dependency metadata may have been updated for this Wond version."
if [ "$reload_failed" -ne 0 ]; then
  echo "Update finished, but one or more background services could not be reloaded."
  echo "Run 'Install Wond Services.command' from $INSTALL_DIR if needed."
else
  echo "Existing Wond background services were reloaded if they were installed."
fi
echo
echo "Done. You can close this window."
"""


def start_dashboard_command() -> str:
    return """#!/bin/bash
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$INSTALL_DIR"
exec "$INSTALL_DIR/.venv/bin/python" -m wond dashboard --open
"""


def install_services_command() -> str:
    return """#!/bin/bash
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$INSTALL_DIR"
PYTHON="$INSTALL_DIR/.venv/bin/python"

"$PYTHON" -m wond install-dashboard-agent --load
"$PYTHON" -m wond install-sync-agent --load
"$PYTHON" -m wond install-agent --load

open "http://127.0.0.1:8787" >/dev/null 2>&1 || true
echo "Wond services loaded."
"""


def doctor_command() -> str:
    return """#!/bin/bash
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$INSTALL_DIR"
exec "$INSTALL_DIR/.venv/bin/python" -m wond doctor
"""


def stop_services_command() -> str:
    return """#!/bin/bash
set -euo pipefail

for LABEL in com.local.wond-dashboard com.local.wond-sync com.local.wond-agent; do
  launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
done

echo "Wond services stopped if they were loaded."
"""


def write_release_helpers(package_root: Path, version: str) -> None:
    write_executable(package_root / "install.command", install_command(version))
    write_executable(package_root / "Start Wond Dashboard.command", start_dashboard_command())
    write_executable(package_root / "Install Wond Services.command", install_services_command())
    write_executable(package_root / "Run Wond Doctor.command", doctor_command())
    write_executable(package_root / "Stop Wond Services.command", stop_services_command())


def write_update_helpers(update_root: Path, version: str) -> None:
    write_executable(update_root / "Update Wond.command", update_command(version))
    (update_root / "README.txt").write_text(
        "\n".join(
            [
                f"Wond {version} update package",
                "",
                "Double-click Update Wond.command to update an existing Wond install.",
                "",
                "The updater replaces release-managed app files only. It does not replace",
                "config.json, data/, local databases, reports, mobile sync imports,",
                "speaker samples, model caches, or other runtime files under data/.",
                "The existing .venv is reused; dependency metadata may be updated.",
                "",
                "Set WOND_INSTALL_DIR before running the command if Wond is not installed",
                "at /Applications/Wond or ~/Applications/Wond.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def zip_dir(src: Path, output: Path) -> None:
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(src.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(src.parent)
            archive.write(path, rel.as_posix())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checksum_file(archive_path: Path) -> Path:
    checksum_path = DIST_DIR / f"{archive_path.name}.sha256"
    checksum_path.unlink(missing_ok=True)
    digest = sha256(archive_path)
    checksum_path.write_text(f"{digest}  {archive_path.name}\n", encoding="utf-8")
    return checksum_path


def build(clean: bool = True) -> tuple[Path, Path, Path, Path]:
    version = package_version()
    package_name = f"Wond-{version}"
    package_root = STAGING_DIR / package_name
    update_root = STAGING_DIR / f"{package_name}-update"
    update_payload = update_root / "payload"
    if clean:
        shutil.rmtree(STAGING_DIR, ignore_errors=True)
    package_root.mkdir(parents=True, exist_ok=True)
    update_payload.mkdir(parents=True, exist_ok=True)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    copy_tracked_files(package_root)
    write_release_helpers(package_root, version)

    copy_tracked_files(update_payload)
    write_release_helpers(update_payload, version)
    write_update_helpers(update_root, version)

    archive_path = DIST_DIR / f"{package_name}-macos.zip"
    update_archive_path = DIST_DIR / f"{package_name}-macos-update.zip"
    archive_path.unlink(missing_ok=True)
    update_archive_path.unlink(missing_ok=True)
    zip_dir(package_root, archive_path)
    zip_dir(update_root, update_archive_path)

    checksum_path = checksum_file(archive_path)
    update_checksum_path = checksum_file(update_archive_path)
    return archive_path, checksum_path, update_archive_path, update_checksum_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Wond macOS release package.")
    parser.add_argument("--keep-staging", action="store_true", help="Keep .release/ after building.")
    args = parser.parse_args()

    archive_path, checksum_path, update_archive_path, update_checksum_path = build(clean=True)
    print(f"Archive: {archive_path}")
    print(f"SHA256: {checksum_path.read_text(encoding='utf-8').strip()}")
    print(f"Update archive: {update_archive_path}")
    print(f"Update SHA256: {update_checksum_path.read_text(encoding='utf-8').strip()}")
    if not args.keep_staging:
        shutil.rmtree(STAGING_DIR, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
