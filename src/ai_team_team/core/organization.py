"""Pure explicit-parent routing shared by runtime and checkpoint validation."""

from .communication import ApprovalPrincipal


def principal_for(node):
    if node is None or isinstance(node, ApprovalPrincipal):
        return node
    if hasattr(node, "team_id"):
        return ApprovalPrincipal(kind="agent_team", principal_id=node.team_id)
    if hasattr(node, "agent_id"):
        return ApprovalPrincipal(kind="agent", principal_id=node.agent_id)
    raise TypeError("An organizational parent must be an Agent, AgentTeam, principal, or None.")


def ancestry(team_id, parents):
    result, seen = [], set()
    current = ApprovalPrincipal(kind="agent_team", principal_id=team_id)
    while current is not None:
        if current.key in seen:
            raise ValueError("The explicit organizational topology contains a cycle.")
        seen.add(current.key)
        result.append(current)
        current = parents.get(current.principal_id) if current.kind == "agent_team" else None
    return result


def communication_route(sender_id, recipient_id, parents, policy, revisions=None):
    """Return required authority and minimal relevant edge/exemption evidence."""
    sender = ancestry(sender_id, parents)
    recipient = ancestry(recipient_id, parents)
    independent = [parents.get(owner) is None for owner in (sender_id, recipient_id)]
    if policy == "permissive":
        return [], {}
    edges = {owner: parents.get(owner) for owner in (sender_id, recipient_id)}
    if all(independent):
        required = []
    elif policy == "parent_approval":
        required = [parents.get(owner) for owner in (sender_id, recipient_id) if parents.get(owner)]
    elif policy == "lineage_approval":
        common = next((node for node in sender if node in recipient), None)
        left = sender[1:sender.index(common) + 1] if common is not None else sender[1:]
        right = recipient[:recipient.index(common)] if common is not None else recipient
        if independent[1]:
            right = []
        required = [*left, *reversed(right)]
        for chain in (sender, recipient):
            stop = chain.index(common) if common in chain else len(chain)
            for node in chain[:stop]:
                if node.kind == "agent_team":
                    edges[node.principal_id] = parents.get(node.principal_id)
    else:
        raise ValueError("Unknown communication institution.")
    required = list({node.key: node for node in required}.values())
    evidence = {
        "policy": policy,
        "endpoints": [
            {"team_id": owner, "authority": "EXEMPT" if exempt else "REQUIRED"}
            for owner, exempt in zip((sender_id, recipient_id), independent)
        ],
        "edges": [{"team_id": owner, "parent": node.model_dump(mode="json") if node else None,
                   "position_revision": (revisions or {}).get(owner, 1)}
                  for owner, node in sorted(edges.items())],
    }
    return required, evidence


def validate_route_evidence(request, agent_ids, team_ids):
    evidence = request.route_evidence
    if not isinstance(evidence, dict) or set(evidence) != {"policy", "endpoints", "edges"}:
        raise ValueError("A communication route requires explicit captured edge evidence.")
    parents, revisions = {}, {}
    for edge in evidence["edges"]:
        if set(edge) != {"team_id", "parent", "position_revision"} or edge["team_id"] not in team_ids or edge["team_id"] in parents:
            raise ValueError("A captured organizational edge is missing or duplicated.")
        parent = ApprovalPrincipal.model_validate(edge["parent"]) if edge["parent"] else None
        if parent and parent.principal_id not in (team_ids if parent.kind == "agent_team" else agent_ids):
            raise ValueError("A captured organizational parent is missing.")
        parents[edge["team_id"]] = parent
        if type(edge["position_revision"]) is not int or edge["position_revision"] < 1:
            raise ValueError("A captured organizational edge requires its positive position revision.")
        revisions[edge["team_id"]] = edge["position_revision"]
    if {request.sender_team_id, request.recipient_team_id} - parents.keys():
        raise ValueError("Captured endpoint parent evidence is missing.")
    expected, canonical = communication_route(request.sender_team_id, request.recipient_team_id,
        parents, request.policy_snapshot["policy"], revisions)
    if expected != request.approval_principals or canonical != evidence:
        raise ValueError("The captured approval route disagrees with its explicit topology.")


def migration_route(team_id, target, parents, revisions, policy, operation):
    """Capture real authorities and only relevant organizational edge versions."""
    old = parents.get(team_id)
    if operation in {"voluntary_detachment", "parent_loss"}:
        principals, relevant = [], {team_id: old}
    else:
        left = ancestry(team_id, parents)[1:]
        right = ancestry(target.principal_id, parents) if target.kind == "agent_team" else [target]
        common = next((node for node in left if node in right), None)
        left = left[:left.index(common) + 1] if common is not None else left
        right = right[:right.index(common) + 1] if common is not None else right
        if policy == "permissive":
            principals = [target]
        elif policy == "ancestor_approval":
            principals = [node for node in (old, target, common) if node is not None]
        elif policy == "lineage_path":
            principals = [*left, *right]
        else:
            raise ValueError("Unknown migration institution.")
        principals = list({node.key: node for node in principals if node is not None}.values())
        relevant = {team_id: old}
        for node in [*left, *right]:
            if node.kind == "agent_team" and node != common:
                relevant[node.principal_id] = parents[node.principal_id]
    evidence = {
        "operation": operation, "policy": policy, "target": target.model_dump(mode="json") if target else None,
        "own_parent_exemption": "EXEMPT" if old is None else "REQUIRED",
        "edges": {key: node.model_dump(mode="json") if node else None for key, node in sorted(relevant.items())},
        "position_revisions": {key: revisions[key] for key in sorted(relevant)},
        "principals": [node.model_dump(mode="json") for node in principals],
    }
    return principals, evidence


def validate_migration_evidence(request, agent_ids, team_ids):
    evidence = request.path_evidence
    if set(evidence) != {"operation", "policy", "target", "own_parent_exemption", "edges", "position_revisions", "principals"}:
        raise ValueError("A migration requires complete explicit captured path evidence.")
    parents = {}
    for owner, value in evidence["edges"].items():
        if owner not in team_ids:
            raise ValueError("Captured migration path references a missing team.")
        parent = ApprovalPrincipal.model_validate(value) if value else None
        if parent and parent.principal_id not in (team_ids if parent.kind == "agent_team" else agent_ids):
            raise ValueError("Captured migration path references a missing parent.")
        parents[owner] = parent
    revisions = evidence["position_revisions"]
    if set(revisions) != set(parents) or any(type(value) is not int or value < 1 for value in revisions.values()):
        raise ValueError("Captured migration edge revisions are missing or invalid.")
    if request.team_id not in parents:
        raise ValueError("The moving team's captured parent edge is missing.")
    original = (ApprovalPrincipal(kind="agent_team", principal_id=request.original_parent_id) if request.original_parent_id else
        ApprovalPrincipal(kind="agent", principal_id=request.original_parent_agent_id) if request.original_parent_agent_id else None)
    target = (ApprovalPrincipal(kind="agent_team", principal_id=request.target_parent_id) if request.target_parent_id else
        ApprovalPrincipal(kind="agent", principal_id=request.target_parent_agent_id) if request.target_parent_agent_id else None)
    if parents[request.team_id] != original:
        raise ValueError("Captured migration evidence disagrees with its original parent.")
    required, canonical = migration_route(request.team_id, target, parents, revisions, request.policy_name, request.operation)
    if canonical != evidence or required != request.principals:
        raise ValueError("The captured migration institution and authority path disagree.")
