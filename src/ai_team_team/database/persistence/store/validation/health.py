"""Health evidence is attributable, bounded, and never business authority."""

import math

from ai_team_team.core.health import HealthSubject
from ai_team_team.core.response import AuditResult


def validate_health(rows, sources, get, source, require):
    for state in rows["health_detector_states"]:
        samples, identifiers = state["samples"], state["observation_ids"]
        require(type(samples) is list and type(identifiers) is list and len(samples) == len(identifiers)
            and len(set(identifiers)) == len(identifiers), "detector sample references are inconsistent")
        for moment, identity in zip(samples, identifiers):
            observation = get("health_observations", identity)
            require(type(moment) in {int, float} and math.isfinite(moment)
                and moment == observation["observed_at"], "detector sample timestamp mismatch")
            require(observation["agent_id"] == state["agent_id"] and observation["detector"] == state["detector"]
                and (observation["tool_name"] or "-") == state["tool_key"] and not observation["valid"],
                "detector streak crosses identity, category, or success")
            if state["detector"] == "tool_arguments":
                require(observation["error_kind"] == state["error_kind"], "argument streak mixes error categories")
        if state["last_assessed_id"] is not None:
            observation = get("health_observations", state["last_assessed_id"])
            require(observation["agent_id"] == state["agent_id"] and observation["detector"] == state["detector"],
                "assessment trigger belongs to another detector owner")
    for observation in rows["health_observations"]:
        require((observation["detector"] == "tool_arguments") == (observation["tool_name"] is not None),
            "tool detector attribution is missing or misplaced")
        require(not observation["valid"] or observation["error_kind"] is None,
            "valid health evidence cannot retain a failure category")
    for incident in rows["health_incidents"]:
        HealthSubject.from_record(incident)
        occurrences = sorted((event for event in rows["health_incident_events"]
            if event["incident_id"] == incident["incident_id"] and event["event_kind"] == "occurrence"),
            key=lambda event: event["occurrence_count"])
        require([event["occurrence_count"] for event in occurrences] == list(range(1, incident["occurrence_count"] + 1)),
            "incident occurrence history is incomplete or duplicated")
        require(occurrences[0]["created_at"] == incident["first_at"]
            and max(event["created_at"] for event in occurrences) == incident["latest_at"],
            "incident first/latest timestamps disagree with retained history")
        claim = incident["evidence"].get("claim")
        delivery = incident["evidence"].get("delivery")
        if delivery is not None:
            require(type(delivery) is dict and set(delivery) == {"occurrence_count", "mode"}
                and type(delivery["occurrence_count"]) is int and 1 <= delivery["occurrence_count"] <= incident["occurrence_count"]
                and delivery["mode"] in {"none", "queue", "wake"}, "incident delivery outbox is malformed")
        require((incident["status"] == "claimed") == (claim is not None), "incident processing claim mismatch")
        if claim is not None:
            event = get("health_incident_events", claim["token"])
            require(event["incident_id"] == incident["incident_id"] and event["event_kind"] == "claimed"
                and event["occurrence_count"] == claim["occurrence_count"] == incident["occurrence_count"]
                and event["actor_agent_id"] == claim["agent_id"], "incident claim owner or generation mismatch")
        if incident["status"] == "acknowledged":
            require(any(event["incident_id"] == incident["incident_id"]
                and event["event_kind"] in {"acknowledged", "cleared"} and event["occurrence_count"] == incident["occurrence_count"]
                for event in rows["health_incident_events"]), "acknowledged incident has no explicit generation acknowledgement")
        for owner, notice in incident["evidence"].get("notices", {}).items():
            event = source("system_memory_events", notice["event_id"])
            require(event["agent_id"] == owner and event["event_type"] == "health_incident"
                and event["payload"].get("incident_id") == incident["incident_id"]
                and event["payload"].get("occurrence_count") == notice["occurrence_count"] <= incident["occurrence_count"],
                "incident notice is missing or belongs to another occurrence")
    for event in rows["health_incident_events"]:
        incident = get("health_incidents", event["incident_id"])
        require(event["occurrence_count"] <= incident["occurrence_count"], "incident event has a future generation")
    for run in rows["audit_runs"]:
        subject = HealthSubject.from_record(run)
        template = run["template"]
        require(template.get("subject") == subject.model_dump(mode="json")
            and template.get("operational_mode") in {"framework", "supervisor", "framework_then_supervisor"}
            and template.get("quota_policy") == "shared_model_ledger", "audit template authority is inconsistent")
        require(run["deadline"] > run["created_at"], "audit has no positive total deadline")
        evidence = template.get("evidence", {})
        require(type(evidence) is dict and type(evidence.get("observation_ids")) is list
            and type(evidence.get("facts")) is list, "audit permitted evidence is malformed")
        for identity in evidence["observation_ids"]:
            observation = get("health_observations", identity)
            require(subject.kind == "agent" and observation["agent_id"] == subject.subject_id,
                "audit evidence belongs to another person")
        participants = sorted((item for item in rows["audit_participants"] if item["audit_id"] == run["audit_id"]),
            key=lambda item: item["position"])
        require([item["scoped_agent_id"] for item in participants] == run["electorate"]
            and [item["position"] for item in participants] == list(range(len(participants))),
            "audit predefined electorate is incomplete")
        for participant in participants:
            require(participant["identity_snapshot"].get("agent_id") == participant["scoped_agent_id"],
                "audit identity snapshot has the wrong immutable identity")
        findings = [item for item in rows["audit_findings"] if item["audit_id"] == run["audit_id"]]
        for finding in findings:
            require(run["created_at"] <= finding["created_at"] < run["deadline"],
                "an audit finding was admitted outside its total deadline")
            require(type(finding["evidence_references"]) is list
                and not set(finding["evidence_references"]) - set(evidence["observation_ids"]),
                "finding cites evidence outside its permitted profile")
        result = next((item for item in rows["audit_evidence"] if item["audit_id"] == run["audit_id"]), None)
        require((run["status"] in {"completed", "unknown", "interrupted"}) == (result is not None),
            "audit terminal state has no exact retained result")
        if result is not None:
            stored = AuditResult.model_validate(result["findings"]["result"], strict=False)
            require(result["result"] == stored.status.value and result["evidence_references"] == evidence
                and result["identity_snapshots"] == [item["identity_snapshot"] for item in participants],
                "retained audit result or identity snapshots disagree")
            if stored.status.value != "unknown":
                require(len(findings) == len(participants), "health conclusion lacks all predefined findings")
                require(sum(item["status"] == stored.status.value for item in findings) > len(findings) / 2,
                    "health conclusion has no strict majority")
            require(run["status"] != "completed" or stored.status.value != "unknown", "completed audit has an unknown result")
    for checkpoint in rows["audit_activity_checkpoints"]:
        require(type(checkpoint["working_context"]) is list
            and all(type(message) is dict and not set(message) - {"role", "content", "name", "tool_call_id", "tool_calls"}
                for message in checkpoint["working_context"]), "audit checkpoint contains unrelated personal metadata")
