# Core Objects Model

This document serves as the architectural data dictionary for the AI-Team-Team (ATT) framework. It breaks down the properties, state mechanics, and relationships of the primary orchestration classes.

## 1. `ATTManager`: The Master Orchestrator

The `ATTManager` is the public orchestration facade exported by the `ai_team_team.core.manager` package. Its implementation lives in the `manager/facade/` package, while bounded manager-owned packages implement communication validation, personal activity, DocLib operations, restore, state validation, and team creation. Additional focused services implement Agent lifecycle, persistence, topology mutation, migration, failover, durable health incidents, runtime registries, and ordered callbacks. SQLite work remains coordinated by the single-writer `PersistenceCoordinator` behind `StateCoordinator`.

### Key Internal State

- **`teams (Dict[str, AgentTeam])`**: A flat hash map tracking every active team in the lineage hierarchy by their unique `team_id`.
- **`agents (Dict[str, Agent])`**: Compatibility index of active agents by unique display name.
- **`_agents_by_id (Dict[str, Agent])`**: Authoritative registry of active, retained, and archived identities by immutable UUID.
- **`model_configs (Dict[str, Any])`**: The centralized registry decoupling model identities from underlying provider configurations.
- **`tools_context (Dict[str, Any])`**: A shared memory space injected into ReAct tools containing references like `{"att_manager": self}`.
- **Invocation Context (`ContextVar`)**: Carries the active Agent, selected operation scope, and personal invocation ID through nested model and tool calls without caching a shared agent to one owner team.
- **Persistence Coordinator**: Holds one cross-process writer lease, one active delta, and one coalesced pending delta. Snapshot materialization and SQLite work execute off the event loop.
- **State Coordinator**: Owns task-local dirty-state batching, authoritative delta submission, flush operations, and the `PersistenceCoordinator` instance.
- **Agent Registry**: Owns active-name and immutable-ID indexes together with private DocLib lifecycle transitions.
- **Topology Service**: Owns the parent index and topology mutation lock used by lookups, rendering, creation, and migration.
- **Supervision Service**: Owns typed health detection, fresh temporary assessment teams, durable incident coalescing, explicit handling claims, and metadata-only attention delivery.
- **Callback Dispatcher**: Owns the ordered background callback queue and isolates observer failures from core state changes.
- **Library Service**: Owns runtime ACL resolution, managed-link traversal, private DocLib access, publication, and file movement.
- **Personal Activity Service**: Owns one continuing runtime per Agent, bounded invocations, explicit idle and sleep, notification checkpoints, and the common provider/tool execution path.
- **Governance Service**: Owns exact cases, frozen eligible people, immutable explicit choices, and receipt-bound outcomes without a separate inference worker.
- **Snapshot and Restore Services**: Build immutable persistence snapshots, validate state and communication references, stage DocLib files, and publish a restore only after every validation succeeds.
- **Team Creation, Migration, Membership, and Failover Services**: Own their respective governance workflows while the facade preserves the public manager API.
- **Runtime Registry**: Owns model bindings, tool registration, tokenizer selection, presets, capability probes, and invocation-time tool visibility.
- **Discovery Service**: Projects existing public Agent and AgentTeam fields into read-only list, keyword-search, and stable-ID inspection results without injecting global directories, modifying identity or membership, or adding a persisted index.
- **Memory Service**: Owns the append-only Journal and the optional Agent-owned segment, card, FTS5 search, ephemeral recall, retained-reference, and indexing-job state.

## 2. `AgentTeam`: The Dynamic Group Unit

An `AgentTeam` represents an organization in an explicit forest. Its membership must satisfy `config.min_subagent_team_size`, whose default is three.

Membership is role-neutral and contains only the relationship between a `team_id` and an `agent_id`. The same `Agent` object may appear in several `team.members` lists; joining or leaving one team does not redefine the Agent or affect any other membership.

### Structural Pointers

- **`organizational_parent`**: The actual Agent, AgentTeam, or `None`; creator provenance does not select it.
- **`parent_team (Optional[AgentTeam])`**: The AgentTeam parent pointer, when the organizational parent is a team.
- **`is_independent (bool)`**: True only when no organizational parent is recorded.
- **`child_teams (List[AgentTeam])`**: References to dynamic sub-teams.
- **`depth (int)`**: A memoized property tracking distance within its actual parent tree, without manufacturing a Root edge. Migrations recursively invalidate the moved branch's cache.

### Concurrency & Mutation State

- **`state_lock (asyncio.Lock)`**: The asynchronous mutex that protects the team's structural integrity. Any ReAct operation that mutates `self.members`, `self.proposals`, or `self.status_map` MUST acquire this lock via `async with team.state_lock:` to prevent race conditions during `asyncio.gather()` parallel tool executions.
- **`message_inbox (List[Dict[str, Any]])`**: AT-addressed durable references, separate from team chat and every person's model window.
- **`proposals (Dict[str, Dict])`**: Active democratic voting proposals (e.g., adding/removing members).

## 3. `Agent`: The Atomic Actor

The `Agent` encapsulates a single identity and ReAct execution profile.

### Execution Properties

- **`llm_client (LLMClientProto)`**: The attached adapter handling prompt formatting and parsing.
- **`agent_id (str)`**: Immutable canonical UUID used by persistence, team membership, creators, governance identities, and private ownership.
- **`private_doc_library_id (str)`**: Read-only identifier for the one persistent `PDL-<agent_id>` workspace. The raw library object is intentionally not exposed on `Agent`.
- **`lifecycle_state (str)`**: `active`, `retained`, or `archived`; inactive identities leave the active name index and do not require a model binding during restore.
- **`messages (List[Dict])`**: The bounded high-fidelity model window.
- **`message_history (List[Dict])`**: A host-facing compatibility view of the Agent's sanitized Journal message events; it is not loaded into the model-visible `messages` window after restore.
- **`lock (asyncio.Lock)`**: Serializes all model work for this identity when the same agent participates in several teams.
- **`working_context_message_limit (int)`**: A recent-message target for derived context compaction; retained Journal facts and stable identity are not replaced by a different team-specific memory.

### ReAct Compilation

Manager's common personal runtime admits bounded provider/tool invocations for the Agent, preserving one person across all scopes.

An ordinary answer is not automatic team publication, a reply, a ballot, task completion, or a request to stop.

The Agent explicitly chooses idle or finite sleep; scheduler boundaries are not discussion rounds.

Governance and restricted temporary audit profiles use the same runtime rather than invoking a second model execution engine.

Private documents are deliberate artifacts, not hidden reasoning. They enter a model observation only after the owner explicitly invokes `read_private_file`, and enter a team library only after explicit publication.

Selective Episodic Memory is optional and Agent-owned by immutable UUID, so team membership changes cannot copy, clear, relabel, or reassign its Journal events, Memory Cards, indexing jobs, or retained references.

An Agent's `role`, description, instructions, model binding, memory, lifecycle state, invocation lock, and Private DocLib belong to the Agent identity rather than to any membership. Invocation-scoped team facts are carried through `ContextVar` values and are never persisted as a team-specific Agent identity.
