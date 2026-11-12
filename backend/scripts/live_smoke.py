#!/usr/bin/env python3
"""Live smoke test against real public sources (needs open internet access).

Runs the real application in-process with its default configuration (platform
list, public-network rule fully enforced) and, for each sample link:

    analyze -> list qualities/subtitles -> download the smallest quality
            -> fetch one subtitle track (when the source has any)

The sample links are openly licensed films on the Internet Archive and Wikimedia
Commons. These must work: a failure fails the run.

    python scripts/live_smoke.py
    python scripts/live_smoke.py https://archive.org/details/SomeItem

With ``--survey`` it then signs in as the administrator of that in-process
application and runs the same compatibility check the admin panel offers
("Check everything that is switched on") for every platform on the list. A check
reads one public video per platform and downloads nothing. The outcome says what
worked from the machine this ran on, on that day. It never fails the run: many
platforms turn away data-centre addresses, and that is a fact to report, not a bug.

    python scripts/live_smoke.py --survey          # the downloads, then the survey
    python scripts/live_smoke.py --survey-only     # only the survey
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
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
SURVEY_MINUTES = 25
ADMIN_EMAIL = "survey@example.org"
ADMIN_FIRST = "survey-initial-password"
ADMIN_PASSWORD = "survey only passphrase 2026"


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


class FailedAttempts(logging.Handler):
    """Collects what the sources answered when a check could not read a link.

    The API never shows this text to anyone; it writes it to its log. The survey
    reads it from there, so that a failure can be told apart from a refusal.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.by_platform: dict[str, list[str]] = {}

    def emit(self, record: logging.LogRecord) -> None:
        if not str(record.msg).startswith("compatibility check attempt failed") or not isinstance(record.args, tuple):
            return
        platform, url, code, detail = record.args
        text = " ".join(str(detail).split()).removeprefix("DownloadError: ").removeprefix("ERROR: ")
        text = re.sub(r";? ?please rep.*$", "", text)  # the extractor's standard request to report a bug
        self.by_platform.setdefault(str(platform), []).append(f"{code} for {url}: {text}")


async def survey(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Check every platform that is switched on, the way the admin panel does. Returns one row per platform."""
    signed_in = await client.post("/api/v1/admin/login", json={"email": ADMIN_EMAIL, "password": ADMIN_FIRST})
    signed_in.raise_for_status()
    changed = await client.post(
        "/api/v1/admin/password", headers={"Authorization": f"Bearer {signed_in.json()['token']}"},
        json={"current_password": ADMIN_FIRST, "new_password": ADMIN_PASSWORD},
    )
    changed.raise_for_status()
    headers = {"Authorization": f"Bearer {changed.json()['token']}"}

    queued = await client.post("/api/v1/admin/platform-checks", headers=headers)
    queued.raise_for_status()
    print(f"survey: {queued.json()['started']} checks queued, two at a time", flush=True)
    deadline = time.monotonic() + SURVEY_MINUTES * 60
    platforms: list[dict[str, Any]] = []
    reported: set[str] = set()
    while True:
        platforms = (await client.get("/api/v1/admin/platforms", headers=headers)).json()["platforms"]
        for platform in platforms:
            check_ = platform["check"]
            if check_ and not platform["checking"] and platform["id"] not in reported:
                reported.add(platform["id"])
                detail = check_["error_code"] or check_["extractor"] or check_["method"]
                print(f"survey: {platform['name']}: {OUTCOMES[outcome(platform)]} ({detail}, {check_['seconds']} s)",
                      flush=True)
        if not any(platform["checking"] for platform in platforms) or time.monotonic() > deadline:
            break
        await asyncio.sleep(5)
    return [platform for platform in platforms if platform["active"] or platform["check"]]


OUTCOMES = {
    "read": "read a public video",
    "refused": "turned away, or the sample links failed",
    "untested": "nothing to test with",
    "unsupported": "unsupported",
    "unfinished": "not finished",
}


def outcome(platform: dict[str, Any]) -> str:
    """What the check of one platform observed, as a key of OUTCOMES."""
    result = platform["check"]
    if platform["checking"] or not result:
        return "unfinished"
    if not result.get("conclusive", True):
        return "untested"
    if result["qualities"] and not result["error_code"]:
        return "read"
    return "unsupported" if platform["status"] == "unsupported" else "refused"


def survey_report(platforms: list[dict[str, Any]], attempts: dict[str, list[str]] | None = None) -> None:
    """Print the survey: a table for the run summary, and one annotation per outcome."""
    def facts(platform: dict[str, Any]) -> str:
        result = platform["check"]
        kind = outcome(platform)
        if kind in ("unfinished", "untested"):
            return OUTCOMES[kind]
        if result["error_code"]:
            return str(result["error_code"])
        if not result["qualities"]:
            return "no video"
        # Some sources do not state the resolution of their files; that says nothing about the content.
        size = f"{result['max_height']}p" if result["max_height"] else "resolution not stated"
        parts = [size, f"{result['qualities']} qualities"]
        if result["subtitles"]:
            parts.append(f"{result['subtitles']} subtitle languages")
        if result["method"] == "generic":
            parts.append("generic reader")
        parts.append(f"{result['seconds']} s")
        return ", ".join(parts)

    groups: dict[str, list[dict[str, Any]]] = {key: [] for key in OUTCOMES}
    for platform in platforms:
        groups[outcome(platform)].append(platform)

    order = list(OUTCOMES)
    header = ("Platform", "Outcome", "Status after the check", "What the check saw", "Link")
    lines = [f"| {' | '.join(header)} |", f"| {' | '.join('---' for _ in header)} |"]
    for platform in sorted(platforms, key=lambda p: (order.index(outcome(p)), p["name"].lower())):
        result = platform["check"] or {}
        summary = result.get("summary") or "The check did not finish in time."
        cells = (platform["name"], OUTCOMES[outcome(platform)], platform["status"], f"{facts(platform)}: {summary}",
                 result.get("url") or "")
        lines.append(f"| {' | '.join(cells)} |")
    table = "\n".join(lines)
    # "Read a public video" is the fact. The status adds what the catalog knows about limits.
    headline = (
        f"{len(groups['read'])} of {len(platforms)} platforms gave a public video to this machine without signing in; "
        f"{len(groups['refused'])} turned it away or their sample links failed, "
        f"{len(groups['untested'])} had nothing to test with, "
        f"{len(groups['unsupported'])} unsupported, {len(groups['unfinished'])} not finished"
    )
    print(f"\nPlatform survey: {headline}\n{table}")

    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::notice title=Platform survey from this runner::{headline}")
        for key, members in groups.items():
            if not members:
                continue
            text = "; ".join(f"{p['name']} ({facts(p)})" for p in sorted(members, key=lambda p: p["name"].lower()))
            text = text.replace("%", "%25").replace("\r", " ").replace("\n", " ")
            # An annotation holds a limited amount of text: split long lists.
            chunks = [text[i:i + 1700] for i in range(0, len(text), 1700)]
            for index, chunk in enumerate(chunks, start=1):
                part = f" {index}/{len(chunks)}" if len(chunks) > 1 else ""
                print(f"::notice title=Platform survey - {OUTCOMES[key]}{part} - {len(members)}::{chunk}")

    # What the sources answered where no link could be read: the first attempt that ended with the reported code.
    names = {platform["id"]: platform["name"] for platform in platforms}
    codes = {platform["id"]: (platform["check"] or {}).get("error_code") for platform in platforms}
    answers: list[str] = []
    for platform_id, rows in sorted((attempts or {}).items(), key=lambda item: names.get(item[0], item[0]).lower()):
        if codes.get(platform_id) is None:
            continue  # a later sample link worked
        shown = next((row for row in rows if row.startswith(f"{codes[platform_id]} ")), rows[0])
        answers.append(f"{names.get(platform_id, platform_id)}: {shown[:300]}")
    if answers:
        print("\nWhat the sources answered:\n" + "\n".join(f"- {answer}" for answer in answers))
        if os.environ.get("GITHUB_ACTIONS"):
            text = " || ".join(answers).replace("%", "%25").replace("\r", " ").replace("\n", " ")
            chunks = [text[i:i + 1700] for i in range(0, len(text), 1700)][:5]
            for index, chunk in enumerate(chunks, start=1):
                print(f"::notice title=Platform survey - what the sources answered {index}/{len(chunks)}::{chunk}")
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with Path(summary_file).open("a", encoding="utf-8") as handle:
            handle.write(f"## Platform survey from this runner\n\n{headline}\n\n{table}\n")
            if answers:
                listed = "\n".join(f"- {answer}" for answer in answers)
                handle.write(f"\n### What the sources answered\n\n{listed}\n")


async def main() -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None, dict[str, list[str]]]:
    arguments = sys.argv[1:]
    only_survey = "--survey-only" in arguments
    with_survey = only_survey or "--survey" in arguments
    urls = [argument for argument in arguments if not argument.startswith("--")]
    urls = urls or [example.url for example in EXAMPLES]
    attempts = FailedAttempts()
    with tempfile.TemporaryDirectory(prefix="lumora-smoke-") as tmp:
        settings = Settings(
            _env_file=None, environment="test", storage_dir=Path(tmp) / "storage", data_dir=Path(tmp) / "data",
            rate_limit_enabled=False, log_level="WARNING", max_file_size_mb=1024, min_free_disk_mb=0,
            job_timeout_seconds=900, analyze_timeout_seconds=90,
            admin_email=ADMIN_EMAIL if with_survey else None,
            admin_bootstrap_password=ADMIN_FIRST if with_survey else None,
        )
        app = create_app(settings)
        # The checker writes what a source answered to the log only; listen there, without printing it twice.
        checker_log = logging.getLogger("app.services.compat")
        checker_log.setLevel(logging.INFO)
        checker_log.addHandler(attempts)
        checker_log.propagate = False
        transport = httpx.ASGITransport(app=app)
        api = httpx.AsyncClient(transport=transport, base_url="http://api.local", timeout=1200)
        async with app.router.lifespan_context(app), api as client:
            config = (await client.get("/api/v1/config")).json()
            print(f"policy={config['sources']['mode']} domains={len(config['sources']['domains'])}", flush=True)
            rows = [] if only_survey else [await check(client, url) for url in urls]
            platforms = await survey(client) if with_survey else None

    return rows, platforms, attempts.by_platform


def report(rows: list[dict[str, Any]]) -> int:
    lines = ["| Link | Result | Details |", "| --- | --- | --- |"]
    for row in rows:
        details = "; ".join(f"{k}: {v}" for k, v in row.items() if k not in ("url", "ok", "error"))
        result = "passed" if row["ok"] else f"FAILED ({row.get('error')})"
        lines.append(f"| {row['url']} | {result} | {details} |")
    text = "\n".join(lines)
    print(text)
    if os.environ.get("GITHUB_ACTIONS"):
        # One annotation per link, so the outcome is visible on the run page itself.
        for row in rows:
            details = "; ".join(f"{k}: {v}" for k, v in row.items() if k not in ("url", "ok", "error"))
            level, title = ("notice", "passed") if row["ok"] else ("error", f"FAILED ({row.get('error')})")
            message = f"{row['url']} | {details}".replace("%", "%25").replace("\r", " ").replace("\n", " ")
            print(f"::{level} title=Live smoke test {title}::{message[:1800]}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as handle:
            handle.write("## Live smoke test\n\n" + text + "\n")
    return 0 if all(row["ok"] for row in rows) else 1


if __name__ == "__main__":
    smoke_rows, surveyed, failed_attempts = asyncio.run(main())
    exit_code = report(smoke_rows) if smoke_rows else 0
    if surveyed is not None:
        survey_report(surveyed, failed_attempts)
    raise SystemExit(exit_code)
