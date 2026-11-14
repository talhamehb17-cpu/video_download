"""The live list of platforms: catalog + operator decisions + check results.

State is one small JSON file in the data directory, written atomically with
owner-only permissions. Without a writable data directory the registry still
works, but changes last only until the service restarts (``persistent`` is False).
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.platforms.catalog import CATALOG, CatalogEntry

log = logging.getLogger(__name__)

Status = Literal["supported", "partial", "unsupported", "requires_review"]
STATUSES: tuple[Status, ...] = ("supported", "partial", "unsupported", "requires_review")
MAX_CUSTOM_PLATFORMS = 200
_STORE_VERSION = 1
_LABEL = r"(?!-)[a-z0-9-]{1,63}(?<!-)"
_DOMAIN_RE = re.compile(rf"^(?:{_LABEL}\.)+[a-z][a-z0-9-]{{1,62}}$")
_COUNTRY_TAIL_RE = re.compile(r"^[a-z]{2,3}(\.[a-z]{2})?$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def normalise_domain(value: str) -> str | None:
    """``"https://WWW.Example.com/watch"`` -> ``"example.com"``; None when it is not a domain."""
    text = (value or "").strip().lower()
    text = re.sub(r"^[a-z][a-z0-9+.\-]*://", "", text)
    text = text.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    text = text.rsplit("@", 1)[-1].split(":", 1)[0].strip(".")
    try:
        text = text.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        return None
    for prefix in ("www.", "m.", "mobile."):
        if text.startswith(prefix) and text.count(".") >= 2:
            text = text[len(prefix):]
            break
    return text if len(text) <= 253 and _DOMAIN_RE.match(text) else None


def host_matches(host: str, pattern: str) -> bool:
    """True when ``host`` is ``pattern`` or one of its sub-domains (see the catalog for ``name.*``)."""
    host = host.lower().rstrip(".")
    if pattern.endswith(".*"):
        name = pattern[:-2]
        labels = host.split(".")
        for index, label in enumerate(labels[:-1]):
            if label == name and _COUNTRY_TAIL_RE.match(".".join(labels[index + 1:])):
                return True
        return False
    return host == pattern or host.endswith("." + pattern)


@dataclass
class CheckResult:
    """What one compatibility check observed. Every text here is safe to display."""

    at: float
    status: Status
    summary: str
    method: Literal["extractor", "generic", "none"] = "none"
    extractor: str | None = None
    url: str | None = None
    title: str | None = None
    qualities: int = 0
    max_height: int | None = None
    subtitles: int = 0
    error_code: str | None = None
    error_message: str | None = None
    seconds: float | None = None
    # False when the check learned nothing about the website: there was no link to
    # test, or the check itself broke. Such a result never changes a status.
    conclusive: bool = True


@dataclass
class Platform:
    id: str
    name: str
    domains: tuple[str, ...]
    builtin: bool
    declared: Literal["full", "partial", "unsupported"] | None
    note: str | None
    region: str
    enabled: bool
    check: CheckResult | None = None
    checking: bool = False
    created_at: float | None = None
    stats: dict[str, int] = field(default_factory=lambda: {"ok": 0, "failed": 0})

    @property
    def status(self) -> Status:
        if self.declared == "unsupported":
            return "unsupported"
        if self.check is not None and self.check.conclusive:
            # One link that worked does not lift the known limits of a platform.
            if self.check.status == "supported" and self.declared == "partial":
                return "partial"
            return self.check.status
        if self.declared == "full":
            return "supported"
        if self.declared == "partial":
            return "partial"
        return "requires_review"

    @property
    def can_enable(self) -> bool:
        return self.status != "unsupported"

    @property
    def active(self) -> bool:
        """Links from this platform are accepted."""
        return self.enabled and self.can_enable

    def matches(self, host: str) -> int:
        """Length of the best matching address (0 = no match), so the most specific platform wins."""
        return max((len(d) for d in self.domains if host_matches(host, d)), default=0)


def _from_catalog(entry: CatalogEntry) -> Platform:
    return Platform(
        id=entry.id, name=entry.name, domains=entry.domains, builtin=True, declared=entry.support,
        note=entry.note, region=entry.region, enabled=entry.support != "unsupported",
    )


def _check_from(raw: Any) -> CheckResult | None:
    if not isinstance(raw, dict) or raw.get("status") not in STATUSES:
        return None
    known = set(CheckResult.__dataclass_fields__)
    try:
        return CheckResult(**{key: value for key, value in raw.items() if key in known})
    except TypeError:
        return None


class PlatformRegistry:
    def __init__(self, data_dir: Path | None) -> None:
        self._path = data_dir / "platforms.json" if data_dir is not None else None
        self._lock = threading.RLock()
        self._platforms: dict[str, Platform] = {entry.id: _from_catalog(entry) for entry in CATALOG}
        self.persistent = self._path is not None
        self._load()

    # ------------------------------------------------------------------ persistence
    def _load(self) -> None:
        if self._path is None or not self._path.is_file():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            overrides = data.get("overrides") or {}
            custom = data.get("custom") or []
        except (OSError, ValueError, AttributeError) as exc:
            log.error("platform settings in %s could not be read (%s); starting from the defaults", self._path, exc)
            return
        for platform_id, saved in overrides.items():
            platform = self._platforms.get(platform_id)
            if platform is None or not isinstance(saved, dict):
                continue
            if isinstance(saved.get("enabled"), bool):
                platform.enabled = saved["enabled"]
            platform.check = _check_from(saved.get("check"))
        for saved in custom[:MAX_CUSTOM_PLATFORMS]:
            if not isinstance(saved, dict):
                continue
            domain = normalise_domain(str((saved.get("domains") or [""])[0]))
            if domain is None or self.match(domain) is not None:
                continue
            platform = Platform(
                id=f"site-{_SLUG_RE.sub('-', domain).strip('-')}", name=str(saved.get("name") or domain)[:60],
                domains=(domain,), builtin=False, declared=None, note=None, region="custom",
                enabled=bool(saved.get("enabled")), check=_check_from(saved.get("check")),
                created_at=float(saved.get("created_at") or time.time()),
            )
            self._platforms[platform.id] = platform

    def _save(self) -> None:
        if self._path is None:
            return
        overrides: dict[str, Any] = {}
        custom: list[dict[str, Any]] = []
        for platform in self._platforms.values():
            check = asdict(platform.check) if platform.check else None
            if platform.builtin:
                default = platform.declared != "unsupported"
                if platform.enabled != default or check:
                    overrides[platform.id] = {"enabled": platform.enabled, "check": check}
            else:
                custom.append({
                    "name": platform.name, "domains": list(platform.domains), "enabled": platform.enabled,
                    "check": check, "created_at": platform.created_at,
                })
        payload = json.dumps({"version": _STORE_VERSION, "overrides": overrides, "custom": custom}, indent=1)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp = tempfile.mkstemp(dir=self._path.parent, prefix=".platforms-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                os.chmod(temp, 0o600)
                os.replace(temp, self._path)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
            self.persistent = True
        except OSError as exc:
            if self.persistent:
                log.error("platform settings could not be saved to %s (%s); changes last until restart",
                          self._path, exc)
            self.persistent = False

    # ------------------------------------------------------------------ queries
    def all(self) -> list[Platform]:
        with self._lock:
            return list(self._platforms.values())

    def get(self, platform_id: str) -> Platform | None:
        with self._lock:
            return self._platforms.get(platform_id)

    def match(self, host: str) -> Platform | None:
        """The platform a host name belongs to, if any."""
        host = host.lower().rstrip(".")
        best: tuple[int, Platform] | None = None
        with self._lock:
            for platform in self._platforms.values():
                score = platform.matches(host)
                if score and (best is None or score > best[0]):
                    best = (score, platform)
        return best[1] if best else None

    def active_domains(self) -> list[str]:
        with self._lock:
            return sorted({d for p in self._platforms.values() if p.active for d in p.domains})

    # ------------------------------------------------------------------ changes
    def add(self, domain: str, name: str | None = None) -> Platform:
        """Register a website the catalog does not know. It starts switched off, waiting for review."""
        with self._lock:
            if sum(1 for p in self._platforms.values() if not p.builtin) >= MAX_CUSTOM_PLATFORMS:
                raise ValueError("too many websites")
            platform = Platform(
                id=f"site-{_SLUG_RE.sub('-', domain).strip('-')}", name=(name or domain)[:60], domains=(domain,),
                builtin=False, declared=None, note=None, region="custom", enabled=False, created_at=time.time(),
            )
            self._platforms[platform.id] = platform
            self._save()
            return platform

    def remove(self, platform: Platform) -> None:
        with self._lock:
            if not platform.builtin:
                self._platforms.pop(platform.id, None)
                self._save()

    def set_enabled(self, platform: Platform, enabled: bool) -> None:
        with self._lock:
            platform.enabled = enabled
            self._save()

    def set_check(self, platform: Platform, check: CheckResult) -> None:
        with self._lock:
            platform.check = check
            platform.checking = False
            if not platform.can_enable:
                platform.enabled = False
            self._save()

    def record(self, host: str, ok: bool) -> None:
        """Count one real request, so the admin sees how each platform is doing."""
        platform = self.match(host)
        if platform is not None:
            platform.stats["ok" if ok else "failed"] += 1
