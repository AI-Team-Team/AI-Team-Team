"""Real transactions retain full corruption checks and publish caches last."""

import asyncio
import os
import sqlite3
from contextlib import closing
from unittest.mock import patch

from sqlalchemy import event, insert, text
from sqlalchemy.orm import Session

from ai_team_team import StateRestoreError
from ai_team_team.database.models import AgentMemoryCardModel, AgentMemorySegmentModel
from ai_team_team.database.persistence.records import DomainRecord, thaw
from ai_team_team.database.persistence.store.records import validate_database

from ._support import StoreCase, model_request, OWNER


class DatabaseBoundaryTests(StoreCase):
    def updated_request(self, **changes):
        return DomainRecord.capture("model_requests", {**thaw(model_request(OWNER).values), "state_version": 2, **changes})

    def assert_reference_valid(self):
        with self.store.session_factory() as session:
            validate_database(session)

    def test_regular_delta_does_not_run_full_reference_validation(self):
        with patch("ai_team_team.database.persistence.store.records.validate_database", wraps=validate_database) as full:
            self.write((self.updated_request(dispatch_state="sent", dispatched_at=2.0),))
        full.assert_not_called()
        self.assert_reference_valid()

    def test_changed_target_rechecks_cached_reverse_dependencies(self):
        frame = self.store._validation._accepted.graph.records["notification_frames"][0]
        invalid = DomainRecord.capture("notification_frames", {**dict(frame), "context_version": 2})
        # Direct SQL models an invalid target change, bypassing append guards.
        with self.store.session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            self.store._validation.begin(session)
            session.execute(text("UPDATE notification_frames SET context_version=2 WHERE frame_id='frame'"))
            with self.assertRaisesRegex(StateRestoreError, "context version mismatch"):
                self.store._validation.prepare(session)
            with self.assertRaisesRegex(StateRestoreError, "context version mismatch"):
                validate_database(session)
            session.rollback()
            self.store._validation.finish()
        self.assertEqual(invalid.values["context_version"], 2)
        self.assert_reference_valid()

    def test_failed_commit_does_not_publish_candidate_or_change_database(self):
        with patch.object(Session, "commit", side_effect=RuntimeError("Synthetic commit failure")):
            with self.assertRaisesRegex(RuntimeError, "Synthetic commit failure"):
                self.write((self.updated_request(dispatch_state="sent", dispatched_at=2.0),))
        self.assertIsNone(self.store._validation._accepted)
        with closing(sqlite3.connect(self.path)) as database:
            self.assertEqual(database.execute("SELECT dispatch_state FROM model_requests").fetchone(), ("unsent",))
            self.assertEqual(database.execute("SELECT count(*) FROM commit_receipts").fetchone(), (1,))
        self.write((self.updated_request(dispatch_state="sent", dispatched_at=2.0),))
        self.assert_reference_valid()

    def test_cache_is_promoted_only_after_real_commit(self):
        accepted = self.store._validation._accepted
        original = Session.commit
        observed = []

        def commit(session):
            self.assertIs(self.store._validation._accepted, accepted)
            with closing(sqlite3.connect(self.path)) as database:
                observed.append(database.execute("SELECT dispatch_state FROM model_requests").fetchone()[0])
            return original(session)

        with patch.object(Session, "commit", commit):
            self.write((self.updated_request(dispatch_state="sent", dispatched_at=2.0),))
        self.assertEqual(observed, ["unsent"])
        self.assertIsNot(self.store._validation._accepted, accepted)
        self.assert_reference_valid()

    def test_base_exception_rolls_back_and_discards_candidate(self):
        with patch.object(Session, "commit", side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                self.write((self.updated_request(dispatch_state="sent", dispatched_at=2.0),))
        self.assertIsNone(self.store._validation._accepted)
        self.assertFalse(self.store._validation.tracker.active)
        self.assert_reference_valid()

    def test_external_connection_corruption_invalidates_baseline(self):
        with closing(sqlite3.connect(self.path)) as database:
            database.execute("UPDATE notification_frames SET context_version=2")
            database.commit()
        with self.assertRaisesRegex(StateRestoreError, "context version mismatch"):
            self.write()
        self.assertIsNone(self.store._validation._accepted)

    def test_same_engine_mutation_invalidates_baseline(self):
        with self.store.session_factory() as session:
            session.execute(text("UPDATE notification_frames SET context_version=2"))
            session.commit()
        with self.assertRaisesRegex(StateRestoreError, "context version mismatch"):
            self.write()

    def test_new_connection_rebuilds_baseline(self):
        self.store.engine.dispose()
        with patch("ai_team_team.database.persistence.store.records.validate_database", wraps=validate_database) as full:
            self.write()
        self.assertEqual(full.call_count, 1)
        self.assert_reference_valid()

    def test_raw_connection_mutation_invalidates_baseline(self):
        connection = self.store.engine.raw_connection()
        try:
            connection.execute("UPDATE notification_frames SET context_version=2")
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(StateRestoreError, "context version mismatch"):
            self.write()

    def test_unmodelled_trigger_forces_full_validation(self):
        with self.store.session_factory() as session:
            session.execute(text("CREATE TRIGGER hidden_change AFTER UPDATE ON model_requests BEGIN UPDATE notification_frames SET context_version=2; END"))
            session.commit()
        # Establish a valid baseline with the trigger already present.
        self.write()
        with self.assertRaisesRegex(StateRestoreError, "context version mismatch"):
            self.write((self.updated_request(dispatch_state="sent", dispatched_at=2.0),), version=3)
        self.assert_reference_valid()

    def test_receipt_trigger_cannot_change_facts_after_validation(self):
        with self.store.session_factory() as session:
            session.execute(text("CREATE TRIGGER late_change AFTER INSERT ON commit_receipts BEGIN UPDATE notification_frames SET context_version=2; END"))
            session.commit()
        with self.assertRaisesRegex(StateRestoreError, "context version mismatch"):
            self.write()
        self.assertIsNone(self.store._validation._accepted)
        self.assert_reference_valid()

    def test_temporary_trigger_also_forces_full_validation(self):
        with self.store.session_factory() as session:
            session.execute(text("CREATE TEMP TRIGGER temporary_change AFTER UPDATE ON main.model_requests BEGIN UPDATE notification_frames SET context_version=2; END"))
            session.commit()
        self.write()
        with self.assertRaisesRegex(StateRestoreError, "context version mismatch"):
            self.write((self.updated_request(dispatch_state="sent", dispatched_at=2.0),), version=3)
        self.assert_reference_valid()

    def test_replaced_database_file_is_rejected_before_writing(self):
        replacement = self.path + ".replacement"
        with closing(sqlite3.connect(self.path)) as source, closing(sqlite3.connect(replacement)) as target:
            source.backup(target)
        # Windows does not permit replacing a file with open SQLite handles.
        self.store.engine.dispose()
        os.replace(replacement, self.path)
        with self.assertRaisesRegex(StateRestoreError, "file identity changed"):
            self.write()
        self.assertIsNone(self.store._validation._accepted)

    def test_delta_sql_work_does_not_scale_with_unrelated_tables(self):
        statements = []

        def observe(connection, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(self.store.engine, "after_cursor_execute", observe)
        try:
            self.write((self.updated_request(dispatch_state="sent", dispatched_at=2.0),))
        finally:
            event.remove(self.store.engine, "after_cursor_execute", observe)
        self.assertLess(len(statements), 100)
        self.assertFalse(any('FROM "libraries"' in sql or 'FROM libraries' in sql for sql in statements))
        self.assert_reference_valid()

    def test_unknown_statement_effect_falls_back_to_full_reference(self):
        with self.store.session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            self.store._validation.begin(session)
            session.execute(text("WITH target AS (SELECT 'model-request' AS id) UPDATE model_requests "
                                 "SET dispatch_state='sent', dispatched_at=2.0, state_version=2 "
                                 "WHERE model_request_id IN (SELECT id FROM target)"))
            with patch("ai_team_team.database.persistence.store.records.validate_database", wraps=validate_database) as full:
                candidate = self.store._validation.prepare(session)
            self.assertEqual(full.call_count, 1)
            session.commit()
            self.store._validation.finish(candidate)
        self.assert_reference_valid()

    def test_native_cascade_refreshes_indirect_source_projections(self):
        with self.store.session_factory() as session:
            session.execute(insert(AgentMemorySegmentModel).values(segment_id="segment", agent_id=OWNER,
                invocation_id="invocation", recall_content="Retained artifact", content_sha256="0" * 64,
                status="indexed", attempts=0, created_at=1.0, updated_at=1.0))
            session.execute(insert(AgentMemoryCardModel).values(memory_id="card", agent_id=OWNER,
                invocation_id="invocation", title="Title", summary="Summary", segment_id="segment",
                status="active", version=1, created_at=1.0, updated_at=1.0))
            session.commit()
        self.write()
        self.assertEqual(len(self.store._validation._accepted.graph.sources["agent_memory_cards"]), 1)
        with self.store.session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            self.store._validation.begin(session)
            session.execute(text("DELETE FROM agent_memory_segments WHERE segment_id='segment'"))
            candidate = self.store._validation.prepare(session)
            self.assertFalse(candidate.graph.sources["agent_memory_cards"])
            validate_database(session)
            session.commit()
            self.store._validation.finish(candidate)
        self.assert_reference_valid()
