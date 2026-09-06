"""Background materialization of immutable state snapshots."""

import json
from typing import Any, Dict


class StoreMaterializationMixin:
    @staticmethod
    def _materialize(snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """Performs expensive deep JSON copying on the persistence worker."""
        result = dict(snapshot)
        configs = snapshot.get("configs")
        if configs is not None:
            result["configs"] = {
                key: (value if key in {"schema_version", "root_ai_id"} else json.dumps(value))
                for key, value in configs.items()
            }
        for key in ("agents", "agent_dependencies"):
            result[key] = [
                {
                    **agent,
                    "last_context": (
                        json.dumps(agent["last_context"])
                        if agent.get("last_context") is not None
                        else None
                    ),
                    "messages": json.loads(json.dumps(list(agent["messages"]))),
                }
                for agent in snapshot.get(key, ())
            ]
        result["library_dependencies"] = [
            {
                **library,
                "files": json.loads(json.dumps(dict(library.get("files", {})))),
            }
            for library in snapshot.get("library_dependencies", ())
        ]
        result["teams"] = [
            {
                **team,
                "status_map": json.dumps(team["status_map"]),
            }
            for team in snapshot.get("teams", ())
        ]
        result["inboxes"] = {
            team_id: {
                **inbox,
                "messages": json.loads(json.dumps(list(inbox["messages"]))),
            }
            for team_id, inbox in snapshot.get("inboxes", {}).items()
        }
        result["proposals"] = json.loads(json.dumps(snapshot.get("proposals", {})))
        result["permissions"] = json.loads(json.dumps(snapshot.get("permissions", {})))
        result["links"] = json.loads(json.dumps(snapshot.get("links", {})))
        for key in (
            "communication_requests",
            "communication_approvals",
            "communication_ballots",
            "communication_agreements",
            "peer_messages",
            "memory_events",
            "memory_segments",
            "memory_cards",
            "memory_references",
        ):
            result[key] = json.loads(json.dumps(snapshot.get(key, [])))
        return result
