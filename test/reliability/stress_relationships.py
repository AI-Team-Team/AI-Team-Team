"""Longer reproducible histories use the same public-relationship oracle."""

import os

from ai_team_team import Agent
from test.test_att.test_autonomous_activity_phase1._support import make_manager
from test.test_att.test_conversations._relationship_schedules import exercise_relationship_schedule
from test.test_att.test_conversations._support import ChatTestCase


class ExtendedRelationshipTests(ChatTestCase):
    async def test_seeded_relationship_histories_survive_repeated_restore(self):
        count = int(os.environ.get("ATT_STRESS_SEEDS", "8"))
        operations = int(os.environ.get("ATT_STRESS_OPERATIONS", "96"))
        if count <= 0 or operations <= 0:
            raise ValueError("Extended workloads require positive seed and operation counts.")
        for seed in range(count):
            with self.subTest(seed=seed):
                # Every seed has a separate relationship and database; the
                # initial state is part of the reproducible operation trace.
                if seed:
                    await self.manager.close()
                    self.manager, self.path, self.client = make_manager(self)
                    self.root = self.manager.root_ai
                    self.other = self.manager.register_agent(Agent("Other", "Researcher", self.client))
                    self.manager._activity.schedule_notice = lambda _notice_id: None
                await exercise_relationship_schedule(self, 20261029 + seed, operations, restore_every=16)
        self.acceptance_metrics = {"seeds": count, "schedule_steps": count * operations}
