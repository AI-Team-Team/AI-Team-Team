"""A real process interruption cannot authorize replay of its recorded operation."""

import asyncio
import subprocess
import sys
from pathlib import Path

from test.test_att.test_agent_activity._support import idle
from test.test_att.test_autonomous_activity_phase0._fixtures import ModelStep

from ._support import BackgroundTestCase


CHILD = r'''
import asyncio
import os
import sys
from pathlib import Path
from ai_team_team import Agent, ATTConfig, ATTManager, LLMResponse
from ai_team_team.core.activity.contracts import ToolExecutionContract

class Client:
    async def generate(self, prompt=None, system_instruction=None, **kwargs):
        raise AssertionError("The crash fixture never admits personal model activity.")

async def main():
    workspace = Path(sys.argv[1])
    client = Client()
    manager = ATTManager(Agent("CrashOwner", "Researcher", client),
        ATTConfig(workspace_root=str(workspace)), db_path=str(workspace / "state.sqlite"))
    manager.register_llm_client("fixture", client)

    async def operation():
        with open(workspace / "effects.log", "a", encoding="utf-8") as stream:
            stream.write("one actual dispatch\n")
            stream.flush()
            os.fsync(stream.fileno())
        os._exit(73)

    manager.register_tool("operation", func=operation, execution_contract=ToolExecutionContract(
        effects=("artifact_write",), background_allowed=True, required_scope="personal", mutation_safety="trusted_host"))
    await manager.start_background_task("operation", {}, actor=manager.root_ai)
    await asyncio.Event().wait()

asyncio.run(main())
'''


class ProcessInterruptionTests(BackgroundTestCase):
    async def test_crash_after_dispatch_preserves_uncertainty_and_does_not_replay(self):
        workspace = Path(self.workspace.name) / "child"
        workspace.mkdir()
        result = await asyncio.to_thread(subprocess.run, [sys.executable, "-c", CHILD, str(workspace)],
            capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 73, result.stderr.decode())
        counter = workspace / "effects.log"
        before = counter.read_text(encoding="utf-8")
        self.client.steps.append(ModelStep(idle()))
        await self.manager.load_state(str(workspace / "state.sqlite"))
        await self.settle()
        tasks = self.manager.list_background_tasks(actor=self.manager.root_ai)
        self.assertEqual(tasks.total_count, 1)
        self.assertEqual(tasks.items[0].execution_state, "running")
        self.assertTrue(tasks.items[0].outcome_unconfirmed)
        self.assertNotIn(tasks.items[0].execution_id, self.manager._executions.jobs)
        self.assertTrue(all(job.tool.name == "set_activity_intent"
            and job.context.generation == self.manager._resources.generation for job in self.manager._executions.jobs.values()))
        self.assertEqual(counter.read_text(encoding="utf-8"), before)
        self.assertEqual(before.splitlines(), ["one actual dispatch"])
