"""Owned communication fixtures and bounded, commit-aware test waits."""

import asyncio
import json
import os
import shutil
import tempfile
import unittest

from ai_team_team import ATTConfig, ATTManager, Agent, PermissiveCommunicationConfig
from test.governance_client import PersonalGovernanceClient


class _ObservedTaskRegistry(dict):
    """Retains every assigned Task after the scheduler removes or replaces its key."""

    def __init__(self, live_tasks):
        super().__init__()
        self.history = []
        for key, task in live_tasks.items():
            self[key] = task

    def __setitem__(self, key, task):
        super().__setitem__(key, task)
        self.history.append((key, task))


class _ObservedTaskSet(set):
    """Retain actual personal workers even after production removes them."""

    def __init__(self, tasks):
        super().__init__()
        self.history = []
        for task in tasks:
            self.add(task)

    def add(self, task):
        super().add(task)
        self.history.append(task)


class CommunicationTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._managers = []
        self.old_cwd = os.getcwd()
        self.workspace = tempfile.mkdtemp(prefix="att-communication-")
        self.addAsyncCleanup(self._cleanup_workspace)
        os.chdir(self.workspace)
        self.client = PersonalGovernanceClient()
        self.root = Agent("Root", "Root governor", self.client)

    async def _cleanup_workspace(self):
        errors = []
        for manager in reversed(self._managers):
            try:
                await manager.close()
            except BaseException as error:
                errors.append(error)
        os.chdir(self.old_cwd)
        if errors:
            # A failed close may still own resources in this directory.
            raise BaseExceptionGroup(
                f"Communication fixture cleanup failed; workspace retained at {self.workspace}.",
                errors,
            )
        shutil.rmtree(self.workspace)

    def manager(self, communication=None, db_path=None, *, root_ai=None):
        manager = ATTManager(
            self.root if root_ai is None else root_ai,
            ATTConfig(
                communication=communication or PermissiveCommunicationConfig(),
                workspace_root=self.workspace,
            ),
            db_path,
            persistence_mode="durable" if db_path else "volatile",
        )
        self._managers.append(manager)
        # Observe registration, not a later poll that can miss completed failures.
        manager.broker._approval_tasks = _ObservedTaskRegistry(manager.broker._approval_tasks)
        manager._governance.tasks = _ObservedTaskRegistry(manager._governance.tasks)
        manager._activity.workers = _ObservedTaskSet(manager._activity.workers)
        manager.register_llm_client("default", self.client)
        return manager

    def _request_manager(self, request_id):
        for manager in reversed(self._managers):
            if not manager._closed and request_id in manager.broker.communication_requests:
                return manager
        self.fail(f"No active communication fixture owns request {request_id}.")

    def _request_tasks(self, manager, request_id):
        round_ids = {
            item.round_id
            for item in manager._governance.rounds.values()
            if item.business_kind == "communication" and item.business_id == request_id
        }
        tasks = {}
        for registry in (manager.broker._approval_tasks, manager._governance.tasks):
            for generation, (key, task) in enumerate(registry.history, start=1):
                if key.startswith(f"{request_id}:") or any(
                    key == f"resolve:{round_id}" or key.startswith(f"mail:{round_id}:")
                    for round_id in round_ids
                ):
                    tasks[f"{key}#{generation}"] = task
        voters = {owner for item in manager._governance.rounds.values() if item.round_id in round_ids
                  for owner in item.voter_agent_ids}
        for generation, task in enumerate(manager._activity.workers.history, start=1):
            if task.get_name() in {f"att-person-{owner}" for owner in voters}:
                tasks[f"{task.get_name()}#{generation}"] = task
        return tasks

    @staticmethod
    def _raise_completed_task_errors(tasks):
        for task in tasks.values():
            if task.done():
                # Inspect Task outcome, not a possibly exception-valued return value.
                task.result()

    def _request_diagnostics(self, manager, request_id, expected):
        request = manager.broker.communication_requests.get(request_id)
        tasks = []
        for key, task in sorted(self._request_tasks(manager, request_id).items()):
            frames = task.get_stack(limit=1)
            error = task.exception() if task.done() and not task.cancelled() else None
            tasks.append(
                {
                    "key": key,
                    "state": "cancelled"
                    if task.cancelled()
                    else "failed"
                    if error is not None
                    else "done"
                    if task.done()
                    else "running",
                    "error_type": type(error).__name__ if error is not None else None,
                    "location": (
                        {
                            "file": os.path.basename(frames[0].f_code.co_filename),
                            "function": frames[0].f_code.co_name,
                            "line": frames[0].f_lineno,
                        }
                        if frames
                        else None
                    ),
                }
            )
        # Deliberately exclude rationale, message bodies, prompts, and tool arguments.
        return json.dumps(
            {
                "request_id": request_id,
                "expected": expected,
                "status": request.status.value if request is not None else "MISSING",
                "transaction_busy": manager.broker._transaction_lock.locked(),
                "approvals": [
                    {"principal": item.principal.key, "status": item.status.value}
                    for item in manager.broker.approvals_for_request(request_id)
                ],
                "rounds": [
                    {
                        "round_id": item.round_id,
                        "status": item.status,
                        "votes": len(item.ballots),
                        "voters": len(item.voter_agent_ids),
                    }
                    for item in manager._governance.rounds.values()
                    if item.business_kind == "communication" and item.business_id == request_id
                ],
                "tasks": tasks,
            },
            sort_keys=True,
        )

    async def wait_for_status(self, request, expected, timeout=60.0):
        """Observe current registry state, not an object replaced by rollback."""
        manager = self._request_manager(request.request_id)
        deadline = asyncio.timeout(timeout)
        try:
            async with deadline:
                while True:
                    self._raise_completed_task_errors(
                        self._request_tasks(manager, request.request_id)
                    )
                    current = manager.broker.communication_requests[request.request_id]
                    # Status is staged before the authoritative commit is awaited.
                    if not manager.broker._transaction_lock.locked():
                        if current.status.value == expected:
                            return current
                        if current.status.value in {"APPROVED", "DENIED", "STALE"}:
                            self.fail(
                                "Unexpected terminal communication status: "
                                + self._request_diagnostics(manager, request.request_id, expected)
                            )
                    await asyncio.sleep(0.01)
        except TimeoutError:
            if not deadline.expired():
                raise
            self.fail(
                f"Communication status did not settle within {timeout:g}s: "
                + self._request_diagnostics(manager, request.request_id, expected)
            )

    async def wait_for_governance_idle(self, request, timeout=60.0):
        """Wait for a negative decision's real mail interactions to finish."""
        manager = self._request_manager(request.request_id)
        deadline = asyncio.timeout(timeout)
        try:
            async with deadline:
                while True:
                    tracked = self._request_tasks(manager, request.request_id)
                    self._raise_completed_task_errors(tracked)
                    tasks = tuple(task for task in tracked.values() if not task.done())
                    if tasks:
                        # Notice a failed worker even while a sibling remains blocked.
                        # Cancelling this observer does not cancel the worker Tasks.
                        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                        self._raise_completed_task_errors(tracked)
                    elif not manager.broker._transaction_lock.locked():
                        # Mail ingress can be accepted before the ready scheduler
                        # has registered its worker; neither gap is idle.
                        if not manager._activity.dispatch_tasks and manager._activity.ready.empty():
                            return
                    await asyncio.sleep(0.01)
        except TimeoutError:
            if not deadline.expired():
                raise
            self.fail(
                f"Communication workers did not settle within {timeout:g}s: "
                + self._request_diagnostics(manager, request.request_id, "IDLE")
            )
