"""Convert internal records into API responses (and decide what clients may see)."""

from __future__ import annotations

import re
import time
from dataclasses import asdict

from app import __version__, schemas
from app.admin.auth import Session
from app.errors import AppError
from app.platforms.registry import STATUSES, Platform, PlatformRegistry
from app.security.url_validation import SourcePolicy, domain_matches, validate_url_syntax
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
    policy = source_policy(settings, services.platforms)
    return [example for example in candidates if _accepted(example.url, policy)]


def notices(codes: list[str]) -> list[schemas.Notice]:
    return [schemas.Notice(code=code, message=NOTICES[code]) for code in dict.fromkeys(codes) if code in NOTICES]


def error_body(error: AppError) -> schemas.ErrorBody:
    return schemas.ErrorBody(code=error.code, message=error.message, hint=error.hint, retry_after=error.retry_after)


def analysis_response(analysis: Analysis, platforms: PlatformRegistry | None = None) -> schemas.AnalysisResponse:
    platform = platforms.match(analysis.domain) if platforms is not None else None
    return schemas.AnalysisResponse(
        id=analysis.id,
        url=analysis.url,
        title=analysis.title,
        uploader=analysis.uploader,
        duration=analysis.duration,
        thumbnail_url=f"{API_PREFIX}/analyses/{analysis.id}/thumbnail" if analysis.thumbnail else None,
        source=schemas.Source(
            domain=analysis.domain, extractor=analysis.extractor, platform=platform.name if platform else None
        ),
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
        age_restricted=analysis.age_restricted,
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
    if settings.source_policy == "allowlist":
        domains = sorted(settings.allowed_domains)
    elif settings.source_policy == "platforms":
        domains = services.platforms.active_domains()
    else:
        domains = []
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
            age_confirmation=settings.age_confirmation and not settings.block_age_restricted,
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


# ---------------------------------------------------------------------------- platforms
_UNCONFIRMED = "Not confirmed on this server yet, so links may fail."
_CHECK_FAILED = "The last check on this server couldn't read a video from this platform, so links may fail."
_NO_INTEGRATION = "Added by the operator of this service. It has no dedicated integration, so some pages may fail."
_ALLOWED_BY_OPERATOR = "Enabled by the operator of this service. There is no dedicated integration, so links may fail."
_SLUG = re.compile(r"[^a-z0-9]+")


def _accepts(platform: Platform, services: Services) -> bool:
    """Whether a link from this platform would pass the source policy right now."""
    settings = services.settings
    if any(domain_matches(d.removesuffix(".*"), settings.blocked_domains) for d in platform.domains):
        return False
    if settings.source_policy == "allowlist":
        # With an allow list the switches and check results are not consulted (see SourcePolicy.check_domain).
        return platform.declared != "unsupported" and any(
            domain_matches(d.removesuffix(".*"), settings.allowed_domains) for d in platform.domains
        )
    return platform.active


def platforms_response(services: Services) -> schemas.PlatformsResponse:
    """What visitors may know: platforms that work, and well-known ones that never will."""
    items: list[schemas.PlatformInfo] = []
    for platform in services.platforms.all():
        accepted = _accepts(platform, services)
        if not accepted and not platform.builtin:
            continue  # websites under review are the administrator's business
        status = platform.status
        note = platform.note
        # Visitors are told what a check saw only when it tested a link.
        check = platform.check if platform.check is not None and platform.check.conclusive else None
        verified = check is not None and check.error_code is None and check.qualities > 0
        if status == "requires_review":
            status = "partial"
            note = note or (_NO_INTEGRATION if verified else _CHECK_FAILED if check else _UNCONFIRMED)
        items.append(schemas.PlatformInfo(
            id=platform.id, name=platform.name, domains=list(platform.domains), status=status,  # type: ignore[arg-type]
            enabled=accepted, verified=verified, checked_at=check.at if check else None, note=note,
            region=platform.region,
        ))
    settings = services.settings
    if settings.source_policy == "allowlist":
        # Domains the operator allows that belong to no known platform are accepted too;
        # leaving them out would tell visitors that a working link is not possible.
        for domain in sorted(set(settings.allowed_domains)):
            if services.platforms.match(domain) is None and not domain_matches(domain, settings.blocked_domains):
                items.append(schemas.PlatformInfo(
                    id=f"allowed-{_SLUG.sub('-', domain).strip('-')}", name=domain, domains=[domain], status="partial",
                    enabled=True, verified=False, checked_at=None, note=_ALLOWED_BY_OPERATOR, region="custom",
                ))
    return schemas.PlatformsResponse(mode=settings.source_policy, platforms=items)


def admin_platform(platform: Platform, services: Services) -> schemas.AdminPlatform:
    check = platform.check
    return schemas.AdminPlatform(
        id=platform.id, name=platform.name, domains=list(platform.domains), builtin=platform.builtin,
        expected=platform.declared, note=platform.note, region=platform.region, status=platform.status,
        enabled=platform.enabled, active=_accepts(platform, services), can_enable=platform.can_enable,
        checking=platform.checking,
        check=schemas.AdminCheck(**asdict(check)) if check else None,
        requests_ok=platform.stats["ok"], requests_failed=platform.stats["failed"],
    )


def admin_platforms_response(services: Services) -> schemas.AdminPlatformsResponse:
    platforms = services.platforms.all()
    return schemas.AdminPlatformsResponse(
        mode=services.settings.source_policy, persistent=services.platforms.persistent,
        platforms=[admin_platform(platform, services) for platform in platforms],
    )


def admin_overview(services: Services) -> schemas.AdminOverview:
    settings = services.settings
    counts: dict[str, int] = dict.fromkeys(STATUSES, 0)
    for platform in services.platforms.all():
        counts[platform.status] += 1
    counts["enabled"] = sum(1 for platform in services.platforms.all() if _accepts(platform, services))
    return schemas.AdminOverview(
        version=__version__, extractor_version=services.extractor_version, ffmpeg=services.ffmpeg_version,
        environment=settings.environment, mode=settings.source_policy,
        max_file_size_bytes=settings.max_file_size_bytes, max_concurrent_jobs=settings.max_concurrent_jobs,
        file_ttl_seconds=settings.file_ttl_seconds,
        running_jobs=services.jobs.count(JobStatus.RUNNING), queued_jobs=services.jobs.count(JobStatus.QUEUED),
        kept_files=services.jobs.count(JobStatus.COMPLETED),
        uptime_seconds=int(time.monotonic() - services.started_at),
        disk=schemas.AdminDisk(
            free_bytes=services.storage.free_bytes(), total_bytes=services.storage.total_bytes(),
            used_bytes=services.storage.used_bytes(), reserved_bytes=services.jobs.reserved_bytes(),
            floor_bytes=settings.min_free_disk_bytes, budget_bytes=settings.storage_budget_bytes,
        ),
        counts=counts,
        persistent=services.platforms.persistent and services.admin.persistent,
        errors=[schemas.AdminErrorEntry(**entry) for entry in reversed(services.errors)],
    )


def admin_session(services: Services, session: Session, token: str | None = None) -> schemas.AdminSession:
    return schemas.AdminSession(
        email=services.admin.email or "", must_change_password=session.must_change_password,
        expires_in=max(0, int(services.admin.expires_at(session) - time.time())), token=token,
        persistent=services.admin.persistent,
    )
