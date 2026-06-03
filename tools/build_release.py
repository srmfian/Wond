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


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )


def package_version() -> str:
    tree = ast.parse((ROOT / "wond" / "__init__.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__version__":
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        return node.value.value
    raise RuntimeError("Could not find wond.__version__")


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
INSTALL_DIR="${{WOND_INSTALL_DIR:-$HOME/Applications/Wond_Local}}"
SOURCE_REAL="$(cd "$SOURCE_DIR" && pwd -P)"

echo "Installing Wond $VERSION"
echo "Source: $SOURCE_DIR"
echo "Install directory: $INSTALL_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required. Install Python 3.11 or newer first."
  exit 1
fi

mkdir -p "$INSTALL_DIR"
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


def build(clean: bool = True) -> tuple[Path, Path]:
    version = package_version()
    package_name = f"Wond-{version}"
    package_root = STAGING_DIR / package_name
    if clean:
        shutil.rmtree(STAGING_DIR, ignore_errors=True)
    package_root.mkdir(parents=True, exist_ok=True)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    copy_tracked_files(package_root)
    write_release_helpers(package_root, version)

    archive_path = DIST_DIR / f"{package_name}-macos.zip"
    checksum_path = DIST_DIR / f"{archive_path.name}.sha256"
    archive_path.unlink(missing_ok=True)
    checksum_path.unlink(missing_ok=True)
    zip_dir(package_root, archive_path)

    digest = sha256(archive_path)
    checksum_path.write_text(f"{digest}  {archive_path.name}\n", encoding="utf-8")
    return archive_path, checksum_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Wond macOS release package.")
    parser.add_argument("--keep-staging", action="store_true", help="Keep .release/ after building.")
    args = parser.parse_args()

    archive_path, checksum_path = build(clean=True)
    print(f"Archive: {archive_path}")
    print(f"SHA256: {checksum_path.read_text(encoding='utf-8').strip()}")
    if not args.keep_staging:
        shutil.rmtree(STAGING_DIR, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
