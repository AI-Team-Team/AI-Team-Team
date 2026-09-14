# Hierarchical Dynamic Delegation Specification

This document details the lifecycle, execution protocol, spawning gates, and safe ReAct tool parsing of the **Hierarchical Dynamic Delegation** framework under the ATT topology.

## 1. Dynamic Spawning & Lineage Hierarchy

Every autonomous task or research query spawns a specialized dynamic Agent Team (AT) inside a tree lineage structure coordinated by the `ATTManager`:

* **Level 0 (Root AI)**: The primary coordinating workflow agent (e.g. Root_AI_Level_0).
* **Level 1 (Child AT)**: Dynamic Agent Teams spawned by Level 0 or its active members to manage specific domains. Must satisfy `config.min_subagent_team_size` (default: $\ge 3$).
* **Level $N$ (Descendant ATs)**: Dynamic sub-teams recursively launched by higher-level members to run specialized tasks. Depth is strictly constrained by `config.max_delegation_depth`.

Both individual `Agent` instances and `AgentTeam` instances support dynamic spawning via the unified `launch_att()` method. Every team holds a trackable `team_purpose` to broadcast its objective to the network. Furthermore, dynamic teams support **heterogeneous LLM model routing**, allowing different subagent roles (e.g. Planner, Writer) to be dynamically routed to different model configurations registered in `ATTManager` and resolved through the central generator callback handler.

For a detailed visual of spawning and topology changes, see [Lineage Tree Mutations](flowcharts/Lineage_Tree_Mutations.md).

## 2. Dual-Mode Bounded Reasoning Loops & Safe Parsers

Agents in dynamic teams resolve tasks using a pluggable strategy loop based on configuration or client capabilities:

### Reasoning Strategy Selection

The ATT framework abstracts reasoning execution into distinct strategies to decouple reasoning from LLM provider details:

1. **Text ReAct Mode (`"text_react"`)**: A classic **Reasoning & Action (ReAct)** loop. The loop alternates between `Thought`, `Action` (tool call), and `Observation` until a `Final Answer` is reached or the step limit is hit (default: 5).
2. **Native Tool Calling Mode (`"native"`)**: A native structured tool execution loop. The framework gathers tool schemas (derived from functions, Pydantic, or TypedDict), registers them with the LLM, parses the returning native `tool_calls` payloads, executes all tool calls **concurrently in parallel** using `asyncio.gather`, and resumes the loop until the final answer text is generated or `max_tool_rounds` is reached.
3. **Auto Mode (`"auto"`)**: Uses the manager's safe capability probe. Only a synchronous literal `True` selects Native Mode; exceptions, awaitables, and other values emit a system event and fall back to Text ReAct.

### Prompt Sequence Protocol

1. **System Instruction**: Injects ReAct formatting instructions alongside the dynamic identity profile and the list of available tools:

   ```text
   Thought: Analyzing rule constraints in database.
   Action: query_sqlite("SELECT status FROM characters WHERE name = 'Iris'")
   Observation: [('dead',)]
   
   Thought: The character Iris is dead in the DB.
   Final Answer: Timeline conflict found: Iris is dead, contradiction exists.
   ```

   * **Failover Prompt Protection**: If an agent hits a token limit during the strategy generation phase, the failover loop actively intercepts the retry phase. To prevent the latest user prompt from being repeatedly stuffed into the context queue during a model swap, the loop safely pops the orphaned prompt (`messages.pop()`) before retrying.

2. **Robust Action & Safe Argument Parser**:
   To ensure high parsing resilience under varying LLM temperatures or when using smaller models, the ReAct parser supports multiple action parsing strategies:
   * **Alternative XML Tag Format**: The parser natively extracts actions structured as XML tags, e.g. `<action name="tool_name">arguments</action>`. If the arguments inside the XML block are wrapped in Markdown code fences (e.g., ` ```python ... ``` `), the parser automatically strips them.
   * **Standard Action Format with Markdown Code Block Stripping**: The parser supports the classic `Action: tool_name(arguments)` pattern and handles wrapping inside Markdown code blocks (e.g., `Action: ```python tool_name(arguments) ``` `).
   * **Balanced Python-Call Scanner**: The standard Action scanner tracks `()`, `[]`, `{}`, single and double quotes, triple quotes, escapes, multiline content, Markdown fences, and Unicode. It closes the invocation only when the outer call delimiter closes, so parentheses inside string values cannot truncate the call.
   * **Literal-Only Arguments**: Arguments must be valid Python literals or keyword assignments. Truncated expressions, duplicate keywords, expanded `*args`/`**kwargs`, identifiers, unknown parameters, and type mismatches become `invalid_arguments` observations and never execute the tool. There is no positional-string fallback.

3. **Hierarchical Topology Map**:
   To support organizational awareness and structural modifications, the ReAct prompt's `identity_header` dynamically injects a rendered indented ASCII tree topology map representing all active teams (`manager.render_topology_tree()`). Agents use this map to discover sibling and peer teams and locate potential migration parents.

## 3. Bidirectional Escalation Channel

When an active team or agent at a deep delegation level determines that it needs further automated delegation or hits parent-routing gates:

1. It dispatches a structured escalation message upward to its parent team:

   ```json
   {
     "type": "escalation_spawn",
     "objective": "Task details to be delegated...",
     "rationale": "Objective details...",
     "from": "AT-abc123"
   }
   ```

2. The parent team receives this payload directly into its `message_inbox`.
3. If the parent team is currently idle, receiving this alert triggers the **Active Wake-up Mechanism** (governed by `config.enable_emergency_wakeup`), which automatically starts a 1-round emergency discussion on the parent team to resolve the issue. If the parent team is already active, the `ATTManager` automatically extracts these inbox alerts at the start of the **very next round** (round-by-round consumption) and prepends them directly into the discussion prompt of all agents.
4. Sibling agents in the parent team consume the alerts, formulate resolutions or delegate to a sibling node, and relay results back, maintaining flat execution bounds.

AgentTeam-to-AgentTeam messaging follows the single communication institution in `ATTConfig`, regardless of topology depth. See [Autonomous Communication Governance](flowcharts/Autonomous_Communication_Governance.md) and [Team Governance](Team_Governance.md).

## 4. Consolidated Autonomy Tools

The available tool set is resolved for every invocation. `dispatch_subagent` and the initial/revision deliberation entry point `discuss_team_formation_proposal` are hidden when dynamic delegation is disabled or the current depth reaches `max_delegation_depth`; existing formation requests and drafts can still be inspected, answered, explicitly published, created, or abandoned. `delegate_escalation` is hidden without a parent, and voting tools follow the live voting configuration. Identity prompts describe only tools that are actually available, so configuration changes and migrations affect the next model call immediately.

* **`dispatch_subagent(task: str, team_purpose: str, member_configs: dict = None, existing_member_ids: list[str] = None, system_instructions: str = "", is_public_visible: bool = False, initial_documents: dict = None, initiator_joins: bool = False, unanimous_acceptance_action: str = "require_confirmation", late_join_policy: str = "disabled") -> str`**: All-new delegation creates the child and synchronously runs its discussion. Naming existing Agent IDs or choosing initiator self-membership opens a persistent consent workflow and returns `PENDING_RESPONSES`; ATT creates no team entities or files until an eligible accepted membership commits, and any initial task runs later without holding the initiating Agent's invocation lock.
* **Formation and Agent inbox tools**: `list_agent_inbox`, `mark_agent_inbox_read`, `inspect_team_formation`, `discuss_team_formation_proposal`, `inspect_team_formation_draft`, `retry_team_formation_draft`, `publish_team_formation_draft`, `revise_team_formation`, `respond_team_invitation`, `create_team_from_formation`, `abandon_team_formation`, and `decide_team_formation_late_join` operate from the invocation-scoped Agent identity. Every authorization-bearing action names the exact proposal revision it reviewed, and no tool accepts an acting-Agent override. See [Consensual Existing-Agent Team Formation](Consensual_Team_Formation.md).
* **`delegate_escalation(objective: str, rationale: str) -> str`**: Escalates task objectives upward in the lineage tree to the direct parent.
* **`update_team_purpose(new_purpose: str) -> str`**: Updates the purpose string of the caller's team.
* **`update_team_status(purpose: str, progress: str) -> str`**: Allows a team to dynamically update its globally broadcasted purpose and progress metrics.
* **`request_peer_communication(team_id: str, rationale: str) -> str`**: Requests a durable channel under the configured parent- or lineage-approval institution. The caller cannot override policy, direction, sender, or principals.
* **`send_peer_message(team_id: str, message: str) -> str`**: Durably sends from the invocation-scoped AgentTeam. Approval institutions require an active Agreement; permissive mode does not.
* **`revoke_peer_agreement(agreement_id: str, reason: str) -> str`**: Lets either endpoint AgentTeam revoke a channel.
* **`list_peer_requests(status: str = "pending") -> str`**: Lists communication requests visible to the current endpoint or approval AgentTeam.
* **`list_peer_agreements(active_only: bool = True) -> str`**: Lists Agreements whose endpoints include the current AgentTeam.
* **`add_team_member(team_id: str, role_name: str, model_name: str, role_description: str, system_instructions: str) -> str`**: Allows parent teams to administratively add a new member with custom configurations to a child team.
* **`remove_team_member(team_id: str, agent_name: str) -> str`**: Allows parent teams to administratively remove a member from a child team, enforcing the minimum team size constraint of 3.
* **`initiate_membership_vote(action: str, target: str, rationale: str, initiator_type: str = "individual", proposed_details: dict = None) -> str`**: Initiates a democratic membership proposal to add/remove a member.
* **`cast_vote(proposal_id: str, vote: str, public: bool = True, rationale: str = "") -> str`**: Casts a vote ("Agree", "Disagree", or "Abstain") on an active membership proposal. If `public` is set to `False`, the ballot is cast anonymously, hiding the voter's identity in the team discussion context.
* **`retract_membership_vote(proposal_id: str) -> str`**: Allows the initiator of an active proposal to withdraw it.
* **`request_migration(target_parent_id: str, rationale: str) -> str`**: Requests to migrate the caller's team. The configured migration policy uses explicit AgentTeam principals and the Root Agent at the topology root, then revalidates the topology atomically before committing.
* **`create_doc_library(name: str, description: str, is_public: bool) -> str`**: Creates a new document library owned by the caller's team.
* **`update_library_metadata(lib_id: str, description: Optional[str], is_public: Optional[bool]) -> str`**: Updates metadata or visibility of a library owned by the caller's team.
* **`list_public_libraries() -> str`**: Lists all document libraries registered as publicly visible.
* **`grant_library_permission(lib_id: str, path: str, target_team_id: str, permission: str) -> str`**: Owner team grants READ/WRITE permission to a target team for a path in their library.
* **`revoke_library_permission(lib_id: str, path: str, target_team_id: str) -> str`**: Owner team revokes permissions.
* **`write_library_file(lib_id: str, path: str, content: str) -> str`**: Writes content to a file in a library (requires WRITE permission).
* **`read_library_file(lib_id: str, path: str, start_line: int = 1, end_line: Optional[int] = None, start_character: int = 1, character_count: Optional[int] = None, expected_file_version: Optional[str] = None) -> FileReadResult`**: Reads a token-bounded normalized text range with live READ permission and effective-model token counting.
* **`recall_memory(memory_id: str, start_line: int = 1, end_line: Optional[int] = None, start_character: int = 1, character_count: Optional[int] = None, expected_segment_version: Optional[str] = None) -> MemoryRecallResult`**: When optional episodic memory is enabled, recalls an Agent-owned historical segment with exact line/Unicode-character continuation coordinates and Segment-version validation.
* **`delete_library_file(lib_id: str, path: str) -> str`**: Deletes a file or directory in a library (requires WRITE permission).
* **`list_library_files(lib_id: str, path: str) -> str`**: Lists files and directories under a path in a library (requires READ permission).
* Custom tools (e.g. database query, semantic search) can be registered dynamically by the host application on `ATTManager`.

## 5. Atomic Team Creation

`create_agent_team()` validates the creator, team size, new-member configuration, existing active Agent references, duplicate identities, model aliases, initial document paths and bodies, and mutually exclusive fields before any mutation. Existing Agent inputs open invitations; they do not enter the creation transaction until they accept.

Every consent-bearing proposal starts at revision `1`. Material changes create immutable revision history, reset retained invitation attitudes, and require renewed consent; stale callers cannot respond or create from an older revision. Optional detached creator-AgentTeam deliberation can produce a structured draft before publication, and `formation_deliberation_policy="required_when_team_scoped"` makes that path mandatory for team-scoped proposals and revisions.

New Agent identities, their Private DocLibs, the Team DocLib, and initial files are created under a detached staging directory after the formation becomes eligible. Accepted existing members retain the same object, UUID, identity fields, model binding, memory, invocation lock, lifecycle state, Agent inbox, and Private DocLib; formation notifications are appended to that existing inbox rather than replacing it.

The topology lock then revalidates and commits registry and parent/child state while DocLib directories are atomically published.

A failure at validation, construction, or publication restores registries, pointers, dirty state, and filesystem directories; callbacks, logging, and auto-save begin only after commit. A successful commit adds only `team_id ↔ agent_id` relationships for existing Agents and introduces no framework-level team role.

Synchronous delegation admission applies to work that actually waits for an Agent invocation. Existing-Agent formation is asynchronous and does not reserve a dependency merely because an invitation exists; the general wait-for graph still rejects any later synchronous direct or transitive cycle.

A failure in the team's later first discussion does not roll back the successfully created AgentTeam when creation and dependency admission both succeeded. An unsatisfiable Agent wait cycle is not a discussion failure: it is rejected before creation and leaves all Agent, library, filesystem, and topology state unchanged.

## 6. Team Governance & Democratic Voting System

To ensure team autonomy and collaborative membership management, the ATT framework introduces an optional, asynchronous democratic voting system:

* **Optional Activation**: Enabled via `ATTConfig(enable_membership_voting=True)`. By default, it is disabled (`False`).
* **Proposal Mechanics**: Any agent can call `initiate_membership_vote` to propose adding a new member (defining their role, description, instructions, and model) or removing an existing member.
* **Unanimous Participation**: The vote remains active and pending in the team's context. A proposal is only resolved and evaluated once **all** active members of the team have explicitly cast their vote (`"Agree"`, `"Disagree"`, or `"Abstain"`).
* **Consensus Gate**: If all members have voted, the framework calculates the ratio of `"Agree"` votes. A **$\ge 2/3$ majority** of total members is required to approve the proposal. Approved proposals execute their action (creating/appending the new agent or deleting the target agent); if the team is actively running a debate session, the execution is deferred to the end of the current round to prevent message list and execution state misalignment. Rejected proposals are closed without modification.
* **Anonymous Voting (Public vs. Private Ballots)**: The `cast_vote` tool accepts an optional `public: bool` parameter (default: `True`). Setting `public=False` enforces voter anonymity: the voter's identity is masked as `"Anonymous Voter"` in the active membership votes queue injected into the team's prompt context, while still allowing the system to verify that all distinct members have voted.
* **Concurrency Safety (State Locking)**: All democratic voting actions (`initiate`, `cast_vote`, `retract`) mutate the shared `team.proposals` structure. To guarantee memory safety during parallel `asyncio.gather` tool executions (Native Mode), the `AgentTeam` utilizes a lazy-initialized `state_lock` (`asyncio.Lock`). Every structural mutation to the team's proposal queue is strictly wrapped in this asynchronous mutex, preventing race conditions.
