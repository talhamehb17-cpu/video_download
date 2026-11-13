"""A tiny local "public video source" used by integration tests and local demos.

It serves the synthetic fixtures from :mod:`build_media` the way a real site would:
an HTML watch page with an HTML5 ``<video>`` (several qualities + subtitle tracks),
direct media files (with HTTP range support), an HLS master playlist and a DASH
manifest. A few extra routes simulate hostile or broken sources so the security
checks can be tested (redirects into the internal network, playlists that point at
internal hosts, oversized files, slow responses...).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

WATCH_PAGE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Lumora sample clip</title>
    <meta property="og:title" content="Lumora sample clip">
    <meta name="description" content="Synthetic test bars and a 440 Hz tone.">
  </head>
  <body>
    <h1>Lumora sample clip</h1>
    <video controls poster="/media/poster.jpg" width="640">
      <source src="/media/v720.mp4" type="video/mp4" res="720" label="720p">
      <source src="/media/v360.mp4" type="video/mp4" res="360" label="360p">
      <source src="/media/v240.mp4" type="video/mp4" res="240" label="240p">
      <track kind="subtitles" src="/subs/en.vtt" srclang="en" label="English" default>
      <track kind="subtitles" src="/subs/es.vtt" srclang="es" label="Español">
      <track kind="subtitles" src="/subs/fr.srt" srclang="fr" label="Français">
    </video>
  </body>
</html>
"""

WEBM_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Lumora WebM sample</title></head>
<body><video controls>
  <source src="/media/v360.webm" type="video/webm" res="360" label="360p">
  <track kind="subtitles" src="/subs/en.vtt" srclang="en" label="English">
</video></body></html>
"""

NO_SUBS_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Clip without subtitles</title></head>
<body><video controls><source src="/media/v240.mp4" type="video/mp4" res="240"></video></body></html>
"""

# The same public page, carrying the machine-readable "restricted to adults" label that
# websites put on themselves. Readers report it as an 18+ rating. Nobody has to sign
# in to watch it, and the clip is the usual synthetic one.
RATED_PAGE = WATCH_PAGE.replace(
    '<meta charset="utf-8">',
    '<meta charset="utf-8">\n    <meta name="rating" content="RTA-5042-1996-1400-1577-RTA">',
)

ARTICLE_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Just an article</title></head>
<body><article><h1>No video here</h1><p>Only words.</p></article></body></html>
"""


def create_app(root: Path, *, internal_port: int = 9) -> Starlette:
    """Build the fixture app. ``internal_port`` is a loopback port the app under test
    must never be able to reach (used by the SSRF routes)."""

    internal = f"http://127.0.0.1:{internal_port}"

    async def watch(_: Request) -> Response:
        return HTMLResponse(WATCH_PAGE)

    async def watch_rated(_: Request) -> Response:
        return HTMLResponse(RATED_PAGE)

    async def watch_webm(_: Request) -> Response:
        return HTMLResponse(WEBM_PAGE)

    async def watch_nosubs(_: Request) -> Response:
        return HTMLResponse(NO_SUBS_PAGE)

    async def article(_: Request) -> Response:
        return HTMLResponse(ARTICLE_PAGE)

    async def redirect_internal(_: Request) -> Response:
        return RedirectResponse(f"{internal}/secret.mp4", status_code=302)

    async def hls_internal(_: Request) -> Response:
        # A playlist whose segments live on an internal host: classic SSRF vector.
        body = (
            "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:0\n"
            f"#EXT-X-PLAYLIST-TYPE:VOD\n#EXTINF:2.0,\n{internal}/secret.ts\n#EXT-X-ENDLIST\n"
        )
        return PlainTextResponse(body, media_type="application/vnd.apple.mpegurl")

    async def embed_internal(_: Request) -> Response:
        return HTMLResponse(
            f'<html><head><title>Embeds an internal file</title></head><body>'
            f'<video><source src="{internal}/secret.mp4" type="video/mp4"></video></body></html>'
        )

    async def forbidden(_: Request) -> Response:
        return PlainTextResponse("Forbidden", status_code=403)

    async def gone(_: Request) -> Response:
        return PlainTextResponse("Not found", status_code=404)

    async def slow(request: Request) -> Response:
        await asyncio.sleep(float(request.query_params.get("s", "30")))
        return HTMLResponse(WATCH_PAGE)

    async def huge(request: Request) -> Response:
        """A "video" that announces (or silently streams) far more data than allowed."""
        size = int(request.query_params.get("bytes", str(64 * 1024 * 1024)))
        announce = request.query_params.get("announce", "1") == "1"

        async def body():
            chunk = b"\0" * 65536
            sent = 0
            while sent < size:
                yield chunk
                sent += len(chunk)
                await asyncio.sleep(0)

        headers = {"Content-Length": str(size)} if announce else {}
        if request.method == "HEAD":
            return Response(status_code=200, headers=headers, media_type="video/mp4")
        return StreamingResponse(body(), media_type="video/mp4", headers=headers)

    async def throttled(request: Request) -> Response:
        """Serve a real MP4 slowly so progress and cancellation can be observed."""
        path = root / "media" / "v720.mp4"
        data = path.read_bytes()
        delay = float(request.query_params.get("delay", "0.05"))
        chunk_size = int(request.query_params.get("chunk", "32768"))

        async def body():
            for i in range(0, len(data), chunk_size):
                yield data[i : i + chunk_size]
                await asyncio.sleep(delay)

        headers = {"Content-Length": str(len(data)), "Accept-Ranges": "none"}
        if request.method == "HEAD":
            return Response(status_code=200, headers=headers, media_type="video/mp4")
        return StreamingResponse(body(), media_type="video/mp4", headers=headers)

    return Starlette(
        routes=[
            Route("/watch/demo", watch),
            Route("/watch/webm", watch_webm),
            Route("/watch/rated", watch_rated),
            Route("/watch/nosubs", watch_nosubs),
            Route("/article", article),
            Route("/redirect/internal", redirect_internal),
            Route("/ssrf/playlist.m3u8", hls_internal),
            Route("/ssrf/embed", embed_internal),
            Route("/forbidden", forbidden),
            Route("/gone", gone),
            Route("/slow", slow),
            Route("/huge.mp4", huge, methods=["GET", "HEAD"]),
            Route("/throttled.mp4", throttled, methods=["GET", "HEAD"]),
            Mount("/media", StaticFiles(directory=root / "media")),
            Mount("/subs", StaticFiles(directory=root / "subs")),
            Mount("/hls", StaticFiles(directory=root / "hls")),
            Mount("/dash", StaticFiles(directory=root / "dash")),
        ]
    )
