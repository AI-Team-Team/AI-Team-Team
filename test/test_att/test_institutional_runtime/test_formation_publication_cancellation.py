"""An exact formation receipt separates withdrawal from a lost response."""

import asyncio
from unittest.mock import patch

from ai_team_team import StatePersistenceError, TeamFormationDraftCandidate
from test.test_att.test_agent_activity._support import ActivityTestCase, idle
from ._lock_support import ObservedLock


class FormationPublicationCancellationTests(ActivityTestCase):
    def candidate(self, *, automatic=False, task=None):
        import json
        return TeamFormationDraftCandidate.model_validate_json(json.dumps({
            "member_count": 3, "preset_name": "custom", "system_instructions": "Own design.",
            "team_purpose": "Optional personal proposal", "member_configs": {"NewA": {}, "NewB": {}},
            "is_public_visible": False, "initiator_joins": True,
            "unanimous_acceptance_action": "auto_create" if automatic else "require_confirmation",
            "late_join_policy": "disabled", "task": task}))

    async def prepare(self, **kwargs):
        return await self.manager.prepare_team_formation_draft(actor=self.root,
            objective="Publish only my explicitly accepted candidate.", candidate=self.candidate(**kwargs))

    async def assert_unaccepted_cancel_rolls_back(self, *, durable, boundary):
        if durable:
            self.manager = self.make_manager(self.root, durable=True)
        draft = await self.prepare()
        prior_mail = list(self.root.agent_inbox)
        owner = self.manager._activity if boundary == "activity" else self.manager
        attribute = "lock" if boundary == "activity" else "_runtime_gate"
        gate = ObservedLock(getattr(owner, attribute))
        # The public operation-accounting entry also uses the runtime gate.
        # Enter the finalizer directly when testing its later admission wait.
        async def publish():
            if boundary == "activity":
                return await self.manager.publish_team_formation_draft(draft.draft_id, actor=self.root)
            return await self.manager._formations.publish_team_formation_draft(draft.draft_id, actor=self.root)

        with patch.object(owner, attribute, gate):
            async with gate:
                pending = asyncio.create_task(publish())
                await gate.wait_for_attempt(pending)
                pending.cancel()
                if boundary == "activity":
                    with self.assertRaises(asyncio.CancelledError):
                        await pending
            if boundary != "activity":
                with self.assertRaises(asyncio.CancelledError):
                    await pending
        self.assertEqual(self.manager.get_team_formation_draft(draft.draft_id, actor=self.root).status.value, "ready")
        self.assertFalse(self.manager._formations.requests)
        self.assertFalse(self.manager._formations.revisions)
        self.assertFalse(self.manager._formations.invitations)
        self.assertEqual(self.root.agent_inbox, prior_mail)
        self.assertFalse(self.manager._inbox._staged_mail_ids)
        self.assertNotIn(f"FORMATION-PUBLISH-{draft.draft_id}", self.manager._records.receipts)
        if durable:
            await self.manager.save_state()
            state = await self.manager._persistence.read(self.manager.db_path)
            self.manager._validate_state_snapshot(state)
            self.assertFalse(state["formation_requests"])

    async def test_volatile_cancel_before_activity_lock_withdraws_only_its_publication(self):
        await self.assert_unaccepted_cancel_rolls_back(durable=False, boundary="activity")

    async def test_durable_cancel_before_activity_lock_withdraws_only_its_publication(self):
        await self.assert_unaccepted_cancel_rolls_back(durable=True, boundary="activity")

    async def test_cancel_before_runtime_gate_withdraws_the_unaccepted_request(self):
        await self.assert_unaccepted_cancel_rolls_back(durable=False, boundary="runtime")

    async def test_cancelled_publication_does_not_wait_again_to_release_operation_accounting(self):
        draft = await self.prepare()
        activity = ObservedLock(self.manager._activity.lock)
        with patch.object(self.manager._activity, "lock", activity):
            async with activity:
                pending = asyncio.create_task(self.manager.publish_team_formation_draft(draft.draft_id, actor=self.root))
                await activity.wait_for_attempt(pending)
                async with self.manager._runtime_gate:
                    pending.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await asyncio.wait_for(pending, 5)
                    self.assertEqual(self.manager._active_formation_operations, 0)
                    self.assertNotIn(pending, self.manager._formation_operation_tasks)
        self.assertFalse(self.manager._formations.requests)

    async def test_failed_automatic_creation_reports_on_the_restored_request(self):
        draft = await self.prepare(automatic=True)
        commit = self.manager._records.commit

        async def reject_creation(*args, **kwargs):
            if str(kwargs.get("operation_id", "")).startswith("FORMATION-CREATE-"):
                raise OSError("Injected creation rejection")
            return await commit(*args, **kwargs)

        with patch.object(self.manager._activity, "schedule_notice"), patch.object(self.manager._records, "commit", reject_creation):
            publication = await self.manager.publish_team_formation_draft(draft.draft_id, actor=self.root)
            while self.manager._formations.tasks:
                await asyncio.gather(*tuple(self.manager._formations.tasks))
                await asyncio.sleep(0)
        request = self.manager.get_team_formation(publication.request_id)
        self.assertIsNone(request.created_team_id)
        self.assertIn("Injected creation rejection", request.decision_reason)
        self.assertFalse(self.manager.teams)
        self.assertTrue(any(mail["message_type"] == "team_formation_auto_create_failed" for mail in self.root.agent_inbox))

    async def assert_accepted_publication_survives(self, *, durable, automatic=False):
        if durable:
            self.manager = self.make_manager(self.root, durable=True)
        draft = await self.prepare(automatic=automatic)
        original = self.manager._records.commit

        async def cancelled_response(*args, **kwargs):
            receipt = await original(*args, **kwargs)
            if kwargs.get("operation_id") == f"FORMATION-PUBLISH-{draft.draft_id}":
                raise asyncio.CancelledError
            return receipt

        with patch.object(self.manager._activity, "schedule_notice"), patch.object(self.manager._records, "commit", cancelled_response):
            with self.assertRaises(asyncio.CancelledError):
                await self.manager.publish_team_formation_draft(draft.draft_id, actor=self.root)
            while self.manager._formations.tasks:
                await asyncio.gather(*tuple(self.manager._formations.tasks))
                await asyncio.sleep(0)
        current = self.manager.get_team_formation_draft(draft.draft_id, actor=self.root)
        self.assertEqual(current.status.value, "published")
        self.assertEqual(len(self.manager._formations.requests), 1)
        self.assertFalse(self.manager._inbox._staged_mail_ids)
        if automatic:
            self.assertEqual(len(self.manager.teams), 1)
        if durable:
            await self.manager.save_state()
            self.manager._validate_state_snapshot(await self.manager._persistence.read(self.manager.db_path))

    async def test_volatile_published_receipt_survives_observer_cancellation(self):
        await self.assert_accepted_publication_survives(durable=False)

    async def test_durable_published_receipt_survives_observer_cancellation(self):
        await self.assert_accepted_publication_survives(durable=True)

    async def test_accepted_automatic_publication_keeps_its_creation_dispatch(self):
        await self.assert_accepted_publication_survives(durable=False, automatic=True)

    async def test_rejected_publication_is_ready_and_retryable(self):
        draft = await self.prepare()
        with patch.object(self.manager._records, "commit", side_effect=StatePersistenceError("Rejected publication")):
            with self.assertRaises(StatePersistenceError):
                await self.manager.publish_team_formation_draft(draft.draft_id, actor=self.root)
        self.assertFalse(self.manager._formations.requests)
        self.assertEqual(self.manager.get_team_formation_draft(draft.draft_id, actor=self.root).status.value, "ready")
        with patch.object(self.manager._activity, "schedule_notice"):
            result = await self.manager.publish_team_formation_draft(draft.draft_id, actor=self.root)
        self.assertEqual(result.status, "DRAFT_PUBLISHED")

    async def test_accepted_creation_keeps_initial_arrivals_after_losing_its_response(self):
        draft = await self.prepare(task="Initial addressed work is not a synchronous child discussion.")
        self.steps(idle(), idle(), idle())
        original = self.manager._records.commit
        with patch.object(self.manager._activity, "schedule_notice"):
            publication = await self.manager.publish_team_formation_draft(draft.draft_id, actor=self.root)

            async def cancelled_response(*args, **kwargs):
                receipt = await original(*args, **kwargs)
                if kwargs.get("operation_id") == f"FORMATION-CREATE-{publication.request_id}":
                    raise asyncio.CancelledError
                return receipt

            with patch.object(self.manager._records, "commit", cancelled_response):
                with self.assertRaises(asyncio.CancelledError):
                    await self.manager.create_team_from_formation(publication.request_id, actor=self.root, proposal_revision=1)
            while self.manager._formations.tasks:
                await asyncio.gather(*tuple(self.manager._formations.tasks))
                await asyncio.sleep(0)
            await self.settle()
        team = next(iter(self.manager.teams.values()))
        self.assertFalse(team._publication_pending)
        self.assertEqual({row.values["agent_id"] for row in self.records("activity_admissions")},
            {person.agent_id for person in team.members})
