"""Personal tool batches share registered execution and cancellation semantics."""

import asyncio


class ForegroundToolMixin:
    async def execute_tool(self, session, name, args, kwargs, *, call_id, tools):
        return await self.manager._executions.execute(session, name, args, kwargs,
            call_id=call_id, tools=tools)

    async def execute_batch(self, executions):
        with self.manager._resources.execution() as authority:
            return await self._execute_batch(executions, authority)

    async def _execute_batch(self, executions, authority):
        tasks = [asyncio.create_task(execution) for execution in executions]
        try:
            pending = set(tasks)
            while pending:
                # FIRST_EXCEPTION does not wake for a cancelled child. A
                # cancelled tool must fence every sibling immediately, even
                # when another tool is still awaiting an external service.
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    if not task.cancelled() and task.exception() is not None:
                        raise task.exception()
                if any(task.cancelled() for task in done):
                    raise asyncio.CancelledError()
            return [task.result() for task in tasks]
        except BaseException:
            self.manager._resources.revoke(authority)
            owned_observers = [task for task in tasks if task in self.manager._executions.observers]
            for task in tasks:
                if not task.done():
                    task.cancel()
            # Local transactions settle themselves before raising cancellation;
            # arbitrary external waits are fenced, not awaited indefinitely.
            for task in tasks:
                self.tool_tasks.add(task)
                task.add_done_callback(self.tool_finished)
            if owned_observers:
                await asyncio.wait(owned_observers, timeout=self.manager.config.executions.cancellation_grace_seconds)
            await asyncio.sleep(0)
            raise

    def tool_finished(self, task):
        self.tool_tasks.discard(task)
        if not task.cancelled():
            task.exception()
