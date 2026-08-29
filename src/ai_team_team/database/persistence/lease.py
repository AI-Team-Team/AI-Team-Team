"""Cross-process writer ownership for ATT SQLite state databases."""

import os
from pathlib import Path
from typing import Any

from ai_team_team.core.exceptions import DatabaseOwnershipError


class WriterLease:
    """A non-blocking cross-process lease for one SQLite writer manager."""

    def __init__(self, db_path: str):
        self.db_path = str(Path(db_path).resolve())
        self.lock_path = f"{self.db_path}.writer.lock"
        Path(self.lock_path).parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.lock_path, "a+", encoding="utf-8")
        try:
            try:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._lock_kind = "fcntl"
            except ImportError:
                import msvcrt

                msvcrt_api: Any = msvcrt
                self._file.seek(0)
                if not self._file.read(1):
                    self._file.write(" ")
                    self._file.flush()
                self._file.seek(0)
                msvcrt_api.locking(self._file.fileno(), msvcrt_api.LK_NBLCK, 1)
                self._lock_kind = "msvcrt"
        except (BlockingIOError, OSError) as exc:
            self._file.close()
            raise DatabaseOwnershipError(
                f"State database {self.db_path!r} already has an active writer manager."
            ) from exc
        self._file.seek(0)
        self._file.truncate()
        self._file.write(f"pid={os.getpid()}\n")
        self._file.flush()

    def close(self) -> None:
        if self._file.closed:
            return
        try:
            if self._lock_kind == "fcntl":
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            else:
                import msvcrt

                msvcrt_api: Any = msvcrt
                self._file.seek(0)
                msvcrt_api.locking(self._file.fileno(), msvcrt_api.LK_UNLCK, 1)
        finally:
            self._file.close()
