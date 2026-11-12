"""Compatibility checks: what can this server do with a website, right now?

A check never downloads media. It asks the worker (same lock-down, same network
guard as every analysis) two things: does yt-dlp have a dedicated integration for
the website, and can one link be read without signing in. The answer becomes one
of four states:

* ``supported``       - a dedicated integration read a public video.
* ``partial``         - it works with limits (audio only, or known limits of the platform).
* ``unsupported``     - nothing can be downloaded within the rules of this service.
* ``requires_review`` - a person has to decide: only the generic reader found a
  video on a website that is not in the catalog, or the platform turned this
  server away.

A check that learned nothing about the website is recorded as not conclusive:
there was no link to test, the video behind the link no longer exists, or the
check could not be completed. The administrator sees why, and the status stays
what it was going to be without it.

Adding or checking a website never switches it on. That is a separate decision.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from urllib.parse import urlsplit

from app.config import Settings
from app.errors import ERRORS, AppError
from app.platforms.registry import CheckResult, Platform, PlatformRegistry
from app.services.analysis import clean_text, worker_limits
from app.services.runner import run_worker
from app.services.storage import TempStorage

log = logging.getLogger(__name__)

# The platform answered, but not with a video: a different link, or a different
# network, may well work. A person should look at it.
_TURNED_AWAY = {
    "login_required", "verification_required", "source_forbidden", "source_rate_limited", "geo_restricted",
    "age_restricted", "private_content", "paywalled", "live_stream", "too_long",
}
_NOTHING_THERE = {"unsupported_source", "no_formats", "unsupported_stream"}
_PAGE_READERS = {"Generic", "HTML5MediaEmbed"}


def _message(code: str) -> str:
    spec = ERRORS.get(code) or ERRORS["extraction_failed"]
    return spec.message


def interpret(
    result: dict[str, Any], *, given_url: str | None, seconds: float, catalogued: bool = False
) -> CheckResult:
    """Turn the worker's observations into a state and one sentence.

    ``catalogued`` says the website is a platform of the built-in catalog, where a
    person already decided that it belongs on the list.
    """
    integrations = [str(name) for name in result.get("integrations") or []]
    attempts = [a for a in result.get("attempts") or [] if isinstance(a, dict)]
    now = time.time()
    base: dict[str, Any] = {
        "at": now, "seconds": round(seconds, 1),
        "method": "extractor" if integrations else "none",
        "extractor": ", ".join(integrations[:4]) or None,
    }
    success = next((a for a in attempts if a.get("ok")), None)
    if success is not None:
        # Readers that look for a video file or player on any page are not an
        # integration of this website, whatever they are called.
        dedicated = bool(integrations) and str(success.get("extractor") or "Generic") not in _PAGE_READERS
        base |= {
            "url": str(success.get("url")), "title": clean_text(success.get("title"), limit=120),
            "qualities": int(success.get("streams") or 0), "max_height": success.get("max_height"),
            "subtitles": int(success.get("subtitles") or 0),
            "method": "extractor" if dedicated else "generic",
            "extractor": str(success.get("extractor")) if dedicated else None,
        }
        if not dedicated and catalogued:
            return CheckResult(status="partial", summary=(
                "A generic reader found a public video on the page without signing in. "
                "Pages that publish a plain video file work; other pages may not."
            ), **base)
        if not dedicated:
            return CheckResult(status="requires_review", summary=(
                "There is no dedicated integration for this website. A generic reader found a video on the page. "
                "Switch it on only if this website allows its videos to be downloaded."
            ), **base)
        if not success.get("video"):
            return CheckResult(status="partial", summary="The integration works, but only audio was offered.", **base)
        height = f" up to {success['max_height']}p" if success.get("max_height") else ""
        return CheckResult(status="supported", summary=f"A public video was read{height} without signing in.", **base)

    if not attempts:
        if integrations:
            summary = "An integration exists, but there was no link to test it with. Paste a link to a public video."
        elif catalogued:
            summary = "There are no sample links for this platform. Paste a link to a page with a video to test it."
        else:
            summary = "No integration is known for this website. Paste a link to a page with a video to test it."
        return CheckResult(status="requires_review", summary=summary, conclusive=False, **base)

    # Sample links are of different kinds, and one of them may simply be gone. What
    # happened to most of them describes the platform best; the first decides a tie.
    codes = [str(attempt.get("code") or "extraction_failed") for attempt in attempts]
    code = max(dict.fromkeys(codes), key=codes.count)
    shown = attempts[codes.index(code)]
    base |= {"url": str(shown.get("url")), "error_code": code, "error_message": _message(code)}
    # "Sample links" only when every link was one: the link of an earlier check may be among them.
    noun = "sample link" if result.get("sample_links", True) and not result.get("previous_link") else "link"
    if given_url or (len(attempts) == 1 and noun == "link"):
        tried = "the link"
    elif codes.count(code) == len(attempts):
        tried = f"{len(attempts)} {noun}{'s' if len(attempts) != 1 else ''}"
    else:
        tried = f"{codes.count(code)} of {len(attempts)} {noun}s"
    if code == "drm_protected":
        return CheckResult(status="unsupported", summary="The video is DRM-protected. Lumora never circumvents DRM.",
                           **base)
    if code == "blocked_destination":
        return CheckResult(status="unsupported", summary="The link leads to a private or internal address.", **base)
    if code in _NOTHING_THERE and not integrations:
        return CheckResult(status="unsupported", summary=(
            "No integration exists for this website and no video was found at the link."
        ), **base)
    if code in _TURNED_AWAY:
        return CheckResult(status="requires_review", summary=(
            f"The platform turned this server away for {tried}: {_message(code)} "
            "Try another public link. If every link ends like this, the platform doesn't work from this server."
        ), **base)
    if code == "not_found":
        # A video that is gone says nothing about the platform: nothing was learned.
        return CheckResult(status="requires_review", conclusive=False, summary=(
            f"The video behind {tried} no longer exists. Paste a link to a current public video."
        ), **base)
    return CheckResult(status="requires_review", summary=(
        f"Reading {tried} failed: {_message(code)} Try again later or with another link."
    ), **base)


def previous_link(platform: Platform) -> str | None:
    """The link the last check of this platform used, if it still belongs to the platform."""
    link = platform.check.url if platform.check is not None else None
    if not link:
        return None
    try:
        host = (urlsplit(link).hostname or "").lower()
    except ValueError:
        return None
    return link if host and platform.matches(host) else None


# Checks that may wait for their turn at once: enough for every platform on the list.
MAX_PENDING = 120


class CompatibilityChecker:
    """Runs checks in the background, one per platform and two at a time overall."""

    def __init__(
        self, settings: Settings, storage: TempStorage, registry: PlatformRegistry, ffmpeg_path: str | None
    ) -> None:
        self._settings = settings
        self._storage = storage
        self._registry = registry
        self._ffmpeg_path = ffmpeg_path
        self._slots = asyncio.Semaphore(2)
        self._tasks: set[asyncio.Task[None]] = set()
        self._serial = 0

    def start(self, platform: Platform, url: str | None) -> None:
        if platform.checking:
            raise AppError("check_in_progress")
        if len(self._tasks) >= MAX_PENDING:
            raise AppError("server_busy", retry_after=20)
        platform.checking = True
        task = asyncio.create_task(self._run(platform, url), name=f"check-{platform.id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def start_many(self, platforms: list[Platform]) -> int:
        """Queue a check with sample links for each platform that has none running. Returns how many."""
        started = 0
        for platform in platforms:
            if platform.checking or platform.declared == "unsupported" or len(self._tasks) >= MAX_PENDING:
                continue
            self.start(platform, None)
            started += 1
        return started

    @property
    def pending(self) -> int:
        return len(self._tasks)

    async def _run(self, platform: Platform, url: str | None) -> None:
        started = time.monotonic()
        self._serial += 1
        directory = self._storage.create("analyses", f"check-{self._serial:06d}-{int(time.time())}")
        # Without a link the worker reads the link of the previous check again, then
        # the integration's own sample links.
        previous = previous_link(platform) if url is None else None
        try:
            async with self._slots:
                started = time.monotonic()  # time spent waiting for a turn is not part of the check
                result = await run_worker(
                    {
                        "task": "compat", "work_dir": str(directory), "ffmpeg_path": self._ffmpeg_path,
                        "limits": worker_limits(self._settings), "url": url, "domains": list(platform.domains),
                        "fallback_url": previous,
                        "exempt": [list(pair) for pair in self._settings.unsafe_allow_pairs],
                        "nice": self._settings.worker_nice,
                    },
                    timeout=self._settings.admin_check_timeout_seconds, timeout_code="source_timeout",
                )
            for attempt in result.get("attempts") or []:
                if isinstance(attempt, dict) and not attempt.get("ok"):
                    # What the source said stays in the server log; the panel shows a fixed message.
                    log.info("compatibility check attempt failed platform=%s url=%s code=%s detail=%s",
                             platform.id, attempt.get("url"), attempt.get("code"),
                             str(attempt.get("detail") or "")[:300])
            check = interpret(
                result, given_url=url, seconds=time.monotonic() - started, catalogued=platform.builtin,
            )
        except AppError as exc:
            log.info("compatibility check failed platform=%s code=%s detail=%s",
                     platform.id, exc.code, (exc.detail or "")[:300])
            check = CheckResult(
                at=time.time(), status="requires_review", url=url, error_code=exc.code, error_message=exc.message,
                seconds=round(time.monotonic() - started, 1), conclusive=False,
                summary=f"The check could not be completed: {exc.message} Try again later.",
            )
        except asyncio.CancelledError:
            platform.checking = False
            raise
        except Exception:
            log.exception("compatibility check crashed platform=%s", platform.id)
            check = CheckResult(at=time.time(), status="requires_review", conclusive=False,
                                summary="The check failed unexpectedly. See the server log.")
        finally:
            self._storage.remove(directory)
        self._registry.set_check(platform, check)
        log.info("compatibility check platform=%s status=%s method=%s seconds=%.1f",
                 platform.id, check.status, check.method, check.seconds or 0)

    async def shutdown(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
