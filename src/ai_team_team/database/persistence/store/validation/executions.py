"""Execution ownership, source provenance, and factual progress validation."""


def validate_executions(rows, source, get, require):
    for row in rows["executions"]:
        require(row["visibility"] == "foreground" or row["contract_snapshot"] is not None,
                "background execution lacks its explicit declaration")
        if row["invocation_id"] is not None:
            invocation = get("activity_invocations", row["invocation_id"])
            require((row["agent_id"], row["scope_kind"], row["scope_team_id"], row["runtime_generation"]) ==
                    (invocation["agent_id"], invocation["scope_kind"], invocation["scope_team_id"], invocation["runtime_generation"]), "execution captured scope mismatch")
        else:
            require(type(row["metadata"]) is dict and row["metadata"].get("origin") == "host"
                    and row["call_id"] is not None and row["contract_snapshot"] is not None, "Host execution lacks admission provenance")
        if row["contract_snapshot"] is not None:
            import json
            from ai_team_team.core.activity.contracts import ToolExecutionContract
            contract = dict(row["contract_snapshot"])
            executor = contract.pop("executor", None)
            storage = contract.pop("result_storage", None)
            require(type(executor) is str and bool(executor.strip()), "execution executor binding snapshot missing")
            require(storage in {"protected", "transient"}, "execution result-storage policy missing")
            try:
                declared = ToolExecutionContract.model_validate_json(json.dumps(contract))
            except (TypeError, ValueError):
                require(False, "invalid execution contract snapshot")
            require(tuple(row["effects"]) == declared.effects, "execution effects disagree with captured contract")
            require(row["visibility"] == "foreground" or declared.background_allowed, "execution cannot become background without permission")
            require(type(row["metadata"]) is dict and set(row["metadata"]) == {"description", "labels", "origin"}
                    and type(row["metadata"]["description"]) is str
                    and type(row["metadata"]["labels"]) is list and all(type(label) is str for label in row["metadata"]["labels"])
                    and row["metadata"]["origin"] == ("model" if row["invocation_id"] else "host"), "invalid execution metadata")
            require(type(row["source_references"]) is list, "missing execution source provenance")
            for provenance in row["source_references"]:
                require(type(provenance) is dict and provenance.get("kind") in {"library", "external"}, "invalid execution source provenance")
                if provenance["kind"] == "library":
                    require(set(provenance) == {"kind", "lib_id", "path", "scope_team_id"}, "invalid library source provenance fields")
                    library = source("libraries", provenance["lib_id"])
                    require(provenance["scope_team_id"] == row["scope_team_id"], "execution source scope changed")
                    if library["library_kind"] == "agent_private":
                        require(library["owner_agent_id"] == row["agent_id"], "execution source private owner mismatch")
                    from ai_team_team.doc_library import DocumentLibrary
                    try:
                        normalized = DocumentLibrary._normalize_path(provenance["path"] or "/", allow_root=True)
                    except (TypeError, ValueError, PermissionError):
                        require(False, "invalid execution source path")
                    require(normalized == provenance["path"], "execution source path is not canonical")
            require(any(payload["execution_id"] == row["execution_id"] and payload["content_kind"] == "input"
                        for payload in rows["execution_payloads"]), "execution lacks its committed input reference")
            attempts = [item for item in rows["execution_attempts"] if item["execution_id"] == row["execution_id"]]
            require(sorted(item["attempt_index"] for item in attempts) == list(range(1, len(attempts) + 1)),
                    "execution attempt ordering is incomplete")
            require(bool(attempts) == (row["started_at"] is not None), "execution start and dispatch evidence disagree")
            require(row["status"] != "completed" or bool(attempts), "completed execution was never dispatched")
            if row["status"] in {"completed", "failed", "cancelled"}:
                require(row["finished_at"] is not None, "terminal execution lacks its completion timing")
            if row["status"] in {"completed", "failed"}:
                require(any(payload["execution_id"] == row["execution_id"] and payload["content_kind"] == "result"
                            for payload in rows["execution_payloads"]), "terminal execution lacks its confirmed result envelope")
            observations = [item for item in rows["execution_observations"] if item["execution_id"] == row["execution_id"]]
            require(all(type(item["observation_index"]) is int for item in observations), "execution health ordering is missing")
            require(sorted(item["observation_index"] for item in observations) == list(range(1, len(observations) + 1)),
                    "execution health ordering is incomplete")
        require(row["started_at"] is None or row["started_at"] >= row["created_at"], "execution started before admission")
        require(row["finished_at"] is None or row["status"] in {"completed", "failed", "cancelled"}
                and row["finished_at"] >= (row["started_at"] if row["started_at"] is not None else row["created_at"]), "invalid execution completion timing")
        require(type(row["effects"]) is list and bool(row["effects"])
                and all(type(effect) is str and effect in {"read_only", "artifact_write", "domain_mutation", "self_modification", "undeclared"} for effect in row["effects"])
                and len(set(row["effects"])) == len(row["effects"]), "execution effects snapshot invalid")
    for row in rows["execution_payloads"]:
        require(get("executions", row["execution_id"])["agent_id"] == row["agent_id"], "payload owner mismatch")
        if get("executions", row["execution_id"])["contract_snapshot"] is not None:
            import hashlib
            import json
            actual_digest = hashlib.sha256(json.dumps(row["content"], sort_keys=True, ensure_ascii=False,
                separators=(",", ":"), allow_nan=False).encode()).hexdigest()
            require(row["digest"] == actual_digest, "execution payload digest mismatch")
            expected_id = ("INPUT-" if row["content_kind"] == "input" else "RESULT-") + row["execution_id"]
            require(row["payload_id"] == expected_id, "execution payload reference is not canonical")
            content = row["content"]
            require(type(content) is dict, "execution payload must be an object")
            if row["content_kind"] == "result":
                from ai_team_team.core.response import ToolResultStatus
                require(set(content) == {"status", "content", "error_kind", "attempts", "transient"}, "invalid result envelope")
                require(content["status"] in {item.value for item in ToolResultStatus}
                        and (content["error_kind"] is None or type(content["error_kind"]) is str), "invalid result classification")
                require(get("executions", row["execution_id"])["status"] == ("completed" if content["status"] == "success" else "failed"),
                        "result classification disagrees with the terminal execution")
                require(type(content["transient"]) is bool and content["transient"] ==
                    (get("executions", row["execution_id"])["contract_snapshot"]["result_storage"] == "transient"), "result storage policy mismatch")
                require(content["content"] is None if content["transient"] else type(content["content"]) is str,
                        "transient result body was persisted")
                require(type(content["attempts"]) is int and content["attempts"] >= 1, "invalid result attempt count")
            else:
                require(set(content) == {"arguments", "transient"} and type(content["transient"]) is bool,
                        "invalid execution input envelope")
                arguments = content["arguments"]
                require(arguments == {} if content["transient"] else type(arguments) is dict
                        and set(arguments) == {"args", "kwargs"} and type(arguments["args"]) is list and type(arguments["kwargs"]) is dict,
                        "invalid or unredacted execution arguments")
    for row in rows["execution_observations"]:
        if row["attempt_id"]:
            require(get("execution_attempts", row["attempt_id"])["execution_id"] == row["execution_id"], "observation attempt mismatch")
    for row in rows["execution_controls"]:
        require(get("executions", row["execution_id"])["agent_id"] == row["requester_agent_id"], "control requester mismatch")
        require((row["acknowledgement"] == "acknowledged") == (row["acknowledged_at"] is not None), "control acknowledgement evidence mismatch")
