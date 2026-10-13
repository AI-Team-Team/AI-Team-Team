"""Recoverable directory publication; SQLite and renames are not OS-atomic."""

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from ai_team_team.core.exceptions import StateRestoreError
from .lease import WriterLease


def sync_directory(path):
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def directory_digest(staged, *, synchronize=False):
    """Use framed paths and streamed bytes without copying large file bodies."""
    digest = hashlib.sha256()
    if staged:
        for source in sorted(Path(staged).rglob("*")):
            if source.is_symlink():
                raise StateRestoreError("Publication staging cannot contain native symbolic links.")
            relative = source.relative_to(staged).as_posix().encode("utf-8")
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            digest.update(b"D" if source.is_dir() else b"F")
            if source.is_file():
                digest.update(source.stat().st_size.to_bytes(8, "big"))
                # Windows FlushFileBuffers requires a writable descriptor.
                with source.open("rb+" if synchronize else "rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                    if synchronize:
                        os.fsync(stream.fileno())
        if synchronize:
            for directory in sorted((source for source in Path(staged).rglob("*") if source.is_dir()), reverse=True):
                sync_directory(directory)
            sync_directory(staged)
    return digest.hexdigest()


class PublicationJournal:
    """Durable intent precedes the first rename; reconciliation is repeatable."""

    def __init__(self, managed_root, publication_id):
        self.root = Path(managed_root).resolve()
        self.publication_id = publication_id
        self.path = self.root / ".att-publication.json"
        self.entries = []
        self.database_path = None
        self.status = "prepared"
        self.lease = None

    def prepare(self, libraries, old_libraries):
        self.lease = WriterLease(str(self.root / ".att-publication"))
        if self.path.exists():
            raise StateRestoreError("An unresolved publication must be reconciled before another restore.")
        for lib_id in sorted(set(libraries) | set(old_libraries)):
            final = self.root / lib_id
            if final.parent != self.root or final.is_symlink():
                raise StateRestoreError("Invalid publication library path.")
            library = libraries.get(lib_id)
            if library is None and Path(old_libraries[lib_id].root_dir).resolve() != final:
                continue
            staged = Path(library.root_dir).resolve() if library else None
            if staged is not None and self.root not in staged.parents:
                raise StateRestoreError("Publication staging must be inside the managed filesystem.")
            self.entries.append({"final": str(final), "backup": str(self.root / f".{lib_id}-publication-{self.publication_id}"),
                                 "staged": str(staged) if staged else None, "existed": final.exists(), "digest": directory_digest(staged, synchronize=True)})
        self._save()
        return tuple(dict(entry) for entry in self.entries)

    def _save(self):
        descriptor, temporary = tempfile.mkstemp(prefix=".att-publication-write-", dir=self.root)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump({"publication_id": self.publication_id, "database_path": self.database_path,
                           "status": self.status, "entries": self.entries}, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            sync_directory(self.root)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @classmethod
    def open(cls, managed_root):
        root = Path(managed_root).resolve()
        path = root / ".att-publication.json"
        if not path.exists():
            return None
        if path.is_symlink():
            raise StateRestoreError("Publication journal cannot be a symbolic link.")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise StateRestoreError("Invalid publication journal encoding.") from exc
        if not isinstance(data, dict) or set(data) != {"publication_id", "database_path", "status", "entries"}:
            raise StateRestoreError("Invalid publication journal structure.")
        journal = cls(root, data["publication_id"])
        if type(journal.publication_id) is not str or len(journal.publication_id) != 32 or any(character not in "0123456789abcdef" for character in journal.publication_id):
            raise StateRestoreError("Invalid publication identity.")
        journal.entries = data["entries"]
        journal.database_path = data["database_path"]
        journal.status = data["status"]
        if journal.status not in {"prepared", "rollback"}:
            raise StateRestoreError("Invalid publication disposition.")
        if not isinstance(journal.entries, list) or (journal.database_path is not None and type(journal.database_path) is not str):
            raise StateRestoreError("Invalid publication references.")
        seen = set()
        for entry in journal.entries:
            if (not isinstance(entry, dict) or set(entry) != {"final", "backup", "staged", "existed", "digest"}
                    or any(type(entry[key]) is not str for key in ("final", "backup", "digest"))
                    or (entry["staged"] is not None and type(entry["staged"]) is not str)
                    or len(entry["digest"]) != 64 or any(char not in "0123456789abcdef" for char in entry["digest"])):
                raise StateRestoreError("Invalid staged-file evidence.")
            final, backup = Path(entry["final"]), Path(entry["backup"])
            if (final.parent != root or backup.parent != root or final.name in seen
                    or final.name.startswith(".") or final.is_symlink() or backup.is_symlink()):
                raise StateRestoreError("Publication paths escape the managed root.")
            seen.add(final.name)
            if backup.name != f".{final.name}-publication-{journal.publication_id}":
                raise StateRestoreError("Publication backup identity mismatch.")
            staged = Path(entry["staged"]) if entry["staged"] else None
            if staged and (root not in staged.resolve().parents or staged.is_symlink()):
                raise StateRestoreError("Invalid publication staging reference.")
            if type(entry["existed"]) is not bool:
                raise StateRestoreError("Invalid publication existence evidence.")
        return journal

    def publish(self, libraries):
        for entry in self.entries:
            final, backup = Path(entry["final"]), Path(entry["backup"])
            if backup.exists() or final.is_symlink():
                raise StateRestoreError("Publication paths changed after preparation.")
            if entry["staged"]:
                staged = Path(entry["staged"])
                if not staged.is_dir() or directory_digest(staged) != entry["digest"]:
                    raise StateRestoreError("Publication staging changed after validation.")
            if entry["existed"]:
                os.replace(final, backup)
            if entry["staged"]:
                os.replace(entry["staged"], final)
                libraries[final.name].root_dir = str(final)
            sync_directory(self.root)

    def rollback(self):
        for entry in reversed(self.entries):
            final, backup = Path(entry["final"]), Path(entry["backup"])
            if backup.exists():
                if final.exists():
                    shutil.rmtree(final)
                os.replace(backup, final)
            elif not entry["existed"] and final.exists():
                shutil.rmtree(final)
            elif entry["existed"] and not final.exists():
                raise StateRestoreError("Publication rollback cannot locate the original library.")
        sync_directory(self.root)

    def mark_rollback(self):
        """Persist rollback intent before undoing a published directory decision."""
        if self.path.exists():
            self.status = "rollback"
            self._save()

    def finish(self):
        for entry in self.entries:
            backup = Path(entry["backup"])
            if backup.exists():
                shutil.rmtree(backup)
        if self.path.exists():
            self.path.unlink()
        sync_directory(self.root)

    def release(self):
        if self.lease is not None:
            self.lease.close()
            self.lease = None
