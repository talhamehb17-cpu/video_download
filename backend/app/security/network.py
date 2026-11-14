"""Network-level safety rules shared by the API process and the media worker.

The service fetches URLs chosen by anonymous users, which makes server-side request
forgery (SSRF) the main risk. The rule enforced here is simple: the service may only
ever talk to *public* internet addresses. Loopback, private (RFC 1918), link-local
(including cloud metadata endpoints such as 169.254.169.254), carrier-grade NAT,
multicast, documentation and otherwise reserved ranges are refused -- for IPv4 and
IPv6, including IPv4 addresses smuggled inside IPv6 (mapped, 6to4, NAT64, Teredo).

This module has no third-party dependencies so the worker can import it before
anything else is loaded.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

_BLOCKED_V4 = tuple(
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",        # "this" network
        "10.0.0.0/8",       # private
        "100.64.0.0/10",    # carrier-grade NAT
        "127.0.0.0/8",      # loopback
        "169.254.0.0/16",   # link-local / cloud metadata
        "172.16.0.0/12",    # private
        "192.0.0.0/24",     # IETF protocol assignments
        "192.0.2.0/24",     # documentation
        "192.88.99.0/24",   # deprecated 6to4 relay anycast
        "192.168.0.0/16",   # private
        "198.18.0.0/15",    # benchmarking
        "198.51.100.0/24",  # documentation
        "203.0.113.0/24",   # documentation
        "224.0.0.0/4",      # multicast
        "240.0.0.0/4",      # reserved + broadcast
    )
)

_BLOCKED_V6 = tuple(
    ipaddress.ip_network(n)
    for n in (
        "::/128",           # unspecified
        "::1/128",          # loopback
        "64:ff9b:1::/48",   # local-use NAT64
        "100::/64",         # discard-only
        "2001::/23",        # IETF protocol assignments (includes Teredo)
        "2001:db8::/32",    # documentation
        "2002::/16",        # 6to4
        "3fff::/20",        # documentation
        "5f00::/16",        # segment routing
        "fc00::/7",         # unique local
        "fe80::/10",        # link-local
        "fec0::/10",        # deprecated site-local
        "ff00::/8",         # multicast
    )
)

_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_V4_COMPATIBLE = ipaddress.ip_network("::/96")


def parse_ip(value: str) -> IPAddress | None:
    """Parse an IP literal (tolerating brackets and IPv6 zone ids). ``None`` if not an IP."""
    text = value.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    text = text.split("%", 1)[0]
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        return None


def _embedded_ipv4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip in _NAT64 or (ip in _V4_COMPATIBLE and int(ip) > 1):
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def is_public_ip(ip: IPAddress | str) -> bool:
    """True only for globally routable unicast addresses."""
    if isinstance(ip, str):
        parsed = parse_ip(ip)
        if parsed is None:
            return False
        ip = parsed

    if isinstance(ip, ipaddress.IPv6Address):
        embedded = _embedded_ipv4(ip)
        if embedded is not None:
            return is_public_ip(embedded)
        if any(ip in net for net in _BLOCKED_V6):
            return False
    elif any(ip in net for net in _BLOCKED_V4):
        return False

    # Belt and braces: also require the standard library to agree.
    return bool(ip.is_global) and not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
        or ip.is_reserved or ip.is_unspecified
    )


def all_public(addresses: Iterable[str]) -> bool:
    addresses = list(addresses)
    return bool(addresses) and all(is_public_ip(a) for a in addresses)


# Host names that never belong on the public internet. Checked before DNS so the
# answer is fast and does not depend on the resolver.
_INTERNAL_SUFFIXES = (
    ".localhost", ".local", ".localdomain", ".internal", ".intranet", ".lan", ".home",
    ".home.arpa", ".corp", ".private", ".test", ".example", ".invalid", ".onion", ".arpa",
)
_INTERNAL_NAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback", "broadcasthost"})


def is_internal_hostname(host: str) -> bool:
    """True for names that are obviously not public DNS names."""
    name = host.strip().rstrip(".").lower()
    if not name or name in _INTERNAL_NAMES:
        return True
    if any(name.endswith(suffix) for suffix in _INTERNAL_SUFFIXES):
        return True
    labels = name.split(".")
    if len(labels) < 2:
        return True  # single-label names resolve inside private networks ("redis", "metadata")
    # A purely numeric (or hex) last label is how obfuscated IPv4 literals look
    # ("127.1", "0x7f.0.0.1", "2130706433"); real TLDs are alphabetic or punycode.
    tld = labels[-1]
    return tld.isdigit() or tld.startswith("0x") or not (tld.isalpha() or tld.startswith("xn--"))


def parse_host_port_list(items: Iterable[str]) -> frozenset[tuple[str, int]]:
    """Parse ``host:port`` pairs (used only for the explicit test/dev allow list)."""
    pairs: set[tuple[str, int]] = set()
    for raw in items:
        raw = raw.strip()
        if not raw:
            continue
        host, sep, port = raw.rpartition(":")
        if not sep or not port.isdigit():
            raise ValueError(f"expected host:port, got {raw!r}")
        pairs.add((host.strip("[]").lower(), int(port)))
    return frozenset(pairs)
