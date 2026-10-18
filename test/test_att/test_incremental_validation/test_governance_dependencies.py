"""Every governance input table retains the full reference's authority checks."""

from unittest.mock import patch

from sqlalchemy import select, text, update

from ai_team_team import StateRestoreError
from ai_team_team.core.communication import ApprovalPrincipal
from ai_team_team.core.governance import GovernanceBallot, GovernanceRound
from ai_team_team.database.models import (
    GovernanceBallotModel,
    GovernanceElectorateModel,
    GovernanceRoundModel,
    MigrationRequestModel,
)
from ai_team_team.database.persistence.receipts import CommitReceipt
from ai_team_team.database.persistence.store.governance_reader import read_governance_state
from ai_team_team.database.persistence.store.records import read_receipt, validate_database

from ._support import OWNER, StoreCase


class GovernanceDependencyTests(StoreCase):
    def setUp(self):
        super().setUp()
        vote = GovernanceRound(
            round_id="case", business_kind="migration", business_id="request",
            principal=ApprovalPrincipal(kind="agent", principal_id=OWNER),
            round_number=1, choice_kind="boolean", voter_agent_ids=[OWNER],
            prompt="Decide a synthetic request.", created_at=1.0,
            ballots=[GovernanceBallot(ballot_id="ballot", round_id="case",
                voter_agent_id=OWNER, choice={"approved": True}, created_at=2.0)],
        )
        self.store.write({
            "full": False, "state_version": 2, "links": None,
            "governance_rounds": [vote.model_dump(mode="json")],
            "_operations": (CommitReceipt("governance-setup", 2, "durable", ()),),
        })
        with self.store.session_factory() as session:
            validate_database(session)

    def assert_both_paths_reject(self, model, changes, reason):
        table = model.__table__
        try:
            with self.store.session_factory() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                self.store._validation.begin(session)
                self.assertIsNotNone(self.store._validation._base)
                session.execute(update(table).values(**changes))
                self.assertEqual(self.store._validation.tracker.touched, {table.name})
                with self.assertRaisesRegex(StateRestoreError, reason):
                    validate_database(session)
                with patch("ai_team_team.database.persistence.store.records.validate_database",
                           wraps=validate_database) as full:
                    with self.assertRaisesRegex(StateRestoreError, reason):
                        self.store._validation.prepare(session)
                full.assert_not_called()
                session.rollback()
        finally:
            self.store._validation.finish()

    def test_case_only_change_is_rejected_by_both_paths(self):
        self.assert_both_paths_reject(
            GovernanceRoundModel, {"choice_schema": {}}, "frozen electorate or choice schema"
        )

    def test_electorate_only_change_is_rejected_by_both_paths(self):
        self.assert_both_paths_reject(
            GovernanceElectorateModel, {"eligibility": {}}, "frozen electorate or choice schema"
        )

    def test_ballot_only_change_is_rejected_by_both_paths(self):
        self.assert_both_paths_reject(
            GovernanceBallotModel, {"choice": {"approved": "true"}}, "immutable choice schema"
        )

    def test_each_governance_input_table_triggers_reader(self):
        for model, column_name in (
            (GovernanceRoundModel, "state_version"),
            (GovernanceElectorateModel, "position"),
            (GovernanceBallotModel, "choice"),
            (MigrationRequestModel, "state_version"),
        ):
            table = model.__table__
            with self.subTest(table=table.name):
                self.write(version=3)
                try:
                    with self.store.session_factory() as session:
                        session.execute(text("BEGIN IMMEDIATE"))
                        self.store._validation.begin(session)
                        self.assertIsNotNone(self.store._validation._base)
                        session.execute(update(table).values({column_name: table.c[column_name]}))
                        self.assertEqual(self.store._validation.tracker.touched, {table.name})
                        with patch("ai_team_team.database.persistence.store.governance_reader.read_governance_state",
                                   wraps=read_governance_state) as governance, patch(
                                "ai_team_team.database.persistence.store.records.validate_database",
                                wraps=validate_database) as full:
                            self.store._validation.prepare(session)
                        self.assertEqual(governance.call_count, 1)
                        full.assert_not_called()
                        session.rollback()
                finally:
                    self.store._validation.finish()

    def test_unrelated_delta_does_not_repeat_governance_reader(self):
        with patch("ai_team_team.database.persistence.store.governance_reader.read_governance_state",
                   wraps=read_governance_state) as governance:
            self.write(version=3)
        governance.assert_not_called()

    def test_invalid_electorate_write_rolls_back_without_a_receipt(self):
        original = self.store._write_governance

        def mutate(session, *args):
            original(session, *args)
            session.execute(update(GovernanceElectorateModel).values(eligibility={}))

        with patch.object(self.store, "_write_governance", side_effect=mutate):
            with self.assertRaisesRegex(StateRestoreError, "frozen electorate or choice schema"):
                self.write(version=3)
        self.assertIsNone(self.store._validation._accepted)
        with self.store.session_factory() as session:
            self.assertEqual(session.execute(select(GovernanceElectorateModel.eligibility)).scalar_one(), {"frozen": True})
            self.assertIsNone(read_receipt(session, "operation-3"))
            validate_database(session)
