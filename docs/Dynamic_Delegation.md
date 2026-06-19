# Hierarchical Dynamic Delegation Specification

This document details the lifecycle, execution protocol, spawning gates, and safe ReAct tool parsing of the **Hierarchical Dynamic Delegation** framework under the ATT topology.

## 1. Dynamic Spawning & Lineage Hierarchy

Every autonomous task or research query spawns a specialized dynamic Agent Team (AT) inside a tree lineage structure coordinated by the `ATTManager`:

* **Level 0 (Root AI)**: The primary coordinating workflow agent (e.g. Root_AI_Level_0).
* **Level 1 (Child AT)**: Dynamic Agent Teams spawned by Level 0 or its active members to manage specific domains. Must satisfy `config.min_subagent_team_size` (default: $\ge 3$).
* **Level $N$ (Descendant ATs)**: Dynamic sub-teams recursively launched by higher-level members to run specialized tasks. Depth is strictly constrained by `config.max_delegation_depth`.

Both individual `Agent` instances and `AgentTeam` instances support dynamic spawning via the unified `launch_att()` method. Every team holds a trackable `team_purpose` to broadcast its objective to the network. Furthermore, dynamic teams support **heterogeneous LLM model routing**, allowing different subagent roles (e.g. Planner, Writer) to be dynamically routed to different model configurations registered in `ATTManager` and resolved through the central generator callback handler.

For a detailed step-by-step visual of the spawning control flow, see the [Dynamic Spawning & Tool Binding Flowchart](flowcharts/Spawning_Escalation.md#1-dynamic-spawning--tool-binding-flowchart) and the [Tools Context Registration & Team Spawning Sequence](flowcharts/Negotiation_Broker_Sibling_Routing.md#1-sequence-of-tools-context-registration-&-team-spawning).

## 2. Bounded ReAct Execution Loop & Safe Parser

Agents in dynamic teams resolve tasks inside a structured **Reasoning & Action (ReAct)** loop. The loop alternates between `Thought`, `Action` (tool call), and `Observation` until a `Final Answer` is reached or the step limit is hit (default: 5).

### Prompt Sequence Protocol

1. **System Instruction**: Injects ReAct formatting instructions alongside the dynamic identity profile and the list of available tools:

   ```text
   Thought: Analyzing rule constraints in database.
   Action: query_sqlite(SELECT status FROM characters WHERE name = 'Iris')
   Observation: [('dead',)]
   
   Thought: The character Iris is dead in the DB.
   Final Answer: Timeline conflict found: Iris is dead, contradiction exists.
   ```

2. **Robust Action & Safe Argument Parser**:
   To ensure high parsing resilience under varying LLM temperatures or when using smaller models, the ReAct parser supports multiple action parsing strategies:
   * **Alternative XML Tag Format**: The parser natively extracts actions structured as XML tags, e.g. `<action name="tool_name">arguments</action>`. If the arguments inside the XML block are wrapped in Markdown code fences (e.g., ` ```python ... ``` `), the parser automatically strips them.
   * **Standard Action Format with Markdown Code Block Stripping**: The parser supports the classic `Action: tool_name(arguments)` pattern and handles wrapping inside Markdown code blocks (e.g., `Action: ```python tool_name(arguments) ``` `).
   * **Multiline Argument Lists**: Regex patterns are compiled with `re.DOTALL` to support multiline argument inputs.
   * **Safe Lexical Scanner**: Once the argument string is extracted, a custom character-by-character tokenizing scanner parses individual parameters. This scanner splits arguments by commas only at the top level (ignoring commas within quotes, or nesting structures like parentheses, brackets, and braces). It evaluates arguments using Python's safe literal evaluation (`ast.literal_eval`) with a robust heuristic merger that recombines split chunks if a top-level comma occurs inside unquoted string values (such as SQL statements or multi-line text), preventing parser crashes when tools accept complex unquoted parameters.

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

For a visual breakdown of sibling communication authorization and inter-team message routing gates, see the [Dynamic Sibling Talk Authorization Sequence](flowcharts/Spawning_Escalation.md#2-dynamic-sibling-talk-authorization-sequence) and the [Sibling & Cross-Lineage Negotiation Flowchart](flowcharts/Negotiation_Broker_Sibling_Routing.md#2-sibling-&-cross-lineage-negotiation-flowchart). For more details on the communication gating strategies, see the [Policy-Based Governance & Decoupled Rules Guide](Policies.md).

## 4. Consolidated Autonomy Tools

* **`dispatch_subagent(task: str, team_purpose: str, member_configs: dict = None, system_instructions: str = "", allow_sibling_talk: bool = False, sibling_talk_rules: str = "", is_public_visible: bool = False, initial_documents: dict = None) -> str`**: Spawns a recursive child AT under the ATT tree. Each AT (AI-Team) must have at least 3 Agents, specified inside `member_configs` (mapping role names to their model alias, role description, and system instructions). Supports optional context passing via `initial_documents` (a map of file paths to content strings pre-populated in the child team's default DocLib).
* **`delegate_escalation(objective: str, rationale: str) -> str`**: Escalates task objectives upward in the lineage tree to the direct parent.
* **`set_sibling_talk(child_id: str, allow: bool) -> str`**: Allows parent teams to dynamically authorize sibling peer communication.
* **`update_team_purpose(new_purpose: str) -> str`**: Updates the purpose string of the caller's team.
* **`update_team_status(purpose: str, progress: str) -> str`**: Allows a team to dynamically update its globally broadcasted purpose and progress metrics.
* **`negotiate_peer_talk(target_team_id: str, rationale: str) -> str`**: Requests parent teams to negotiate a cross-lineage communication agreement.
* **`send_peer_message(team_id: str, message: str) -> str`**: Sends a direct message to a peer team's inbox, subject to sibling rules or parent brokerage agreements.
* **`add_team_member(team_id: str, role_name: str, model_name: str, role_description: str, system_instructions: str) -> str`**: Allows parent teams to administratively add a new member with custom configurations to a child team.
* **`remove_team_member(team_id: str, agent_name: str) -> str`**: Allows parent teams to administratively remove a member from a child team, enforcing the minimum team size constraint of 3.
* **`initiate_membership_vote(action: str, target: str, rationale: str, initiator_type: str = "individual", proposed_details: dict = None) -> str`**: Initiates a democratic membership proposal to add/remove a member.
* **`cast_vote(proposal_id: str, vote: str, public: bool = True, rationale: str = "") -> str`**: Casts a vote ("Agree", "Disagree", or "Abstain") on an active membership proposal. If `public` is set to `False`, the ballot is cast anonymously, hiding the voter's identity in the team discussion context.
* **`retract_membership_vote(proposal_id: str) -> str`**: Allows the initiator of an active proposal to withdraw it.
* **`request_migration(target_parent_id: str, rationale: str) -> str`**: Requests to migrate the caller's team to a new parent team in the active hierarchy. Migrations are arbitrated according to the configured migration policy (which defaults to requiring approvals from the Least Common Ancestor and parent team representatives using their own LLM clients, described in detail in the [Policy-Based Governance & Decoupled Rules Guide](Policies.md)), automatically enforce count limits, and dispatch inbox alerts to the affected parents.
* **`create_doc_library(name: str, description: str, is_public: bool) -> str`**: Creates a new document library owned by the caller's team.
* **`update_library_metadata(lib_id: str, description: Optional[str], is_public: Optional[bool]) -> str`**: Updates metadata or visibility of a library owned by the caller's team.
* **`list_public_libraries() -> str`**: Lists all document libraries registered as publicly visible.
* **`grant_library_permission(lib_id: str, path: str, target_team_id: str, permission: str) -> str`**: Owner team grants READ/WRITE permission to a target team for a path in their library.
* **`revoke_library_permission(lib_id: str, path: str, target_team_id: str) -> str`**: Owner team revokes permissions.
* **`write_library_file(lib_id: str, path: str, content: str) -> str`**: Writes content to a file in a library (requires WRITE permission).
* **`read_library_file(lib_id: str, path: str, start_line: int, end_line: Optional[int]) -> str`**: Reads a file chunk from a library (requires READ permission, checks file-gating).
* **`delete_library_file(lib_id: str, path: str) -> str`**: Deletes a file or directory in a library (requires WRITE permission).
* **`list_library_files(lib_id: str, path: str) -> str`**: Lists files and directories under a path in a library (requires READ permission).
* Custom tools (e.g. database query, semantic search) can be registered dynamically by the host application on `ATTManager`.

## 5. Team Governance & Democratic Voting System

To ensure team autonomy and collaborative membership management, the ATT framework introduces an optional, asynchronous democratic voting system:

* **Optional Activation**: Enabled via `ATTConfig(enable_membership_voting=True)`. By default, it is disabled (`False`).
* **Proposal Mechanics**: Any agent can call `initiate_membership_vote` to propose adding a new member (defining their role, description, instructions, and model) or removing an existing member.
* **Unanimous Participation**: The vote remains active and pending in the team's context. A proposal is only resolved and evaluated once **all** active members of the team have explicitly cast their vote (`"Agree"`, `"Disagree"`, or `"Abstain"`).
* **Consensus Gate**: If all members have voted, the framework calculates the ratio of `"Agree"` votes. A **$\ge 2/3$ majority** of total members is required to approve the proposal. Approved proposals automatically execute their action (creating/appending the new agent or deleting the target agent), while rejected proposals are closed without modification.
* **Anonymous Voting (Public vs. Private Ballots)**: The `cast_vote` tool accepts an optional `public: bool` parameter (default: `True`). Setting `public=False` enforces voter anonymity: the voter's identity is masked as `"Anonymous Voter"` in the active membership votes queue injected into the team's prompt context, while still allowing the system to verify that all distinct members have voted.
