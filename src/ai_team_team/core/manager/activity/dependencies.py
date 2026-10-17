"""Synchronous observation keeps dependency safety without hoarding a worker slot."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from ai_team_team.core.exceptions import ATTException


@dataclass
class WorkerResume:
    worker: Any
    session: Any
    future: Any
    waits: int = 0
    queued: bool = False


class InteractionDependencyMixin:
    @asynccontextmanager
    async def interaction_dependency(self, agent_id):
        # Reserve before source acceptance. Detached admissions intentionally
        # have neutral contexts, but the synchronous observer still owns edges.
        async with self.manager._lifecycle.reserve_synchronous_dependencies((agent_id,)):
            session = self.current.get()
            worker = getattr(session, "worker", None)
            resume = None
            if (
                worker in self.workers
                and session.running
                and self.sessions.get(session.agent_id) is session
                and self.manager._lifecycle.live_invocation_chain()
            ):
                resume = self.suspended_workers.get(worker)
                if resume is None:
                    resume = WorkerResume(
                        worker, session, asyncio.get_running_loop().create_future()
                    )
                    self.suspended_workers[worker] = resume
                resume.waits += 1
                self.capacity.set()
            aborting = False
            try:
                yield
            except (asyncio.CancelledError, ATTException):
                aborting = True
                raise
            finally:
                if resume is not None:
                    resume.waits -= 1
                    if (
                        aborting
                        or self.closing
                        or not session.active
                        or worker.done()
                        or worker.cancelling()
                        or asyncio.current_task().cancelling()
                    ):
                        # A cancelled tool must finish unwinding without
                        # waiting for the downstream owner's provider or slot.
                        resume.future.cancel()
                    elif resume.waits == 0 and not resume.future.done():
                        if not resume.queued:
                            resume.queued = True
                            self.ready.put_nowait(resume)
                            self.capacity.set()
                    if not resume.future.cancelled():
                        # Resume via the same FIFO capacity gate as new people.
                        # One cancelled observer cannot cancel a sibling's slot.
                        await asyncio.shield(resume.future)

    def resume_worker(self, resume):
        resume.queued = False
        if (
            resume.worker not in self.workers
            or resume.worker.done()
            or resume.future.done()
            or not resume.session.active
        ):
            return
        if resume.waits == 0:
            self.suspended_workers.pop(resume.worker, None)
            resume.future.set_result(None)
