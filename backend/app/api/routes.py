"""HTTP endpoints. Thin by design: validation, rate limits, then a service call."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import FileResponse

from app import schemas
from app.deps import ClientDep, ServicesDep, rate_limited
from app.errors import AppError
from app.presenters import (
    analysis_response,
    config_response,
    health_response,
    job_response,
    platforms_response,
)
from app.security.client import ClientIdentity
from app.security.filenames import build_filename, content_disposition
from app.services.jobs import JobStatus

router = APIRouter()
meta = APIRouter(tags=["meta"])
api = APIRouter(prefix="/api/v1")

_ID_RE = re.compile(schemas.ID_PATTERN)
ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": schemas.ErrorResponse} for code in (404, 409, 410, 413, 422, 429, 500, 502, 503, 504, 507)
}

AnalysisId = Annotated[str, Path(min_length=16, max_length=64)]
JobId = Annotated[str, Path(min_length=16, max_length=64)]


def _check_id(value: str, missing: str) -> str:
    if not _ID_RE.match(value):
        raise AppError(missing)
    return value


# --------------------------------------------------------------------------------- meta
@meta.get("/health", response_model=schemas.HealthResponse, summary="Liveness probe")
@api.get("/health", response_model=schemas.HealthResponse, tags=["meta"], summary="Service health")
async def health(services: ServicesDep) -> schemas.HealthResponse:
    return health_response(services)


@api.get("/config", response_model=schemas.ConfigResponse, tags=["meta"], summary="Limits, capabilities, sources")
async def config(
    services: ServicesDep, _: Annotated[ClientIdentity, Depends(rate_limited("default"))]
) -> schemas.ConfigResponse:
    return config_response(services)


@api.get("/platforms", response_model=schemas.PlatformsResponse, tags=["meta"],
         summary="Platforms this service knows, and what to expect from each")
async def platforms(
    services: ServicesDep, _: Annotated[ClientIdentity, Depends(rate_limited("default"))]
) -> schemas.PlatformsResponse:
    return platforms_response(services)


# ----------------------------------------------------------------------------- analysis
@api.post(
    "/analyze", response_model=schemas.AnalysisResponse, responses=ERRORS, tags=["analysis"],
    summary="Validate a link and read its public metadata",
)
async def analyze(
    body: schemas.AnalyzeRequest,
    services: ServicesDep,
    client: Annotated[ClientIdentity, Depends(rate_limited("analyze"))],
) -> schemas.AnalysisResponse:
    analysis = await services.analyses.analyze(body.url, client)
    return analysis_response(analysis, services.platforms)


@api.get(
    "/analyses/{analysis_id}/thumbnail", response_class=FileResponse, responses=ERRORS, tags=["analysis"],
    summary="Poster image of an analyzed video",
)
async def thumbnail(
    analysis_id: AnalysisId, services: ServicesDep, _: Annotated[ClientIdentity, Depends(rate_limited("files"))]
) -> FileResponse:
    analysis = services.analyses.get(_check_id(analysis_id, "analysis_expired"))
    if analysis.thumbnail is None or not analysis.thumbnail[0].is_file():
        raise AppError("option_not_found")
    path, media_type = analysis.thumbnail
    return FileResponse(
        path, media_type=media_type,
        headers={"Cache-Control": "private, max-age=600", "Cross-Origin-Resource-Policy": "cross-origin"},
    )


@api.get(
    "/analyses/{analysis_id}/subtitles/{track_id}", response_class=FileResponse, responses=ERRORS,
    tags=["analysis"], summary="Download one subtitle track as SRT or WebVTT",
)
async def subtitle(
    analysis_id: AnalysisId,
    track_id: Annotated[str, Path(pattern=r"^s[0-9]{1,4}$")],
    services: ServicesDep,
    client: Annotated[ClientIdentity, Depends(rate_limited("files"))],
    format: Annotated[Literal["srt", "vtt"], Query(description="Subtitle file format")] = "srt",
) -> FileResponse:
    analysis = services.analyses.get(_check_id(analysis_id, "analysis_expired"))
    path = await services.analyses.subtitle_file(analysis, track_id, format, client)
    track = analysis.subtitle(track_id)
    suffix = track.language if track.kind == "manual" else f"{track.language} auto"
    filename = build_filename(analysis.title, format, suffix=suffix, fallback="subtitles")
    media_type = "text/vtt; charset=utf-8" if format == "vtt" else "application/x-subrip; charset=utf-8"
    return FileResponse(
        path, media_type=media_type,
        headers={"Content-Disposition": content_disposition(filename), "Cache-Control": "private, no-store"},
    )


# --------------------------------------------------------------------------------- jobs
@api.post(
    "/jobs", response_model=schemas.JobResponse, status_code=202, responses=ERRORS, tags=["jobs"],
    summary="Start preparing a download in the background",
)
async def create_job(
    body: schemas.JobCreateRequest,
    services: ServicesDep,
    client: Annotated[ClientIdentity, Depends(rate_limited("jobs"))],
) -> schemas.JobResponse:
    analysis = services.analyses.get(body.analysis_id)
    quality = analysis.quality(body.quality_id)
    tracks = [analysis.subtitle(track_id) for track_id in dict.fromkeys(body.embed_subtitles)]
    job = services.jobs.create(analysis, quality, tracks, client)
    return job_response(job, services.jobs)


@api.get("/jobs/{job_id}", response_model=schemas.JobResponse, responses=ERRORS, tags=["jobs"],
         summary="Progress and result of a job")
async def get_job(
    job_id: JobId, services: ServicesDep, _: Annotated[ClientIdentity, Depends(rate_limited("status"))]
) -> schemas.JobResponse:
    job = services.jobs.get(_check_id(job_id, "job_not_found"))
    return job_response(job, services.jobs)


@api.delete("/jobs/{job_id}", response_model=schemas.JobResponse, responses=ERRORS, tags=["jobs"],
            summary="Cancel a job, or delete its finished file immediately")
async def cancel_job(
    job_id: JobId, services: ServicesDep, _: Annotated[ClientIdentity, Depends(rate_limited("default"))]
) -> schemas.JobResponse:
    job = services.jobs.get(_check_id(job_id, "job_not_found"))
    await services.jobs.cancel(job)
    return job_response(job, services.jobs)


@api.get("/jobs/{job_id}/file", response_class=FileResponse, responses=ERRORS, tags=["jobs"],
         summary="Download the prepared file")
async def job_file(
    job_id: JobId, services: ServicesDep, client: ClientDep,
    _: Annotated[ClientIdentity, Depends(rate_limited("files"))],
) -> FileResponse:
    job = services.jobs.get(_check_id(job_id, "job_not_found"))
    if job.status in (JobStatus.EXPIRED, JobStatus.DELETED):
        raise AppError("file_expired")
    if job.status is not JobStatus.COMPLETED or job.file_path is None or job.file_name is None:
        raise AppError("file_not_ready")
    if not job.file_path.is_file():
        raise AppError("file_expired")
    job.downloads += 1
    return FileResponse(
        job.file_path,
        media_type=job.media_type,
        headers={"Content-Disposition": content_disposition(job.file_name), "Cache-Control": "private, no-store"},
    )


router.include_router(meta)
router.include_router(api)
