"""The SQL reference and incremental path agree, including reverse effects."""

import unittest

from ai_team_team import StateRestoreError
from ai_team_team.database.persistence.records import DomainRecord, freeze, thaw
from ai_team_team.database.persistence.store.detached_validation import validate_detached_records
from ai_team_team.database.persistence.store.validation.detached import DetachedValidationCache

from ._support import OWNER, invocation_graph, model_request, record, state


def replace_record(candidate, name, identifier, **changes):
    result = dict(candidate)
    result["records"] = tuple(
        DomainRecord(row.table_name, freeze({**thaw(row.values), **changes}))
        if row.table_name == name and identifier in row.identity[1] else row
        for row in candidate["records"])
    return result


class DetachedEquivalenceTests(unittest.TestCase):
    def setUp(self):
        self.cache = DetachedValidationCache()
        self.initial = state()
        self.baseline = self.cache.prepare(self.initial)
        self.cache.accept(self.baseline)

    def assert_equivalent(self, candidate, *, valid):
        for name, validate in (
            ("full", lambda: validate_detached_records(candidate, partial=True)),
            ("incremental", lambda: self.cache.prepare(candidate)),
        ):
            with self.subTest(path=name):
                if valid:
                    validate()
                else:
                    with self.assertRaises(StateRestoreError):
                        validate()
        self.assertIs(self.cache._accepted, self.baseline)

    def test_valid_dispatch_update_reuses_unaffected_groups(self):
        candidate = replace_record(self.initial, "model_requests", "model-request",
                                   dispatch_state="sent", dispatched_at=2.0, state_version=2)
        self.assert_equivalent(candidate, valid=True)
        prepared = self.cache.prepare(candidate)
        self.assertEqual(prepared.checked_tables, {"model_requests"})
        self.assertIs(prepared.graph.records["notification_frames"], self.baseline.graph.records["notification_frames"])
        self.cache.accept(prepared)
        self.assertIs(self.cache._accepted, prepared)

    def test_corruption_matrix_matches_full_reference(self):
        cases = [
            ("model_requests", "model-request", {"input_version": 9}),
            ("model_requests", "model-request", {"dispatch_state": "sent", "dispatched_at": 0.5}),
            ("model_requests", "model-request", {"outcome": "completed"}),
            ("model_requests", "model-request", {"attempt_index": True}),
            ("model_requests", "model-request", {"state_version": 0}),
            ("model_requests", "model-request", {"model_alias": " "}),
            ("activity_invocations", "invocation", {"runtime_generation": 2}),
            ("activity_invocations", "invocation", {"started_at": 0.0}),
            ("notification_frames", "frame", {"context_version": 0}),
            ("activity_admissions", "admission", {"scope_kind": "agent_team", "scope_team_id": None}),
        ]
        for table, identifier, changes in cases:
            with self.subTest(table=table, fields=tuple(changes)):
                self.assert_equivalent(replace_record(self.initial, table, identifier, **changes), valid=False)

    def test_deleted_prerequisite_invalidates_unchanged_dependants(self):
        candidate = {**self.initial, "records": tuple(row for row in self.initial["records"] if row.table_name != "notification_frames")}
        self.assert_equivalent(candidate, valid=False)

    def test_duplicate_identity_is_not_hidden_by_an_index(self):
        self.assert_equivalent({**self.initial, "records": (*self.initial["records"], self.initial["records"][0])}, valid=False)

    def test_partial_unique_index_remains_enforced(self):
        duplicate = record("activity_admissions", admission_id="second", agent_id=OWNER, runtime_generation=1,
                           scope_kind="personal", disposition="admitted", accepted_at=2.0)
        self.assert_equivalent({**self.initial, "records": (*self.initial["records"], duplicate)}, valid=False)

    def test_changed_request_invalidates_unchanged_presented_claim(self):
        request = DomainRecord.capture("model_requests", {**thaw(model_request(OWNER).values),
            "dispatch_state": "sent", "outcome": "completed", "dispatched_at": 2.0})
        notice = record("agent_notifications", notification_id="notice", agent_id=OWNER, source_kind="personal_mail",
                        mail_id="mail", classification="ordinary", deduplication_key="mail", arrival_generation=1, created_at=1.0)
        claim = record("notification_claims", notification_id="notice", model_request_id="model-request", frame_id="frame",
                       status="presented", observed_at=3.0)
        candidate = state((*invocation_graph(OWNER), request, notice, claim))
        candidate["agent_inboxes"] = {OWNER: [{"message_id": "mail", "agent_id": OWNER, "message_type": "note",
                                              "payload": {}, "created_at": 1.0, "read_at": None}]}
        self.baseline = self.cache.prepare(candidate)
        self.cache.accept(self.baseline)
        self.assert_equivalent(replace_record(candidate, "model_requests", "model-request", outcome="pending", state_version=2), valid=False)

    def test_changed_membership_is_checked_without_changed_activity_records(self):
        stream = record("chat_streams", stream_id="stream", team_id="team", next_position=2)
        join = record("chat_events", event_id="join", stream_id="stream", sequence=1,
                      event_kind="join", actor_agent_id=OWNER, created_at=1.0)
        interval = record("membership_intervals", interval_id="interval", team_id="team", agent_id=OWNER,
                          stream_id="stream", join_event_id="join")
        candidate = state((stream, join, interval))
        creation = record("team_topology_events", event_id="created", team_id="team", creator_agent_id=OWNER,
            transition="creation", position_revision=1, created_at=1.0)
        candidate["records"] = (*candidate["records"], creation)
        candidate["teams"] = [{"team_id": "team", "creator_type": "agent", "creator_id": OWNER,
                                "team_kind": "ordinary", "lifecycle_state": "active", "members": [OWNER]}]
        self.baseline = self.cache.prepare(candidate)
        self.cache.accept(self.baseline)
        self.assert_equivalent({**candidate, "teams": [{**candidate["teams"][0], "members": []}]}, valid=False)

    def test_invalidation_rejects_a_prepared_old_generation(self):
        candidate = self.cache.prepare(self.initial)
        self.cache.invalidate()
        self.cache.accept(candidate)
        self.assertIsNone(self.cache._accepted)
        fresh = self.cache.prepare(self.initial)
        self.assertIn("activity_admissions", fresh.checked_tables)

    def test_missing_source_is_rejected_after_a_valid_baseline(self):
        self.assert_equivalent({**self.initial, "agents": []}, valid=False)

    def test_out_of_order_preparation_cannot_replace_a_newer_baseline(self):
        first = self.cache.prepare(self.initial)
        second = self.cache.prepare(self.initial)
        self.cache.accept(second)
        self.cache.accept(first)
        self.assertIs(self.cache._accepted, second)

    def test_source_payloads_do_not_alias_the_callers_mutable_snapshot(self):
        candidate = {**self.initial, "agent_inboxes": {OWNER: [{"message_id": "mail", "agent_id": OWNER,
            "message_type": "note", "payload": {"nested": ["original"]}, "created_at": 1.0, "read_at": None}]}}
        prepared = self.cache.prepare(candidate)
        self.cache.accept(prepared)
        candidate["agent_inboxes"][OWNER][0]["payload"]["nested"].append("later")
        self.assertEqual(prepared.physical_sources["agent_inbox"][0]["payload"], {"nested": ["original"]})
        replacement = self.cache.prepare(candidate)
        self.assertEqual(replacement.checked_tables, {"agent_inbox"})
