"""Predefined audit-only tools never inherit ordinary tools or library authority."""

from ai_team_team.core.activity.contracts import ToolExecutionContract
from ai_team_team.core.health import HealthFinding
from ai_team_team.core.exceptions import ToolBusinessError, ToolPermissionError
from ai_team_team.tool import Tool, render_tool_prompt
from ai_team_team.database.persistence.records import thaw

from ..activity.values import capture, identifier


class AuditToolMixin:
    def tools_for(self, session):
        profile = self.manager._activity.require_audit_profile(session.agent_id)

        def current():
            actor = self.manager._active_tool_agent.get()
            if (self.manager._activity.current.get() is not session or actor is None
                    or actor.agent_id != session.agent_id):
                raise ToolPermissionError("Audit tools require this exact scoped personal invocation.")
            self.manager._activity.check_generation(session)

        async def read_audit_evidence():
            """Read only the immutable evidence explicitly admitted for this assessment."""
            current()
            return {"audit_id": profile["audit_id"], "evidence": thaw(profile["template"]["evidence"]),
                    "subject": thaw(profile["template"]["subject"])}

        async def share_audit_finding(message: str):
            """Deliberately share a permitted health finding with the same temporary audit AT."""
            current()
            if not message.strip():
                raise ToolBusinessError("A shared finding cannot be empty.")
            async with self.lock:
                sequence = 1 + max((row.values["sequence"] for row in self.manager._records.snapshot()
                    if row.table_name == "audit_chat_evidence" and row.values["audit_id"] == profile["audit_id"]), default=0)
                row = capture(self.manager, "audit_chat_evidence", event_id=identifier("AUDIT-MESSAGE"),
                    audit_id=profile["audit_id"], scoped_agent_id=session.agent_id,
                    sequence=sequence, event_kind="send", findings={"message": message},
                    created_at=self.manager._activity.clock.wall_time())
                await self.manager._records.commit((row,), authority_check=current)
            return {"status": "PUBLISHED", "event_id": row.values["event_id"]}

        async def read_audit_conversation():
            """Explicitly inspect the restricted audit conversation, not an automatic transcript."""
            current()
            return [thaw(row.values) for row in self.manager._records.snapshot()
                    if row.table_name == "audit_chat_evidence" and row.values["audit_id"] == profile["audit_id"]]

        async def submit_health_finding(finding: HealthFinding):
            """Submit your own immutable structured finding; no other auditor may vote for you."""
            current()
            key = ("audit_findings", (profile["audit_id"], session.agent_id))
            async with self.lock:
                previous = self.manager._records.index.get(key)
                payload = finding.model_dump(mode="json")
                if previous is not None:
                    if any(thaw(previous.values[field]) != value for field, value in payload.items()):
                        raise ToolBusinessError("An accepted health finding cannot be rewritten.")
                    return {"status": "ALREADY_SUBMITTED"}
                allowed_refs = set(profile["template"]["evidence"].get("observation_ids", ()))
                if set(finding.evidence_references) - allowed_refs:
                    raise ToolPermissionError("A finding cannot claim evidence outside the admitted assessment.")
                row = capture(self.manager, "audit_findings", audit_id=profile["audit_id"],
                    scoped_agent_id=session.agent_id, **payload, created_at=self.manager._activity.clock.wall_time())
                try:
                    await self.manager._records.commit((row,), authority_check=current)
                finally:
                    if key in self.manager._records.index:
                        self.activity_changed(profile["audit_id"])
            return {"status": "SUBMITTED", "audit_id": profile["audit_id"]}

        contract = ToolExecutionContract(effects=("self_modification",), background_allowed=False,
            required_scope="agent_team", mutation_safety="managed_lease")
        return {name: Tool(name=name, func=func, execution_contract=contract,
                    resource_resolver=lambda scope, arguments: ()) for name, func in (
            ("read_audit_evidence", read_audit_evidence), ("share_audit_finding", share_audit_finding),
            ("read_audit_conversation", read_audit_conversation), ("submit_health_finding", submit_health_finding))}

    def instructions(self, session, tools, native):
        member = self.manager._agents_by_id[session.agent_id]
        parts = [f"You are fresh temporary auditor {member.name} ({member.agent_id}), role {member.role}.",
            "Assess health only, not business progress, quality, completion, membership, or permission policy. "
            "Use read_audit_evidence, deliberately share permitted findings if useful, and submit your own HealthFinding. "
            "Every predefined member must submit a valid finding before a strict majority can form a conclusion. "
            "A missing finding, failure, or tie is UNKNOWN. Ordinary answers are not findings. "
            "Do not infer health failure from silence, normal waiting, ordinary denials, non-English text, or special characters. "
            "You have no ordinary team, file, recruitment, communication, model-selection, or business-repair authority. "
            "After submitting, explicitly choose idle. The whole assessment has one immutable deadline."]
        if not native:
            parts.extend(["AVAILABLE TOOLS", "\n".join(render_tool_prompt(tool, "full") for tool in tools.values()),
                "Use Action: tool_name(<safe literal arguments>) or a supported XML action for tools."])
        return "\n\n".join(parts)
