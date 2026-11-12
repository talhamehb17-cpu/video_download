"""Analyze a link: validate it, read its public metadata, remember the result.

An :class:`Analysis` is the server-side record of what a source offered. Clients
only ever receive opaque ids (``q3``, ``s1``); the extractor details needed to act
on them stay here, so a client can never ask for something that wasn't offered.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urlsplit

from app.config import Settings
from app.errors import AppError
from app.platforms.registry import PlatformRegistry
from app.security.client import ClientIdentity
from app.security.url_validation import SourcePolicy, validate_public_url, validate_url_syntax
from app.services.formats import QualityChoice, SubtitleChoice, build_qualities, build_subtitles
from app.services.runner import run_worker
from app.services.storage import TempStorage

log = logging.getLogger(__name__)

T = TypeVar("T")

MAX_INFO_BYTES = 16 * 1024 * 1024
MAX_STORED_ANALYSES = 2000
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")


def clean_text(value: Any, *, limit: int = 300) -> str | None:
    """Make untrusted text from a source safe and tidy for display."""
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", _CONTROL_RE.sub(" ", value)).strip()
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def source_policy(settings: Settings, platforms: PlatformRegistry | None = None) -> SourcePolicy:
    return SourcePolicy(
        mode=settings.source_policy,
        allowed_domains=tuple(settings.allowed_domains),
        blocked_domains=tuple(settings.blocked_domains),
        allowed_ports=frozenset(settings.allowed_ports),
        exempt=settings.unsafe_allow_pairs,
        platforms=platforms,
    )


def worker_limits(settings: Settings) -> dict[str, Any]:
    return {
        "max_file_bytes": settings.max_file_size_bytes,
        "max_duration_seconds": settings.max_duration_seconds,
        "block_age_restricted": settings.block_age_restricted,
        "min_free_bytes": settings.min_free_disk_bytes,
    }


@dataclass
class Analysis:
    id: str
    client_key: str
    url: str
    directory: Path
    info_path: Path
    created_at: float
    expires_at: float
    title: str
    uploader: str | None
    duration: float | None
    domain: str
    extractor: str
    qualities: list[QualityChoice]
    subtitles: list[SubtitleChoice]
    notices: list[str]
    thumbnail: tuple[Path, str] | None = None
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    def quality(self, quality_id: str) -> QualityChoice:
        for choice in self.qualities:
            if choice.id == quality_id:
                return choice
        raise AppError("option_not_found")

    def subtitle(self, track_id: str) -> SubtitleChoice:
        for track in self.subtitles:
            if track.id == track_id:
                return track
        raise AppError("option_not_found")


class LightTaskLimiter:
    """Bounds short worker tasks (analysis, subtitles): globally and per client."""

    def __init__(self, concurrency: int, per_client: int) -> None:
        self._slots = asyncio.Semaphore(concurrency)
        self._max_waiting = concurrency * 4
        self._waiting = 0
        self._per_client = per_client
        self._active: Counter[str] = Counter()

    async def __call__(self, client_key: str, coroutine_factory: Callable[[], Awaitable[T]]) -> T:
        if self._active[client_key] >= self._per_client:
            raise AppError("rate_limited", message="You have too many requests in progress. Please wait a moment.",
                           retry_after=5)
        if self._waiting >= self._max_waiting:
            raise AppError("server_busy", retry_after=15)
        self._active[client_key] += 1
        self._waiting += 1
        try:
            async with self._slots:
                self._waiting -= 1
                try:
                    return await coroutine_factory()
                finally:
                    self._waiting += 1
        finally:
            self._waiting -= 1
            self._active[client_key] -= 1
            if self._active[client_key] <= 0:
                del self._active[client_key]


class AnalysisService:
    def __init__(
        self, settings: Settings, storage: TempStorage, ffmpeg_path: str | None,
        platforms: PlatformRegistry | None = None, on_failure: Callable[[str, AppError], None] | None = None,
    ) -> None:
        self._settings = settings
        self._storage = storage
        self._ffmpeg_path = ffmpeg_path
        self._platforms = platforms
        self._on_failure = on_failure
        self._policy = source_policy(settings, platforms)
        self._items: dict[str, Analysis] = {}
        self._light = LightTaskLimiter(settings.max_concurrent_light_tasks, settings.max_light_jobs_per_client)

    # ------------------------------------------------------------------ helpers
    def _base_task(self, kind: str, work_dir: Path) -> dict[str, Any]:
        return {
            "task": kind,
            "work_dir": str(work_dir),
            "ffmpeg_path": self._ffmpeg_path,
            "limits": worker_limits(self._settings),
            "exempt": [list(pair) for pair in self._settings.unsafe_allow_pairs],
            "nice": self._settings.worker_nice,
        }

    def __len__(self) -> int:
        return len(self._items)

    # ------------------------------------------------------------------ analyze
    async def analyze(self, raw_url: str, client: ClientIdentity) -> Analysis:
        validated = await validate_public_url(raw_url, self._policy)
        return await self._light(client.key, lambda: self._analyze(validated.url, validated.host, client))

    async def _analyze(self, url: str, host: str, client: ClientIdentity) -> Analysis:
        analysis_id = secrets.token_urlsafe(18)
        directory = self._storage.create("analyses", analysis_id)
        started = time.monotonic()
        try:
            task = self._base_task("analyze", directory) | {"url": url}
            result = await run_worker(
                task, timeout=self._settings.analyze_timeout_seconds, timeout_code="source_timeout"
            )
            analysis = self._build(analysis_id, url, host, directory, result, client)
        except AppError as exc:
            self._storage.remove(directory)
            log.info("analyze failed domain=%s code=%s client=%s detail=%s",
                     host, exc.code, client.log_label, (exc.detail or "")[:400])
            if self._platforms is not None:
                self._platforms.record(host, ok=False)
            if self._on_failure is not None:
                self._on_failure(host, exc)
            raise
        except BaseException:
            self._storage.remove(directory)
            raise
        self._items[analysis_id] = analysis
        self._evict_overflow()
        if self._platforms is not None:
            self._platforms.record(host, ok=True)
        log.info("analyze ok domain=%s extractor=%s qualities=%d subtitles=%d seconds=%.1f client=%s",
                 analysis.domain, analysis.extractor, len(analysis.qualities), len(analysis.subtitles),
                 time.monotonic() - started, client.log_label)
        return analysis

    def _build(
        self, analysis_id: str, url: str, host: str, directory: Path, result: dict[str, Any], client: ClientIdentity
    ) -> Analysis:
        info_path = directory / "info.json"
        if not info_path.is_file() or info_path.stat().st_size > MAX_INFO_BYTES:
            raise AppError("extraction_failed", detail="metadata missing or too large")
        info = json.loads(info_path.read_text(encoding="utf-8"))
        if not isinstance(info, dict):
            raise AppError("extraction_failed", detail="unexpected metadata shape")

        # The extractor may have followed the link to another site (an embedded
        # player, a redirect). The final page must satisfy the source policy too.
        raw_page_url = info.get("webpage_url")
        page_url: str = raw_page_url if isinstance(raw_page_url, str) else url
        domain = host
        try:
            page_host = (urlsplit(page_url).hostname or "").lower()
        except ValueError:
            page_host = ""
        if page_host and page_host != host:
            try:
                domain = validate_url_syntax(page_url, self._policy).host
            except AppError as exc:
                raise AppError("domain_not_allowed", detail=f"final page {page_host} rejected: {exc.code}") from exc

        ffmpeg = self._ffmpeg_path is not None
        summary = build_qualities(info, ffmpeg_available=ffmpeg, max_bytes=self._settings.max_file_size_bytes)
        if not summary.qualities:
            raise AppError("drm_protected" if summary.drm_only else "no_formats")

        notices = [str(code) for code in result.get("notices") or []]
        if not ffmpeg:
            notices.append("ffmpeg_unavailable")

        thumbnail: tuple[Path, str] | None = None
        thumb = result.get("thumbnail")
        if isinstance(thumb, dict):
            path = directory / str(thumb.get("file") or "")
            content_type = str(thumb.get("content_type") or "")
            if path.name.startswith("thumb.") and path.is_file() and content_type.startswith("image/"):
                thumbnail = (path, content_type)

        duration = info.get("duration")
        now = time.time()
        return Analysis(
            id=analysis_id,
            client_key=client.key,
            url=url,
            directory=directory,
            info_path=info_path,
            created_at=now,
            expires_at=now + self._settings.analysis_ttl_seconds,
            title=clean_text(info.get("title")) or "Untitled video",
            uploader=clean_text(info.get("uploader") or info.get("channel") or info.get("creator"), limit=120),
            duration=float(duration) if isinstance(duration, (int, float)) and duration > 0 else None,
            domain=domain.removeprefix("www."),
            extractor=clean_text(info.get("extractor_key"), limit=60) or "Generic",
            qualities=summary.qualities,
            subtitles=build_subtitles(info, ffmpeg_available=ffmpeg),
            notices=notices,
            thumbnail=thumbnail,
        )

    # ------------------------------------------------------------------ lookups
    def get(self, analysis_id: str) -> Analysis:
        analysis = self._items.get(analysis_id)
        if analysis is None or analysis.expires_at <= time.time():
            raise AppError("analysis_expired")
        return analysis

    # ------------------------------------------------------------------ subtitles
    async def subtitle_file(self, analysis: Analysis, track_id: str, target: str, client: ClientIdentity) -> Path:
        """Fetch one subtitle track as SRT or WebVTT (cached for the analysis lifetime)."""
        track = analysis.subtitle(track_id)
        if target not in track.formats:
            raise AppError("option_not_found")
        key = f"{track.id}.{target}"
        directory = analysis.directory / "subtitles" / key
        output = directory / f"track.{target}"
        lock = analysis.locks.setdefault(key, asyncio.Lock())
        async with lock:
            if output.is_file():
                return output
            if target != track.source_for(target) and self._ffmpeg_path is None:
                raise AppError("ffmpeg_unavailable")

            async def fetch() -> Path:
                directory.mkdir(parents=True, exist_ok=True)
                task = self._base_task("subtitle", directory) | {
                    "info_path": str(analysis.info_path),
                    "language": track.language,
                    "kind": track.kind,
                    "source_ext": track.source_for(target),
                    "target": target,
                    "output_name": output.name,
                }
                try:
                    await run_worker(
                        task, timeout=self._settings.subtitle_timeout_seconds, timeout_code="source_timeout"
                    )
                except BaseException as exc:
                    self._storage.remove(directory)
                    if isinstance(exc, AppError):
                        log.info("subtitle failed domain=%s lang=%s code=%s detail=%s",
                                 analysis.domain, track.language, exc.code, (exc.detail or "")[:300])
                    raise
                if not output.is_file():
                    raise AppError("subtitle_unavailable", detail="worker reported success without a file")
                return output

            return await self._light(client.key, fetch)

    # ------------------------------------------------------------------ housekeeping
    def _discard(self, analysis_id: str) -> None:
        analysis = self._items.pop(analysis_id, None)
        if analysis is not None:
            self._storage.remove(analysis.directory)

    def _evict_overflow(self) -> None:
        overflow = len(self._items) - MAX_STORED_ANALYSES
        if overflow > 0:
            for analysis_id in sorted(self._items, key=lambda i: self._items[i].created_at)[:overflow]:
                self._discard(analysis_id)

    def cleanup(self, now: float | None = None) -> int:
        """Delete expired analyses (metadata, poster, cached subtitles)."""
        now = time.time() if now is None else now
        expired = [i for i, a in self._items.items() if a.expires_at <= now and not any(
            lock.locked() for lock in a.locks.values()
        )]
        for analysis_id in expired:
            self._discard(analysis_id)
        return len(expired)
