"""What the worker can do: analyze a page, download a format, fetch a subtitle, check a platform.

Imported only after :mod:`app.worker.guard` has locked the process down.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import sys
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yt_dlp
from yt_dlp.downloader.external import FFmpegFD
from yt_dlp.utils import DownloadError, GeoRestrictedError, UnsupportedError

from app.platforms.registry import host_matches
from app.services.formats import ALLOWED_PROTOCOLS, usable_streams
from app.worker import guard
from app.worker.classify import classify_message

Emit = Callable[[dict[str, Any]], None]

# FFmpeg is only ever used on files this worker has just written. Restricting its
# input protocols means a crafted "media" file (e.g. a playlist in disguise) cannot
# make FFmpeg open network connections or other protocols on our behalf.
FFMPEG_INPUT_RULES = ["-protocol_whitelist", "file,pipe,crypto,data"]

THUMBNAIL_MAX_BYTES = 5 * 1024 * 1024
THUMBNAIL_TARGET_WIDTH = 960
_IMAGE_SIGNATURES: tuple[tuple[bytes, int, str, str], ...] = (
    (b"\xff\xd8\xff", 0, "jpg", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", 0, "png", "image/png"),
    (b"GIF87a", 0, "gif", "image/gif"),
    (b"GIF89a", 0, "gif", "image/gif"),
    (b"WEBP", 8, "webp", "image/webp"),
    (b"ftypavif", 4, "avif", "image/avif"),
)
_AVAILABILITY_ERRORS = {
    "private": "private_content",
    "premium_only": "paywalled",
    "subscriber_only": "paywalled",
    "needs_auth": "login_required",
}
_STAGE_BY_POSTPROCESSOR = {
    "Merger": "merging",
    "EmbedSubtitle": "embedding_subtitles",
    "SubtitlesConvertor": "converting_subtitles",
    "FixupM3u8": "optimizing",
    "FixupM4a": "optimizing",
    "FixupStretched": "optimizing",
    "FixupTimestamp": "optimizing",
    "FixupDuration": "optimizing",
    "FixupDuplicateMoov": "optimizing",
    "VideoRemuxer": "optimizing",
}


class TaskError(Exception):
    """A failure with a known error code; ``detail`` is for logs only."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


# ------------------------------------------------------------------- yt-dlp plumbing
# What the YouTube reader prints when the platform answered with its age check and the
# reader went on to try another player. Anchored to the reader's own sentence, after
# its "[youtube] <id>: " prefix, so that words in an address or a title never match.
AGE_CHECK_NOTICE = re.compile(r"^\[youtube\] [\w-]{6,}: This video is age-restricted\b")


class _Log:
    """Collects yt-dlp output; nothing is ever printed to the protocol stream."""

    def __init__(self) -> None:
        self.lines: deque[str] = deque(maxlen=80)
        self.warnings: list[str] = []
        self.errors: list[str] = []
        # The reader reported that the platform put this video behind its age check.
        self.age_check = False

    def _add(self, level: str, message: str) -> None:
        if AGE_CHECK_NOTICE.search(message):
            self.age_check = True
        line = f"{level}: {message}"[:600]
        self.lines.append(line)
        print(line, file=sys.stderr, flush=True)

    def debug(self, message: str) -> None:
        if not message.startswith("[debug] "):
            self._add("info", message)

    def info(self, message: str) -> None:
        self._add("info", message)

    def warning(self, message: str) -> None:
        self.warnings.append(message[:300])
        self._add("warning", message)

    def error(self, message: str) -> None:
        self.errors.append(message[:600])
        self._add("error", message)


def _refuse_ffmpeg_download(self: Any, tmpfilename: str, info_dict: dict[str, Any]) -> None:
    raise TaskError("unsupported_stream", "stream would need FFmpeg to fetch it from the network; refused")


def disable_ffmpeg_network_downloader() -> None:
    """Never let FFmpeg fetch media from the network.

    yt-dlp can hand a stream URL to FFmpeg ("delegate to ffmpeg"). FFmpeg opens its
    own sockets, which would bypass the worker's network guard, so that path is
    removed entirely. FFmpeg remains available for local post-processing.
    """
    FFmpegFD._call_downloader = _refuse_ffmpeg_download  # type: ignore[method-assign]
    FFmpegFD.available = classmethod(lambda cls, path=None: False)  # type: ignore[method-assign,assignment]
    FFmpegFD.can_download = classmethod(lambda cls, info_dict, path=None: False)  # type: ignore[method-assign,assignment]


def base_options(task: dict[str, Any], log: _Log) -> dict[str, Any]:
    """Options shared by every task. The compliance rules of the service live here."""
    work_dir = str(task["work_dir"])
    options: dict[str, Any] = {
        # --- output: quiet, deterministic, confined to the task directory ---------
        "quiet": True,
        "noprogress": True,
        "logger": log,
        "color": "never",
        "paths": {"home": work_dir, "temp": work_dir},
        "cachedir": False,
        "overwrites": True,
        "updatetime": False,
        "continuedl": False,
        "restrictfilenames": True,
        "writethumbnail": False,
        "writeinfojson": False,
        "warn_when_outdated": False,
        # --- one video at a time ---------------------------------------------------
        "noplaylist": True,
        "playlist_items": "1",
        "extract_flat": False,
        "default_search": "error",
        "ignoreerrors": False,
        # --- never authenticate, never circumvent ------------------------------------
        # No cookies, accounts or .netrc are ever configured. No proxy and no geo
        # bypass (so regional blocks are respected), no DRM-protected formats, no
        # browser impersonation, and no JavaScript runtime for solving platform
        # anti-bot challenges.
        "usenetrc": False,
        "proxy": "",
        "geo_bypass": False,
        "allow_unplayable_formats": False,
        "ignore_no_formats_error": False,
        "enable_file_urls": False,
        "js_runtimes": {},
        "remote_components": [],
        # --- networking: Python sockets only (guarded), bounded retries ----------------
        "socket_timeout": int(task.get("socket_timeout", 15)),
        "retries": 3,
        "fragment_retries": 5,
        "extractor_retries": 2,
        "file_access_retries": 2,
        "concurrent_fragment_downloads": 4,
        "external_downloader": {"default": "native"},
        "hls_prefer_native": True,
        "external_downloader_args": {"ffmpeg_i": FFMPEG_INPUT_RULES},
        "postprocessor_args": {"ffmpeg_i": FFMPEG_INPUT_RULES},
    }
    if task.get("ffmpeg_path"):
        options["ffmpeg_location"] = task["ffmpeg_path"]
    return options


def describe_error(exc: BaseException, log: _Log, *, default: str) -> tuple[str, str]:
    """Return ``(code, detail)`` for any exception raised while running a task."""
    if isinstance(exc, TaskError):
        return exc.code, exc.detail
    detail = f"{type(exc).__name__}: {exc}"[:800]
    if guard.blocked_destinations():
        return "blocked_destination", f"{detail} | blocked: {guard.blocked_destinations()[:3]}"

    cause: BaseException | None = exc
    if isinstance(exc, DownloadError) and exc.exc_info and len(exc.exc_info) > 1:
        cause = exc.exc_info[1] or exc
    if isinstance(cause, UnsupportedError):
        return "unsupported_source", detail
    if isinstance(cause, GeoRestrictedError):
        return "geo_restricted", detail
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 27:
        return "file_too_large", detail
    text = " | ".join([str(exc), *log.errors[-3:]])
    return classify_message(text, default=default), detail


# Left over from an earlier format selection. If they survive into a new download,
# yt-dlp reuses the old choice (e.g. it would merge video into an audio-only request).
_SELECTION_KEYS = (
    "requested_formats", "requested_downloads", "requested_subtitles", "requested_entries",
    "filepath", "filename", "_filename", "infojson_filename",
)


def _reusable(info: dict[str, Any]) -> dict[str, Any]:
    """Metadata that can be processed again with a different format choice."""
    for key in _SELECTION_KEYS:
        info.pop(key, None)
    return info


# ----------------------------------------------------------------------------- analyze
# Some readers answer a platform's age question on their own, before anybody is asked:
# the Reddit reader sends Reddit's "I am over 18" cookie with every request, the
# Dailymotion reader switches the family filter off, others send a cookie, a form or a
# made-up birthday. An 18+ label from one of them therefore means that the platform asks
# first, and that question is not Lumora's to answer for a visitor.
#
# Keyed by the reader, with the domains of its pages where another reader can finish
# the job: a Reddit post that embeds a video from elsewhere keeps the address of the
# post and Reddit's label. The list is checked against the installed readers by
# tests/test_age_policy.py, so an update of yt-dlp that adds one is noticed.
AGE_QUESTION_ANSWERED_BY_READER: dict[str, tuple[str, ...]] = {
    # platforms of the built-in list
    "Reddit": ("reddit.com", "redd.it"),
    "Dailymotion": ("dailymotion.com", "dai.ly"),
    # websites outside the list (SOURCE_POLICY=open, or added by an administrator)
    "CDA": (),
    "PornHub": (),
    "VideoPress": (),
    "YouPorn": (),
}


def _reader_answered_an_age_question(info: dict[str, Any]) -> bool:
    if info.get("extractor_key") in AGE_QUESTION_ANSWERED_BY_READER:
        return True
    domains = [domain for group in AGE_QUESTION_ANSWERED_BY_READER.values() for domain in group]
    for key in ("webpage_url", "original_url"):
        address = info.get(key)
        try:
            host = (urlsplit(address).hostname or "") if isinstance(address, str) else ""
        except ValueError:
            continue
        if host and any(host_matches(host, domain) for domain in domains):
            return True
    return False


def enforce_content_policy(info: dict[str, Any], limits: dict[str, Any], *, age_check: bool = False) -> None:
    """Refuse anything that isn't a plain, public, on-demand video.

    About age, the platform decides. ``age_limit`` is a label, and many platforms put
    "18+" on videos they give to everybody (sensitive, mature, explicit): the label
    alone declines nothing. What declines a video is the platform asking for a
    sign-in or an age confirmation. That shows in three ways:

    * ``availability`` says an account is needed and the video carries the label;
    * the reader's log says so (``age_check``): it met the platform's age check and
      went on to read the video through another player;
    * the reader is one that answers the platform's age question by itself, and the
      video carries the label (``AGE_QUESTION_ANSWERED_BY_READER``).

    In all three cases the reader may well have got the video. It is not handed out.
    """
    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming", "post_live"):
        raise TaskError("live_stream", f"live_status={info.get('live_status')}")

    age_limit = info.get("age_limit")
    adult_label = isinstance(age_limit, (int, float)) and not isinstance(age_limit, bool) and age_limit >= 18

    availability = info.get("availability")
    if availability in _AVAILABILITY_ERRORS:
        code = _AVAILABILITY_ERRORS[availability]
        if code == "login_required" and (adult_label or age_check):
            code = "age_restricted"  # the sign-in the platform asks for is its age check
        raise TaskError(code, f"availability={availability} age_limit={age_limit}")
    if age_check:
        raise TaskError("age_restricted", "the reader reported the platform's age check")
    if adult_label and _reader_answered_an_age_question(info):
        raise TaskError(
            "age_restricted",
            f"age_limit={age_limit} reader={info.get('extractor_key')}: the platform asks for an age confirmation",
        )

    # The operator's stricter rule, off by default: decline on the label itself.
    if limits.get("block_age_restricted", False) and adult_label:
        raise TaskError("age_rating_blocked", f"age_limit={age_limit}")

    duration = info.get("duration")
    max_duration = limits.get("max_duration_seconds")
    if max_duration and isinstance(duration, (int, float)) and duration > max_duration:
        raise TaskError("too_long", f"duration={duration}")

    streams, total, drm = usable_streams(info)
    if not streams:
        if total and drm == total:
            raise TaskError("drm_protected", "every format is DRM protected")
        protocols = sorted({str(f.get("protocol")) for f in info.get("formats") or [] if isinstance(f, dict)})
        allowed = sorted(ALLOWED_PROTOCOLS)
        raise TaskError("no_formats", f"no usable formats; protocols seen {protocols}, allowed {allowed}")


def _pick_thumbnail_url(info: dict[str, Any]) -> str | None:
    candidates = [
        t for t in (info.get("thumbnails") or [])
        if isinstance(t, dict) and isinstance(t.get("url"), str)
    ]
    sized = [t for t in candidates if isinstance(t.get("width"), (int, float)) and t["width"] > 0]
    if sized:
        large_enough = [t for t in sized if t["width"] >= THUMBNAIL_TARGET_WIDTH]
        pick = min(large_enough, key=lambda t: t["width"]) if large_enough else max(sized, key=lambda t: t["width"])
        return str(pick["url"])
    url = info.get("thumbnail")
    if isinstance(url, str):
        return url
    return str(candidates[-1]["url"]) if candidates else None


def _sniff_image(data: bytes) -> tuple[str, str] | None:
    for signature, offset, ext, content_type in _IMAGE_SIGNATURES:
        if data[offset : offset + len(signature)] == signature:
            return ext, content_type
    return None


def fetch_thumbnail(ydl: Any, info: dict[str, Any], work_dir: Path, log: _Log) -> dict[str, str] | None:
    """Copy the poster image next to the metadata so the browser never has to hotlink it."""
    url = _pick_thumbnail_url(info)
    if not url or not url.lower().startswith(("http://", "https://")):
        return None
    try:
        response = ydl.urlopen(url)
        try:
            data = response.read(THUMBNAIL_MAX_BYTES + 1)
        finally:
            response.close()
    except Exception as exc:  # a missing poster must never fail the analysis
        log.warning(f"thumbnail unavailable: {type(exc).__name__}: {exc}")
        return None
    if not data or len(data) > THUMBNAIL_MAX_BYTES:
        log.warning("thumbnail skipped: empty or too large")
        return None
    kind = _sniff_image(data)
    if kind is None:
        log.warning("thumbnail skipped: not a supported image type")
        return None
    ext, content_type = kind
    (work_dir / f"thumb.{ext}").write_bytes(data)
    return {"file": f"thumb.{ext}", "content_type": content_type}


def analyze(task: dict[str, Any], emit: Emit, log: _Log) -> dict[str, Any]:
    work_dir = Path(task["work_dir"])
    notices: list[str] = []
    with yt_dlp.YoutubeDL(base_options(task, log) | {"skip_download": True}) as ydl:
        raw = ydl.extract_info(task["url"], download=False)
        if not raw:
            raise TaskError("unsupported_source", "extractor returned nothing")
        info = ydl.sanitize_info(raw)
        if info.get("_type") in ("playlist", "multi_video"):
            entries = [entry for entry in (info.get("entries") or []) if isinstance(entry, dict)]
            if not entries:
                raise TaskError("unsupported_source", "no playable entry in playlist")
            count = info.get("playlist_count")
            if (isinstance(count, int) and count > 1) or len(entries) > 1:
                notices.append("playlist_first_item")
            info = entries[0]
        # Keep what the source offers, not what yt-dlp happened to pick by default:
        # a later download must select from ``formats`` afresh (see ``_reusable``).
        info = _reusable(ydl.sanitize_info(info, remove_private_keys=True))
        enforce_content_policy(info, task.get("limits") or {}, age_check=log.age_check)
        thumbnail = fetch_thumbnail(ydl, info, work_dir, log)

    if info.get("extractor_key") == "HTML5MediaEmbed" and isinstance(info.get("title"), str):
        info["title"] = re.sub(r" \(1\)$", "", info["title"])  # numbering added for single embeds
    (work_dir / "info.json").write_text(json.dumps(info), encoding="utf-8")
    return {"notices": notices, "thumbnail": thumbnail}


# ---------------------------------------------------------------------------- download
def _free_bytes(directory: Path) -> int | None:
    try:
        return shutil.disk_usage(directory).free
    except OSError:
        return None


class _Progress:
    """Aggregates per-format download callbacks into one honest overall figure."""

    MIN_INTERVAL = 0.2

    def __init__(
        self, emit: Emit, parts: list[dict[str, Any]], max_bytes: int | None,
        *, work_dir: Path | None = None, min_free_bytes: int = 0,
    ) -> None:
        self._work_dir = work_dir
        self._min_free = min_free_bytes
        self._last_space_check = 0.0
        self._emit = emit
        self._order = [str(p["format_id"]) for p in parts]
        self._kind = {str(p["format_id"]): str(p.get("kind") or "media") for p in parts}
        self._expected = {str(p["format_id"]): p.get("size") for p in parts}
        self._done: dict[str, int] = {}
        self._total: dict[str, int | None] = {}
        self._fraction: dict[str, float | None] = {}
        self._finished: set[str] = set()
        self._max_bytes = max_bytes
        self._last_emit = 0.0

    def hook(self, d: dict[str, Any]) -> None:
        format_id = str((d.get("info_dict") or {}).get("format_id") or "")
        if format_id not in self._kind:
            return  # subtitle or other side file
        status = d.get("status")
        downloaded = int(d.get("downloaded_bytes") or 0)
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        total = int(total) if total else None
        self._done[format_id] = downloaded
        self._total[format_id] = total

        if status == "finished":
            self._finished.add(format_id)
            self._fraction[format_id] = 1.0
        elif total:
            self._fraction[format_id] = min(1.0, downloaded / total)
        elif d.get("fragment_count"):
            self._fraction[format_id] = min(1.0, (d.get("fragment_index") or 0) / d["fragment_count"])
        else:
            self._fraction[format_id] = None

        if self._max_bytes:
            known_total = sum(t for t in self._total.values() if t)
            if sum(self._done.values()) > self._max_bytes or known_total > self._max_bytes:
                raise TaskError("file_too_large", f"exceeds {self._max_bytes} bytes")

        now = time.monotonic()
        if self._min_free and self._work_dir is not None and now - self._last_space_check >= 1.0:
            # Stop before the disk is full: other services on this machine need it too.
            self._last_space_check = now
            free = _free_bytes(self._work_dir)
            if free is not None and free < self._min_free:
                raise TaskError("insufficient_storage", f"{free} bytes free, floor is {self._min_free}")
        if status != "finished" and now - self._last_emit < self.MIN_INTERVAL:
            return
        self._last_emit = now
        speed, eta = d.get("speed"), d.get("eta")
        self._emit({
            "event": "progress",
            "stage": "downloading",
            "part": self._order.index(format_id) + 1,
            "parts": len(self._order),
            "part_kind": self._kind[format_id],
            "percent": self._overall_percent(),
            "downloaded_bytes": sum(self._done.values()),
            "total_bytes": self._overall_total(),
            "speed_bps": float(speed) if speed else None,
            "eta_seconds": float(eta) if eta is not None and status != "finished" else None,
        })

    def _weight(self, format_id: str) -> int | None:
        return self._total.get(format_id) or self._expected.get(format_id)

    def _overall_total(self) -> int | None:
        weights = [self._weight(f) for f in self._order]
        return sum(w for w in weights if w) if all(weights) else None

    def _overall_percent(self) -> float | None:
        weights = [self._weight(f) for f in self._order]
        if all(weights):
            done = sum(
                (weights[i] or 0) if f in self._finished else min(self._done.get(f, 0), weights[i] or 0)
                for i, f in enumerate(self._order)
            )
            return round(min(100.0, 100.0 * done / sum(w or 0 for w in weights)), 1)
        fractions = [self._fraction.get(f, 0.0) if f in self._done else 0.0 for f in self._order]
        if any(fraction is None for fraction in fractions):
            return None  # size unknown: report bytes and speed, but no made-up percentage
        return round(100.0 * sum(f or 0.0 for f in fractions) / len(self._order), 1)


def _postprocessor_hook(emit: Emit) -> Callable[[dict[str, Any]], None]:
    def hook(d: dict[str, Any]) -> None:
        stage = _STAGE_BY_POSTPROCESSOR.get(str(d.get("postprocessor")))
        if stage and d.get("status") == "started":
            emit({"event": "stage", "stage": "processing", "detail": stage})

    return hook


def _inside(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def _subtitle_options(tracks: list[dict[str, Any]], target: str) -> dict[str, Any]:
    order = [target, *[e for e in ("vtt", "srt", "ass", "ssa", "ttml", "dfxp", "tt", "lrc") if e != target]]
    return {
        "writesubtitles": any(t["kind"] == "manual" for t in tracks),
        "writeautomaticsub": any(t["kind"] == "auto" for t in tracks),
        "subtitleslangs": [re.escape(str(t["language"])) for t in tracks],
        "subtitlesformat": "/".join(order),
    }


def _verify_selection(result: dict[str, Any], record: dict[str, Any], spec: str) -> None:
    """Make sure the streams that were fetched are exactly the ones that were chosen.

    A merged download lists its parts in ``requested_formats``; a single-stream
    download has no such list. Either way the result must match ``spec``.
    """
    merged = record.get("requested_formats")
    if merged:
        got = "+".join(str(f.get("format_id")) for f in merged)
    else:
        got = str(record.get("format_id") or result.get("format_id"))
    if got != spec:
        raise TaskError("download_failed", f"asked for formats {spec!r} but fetched {got!r}")


def download(task: dict[str, Any], emit: Emit, log: _Log) -> dict[str, Any]:
    work_dir = Path(task["work_dir"])
    limits = task.get("limits") or {}
    max_bytes = limits.get("max_file_bytes")
    info = _reusable(json.loads(Path(task["info_path"]).read_text(encoding="utf-8")))
    parts: list[dict[str, Any]] = task["parts"]
    embed: list[dict[str, Any]] = task.get("embed_subtitles") or []

    known_sizes = [int(p["size"]) for p in parts if p.get("size")]
    if max_bytes and len(known_sizes) == len(parts) and sum(known_sizes) > max_bytes:
        raise TaskError("file_too_large", f"expected {sum(known_sizes)} bytes")

    min_free = int(limits.get("min_free_bytes") or 0)
    free = _free_bytes(work_dir)
    if min_free and free is not None and free < min_free:
        raise TaskError("insufficient_storage", f"{free} bytes free before the download, floor is {min_free}")
    progress = _Progress(emit, parts, max_bytes, work_dir=work_dir, min_free_bytes=min_free)
    options = base_options(task, log) | {
        "format": task["format_spec"],
        "outtmpl": {"default": "media.%(ext)s"},
        "progress_hooks": [progress.hook],
        "postprocessor_hooks": [_postprocessor_hook(emit)],
    }
    if len(parts) > 1 and task.get("container"):
        options["merge_output_format"] = task["container"]
    if embed:
        target = "vtt" if task.get("container") == "webm" else "srt"
        options |= _subtitle_options(embed, target)
        options["postprocessors"] = [
            {"key": "FFmpegSubtitlesConvertor", "format": target, "when": "before_dl"},
            {"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False},
        ]

    emit({"event": "stage", "stage": "downloading", "detail": None})
    with yt_dlp.YoutubeDL(options) as ydl:
        result = ydl.process_ie_result(copy.deepcopy(info), download=True)

    downloads = (result or {}).get("requested_downloads") or []
    if not downloads or not downloads[0].get("filepath"):
        raise TaskError("download_failed", "no output file was reported")
    _verify_selection(result or {}, downloads[0], str(task["format_spec"]))
    final = Path(downloads[0]["filepath"])
    if not _inside(final, work_dir) or not final.is_file():
        raise TaskError("download_failed", f"unexpected output path {final}")
    size = final.stat().st_size
    if size <= 0:
        raise TaskError("download_failed", "output file is empty")
    if max_bytes and size > max_bytes:
        raise TaskError("file_too_large", f"output is {size} bytes")

    # A subtitle file that is still on disk was not embedded (the embedder removes
    # the ones it used), so only report what really ended up inside the video.
    embedded: list[str] = []
    requested = (result or {}).get("requested_subtitles") or {}
    for track in embed:
        entry = requested.get(track["language"]) or {}
        sidecar = entry.get("filepath")
        if sidecar and not Path(sidecar).exists():
            embedded.append(str(track["language"]))

    for leftover in work_dir.iterdir():
        if leftover.is_file() and leftover != final:
            leftover.unlink(missing_ok=True)

    return {
        "file": final.name,
        "size": size,
        "ext": final.suffix.lstrip(".").lower(),
        "embedded_subtitles": embedded,
        "subtitles_requested": [str(t["language"]) for t in embed],
    }


# ---------------------------------------------------------------------------- subtitle
def _looks_like(target: str, path: Path) -> bool:
    head = path.read_bytes()[:4096].lstrip(b"\xef\xbb\xbf").lstrip()
    if target == "vtt":
        return head.startswith(b"WEBVTT")
    return b"-->" in head


def subtitle(task: dict[str, Any], emit: Emit, log: _Log) -> dict[str, Any]:
    work_dir = Path(task["work_dir"])
    info = _reusable(json.loads(Path(task["info_path"]).read_text(encoding="utf-8")))
    language, kind = str(task["language"]), str(task["kind"])
    source_ext, target = str(task["source_ext"]), str(task["target"])

    options = base_options(task, log) | {
        "skip_download": True,
        "writesubtitles": kind == "manual",
        "writeautomaticsub": kind == "auto",
        "subtitleslangs": [re.escape(language)],
        "subtitlesformat": source_ext,
        "outtmpl": {"default": "subtitle.%(ext)s"},
    }
    if source_ext != target:
        options["postprocessors"] = [{"key": "FFmpegSubtitlesConvertor", "format": target, "when": "before_dl"}]

    with yt_dlp.YoutubeDL(options) as ydl:
        result = ydl.process_ie_result(copy.deepcopy(info), download=True)

    entry = ((result or {}).get("requested_subtitles") or {}).get(language) or {}
    filepath = entry.get("filepath")
    if not filepath:
        raise TaskError("subtitle_unavailable", f"no file produced for {language!r}")
    path = Path(filepath)
    if not _inside(path, work_dir) or not path.is_file() or path.stat().st_size == 0:
        raise TaskError("subtitle_unavailable", f"missing or empty subtitle file {path.name}")
    if path.suffix.lstrip(".").lower() != target or not _looks_like(target, path):
        raise TaskError("subtitle_unavailable", f"{path.name} is not valid {target}")

    final = work_dir / task["output_name"]
    path.replace(final)
    for leftover in work_dir.glob("subtitle.*"):
        if leftover != final:
            leftover.unlink(missing_ok=True)
    return {"file": final.name, "size": final.stat().st_size}


# ------------------------------------------------------------------------------ compat
MAX_SAMPLE_LINKS = 3


def _sample_worthy(test: dict[str, Any]) -> bool:
    """A test link of the extractor's maintainers that points to one plain, public video.

    Links with an 18+ label are left out whatever BLOCK_AGE_RESTRICTED says: a check
    should learn about the platform from an ordinary video.
    """
    info = test.get("info_dict")
    return (
        not test.get("only_matching") and not test.get("skip")
        and not any(str(key).startswith("playlist") for key in test)
        and isinstance(info, dict) and bool(info.get("id")) and not info.get("is_live")
        and info.get("live_status") in (None, "not_live", "was_live")
        and not (info.get("age_limit") or 0) >= 18
    )


def find_integrations(domains: list[str], url: str | None) -> tuple[list[str], list[str]]:
    """Dedicated extractors for a website, and sample links to try when none was given.

    The generic reader (which looks for a video file or player on any page) is not
    an integration and is left out.
    """
    from yt_dlp.extractor import gen_extractor_classes

    own = {domain.removeprefix("www.") for domain in domains}
    names: list[str] = []
    found: list[tuple[int, list[tuple[int, str]]]] = []  # per extractor: number of tests, [(rank, link)]
    for extractor in gen_extractor_classes():
        if extractor.ie_key() == "Generic":
            continue
        try:
            tests = list(extractor.get_testcases(include_onlymatching=True))
        except Exception:  # one broken extractor must not hide the others
            tests = []
        hit = False
        links: list[tuple[int, str]] = []
        for test in tests:
            test_url = test.get("url")
            if not isinstance(test_url, str):
                continue
            try:
                host = (urlsplit(test_url).hostname or "").lower()
            except ValueError:
                continue
            if not any(host_matches(host, domain) for domain in domains):
                continue
            hit = True
            if _sample_worthy(test):
                # The website's own address before its sub-domains (players, archives, mobile sites).
                links.append((0 if host.removeprefix("www.") in own else 1, test_url))
        if not hit and url is not None:
            try:
                hit = bool(extractor.suitable(url))
            except Exception:
                hit = False
        if hit:
            names.append(str(extractor.IE_NAME))
        if links:
            found.append((len(tests), sorted(links, key=lambda item: item[0])))
    # The main integration is the one with the most tests among those for the
    # website's own address. Two of its links come first; then one link of each
    # other integration, so that a third attempt covers a different kind of page.
    found.sort(key=lambda item: (item[1][0][0], -item[0]))
    ordered: list[str] = []
    if found:
        main = [link for _rank, link in found[0][1]]
        ordered = main[:2] + [links[0][1] for _size, links in found[1:]] + main[2:]
    return sorted(set(names))[:12], list(dict.fromkeys(ordered))[:MAX_SAMPLE_LINKS]


def _try_link(task: dict[str, Any], url: str) -> dict[str, Any]:
    """Read one link exactly as an analysis would, and say what was found."""
    log = _Log()
    started = time.monotonic()
    try:
        with yt_dlp.YoutubeDL(base_options(task, log) | {"skip_download": True}) as ydl:
            raw = ydl.extract_info(url, download=False)
            if not raw:
                raise TaskError("unsupported_source", "extractor returned nothing")
            info = ydl.sanitize_info(raw)
            if info.get("_type") in ("playlist", "multi_video"):
                entries = [entry for entry in (info.get("entries") or []) if isinstance(entry, dict)]
                if not entries:
                    raise TaskError("unsupported_source", "no playable entry in playlist")
                info = entries[0]
            info = ydl.sanitize_info(info, remove_private_keys=True)
            enforce_content_policy(info, task.get("limits") or {}, age_check=log.age_check)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:
        code, detail = describe_error(exc, log, default="extraction_failed")
        return {"url": url, "ok": False, "code": code, "detail": detail[:300],
                "seconds": round(time.monotonic() - started, 1)}
    streams, _total, _drm = usable_streams(info)
    heights = [stream.height for stream in streams if stream.height]
    subtitles = info.get("subtitles")
    title = info.get("title")
    return {
        "url": url, "ok": True,
        "extractor": str(info.get("extractor_key") or "Generic"),
        "title": title[:200] if isinstance(title, str) else None,
        "streams": len(streams),
        "video": sum(1 for stream in streams if stream.kind in ("muxed", "video")),
        "audio": sum(1 for stream in streams if stream.kind in ("muxed", "audio")),
        "max_height": max(heights) if heights else None,
        "subtitles": len(subtitles) if isinstance(subtitles, dict) else 0,
        "seconds": round(time.monotonic() - started, 1),
    }


def compat(task: dict[str, Any], emit: Emit, log: _Log) -> dict[str, Any]:
    """Check what this server can do with a website: is there an integration, does a link work?"""
    url = task.get("url") if isinstance(task.get("url"), str) else None
    fallback = task.get("fallback_url") if isinstance(task.get("fallback_url"), str) else None
    integrations, samples = find_integrations([str(d) for d in task.get("domains") or []], url)
    attempts: list[dict[str, Any]] = []
    # A link the administrator gave. Without one: the link that the previous check
    # of this website used (what worked then should work now), then the
    # integration's own sample links.
    links = [url] if url else list(dict.fromkeys(([fallback] if fallback else []) + samples))[:MAX_SAMPLE_LINKS]
    for link in links:
        attempts.append(_try_link(task, link))
        if attempts[-1]["ok"]:
            break
    return {
        "integrations": integrations, "attempts": attempts, "sample_links": bool(not url and samples),
        "previous_link": bool(not url and fallback and fallback not in samples),
    }


TASKS: dict[str, tuple[Callable[[dict[str, Any], Emit, _Log], dict[str, Any]], str]] = {
    "compat": (compat, "extraction_failed"),
    "analyze": (analyze, "extraction_failed"),
    "download": (download, "download_failed"),
    "subtitle": (subtitle, "subtitle_unavailable"),
}


def run(task: dict[str, Any], emit: Emit) -> None:
    """Run one task and emit exactly one terminal event (``result`` or ``error``)."""
    log = _Log()
    handler, default_error = TASKS[task["task"]]
    disable_ffmpeg_network_downloader()
    try:
        result = handler(task, emit, log)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:
        code, detail = describe_error(exc, log, default=default_error)
        emit({"event": "error", "code": code, "detail": detail})
        return
    emit({"event": "result", **result, "warnings": log.warnings[-5:]})
