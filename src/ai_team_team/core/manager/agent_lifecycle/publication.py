"""Candidate lifecycle projections are published only after their receipt."""


def validate_changes(manager, changes):
    aliases = {}
    for owner, state in (changes or {}).items():
        agent = manager._agents_by_id[owner]
        if state not in {"retained", "archived", "dead", "active"}:
            raise ValueError("Invalid Agent lifecycle transition.")
        if agent.lifecycle_state == "dead" and state != "dead":
            raise ValueError("Death is terminal; a dead Agent cannot be reactivated.")
        aliases[owner] = manager.resolve_model_alias(agent.llm_client) if agent.lifecycle_state == "active" else agent._model_alias
    return aliases


def library_state(changes, library):
    state = (changes or {}).get(library.owner_agent_id)
    return "archived" if state == "dead" else state or library.lifecycle_state


def publish_changes(manager, changes, aliases):
    for owner, state in (changes or {}).items():
        agent = manager._agents_by_id[owner]
        library = manager.libraries[agent.private_doc_library_id]
        agent.lifecycle_state = state
        library.lifecycle_state = "archived" if state == "dead" else state
        agent._model_alias = aliases[owner]
        if state != "active":
            manager.agents.pop(agent.name, None)
            agent.llm_client = None
        else:
            manager.agents[agent.name] = agent

