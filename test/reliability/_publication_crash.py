"""Abrupt file publication and pre-activation recovery exits use real journals."""

import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import time
import uuid
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from ai_team_team import ATTConfig, ATTManager, Agent
from ai_team_team.database.persistence.lease import WriterLease
from ai_team_team.database.persistence.publication import PublicationJournal
from ai_team_team.database.persistence.records import DomainRecord
from ai_team_team.database.persistence.store import DatabaseStore

from ._execution_crash import UnusedClient


def partial_files(path, managed_root, library_ids):
    lease = WriterLease(path)
    identifier = uuid.uuid4().hex
    staging = Path(tempfile.mkdtemp(prefix=".att-restore-crash-", dir=managed_root))
    libraries = {}
    for lib_id in library_ids:
        folder = staging / lib_id
        folder.mkdir()
        (folder / "note.txt").write_text("checkpoint", encoding="utf-8")
        libraries[lib_id] = SimpleNamespace(root_dir=str(folder))
    journal = PublicationJournal(managed_root, identifier)
    journal.database_path = path
    entries = journal.prepare(libraries, {})
    with closing(sqlite3.connect(path)) as database:
        checkpoint = database.execute("SELECT config_value FROM manager_config WHERE config_key='checkpoint_id'").fetchone()[0]
    store = DatabaseStore(path)
    store.write({"full": False, "records": (DomainRecord.capture("publication_manifests", {
        "publication_id": identifier, "checkpoint_id": checkpoint, "previous_generation": 1,
        "target_generation": 2, "staged_files": list(entries), "recovery_operation_id": identifier,
        "status": "prepared", "prepared_at": time.time(), "resolved_at": None, "state_version": 1,
    }),)})
    original = os.replace

    def crash_replace(source, target, *args, **kwargs):
        original(source, target, *args, **kwargs)
        target = Path(target)
        if target.parent.resolve() == Path(managed_root).resolve() and not target.name.startswith("."):
            os._exit(73)
    os.replace = crash_replace
    journal.publish(libraries)
    lease.close()
    raise AssertionError("The partial directory-publication exit did not occur.")


async def before_notice(path, workspace):
    client = UnusedClient()
    manager = ATTManager(Agent("RecoveryHost", "Architect", client),
        ATTConfig(workspace_root=workspace), persistence_mode="volatile")
    manager.register_llm_client("fixture", client)
    manager._activity.resume_after_restore = lambda: os._exit(73)
    await manager.load_state(path)
    raise AssertionError("The recovery handoff exit did not occur.")


if __name__ == "__main__":
    if sys.argv[1] == "files":
        partial_files(sys.argv[2], sys.argv[3], json.loads(sys.argv[4]))
    else:
        asyncio.run(before_notice(sys.argv[2], sys.argv[3]))
