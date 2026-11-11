"""URL validation, the public-network rule, file names, rate limits, client identity."""

from __future__ import annotations

import socket

import pytest
from starlette.requests import Request

from app.config import DEFAULT_ALLOWED_DOMAINS, Settings, parse_rate
from app.errors import AppError
from app.security import url_validation
from app.security.client import anonymize_ip, identify_client
from app.security.filenames import build_filename, content_disposition, sanitize_stem
from app.security.network import is_internal_hostname, is_public_ip
from app.security.rate_limit import RateLimiter
from app.security.url_validation import SourcePolicy, validate_public_url, validate_url_syntax
from app.worker import guard

OPEN = SourcePolicy()


# --------------------------------------------------------------------------- addresses
@pytest.mark.parametrize("address", [
    "8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700:4700::1111", "64:ff9b::808:808", "::ffff:8.8.8.8",
])
def test_public_addresses_are_allowed(address: str) -> None:
    assert is_public_ip(address)


@pytest.mark.parametrize("address", [
    "127.0.0.1", "127.255.255.254", "10.1.2.3", "172.16.0.1", "172.31.255.255", "192.168.1.1",
    "169.254.169.254",            # cloud metadata
    "100.64.0.1",                 # carrier-grade NAT
    "0.0.0.0", "224.0.0.1", "255.255.255.255", "198.18.0.1", "192.0.2.1",
    "::1", "::", "fe80::1", "fe80::1%eth0", "fc00::1", "fd12:3456::1", "ff02::1", "2001:db8::1", "fec0::1",
    "::ffff:127.0.0.1", "::ffff:10.0.0.1",   # IPv4-mapped
    "64:ff9b::7f00:1", "64:ff9b::a00:1",     # NAT64-wrapped private IPv4
    "2002:7f00:1::",                         # 6to4
    "::127.0.0.1",                           # IPv4-compatible
    "[::1]", "not-an-ip", "",
])
def test_non_public_addresses_are_blocked(address: str) -> None:
    assert not is_public_ip(address)


@pytest.mark.parametrize("host", [
    "localhost", "LOCALHOST.", "foo.local", "db.internal", "redis", "metadata", "printer.lan", "x.onion",
    "127.1", "0x7f.0.0.1", "2130706433", "017700000001", "a.b.123", "",
])
def test_internal_hostnames(host: str) -> None:
    assert is_internal_hostname(host)


@pytest.mark.parametrize("host", ["example.com", "sub.domain.co.uk", "xn--bcher-kva.de", "archive.org."])
def test_public_hostnames(host: str) -> None:
    assert not is_internal_hostname(host)


# ------------------------------------------------------------------------- URL syntax
@pytest.mark.parametrize(("raw", "expected"), [
    ("https://example.com/watch?v=1", "https://example.com/watch?v=1"),
    ("example.com/video", "https://example.com/video"),
    ("  HTTP://Example.COM:80/a%20b  ", "http://example.com/a%20b"),
    ("https://bücher.de/x#fragment", "https://xn--bcher-kva.de/x"),
    ("https://example.com", "https://example.com/"),
])
def test_valid_urls_are_normalised(raw: str, expected: str) -> None:
    assert validate_url_syntax(raw, OPEN).url == expected


@pytest.mark.parametrize(("raw", "code"), [
    ("", "invalid_url"),
    ("https://exa mple.com", "invalid_url"),
    ("http:///nohost", "invalid_url"),
    ("https://" + "a" * 3000 + ".com", "invalid_url"),
    ("http://user:pw@example.com/", "invalid_url"),
    ("http://example.com\\@evil.com/", "invalid_url"),
    ("http://-bad-.com/", "invalid_url"),
    ("http://exa_mple.com/", "invalid_url"),
    ("http://example.com:99999/", "invalid_url"),
    ("ftp://example.com/x", "unsupported_scheme"),
    ("file:///etc/passwd", "unsupported_scheme"),
    ("javascript:alert(1)", "unsupported_scheme"),
    ("data:text/html,hi", "unsupported_scheme"),
    ("gopher://example.com", "unsupported_scheme"),
    ("ytsearch:cats", "unsupported_scheme"),
    ("http://localhost/x", "blocked_destination"),
    ("http://127.0.0.1/x", "blocked_destination"),
    ("http://8.8.8.8/x", "blocked_destination"),            # IP literals are never accepted
    ("http://[::1]/x", "blocked_destination"),
    ("http://[::ffff:127.0.0.1]/", "blocked_destination"),
    ("http://2130706433/x", "blocked_destination"),         # decimal IPv4
    ("http://0x7f.0.0.1/", "blocked_destination"),          # hex IPv4
    ("http://127.1/", "blocked_destination"),               # short IPv4
    ("http://169.254.169.254/latest/meta-data/", "blocked_destination"),
    ("http://metadata/", "blocked_destination"),
    ("http://foo.internal/", "blocked_destination"),
    ("http://example.com:22/", "blocked_destination"),
    ("http://example.com:8080/", "blocked_destination"),
])
def test_invalid_urls_are_rejected(raw: str, code: str) -> None:
    with pytest.raises(AppError) as error:
        validate_url_syntax(raw, OPEN)
    assert error.value.code == code


def test_blocklist_and_allowlist() -> None:
    blocked = SourcePolicy(blocked_domains=("blocked.com",))
    for url in ("https://blocked.com/x", "https://www.blocked.com/x"):
        with pytest.raises(AppError) as error:
            validate_url_syntax(url, blocked)
        assert error.value.code == "domain_not_allowed"
    assert validate_url_syntax("https://notblocked.com/x", blocked)

    allow = SourcePolicy(mode="allowlist", allowed_domains=("archive.org",))
    assert validate_url_syntax("https://archive.org/details/x", allow)
    assert validate_url_syntax("https://ia800.us.archive.org/x.mp4", allow)
    for url in ("https://evilarchive.org/x", "https://archive.org.evil.com/x", "https://www.youtube.com/watch?v=1"):
        with pytest.raises(AppError) as error:
            validate_url_syntax(url, allow)
        assert error.value.code == "domain_not_allowed"


def test_exemption_is_exact_host_and_port() -> None:
    policy = SourcePolicy(exempt=frozenset({("127.0.0.1", 8765)}))
    assert validate_url_syntax("http://127.0.0.1:8765/watch", policy).is_exempt
    for url in ("http://127.0.0.1:8766/x", "http://127.0.0.1/x", "http://localhost:8765/x"):
        with pytest.raises(AppError):
            validate_url_syntax(url, policy)


@pytest.mark.parametrize(("addresses", "allowed"), [
    (["93.184.216.34"], True),
    (["10.0.0.7"], False),
    (["93.184.216.34", "127.0.0.1"], False),      # one private answer poisons the name (DNS rebinding)
    (["fd00::1"], False),
    ([], False),
])
async def test_dns_answers_must_all_be_public(
    monkeypatch: pytest.MonkeyPatch, addresses: list[str], allowed: bool
) -> None:
    async def fake_resolve(host: str, port: int, *, timeout: float = 5.0) -> list[str]:
        return addresses

    monkeypatch.setattr(url_validation, "resolve_host", fake_resolve)
    if allowed:
        assert (await validate_public_url("https://example.com/v", OPEN)).host == "example.com"
    else:
        with pytest.raises(AppError) as error:
            await validate_public_url("https://example.com/v", OPEN)
        assert error.value.code == "blocked_destination"


async def test_unresolvable_host(monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        raise socket.gaierror("no such host")

    import asyncio
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", failing)
    with pytest.raises(AppError) as error:
        await validate_public_url("https://does-not-exist.example-domain.com/v", OPEN)
    assert error.value.code == "source_unreachable"


# ------------------------------------------------------------------ worker socket guard
@pytest.fixture
def listener() -> socket.socket:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    yield server
    server.close()


def test_socket_guard_blocks_private_destinations(listener: socket.socket) -> None:
    port = listener.getsockname()[1]
    guard.install_network_guard()
    try:
        for address in (("127.0.0.1", port), ("localhost", port), ("10.0.0.1", 80), ("169.254.169.254", 80)):
            with socket.socket() as sock, pytest.raises(guard.BlockedDestination):
                sock.connect(address)
        with socket.socket() as sock, pytest.raises(guard.BlockedDestination):
            sock.connect_ex(("127.0.0.1", port))
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=2)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock, pytest.raises(guard.BlockedDestination):
            sock.sendto(b"x", ("127.0.0.1", port))
        with socket.socket(socket.AF_UNIX) as sock, pytest.raises(guard.BlockedDestination):
            sock.connect("/tmp/does-not-matter.sock")
        assert len(guard.blocked_destinations()) >= 7
    finally:
        guard.uninstall_network_guard()
    with socket.create_connection(("127.0.0.1", port), timeout=2):
        pass  # back to normal once uninstalled


def test_socket_guard_exemption_is_exact(listener: socket.socket) -> None:
    port = listener.getsockname()[1]
    guard.install_network_guard([("127.0.0.1", port)])
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            pass
        with socket.socket() as sock, pytest.raises(guard.BlockedDestination):
            sock.connect(("127.0.0.1", port + 1 if port < 65535 else port - 1))
    finally:
        guard.uninstall_network_guard()


# -------------------------------------------------------------------------- file names
@pytest.mark.parametrize(("title", "expected"), [
    ("My: Video / Title?* <1>", "My Video Title 1"),
    ("  ..  ", "video"),
    ("CON", "video"),
    (None, "video"),
    ("../../etc/passwd", "etc passwd"),
    ("evil\u202egnp.exe", "evilgnp.exe"),             # right-to-left override removed
    ("日本語のタイトル", "日本語のタイトル"),
    ("line\nbreak\tand\x00null", "linebreakandnull"),
])
def test_sanitize_stem(title: str | None, expected: str) -> None:
    assert sanitize_stem(title) == expected


def test_filenames_and_headers() -> None:
    assert len(sanitize_stem("a" * 500)) == 120
    assert build_filename("Clip", "MP4", suffix="1080p") == "Clip (1080p).mp4"
    assert build_filename("Clip", "../sh") == "Clip.bin"
    assert build_filename(None, "srt", suffix="en", fallback="subtitles") == "subtitles (en).srt"
    header = content_disposition('Été "Paris" 日本.mp4')
    assert header.startswith('attachment; filename="Ete Paris.mp4"; filename*=UTF-8\'\'')
    assert '"' not in header.split("filename*=")[1] and "\n" not in header
    assert "%E6%97%A5%E6%9C%AC" in header


# -------------------------------------------------------------------------- rate limits
def test_rate_limiter_token_bucket() -> None:
    limiter = RateLimiter({"analyze": (3, 60.0)})
    assert [limiter.check("analyze", "a", now=0.0).allowed for _ in range(4)] == [True, True, True, False]
    assert limiter.check("analyze", "a", now=0.0).retry_after == 20
    assert limiter.check("analyze", "b", now=0.0).allowed          # other clients are unaffected
    assert limiter.check("analyze", "a", now=21.0).allowed         # one token refilled
    assert limiter.prune(now=10_000.0) == 2 and len(limiter) == 0
    assert RateLimiter({"x": (1, 60.0)}, enabled=False).check("x", "a").allowed


@pytest.mark.parametrize(("text", "expected"), [
    ("12/minute", (12, 60.0)), ("600/60", (600, 60.0)), ("5/10s", (5, 10.0)), ("3/2h", (3, 7200.0)),
])
def test_parse_rate(text: str, expected: tuple[int, float]) -> None:
    assert parse_rate(text) == expected


@pytest.mark.parametrize("text", ["", "12", "fast", "0/minute", "5/0s", "-1/minute"])
def test_parse_rate_rejects_garbage(text: str) -> None:
    with pytest.raises(ValueError):
        parse_rate(text)


# ---------------------------------------------------------------------- client identity
def _request(headers: dict[str, str], peer: str = "10.0.0.9") -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "client": (peer, 1234), "method": "GET", "path": "/"})


def test_client_identity() -> None:
    spoofed = {"X-Forwarded-For": "6.6.6.6, 203.0.113.7"}
    assert identify_client(_request(spoofed), header=None, trusted_hops=0).ip == "10.0.0.9"   # header ignored
    assert identify_client(_request(spoofed), header=None, trusted_hops=1).ip == "203.0.113.7"
    assert identify_client(_request(spoofed), header=None, trusted_hops=2).ip == "6.6.6.6"
    assert identify_client(_request({"X-Forwarded-For": "junk"}), header=None, trusted_hops=1).ip == "10.0.0.9"
    cdn = {"CF-Connecting-IP": "198.51.100.4", **spoofed}
    assert identify_client(_request(cdn), header="CF-Connecting-IP", trusted_hops=1).ip == "198.51.100.4"
    # A whole IPv6 /64 is one client; logs only ever see a coarsened address.
    a = identify_client(_request({}, peer="2001:db8:1:2:aaaa::1"), header=None, trusted_hops=0)
    b = identify_client(_request({}, peer="2001:db8:1:2:bbbb::2"), header=None, trusted_hops=0)
    assert a.key == b.key
    assert anonymize_ip("203.0.113.77") == "203.0.113.0" and anonymize_ip("nonsense") == "unknown"


# ------------------------------------------------------------------------------- config
def test_settings_defaults_and_parsing(tmp_path: object) -> None:
    settings = Settings(_env_file=None)
    assert settings.source_policy == "allowlist"
    assert settings.allowed_domains == list(DEFAULT_ALLOWED_DOMAINS)
    assert settings.allowed_ports == [80, 443] and settings.unsafe_allow_hosts == []
    parsed = Settings(
        _env_file=None, allowed_origins="https://a.example/, https://b.example",
        allowed_domains="*.Example.org, archive.org.", allowed_ports="80,443,8443",
    )
    assert parsed.allowed_origins == ["https://a.example", "https://b.example"]
    assert parsed.allowed_domains == ["example.org", "archive.org"]
    assert parsed.allowed_ports == [80, 443, 8443]


@pytest.mark.parametrize("overrides", [
    {"environment": "production", "unsafe_allow_hosts": "127.0.0.1:8765"},   # test hook in production
    {"environment": "production", "allowed_origins": "*"},                   # wildcard CORS in production
    {"unsafe_allow_hosts": "localhost:8765"},                                # must be an IP literal
    {"unsafe_allow_hosts": "127.0.0.1"},                                     # port is mandatory
    {"source_policy": "allowlist", "allowed_domains": ""},
    {"rate_limit_analyze": "lots"},
    {"file_ttl_seconds": 5},
    {"example_links": "A label and a link but no source | https://archive.org/details/x"},
])
def test_settings_reject_unsafe_configuration(overrides: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, **overrides)
