import abc
import asyncio
import inspect
import logging
import json
import re
import ast
import time
from typing import Dict, Any, List, Optional, Tuple, Union
from ai_team_team.core.agent import Agent
from ai_team_team.core.response import ToolCall, ToolResult, LLMResponse
from ai_team_team.core.exceptions import ATTException
from ai_team_team.core.utils import generate_with_retry


_PRIVATE_TOOL_NAMES = {
    "list_private_files",
    "read_private_file",
    "write_private_file",
    "delete_private_file",
    "move_private_file",
    "publish_private_file",
}
_PRIVATE_WINDOW_MARKER = "[ATT_PRIVATE_OBSERVATION]"


def _redact_private_log(text: Any) -> str:
    """Removes complete log payloads that mention private operations."""
    rendered = str(text)
    if (
        _PRIVATE_WINDOW_MARKER in rendered
        or any(name in rendered for name in _PRIVATE_TOOL_NAMES)
    ):
        return "[private tool payload redacted]"
    return rendered


def _private_action_metadata(
    tool_name: str, tool_obj: Any, args: List[Any], kwargs: Dict[str, Any]
) -> str:
    """Formats private operation metadata without file content."""
    try:
        bound = inspect.signature(tool_obj.func).bind_partial(*args, **kwargs)
        allowed = {
            key: value
            for key, value in bound.arguments.items()
            if key != "content"
        }
    except (TypeError, ValueError):
        allowed = {key: value for key, value in kwargs.items() if key != "content"}
    return f"{tool_name}({allowed!r})"


def _append_agent_message(
    agent: Agent, message: Dict[str, Any], team: Any, manager: Any
) -> None:
    """Records a message with its invocation-scoped team and discussion."""
    enriched = dict(message)
    enriched["team_id"] = team.team_id
    discussion_id = (
        manager._active_discussion_id.get() if manager else None
    )
    enriched["discussion_id"] = discussion_id
    agent.append_message(enriched)


def _append_private_window_message(
    agent: Agent,
    message: Dict[str, Any],
    team: Any,
    manager: Any,
) -> None:
    """Keeps a private observation in the model window but not durable history."""
    actual = dict(message)
    actual["content"] = (
        f"{_PRIVATE_WINDOW_MARKER}\n{actual.get('content', '')}"
    )
    actual["team_id"] = team.team_id
    actual["discussion_id"] = (
        manager._active_discussion_id.get() if manager else None
    )
    persisted = dict(actual)
    persisted["content"] = "[private tool result redacted]"
    agent.sync_message_history()
    agent.messages.append(actual)
    agent.message_history.append(persisted)
    agent._history_seen_ids.add(id(actual))


def _has_private_window_content(agent: Agent) -> bool:
    """Returns whether the active model window contains private observations."""
    return any(
        _PRIVATE_WINDOW_MARKER in str(message.get("content", ""))
        for message in agent.messages
    )


def _privacy_safe_agent_output(agent: Agent, value: Any) -> str:
    """Redacts callback/log output derived from a private model window."""
    if _has_private_window_content(agent):
        return "[private-derived agent output redacted]"
    return _redact_private_log(value)


def _scrub_private_window_messages(agent: Agent) -> None:
    """Expires private observations when the current model invocation ends."""
    for index, message in enumerate(agent.messages):
        if _PRIVATE_WINDOW_MARKER not in str(message.get("content", "")):
            continue
        safe_message = dict(message)
        safe_message["content"] = "[private tool result redacted]"
        agent._history_seen_ids.discard(id(message))
        agent._history_seen_ids.add(id(safe_message))
        agent.messages[index] = safe_message


def _redact_private_tool_calls(
    tool_calls: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Removes private file bodies from structured assistant messages."""
    sanitized = []
    for tool_call in tool_calls:
        item = dict(tool_call)
        function = item.get("function")
        name = item.get("name")
        if isinstance(function, dict):
            name = function.get("name", name)
        if name in _PRIVATE_TOOL_NAMES:
            if isinstance(function, dict):
                safe_function = dict(function)
                safe_function["arguments"] = {"private_payload": "redacted"}
                item["function"] = safe_function
            if "arguments" in item:
                item["arguments"] = {"private_payload": "redacted"}
        sanitized.append(item)
    return sanitized

async def _prepare_agent_context(team: Any, agent: Agent, prompt: str, manager: Any) -> str:
    """Prepares the agent context, memory compression, transition notice, and returns the identity header."""
    team.set_status(agent.name, "Thinking...")
    if manager:
        manager._emit_callback("on_status_change", agent.name, "Thinking...")

    peer_context = ""
    if manager:
        peer_context = f"\n### ACTIVE AGENT TEAMS TOPOLOGY (Global Map)\n{manager.render_topology_tree()}\n"

    max_depth = manager.config.max_delegation_depth if manager else 2
    min_size = manager.config.min_subagent_team_size if manager else 3

    all_models = {}
    if manager:
        for k, v in manager.model_configs.items():
            all_models[k] = v.get("ai_note", "No description")
        for k in manager.llm_clients.keys():
            if k not in all_models:
                all_models[k] = "No description"

    model_options = "\n".join([f"  - {k}: {note}" for k, note in all_models.items()])
    role_desc_str = f"- **Role Description**: {agent.role_description}\n" if getattr(agent, "role_description", "") else ""
    experts_str = ""
    if manager:
        experts_lines = []
        for name, exp_agent in sorted(manager.agents.items()):
            role_desc = getattr(exp_agent, "role_description", "") or "No description"
            experts_lines.append(f"  - **{name}** ({exp_agent.role}): {role_desc}")
        if experts_lines:
            experts_str = f"## GLOBAL EXPERTS AVAILABLE FOR HIRE\n" + "\n".join(experts_lines) + "\n\n"

    identity_header = (
        f"## AGENT IDENTITY PROFILE\n"
        f"- **Role Name**: {agent.role}\n"
        f"{role_desc_str}"
        f"- **Agent Name**: {agent.name}\n"
        f"- **Parent Team**: {team.team_id} (Preset: {team.preset_name})\n"
        f"- **Team Purpose**: {team.team_purpose}\n"
        f"- **Current Objective**: Cooperate in team tasks.\n"
        f"- **AT Delegation Depth**: {team.depth} / {max_depth}\n"
        f"{peer_context}"
        f"{experts_str}"
        f"### AUTONOMY RULES\n"
        f"1. You can dynamically spawn child ATs using the `dispatch_subagent` tool to solve sub-problems.\n"
        f"2. You MUST NOT spawn child ATs if your Delegation Depth is already at the maximum ({max_depth}). If you need help at max depth, use `delegate_escalation` to ask your parent.\n"
        f"3. A valid AT MUST have at least {min_size} members.\n"
        f"4. You can dynamically request to migrate your team to a different parent team in the topology using the `request_migration` tool if it helps in task routing.\n"
        f"5. When creating an AT, you can assign models based on task complexity. Available models:\n"
        f"{model_options}\n"
    )

    current_context = {
        "team_id": team.team_id,
        "preset_name": team.preset_name,
        "team_purpose": team.team_purpose,
        "role": agent.role,
        "role_description": getattr(agent, "role_description", ""),
        "system_instructions": getattr(agent, "system_instructions", ""),
        "tools": sorted(list(team.tools.keys())) if getattr(team, "tools", None) else []
    }
    if agent.last_context and agent.last_context.get("team_id") != team.team_id:
        notice = (
            f"*** TRANSITION NOTICE: ACTIVE TEAM UPDATE ***\n"
            f"You have transitioned to work with another team group:\n"
            f"- Active Team: {team.team_id} (Preset: {team.preset_name})\n"
            f"- Team Purpose: {team.team_purpose}\n"
            f"- Your Assigned Role: {agent.role}\n"
            f"Please continue your work and cooperate in this team based on your prior memory."
        )
        _append_agent_message(
            agent, {"role": "system", "content": notice}, team, manager
        )
    agent.last_context = current_context

    enable_compression = manager.config.enable_memory_compression if manager else True
    max_turns = manager.config.max_memory_turns if manager else 20

    if enable_compression and len(agent.messages) > max_turns + 2:
        first_msg = agent.messages[0]
        
        slice_idx = len(agent.messages) - max_turns
        while slice_idx > 1 and agent.messages[slice_idx].get("role") in ("tool", "function"):
            slice_idx -= 1
        
        intermediate_messages = agent.messages[1 : slice_idx]
        history_text_parts = []
        for msg in intermediate_messages:
            r = msg.get("role", "unknown").upper()
            c = msg.get("content", "")
            history_text_parts.append(f"{r}: {c}")
        history_text = _redact_private_log("\n".join(history_text_parts))
        
        summary_prompt = (
            f"Summarize the preceding execution logs and discussions into a single cohesive paragraph of historical facts. "
            f"Focus on what was completed.\n\n"
            f"--- EXECUTION LOGS AND DISCUSSIONS BEGIN ---\n"
            f"{history_text}\n"
            f"--- EXECUTION LOGS AND DISCUSSIONS END ---\n"
        )
        
        summarize_client = agent.llm_client
        retries = manager.config.llm_max_retries if manager else 3
        backoff = manager.config.llm_retry_backoff_factor if manager else 1.5
        
        try:
            summary_resp = await generate_with_retry(
                llm_client=summarize_client,
                prompt=summary_prompt,
                system_instruction="You are a precise summarization assistant.",
                temperature=0.3,
                retries=retries,
                backoff_factor=backoff,
                manager=manager
            )
            summary_text = summary_resp.text if isinstance(summary_resp, LLMResponse) else str(summary_resp)
            summary_text = summary_text.strip()
        except Exception as e:
            team.logger.warning(f"Memory compression summarization failed: {e}. Using a generic fallback summary.")
            summary_text = "Early execution history compressed due to context limits."
        
        archive_message = {
            "role": "system",
            "content": f"*** HISTORICAL SUMMARY ARCHIVE ***\n{summary_text}"
        }
        latest_messages = agent.messages[slice_idx :]
        _append_agent_message(agent, archive_message, team, manager)
        enriched_archive = agent.messages.pop()
        agent.messages = [first_msg, enriched_archive] + latest_messages

    _append_agent_message(
        agent, {"role": "user", "content": prompt}, team, manager
    )
    return identity_header

def parse_tool_args(args_str: str) -> Tuple[List[Any], Dict[str, Any]]:
    """Robustly parse string arguments into Python args and kwargs using AST."""
    if not args_str or not args_str.strip():
        return [], {}
    try:
        tree = ast.parse(f"dummy_func({args_str})", mode='eval')
        call = tree.body
        
        args = []
        for arg in call.args:
            args.append(ast.literal_eval(arg))
            
        kwargs = {}
        for kw in call.keywords:
            kwargs[kw.arg] = ast.literal_eval(kw.value)
            
        return args, kwargs
    except Exception as e:
        # Fallback for LLM string hallucinations
        try:
            parsed_vals = ast.literal_eval(f"({args_str})")
            if isinstance(parsed_vals, tuple):
                return list(parsed_vals), {}
            else:
                return [parsed_vals], {}
        except Exception:
            pass
        return [args_str.strip()], {}


class BaseReasoningStrategy(metaclass=abc.ABCMeta):
    """Abstract base class representing a reasoning strategy for an agent turn."""
    @abc.abstractmethod
    async def execute(
        self,
        team: Any,
        agent: Agent,
        prompt: str,
        system_instruction: str,
        max_steps: int,
        manager: Any
    ) -> str:
        pass

class TextReactReasoningStrategy(BaseReasoningStrategy):
    """Implements the standard text-based Thought/Action/Observation ReAct reasoning loop."""
    async def execute(
        self,
        team: Any,
        agent: Agent,
        prompt: str,
        system_instruction: str,
        max_steps: int,
        manager: Any
    ) -> str:
        try:
            identity_header = await _prepare_agent_context(team, agent, prompt, manager)

            if getattr(team, "tools", None):
                tools_desc = []
                for t_name, tool in team.tools.items():
                    tools_desc.append(f"- **{t_name}**: {tool.description}")
                tools_list_str = "\n".join(tools_desc)

                agent_sys_inst = f"### YOUR INDIVIDUAL MISSION\n{agent.system_instructions}\n\n" if getattr(agent, "system_instructions", "") else ""
                
                voting_context = ""
                if manager and manager.config.enable_membership_voting and team.proposals:
                    voting_lines = ["### ACTIVE MEMBERSHIP VOTES:"]
                    for vp_id, prop in team.proposals.items():
                        if prop.get("status") == "active":
                            voted_list = []
                            member_names = {
                                member.agent_id: member.name
                                for member in team.members
                            }
                            for voter_id, v_data in prop["votes"].items():
                                if v_data["public"]:
                                    voter_name = member_names.get(
                                        voter_id, "Former member"
                                    )
                                    voted_list.append(
                                        f"{voter_name}: {v_data['vote']} (Public)"
                                    )
                                else:
                                    voted_list.append(f"Anonymous Voter: {v_data['vote']}")
                            voted_str = ", ".join(voted_list) if voted_list else "None"
                            remaining = [
                                member.name
                                for member in team.members
                                if member.agent_id not in prop["votes"]
                            ]
                            remaining_str = ", ".join(remaining) if remaining else "None"
                            voting_lines.append(
                                f"- Proposal [{vp_id}]: {prop['action'].upper()} '{prop['target']}'\n"
                                f"  - Initiator: {prop['initiator_type'].capitalize()} ({prop['initiator_name']})\n"
                                f"  - Rationale: {prop['rationale']}\n"
                                f"  - Current Votes: {voted_str}\n"
                                f"  - Remaining Voters: {remaining_str} (You can cast your vote using the 'cast_vote' tool)"
                            )
                    if len(voting_lines) > 1:
                        voting_context = "\n" + "\n".join(voting_lines) + "\n"

                react_system_instruction = (
                    f"{system_instruction}\n\n"
                    f"{agent_sys_inst}"
                    f"{identity_header}"
                    f"{voting_context}"
                    f"### AVAILABLE TOOLS\n"
                    f"{tools_list_str}\n\n"
                    f"### REACT FORMAT INSTRUCTIONS\n"
                    f"When executing your task, you can reason and use tools step-by-step. Use the following format:\n"
                    f"Thought: <your reasoning about the next step>\n"
                    f"Action: <tool_name>(<arguments_separated_by_commas_or_kwargs>)\n"
                    f"Observation: <the tool output will appear here>\n\n"
                    f"You can repeat the Thought/Action/Observation loop multiple times if needed. "
                    f"Once you have all the necessary information, or if you do not need to use any tools, output exactly:\n"
                    f"Final Answer: <your final answer here>"
                )

                tool_retry_count = 0
                for step in range(max_steps):
                    try:
                        team.set_status(agent.name, f"Thinking (Step {step+1}/{max_steps})...")
                        if manager:
                            manager._emit_callback(
                                "on_status_change",
                                agent.name,
                                f"Thinking (Step {step+1}/{max_steps})...",
                            )

                        retries = manager.config.llm_max_retries if manager else 3
                        backoff = manager.config.llm_retry_backoff_factor if manager else 1.5
                        
                        resp_obj = await generate_with_retry(
                            llm_client=agent.llm_client,
                            prompt=agent.messages,
                            system_instruction=react_system_instruction,
                            temperature=0.3,
                            retries=retries,
                            backoff_factor=backoff,
                            manager=manager
                        )
                        
                        response = resp_obj.text if isinstance(resp_obj, LLMResponse) else str(resp_obj)
                        response = response.strip()

                        team.logger.info(
                            "Agent %s ReAct step %s response:\n%s",
                            agent.name,
                            step + 1,
                            _privacy_safe_agent_output(agent, response),
                        )

                        _append_agent_message(
                            agent,
                            {
                                "role": "assistant",
                                "content": _privacy_safe_agent_output(
                                    agent, response
                                ),
                            },
                            team,
                            manager,
                        )

                        if manager and manager.on_log_append:
                            formatted_prompt = json.dumps(agent.messages[:-1], indent=2, ensure_ascii=False)
                            log_content = (
                                f"AGENT: {agent.name}\n"
                                f"ROLE: {agent.role}\n"
                                f"STEP: {step+1}\n"
                                f"--- SYSTEM INSTRUCTION BEGIN ---\n"
                                f"{react_system_instruction}\n"
                                f"--- SYSTEM INSTRUCTION END ---\n"
                                f"--- PROMPT BEGIN ---\n"
                                f"{_redact_private_log(formatted_prompt)}\n"
                                f"--- PROMPT END ---\n"
                                f"--- RESPONSE BEGIN ---\n"
                                f"{_privacy_safe_agent_output(agent, response)}\n"
                                f"--- RESPONSE END ---\n"
                            )
                            manager._emit_callback(
                                "on_log_append",
                                team.team_id,
                                f"ReAct LLM Step | {agent.name} ({agent.role}) Step {step+1}",
                                log_content,
                                team.chapter_num
                            )

                        if "Final Answer:" in response:
                            final_ans_content = response.split("Final Answer:", 1)[1].strip()
                            if manager:
                                callback_answer = (
                                    "[private-derived final answer redacted]"
                                    if _has_private_window_content(agent)
                                    else final_ans_content
                                )
                                manager._emit_callback(
                                    "on_activity_added",
                                    agent.name,
                                    "Final Answer",
                                    callback_answer,
                                )
                            return final_ans_content

                        thought_match = re.search(r"Thought:\s*(.*)", response, re.IGNORECASE)
                        if thought_match:
                            thought_content = thought_match.group(1).split("Action:")[0].strip()
                            if manager:
                                callback_thought = (
                                    "[private-derived thought redacted]"
                                    if _has_private_window_content(agent)
                                    else thought_content
                                )
                                manager._emit_callback(
                                    "on_activity_added",
                                    agent.name,
                                    "Thought",
                                    callback_thought,
                                )

                        tool_name = None
                        tool_args_str = None

                        xml_match = re.search(r'<action\s+name="(\w+)"\s*>(.*?)</action>', response, re.DOTALL | re.IGNORECASE)
                        if xml_match:
                            tool_name = xml_match.group(1).strip()
                            tool_args_str = xml_match.group(2).strip()
                            if tool_args_str.startswith("```") and tool_args_str.endswith("```"):
                                lines = tool_args_str.splitlines()
                                if lines[0].startswith("```"):
                                    lines = lines[1:]
                                if lines and lines[-1].endswith("```"):
                                    lines = lines[:-1]
                                tool_args_str = "\n".join(lines).strip()
                        else:
                            react_match = re.search(r'Action:\s*(?:```(?:python)?\s*)?(\w+)\((.*?)\)(?:\s*```)?', response, re.DOTALL | re.IGNORECASE)
                            if react_match:
                                tool_name = react_match.group(1).strip()
                                tool_args_str = react_match.group(2).strip()

                        if tool_name is not None:
                            args, kwargs = parse_tool_args(tool_args_str)
                            private_tool = tool_name in _PRIVATE_TOOL_NAMES
                            action_metadata = f"{tool_name}({tool_args_str})"

                            if tool_name in team.tools:
                                tool_obj = team.tools[tool_name]
                                action_metadata = (
                                    _private_action_metadata(
                                        tool_name, tool_obj, args, kwargs
                                    )
                                    if private_tool
                                    else f"{tool_name}({tool_args_str})"
                                )
                                team.logger.info(
                                    "Executing tool: %s",
                                    action_metadata,
                                )
                                
                                team.set_status(agent.name, f"Executing Tool: {tool_name}")
                                if manager:
                                    manager._emit_callback(
                                        "on_status_change",
                                        agent.name,
                                        f"Executing Tool: {tool_name}",
                                    )
                                    manager._emit_callback(
                                        "on_activity_added",
                                        agent.name,
                                        "Action",
                                        action_metadata,
                                    )

                                active_agent_token = (
                                    manager._active_tool_agent.set(agent)
                                    if manager
                                    else None
                                )
                                invocation_token = (
                                    manager._active_tool_invocation_id.set(
                                        f"{manager._active_discussion_id.get() or 'runtime'}:"
                                        f"{agent.agent_id}:{step}:{tool_name}"
                                    )
                                    if manager
                                    else None
                                )
                                try:
                                    if (
                                        manager
                                        and tool_name
                                        in manager.tool_auditors
                                    ):
                                        auditor = manager.tool_auditors[
                                            tool_name
                                        ]
                                        if inspect.iscoroutinefunction(
                                            auditor
                                        ):
                                            approved, audit_reason = (
                                                await auditor(
                                                    *args, **kwargs
                                                )
                                            )
                                        else:
                                            approved, audit_reason = (
                                                await asyncio.to_thread(
                                                    auditor,
                                                    *args,
                                                    **kwargs,
                                                )
                                            )
                                        if not approved:
                                            observation = (
                                                "Error: Tool execution "
                                                "rejected by auditor: "
                                                f"{audit_reason}"
                                            )
                                        else:
                                            observation = await tool_obj(
                                                *args, **kwargs
                                            )
                                    else:
                                        observation = await tool_obj(*args, **kwargs)
                                finally:
                                    if (
                                        manager
                                        and active_agent_token is not None
                                    ):
                                        manager._active_tool_agent.reset(
                                            active_agent_token
                                        )
                                    if manager and invocation_token is not None:
                                        manager._active_tool_invocation_id.reset(
                                            invocation_token
                                        )
                                
                                team.set_status(agent.name, "Thinking...")
                                if manager:
                                    manager._emit_callback(
                                        "on_status_change",
                                        agent.name,
                                        "Thinking...",
                                    )
                                if manager:
                                    manager._auto_save(
                                        agents={agent.agent_id},
                                        teams={team.team_id},
                                    )
                                if manager:
                                    obs_summary = (
                                        "[private tool result redacted]"
                                        if private_tool
                                        else str(observation)
                                    )
                                    if len(obs_summary) > 80:
                                        obs_summary = obs_summary[:77] + "..."
                                    manager._emit_callback(
                                        "on_activity_added",
                                        agent.name,
                                        "Observation",
                                        obs_summary,
                                    )
                            else:
                                observation = f"Error: Tool '{tool_name}' is not registered."
                                if manager:
                                    manager._emit_callback(
                                        "on_activity_added",
                                        agent.name,
                                        "Observation",
                                        observation,
                                    )

                            logged_observation = (
                                "[private tool result redacted]"
                                if private_tool
                                else observation
                            )
                            team.logger.info(
                                "Tool %s observation: %s",
                                tool_name,
                                logged_observation,
                            )
                            
                            if manager and manager.on_log_append:
                                log_content = (
                                    f"AGENT: {agent.name}\n"
                                    f"ROLE: {agent.role}\n"
                                    f"ACTION: "
                                    f"{action_metadata if private_tool else f'{tool_name}({tool_args_str})'}\n"
                                    f"OBSERVATION:\n{logged_observation}\n"
                                )
                                manager._emit_callback(
                                    "on_log_append",
                                    team.team_id,
                                    f"ReAct Tool Call | {agent.name} ({agent.role})",
                                    log_content,
                                    team.chapter_num
                                )

                            if observation.startswith("Error:") or observation.startswith("Error "):
                                tool_retry_count += 1
                                max_retries = manager.config.max_tool_retries if manager else 3
                                if tool_retry_count > max_retries:
                                    raise ATTException(f"Tool execution failed {tool_retry_count} times in this step. Maximum tool retries ({max_retries}) exceeded. Last error: {observation}")

                            observation_message = {
                                "role": "user",
                                "content": f"Observation: {observation}",
                            }
                            if private_tool:
                                _append_private_window_message(
                                    agent,
                                    observation_message,
                                    team,
                                    manager,
                                )
                            else:
                                _append_agent_message(
                                    agent,
                                    observation_message,
                                    team,
                                    manager,
                                )
                        else:
                            if step == max_steps - 1:
                                return response
                            _append_agent_message(
                                agent,
                                {
                                    "role": "user",
                                    "content": "Observation: Please output either 'Action: tool_name(args)' or 'Final Answer: <content>'.",
                                },
                                team,
                                manager,
                            )
                    except ATTException as e:
                        raise e
                    except Exception as e:
                        team.logger.error(f"Error in ReAct step {step+1} for agent {agent.name}: {e}")
                        return f"Error executing task during ReAct loop: {e}"

                return "Error: ReAct loop exceeded maximum steps without producing a Final Answer."

            else:
                agent_sys_inst = f"### YOUR INDIVIDUAL MISSION\n{agent.system_instructions}\n\n" if getattr(agent, "system_instructions", "") else ""
                full_system_instruction = (
                    f"{system_instruction}\n\n"
                    f"{agent_sys_inst}"
                    f"{identity_header}\n"
                    f"Output exactly 'Final Answer: <content>' when complete."
                )

                try:
                    retries = manager.config.llm_max_retries if manager else 3
                    backoff = manager.config.llm_retry_backoff_factor if manager else 1.5
                    resp_obj = await generate_with_retry(
                        llm_client=agent.llm_client,
                        prompt=agent.messages,
                        system_instruction=full_system_instruction,
                        temperature=0.3,
                        retries=retries,
                        backoff_factor=backoff,
                        manager=manager
                    )
                    
                    response = resp_obj.text if isinstance(resp_obj, LLMResponse) else str(resp_obj)
                    response = response.strip()
                    _append_agent_message(
                        agent,
                        {
                            "role": "assistant",
                            "content": _privacy_safe_agent_output(
                                agent, response
                            ),
                        },
                        team,
                        manager,
                    )

                    if manager and manager.on_log_append:
                        formatted_prompt = json.dumps(agent.messages[:-1], indent=2, ensure_ascii=False)
                        log_content = (
                            f"AGENT: {agent.name}\n"
                            f"ROLE: {agent.role}\n"
                            f"--- SYSTEM INSTRUCTION BEGIN ---\n"
                            f"{full_system_instruction}\n"
                            f"--- SYSTEM INSTRUCTION END ---\n"
                            f"--- PROMPT BEGIN ---\n"
                            f"{_redact_private_log(formatted_prompt)}\n"
                            f"--- PROMPT END ---\n"
                            f"--- RESPONSE BEGIN ---\n"
                            f"{_privacy_safe_agent_output(agent, response)}\n"
                            f"--- RESPONSE END ---\n"
                        )
                        manager._emit_callback(
                            "on_log_append",
                            team.team_id,
                            f"Direct LLM Call | {agent.name} ({agent.role})",
                            log_content,
                            team.chapter_num
                        )

                    if "Final Answer:" in response:
                        final_ans_content = response.split("Final Answer:", 1)[1].strip()
                        if manager:
                            callback_answer = (
                                "[private-derived final answer redacted]"
                                if _has_private_window_content(agent)
                                else final_ans_content
                            )
                            manager._emit_callback(
                                "on_activity_added",
                                agent.name,
                                "Final Answer",
                                callback_answer,
                            )
                        return final_ans_content
                    return response
                except ATTException as e:
                    raise e
                except Exception as e:
                    team.logger.error(f"Agent {agent.name} execution error: {e}")
                    return f"Error executing task: {e}"
        finally:
            _scrub_private_window_messages(agent)
            team.set_status(agent.name, "Idle")
            if manager:
                manager._emit_callback(
                    "on_status_change", agent.name, "Idle"
                )
            if manager:
                manager._auto_save(
                    agents={agent.agent_id},
                    teams={team.team_id},
                )

class NativeReasoningStrategy(BaseReasoningStrategy):
    """Implements modern API-level parallel native tool calling reasoning loop."""
    async def execute(
        self,
        team: Any,
        agent: Agent,
        prompt: str,
        system_instruction: str,
        max_steps: int,
        manager: Any
    ) -> str:
        try:
            tool_retry_count = 0
            identity_header = await _prepare_agent_context(team, agent, prompt, manager)

            # Prepare native tools
            native_tools = []
            if getattr(team, "tools", None):
                native_tools = list(team.tools.values())

            agent_sys_inst = f"### YOUR INDIVIDUAL MISSION\n{agent.system_instructions}\n\n" if getattr(agent, "system_instructions", "") else ""
            native_system_instruction = (
                f"{system_instruction}\n\n"
                f"{agent_sys_inst}"
                f"{identity_header}"
            )

            max_tool_rounds = manager.config.max_tool_rounds if manager else 5

            for round_idx in range(max_tool_rounds):
                team.set_status(agent.name, f"Thinking (Round {round_idx+1}/{max_tool_rounds})...")
                if manager:
                    manager._emit_callback(
                        "on_status_change",
                        agent.name,
                        f"Thinking (Round {round_idx+1}/{max_tool_rounds})...",
                    )

                retries = manager.config.llm_max_retries if manager else 3
                backoff = manager.config.llm_retry_backoff_factor if manager else 1.5

                response = await generate_with_retry(
                    llm_client=agent.llm_client,
                    prompt=agent.messages,
                    system_instruction=native_system_instruction,
                    temperature=0.3,
                    require_json=False,
                    retries=retries,
                    backoff_factor=backoff,
                    tools=native_tools if native_tools else None,
                    return_response_obj=True,
                    manager=manager
                )

                if isinstance(response, str):
                    response = LLMResponse(text=response)

                team.logger.info(
                    "Agent %s Native response round %s: text=%s, tool_calls=%s",
                    agent.name,
                    round_idx + 1,
                    (
                        "[private-derived response redacted]"
                        if _has_private_window_content(agent)
                        else response.text
                    ),
                    len(response.tool_calls),
                )

                # Convert to LLM message formats
                if response.tool_calls:
                    # Append assistant message with structured tool calls
                    tool_calls_dict = _redact_private_tool_calls(
                        [tc.to_dict() for tc in response.tool_calls]
                    )
                    _append_agent_message(
                        agent,
                        {
                            "role": "assistant",
                            "content": _privacy_safe_agent_output(
                                agent, response.text
                            ),
                            "tool_calls": tool_calls_dict,
                        },
                        team,
                        manager,
                    )

                    # Concurrently execute tools
                    tasks = []
                    for tc in response.tool_calls:
                        tasks.append(self._execute_single_tool(tc, team, agent, manager))
                    
                    results: List[ToolResult] = await asyncio.gather(*tasks)

                    # Append tool result messages
                    for tr in results:
                        result_message = {
                            "role": "tool",
                            "tool_call_id": tr.tool_call_id,
                            "name": tr.name,
                            "content": tr.content,
                        }
                        if tr.name in _PRIVATE_TOOL_NAMES:
                            _append_private_window_message(
                                agent, result_message, team, manager
                            )
                        else:
                            _append_agent_message(
                                agent, result_message, team, manager
                            )

                        # Trigger callbacks
                        if manager:
                            manager._emit_callback(
                                "on_activity_added",
                                agent.name,
                                "Action",
                                f"{tr.name}(id={tr.tool_call_id})",
                            )
                            obs_summary = (
                                "[private tool result redacted]"
                                if tr.name in _PRIVATE_TOOL_NAMES
                                else str(tr.content)
                            )
                            if len(obs_summary) > 80:
                                obs_summary = obs_summary[:77] + "..."
                            manager._emit_callback(
                                "on_activity_added",
                                agent.name,
                                "Observation",
                                obs_summary,
                            )

                        if manager and manager.on_log_append:
                            log_content = (
                                f"AGENT: {agent.name}\n"
                                f"ROLE: {agent.role}\n"
                                f"TOOL CALL ID: {tr.tool_call_id}\n"
                                f"ACTION: {tr.name}\n"
                                f"OBSERVATION:\n"
                                f"{'[private tool result redacted]' if tr.name in _PRIVATE_TOOL_NAMES else tr.content}\n"
                            )
                            manager._emit_callback(
                                "on_log_append",
                                team.team_id,
                                f"Native Tool Result | {agent.name} ({agent.role})",
                                log_content,
                                team.chapter_num
                            )
                    
                    has_error = False
                    for tr in results:
                        if tr.content.startswith("Error:") or tr.content.startswith("Error "):
                            has_error = True
                            tool_retry_count += 1
                    
                    if has_error:
                        max_retries = manager.config.max_tool_retries if manager else 3
                        if tool_retry_count > max_retries:
                            raise ATTException(f"Tool execution failed {tool_retry_count} times in this step. Maximum tool retries ({max_retries}) exceeded.")

                    if manager:
                        manager._auto_save(
                            agents={agent.agent_id},
                            teams={team.team_id},
                        )
                else:
                    # Final answer received (no tool calls requested)
                    _append_agent_message(
                        agent,
                        {
                            "role": "assistant",
                            "content": _privacy_safe_agent_output(
                                agent, response.text
                            ),
                        },
                        team,
                        manager,
                    )
                    
                    if manager:
                        callback_answer = (
                            "[private-derived final answer redacted]"
                            if _has_private_window_content(agent)
                            else (response.text or "")
                        )
                        manager._emit_callback(
                            "on_activity_added",
                            agent.name,
                            "Final Answer",
                            callback_answer,
                        )
                        
                    if manager and manager.on_log_append:
                        formatted_prompt = json.dumps(agent.messages[:-1], indent=2, ensure_ascii=False)
                        log_content = (
                            f"AGENT: {agent.name}\n"
                            f"ROLE: {agent.role}\n"
                            f"--- SYSTEM INSTRUCTION BEGIN ---\n"
                            f"{native_system_instruction}\n"
                            f"--- SYSTEM INSTRUCTION END ---\n"
                            f"--- PROMPT BEGIN ---\n"
                            f"{_redact_private_log(formatted_prompt)}\n"
                            f"--- PROMPT END ---\n"
                            f"--- RESPONSE BEGIN ---\n"
                            f"{_privacy_safe_agent_output(agent, response.text)}\n"
                            f"--- RESPONSE END ---\n"
                        )
                        manager._emit_callback(
                            "on_log_append",
                            team.team_id,
                            f"Native Final Response | {agent.name} ({agent.role})",
                            log_content,
                            team.chapter_num
                        )
                    
                    return response.text or ""

            return "Error: Native tool calling exceeded maximum tool rounds without producing a text final answer."
        finally:
            _scrub_private_window_messages(agent)
            team.set_status(agent.name, "Idle")
            if manager:
                manager._emit_callback(
                    "on_status_change", agent.name, "Idle"
                )
            if manager:
                manager._auto_save(
                    agents={agent.agent_id},
                    teams={team.team_id},
                )

    async def _execute_single_tool(self, tool_call: ToolCall, team: Any, agent: Agent, manager: Any) -> ToolResult:
        tool_name = tool_call.name
        args = []
        kwargs = tool_call.arguments or {}
        if isinstance(kwargs, str):
            try:
                kwargs = json.loads(kwargs)
            except json.JSONDecodeError as exc:
                return ToolResult(
                    tool_call_id=tool_call.call_id,
                    name=tool_name,
                    content=(
                        f"Error: Tool '{tool_name}' arguments are invalid "
                        f"JSON: {exc}"
                    ),
                    raw=tool_call.raw,
                )
        if not isinstance(kwargs, dict):
            return ToolResult(
                tool_call_id=tool_call.call_id,
                name=tool_name,
                content=(
                    f"Error: Tool '{tool_name}' arguments must be an object."
                ),
                raw=tool_call.raw,
            )
        active_agent_token = (
            manager._active_tool_agent.set(agent) if manager else None
        )
        invocation_token = (
            manager._active_tool_invocation_id.set(
                tool_call.call_id
                or f"{manager._active_discussion_id.get() or 'runtime'}:"
                f"{agent.agent_id}:{tool_name}"
            )
            if manager
            else None
        )

        def finish(result: ToolResult) -> ToolResult:
            if manager and active_agent_token is not None:
                manager._active_tool_agent.reset(active_agent_token)
            if manager and invocation_token is not None:
                manager._active_tool_invocation_id.reset(invocation_token)
            return result

        # Audit check
        if manager and tool_name in manager.tool_auditors:
            auditor = manager.tool_auditors[tool_name]
            try:
                if inspect.iscoroutinefunction(auditor):
                    approved, audit_reason = await auditor(*args, **kwargs)
                else:
                    approved, audit_reason = await asyncio.to_thread(auditor, *args, **kwargs)
                if not approved:
                    content = f"Error: Tool execution rejected by auditor: {audit_reason}"
                    return finish(ToolResult(tool_call_id=tool_call.call_id, name=tool_name, content=content, raw=tool_call.raw))
            except Exception as e:
                content = f"Error auditing tool '{tool_name}': {e}"
                return finish(ToolResult(tool_call_id=tool_call.call_id, name=tool_name, content=content, raw=tool_call.raw))

        if tool_name in team.tools:
            tool_obj = team.tools[tool_name]
            try:
                content = await tool_obj(*args, **kwargs)
            except Exception as e:
                content = f"Error executing tool '{tool_name}': {e}"
        else:
            content = f"Error: Tool '{tool_name}' is not registered."

        return finish(ToolResult(tool_call_id=tool_call.call_id, name=tool_name, content=content, raw=tool_call.raw))
