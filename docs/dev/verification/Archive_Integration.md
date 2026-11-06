# Archived Designs and Current Contracts

ATT keeps the original development sources as historical evidence and explains implemented behavior in current topic guides.

This document identifies the specific current destinations of confirmed rules, superseded descriptions, and deferred proposals.

The [current rule register](Contract_Traceability.md) connects every maintained behavioral requirement to explanatory headings and implementation entry points, while the [behavioral ledger](verification_cases.json) supplies actual test selectors.

The earlier [340-section disposition snapshot](../../../docs_archive/snapshots/2026-11-02-document-disposition.json) records the first transfer and broad destinations as they stood then.

Its repeated file-level descriptions and old directory names are historical routing metadata, not proof that every sentence was integrated or that a present source tree passed a historical test run.

## Integration Scope

The original organization snapshot contains 63 Markdown documents with 340 sections and five structured JSON artifacts.

Current documentation groups their retained rules by subject rather than preserving development-phase and schema-extension boundaries as reader prerequisites.

Individual source sections may combine current requirements, superseded proposals, deferred features, navigation, and dated implementation evidence; those meanings require separate dispositions.

Repeated requirements share a canonical explanation, while permission boundaries, failure conditions, recovery rules, and confirmed defaults remain explicit in that explanation.

Original files and historical measurements remain unchanged, and a known implementation difference remains an open issue rather than becoming a revised requirement.

## Frozen Engineering Contracts

The source below is [Contracts.md](../../../docs_archive/dev/autonomous_activity/Contracts.md), whose initial target API wording predates the final implemented surface.

Separate rows distinguish rules inside a shared archived heading instead of assigning every heading the same target list.

| Archived section and retained rule | Current explanatory section | Behavioral requirements |
| --- | --- | --- |
| Authority and Value Records: identity ownership and membership-only changes. | [Ordinary Identities](../../Database/Ownership_and_Evidence.md#ordinary-identities) | `A01-01`, `A01-02`, `A01-04` |
| Authority and Value Records: validation is distinct from current authority and acceptance. | [Concrete References and Exclusive Choices](../../Database/Relational_Constraints.md#concrete-references-and-exclusive-choices), [Acceptance Before Observation](../../Autonomous_Agent_Runtime_Architecture/Concurrency_and_Observers.md#acceptance-before-observation) | `A14-03`, `A35-03`, `A38-01` |
| Authority and Value Records: explicit durable versus volatile receipts. | [Incremental single-writer design](../../State_Persistence.md#incremental-single-writer-design) | `A37-01`, `A37-02`, `A37-03` |
| One Captured Scope: one actual person/team scope per invocation and Native batch. | [Captured Scope](../../Autonomous_Agent_Runtime_Architecture/Context_and_Notifications.md#captured-scope) | `A06-01`, `A06-02`, `A06-03` |
| One Captured Scope: former-team history supplies no posting or file permission. | [Ending a Team Scope](../../Autonomous_Agent_Runtime_Architecture/Context_and_Notifications.md#ending-a-team-scope), [Leaving, Rejoining, and Dissolution](../../Personal_Conversations.md#leaving-rejoining-and-dissolution) | `A06-04`, `A07-01`, `A07-02` |
| Activity Intent and Fair Yields: continuing by default, personal idle/sleep, and no business-completion inference. | [Explicit Controls](../../Autonomous_Agent_Runtime_Architecture/Personal_Scheduling.md#explicit-controls) | `A03-01`, `A03-02` |
| Activity Intent and Fair Yields: one owner, bounded technical work, and complete-batch control acceptance. | [Admission and Fairness](../../Autonomous_Agent_Runtime_Architecture/Personal_Scheduling.md#admission-and-fairness), [Explicit Controls](../../Autonomous_Agent_Runtime_Architecture/Personal_Scheduling.md#explicit-controls) | `A02-01`, `A02-03`, `A04-03`, `A04-04` |
| Sleep and Suppression: finite countdown, strict units, captured Host bounds, and offline remainder. | [Intent and Sleep](../../Autonomous_Agent_Runtime_Architecture/Lifecycle_and_Recovery.md#intent-and-sleep), [Timers, Context, and History](../../Database/Recovery_and_Publication.md#timers-context-and-history) | `A29-01`, `A29-02`, `A34-01` |
| Sleep and Suppression: permanent/timed preferences, protected notices, and body-free ending summaries. | [Protected Information and Personal Summaries](../../Autonomous_Agent_Runtime_Architecture/Context_and_Notifications.md#protected-information-and-personal-summaries) | `A29-03`, `A30-01`, `A30-02`, `A30-03`, `A30-04` |
| Source, Notice, Frame, and Presentation: fresh causal frames and distinct reservation/presentation/read facts. | [Sources and Presentation](../../Autonomous_Agent_Runtime_Architecture/Context_and_Notifications.md#sources-and-presentation), [Presentation Claims](../../Database/Request_and_Token_States.md#presentation-claims) | `A04-01`, `A04-02`, `A05-01`, `A05-02`, `A05-03` |
| Host Entry Points: current admission, observation, mail, and interaction behavior. | [Admission, Answers, and Checkpoints](../../Personal_Activity.md#admission-answers-and-checkpoints), [Manager API](../../user/API_Reference.md#-attmanager) | `A02-01`, `A03-02`, `A37-04` |
| Host Entry Points: injected runtime clock and lifetime freeze. | [Clock Binding and Offline-Time Accounting](../../Autonomous_Agent_Runtime_Architecture/Lifecycle_and_Recovery.md#clock-binding-and-offline-time-accounting) | `A27-02`, `A29-04`, `A34-01`, `A34-03` |
| Effects, Resources, and Execution: exact effects, whitelist, scope, safety, and binding declarations. | [ToolExecutionContract Fields](../../Autonomous_Agent_Runtime_Architecture/Executor_Integration.md#toolexecutioncontract-fields), [Executor Binding and ExecutorCall](../../Autonomous_Agent_Runtime_Architecture/Executor_Integration.md#executor-binding-and-executorcall) | `A14-01`, `A14-02`, `A14-03`, `A14-04` |
| Effects, Resources, and Execution: cross-owner resources, alias targets, and accepted semantic overwrite. | [ResourceClaim and Resolver Contract](../../Autonomous_Agent_Runtime_Architecture/Executor_Integration.md#resourceclaim-and-resolver-contract) | `A15-01`, `A15-02`, `A15-03`, `A15-04` |
| Effects, Resources, and Execution: same-execution detachment and one Native observation. | [Detachment and Resources](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#detachment-and-resources) | `A19-01`, `A19-02`, `A19-03` |
| Failures, Cooldowns, and Cancellation: correctable observations and accepted same-tool cooldowns. | [Registered Operations](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#registered-operations) | `A16-01`, `A16-02`, `A16-03`, `A18-01`, `A18-02`, `A18-03` |
| Failures, Cooldowns, and Cancellation: model timeout/retry/quota boundaries. | [Retry and Availability](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#retry-and-availability), [Token Claim States](../../Database/Request_and_Token_States.md#token-claim-states) | `A17-01` through `A17-07` |
| Failures, Cooldowns, and Cancellation: factual stops, supported suspension, and accepted local outcomes. | [Cancellation and Suspension Hooks](../../Autonomous_Agent_Runtime_Architecture/Executor_Integration.md#cancellation-and-suspension-hooks), [Outcomes and Controls](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#outcomes-and-controls) | `A21-01` through `A21-05` |
| Confirmed Institutional Boundaries: voluntary exact-case ballots and actual parent principals. | [Approval Decisions](../../Team_Governance.md#e-approval-decisions), [Request and Agreement Lifecycle](../../Team_Governance.md#f-request-and-agreement-lifecycle) | `A24-01` through `A24-05`, `A25-01` through `A25-05` |
| Confirmed Institutional Boundaries: four independent attitudes and exact-revision formation consent. | [Invitation Attitudes](../../Consensual_Team_Formation.md#invitation-attitudes), [Proposal Revisions and Exact Consent](../../Consensual_Team_Formation.md#proposal-revisions-and-exact-consent) | `A26-01` through `A26-05` |
| Confirmed Institutional Boundaries: real temporary audits, forensic identities, and no inferred repair authority. | [Fresh managed lifecycle](../../Supervisory_Team.md#fresh-managed-lifecycle), [Temporary Supervisory Identities](../../Database/Ownership_and_Evidence.md#temporary-supervisory-identities) | `A28-01` through `A28-07`, `A42-03` |
| Confirmed Institutional Boundaries: terminal retained death and independent surviving organizations. | [Retained Lifecycle](../../Autonomous_Agent_Runtime_Architecture/Lifecycle_and_Recovery.md#retained-lifecycle) | `A31-01` through `A31-05`, `A32-01` through `A32-04` |

## Confirmed Blueprint Decisions

The [decision record](../../../docs_archive/blueprints/Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/19_Decision_Status.md) identifies D01 through D15 as confirmed institutions.

Its remaining engineering dependencies and earlier proposed method names describe development history; the destinations below explain the implemented contracts.

| Decision | Current canonical explanation |
| --- | --- |
| D01: continuing personal activity and deliberate idle/sleep. | [Explicit Controls](../../Autonomous_Agent_Runtime_Architecture/Personal_Scheduling.md#explicit-controls) |
| D02: one validated scope with a complete-batch boundary. | [Captured Scope](../../Autonomous_Agent_Runtime_Architecture/Context_and_Notifications.md#captured-scope) |
| D03: voluntary communication queue, independent-side exemptions, and actual lineages. | [Inter-Team Communication Policies](../../Team_Governance.md#3-inter-team-communication-policies) |
| D04: sleep safeguard, suppression, protected notices, summaries, and countdown bounds. | [Explicit Idle, Sleep, and Reminders](../../Personal_Activity.md#explicit-idle-sleep-and-reminders), [Intent and Sleep](../../Autonomous_Agent_Runtime_Architecture/Lifecycle_and_Recovery.md#intent-and-sleep) |
| D05: Markdown sources, authorized revisions/withdrawal, frozen views, and personal archives. | [Personal and AgentTeam Conversations](../../Personal_Conversations.md) |
| D06: atomic stranger allowance, direct edits, blocks/refusal, and explicit friendship. | [Direct Relationships](../../Personal_Conversations.md#direct-relationships), [Delivery and Idempotency](../../Personal_Conversations.md#delivery-and-idempotency) |
| D07: actual-start threshold and same-execution detachment. | [Same Execution, Different Observation](../../Background_Tasks.md#same-execution-different-observation) |
| D08: explicit background whitelist and resource serialization without optimistic overwrite detection. | [ToolExecutionContract Fields](../../Autonomous_Agent_Runtime_Architecture/Executor_Integration.md#toolexecutioncontract-fields), [ResourceClaim and Resolver Contract](../../Autonomous_Agent_Runtime_Architecture/Executor_Integration.md#resourceclaim-and-resolver-contract) |
| D09: factual task dimensions, queryable history, owner-only retained results, and source policy. | [Independent Task Dimensions](../../Background_Tasks.md#independent-task-dimensions), [Protected Results and Stopping](../../Background_Tasks.md#protected-results-and-stopping) |
| D10: fresh real health-assessment teams, full structured participation, deadlines, and explicit incidents. | [Supervisory Team](../../Supervisory_Team.md) |
| D11: independent Agent identity, terminal retained death, surviving teams, target acceptance, and archives. | [Retained Lifecycle](../../Autonomous_Agent_Runtime_Architecture/Lifecycle_and_Recovery.md#retained-lifecycle), [Migration and Reorganization](../../Team_Governance.md#4-migration--reorganization-policies) |
| D12: autonomous proposals, addressed consent, four attitudes, and optional candidates. | [Consensual Formation](../../Consensual_Team_Formation.md) |
| D13: successful own-position cooldown and configured downtime accounting. | [Migration and Reorganization](../../Team_Governance.md#4-migration--reorganization-policies), [Clock Binding](../../Autonomous_Agent_Runtime_Architecture/Lifecycle_and_Recovery.md#clock-binding-and-offline-time-accounting) |
| D14: explicit durable default and intentionally volatile mode. | [Incremental single-writer design](../../State_Persistence.md#incremental-single-writer-design) |
| D15: tool fault cooldown and separate bounded model retries/recovery. | [Registered Operations](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#registered-operations), [Retry and Availability](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#retry-and-availability) |

## Engineering Details and Schema History

| Archived source | Current retained engineering contract |
| --- | --- |
| [Schema 12](../../../docs_archive/dev/autonomous_activity/Schema_12.md) | The current [schema catalogue](../../Database/Schema.md), [complete SQL declarations](../../Database/Schema.sql), and [relational constraints](../../Database/Relational_Constraints.md) cover retained core and all later domains together; schema 12 itself is unsupported. |
| [Schema 13](../../../docs_archive/dev/autonomous_activity/Schema_13.md) | [Chat Views and Read Settlement](../../State_Persistence.md#chat-views-and-read-settlement) retains exact read compensation and immutable command evidence; [conversation rules](../../Personal_Conversations.md) retain unrestricted positive withdrawal windows and historical relationship consent. |
| [Schema 14](../../../docs_archive/dev/autonomous_activity/Schema_14.md) | [Execution and Resource Evidence](../../Database/Schema.md#execution-and-resource-evidence), [exact keys](../../Database/Relational_Constraints.md#declared-primary-and-unique-keys), and [executor integration](../../Autonomous_Agent_Runtime_Architecture/Executor_Integration.md) retain provenance, protected inputs/results, ordered health observations, and declared capabilities. |
| [Schema 15](../../../docs_archive/dev/autonomous_activity/Schema_15.md) | [Institutional authority](../../Database/Schema.md#communication-and-institutional-authority), [governance](../../Team_Governance.md), and [supervision](../../Supervisory_Team.md) retain exact cases, actual parents, temporary audit evidence, and persistent incidents. |
| [Schema 16](../../../docs_archive/dev/autonomous_activity/Schema_16.md) | [Notifications, Suppression, and Sleep](../../Database/Schema.md#notifications-suppression-and-sleep) and [Recovery and Publication](../../Database/Recovery_and_Publication.md) retain ending summaries, countdowns, before-images, acknowledged suspension, and terminal retained death. |
| [Phase 1 engineering profile](../../../docs_archive/dev/autonomous_activity/Phase_1.md) | [Immutable Capture and Dependency Closure](../../Database/Transactions_and_Validation.md#immutable-capture-and-dependency-closure), [exact receipts](../../Database/Transactions_and_Validation.md#bounded-writer-and-exact-acceptance), [request matrices](../../Database/Request_and_Token_States.md), and [recoverable publication](../../Database/Recovery_and_Publication.md#recoverable-publication). |
| [Phase 2 engineering profile](../../../docs_archive/dev/autonomous_activity/Phase_2.md) | [Personal scheduling](../../Autonomous_Agent_Runtime_Architecture/Personal_Scheduling.md), [notification/context boundaries](../../Autonomous_Agent_Runtime_Architecture/Context_and_Notifications.md), [provider/executor coordination](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md), and [concurrency/observers](../../Autonomous_Agent_Runtime_Architecture/Concurrency_and_Observers.md). |
| [Phase 3 engineering profile](../../../docs_archive/dev/autonomous_activity/Phase_3.md) | [Conversation semantics](../../Personal_Conversations.md), [read settlement](../../State_Persistence.md#chat-views-and-read-settlement), and [relational reference validation](../../Database/Relational_Constraints.md#concrete-references-and-exclusive-choices). |
| [Phase 4 engineering profile](../../../docs_archive/dev/autonomous_activity/Phase_4.md) | [Background tasks](../../Background_Tasks.md), [binding contracts](../../Autonomous_Agent_Runtime_Architecture/Executor_Integration.md#executor-binding-and-executorcall), [health evidence/deadlines](../../Autonomous_Agent_Runtime_Architecture/Executor_Integration.md#health-reports-and-deadlines), and [accepted outcomes](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#outcomes-and-controls). |
| [Phase 5 engineering profile](../../../docs_archive/dev/autonomous_activity/Phase_5.md) | [Current invocation surface](../../Autonomous_Agent_Runtime_Architecture/Personal_Scheduling.md#current-invocation-surface), [institutional services](../../Autonomous_Agent_Runtime_Architecture/Institutional_Services.md), and [explicit health incidents](../../Supervisory_Team.md#incident-lifecycle). |
| [Phase 6 engineering profile](../../../docs_archive/dev/autonomous_activity/Phase_6.md) | [Lifecycle and clock handoffs](../../Autonomous_Agent_Runtime_Architecture/Lifecycle_and_Recovery.md), [timer/history recovery](../../Database/Recovery_and_Publication.md#timers-context-and-history), and [publication rollback](../../Database/Recovery_and_Publication.md#failure-boundaries). |
| [Phase 7 documentation profile](../../../docs_archive/dev/autonomous_activity/Phase_7.md) | Current [user reference](../../user/API_Reference.md), [Quickstart](../../user/Quickstart.md), [architecture topics](../../Autonomous_Agent_Runtime_Architecture/README.md), and [example verification](../testing.md#documentation-and-installed-examples). |
| [Phase 8 verification profile](../../../docs_archive/dev/autonomous_activity/Phase_8.md) | Current [verification commands and evidence requirements](README.md), [test guide](../testing.md), [performance methodology](../Performance_Measurement.md), and [behavioral coverage](Verification_Coverage.md). |

The current schema reference describes version `16`; earlier activation chronology and earlier schema numbers remain historical evidence.

Current physical SQL and cross-row validation must agree, rather than treating a later extension document as the complete database definition.

## Superseded Descriptions and Deferred Research

The blueprint's earlier statement that maximum sleep duration, checkpoint interval, and several other engineering defaults were not selected predates the confirmed decisions and implemented configuration.

Current values and strict assignment behavior are maintained in [ATTConfig](../../user/API_Reference.md#-attconfig) and the focused lifecycle/execution references.

Proposed public signatures and transitional `AgentTurnResult`, discussion provenance, mandatory deliberation, and whole-team execution gates do not describe the current API.

The [current invocation surface](../../Autonomous_Agent_Runtime_Architecture/Personal_Scheduling.md#current-invocation-surface) and [current API reference](../../user/API_Reference.md) state the supported behavior.

Communication-approval `wake`, topics/channels/threads, long-lived supervisory teams, and Git-backed Team DocLib collaboration remain separately labeled [Roadmap research](../../../Roadmap/Roadmap.md).

Protected system-notice wake and sleep's finite timer are implemented contracts with independent scheduling rules; deferring immediate communication approval does not disable them.

WorkItem remains a conceptual distinction, with deliberate plans and work judgments stored through existing DocLibs rather than a compulsory framework business-acceptance procedure.

## Specific Blueprint Clauses

Confirmed clauses within a shared chapter need distinct explanations rather than a single chapter-to-guide link.

The following routes make conversation, summary, and detector details explicit while retaining the known implementation difference separately.

| Archived clause | Current explanation | Disposition |
| --- | --- | --- |
| [Ordinary activity and work](../../../docs_archive/blueprints/Autonomous_Agent_Activity_Messaging_and_Background_Tasks/04_Ordinary_Activity.md) and [work artifacts](../../../docs_archive/blueprints/Autonomous_Agent_Activity_Messaging_and_Background_Tasks/09_Work_Artifacts.md): people define work, collaboration, and completion without mandatory business records or a framework acceptance gate. | [Work, Conversation, and Completion](../../Personal_Activity.md#work-conversation-and-completion) | Preserves open-ended work, participant judgments, and the distinction between silence, personal intent, membership, execution, and institutional authority. |
| [Team history](../../../docs_archive/blueprints/Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/08_Team_Conversations.md): accepted stream order defines join/leave visibility, revision limits, and every retrieval surface. | [Leaving, Rejoining, and Dissolution](../../Personal_Conversations.md#leaving-rejoining-and-dissolution), [Edits, Withdrawal, and Personal Controls](../../Personal_Conversations.md#edits-withdrawal-and-personal-controls) | Preserves pre-join and absence exclusions, frozen revision caps, filtered counts/cursors, and independently authorized reply references. |
| [Direct-chat design: rejection and blocks](../../../docs_archive/blueprints/Autonomous_Agent_Activity_Messaging_and_Background_Tasks/08_Direct_Chat_and_Friendship.md#rejection-blocking-and-removing-friendship): rejecting a request creates a recipient-owned refusal. | [Direct Relationships](../../Personal_Conversations.md#direct-relationships) | Documented alongside explicit refusal lifting and independent allowance resets. |
| [Direct-chat plan: relationship transitions](../../../docs_archive/blueprints/Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/09_Direct_Chat_and_Friendship.md#93-relationship-transitions): blocking ends friendship and informs the other person through a system notice. | [Direct Relationships](../../Personal_Conversations.md#direct-relationships) | Documented as addressed relationship mail, without bypassing blocked chat delivery. |
| [Conversation plan: editing and withdrawal](../../../docs_archive/blueprints/Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/08_Team_Conversations.md#84-editing-withdrawal-and-personal-deletion): editing has no time limit. | [Edits, Withdrawal, and Personal Controls](../../Personal_Conversations.md#edits-withdrawal-and-personal-controls) | Documented separately from the withdrawal window and live-authority requirements. |
| [Conversation plan: visibility and read state](../../../docs_archive/blueprints/Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/08_Team_Conversations.md#83-visibility-and-read-state): bounded previews preserve unread totals and disclose clipping. | [Unread Counts and Bounded Previews](../../Personal_Conversations.md#unread-counts-and-bounded-previews) | Documented with the distinction between one unread message and multiple retained revision previews. |
| [Task-summary design](../../../docs_archive/blueprints/Autonomous_Agent_Activity_Messaging_and_Background_Tasks/12_Task_Queries_and_Notifications.md): ordinary prompts include lightweight task counts, and stalled health can overlap running state. | [Model-Visible Task Summary](../../Background_Tasks.md#model-visible-task-summary) | Documented with current live, terminal-attention, suspension, health, and uncertainty aggregation. |
| [Background artifacts and task dimensions](../../../docs_archive/blueprints/Autonomous_Agent_Activity_Messaging_and_Background_Tasks/10_Background_Execution.md): personal file artifacts, health evidence, and task attention remain distinct from personal model mutation. | [Registration and Admission](../../Background_Tasks.md#registration-and-admission), [Independent Task Dimensions](../../Background_Tasks.md#independent-task-dimensions) | Private artifact writes retain live ownership/resource checks; labels, silence, health observations, and reading a task notice supply no automatic state transition or attention acknowledgement. |
| [Foreground execution integration](../../../docs_archive/dev/autonomous_activity/Phase_4.md#tool-and-executor-contracts): foreground and background operations share resource checks, with explicit source-free personal coordination. | [ResourceClaim and Resolver Contract](../../Autonomous_Agent_Runtime_Architecture/Executor_Integration.md#resourceclaim-and-resolver-contract) | Self-modification cannot bypass other effects or shared claims, and nested personal model waits cannot retain conflicting shared resources. |
| [Institutional transactions](../../../docs_archive/blueprints/Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/13_Transactions_and_Concurrency.md): accepted ballots and principal decisions remain durable before the final channel outcome. | [Request and Agreement Lifecycle](../../Team_Governance.md#f-request-and-agreement-lifecycle), [Service-Specific Lock Ordering](../../Autonomous_Agent_Runtime_Architecture/Concurrency_and_Observers.md#service-specific-lock-ordering) | The final Request approval and Agreement creation are atomic together, with actual per-workflow locks and no model wait under local decision protection. |
| [Conversation schema](../../../docs_archive/dev/autonomous_activity/Schema_13.md#additional-tables): earlier revision reads cannot clear later unread revisions or their reminders. | [Host API and Model Tools](../../Personal_Conversations.md#host-api-and-model-tools) | Preserves monotonic personal read evidence independently of explicit version selection and read compensation. |
| [Execution schema](../../../docs_archive/dev/autonomous_activity/Schema_14.md#validation-and-recovery): retained result inspection does not require a historical executor binding. | [Protected Results and Stopping](../../Background_Tasks.md#protected-results-and-stopping) | Retains owner/source authorization without reconnecting or replaying an old operation. |
| [Incident recovery](../../../docs_archive/dev/autonomous_activity/Schema_15.md#health-and-recovery): retained alert delivery resumes independently of health assessment execution. | [Domain Recovery](../../Database/Recovery_and_Publication.md#domain-recovery) | Receipt-owned notification outboxes may resume after publication without recreating auditors or rerunning the assessment. |
| [Health design](../../../docs_archive/blueprints/Autonomous_Agent_Activity_Messaging_and_Background_Tasks/14_Health_Supervision.md): memberships do not reset an Agent's detection state. | [Triggering an assessment](../../Supervisory_Team.md#triggering-an-assessment) | Documented as continuing identity-owned evidence. |
| [Health plan: evidence and triggers](../../../docs_archive/blueprints/Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/12_Health_Supervision.md#121-evidence-and-triggers): count logical observations once and reject language or character style alone as semantic evidence. | [Triggering an assessment](../../Supervisory_Team.md#triggering-an-assessment) | Documented with duplicate-observer and internal-retry exclusions and Host detector responsibilities. |
| [Personal-activity plan: failure isolation](../../../docs_archive/blueprints/Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/05_Personal_Activity.md#54-failure-isolation): cooldown rejection returns remaining time. | [Registered Operations](../../Autonomous_Agent_Runtime_Architecture/Model_and_Tool_Execution.md#registered-operations) and [tracked issue](../../../todo.md#tool-cooldown-remaining-time) | Open implementation difference: the rejection currently omits the duration. |

The maintained matrix and 186-requirement ledger do not enumerate every archived sentence or establish that every clause in a compound row is exercised by its selected tests.

The cooldown disclosure remains an explicit unresolved requirement even when existing cooldown tests pass.

## Maintained Artifacts and Historical Evidence

| Artifact family | Current use |
| --- | --- |
| Original verification matrix, coverage text, and `verification_cases.json`. | Maintained [matrix](Verification_Matrix.md), [behavioral coverage](Verification_Coverage.md), and [ledger](verification_cases.json), with [specific documentation routes](documentation_cases.json). |
| Original `tool_effects.json`. | All 61 frozen effect contracts remain identical in the maintained [tool-effect contract manifest](../../../test/contracts/tool_effects.json), with obsolete migration dispositions removed; this subset is not the complete current tool directory. |
| `Replacement_Inventory.md`, `round_dependencies.json`, and their retired scanner checks. | Historical replacement inventory; continuing absence, identity, schema, privacy, and authority regressions remain functional tests. |
| Original phase test selectors, suite counts, timings, platform notes, and acceptance JSON. | Source-bound historical observations, preserved unchanged rather than relabeled as fresh runs. |
| Original plan sequence, open engineering dependencies, status indexes, and implementation chronology. | Historical design context; current guides state implemented behavior without requiring those stages as reader prerequisites. |

All 186 stable behavioral IDs and requirement texts remain unchanged from the archived ledger.

Current selector updates account for functional test relocation and the exercised audit-privacy control, while the original acceptance JSON retains its original source digests, outcomes, and platform limitations.

Every current rule route should be checked against both its explanatory text and actual assertions, including valid input and positive controls at authority boundaries.

Reference validation prevents broken destinations and missing requirements, while human semantic review determines whether the explanation states the rule accurately and completely.
