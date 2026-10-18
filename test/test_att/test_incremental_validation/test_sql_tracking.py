"""Unknown SQL cannot borrow a derived-table exemption from its text."""

from unittest.mock import patch

from sqlalchemy import select, text

from ai_team_team import StateRestoreError
from ai_team_team.database.models import ACTIVITY_TABLES
from ai_team_team.database.persistence.store.records import read_receipt, validate_database

from ._support import OWNER, StoreCase


class SQLTrackingTests(StoreCase):
    def test_fts_markers_do_not_exempt_unknown_business_writes(self):
        markers = (
            "marker AS (SELECT 'agent_memory_cards_fts')",
            "marker AS (SELECT 1 /* agent_memory_cards_fts */)",
            "agent_memory_cards_fts AS (SELECT 1)",
            "marker AS (SELECT 1 /* agent_memory_cards_fts_shadow */)",
        )
        for marker in markers:
            with self.subTest(marker=marker):
                self.write(version=2)
                try:
                    with self.store.session_factory() as session:
                        session.execute(text("BEGIN IMMEDIATE"))
                        self.store._validation.begin(session)
                        self.assertIsNotNone(self.store._validation._base)
                        session.execute(text(f"WITH {marker} UPDATE notification_frames SET context_version=2 WHERE frame_id='frame'"))
                        self.assertTrue(self.store._validation.tracker.uncertain)
                        with self.assertRaisesRegex(StateRestoreError, "context version mismatch"):
                            validate_database(session)
                        with patch("ai_team_team.database.persistence.store.records.validate_database",
                                   wraps=validate_database) as full:
                            with self.assertRaisesRegex(StateRestoreError, "context version mismatch"):
                                self.store._validation.prepare(session)
                        self.assertEqual(full.call_count, 1)
                        session.rollback()
                finally:
                    self.store._validation.finish()

    def test_valid_unknown_write_with_fts_marker_still_runs_full_reference(self):
        try:
            with self.store.session_factory() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                self.store._validation.begin(session)
                session.execute(text("WITH marker AS (SELECT 'agent_memory_cards_fts') UPDATE model_requests "
                                     "SET dispatch_state='sent', dispatched_at=2.0, state_version=2"))
                with patch("ai_team_team.database.persistence.store.records.validate_database",
                           wraps=validate_database) as full:
                    candidate = self.store._validation.prepare(session)
                self.assertEqual(full.call_count, 1)
                self.assertEqual(candidate.graph.records["model_requests"][0]["dispatch_state"], "sent")
                validate_database(session)
                session.rollback()
        finally:
            self.store._validation.finish()

    def test_lookalike_fts_tables_and_definitions_are_not_exempt(self):
        for statement in (
            "CREATE TABLE agent_memory_cards_fts_shadow (payload TEXT)",
            "CREATE TABLE agent_memory_cards_fts (payload TEXT)",
        ):
            with self.subTest(statement=statement):
                self.write(version=2)
                try:
                    with self.store.session_factory() as session:
                        session.execute(text("BEGIN IMMEDIATE"))
                        self.store._validation.begin(session)
                        session.execute(text(statement))
                        self.assertTrue(self.store._validation.tracker.uncertain)
                        session.rollback()
                finally:
                    self.store._validation.finish()

    def test_actual_derived_fts_writer_operations_remain_recognized(self):
        try:
            with self.store.session_factory() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                self.store._validation.begin(session)
                self.store._sync_memory_fts(session, {
                    "episodic_memory_enabled": True, "full": True,
                    "memory_cards": [{"memory_id": "derived", "agent_id": OWNER,
                        "title": "Title", "summary": "Summary", "tags": ["test"], "status": "active"}],
                })
                self.assertFalse(self.store._validation.tracker.uncertain)
                self.store._write_deletions(session, {"deleted_agents": ["absent"]})
                self.assertFalse(self.store._validation.tracker.uncertain)
                self.store._sync_memory_fts(session, {"episodic_memory_enabled": False})
                self.assertFalse(self.store._validation.tracker.uncertain)
                session.rollback()
        finally:
            self.store._validation.finish()

    def test_lookalike_table_dml_is_not_exempt(self):
        for name in ("agent_memory_cards_fts_shadow", "agent_memory_card\u017f_ft\u017f"):
            with self.subTest(table=name):
                try:
                    with self.store.session_factory() as session:
                        session.execute(text("BEGIN IMMEDIATE"))
                        self.store._validation.begin(session)
                        session.execute(text(f"CREATE TABLE {name} (payload TEXT)"))
                        # Isolate DML classification from the preceding DDL.
                        self.store._validation.tracker.start()
                        session.execute(text(f"DELETE FROM {name}"))
                        self.assertTrue(self.store._validation.tracker.uncertain)
                        session.rollback()
                finally:
                    self.store._validation.finish()

    def test_invalid_unknown_write_rolls_back_without_a_receipt(self):
        original = self.store._write_configs

        def mutate(session, configs):
            original(session, configs)
            session.execute(text("WITH marker AS (SELECT 'agent_memory_cards_fts') "
                                 "UPDATE notification_frames SET context_version=2 WHERE frame_id='frame'"))

        with patch.object(self.store, "_write_configs", side_effect=mutate):
            with self.assertRaisesRegex(StateRestoreError, "context version mismatch"):
                self.write(version=2)
        self.assertIsNone(self.store._validation._accepted)
        with self.store.session_factory() as session:
            self.assertEqual(session.execute(select(ACTIVITY_TABLES["notification_frames"].c.context_version)).scalar_one(), 1)
            self.assertIsNone(read_receipt(session, "operation-2"))
            validate_database(session)
