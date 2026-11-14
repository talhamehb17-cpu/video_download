"""Start a media worker process, stream its events and stop it on demand.

The worker runs in its own process group so that cancelling a task - or hitting a
time limit - can stop the worker *and* any FFmpeg child with one signal.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.errors import AppError

log = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
EventHandler = Callable[[dict[str, Any]], None]
_GRACE_SECONDS = 2.0
_DEFAULT_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def worker_environment(work_dir: str) -> dict[str, str]:
    """A minimal environment: no inherited secrets, proxies or user configuration."""
    return {
        "PATH": os.environ.get("PATH", _DEFAULT_PATH),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONPATH": str(BACKEND_ROOT),
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "HOME": work_dir,
        "TMPDIR": work_dir,
        "XDG_CACHE_HOME": os.path.join(work_dir, ".cache"),
        "XDG_CONFIG_HOME": os.path.join(work_dir, ".config"),
        "YTDLP_NO_PLUGINS": "1",
    }


async def _terminate(proc: asyncio.subprocess.Process) -> None:
    """Stop the worker's whole process group: politely first, then for good."""
    if proc.returncode is not None:
        return
    for sig, wait in ((signal.SIGTERM, _GRACE_SECONDS), (signal.SIGKILL, 5.0)):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, sig)
        try:
            await asyncio.wait_for(proc.wait(), timeout=wait)
            return
        except (TimeoutError, asyncio.TimeoutError):
            continue


def _kill_now(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)


async def _read_events(
    stream: asyncio.StreamReader, on_event: EventHandler | None
) -> dict[str, Any] | None:
    terminal: dict[str, Any] | None = None
    while True:
        try:
            line = await stream.readline()
        except ValueError:  # a line longer than the stream limit: not our protocol
            log.error("worker sent an oversized line; ignoring the rest of its output")
            break
        if not line:
            break
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("event") in ("result", "error"):
            terminal = event
        elif on_event is not None:
            try:
                on_event(event)
            except Exception:  # a broken listener must not break the pipe
                log.exception("worker event handler failed")
    return terminal


async def _drain(stream: asyncio.StreamReader, tail: deque[str]) -> None:
    buffer = b""
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            break
        buffer = (buffer + chunk)[-16384:]
    tail.extend(buffer.decode("utf-8", "replace").splitlines()[-25:])


async def run_worker(
    task: dict[str, Any],
    *,
    timeout: float,
    on_event: EventHandler | None = None,
    timeout_code: str = "job_timeout",
) -> dict[str, Any]:
    """Run one worker task to completion and return its ``result`` event.

    Raises :class:`AppError` for reported failures and time-outs. If the calling
    task is cancelled, the worker is stopped before the cancellation propagates.
    """
    work_dir = str(task["work_dir"])
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "app.worker",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(BACKEND_ROOT),
        env=worker_environment(work_dir),
        start_new_session=True,
        limit=1024 * 1024,
    )
    assert proc.stdin and proc.stdout and proc.stderr
    stderr_tail: deque[str] = deque(maxlen=25)
    terminal: dict[str, Any] | None = None
    try:
        async with asyncio.timeout(timeout):
            proc.stdin.write(json.dumps(task).encode("utf-8"))
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                await proc.stdin.drain()
            proc.stdin.close()
            terminal, _ = await asyncio.gather(
                _read_events(proc.stdout, on_event), _drain(proc.stderr, stderr_tail)
            )
            await proc.wait()
    except TimeoutError:
        await _terminate(proc)
        raise AppError(timeout_code, detail=f"worker exceeded {timeout:.0f}s") from None
    except asyncio.CancelledError:
        await asyncio.shield(_terminate(proc))
        raise
    finally:
        _kill_now(proc)

    if terminal is None:
        detail = f"worker exited with {proc.returncode} without a result: {' | '.join(stderr_tail)[-1500:]}"
        raise AppError("internal_error", detail=detail)
    if terminal.get("event") == "error":
        raise AppError(str(terminal.get("code") or "internal_error"), detail=str(terminal.get("detail") or ""))
    return terminal
