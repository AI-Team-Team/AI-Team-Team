# Verification Coverage and Evidence

ATT connects the [current verification matrix](Verification_Matrix.md) to independently reviewable behavioral assertions.

The [machine-readable ledger](verification_cases.json) retains stable requirement identities, exact selectors, and current source locations.

Declared coverage and actual execution outcomes are separate facts, as described in the [verification guide](README.md).

This ledger does not enumerate every sentence in the archived blueprints or every clause of a compound matrix row.

In particular, the [cooldown remaining-time response](../../../todo.md#tool-cooldown-remaining-time) is a known implementation gap despite the existing cooldown regressions.

A42-03 maps separate voting and audit assertions: the audit test snapshots actual provider inputs, verifies that explicitly permitted evidence is present, and rejects an owned private-file sentinel from every prompt and instruction.

Evidence-schema rejection and restricted-tool views provide additional boundaries but do not substitute for the input non-injection assertion.

All runtime specification scenarios participate in ordinary discovery, with no separate phase-only gate.

Component fixtures retain their deliberate boundaries, while common-runtime protocol and durability parity is separately covered by the four institutional-chat checks.

## Identity

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A01-01 | Joining and leaving preserve Agent-owned fields. | [test_join_shared_memberships_and_leave_preserve_every_owned_field](../../../test/test_att/test_runtime_contracts/test_identity_invariants.py) |
| A01-02 | Shared membership preserves personal memory and private-library ownership. | [test_membership_changes_do_not_touch_agent_memory](../../../test/test_att/test_episodic_memory/test_persistence_and_privacy/test_identity_lifecycle.py); [test_registration_private_boundary_and_shared_identity](../../../test/test_att/test_private_doclib/test_access_and_publishing.py) |
| A01-03 | Root votes as its own Agent identity. | [test_explicit_root_agent_votes_as_itself_not_as_a_team_replacement](../../../test/test_att/test_failover.py) |
| A01-04 | Unaffiliated people enter ordinary formation without identity mutation. | [test_ordinary_api_only_opens_invitations_and_preserves_agent_identity](../../../test/test_att/test_team_formation/test_consent_and_lifecycle.py); [test_shared_person_has_one_directory_record_and_unchanged_personal_state](../../../test/test_att/test_discovery/test_scope_and_privacy.py) |

## Activity serialization

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A02-01 | Concurrent sources coalesce into one personal admission. | [test_shared_person_admission_coalesces_across_team_scopes](../../../test/test_att/test_runtime_contracts/test_personal_activity_contracts.py) |
| A02-02 | Chat and governance coexist without implicit votes in both protocols and durability modes. | [test_native_volatile_mail_and_chat_preserve_explicit_authority](../../../test/test_att/test_agent_activity/test_institutional_chat_interleavings.py); [test_text_volatile_mail_and_chat_preserve_explicit_authority](../../../test/test_att/test_agent_activity/test_institutional_chat_interleavings.py); [test_native_durable_mail_and_chat_preserve_explicit_authority](../../../test/test_att/test_agent_activity/test_institutional_chat_interleavings.py); [test_text_durable_mail_and_chat_preserve_explicit_authority](../../../test/test_att/test_agent_activity/test_institutional_chat_interleavings.py) |
| A02-03 | Other eligible people progress while an independent person waits. | [test_different_people_are_not_held_by_a_team_barrier](../../../test/test_att/test_agent_activity/test_admission_and_controls.py); [test_budget_yields_fairly_without_setting_idle](../../../test/test_att/test_agent_activity/test_admission_and_controls.py) |
| A02-04 | Cancellation and unavailable local providers retain one owner. | [test_interaction_observer_cannot_cancel_an_already_dispatched_model](../../../test/test_att/test_agent_activity/test_dispatch_receipt_boundaries.py); [test_timeout_preserves_unknown_usage_and_never_overlaps_a_live_local_request](../../../test/test_att/test_agent_activity/test_model_requests.py) |

## No rounds

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A03-01 | A silent member does not prevent another member from reaching idle. | [test_a_silent_member_does_not_hold_another_member_at_a_team_barrier](../../../test/test_att/test_agent_activity/test_scope_boundaries.py) |
| A03-02 | Ordinary answers continue without automatic publication. | [test_a_plain_answer_continues_activity_without_publication](../../../test/test_att/test_runtime_contracts/test_personal_activity_contracts.py) |
| A03-03 | Retired methods, result exports, and configuration cannot remain execution paths. | [test_round_execution_exports_methods_and_configuration_are_absent](../../../test/test_att/test_agent_activity/test_public_runtime_contract.py); [test_public_activity_and_relational_metadata_have_no_round_provenance](../../../test/test_att/test_agent_activity/test_public_runtime_contract.py) |
| A03-04 | Governance retains cases without a team discussion engine. | [test_queue_delivers_personal_ballots_without_a_discussion](../../../test/test_att/test_institutional_runtime/test_communication.py) |

## Notification boundaries

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A04-01 | Arrivals during a provider wait enter the following valid frame. | [test_mail_arriving_during_model_wait_enters_the_next_request_without_overlap](../../../test/test_att/test_agent_activity/test_notifications_and_tools.py) |
| A04-02 | Arrivals during a tool wait enter the following valid frame. | [test_arrival_during_a_tool_wait_enters_the_immediate_next_valid_frame](../../../test/test_att/test_runtime_contracts/test_personal_activity_contracts.py) |
| A04-03 | Native batches retain their scope until all observations settle. | [test_scope_control_keeps_the_entire_native_batch_in_its_original_team](../../../test/test_att/test_agent_activity/test_admission_and_controls.py) |
| A04-04 | Arrivals racing idle/checkpoint receipt cannot be stranded. | [test_arrival_waiting_at_the_idle_checkpoint_cannot_be_stranded](../../../test/test_att/test_agent_activity/test_runtime_boundaries.py); [test_protected_arrival_during_the_sleep_response_is_not_lost_at_the_boundary](../../../test/test_att/test_agent_activity/test_sleep_scope.py) |

## Presentation semantics

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A05-01 | Presented unread mail does not cause repeated admissions or imply reading. | [test_presented_unanswered_mail_does_not_reactivate_or_mark_read](../../../test/test_att/test_agent_activity/test_notifications_and_tools.py); [test_duplicate_trusted_ingress_does_not_wake_a_presented_unread_notice](../../../test/test_att/test_agent_activity/test_dispatch_receipt_boundaries.py) |
| A05-02 | Mail opening and read flags never supply a ballot. | [test_unanswered_read_email_never_becomes_a_vote](../../../test/test_att/test_personal_governance/test_identity_and_mail.py) |
| A05-03 | Uncertain provider receipt cannot establish successful usage or presentation. | [test_cancellation_keeps_unknown_sent_reservation_without_inventing_usage](../../../test/test_att/test_critical_hardening/test_discussion_and_token_budget.py); [test_timeout_preserves_unknown_usage_and_never_overlaps_a_live_local_request](../../../test/test_att/test_agent_activity/test_model_requests.py) |

## Scope

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A06-01 | Shared membership does not supply an ambiguous or borrowed current team. | [test_shared_agent_context_memory_and_serial_calls](../../../test/test_att/test_high_hardening/test_shared_agent_and_lifecycle.py) |
| A06-02 | Unavailable or nonmember scopes fail before a provider request. | [test_missing_or_nonmember_scope_fails_without_a_model_request](../../../test/test_att/test_agent_activity/test_admission_and_controls.py); [test_notification_filter_for_an_external_at_confers_no_membership_or_file_rights](../../../test/test_att/test_agent_activity/test_scope_boundaries.py) |
| A06-03 | A complete captured batch retains the original scope. | [test_scope_control_keeps_the_entire_native_batch_in_its_original_team](../../../test/test_att/test_agent_activity/test_admission_and_controls.py) |
| A06-04 | Valid publication succeeds in live scope and is explicitly denied after dissolution. | [test_the_same_valid_publication_succeeds_while_its_scope_remains_active](../../../test/test_att/test_agent_activity/test_scope_boundaries.py); [test_dissolution_during_a_provider_wait_closes_the_old_scope_before_tools_execute](../../../test/test_att/test_agent_activity/test_scope_boundaries.py) |

## Team history

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A07-01 | Departure freezes revisions and rejoining excludes absence-period sources. | [test_leave_edit_withdraw_rejoin_never_unlocks_an_absence_gap](../../../test/test_att/test_conversations/test_history_and_reads.py) |
| A07-02 | Archived conversations remain inspectable without current posting authority. | [test_archive_closes_membership_and_preserves_inspection_and_personal_controls](../../../test/test_att/test_conversations/test_history_and_reads.py) |
| A07-03 | Hidden source counts, searches, pagination, and reply references fail closed. | [test_list_search_pagination_and_reply_do_not_expose_hidden_sources](../../../test/test_att/test_conversations/test_history_and_reads.py) |
| A07-04 | Membership publication and retirement are atomic relationship changes. | [test_join_and_retirement_are_serialized_without_changing_owned_fields](../../../test/test_att/test_conversations/test_membership_publication.py); [test_member_removal_and_message_publication_share_the_same_lock](../../../test/test_att/test_conversations/test_commit_and_restore.py) |

## Chat read state

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A08-01 | Preview inspection never marks a message read. | [test_team_source_has_personal_views_and_preview_never_marks_read](../../../test/test_att/test_conversations/test_publication.py) |
| A08-02 | Partial reads return only authorized content with versioned continuation. | [test_partial_unicode_read_marks_only_returned_source_and_checks_continuation](../../../test/test_att/test_conversations/test_history_and_reads.py) |
| A08-03 | Read observation and its read marker share accepted persistence. | [test_read_marker_and_observation_share_the_same_writer_snapshot](../../../test/test_att/test_conversations/test_read_checkpoint_durability.py); [test_cancel_after_observation_acceptance_preserves_both_the_body_and_its_read_fact](../../../test/test_att/test_conversations/test_read_checkpoint_durability.py) |
| A08-04 | Failures and cancelled siblings do not leave false read facts. | [test_failed_read_commit_does_not_return_body_or_change_read_state](../../../test/test_att/test_conversations/test_history_and_reads.py); [test_cancelled_native_sibling_does_not_mark_a_prepared_body_read](../../../test/test_att/test_conversations/test_read_delivery.py) |
| A08-05 | Explicit unread state and concurrent new revisions remain independent. | [test_cancelled_read_restores_the_exact_previous_watermark_and_unread_override](../../../test/test_att/test_conversations/test_read_delivery.py); [test_a_new_revision_during_batch_settlement_remains_unread](../../../test/test_att/test_conversations/test_read_delivery.py) |

## Message changes

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A09-01 | Titles, Unicode, untitled messages, and code fences obey Markdown limits. | [test_title_limits_unicode_untitled_and_fenced_headings](../../../test/test_att/test_conversations/test_changes_and_notifications.py) |
| A09-02 | A successful edit renews the withdrawal deadline and failed edits do not. | [test_successful_edit_renews_window_but_failed_edit_does_not](../../../test/test_att/test_conversations/test_changes_and_notifications.py) |
| A09-03 | Withdrawal retains separate read and preview history. | [test_withdrawal_preserves_read_receipts_and_only_personal_reminder_preview](../../../test/test_att/test_conversations/test_changes_and_notifications.py); [test_later_withdrawal_preserves_frozen_views_read_evidence_and_previews](../../../test/test_att/test_state_integrity/test_withdrawal_projection_boundaries.py) |
| A09-04 | Withdrawn sources cannot be reopened through projection changes. | [test_confirmed_withdrawal_cannot_be_removed_or_replaced_in_either_mode](../../../test/test_att/test_state_integrity/test_withdrawal_projection_boundaries.py); [test_sql_writer_independently_rejects_reopening_a_withdrawn_message](../../../test/test_att/test_state_integrity/test_withdrawal_projection_boundaries.py) |
| A09-05 | Personal deletion survives editing and restoration is explicit. | [test_personal_delete_survives_edit_and_can_be_explicitly_restored](../../../test/test_att/test_conversations/test_history_and_reads.py) |

## Withdrawal window evidence

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A10-01 | A 1200-second configured window is legal and retains applied historical evidence. | [test_window_can_exceed_ten_minutes_and_history_uses_its_applied_value](../../../test/test_att/test_conversations/test_changes_and_notifications.py) |
| A10-02 | Nonpositive or nonfinite withdrawal configuration is rejected on construction and assignment. | [test_window_can_exceed_ten_minutes_and_history_uses_its_applied_value](../../../test/test_att/test_conversations/test_changes_and_notifications.py) |
| A10-03 | Source and withdrawal projection must commit together. | [test_withdrawal_and_source_projection_must_commit_together](../../../test/test_att/test_state_integrity/test_withdrawal_projection_boundaries.py) |

## Direct admission

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A11-01 | Concurrent edits and sends consume one shared directional allowance. | [test_concurrent_sends_and_edits_share_the_same_directional_allowance](../../../test/test_att/test_conversations/test_relationship_interleavings.py) |
| A11-02 | Historical-generation and friendship-era edits charge the current period. | [test_old_generation_and_friendship_era_edits_charge_the_current_period](../../../test/test_att/test_conversations/test_relationship_interleavings.py) |
| A11-03 | Failed edits preserve quota, reminders, and the prior withdrawal deadline. | [test_failed_edit_preserves_allowance_reminders_and_withdrawal_deadline](../../../test/test_att/test_conversations/test_relationship_interleavings.py) |
| A11-04 | Directional allowance and idempotent sends are atomic. | [test_direct_send_is_atomic_idempotent_and_directionally_limited](../../../test/test_att/test_conversations/test_publication.py) |
| A11-05 | Edits share the current allowance and honor blocks. | [test_direct_edit_cannot_bypass_stranger_allowance_or_block](../../../test/test_att/test_conversations/test_changes_and_notifications.py) |
| A11-06 | Failed persistence does not charge quota or create delivery. | [test_failed_write_does_not_consume_allowance_or_publish_an_arrival](../../../test/test_att/test_conversations/test_relationships.py) |
| A11-07 | Mixed generation, edit, replay, and restore histories follow current authority. | [test_seeded_relationship_periods_edits_and_receipt_replays](../../../test/test_att/test_conversations/test_relationship_interleavings.py) |

## Friendship and blocks

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A12-01 | Either endpoint blocks both delivery directions; only final unblock resets the period. | [test_blocks_are_independently_owned_and_only_final_clear_starts_a_new_period](../../../test/test_att/test_conversations/test_relationships.py) |
| A12-02 | Removing absent friendship or cancelling/crossing requests grants no allowance reset. | [test_crossed_requests_are_not_consent_and_cancellation_does_not_reset_allowance](../../../test/test_att/test_conversations/test_relationships.py) |
| A12-03 | Accepting during a block race cannot resurrect friendship. | [test_acceptance_racing_block_cannot_restore_friendship_through_block](../../../test/test_att/test_conversations/test_relationships.py) |

## Relationship history and current authorization

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A13-01 | Accepted old-generation requests survive removal and restore as history. | [test_historical_acceptance_survives_removal_and_restore_without_restoring_authority](../../../test/test_att/test_conversations/test_relationships.py) |
| A13-02 | Recipient refusal remains owned and requires explicit lifting. | [test_refusal_is_recipient_owned_and_requires_explicit_lifting](../../../test/test_att/test_conversations/test_relationships.py) |
| A13-03 | Generated relationship histories preserve ownership and current authorization. | [test_seeded_relationship_histories_survive_repeated_restore](../../../test/reliability/stress_relationships.py) |

## Tool contracts

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A14-01 | Unknown and foreground-only tools cannot be dispatched in background. | [test_invalid_unknown_and_foreground_only_tools_never_dispatch](../../../test/test_att/test_background_tasks/test_admission_and_results.py) |
| A14-02 | Auditor denial creates no actual execution attempt. | [test_auditor_denial_is_not_an_execution_attempt](../../../test/test_att/test_background_tasks/test_admission_and_results.py) |
| A14-03 | Strict nested validation precedes execution and auditing. | [test_strict_schema_validation_prevents_execution](../../../test/test_att/test_tool_execution_hardening/test_action_parsing_and_schema.py); [test_argument_validation_runs_before_tool_auditor](../../../test/test_att/test_tool_execution_hardening/test_tool_runtime.py) |
| A14-04 | Self-mutation and actor/policy overrides cannot create background authority. | [test_background_is_explicit_and_self_mutation_is_rejected](../../../test/test_att/test_runtime_contracts/test_contracts.py); [test_tool_schema_does_not_allow_actor_or_operation_key_overrides](../../../test/test_att/test_conversations/test_personal_runtime.py) |

## Resource conflicts

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A15-01 | Conflicting resources serialize while independent ones progress. | [test_conflicting_calls_serialize_while_independent_resources_progress](../../../test/test_att/test_background_tasks/test_resources_and_privacy.py) |
| A15-02 | Foreground and background share reservations across owners. | [test_undeclared_foreground_waits_for_another_owners_global_writer](../../../test/test_att/test_background_tasks/test_foreground_coordination.py); [test_mixed_effect_reservation_blocks_new_background_dispatch](../../../test/test_att/test_background_tasks/test_foreground_contracts.py) |
| A15-03 | Managed-link target changes cannot redirect an accepted write. | [test_retarget_between_resolution_and_physical_write_is_rejected](../../../test/test_att/test_background_tasks/test_binding_boundaries.py); [test_actual_target_must_be_claimed_even_if_alias_has_returned_to_original](../../../test/test_att/test_background_tasks/test_binding_boundaries.py) |
| A15-04 | Concurrent unrelated physical file writes can stage independently. | [test_same_library_unrelated_physical_writes_can_stage_concurrently](../../../test/test_att/test_background_tasks/test_resources_and_privacy.py) |

## Tool availability and retries

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A16-01 | Correctable input and ordinary business/permission errors remain observations. | [test_native_and_text_failures_remain_observations_not_idle_or_team_failure](../../../test/test_att/test_agent_activity/test_notifications_and_tools.py); [test_invalid_sleep_is_correctable_without_cooling_the_control](../../../test/test_att/test_agent_activity/test_notifications_and_tools.py) |
| A16-02 | Execution faults cool new same-tool calls without extending the deadline. | [test_execution_fault_cools_only_new_calls_to_the_same_tool](../../../test/test_att/test_agent_activity/test_notifications_and_tools.py) |
| A16-03 | Only typed eligible execution retries replay a tool. | [test_typed_transient_retry_policies](../../../test/test_att/test_tool_execution_hardening/test_tool_runtime.py); [test_each_real_execution_retry_has_evidence_but_an_auditor_denial_has_none](../../../test/test_att/test_agent_activity/test_runtime_boundaries.py) |
| A16-04 | Provider retry waits remain separate from tool cooldowns. | [test_provider_wait_overrides_jitter_cap_and_refreshes_arrivals_on_retry](../../../test/test_att/test_agent_activity/test_model_requests.py) |

## Model retry boundaries

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A17-01 | Full Jitter caps, per-alias timeouts, and exact framework attempt counts are enforced. | [test_full_jitter_bounds_per_model_deadline_and_exact_framework_attempts](../../../test/test_att/test_agent_activity/test_model_requests.py) |
| A17-02 | Transient exhaustion waits for its configured recovery boundary. | [test_transient_exhaustion_obeys_the_configured_recovery_admission_delay](../../../test/test_att/test_agent_activity/test_model_requests.py) |
| A17-03 | System instructions, schemas, and output budgets share atomic reservation. | [test_explicit_input_and_schema_are_reserved_and_usage_settles_once](../../../test/test_att/test_agent_activity/test_model_requests.py); [test_concurrent_people_cannot_reserve_the_same_remaining_allowance](../../../test/test_att/test_critical_hardening/test_discussion_and_token_budget.py) |
| A17-04 | Provider wait instructions cannot exceed the remaining whole-sequence budget. | [test_provider_wait_beyond_sequence_budget_defers_without_early_dispatch](../../../test/test_att/test_agent_activity/test_model_requests.py); [test_provider_capacity_wait_is_inside_the_whole_sequence_budget](../../../test/test_att/test_agent_activity/test_runtime_boundaries.py) |
| A17-05 | Permanent faults require remediation without periodic recovery. | [test_permanent_provider_error_has_no_periodic_recovery](../../../test/test_att/test_agent_activity/test_model_requests.py); [test_host_remediation_does_not_reset_usage_or_the_person](../../../test/test_att/test_agent_activity/test_runtime_boundaries.py) |
| A17-06 | Late responses and unacknowledged local calls remain fenced. | [test_provider_completion_after_deadline_is_fenced_even_if_timer_started_late](../../../test/test_att/test_agent_activity/test_runtime_boundaries.py); [test_synchronous_provider_timeout_retains_the_live_local_owner](../../../test/test_att/test_agent_activity/test_runtime_boundaries.py) |
| A17-07 | Uncooperative providers cannot indefinitely block manager close. | [test_close_does_not_wait_for_an_uncooperative_provider](../../../test/test_att/test_agent_activity/test_model_requests.py) |

## Cooldown recovery

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A18-01 | Downtime-excluded cooldown restores a remainder independently of sleep. | [test_excluded_cooldown_restores_its_remainder_not_elapsed_offline_time](../../../test/test_att/test_agent_activity/test_profiles_and_countdowns.py) |
| A18-02 | Rejected or cancelled cooldown receipts retain correct live boundaries. | [test_rejected_cooldown_receipt_does_not_publish_a_monotonic_deadline](../../../test/test_att/test_agent_activity/test_cooldown_transactions.py); [test_cancelled_observer_publishes_a_successfully_committed_deadline](../../../test/test_att/test_agent_activity/test_cooldown_transactions.py) |
| A18-03 | Parallel faults serialize cooldown record versions. | [test_parallel_same_tool_faults_serialize_their_record_versions](../../../test/test_att/test_agent_activity/test_cooldown_transactions.py) |

## Detachment

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A19-01 | Threshold observation detaches the same single execution. | [test_threshold_releases_only_the_wait_and_produces_one_native_observation](../../../test/test_att/test_runtime_contracts/test_background_execution_contracts.py); [test_text_detachment_continues_without_a_second_execution](../../../test/test_att/test_background_tasks/test_detachment.py) |
| A19-02 | Fast siblings and one handle close one complete native batch. | [test_fast_native_sibling_and_one_handle_close_a_complete_batch](../../../test/test_att/test_background_tasks/test_detachment.py) |
| A19-03 | Fast results remain foreground without a second result notice. | [test_fast_result_stays_foreground_without_a_task_notice](../../../test/test_att/test_background_tasks/test_detachment.py) |

## Artifact execution

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A20-01 | Archived private libraries reject ordinary mutation while retained identities can reactivate. | [test_archive_retain_reactivate_and_delete](../../../test/test_att/test_private_doclib/test_agent_lifecycle.py) |
| A20-02 | Private-library ownership and publication remain explicit. | [test_registration_private_boundary_and_shared_identity](../../../test/test_att/test_private_doclib/test_access_and_publishing.py); [test_publish_collision_move_and_private_events_hide_content](../../../test/test_att/test_private_doclib/test_access_and_publishing.py) |
| A20-03 | Native symlinks and managed-link cycles cannot escape the managed boundary. | [test_native_symlink_cannot_escape_doclib](../../../test/test_att/test_critical_hardening/test_doclib_security.py); [test_managed_doclib_link_cycle_is_rejected](../../../test/test_att/test_critical_hardening/test_doclib_security.py) |
| A20-04 | Managed links recheck current target ACL. | [test_managed_doclib_link_enforces_live_target_acl](../../../test/test_att/test_critical_hardening/test_doclib_security.py) |
| A20-05 | Already entered atomic writes settle; revoked late writes fail closed. | [test_already_entered_atomic_file_operation_settles_after_cancellation](../../../test/test_att/test_agent_activity/test_execution_authority.py); [test_cancelled_synchronous_tool_cannot_start_a_late_write](../../../test/test_att/test_agent_activity/test_execution_authority.py) |

## Cancellation

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A21-01 | Queued cancellation prevents dispatch. | [test_queued_cancel_prevents_dispatch](../../../test/test_att/test_background_tasks/test_cancellation_and_health.py) |
| A21-02 | Running cooperative cancellation has factual acknowledgement. | [test_cooperative_running_cancel_has_an_acknowledgement](../../../test/test_att/test_background_tasks/test_cancellation_and_health.py) |
| A21-03 | Threads retain reservations until actual return and known completion wins. | [test_cancelled_thread_keeps_its_resource_reservation_until_actual_return](../../../test/test_att/test_background_tasks/test_cancellation_and_health.py); [test_uncooperative_async_completion_remains_a_confirmed_completion](../../../test/test_att/test_background_tasks/test_cancellation_and_health.py) |
| A21-04 | Provider suspension requires acknowledgement and otherwise uses supported termination. | [test_supported_suspension_is_acknowledged_without_a_fabricated_terminal_state](../../../test/test_att/test_background_tasks/test_owner_lifecycle.py); [test_unacknowledged_suspension_falls_back_to_supported_termination](../../../test/test_att/test_background_tasks/test_owner_lifecycle.py) |
| A21-05 | Accepted local outcomes settle beyond the external grace period. | [test_close_waits_for_local_outcomes_without_using_the_external_grace_limit](../../../test/test_att/test_background_tasks/test_control_settlement.py); [test_returned_foreground_outcome_settles_while_close_waits_for_runtime_gate](../../../test/test_att/test_institutional_runtime/test_shutdown_settlement.py) |

## Task dimensions

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A22-01 | Execution, health, attention, and uncertainty are independent values. | [test_execution_health_attention_and_uncertainty_are_independent](../../../test/test_att/test_runtime_contracts/test_contracts.py) |
| A22-02 | Unsupported heartbeat never becomes an inferred stall. | [test_unsupported_heartbeat_is_not_an_inferred_stall](../../../test/test_att/test_background_tasks/test_cancellation_and_health.py) |
| A22-03 | Repeated health evidence coalesces only within a consecutive state. | [test_return_to_a_previous_health_state_is_a_new_observation](../../../test/test_att/test_background_tasks/test_health_transitions.py); [test_consecutive_identical_nonhealthy_reports_coalesce_only_until_a_transition](../../../test/test_att/test_background_tasks/test_health_transitions.py) |

## Retained task-result access

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A23-01 | Default lawful retained results remain owner-readable after revocation. | [test_default_retention_and_restrictive_mode_do_not_grant_new_source_access](../../../test/test_att/test_background_tasks/test_resources_and_privacy.py) |
| A23-02 | Restrictive policy cannot borrow a later membership or unverifiable source. | [test_restrictive_mode_cannot_borrow_new_membership_or_permissions](../../../test/test_att/test_background_tasks/test_resources_and_privacy.py); [test_restrictive_mode_rejects_unverifiable_external_source_provenance](../../../test/test_att/test_background_tasks/test_resources_and_privacy.py) |
| A23-03 | Revocation before acceptance cannot create a lawful retained body. | [test_revocation_before_result_acceptance_does_not_create_a_retained_copy](../../../test/test_att/test_background_tasks/test_commit_boundaries.py); [test_failure_body_is_not_an_authorization_bypass](../../../test/test_att/test_background_tasks/test_binding_boundaries.py) |
| A23-04 | Transient bodies do not reappear after restore or enter durable task payloads. | [test_transient_result_does_not_reappear_or_reread_after_restore](../../../test/test_att/test_background_tasks/test_persistence_and_recovery.py); [test_transient_private_read_never_persists_its_body_as_a_task_payload](../../../test/test_att/test_background_tasks/test_resources_and_privacy.py) |

## Governance

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A24-01 | Incomplete electorates, membership changes, and ties cannot become approvals. | [test_complete_electorate_required_and_session_released](../../../test/test_att/test_personal_governance/test_rounds_and_concurrency.py); [test_membership_changes_supersede_instead_of_reusing_votes](../../../test/test_att/test_personal_governance/test_rounds_and_concurrency.py); [test_tie_creates_new_round_without_deleting_history](../../../test/test_att/test_personal_governance/test_rounds_and_concurrency.py) |
| A24-02 | Reading addressed mail does not vote and actual choices are strict and immutable. | [test_unanswered_read_email_never_becomes_a_vote](../../../test/test_att/test_personal_governance/test_identity_and_mail.py); [test_strict_immutable_choice_and_cross_identity_rejection](../../../test/test_att/test_personal_governance/test_identity_and_mail.py) |
| A24-03 | Complete parent electorates and Root identity remain explicit. | [test_parent_team_requires_every_explicit_ballot_before_alias_application](../../../test/test_att/test_failover.py); [test_explicit_root_agent_votes_as_itself_not_as_a_team_replacement](../../../test/test_att/test_failover.py) |
| A24-04 | Unsupported communication wake is rejected on construction and assignment. | [test_communication_wake_is_rejected_at_construction_and_assignment](../../../test/test_att/test_institutional_runtime/test_routing.py) |
| A24-05 | Case and channel recovery retain exact ballot provenance. | [test_case_and_channel_restore_keep_exact_ballot_provenance](../../../test/test_att/test_institutional_runtime/test_communication.py) |

## Independence and approval

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A25-01 | Independent pairs communicate under every configured institution. | [test_independent_pair_is_permissive_under_every_policy](../../../test/test_att/test_institutional_runtime/test_routing.py) |
| A25-02 | Cross-tree lineage follows real tops without an invented Root. | [test_cross_tree_lineage_has_no_synthetic_root](../../../test/test_att/test_institutional_runtime/test_routing.py) |
| A25-03 | An independent parent still governs its attached child's requests. | [test_independent_parent_still_approves_for_attached_child](../../../test/test_att/test_institutional_runtime/test_routing.py) |
| A25-04 | Relevant independence transitions stale pending requests. | [test_relevant_detachment_stales_even_before_any_ballot](../../../test/test_att/test_institutional_runtime/test_communication.py) |
| A25-05 | Active agreement revocation remains endpoint-owned and directionally idempotent. | [test_one_way_delivery_idempotency_and_endpoint_revocation](../../../test/test_att/test_communication/test_agreements_and_delivery.py) |

## Formation

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A26-01 | Four attitudes and deliberate None are distinct from mail read flags. | [test_four_attitudes_are_visible_but_only_acceptance_joins](../../../test/test_att/test_team_formation/test_consent_and_lifecycle.py); [test_formation_four_attitudes_are_independent_of_email_read_state](../../../test/test_att/test_personal_governance/test_lifecycle_and_choices.py) |
| A26-02 | Material revisions require renewed exact consent and reject stale responses. | [test_material_revision_resets_exact_consent_and_rejects_stale_actions](../../../test/test_att/test_team_formation/test_revisions_and_deliberation.py) |
| A26-03 | Unanimity, final confirmation, and abandonment retain independent decisions. | [test_unanimous_auto_creation_and_confirmation_abandonment](../../../test/test_att/test_team_formation/test_consent_and_lifecycle.py) |
| A26-04 | Late joining is invitee-initiated and revalidates lifecycle. | [test_late_join_is_always_invitee_initiated](../../../test/test_att/test_team_formation/test_consent_and_lifecycle.py); [test_late_join_revalidates_agent_lifecycle_after_waiting_for_team_lock](../../../test/test_att/test_team_formation/test_consent_and_lifecycle.py) |
| A26-05 | Optional drafts remain supplied advisory candidates. | [test_collaborative_draft_is_detached_advisory_work_until_publication](../../../test/test_att/test_team_formation/test_revisions_and_deliberation.py); [test_preparing_candidate_never_invokes_a_hanging_provider](../../../test/test_att/test_team_formation/test_revisions_and_deliberation.py) |

## Migration and failover

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A27-01 | Actual ancestor and lineage principals govern migration. | [test_ancestor_approval_uses_agent_teams_and_root_agent](../../../test/test_att/test_policies.py); [test_lineage_path_uses_every_explicit_principal](../../../test/test_att/test_policies.py) |
| A27-02 | Migration cooldown and acceptance share successful commit time. | [test_parent_acceptance_event_cooldown_and_receipt_share_one_final_time](../../../test/test_att/test_institutional_runtime/test_migration_writer_time.py); [test_remaining_cooldown_counts_online_time_after_sql_commit_before_observation](../../../test/test_att/test_institutional_runtime/test_migration_writer_time.py) |
| A27-03 | Runtime host policy is revalidated after lock and writer waits. | [test_durable_detachment_rechecks_host_disable_after_runtime_gate_wait](../../../test/test_att/test_institutional_runtime/test_migration_acceptance.py); [test_final_authority_check_rejects_disable_after_record_production](../../../test/test_att/test_institutional_runtime/test_migration_acceptance.py) |
| A27-04 | Parent failover has its own expiry and rejects late choices without auto fallback. | [test_failover_timeout_closes_authority_but_retains_mail](../../../test/test_att/test_personal_governance/test_lifecycle_and_choices.py); [test_no_parent_and_self_parent_fail_closed_without_an_automatic_fallback](../../../test/test_att/test_failover.py) |

## Supervision

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A28-01 | Missing explicit findings create no health authority. | [test_ordinary_answers_and_missing_findings_supply_no_health_authority](../../../test/test_att/test_supervision.py) |
| A28-02 | Confirmed integrity faults apply protection before incident persistence. | [test_confirmed_integrity_fault_applies_protection_before_incident_commit](../../../test/test_att/test_supervision.py) |
| A28-03 | Audits create fresh real teams with common runtime and all findings. | [test_real_fresh_team_uses_common_runtime_and_all_findings](../../../test/test_att/test_institutional_runtime/test_health.py); [test_parallel_audits_have_separate_live_owners_and_provider_context](../../../test/test_att/test_supervision_lifecycle.py) |
| A28-04 | Protocol and tool evidence use separate explicit thresholds. | [test_protocol_streak_uses_one_person_and_different_protocol_codes](../../../test/test_att/test_institutional_runtime/test_health.py); [test_tool_streaks_are_per_tool_and_category](../../../test/test_att/test_institutional_runtime/test_health.py) |
| A28-05 | Unavailable audits preserve incidents without stopping ordinary people. | [test_unavailable_assessment_retains_incident_without_stopping_person](../../../test/test_att/test_institutional_runtime/test_health_admission_boundaries.py) |
| A28-06 | Audit deadline includes scheduler capacity and fences late findings. | [test_total_deadline_includes_waiting_for_common_scheduler_capacity](../../../test/test_att/test_institutional_runtime/test_health_admission_boundaries.py); [test_provider_response_after_total_deadline_cannot_submit_finding](../../../test/test_att/test_institutional_runtime/test_health_admission_boundaries.py) |
| A28-07 | Incident handling checks current actual parent authority. | [test_acknowledgement_rechecks_parent_authority_before_durable_acceptance](../../../test/test_att/test_institutional_runtime/test_incident_authority_publication.py); [test_claim_rechecks_parent_authority_before_volatile_acceptance](../../../test/test_att/test_institutional_runtime/test_incident_authority_publication.py) |

## Sleep

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A29-01 | Countdown units and total bounds are strict and Host-owned. | [test_duration_units_are_strict_and_total_bounds_are_host_owned](../../../test/test_att/test_runtime_contracts/test_contracts.py); [test_duration_wire_schemas_match_positive_omittable_units](../../../test/test_att/test_runtime_contracts/test_contracts.py) |
| A29-02 | Sleep retains a mandatory finite deadline while mail is delivered. | [test_sleep_has_a_live_finite_safeguard_and_mail_does_not_cancel_it](../../../test/test_att/test_agent_activity/test_admission_and_controls.py) |
| A29-03 | Protected arrivals cross the sleep boundary without loss. | [test_protected_arrival_during_the_sleep_response_is_not_lost_at_the_boundary](../../../test/test_att/test_agent_activity/test_sleep_scope.py); [test_ordinary_mail_cannot_spoof_a_protected_wake](../../../test/test_att/test_agent_activity/test_notifications_and_tools.py) |
| A29-04 | Provider unavailability cannot extend voluntary sleep. | [test_provider_unavailability_does_not_extend_voluntary_sleep](../../../test/test_att/test_agent_activity/test_sleep_scope.py) |

## Do-not-disturb

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A30-01 | Permanent and timed preferences share owner and duration rules. | [test_sleep_and_suppression_share_bounds_without_forcing_permanent_expiry](../../../test/test_att/test_runtime_contracts/test_contracts.py); [test_preferences_cannot_select_another_owner_or_bypass_protected_notices](../../../test/test_att/test_agent_activity/test_notification_suppression.py) |
| A30-02 | Expiry retains one source-count summary with unchanged read state. | [test_timed_expiration_emits_one_count_summary_without_reading_mail](../../../test/test_att/test_agent_activity/test_notification_suppression.py) |
| A30-03 | Summaries never include private bodies, titles, or replay old notices. | [test_removal_frame_contains_counts_but_no_titles_bodies_or_reminder_replay](../../../test/test_att/test_agent_activity/test_notification_suppression_privacy.py) |
| A30-04 | Overlapping preferences and frozen archives remain independently filtered. | [test_new_overlapping_preference_does_not_strand_an_earlier_summary](../../../test/test_att/test_agent_activity/test_notification_suppression_privacy.py); [test_departure_after_summary_creation_removes_its_archived_source_counts](../../../test/test_att/test_agent_activity/test_notification_suppression_privacy.py) |

## Independent identity and death

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A31-01 | Host-confirmed death is terminal and retains private artifacts. | [test_death_is_explicit_host_only_terminal_and_preserves_private_artifacts](../../../test/test_att/test_agent_lifecycle/test_retained_death.py) |
| A31-02 | Death of members or creators preserves surviving teams and direct-child structure. | [test_member_and_creator_death_preserves_teams_and_detaches_only_direct_children](../../../test/test_att/test_agent_lifecycle/test_retained_death.py) |
| A31-03 | Live and queued observers terminate without a prior idle boundary. | [test_active_invocation_is_cancelled_without_an_idle_lock_requirement](../../../test/test_att/test_agent_lifecycle/test_retained_death.py); [test_queued_death_fails_all_checkpoint_and_interaction_waiters](../../../test/test_att/test_agent_lifecycle/test_activity_observers.py) |
| A31-04 | Known returned results settle before death closes their authority. | [test_returned_personal_result_survives_death_and_observer_cancellation](../../../test/test_att/test_background_tasks/test_lifecycle_outcome_boundaries.py); [test_source_revocation_still_denies_a_returned_result_during_death](../../../test/test_att/test_background_tasks/test_lifecycle_outcome_boundaries.py) |
| A31-05 | Dead identities restore without a model binding or automatic wake. | [test_dead_identity_round_trip_requires_no_model_binding_and_never_wakes](../../../test/test_att/test_agent_lifecycle/test_retained_death.py) |

## Independent teams and live discovery

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A32-01 | Parents are explicit and personal membership never infers ancestry. | [test_personal_scope_and_memberships_cannot_reinfer_an_existing_parent](../../../test/test_att/test_agent_activity/test_admission_and_controls.py); [test_explicit_agent_parent_without_root_substitution](../../../test/test_att/test_institutional_runtime/test_topology.py) |
| A32-02 | Dissolution and parent retirement detach surviving direct children only. | [test_parent_team_dissolution_detaches_direct_children_only](../../../test/test_att/test_institutional_runtime/test_topology.py); [test_retiring_actual_agent_parent_preserves_creator_and_children](../../../test/test_att/test_institutional_runtime/test_topology.py) |
| A32-03 | Archived teams retain provenance without reentering live topology. | [test_archived_child_retains_provenance_when_its_parent_is_later_archived](../../../test/test_att/test_conversations/test_topology_lifecycle.py); [test_inactive_deleted_and_audit_entities_are_excluded_from_every_operation](../../../test/test_att/test_discovery/test_scope_and_privacy.py) |
| A32-04 | Discovery uses restored registries without a persistent directory index. | [test_round_trip_uses_restored_registries_without_a_persisted_discovery_index](../../../test/test_att/test_discovery/test_authority_and_restore.py) |

## Voluntary topology changes

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A33-01 | Target acceptance and own-position cooldown are required for attachment. | [test_target_acceptance_and_own_cooldown](../../../test/test_att/test_institutional_runtime/test_topology.py) |
| A33-02 | Agent tool detachment does not await an old parent. | [test_migration_tool_can_choose_null_without_waiting_for_an_old_parent](../../../test/test_att/test_institutional_runtime/test_tool_entry_points.py) |
| A33-03 | Live Host disablement and exact final authority can reject a waiting transition. | [test_detachment_rechecks_host_disable_after_record_lock_wait](../../../test/test_att/test_institutional_runtime/test_migration_acceptance.py); [test_final_authority_check_rejects_disable_after_record_production](../../../test/test_att/test_institutional_runtime/test_migration_acceptance.py) |
| A33-04 | Parent provenance survives migration and restoration. | [test_migration_after_restore_updates_the_parent_resolver](../../../test/test_att/test_state_persistence/test_topology_index.py); [test_provenance_dependencies_keep_distinct_parent_and_creator_after_migration](../../../test/test_att/test_episodic_memory/test_persistence_and_privacy/test_incremental_dependencies.py) |

## Countdown recovery

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A34-01 | Offline time is excluded and restoration-start anchors survive slow publication. | [test_sleep_export_samples_remainder_and_restore_does_not_spend_offline_time](../../../test/test_att/test_agent_activity/test_checkpoints_and_recovery.py); [test_sleep_expired_during_slow_restore_settles_only_after_publication](../../../test/test_att/test_state_persistence/test_recovery_wake_boundaries.py) |
| A34-02 | Failed recovery preserves original timer deadlines. | [test_rejected_recovery_releases_the_original_expired_sleep](../../../test/test_att/test_state_persistence/test_countdown_handoffs.py); [test_rejected_recovery_releases_the_original_expired_suppression](../../../test/test_att/test_state_persistence/test_countdown_handoffs.py) |
| A34-03 | Timer handoffs exclude restore until accepted local settlement. | [test_sleep_expiry_owns_its_generation_while_the_activity_lock_is_queued](../../../test/test_att/test_state_persistence/test_countdown_handoffs.py); [test_checkpoint_sampling_handoff_also_excludes_restore](../../../test/test_att/test_state_persistence/test_countdown_handoffs.py) |
| A34-04 | A successful publication hands off exactly one new timer. | [test_successful_publication_uses_one_new_timer_and_discards_the_old_one](../../../test/test_att/test_state_persistence/test_countdown_handoffs.py) |

## Incremental persistence

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A35-01 | Committed dependency closures survive first partial export. | [test_first_partial_export_includes_observation_execution_dependencies](../../../test/test_att/test_background_tasks/test_foreground_evidence.py); [test_segment_only_delta_includes_sources_owner_and_indexed_card](../../../test/test_att/test_episodic_memory/test_persistence_and_privacy/test_incremental_dependencies.py) |
| A35-02 | Unrelated identity and team rows remain unchanged for chat-only deltas. | [test_chat_only_delta_preserves_unrelated_identity_and_team_rows](../../../test/test_att/test_conversations/test_commit_and_restore.py) |
| A35-03 | Cancelled observers retain accepted writes and exact receipts. | [test_cancellation_does_not_drop_an_accepted_write_or_team_lock](../../../test/test_att/test_high_hardening/test_persistence_queue.py); [test_cancelled_delivery_settles_and_replays_the_exact_durable_receipt](../../../test/test_att/test_conversations/test_commit_and_restore.py) |
| A35-04 | Incremental validation agrees with strict reference validation. | [test_deleted_prerequisite_invalidates_unchanged_dependants](../../../test/test_att/test_incremental_validation/test_detached_equivalence.py); [test_changed_request_invalidates_unchanged_presented_claim](../../../test/test_att/test_incremental_validation/test_detached_equivalence.py) |

## Schema and ownership

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A36-01 | Old, future, and malformed schema versions cause no DDL or workspace mutation. | [test_old_future_and_malformed_versions_leave_database_and_workspace_unchanged](../../../test/test_att/test_state_persistence/test_unsupported_schema.py) |
| A36-02 | Competing processes and abrupt restart enforce exclusive writer ownership. | [test_writer_ownership_and_abrupt_restart_recovery](../../../test/test_att/test_high_hardening/test_database_integrity.py) |
| A36-03 | SQLite pragmas and coalesced pending deltas preserve strict writer semantics. | [test_sqlite_pragmas_and_coalesced_pending_delta](../../../test/test_att/test_high_hardening/test_persistence_queue.py) |

## Durability modes

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A37-01 | Durable selection and missing paths are explicit rather than silently volatile. | [test_durable_is_default_and_volatile_is_explicit](../../../test/test_att/test_state_integrity/test_records_and_receipts.py) |
| A37-02 | Host chat and exports preserve equivalent identities in durable and volatile modes. | [test_sources_views_changes_and_export_keep_the_same_person_in_both_modes](../../../test/test_att/test_conversations/test_durability_parity.py) |
| A37-03 | Receipts survive lost responses and retain accepted identities. | [test_lost_response_retry_after_restore_returns_the_original_receipt](../../../test/test_att/test_state_integrity/test_commit_boundaries.py) |
| A37-04 | Complete consumer examples avoid project-root DocLib and verify restored identity. | [test_personal_cli_runs_from_outside_the_repository](../../../test/test_att/test_documentation_contracts/test_examples.py); [test_text_cli_runs_from_outside_the_repository](../../../test/test_att/test_documentation_contracts/test_examples.py); [test_background_cli_runs_from_outside_the_repository](../../../test/test_att/test_documentation_contracts/test_examples.py) |

## Restore corruption

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A38-01 | Chat and command-reference corruption cannot change live runtime or files. | [test_corrupt_chat_reference_matrix_does_not_publish_runtime_or_files](../../../test/test_att/test_conversations/test_commit_and_restore.py); [test_corrupt_command_receipts_reject_restore_without_changing_runtime_or_files](../../../test/test_att/test_conversations/test_operation_receipts.py) |
| A38-02 | Execution and private-owner reference corruption fails atomically. | [test_corrupt_execution_matrix_preserves_original_manager_and_files](../../../test/test_att/test_background_tasks/test_persistence_and_recovery.py); [test_current_schema_round_trip_and_corruption_is_atomic](../../../test/test_att/test_private_doclib/test_persistence_and_corruption.py) |
| A38-03 | Sleep, suppression, and dead ownership corruption fail before publication. | [test_timed_suppression_corruption_matrix_preserves_the_live_manager](../../../test/test_att/test_state_persistence/test_activity_lifecycle_validation.py); [test_dead_member_or_active_private_library_cannot_restore_as_valid_state](../../../test/test_att/test_state_persistence/test_activity_lifecycle_validation.py) |
| A38-04 | Memory lifecycle and complete personal context are validated independently. | [test_restore_validation_rejects_invalid_memory_lifecycle_edges](../../../test/test_att/test_episodic_memory/test_persistence_and_privacy/test_snapshots_and_restore.py); [test_invalid_context_matrix_is_rejected_before_any_publication](../../../test/test_att/test_agent_activity/test_restore_context_validation.py) |

## Crash boundaries

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A39-01 | Real exits surround dispatch, returned outcome, and SQLite result commit. | [test_process_exit_before_and_after_dispatch_and_result_commit_never_replays](../../../test/test_att/test_background_tasks/test_crash_boundaries.py) |
| A39-02 | A process exit between directory swaps restores every original library. | [test_process_exit_between_library_swaps_rolls_back_every_original_directory](../../../test/test_att/test_state_persistence/test_publication_crash_boundaries.py) |
| A39-03 | An exit after recovery receipt but before activation retains one addressed notice. | [test_exit_after_recovery_receipt_before_activation_keeps_one_notice_and_no_replay](../../../test/test_att/test_state_persistence/test_publication_crash_boundaries.py) |
| A39-04 | Rollback intent restores prior request and quota rows after an actual crash. | [test_crash_after_rollback_intent_restores_existing_request_and_claim_rows](../../../test/test_att/test_state_persistence/test_recovery_publication_crash.py) |

## Recovery policy

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A40-01 | Unfinished Host execution wakes its same owner without replay or reconnect. | [test_unfinished_host_execution_wakes_a_never_activated_owner_once_without_replay](../../../test/test_att/test_state_persistence/test_activity_recovery.py) |
| A40-02 | Unaffected sleep and source read state survive restoration. | [test_timed_suppression_and_sleep_exclude_offline_time_and_keep_source_unread](../../../test/test_att/test_state_persistence/test_activity_recovery.py) |
| A40-03 | Known terminal results restore attention and provenance without redispatch. | [test_result_attention_config_and_provenance_round_trip](../../../test/test_att/test_background_tasks/test_persistence_and_recovery.py) |
| A40-04 | Repeated restore deduplicates uncertain execution notices. | [test_process_exit_before_and_after_dispatch_and_result_commit_never_replays](../../../test/test_att/test_background_tasks/test_crash_boundaries.py); [test_exit_after_recovery_receipt_before_activation_keeps_one_notice_and_no_replay](../../../test/test_att/test_state_persistence/test_publication_crash_boundaries.py) |

## Runtime replacement

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A41-01 | Old synchronous writes and returned delegated authority cannot cross a revoked generation. | [test_cancelled_synchronous_tool_cannot_start_a_late_write](../../../test/test_att/test_agent_activity/test_execution_authority.py); [test_returned_tool_cannot_implicitly_delegate_its_authority](../../../test/test_att/test_agent_activity/test_execution_authority.py) |
| A41-02 | Live executor ownership excludes restore. | [test_restore_rejects_a_live_executor_even_without_personal_activity](../../../test/test_att/test_background_tasks/test_resources_and_privacy.py) |
| A41-03 | Failed runtime publication restores exact previous quota and request facts. | [test_runtime_switch_failure_restores_existing_request_and_quota_rows_exactly](../../../test/test_att/test_state_persistence/test_activity_recovery.py) |
| A41-04 | Indexing close and restore suspension cannot leave cancelled queue workers. | [test_close_cannot_leave_a_cancelled_indexer_waiting_for_another_item](../../../test/test_att/test_episodic_memory/test_indexing_lifecycle.py); [test_restore_suspension_finishes_when_an_index_result_wins_cancellation](../../../test/test_att/test_episodic_memory/test_indexing_lifecycle.py); [test_close_releases_a_flush_observer_without_discarding_pending_segments](../../../test/test_att/test_episodic_memory/test_indexing_lifecycle.py) |

## Privacy

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A42-01 | Counts, discovery, callbacks, and operation events contain no chat bodies. | [test_callbacks_and_discovery_never_contain_chat_payloads](../../../test/test_att/test_conversations/test_changes_and_notifications.py); [test_disabled_details_and_page_counts_do_not_parse_unreturned_bodies](../../../test/test_att/test_conversations/test_changes_and_notifications.py) |
| A42-02 | Private observations remain transient across checkpoints and model protocols. | [test_private_read_is_transient_even_at_a_mid_activity_checkpoint](../../../test/test_att/test_agent_activity/test_notifications_and_tools.py); [test_react_private_payload_is_not_durable_or_callback_visible](../../../test/test_att/test_private_doclib/test_reasoning_privacy.py); [test_native_private_result_cannot_enter_persisted_memory](../../../test/test_att/test_episodic_memory/test_persistence_and_privacy/test_tool_privacy.py) |
| A42-03 | Voting and audits cannot automatically ingest personal private artifacts. | Voting: [test_private_files_are_not_injected_into_voting_context](../../../test/test_att/test_personal_governance/test_identity_and_mail.py); audit provider inputs: [test_real_fresh_team_uses_common_runtime_and_all_findings](../../../test/test_att/test_institutional_runtime/test_health.py). |
| A42-04 | Result bodies cannot be read by another execution owner. | [test_other_owner_cannot_inspect_search_read_or_cancel](../../../test/test_att/test_background_tasks/test_admission_and_results.py) |

## Optional memory

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A43-01 | Disabled mode needs no indexing and can persist Journal without cards. | [test_disabled_by_default_and_runtime_tool_view_tracks_configuration](../../../test/test_att/test_episodic_memory/test_catalog_and_recall/test_optional_mode.py); [test_disabled_mode_persists_journal_without_cards_or_fts](../../../test/test_att/test_episodic_memory/test_catalog_and_recall/test_optional_mode.py) |
| A43-02 | Indexing owns invocation provenance and cannot capture another person or business scope. | [test_one_finished_invocation_creates_one_isolated_card](../../../test/test_att/test_episodic_memory/test_catalog_and_recall/test_indexing.py); [test_background_indexer_does_not_inherit_business_invocation_context](../../../test/test_att/test_episodic_memory/test_catalog_and_recall/test_indexing.py); [test_another_agent_registered_during_activity_cannot_enter_its_segment](../../../test/test_att/test_episodic_memory/test_catalog_and_recall/test_indexing.py) |
| A43-03 | Ephemeral recall clears and membership leaves the catalog intact. | [test_search_is_owner_scoped_and_recall_expires](../../../test/test_att/test_episodic_memory/test_catalog_and_recall/test_recall.py); [test_membership_changes_do_not_touch_agent_memory](../../../test/test_att/test_episodic_memory/test_persistence_and_privacy/test_identity_lifecycle.py) |
| A43-04 | Disabling with a backlog releases flush and reenable preserves pending indexing. | [test_disabling_indexing_drains_a_backlog_and_reenable_preserves_pending_work](../../../test/test_att/test_episodic_memory/test_indexing_lifecycle.py) |

## Stress and cleanup

| ID | Requirement | Behavioral evidence |
| --- | --- | --- |
| A44-01 | Ordered callbacks tolerate blocking and failures without blocking the event loop. | [test_callbacks_are_ordered_nonblocking_and_isolated](../../../test/test_att/test_high_hardening/test_shared_agent_and_lifecycle.py) |
| A44-02 | Many-source admissions retain one person and fair independent progress. | [test_many_sources_coalesce_without_cloning_people_or_starving_other_owners](../../../test/reliability/stress_admission.py) |
| A44-03 | Continuous slow-writer producers retain all keys with two completion handles. | [test_continuous_producers_coalesce_without_losing_keys_or_blocking_the_loop](../../../test/reliability/stress_writer.py) |
| A44-04 | Seeded relationship periods preserve current authority across repeated restores. | [test_seeded_relationship_histories_survive_repeated_restore](../../../test/reliability/stress_relationships.py) |
| A44-05 | Loop responsiveness continues while detached validation is blocked. | [test_slow_preparation_does_not_block_heartbeat_or_publish_baseline](../../../test/test_att/test_incremental_validation/test_volatile_lifecycle.py) |

