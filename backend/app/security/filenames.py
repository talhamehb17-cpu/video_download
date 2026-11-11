"""Safe download file names and Content-Disposition headers."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
_RESERVED_RE = re.compile(r'[<>:"/\\|?*]')
_SPACE_RE = re.compile(r"\s+")
_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
_SAFE_EXT_RE = re.compile(r"^[a-z0-9]{1,5}$")
MAX_STEM_LENGTH = 120


def sanitize_stem(title: str | None, *, fallback: str = "video") -> str:
    """Turn an arbitrary (untrusted) title into a safe file-name stem.

    Keeps Unicode letters so non-English titles survive, but removes anything that
    could act as a path separator, a control/bidi character, or a reserved name on
    Windows, macOS or Linux.
    """
    text = unicodedata.normalize("NFC", title or "")
    text = _CONTROL_RE.sub("", text)
    text = _RESERVED_RE.sub(" ", text)
    text = _SPACE_RE.sub(" ", text).strip(" .")
    if len(text) > MAX_STEM_LENGTH:
        text = text[:MAX_STEM_LENGTH].rstrip(" .")
    if not text or text.lower() in _WINDOWS_RESERVED or set(text) <= {".", " "}:
        return fallback
    return text


def build_filename(title: str | None, ext: str, *, suffix: str | None = None, fallback: str = "video") -> str:
    """``"<title> (<suffix>).<ext>"`` with every part sanitised."""
    ext = ext.lower().lstrip(".")
    if not _SAFE_EXT_RE.match(ext):
        ext = "bin"
    stem = sanitize_stem(title, fallback=fallback)
    if suffix:
        clean_suffix = sanitize_stem(suffix, fallback="")
        if clean_suffix:
            stem = f"{stem} ({clean_suffix})"
    return f"{stem}.{ext}"


def _ascii_fallback(filename: str) -> str:
    stem, dot, ext = filename.rpartition(".")
    ascii_stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")
    ascii_stem = re.sub(r"[^A-Za-z0-9 ._()\-]", "", ascii_stem)
    ascii_stem = _SPACE_RE.sub(" ", ascii_stem).strip(" .") or "download"
    return f"{ascii_stem}{dot}{ext}"


def content_disposition(filename: str) -> str:
    """RFC 6266 header value: an ASCII fallback plus the UTF-8 name."""
    fallback = _ascii_fallback(filename)
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"
