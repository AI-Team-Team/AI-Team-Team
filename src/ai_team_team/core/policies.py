import re
import json
import logging
from typing import Any, Tuple, List

logger = logging.getLogger("ATT.Policies")

async def generate_with_retry_fallback(
    llm_client: Any,
    prompt: str,
    system_instruction: str,
    manager: Any
) -> str:
    from .utils import generate_with_retry
    retries = manager.config.llm_max_retries if manager else 3
    backoff = manager.config.llm_retry_backoff_factor if manager else 1.5
    return await generate_with_retry(
        llm_client=llm_client,
        prompt=prompt,
        system_instruction=system_instruction,
        temperature=0.2,
        require_json=True,
        retries=retries,
        backoff_factor=backoff
    )

def get_team_representative(team: Any, manager: Any) -> Any:
    if team is None:
        return manager.root_ai
    if team.members:
        return team.members[0]
    if getattr(team, "creator", None) and hasattr(team.creator, "llm_client"):
        return team.creator
    return manager.root_ai

def get_ancestry_chain(team: Any) -> List[Any]:
    chain = []
    curr = team
    while curr:
        chain.append(curr)
        curr = curr.parent_team
    return chain

def find_lca(t1: Any, t2: Any) -> Any:
    if not t1 or not t2:
        return None
    chain1 = get_ancestry_chain(t1)
    chain2 = get_ancestry_chain(t2)
    chain1.reverse()
    chain2.reverse()
    lca = None
    for n1, n2 in zip(chain1, chain2):
        if n1.team_id == n2.team_id:
            lca = n1
        else:
            break
    return lca

def get_path_to_ancestor(start: Any, ancestor: Any) -> List[Any]:
    path = []
    curr = start
    while curr and curr != ancestor:
        path.append(curr)
        curr = curr.parent_team
    if curr == ancestor and ancestor:
        path.append(ancestor)
    return path

def check_rules_single_direction(parent: Any, opponent_team: Any) -> bool:
    if not parent:
        return True
    rules = parent.communication_rules.get("rules", [])
    if not rules:
        return parent.communication_rules.get("allow_sibling_talk", False)
    
    for rule in rules:
        rule_str = rule.strip()
        if rule_str in {"allow_all", "allow_any"}:
            return True
        if rule_str.startswith("allow_team:"):
            target_id = rule_str.split("allow_team:", 1)[1].strip()
            if opponent_team.team_id == target_id:
                return True
        if rule_str.startswith("allow_parent:"):
            target_parent_id = rule_str.split("allow_parent:", 1)[1].strip()
            opp_parent = opponent_team.parent_team
            if opp_parent and opp_parent.team_id == target_parent_id:
                return True
        if rule_str.startswith("allow_purpose:"):
            pattern = rule_str.split("allow_purpose:", 1)[1].strip()
            try:
                if re.match(pattern, opponent_team.team_purpose or "", re.IGNORECASE):
                    return True
            except Exception as e:
                logger.error(f"Invalid regex pattern in communication rules: {pattern}. Error: {e}")
    return False

# Base Policies

class BaseCommunicationPolicy:
    async def authorize_peer_talk(
        self,
        sender: Any,
        recipient: Any,
        manager: Any,
        rationale: str
    ) -> bool:
        raise NotImplementedError

class BaseMigrationPolicy:
    async def authorize_migration(
        self,
        team: Any,
        target_parent: Any,
        manager: Any,
        rationale: str
    ) -> Tuple[bool, str]:
        raise NotImplementedError

# Communication Policy Implementations

class PermissiveCommunicationPolicy(BaseCommunicationPolicy):
    async def authorize_peer_talk(
        self,
        sender: Any,
        recipient: Any,
        manager: Any,
        rationale: str
    ) -> bool:
        return True

class RuleGatedCommunicationPolicy(BaseCommunicationPolicy):
    async def authorize_peer_talk(
        self,
        sender: Any,
        recipient: Any,
        manager: Any,
        rationale: str
    ) -> bool:
        sender_parent = sender.parent_team
        recipient_parent = recipient.parent_team
        
        ok_sender = check_rules_single_direction(sender_parent, recipient)
        ok_recipient = check_rules_single_direction(recipient_parent, sender)
        
        return ok_sender and ok_recipient

class ProxiedCommunicationPolicy(BaseCommunicationPolicy):
    async def authorize_peer_talk(
        self,
        sender: Any,
        recipient: Any,
        manager: Any,
        rationale: str
    ) -> bool:
        sender_parent = sender.parent_team
        recipient_parent = recipient.parent_team
        
        parents = []
        for p in [sender_parent, recipient_parent]:
            if p not in parents:
                parents.append(p)

        for p in parents:
            rep = get_team_representative(p, manager)
            if not rep or not getattr(rep, "llm_client", None):
                continue
            
            prompt = (
                f"Evaluate a request to establish a cross-lineage peer-to-peer communication channel.\n\n"
                f"Sender Team: {sender.team_id} (Purpose: {sender.team_purpose})\n"
                f"Recipient Team: {recipient.team_id} (Purpose: {recipient.team_purpose})\n"
                f"Rationale: \"{rationale}\"\n\n"
                f"Output exactly a JSON payload:\n"
                f"{{\n"
                f"  \"approved\": true | false,\n"
                f"  \"reason\": \"Reasoning for your decision...\"\n"
                f"}}"
            )
            try:
                response = await generate_with_retry_fallback(
                    llm_client=rep.llm_client,
                    prompt=prompt,
                    system_instruction=f"You are the representative agent ({rep.name}) of parent team {p.team_id if p else 'Root'}. Evaluate peer communication request.",
                    manager=manager
                )
                if "```" in response:
                    response = response.replace("```json", "").replace("```", "").strip()
                data = json.loads(response)
                if not bool(data.get("approved", False)):
                    logger.info(f"Peer talk between {sender.team_id} and {recipient.team_id} rejected by parent representative {rep.name}")
                    return False
            except Exception as e:
                logger.warning(f"Error querying peer talk approval from representative {rep.name}: {e}. Defaulting to approved.")
        return True

# Migration Policy Implementations

class PermissiveMigrationPolicy(BaseMigrationPolicy):
    async def authorize_migration(
        self,
        team: Any,
        target_parent: Any,
        manager: Any,
        rationale: str
    ) -> Tuple[bool, str]:
        return True, "Migration allowed by permissive policy."

class AncestorApprovalMigrationPolicy(BaseMigrationPolicy):
    async def authorize_migration(
        self,
        team: Any,
        target_parent: Any,
        manager: Any,
        rationale: str
    ) -> Tuple[bool, str]:
        current_parent = team.parent_team
        current_parent_id = current_parent.team_id if current_parent else "Root"
        
        involved_teams = []
        if current_parent:
            involved_teams.append(current_parent)
        if target_parent:
            involved_teams.append(target_parent)
        lca = find_lca(current_parent, target_parent)
        if lca:
            involved_teams.append(lca)
        else:
            involved_teams.append(None) # Represents Root AI
            
        unique_involved = []
        for t in involved_teams:
            if t not in unique_involved:
                unique_involved.append(t)
                
        for t in unique_involved:
            rep = get_team_representative(t, manager)
            if not rep or not getattr(rep, "llm_client", None):
                continue
            
            arbitration_prompt = (
                f"Evaluate a request to reorganize the agent team hierarchy.\n\n"
                f"Team requesting migration: {team.team_id}\n"
                f"Current Purpose: {team.team_purpose}\n"
                f"Current Parent Team: {current_parent_id} (Purpose: {current_parent.team_purpose if current_parent else 'Root Coordinator'})\n\n"
                f"Target Parent Team: {target_parent.team_id}\n"
                f"Target Parent Purpose: {target_parent.team_purpose}\n\n"
                f"Migration Rationale provided by the team:\n\"{rationale}\"\n\n"
                f"Please evaluate if this migration is logical, beneficial for task progress, and does not create redundant hierarchy.\n"
                f"Output exactly a JSON payload:\n"
                f"{{\n"
                f"  \"approved\": true | false,\n"
                f"  \"reason\": \"Reasoning for your decision...\"\n"
                f"}}"
            )
            try:
                response = await generate_with_retry_fallback(
                    llm_client=rep.llm_client,
                    prompt=arbitration_prompt,
                    system_instruction=f"You are the representative agent ({rep.name}) of team {t.team_id if t else 'Root'}. Evaluate restructure proposal.",
                    manager=manager
                )
                if "```" in response:
                    response = response.replace("```json", "").replace("```", "").strip()
                data = json.loads(response)
                approved = bool(data.get("approved", False))
                reason = str(data.get("reason", "No reason provided."))
                if not approved:
                    return False, f"Rejected by representative {rep.name} of team {t.team_id if t else 'Root'}: {reason}"
            except Exception as e:
                logger.warning(f"Error querying migration approval from representative {rep.name}: {e}. Defaulting to approved.")
        return True, "Approved by ancestor approval policy."

class LineagePathMigrationPolicy(BaseMigrationPolicy):
    async def authorize_migration(
        self,
        team: Any,
        target_parent: Any,
        manager: Any,
        rationale: str
    ) -> Tuple[bool, str]:
        current_parent = team.parent_team
        current_parent_id = current_parent.team_id if current_parent else "Root"
        
        lca = find_lca(current_parent, target_parent)
        
        path1 = get_path_to_ancestor(current_parent, lca)
        path2 = get_path_to_ancestor(target_parent, lca)
        
        involved_teams = path1 + path2
        if not lca:
            involved_teams.append(None) # Root level
            
        unique_involved = []
        for t in involved_teams:
            if t not in unique_involved:
                unique_involved.append(t)
                
        for t in unique_involved:
            rep = get_team_representative(t, manager)
            if not rep or not getattr(rep, "llm_client", None):
                continue
            
            arbitration_prompt = (
                f"Evaluate a request to reorganize the agent team hierarchy.\n\n"
                f"Team requesting migration: {team.team_id}\n"
                f"Current Purpose: {team.team_purpose}\n"
                f"Current Parent Team: {current_parent_id} (Purpose: {current_parent.team_purpose if current_parent else 'Root Coordinator'})\n\n"
                f"Target Parent Team: {target_parent.team_id}\n"
                f"Target Parent Purpose: {target_parent.team_purpose}\n\n"
                f"Migration Rationale provided by the team:\n\"{rationale}\"\n\n"
                f"Please evaluate if this migration is logical, beneficial for task progress, and does not create redundant hierarchy.\n"
                f"Output exactly a JSON payload:\n"
                f"{{\n"
                f"  \"approved\": true | false,\n"
                f"  \"reason\": \"Reasoning for your decision...\"\n"
                f"}}"
            )
            try:
                response = await generate_with_retry_fallback(
                    llm_client=rep.llm_client,
                    prompt=arbitration_prompt,
                    system_instruction=f"You are the representative agent ({rep.name}) of team {t.team_id if t else 'Root'}. Evaluate restructure proposal.",
                    manager=manager
                )
                if "```" in response:
                    response = response.replace("```json", "").replace("```", "").strip()
                data = json.loads(response)
                approved = bool(data.get("approved", False))
                reason = str(data.get("reason", "No reason provided."))
                if not approved:
                    return False, f"Rejected by representative {rep.name} of team {t.team_id if t else 'Root'}: {reason}"
            except Exception as e:
                logger.warning(f"Error querying migration approval from representative {rep.name}: {e}. Defaulting to approved.")
        return True, "Approved by lineage path policy."

# Policy resolution helpers

def resolve_communication_policy(policy_name: str) -> BaseCommunicationPolicy:
    policies = {
        "permissive": PermissiveCommunicationPolicy(),
        "rule_gated": RuleGatedCommunicationPolicy(),
        "proxied": ProxiedCommunicationPolicy()
    }
    return policies.get(policy_name.lower(), PermissiveCommunicationPolicy())

def resolve_migration_policy(policy_name: str) -> BaseMigrationPolicy:
    policies = {
        "permissive": PermissiveMigrationPolicy(),
        "ancestor_approval": AncestorApprovalMigrationPolicy(),
        "lineage_path": LineagePathMigrationPolicy()
    }
    return policies.get(policy_name.lower(), AncestorApprovalMigrationPolicy())
