"""Fresh processes recover uncertain dispatches and accepted terminal facts."""

import asyncio
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

from test.test_att.test_agent_activity._support import idle
from test.test_att.test_autonomous_activity_phase0._fixtures import ModelStep
from ._support import BackgroundTestCase


class ExecutionCrashBoundaryTests(BackgroundTestCase):
    async def test_process_exit_before_and_after_dispatch_and_result_commit_never_replays(self):
        root = Path(__file__).resolve().parents[3]
        phases = ("before_dispatch", "after_dispatch", "after_result_observation",
                  "before_result_commit", "after_result_commit")
        for phase in phases:
            with self.subTest(phase=phase):
                workspace = Path(self.workspace.name) / phase
                environment = {**os.environ, "PYTHONPATH": str(root / "src") + os.pathsep + str(root),
                               "PYTHONIOENCODING": "utf-8"}
                child = await asyncio.to_thread(subprocess.run,
                    [sys.executable, "-m", "test.reliability._execution_crash", str(workspace), phase],
                    cwd=root, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=60)
                self.assertEqual(child.returncode, 73, child.stderr)
                path = workspace / "state.sqlite"
                effects = workspace / "effects.log"
                expected = [] if phase == "before_dispatch" else ["dispatched"]
                self.assertEqual(effects.read_text(encoding="utf-8").splitlines() if effects.exists() else [], expected)
                with closing(sqlite3.connect(path)) as database:
                    status = database.execute("SELECT status FROM executions WHERE tool_name='operation'").fetchone()[0]
                self.assertEqual(status, "queued" if phase == "before_dispatch" else
                    "completed" if phase == "after_result_commit" else "running")
                if phase != "after_result_commit":
                    self.client.steps.append(ModelStep(idle()))
                calls_before = len(self.client.requests)
                await self.manager.load_state(str(path))
                await self.settle()
                owner = self.manager.root_ai
                page = self.manager.list_background_tasks(actor=owner)
                self.assertEqual(page.total_count, 1)
                task = page.items[0]
                if phase == "after_result_commit":
                    self.assertEqual(task.execution_state, "completed")
                    self.assertFalse(task.outcome_unconfirmed)
                    result = await self.manager.read_background_task_result(task.execution_id, actor=owner)
                    self.assertIn("Committed synthetic result", result.content)
                else:
                    self.assertTrue(task.outcome_unconfirmed)
                self.assertNotIn(task.execution_id, self.manager._executions.jobs)
                await self.manager.save_state()
                calls_after_recovery = len(self.client.requests)
                await self.manager.load_state(str(path))
                await self.settle()
                self.assertEqual(effects.read_text(encoding="utf-8").splitlines() if effects.exists() else [], expected)
                self.assertEqual(len(self.client.requests), calls_after_recovery)
                self.assertEqual(self.client.unexpected_requests, 0)
                if phase == "after_result_commit":
                    self.assertEqual(calls_after_recovery, calls_before)
