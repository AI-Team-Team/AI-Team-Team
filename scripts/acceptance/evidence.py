"""Identify the tested sources and environment without collecting runtime payloads."""

import hashlib
import json
import platform
import sqlite3
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path


PACKAGES = ("pydantic", "typing-extensions", "jsonschema", "sqlalchemy", "tokenizers")


def git(root, *arguments):
    result = subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "-C", str(root), *arguments],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def source_digest(root):
    """Identify current source, test, documentation, and configuration inputs."""
    files = set()
    for area in ("src", "test", "typecheck", "examples", "scripts", ".github", "docs", "Roadmap"):
        for path in (root / area).rglob("*"):
            if (not path.is_file() or path.suffix in {".pyc", ".pyo"}
                    or path.name == ".DS_Store"
                    or any(part in {"__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
                           or part.endswith(".egg-info") for part in path.parts)):
                continue
            files.add(path)
    files.update(root / name for name in ("README.md", "pyproject.toml", "MANIFEST.in") if (root / name).exists())
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def environment(root, revision=None):
    checkout = git(root, "rev-parse", "HEAD")
    return {
        "base_commit": checkout or revision,
        "source_kind": "checkout" if checkout else "archive",
        "worktree_dirty": bool(git(root, "status", "--porcelain")) if checkout else None,
        "source_digest": source_digest(root),
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "sqlite": sqlite3.sqlite_version,
        "packages": {name: version(name) for name in PACKAGES},
    }


def write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


