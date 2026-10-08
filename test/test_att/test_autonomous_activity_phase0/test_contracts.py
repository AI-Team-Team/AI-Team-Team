"""Executable validation of the frozen value contracts, not runtime acceptance."""

import json
import unittest

from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError

from ai_team_team.core.activity.contracts import (
    ActivityIntent,
    ActivityView,
    AgentTeamScope,
    CountdownBounds,
    ExecutionObservation,
    InvocationScope,
    NotificationReference,
    NotificationSource,
    OperationScope,
    PersonalScope,
    PresentationClaim,
    SleepIntent,
    SuppressionPreference,
    TARGET_STATE_SCHEMA_VERSION,
    ToolExecutionContract,
    WakeDuration,
)


class TestScopeAndIntentContracts(unittest.IsolatedAsyncioTestCase):
    def test_scope_is_strict_and_immutable_without_actor_override(self):
        adapter = TypeAdapter(OperationScope)
        scope = adapter.validate_python({"kind": "agent_team", "team_id": "AT-A"})
        captured = InvocationScope(
            agent_id="person-A", invocation_id="invocation-A", runtime_generation=1, scope=scope
        )
        with self.assertRaises(ValidationError):
            captured.scope = PersonalScope()
        for invalid in (
            {"kind": "agent_team", "team_id": ""},
            {"kind": "personal", "team_id": "AT-A"},
            {"kind": "agent_team", "team_id": 1},
            {"kind": "agent_team", "team_id": "AT-A", "sender_agent_id": "person-B"},
            {"kind": "root_agent"},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                adapter.validate_python(invalid)
        restored = InvocationScope.model_validate_json(captured.model_dump_json())
        self.assertEqual(restored, captured)

    def test_only_explicit_idle_or_sleep_are_controls(self):
        adapter = TypeAdapter(ActivityIntent)
        self.assertEqual(adapter.validate_python({"kind": "idle"}).kind, "idle")
        for kind in ("continuing", "completed", "silent", "dead"):
            with self.subTest(kind=kind), self.assertRaises(ValidationError):
                adapter.validate_python({"kind": kind})
        with self.assertRaises(ValidationError):
            adapter.validate_python({"kind": "sleep", "early_conditions": ()})

    def test_duration_units_are_strict_and_total_bounds_are_host_owned(self):
        duration = WakeDuration(days=1, hours=2, minutes=3)
        self.assertEqual(duration.total_seconds, 93780)
        CountdownBounds().check(duration)
        for invalid in (
            {},
            {"minutes": 0},
            {"minutes": -1},
            {"hours": True},
            {"minutes": "5"},
            {"minutes": 1.5},
            {"seconds": 300},
            {"days": None},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                WakeDuration.model_validate(invalid)
        for invalid in (WakeDuration(minutes=4), WakeDuration(days=2, minutes=1)):
            with self.assertRaises(ValueError):
                CountdownBounds().check(invalid)
        CountdownBounds(minimum_minutes=1, maximum_minutes=3).check(WakeDuration(minutes=2))
        self.assertEqual(WakeDuration.model_validate_json(duration.model_dump_json()), duration)
        self.assertEqual(WakeDuration(minutes=5).model_dump(), {"minutes": 5})
        with self.assertRaises(ValidationError):
            CountdownBounds(minimum_minutes=10, maximum_minutes=5)

    def test_sleep_and_suppression_share_bounds_without_forcing_permanent_expiry(self):
        bounds = CountdownBounds()
        sleep = SleepIntent(countdown=WakeDuration(minutes=5))
        sleep.check_bounds(bounds)
        permanent = SuppressionPreference(scope="all")
        permanent.check_bounds(bounds)
        self.assertIsNone(permanent.countdown)
        timed = SuppressionPreference(
            scope="agent_team", source_id="AT-A", countdown=WakeDuration(minutes=5)
        )
        timed.check_bounds(bounds)
        with self.assertRaises(ValueError):
            SuppressionPreference(scope="all", countdown=WakeDuration(minutes=4)).check_bounds(
                bounds
            )
        for invalid in (
            {"scope": "all", "source_id": "AT-A"},
            {"scope": "agent_team"},
            {"scope": "all", "suppress_protected": True},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                SuppressionPreference.model_validate(invalid)

    def test_duration_wire_schemas_match_positive_omittable_units(self):
        for mode in ("validation", "serialization"):
            schema = WakeDuration.model_json_schema(mode=mode)
            Draft202012Validator.check_schema(schema)
            validator = Draft202012Validator(schema)
            for valid in ({"minutes": 5}, {"days": 1, "hours": 2, "minutes": 3}):
                with self.subTest(mode=mode, valid=valid):
                    self.assertTrue(validator.is_valid(valid))
                    self.assertEqual(
                        WakeDuration.model_validate(valid).model_dump(mode="json"), valid
                    )
            for invalid in (
                {},
                {"days": None},
                {"minutes": 0},
                {"hours": True},
                {"minutes": "5"},
                {"minutes": 1.5},
                {"seconds": 300},
            ):
                with self.subTest(mode=mode, invalid=invalid):
                    self.assertFalse(validator.is_valid(invalid))
                    with self.assertRaises(ValidationError):
                        WakeDuration.model_validate(invalid)
            sleep = SleepIntent(countdown=WakeDuration(minutes=5))
            nested = Draft202012Validator(SleepIntent.model_json_schema(mode=mode))
            payload = sleep.model_dump(mode="json")
            self.assertTrue(nested.is_valid(payload))
            for invalid in ({}, {"days": None}, {"seconds": 300}):
                with self.subTest(mode=mode, nested=invalid):
                    self.assertFalse(nested.is_valid({**payload, "countdown": invalid}))

    def test_activity_inspection_exposes_one_immutable_captured_scope(self):
        scope = AgentTeamScope(team_id="AT-A")
        view = ActivityView(
            agent_id="person-A",
            admission_id="admission-A",
            scope=scope,
            intent="continuing",
            availability="waiting_model",
        )
        self.assertEqual(view.scope, scope)
        with self.assertRaises(ValidationError):
            view.scope = AgentTeamScope(team_id="AT-B")
        self.assertEqual(ActivityView.model_validate_json(view.model_dump_json()), view)


class TestNotificationAndExecutionContracts(unittest.IsolatedAsyncioTestCase):
    def test_delivery_and_presentation_cannot_supply_read_or_vote_facts(self):
        source = NotificationSource(kind="personal_mail", source_id="mail-A")
        notice = NotificationReference(
            notification_id="notice-A",
            recipient_agent_id="person-A",
            source=source,
            classification="ordinary",
            arrival_generation=1,
            deduplication_key="mail-A:arrival",
        )
        claim = PresentationClaim(
            notification_id=notice.notification_id,
            frame_id="frame-A",
            model_request_id="request-A",
            state="uncertain",
        )
        self.assertEqual(claim.state, "uncertain")
        for additional in ({"read_at": 1.0}, {"approved": True}, {"message_body": "PRIVATE"}):
            with self.subTest(additional=additional), self.assertRaises(ValidationError):
                NotificationReference.model_validate({**notice.model_dump(), **additional})
        self.assertNotIn("PRIVATE", notice.model_dump_json())
        self.assertEqual(
            NotificationReference.model_validate_json(notice.model_dump_json()), notice
        )

    def test_background_is_explicit_and_self_mutation_is_rejected(self):
        base = {"effects": ("read_only",), "required_scope": "either"}
        with self.assertRaises(ValidationError):
            ToolExecutionContract.model_validate(base)
        with self.assertRaises(ValidationError):
            ToolExecutionContract.model_validate({**base, "background_allowed": "true"})
        for effect in ("self_modification", "undeclared"):
            with self.subTest(effect=effect), self.assertRaises(ValidationError):
                ToolExecutionContract(
                    effects=(effect,), required_scope="personal", background_allowed=True
                )
        ToolExecutionContract(
            effects=("artifact_write",),
            required_scope="personal",
            background_allowed=True,
            mutation_safety="managed_lease",
        )
        with self.assertRaises(ValidationError):
            ToolExecutionContract(
                effects=("artifact_write",), required_scope="personal", background_allowed=True
            )
        with self.assertRaises(ValidationError):
            ToolExecutionContract.model_validate(
                {**base, "background_allowed": True, "retry_safe": True}
            )

    def test_execution_health_attention_and_uncertainty_are_independent(self):
        base = dict(
            execution_id="execution-A",
            owner_agent_id="person-A",
            scope=AgentTeamScope(team_id="AT-A"),
            runtime_generation=1,
        )
        for state, health, attention in (
            ("failed", "error", "acknowledged"),
            ("running", "stalled", "required"),
            ("completed", "healthy", "required"),
        ):
            record = ExecutionObservation(
                **base, execution_state=state, health_state=health, attention_state=attention
            )
            self.assertEqual(record.execution_state, state)
        uncertain = ExecutionObservation(
            **base,
            execution_state="running",
            health_state="unknown",
            attention_state="required",
            outcome_unconfirmed=True,
            cancellation_requested=True,
        )
        self.assertEqual(uncertain.execution_state, "running")
        with self.assertRaises(ValidationError):
            ExecutionObservation.model_validate(
                {**uncertain.model_dump(), "execution_state": "interrupted"}
            )
        with self.assertRaises(ValidationError):
            ExecutionObservation.model_validate(
                {**uncertain.model_dump(), "execution_state": "completed"}
            )

    def test_schema_target_is_reserved_without_live_objects_or_round_fields(self):
        self.assertEqual(TARGET_STATE_SCHEMA_VERSION, "12")
        schemas = [
            InvocationScope,
            SleepIntent,
            NotificationReference,
            PresentationClaim,
            ToolExecutionContract,
            ExecutionObservation,
        ]
        for model in schemas:
            encoded = json.dumps(model.model_json_schema())
            for forbidden in ("round_number", "discussion_id", "sender_team_id", "llm_client"):
                self.assertNotIn(forbidden, encoded)
