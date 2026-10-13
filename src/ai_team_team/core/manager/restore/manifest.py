"""Durable publication decisions and deterministic interruption annotations."""

import asyncio
import time
import uuid

from ai_team_team.database.persistence.publication import PublicationJournal
from ai_team_team.database.persistence.records import DomainRecord, thaw
from ai_team_team.database.persistence.receipts import settle_commit
from .recovery import derive_recovery


async def prepare_manifest(manager, staged, managed_root, state):
    identifier = uuid.uuid4().hex
    journal = PublicationJournal(managed_root, identifier)
    journal.database_path = getattr(manager, "_restore_source_path", None) or manager.db_path
    manager._publication_journal = journal
    entries = await asyncio.to_thread(journal.prepare, staged.libraries, manager.libraries)
    generation = max(manager._resources.generation,
                     int(state["configs"].get("publication_generation", "1")),
                     *(record.values["target_generation"] for record in state.get("records", ())
                       if record.table_name == "publication_manifests"))
    manifest = DomainRecord.capture("publication_manifests", {
        "publication_id": identifier, "checkpoint_id": state["configs"].get("checkpoint_id", identifier),
        "previous_generation": generation, "target_generation": generation + 1,
        "staged_files": list(entries), "recovery_operation_id": f"recovery-{identifier}",
        "status": "prepared", "prepared_at": time.time(), "resolved_at": None, "state_version": 1,
    })
    await commit_manifest(manager, manifest)
    staged._records._merge((manifest,))
    annotations, events, plan = derive_recovery(staged, manifest.values["checkpoint_id"], identifier)
    manager._publication_annotations = annotations, events
    staged._recovery_plan = plan
    return manifest


async def commit_manifest(manager, manifest, *, annotations=(), events=(), rollback=False):
    path = getattr(manager, "_restore_source_path", None) or manager.db_path
    if path:
        snapshot = {"full": False, "state_version": max(1, manager._state_version),
                    "configs": {"publication_generation": manifest.values["target_generation"]} if manifest.values["status"] == "published" else None,
                    "records": (manifest, *annotations), "memory_events": events,
                    "_publication_rollback": manifest.values["publication_id"] if rollback else None,
                    "_publication_operation": True}
        await settle_commit(asyncio.wrap_future(manager._persistence.submit(path, snapshot)))


async def resolve_manifest(manager, manifest, status):
    values = thaw(manifest.values)
    values.update(status=status, resolved_at=time.time(), state_version=manifest.version + (2 if status == "rolled_back" else 1))
    resolved = DomainRecord.capture("publication_manifests", values)
    annotations, events = getattr(manager, "_publication_annotations", ((), ()))
    await commit_manifest(manager, resolved, annotations=annotations if status == "published" else (),
                          events=events if status == "published" else (), rollback=status == "rolled_back")
    return resolved
