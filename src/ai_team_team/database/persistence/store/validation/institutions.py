"""Exact institutional authority behind position and resource transitions."""

import hashlib
import json
from collections import Counter


def validate_institutions(rows, sources, get, source, require, *, allow_unreferenced_sources=False):
    def case(identity, kind, business_id, agent_id, team_id, *, complete=True):
        result = source("governance_cases", identity)
        data = result["data"]
        require((result["principal_agent_id"], result["principal_team_id"]) == (agent_id, team_id)
            and data["business_kind"] == kind and data["business_id"] == business_id,
            "institutional case purpose or principal mismatch")
        ballots = [row for row in sources["governance_ballots"] if row["case_id"] == identity]
        require(not complete or len(ballots) == len(data["voter_agent_ids"]) and {row["voter_agent_id"] for row in ballots} == set(data["voter_agent_ids"]),
            "institutional authority lacks every frozen explicit ballot")
        if complete and data["choice_kind"] == "boolean":
            require(all(type(row["choice"].get("approved")) is bool for row in ballots),
                "boolean authority contains a nonliteral decision")
            approved = sum(row["choice"]["approved"] is True for row in ballots)
            require((data["status"] == "APPROVED" and approved > len(ballots) / 2)
                or (data["status"] == "DENIED" and approved < len(ballots) / 2),
                "institutional boolean authority disagrees with its strict majority")
        return {**data, "ballots": ballots}

    for acceptance in rows["parent_acceptances"]:
        require(acceptance["case_id"] is not None and acceptance["decision_agent_id"] is None,
            "organizational acceptance requires its explicit frozen case")
        record = source("governance_cases", acceptance["case_id"])["data"]
        choice = case(acceptance["case_id"], "migration", record["business_id"],
            acceptance["parent_agent_id"], acceptance["parent_team_id"])
        request = source("migration_requests", record["business_id"])["data"]
        require(request["team_id"] == acceptance["attaching_team_id"]
            and (request["target_parent_agent_id"], request["target_parent_id"]) == (
                acceptance["parent_agent_id"], acceptance["parent_team_id"]),
            "acceptance was issued for a different child or proposed parent")
        fingerprint = hashlib.sha256(json.dumps(request["path_evidence"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        require(acceptance["topology_fingerprint"] == fingerprint and choice["status"] == "APPROVED"
            and acceptance["approved"] == 1, "parent acceptance has no matching explicit approval")
    for team in sources["teams"]:
        history = sorted((event for event in rows["team_topology_events"] if event["team_id"] == team["team_id"]),
            key=lambda event: event["position_revision"])
        if not history and allow_unreferenced_sources and team["position_revision"] == 1:
            from ai_team_team.database.models import ACTIVITY_TABLES
            referenced = any(constraint.referred_table.name == "teams"
                and any(row[element.parent.name] == team["team_id"] for element in constraint.elements)
                for name, table in ACTIVITY_TABLES.items() for row in rows[name]
                for constraint in table.foreign_key_constraints)
            if not referenced:
                # An unused staging prerequisite is not an accepted team fact.
                # Any actual activity/relationship reference requires history.
                continue
        require(bool(history) and history[0]["transition"] == "creation"
            and [event["position_revision"] for event in history] == list(range(1, len(history) + 1)),
            "organizational position history is missing, duplicated, or discontinuous")
        require(history[0]["old_parent_agent_id"] is None and history[0]["old_parent_team_id"] is None,
            "team creation has a fictional previous parent")
        for previous, current in zip(history, history[1:]):
            require((previous["new_parent_agent_id"], previous["new_parent_team_id"]) == (
                current["old_parent_agent_id"], current["old_parent_team_id"]), "position history changes the prior parent")
            require(current["transition"] != "creation", "a team cannot be created twice")
            if current["transition"] in {"attachment", "migration"}:
                require(current["acceptance_id"] is not None, "attachment bypassed target-parent acceptance")
        latest = history[-1]
        require((team["position_revision"], team["parent_agent_id"], team["parent_team_id"]) == (
            latest["position_revision"], latest["new_parent_agent_id"], latest["new_parent_team_id"]),
            "current organizational projection disagrees with accepted position history")
        own = [event for event in history if event["transition"] in {"attachment", "migration", "voluntary_detachment"}]
        cooldown = next((item for item in rows["team_position_cooldowns"] if item["team_id"] == team["team_id"]), None)
        require(bool(own) == (cooldown is not None), "own-position history has no exact cooldown evidence")
        if own:
            require(cooldown["event_id"] == own[-1]["event_id"] and cooldown["duration_seconds"] == 600,
                "cooldown was reset by an unrelated or inherited transition")
            if cooldown["accounting_mode"] == "wall_time":
                require(cooldown["deadline"] == own[-1]["created_at"] + cooldown["duration_seconds"],
                    "position cooldown deadline is not anchored to its successful commit")
            else:
                require(0 <= cooldown["remaining_seconds"] <= cooldown["duration_seconds"],
                    "remaining position cooldown exceeds its original duration")
    for attempt in rows["resource_decisions"]:
        captured_position = next((event for event in rows["team_topology_events"]
            if event["team_id"] == attempt["scope_team_id"] and event["position_revision"] == attempt["scope_position_revision"]), None)
        require(captured_position is not None and (
            captured_position["new_parent_agent_id"], captured_position["new_parent_team_id"]) == (
                attempt["principal_agent_id"], attempt["principal_team_id"]),
            "resource parent authority has no captured organizational position")
        require(type(attempt["candidates"]) is list and bool(attempt["candidates"])
            and len(set(attempt["candidates"])) == len(attempt["candidates"])
            and attempt["exhausted_alias"] not in attempt["candidates"],
            "resource candidates are empty, duplicated, or include the exhausted alias")
        if attempt["decision_case_id"] is not None:
            decision = case(attempt["decision_case_id"], "failover", attempt["attempt_id"],
                attempt["principal_agent_id"], attempt["principal_team_id"], complete=attempt["status"] == "applied")
            require(decision["candidates"] == attempt["candidates"] and decision["expires_at"] == attempt["deadline"],
                "resource attempt changed its captured candidates or independent deadline")
        else:
            decision = None
        if attempt["status"] == "applied":
            require(decision is not None and decision["status"] == "APPROVED"
                and len(decision["ballots"]) == len(decision["voter_agent_ids"]),
                "resource replacement has no complete explicit parent decision")
            counts = Counter(ballot["choice"]["model_alias"] for ballot in decision["ballots"])
            require(attempt["selected_alias"] in attempt["candidates"]
                and counts[attempt["selected_alias"]] > len(decision["voter_agent_ids"]) / 2
                and attempt["resolved_at"] < attempt["deadline"], "resource replacement has no timely strict majority")
