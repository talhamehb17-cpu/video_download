"""Runtime configuration, read from environment variables (and an optional ``.env``).

Every knob has a safe default so the API starts with zero configuration in
development. See ``.env.example`` for a commented list.
"""

from __future__ import annotations

import re
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.security.network import parse_host_port_list, parse_ip

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CsvList = Annotated[list[str], NoDecode]
ExampleLink = tuple[str, str, str]  # label, source name, URL

# Sources that publish their media for download and reuse (public-domain or openly
# licensed) and that work without signing in or circumventing anything. This is the
# list used by SOURCE_POLICY=allowlist unless ALLOWED_DOMAINS replaces it.
DEFAULT_ALLOWED_DOMAINS = (
    "archive.org",       # Internet Archive
    "wikimedia.org",     # Wikimedia Commons
    "media.ccc.de",      # Chaos Computer Club conference recordings
    "nasa.gov",          # NASA (public domain)
    "blender.org",       # Blender Foundation open movies
)
_RATE_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)?\s*(s|sec|second|seconds|m|min|minute|minutes|h|hour|hours)?\s*$", re.I)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600}


def parse_rate(value: str) -> tuple[int, float]:
    """Parse ``"12/minute"``, ``"600/60"`` or ``"5/10s"`` into ``(limit, window_seconds)``."""
    match = _RATE_RE.match(value)
    if not match or (match.group(2) is None and match.group(3) is None):
        raise ValueError(f"invalid rate {value!r}; use e.g. '12/minute' or '600/60'")
    limit = int(match.group(1))
    count = int(match.group(2)) if match.group(2) else 1
    unit = _UNIT_SECONDS[(match.group(3) or "s")[0].lower()]
    window = float(count * unit)
    if limit < 1 or window <= 0:
        raise ValueError(f"invalid rate {value!r}")
    return limit, window


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- General -----------------------------------------------------------------
    app_name: str = "Lumora API"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    enable_docs: bool = True

    # --- HTTP / CORS -------------------------------------------------------------
    allowed_origins: CsvList = Field(
        default_factory=lambda: [
            "http://localhost:5173", "http://127.0.0.1:5173",
            "http://localhost:4173", "http://127.0.0.1:4173",
        ]
    )
    allowed_origin_regex: str | None = None
    # How to find the real client address behind a reverse proxy.
    client_ip_header: str | None = None  # e.g. "CF-Connecting-IP" or "Fly-Client-IP"
    trusted_proxy_hops: int = Field(default=0, ge=0, le=10)
    max_request_body_bytes: int = Field(default=16_384, ge=1024)

    # --- Storage & retention -----------------------------------------------------
    storage_dir: Path = Path(tempfile.gettempdir()) / "lumora-media"
    # Small files that must survive a restart: the administrator account and the
    # platform settings. Never inside STORAGE_DIR, which is wiped at every start.
    data_dir: Path = BACKEND_ROOT / "data"
    file_ttl_seconds: int = Field(default=1800, ge=60)
    analysis_ttl_seconds: int = Field(default=1800, ge=60)
    job_record_ttl_seconds: int = Field(default=3600, ge=60)
    cleanup_interval_seconds: int = Field(default=30, ge=1)
    # Space on the storage volume that Lumora never touches: no download starts,
    # and a running one stops, before free space would fall below it.
    min_free_disk_mb: int = Field(default=1024, ge=0)
    # Most space Lumora may occupy with downloads in progress and finished files
    # together. 0 = only the free-space floor above applies.
    storage_budget_mb: int = Field(default=0, ge=0)

    # --- Processing limits -------------------------------------------------------
    max_file_size_mb: int = Field(default=1536, ge=1)
    max_duration_seconds: int = Field(default=4 * 3600, ge=1)
    max_concurrent_jobs: int = Field(default=2, ge=1, le=32)
    max_concurrent_light_tasks: int = Field(default=4, ge=1, le=64)
    max_queued_jobs: int = Field(default=20, ge=0)
    max_active_jobs_per_client: int = Field(default=2, ge=1)
    max_light_jobs_per_client: int = Field(default=4, ge=1)
    analyze_timeout_seconds: int = Field(default=45, ge=5)
    subtitle_timeout_seconds: int = Field(default=90, ge=5)
    job_timeout_seconds: int = Field(default=1800, ge=30)

    # --- Rate limits (per client) ------------------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_analyze: str = "12/minute"
    rate_limit_jobs: str = "12/minute"
    rate_limit_status: str = "600/minute"
    rate_limit_files: str = "60/minute"
    rate_limit_default: str = "240/minute"
    rate_limit_admin_login: str = "10/minute"
    rate_limit_admin: str = "240/minute"

    # --- Administrator --------------------------------------------------------------
    # The account is created from these two values the first time the service
    # starts. The password only works until it has been changed after the first
    # sign-in; from then on the stored (hashed) password counts. Leave either one
    # empty and the admin panel stays switched off.
    admin_email: str | None = None
    admin_bootstrap_password: SecretStr | None = None
    admin_session_minutes: int = Field(default=30, ge=5, le=1440)       # ends after this long without a request
    admin_session_max_hours: int = Field(default=12, ge=1, le=168)      # ends after this long in any case
    admin_max_failed_logins: int = Field(default=5, ge=3, le=50)        # then sign-in is paused, longer each time
    admin_check_timeout_seconds: int = Field(default=60, ge=10, le=300)

    # --- Source policy -----------------------------------------------------------
    # "platforms" (default): links from the platforms that are switched on, i.e. the
    #         built-in catalog plus websites the administrator added and approved.
    # "allowlist": only ALLOWED_DOMAINS and their sub-domains; the admin panel's
    #         switches have no effect.
    # "open": every public source the extractor supports, minus BLOCKED_DOMAINS and
    #         platforms the administrator switched off.
    # Whatever the mode, the operator is responsible for only serving sources that
    # permit it.
    source_policy: Literal["platforms", "open", "allowlist"] = "platforms"
    allowed_domains: CsvList = Field(default_factory=lambda: list(DEFAULT_ALLOWED_DOMAINS))
    blocked_domains: CsvList = Field(default_factory=list)
    block_age_restricted: bool = True
    allowed_ports: Annotated[list[int], NoDecode] = Field(default_factory=lambda: [80, 443])
    # Exact host:port pairs exempt from the public-network rule. For automated tests
    # and local demos only; refused when ENVIRONMENT=production.
    unsafe_allow_hosts: CsvList = Field(default_factory=list)
    # "Try an example" links for the home page: "Label | Source | URL" entries
    # separated by ";". Unset = two openly licensed films; empty = none. Links the
    # source policy would refuse are never offered.
    example_links: Annotated[list[ExampleLink] | None, NoDecode] = None

    # --- Tools -------------------------------------------------------------------
    ffmpeg_path: str | None = None
    worker_nice: int = Field(default=5, ge=0, le=19)

    # ------------------------------------------------------------------ validators
    @field_validator("allowed_origins", "allowed_domains", "blocked_domains", "unsafe_allow_hosts", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("example_links", mode="before")
    @classmethod
    def _split_examples(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        entries: list[ExampleLink] = []
        for item in value.split(";"):
            if not item.strip():
                continue
            parts = [part.strip() for part in item.split("|")]
            if len(parts) != 3 or not all(parts):
                raise ValueError("EXAMPLE_LINKS entries must look like 'Label | Source | https://…', separated by ';'")
            entries.append((parts[0][:60], parts[1][:60], parts[2]))
        return entries

    @field_validator("allowed_ports", mode="before")
    @classmethod
    def _split_ports(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(item) for item in value.split(",") if item.strip()]
        return value

    @field_validator("allowed_origins")
    @classmethod
    def _normalise_origins(cls, value: list[str]) -> list[str]:
        return [origin.rstrip("/") for origin in value]

    @field_validator("allowed_domains", "blocked_domains")
    @classmethod
    def _normalise_domains(cls, value: list[str]) -> list[str]:
        return [d.lower().lstrip("*").strip(".") for d in value if d.strip(".* ")]

    @field_validator(
        "client_ip_header", "allowed_origin_regex", "ffmpeg_path", "admin_email", "admin_bootstrap_password",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("admin_email")
    @classmethod
    def _normalise_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        email = value.strip().lower()
        if not re.fullmatch(r"[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s.]{2,}", email):
            raise ValueError("ADMIN_EMAIL must be an e-mail address")
        return email

    @field_validator(
        "rate_limit_analyze", "rate_limit_jobs", "rate_limit_status", "rate_limit_files", "rate_limit_default",
        "rate_limit_admin_login", "rate_limit_admin",
    )
    @classmethod
    def _check_rate(cls, value: str) -> str:
        parse_rate(value)
        return value

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        for host, _port in parse_host_port_list(self.unsafe_allow_hosts):  # fail fast on typos
            if parse_ip(host) is None:
                raise ValueError("UNSAFE_ALLOW_HOSTS entries must be IP:port pairs, e.g. 127.0.0.1:8765")
        if self.environment == "production":
            if self.unsafe_allow_hosts:
                raise ValueError("UNSAFE_ALLOW_HOSTS must be empty when ENVIRONMENT=production")
            if "*" in self.allowed_origins:
                raise ValueError("ALLOWED_ORIGINS must list explicit origins in production")
        if self.source_policy == "allowlist" and not self.allowed_domains:
            raise ValueError("SOURCE_POLICY=allowlist requires ALLOWED_DOMAINS")
        return self

    # ------------------------------------------------------------------ derived
    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def min_free_disk_bytes(self) -> int:
        return self.min_free_disk_mb * 1024 * 1024

    @property
    def storage_budget_bytes(self) -> int | None:
        return self.storage_budget_mb * 1024 * 1024 or None

    @property
    def admin_configured(self) -> bool:
        return bool(self.admin_email and self.admin_bootstrap_password)

    @property
    def unsafe_allow_pairs(self) -> frozenset[tuple[str, int]]:
        return parse_host_port_list(self.unsafe_allow_hosts)


@lru_cache
def get_settings() -> Settings:
    return Settings()
