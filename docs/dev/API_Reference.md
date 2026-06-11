# API Reference

This document provides a technical overview of the core Python classes and public interfaces in the `ai-team-team` package.

## Core Classes

### `Agent`

Represents an individual AI specialist equipped with role definitions and generator client integration.

* **Constructor**:

  ```python
  agent = Agent(name: str, role: str, llm_client: Optional[Any] = None)
  ```

* **Methods**:
  * `launch_att(manager: ATTManager, member_count: int = 3, roles_and_presets: Optional[List[Tuple[str, str]]] = None, system_instructions: str = "", team_purpose: str = "Unspecified team purpose") -> AgentTeam`
        Allows any active agent to recursively launch their own child dynamic `AgentTeam` structure.

### `AgentTeam`

Represents a dynamic team of at least 3 agents ($N \ge 3$) executing discussions, debates, and tasks.

* **Constructor**:

  ```python
  team = AgentTeam(creator: Any, preset_name: str, team_purpose: str = "Unspecified team purpose")
  ```

* **Properties**:
  * `parent_team -> Optional[AgentTeam]`: Resolves the parent team in the lineage tree.
  * `depth -> int`: Returns the lineage depth of the team (Level 1, Level 2, ..., Level $N$).
* **Methods**:
  * `launch_att(...) -> AgentTeam`: Allows the active team to recursively spawn a child team.
  * `receive_message(message: Dict[str, Any])`: Appends incoming signals or parent alerts to the team's inbox queue.
  * `execute_react_step(agent: Agent, prompt: str, system_instruction: str, max_steps: int = 5, manager: Optional[ATTManager] = None) -> str`
        Runs a Reason & Action (ReAct) loop, formatting active tools, executing audited calls, and yielding a `Final Answer`. Handles safe literal evaluations for string arguments containing commas.

### `ATTManager`

Master orchestrator managing the overall ATT topology, dynamic presets, tool registrations, and callback events.

* **Constructor**:

  ```python
  manager = ATTManager(root_ai: Agent, critic_client: Any, config: Optional[ATTConfig] = None)
  ```

* **Methods**:
  * `register_preset(name: str, description: str, system_instructions: str, roles: List[Tuple[str, str]])`
    Registers custom dynamic committee presets.
  * `get_preset(name: str) -> dict`
    Retrieves a registered preset or defaults to `generic`.
  * `register_tool(name: str, description: str, func: Callable[..., Any])`
    Registers a custom tool globally to be automatically bound to all dynamic teams.
  * `register_tool_auditor(tool_name: str, auditor_func: Callable[..., Tuple[bool, str]])`
    Registers an auditing hook callback that intercepts specific tool calls before execution.
  * `register_tools_context(context: Dict[str, Any])`
    Registers system resources context (databases, file readers) and automatically binds coordination tools to all teams.
  * `create_agent_team(creator: Any, member_count: int = 3, roles_and_presets: List[Tuple[str, str]] = None, preset_name: str = "custom", system_instructions: str = "", team_purpose: str = "Unspecified team purpose") -> AgentTeam`
    Spawns a new team of size $N \ge 3$, establishes parent-child lineages, and binds generic/custom tools.
  * `execute_team_discussion(team: AgentTeam, prompt: str, rounds: int = 2) -> str`
    Executes a multi-agent debate session, automatically injecting unresolved inbox alerts, and running supervisory transcript audits.

### `ATTConfig`

Configuration options for tuning the ATT multi-agent framework.

* **Constructor**:

  ```python
  config = ATTConfig(
      enable_dynamic_delegation: bool = True,
      max_delegation_depth: int = 2,
      min_subagent_team_size: int = 3,
      subagent_discussion_rounds: int = 2,
      react_max_steps: int = 5,
      inbox_summarize_threshold_chars: int = 1500,
      model_registry: Optional[dict] = None
  )
  ```

### `NegotiationBroker`

Coordinates sibling and cross-lineage communication permissions.

* **Methods**:
  * `negotiate_communication(sender: AgentTeam, recipient: AgentTeam, mode: str = "proxied") -> bool`
        Checks sibling rules on common parents or runs agreement debates between parent teams to negotiate tunnels.

### `SupervisoryTeam`

A 3-AI supervisory committee checking transcripts for logical deadlocks, circular reasoning, and dialogue health.

* **Methods**:
  * `audit_team_dialog(team: AgentTeam, transcript: str) -> Tuple[bool, str]`
    Audits logs and yields is_healthy status and reasoning.
  * `report_anomaly(failed_team: AgentTeam, reason: str, manager: ATTManager)`
    Escalates failure alerts recursively up ancestors or directly to the Level 0 Root AI.

### `GatedFileReader`

Size-aware paginated file reader protecting agent context windows.

* **Constructor**:

  ```python
  reader = GatedFileReader(large_threshold_kb: int = 50, max_chunk: int = 100)
  ```

* **Methods**:
  * `read_file(path: str, start_line: int = 1, end_line: Optional[int] = None) -> str`
    Reads a file. Fallbacks to Outline Warning if the file size exceeds threshold and no line window is provided.
  * `read_file_tail(path: str, line_count: int = 50) -> str`
    Returns the last line_count lines of a file with prepended line numbers.
