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

async def _prepare_agent_context(team: Any, agent: Agent, prompt: str, manager: Any) -> str:
    """Prepares the agent context, memory compression, transition notice, and returns the identity header."""
    team.status_map[agent.name] = "Thinking..."
    if manager and manager.on_status_change:
        manager.on_status_change(agent.name, "Thinking...")

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
        agent.messages.append({"role": "system", "content": notice})
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
        history_text = "\n".join(history_text_parts)
        
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
        agent.messages = [first_msg, archive_message] + latest_messages

    agent.messages.append({"role": "user", "content": prompt})
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
                            for voter, v_data in prop["votes"].items():
                                if v_data["public"]:
                                    voted_list.append(f"{voter}: {v_data['vote']} (Public)")
                                else:
                                    voted_list.append(f"Anonymous Voter: {v_data['vote']}")
                            voted_str = ", ".join(voted_list) if voted_list else "None"
                            remaining = [m.name for m in team.members if m.name not in prop["votes"]]
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

                for step in range(max_steps):
                    try:
                        team.status_map[agent.name] = f"Thinking (Step {step+1}/{max_steps})..."
                        if manager and manager.on_status_change:
                            manager.on_status_change(agent.name, f"Thinking (Step {step+1}/{max_steps})...")

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

                        team.logger.info(f"Agent {agent.name} ReAct step {step+1} response:\n{response}")

                        agent.messages.append({"role": "assistant", "content": response})

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
                                f"{formatted_prompt}\n"
                                f"--- PROMPT END ---\n"
                                f"--- RESPONSE BEGIN ---\n"
                                f"{response}\n"
                                f"--- RESPONSE END ---\n"
                            )
                            manager.on_log_append(
                                team.team_id,
                                f"ReAct LLM Step | {agent.name} ({agent.role}) Step {step+1}",
                                log_content,
                                team.chapter_num
                            )

                        if "Final Answer:" in response:
                            final_ans_content = response.split("Final Answer:", 1)[1].strip()
                            if manager and manager.on_activity_added:
                                manager.on_activity_added(agent.name, "Final Answer", final_ans_content)
                            return final_ans_content

                        thought_match = re.search(r"Thought:\s*(.*)", response, re.IGNORECASE)
                        if thought_match:
                            thought_content = thought_match.group(1).split("Action:")[0].strip()
                            if manager and manager.on_activity_added:
                                manager.on_activity_added(agent.name, "Thought", thought_content)

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

                            if tool_name in team.tools:
                                tool_obj = team.tools[tool_name]
                                team.logger.info(f"Executing tool: {tool_name} with args={args}, kwargs={kwargs}")
                                
                                team.status_map[agent.name] = f"Executing Tool: {tool_name}"
                                if manager and manager.on_status_change:
                                    manager.on_status_change(agent.name, f"Executing Tool: {tool_name}")
                                if manager and manager.on_activity_added:
                                    manager.on_activity_added(agent.name, "Action", f"{tool_name}({tool_args_str})")

                                if manager and tool_name in manager.tool_auditors:
                                    auditor = manager.tool_auditors[tool_name]
                                    if inspect.iscoroutinefunction(auditor):
                                        approved, audit_reason = await auditor(*args, **kwargs)
                                    else:
                                        approved, audit_reason = await asyncio.to_thread(auditor, *args, **kwargs)
                                    if not approved:
                                        observation = f"Error: Tool execution rejected by auditor: {audit_reason}"
                                    else:
                                        observation = await tool_obj(*args, **kwargs)
                                else:
                                    observation = await tool_obj(*args, **kwargs)
                                
                                team.status_map[agent.name] = "Thinking..."
                                if manager and manager.on_status_change:
                                    manager.on_status_change(agent.name, "Thinking...")
                                if manager:
                                    manager._auto_save()
                                if manager and manager.on_activity_added:
                                    obs_summary = str(observation)
                                    if len(obs_summary) > 80:
                                        obs_summary = obs_summary[:77] + "..."
                                    manager.on_activity_added(agent.name, "Observation", obs_summary)
                            else:
                                observation = f"Error: Tool '{tool_name}' is not registered."
                                if manager and manager.on_activity_added:
                                    manager.on_activity_added(agent.name, "Observation", observation)

                            team.logger.info(f"Tool {tool_name} observation: {observation}")
                            
                            if manager and manager.on_log_append:
                                log_content = (
                                    f"AGENT: {agent.name}\n"
                                    f"ROLE: {agent.role}\n"
                                    f"ACTION: {tool_name}({tool_args_str})\n"
                                    f"OBSERVATION:\n{observation}\n"
                                )
                                manager.on_log_append(
                                    team.team_id,
                                    f"ReAct Tool Call | {agent.name} ({agent.role})",
                                    log_content,
                                    team.chapter_num
                                )

                            agent.messages.append({"role": "user", "content": f"Observation: {observation}"})
                        else:
                            if step == max_steps - 1:
                                return response
                            agent.messages.append({"role": "user", "content": "Observation: Please output either 'Action: tool_name(args)' or 'Final Answer: <content>'."})
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
                    agent.messages.append({"role": "assistant", "content": response})

                    if manager and manager.on_log_append:
                        formatted_prompt = json.dumps(agent.messages[:-1], indent=2, ensure_ascii=False)
                        log_content = (
                            f"AGENT: {agent.name}\n"
                            f"ROLE: {agent.role}\n"
                            f"--- SYSTEM INSTRUCTION BEGIN ---\n"
                            f"{full_system_instruction}\n"
                            f"--- SYSTEM INSTRUCTION END ---\n"
                            f"--- PROMPT BEGIN ---\n"
                            f"{formatted_prompt}\n"
                            f"--- PROMPT END ---\n"
                            f"--- RESPONSE BEGIN ---\n"
                            f"{response}\n"
                            f"--- RESPONSE END ---\n"
                        )
                        manager.on_log_append(
                            team.team_id,
                            f"Direct LLM Call | {agent.name} ({agent.role})",
                            log_content,
                            team.chapter_num
                        )

                    if "Final Answer:" in response:
                        final_ans_content = response.split("Final Answer:", 1)[1].strip()
                        if manager and manager.on_activity_added:
                            manager.on_activity_added(agent.name, "Final Answer", final_ans_content)
                        return final_ans_content
                    return response
                except ATTException as e:
                    raise e
                except Exception as e:
                    team.logger.error(f"Agent {agent.name} execution error: {e}")
                    return f"Error executing task: {e}"
        finally:
            team.status_map[agent.name] = "Idle"
            if manager and manager.on_status_change:
                manager.on_status_change(agent.name, "Idle")
            if manager:
                manager._auto_save()

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
                team.status_map[agent.name] = f"Thinking (Round {round_idx+1}/{max_tool_rounds})..."
                if manager and manager.on_status_change:
                    manager.on_status_change(agent.name, f"Thinking (Round {round_idx+1}/{max_tool_rounds})...")

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

                team.logger.info(f"Agent {agent.name} Native response round {round_idx+1}: text={response.text}, tool_calls={len(response.tool_calls)}")

                # Convert to LLM message formats
                if response.tool_calls:
                    # Append assistant message with structured tool calls
                    tool_calls_dict = [tc.to_dict() for tc in response.tool_calls]
                    agent.messages.append({
                        "role": "assistant",
                        "content": response.text,
                        "tool_calls": tool_calls_dict
                    })

                    # Concurrently execute tools
                    tasks = []
                    for tc in response.tool_calls:
                        tasks.append(self._execute_single_tool(tc, team, agent, manager))
                    
                    results: List[ToolResult] = await asyncio.gather(*tasks)

                    # Append tool result messages
                    for tr in results:
                        agent.messages.append({
                            "role": "tool",
                            "tool_call_id": tr.tool_call_id,
                            "name": tr.name,
                            "content": tr.content
                        })

                        # Trigger callbacks
                        if manager and manager.on_activity_added:
                            manager.on_activity_added(agent.name, "Action", f"{tr.name}(id={tr.tool_call_id})")
                            obs_summary = str(tr.content)
                            if len(obs_summary) > 80:
                                obs_summary = obs_summary[:77] + "..."
                            manager.on_activity_added(agent.name, "Observation", obs_summary)

                        if manager and manager.on_log_append:
                            log_content = (
                                f"AGENT: {agent.name}\n"
                                f"ROLE: {agent.role}\n"
                                f"TOOL CALL ID: {tr.tool_call_id}\n"
                                f"ACTION: {tr.name}\n"
                                f"OBSERVATION:\n{tr.content}\n"
                            )
                            manager.on_log_append(
                                team.team_id,
                                f"Native Tool Result | {agent.name} ({agent.role})",
                                log_content,
                                team.chapter_num
                            )
                    
                    if manager:
                        manager._auto_save()
                else:
                    # Final answer received (no tool calls requested)
                    agent.messages.append({"role": "assistant", "content": response.text})
                    
                    if manager and manager.on_activity_added:
                        manager.on_activity_added(agent.name, "Final Answer", response.text or "")
                        
                    if manager and manager.on_log_append:
                        formatted_prompt = json.dumps(agent.messages[:-1], indent=2, ensure_ascii=False)
                        log_content = (
                            f"AGENT: {agent.name}\n"
                            f"ROLE: {agent.role}\n"
                            f"--- SYSTEM INSTRUCTION BEGIN ---\n"
                            f"{native_system_instruction}\n"
                            f"--- SYSTEM INSTRUCTION END ---\n"
                            f"--- PROMPT BEGIN ---\n"
                            f"{formatted_prompt}\n"
                            f"--- PROMPT END ---\n"
                            f"--- RESPONSE BEGIN ---\n"
                            f"{response.text}\n"
                            f"--- RESPONSE END ---\n"
                        )
                        manager.on_log_append(
                            team.team_id,
                            f"Native Final Response | {agent.name} ({agent.role})",
                            log_content,
                            team.chapter_num
                        )
                    
                    return response.text or ""

            return "Error: Native tool calling exceeded maximum tool rounds without producing a text final answer."
        finally:
            team.status_map[agent.name] = "Idle"
            if manager and manager.on_status_change:
                manager.on_status_change(agent.name, "Idle")
            if manager:
                manager._auto_save()

    async def _execute_single_tool(self, tool_call: ToolCall, team: Any, agent: Agent, manager: Any) -> ToolResult:
        tool_name = tool_call.name
        args = []
        kwargs = tool_call.arguments or {}

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
                    return ToolResult(tool_call_id=tool_call.call_id, name=tool_name, content=content, raw=tool_call.raw)
            except Exception as e:
                content = f"Error auditing tool '{tool_name}': {e}"
                return ToolResult(tool_call_id=tool_call.call_id, name=tool_name, content=content, raw=tool_call.raw)

        if tool_name in team.tools:
            tool_obj = team.tools[tool_name]
            try:
                content = await tool_obj(*args, **kwargs)
            except Exception as e:
                content = f"Error executing tool '{tool_name}': {e}"
        else:
            content = f"Error: Tool '{tool_name}' is not registered."

        return ToolResult(tool_call_id=tool_call.call_id, name=tool_name, content=content, raw=tool_call.raw)
