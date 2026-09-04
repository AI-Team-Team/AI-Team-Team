# Core Objects Model

This document serves as the architectural data dictionary for the AI-Team-Team (ATT) framework. It breaks down the properties, state mechanics, and relationships of the primary orchestration classes.

## 1. `ATTManager`: The Master Orchestrator

The `ATTManager` is the public orchestration facade exported by the `ai_team_team.core.manager` package. Its implementation lives in the `manager/facade/` package, while bounded manager-owned packages implement communication validation, serialized discussions, DocLib operations, restore, state validation, and team creation. Additional focused services implement Agent lifecycle, persistence, topology mutation, migration, failover, durable alerts, runtime registries, and ordered callbacks. SQLite work remains coordinated by the single-writer `PersistenceCoordinator` behind `StateCoordinator`.

### Key Internal State

- **`teams (Dict[str, AgentTeam])`**: A flat hash map tracking every active team in the lineage hierarchy by their unique `team_id`.
- **`agents (Dict[str, Agent])`**: Compatibility index of active agents by unique display name.
- **`_agents_by_id (Dict[str, Agent])`**: Authoritative registry of active, retained, and archived identities by immutable UUID.
- **`model_configs (Dict[str, Any])`**: The centralized registry decoupling model identities from underlying provider configurations.
- **`deferred_emergency_tasks (queue.Queue)`**: A thread-safe queue holding `asyncio` coroutines. If an emergency alert triggers while the asyncio event loop is blocked or not running, the task is deferred here and processed later via `manager.flush_deferred_tasks()`.
- **`tools_context (Dict[str, Any])`**: A shared memory space injected into ReAct tools containing references like `{"att_manager": self}`.
- **Invocation Context (`ContextVar`)**: Carries the active agent, team, and discussion ID through nested model and tool calls without caching a shared agent to one owner team.
- **Persistence Coordinator**: Holds one cross-process writer lease, one active delta, and one coalesced pending delta. Snapshot materialization and SQLite work execute off the event loop.
- **State Coordinator**: Owns task-local dirty-state batching, authoritative delta submission, flush operations, and the `PersistenceCoordinator` instance.
- **Agent Registry**: Owns active-name and immutable-ID indexes together with private DocLib lifecycle transitions.
- **Topology Service**: Owns the parent index and topology mutation lock used by lookups, rendering, creation, and migration.
- **Alert Service**: Owns durable alert coalescing, acknowledgement, deferred emergency work, and wakeup deduplication.
- **Callback Dispatcher**: Owns the ordered background callback queue and isolates observer failures from core state changes.
- **Library Service**: Owns runtime ACL resolution, managed-link traversal, private DocLib access, publication, and file movement.
- **Discussion Coordinator**: Owns per-team session serialization, round execution, inbox consumption, structured turn collection, supervision, and post-discussion delivery handling.
- **Snapshot and Restore Services**: Build immutable persistence snapshots, validate state and communication references, stage DocLib files, and publish a restore only after every validation succeeds.
- **Team Creation, Migration, Membership, and Failover Services**: Own their respective governance workflows while the facade preserves the public manager API.
- **Runtime Registry**: Owns model bindings, tool registration, tokenizer selection, presets, capability probes, and invocation-time tool visibility.

## 2. `AgentTeam`: The Dynamic Group Unit

An `AgentTeam` represents a single node in the hierarchy. A team must have at least 3 members to ensure democratic voting validity.

Membership is role-neutral and contains only the relationship between a `team_id` and an `agent_id`. The same `Agent` object may appear in several `team.members` lists; joining or leaving one team does not redefine the Agent or affect any other membership.

### Structural Pointers

- **`parent_team (Optional[AgentTeam])`**: The dual-linked reference to the parent. None for Level 1 teams spawned by the Root AI.
- **`child_teams (List[AgentTeam])`**: References to dynamic sub-teams.
- **`depth (int)`**: A memoized property tracking distance from the Root AI. Migrations recursively invalidate the moved branch's cache.

### Concurrency & Mutation State

- **`state_lock (asyncio.Lock)`**: The asynchronous mutex that protects the team's structural integrity. Any ReAct operation that mutates `self.members`, `self.proposals`, or `self.status_map` MUST acquire this lock via `async with team.state_lock:` to prevent race conditions during `asyncio.gather()` parallel tool executions.
- **`discussion_lock (asyncio.Lock)`**: Serializes ordinary and emergency discussions for this team without blocking discussions in other teams.
- **`message_inbox (List[Dict[str, Any]])`**: The asynchronous receiving queue for sibling messages and parent escalations.
- **`proposals (Dict[str, Dict])`**: Active democratic voting proposals (e.g., adding/removing members).

## 3. `Agent`: The Atomic Actor

The `Agent` encapsulates a single identity and ReAct execution profile.

### Execution Properties

- **`llm_client (LLMClientProto)`**: The attached adapter handling prompt formatting and parsing.
- **`agent_id (str)`**: Immutable canonical UUID used by persistence, team membership, creators, governance identities, and private ownership.
- **`private_doc_library_id (str)`**: Read-only identifier for the one persistent `PDL-<agent_id>` workspace. The raw library object is intentionally not exposed on `Agent`.
- **`lifecycle_state (str)`**: `active`, `retained`, or `archived`; inactive identities leave the active name index and do not require a model binding during restore.
- **`messages (List[Dict])`**: The bounded high-fidelity model window.
- **`message_history (List[Dict])`**: The complete persistent cross-team history; generated records contain `team_id` and `discussion_id`.
- **`lock (asyncio.Lock)`**: Serializes all model work for this identity when the same agent participates in several teams.
- **`max_memory_turns (int)`**: The configuration value defining when the agent compresses old conversational turns into a background summary to save context window tokens.

### ReAct Compilation

The agent does not run its own `while` loop. Instead, the `AgentTeam` invokes `manager.execute_reasoning_step(agent, ...)`, feeding the ReAct output back into the manager's state persistence layer.

Private documents are deliberate artifacts, not hidden reasoning. They enter a model observation only after the owner explicitly invokes `read_private_file`, and enter a team library only after explicit publication.

An Agent's `role`, description, instructions, model binding, memory, lifecycle state, invocation lock, and Private DocLib belong to the Agent identity rather than to any membership. Invocation-scoped team facts are carried through `ContextVar` values and are never persisted as a team-specific Agent identity.
