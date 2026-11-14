"""Temporary storage for metadata and prepared files.

Everything lives under one directory that is wiped when the service starts and
stops, and each analysis / job gets its own sub-directory that is deleted when it
expires. Nothing is ever written anywhere else.

To move prepared files to object storage (S3, R2, GCS...), keep this class for the
worker's scratch space and upload the finished file from ``JobManager._finish``;
the rest of the application only deals with opaque job ids.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

Area = Literal["analyses", "jobs"]


class TempStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    def prepare(self) -> None:
        """Start from an empty directory (removes leftovers from a previous run)."""
        self.wipe()
        for area in ("analyses", "jobs"):
            (self.root / area).mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)

    def wipe(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)

    def create(self, area: Area, item_id: str) -> Path:
        path = self.root / area / item_id
        path.mkdir(parents=True, exist_ok=False, mode=0o700)
        return path

    def remove(self, path: Path | None) -> None:
        """Delete a directory created by :meth:`create` (and nothing outside the root)."""
        if path is None:
            return
        resolved = path.resolve()
        if self.root not in resolved.parents:
            log.error("refusing to delete %s: outside the storage root", resolved)
            return
        shutil.rmtree(resolved, ignore_errors=True)

    def contains(self, path: Path) -> bool:
        return self.root in path.resolve().parents

    def free_bytes(self) -> int:
        try:
            return shutil.disk_usage(self.root).free
        except OSError:
            return 0

    def total_bytes(self) -> int:
        try:
            return shutil.disk_usage(self.root).total
        except OSError:
            return 0

    @staticmethod
    def size_of(directory: Path | None) -> int:
        """Bytes currently held by one job or analysis directory."""
        if directory is None:
            return 0
        total = 0
        try:
            for item in directory.rglob("*"):
                try:
                    if item.is_file():
                        total += item.stat().st_size
                except OSError:
                    continue
        except OSError:
            return total
        return total

    def used_bytes(self) -> int:
        total = 0
        for item in self.root.rglob("*"):
            try:
                if item.is_file():
                    total += item.stat().st_size
            except OSError:
                continue
        return total
