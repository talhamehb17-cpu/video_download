"""Lock-down applied inside the worker before any extractor code runs.

* **Network guard** - every outgoing socket connection made from Python is checked
  against the public-address rule at the moment of ``connect()``, using the actual
  IP being dialled. That covers redirects, embedded players, playlists, thumbnails
  and DNS rebinding, regardless of which HTTP library opens the socket.
* **Resource limits** - a hard per-file size limit enforced by the kernel (it also
  applies to FFmpeg children), no core dumps, lower CPU priority.
"""

from __future__ import annotations

import contextlib
import os
import signal
import socket
import sys
from collections.abc import Iterable
from typing import Any

from app.security.network import is_public_ip, parse_ip

MARKER = "blocked by network policy"


class BlockedDestination(PermissionError):
    """Raised instead of opening a connection the policy does not allow."""


_blocked: list[str] = []
_exempt: frozenset[tuple[str, int]] = frozenset()
_originals: dict[str, Any] = {}


def blocked_destinations() -> list[str]:
    """Destinations refused so far in this process (for diagnostics)."""
    return list(_blocked)


def _deny(what: str) -> None:
    _blocked.append(what)
    raise BlockedDestination(f"{MARKER}: {what}")


def _check(sock: socket.socket, address: Any) -> None:
    if sock.family not in (socket.AF_INET, socket.AF_INET6):
        _deny(f"socket family {sock.family!r}")
    if not isinstance(address, tuple) or len(address) < 2:
        _deny(repr(address))
    host, port = str(address[0]), address[1]
    ip = parse_ip(host)
    if ip is None or not isinstance(port, int):
        # connect() would resolve a host name itself, outside our control.
        _deny(f"unresolved destination {host!r}")
        return
    mapped = getattr(ip, "ipv4_mapped", None)
    literal = str(mapped or ip)
    if (literal, port) in _exempt:
        return
    if not is_public_ip(ip):
        _deny(f"{literal}:{port}")


def install_network_guard(exempt: Iterable[tuple[str, int]] = ()) -> None:
    """Patch ``socket.socket`` so only public destinations can be reached."""
    global _exempt
    _exempt = frozenset((str(host).lower(), int(port)) for host, port in exempt)
    if _originals:
        return

    cls = socket.socket
    _originals.update(connect=cls.connect, connect_ex=cls.connect_ex, sendto=cls.sendto)
    original_connect, original_connect_ex, original_sendto = cls.connect, cls.connect_ex, cls.sendto

    def connect(self: socket.socket, address: Any) -> None:
        _check(self, address)
        return original_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        _check(self, address)
        return original_connect_ex(self, address)

    def sendto(self: socket.socket, data: Any, *args: Any) -> int:
        if args:
            _check(self, args[-1])
        return original_sendto(self, data, *args)

    cls.connect = connect  # type: ignore[method-assign,assignment]
    cls.connect_ex = connect_ex  # type: ignore[method-assign,assignment]
    cls.sendto = sendto  # type: ignore[method-assign,assignment]

    # HTTP stacks that open sockets from native code would bypass the patch above,
    # so make sure they can never be imported in this process.
    sys.modules["curl_cffi"] = None  # type: ignore[assignment]


def uninstall_network_guard() -> None:
    """Restore the original socket methods (used by tests)."""
    global _exempt
    if _originals:
        cls = socket.socket
        cls.connect = _originals["connect"]  # type: ignore[method-assign]
        cls.connect_ex = _originals["connect_ex"]  # type: ignore[method-assign]
        cls.sendto = _originals["sendto"]  # type: ignore[method-assign]
        _originals.clear()
    sys.modules.pop("curl_cffi", None)
    _blocked.clear()
    _exempt = frozenset()


def die_with_parent() -> None:
    """Ask the kernel to kill this worker if the API process disappears (Linux only)."""
    with contextlib.suppress(Exception):  # not available on every platform
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl(1, int(signal.SIGKILL))  # PR_SET_PDEATHSIG


def apply_resource_limits(*, max_file_bytes: int | None, nice: int = 0) -> None:
    """Kernel-enforced limits for this process and every child it starts."""
    try:
        import resource
    except ImportError:  # pragma: no cover - non-POSIX platforms
        return

    if max_file_bytes:
        # With SIGXFSZ ignored, writing past the limit fails with EFBIG instead of
        # killing the process, so the failure can be reported properly. Ignored
        # signals stay ignored across exec(), so FFmpeg behaves the same way.
        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
        resource.setrlimit(resource.RLIMIT_FSIZE, (max_file_bytes, max_file_bytes))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if nice > 0:
        with contextlib.suppress(OSError):
            os.nice(nice)
