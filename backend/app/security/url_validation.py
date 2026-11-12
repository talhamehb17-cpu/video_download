"""Server-side validation of user-supplied URLs.

Three layers, cheapest first:

1. **Syntax** - http(s) only, no embedded credentials, sane length, allowed ports,
   a real public-looking host name (no IP literals, no internal names).
2. **Source policy** - operator-defined block list / allow list of domains.
3. **DNS** - every address the host resolves to must be public.

This gives users a fast, precise error. It is *not* the only SSRF defence: the media
worker re-checks every outgoing connection at the socket level (see
``app.worker.guard``), which also covers redirects, embedded players, playlists and
DNS rebinding.
"""

from __future__ import annotations

import asyncio
import re
import socket
from dataclasses import dataclass, field
from urllib.parse import SplitResult, urlsplit, urlunsplit

from app.errors import AppError
from app.platforms.registry import PlatformRegistry
from app.security.network import all_public, is_internal_hostname, is_public_ip, parse_ip

MAX_URL_LENGTH = 2048
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")
_BAD_CHARS_RE = re.compile(r"[\x00-\x20\x7f\\<>\"'`{}|^]")
_HOST_LABEL_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_DEFAULT_PORTS = {"http": 80, "https": 443}


@dataclass(frozen=True)
class ValidatedUrl:
    url: str        # normalised, safe to hand to the extractor
    scheme: str
    host: str       # lower-case ASCII (punycode) host name or IP literal
    port: int
    is_exempt: bool  # matched the explicit test/dev allow list


@dataclass(frozen=True)
class SourcePolicy:
    """Which websites a link may point to.

    In order: the operator's block list always wins; a platform that cannot work
    within the rules (DRM) is always declined; then the mode decides -
    ``allowlist`` (only the listed domains), ``platforms`` (only platforms that are
    switched on) or ``open`` (everything except platforms that were switched off).
    """

    mode: str = "open"                       # "platforms" | "open" | "allowlist"
    allowed_domains: tuple[str, ...] = ()
    blocked_domains: tuple[str, ...] = ()
    allowed_ports: frozenset[int] = frozenset({80, 443})
    exempt: frozenset[tuple[str, int]] = frozenset()
    platforms: PlatformRegistry | None = field(default=None, compare=False)

    def is_exempt(self, host: str, port: int) -> bool:
        return (host.lower().strip("[]"), port) in self.exempt

    def check_domain(self, host: str) -> None:
        """Raise if the operator's policy doesn't allow this host."""
        name = host.lower().rstrip(".")
        if domain_matches(name, self.blocked_domains):
            raise AppError("domain_not_allowed")
        platform = self.platforms.match(name) if self.platforms is not None else None
        if platform is not None and platform.declared == "unsupported":
            raise AppError("platform_unsupported", message=f"{platform.name} videos can't be downloaded.",
                           hint=platform.note)
        if self.mode == "allowlist":
            if not domain_matches(name, self.allowed_domains):
                raise AppError("domain_not_allowed")
            return
        if platform is None:
            if self.mode == "platforms":
                raise AppError("domain_not_allowed")
            return
        if not platform.active:
            if not platform.builtin and self.mode == "platforms":
                # A website the administrator is still reviewing looks like any other unlisted one.
                raise AppError("domain_not_allowed")
            if platform.status == "unsupported":
                raise AppError("platform_unsupported", message=f"{platform.name} doesn't work with this service.",
                               hint="A compatibility check found nothing that can be downloaded.")
            raise AppError("platform_disabled", message=f"{platform.name} is switched off on this service.")


def domain_matches(host: str, domains: tuple[str, ...] | list[str]) -> bool:
    """True if ``host`` equals one of ``domains`` or is a sub-domain of one."""
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in domains if d)


def _ascii_host(host: str) -> str:
    try:
        return host.encode("idna").decode("ascii").lower()
    except (UnicodeError, ValueError) as exc:
        raise AppError("invalid_url") from exc


def validate_url_syntax(raw: str, policy: SourcePolicy) -> ValidatedUrl:
    """Layer 1 + 2. Pure function: no network access."""
    if not isinstance(raw, str):
        raise AppError("invalid_url")
    text = raw.strip()
    if not text or len(text) > MAX_URL_LENGTH:
        raise AppError("invalid_url")
    if _BAD_CHARS_RE.search(text):
        raise AppError("invalid_url")

    # People paste "example.com/watch?v=..." all the time; assume https.
    if not _SCHEME_RE.match(text):
        text = "https://" + text.lstrip("/")

    try:
        parts: SplitResult = urlsplit(text)
        port = parts.port
        host = parts.hostname
    except ValueError as exc:
        raise AppError("invalid_url") from exc

    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS:
        raise AppError("unsupported_scheme")
    if not host:
        raise AppError("invalid_url")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise AppError("invalid_url", hint="Links with embedded usernames or passwords aren't accepted.")

    port = port or _DEFAULT_PORTS[scheme]
    ip = parse_ip(host)
    exempt = policy.is_exempt(host, port)

    if ip is not None:
        # Real video pages live on domain names. IP literals are almost always an
        # attempt to reach something that shouldn't be reachable.
        if not exempt:
            raise AppError("blocked_destination")
        ascii_host = host.lower()
        netloc_host = f"[{ascii_host}]" if ":" in ascii_host else ascii_host
    else:
        ascii_host = _ascii_host(host.rstrip("."))
        if not exempt:
            if is_internal_hostname(ascii_host):
                raise AppError("blocked_destination")
            if len(ascii_host) > 253 or not all(_HOST_LABEL_RE.match(label) for label in ascii_host.split(".")):
                raise AppError("invalid_url")
        netloc_host = ascii_host

    if not exempt:
        if port not in policy.allowed_ports:
            raise AppError("blocked_destination", hint="Only standard web ports are supported.")
        policy.check_domain(ascii_host)

    netloc = netloc_host if port == _DEFAULT_PORTS[scheme] else f"{netloc_host}:{port}"
    normalised = urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))
    return ValidatedUrl(url=normalised, scheme=scheme, host=ascii_host, port=port, is_exempt=exempt)


async def resolve_host(host: str, port: int, *, timeout: float = 5.0) -> list[str]:
    """Resolve ``host`` to the list of addresses a connection could use."""
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(
            loop.getaddrinfo(host, port, type=socket.SOCK_STREAM), timeout=timeout
        )
    except (TimeoutError, asyncio.TimeoutError) as exc:
        raise AppError("source_unreachable", hint="The domain name took too long to resolve.") from exc
    except (socket.gaierror, OSError) as exc:
        raise AppError("source_unreachable", hint="That domain name doesn't seem to exist.") from exc
    return sorted({str(info[4][0]) for info in infos})


async def validate_public_url(raw: str, policy: SourcePolicy) -> ValidatedUrl:
    """All three layers. Raises :class:`AppError` with a user-facing explanation."""
    validated = validate_url_syntax(raw, policy)
    if validated.is_exempt:
        return validated
    addresses = await resolve_host(validated.host, validated.port)
    if not all_public(addresses):
        raise AppError("blocked_destination")
    return validated


def assert_public_address(address: str) -> None:
    if not is_public_ip(address):
        raise AppError("blocked_destination")
