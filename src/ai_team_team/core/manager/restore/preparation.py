"""Operation-specific recovery settles in detached state before publication."""

import asyncio

from ..activity.values import capture


def changed_rows(before, after, key):
    original = {key(row): row for row in before}
    return [row for row in after if original.get(key(row)) != row]


async def prepare_domain_recovery(manager, staged, state, annotations, events, *, restoration_start):
    staged._activity.clock = manager._activity.clock
    await staged._activity.after_restore(restoration_start=restoration_start)
    # These services settle their own protocols; recovery does not supply votes,
    # reissue invitations, choose models, or execute an interrupted tool.
    await staged._failover.interrupt_pending()
    await staged.supervisor.interrupt_restored_assessments()
    reset, requests = [], {}
    for row in staged._records.snapshot():
        if row.table_name == "audit_execution_evidence" and row.values["status"] in {"queued", "running"}:
            reset.append(capture(staged, row.table_name, execution_id=row.values["execution_id"],
                outcome_unconfirmed=1, attention="required"))
        if row.table_name in {"audit_model_requests", "memory_index_requests"} and row.values["outcome"] == "pending":
            identifier = "request_id"
            unsent = row.values["dispatch_state"] == "unsent"
            reset.append(capture(staged, row.table_name, **{identifier: row.values[identifier]},
                dispatch_state="confirmed_unsent" if unsent else "unknown_sent",
                outcome="cancelled" if unsent else "uncertain"))
            requests["audit_request_id" if row.table_name == "audit_model_requests" else "index_request_id", row.values[identifier]] = unsent
    for row in staged._records.snapshot():
        if row.table_name == "model_token_claims" and row.values["settlement"] == "reserved":
            match = next((unsent for (field, identifier), unsent in requests.items()
                          if row.values[field] == identifier), None)
            if match is not None:
                reset.append(capture(staged, "model_token_claims", claim_id=row.values["claim_id"],
                    settlement="confirmed_unsent" if match else "unknown_sent",
                    settled_at=staged._activity.clock.wall_time()))
    if reset:
        await staged._records.commit(reset)
    return await asyncio.to_thread(capture_recovery_delta, staged, state)


def capture_recovery_delta(staged, state):
    """The detached manager has no mutators while large JSON values are copied."""
    original = {row.identity: row for row in state.get("records", ())}
    delta = {"records": tuple(row for row in staged._records.snapshot()
                              if row.table_name != "publication_manifests" and original.get(row.identity) != row)}
    snapshot = staged._memory.snapshot()
    for section, key in (("memory_events", "event_id"), ("memory_segments", "segment_id")):
        delta[section] = changed_rows(state.get(section, ()), snapshot[section], lambda row: row[key])
    delta["governance_cases"] = changed_rows(state.get("governance_cases", ()), staged._governance.snapshot(), lambda row: row["case_id"])
    delta["communication_requests"] = changed_rows(state.get("communication_requests", ()),
        [item.model_dump(mode="json") for item in staged.broker.communication_requests.values()], lambda row: row["request_id"])
    approvals = [item.model_dump(mode="json") for item in staged.broker.communication_approvals.values()]
    changed = changed_rows(state.get("communication_approvals", ()), approvals,
        lambda row: (row["request_id"], row["principal"]["kind"], row["principal"]["principal_id"]))
    changed_ids = {row["request_id"] for row in changed}
    delta["communication_approvals"] = [row for row in approvals if row["request_id"] in changed_ids]
    return delta
