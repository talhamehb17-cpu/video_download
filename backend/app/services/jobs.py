"""Background download jobs: queueing, real progress, cancellation and expiry.

State is kept in this process (one API process owns its workers and its temporary
files). To scale out, put the job records in Redis and the finished files in
object storage; the HTTP layer only depends on the methods of :class:`JobManager`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import shutil
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.config import Settings
from app.errors import AppError
from app.security.client import ClientIdentity
from app.security.filenames import build_filename
from app.services.analysis import Analysis, worker_limits
from app.services.formats import QualityChoice, SubtitleChoice
from app.services.runner import run_worker
from app.services.storage import TempStorage

log = logging.getLogger(__name__)


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"      # the file reached its time limit and was deleted
    DELETED = "deleted"      # the user asked for the file to be deleted


ACTIVE = (JobStatus.QUEUED, JobStatus.RUNNING)
MEDIA_TYPES = {
    "mp4": "video/mp4", "m4v": "video/mp4", "mov": "video/quicktime", "webm": "video/webm",
    "mkv": "video/x-matroska", "m4a": "audio/mp4", "mp3": "audio/mpeg", "ogg": "audio/ogg",
    "oga": "audio/ogg", "opus": "audio/ogg", "flac": "audio/flac", "wav": "audio/wav",
    "aac": "audio/aac", "weba": "audio/webm", "mka": "audio/x-matroska",
}


@dataclass
class Progress:
    percent: float | None = None
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed_bps: float | None = None
    eta_seconds: float | None = None
    part: int | None = None
    parts: int | None = None
    part_kind: str | None = None


@dataclass
class Job:
    id: str
    client_key: str
    title: str
    domain: str
    quality: QualityChoice
    embed: list[SubtitleChoice]
    directory: Path
    created_at: float
    status: JobStatus = JobStatus.QUEUED
    stage: str = "queued"
    stage_detail: str | None = None
    progress: Progress = field(default_factory=Progress)
    started_at: float | None = None
    finished_at: float | None = None
    expires_at: float | None = None
    file_path: Path | None = None
    file_name: str | None = None
    file_size: int | None = None
    container: str | None = None
    error: AppError | None = None
    embedded_subtitles: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    downloads: int = 0
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    @property
    def media_type(self) -> str:
        return MEDIA_TYPES.get(self.container or "", "application/octet-stream")


class JobManager:
    def __init__(self, settings: Settings, storage: TempStorage, ffmpeg_path: str | None) -> None:
        self._settings = settings
        self._storage = storage
        self._ffmpeg_path = ffmpeg_path
        self._jobs: dict[str, Job] = {}
        self._slots = asyncio.Semaphore(settings.max_concurrent_jobs)

    # ------------------------------------------------------------------ queries
    def get(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise AppError("job_not_found")
        return job

    def count(self, *statuses: JobStatus) -> int:
        return sum(1 for job in self._jobs.values() if job.status in statuses)

    def queue_position(self, job: Job) -> int | None:
        if job.status is not JobStatus.QUEUED:
            return None
        return 1 + sum(
            1 for other in self._jobs.values()
            if other.status is JobStatus.QUEUED and other.created_at < job.created_at
        )

    # ------------------------------------------------------------------ create
    def create(
        self, analysis: Analysis, quality: QualityChoice, embed: list[SubtitleChoice], client: ClientIdentity
    ) -> Job:
        if quality.exceeds_limit:
            raise AppError("file_too_large")
        if embed and not quality.can_embed_subtitles:
            raise AppError("embed_unsupported")
        if quality.requires_merge and self._ffmpeg_path is None:
            raise AppError("ffmpeg_unavailable")
        mine = sum(1 for job in self._jobs.values() if job.client_key == client.key and job.status in ACTIVE)
        if mine >= self._settings.max_active_jobs_per_client:
            raise AppError("too_many_jobs")
        if self.count(JobStatus.QUEUED) >= self._settings.max_queued_jobs:
            raise AppError("server_busy", retry_after=30)
        if self._storage.free_bytes() < self._settings.min_free_disk_mb * 1024 * 1024:
            raise AppError("storage_full", retry_after=60)

        job_id = secrets.token_urlsafe(18)
        directory = self._storage.create("jobs", job_id)
        # Keep a private copy of the metadata so the job doesn't depend on the
        # analysis still existing when it leaves the queue.
        shutil.copyfile(analysis.info_path, directory / "info.json")
        job = Job(
            id=job_id,
            client_key=client.key,
            title=analysis.title,
            domain=analysis.domain,
            quality=quality,
            embed=list(embed),
            directory=directory,
            created_at=time.time(),
        )
        self._jobs[job_id] = job
        job.task = asyncio.create_task(self._run(job), name=f"job-{job_id[:6]}")
        log.info("job created id=%s domain=%s quality=%s container=%s merge=%s embed=%d client=%s",
                 job_id[:6], job.domain, quality.label, quality.container, quality.requires_merge,
                 len(embed), client.log_label)
        return job

    # ------------------------------------------------------------------ run
    def _task(self, job: Job) -> dict[str, Any]:
        quality = job.quality
        multi = len(quality.parts) > 1
        return {
            "task": "download",
            "work_dir": str(job.directory),
            "info_path": str(job.directory / "info.json"),
            "ffmpeg_path": self._ffmpeg_path,
            "format_spec": quality.format_spec,
            "container": quality.container,
            "parts": [
                {
                    "format_id": part.format_id,
                    "kind": ("audio" if part.kind == "audio" else "video") if multi else
                            ("audio" if quality.kind == "audio" else "media"),
                    "size": part.size,
                }
                for part in quality.parts
            ],
            "embed_subtitles": [{"language": t.language, "kind": t.kind} for t in job.embed],
            "limits": worker_limits(self._settings),
            "exempt": [list(pair) for pair in self._settings.unsafe_allow_pairs],
            "nice": self._settings.worker_nice,
        }

    def _on_event(self, job: Job, event: dict[str, Any]) -> None:
        kind = event.get("event")
        if kind == "progress":
            job.stage = "downloading"
            job.stage_detail = None
            job.progress = Progress(
                percent=event.get("percent"),
                downloaded_bytes=int(event.get("downloaded_bytes") or 0),
                total_bytes=event.get("total_bytes"),
                speed_bps=event.get("speed_bps"),
                eta_seconds=event.get("eta_seconds"),
                part=event.get("part"),
                parts=event.get("parts"),
                part_kind=event.get("part_kind"),
            )
        elif kind == "stage":
            job.stage = str(event.get("stage") or job.stage)
            job.stage_detail = event.get("detail")
            if job.stage == "processing":
                # Post-processing reports no measurable progress, so none is shown.
                job.progress.percent = None
                job.progress.speed_bps = None
                job.progress.eta_seconds = None

    async def _run(self, job: Job) -> None:
        try:
            async with self._slots:
                if job.status is not JobStatus.QUEUED:
                    return
                job.status, job.stage, job.started_at = JobStatus.RUNNING, "starting", time.time()
                result = await run_worker(
                    self._task(job),
                    timeout=self._settings.job_timeout_seconds,
                    on_event=lambda event: self._on_event(job, event),
                )
            self._finish(job, result)
        except AppError as exc:
            self._fail(job, exc)
        except asyncio.CancelledError:
            self._close(job, JobStatus.CANCELLED)
        except Exception:
            log.exception("job %s crashed", job.id[:6])
            self._fail(job, AppError("internal_error"))

    def _finish(self, job: Job, result: dict[str, Any]) -> None:
        path = job.directory / str(result.get("file") or "")
        if not path.is_file() or not self._storage.contains(path):
            self._fail(job, AppError("download_failed", detail="result file is missing"))
            return
        with contextlib.suppress(OSError):
            (job.directory / "info.json").unlink()
        now = time.time()
        ext = path.suffix.lstrip(".").lower()
        job.file_path, job.file_size, job.container = path, path.stat().st_size, ext
        suffix = job.quality.label if job.quality.kind == "video" and job.quality.height else None
        job.file_name = build_filename(job.title, ext, suffix=suffix)
        job.embedded_subtitles = [str(lang) for lang in result.get("embedded_subtitles") or []]
        if set(result.get("subtitles_requested") or []) - set(job.embedded_subtitles):
            job.notices.append("subtitles_not_embedded")
        job.progress.percent, job.progress.speed_bps, job.progress.eta_seconds = 100.0, None, None
        job.status, job.stage, job.stage_detail = JobStatus.COMPLETED, "ready", None
        job.finished_at, job.expires_at = now, now + self._settings.file_ttl_seconds
        log.info("job done id=%s bytes=%d seconds=%.1f", job.id[:6], job.file_size, now - (job.started_at or now))

    def _fail(self, job: Job, error: AppError) -> None:
        if job.status not in ACTIVE:
            return
        job.error = error
        self._close(job, JobStatus.FAILED)
        log.info("job failed id=%s code=%s detail=%s", job.id[:6], error.code, (error.detail or "")[:400])

    def _close(self, job: Job, status: JobStatus) -> None:
        """Move a job to a terminal state and delete everything it wrote."""
        self._storage.remove(job.directory)
        job.file_path = None
        job.status, job.stage, job.stage_detail = status, status.value, None
        job.finished_at = job.finished_at or time.time()
        job.progress.speed_bps = job.progress.eta_seconds = None

    # ------------------------------------------------------------------ cancel / delete
    async def cancel(self, job: Job) -> Job:
        """Stop a queued or running job, or delete a finished file right away."""
        if job.status in ACTIVE:
            job.status = JobStatus.CANCELLED  # visible immediately, even before the worker has stopped
            task = job.task
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await asyncio.wait_for(asyncio.shield(task), timeout=10)
            self._close(job, JobStatus.CANCELLED)
            log.info("job cancelled id=%s", job.id[:6])
        elif job.status is JobStatus.COMPLETED:
            self._close(job, JobStatus.DELETED)
            log.info("job file deleted on request id=%s", job.id[:6])
        return job

    # ------------------------------------------------------------------ housekeeping
    def cleanup(self, now: float | None = None) -> tuple[int, int]:
        """Delete expired files and forget old records. Returns ``(expired, forgotten)``."""
        now = time.time() if now is None else now
        expired = forgotten = 0
        for job_id, job in list(self._jobs.items()):
            if job.status is JobStatus.COMPLETED and job.expires_at is not None and job.expires_at <= now:
                self._close(job, JobStatus.EXPIRED)
                expired += 1
            finished = job.status not in ACTIVE and job.status is not JobStatus.COMPLETED
            if finished and now - (job.finished_at or job.created_at) >= self._settings.job_record_ttl_seconds:
                del self._jobs[job_id]
                forgotten += 1
        return expired, forgotten

    async def shutdown(self) -> None:
        """Stop every worker. Called when the service stops."""
        tasks = [job.task for job in self._jobs.values() if job.task is not None and not job.task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
