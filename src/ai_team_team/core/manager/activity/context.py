"""One personal window and fresh, explicitly scoped provider instructions."""

import json

from ai_team_team.core.strategies.shared import (
    _append_agent_message,
    _append_private_window_message,
    _append_transient_window_message,
    _memory_recall_placeholder,
    _MEMORY_WINDOW_MARKER,
    _PRIVATE_TOOL_NAMES,
    _MEMORY_RECALL_TOOL_NAMES,
    _record_tool_result,
)
from ai_team_team.tool import render_tool_prompt


class ContextMixin:
    def bound_window(self, session):
        """Keep complete recent exchanges; the person's Journal remains intact."""
        config = self.manager.config
        agent = self.require_agent(session.agent_id)
        limit = config.max_memory_turns
        if not config.enable_memory_compression or len(agent.messages) <= limit + 2:
            return
        cut = len(agent.messages) - limit
        while cut > 1 and agent.messages[cut].get("role") in {"tool", "function"}:
            cut -= 1
        if cut <= 2:
            return
        # This is a derived reference summary, not another model request or a
        # new Journal fact. No private or metadata-only observation is copied.
        history = agent.messages[1:cut]
        references = list(
            dict.fromkeys(
                message.get("invocation_id") for message in history if message.get("invocation_id")
            )
        )
        archive = {
            "role": "system",
            "content": "Earlier personal Working Context was compacted; the complete personal history and Journal were retained. "
            "This is not a new event or a loss of identity. Deliberately consult retained artifacts or available memory tools when needed. "
            f"Recent archived invocation references: {', '.join(references[-8:]) or 'legacy context'}.",
        }
        self.append(session, archive, capture_content=False)
        derived = agent.messages.pop()
        agent.messages = [agent.messages[0], derived, *agent.messages[cut:]]

    def window_for_snapshot(self, agent):
        """Persist only complete Native exchanges; issued facts remain in Journal."""
        messages = agent.messages
        pending = set()
        batch_start = None
        for index, message in enumerate(messages):
            if message.get("tool_calls"):
                if pending:
                    raise RuntimeError("A personal window contains overlapping Native batches.")
                batch_start = index
                pending = {call["id"] for call in message["tool_calls"]}
            elif message.get("role") == "tool":
                pending.discard(message.get("tool_call_id"))
                if not pending:
                    batch_start = None
        return messages[:batch_start] if pending and batch_start is not None else messages

    def append(self, session, message, *, capture_content=True):
        agent = self.require_agent(session.agent_id)
        _append_agent_message(
            agent, message, self.team_for(session), self.manager, capture_content=capture_content
        )

    def instructions(self, session, tools, native):
        agent = self.require_agent(session.agent_id)
        team = self.team_for(session)
        parts = [
            agent.system_instructions,
            f"You are {agent.name} ({agent.agent_id}), role: {agent.role}. {agent.role_description}",
            (
                f"Current AgentTeam: {team.team_id}. Purpose: {team.team_purpose}.\n{team.system_instructions}"
                if team
                else "Current scope: personal; no AgentTeam authority."
            ),
            "You are one continuing person with the same personal memory across all memberships. "
            "Activity continues by default. Ordinary answers and silence are personal, not public messages or completion. "
            "Use set_activity_intent for deliberate idle or finite sleep. Use set_operation_scope to request a different "
            "authorized scope after the current complete tool batch. Receiving or reading mail never casts a ballot.",
            "Team chat, personal direct chat, and personal mail are distinct. Use send_team_message or send_direct_message "
            "only for deliberate publication. Chat previews never mark a source read. Historical team inspection grants "
            "no current team, tool, or file authority. Friendship grants no team or file access.",
        ]
        if self.manager.config.episodic_memory.enabled:
            parts.append(self.manager._memory.retained_context(agent.agent_id))
        if not native:
            parts.append(
                "AVAILABLE TOOLS\n"
                + "\n".join(
                    render_tool_prompt(
                        tool,
                        self.manager.config.tool_prompt_modes.get(name)
                        or tool.prompt_schema_mode
                        or self.manager.config.text_tool_schema_mode,
                    )
                    for name, tool in tools.items()
                )
            )
            parts.append(
                "Use exactly one Action: tool_name(<safe literal arguments>) or an XML action when calling a tool. "
                "An ordinary answer, including Final Answer, does not end continuing activity; use the idle control deliberately."
            )
        return "\n\n".join(part for part in parts if part)

    def append_observation(self, session, result, tools, native):
        agent, team = self.require_agent(session.agent_id), self.team_for(session)
        _record_tool_result(self.manager, team, agent, result)
        message = (
            {
                "role": "tool",
                "name": result.name,
                "tool_call_id": result.tool_call_id,
                "content": f"[{result.status.value}] {result.content}",
            }
            if native
            else {
                "role": "user",
                "content": f"Observation [{result.status.value}]: {result.content}",
            }
        )
        message.update(
            tool_status=result.status.value,
            tool_error_kind=result.error_kind,
            tool_attempts=result.attempts,
            invocation_id=session.invocation_id,
        )
        if result.name == "read_chat_message" and not result.failed:
            message["source_chat_message_id"] = json.loads(result.content)["message_id"]
        if result.name in _PRIVATE_TOOL_NAMES:
            _append_private_window_message(agent, message, team, self.manager)
        elif result.name in _MEMORY_RECALL_TOOL_NAMES:
            _append_transient_window_message(
                agent,
                message,
                team,
                self.manager,
                marker=_MEMORY_WINDOW_MARKER,
                placeholder=_memory_recall_placeholder(result),
            )
        else:
            self.append(
                session,
                message,
                capture_content=result.name in tools
                and tools[result.name].memory_capture == "content",
            )
        if result._chat_read_acknowledgement is not None and not result.failed:
            session.pending_chat_read_acknowledgements.append(result._chat_read_acknowledgement)
