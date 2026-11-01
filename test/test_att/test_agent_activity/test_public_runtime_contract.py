"""Retired orchestration cannot remain as an accidental public execution path."""

import unittest

import ai_team_team
from ai_team_team import ATTConfig, ATTManager, AgentTeam
from ai_team_team.core.activity.contracts import ActivityCheckpoint, ActivityView
from ai_team_team.database.models import ACTIVITY_TABLES


class PublicRuntimeContractTests(unittest.TestCase):
    def test_round_execution_exports_methods_and_configuration_are_absent(self):
        for name in ("AgentTurnResult", "AgentTurnStatus", "DiscussionResult", "DiscussionStatus", "DiscussionRoundResult", "TurnFailurePolicyConfig"):
            self.assertFalse(hasattr(ai_team_team, name), name)
        for owner, methods in ((ATTManager, ("execute_team_discussion", "execute_team_discussion_detailed")),
                               (AgentTeam, ("execute_reasoning_step", "execute_reasoning_step_detailed"))):
            for name in methods:
                self.assertFalse(hasattr(owner, name), name)
        for name in ("subagent_discussion_rounds", "emergency_discussion_rounds", "max_tool_rounds",
                     "react_max_steps", "turn_failure_policy", "max_memory_turns", "max_migrations_per_team_discussion"):
            self.assertNotIn(name, ATTConfig.model_fields)
            with self.assertRaises(ValueError):
                ATTConfig(**{name: 1})

    def test_public_activity_and_relational_metadata_have_no_round_provenance(self):
        forbidden = {"round_number", "discussion_id", "turn_id", "round_id"}
        for model in (ActivityView, ActivityCheckpoint, ai_team_team.InteractionResult):
            self.assertFalse(forbidden.intersection(model.model_fields), model.__name__)
        for name, table in ACTIVITY_TABLES.items():
            self.assertFalse(forbidden.intersection(table.c.keys()), name)
