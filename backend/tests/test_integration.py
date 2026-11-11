"""End-to-end tests: API -> worker process -> yt-dlp/FFmpeg -> local sample source.

Everything here is real (no mocks): real HTTP downloads, real merging, real subtitle
conversion and embedding, real process cancellation, real kernel limits.
"""

from __future__ import annotations

import asyncio
import re
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.services.ffmpeg import locate_ffmpeg
from tests.conftest import processes_using, wait_for_job

pytestmark = pytest.mark.integration


def streams(path: Path) -> list[str]:
    """Stream types inside a media file, as reported by FFmpeg."""
    ffmpeg = locate_ffmpeg()
    assert ffmpeg
    out = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    found = (re.search(r"(Video|Audio|Subtitle): .*", line) for line in out.splitlines() if "Stream #" in line)
    return [match.group(0) for match in found if match]


async def analyze(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    response = await client.post("/api/v1/analyze", json={"url": url})
    assert response.status_code == 200, response.text
    return response.json()


async def start_job(client: httpx.AsyncClient, analysis: dict[str, Any], quality: dict[str, Any],
                    embed: list[str] | None = None) -> dict[str, Any]:
    payload = {"analysis_id": analysis["id"], "quality_id": quality["id"], "embed_subtitles": embed or []}
    response = await client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 202, response.text
    return response.json()


async def fetch_file(client: httpx.AsyncClient, job: dict[str, Any], tmp_path: Path) -> Path:
    response = await client.get(job["file"]["url"])
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment;")
    assert len(response.content) == job["file"]["size"]
    path = tmp_path / f"download.{job['file']['container']}"
    path.write_bytes(response.content)
    return path


def storage(client: httpx.AsyncClient) -> Path:
    return client.app.state.services.storage.root  # type: ignore[attr-defined,no-any-return]


# ------------------------------------------------------------------------------ analyze
async def test_analyze_page_with_qualities_subtitles_and_poster(live: httpx.AsyncClient, source: str) -> None:
    analysis = await analyze(live, f"{source}/watch/demo")
    assert analysis["title"] == "Lumora sample clip"
    assert analysis["source"] == {"domain": "127.0.0.1", "extractor": "HTML5MediaEmbed"}
    assert [(q["label"], q["container"], q["recommended"]) for q in analysis["qualities"]] == [
        ("720p", "mp4", True), ("360p", "mp4", False), ("240p", "mp4", False),
    ]
    assert [(s["language"], s["kind"], s["formats"]) for s in analysis["subtitles"]] == [
        ("en", "manual", ["srt", "vtt"]), ("es", "manual", ["srt", "vtt"]), ("fr", "manual", ["srt", "vtt"]),
    ]
    # Internal details never leave the server.
    assert "format_spec" not in str(analysis) and source not in str(analysis["qualities"])

    poster = await live.get(analysis["thumbnail_url"])
    assert poster.status_code == 200 and poster.headers["content-type"] == "image/jpeg"
    assert poster.content[:3] == b"\xff\xd8\xff" and poster.headers["x-content-type-options"] == "nosniff"


async def test_analyze_streaming_manifests(live: httpx.AsyncClient, source: str) -> None:
    hls = await analyze(live, f"{source}/hls/master.m3u8")
    assert [(q["label"], q["requires_merge"]) for q in hls["qualities"]] == [("360p", False), ("240p", False)]
    assert hls["duration"] == 8 and [s["language"] for s in hls["subtitles"]] == ["en"]

    dash = await analyze(live, f"{source}/dash/manifest.mpd")
    assert [(q["kind"], q["label"], q["requires_merge"]) for q in dash["qualities"]] == [
        ("video", "360p", True), ("video", "240p", True), ("audio", "Audio only", False),
    ]
    assert dash["qualities"][0]["video_codec"] == "H.264" and dash["qualities"][0]["audio_codec"] == "AAC"


@pytest.mark.parametrize(("path", "code"), [
    ("/article", "unsupported_source"),          # a page without any video
    ("/gone", "not_found"),
    ("/forbidden", "source_forbidden"),
    ("/redirect/internal", "blocked_destination"),   # public page redirecting into the internal network
])
async def test_analyze_failures_are_explained(live: httpx.AsyncClient, source: str, path: str, code: str) -> None:
    response = await live.post("/api/v1/analyze", json={"url": source + path})
    error = response.json()["error"]
    assert error["code"] == code and error["message"]
    assert "127.0.0.1" not in error["message"] and "Traceback" not in response.text
    assert list((storage(live) / "analyses").iterdir()) == []       # nothing left behind


async def test_analyze_timeout(make_client: Callable[..., Any], source: str) -> None:
    port = source.rsplit(":", 1)[1]
    client = await make_client(unsafe_allow_hosts=[f"127.0.0.1:{port}"], analyze_timeout_seconds=5)
    started = time.monotonic()
    response = await client.post("/api/v1/analyze", json={"url": f"{source}/slow?s=60"})
    assert response.json()["error"]["code"] == "source_timeout"
    assert time.monotonic() - started < 15
    assert list((storage(client) / "analyses").iterdir()) == []


async def test_loopback_is_blocked_without_the_test_exemption(client: httpx.AsyncClient, source: str) -> None:
    response = await client.post("/api/v1/analyze", json={"url": f"{source}/watch/demo"})
    assert response.json()["error"]["code"] == "blocked_destination"


# ---------------------------------------------------------------------------- subtitles
async def test_subtitle_downloads_in_both_formats(live: httpx.AsyncClient, source: str) -> None:
    analysis = await analyze(live, f"{source}/watch/demo")
    tracks = {t["language"]: t["id"] for t in analysis["subtitles"]}
    base = f"/api/v1/analyses/{analysis['id']}/subtitles"

    srt = await live.get(f"{base}/{tracks['en']}", params={"format": "srt"})      # WebVTT source -> SRT
    assert srt.status_code == 200 and srt.headers["content-type"].startswith("application/x-subrip")
    assert srt.text.startswith("1\n00:00:00,500 --> 00:00:02,500\n") and "Subtitles & qualities are real." in srt.text
    assert 'filename="Lumora sample clip (en).srt"' in srt.headers["content-disposition"]

    vtt = await live.get(f"{base}/{tracks['fr']}", params={"format": "vtt"})      # SRT source -> WebVTT
    assert vtt.status_code == 200 and vtt.headers["content-type"].startswith("text/vtt")
    assert vtt.text.startswith("WEBVTT") and "Bienvenue dans le clip d'exemple Lumora." in vtt.text

    again = await live.get(f"{base}/{tracks['en']}", params={"format": "srt"})    # served from the cache
    assert again.text == srt.text

    assert (await live.get(f"{base}/s99")).json()["error"]["code"] == "option_not_found"
    assert (await live.get(f"{base}/{tracks['en']}", params={"format": "ass"})).status_code == 422


async def test_subtitles_from_hls_segments(live: httpx.AsyncClient, source: str) -> None:
    analysis = await analyze(live, f"{source}/hls/master.m3u8")
    track = analysis["subtitles"][0]["id"]
    srt = await live.get(f"/api/v1/analyses/{analysis['id']}/subtitles/{track}", params={"format": "srt"})
    assert srt.status_code == 200 and "Welcome to the <i>Lumora</i> sample clip." in srt.text


# ---------------------------------------------------------------------------- downloads
async def test_download_selected_quality(
    live: httpx.AsyncClient, source: str, media_root: Path, tmp_path: Path
) -> None:
    analysis = await analyze(live, f"{source}/watch/demo")
    quality = next(q for q in analysis["qualities"] if q["label"] == "240p")      # not the default one
    created = await start_job(live, analysis, quality)
    assert created["status"] in ("queued", "running")
    job = await wait_for_job(live, created["id"])
    assert job["status"] == "completed" and job["progress"]["percent"] == 100.0
    assert job["file"]["name"] == "Lumora sample clip (240p).mp4" and 0 < job["file"]["expires_in"] <= 1800
    path = await fetch_file(live, job, tmp_path)
    assert path.read_bytes() == (media_root / "media" / "v240.mp4").read_bytes()   # byte-identical to the source

    partial = await live.get(job["file"]["url"], headers={"Range": "bytes=0-99"})  # resumable
    assert partial.status_code == 206 and len(partial.content) == 100


async def test_download_hls_and_merge_dash(live: httpx.AsyncClient, source: str, tmp_path: Path) -> None:
    hls = await analyze(live, f"{source}/hls/master.m3u8")
    dash = await analyze(live, f"{source}/dash/manifest.mpd")
    hls_job = await start_job(live, hls, hls["qualities"][0])
    dash_job = await start_job(live, dash, dash["qualities"][0])          # separate video + audio streams
    for created in (hls_job, dash_job):
        job = await wait_for_job(live, created["id"])
        assert job["status"] == "completed", job
        found = streams(await fetch_file(live, job, tmp_path))
        assert len(found) == 2 and found[0].startswith("Video: h264") and found[1].startswith("Audio: aac")


async def test_audio_only_download(live: httpx.AsyncClient, source: str, tmp_path: Path) -> None:
    dash = await analyze(live, f"{source}/dash/manifest.mpd")
    audio = next(q for q in dash["qualities"] if q["kind"] == "audio")
    job = await wait_for_job(live, (await start_job(live, dash, audio))["id"])
    assert job["status"] == "completed" and job["file"]["name"].endswith(".m4a")
    found = streams(await fetch_file(live, job, tmp_path))
    assert len(found) == 1 and found[0].startswith("Audio: aac")
    refused = await live.post("/api/v1/jobs", json={
        "analysis_id": dash["id"], "quality_id": audio["id"], "embed_subtitles": [],
    })
    assert refused.status_code == 202        # (same client may run two jobs)


async def test_embed_subtitles(live: httpx.AsyncClient, source: str, tmp_path: Path) -> None:
    analysis = await analyze(live, f"{source}/watch/demo")
    tracks = {t["language"]: t["id"] for t in analysis["subtitles"]}
    quality = next(q for q in analysis["qualities"] if q["label"] == "360p")
    created = await start_job(live, analysis, quality, embed=[tracks["en"], tracks["fr"]])
    job = await wait_for_job(live, created["id"])
    assert job["status"] == "completed" and job["embedded_subtitles"] == ["en", "fr"] and job["notices"] == []
    found = streams(await fetch_file(live, job, tmp_path))
    assert [s.split(" ")[0] for s in found] == ["Video:", "Audio:", "Subtitle:", "Subtitle:"]


async def test_embedding_into_audio_is_refused(live: httpx.AsyncClient, source: str) -> None:
    dash = await analyze(live, f"{source}/dash/manifest.mpd")
    demo = await analyze(live, f"{source}/watch/demo")
    audio = next(q for q in dash["qualities"] if q["kind"] == "audio")
    assert not audio["can_embed_subtitles"]
    unknown = await live.post("/api/v1/jobs", json={
        "analysis_id": demo["id"], "quality_id": "q1", "embed_subtitles": ["s42"],
    })
    assert unknown.json()["error"]["code"] == "option_not_found"
    missing = await live.post("/api/v1/jobs", json={"analysis_id": demo["id"], "quality_id": "q42"})
    assert missing.json()["error"]["code"] == "option_not_found"


# ------------------------------------------------------------- progress and cancellation
async def test_progress_then_cancel_kills_the_worker(live: httpx.AsyncClient, source: str) -> None:
    analysis = await analyze(live, f"{source}/throttled.mp4?delay=0.1&chunk=16384")
    created = await start_job(live, analysis, analysis["qualities"][0])
    job_dir = storage(live) / "jobs" / created["id"]

    seen: list[float] = []
    deadline = time.monotonic() + 20
    while len(seen) < 3 and time.monotonic() < deadline:        # real, increasing progress
        job = (await live.get(f"/api/v1/jobs/{created['id']}")).json()
        percent = job["progress"]["percent"]
        if job["stage"] == "downloading" and percent is not None and (not seen or percent > seen[-1]):
            seen.append(percent)
        await asyncio.sleep(0.1)
    assert len(seen) == 3 and seen == sorted(seen) and 0 <= seen[0] < seen[-1] < 100
    assert job["progress"]["downloaded_bytes"] > 0 and job["progress"]["total_bytes"] == 4803724
    assert job["progress"]["speed_bps"] and job["file"] is None
    assert processes_using(job_dir), "a worker process should be running for this job"
    assert (await live.get(f"/api/v1/jobs/{created['id']}/file")).json()["error"]["code"] == "file_not_ready"

    cancelled = (await live.delete(f"/api/v1/jobs/{created['id']}")).json()
    assert cancelled["status"] == "cancelled" and cancelled["file"] is None
    assert not job_dir.exists(), "partial download must be deleted"
    assert processes_using(job_dir) == [], "no worker may survive a cancel"
    assert (await live.get(f"/api/v1/jobs/{created['id']}")).json()["status"] == "cancelled"
    assert (await live.delete(f"/api/v1/jobs/{created['id']}")).json()["status"] == "cancelled"   # idempotent


async def test_queue_and_per_client_limit(make_client: Callable[..., Any], source: str) -> None:
    port = source.rsplit(":", 1)[1]
    client = await make_client(
        unsafe_allow_hosts=[f"127.0.0.1:{port}"], max_concurrent_jobs=1, max_active_jobs_per_client=2,
    )
    analysis = await analyze(client, f"{source}/throttled.mp4?delay=0.1&chunk=16384")
    first = await start_job(client, analysis, analysis["qualities"][0])
    second = await start_job(client, analysis, analysis["qualities"][0])
    third = await client.post("/api/v1/jobs", json={"analysis_id": analysis["id"], "quality_id": "q1"})
    assert (third.status_code, third.json()["error"]["code"]) == (429, "too_many_jobs")

    await asyncio.sleep(0.5)
    waiting = (await client.get(f"/api/v1/jobs/{second['id']}")).json()
    assert (waiting["status"], waiting["queue_position"]) == ("queued", 1)        # only one runs at a time
    assert (await client.get(f"/api/v1/jobs/{first['id']}")).json()["status"] == "running"

    assert (await client.delete(f"/api/v1/jobs/{second['id']}")).json()["status"] == "cancelled"   # cancel while queued
    assert (await client.delete(f"/api/v1/jobs/{first['id']}")).json()["status"] == "cancelled"
    assert list((storage(client) / "jobs").iterdir()) == []


# ----------------------------------------------------------------------- limits and SSRF
@pytest.mark.parametrize("announce", ["1", "0"])
async def test_file_size_limit(make_client: Callable[..., Any], source: str, announce: str) -> None:
    """Announced sizes are refused up front; unannounced ones are stopped by the kernel limit."""
    port = source.rsplit(":", 1)[1]
    client = await make_client(unsafe_allow_hosts=[f"127.0.0.1:{port}"], max_file_size_mb=2)
    analysis = await analyze(client, f"{source}/huge.mp4?bytes=33554432&announce={announce}")
    job = await wait_for_job(client, (await start_job(client, analysis, analysis["qualities"][0]))["id"])
    assert job["status"] == "failed" and job["error"]["code"] == "file_too_large" and job["file"] is None
    assert list((storage(client) / "jobs").iterdir()) == []


async def test_playlist_pointing_at_internal_hosts_is_blocked(live: httpx.AsyncClient, source: str) -> None:
    analysis = await analyze(live, f"{source}/ssrf/playlist.m3u8")     # the manifest itself is public
    job = await wait_for_job(live, (await start_job(live, analysis, analysis["qualities"][0]))["id"])
    assert job["status"] == "failed" and job["error"]["code"] == "blocked_destination"


async def test_embedded_internal_media_is_blocked(live: httpx.AsyncClient, source: str) -> None:
    analysis = await analyze(live, f"{source}/ssrf/embed")             # page embeds an internal file
    job = await wait_for_job(live, (await start_job(live, analysis, analysis["qualities"][0]))["id"])
    assert job["status"] == "failed" and job["error"]["code"] == "blocked_destination"


# ------------------------------------------------------------------ expiry and clean-up
async def test_files_expire_and_can_be_deleted_early(live: httpx.AsyncClient, source: str) -> None:
    services = live.app.state.services  # type: ignore[attr-defined]
    analysis = await analyze(live, f"{source}/watch/demo")
    quality = analysis["qualities"][-1]
    first = await wait_for_job(live, (await start_job(live, analysis, quality))["id"])
    second = await wait_for_job(live, (await start_job(live, analysis, quality))["id"])
    jobs_dir = storage(live) / "jobs"
    assert len(list(jobs_dir.iterdir())) == 2

    deleted = (await live.delete(f"/api/v1/jobs/{first['id']}")).json()            # "delete now"
    assert deleted["status"] == "deleted" and deleted["file"] is None
    assert (await live.get(first["file"]["url"])).json()["error"]["code"] == "file_expired"
    assert [p.name for p in jobs_dir.iterdir()] == [second["id"]]

    assert services.jobs.cleanup(now=time.time() + 60) == (0, 0)                   # not due yet
    assert services.jobs.cleanup(now=time.time() + 1801) == (1, 0)                 # past the 30-minute lifetime
    expired = (await live.get(f"/api/v1/jobs/{second['id']}")).json()
    assert expired["status"] == "expired" and expired["file"] is None
    gone = await live.get(second["file"]["url"])
    assert (gone.status_code, gone.json()["error"]["code"]) == (410, "file_expired")
    assert list(jobs_dir.iterdir()) == []

    assert services.jobs.cleanup(now=time.time() + 3 * 3600)[1] == 2               # records forgotten later
    assert (await live.get(f"/api/v1/jobs/{second['id']}")).status_code == 404

    analyses_dir = storage(live) / "analyses"
    assert len(list(analyses_dir.iterdir())) == 1
    assert services.analyses.cleanup(now=time.time() + 1801) == 1
    assert list(analyses_dir.iterdir()) == []
    stale = await live.post("/api/v1/jobs", json={"analysis_id": analysis["id"], "quality_id": quality["id"]})
    assert stale.json()["error"]["code"] == "analysis_expired"


async def test_shutdown_stops_workers_and_wipes_storage(make_client: Callable[..., Any], source: str) -> None:
    from app.main import create_app
    from tests.conftest import make_settings

    port = source.rsplit(":", 1)[1]
    root = Path(storage(await make_client())).parent.parent / "shutdown"
    app = create_app(make_settings(root, unsafe_allow_hosts=[f"127.0.0.1:{port}"]))
    transport = httpx.ASGITransport(app=app)
    api = httpx.AsyncClient(transport=transport, base_url="http://api.test")
    async with app.router.lifespan_context(app), api as c:
        analysis = await analyze(c, f"{source}/throttled.mp4?delay=0.1&chunk=16384")
        created = await start_job(c, analysis, analysis["qualities"][0])
        job_dir = app.state.services.storage.root / "jobs" / created["id"]
        for _ in range(100):
            if processes_using(job_dir):
                break
            await asyncio.sleep(0.05)
        assert processes_using(job_dir)
    assert processes_using(job_dir) == []
    assert not app.state.services.storage.root.exists()


# ------------------------------------------------------------------------- regressions
def test_selection_check_detects_wrong_streams() -> None:
    """The worker refuses to hand over a file built from streams other than the chosen ones."""
    from app.worker.tasks import TaskError, _reusable, _verify_selection

    merged = {"requested_formats": [{"format_id": "0"}, {"format_id": "2"}]}
    _verify_selection({"format_id": "0+2"}, merged, "0+2")
    _verify_selection({"format_id": "2"}, {"format_id": "2"}, "2")
    _verify_selection({"format_id": "668"}, {"format_id": None}, "668")      # some fix-ups drop the id
    for result, record, spec in (
        ({"format_id": "2"}, merged, "2"),                # asked for audio only, got video + audio merged
        ({"format_id": "0"}, {"format_id": "0"}, "0+2"),  # asked for a merge, got a single stream
        ({"format_id": "1+2"}, {"requested_formats": [{"format_id": "1"}, {"format_id": "2"}]}, "0+2"),
    ):
        with pytest.raises(TaskError) as error:
            _verify_selection(result, record, spec)
        assert error.value.code == "download_failed"

    stale = {"formats": [], "requested_formats": [1], "requested_subtitles": {}, "filepath": "/x", "title": "t"}
    assert _reusable(stale) == {"formats": [], "title": "t"}
