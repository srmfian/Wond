from __future__ import annotations

import shutil
from pathlib import Path


COMMON_BIN_DIRS = (
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
    Path("/usr/bin"),
    Path("/bin"),
)


def find_executable(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for folder in COMMON_BIN_DIRS:
        candidate = folder / name
        if candidate.exists() and candidate.is_file():
            return str(candidate)
    return None
