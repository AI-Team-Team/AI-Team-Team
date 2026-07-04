import asyncio
import sqlite3
import os
import logging
import json
import time
from typing import List, Dict, Optional, Tuple, Any, Callable

from ai_team_team.doc_library import DocumentLibrary
from ai_team_team.tool import Tool

# Modular sub-module imports
from .agent import Agent
from .team import AgentTeam
from .broker import NegotiationBroker
from .config import ATTConfig
from .exceptions import ATTException
from .utils import generate_with_retry
from .adapters import ManagerDefaultClientAdapter, HandlerClientAdapter

from ai_team_team.database.session import get_session
from ai_team_team.database.models import (
    Base,
    ManagerConfigModel,
    AgentModel,
    AgentMessageModel,
    TeamModel,
    TeamInboxModel,
    TeamProposalModel,
    BrokerAgreementModel,
    LibraryModel,
    LibraryPermissionModel,
    DocLibFileModel
)

class ATTManager:
    """Master controller managing the overall ATT (AI Team Team) topology."""
    def __init__(self, root_ai: Agent, config: Optional[ATTConfig] = None, db_path: Optional[str] = None):
        self.root_ai = root_ai
        self.config = config or ATTConfig()
        self.db_path = db_path
        self.agents: Dict[str, Agent] = {root_ai.name: root_ai}
        self.teams: Dict[str, AgentTeam] = {}
        self.broker = NegotiationBroker(self)
        self.llm_clients: Dict[str, Any] = {}
        
        self.model_configs: Dict[str, Dict[str, Any]] = {}
        self.generator_handler: Optional[Callable[..., str]] = None
        
        from ai_team_team.supervision import SupervisoryTeam
        self.supervisor = SupervisoryTeam(root_ai, ManagerDefaultClientAdapter(self), manager=self)
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
        self.on_emergency_escalation: Optional[Callable[[str, str, str], None]] = None

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

    def register_tool(
        self,
        name: Any = None,
        description: Optional[str] = None,
        func: Optional[Callable[..., Any]] = None,
        schema: Optional[Any] = None
    ):
        """Registers a custom utility tool to all teams."""
        tool = Tool(name, description, func, schema)
        self.global_tools[tool.name] = tool
        # Bind to existing teams
        for team in self.teams.values():
            team.tools[tool.name] = tool

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
        from ai_team_team.tool import get_default_tools
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
            default_wrapper = ManagerDefaultClientAdapter(self)
            if client_name:
                if client_name in self.llm_clients:
                    return self.llm_clients[client_name]
                elif client_name in self.model_configs and self.generator_handler:
                    adapter = HandlerClientAdapter(client_name, self.generator_handler)
                    config = self.model_configs.get(client_name)
                    if config:
                        adapter._supports_native = config.get("supports_native_tool_calling", False)
                    return adapter
                else:
                    self.logger.warning(f"Client '{client_name}' not found in registry. Falling back to default client.")
            if "default" in self.llm_clients:
                return self.llm_clients["default"]
            if self.root_ai.llm_client:
                return self.root_ai.llm_client
            return default_wrapper

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
        from ai_team_team.tool import get_default_tools
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
        
        from .policies import resolve_migration_policy
        policy_name = getattr(self.config, "migration_policy", "ancestor_approval")
        policy = resolve_migration_policy(policy_name)
        
        try:
            approved, reason = await policy.authorize_migration(team, target_parent, self, rationale)
            
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

    async def execute_team_discussion(self, team: AgentTeam, prompt: str, rounds: int = 2, skip_audit: bool = False) -> str:
        """Executes a multi-agent debate session inside the AT, monitored by the Supervisor."""
        team.migration_count = 0
        team.is_running = True
        self.logger.info(f"Executing discussion in team {team.team_id} (rounds={rounds}, skip_audit={skip_audit})...")
        
        dialog_history = []
        last_round_answers = {}
        is_healthy, reason = True, "Audit skipped."
        
        try:
            for r in range(1, rounds + 1):
                # Consume inbox messages at the start of every round
                inbox_context = ""
                if team.message_inbox:
                    inbox_lines = []
                    for msg in team.message_inbox:
                        inbox_lines.append(f"- **From [{msg.get('from', 'Unknown')}]**: {msg.get('reason') or msg.get('objective') or str(msg)}")
                    
                    raw_inbox_text = "\n".join(inbox_lines)
                    threshold = self.config.inbox_summarize_threshold_chars
                    if len(raw_inbox_text) > threshold:
                        summarize_client = None
                        if team.members and getattr(team.members[0], "llm_client", None):
                            summarize_client = team.members[0].llm_client
                        elif self.root_ai and getattr(self.root_ai, "llm_client", None):
                            summarize_client = self.root_ai.llm_client
                        
                        if summarize_client:
                            self.logger.info("Inbox context too large, summarizing before injection...")
                            summary_prompt = f"Summarize the following system alerts and escalations concisely:\n\n{raw_inbox_text}"
                            try:
                                raw_inbox_text = await generate_with_retry(
                                    llm_client=summarize_client,
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

                round_members = list(team.members)
                tasks = []
                for agent in round_members:
                    if r == 1:
                        round_prompt = f"{prompt}{inbox_context}"
                    else:
                        other_answers = []
                        for other_agent in round_members:
                            if other_agent.name != agent.name:
                                ans = last_round_answers.get((r - 1, other_agent.name), "No response.")
                                other_answers.append(f"{other_agent.name} (Role: {other_agent.role}): {ans}")
                        
                        round_prompt = (
                            f"Here is the discussion from Round {r - 1}:\n"
                            + "\n".join(other_answers) + "\n\n"
                            f"Please continue the discussion. Build on or challenge their arguments."
                            f"{inbox_context}"
                        )

                    async def _run_agent(ag=agent, pr=round_prompt):
                        return await team.execute_reasoning_step(
                            agent=ag,
                            prompt=pr,
                            system_instruction=team.system_instructions,
                            max_steps=self.config.react_max_steps,
                            manager=self
                        )
                    tasks.append(_run_agent())

                results = await asyncio.gather(*tasks, return_exceptions=True)

                for agent, result in zip(round_members, results):
                    if isinstance(result, ATTException):
                        self.logger.error(f"Failed to execute discussion step due to ATT error: {result}")
                        if not skip_audit:
                            await self.supervisor.report_anomaly(team, f"LLM client invocation error: {result}", self)
                        raise result
                    elif isinstance(result, Exception):
                        self.logger.error(f"Agent {agent.name} encountered an error: {result}")
                        ans = f"Error: {result}"
                    else:
                        ans = str(result)
                    
                    last_round_answers[(r, agent.name)] = ans
                    dialog_history.append(f"{agent.name}: {ans}")

                # Apply any deferred approved voting proposals at the end of the round
                if self.config.enable_membership_voting:
                    for prop_id, prop in list(team.proposals.items()):
                        if prop.get("status") == "approved" and not prop.setdefault("proposed_details", {}).get("executed", False):
                            # Mark as executed in the proposal details to avoid executing multiple times
                            prop["proposed_details"]["executed"] = True
                            
                            action = prop.get("action")
                            target = prop.get("target")
                            
                            if action == "add":
                                model_name = prop["proposed_details"].get("model")
                                role_desc = prop["proposed_details"].get("role_description", "")
                                sys_inst = prop["proposed_details"].get("system_instructions", "")
                                
                                client = None
                                if model_name in self.llm_clients:
                                    client = self.llm_clients[model_name]
                                elif model_name in self.model_configs and self.generator_handler:
                                    from .adapters import HandlerClientAdapter
                                    client = HandlerClientAdapter(model_name, self.generator_handler)
                                else:
                                    client = ManagerDefaultClientAdapter(self)
                                    
                                new_agent = Agent(
                                    name=f"Dynamic_{target}",
                                    role=target,
                                    llm_client=client,
                                    role_description=role_desc,
                                    system_instructions=sys_inst
                                )
                                team.members.append(new_agent)
                                self.agents[new_agent.name] = new_agent
                                self.logger.info(f"Deferred execution: Added member '{new_agent.name}' to team '{team.team_id}'.")
                            elif action == "remove":
                                min_size = self.config.min_subagent_team_size
                                if len(team.members) <= min_size:
                                    prop["status"] = "rejected"
                                    self.logger.warning(f"Deferred execution: Removing '{target}' failed because it violates min team size of {min_size}. Status changed to rejected.")
                                    continue
                                
                                target_agent = None
                                for m in team.members:
                                    if m.name == target:
                                        target_agent = m
                                        break
                                if target_agent:
                                    team.members.remove(target_agent)
                                    self.logger.info(f"Deferred execution: Removed member '{target}' from team '{team.team_id}'.")
                                else:
                                    prop["status"] = "rejected"
                                    self.logger.warning(f"Deferred execution: Member '{target}' not found. Status changed to rejected.")

            transcript = "\n".join(dialog_history)
            
            # Run supervisory audit
            if not skip_audit:
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
        finally:
            team.is_running = False
            # Check for left-over emergency messages in inbox
            if team.message_inbox and getattr(self.config, "enable_emergency_wakeup", True):
                emergency_msg = next((msg for msg in team.message_inbox if msg.get("type") in {"child_failure_escalation", "escalation_spawn"}), None)
                if emergency_msg:
                    self.logger.warning(f"Post-discussion emergency wakeup triggered for team {team.team_id}")
                    try:
                        asyncio.create_task(self.execute_emergency_discussion(team, emergency_msg))
                    except RuntimeError:
                        pass

    async def execute_emergency_discussion(self, team: AgentTeam, alert: Dict[str, Any]) -> str:
        """Executes an emergency discussion round to handle child failure or escalation."""
        emergency_prompt = (
            f"EMERGENCY MEETING: An anomaly or escalation was reported from your child team or supervisor.\n"
            f"Alert details: {alert.get('reason') or alert.get('objective') or str(alert)}\n"
            f"Please evaluate this issue and decide on corrective actions or escalate further."
        )
        rounds = getattr(self.config, "emergency_discussion_rounds", 1)
        self.logger.warning(f"Starting emergency discussion on team {team.team_id} for {rounds} round(s)...")
        return await self.execute_team_discussion(team, prompt=emergency_prompt, rounds=rounds)

    def _auto_save(self):
        """Triggers a snapshot save if a database path is configured."""
        if self.db_path:
            self.save_state()

    def save_state(self, db_path: Optional[str] = None):
        """Serializes the entire manager topology, agents, teams, libraries, etc. to SQLite using SQLAlchemy ORM."""
        target_path = db_path or self.db_path
        if not target_path:
            return

        try:
            from sqlalchemy import text
            with get_session(target_path, disable_fks=True) as session:
                # 1. Clear Existing Data
                tables = [
                    "doc_lib_files", "library_permissions", "libraries", "broker_agreements",
                    "team_proposals", "team_inbox", "team_members", "teams", "agent_messages", "agents", "manager_config"
                ]
                for t in tables:
                    session.execute(text(f"DELETE FROM {t};"))

                # 2. Save Configs
                att_config_data = json.dumps(self.config.__dict__)
                session.add(ManagerConfigModel(config_key="att_config", config_value=att_config_data))
                if self.root_ai:
                    session.add(ManagerConfigModel(config_key="root_ai_name", config_value=self.root_ai.name))

                # 3. Save Agents
                agent_models_map = {}
                for agent in self.agents.values():
                    model_alias = None
                    if agent.llm_client:
                        from unittest.mock import Mock
                        if isinstance(agent.llm_client, Mock):
                            model_alias = "mock_client"
                        elif hasattr(agent.llm_client, "model_name") and not isinstance(agent.llm_client.model_name, Mock):
                            model_alias = str(agent.llm_client.model_name)
                        elif hasattr(agent.llm_client, "manager") and not isinstance(agent.llm_client.manager, Mock):
                            model_alias = "default"

                    last_ctx_json = json.dumps(agent.last_context) if agent.last_context else None
                    agent_model = AgentModel(
                        name=agent.name,
                        role=agent.role,
                        role_description=getattr(agent, "role_description", ""),
                        system_instructions=getattr(agent, "system_instructions", ""),
                        model_alias=model_alias,
                        last_context=last_ctx_json
                    )
                    session.add(agent_model)
                    agent_models_map[agent.name] = agent_model

                    for idx, msg in enumerate(agent.messages):
                        msg_model = AgentMessageModel(
                            agent_name=agent.name,
                            role=msg.get("role", "user"),
                            content=msg.get("content", ""),
                            tool_calls=msg.get("tool_calls"),
                            tool_call_id=msg.get("tool_call_id"),
                            name=msg.get("name"),
                            created_at=time.time() + idx * 0.001
                        )
                        session.add(msg_model)

                # 4. Save Teams
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
                    
                    team_model = TeamModel(
                        team_id=team.team_id,
                        preset_name=team.preset_name,
                        team_purpose=team.team_purpose,
                        team_progress=team.team_progress,
                        depth=team.depth,
                        chapter_num=team.chapter_num,
                        parent_team_id=parent_id,
                        migration_count=team.migration_count,
                        creator_type=creator_type,
                        creator_id=creator_id,
                        communication_rules=comm_rules_json,
                        status_map=status_map_json,
                        system_instructions=getattr(team, "system_instructions", "")
                    )
                    session.add(team_model)

                    # Save team members via relationship
                    team_model.members = [agent_models_map[m.name] for m in team.members if m.name in agent_models_map]

                    for idx, msg in enumerate(team.message_inbox):
                        sender = msg.get("from", "Unknown")
                        msg_type = msg.get("type", "Unknown")
                        payload = json.dumps(msg)
                        inbox_model = TeamInboxModel(
                            team_id=team.team_id,
                            sender=sender,
                            msg_type=msg_type,
                            payload=payload,
                            created_at=time.time() + idx * 0.001
                        )
                        session.add(inbox_model)

                    for prop_id, prop in team.proposals.items():
                        proposal_model = TeamProposalModel(
                            proposal_id=prop_id,
                            team_id=team.team_id,
                            action=prop.get("action"),
                            target=prop.get("target"),
                            initiator_type=prop.get("initiator_type"),
                            initiator_name=prop.get("initiator_name"),
                            rationale=prop.get("rationale"),
                            proposed_details=json.dumps(prop.get("proposed_details", {})),
                            votes=json.dumps(prop.get("votes", {})),
                            status=prop.get("status")
                        )
                        session.add(proposal_model)

                # 5. Save Broker agreements
                for sender_id, recipient_id in self.broker.peer_talk_agreements:
                    agreement_model = BrokerAgreementModel(
                        sender_team_id=sender_id,
                        recipient_team_id=recipient_id
                    )
                    session.add(agreement_model)

                # 6. Save Libraries and Permissions
                for lib_id, lib in self.libraries.items():
                    lib_model = LibraryModel(
                        lib_id=lib.lib_id,
                        name=lib.name,
                        owner_team_id=lib.owner_team_id,
                        description=lib.description,
                        is_public_visible=1 if lib.is_public_visible else 0
                    )
                    session.add(lib_model)

                    if os.path.exists(lib.root_dir):
                        for root, dirs, files in os.walk(lib.root_dir):
                            for file in files:
                                full_path = os.path.join(root, file)
                                rel_path = os.path.relpath(full_path, lib.root_dir)
                                try:
                                    with open(full_path, "r", encoding="utf-8") as f:
                                        content = f.read()
                                    file_model = DocLibFileModel(
                                        lib_id=lib.lib_id,
                                        path=rel_path,
                                        content=content
                                    )
                                    session.add(file_model)
                                except Exception as e:
                                    self.logger.warning(f"Failed to read/serialize file {full_path}: {e}")

                for lib_id, paths_map in self.library_permissions.items():
                    for path, teams_map in paths_map.items():
                        for team_id, permission in teams_map.items():
                            perm_model = LibraryPermissionModel(
                                lib_id=lib_id,
                                path=path,
                                team_id=team_id,
                                permission=permission
                            )
                            session.add(perm_model)

            self.logger.info(f"Successfully saved state to SQLite database: {target_path}")
        except Exception as e:
            self.logger.error(f"Error saving state to SQLite database at {target_path}: {e}")

    def load_state(self, db_path: str):
        """Loads and reconstructs the entire manager topology, configs, and agent states from SQLite using SQLAlchemy ORM."""
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"State database file '{db_path}' not found.")

        try:
            with get_session(db_path) as session:
                # Helper function to restore LLM clients
                def get_agent_client_by_name(client_name: Optional[str]) -> Any:
                    default_wrapper = ManagerDefaultClientAdapter(self)
                    if client_name:
                        if client_name in self.llm_clients:
                            return self.llm_clients[client_name]
                        elif client_name in self.model_configs and self.generator_handler:
                            adapter = HandlerClientAdapter(client_name, self.generator_handler)
                            config = self.model_configs.get(client_name)
                            if config:
                                adapter._supports_native = config.get("supports_native_tool_calling", False)
                            return adapter
                        else:
                            self.logger.warning(f"Client '{client_name}' not found in registry during restore. Falling back to default client.")
                    if "default" in self.llm_clients:
                        return self.llm_clients["default"]
                    if self.root_ai.llm_client:
                        return self.root_ai.llm_client
                    return default_wrapper

                # 1. Load Configs
                config_rows = session.query(ManagerConfigModel).all()
                config_map = {row.config_key: row.config_value for row in config_rows}
                
                if "att_config" in config_map:
                    config_data = json.loads(config_map["att_config"])
                    for k, v in config_data.items():
                        setattr(self.config, k, v)
                
                # 2. Reconstruct Agents
                self.agents.clear()
                agent_rows = session.query(AgentModel).all()
                for row in agent_rows:
                    client = get_agent_client_by_name(row.model_alias)
                    agent = Agent(
                        name=row.name,
                        role=row.role,
                        llm_client=client,
                        role_description=row.role_description,
                        system_instructions=row.system_instructions
                    )
                    agent.last_context = json.loads(row.last_context) if row.last_context else None
                    
                    # Restore agent messages ordered by created_at in the relationship definition
                    agent.messages = []
                    for msg in row.messages:
                        m_dict = {"role": msg.role, "content": msg.content}
                        if msg.tool_calls is not None:
                            m_dict["tool_calls"] = msg.tool_calls
                        if msg.tool_call_id is not None:
                            m_dict["tool_call_id"] = msg.tool_call_id
                        if msg.name is not None:
                            m_dict["name"] = msg.name
                        agent.messages.append(m_dict)
                    
                    self.agents[agent.name] = agent

                if "root_ai_name" in config_map:
                    root_ai_name = config_map["root_ai_name"]
                    if root_ai_name in self.agents:
                        self.root_ai = self.agents[root_ai_name]
                        if hasattr(self, "supervisor") and self.supervisor:
                            self.supervisor.root_ai = self.root_ai

                # 3. Reconstruct Libraries
                self.libraries.clear()
                library_rows = session.query(LibraryModel).all()
                for row in library_rows:
                    lib = DocumentLibrary(
                        lib_id=row.lib_id,
                        name=row.name,
                        owner_team_id=row.owner_team_id,
                        description=row.description,
                        is_public_visible=bool(row.is_public_visible)
                    )
                    # Clear local directory before restoring
                    import shutil
                    shutil.rmtree(lib.root_dir, ignore_errors=True)
                    os.makedirs(lib.root_dir, exist_ok=True)
                    self.libraries[lib.lib_id] = lib

                files_rows = session.query(DocLibFileModel).all()
                for row in files_rows:
                    lib_id = row.lib_id
                    if lib_id in self.libraries:
                        self.libraries[lib_id].write_file(row.path, row.content)

                # Restore library permissions
                self.library_permissions.clear()
                perms_rows = session.query(LibraryPermissionModel).all()
                for row in perms_rows:
                    lib_id = row.lib_id
                    path = row.path
                    team_id = row.team_id
                    perm = row.permission
                    if lib_id not in self.library_permissions:
                        self.library_permissions[lib_id] = {}
                    if path not in self.library_permissions[lib_id]:
                        self.library_permissions[lib_id][path] = {}
                    self.library_permissions[lib_id][path][team_id] = perm

                # 4. Reconstruct Teams
                self.teams.clear()
                teams_rows = session.query(TeamModel).all()
                team_map = {}
                
                # First pass: Instantiate teams without resolving parent/children references (since some might not be instantiated yet)
                for row in teams_rows:
                    creator_type = row.creator_type
                    creator_id = row.creator_id
                    
                    creator = None
                    if creator_type == "agent":
                        creator = self.agents.get(creator_id)
                    
                    team = AgentTeam(creator=creator, preset_name=row.preset_name, team_purpose=row.team_purpose)
                    team.team_id = row.team_id
                    team.logger = logging.getLogger(f"AgentTeam:{team.team_id}")
                    team.team_progress = row.team_progress
                    team.chapter_num = row.chapter_num
                    team.migration_count = row.migration_count
                    team.communication_rules = json.loads(row.communication_rules) if row.communication_rules else {"allow_sibling_talk": False, "rules": []}
                    team.status_map = json.loads(row.status_map) if row.status_map else {}
                    team.system_instructions = row.system_instructions
                    team.manager = self
                    team_map[team.team_id] = team

                # Second pass: Resolve hierarchy & team creator references
                for row in teams_rows:
                    team_id = row.team_id
                    team = team_map[team_id]
                    
                    parent_team_id = row.parent_team_id
                    if parent_team_id:
                        parent_team = team_map.get(parent_team_id)
                        team._parent_team = parent_team
                        if team not in parent_team.child_teams:
                            parent_team.child_teams.append(team)
                            
                    if row.creator_type == "team" and row.creator_id:
                        team.creator = team_map.get(row.creator_id)

                self.teams = team_map

                # 5. Populate Team Members
                for row in teams_rows:
                    t_id = row.team_id
                    if t_id in self.teams:
                        for member_row in row.members:
                            if member_row.name in self.agents:
                                self.teams[t_id].members.append(self.agents[member_row.name])

                # 6. Associate Built-in DocLibs & Re-bind Tools to Teams
                from ai_team_team.tool import get_default_tools
                for team in self.teams.values():
                    team.doc_library = self.libraries.get(f"DL-{team.team_id}")
                    # Re-bind tools
                    team.tools.clear()
                    team.tools.update(get_default_tools(self.tools_context, team))
                    team.tools.update(self.global_tools)

                # 7. Restore Team Inboxes
                for row in teams_rows:
                    t_id = row.team_id
                    if t_id in self.teams:
                        for inbox_row in row.inbox:
                            msg = json.loads(inbox_row.payload)
                            self.teams[t_id].message_inbox.append(msg)

                # 8. Restore Proposals
                for row in teams_rows:
                    t_id = row.team_id
                    if t_id in self.teams:
                        for prop_row in row.proposals:
                            prop_id = prop_row.proposal_id
                            self.teams[t_id].proposals[prop_id] = {
                                "action": prop_row.action,
                                "target": prop_row.target,
                                "initiator_type": prop_row.initiator_type,
                                "initiator_name": prop_row.initiator_name,
                                "rationale": prop_row.rationale,
                                "proposed_details": json.loads(prop_row.proposed_details) if prop_row.proposed_details else {},
                                "votes": json.loads(prop_row.votes) if prop_row.votes else {},
                                "status": prop_row.status
                            }

                # 9. Restore Broker peer agreements
                self.broker.peer_talk_agreements.clear()
                agreements_rows = session.query(BrokerAgreementModel).all()
                for row in agreements_rows:
                    self.broker.peer_talk_agreements.add((row.sender_team_id, row.recipient_team_id))

            self.logger.info(f"Successfully loaded state from SQLite database: {db_path}")
        except Exception as e:
            self.logger.error(f"Error loading state from SQLite database {db_path}: {e}")
            raise e
