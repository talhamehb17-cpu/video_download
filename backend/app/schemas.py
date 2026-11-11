"""Request and response models of the public API (the contract with the frontend)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

ID_PATTERN = r"^[A-Za-z0-9_-]{16,64}$"


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AnalyzeRequest(RequestModel):
    url: str = Field(min_length=1, max_length=2048, description="Public page or media URL (http/https).")


class JobCreateRequest(RequestModel):
    analysis_id: str = Field(pattern=ID_PATTERN)
    quality_id: str = Field(pattern=r"^q[0-9]{1,3}$")
    embed_subtitles: list[Annotated[str, Field(pattern=r"^s[0-9]{1,4}$")]] = Field(
        default_factory=list, max_length=8, description="Subtitle track ids to embed into the file."
    )


# ----------------------------------------------------------------------------- errors
class FieldError(BaseModel):
    field: str
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    hint: str | None = None
    retry_after: int | None = None
    fields: list[FieldError] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


# --------------------------------------------------------------------------- analysis
class Notice(BaseModel):
    code: str
    message: str


class Source(BaseModel):
    domain: str
    extractor: str


class Quality(BaseModel):
    id: str
    kind: Literal["video", "audio"]
    label: str
    container: str
    height: int | None
    width: int | None
    fps: float | None
    video_codec: str | None
    audio_codec: str | None
    has_audio: bool
    requires_merge: bool
    filesize: int | None
    filesize_is_estimate: bool
    bitrate_kbps: float | None
    dynamic_range: str | None
    can_embed_subtitles: bool
    exceeds_limit: bool
    recommended: bool


class SubtitleTrack(BaseModel):
    id: str
    language: str
    name: str | None
    kind: Literal["manual", "auto"]
    formats: list[Literal["srt", "vtt"]]
    embeddable: bool


class AnalysisResponse(BaseModel):
    id: str
    url: str
    title: str
    uploader: str | None
    duration: float | None
    thumbnail_url: str | None
    source: Source
    qualities: list[Quality]
    subtitles: list[SubtitleTrack]
    notices: list[Notice]
    expires_in: int


# ------------------------------------------------------------------------------- jobs
class ProgressInfo(BaseModel):
    percent: float | None
    downloaded_bytes: int
    total_bytes: int | None
    speed_bps: float | None
    eta_seconds: float | None
    part: int | None
    parts: int | None
    part_kind: str | None


class FileInfo(BaseModel):
    name: str
    size: int
    container: str
    url: str
    expires_in: int


class JobResponse(BaseModel):
    id: str
    status: Literal["queued", "running", "completed", "failed", "cancelled", "expired", "deleted"]
    stage: str
    stage_detail: str | None
    queue_position: int | None
    title: str
    quality_label: str
    container: str
    progress: ProgressInfo
    file: FileInfo | None
    error: ErrorBody | None
    embedded_subtitles: list[str]
    notices: list[Notice]


# ------------------------------------------------------------------------------- meta
class Limits(BaseModel):
    max_file_size_bytes: int
    max_duration_seconds: int
    file_ttl_seconds: int
    analysis_ttl_seconds: int


class Capabilities(BaseModel):
    merge: bool
    subtitle_conversion: bool
    subtitle_embedding: bool
    subtitle_formats: list[str]


class Example(BaseModel):
    label: str
    source: str
    url: str


class SourcePolicyInfo(BaseModel):
    mode: Literal["open", "allowlist"]
    domains: list[str]
    examples: list[Example]


class ConfigResponse(BaseModel):
    name: str
    version: str
    limits: Limits
    capabilities: Capabilities
    sources: SourcePolicyInfo


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
    ffmpeg: bool
    active_jobs: int
    queued_jobs: int
    uptime_seconds: int
