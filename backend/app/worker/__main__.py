"""Entry point of the media worker: ``python -m app.worker``.

Protocol: one JSON task on stdin; newline-delimited JSON events on stdout
(``stage``, ``progress`` and finally ``result`` or ``error``). Diagnostics go to
stderr. See :mod:`app.worker` for the reasoning.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any


def main() -> int:
    # Keep a private handle on the protocol stream, then point fd 1 at stderr so
    # nothing else in this process - or FFmpeg - can write into the protocol.
    channel = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    def emit(event: dict[str, Any]) -> None:
        channel.write(json.dumps(event, separators=(",", ":"), ensure_ascii=True) + "\n")
        channel.flush()

    try:
        task = json.loads(sys.stdin.read())
        if not isinstance(task, dict) or task.get("task") not in ("analyze", "download", "subtitle"):
            raise ValueError("unknown task")
    except Exception as exc:
        emit({"event": "error", "code": "internal_error", "detail": f"bad task: {exc}"})
        return 2

    from app.worker import guard

    limits = task.get("limits") or {}
    guard.die_with_parent()
    guard.apply_resource_limits(max_file_bytes=limits.get("max_file_bytes"), nice=int(task.get("nice") or 0))
    guard.install_network_guard(tuple(pair) for pair in task.get("exempt") or [])

    try:
        from app.worker import tasks  # imports yt-dlp: only after the lock-down above

        tasks.run(task, emit)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:
        emit({"event": "error", "code": "internal_error", "detail": f"{type(exc).__name__}: {exc}"[:800]})
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
