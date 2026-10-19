"""Real managers with isolated workspaces and explicitly held arrival dispatch."""

import unittest

from ai_team_team import Agent
from test.test_att.test_autonomous_activity_phase1._support import make_manager


class ChatTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager, self.path, self.client = make_manager(self)
        self.root = self.manager.root_ai
        self.other = self.manager.register_agent(Agent("Other", "Researcher", self.client))
        # Component tests inspect committed arrival evidence without dispatching
        # a model. Separate end-to-end tests use the real personal scheduler.
        self.manager._activity.schedule_notice = lambda _notice_id: None

    def team(self):
        return self.manager.bootstrap_agent_team(self.root, existing_members=[self.root, self.other],
            member_configs={f"Member-{index}": {"model": "fixture"} for index in range(2)})

    def records(self, table):
        return [row for row in self.manager._records.snapshot() if row.table_name == table]
