import asyncio
import sqlite3
import os
import inspect

import uuid
import logging
import time
import json
import re
import ast
from typing import List, Dict, Optional, Any, Tuple, Callable, Union
from .tool import Tool
from .doc_library import DocumentLibrary


class ATTException(Exception):
    """Base exception for ATT framework errors."""
    pass

class LLMGenerationError(ATTException):
    """Raised when LLM generation fails after all retry attempts."""
    pass

async def generate_with_retry(
    llm_client: Any,
    prompt: Union[str, List[Dict[str, str]]],
    system_instruction: Optional[str] = None,
    temperature: float = 0.3,
    require_json: bool = False,
    retries: int = 3,
    backoff_factor: float = 1.5
) -> str:
    """Invokes LLM generate with a retry policy and exponential backoff."""
    last_ex = None
    logger = logging.getLogger("ATT.Core")
    for attempt in range(retries):
        try:
            result = await llm_client.generate(
                prompt=prompt,
                system_instruction=system_instruction,
                temperature=temperature,
                require_json=require_json
            )
            return result
        except Exception as e:
            last_ex = e
            if attempt == retries - 1:
                break
            sleep_time = backoff_factor ** attempt
            logger.warning(f"LLM generation failed (attempt {attempt+1}/{retries}): {e}. Retrying in {sleep_time:.2f}s...")
            await asyncio.sleep(sleep_time)
    raise LLMGenerationError(f"LLM generation failed after {retries} attempts: {last_ex}") from last_ex


class HandlerClientAdapter:
    """Wraps a global generator handler callback to conform to LLMClientProto."""
    def __init__(self, model_name: str, handler: Callable[..., str]):
        self.model_name = model_name
        self.handler = handler

    async def generate(
        self,
        prompt: Union[str, List[Dict[str, str]]],
        system_instruction: Optional[str] = None,
        temperature: float = 0.3,
        require_json: bool = False
    ) -> str:
        return await self.handler(
            model_name=self.model_name,
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=temperature,
            require_json=require_json
        )

class ManagerCriticClientAdapter:
    """Wraps the manager's critic client and global generator handler callback."""
    def __init__(self, manager: 'ATTManager'):
        self.manager = manager

    async def generate(
        self,
        prompt: Union[str, List[Dict[str, str]]],
        system_instruction: Optional[str] = None,
        temperature: float = 0.3,
        require_json: bool = False
    ) -> str:
        if self.manager.critic_client:
            return await self.manager.critic_client.generate(
                prompt=prompt,
                system_instruction=system_instruction,
                temperature=temperature,
                require_json=require_json
            )
        if self.manager.generator_handler:
            return await self.manager.generator_handler(
                model_name="critic",
                prompt=prompt,
                system_instruction=system_instruction,
                temperature=temperature,
                require_json=require_json
            )
        raise ValueError("No critic client or generator handler configured on ATTManager.")


class ATTConfig:
    """Configuration options for the ATT multi-agent framework."""
    def __init__(
        self,
        enable_dynamic_delegation: bool = True,
        max_delegation_depth: int = 2,
        min_subagent_team_size: int = 3,
        subagent_discussion_rounds: int = 2,
        react_max_steps: int = 5,
        inbox_summarize_threshold_chars: int = 1500,
        model_registry: Optional[dict] = None,
        max_migrations_per_team_discussion: int = 1,
        enable_membership_voting: bool = False,
        llm_max_retries: int = 3,
        llm_retry_backoff_factor: float = 1.5
    ):
        self.enable_dynamic_delegation = enable_dynamic_delegation
        self.max_delegation_depth = max_delegation_depth
        self.min_subagent_team_size = min_subagent_team_size
        self.subagent_discussion_rounds = subagent_discussion_rounds
        self.react_max_steps = react_max_steps
        self.inbox_summarize_threshold_chars = inbox_summarize_threshold_chars
        self.model_registry = model_registry or {}
        self.max_migrations_per_team_discussion = max_migrations_per_team_discussion
        self.enable_membership_voting = enable_membership_voting
        self.llm_max_retries = llm_max_retries
        self.llm_retry_backoff_factor = llm_retry_backoff_factor

class Agent:
    def __init__(self, name: str, role: str, llm_client: Optional[Any] = None, role_description: str = "", system_instructions: str = ""):
        self.name = name
        self.role = role
        self.llm_client = llm_client
        self.role_description = role_description
        self.system_instructions = system_instructions
        self.messages: List[Dict[str, str]] = []
        self.last_context: Optional[Dict[str, Any]] = None

    def launch_att(
        self,
        manager: 'ATTManager',
        member_count: int = 3,
        roles_and_presets: Optional[List[Tuple[str, str]]] = None,
        system_instructions: str = "",
        team_purpose: str = "Unspecified team purpose",
        roles_and_models: Optional[Dict[str, str]] = None,
        member_configs: Optional[Dict[str, Dict[str, Any]]] = None,
        is_public_visible: bool = False,
        initial_docs: Optional[Dict[str, str]] = None
    ) -> 'AgentTeam':
        """Allows this agent to launch a dynamic sub-team (Level $N$)."""
        child = manager.create_agent_team(
            creator=self,
            member_count=member_count,
            roles_and_presets=roles_and_presets,
            system_instructions=system_instructions,
            team_purpose=team_purpose,
            roles_and_models=roles_and_models,
            member_configs=member_configs,
            is_public_visible=is_public_visible,
            initial_docs=initial_docs
        )
        for team in manager.teams.values():
            if self in team.members:
                child.chapter_num = team.chapter_num
                break
        return child


class AgentTeam:
    def __init__(self, creator: Any, preset_name: str, team_purpose: str = "Unspecified team purpose"):
        self.team_id = f"AT-{uuid.uuid4().hex[:6]}"
        self.creator = creator
        self.preset_name = preset_name
        self.team_purpose = team_purpose
        self.team_progress = "Not started"
        self.proposals: Dict[str, Dict[str, Any]] = {}
        self.chapter_num: Optional[int] = None
        self.status_map: Dict[str, str] = {}
        self.members: List[Agent] = []
        
        self.child_teams: List['AgentTeam'] = []
        self.communication_rules: Dict[str, Any] = {
            "allow_sibling_talk": False,
            "rules": []
        }
        self.logger = logging.getLogger(f"AgentTeam:{self.team_id}")
        self.message_inbox: List[Dict[str, Any]] = []
        self.tools: Dict[str, Tool] = {}
        self._parent_team: Optional['AgentTeam'] = None
        self.migration_count = 0
        self.doc_library: Optional[DocumentLibrary] = None


    @property
    def parent_team(self) -> Optional['AgentTeam']:
        if self._parent_team is not None:
            return self._parent_team
        if isinstance(self.creator, AgentTeam):
            return self.creator
        return None

    @property
    def depth(self) -> int:
        parent = self.parent_team
        return (parent.depth + 1) if parent else 1

    def add_child_team(self, child: 'AgentTeam'):
        self.child_teams.append(child)

    def launch_att(
        self,
        manager: 'ATTManager',
        member_count: int = 3,
        roles_and_presets: Optional[List[Tuple[str, str]]] = None,
        system_instructions: str = "",
        team_purpose: str = "Unspecified team purpose",
        roles_and_models: Optional[Dict[str, str]] = None,
        member_configs: Optional[Dict[str, Dict[str, Any]]] = None,
        is_public_visible: bool = False,
        initial_docs: Optional[Dict[str, str]] = None
    ) -> 'AgentTeam':
        """Allows any active team to recursively launch their own child AT."""
        child = manager.create_agent_team(
            creator=self,
            member_count=member_count,
            roles_and_presets=roles_and_presets,
            system_instructions=system_instructions,
            team_purpose=team_purpose,
            roles_and_models=roles_and_models,
            member_configs=member_configs,
            is_public_visible=is_public_visible,
            initial_docs=initial_docs
        )
        child.chapter_num = self.chapter_num
        return child


    def receive_message(self, message: Dict[str, Any]):
        self.message_inbox.append(message)
        self.logger.info(f"Team {self.team_id} received message of type '{message.get('type')}' from '{message.get('from')}'")
        if getattr(self, "manager", None):
            self.manager._auto_save()

    async def execute_react_step(
        self,
        agent: Agent,
        prompt: str,
        system_instruction: str,
        max_steps: int = 5,
        manager: Optional['ATTManager'] = None
    ) -> str:
        """Executes a ReAct loop for a single agent inside the AT."""
        if not agent.llm_client:
            return "Error: Agent has no LLM client configured."

        self.status_map[agent.name] = "Thinking..."
        if manager and manager.on_status_change:
            manager.on_status_change(agent.name, "Thinking...")

        peer_context = ""
        if manager:
            peer_context = f"\n### ACTIVE AGENT TEAMS TOPOLOGY (Global Map)\n{manager.render_topology_tree()}\n"

        # Read configuration variables safely
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
        identity_header = (
            f"## AGENT IDENTITY PROFILE\n"
            f"- **Role Name**: {agent.role}\n"
            f"{role_desc_str}"
            f"- **Agent Name**: {agent.name}\n"
            f"- **Parent Team**: {self.team_id} (Preset: {self.preset_name})\n"
            f"- **Team Purpose**: {self.team_purpose}\n"
            f"- **Current Objective**: Cooperate in team tasks.\n"
            f"- **AT Delegation Depth**: {self.depth} / {max_depth}\n"
            f"{peer_context}"
            f"### AUTONOMY RULES\n"
            f"1. You can dynamically spawn child ATs using the `dispatch_subagent` tool to solve sub-problems.\n"
            f"2. You MUST NOT spawn child ATs if your Delegation Depth is already at the maximum ({max_depth}). If you need help at max depth, use `delegate_escalation` to ask your parent.\n"
            f"3. A valid AT MUST have at least {min_size} members.\n"
            f"4. You can dynamically request to migrate your team to a different parent team in the topology using the `request_migration` tool if it helps in task routing.\n"
            f"5. When creating an AT, you can assign models based on task complexity. Available models:\n"
            f"{model_options}\n"
        )

        try:
            # Handle Context Shift Notice
            current_context = {
                "team_id": self.team_id,
                "preset_name": self.preset_name,
                "team_purpose": self.team_purpose,
                "role": agent.role,
                "role_description": getattr(agent, "role_description", ""),
                "system_instructions": getattr(agent, "system_instructions", ""),
                "tools": sorted(list(self.tools.keys())) if getattr(self, "tools", None) else []
            }
            if agent.last_context and agent.last_context != current_context:
                tools_str = ""
                if current_context["tools"]:
                    for t_name in current_context["tools"]:
                        tool = self.tools[t_name]
                        tools_str += f"- {t_name}: {tool.description}\n"
                notice = (
                    f"*** SYSTEM NOTICE: CONTEXT SWITCH ***\n"
                    f"You are now acting in a different team environment:\n"
                    f"- Active Team: {self.team_id} (Preset: {self.preset_name})\n"
                    f"- Team Purpose: {self.team_purpose}\n"
                    f"- Your Role: {agent.role}\n"
                    f"- Your Role Description: {current_context['role_description']}\n"
                    f"- Your System Instructions: {current_context['system_instructions']}\n\n"
                    f"Available Tools in this team:\n{tools_str}\n"
                    f"Please review your prior memories and address the following prompt under your current role and tools."
                )
                agent.messages.append({"role": "system", "content": notice})
            agent.last_context = current_context

            # Append current prompt objective to private multi-turn history
            agent.messages.append({"role": "user", "content": prompt})

            if getattr(self, "tools", None):
                tools_desc = []
                for t_name, tool in self.tools.items():
                    tools_desc.append(f"- **{t_name}**: {tool.description}")
                tools_list_str = "\n".join(tools_desc)

                agent_sys_inst = f"### YOUR INDIVIDUAL MISSION\n{agent.system_instructions}\n\n" if getattr(agent, "system_instructions", "") else ""
                
                voting_context = ""
                if manager and manager.config.enable_membership_voting and self.proposals:
                    voting_lines = ["### ACTIVE MEMBERSHIP VOTES:"]
                    for vp_id, prop in self.proposals.items():
                        if prop.get("status") == "active":
                            voted_list = []
                            for voter, v_data in prop["votes"].items():
                                if v_data["public"]:
                                    voted_list.append(f"{voter}: {v_data['vote']} (Public)")
                                else:
                                    voted_list.append(f"Anonymous Voter: {v_data['vote']}")
                            voted_str = ", ".join(voted_list) if voted_list else "None"
                            remaining = [m.name for m in self.members if m.name not in prop["votes"]]
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
                        self.status_map[agent.name] = f"Thinking (Step {step+1}/{max_steps})..."
                        if manager and manager.on_status_change:
                            manager.on_status_change(agent.name, f"Thinking (Step {step+1}/{max_steps})...")

                        retries = manager.config.llm_max_retries if manager else 3
                        backoff = manager.config.llm_retry_backoff_factor if manager else 1.5
                        response = (await generate_with_retry(
                            llm_client=agent.llm_client,
                            prompt=agent.messages,
                            system_instruction=react_system_instruction,
                            temperature=0.3,
                            retries=retries,
                            backoff_factor=backoff
                        )).strip()

                        self.logger.info(f"Agent {agent.name} ReAct step {step+1} response:\n{response}")

                        agent.messages.append({"role": "assistant", "content": response})

                        # Trigger logging callback
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
                                self.team_id,
                                f"ReAct LLM Step | {agent.name} ({agent.role}) Step {step+1}",
                                log_content,
                                self.chapter_num
                            )

                        # Check for Final Answer
                        if "Final Answer:" in response:
                            final_ans_content = response.split("Final Answer:", 1)[1].strip()
                            if manager and manager.on_activity_added:
                                manager.on_activity_added(agent.name, "Final Answer", final_ans_content)
                            
                            return final_ans_content

                        # Parse Thought
                        thought_match = re.search(r"Thought:\s*(.*)", response, re.IGNORECASE)
                        if thought_match:
                            thought_content = thought_match.group(1).split("Action:")[0].strip()
                            if manager and manager.on_activity_added:
                                manager.on_activity_added(agent.name, "Thought", thought_content)

                        # Parse Action
                        tool_name = None
                        tool_args_str = None

                        # 1. Try XML-style match
                        xml_match = re.search(r'<action\s+name="(\w+)"\s*>(.*?)</action>', response, re.DOTALL | re.IGNORECASE)
                        if xml_match:
                            tool_name = xml_match.group(1).strip()
                            tool_args_str = xml_match.group(2).strip()
                            # Strip code block markers if the model wrapped args inside the XML tag
                            if tool_args_str.startswith("```") and tool_args_str.endswith("```"):
                                lines = tool_args_str.splitlines()
                                if lines[0].startswith("```"):
                                    lines = lines[1:]
                                if lines and lines[-1].endswith("```"):
                                    lines = lines[:-1]
                                tool_args_str = "\n".join(lines).strip()
                        else:
                            # 2. Try standard Action: func(args) match with robust markdown fence support and DOTALL
                            react_match = re.search(r'Action:\s*(?:```(?:python)?\s*)?(\w+)\((.*?)\)(?:\s*```)?', response, re.DOTALL | re.IGNORECASE)
                            if react_match:
                                tool_name = react_match.group(1).strip()
                                tool_args_str = react_match.group(2).strip()

                        if tool_name is not None:

                            def parse_args(args_str):
                                if not args_str:
                                    return [], {}

                                # 1. Split arguments by top-level commas (not inside quotes or nesting symbols)
                                chunks = []
                                current_chunk = []
                                in_single_quote = False
                                in_double_quote = False
                                escape = False
                                paren_depth = 0
                                bracket_depth = 0
                                brace_depth = 0

                                for char in args_str:
                                    if escape:
                                        escape = False
                                        current_chunk.append(char)
                                        continue
                                    if char == '\\':
                                        escape = True
                                        current_chunk.append(char)
                                        continue
                                    if char == "'" and not in_double_quote:
                                        in_single_quote = not in_single_quote
                                    elif char == '"' and not in_single_quote:
                                        in_double_quote = not in_double_quote

                                    if not in_single_quote and not in_double_quote:
                                        if char == '(':
                                            paren_depth += 1
                                        elif char == ')':
                                            paren_depth = max(0, paren_depth - 1)
                                        elif char == '[':
                                            bracket_depth += 1
                                        elif char == ']':
                                            bracket_depth = max(0, bracket_depth - 1)
                                        elif char == '{':
                                            brace_depth += 1
                                        elif char == '}':
                                            brace_depth = max(0, brace_depth - 1)
                                        elif char == ',' and paren_depth == 0 and bracket_depth == 0 and brace_depth == 0:
                                            chunks.append("".join(current_chunk).strip())
                                            current_chunk = []
                                            continue

                                    current_chunk.append(char)

                                chunks.append("".join(current_chunk).strip())

                                # 2. Helper to clean and parse value
                                def parse_val(val_str):
                                    val_str = val_str.strip()
                                    if not val_str:
                                        return ""
                                    try:
                                        return ast.literal_eval(val_str)
                                    except Exception:
                                        # Fallback to unquoting
                                        if (val_str.startswith("'") and val_str.endswith("'")) or (val_str.startswith('"') and val_str.endswith('"')):
                                            return val_str[1:-1]
                                        if val_str.lower() == "true":
                                            return True
                                        if val_str.lower() == "false":
                                            return False
                                        if val_str.lower() == "none":
                                            return None
                                        return val_str

                                # 3. Process each chunk
                                args = []
                                kwargs = {}

                                for chunk in chunks:
                                    if not chunk:
                                        continue
                                    # Find top-level '=' in the chunk
                                    eq_idx = -1
                                    c_in_single_quote = False
                                    c_in_double_quote = False
                                    c_escape = False
                                    c_paren = 0
                                    c_bracket = 0
                                    c_brace = 0

                                    for idx, char in enumerate(chunk):
                                        if c_escape:
                                            c_escape = False
                                            continue
                                        if char == '\\':
                                            c_escape = True
                                            continue
                                        if char == "'" and not c_in_double_quote:
                                            c_in_single_quote = not c_in_single_quote
                                        elif char == '"' and not c_in_single_quote:
                                            c_in_double_quote = not c_in_double_quote

                                        if not c_in_single_quote and not c_in_double_quote:
                                            if char == '(':
                                                c_paren += 1
                                            elif char == ')':
                                                c_paren = max(0, c_paren - 1)
                                            elif char == '[':
                                                c_bracket += 1
                                            elif char == ']':
                                                c_bracket = max(0, c_bracket - 1)
                                            elif char == '{':
                                                c_brace += 1
                                            elif char == '}':
                                                c_brace = max(0, c_brace - 1)
                                            elif char == '=' and c_paren == 0 and c_bracket == 0 and c_brace == 0:
                                                eq_idx = idx
                                                break

                                    if eq_idx != -1:
                                        k = chunk[:eq_idx].strip()
                                        if (k.startswith("'") and k.endswith("'")) or (k.startswith('"') and k.endswith('"')):
                                            k = k[1:-1]
                                        v_str = chunk[eq_idx+1:].strip()
                                        kwargs[k] = parse_val(v_str)
                                    else:
                                        args.append(parse_val(chunk))

                                return args, kwargs

                            args, kwargs = parse_args(tool_args_str)

                            if tool_name in self.tools:
                                tool_obj = self.tools[tool_name]
                                self.logger.info(f"Executing tool: {tool_name} with args={args}, kwargs={kwargs}")
                                
                                self.status_map[agent.name] = f"Executing Tool: {tool_name}"
                                if manager and manager.on_status_change:
                                    manager.on_status_change(agent.name, f"Executing Tool: {tool_name}")
                                if manager and manager.on_activity_added:
                                    manager.on_activity_added(agent.name, "Action", f"{tool_name}({tool_args_str})")

                                # Audit execution if an auditor is registered
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
                                
                                self.status_map[agent.name] = "Thinking..."
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

                            self.logger.info(f"Tool {tool_name} observation: {observation}")
                            
                            # Log tool callback
                            if manager and manager.on_log_append:
                                log_content = (
                                    f"AGENT: {agent.name}\n"
                                    f"ROLE: {agent.role}\n"
                                    f"ACTION: {tool_name}({tool_args_str})\n"
                                    f"OBSERVATION:\n{observation}\n"
                                )
                                manager.on_log_append(
                                    self.team_id,
                                    f"ReAct Tool Call | {agent.name} ({agent.role})",
                                    log_content,
                                    self.chapter_num
                                )

                            agent.messages.append({"role": "user", "content": f"Observation: {observation}"})
                        else:
                            if step == max_steps - 1:
                                return response
                            agent.messages.append({"role": "user", "content": "Observation: Please output either 'Action: tool_name(args)' or 'Final Answer: <content>'."})
                    except ATTException as e:
                        raise e
                    except Exception as e:
                        self.logger.error(f"Error in ReAct step {step+1} for agent {agent.name}: {e}")
                        return f"Error executing task during ReAct loop: {e}"

                return "Error: ReAct loop exceeded maximum steps without producing a Final Answer."

            else:
                # Fallback to direct call if no tools are bound
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
                    response = (await generate_with_retry(
                        llm_client=agent.llm_client,
                        prompt=agent.messages,
                        system_instruction=full_system_instruction,
                        temperature=0.3,
                        retries=retries,
                        backoff_factor=backoff
                    )).strip()
                    
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
                            self.team_id,
                            f"Direct LLM Call | {agent.name} ({agent.role})",
                            log_content,
                            self.chapter_num
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
                    self.logger.error(f"Agent {agent.name} execution error: {e}")
                    return f"Error executing task: {e}"
        finally:
            self.status_map[agent.name] = "Idle"
            if manager and manager.on_status_change:
                manager.on_status_change(agent.name, "Idle")
            if manager:
                manager._auto_save()

class NegotiationBroker:
    """Coordinates sibling and cross-lineage communication permissions."""
    def __init__(self, manager: 'ATTManager'):
        self.manager = manager
        self.logger = logging.getLogger("NegotiationBroker")
        self.peer_talk_agreements = set() # Set of Tuple[str, str] (sender_id, recipient_id)

    async def negotiate_communication(self, sender: AgentTeam, recipient: AgentTeam, mode: str = "proxied") -> bool:
        sender_parent = sender.parent_team or self.manager.find_parent_team(sender)
        recipient_parent = recipient.parent_team or self.manager.find_parent_team(recipient)

        if sender_parent and recipient_parent and sender_parent.team_id == recipient_parent.team_id:
            parent = sender_parent
            allow = parent.communication_rules.get("allow_sibling_talk", False)
            self.logger.info(f"Sibling negotiation between {sender.team_id} and {recipient.team_id}: Parent {parent.team_id} decision={allow}")
            return allow

        # Check for negotiated cross-lineage peer agreement
        pair = (sender.team_id, recipient.team_id)
        if pair in self.peer_talk_agreements:
            return True

        self.logger.warning(f"Communication denied between {sender.team_id} and {recipient.team_id}. No active agreement exists.")
        return False

    async def establish_peer_agreement(self, sender: AgentTeam, recipient: AgentTeam, mode: str = "proxied") -> bool:
        sender_parent = sender.parent_team or self.manager.find_parent_team(sender)
        recipient_parent = recipient.parent_team or self.manager.find_parent_team(recipient)

        if not sender_parent or not recipient_parent:
            self.logger.warning(f"Lineage incomplete. Cannot establish peer agreement between {sender.team_id} and {recipient.team_id}.")
            return False

        self.logger.info(f"Cross-lineage peer talk negotiation requested between {sender.team_id} and {recipient.team_id}.")
        success = await self._run_parent_negotiation_loop(sender_parent, recipient_parent, mode)
        if success:
            self.peer_talk_agreements.add((sender.team_id, recipient.team_id))
            self.manager._auto_save()
            return True
        return False

    async def _run_parent_negotiation_loop(self, p1: AgentTeam, p2: AgentTeam, mode: str) -> bool:
        self.logger.info(f"Parents {p1.team_id} and {p2.team_id} are negotiating communication channel (mode: {mode})...")
        if mode in {"proxied", "indirect", "rule_gated"}:
            self.logger.info("Negotiation loop succeeded: communication contract established.")
            return True
        self.logger.warning(f"Negotiation loop rejected: mode '{mode}' is unsupported or unsafe.")
        return False

class ATTManager:
    """Master controller managing the overall ATT (AI Team Team) topology."""
    def __init__(self, root_ai: Agent, critic_client: Optional[Any] = None, config: Optional[ATTConfig] = None, db_path: Optional[str] = None):
        self.root_ai = root_ai
        self.critic_client = critic_client
        self.config = config or ATTConfig()
        self.db_path = db_path
        self.agents: Dict[str, Agent] = {root_ai.name: root_ai}
        self.teams: Dict[str, AgentTeam] = {}
        self.broker = NegotiationBroker(self)
        self.llm_clients: Dict[str, Any] = {}
        
        self.model_configs: Dict[str, Dict[str, Any]] = {}
        self.generator_handler: Optional[Callable[..., str]] = None
        
        from .supervision import SupervisoryTeam
        self.supervisor = SupervisoryTeam(root_ai, ManagerCriticClientAdapter(self), manager=self)
        self.logger = logging.getLogger("ATTManager")
        self.tools_context: Dict[str, Any] = {}
        self.libraries: Dict[str, DocumentLibrary] = {}
        self.library_permissions: Dict[str, Dict[str, Dict[str, str]]] = {} # lib_id -> path -> team_id -> permission

        
        # Public Tool registries
        self.global_tools: Dict[str, Tool] = {}
        self.tool_auditors: Dict[str, Callable[..., Tuple[bool, str]]] = {}
        
        # Event callbacks
        self.on_status_change: Optional[Callable[[str, str], None]] = None
        self.on_activity_added: Optional[Callable[[str, str, str], None]] = None
        self.on_log_append: Optional[Callable[[str, str, str, Optional[int]], None]] = None
        self.on_team_migration: Optional[Callable[[str, Optional[str], str], None]] = None

        # Base preset configurations
        self.presets: Dict[str, dict] = {
            "generic": {
                "description": "Default Generic AT",
                "system_instructions": "Cooperate to solve the task.",
                "roles": [
                    ("Specialist_A", "Contributes key analytical viewpoints."),
                    ("Specialist_B", "Contributes creative and structural solutions."),
                    ("Arbitrator", "Synthesizes the final decision.")
                ]
            }
        }

    def register_tool(self, name: str, description: str, func: Callable[..., Any]):
        """Registers a custom utility tool to all teams."""
        self.global_tools[name] = Tool(name, description, func)
        # Bind to existing teams
        for team in self.teams.values():
            team.tools[name] = self.global_tools[name]

    def register_tool_auditor(self, tool_name: str, auditor_func: Callable[..., Tuple[bool, str]]):
        """Registers an auditing hook executed before specific tool calls."""
        self.tool_auditors[tool_name] = auditor_func

    def register_model(self, name: str, config: Dict[str, Any]):
        """Registers a unified model configuration (e.g. metadata, type, ai_note)."""
        self.model_configs[name] = config

    def register_generator_handler(self, handler: Callable[..., str]):
        """Registers a global callback handler for generating text from a model alias."""
        self.generator_handler = handler

    def register_preset(self, name: str, description: str, system_instructions: str, roles: List[Tuple[str, str]]):
        """Registers a custom dynamic committee preset."""
        self.presets[name] = {
            "description": description,
            "system_instructions": system_instructions,
            "roles": roles
        }

    def get_preset(self, name: str) -> dict:
        return self.presets.get(name, self.presets["generic"])

    def register_tools_context(self, context: Dict[str, Any]):
        """Registers system dependencies/resources context for binding tools to AIs."""
        self.tools_context.update(context)
        from .tool import get_default_tools
        # Bind generic tools to existing teams
        for team in self.teams.values():
            team.tools.update(get_default_tools(self.tools_context, team))
            # Also bind globally registered tools
            team.tools.update(self.global_tools)

    def create_agent_team(
        self,
        creator: Any,
        member_count: int = 3,
        roles_and_presets: List[Tuple[str, str]] = None,
        preset_name: str = "custom",
        system_instructions: str = "",
        team_purpose: str = "Unspecified team purpose",
        roles_and_models: Optional[Dict[str, str]] = None,
        member_configs: Optional[Dict[str, Dict[str, Any]]] = None,
        is_public_visible: bool = False,
        initial_docs: Optional[Dict[str, str]] = None
    ) -> AgentTeam:

        """Dynamically spawns a new recursive Agent Team (AT)."""
        if member_configs:
            member_count = len(member_configs)
            
        min_size = self.config.min_subagent_team_size
        assert member_count >= min_size, f"An Agent Team must contain at least {min_size} members to debate properly."
        
        team = AgentTeam(creator=creator, preset_name=preset_name, team_purpose=team_purpose)
        team.manager = self
        if isinstance(creator, AgentTeam):
            team._parent_team = creator
        else:
            team._parent_team = self.find_parent_team(team)
        
        if isinstance(creator, AgentTeam):
            team.chapter_num = creator.chapter_num
        elif isinstance(creator, Agent):
            for t in self.teams.values():
                if creator in t.members:
                    team.chapter_num = t.chapter_num
                    break

        def get_agent_client_by_name(client_name: Optional[str]) -> Any:
            critic_wrapper = ManagerCriticClientAdapter(self)
            if client_name:
                if client_name in self.llm_clients:
                    return self.llm_clients[client_name]
                elif client_name in self.model_configs and self.generator_handler:
                    return HandlerClientAdapter(client_name, self.generator_handler)
                else:
                    self.logger.warning(f"Client '{client_name}' not found in registry. Falling back to default critic client.")
            return self.critic_client if self.critic_client is not None else critic_wrapper

        def get_agent_client(role_name: str, agent_name: str) -> Any:
            client_name = None
            if roles_and_models:
                client_name = roles_and_models.get(role_name) or roles_and_models.get(agent_name)
            return get_agent_client_by_name(client_name)

        members = []
        if member_configs:
            for role_name, config in member_configs.items():
                if isinstance(config, Agent):
                    agent = config
                    agent.role = role_name
                    self.agents[agent.name] = agent
                    members.append(agent)
                elif isinstance(config, dict) and config.get("hire_agent") in self.agents:
                    agent = self.agents[config["hire_agent"]]
                    agent.role = role_name
                    members.append(agent)
                elif isinstance(config, dict) and config.get("model") in self.agents:
                    agent = self.agents[config["model"]]
                    agent.role = role_name
                    members.append(agent)
                else:
                    model_alias = config.get("model")
                    role_desc = config.get("role_description", "")
                    sys_inst = config.get("system_instructions", "")
                    agent_name = f"Dynamic_{role_name}_{team.team_id.split('-')[1]}"
                    client = get_agent_client_by_name(model_alias)
                    agent = Agent(
                        name=agent_name,
                        role=role_name,
                        llm_client=client,
                        role_description=role_desc,
                        system_instructions=sys_inst
                    )
                    self.agents[agent_name] = agent
                    members.append(agent)
        elif roles_and_presets:
            for name, role in roles_and_presets:
                agent = Agent(name=name, role=role, llm_client=get_agent_client(role, name))
                self.agents[name] = agent
                members.append(agent)
        else:
            preset = self.get_preset(preset_name)
            roles = preset.get("roles", [])
            if len(roles) >= member_count:
                for name, role in roles[:member_count]:
                    agent = Agent(name=name, role=role, llm_client=get_agent_client(role, name))
                    self.agents[name] = agent
                    members.append(agent)
            else:
                for i in range(member_count):
                    m_name = f"{team.team_id}_member_{i+1}"
                    agent = Agent(name=m_name, role="Specialist", llm_client=get_agent_client("Specialist", m_name))
                    self.agents[m_name] = agent
                    members.append(agent)

        team.members = members
        team.system_instructions = system_instructions or self.get_preset(preset_name).get("system_instructions", "")
        
        # Bind generic tools
        from .tool import get_default_tools
        team.tools.update(get_default_tools(self.tools_context, team))
        
        # Bind globally registered custom tools
        team.tools.update(self.global_tools)
            
        self.teams[team.team_id] = team
        
        # Instantiate and associate default built-in DocLib for the team
        lib_id = f"DL-{team.team_id}"
        lib_name = f"{team.team_id} Built-in Library"
        lib_desc = f"Default document library for team {team.team_id}."
        lib = DocumentLibrary(
            lib_id=lib_id,
            name=lib_name,
            owner_team_id=team.team_id,
            description=lib_desc,
            is_public_visible=is_public_visible
        )
        self.libraries[lib_id] = lib
        team.doc_library = lib
        
        # Write initial_docs if any
        if initial_docs:
            for file_path, content in initial_docs.items():
                lib.write_file(file_path, content)

        
        if isinstance(creator, AgentTeam):
            creator.add_child_team(team)
        elif isinstance(creator, Agent):
            parent_t = self.find_parent_team(team)
            if parent_t:
                parent_t.add_child_team(team)
            
        self.logger.info(f"Successfully spawned Agent Team {team.team_id} (N={len(members)}, Preset: {preset_name}) spawned by {creator.name if hasattr(creator, 'name') else creator.team_id}")
        self._auto_save()
        return team

    def find_parent_team(self, target: AgentTeam) -> Optional[AgentTeam]:
        for team in self.teams.values():
            if target in team.child_teams:
                return team
        
        creator = target.creator
        if isinstance(creator, Agent):
            for team in self.teams.values():
                if creator in team.members:
                    return team
        return None
        
    def check_library_access(self, team_id: str, lib_id: str, path: str, required_permission: str) -> bool:
        """
        Checks if a team has the required permission ('READ' or 'WRITE') for a path in a DocLib.
        Owner of the library always has 'WRITE' (which includes 'READ') for all paths.
        """
        if lib_id not in self.libraries:
            return False
        lib = self.libraries[lib_id]
        if lib.owner_team_id == team_id:
            return True
            
        # Check explicit permissions
        if lib_id not in self.library_permissions:
            return False
            
        # Find prefix/parent path matches.
        clean_path = "/" + path.strip("/").replace("\\", "/")
        if clean_path == "/":
            parts = ["/"]
        else:
            parts = []
            current = clean_path
            while current and current != "/":
                parts.append(current)
                current = os.path.dirname(current)
            parts.append("/")
            
        # Check permissions for each segment
        for p in parts:
            if p in self.library_permissions[lib_id]:
                team_perms = self.library_permissions[lib_id][p]
                if team_id in team_perms:
                    perm = team_perms[team_id]
                    if required_permission == "READ":
                        if perm in {"READ", "WRITE"}:
                            return True
                    elif required_permission == "WRITE":
                        if perm == "WRITE":
                            return True
        return False


    def render_topology_tree(self) -> str:
        """Renders the active hierarchical agent team lineage as an indented tree."""
        lines = [f"- [Root AI: {self.root_ai.name}] (Level 0)"]
        
        level_1_teams = []
        for team in self.teams.values():
            if team.parent_team is None:
                level_1_teams.append(team)
                
        def traverse(team, depth=1):
            indent = "  " * depth
            prefix = "└── " if depth > 1 else "├── "
            lines.append(f"{indent}{prefix}{team.team_id} (Purpose: {team.team_purpose} | Progress: {team.team_progress}) [Level {team.depth}]")
            for child in team.child_teams:
                traverse(child, depth + 1)
                
        for t in level_1_teams:
            traverse(t, 1)
            
        return "\n".join(lines)

    async def negotiate_and_execute_migration(self, team: AgentTeam, target_parent: AgentTeam, rationale: str) -> Tuple[bool, str]:
        """Arbitrates the migration of an AgentTeam using the critic LLM client, updates structure, and broadcasts alerts."""
        limit = self.config.max_migrations_per_team_discussion
        current_count = getattr(team, "migration_count", 0)
        if current_count >= limit:
            return False, f"Rejected: Cannot request migration. Maximum migrations per discussion session ({limit}) reached."

        current_parent = team.parent_team
        current_parent_id = current_parent.team_id if current_parent else "Root AI"
        
        arbitration_prompt = (
            f"Arbitrate a request to reorganize the agent team hierarchy.\n\n"
            f"Team requesting migration: {team.team_id}\n"
            f"Current Purpose: {team.team_purpose}\n"
            f"Current Parent Team: {current_parent_id} (Purpose: {current_parent.team_purpose if current_parent else 'Root Coordinator'})\n\n"
            f"Target Parent Team: {target_parent.team_id}\n"
            f"Target Parent Purpose: {target_parent.team_purpose}\n\n"
            f"Migration Rationale provided by the team:\n\"{rationale}\"\n\n"
            f"Please evaluate if this migration is logical, beneficial for task progress, and does not create redundant hierarchy.\n"
            f"Output exactly a JSON payload:\n"
            f"{{\n"
            f"  \"approved\": true | false,\n"
            f"  \"reason\": \"Reasoning for your arbitration decision...\"\n"
            f"}}"
        )
        
        try:
            response = await generate_with_retry(
                llm_client=self.critic_client,
                prompt=arbitration_prompt,
                system_instruction="You are a strict, objective Systems Architect Arbiter. Evaluate organizational restructuring proposals.",
                temperature=0.2,
                require_json=True,
                retries=self.config.llm_max_retries,
                backoff_factor=self.config.llm_retry_backoff_factor
            )
            if "```" in response:
                response = response.replace("```json", "").replace("```", "").strip()
            data = json.loads(response)
            approved = bool(data.get("approved", False))
            reason = str(data.get("reason", "No reason provided."))
            
            if approved:
                # 1. Update structural links
                if current_parent:
                    if team in current_parent.child_teams:
                        current_parent.child_teams.remove(team)
                
                target_parent.add_child_team(team)
                team._parent_team = target_parent
                team.migration_count = current_count + 1
                
                # 2. Dispatch notifications
                if current_parent:
                    current_parent.receive_message({
                        "from": "System/Migration",
                        "type": "migration_alert",
                        "reason": f"Child team '{team.team_id}' has migrated to parent '{target_parent.team_id}'. Rationale: {rationale}"
                    })
                target_parent.receive_message({
                    "from": "System/Migration",
                    "type": "migration_alert",
                    "reason": f"Team '{team.team_id}' has joined as your child. Rationale: {rationale}"
                })
                team.receive_message({
                    "from": "System/Migration",
                    "type": "migration_alert",
                    "reason": f"Your team has successfully migrated to parent '{target_parent.team_id}'. Arbiter Reason: {reason}"
                })
                
                # 3. Trigger callback
                if self.on_team_migration:
                    self.on_team_migration(team.team_id, current_parent_id if current_parent else None, target_parent.team_id)
                
                self.logger.info(f"Migration of team {team.team_id} to parent {target_parent.team_id} approved. Reason: {reason}")
                self._auto_save()
                return True, f"Approved: {reason}"
            else:
                self.logger.info(f"Migration of team {team.team_id} to parent {target_parent.team_id} rejected. Reason: {reason}")
                return False, f"Rejected: {reason}"
                
        except Exception as e:
            self.logger.error(f"Migration arbitration error: {e}")
            return False, f"Arbitration error: {e}"

    async def execute_team_discussion(self, team: AgentTeam, prompt: str, rounds: int = 2) -> str:
        """Executes a multi-agent debate session inside the AT, monitored by the Supervisor.
        
        Agents within the same round execute concurrently via asyncio.gather.
        Between rounds, dialog history is injected so agents can build on previous outputs.
        """
        team.migration_count = 0
        self.logger.info(f"Executing discussion in team {team.team_id} (rounds={rounds})...")
        
        inbox_context = ""
        if team.message_inbox:
            inbox_lines = []
            for msg in team.message_inbox:
                inbox_lines.append(f"- **From [{msg.get('from', 'Unknown')}]**: {msg.get('reason') or msg.get('objective') or str(msg)}")
            
            raw_inbox_text = chr(10).join(inbox_lines)
            threshold = self.config.inbox_summarize_threshold_chars
            if len(raw_inbox_text) > threshold and self.critic_client:
                self.logger.info("Inbox context too large, summarizing before injection...")
                summary_prompt = f"Summarize the following system alerts and escalations concisely:\n\n{raw_inbox_text}"
                try:
                    raw_inbox_text = await generate_with_retry(
                        llm_client=self.critic_client,
                        prompt=summary_prompt,
                        system_instruction="You are a strict system summarizer. Compress alerts while keeping critical facts and failures.",
                        temperature=0.1,
                        retries=self.config.llm_max_retries,
                        backoff_factor=self.config.llm_retry_backoff_factor
                    )
                except Exception as e:
                    self.logger.warning(f"Failed to summarize inbox: {e}")
                    
            inbox_context = (
                f"\n\n### UNRESOLVED INBOX ALERTS & ESCALATIONS\n"
                f"Your team has received the following signals from your descendants or supervisor:\n"
                f"{raw_inbox_text}\n"
                f"Please address or incorporate these alerts into your decision-making."
            )
            team.message_inbox = []

        dialog_history = []
        base_prompt = f"{prompt}{inbox_context}"
        last_round_answers = {}
        
        for r in range(1, rounds + 1):
            tasks = []
            for agent in team.members:
                if r == 1:
                    round_prompt = base_prompt
                else:
                    other_answers = []
                    for other_agent in team.members:
                        if other_agent.name != agent.name:
                            ans = last_round_answers.get((r - 1, other_agent.name), "No response.")
                            other_answers.append(f"{other_agent.name} (Role: {other_agent.role}): {ans}")
                    
                    round_prompt = (
                        f"Here is the discussion from Round {r - 1}:\n"
                        + "\n".join(other_answers) + "\n\n"
                        f"Please continue the discussion. Build on or challenge their arguments."
                    )

                async def _run_agent(ag=agent, pr=round_prompt):
                    return await team.execute_react_step(
                        agent=ag,
                        prompt=pr,
                        system_instruction=team.system_instructions,
                        max_steps=self.config.react_max_steps,
                        manager=self
                    )
                tasks.append(_run_agent())

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for agent, result in zip(team.members, results):
                if isinstance(result, ATTException):
                    self.logger.error(f"Failed to execute discussion step due to ATT error: {result}")
                    await self.supervisor.report_anomaly(team, f"LLM client invocation error: {result}", self)
                    raise result
                elif isinstance(result, Exception):
                    self.logger.error(f"Agent {agent.name} encountered an error: {result}")
                    ans = f"Error: {result}"
                else:
                    ans = str(result)
                
                last_round_answers[(r, agent.name)] = ans
                dialog_history.append(f"{agent.name}: {ans}")

        transcript = "\n".join(dialog_history)
        
        # Run supervisory audit
        is_healthy, reason = await self.supervisor.audit_team_dialog(team, transcript)
        if not is_healthy:
            await self.supervisor.report_anomaly(team, reason, self)
            
        # Log debate transcript using logger callback
        if self.on_log_append:
            log_title = f"Synthesized Debate Transcript | {team.team_id} ({team.preset_name}) - Rounds: {rounds}"
            log_content = (
                f"TEAM_ID: {team.team_id}\n"
                f"PRESET_NAME: {team.preset_name}\n"
                f"PURPOSE: {team.team_purpose}\n"
                f"PROMPT: {prompt}\n"
                f"--- SYNTHESIZED TRANSCRIPT BEGIN ---\n"
                f"{transcript}\n"
                f"--- SYNTHESIZED TRANSCRIPT END ---\n"
                f"AUDIT STATUS: {'Healthy' if is_healthy else 'Anomaly Detected'}\n"
                f"AUDIT REASON: {reason}\n"
            )
            self.on_log_append(
                team.team_id,
                log_title,
                log_content,
                team.chapter_num
            )

        self._auto_save()
        return transcript

    def _auto_save(self):
        """Triggers a snapshot save if a database path is configured."""
        if self.db_path:
            self.save_state()

    def save_state(self, db_path: Optional[str] = None):
        """Serializes the entire manager topology, agents, teams, libraries, etc. to SQLite."""
        target_path = db_path or self.db_path
        if not target_path:
            return

        try:
            conn = sqlite3.connect(target_path)
            try:
                # Disable Foreign Keys during save to allow arbitrary insertion order
                conn.execute("PRAGMA foreign_keys = OFF;")
                
                # Create Tables
                conn.execute("""
                CREATE TABLE IF NOT EXISTS manager_config (
                    config_key TEXT PRIMARY KEY,
                    config_value TEXT
                );
                """)
                conn.execute("""
                CREATE TABLE IF NOT EXISTS agents (
                    name TEXT PRIMARY KEY,
                    role TEXT,
                    role_description TEXT,
                    system_instructions TEXT,
                    model_alias TEXT,
                    last_context TEXT
                );
                """)
                conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_name TEXT,
                    role TEXT,
                    content TEXT,
                    created_at REAL,
                    FOREIGN KEY(agent_name) REFERENCES agents(name) ON DELETE CASCADE
                );
                """)
                conn.execute("""
                CREATE TABLE IF NOT EXISTS teams (
                    team_id TEXT PRIMARY KEY,
                    preset_name TEXT,
                    team_purpose TEXT,
                    team_progress TEXT,
                    depth INTEGER,
                    chapter_num INTEGER,
                    parent_team_id TEXT,
                    migration_count INTEGER,
                    creator_type TEXT,
                    creator_id TEXT,
                    communication_rules TEXT,
                    status_map TEXT,
                    system_instructions TEXT
                );
                """)
                conn.execute("""
                CREATE TABLE IF NOT EXISTS team_members (
                    team_id TEXT,
                    agent_name TEXT,
                    PRIMARY KEY(team_id, agent_name),
                    FOREIGN KEY(team_id) REFERENCES teams(team_id) ON DELETE CASCADE,
                    FOREIGN KEY(agent_name) REFERENCES agents(name) ON DELETE CASCADE
                );
                """)
                conn.execute("""
                CREATE TABLE IF NOT EXISTS team_inbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    team_id TEXT,
                    sender TEXT,
                    msg_type TEXT,
                    payload TEXT,
                    created_at REAL,
                    FOREIGN KEY(team_id) REFERENCES teams(team_id) ON DELETE CASCADE
                );
                """)
                conn.execute("""
                CREATE TABLE IF NOT EXISTS team_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    team_id TEXT,
                    action TEXT,
                    target TEXT,
                    initiator_type TEXT,
                    initiator_name TEXT,
                    rationale TEXT,
                    proposed_details TEXT,
                    votes TEXT,
                    status TEXT,
                    FOREIGN KEY(team_id) REFERENCES teams(team_id) ON DELETE CASCADE
                );
                """)
                conn.execute("""
                CREATE TABLE IF NOT EXISTS broker_agreements (
                    sender_team_id TEXT,
                    recipient_team_id TEXT,
                    PRIMARY KEY(sender_team_id, recipient_team_id)
                );
                """)
                conn.execute("""
                CREATE TABLE IF NOT EXISTS libraries (
                    lib_id TEXT PRIMARY KEY,
                    name TEXT,
                    owner_team_id TEXT,
                    description TEXT,
                    is_public_visible INTEGER
                );
                """)
                conn.execute("""
                CREATE TABLE IF NOT EXISTS library_permissions (
                    lib_id TEXT,
                    path TEXT,
                    team_id TEXT,
                    permission TEXT,
                    PRIMARY KEY(lib_id, path, team_id)
                );
                """)
                conn.execute("""
                CREATE TABLE IF NOT EXISTS doc_lib_files (
                    lib_id TEXT,
                    path TEXT,
                    content TEXT,
                    PRIMARY KEY(lib_id, path),
                    FOREIGN KEY(lib_id) REFERENCES libraries(lib_id) ON DELETE CASCADE
                );
                """)

                # Clear Existing Data
                tables = [
                    "doc_lib_files", "library_permissions", "libraries", "broker_agreements",
                    "team_proposals", "team_inbox", "team_members", "teams", "agent_messages", "agents", "manager_config"
                ]
                for t in tables:
                    conn.execute(f"DELETE FROM {t};")

                # 1. Save Configs
                att_config_data = json.dumps(self.config.__dict__)
                conn.execute("INSERT INTO manager_config (config_key, config_value) VALUES (?, ?);", ("att_config", att_config_data))
                if self.root_ai:
                    conn.execute("INSERT INTO manager_config (config_key, config_value) VALUES (?, ?);", ("root_ai_name", self.root_ai.name))

                # 2. Save Agents
                for agent in self.agents.values():
                    model_alias = None
                    if agent.llm_client:
                        from unittest.mock import Mock
                        if isinstance(agent.llm_client, Mock):
                            model_alias = "mock_client"
                        elif hasattr(agent.llm_client, "model_name") and not isinstance(agent.llm_client.model_name, Mock):
                            model_alias = str(agent.llm_client.model_name)
                        elif hasattr(agent.llm_client, "manager") and not isinstance(agent.llm_client.manager, Mock):
                            model_alias = "critic"
                    
                    last_ctx_json = json.dumps(agent.last_context) if agent.last_context else None
                    conn.execute(
                        "INSERT INTO agents (name, role, role_description, system_instructions, model_alias, last_context) VALUES (?, ?, ?, ?, ?, ?);",
                        (agent.name, agent.role, getattr(agent, "role_description", ""), getattr(agent, "system_instructions", ""), model_alias, last_ctx_json)
                    )

                    for idx, msg in enumerate(agent.messages):
                        conn.execute(
                            "INSERT INTO agent_messages (agent_name, role, content, created_at) VALUES (?, ?, ?, ?);",
                            (agent.name, msg.get("role", "user"), msg.get("content", ""), time.time() + idx * 0.001)
                        )

                # 3. Save Teams
                for team in self.teams.values():
                    parent_id = team.parent_team.team_id if team.parent_team else None
                    
                    creator_type = None
                    creator_id = None
                    if team.creator:
                        if hasattr(team.creator, "name"):
                            creator_type = "agent"
                            creator_id = team.creator.name
                        elif hasattr(team.creator, "team_id"):
                            creator_type = "team"
                            creator_id = team.creator.team_id
                            
                    comm_rules_json = json.dumps(team.communication_rules)
                    status_map_json = json.dumps(team.status_map)
                    
                    conn.execute(
                        """INSERT INTO teams (
                            team_id, preset_name, team_purpose, team_progress, depth, chapter_num, parent_team_id,
                            migration_count, creator_type, creator_id, communication_rules, status_map, system_instructions
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);""",
                        (
                            team.team_id, team.preset_name, team.team_purpose, team.team_progress, team.depth,
                            team.chapter_num, parent_id, team.migration_count, creator_type, creator_id,
                            comm_rules_json, status_map_json, getattr(team, "system_instructions", "")
                        )
                    )

                    for member in team.members:
                        conn.execute("INSERT INTO team_members (team_id, agent_name) VALUES (?, ?);", (team.team_id, member.name))

                    for idx, msg in enumerate(team.message_inbox):
                        sender = msg.get("from", "Unknown")
                        msg_type = msg.get("type", "Unknown")
                        payload = json.dumps(msg)
                        conn.execute(
                            "INSERT INTO team_inbox (team_id, sender, msg_type, payload, created_at) VALUES (?, ?, ?, ?, ?);",
                            (team.team_id, sender, msg_type, payload, time.time() + idx * 0.001)
                        )

                    for prop_id, prop in team.proposals.items():
                        conn.execute(
                            """INSERT INTO team_proposals (
                                proposal_id, team_id, action, target, initiator_type, initiator_name, rationale, proposed_details, votes, status
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);""",
                            (
                                prop_id, team.team_id, prop.get("action"), prop.get("target"),
                                prop.get("initiator_type"), prop.get("initiator_name"), prop.get("rationale"),
                                json.dumps(prop.get("proposed_details", {})), json.dumps(prop.get("votes", {})), prop.get("status")
                            )
                        )

                # 4. Save Broker agreements
                for sender_id, recipient_id in self.broker.peer_talk_agreements:
                    conn.execute("INSERT INTO broker_agreements (sender_team_id, recipient_team_id) VALUES (?, ?);", (sender_id, recipient_id))

                # 5. Save Libraries and Permissions
                for lib_id, lib in self.libraries.items():
                    conn.execute(
                        "INSERT INTO libraries (lib_id, name, owner_team_id, description, is_public_visible) VALUES (?, ?, ?, ?, ?);",
                        (lib.lib_id, lib.name, lib.owner_team_id, lib.description, 1 if lib.is_public_visible else 0)
                    )

                    if os.path.exists(lib.root_dir):
                        for root, dirs, files in os.walk(lib.root_dir):
                            for file in files:
                                full_path = os.path.join(root, file)
                                rel_path = os.path.relpath(full_path, lib.root_dir)
                                try:
                                    with open(full_path, "r", encoding="utf-8") as f:
                                        content = f.read()
                                    conn.execute(
                                        "INSERT INTO doc_lib_files (lib_id, path, content) VALUES (?, ?, ?);",
                                        (lib.lib_id, rel_path, content)
                                    )
                                except Exception as e:
                                    self.logger.warning(f"Failed to read/serialize file {full_path}: {e}")

                for lib_id, paths_map in self.library_permissions.items():
                    for path, teams_map in paths_map.items():
                        for team_id, permission in teams_map.items():
                            conn.execute(
                                "INSERT INTO library_permissions (lib_id, path, team_id, permission) VALUES (?, ?, ?, ?);",
                                (lib_id, path, team_id, permission)
                            )
                            
                conn.commit()
            except Exception as db_err:
                conn.rollback()
                raise db_err
            finally:
                conn.close()
            self.logger.info(f"Successfully saved state to SQLite database: {target_path}")
        except Exception as e:
            self.logger.error(f"Error saving state to SQLite database at {target_path}: {e}")

    def load_state(self, db_path: str):
        """Loads and reconstructs the entire manager topology, configs, and agent states from SQLite."""
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"State database file '{db_path}' not found.")

        try:
            conn = sqlite3.connect(db_path)
            try:
                conn.row_factory = sqlite3.Row
                
                # Helper function to restore LLM clients
                def get_agent_client_by_name(client_name: Optional[str]) -> Any:
                    critic_wrapper = ManagerCriticClientAdapter(self)
                    if client_name:
                        if client_name in ("critic", "mock_client"):
                            return self.critic_client if self.critic_client is not None else critic_wrapper
                        if client_name in self.llm_clients:
                            return self.llm_clients[client_name]
                        elif client_name in self.model_configs and self.generator_handler:
                            return HandlerClientAdapter(client_name, self.generator_handler)
                        else:
                            self.logger.warning(f"Client '{client_name}' not found in registry during restore. Falling back to critic client.")
                    return self.critic_client if self.critic_client is not None else critic_wrapper

                # 1. Load Configs
                config_row = conn.execute("SELECT config_value FROM manager_config WHERE config_key = 'att_config';").fetchone()
                if config_row:
                    config_data = json.loads(config_row["config_value"])
                    for k, v in config_data.items():
                        setattr(self.config, k, v)
                
                # 2. Reconstruct Agents
                self.agents.clear()
                agents_rows = conn.execute("SELECT * FROM agents;").fetchall()
                for row in agents_rows:
                    client = get_agent_client_by_name(row["model_alias"])
                    agent = Agent(
                        name=row["name"],
                        role=row["role"],
                        llm_client=client,
                        role_description=row["role_description"],
                        system_instructions=row["system_instructions"]
                    )
                    agent.last_context = json.loads(row["last_context"]) if row["last_context"] else None
                    
                    # Restore agent messages
                    msg_rows = conn.execute("SELECT * FROM agent_messages WHERE agent_name = ? ORDER BY created_at ASC;", (agent.name,)).fetchall()
                    agent.messages = [{"role": r["role"], "content": r["content"]} for r in msg_rows]
                    
                    self.agents[agent.name] = agent

                root_ai_row = conn.execute("SELECT config_value FROM manager_config WHERE config_key = 'root_ai_name';").fetchone()
                if root_ai_row:
                    root_ai_name = root_ai_row["config_value"]
                    if root_ai_name in self.agents:
                        self.root_ai = self.agents[root_ai_name]

                # 3. Reconstruct Libraries
                self.libraries.clear()
                libraries_rows = conn.execute("SELECT * FROM libraries;").fetchall()
                for row in libraries_rows:
                    lib = DocumentLibrary(
                        lib_id=row["lib_id"],
                        name=row["name"],
                        owner_team_id=row["owner_team_id"],
                        description=row["description"],
                        is_public_visible=bool(row["is_public_visible"])
                    )
                    # Clear local directory before restoring
                    import shutil
                    shutil.rmtree(lib.root_dir, ignore_errors=True)
                    os.makedirs(lib.root_dir, exist_ok=True)
                    self.libraries[lib.lib_id] = lib

                files_rows = conn.execute("SELECT * FROM doc_lib_files;").fetchall()
                for row in files_rows:
                    lib_id = row["lib_id"]
                    if lib_id in self.libraries:
                        self.libraries[lib_id].write_file(row["path"], row["content"])

                # Restore library permissions
                self.library_permissions.clear()
                perms_rows = conn.execute("SELECT * FROM library_permissions;").fetchall()
                for row in perms_rows:
                    lib_id = row["lib_id"]
                    path = row["path"]
                    team_id = row["team_id"]
                    perm = row["permission"]
                    if lib_id not in self.library_permissions:
                        self.library_permissions[lib_id] = {}
                    if path not in self.library_permissions[lib_id]:
                        self.library_permissions[lib_id][path] = {}
                    self.library_permissions[lib_id][path][team_id] = perm

                # 4. Reconstruct Teams
                self.teams.clear()
                teams_rows = conn.execute("SELECT * FROM teams;").fetchall()
                team_map = {}
                
                # First pass: Instantiate teams without resolving parent/children references (since some might not be instantiated yet)
                for row in teams_rows:
                    creator_type = row["creator_type"]
                    creator_id = row["creator_id"]
                    
                    creator = None
                    if creator_type == "agent":
                        creator = self.agents.get(creator_id)
                    
                    team = AgentTeam(creator=creator, preset_name=row["preset_name"], team_purpose=row["team_purpose"])
                    team.team_id = row["team_id"]
                    team.logger = logging.getLogger(f"AgentTeam:{team.team_id}")
                    team.team_progress = row["team_progress"]
                    team.chapter_num = row["chapter_num"]
                    team.migration_count = row["migration_count"]
                    team.communication_rules = json.loads(row["communication_rules"])
                    team.status_map = json.loads(row["status_map"])
                    team.system_instructions = row["system_instructions"]
                    team.manager = self
                    team_map[team.team_id] = team

                # Second pass: Resolve hierarchy & team creator references
                for row in teams_rows:
                    team_id = row["team_id"]
                    team = team_map[team_id]
                    
                    parent_team_id = row["parent_team_id"]
                    if parent_team_id:
                        parent_team = team_map.get(parent_team_id)
                        team._parent_team = parent_team
                        if team not in parent_team.child_teams:
                            parent_team.child_teams.append(team)
                            
                    if row["creator_type"] == "team" and row["creator_id"]:
                        team.creator = team_map.get(row["creator_id"])

                self.teams = team_map

                # 5. Populate Team Members
                members_rows = conn.execute("SELECT * FROM team_members;").fetchall()
                for row in members_rows:
                    t_id = row["team_id"]
                    a_name = row["agent_name"]
                    if t_id in self.teams and a_name in self.agents:
                        self.teams[t_id].members.append(self.agents[a_name])

                # 6. Associate Built-in DocLibs & Re-bind Tools to Teams
                from .tool import get_default_tools
                for team in self.teams.values():
                    team.doc_library = self.libraries.get(f"DL-{team.team_id}")
                    # Re-bind tools
                    team.tools.clear()
                    team.tools.update(get_default_tools(self.tools_context, team))
                    team.tools.update(self.global_tools)

                # 7. Restore Team Inboxes
                inbox_rows = conn.execute("SELECT * FROM team_inbox ORDER BY created_at ASC;").fetchall()
                for row in inbox_rows:
                    t_id = row["team_id"]
                    if t_id in self.teams:
                        msg = json.loads(row["payload"])
                        self.teams[t_id].message_inbox.append(msg)

                # 8. Restore Proposals
                proposals_rows = conn.execute("SELECT * FROM team_proposals;").fetchall()
                for row in proposals_rows:
                    t_id = row["team_id"]
                    if t_id in self.teams:
                        prop_id = row["proposal_id"]
                        self.teams[t_id].proposals[prop_id] = {
                            "action": row["action"],
                            "target": row["target"],
                            "initiator_type": row["initiator_type"],
                            "initiator_name": row["initiator_name"],
                            "rationale": row["rationale"],
                            "proposed_details": json.loads(row["proposed_details"]),
                            "votes": json.loads(row["votes"]),
                            "status": row["status"]
                        }

                # 9. Restore Broker peer agreements
                self.broker.peer_talk_agreements.clear()
                agreements_rows = conn.execute("SELECT * FROM broker_agreements;").fetchall()
                for row in agreements_rows:
                    self.broker.peer_talk_agreements.add((row["sender_team_id"], row["recipient_team_id"]))

            finally:
                conn.close()
            self.logger.info(f"Successfully loaded state from SQLite database: {db_path}")
        except Exception as e:
            self.logger.error(f"Error loading state from SQLite database {db_path}: {e}")
            raise e
