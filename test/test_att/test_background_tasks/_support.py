"""Background tests use explicit barriers instead of the real detachment delay."""

import asyncio
from unittest.mock import Mock

from ai_team_team.core.activity.contracts import ToolExecutionContract
from test.test_att.test_agent_activity._support import ActivityTestCase


def contract(**overrides):
    return ToolExecutionContract(**{
        "effects": ("read_only",), "background_allowed": True, "required_scope": "personal",
        **overrides,
    })


class BackgroundTestCase(ActivityTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        # Host-only service tests verify durable ingress independently of model
        # decisions. The real Text/Native cases exercise normal wake delivery.
        self.manager._activity.schedule_notice = Mock()
        self.manager.register_token_counter("fixture", lambda text: len(text))

    async def finish(self, handle):
        job = self.manager._executions.jobs[handle.execution_id]
        await asyncio.wait_for(job.finished.wait(), 10)
        await asyncio.sleep(0)
        if job.error is not None:
            raise job.error
        return job

    async def start(self, name, arguments=None, **kwargs):
        return await self.manager.start_background_task(name, arguments or {}, actor=self.root, **kwargs)
