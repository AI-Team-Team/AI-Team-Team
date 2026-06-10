import uuid
import logging
import time
import json
import re
import ast
from typing import List, Dict, Optional, Any, Tuple, Callable
from .tool import Tool

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
        model_registry: Optional[dict] = None
    ):
        self.enable_dynamic_delegation = enable_dynamic_delegation
        self.max_delegation_depth = max_delegation_depth
        self.min_subagent_team_size = min_subagent_team_size
        self.subagent_discussion_rounds = subagent_discussion_rounds
        self.react_max_steps = react_max_steps
        self.inbox_summarize_threshold_chars = inbox_summarize_threshold_chars
        self.model_registry = model_registry or {}

class Agent:
    def __init__(self, name: str, role: str, llm_client: Optional[Any] = None):
        self.name = name
        self.role = role
        self.llm_client = llm_client

    def launch_att(
        self,
        manager: 'ATTManager',
        member_count: int = 3,
        roles_and_presets: Optional[List[Tuple[str, str]]] = None,
        system_instructions: str = "",
        team_purpose: str = "Unspecified team purpose"
    ) -> 'AgentTeam':
        """Allows this agent to launch a dynamic sub-team (Level 2+)."""
        child = manager.create_agent_team(
            creator=self,
            member_count=member_count,
            roles_and_presets=roles_and_presets,
            system_instructions=system_instructions,
            team_purpose=team_purpose
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

    @property
    def parent_team(self) -> Optional['AgentTeam']:
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
        team_purpose: str = "Unspecified team purpose"
    ) -> 'AgentTeam':
        """Allows any active team to recursively launch their own child AT."""
        child = manager.create_agent_team(
            creator=self,
            member_count=member_count,
            roles_and_presets=roles_and_presets,
            system_instructions=system_instructions,
            team_purpose=team_purpose
        )
        child.chapter_num = self.chapter_num
        return child

    def receive_message(self, message: Dict[str, Any]):
        self.message_inbox.append(message)
        self.logger.info(f"Team {self.team_id} received message of type '{message.get('type')}' from '{message.get('from')}'")

    def execute_react_step(
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
            peer_lines = []
            for tid, t in manager.teams.items():
                if tid != self.team_id:
                    peer_lines.append(f"  - {tid} (Purpose: {t.team_purpose})")
            if peer_lines:
                peer_context = f"\n### ACTIVE PEER TEAMS (Global Registry)\n" + "\n".join(peer_lines) + "\n"

        # Read configuration variables safely
        model_registry = manager.config.model_registry if manager else {}
        max_depth = manager.config.max_delegation_depth if manager else 2
        min_size = manager.config.min_subagent_team_size if manager else 3

        model_options = "\n".join([f"  - {k}: {v.get('ai_note', 'No description')}" for k, v in model_registry.items()])
        identity_header = (
            f"## AGENT IDENTITY PROFILE\n"
            f"- **Role Name**: {agent.role}\n"
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
            f"4. When creating an AT, you can assign models based on task complexity. Available models:\n"
            f"{model_options}\n"
        )

        try:
            if getattr(self, "tools", None):
                tools_desc = []
                for t_name, tool in self.tools.items():
                    tools_desc.append(f"- **{t_name}**: {tool.description}")
                tools_list_str = "\n".join(tools_desc)

                react_system_instruction = (
                    f"{system_instruction}\n\n"
                    f"{identity_header}\n"
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

                current_prompt = prompt
                react_history = []
                
                for step in range(max_steps):
                    try:
                        self.status_map[agent.name] = f"Thinking (Step {step+1}/{max_steps})..."
                        if manager and manager.on_status_change:
                            manager.on_status_change(agent.name, f"Thinking (Step {step+1}/{max_steps})...")

                        full_prompt = current_prompt
                        if react_history:
                            full_prompt = (
                                f"{current_prompt}\n\n"
                                f"--- ReAct Iteration History ---\n"
                                f"{chr(10).join(react_history)}\n"
                                f"Next step:"
                            )

                        response = agent.llm_client.generate(
                            prompt=full_prompt,
                            system_instruction=react_system_instruction,
                            temperature=0.3
                        ).strip()

                        self.logger.info(f"Agent {agent.name} ReAct step {step+1} response:\n{response}")

                        # Trigger logging callback
                        if manager and manager.on_log_append:
                            log_content = (
                                f"AGENT: {agent.name}\n"
                                f"ROLE: {agent.role}\n"
                                f"STEP: {step+1}\n"
                                f"--- SYSTEM INSTRUCTION BEGIN ---\n"
                                f"{react_system_instruction}\n"
                                f"--- SYSTEM INSTRUCTION END ---\n"
                                f"--- PROMPT BEGIN ---\n"
                                f"{full_prompt}\n"
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
                        action_match = re.search(r"Action:\s*(\w+)\((.*)\)", response, re.IGNORECASE)
                        if action_match:
                            tool_name = action_match.group(1).strip()
                            tool_args_str = action_match.group(2).strip()

                            def parse_args(args_str):
                                if not args_str:
                                    return [], {}
                                try:
                                    parsed = ast.literal_eval(f"({args_str})")
                                    if isinstance(parsed, tuple):
                                        args = list(parsed)
                                    else:
                                        args = [parsed]
                                    return args, {}
                                except Exception:
                                    args = []
                                    kwargs = {}
                                    parts = args_str.split(",")
                                    for p in parts:
                                        p = p.strip()
                                        if "=" in p:
                                            k, v = p.split("=", 1)
                                            kwargs[k.strip()] = v.strip().strip("'\"")
                                        else:
                                            args.append(p.strip().strip("'\""))
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
                                    approved, audit_reason = manager.tool_auditors[tool_name](*args, **kwargs)
                                    if not approved:
                                        observation = f"Error: Tool execution rejected by auditor: {audit_reason}"
                                    else:
                                        observation = tool_obj(*args, **kwargs)
                                else:
                                    observation = tool_obj(*args, **kwargs)
                                
                                self.status_map[agent.name] = "Thinking..."
                                if manager and manager.on_status_change:
                                    manager.on_status_change(agent.name, "Thinking...")
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

                            react_history.append("Thought: Analyzing task.")
                            react_history.append(f"Action: {tool_name}({tool_args_str})")
                            react_history.append(f"Observation: {observation}")
                        else:
                            if step == max_steps - 1:
                                return response
                            react_history.append(response)
                            react_history.append("Observation: Please output either 'Action: tool_name(args)' or 'Final Answer: <content>'.")
                    except Exception as e:
                        self.logger.error(f"Error in ReAct step {step+1} for agent {agent.name}: {e}")
                        return f"Error executing task during ReAct loop: {e}"

                return "Error: ReAct loop exceeded maximum steps without producing a Final Answer."

            else:
                # Fallback to direct call if no tools are bound
                full_system_instruction = (
                    f"{system_instruction}\n\n"
                    f"{identity_header}\n"
                    f"Output exactly 'Final Answer: <content>' when complete."
                )

                try:
                    response = agent.llm_client.generate(
                        prompt=prompt,
                        system_instruction=full_system_instruction,
                        temperature=0.3
                    ).strip()
                    
                    if manager and manager.on_log_append:
                        log_content = (
                            f"AGENT: {agent.name}\n"
                            f"ROLE: {agent.role}\n"
                            f"--- SYSTEM INSTRUCTION BEGIN ---\n"
                            f"{full_system_instruction}\n"
                            f"--- SYSTEM INSTRUCTION END ---\n"
                            f"--- PROMPT BEGIN ---\n"
                            f"{prompt}\n"
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
                except Exception as e:
                    self.logger.error(f"Agent {agent.name} execution error: {e}")
                    return f"Error executing task: {e}"
        finally:
            self.status_map[agent.name] = "Idle"
            if manager and manager.on_status_change:
                manager.on_status_change(agent.name, "Idle")

class NegotiationBroker:
    """Coordinates sibling and cross-lineage communication permissions."""
    def __init__(self, manager: 'ATTManager'):
        self.manager = manager
        self.logger = logging.getLogger("NegotiationBroker")

    def negotiate_communication(self, sender: AgentTeam, recipient: AgentTeam, mode: str = "proxied") -> bool:
        sender_parent = sender.parent_team or self.manager.find_parent_team(sender)
        recipient_parent = recipient.parent_team or self.manager.find_parent_team(recipient)

        if sender_parent and recipient_parent and sender_parent.team_id == recipient_parent.team_id:
            parent = sender_parent
            allow = parent.communication_rules.get("allow_sibling_talk", False)
            self.logger.info(f"Sibling negotiation between {sender.team_id} and {recipient.team_id}: Parent {parent.team_id} decision={allow}")
            return allow

        if not sender_parent or not recipient_parent:
            self.logger.warning(f"Lineage incomplete. Cannot negotiate communication between {sender.team_id} and {recipient.team_id}.")
            return False

        self.logger.info(f"Cross-lineage negotiation requested between {sender.team_id} and {recipient.team_id} (via parents {sender_parent.team_id} and {recipient_parent.team_id}).")
        return self._run_parent_negotiation_loop(sender_parent, recipient_parent, mode)

    def _run_parent_negotiation_loop(self, p1: AgentTeam, p2: AgentTeam, mode: str) -> bool:
        self.logger.info(f"Parents {p1.team_id} and {p2.team_id} are negotiating communication channel (mode: {mode})...")
        if mode in {"proxied", "indirect", "rule_gated"}:
            self.logger.info("Negotiation loop succeeded: communication contract established.")
            return True
        self.logger.warning(f"Negotiation loop rejected: mode '{mode}' is unsupported or unsafe.")
        return False

class ATTManager:
    """Master controller managing the overall ATT (AI Team Team) topology."""
    def __init__(self, root_ai: Agent, critic_client: Any, config: Optional[ATTConfig] = None):
        self.root_ai = root_ai
        self.critic_client = critic_client
        self.config = config or ATTConfig()
        self.teams: Dict[str, AgentTeam] = {}
        self.broker = NegotiationBroker(self)
        
        from .supervision import SupervisoryTeam
        self.supervisor = SupervisoryTeam(root_ai, critic_client)
        self.logger = logging.getLogger("ATTManager")
        self.tools_context: Dict[str, Any] = {}
        
        # Public Tool registries
        self.global_tools: Dict[str, Tool] = {}
        self.tool_auditors: Dict[str, Callable[..., Tuple[bool, str]]] = {}
        
        # Event callbacks
        self.on_status_change: Optional[Callable[[str, str], None]] = None
        self.on_activity_added: Optional[Callable[[str, str, str], None]] = None
        self.on_log_append: Optional[Callable[[str, str, str, Optional[int]], None]] = None

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
        team_purpose: str = "Unspecified team purpose"
    ) -> AgentTeam:
        """Dynamically spawns a new recursive Agent Team (AT)."""
        min_size = self.config.min_subagent_team_size
        assert member_count >= min_size, f"An Agent Team must contain at least {min_size} members to debate properly."
        
        team = AgentTeam(creator=creator, preset_name=preset_name, team_purpose=team_purpose)
        
        if isinstance(creator, AgentTeam):
            team.chapter_num = creator.chapter_num
        elif isinstance(creator, Agent):
            for t in self.teams.values():
                if creator in t.members:
                    team.chapter_num = t.chapter_num
                    break

        members = []
        if roles_and_presets:
            for name, role in roles_and_presets:
                members.append(Agent(name=name, role=role, llm_client=self.critic_client))
        else:
            preset = self.get_preset(preset_name)
            roles = preset.get("roles", [])
            if len(roles) >= member_count:
                for name, role in roles[:member_count]:
                    members.append(Agent(name=name, role=role, llm_client=self.critic_client))
            else:
                for i in range(member_count):
                    members.append(Agent(name=f"{team.team_id}_member_{i+1}", role="Specialist", llm_client=self.critic_client))

        team.members = members
        team.system_instructions = system_instructions or self.get_preset(preset_name).get("system_instructions", "")
        
        # Bind generic tools
        from .tool import get_default_tools
        team.tools.update(get_default_tools(self.tools_context, team))
        
        # Bind globally registered custom tools
        team.tools.update(self.global_tools)
            
        self.teams[team.team_id] = team
        
        if isinstance(creator, AgentTeam):
            creator.add_child_team(team)
            
        self.logger.info(f"Successfully spawned Agent Team {team.team_id} (N={len(members)}, Preset: {preset_name}) spawned by {creator.name if hasattr(creator, 'name') else creator.team_id}")
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

    def execute_team_discussion(self, team: AgentTeam, prompt: str, rounds: int = 2) -> str:
        """Executes a multi-agent debate session inside the AT, monitored by the Supervisor."""
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
                    raw_inbox_text = self.critic_client.generate(
                        summary_prompt,
                        system_instruction="You are a strict system summarizer. Compress alerts while keeping critical facts and failures.",
                        temperature=0.1
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
        full_prompt = f"{prompt}{inbox_context}"
        
        for r in range(1, rounds + 1):
            for agent in team.members:
                self.logger.info(f"Agent {agent.name} thinking...")
                final_answer = team.execute_react_step(
                    agent=agent, 
                    prompt=full_prompt, 
                    system_instruction=team.system_instructions,
                    max_steps=self.config.react_max_steps,
                    manager=self
                )
                dialog_history.append(f"{agent.name}: {final_answer}")

        transcript = "\n".join(dialog_history)
        
        # Run supervisory audit
        is_healthy, reason = self.supervisor.audit_team_dialog(team, transcript)
        if not is_healthy:
            self.supervisor.report_anomaly(team, reason, self)
            
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

        return transcript
