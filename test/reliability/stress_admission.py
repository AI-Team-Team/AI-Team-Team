"""Many admitted people and shared memberships retain personal serial ownership."""

import asyncio
import os
import random
from unittest.mock import patch

from ai_team_team import ATTConfig, Agent, LLMResponse
from test.async_waits import wait_for_runtime
from test.test_att.test_agent_activity._support import ActivityTestCase, idle
from test.test_att.test_runtime_contracts._fixtures import AsyncBarrier, ModelStep, ScriptedModelClient


class AdmissionPressureTests(ActivityTestCase):
    async def test_many_sources_coalesce_without_cloning_people_or_starving_other_owners(self):
        await self.manager.close()
        self.manager = self.make_manager(self.root, config=ATTConfig(
            workspace_root=self.workspace.name, tool_calling_mode="native",
            activity={"model_requests_per_invocation": 1, "max_concurrent_activities": 3,
                      "max_concurrent_model_requests": 2},
        ))
        count = min(16, int(os.environ.get("ATT_STRESS_OPERATIONS", "96")))
        if count <= 0:
            raise ValueError("Admission pressure requires a positive population.")
        gate = AsyncBarrier()
        people, clients = [], []
        for index in range(count):
            client = ScriptedModelClient(ModelStep(LLMResponse(text="Private continuing work"), gate),
                ModelStep(LLMResponse(text="Another personal observation")), ModelStep(idle()))
            self.manager.register_llm_client(f"person-{index}", client)
            person = self.manager.register_agent(Agent(f"Person-{index}", "Researcher", client))
            people.append(person)
            clients.append(client)
        shared = people[0]
        owned_fields = (shared.agent_id, shared.role, shared.llm_client, shared.private_doc_library_id)
        with patch.object(self.manager._activity, "schedule_notice"):
            for number in range(8):
                self.manager.bootstrap_agent_team(self.root, existing_members=[shared],
                    member_configs={f"Peer-{number}-A": {"model": "fixture"}, f"Peer-{number}-B": {"model": "fixture"}})
            await self.manager.flush_callbacks()
        sources = [person for person in people for _ in range(3)]
        random.Random(31013).shuffle(sources)
        try:
            admissions = await asyncio.gather(*(self.manager.activate_agent(person.agent_id) for person in sources))
            by_owner = {person.agent_id: [] for person in people}
            for admission in admissions:
                by_owner[admission.agent_id].append(admission)
            for owner, owned in by_owner.items():
                self.assertEqual(len({item.admission_id for item in owned}), 1, owner)
                self.assertEqual(sorted(item.status for item in owned), ["COALESCED", "COALESCED", "QUEUED"])
        finally:
            gate.release()
        await wait_for_runtime(self.manager, asyncio.gather(*(
            self.manager.wait_for_activity_checkpoint(owned[0].admission_id, intent="idle")
            for owned in by_owner.values())), label="All eligible people reach their explicit idle boundary")
        await self.settle()
        self.assertEqual((shared.agent_id, shared.role, shared.llm_client, shared.private_doc_library_id), owned_fields)
        self.assertEqual(sum(shared in team.members for team in self.manager.teams.values()), 8)
        self.assertTrue(all(client.maximum_in_flight == 1 for client in clients))
        self.assertTrue(all(len(client.requests) == 3 and client.unexpected_requests == 0 for client in clients))
        self.assertFalse(self.records("chat_messages"))
        self.assertFalse(self.manager._activity.workers)
        self.acceptance_metrics = {"owners": count, "shared_memberships": 8,
                                   "source_admissions": len(admissions), "provider_requests": sum(len(client.requests) for client in clients)}
