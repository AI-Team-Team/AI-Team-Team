"""A parent remedy is an independent bounded case, never a nested discussion."""

import asyncio
from pathlib import Path
from unittest.mock import patch

from ai_team_team import Agent, TokenLimitExceededError
from test.governance_client import PersonalGovernanceClient, settle_governance_activity
from test.test_att.test_agent_activity._support import ActivityTestCase, idle
from test.test_att.test_autonomous_activity_phase0._fixtures import ModelStep, ScriptedModelClient


class TestATTFailover(ActivityTestCase):
    def exhausted(self):
        error = TokenLimitExceededError("The configured model quota is exhausted.")
        error.required_tokens = 1
        return error

    def setup_models(self, *, respond=True):
        governor = PersonalGovernanceClient(native=True, model_alias="replacement", respond=respond)
        limited = ScriptedModelClient()
        replacement = ScriptedModelClient(*(ModelStep(idle()) for _ in range(8)))
        self.root.llm_client = governor
        self.manager.llm_clients.pop("fixture")
        self.manager.register_llm_client("governor", governor)
        self.manager.register_llm_client("limited", limited)
        self.manager.register_llm_client("replacement", replacement)
        self.manager.config.model_token_limits["limited"] = 0
        self.manager.config.failover_policy = "parent"
        return limited, replacement

    def child(self, parent=None):
        return self.manager.create_agent_team(self.root, parent=parent,
            member_configs={name: {"model": "limited"} for name in ("A", "B", "C")})

    async def test_disabled_remedy_leaves_the_person_and_quota_unchanged(self):
        limited, _ = self.setup_models()
        self.manager.config.failover_policy = "none"
        team = self.child(self.root)
        person = team.members[0]
        result = await self.manager.request_model_resource(person, team, self.exhausted())
        self.assertEqual(result.status, "UNAVAILABLE")
        self.assertIs(person.llm_client, limited)
        self.assertFalse(self.records("resource_decisions"))

    async def test_auto_is_an_independent_policy_using_the_same_atomic_ledger(self):
        limited, replacement = self.setup_models()
        self.manager.config.failover_policy = "auto"
        self.manager.config.model_token_limits["governor"] = 0
        team = self.child()
        person = team.members[0]
        result = await self.manager.request_model_resource(person, team, self.exhausted())
        self.assertEqual(result.status, "APPLIED")
        self.assertIs(person.llm_client, replacement)
        self.assertFalse(self.manager._governance.cases)
        self.assertFalse(self.records("resource_decisions"))

    async def test_parent_team_requires_every_explicit_ballot_before_alias_application(self):
        _, replacement = self.setup_models()
        parent = self.manager.create_agent_team(self.root)
        child = self.child(parent)
        person = child.members[0]
        before = person.agent_id, person.private_doc_library_id
        result = await self.manager.request_model_resource(person, child, self.exhausted())
        self.assertEqual(result.status, "PENDING")
        await settle_governance_activity(self.manager)
        row = self.manager._records.index[("resource_decisions", (result.attempt_id,))]
        self.assertEqual(row.values["status"], "applied")
        self.assertIs(person.llm_client, replacement)
        self.assertEqual((person.agent_id, person.private_doc_library_id), before)
        case = self.manager._governance.cases[row.values["decision_case_id"]]
        self.assertEqual(case.principal.kind, "agent_team")
        self.assertEqual(len(case.ballots), 3)
        self.assertFalse(any(key.startswith("deadline:") and not task.done() for key, task in self.manager._failover.tasks.items()))

    async def test_explicit_root_agent_votes_as_itself_not_as_a_team_replacement(self):
        self.setup_models()
        child = self.child(self.root)
        result = await self.manager.request_model_resource(child.members[0], child, self.exhausted())
        await settle_governance_activity(self.manager)
        row = self.manager._records.index[("resource_decisions", (result.attempt_id,))]
        case = self.manager._governance.cases[row.values["decision_case_id"]]
        self.assertEqual((case.principal.kind, case.principal.principal_id), ("agent", self.root.agent_id))
        self.assertEqual(case.voter_agent_ids, [self.root.agent_id])
        self.assertEqual(row.values["status"], "applied")

    async def test_no_parent_and_self_parent_fail_closed_without_an_automatic_fallback(self):
        self.setup_models()
        child = self.child()
        person = child.members[0]
        result = await self.manager.request_model_resource(person, child, self.exhausted())
        self.assertEqual(result.status, "UNAVAILABLE")
        shared_parent = self.manager.bootstrap_agent_team(self.root,
            existing_members=[person], member_configs={"Helper1": {}, "Helper2": {}})
        target = self.manager.bootstrap_agent_team(self.root, parent=shared_parent,
            existing_members=[person], member_configs={"Helper3": {}, "Helper4": {}})
        result = await self.manager.request_model_resource(person, target, self.exhausted())
        self.assertEqual(result.status, "UNAVAILABLE")
        self.assertFalse(self.records("resource_decisions"))

    async def test_returning_pending_does_not_expire_the_attempt_but_its_own_deadline_does(self):
        self.manager.register_runtime_clock(self.clock)
        self.setup_models(respond=False)
        child = self.child(self.root)
        result = await self.manager.request_model_resource(child.members[0], child, self.exhausted())
        async with asyncio.timeout(5):
            while not any(case.business_id == result.attempt_id for case in self.manager._governance.cases.values()):
                await asyncio.sleep(0)
        self.assertEqual(self.records("resource_decisions")[0].values["status"], "pending")
        self.clock.advance(120)
        await settle_governance_activity(self.manager)
        row = self.records("resource_decisions")[0]
        self.assertEqual(row.values["status"], "expired")
        case = self.manager._governance.cases[row.values["decision_case_id"]]
        self.assertEqual(case.status, "EXPIRED")

    async def test_restore_interrupts_an_old_attempt_without_replaying_ballots_or_provider_calls(self):
        self.setup_models(respond=False)
        child = self.child(self.root)
        result = await self.manager.request_model_resource(child.members[0], child, self.exhausted())
        async with asyncio.timeout(5):
            while not any(case.business_id == result.attempt_id for case in self.manager._governance.cases.values()):
                await asyncio.sleep(0)
        await self.settle()
        path = str(Path(self.workspace.name) / "resource.sqlite")
        await self.manager.save_state(path)
        calls = len(self.root.llm_client.calls)
        await self.manager.load_state(path)
        await self.settle()
        row = self.records("resource_decisions")[0]
        self.assertEqual(row.values["status"], "interrupted")
        self.assertEqual(len(self.root.llm_client.calls), calls)
        self.assertTrue(all(item.status == "EXPIRED" for item in self.manager._governance.cases.values()))

    async def test_deadline_is_independent_of_delayed_case_preparation(self):
        self.manager.register_runtime_clock(self.clock)
        self.setup_models(respond=False)
        child = self.child(self.root)
        entered = asyncio.Event()

        async def blocked(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()

        with patch.object(self.manager.broker.decision_provider, "request_model_choice", blocked):
            result = await self.manager.request_model_resource(child.members[0], child, self.exhausted())
            await entered.wait()
            self.clock.advance(120)
            await settle_governance_activity(self.manager)
        row = self.manager._records.index[("resource_decisions", (result.attempt_id,))]
        self.assertEqual(row.values["status"], "expired")
        self.assertFalse(self.manager._governance.cases)
