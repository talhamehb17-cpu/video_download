"""Locate FFmpeg. It is required for merging, container fix-ups and subtitle work."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path


def locate_ffmpeg(configured: str | None = None) -> str | None:
    """Return the FFmpeg executable to use, or ``None`` if there is none.

    Order: ``FFMPEG_PATH`` -> ``ffmpeg`` on ``PATH`` -> the binary bundled with the
    optional ``imageio-ffmpeg`` package (a convenience for local development).
    """
    if configured:
        found = shutil.which(configured)
        if found:
            return found
        return configured if Path(configured).is_file() else None
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        return None


def ffmpeg_version(path: str | None) -> str | None:
    if not path:
        return None
    try:
        out = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=10, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"ffmpeg version (\S+)", out)
    return match.group(1) if match else None
