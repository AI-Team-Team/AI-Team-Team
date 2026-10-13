"""Resolve crash-left publication before reading or mutating managed state."""

import json
import time
from pathlib import Path

from sqlalchemy import select

from ai_team_team.core.exceptions import StateRestoreError
from ai_team_team.database.models import ACTIVITY_TABLES, ManagerConfigModel
from ai_team_team.database.persistence.publication import PublicationJournal
from ai_team_team.database.persistence.lease import WriterLease


def reconcile_publication(store):
    with store.session_factory() as session:
        from .records import validate_database
        validate_database(session)
        config = session.get(ManagerConfigModel, "att_config")
        if config is None:
            return
        root = Path(json.loads(config.config_value)["workspace_root"]).resolve() / ".att_doc_libs"
        if root.is_symlink():
            raise StateRestoreError("A publication cannot use a symbolic managed root.")
        if not (root / ".att-publication.json").exists():
            return
        with WriterLease(str(root / ".att-publication")):
            _reconcile_journal(store, session, root)


def _reconcile_journal(store, session, root):
    journal = PublicationJournal.open(root)
    if journal is None:
        return
    if journal.database_path is not None and Path(journal.database_path).resolve() != Path(store.db_path):
        raise StateRestoreError("The managed root has a publication belonging to another state database.")
    table = ACTIVITY_TABLES["publication_manifests"]
    predicate = table.c.publication_id == journal.publication_id
    row = session.execute(select(table).where(predicate)).mappings().one_or_none()
    if row is not None and row["staged_files"] != journal.entries:
        raise StateRestoreError("Publication journal contradicts its durable manifest.")
    if row is None or row["status"] != "published" or journal.status == "rollback":
        journal.rollback()
        from .publication_rollback import discard_provisional_records
        discard_provisional_records(session, journal.publication_id)
        if row is not None and row["status"] != "rolled_back":
            session.execute(table.update().where(predicate).values(status="rolled_back", state_version=row["state_version"] + 1, resolved_at=time.time()))
        # Provisional additions must be removed even when a previous attempt
        # already recorded rollback but crashed before journal cleanup.
        session.commit()
    else:
        for entry in journal.entries:
            if entry["staged"] and not Path(entry["final"]).is_dir():
                raise StateRestoreError("A committed publication is missing its final directory.")
    journal.finish()
