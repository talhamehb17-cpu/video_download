"""The application's long-lived services, built once at start-up."""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from importlib import metadata
from typing import Any

from app.admin.auth import AdminAuth
from app.config import Settings, parse_rate
from app.errors import AppError
from app.platforms.registry import PlatformRegistry
from app.security.rate_limit import RateLimiter
from app.services.analysis import AnalysisService
from app.services.compat import CompatibilityChecker
from app.services.ffmpeg import ffmpeg_version, locate_ffmpeg
from app.services.jobs import JobManager
from app.services.storage import TempStorage

log = logging.getLogger(__name__)

MAX_REMEMBERED_ERRORS = 100
# Refusals that say something about the link, not about the integration.
_NOT_AN_INTEGRATION_ERROR = {"cancelled", "file_too_large", "too_long", "insufficient_storage", "job_timeout"}


@dataclass
class Services:
    settings: Settings
    storage: TempStorage
    platforms: PlatformRegistry
    admin: AdminAuth
    checker: CompatibilityChecker
    analyses: AnalysisService
    jobs: JobManager
    limiter: RateLimiter
    ffmpeg_path: str | None
    ffmpeg_version: str | None
    extractor_version: str
    errors: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=MAX_REMEMBERED_ERRORS))
    started_at: float = field(default_factory=time.monotonic)


def _extractor_version() -> str:
    try:
        return metadata.version("yt-dlp")
    except metadata.PackageNotFoundError:
        return "unknown"


def build_services(settings: Settings) -> Services:
    storage = TempStorage(settings.storage_dir)
    storage.prepare()
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        log.error("the data directory %s cannot be created (%s): admin and platform settings will not survive "
                  "a restart", settings.data_dir, exc)
    ffmpeg_path = locate_ffmpeg(settings.ffmpeg_path)
    platforms = PlatformRegistry(settings.data_dir)
    errors: deque[dict[str, Any]] = deque(maxlen=MAX_REMEMBERED_ERRORS)

    def remember(stage: str, host: str, error: AppError) -> None:
        """Keep the last failures for the administrator: the website and the reason, never the link."""
        if error.code in _NOT_AN_INTEGRATION_ERROR:
            return
        platform = platforms.match(host)
        errors.append({
            "at": time.time(), "stage": stage, "domain": host.removeprefix("www."),
            "platform": platform.name if platform else None, "code": error.code, "message": error.message,
        })

    limiter = RateLimiter(
        {
            "analyze": parse_rate(settings.rate_limit_analyze),
            "jobs": parse_rate(settings.rate_limit_jobs),
            "status": parse_rate(settings.rate_limit_status),
            "files": parse_rate(settings.rate_limit_files),
            "default": parse_rate(settings.rate_limit_default),
            "admin_login": parse_rate(settings.rate_limit_admin_login),
            "admin": parse_rate(settings.rate_limit_admin),
        },
        enabled=settings.rate_limit_enabled,
    )
    return Services(
        settings=settings,
        storage=storage,
        platforms=platforms,
        admin=AdminAuth(settings),
        checker=CompatibilityChecker(settings, storage, platforms, ffmpeg_path),
        analyses=AnalysisService(
            settings, storage, ffmpeg_path, platforms, on_failure=lambda host, exc: remember("analyze", host, exc)
        ),
        jobs=JobManager(
            settings, storage, ffmpeg_path, on_failure=lambda host, exc: remember("download", host, exc)
        ),
        limiter=limiter,
        ffmpeg_path=ffmpeg_path,
        ffmpeg_version=ffmpeg_version(ffmpeg_path),
        extractor_version=_extractor_version(),
        errors=errors,
    )
