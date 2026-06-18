import uuid
import asyncio
import logging
import json
import re
import ast
import inspect
from typing import List, Dict, Optional, Tuple, Any, Union
from ai_team_team.tool import Tool
from ai_team_team.doc_library import DocumentLibrary
from .agent import Agent
from .exceptions import ATTException
from .utils import generate_with_retry

class AgentTeam:
    """Represents a recursive team panel of Agents collaborating to debate/solve goals."""
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
        manager = manager if manager is not None else getattr(self, "manager", None)
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
            f"- **Parent Team**: {self.team_id} (Preset: {self.preset_name})\n"
            f"- **Team Purpose**: {self.team_purpose}\n"
            f"- **Current Objective**: Cooperate in team tasks.\n"
            f"- **AT Delegation Depth**: {self.depth} / {max_depth}\n"
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
            if agent.last_context and agent.last_context.get("team_id") != self.team_id:
                notice = (
                    f"*** TRANSITION NOTICE: ACTIVE TEAM UPDATE ***\n"
                    f"You have transitioned to work with another team group:\n"
                    f"- Active Team: {self.team_id} (Preset: {self.preset_name})\n"
                    f"- Team Purpose: {self.team_purpose}\n"
                    f"- Your Assigned Role: {agent.role}\n"
                    f"Please continue your work and cooperate in this team based on your prior memory."
                )
                agent.messages.append({"role": "system", "content": notice})
            agent.last_context = current_context

            # Append current prompt objective to private multi-turn history
            agent.messages.append({"role": "user", "content": prompt})

            # Dialogue Memory Pruning / Compression
            enable_compression = manager.config.enable_memory_compression if manager else True
            max_turns = manager.config.max_memory_turns if manager else 20

            if enable_compression and len(agent.messages) > max_turns + 2:
                # 1. Keep the first message (index 0)
                first_msg = agent.messages[0]
                
                # 2. Extract intermediate messages
                intermediate_messages = agent.messages[1 : len(agent.messages) - max_turns]
                
                # 3. Format intermediate messages to string for summarization
                history_text_parts = []
                for msg in intermediate_messages:
                    r = msg.get("role", "unknown").upper()
                    c = msg.get("content", "")
                    history_text_parts.append(f"{r}: {c}")
                history_text = "\n".join(history_text_parts)
                
                # 4. Generate summary using critic client
                summary_prompt = (
                    f"Summarize the preceding execution logs and discussions into a single cohesive paragraph of historical facts. "
                    f"Focus on what was completed.\n\n"
                    f"--- EXECUTION LOGS AND DISCUSSIONS BEGIN ---\n"
                    f"{history_text}\n"
                    f"--- EXECUTION LOGS AND DISCUSSIONS END ---\n"
                )
                
                # Retrieve critic client
                critic_client = None
                if manager:
                    critic_client = manager.critic_client if manager.critic_client is not None else ManagerCriticClientAdapter(manager)
                
                if not critic_client:
                    critic_client = agent.llm_client
                
                retries = manager.config.llm_max_retries if manager else 3
                backoff = manager.config.llm_retry_backoff_factor if manager else 1.5
                
                try:
                    summary_text = await generate_with_retry(
                        llm_client=critic_client,
                        prompt=summary_prompt,
                        system_instruction="You are a precise summarization assistant.",
                        temperature=0.3,
                        retries=retries,
                        backoff_factor=backoff
                    )
                    summary_text = summary_text.strip()
                except Exception as e:
                    self.logger.warning(f"Memory compression summarization failed: {e}. Using a generic fallback summary.")
                    summary_text = "Early execution history compressed due to context limits."
                
                archive_message = {
                    "role": "system",
                    "content": f"*** HISTORICAL SUMMARY ARCHIVE ***\n{summary_text}"
                }
                
                # 5. Keep the latest max_turns messages
                latest_messages = agent.messages[len(agent.messages) - max_turns :]
                
                # Re-assemble agent.messages
                agent.messages = [first_msg, archive_message] + latest_messages

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

                                def parse_val(val_str):
                                    val_str = val_str.strip()
                                    if not val_str:
                                        return ""
                                    try:
                                        return ast.literal_eval(val_str)
                                    except Exception:
                                        if (val_str.startswith("'") and val_str.endswith("'")) or (val_str.startswith('"') and val_str.endswith('"')):
                                            return val_str[1:-1]
                                        if val_str.lower() == "true":
                                            return True
                                        if val_str.lower() == "false":
                                            return False
                                        if val_str.lower() == "none":
                                            return None
                                        return val_str

                                args = []
                                kwargs = {}

                                for chunk in chunks:
                                    if not chunk:
                                        continue
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
