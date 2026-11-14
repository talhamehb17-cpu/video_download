"""Who is calling? Today that is an IP address; tomorrow it can be an account.

Everything that needs a per-caller identity (rate limits, concurrent-job limits,
job ownership) depends on :class:`ClientIdentity` rather than on the request, so
adding sign-in later means changing only :func:`identify_client`.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from starlette.requests import HTTPConnection

from app.security.network import parse_ip


@dataclass(frozen=True)
class ClientIdentity:
    ip: str          # best-effort client address
    key: str         # stable key for limits (IPv6 collapsed to its /64)
    kind: str = "anonymous"

    @property
    def log_label(self) -> str:
        return anonymize_ip(self.ip)


def _rate_key(ip_text: str) -> str:
    ip = parse_ip(ip_text)
    if ip is None:
        return ip_text or "unknown"
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        # One subscriber usually controls a whole /64; limit them as one client.
        return str(ipaddress.ip_network(f"{ip}/64", strict=False).network_address) + "/64"
    return str(ip)


def anonymize_ip(ip_text: str) -> str:
    """Coarsen an address for logs (drop the last IPv4 octet / keep an IPv6 /48)."""
    ip = parse_ip(ip_text)
    if ip is None:
        return "unknown"
    if isinstance(ip, ipaddress.IPv4Address):
        return str(ipaddress.ip_network(f"{ip}/24", strict=False).network_address)
    return str(ipaddress.ip_network(f"{ip}/48", strict=False).network_address)


def client_ip(conn: HTTPConnection, *, header: str | None, trusted_hops: int) -> str:
    """Resolve the caller's address.

    * ``header`` - a header your platform sets and overwrites itself
      (``CF-Connecting-IP``, ``Fly-Client-IP``...). Used when present.
    * ``trusted_hops`` - number of reverse proxies in front of the app. The client
      address is then the N-th entry from the *right* of ``X-Forwarded-For``; entries
      to its left are supplied by the client and can't be trusted.
    * otherwise the TCP peer address.
    """
    if header:
        value = conn.headers.get(header)
        if value and parse_ip(value.strip()) is not None:
            return value.strip()
    if trusted_hops > 0:
        forwarded = [p.strip() for p in conn.headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if len(forwarded) >= trusted_hops:
            candidate = forwarded[-trusted_hops]
            if parse_ip(candidate) is not None:
                return candidate
    return conn.client.host if conn.client else "unknown"


def identify_client(conn: HTTPConnection, *, header: str | None, trusted_hops: int) -> ClientIdentity:
    ip = client_ip(conn, header=header, trusted_hops=trusted_hops)
    return ClientIdentity(ip=ip, key=_rate_key(ip))
