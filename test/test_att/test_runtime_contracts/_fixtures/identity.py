"""Side-effect-free snapshots of every currently present Agent-owned field."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _freeze(value: Any) -> Any:
    if isinstance(value, (str, bytes)):
        content = value.encode("utf-8", errors="surrogatepass") if isinstance(value, str) else value
        return type(value).__name__, hashlib.sha256(content).hexdigest()
    if value is None or isinstance(value, (int, float, bool)):
        return type(value).__name__, value
    if isinstance(value, dict):
        return (
            "dict",
            id(value),
            tuple((_freeze(key), _freeze(item)) for key, item in value.items()),
        )
    if isinstance(value, (list, tuple)):
        return type(value).__name__, id(value), tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return type(value).__name__, id(value), frozenset(_freeze(item) for item in value)
    return type(value).__qualname__, id(value)


def _entry_evidence(path: Path) -> Any:
    if path.is_symlink():
        return "symlink", str(path.readlink())
    if path.is_dir():
        return "directory"
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class AgentIdentitySnapshot:
    object_id: int
    owned_fields: tuple
    private_library_id: str | None
    private_library_object_id: int | None
    private_entries: tuple

    @classmethod
    def capture(cls, agent: Any, manager: Any) -> "AgentIdentitySnapshot":
        # Reading vars does not lazily create invocation or lifecycle locks.
        fields = tuple((name, _freeze(value)) for name, value in sorted(vars(agent).items()))
        library = manager.libraries.get(agent.private_doc_library_id)
        entries = ()
        if library is not None:
            root = Path(library.root_dir)
            if root.is_symlink():
                entries = ((".", _entry_evidence(root)),)
            else:
                entries = tuple(
                    (path.relative_to(root).as_posix(), _entry_evidence(path))
                    for path in sorted(root.rglob("*"))
                )
        return cls(
            id(agent),
            fields,
            agent.private_doc_library_id,
            id(library) if library is not None else None,
            entries,
        )
