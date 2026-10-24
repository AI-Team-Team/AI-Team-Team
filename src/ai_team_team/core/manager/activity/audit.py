"""Restricted audit persistence profile over the same scheduler and runner."""

import asyncio

from ai_team_team.core.activity.contracts import AgentTeamScope
from ai_team_team.core.exceptions import ToolPermissionError
from ai_team_team.database.persistence.records import thaw

from .values import Session, capture, identifier


class AuditActivityMixin:
    def require_audit_profile(self, agent_id):
        profile = self.manager.supervisor.profiles.get(agent_id)
        team = self.manager.teams.get(profile["temporary_team_id"]) if profile else None
        if (profile is None or team is None or team.team_kind != "supervisory"
                or profile["runtime_generation"] != self.generation
                or not any(agent.agent_id == agent_id for agent in team.members)):
            raise ToolPermissionError("A temporary identity requires its exact registered audit profile.")
        return profile

    async def admit_auditor(self, agent_id, profile):
        """Trusted internal admission cannot be selected by a public activity API."""
        if self.manager._active_tool_agent.get() is not None:
            raise ToolPermissionError("Model tools cannot provision an audit activity profile.")
        async with self.lock:
            self.check_open()
            if self.require_audit_profile(agent_id) is not profile:
                raise ToolPermissionError("The registered audit profile changed before admission.")
            if profile["deadline"] <= self.clock.wall_time():
                raise TimeoutError("The audit admission deadline elapsed.")
            session = Session(agent_id, identifier("AUDIT-ADMISSION"), self.generation,
                scope=AgentTeamScope(team_id=profile["temporary_team_id"]), audit_profile=profile,
                audit_finished=asyncio.Event())
            self.sessions[agent_id] = session
            self.enqueue(session)
            return session

    async def audit_checkpoint(self, session, *, end_invocation=False, interrupted=False, extra=()):
        profile = self.require_audit_profile(session.agent_id)
        records = (*extra, capture(self.manager, "audit_activity_checkpoints",
            checkpoint_id=identifier("AUDIT-CHECKPOINT"), audit_id=profile["audit_id"],
            scoped_agent_id=session.agent_id, invocation_id=session.invocation_id or identifier("AUDIT-BOUNDARY"),
            context_version=session.context_version,
            working_context=[{key: thaw(value) for key, value in message.items()
                             if key in {"role", "content", "name", "tool_call_id", "tool_calls"}}
                             for message in self.manager._agents_by_id[session.agent_id].messages],
            intent=session.intent, interrupted=int(interrupted), created_at=self.clock.wall_time()))
        with self.manager._resources.settlement():
            await self.manager._records.commit(records, allow_closing=True)
        if end_invocation:
            session.invocation_id = None

    async def prepare_audit_frame(self, session):
        self.check_generation(session)
        session.context_version += 1
        session.frame_id = identifier("AUDIT-FRAME")
        self.append(session, {"role": "user", "content":
            "Continue this bounded health assessment using only its permitted evidence. "
            "Share findings deliberately in the restricted audit conversation and submit your own structured finding. "
            "Ordinary answers do not submit findings; you may explicitly choose idle if unable to assess."})
        await self.audit_checkpoint(session)

    async def finish_audit_invocation(self, session):
        if session.pending_intent is not None:
            if session.pending_intent.kind != "idle":
                raise ToolPermissionError("A bounded audit cannot sleep or change its scope.")
            session.intent, session.active = "idle", False
        session.pending_intent = None
        session.pending_scope = None
        await self.audit_checkpoint(session, end_invocation=True)
        if not session.active:
            session.audit_finished.set()
        self.manager.supervisor.activity_changed(session.audit_profile["audit_id"])

    async def interrupt_audit(self, session, error):
        session.failure, session.active, session.intent = error, False, "idle"
        session.availability = "closing" if self.closing else "unavailable"
        await self.audit_checkpoint(session, end_invocation=True, interrupted=True)
        session.audit_finished.set()
        self.manager.supervisor.activity_changed(session.audit_profile["audit_id"])

    async def stop_auditors(self, audit_id):
        sessions = [session for session in self.sessions.values()
                    if session.audit_profile and session.audit_profile["audit_id"] == audit_id]
        workers = []
        for session in sessions:
            session.active = False
            worker = getattr(session, "worker", None)
            if worker is not None and not worker.done():
                worker.cancel()
                workers.append(worker)
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)
        for session in sessions:
            self.sessions.pop(session.agent_id, None)
