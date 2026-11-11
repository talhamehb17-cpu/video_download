"""The application's long-lived services, built once at start-up."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.config import Settings, parse_rate
from app.security.rate_limit import RateLimiter
from app.services.analysis import AnalysisService
from app.services.ffmpeg import ffmpeg_version, locate_ffmpeg
from app.services.jobs import JobManager
from app.services.storage import TempStorage


@dataclass
class Services:
    settings: Settings
    storage: TempStorage
    analyses: AnalysisService
    jobs: JobManager
    limiter: RateLimiter
    ffmpeg_path: str | None
    ffmpeg_version: str | None
    started_at: float = field(default_factory=time.monotonic)


def build_services(settings: Settings) -> Services:
    storage = TempStorage(settings.storage_dir)
    storage.prepare()
    ffmpeg_path = locate_ffmpeg(settings.ffmpeg_path)
    limiter = RateLimiter(
        {
            "analyze": parse_rate(settings.rate_limit_analyze),
            "jobs": parse_rate(settings.rate_limit_jobs),
            "status": parse_rate(settings.rate_limit_status),
            "files": parse_rate(settings.rate_limit_files),
            "default": parse_rate(settings.rate_limit_default),
        },
        enabled=settings.rate_limit_enabled,
    )
    return Services(
        settings=settings,
        storage=storage,
        analyses=AnalysisService(settings, storage, ffmpeg_path),
        jobs=JobManager(settings, storage, ffmpeg_path),
        limiter=limiter,
        ffmpeg_path=ffmpeg_path,
        ffmpeg_version=ffmpeg_version(ffmpeg_path),
    )
