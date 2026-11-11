"""Convert internal records into API responses (and decide what clients may see)."""

from __future__ import annotations

import time

from app import __version__, schemas
from app.errors import AppError
from app.security.url_validation import SourcePolicy, validate_url_syntax
from app.services.analysis import Analysis, source_policy
from app.services.jobs import Job, JobManager, JobStatus
from app.state import Services

API_PREFIX = "/api/v1"

NOTICES = {
    "playlist_first_item": "This link contains several videos. Showing the first one.",
    "ffmpeg_unavailable": "Media processing is limited on this server, so some options are hidden.",
    "subtitles_not_embedded": "Some subtitles couldn't be embedded. You can still download them separately.",
}

# Openly licensed films hosted by sources on the default allow list. Operators can
# replace them with EXAMPLE_LINKS.
EXAMPLES = (
    schemas.Example(
        label="Big Buck Bunny", source="Internet Archive", url="https://archive.org/details/BigBuckBunny_124"
    ),
    schemas.Example(
        label="Sintel", source="Wikimedia Commons",
        url="https://commons.wikimedia.org/wiki/File:Sintel_movie_4K.webm",
    ),
)


def _accepted(url: str, policy: SourcePolicy) -> bool:
    """Would this link pass the checks every pasted link goes through?"""
    try:
        validate_url_syntax(url, policy)
    except AppError:
        return False
    return True


def examples(services: Services) -> list[schemas.Example]:
    """Example links to offer. Never one that this server would then refuse."""
    settings = services.settings
    configured = settings.example_links
    candidates = EXAMPLES if configured is None else tuple(
        schemas.Example(label=label, source=source, url=url) for label, source, url in configured
    )
    policy = source_policy(settings)
    return [example for example in candidates if _accepted(example.url, policy)]


def notices(codes: list[str]) -> list[schemas.Notice]:
    return [schemas.Notice(code=code, message=NOTICES[code]) for code in dict.fromkeys(codes) if code in NOTICES]


def error_body(error: AppError) -> schemas.ErrorBody:
    return schemas.ErrorBody(code=error.code, message=error.message, hint=error.hint, retry_after=error.retry_after)


def analysis_response(analysis: Analysis) -> schemas.AnalysisResponse:
    return schemas.AnalysisResponse(
        id=analysis.id,
        url=analysis.url,
        title=analysis.title,
        uploader=analysis.uploader,
        duration=analysis.duration,
        thumbnail_url=f"{API_PREFIX}/analyses/{analysis.id}/thumbnail" if analysis.thumbnail else None,
        source=schemas.Source(domain=analysis.domain, extractor=analysis.extractor),
        qualities=[
            schemas.Quality(
                id=q.id, kind=q.kind, label=q.label, container=q.container,  # type: ignore[arg-type]
                height=q.height, width=q.width, fps=q.fps,
                video_codec=q.video_codec, audio_codec=q.audio_codec, has_audio=q.has_audio,
                requires_merge=q.requires_merge, filesize=q.size, filesize_is_estimate=q.size_is_estimate,
                bitrate_kbps=round(q.bitrate_kbps, 1) if q.bitrate_kbps else None,
                dynamic_range=q.dynamic_range, can_embed_subtitles=q.can_embed_subtitles,
                exceeds_limit=q.exceeds_limit, recommended=q.recommended,
            )
            for q in analysis.qualities
        ],
        subtitles=[
            schemas.SubtitleTrack(
                id=t.id, language=t.language, name=t.name, kind=t.kind,  # type: ignore[arg-type]
                formats=list(t.formats), embeddable=t.embeddable,  # type: ignore[arg-type]
            )
            for t in analysis.subtitles
        ],
        notices=notices(analysis.notices),
        expires_in=max(0, int(analysis.expires_at - time.time())),
    )


def job_response(job: Job, manager: JobManager) -> schemas.JobResponse:
    file: schemas.FileInfo | None = None
    if job.status is JobStatus.COMPLETED and job.file_name and job.file_size is not None and job.expires_at:
        file = schemas.FileInfo(
            name=job.file_name,
            size=job.file_size,
            container=job.container or job.quality.container,
            url=f"{API_PREFIX}/jobs/{job.id}/file",
            expires_in=max(0, int(job.expires_at - time.time())),
        )
    progress = job.progress
    return schemas.JobResponse(
        id=job.id,
        status=job.status.value,
        stage=job.stage,
        stage_detail=job.stage_detail,
        queue_position=manager.queue_position(job),
        title=job.title,
        quality_label=job.quality.label,
        container=job.container or job.quality.container,
        progress=schemas.ProgressInfo(
            percent=progress.percent,
            downloaded_bytes=progress.downloaded_bytes,
            total_bytes=progress.total_bytes,
            speed_bps=progress.speed_bps,
            eta_seconds=progress.eta_seconds,
            part=progress.part,
            parts=progress.parts,
            part_kind=progress.part_kind,
        ),
        file=file,
        error=error_body(job.error) if job.error else None,
        embedded_subtitles=job.embedded_subtitles,
        notices=notices(job.notices),
    )


def config_response(services: Services) -> schemas.ConfigResponse:
    settings = services.settings
    ffmpeg = services.ffmpeg_path is not None
    allowlist = settings.source_policy == "allowlist"
    domains = sorted(settings.allowed_domains) if allowlist else []
    return schemas.ConfigResponse(
        name=settings.app_name,
        version=__version__,
        limits=schemas.Limits(
            max_file_size_bytes=settings.max_file_size_bytes,
            max_duration_seconds=settings.max_duration_seconds,
            file_ttl_seconds=settings.file_ttl_seconds,
            analysis_ttl_seconds=settings.analysis_ttl_seconds,
        ),
        capabilities=schemas.Capabilities(
            merge=ffmpeg,
            subtitle_conversion=ffmpeg,
            subtitle_embedding=ffmpeg,
            subtitle_formats=["srt", "vtt"],
        ),
        sources=schemas.SourcePolicyInfo(mode=settings.source_policy, domains=domains, examples=examples(services)),
    )


def health_response(services: Services) -> schemas.HealthResponse:
    return schemas.HealthResponse(
        status="ok",
        version=__version__,
        ffmpeg=services.ffmpeg_path is not None,
        active_jobs=services.jobs.count(JobStatus.RUNNING),
        queued_jobs=services.jobs.count(JobStatus.QUEUED),
        uptime_seconds=int(time.monotonic() - services.started_at),
    )
