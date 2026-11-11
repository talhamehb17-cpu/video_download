#!/usr/bin/env python3
"""Live smoke test against real public sources (needs open internet access).

Runs the real application in-process with its default configuration (allow-list
policy, public-network rule fully enforced) and, for each sample link:

    analyze -> list qualities/subtitles -> download the smallest quality
            -> fetch one subtitle track (when the source has any)

The sample links are openly licensed films on sources from the default allow list.

    python scripts/live_smoke.py
    python scripts/live_smoke.py https://archive.org/details/SomeItem
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.presenters import EXAMPLES  # noqa: E402

MAX_DOWNLOAD_BYTES = 400 * 1024 * 1024


async def check(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    row: dict[str, Any] = {"url": url, "ok": False}
    started = time.monotonic()
    response = await client.post("/api/v1/analyze", json={"url": url})
    if response.status_code != 200:
        row["error"] = f"analyze: {response.json()['error']['code']}"
        return row
    analysis = response.json()
    row |= {
        "title": analysis["title"], "extractor": analysis["source"]["extractor"],
        "duration": analysis["duration"], "thumbnail": bool(analysis["thumbnail_url"]),
        "qualities": [f"{q['label']}/{q['container']}" for q in analysis["qualities"]],
        "subtitles": [f"{s['language']}{'*' if s['kind'] == 'auto' else ''}" for s in analysis["subtitles"]],
        "analyze_seconds": round(time.monotonic() - started, 1),
    }

    # Prefer the smallest known-size option to keep the test light on the source.
    sized = [q for q in analysis["qualities"] if q["filesize"] and not q["exceeds_limit"]]
    pool = sized or [q for q in analysis["qualities"] if not q["exceeds_limit"]]
    quality = min(pool, key=lambda q: q["filesize"] or 0) if sized else pool[-1]
    if quality["filesize"] and quality["filesize"] > MAX_DOWNLOAD_BYTES:
        row["download"] = f"skipped: smallest option is {quality['filesize'] / 1e6:.0f} MB"
    else:
        started = time.monotonic()
        created = await client.post("/api/v1/jobs", json={"analysis_id": analysis["id"], "quality_id": quality["id"]})
        if created.status_code != 202:
            row["error"] = f"job: {created.json()['error']['code']}"
            return row
        job = created.json()
        while job["status"] in ("queued", "running"):
            await asyncio.sleep(1)
            job = (await client.get(f"/api/v1/jobs/{job['id']}")).json()
        if job["status"] != "completed":
            row["error"] = f"download: {(job.get('error') or {}).get('code', job['status'])}"
            return row
        head = await client.get(job["file"]["url"], headers={"Range": "bytes=0-1023"})
        row["download"] = (
            f"{quality['label']}/{job['file']['container']} {job['file']['size'] / 1e6:.1f} MB "
            f"in {time.monotonic() - started:.0f}s (range request: {head.status_code})"
        )
        await client.delete(f"/api/v1/jobs/{job['id']}")

    if analysis["subtitles"]:
        track = analysis["subtitles"][0]
        sub = await client.get(
            f"/api/v1/analyses/{analysis['id']}/subtitles/{track['id']}", params={"format": "srt"}
        )
        if sub.status_code != 200 or "-->" not in sub.text:
            row["error"] = f"subtitle: {sub.json()['error']['code'] if sub.status_code != 200 else 'not SRT'}"
            return row
        row["subtitle"] = f"{track['language']} srt, {len(sub.content)} bytes"
    row["ok"] = True
    return row


async def main() -> list[dict[str, Any]]:
    urls = sys.argv[1:] or [example.url for example in EXAMPLES]
    with tempfile.TemporaryDirectory(prefix="lumora-smoke-") as tmp:
        settings = Settings(
            _env_file=None, environment="test", storage_dir=Path(tmp) / "storage", rate_limit_enabled=False,
            log_level="WARNING", max_file_size_mb=1024, min_free_disk_mb=0, job_timeout_seconds=900,
            analyze_timeout_seconds=90,
        )
        app = create_app(settings)
        transport = httpx.ASGITransport(app=app)
        api = httpx.AsyncClient(transport=transport, base_url="http://api.local", timeout=1200)
        async with app.router.lifespan_context(app), api as client:
            config = (await client.get("/api/v1/config")).json()
            print(f"policy={config['sources']['mode']} domains={config['sources']['domains']}")
            rows = [await check(client, url) for url in urls]

    return rows


def report(rows: list[dict[str, Any]]) -> int:
    lines = ["| Link | Result | Details |", "| --- | --- | --- |"]
    for row in rows:
        details = "; ".join(f"{k}: {v}" for k, v in row.items() if k not in ("url", "ok", "error"))
        result = "passed" if row["ok"] else f"FAILED ({row.get('error')})"
        lines.append(f"| {row['url']} | {result} | {details} |")
    text = "\n".join(lines)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as handle:
            handle.write("## Live smoke test\n\n" + text + "\n")
    return 0 if all(row["ok"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(report(asyncio.run(main())))
