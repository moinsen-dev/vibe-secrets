"""Best-effort cross-platform clipboard copy, no extra deps."""

from __future__ import annotations

import shutil
import subprocess
import sys


def copy_to_clipboard(value: str) -> bool:
    """Return True on success."""
    candidates: list[list[str]] = []
    if sys.platform == "darwin":
        candidates.append(["pbcopy"])
    elif sys.platform.startswith("linux"):
        candidates.append(["wl-copy"])
        candidates.append(["xclip", "-selection", "clipboard"])
        candidates.append(["xsel", "-b", "-i"])
    elif sys.platform == "win32":
        candidates.append(["clip"])

    for cmd in candidates:
        exe = cmd[0]
        if shutil.which(exe) is None:
            continue
        try:
            p = subprocess.run(
                cmd,
                input=value.encode("utf-8"),
                check=False,
                timeout=5,
            )
            if p.returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            continue
    return False
