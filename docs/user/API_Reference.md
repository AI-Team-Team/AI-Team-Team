# Public API Reference

This document describes the public interface, parameters, and protocol conventions of the `ai-team-team` package. Only components intended for direct instantiation or external interaction are listed here.

## ⚙️ `ATTConfig`

Configuration class to configure the multi-agent framework settings.

### Constructor

```python
from ai_team_team import ATTConfig

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

### Parameters

* **`enable_dynamic_delegation`**: Whether to allow agents to spawn child sub-teams using the `dispatch_subagent` tool.
* **`max_delegation_depth`**: The maximum depth limit of recursive dynamic subagent spawning lineages.
* **`min_subagent_team_size`**: The minimum member count allowed when initiating a dynamic team panel (must be $\ge 3$).
* **`subagent_discussion_rounds`**: The number of debate rounds executed during child subagent panel calls.
* **`react_max_steps`**: The maximum reasoning steps capped per agent turn to prevent infinite ReAct loops.
* **`inbox_summarize_threshold_chars`**: The character threshold above which unread inbox alerts are automatically summarized.
* **`model_registry`**: Mapping of specialized agent roles to specific LLM models or endpoints.

## 👤 `Agent`

Represents an individual AI specialist equipped with role definitions.

### Constructor

```python
from ai_team_team import Agent

agent = Agent(name: str, role: str, llm_client: Optional[Any] = None)
```

### Methods

* **`launch_att(manager: ATTManager, member_count: int = 3, roles_and_presets: Optional[List[Tuple[str, str]]] = None, system_instructions: str = "", team_purpose: str = "Unspecified team purpose") -> AgentTeam`**
  Allows this agent to recursively launch a child dynamic `AgentTeam` structure.

## 🏛️ `ATTManager`

The master controller managing the overall agent team topology, tool registrations, presets, and callback events.

### Constructor

```python
from ai_team_team import ATTManager

manager = ATTManager(root_ai: Agent, critic_client: Any, config: Optional[ATTConfig] = None)
```

### Methods

* **`register_tool(name: str, description: str, func: Callable[..., Any])`**
  Registers a custom utility tool globally to be automatically bound to all dynamic teams.
* **`register_tool_auditor(tool_name: str, auditor_func: Callable[..., Tuple[bool, str]])`**
  Registers an auditing hook executed before specific tool calls.
* **`register_preset(name: str, description: str, system_instructions: str, roles: List[Tuple[str, str]])`**
  Registers a custom dynamic committee preset (e.g. roles and system prompt).
* **`register_tools_context(context: Dict[str, Any])`**
  Registers system resources context (databases, file readers) and automatically binds coordination tools to all teams.
* **`create_agent_team(creator: Any, member_count: int = 3, roles_and_presets: List[Tuple[str, str]] = None, preset_name: str = "custom", system_instructions: str = "", team_purpose: str = "Unspecified") -> AgentTeam`**
  Dynamically spawns a new recursive Agent Team (AT) with a parent-child relationship.
* **`execute_team_discussion(team: AgentTeam, prompt: str, rounds: int = 2) -> str`**
  Executes a multi-agent debate session inside the AT, automatically injecting unresolved inbox alerts, and running supervisory transcript audits.

### Callbacks

* **`on_status_change: Optional[Callable[[str, str], None]]`**
  Invoked when an agent changes state (e.g. `"Thinking..."`, `"Executing Tool..."`, `"Idle"`).
* **`on_activity_added: Optional[Callable[[str, str, str], None]]`**
  Invoked when an agent records a ReAct event. Formatted as: `(agent_name, activity_type, content)`.
* **`on_log_append: Optional[Callable[[str, str, str, Optional[int]], None]]`**
  Invoked when detailed transcripts or execution logs are appended. Formatted as: `(team_id, title, content, chapter_num)`.

## 🛠️ `Tool`

Encapsulates an AI tool with name, description, and execution logic.

### Constructor

```python
from ai_team_team import Tool

tool = Tool(name: str, description: str, func: Callable[..., Any])
```

## 📁 `GatedFileReader`

Size-aware paginated file reader protecting agent context windows.

### Constructor

```python
from ai_team_team import GatedFileReader

reader = GatedFileReader(large_threshold_kb: int = 50, max_chunk: int = 100)
```

### Methods

* **`read_file(path: str, start_line: int = 1, end_line: Optional[int] = None) -> str`**
  Reads a file. Fallbacks to Outline Warning if the file size exceeds `large_threshold_kb` and no `end_line` is provided. Otherwise, returns a line-numbered paginated chunk capped at `max_chunk` lines.
* **`read_file_tail(path: str, line_count: int = 50) -> str`**
  Returns the last `line_count` lines of a file with prepended line numbers.

## 🔌 `LLMClientProto`

Protocol definition for integration of custom LLM backends (adapters).

```python
from typing import Optional, Protocol

class LLMClientProto(Protocol):
    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.3,
        require_json: bool = False
    ) -> str:
        """
        Generates a text completion.
        
        Args:
            prompt: The user query or discussion history.
            system_instruction: Guidelines and context injected for the agent.
            temperature: Sampling temperature.
            require_json: If True, the model MUST return a valid JSON string.
        """
        ...
```
