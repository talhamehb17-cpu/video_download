"""Quality / subtitle choices built from extractor metadata, and error classification."""

from __future__ import annotations

from typing import Any

import pytest

from app.services.formats import build_qualities, build_subtitles
from app.worker.classify import classify_message


def fmt(**fields: Any) -> dict[str, Any]:
    return {"url": "https://cdn.example.com/x", "protocol": "https", **fields}


LADDER: dict[str, Any] = {
    "duration": 600,
    "formats": [
        fmt(format_id="sb0", ext="mhtml", vcodec="none", acodec="none", protocol="mhtml"),
        fmt(format_id="139", ext="m4a", vcodec="none", acodec="mp4a.40.5", tbr=48, filesize=3_600_000),
        fmt(format_id="251", ext="webm", vcodec="none", acodec="opus", tbr=130, filesize=9_700_000),
        fmt(format_id="140", ext="m4a", vcodec="none", acodec="mp4a.40.2", tbr=129, filesize=9_600_000),
        fmt(format_id="18", ext="mp4", vcodec="avc1.42001E", acodec="mp4a.40.2", height=360, fps=30, tbr=500,
            filesize_approx=37_000_000),
        fmt(format_id="134", ext="mp4", vcodec="avc1.4d401e", acodec="none", height=360, fps=30, tbr=400,
            filesize=30_000_000),
        fmt(format_id="136", ext="mp4", vcodec="avc1.64001f", acodec="none", height=720, fps=30, tbr=1500,
            filesize=110_000_000),
        fmt(format_id="247", ext="webm", vcodec="vp09.00.31.08", acodec="none", height=720, fps=30, tbr=1300,
            filesize=98_000_000),
        fmt(format_id="137", ext="mp4", vcodec="avc1.640028", acodec="none", height=1080, fps=30, tbr=3000,
            filesize=225_000_000),
        fmt(format_id="299", ext="mp4", vcodec="avc1.64002a", acodec="none", height=1080, fps=60, tbr=5000,
            filesize=375_000_000),
        fmt(format_id="313", ext="webm", vcodec="vp09.00.50.08", acodec="none", height=2160, fps=30, tbr=14000,
            filesize=1_050_000_000),
        fmt(format_id="drm1", ext="mp4", vcodec="avc1", acodec="mp4a", height=1080, has_drm=True),
        fmt(format_id="rtmp1", ext="flv", vcodec="h264", acodec="aac", height=480, protocol="rtmp"),
        fmt(format_id="bad id;rm -rf", ext="mp4", height=480),
    ],
}


def test_ladder_with_ffmpeg() -> None:
    summary = build_qualities(LADDER, ffmpeg_available=True, max_bytes=1_000_000_000)
    by_label = {(q.label, q.container): q for q in summary.qualities}
    assert [(q.label, q.container, q.format_spec) for q in summary.qualities] == [
        ("2160p", "webm", "313+251"), ("1080p60", "mp4", "299+140"), ("1080p", "mp4", "137+140"),
        ("720p", "mp4", "136+140"), ("720p", "webm", "247+251"), ("360p", "mp4", "18"),
        ("Audio only", "webm", "251"), ("Audio only", "m4a", "140"),
    ]
    # Video-only streams are paired with audio of a matching container; sizes add up.
    full_hd = by_label[("1080p", "mp4")]
    assert full_hd.requires_merge and full_hd.has_audio and full_hd.size == 234_600_000
    assert (full_hd.video_codec, full_hd.audio_codec) == ("H.264", "AAC")
    # A ready-made file beats merging at the same resolution; its size is only an estimate.
    assert not by_label[("360p", "mp4")].requires_merge and by_label[("360p", "mp4")].size_is_estimate
    # Too big for this server: listed, flagged, never recommended.
    assert by_label[("2160p", "webm")].exceeds_limit
    assert [q.label for q in summary.qualities if q.recommended] == ["1080p"]
    assert all(q.can_embed_subtitles for q in summary.qualities if q.kind == "video")
    assert not any(q.can_embed_subtitles for q in summary.qualities if q.kind == "audio")


def test_unusable_formats_are_never_offered() -> None:
    specs = " ".join(q.format_spec for q in build_qualities(LADDER, ffmpeg_available=True).qualities)
    for forbidden in ("drm1", "rtmp1", "sb0", "rm -rf"):
        assert forbidden not in specs


def test_without_ffmpeg_only_ready_made_files() -> None:
    summary = build_qualities(LADDER, ffmpeg_available=False)
    assert [(q.label, q.format_spec) for q in summary.qualities] == [
        ("360p", "18"), ("Audio only", "251"), ("Audio only", "140"),
    ]
    assert not any(q.requires_merge or q.can_embed_subtitles for q in summary.qualities)


def test_html5_and_direct_links() -> None:
    page = {"formats": [fmt(format_id=f"{h}p", ext="mp4", protocol="http", height=h) for h in (240, 360, 720)]}
    qualities = build_qualities(page, ffmpeg_available=True).qualities
    assert [(q.label, q.has_audio, q.recommended) for q in qualities] == [
        ("720p", True, True), ("360p", True, False), ("240p", True, False),
    ]
    direct = build_qualities({"formats": [fmt(format_id="mp4", ext="mp4")]}, ffmpeg_available=False).qualities
    assert [(q.label, q.container, q.size) for q in direct] == [("Original", "mp4", None)]


def test_size_estimate_from_bitrate() -> None:
    info = {"duration": 100, "formats": [fmt(format_id="a", ext="mp4", height=480, tbr=800)]}
    quality = build_qualities(info, ffmpeg_available=True).qualities[0]
    assert quality.size == 10_000_000 and quality.size_is_estimate


def test_drm_only_and_empty() -> None:
    drm = build_qualities({"formats": [fmt(format_id="a", ext="mp4", has_drm=True)]}, ffmpeg_available=True)
    assert drm.qualities == [] and drm.drm_only
    empty = build_qualities({"formats": []}, ffmpeg_available=True)
    assert empty.qualities == [] and not empty.drm_only


def test_subtitles() -> None:
    info = {
        "subtitles": {
            "en": [
                {"ext": "json3", "url": "u"}, {"ext": "vtt", "url": "u"}, {"ext": "srt", "url": "u", "name": "English"},
            ],
            "pt-BR": [{"ext": "ttml", "url": "u"}],
            "de": [{"ext": "json3", "url": "u"}],             # nothing convertible
            "live_chat": [{"ext": "json", "url": "u"}],       # not a subtitle
            "xx": [{"ext": "vtt"}],                           # no URL
            "rt": [{"ext": "vtt", "url": "u", "protocol": "rtmp"}],
        },
        "automatic_captions": {"en": [{"ext": "vtt", "url": "u"}], "bad lang!": [{"ext": "vtt", "url": "u"}]},
    }
    tracks = build_subtitles(info, ffmpeg_available=True)
    assert [(t.id, t.language, t.kind, t.source_exts, t.formats) for t in tracks] == [
        ("s1", "en", "manual", ("vtt", "srt"), ("srt", "vtt")),
        ("s2", "pt-BR", "manual", ("ttml",), ("srt", "vtt")),
        ("s3", "en", "auto", ("vtt",), ("srt", "vtt")),
    ]
    assert tracks[0].name == "English"
    assert tracks[0].source_for("srt") == "srt" and tracks[2].source_for("srt") == "vtt"
    # Without FFmpeg nothing can be converted: only the formats the source really has.
    plain = build_subtitles(info, ffmpeg_available=False)
    assert [(t.language, t.kind, t.formats) for t in plain] == [
        ("en", "manual", ("srt", "vtt")), ("en", "auto", ("vtt",)),
    ]


@pytest.mark.parametrize(("message", "code"), [
    ("[youtube] x: Sign in to confirm your age. This video may be inappropriate for some users.", "age_restricted"),
    ("[youtube] x: Sign in to confirm you’re not a bot. Use --cookies-from-browser", "verification_required"),
    ("[youtube] x: Private video. Sign in if you've been granted access to this video", "private_content"),
    ("[youtube] x: This video is available to this channel's members on level: Gold", "paywalled"),
    ("[youtube] x: The uploader has not made this video available in your country", "geo_restricted"),
    ("[youtube] x: Video unavailable. This video has been removed by the uploader", "not_found"),
    ("[youtube] x: This live event will begin in 3 hours.", "live_stream"),
    ("Unsupported URL: https://example.com/login/premium", "unsupported_source"),   # words in the URL are ignored
    ("[generic] Unable to download webpage: HTTP Error 404: Not Found", "not_found"),
    ("[generic] Unable to download webpage: HTTP Error 403: Forbidden", "source_forbidden"),
    ("[generic] Unable to download webpage: HTTP Error 429: Too Many Requests", "source_rate_limited"),
    ("[generic] Unable to download webpage: [Errno -2] Name or service not known", "source_unreachable"),
    ("[generic] Unable to download webpage: The read operation timed out", "source_timeout"),
    ("[vimeo] 1: This video is DRM protected", "drm_protected"),
    ("[x] 1: Requested format is not available. Use --list-formats", "format_unavailable"),
    ("[x] 1: No video formats found!", "no_formats"),
    ("unable to write data: [Errno 27] File too large", "file_too_large"),
    ("Postprocessing: Conversion failed!", "processing_failed"),
    ("Unable to download webpage: blocked by network policy: 127.0.0.1:80", "blocked_destination"),
    ("[instagram] x: Requested content is not available, rate-limit reached or login required", "login_required"),
    ("Unable to download video subtitles for 'en': HTTP Error 404: Not Found", "subtitle_unavailable"),
    ("something nobody has seen before", "fallback"),
])
def test_error_classification(message: str, code: str) -> None:
    assert classify_message(message, default="fallback") == code
