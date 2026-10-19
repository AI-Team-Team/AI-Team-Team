"""The implemented incompatible schema belongs to ordinary Phase 1 discovery."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from ai_team_team import ATTConfig, ATTManager, Agent
from ai_team_team.core.activity.contracts import TARGET_STATE_SCHEMA_VERSION
from ai_team_team.database.persistence.constants import STATE_SCHEMA_VERSION

from test.test_att.test_autonomous_activity_phase0._fixtures import ScriptedModelClient
from test.test_att.test_autonomous_activity_phase0._fixtures.schema import physical_schema


REQUIRED_TABLES = {
    "agent_activities",
    "activity_admissions",
    "activity_invocations",
    "notification_frames",
    "model_requests",
    "memory_index_requests",
    "model_token_claims",
    "agent_notifications",
    "notification_claims",
    "chat_reminder_previews",
    "notification_suppression",
    "sleep_plans",
    "sleep_conditions",
    "direct_relationships",
    "friendship_requests",
    "chat_operations",
    "chat_preferences",
    "chat_streams",
    "chat_events",
    "membership_intervals",
    "chat_messages",
    "chat_revisions",
    "chat_withdrawals",
    "chat_message_projections",
    "chat_personal_views",
    "executions",
    "execution_attempts",
    "execution_payloads",
    "execution_observations",
    "execution_controls",
    "tool_cooldowns",
    "model_availability",
    "team_position_cooldowns",
    "governance_cases",
    "governance_electorates",
    "governance_ballots",
    "team_topology_events",
    "parent_acceptances",
    "health_incidents",
    "audit_runs",
    "audit_participants",
    "audit_model_requests",
    "audit_execution_evidence",
    "audit_chat_evidence",
    "audit_evidence",
    "recovery_incidents",
    "publication_manifests",
}


class TestSchemaActivation(unittest.IsolatedAsyncioTestCase):
    async def test_physical_schema_matches_the_frozen_target(self):
        self.assertEqual(
            STATE_SCHEMA_VERSION,
            TARGET_STATE_SCHEMA_VERSION,
            "Runtime and physical checkpoint contracts must use the same schema.",
        )
        workspace = tempfile.TemporaryDirectory(prefix="att-phase0-schema-")
        self.addCleanup(workspace.cleanup)
        database_path = Path(workspace.name).resolve() / "state.sqlite"
        client = ScriptedModelClient()
        manager = ATTManager(
            Agent("Root", "Architect", client),
            ATTConfig(workspace_root=workspace.name),
            db_path=str(database_path),
            persistence_mode=("durable" if (str(database_path)) else "volatile"),
        )
        self.addAsyncCleanup(manager.close)
        manager.register_llm_client("fixture", client)
        await manager.save_state()
        tables, version, columns, foreign_key_errors = await asyncio.to_thread(
            physical_schema, database_path
        )
        self.assertEqual(version, (TARGET_STATE_SCHEMA_VERSION,))
        self.assertEqual(REQUIRED_TABLES - tables, set(), "Current activity tables are missing.")
        self.assertNotIn("governance_rounds", tables)
        self.assertNotIn("communication_ballots", tables)
        self.assertNotIn("discussion_id", columns)
        self.assertIn("invocation_id", columns)
        self.assertEqual(foreign_key_errors, [])
        self.assertEqual(client.requests, [])
