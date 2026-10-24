"""Technical incident handling, never automatic repair or business supervision."""

from .contract import Tool
from .context import _resolve_actual_agent


def build_health_tools(manager):
    def actor():
        owner = _resolve_actual_agent(None, manager)
        if owner is None:
            raise PermissionError("Health tools require the current active person.")
        return owner

    async def list_health_incidents(pending_only: bool = True) -> list[dict]:
        owner, items = actor(), []
        for row in manager._records.snapshot():
            if row.table_name != "health_incidents" or pending_only and row.values["status"] == "acknowledged":
                continue
            try:
                visible = manager.inspect_health_incident(row.values["incident_id"], actor=owner)
            except PermissionError:
                continue
            items.append({key: value for key, value in visible.items() if key != "evidence"})
        return items

    async def inspect_health_incident(incident_id: str) -> dict:
        return manager.inspect_health_incident(incident_id, actor=actor())

    async def claim_health_incident(incident_id: str) -> dict:
        return await manager.claim_health_incident(incident_id, actor=actor())

    async def acknowledge_health_incident(incident_id: str, occurrence_count: int, claim_token: str) -> dict:
        return await manager.acknowledge_health_incident(
            incident_id, occurrence_count, actor=actor(), claim_token=claim_token
        )

    return {
        function.__name__: Tool(function.__name__, description, function)
        for function, description in (
            (list_health_incidents, "List permitted technical incident references; reading is not acknowledgement."),
            (inspect_health_incident, "Inspect permitted technical evidence, without intervention authority."),
            (claim_health_incident, "Explicitly begin handling the current incident generation."),
            (acknowledge_health_incident, "Acknowledge the exact handled generation using its claim token; newer evidence stays pending."),
        )
    }
