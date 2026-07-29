# Core Objects Model

This document serves as the architectural data dictionary for the AI-Team-Team (ATT) framework. It breaks down the properties, state mechanics, and relationships of the primary orchestration classes.

## 1. `ATTManager`: The Master Orchestrator

The `ATTManager` is the singleton-like global event bus and state coordinator. It manages the top-level references to all `AgentTeam` instances and handles deferred async operations.

### Key Internal State

- **`teams (Dict[str, AgentTeam])`**: A flat hash map tracking every active team in the lineage hierarchy by their unique `team_id`.
- **`model_configs (Dict[str, Any])`**: The centralized registry decoupling model identities from underlying provider configurations.
- **`deferred_emergency_tasks (queue.Queue)`**: A thread-safe queue holding `asyncio` coroutines. If an emergency alert triggers while the asyncio event loop is blocked or not running, the task is deferred here and processed later via `manager.flush_deferred_tasks()`.
- **`tools_context (Dict[str, Any])`**: A shared memory space injected into ReAct tools containing references like `{"att_manager": self}`.

## 2. `AgentTeam`: The Dynamic Group Unit

An `AgentTeam` represents a single node in the hierarchy. A team must have at least 3 members to ensure democratic voting validity.

### Structural Pointers

- **`parent_team (Optional[AgentTeam])`**: The dual-linked reference to the parent. None for Level 1 teams spawned by the Root AI.
- **`child_teams (List[AgentTeam])`**: References to dynamic sub-teams.
- **`depth (int)`**: A memoized property tracking distance from the Root AI. Migrations recursively invalidate the moved branch's cache.

### Concurrency & Mutation State

- **`state_lock (asyncio.Lock)`**: The asynchronous mutex that protects the team's structural integrity. Any ReAct operation that mutates `self.members`, `self.proposals`, or `self.status_map` MUST acquire this lock via `async with team.state_lock:` to prevent race conditions during `asyncio.gather()` parallel tool executions.
- **`message_inbox (List[Dict[str, Any]])`**: The asynchronous receiving queue for sibling messages and parent escalations.
- **`proposals (Dict[str, Dict])`**: Active democratic voting proposals (e.g., adding/removing members).

## 3. `Agent`: The Atomic Actor

The `Agent` encapsulates a single identity and ReAct execution profile.

### Execution Properties

- **`llm_client (LLMClientProto)`**: The attached adapter handling prompt formatting and parsing.
- **`messages (List[Dict])`**: The sequential high-fidelity memory buffer.
- **`max_memory_turns (int)`**: The configuration value defining when the agent compresses old conversational turns into a background summary to save context window tokens.

### ReAct Compilation

The agent does not run its own `while` loop. Instead, the `AgentTeam` invokes `manager.execute_reasoning_step(agent, ...)`, feeding the ReAct output back into the manager's state persistence layer.
