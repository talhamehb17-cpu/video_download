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
    platform: str | None = None  # display name of the platform, when it is a known one


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
    platform_list: bool = Field(default=True, description="GET /api/v1/platforms exists (API 1.1 and later).")


class Example(BaseModel):
    label: str
    source: str
    url: str


class SourcePolicyInfo(BaseModel):
    mode: Literal["platforms", "open", "allowlist"]
    domains: list[str]
    examples: list[Example]


PublicStatus = Literal["supported", "partial", "unsupported"]


class PlatformInfo(BaseModel):
    """One platform as visitors see it."""

    id: str
    name: str
    domains: list[str] = Field(description="Addresses of the platform. 'name.*' also covers country versions.")
    status: PublicStatus
    enabled: bool = Field(description="Links from this platform are accepted right now.")
    verified: bool = Field(description="A compatibility check on this server read a public video.")
    checked_at: float | None = Field(default=None, description="When that check ran (Unix time).")
    note: str | None = None
    region: str


class PlatformsResponse(BaseModel):
    mode: Literal["platforms", "open", "allowlist"]
    platforms: list[PlatformInfo]


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


# ------------------------------------------------------------------------------ admin
class AdminLoginRequest(RequestModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class AdminPasswordRequest(RequestModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class AdminAvailability(BaseModel):
    configured: bool = Field(description="An administrator account exists, so signing in is possible.")


class AdminSession(BaseModel):
    email: str
    must_change_password: bool
    expires_in: int
    token: str | None = Field(default=None, description="Only present right after signing in or changing the password.")
    persistent: bool = Field(description="False when the server cannot save the account to disk.")


AdminStatus = Literal["supported", "partial", "unsupported", "requires_review"]


class AdminCheck(BaseModel):
    at: float
    status: AdminStatus
    summary: str
    method: Literal["extractor", "generic", "none"]
    extractor: str | None = None
    url: str | None = None
    title: str | None = None
    qualities: int = 0
    max_height: int | None = None
    subtitles: int = 0
    error_code: str | None = None
    error_message: str | None = None
    seconds: float | None = None


class AdminPlatform(BaseModel):
    id: str
    name: str
    domains: list[str]
    builtin: bool
    expected: Literal["full", "partial", "unsupported"] | None
    note: str | None
    region: str
    status: AdminStatus
    enabled: bool
    active: bool
    can_enable: bool
    checking: bool
    check: AdminCheck | None
    requests_ok: int
    requests_failed: int


class AdminPlatformsResponse(BaseModel):
    mode: Literal["platforms", "open", "allowlist"]
    persistent: bool
    platforms: list[AdminPlatform]


class AdminPlatformCreate(RequestModel):
    target: str = Field(min_length=3, max_length=2048, description="A domain or a link to a video page.")
    name: str | None = Field(default=None, max_length=60)


class AdminPlatformUpdate(RequestModel):
    enabled: bool


class AdminCheckRequest(RequestModel):
    url: str | None = Field(default=None, max_length=2048, description="Link to test. Empty = sample links.")


class AdminBulkCheck(BaseModel):
    started: int = Field(description="Checks queued by this request.")
    pending: int = Field(description="Checks running or waiting for their turn, in total.")


class AdminErrorEntry(BaseModel):
    at: float
    stage: Literal["analyze", "download"]
    domain: str
    platform: str | None
    code: str
    message: str


class AdminDisk(BaseModel):
    free_bytes: int
    total_bytes: int
    used_bytes: int
    reserved_bytes: int
    floor_bytes: int
    budget_bytes: int | None


class AdminOverview(BaseModel):
    version: str
    extractor_version: str
    ffmpeg: str | None
    environment: str
    mode: Literal["platforms", "open", "allowlist"]
    max_file_size_bytes: int
    max_concurrent_jobs: int
    file_ttl_seconds: int
    running_jobs: int
    queued_jobs: int
    kept_files: int
    uptime_seconds: int
    disk: AdminDisk
    counts: dict[str, int]
    persistent: bool
    errors: list[AdminErrorEntry]
