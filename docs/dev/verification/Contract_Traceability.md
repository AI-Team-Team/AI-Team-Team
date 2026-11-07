# Current Contract Traceability

ATT maintains explicit routes from each behavioral verification requirement to its current explanatory section and implementation entry points.

The referenced behavioral ledger supplies the actual test selectors and assertions; this document locates the contract those tests exercise.

A valid link or matching entry count establishes reference integrity, while semantic review still requires reading the stated rule, implementation, and test assertions together.

These routes do not enumerate every archived prose clause; [known implementation differences](../../../todo.md#known-issues) remain open independently of a successful ledger projection.

Historical source dispositions are explained in [Archive Integration](Archive_Integration.md), and the [machine-readable routes](documentation_cases.json) retain exact heading names.

## Maintenance

Update a rule route whenever its canonical explanation, implementation ownership, or behavioral requirement changes.

Use the most specific relevant section, retain distinct routes for different rules in one archived chapter, and add missing explanations before declaring their integration complete.

Runtime test results attest only to their recorded source digest and environment; these maintained routes do not upgrade an earlier archived run into evidence for changed inputs.

## A01: Identity

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A01-01` Joining and leaving preserve Agent-owned fields | [Ordinary Identities](../../Database/Ownership_and_Evidence.md#ordinary-identities) | [agents.py](../../../src/ai_team_team/core/manager/agents.py); [membership.py](../../../src/ai_team_team/core/manager/messaging/membership.py) |
| `A01-02` Shared membership preserves personal memory and private-library ownership | [Identity and Membership Boundary](../../Selective_Episodic_Memory.md#identity-and-membership-boundary); [Ordinary Identities](../../Database/Ownership_and_Evidence.md#ordinary-identities) | [catalog.py](../../../src/ai_team_team/core/manager/memory/service/catalog.py); [private_files.py](../../../src/ai_team_team/core/manager/libraries/private_files.py) |
| `A01-03` Root votes as its own Agent identity | [E. Approval Decisions](../../Team_Governance.md#e-approval-decisions) | [cases.py](../../../src/ai_team_team/core/manager/governance/cases.py); [submissions.py](../../../src/ai_team_team/core/manager/governance/submissions.py) |
| `A01-04` Unaffiliated people enter ordinary formation without identity mutation | [Formation Inputs](../../Consensual_Team_Formation.md#formation-inputs) | [agents.py](../../../src/ai_team_team/core/manager/agents.py); [creation.py](../../../src/ai_team_team/core/manager/formations/lifecycle/creation.py) |

## A02: Activity serialization

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A02-01` Concurrent sources coalesce into one personal admission | [One Owner](../../Autonomous_Agent_Runtime_Architecture/Personal_Scheduling.md#one-owner) | [service.py](../../../src/ai_team_team/core/manager/activity/service.py) |
| `A02-02` Chat and governance coexist without implicit votes in both protocols and durability modes | [Sources and Presentation](../../Autonomous_Agent_Runtime_Architecture/Context_and_Notifications.md#sources-and-presentation); [Personal Email Is Not a Ballot](../../Team_Governance.md#personal-email-is-not-a-ballot) | [notifications.py](../../../src/ai_team_team/core/manager/activity/notifications.py); [submissions.py](../../../src/ai_team_team/core/manager/governance/submissions.py) |
| `A02-03` Other eligible people progress while an independent person waits | [Admission and Fairness](../../Autonomous_Agent_Runtime_Architecture/Personal_Scheduling.md#admission-and-fairness) | [service.py](../../../src/ai_team_team/core/manager/activity/service.py); [runner.py](../../../src/ai_team_team/core/manager/activity/runner.py) |
| `A02-04` Cancellation and unavailable local providers retain one owner | [One Owner](../../Autonomous_Agent_Runtime_Architecture/Personal_Scheduling.md#one-owner); [Retry and Availability](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#retry-and-availability) | [service.py](../../../src/ai_team_team/core/manager/activity/service.py); [models.py](../../../src/ai_team_team/core/manager/activity/models.py) |

## A03: No rounds

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A03-01` A silent member does not prevent another member from reaching idle | [One Owner](../../Autonomous_Agent_Runtime_Architecture/Personal_Scheduling.md#one-owner); [Explicit Controls](../../Autonomous_Agent_Runtime_Architecture/Personal_Scheduling.md#explicit-controls) | [runner.py](../../../src/ai_team_team/core/manager/activity/runner.py); [controls.py](../../../src/ai_team_team/core/manager/activity/controls.py) |
| `A03-02` Ordinary answers continue without automatic publication | [Explicit Controls](../../Autonomous_Agent_Runtime_Architecture/Personal_Scheduling.md#explicit-controls) | [runner.py](../../../src/ai_team_team/core/manager/activity/runner.py); [writes.py](../../../src/ai_team_team/core/manager/messaging/writes.py) |
| `A03-03` Retired methods, result exports, and configuration cannot remain execution paths | [Current Invocation Surface](../../Autonomous_Agent_Runtime_Architecture/Personal_Scheduling.md#current-invocation-surface) | [activity_api.py](../../../src/ai_team_team/core/manager/facade/activity_api.py); [config.py](../../../src/ai_team_team/core/config.py) |
| `A03-04` Governance retains cases without a team discussion engine | [E. Approval Decisions](../../Team_Governance.md#e-approval-decisions) | [cases.py](../../../src/ai_team_team/core/manager/governance/cases.py); [submissions.py](../../../src/ai_team_team/core/manager/governance/submissions.py) |

## A04: Notification boundaries

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A04-01` Arrivals during a provider wait enter the following valid frame | [Sources and Presentation](../../Autonomous_Agent_Runtime_Architecture/Context_and_Notifications.md#sources-and-presentation) | [notifications.py](../../../src/ai_team_team/core/manager/activity/notifications.py) |
| `A04-02` Arrivals during a tool wait enter the following valid frame | [Sources and Presentation](../../Autonomous_Agent_Runtime_Architecture/Context_and_Notifications.md#sources-and-presentation) | [notifications.py](../../../src/ai_team_team/core/manager/activity/notifications.py); [dispatch.py](../../../src/ai_team_team/core/manager/executions/dispatch.py) |
| `A04-03` Native batches retain their scope until all observations settle | [Captured Scope](../../Autonomous_Agent_Runtime_Architecture/Context_and_Notifications.md#captured-scope); [Explicit Controls](../../Autonomous_Agent_Runtime_Architecture/Personal_Scheduling.md#explicit-controls) | [controls.py](../../../src/ai_team_team/core/manager/activity/controls.py); [checkpoints.py](../../../src/ai_team_team/core/manager/activity/checkpoints.py) |
| `A04-04` Arrivals racing idle/checkpoint receipt cannot be stranded | [Sources and Presentation](../../Autonomous_Agent_Runtime_Architecture/Context_and_Notifications.md#sources-and-presentation) | [checkpoints.py](../../../src/ai_team_team/core/manager/activity/checkpoints.py); [notifications.py](../../../src/ai_team_team/core/manager/activity/notifications.py) |

## A05: Presentation semantics

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A05-01` Presented unread mail does not cause repeated admissions or imply reading | [Sources and Presentation](../../Autonomous_Agent_Runtime_Architecture/Context_and_Notifications.md#sources-and-presentation) | [notifications.py](../../../src/ai_team_team/core/manager/activity/notifications.py) |
| `A05-02` Mail opening and read flags never supply a ballot | [Personal Email Is Not a Ballot](../../Team_Governance.md#personal-email-is-not-a-ballot) | [submissions.py](../../../src/ai_team_team/core/manager/governance/submissions.py) |
| `A05-03` Uncertain provider receipt cannot establish successful usage or presentation | [Legal Dispatch and Outcome Combinations](../../Database/Request_and_Token_States.md#legal-dispatch-and-outcome-combinations); [Presentation Claims](../../Database/Request_and_Token_States.md#presentation-claims) | [graph.py](../../../src/ai_team_team/database/persistence/store/validation/graph.py); [models.py](../../../src/ai_team_team/core/manager/activity/models.py) |

## A06: Scope

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A06-01` Shared membership does not supply an ambiguous or borrowed current team | [Captured Scope](../../Autonomous_Agent_Runtime_Architecture/Context_and_Notifications.md#captured-scope) | [service.py](../../../src/ai_team_team/core/manager/activity/service.py) |
| `A06-02` Unavailable or nonmember scopes fail before a provider request | [Captured Scope](../../Autonomous_Agent_Runtime_Architecture/Context_and_Notifications.md#captured-scope) | [service.py](../../../src/ai_team_team/core/manager/activity/service.py) |
| `A06-03` A complete captured batch retains the original scope | [Explicit Controls](../../Autonomous_Agent_Runtime_Architecture/Personal_Scheduling.md#explicit-controls); [Captured Scope](../../Autonomous_Agent_Runtime_Architecture/Context_and_Notifications.md#captured-scope) | [controls.py](../../../src/ai_team_team/core/manager/activity/controls.py); [runner.py](../../../src/ai_team_team/core/manager/activity/runner.py) |
| `A06-04` Valid publication succeeds in live scope and is explicitly denied after dissolution | [Ending a Team Scope](../../Autonomous_Agent_Runtime_Architecture/Context_and_Notifications.md#ending-a-team-scope) | [service.py](../../../src/ai_team_team/core/manager/activity/service.py); [writes.py](../../../src/ai_team_team/core/manager/messaging/writes.py) |

## A07: Team history

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A07-01` Departure freezes revisions and rejoining excludes absence-period sources | [Leaving, Rejoining, and Dissolution](../../Personal_Conversations.md#leaving-rejoining-and-dissolution) | [membership.py](../../../src/ai_team_team/core/manager/messaging/membership.py); [views.py](../../../src/ai_team_team/core/manager/messaging/views.py) |
| `A07-02` Archived conversations remain inspectable without current posting authority | [Leaving, Rejoining, and Dissolution](../../Personal_Conversations.md#leaving-rejoining-and-dissolution) | [archive.py](../../../src/ai_team_team/core/manager/messaging/archive.py); [views.py](../../../src/ai_team_team/core/manager/messaging/views.py) |
| `A07-03` Hidden source counts, searches, pagination, and reply references fail closed | [Leaving, Rejoining, and Dissolution](../../Personal_Conversations.md#leaving-rejoining-and-dissolution) | [views.py](../../../src/ai_team_team/core/manager/messaging/views.py); [reads.py](../../../src/ai_team_team/core/manager/messaging/reads.py) |
| `A07-04` Membership publication and retirement are atomic relationship changes | [Membership and Source Projections](../../State_Persistence.md#membership-and-source-projections); [Retained Lifecycle](../../Autonomous_Agent_Runtime_Architecture/Lifecycle_and_Recovery.md#retained-lifecycle) | [membership.py](../../../src/ai_team_team/core/manager/messaging/membership.py); [agents.py](../../../src/ai_team_team/core/manager/agents.py) |

## A08: Chat read state

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A08-01` Preview inspection never marks a message read | [Titles, Previews, and Body Reads](../../Personal_Conversations.md#titles-previews-and-body-reads) | [views.py](../../../src/ai_team_team/core/manager/messaging/views.py); [reads.py](../../../src/ai_team_team/core/manager/messaging/reads.py) |
| `A08-02` Partial reads return only authorized content with versioned continuation | [Titles, Previews, and Body Reads](../../Personal_Conversations.md#titles-previews-and-body-reads) | [reads.py](../../../src/ai_team_team/core/manager/messaging/reads.py) |
| `A08-03` Read observation and its read marker share accepted persistence | [Titles, Previews, and Body Reads](../../Personal_Conversations.md#titles-previews-and-body-reads); [Chat Views and Read Settlement](../../State_Persistence.md#chat-views-and-read-settlement) | [read_receipts.py](../../../src/ai_team_team/core/manager/messaging/read_receipts.py); [checkpoints.py](../../../src/ai_team_team/core/manager/activity/checkpoints.py) |
| `A08-04` Failures and cancelled siblings do not leave false read facts | [Chat Views and Read Settlement](../../State_Persistence.md#chat-views-and-read-settlement) | [read_receipts.py](../../../src/ai_team_team/core/manager/messaging/read_receipts.py) |
| `A08-05` Explicit unread state and concurrent new revisions remain independent | [Edits, Withdrawal, and Personal Controls](../../Personal_Conversations.md#edits-withdrawal-and-personal-controls); [Chat Views and Read Settlement](../../State_Persistence.md#chat-views-and-read-settlement) | [read_receipts.py](../../../src/ai_team_team/core/manager/messaging/read_receipts.py); [views.py](../../../src/ai_team_team/core/manager/messaging/views.py) |

## A09: Message changes

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A09-01` Titles, Unicode, untitled messages, and code fences obey Markdown limits | [Titles, Previews, and Body Reads](../../Personal_Conversations.md#titles-previews-and-body-reads) | [markdown.py](../../../src/ai_team_team/core/manager/messaging/markdown.py) |
| `A09-02` A successful edit renews the withdrawal deadline and failed edits do not | [Edits, Withdrawal, and Personal Controls](../../Personal_Conversations.md#edits-withdrawal-and-personal-controls) | [writes.py](../../../src/ai_team_team/core/manager/messaging/writes.py) |
| `A09-03` Withdrawal retains separate read and preview history | [Edits, Withdrawal, and Personal Controls](../../Personal_Conversations.md#edits-withdrawal-and-personal-controls) | [writes.py](../../../src/ai_team_team/core/manager/messaging/writes.py); [views.py](../../../src/ai_team_team/core/manager/messaging/views.py) |
| `A09-04` Withdrawn sources cannot be reopened through projection changes | [Edits, Withdrawal, and Personal Controls](../../Personal_Conversations.md#edits-withdrawal-and-personal-controls) | [writes.py](../../../src/ai_team_team/core/manager/messaging/writes.py); [graph.py](../../../src/ai_team_team/database/persistence/store/validation/graph.py) |
| `A09-05` Personal deletion survives editing and restoration is explicit | [Edits, Withdrawal, and Personal Controls](../../Personal_Conversations.md#edits-withdrawal-and-personal-controls) | [views.py](../../../src/ai_team_team/core/manager/messaging/views.py) |

## A10: Withdrawal window evidence

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A10-01` A 1200-second configured window is legal and retains applied historical evidence | [Edits, Withdrawal, and Personal Controls](../../Personal_Conversations.md#edits-withdrawal-and-personal-controls); [Scalar and State Checks](../../Database/Relational_Constraints.md#scalar-and-state-checks) | [writes.py](../../../src/ai_team_team/core/manager/messaging/writes.py); [graph.py](../../../src/ai_team_team/database/persistence/store/validation/graph.py) |
| `A10-02` Nonpositive or nonfinite withdrawal configuration is rejected on construction and assignment | [ConversationConfig](../../user/API_Reference.md#conversationconfig) | [config.py](../../../src/ai_team_team/core/config.py) |
| `A10-03` Source and withdrawal projection must commit together | [Concrete References and Exclusive Choices](../../Database/Relational_Constraints.md#concrete-references-and-exclusive-choices) | [writes.py](../../../src/ai_team_team/core/manager/messaging/writes.py); [graph.py](../../../src/ai_team_team/database/persistence/store/validation/graph.py) |

## A11: Direct admission

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A11-01` Concurrent edits and sends consume one shared directional allowance | [Direct Relationships](../../Personal_Conversations.md#direct-relationships) | [relationships.py](../../../src/ai_team_team/core/manager/messaging/relationships.py); [writes.py](../../../src/ai_team_team/core/manager/messaging/writes.py) |
| `A11-02` Historical-generation and friendship-era edits charge the current period | [Direct Relationships](../../Personal_Conversations.md#direct-relationships) | [relationships.py](../../../src/ai_team_team/core/manager/messaging/relationships.py); [writes.py](../../../src/ai_team_team/core/manager/messaging/writes.py) |
| `A11-03` Failed edits preserve quota, reminders, and the prior withdrawal deadline | [Delivery and Idempotency](../../Personal_Conversations.md#delivery-and-idempotency); [Direct Relationships](../../Personal_Conversations.md#direct-relationships) | [writes.py](../../../src/ai_team_team/core/manager/messaging/writes.py); [relationships.py](../../../src/ai_team_team/core/manager/messaging/relationships.py) |
| `A11-04` Directional allowance and idempotent sends are atomic | [Delivery and Idempotency](../../Personal_Conversations.md#delivery-and-idempotency); [Direct Relationships](../../Personal_Conversations.md#direct-relationships) | [writes.py](../../../src/ai_team_team/core/manager/messaging/writes.py); [relationships.py](../../../src/ai_team_team/core/manager/messaging/relationships.py) |
| `A11-05` Edits share the current allowance and honor blocks | [Direct Relationships](../../Personal_Conversations.md#direct-relationships) | [writes.py](../../../src/ai_team_team/core/manager/messaging/writes.py); [relationships.py](../../../src/ai_team_team/core/manager/messaging/relationships.py) |
| `A11-06` Failed persistence does not charge quota or create delivery | [Delivery and Idempotency](../../Personal_Conversations.md#delivery-and-idempotency) | [writes.py](../../../src/ai_team_team/core/manager/messaging/writes.py) |
| `A11-07` Mixed generation, edit, replay, and restore histories follow current authority | [Direct Relationships](../../Personal_Conversations.md#direct-relationships) | [relationships.py](../../../src/ai_team_team/core/manager/messaging/relationships.py); [graph.py](../../../src/ai_team_team/database/persistence/store/validation/graph.py) |

## A12: Friendship and blocks

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A12-01` Either endpoint blocks both delivery directions; only final unblock resets the period | [Direct Relationships](../../Personal_Conversations.md#direct-relationships) | [relationships.py](../../../src/ai_team_team/core/manager/messaging/relationships.py) |
| `A12-02` Removing absent friendship or cancelling/crossing requests grants no allowance reset | [Direct Relationships](../../Personal_Conversations.md#direct-relationships) | [relationships.py](../../../src/ai_team_team/core/manager/messaging/relationships.py) |
| `A12-03` Accepting during a block race cannot resurrect friendship | [Direct Relationships](../../Personal_Conversations.md#direct-relationships) | [relationships.py](../../../src/ai_team_team/core/manager/messaging/relationships.py) |

## A13: Relationship history and current authorization

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A13-01` Accepted old-generation requests survive removal and restore as history | [Direct Relationships](../../Personal_Conversations.md#direct-relationships) | [relationships.py](../../../src/ai_team_team/core/manager/messaging/relationships.py); [graph.py](../../../src/ai_team_team/database/persistence/store/validation/graph.py) |
| `A13-02` Recipient refusal remains owned and requires explicit lifting | [Direct Relationships](../../Personal_Conversations.md#direct-relationships) | [relationships.py](../../../src/ai_team_team/core/manager/messaging/relationships.py) |
| `A13-03` Generated relationship histories preserve ownership and current authorization | [Direct Relationships](../../Personal_Conversations.md#direct-relationships) | [relationships.py](../../../src/ai_team_team/core/manager/messaging/relationships.py); [graph.py](../../../src/ai_team_team/database/persistence/store/validation/graph.py) |

## A14: Tool contracts

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A14-01` Unknown and foreground-only tools cannot be dispatched in background | [ToolExecutionContract Fields](../../Autonomous_Agent_Runtime_Architecture/Executor_Integration.md#toolexecutioncontract-fields) | [service.py](../../../src/ai_team_team/core/manager/executions/service.py) |
| `A14-02` Auditor denial creates no actual execution attempt | [Executor Binding and ExecutorCall](../../Autonomous_Agent_Runtime_Architecture/Executor_Integration.md#executor-binding-and-executorcall); [ToolExecutionContract Fields](../../Autonomous_Agent_Runtime_Architecture/Executor_Integration.md#toolexecutioncontract-fields) | [dispatch.py](../../../src/ai_team_team/core/manager/executions/dispatch.py); [tool_runtime.py](../../../src/ai_team_team/core/tool_runtime.py) |
| `A14-03` Strict nested validation precedes execution and auditing | [ToolExecutionContract Fields](../../Autonomous_Agent_Runtime_Architecture/Executor_Integration.md#toolexecutioncontract-fields) | [dispatch.py](../../../src/ai_team_team/core/manager/executions/dispatch.py); [tool_runtime.py](../../../src/ai_team_team/core/tool_runtime.py) |
| `A14-04` Self-mutation and actor/policy overrides cannot create background authority | [ToolExecutionContract Fields](../../Autonomous_Agent_Runtime_Architecture/Executor_Integration.md#toolexecutioncontract-fields); [Captured Scope](../../Autonomous_Agent_Runtime_Architecture/Context_and_Notifications.md#captured-scope) | [execution.py](../../../src/ai_team_team/core/activity/contracts/execution.py); [dispatch.py](../../../src/ai_team_team/core/manager/executions/dispatch.py) |

## A15: Resource conflicts

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A15-01` Conflicting resources serialize while independent ones progress | [ResourceClaim and Resolver Contract](../../Autonomous_Agent_Runtime_Architecture/Executor_Integration.md#resourceclaim-and-resolver-contract) | [resources.py](../../../src/ai_team_team/core/manager/executions/resources.py) |
| `A15-02` Foreground and background share reservations across owners | [ResourceClaim and Resolver Contract](../../Autonomous_Agent_Runtime_Architecture/Executor_Integration.md#resourceclaim-and-resolver-contract); [Detachment and Resources](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#detachment-and-resources) | [resources.py](../../../src/ai_team_team/core/manager/executions/resources.py); [dispatch.py](../../../src/ai_team_team/core/manager/executions/dispatch.py) |
| `A15-03` Managed-link target changes cannot redirect an accepted write | [ResourceClaim and Resolver Contract](../../Autonomous_Agent_Runtime_Architecture/Executor_Integration.md#resourceclaim-and-resolver-contract) | [dispatch.py](../../../src/ai_team_team/core/manager/executions/dispatch.py); [access.py](../../../src/ai_team_team/core/manager/libraries/access.py) |
| `A15-04` Concurrent unrelated physical file writes can stage independently | [Detachment and Resources](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#detachment-and-resources) | [doc_library.py](../../../src/ai_team_team/doc_library.py); [resources.py](../../../src/ai_team_team/core/manager/executions/resources.py) |

## A16: Tool availability and retries

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A16-01` Correctable input and ordinary business/permission errors remain observations | [Failure Boundaries](../../Autonomous_Agent_Runtime_Architecture/Personal_Scheduling.md#failure-boundaries); [Registered Operations](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#registered-operations) | [tool_runtime.py](../../../src/ai_team_team/core/tool_runtime.py); [runner.py](../../../src/ai_team_team/core/manager/activity/runner.py) |
| `A16-02` Execution faults cool new same-tool calls, and both protocols report the remaining time without extending the deadline | [Registered Operations](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#registered-operations) | [outcomes.py](../../../src/ai_team_team/core/manager/executions/outcomes.py), [dispatch.py](../../../src/ai_team_team/core/manager/executions/dispatch.py), [context.py](../../../src/ai_team_team/core/manager/activity/context.py) |
| `A16-03` Only typed eligible execution retries replay a tool | [Registered Operations](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#registered-operations) | [tool_runtime.py](../../../src/ai_team_team/core/tool_runtime.py) |
| `A16-04` Provider retry waits remain separate from tool cooldowns | [Retry and Availability](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#retry-and-availability); [Registered Operations](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#registered-operations) | [models.py](../../../src/ai_team_team/core/manager/activity/models.py) |

## A17: Model retry boundaries

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A17-01` Full Jitter caps, per-alias timeouts, and exact framework attempt counts are enforced | [Retry and Availability](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#retry-and-availability) | [models.py](../../../src/ai_team_team/core/manager/activity/models.py) |
| `A17-02` Transient exhaustion waits for its configured recovery boundary | [Retry and Availability](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#retry-and-availability) | [models.py](../../../src/ai_team_team/core/manager/activity/models.py) |
| `A17-03` System instructions, schemas, and output budgets share atomic reservation | [Provider Requests](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#provider-requests); [Token Claim States](../../Database/Request_and_Token_States.md#token-claim-states) | [models.py](../../../src/ai_team_team/core/manager/activity/models.py) |
| `A17-04` Provider wait instructions cannot exceed the remaining whole-sequence budget | [Retry and Availability](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#retry-and-availability) | [models.py](../../../src/ai_team_team/core/manager/activity/models.py) |
| `A17-05` Permanent faults require remediation without periodic recovery | [Retry and Availability](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#retry-and-availability) | [service.py](../../../src/ai_team_team/core/manager/activity/service.py); [models.py](../../../src/ai_team_team/core/manager/activity/models.py) |
| `A17-06` Late responses and unacknowledged local calls remain fenced | [Retry and Availability](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#retry-and-availability) | [models.py](../../../src/ai_team_team/core/manager/activity/models.py) |
| `A17-07` Uncooperative providers cannot indefinitely block manager close | [Retry and Availability](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#retry-and-availability); [Shutdown](../../Autonomous_Agent_Runtime_Architecture/Lifecycle_and_Recovery.md#shutdown) | [models.py](../../../src/ai_team_team/core/manager/activity/models.py); [lifecycle.py](../../../src/ai_team_team/core/manager/executions/lifecycle.py) |

## A18: Cooldown recovery

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A18-01` Downtime-excluded cooldown restores a remainder independently of sleep | [Registered Operations](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#registered-operations); [Timers, Context, and History](../../Database/Recovery_and_Publication.md#timers-context-and-history) | [sleep.py](../../../src/ai_team_team/core/manager/activity/sleep.py); [recovery.py](../../../src/ai_team_team/core/manager/restore/recovery.py) |
| `A18-02` Rejected or cancelled cooldown receipts retain correct live boundaries | [Registered Operations](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#registered-operations) | [outcomes.py](../../../src/ai_team_team/core/manager/executions/outcomes.py) |
| `A18-03` Parallel faults serialize cooldown record versions | [Registered Operations](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#registered-operations) | [outcomes.py](../../../src/ai_team_team/core/manager/executions/outcomes.py) |

## A19: Detachment

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A19-01` Threshold observation detaches the same single execution | [Detachment and Resources](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#detachment-and-resources) | [dispatch.py](../../../src/ai_team_team/core/manager/executions/dispatch.py) |
| `A19-02` Fast siblings and one handle close one complete native batch | [Detachment and Resources](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#detachment-and-resources) | [dispatch.py](../../../src/ai_team_team/core/manager/executions/dispatch.py); [checkpoints.py](../../../src/ai_team_team/core/manager/activity/checkpoints.py) |
| `A19-03` Fast results remain foreground without a second result notice | [Detachment and Resources](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#detachment-and-resources) | [dispatch.py](../../../src/ai_team_team/core/manager/executions/dispatch.py) |

## A20: Artifact execution

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A20-01` Archived private libraries reject ordinary mutation while retained identities can reactivate | [Retained Lifecycle](../../Autonomous_Agent_Runtime_Architecture/Lifecycle_and_Recovery.md#retained-lifecycle); [6. Document Libraries (DocLib)](../../Gated_Reading.md#6-document-libraries-doclib) | [agents.py](../../../src/ai_team_team/core/manager/agents.py); [private_files.py](../../../src/ai_team_team/core/manager/libraries/private_files.py) |
| `A20-02` Private-library ownership and publication remain explicit | [6. Document Libraries (DocLib)](../../Gated_Reading.md#6-document-libraries-doclib); [Ordinary Identities](../../Database/Ownership_and_Evidence.md#ordinary-identities) | [private_files.py](../../../src/ai_team_team/core/manager/libraries/private_files.py) |
| `A20-03` Native symlinks and managed-link cycles cannot escape the managed boundary | [6. Document Libraries (DocLib)](../../Gated_Reading.md#6-document-libraries-doclib) | [doc_library.py](../../../src/ai_team_team/doc_library.py); [access.py](../../../src/ai_team_team/core/manager/libraries/access.py) |
| `A20-04` Managed links recheck current target ACL | [6. Document Libraries (DocLib)](../../Gated_Reading.md#6-document-libraries-doclib) | [access.py](../../../src/ai_team_team/core/manager/libraries/access.py) |
| `A20-05` Already entered atomic writes settle; revoked late writes fail closed | [Isolated Execution Context](../../Autonomous_Agent_Runtime_Architecture/Concurrency_and_Observers.md#isolated-execution-context); [Outcomes and Controls](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#outcomes-and-controls) | [dispatch.py](../../../src/ai_team_team/core/manager/executions/dispatch.py); [doc_library.py](../../../src/ai_team_team/doc_library.py) |

## A21: Cancellation

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A21-01` Queued cancellation prevents dispatch | [Cancellation and Suspension Hooks](../../Autonomous_Agent_Runtime_Architecture/Executor_Integration.md#cancellation-and-suspension-hooks) | [controls.py](../../../src/ai_team_team/core/manager/executions/controls.py) |
| `A21-02` Running cooperative cancellation has factual acknowledgement | [Cancellation and Suspension Hooks](../../Autonomous_Agent_Runtime_Architecture/Executor_Integration.md#cancellation-and-suspension-hooks) | [controls.py](../../../src/ai_team_team/core/manager/executions/controls.py) |
| `A21-03` Threads retain reservations until actual return and known completion wins | [Outcomes and Controls](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#outcomes-and-controls); [Cancellation and Suspension Hooks](../../Autonomous_Agent_Runtime_Architecture/Executor_Integration.md#cancellation-and-suspension-hooks) | [lifecycle.py](../../../src/ai_team_team/core/manager/executions/lifecycle.py); [outcomes.py](../../../src/ai_team_team/core/manager/executions/outcomes.py) |
| `A21-04` Provider suspension requires acknowledgement and otherwise uses supported termination | [Cancellation and Suspension Hooks](../../Autonomous_Agent_Runtime_Architecture/Executor_Integration.md#cancellation-and-suspension-hooks) | [controls.py](../../../src/ai_team_team/core/manager/executions/controls.py); [lifecycle.py](../../../src/ai_team_team/core/manager/executions/lifecycle.py) |
| `A21-05` Accepted local outcomes settle beyond the external grace period | [Outcomes and Controls](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#outcomes-and-controls); [Cancellation Settlement](../../Database/Transactions_and_Validation.md#cancellation-settlement) | [outcomes.py](../../../src/ai_team_team/core/manager/executions/outcomes.py); [lifecycle.py](../../../src/ai_team_team/core/manager/executions/lifecycle.py) |

## A22: Task dimensions

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A22-01` Execution, health, attention, and uncertainty are independent values | [Independent Task Dimensions](../../Background_Tasks.md#independent-task-dimensions) | [queries.py](../../../src/ai_team_team/core/manager/executions/queries.py) |
| `A22-02` Unsupported heartbeat never becomes an inferred stall | [Health Reports and Deadlines](../../Autonomous_Agent_Runtime_Architecture/Executor_Integration.md#health-reports-and-deadlines) | [health.py](../../../src/ai_team_team/core/manager/executions/health.py) |
| `A22-03` Repeated health evidence coalesces only within a consecutive state | [Health Reports and Deadlines](../../Autonomous_Agent_Runtime_Architecture/Executor_Integration.md#health-reports-and-deadlines) | [health.py](../../../src/ai_team_team/core/manager/executions/health.py) |

## A23: Retained task-result access

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A23-01` Default lawful retained results remain owner-readable after revocation | [Protected Results and Stopping](../../Background_Tasks.md#protected-results-and-stopping) | [queries.py](../../../src/ai_team_team/core/manager/executions/queries.py) |
| `A23-02` Restrictive policy cannot borrow a later membership or unverifiable source | [Protected Results and Stopping](../../Background_Tasks.md#protected-results-and-stopping); [ResourceClaim and Resolver Contract](../../Autonomous_Agent_Runtime_Architecture/Executor_Integration.md#resourceclaim-and-resolver-contract) | [queries.py](../../../src/ai_team_team/core/manager/executions/queries.py); [dispatch.py](../../../src/ai_team_team/core/manager/executions/dispatch.py) |
| `A23-03` Revocation before acceptance cannot create a lawful retained body | [Protected Results and Stopping](../../Background_Tasks.md#protected-results-and-stopping) | [outcomes.py](../../../src/ai_team_team/core/manager/executions/outcomes.py) |
| `A23-04` Transient bodies do not reappear after restore or enter durable task payloads | [Private and Transient Content](../../Database/Ownership_and_Evidence.md#private-and-transient-content); [Protected Results and Stopping](../../Background_Tasks.md#protected-results-and-stopping) | [outcomes.py](../../../src/ai_team_team/core/manager/executions/outcomes.py); [queries.py](../../../src/ai_team_team/core/manager/executions/queries.py) |

## A24: Governance

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A24-01` Incomplete electorates, membership changes, and ties cannot become approvals | [E. Approval Decisions](../../Team_Governance.md#e-approval-decisions) | [cases.py](../../../src/ai_team_team/core/manager/governance/cases.py); [submissions.py](../../../src/ai_team_team/core/manager/governance/submissions.py) |
| `A24-02` Reading addressed mail does not vote and actual choices are strict and immutable | [Personal Email Is Not a Ballot](../../Team_Governance.md#personal-email-is-not-a-ballot) | [submissions.py](../../../src/ai_team_team/core/manager/governance/submissions.py) |
| `A24-03` Complete parent electorates and Root identity remain explicit | [E. Approval Decisions](../../Team_Governance.md#e-approval-decisions); [B. Parent Approval Policy ("parent_approval")](../../Team_Governance.md#b-parent-approval-policy-parent_approval) | [cases.py](../../../src/ai_team_team/core/manager/governance/cases.py); [approvals.py](../../../src/ai_team_team/core/broker/approvals.py) |
| `A24-04` Unsupported communication wake is rejected on construction and assignment | [D. Request Delivery and Direction](../../Team_Governance.md#d-request-delivery-and-direction) | [config.py](../../../src/ai_team_team/core/config.py) |
| `A24-05` Case and channel recovery retain exact ballot provenance | [F. Request and Agreement Lifecycle](../../Team_Governance.md#f-request-and-agreement-lifecycle); [Domain Recovery](../../Database/Recovery_and_Publication.md#domain-recovery) | [approvals.py](../../../src/ai_team_team/core/broker/approvals.py); [recovery.py](../../../src/ai_team_team/core/manager/restore/recovery.py) |

## A25: Independence and approval

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A25-01` Independent pairs communicate under every configured institution | [A. Permissive Policy ("permissive")](../../Team_Governance.md#a-permissive-policy-permissive) | [routing.py](../../../src/ai_team_team/core/broker/routing.py) |
| `A25-02` Cross-tree lineage follows real tops without an invented Root | [C. Lineage Approval Policy ("lineage_approval")](../../Team_Governance.md#c-lineage-approval-policy-lineage_approval) | [routing.py](../../../src/ai_team_team/core/broker/routing.py) |
| `A25-03` An independent parent still governs its attached child's requests | [B. Parent Approval Policy ("parent_approval")](../../Team_Governance.md#b-parent-approval-policy-parent_approval) | [routing.py](../../../src/ai_team_team/core/broker/routing.py) |
| `A25-04` Relevant independence transitions stale pending requests | [F. Request and Agreement Lifecycle](../../Team_Governance.md#f-request-and-agreement-lifecycle) | [requests.py](../../../src/ai_team_team/core/broker/requests.py); [routing.py](../../../src/ai_team_team/core/broker/routing.py) |
| `A25-05` Active agreement revocation remains endpoint-owned and directionally idempotent | [F. Request and Agreement Lifecycle](../../Team_Governance.md#f-request-and-agreement-lifecycle) | [lifecycle.py](../../../src/ai_team_team/core/broker/lifecycle.py) |

## A26: Formation

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A26-01` Four attitudes and deliberate None are distinct from mail read flags | [Invitation Attitudes](../../Consensual_Team_Formation.md#invitation-attitudes) | [responses.py](../../../src/ai_team_team/core/manager/formations/lifecycle/responses.py) |
| `A26-02` Material revisions require renewed exact consent and reject stale responses | [Proposal Revisions and Exact Consent](../../Consensual_Team_Formation.md#proposal-revisions-and-exact-consent) | [revisions.py](../../../src/ai_team_team/core/manager/formations/lifecycle/revisions.py) |
| `A26-03` Unanimity, final confirmation, and abandonment retain independent decisions | [Creation and Completion](../../Consensual_Team_Formation.md#creation-and-completion) | [creation.py](../../../src/ai_team_team/core/manager/formations/lifecycle/creation.py) |
| `A26-04` Late joining is invitee-initiated and revalidates lifecycle | [Late Joining](../../Consensual_Team_Formation.md#late-joining) | [late_join.py](../../../src/ai_team_team/core/manager/formations/lifecycle/late_join.py) |
| `A26-05` Optional drafts remain supplied advisory candidates | [Voluntary Design and Optional Candidates](../../Consensual_Team_Formation.md#voluntary-design-and-optional-candidates) | [drafts.py](../../../src/ai_team_team/core/manager/formations/lifecycle/drafts.py) |

## A27: Migration and failover

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A27-01` Actual ancestor and lineage principals govern migration | [4. Migration & Reorganization Policies](../../Team_Governance.md#4-migration--reorganization-policies) | [migration.py](../../../src/ai_team_team/core/manager/migration.py) |
| `A27-02` Migration cooldown and acceptance share successful commit time | [4. Migration & Reorganization Policies](../../Team_Governance.md#4-migration--reorganization-policies) | [migration.py](../../../src/ai_team_team/core/manager/migration.py); [transaction.py](../../../src/ai_team_team/database/persistence/store/writer/transaction.py) |
| `A27-03` Runtime host policy is revalidated after lock and writer waits | [4. Migration & Reorganization Policies](../../Team_Governance.md#4-migration--reorganization-policies) | [migration.py](../../../src/ai_team_team/core/manager/migration.py) |
| `A27-04` Parent failover has its own expiry and rejects late choices without auto fallback | [A. Failover Routing Strategies](../../Team_Governance.md#a-failover-routing-strategies) | [failover.py](../../../src/ai_team_team/core/manager/failover.py) |

## A28: Supervision

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A28-01` Missing explicit findings create no health authority | [Fresh managed lifecycle](../../Supervisory_Team.md#fresh-managed-lifecycle) | [assessment.py](../../../src/ai_team_team/core/manager/supervision/assessment.py) |
| `A28-02` Confirmed integrity faults apply protection before incident persistence | [Triggering an assessment](../../Supervisory_Team.md#triggering-an-assessment) | [health_api.py](../../../src/ai_team_team/core/manager/facade/health_api.py); [incidents.py](../../../src/ai_team_team/core/manager/supervision/incidents.py) |
| `A28-03` Audits create fresh real teams with common runtime and all findings | [Fresh managed lifecycle](../../Supervisory_Team.md#fresh-managed-lifecycle) | [service.py](../../../src/ai_team_team/core/manager/supervision/service.py); [assessment.py](../../../src/ai_team_team/core/manager/supervision/assessment.py) |
| `A28-04` Protocol and tool evidence use separate explicit thresholds | [Triggering an assessment](../../Supervisory_Team.md#triggering-an-assessment) | [detection.py](../../../src/ai_team_team/core/manager/supervision/detection.py) |
| `A28-05` Unavailable audits preserve incidents without stopping ordinary people | [Triggering an assessment](../../Supervisory_Team.md#triggering-an-assessment) | [service.py](../../../src/ai_team_team/core/manager/supervision/service.py); [detection.py](../../../src/ai_team_team/core/manager/supervision/detection.py) |
| `A28-06` Audit deadline includes scheduler capacity and fences late findings | [Fresh managed lifecycle](../../Supervisory_Team.md#fresh-managed-lifecycle) | [service.py](../../../src/ai_team_team/core/manager/supervision/service.py); [assessment.py](../../../src/ai_team_team/core/manager/supervision/assessment.py) |
| `A28-07` Incident handling checks current actual parent authority | [Incident lifecycle](../../Supervisory_Team.md#incident-lifecycle); [7. Health Attention and Escalation](../../Team_Governance.md#7-health-attention-and-escalation) | [incidents.py](../../../src/ai_team_team/core/manager/supervision/incidents.py) |

## A29: Sleep

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A29-01` Countdown units and total bounds are strict and Host-owned | [Intent and Sleep](../../Autonomous_Agent_Runtime_Architecture/Lifecycle_and_Recovery.md#intent-and-sleep) | [sleep.py](../../../src/ai_team_team/core/manager/activity/sleep.py); [controls.py](../../../src/ai_team_team/core/manager/activity/controls.py) |
| `A29-02` Sleep retains a mandatory finite deadline while mail is delivered | [Intent and Sleep](../../Autonomous_Agent_Runtime_Architecture/Lifecycle_and_Recovery.md#intent-and-sleep) | [sleep.py](../../../src/ai_team_team/core/manager/activity/sleep.py) |
| `A29-03` Protected arrivals cross the sleep boundary without loss | [Protected Information and Personal Summaries](../../Autonomous_Agent_Runtime_Architecture/Context_and_Notifications.md#protected-information-and-personal-summaries); [Incident lifecycle](../../Supervisory_Team.md#incident-lifecycle) | [notifications.py](../../../src/ai_team_team/core/manager/activity/notifications.py); [sleep.py](../../../src/ai_team_team/core/manager/activity/sleep.py) |
| `A29-04` Provider unavailability cannot extend voluntary sleep | [Intent and Sleep](../../Autonomous_Agent_Runtime_Architecture/Lifecycle_and_Recovery.md#intent-and-sleep) | [sleep.py](../../../src/ai_team_team/core/manager/activity/sleep.py); [service.py](../../../src/ai_team_team/core/manager/activity/service.py) |

## A30: Do-not-disturb

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A30-01` Permanent and timed preferences share owner and duration rules | [Intent and Sleep](../../Autonomous_Agent_Runtime_Architecture/Lifecycle_and_Recovery.md#intent-and-sleep) | [service.py](../../../src/ai_team_team/core/manager/activity/suppression/service.py) |
| `A30-02` Expiry retains one source-count summary with unchanged read state | [Protected Information and Personal Summaries](../../Autonomous_Agent_Runtime_Architecture/Context_and_Notifications.md#protected-information-and-personal-summaries) | [summaries.py](../../../src/ai_team_team/core/manager/activity/suppression/summaries.py) |
| `A30-03` Summaries never include private bodies, titles, or replay old notices | [Protected Information and Personal Summaries](../../Autonomous_Agent_Runtime_Architecture/Context_and_Notifications.md#protected-information-and-personal-summaries) | [summaries.py](../../../src/ai_team_team/core/manager/activity/suppression/summaries.py) |
| `A30-04` Overlapping preferences and frozen archives remain independently filtered | [Protected Information and Personal Summaries](../../Autonomous_Agent_Runtime_Architecture/Context_and_Notifications.md#protected-information-and-personal-summaries) | [summaries.py](../../../src/ai_team_team/core/manager/activity/suppression/summaries.py) |

## A31: Independent identity and death

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A31-01` Host-confirmed death is terminal and retains private artifacts | [Retained Lifecycle](../../Autonomous_Agent_Runtime_Architecture/Lifecycle_and_Recovery.md#retained-lifecycle) | [death.py](../../../src/ai_team_team/core/manager/agent_lifecycle/death.py); [agents.py](../../../src/ai_team_team/core/manager/agents.py) |
| `A31-02` Death of members or creators preserves surviving teams and direct-child structure | [Retained Lifecycle](../../Autonomous_Agent_Runtime_Architecture/Lifecycle_and_Recovery.md#retained-lifecycle) | [death.py](../../../src/ai_team_team/core/manager/agent_lifecycle/death.py); [topology.py](../../../src/ai_team_team/core/manager/topology.py) |
| `A31-03` Live and queued observers terminate without a prior idle boundary | [Retained Lifecycle](../../Autonomous_Agent_Runtime_Architecture/Lifecycle_and_Recovery.md#retained-lifecycle); [Addressed Interaction and Observation](../../Autonomous_Agent_Runtime_Architecture/Personal_Scheduling.md#addressed-interaction-and-observation) | [death.py](../../../src/ai_team_team/core/manager/agent_lifecycle/death.py); [service.py](../../../src/ai_team_team/core/manager/activity/service.py) |
| `A31-04` Known returned results settle before death closes their authority | [Retained Lifecycle](../../Autonomous_Agent_Runtime_Architecture/Lifecycle_and_Recovery.md#retained-lifecycle) | [death.py](../../../src/ai_team_team/core/manager/agent_lifecycle/death.py); [outcomes.py](../../../src/ai_team_team/core/manager/executions/outcomes.py) |
| `A31-05` Dead identities restore without a model binding or automatic wake | [Retained Lifecycle](../../Autonomous_Agent_Runtime_Architecture/Lifecycle_and_Recovery.md#retained-lifecycle); [Activation and Execution Facts](../../Database/Recovery_and_Publication.md#activation-and-execution-facts) | [recovery.py](../../../src/ai_team_team/core/manager/restore/recovery.py); [graph.py](../../../src/ai_team_team/database/persistence/store/validation/graph.py) |

## A32: Independent teams and live discovery

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A32-01` Parents are explicit and personal membership never infers ancestry | [Ordinary Identities](../../Database/Ownership_and_Evidence.md#ordinary-identities); [Live Queries and Persistence](../../Agent_and_AgentTeam_Discovery.md#live-queries-and-persistence) | [topology.py](../../../src/ai_team_team/core/manager/topology.py); [discovery.py](../../../src/ai_team_team/core/manager/discovery.py) |
| `A32-02` Dissolution and parent retirement detach surviving direct children only | [Retained Lifecycle](../../Autonomous_Agent_Runtime_Architecture/Lifecycle_and_Recovery.md#retained-lifecycle); [Leaving, Rejoining, and Dissolution](../../Personal_Conversations.md#leaving-rejoining-and-dissolution) | [topology.py](../../../src/ai_team_team/core/manager/topology.py); [archive.py](../../../src/ai_team_team/core/manager/messaging/archive.py) |
| `A32-03` Archived teams retain provenance without reentering live topology | [Leaving, Rejoining, and Dissolution](../../Personal_Conversations.md#leaving-rejoining-and-dissolution); [Live Queries and Persistence](../../Agent_and_AgentTeam_Discovery.md#live-queries-and-persistence) | [archive.py](../../../src/ai_team_team/core/manager/messaging/archive.py); [discovery.py](../../../src/ai_team_team/core/manager/discovery.py) |
| `A32-04` Discovery uses restored registries without a persistent directory index | [Live Queries and Persistence](../../Agent_and_AgentTeam_Discovery.md#live-queries-and-persistence) | [discovery.py](../../../src/ai_team_team/core/manager/discovery.py) |

## A33: Voluntary topology changes

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A33-01` Target acceptance and own-position cooldown are required for attachment | [4. Migration & Reorganization Policies](../../Team_Governance.md#4-migration--reorganization-policies) | [migration.py](../../../src/ai_team_team/core/manager/migration.py) |
| `A33-02` Agent tool detachment does not await an old parent | [4. Migration & Reorganization Policies](../../Team_Governance.md#4-migration--reorganization-policies) | [migration.py](../../../src/ai_team_team/core/manager/migration.py) |
| `A33-03` Live Host disablement and exact final authority can reject a waiting transition | [4. Migration & Reorganization Policies](../../Team_Governance.md#4-migration--reorganization-policies) | [migration.py](../../../src/ai_team_team/core/manager/migration.py) |
| `A33-04` Parent provenance survives migration and restoration | [4. Migration & Reorganization Policies](../../Team_Governance.md#4-migration--reorganization-policies); [Ordinary Identities](../../Database/Ownership_and_Evidence.md#ordinary-identities) | [migration.py](../../../src/ai_team_team/core/manager/migration.py); [topology.py](../../../src/ai_team_team/core/manager/topology.py) |

## A34: Countdown recovery

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A34-01` Offline time is excluded and restoration-start anchors survive slow publication | [Timers, Context, and History](../../Database/Recovery_and_Publication.md#timers-context-and-history) | [recovery.py](../../../src/ai_team_team/core/manager/restore/recovery.py); [sleep.py](../../../src/ai_team_team/core/manager/activity/sleep.py) |
| `A34-02` Failed recovery preserves original timer deadlines | [State Replacement](../../Autonomous_Agent_Runtime_Architecture/Lifecycle_and_Recovery.md#state-replacement) | [sleep.py](../../../src/ai_team_team/core/manager/activity/sleep.py); [transaction.py](../../../src/ai_team_team/core/manager/restore/transaction.py) |
| `A34-03` Timer handoffs exclude restore until accepted local settlement | [State Replacement](../../Autonomous_Agent_Runtime_Architecture/Lifecycle_and_Recovery.md#state-replacement) | [sleep.py](../../../src/ai_team_team/core/manager/activity/sleep.py); [service.py](../../../src/ai_team_team/core/manager/restore/service.py) |
| `A34-04` A successful publication hands off exactly one new timer | [State Replacement](../../Autonomous_Agent_Runtime_Architecture/Lifecycle_and_Recovery.md#state-replacement); [Timers, Context, and History](../../Database/Recovery_and_Publication.md#timers-context-and-history) | [recovery.py](../../../src/ai_team_team/core/manager/restore/recovery.py); [sleep.py](../../../src/ai_team_team/core/manager/activity/sleep.py) |

## A35: Incremental persistence

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A35-01` Committed dependency closures survive first partial export | [Immutable Capture and Dependency Closure](../../Database/Transactions_and_Validation.md#immutable-capture-and-dependency-closure) | [durable_records.py](../../../src/ai_team_team/core/manager/durable_records.py); [records.py](../../../src/ai_team_team/database/persistence/records.py) |
| `A35-02` Unrelated identity and team rows remain unchanged for chat-only deltas | [Immutable Capture and Dependency Closure](../../Database/Transactions_and_Validation.md#immutable-capture-and-dependency-closure) | [durable_records.py](../../../src/ai_team_team/core/manager/durable_records.py); [transaction.py](../../../src/ai_team_team/database/persistence/store/writer/transaction.py) |
| `A35-03` Cancelled observers retain accepted writes and exact receipts | [Cancellation Settlement](../../Database/Transactions_and_Validation.md#cancellation-settlement); [Bounded Writer and Exact Acceptance](../../Database/Transactions_and_Validation.md#bounded-writer-and-exact-acceptance) | [durable_records.py](../../../src/ai_team_team/core/manager/durable_records.py); [coordinator.py](../../../src/ai_team_team/database/persistence/coordinator.py) |
| `A35-04` Incremental validation agrees with strict reference validation | [Reference and Incremental Validation](../../Database/Transactions_and_Validation.md#reference-and-incremental-validation) | [database.py](../../../src/ai_team_team/database/persistence/store/validation/database.py) |

## A36: Schema and ownership

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A36-01` Old, future, and malformed schema versions cause no DDL or workspace mutation | [Database Admission](../../Database/Transactions_and_Validation.md#database-admission) | [service.py](../../../src/ai_team_team/database/persistence/store/service.py) |
| `A36-02` Competing processes and abrupt restart enforce exclusive writer ownership | [Database Admission](../../Database/Transactions_and_Validation.md#database-admission) | [lease.py](../../../src/ai_team_team/database/persistence/lease.py) |
| `A36-03` SQLite pragmas and coalesced pending deltas preserve strict writer semantics | [Database Admission](../../Database/Transactions_and_Validation.md#database-admission); [Bounded Writer and Exact Acceptance](../../Database/Transactions_and_Validation.md#bounded-writer-and-exact-acceptance) | [service.py](../../../src/ai_team_team/database/persistence/store/service.py); [coordinator.py](../../../src/ai_team_team/database/persistence/coordinator.py) |

## A37: Durability modes

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A37-01` Durable selection and missing paths are explicit rather than silently volatile | [Incremental single-writer design](../../State_Persistence.md#incremental-single-writer-design) | [manager.py](../../../src/ai_team_team/core/manager/facade/manager.py) |
| `A37-02` Host chat and exports preserve equivalent identities in durable and volatile modes | [Incremental single-writer design](../../State_Persistence.md#incremental-single-writer-design) | [writes.py](../../../src/ai_team_team/core/manager/messaging/writes.py); [membership.py](../../../src/ai_team_team/core/manager/messaging/membership.py) |
| `A37-03` Receipts survive lost responses and retain accepted identities | [Bounded Writer and Exact Acceptance](../../Database/Transactions_and_Validation.md#bounded-writer-and-exact-acceptance) | [records.py](../../../src/ai_team_team/database/persistence/records.py); [coordinator.py](../../../src/ai_team_team/database/persistence/coordinator.py) |
| `A37-04` Complete consumer examples avoid project-root DocLib and verify restored identity | [Incremental single-writer design](../../State_Persistence.md#incremental-single-writer-design); [Complete Offline Example](../../Background_Tasks.md#complete-offline-example) | [personal_activity.py](../../../examples/personal_activity.py); [background_tasks.py](../../../examples/background_tasks.py) |

## A38: Restore corruption

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A38-01` Chat and command-reference corruption cannot change live runtime or files | [Preflight and Staging](../../Database/Recovery_and_Publication.md#preflight-and-staging); [Concrete References and Exclusive Choices](../../Database/Relational_Constraints.md#concrete-references-and-exclusive-choices) | [graph.py](../../../src/ai_team_team/database/persistence/store/validation/graph.py); [service.py](../../../src/ai_team_team/core/manager/restore/service.py) |
| `A38-02` Execution and private-owner reference corruption fails atomically | [Preflight and Staging](../../Database/Recovery_and_Publication.md#preflight-and-staging); [Concrete References and Exclusive Choices](../../Database/Relational_Constraints.md#concrete-references-and-exclusive-choices) | [graph.py](../../../src/ai_team_team/database/persistence/store/validation/graph.py); [service.py](../../../src/ai_team_team/core/manager/restore/service.py) |
| `A38-03` Sleep, suppression, and dead ownership corruption fail before publication | [Preflight and Staging](../../Database/Recovery_and_Publication.md#preflight-and-staging); [Scalar and State Checks](../../Database/Relational_Constraints.md#scalar-and-state-checks) | [graph.py](../../../src/ai_team_team/database/persistence/store/validation/graph.py); [service.py](../../../src/ai_team_team/core/manager/restore/service.py) |
| `A38-04` Memory lifecycle and complete personal context are validated independently | [Preflight and Staging](../../Database/Recovery_and_Publication.md#preflight-and-staging); [Checkpointed Personal Memory](../../Autonomous_Agent_Runtime_Architecture/Context_and_Notifications.md#checkpointed-personal-memory) | [service.py](../../../src/ai_team_team/core/manager/restore/service.py) |

## A39: Crash boundaries

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A39-01` Real exits surround dispatch, returned outcome, and SQLite result commit | [Outcomes and Controls](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#outcomes-and-controls); [Recoverable Publication](../../Database/Recovery_and_Publication.md#recoverable-publication) | [dispatch.py](../../../src/ai_team_team/core/manager/executions/dispatch.py); [outcomes.py](../../../src/ai_team_team/core/manager/executions/outcomes.py) |
| `A39-02` A process exit between directory swaps restores every original library | [Failure Boundaries](../../Database/Recovery_and_Publication.md#failure-boundaries) | [publication.py](../../../src/ai_team_team/database/persistence/publication.py) |
| `A39-03` An exit after recovery receipt but before activation retains one addressed notice | [Recoverable Publication](../../Database/Recovery_and_Publication.md#recoverable-publication) | [recovery.py](../../../src/ai_team_team/core/manager/restore/recovery.py); [publication.py](../../../src/ai_team_team/core/manager/restore/publication.py) |
| `A39-04` Rollback intent restores prior request and quota rows after an actual crash | [Failure Boundaries](../../Database/Recovery_and_Publication.md#failure-boundaries) | [publication_rollback.py](../../../src/ai_team_team/database/persistence/store/publication_rollback.py) |

## A40: Recovery policy

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A40-01` Unfinished Host execution wakes its same owner without replay or reconnect | [Activation and Execution Facts](../../Database/Recovery_and_Publication.md#activation-and-execution-facts) | [recovery.py](../../../src/ai_team_team/core/manager/restore/recovery.py) |
| `A40-02` Unaffected sleep and source read state survive restoration | [Activation and Execution Facts](../../Database/Recovery_and_Publication.md#activation-and-execution-facts); [Timers, Context, and History](../../Database/Recovery_and_Publication.md#timers-context-and-history) | [recovery.py](../../../src/ai_team_team/core/manager/restore/recovery.py) |
| `A40-03` Known terminal results restore attention and provenance without redispatch | [Activation and Execution Facts](../../Database/Recovery_and_Publication.md#activation-and-execution-facts) | [recovery.py](../../../src/ai_team_team/core/manager/restore/recovery.py) |
| `A40-04` Repeated restore deduplicates uncertain execution notices | [Activation and Execution Facts](../../Database/Recovery_and_Publication.md#activation-and-execution-facts) | [recovery.py](../../../src/ai_team_team/core/manager/restore/recovery.py) |

## A41: Runtime replacement

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A41-01` Old synchronous writes and returned delegated authority cannot cross a revoked generation | [Isolated Execution Context](../../Autonomous_Agent_Runtime_Architecture/Concurrency_and_Observers.md#isolated-execution-context) | [dispatch.py](../../../src/ai_team_team/core/manager/executions/dispatch.py); [doc_library.py](../../../src/ai_team_team/doc_library.py) |
| `A41-02` Live executor ownership excludes restore | [Preflight and Staging](../../Database/Recovery_and_Publication.md#preflight-and-staging) | [service.py](../../../src/ai_team_team/core/manager/executions/service.py) |
| `A41-03` Failed runtime publication restores exact previous quota and request facts | [Failure Boundaries](../../Database/Recovery_and_Publication.md#failure-boundaries) | [publication_rollback.py](../../../src/ai_team_team/database/persistence/store/publication_rollback.py); [transaction.py](../../../src/ai_team_team/core/manager/restore/transaction.py) |
| `A41-04` Indexing close and restore suspension cannot leave cancelled queue workers | [Persistence and Restore](../../Selective_Episodic_Memory.md#persistence-and-restore) | [runtime.py](../../../src/ai_team_team/core/manager/memory/service/runtime.py) |

## A42: Privacy

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A42-01` Counts, discovery, callbacks, and operation events contain no chat bodies | [Private and Transient Content](../../Database/Ownership_and_Evidence.md#private-and-transient-content); [Notifications and Privacy](../../Personal_Conversations.md#notifications-and-privacy) | [notifications.py](../../../src/ai_team_team/core/manager/activity/notifications.py); [discovery.py](../../../src/ai_team_team/core/manager/discovery.py) |
| `A42-02` Private observations remain transient across checkpoints and model protocols | [Private and Transient Content](../../Database/Ownership_and_Evidence.md#private-and-transient-content); [Checkpointed Personal Memory](../../Autonomous_Agent_Runtime_Architecture/Context_and_Notifications.md#checkpointed-personal-memory) | [checkpoints.py](../../../src/ai_team_team/core/manager/activity/checkpoints.py); [runner.py](../../../src/ai_team_team/core/manager/activity/runner.py) |
| `A42-03` Voting and audits cannot automatically ingest personal private artifacts | [Evidence and privacy](../../Supervisory_Team.md#evidence-and-privacy); [Personal Email Is Not a Ballot](../../Team_Governance.md#personal-email-is-not-a-ballot) | [service.py](../../../src/ai_team_team/core/manager/supervision/service.py); [submissions.py](../../../src/ai_team_team/core/manager/governance/submissions.py) |
| `A42-04` Result bodies cannot be read by another execution owner | [Protected Results and Stopping](../../Background_Tasks.md#protected-results-and-stopping) | [queries.py](../../../src/ai_team_team/core/manager/executions/queries.py) |

## A43: Optional memory

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A43-01` Disabled mode needs no indexing and can persist Journal without cards | [Enabling the Optional Mode](../../Selective_Episodic_Memory.md#enabling-the-optional-mode); [System Memory Journal](../../Selective_Episodic_Memory.md#system-memory-journal) | [catalog.py](../../../src/ai_team_team/core/manager/memory/service/catalog.py); [runtime.py](../../../src/ai_team_team/core/manager/memory/service/runtime.py) |
| `A43-02` Indexing owns invocation provenance and cannot capture another person or business scope | [Identity and Membership Boundary](../../Selective_Episodic_Memory.md#identity-and-membership-boundary); [Persistence and Restore](../../Selective_Episodic_Memory.md#persistence-and-restore) | [indexing.py](../../../src/ai_team_team/core/manager/memory/service/indexing.py) |
| `A43-03` Ephemeral recall clears and membership leaves the catalog intact | [Working Context](../../Selective_Episodic_Memory.md#working-context); [Identity and Membership Boundary](../../Selective_Episodic_Memory.md#identity-and-membership-boundary) | [catalog.py](../../../src/ai_team_team/core/manager/memory/service/catalog.py); [runner.py](../../../src/ai_team_team/core/manager/activity/runner.py) |
| `A43-04` Disabling with a backlog releases flush and reenable preserves pending indexing | [AI-visible Memory Catalog](../../Selective_Episodic_Memory.md#ai-visible-memory-catalog) | [runtime.py](../../../src/ai_team_team/core/manager/memory/service/runtime.py) |

## A44: Stress and cleanup

| Requirement | Canonical explanation | Implementation |
| --- | --- | --- |
| `A44-01` Ordered callbacks tolerate blocking and failures without blocking the event loop | [Ordered Observational Callbacks](../../Autonomous_Agent_Runtime_Architecture/Concurrency_and_Observers.md#ordered-observational-callbacks) | [callbacks.py](../../../src/ai_team_team/core/manager/callbacks.py) |
| `A44-02` Many-source admissions retain one person and fair independent progress | [Admission and Fairness](../../Autonomous_Agent_Runtime_Architecture/Personal_Scheduling.md#admission-and-fairness) | [service.py](../../../src/ai_team_team/core/manager/activity/service.py) |
| `A44-03` Continuous slow-writer producers retain all keys with two completion handles | [Bounded Writer and Exact Acceptance](../../Database/Transactions_and_Validation.md#bounded-writer-and-exact-acceptance) | [coordinator.py](../../../src/ai_team_team/database/persistence/coordinator.py) |
| `A44-04` Seeded relationship periods preserve current authority across repeated restores | [Direct Relationships](../../Personal_Conversations.md#direct-relationships) | [relationships.py](../../../src/ai_team_team/core/manager/messaging/relationships.py) |
| `A44-05` Loop responsiveness continues while detached validation is blocked | [Immutable Capture and Dependency Closure](../../Database/Transactions_and_Validation.md#immutable-capture-and-dependency-closure) | [database.py](../../../src/ai_team_team/database/persistence/store/validation/database.py) |
