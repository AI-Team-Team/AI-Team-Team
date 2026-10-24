"""Reviewed execution declarations; institutional operations remain foreground-only."""

from ai_team_team.core.activity.contracts import ToolExecutionContract


READ_ONLY = {
    "inspect_entity", "inspect_migration_request", "inspect_team_formation",
    "inspect_team_formation_draft", "list_agent_inbox", "list_entities", "list_governance_requests",
    "list_library_files", "list_peer_agreements", "list_peer_requests", "list_private_files",
    "list_public_libraries", "open_agent_mail", "read_library_file", "read_private_file",
    "search_entities", "search_memories", "list_peer_messages", "read_peer_message",
    "list_health_incidents", "inspect_health_incident",
}
ARTIFACTS = {
    "create_library_link", "delete_library_file", "delete_private_file", "move_library_file",
    "move_private_file", "publish_private_file", "write_library_file", "write_private_file",
}
DOMAIN = {"create_doc_library", "update_library_metadata", "grant_library_permission", "revoke_library_permission"}
SELF = {"forget_memory", "keep_memory_in_context", "recall_memory"}
TEAM = ARTIFACTS - {"delete_private_file", "move_private_file", "write_private_file"}
TEAM |= DOMAIN | {"list_library_files", "read_library_file", "list_peer_agreements", "list_peer_requests"}
TEAM |= {"send_peer_message", "request_peer_communication", "revoke_peer_agreement", "list_peer_messages", "read_peer_message"}
TEAM |= {"request_migration", "dispatch_subagent", "delegate_escalation", "add_team_member", "remove_team_member",
    "initiate_membership_vote", "cast_vote", "retract_membership_vote", "update_team_status", "update_team_purpose"}
EITHER_HEALTH = {"list_health_incidents", "inspect_health_incident", "claim_health_incident", "acknowledge_health_incident"}
EITHER = {"inspect_entity", "list_entities", "search_entities", "list_public_libraries"}
EITHER |= EITHER_HEALTH
EITHER |= {"propose_team_formation", "prepare_team_formation_draft", "publish_team_formation_draft", "inspect_migration_request"}


def declare_builtin_effects(tools):
    for name, tool in tools.items():
        effect = ("read_only" if name in READ_ONLY else "artifact_write" if name in ARTIFACTS
                  else "self_modification" if name in SELF else "domain_mutation")
        # Institutional commands complete local receipts, not awaited business work.
        tool.execution_contract = ToolExecutionContract(
            effects=(effect,), background_allowed=name in READ_ONLY | ARTIFACTS | DOMAIN,
            required_scope="agent_team" if name in TEAM else "either" if name in EITHER else "personal",
            mutation_safety="managed_lease" if effect != "read_only" else "none",
            cancellation="none",
        )
        tool._builtin = True
        if name in {"read_private_file", "recall_memory"}:
            tool.result_storage = "transient"
    return tools
