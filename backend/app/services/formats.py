"""Turn raw extractor metadata into the quality and subtitle choices shown to users.

Pure functions over plain dictionaries: no network, no yt-dlp import. Both the API
process and the media worker use this module, so the worker downloads exactly what
the API offered. Only formats the source really provides are listed; nothing is
transcoded or up-scaled.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

# Protocols handled by yt-dlp's native (Python) downloaders, whose connections pass
# through the worker's socket guard. Anything else (RTMP, RTSP, MMS...) would need
# an external program and is not offered.
ALLOWED_PROTOCOLS = frozenset({"http", "https", "m3u8", "m3u8_native", "http_dash_segments", "ism"})

AUDIO_EXTS = frozenset({"m4a", "mp3", "aac", "ogg", "oga", "opus", "flac", "wav", "weba", "mka", "wma"})
MP4_VIDEO_EXTS = frozenset({"mp4", "m4v", "mov"})
MP4_AUDIO_EXTS = frozenset({"m4a", "mp4", "aac", "mov"})
WEBM_AUDIO_EXTS = frozenset({"webm", "weba"})
EMBED_CONTAINERS = frozenset({"mp4", "mov", "m4a", "webm", "mkv", "mka"})
CONTAINER_ORDER = {"mp4": 0, "m4v": 1, "mov": 2, "webm": 3, "mkv": 4}

# Subtitle source formats that can be delivered as SRT or WebVTT.
SUBTITLE_SOURCE_EXTS = ("vtt", "srt", "ass", "ssa", "ttml", "dfxp", "tt", "lrc")
SUBTITLE_TARGETS = ("srt", "vtt")
_NON_SUBTITLE_KEYS = frozenset({"live_chat", "comments", "danmaku", "rechat"})

MAX_VIDEO_OPTIONS = 18
MAX_AUDIO_OPTIONS = 3
MAX_SUBTITLE_TRACKS = 250
RECOMMENDED_MAX_HEIGHT = 1080


@dataclass(frozen=True)
class Stream:
    """One usable format from the source, normalised."""

    format_id: str
    kind: str                 # "muxed" | "video" | "audio"
    ext: str
    protocol: str
    rank: int                 # position in the extractor's worst -> best ordering
    height: int | None = None
    width: int | None = None
    fps: float | None = None
    tbr: float | None = None  # total bitrate, kbit/s
    vcodec: str | None = None
    acodec: str | None = None
    size: int | None = None
    size_is_estimate: bool = False
    note: str | None = None
    dynamic_range: str | None = None
    language: str | None = None
    language_preference: int = 0


@dataclass(frozen=True)
class QualityChoice:
    """A downloadable option: one stream, or a video stream plus an audio stream."""

    id: str
    kind: str                 # "video" | "audio"
    label: str
    container: str
    format_spec: str          # yt-dlp format selector; never sent to clients
    parts: tuple[Stream, ...]
    height: int | None
    width: int | None
    fps: float | None
    video_codec: str | None
    audio_codec: str | None
    has_audio: bool
    requires_merge: bool
    size: int | None
    size_is_estimate: bool
    bitrate_kbps: float | None
    dynamic_range: str | None
    can_embed_subtitles: bool
    exceeds_limit: bool = False
    recommended: bool = False


@dataclass(frozen=True)
class SubtitleChoice:
    id: str
    language: str
    name: str | None
    kind: str                         # "manual" | "auto"
    source_exts: tuple[str, ...]      # what the source offers (convertible ones only)
    formats: tuple[str, ...]          # what we can deliver: subset of ("srt", "vtt")
    embeddable: bool = False

    def source_for(self, target: str) -> str:
        """Best source format to fetch when the user wants ``target``."""
        order = (target, *[e for e in SUBTITLE_SOURCE_EXTS if e != target])
        for ext in order:
            if ext in self.source_exts:
                return ext
        raise ValueError(f"no usable subtitle source for {target}")


@dataclass
class FormatSummary:
    qualities: list[QualityChoice] = field(default_factory=list)
    drm_only: bool = False
    total_formats: int = 0


# --------------------------------------------------------------------------- helpers
def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number > 0 else None


def _int(value: Any) -> int | None:
    number = _num(value)
    return int(number) if number is not None else None


def _codec(value: Any) -> str | None:
    """yt-dlp uses the string ``"none"`` for "no such track" and ``None`` for unknown."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().lower()


_VIDEO_CODEC_NAMES = (
    ("avc", "H.264"), ("h264", "H.264"), ("hev", "H.265"), ("hvc", "H.265"), ("h265", "H.265"),
    ("vp09", "VP9"), ("vp9", "VP9"), ("vp08", "VP8"), ("vp8", "VP8"), ("av01", "AV1"), ("av1", "AV1"),
    ("theora", "Theora"), ("mp4v", "MPEG-4"), ("dvh", "Dolby Vision"),
)
_AUDIO_CODEC_NAMES = (
    ("mp4a", "AAC"), ("aac", "AAC"), ("opus", "Opus"), ("vorbis", "Vorbis"), ("mp3", "MP3"),
    ("ec-3", "E-AC-3"), ("eac3", "E-AC-3"), ("ac-3", "AC-3"), ("ac3", "AC-3"), ("flac", "FLAC"),
    ("alac", "ALAC"), ("pcm", "PCM"),
)


def codec_name(codec: str | None, *, audio: bool) -> str | None:
    if not codec or codec == "none":
        return None
    for prefix, name in _AUDIO_CODEC_NAMES if audio else _VIDEO_CODEC_NAMES:
        if codec.startswith(prefix):
            return name
    return None


def _estimate_size(fmt: dict[str, Any], duration: float | None) -> tuple[int | None, bool]:
    exact = _int(fmt.get("filesize"))
    if exact:
        return exact, False
    approx = _int(fmt.get("filesize_approx"))
    if approx:
        return approx, True
    tbr = _num(fmt.get("tbr"))
    if tbr and duration:
        return int(tbr * 1000 / 8 * duration), True
    return None, False


def _clean_note(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", "", value)).strip()
    return text[:40] or None


def _to_stream(fmt: dict[str, Any], rank: int, duration: float | None) -> Stream | None:
    format_id = fmt.get("format_id")
    if not isinstance(format_id, str) or not format_id or not re.fullmatch(r"[A-Za-z0-9._\-]{1,80}", format_id):
        # Ids are passed back to yt-dlp as a selector; refuse anything that isn't a plain token.
        return None
    if fmt.get("has_drm"):
        return None
    if not (fmt.get("url") or fmt.get("manifest_url") or fmt.get("fragments")):
        return None
    protocol = str(fmt.get("protocol") or "")
    if protocol not in ALLOWED_PROTOCOLS:
        return None
    ext = str(fmt.get("ext") or "").lower()
    if not re.fullmatch(r"[a-z0-9]{1,5}", ext) or ext == "mhtml":
        return None

    vcodec, acodec = _codec(fmt.get("vcodec")), _codec(fmt.get("acodec"))
    height, width = _int(fmt.get("height")), _int(fmt.get("width"))
    if vcodec == "none" and acodec == "none":
        return None  # storyboards / image tracks
    if vcodec == "none" or (vcodec is None and height is None and ext in AUDIO_EXTS):
        kind = "audio"
    elif acodec == "none":
        kind = "video"
    else:
        kind = "muxed"

    size, estimated = _estimate_size(fmt, duration)
    dynamic_range = fmt.get("dynamic_range")
    language = fmt.get("language")
    preference = fmt.get("language_preference")
    return Stream(
        format_id=format_id,
        kind=kind,
        ext=ext,
        protocol=protocol,
        rank=rank,
        height=None if kind == "audio" else height,
        width=None if kind == "audio" else width,
        fps=None if kind == "audio" else _num(fmt.get("fps")),
        tbr=_num(fmt.get("tbr")) or _num(fmt.get("abr") if kind == "audio" else fmt.get("vbr")),
        vcodec=None if vcodec == "none" else vcodec,
        acodec=None if acodec == "none" else acodec,
        size=size,
        size_is_estimate=estimated,
        note=_clean_note(fmt.get("format_note")),
        dynamic_range=dynamic_range if isinstance(dynamic_range, str) and dynamic_range.upper() != "SDR" else None,
        language=language if isinstance(language, str) else None,
        language_preference=preference if isinstance(preference, int) else 0,
    )


def usable_streams(info: dict[str, Any]) -> tuple[list[Stream], int, int]:
    """Return ``(streams, total_formats, drm_formats)`` for an extractor result."""
    raw = [f for f in (info.get("formats") or []) if isinstance(f, dict)]
    duration = _num(info.get("duration"))
    streams = [s for rank, f in enumerate(raw) if (s := _to_stream(f, rank, duration)) is not None]
    return streams, len(raw), sum(1 for f in raw if f.get("has_drm"))


def _fps_bucket(fps: float | None) -> int:
    return 60 if fps and fps >= 48 else 30


def _pick_audio(video: Stream, audios: list[Stream]) -> tuple[Stream, str] | None:
    """Best audio stream for ``video`` and the container the pair fits in."""
    if not audios:
        return None

    def best(candidates: list[Stream]) -> Stream | None:
        return max(candidates, key=lambda a: (a.language_preference, a.tbr or 0, a.rank), default=None)

    if video.ext in MP4_VIDEO_EXTS:
        match = best([a for a in audios if a.ext in MP4_AUDIO_EXTS])
        if match:
            return match, "mp4"
    if video.ext == "webm":
        match = best([a for a in audios if a.ext in WEBM_AUDIO_EXTS])
        if match:
            return match, "webm"
    fallback = best(audios)
    return (fallback, "mkv") if fallback else None


def _label(stream: Stream, single: bool) -> str:
    if stream.height:
        suffix = "60" if _fps_bucket(stream.fps) == 60 else ""
        return f"{stream.height}p{suffix}"
    if single:
        return "Original"
    return stream.note or f"Original ({stream.ext.upper()})"


def _sum_sizes(parts: tuple[Stream, ...]) -> tuple[int | None, bool]:
    if any(p.size is None for p in parts):
        return None, False
    return sum(p.size or 0 for p in parts), any(p.size_is_estimate for p in parts)


def build_qualities(info: dict[str, Any], *, ffmpeg_available: bool, max_bytes: int | None = None) -> FormatSummary:
    streams, total, drm = usable_streams(info)
    summary = FormatSummary(total_formats=total, drm_only=bool(total) and drm == total)
    if not streams:
        return summary

    audios = [s for s in streams if s.kind == "audio"]
    videos = [s for s in streams if s.kind in ("muxed", "video")]
    unknown_height = [s for s in videos if not s.height]

    # --- one candidate per (resolution, frame-rate class, container) ---------------
    best: dict[tuple[Any, ...], tuple[tuple[Any, ...], dict[str, Any]]] = {}
    for stream in videos:
        if stream.kind == "muxed":
            parts: tuple[Stream, ...] = (stream,)
            container, requires_merge, has_audio = stream.ext, False, True
        else:
            pair = _pick_audio(stream, audios) if ffmpeg_available else None
            if pair is None:
                if audios:
                    continue  # needs merging, but FFmpeg is unavailable
                parts, container, requires_merge, has_audio = (stream,), stream.ext, False, False
            else:
                parts, container, requires_merge, has_audio = (stream, pair[0]), pair[1], True, True

        if stream.height:
            key: tuple[Any, ...] = (stream.height, _fps_bucket(stream.fps), container)
        else:
            key = (0, stream.format_id, container)
        # Prefer: has audio > no merge needed > higher bitrate > extractor's own ranking.
        score = (has_audio, not requires_merge, stream.tbr or 0, stream.rank)
        if key not in best or score > best[key][0]:
            best[key] = (score, {
                "stream": stream, "parts": parts, "container": container,
                "requires_merge": requires_merge, "has_audio": has_audio,
            })

    chosen = [entry for _, entry in best.values()]
    chosen.sort(
        key=lambda e: (
            -(e["stream"].height or 0),
            -_fps_bucket(e["stream"].fps),
            CONTAINER_ORDER.get(e["container"], 9),
            -e["stream"].rank,
        )
    )
    chosen = chosen[:MAX_VIDEO_OPTIONS]

    qualities: list[QualityChoice] = []
    single_unknown = len(unknown_height) == 1 or len(chosen) == 1
    for entry in chosen:
        stream, parts = entry["stream"], entry["parts"]
        size, estimated = _sum_sizes(parts)
        audio_part = parts[1] if len(parts) > 1 else stream
        qualities.append(
            QualityChoice(
                id=f"q{len(qualities) + 1}",
                kind="video",
                label=_label(stream, single_unknown),
                container=entry["container"],
                format_spec="+".join(p.format_id for p in parts),
                parts=parts,
                height=stream.height,
                width=stream.width,
                fps=stream.fps,
                video_codec=codec_name(stream.vcodec, audio=False),
                audio_codec=codec_name(audio_part.acodec, audio=True) if entry["has_audio"] else None,
                has_audio=entry["has_audio"],
                requires_merge=entry["requires_merge"],
                size=size,
                size_is_estimate=estimated,
                bitrate_kbps=sum(p.tbr for p in parts if p.tbr) or None,
                dynamic_range=stream.dynamic_range,
                can_embed_subtitles=ffmpeg_available and entry["container"] in EMBED_CONTAINERS,
                exceeds_limit=bool(max_bytes and size and size > max_bytes),
            )
        )

    # --- audio-only: the best stream per container ---------------------------------
    best_audio: dict[str, Stream] = {}
    for audio in audios:
        current = best_audio.get(audio.ext)
        if current is None or (audio.language_preference, audio.tbr or 0, audio.rank) > (
            current.language_preference, current.tbr or 0, current.rank
        ):
            best_audio[audio.ext] = audio
    for audio in sorted(best_audio.values(), key=lambda a: (-(a.tbr or 0), -a.rank))[:MAX_AUDIO_OPTIONS]:
        qualities.append(
            QualityChoice(
                id=f"q{len(qualities) + 1}",
                kind="audio",
                label="Audio only",
                container=audio.ext,
                format_spec=audio.format_id,
                parts=(audio,),
                height=None, width=None, fps=None,
                video_codec=None,
                audio_codec=codec_name(audio.acodec, audio=True),
                has_audio=True,
                requires_merge=False,
                size=audio.size,
                size_is_estimate=audio.size_is_estimate,
                bitrate_kbps=audio.tbr,
                dynamic_range=None,
                can_embed_subtitles=False,
                exceeds_limit=bool(max_bytes and audio.size and audio.size > max_bytes),
            )
        )

    summary.qualities = _mark_recommended(qualities)
    return summary


def _mark_recommended(qualities: list[QualityChoice]) -> list[QualityChoice]:
    """Recommend the best option that plays everywhere: MP4 with audio, up to 1080p."""
    from dataclasses import replace

    candidates = [q for q in qualities if q.kind == "video" and not q.exceeds_limit]
    if not candidates:
        candidates = [q for q in qualities if not q.exceeds_limit]
    if not candidates:
        return qualities

    def score(q: QualityChoice) -> tuple[Any, ...]:
        height = q.height or 0
        return (
            q.has_audio,
            height <= RECOMMENDED_MAX_HEIGHT,
            q.container == "mp4",
            height if height <= RECOMMENDED_MAX_HEIGHT else -height,
            (q.fps or 0) < 48,
        )

    winner = max(candidates, key=score)
    return [replace(q, recommended=q.id == winner.id) for q in qualities]


def build_subtitles(info: dict[str, Any], *, ffmpeg_available: bool) -> list[SubtitleChoice]:
    tracks: list[SubtitleChoice] = []
    for kind, key in (("manual", "subtitles"), ("auto", "automatic_captions")):
        source = info.get(key)
        if not isinstance(source, dict):
            continue
        for language in sorted(source):
            entries = source[language]
            if not isinstance(language, str) or language in _NON_SUBTITLE_KEYS or not isinstance(entries, list):
                continue
            if not re.fullmatch(r"[A-Za-z0-9_\-]{1,35}", language):
                continue
            exts: list[str] = []
            name: str | None = None
            for entry in entries:
                if not isinstance(entry, dict) or not (entry.get("url") or entry.get("data")):
                    continue
                protocol = entry.get("protocol")
                if protocol and protocol not in ALLOWED_PROTOCOLS:
                    continue
                ext = str(entry.get("ext") or "").lower()
                if ext in SUBTITLE_SOURCE_EXTS and ext not in exts:
                    exts.append(ext)
                if name is None and isinstance(entry.get("name"), str):
                    name = _clean_note(entry["name"])
            if not exts:
                continue
            formats = SUBTITLE_TARGETS if ffmpeg_available else tuple(t for t in SUBTITLE_TARGETS if t in exts)
            if not formats:
                continue
            tracks.append(
                SubtitleChoice(
                    id=f"s{len(tracks) + 1}",
                    language=language,
                    name=name,
                    kind=kind,
                    source_exts=tuple(exts),
                    formats=tuple(formats),
                    embeddable=ffmpeg_available,
                )
            )
            if len(tracks) >= MAX_SUBTITLE_TRACKS:
                return tracks
    return tracks
