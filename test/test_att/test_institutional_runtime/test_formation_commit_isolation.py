"""Formation candidates cannot escape through other commits or rollback mail."""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

from ai_team_team import Agent, TeamFormationDraftCandidate, TeamFormationRevisionPatch
from test.test_att.test_agent_activity._support import ActivityTestCase
from ._lock_support import ObservedLock


class FormationCommitIsolationTests(ActivityTestCase):
    def candidate(self):
        return TeamFormationDraftCandidate.model_validate_json(json.dumps({
            "member_count": 3, "preset_name": "custom", "system_instructions": "Own design.",
            "team_purpose": "Independent proposal", "member_configs": {"NewA": {}, "NewB": {}},
            "is_public_visible": False, "initiator_joins": True,
            "unanimous_acceptance_action": "require_confirmation", "late_join_policy": "disabled"}))

    def proposal(self, *, purpose="Original proposal", invitee=None):
        return self.manager.propose_team_formation(creator=self.root, initiating_agent=self.root,
            initiator_joins=True, existing_members=[invitee] if invitee else None,
            member_configs={"NewA": {}} if invitee else {"NewA": {}, "NewB": {}},
            team_purpose=purpose, initial_docs={"draft.txt": "Unaccepted team file."})

    async def test_full_save_cannot_accept_another_tasks_unpublished_draft(self):
        self.manager = self.make_manager(self.root, durable=True)
        draft = await self.manager.prepare_team_formation_draft(actor=self.root,
            objective="Do not persist a publication without its receipt.", candidate=self.candidate())
        await self.manager.flush_state()
        activity = ObservedLock(self.manager._activity.lock)
        with patch.object(self.manager._activity, "schedule_notice"), patch.object(self.manager._activity, "lock", activity):
            async with self.manager._records.lock:
                async with activity:
                    saved = asyncio.create_task(self.manager.save_state())
                    await activity.wait_for_attempt(saved)
                    publication = asyncio.create_task(self.manager.publish_team_formation_draft(draft.draft_id, actor=self.root))
                    await activity.wait_for_attempt(publication)
                    self.assertEqual(self.manager.get_team_formation_draft(draft.draft_id, actor=self.root).status.value, "ready")
                    self.assertFalse(self.manager._formations.requests)
                try:
                    await asyncio.wait_for(asyncio.shield(saved), 10)
                finally:
                    publication.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await publication
            state = await self.manager._persistence.read(self.manager.db_path)
            self.manager._validate_state_snapshot(state)
            self.assertFalse(state["formation_requests"])
            self.assertEqual(state["formation_drafts"][0]["status"], "ready")
            await self.manager.load_state(self.manager.db_path)
        self.assertFalse(self.manager._formations.requests)
        self.assertFalse(self.manager._inbox._staged_mail_ids)
        self.assertNotIn(f"FORMATION-PUBLISH-{draft.draft_id}", self.manager._records.receipts)

    async def test_full_save_and_restore_never_resurrect_an_unaccepted_team(self):
        self.manager = self.make_manager(self.root, durable=True)
        request = self.proposal()
        await self.manager.flush_state()
        activity = ObservedLock(self.manager._activity.lock)
        with patch.object(self.manager._activity, "schedule_notice"), patch.object(self.manager._activity, "lock", activity):
            async with self.manager._records.lock:
                async with activity:
                    saved = asyncio.create_task(self.manager.save_state())
                    await activity.wait_for_attempt(saved)
                    creation = asyncio.create_task(self.manager.create_team_from_formation(
                        request.request_id, actor=self.root, proposal_revision=1))
                    await activity.wait_for_attempt(creation)
                    team = next(iter(self.manager.teams.values()))
                    directory = Path(team.doc_library.root_dir)
                    self.assertIsNone(self.manager.get_team_formation(request.request_id).created_team_id)
                try:
                    await asyncio.wait_for(asyncio.shield(saved), 10)
                    self.assertFalse(any(row.values.get("team_id") == team.team_id for row in self.manager._records.snapshot()))
                finally:
                    creation.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await creation
            state = await self.manager._persistence.read(self.manager.db_path)
            self.manager._validate_state_snapshot(state)
            self.assertFalse(state["teams"])
            self.assertEqual(len(state["agents"]), 1)
            self.assertEqual(len(state["libraries"]), 1)
            self.assertIsNone(state["formation_requests"][0]["created_team_id"])
            await self.manager.load_state(self.manager.db_path)
        self.assertFalse(self.manager.teams)
        self.assertFalse(directory.exists())
        self.assertNotIn(f"FORMATION-CREATE-{request.request_id}", self.manager._records.receipts)

    async def test_full_save_cannot_advance_another_tasks_unaccepted_revision(self):
        self.manager = self.make_manager(self.root, durable=True)
        request = self.proposal()
        await self.manager.flush_state()
        activity = ObservedLock(self.manager._activity.lock)
        with patch.object(self.manager._activity, "schedule_notice"), patch.object(self.manager._activity, "lock", activity):
            async with self.manager._records.lock:
                async with activity:
                    saved = asyncio.create_task(self.manager.save_state())
                    await activity.wait_for_attempt(saved)
                    revision = asyncio.create_task(self.manager.revise_team_formation(request.request_id,
                        actor=self.root, base_revision=1, changes=TeamFormationRevisionPatch(team_purpose="Unaccepted successor")))
                    await activity.wait_for_attempt(revision)
                try:
                    await asyncio.wait_for(asyncio.shield(saved), 10)
                finally:
                    revision.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await revision
        state = await self.manager._persistence.read(self.manager.db_path)
        self.manager._validate_state_snapshot(state)
        self.assertEqual(state["formation_requests"][0]["proposal_revision"], 1)
        self.assertEqual(len(state["formation_revisions"]), 1)
        self.assertEqual(self.manager.get_team_formation(request.request_id), request)

    async def assert_cancelled_transition(self, *, durable, action):
        if durable:
            self.manager = self.make_manager(self.root, durable=True)
        invitee = self.manager.register_agent(Agent("Invitee", "Researcher", self.client))
        request = self.proposal(invitee=invitee)
        await self.manager.flush_state()
        old_mail = [dict(row) for row in self.root.agent_inbox]
        activity = ObservedLock(self.manager._activity.lock)
        async def transition():
            if action == "revision":
                return await self.manager.revise_team_formation(request.request_id, actor=self.root,
                    base_revision=1, changes=TeamFormationRevisionPatch(team_purpose="Unaccepted revision"))
            if action == "abandon":
                return await self.manager.abandon_team_formation(request.request_id, actor=self.root,
                    proposal_revision=1, reason="Unaccepted abandonment")
            return await self.manager.respond_team_invitation(request.request_id, actor=invitee,
                proposal_revision=1, attitude="accepted")
        with patch.object(self.manager._activity, "schedule_notice"), patch.object(self.manager._activity, "lock", activity):
            async with activity:
                pending = asyncio.create_task(transition())
                await activity.wait_for_attempt(pending)
                self.assertEqual(self.manager.get_team_formation(request.request_id), request)
                pending.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await pending
        self.assertEqual(self.manager.get_team_formation(request.request_id), request)
        self.assertEqual(self.root.agent_inbox, old_mail)
        self.assertFalse(self.manager.list_team_formation_decisions(request.request_id))
        self.assertEqual(len(self.manager.list_team_formation_revisions(request.request_id)), 1)
        self.assertFalse(self.manager._inbox._staged_mail_ids)
        if durable:
            state = await self.manager._persistence.read(self.manager.db_path)
            self.manager._validate_state_snapshot(state)
            self.assertEqual(state["formation_requests"][0]["proposal_revision"], 1)
            self.assertEqual(state["formation_requests"][0]["status"], request.status.value)
            self.assertFalse(state["formation_decisions"])

    async def test_volatile_revision_cancel_keeps_the_accepted_revision(self):
        await self.assert_cancelled_transition(durable=False, action="revision")

    async def test_durable_revision_cancel_keeps_the_accepted_revision(self):
        await self.assert_cancelled_transition(durable=True, action="revision")

    async def test_volatile_abandon_cancel_keeps_the_open_proposal(self):
        await self.assert_cancelled_transition(durable=False, action="abandon")

    async def test_durable_abandon_cancel_keeps_the_open_proposal(self):
        await self.assert_cancelled_transition(durable=True, action="abandon")

    async def test_volatile_response_cancel_keeps_the_previous_attitude(self):
        await self.assert_cancelled_transition(durable=False, action="response")

    async def test_durable_response_cancel_keeps_the_previous_attitude(self):
        await self.assert_cancelled_transition(durable=True, action="response")

    async def test_revision_rejection_preserves_independently_accepted_mail_and_notice(self):
        invitee = self.manager.register_agent(Agent("Invitee", "Researcher", self.client))
        request = self.proposal(invitee=invitee)
        commit = self.manager._records.commit
        async def reject_revision(*args, **kwargs):
            if request.request_id in (kwargs.get("dirty") or {}).get("formation_revisions", ()):
                raise OSError("Rejected revision")
            return await commit(*args, **kwargs)
        activity = ObservedLock(self.manager._activity.lock)
        with patch.object(self.manager._activity, "schedule_notice"), patch.object(self.manager._activity, "lock", activity), \
                patch.object(self.manager._records, "commit", reject_revision):
            async with activity:
                delivery = asyncio.create_task(self.manager._activity.deliver_mail(self.root.agent_id,
                    message_type="personal_instruction", payload={"text": "Independent accepted instruction."}, schedule=False))
                await activity.wait_for_attempt(delivery)
                revision = asyncio.create_task(self.manager.revise_team_formation(request.request_id,
                    actor=self.root, base_revision=1, changes=TeamFormationRevisionPatch(team_purpose="Rejected revision")))
                await activity.wait_for_attempt(revision)
            accepted = await delivery
            with self.assertRaisesRegex(OSError, "Rejected revision"):
                await revision
        self.assertTrue(any(mail["message_id"] == accepted.message_id for mail in self.root.agent_inbox))
        self.assertIn(("agent_notifications", (f"NOTICE-{accepted.message_id}",)), self.manager._records.index)
        self.assertEqual(self.manager.get_team_formation(request.request_id), request)
        self.assertFalse(any(mail["message_type"] == "team_formation_revised" for mail in self.root.agent_inbox))

    async def test_concurrent_distinct_proposal_revisions_publish_only_their_own_patch(self):
        first = self.proposal(purpose="First original")
        second = self.proposal(purpose="Second original")
        with patch.object(self.manager._activity, "schedule_notice"):
            await asyncio.gather(*(self.manager.revise_team_formation(request.request_id,
                actor=self.root, base_revision=1, changes=TeamFormationRevisionPatch(team_purpose=purpose))
                for request, purpose in ((first, "First successor"), (second, "Second successor"))))
        self.assertEqual(self.manager.get_team_formation(first.request_id).team_purpose, "First successor")
        self.assertEqual(self.manager.get_team_formation(second.request_id).team_purpose, "Second successor")
        self.assertEqual(len(self.manager.list_team_formation_revisions(first.request_id)), 2)
        self.assertEqual(len(self.manager.list_team_formation_revisions(second.request_id)), 2)

    async def test_a_proposal_added_during_another_candidates_wait_is_not_replaced(self):
        first = self.proposal(purpose="First original")
        activity = ObservedLock(self.manager._activity.lock)
        with patch.object(self.manager._activity, "schedule_notice"), patch.object(self.manager._activity, "lock", activity):
            async with activity:
                revision = asyncio.create_task(self.manager.revise_team_formation(first.request_id,
                    actor=self.root, base_revision=1, changes=TeamFormationRevisionPatch(team_purpose="First successor")))
                await activity.wait_for_attempt(revision)
                second = self.proposal(purpose="Created while another candidate waits")
            await revision
        self.assertEqual(self.manager.get_team_formation(second.request_id), second)
        self.assertEqual(self.manager.get_team_formation(first.request_id).proposal_revision, 2)

    async def test_accepted_revision_survives_its_observers_lost_response(self):
        self.manager = self.make_manager(self.root, durable=True)
        request = self.proposal()
        commit = self.manager._records.commit
        async def lose_response(*args, **kwargs):
            receipt = await commit(*args, **kwargs)
            if str(kwargs.get("operation_id", "")).startswith("FORMATION-REVISE-"):
                raise asyncio.CancelledError
            return receipt
        with patch.object(self.manager._activity, "schedule_notice"), patch.object(self.manager._records, "commit", lose_response):
            with self.assertRaises(asyncio.CancelledError):
                await self.manager.revise_team_formation(request.request_id, actor=self.root, base_revision=1,
                    changes=TeamFormationRevisionPatch(team_purpose="Accepted successor"))
        self.assertEqual(self.manager.get_team_formation(request.request_id).proposal_revision, 2)
        self.assertFalse(self.manager._inbox._staged_mail_ids)
        state = await self.manager._persistence.read(self.manager.db_path)
        self.manager._validate_state_snapshot(state)
        self.assertEqual(state["formation_requests"][0]["team_purpose"], "Accepted successor")

    async def test_accepted_revision_keeps_automatic_creation_after_a_lost_response(self):
        from ai_team_team.core.formation import UnanimousAcceptanceAction

        request = self.proposal()
        commit = self.manager._records.commit
        async def lose_response(*args, **kwargs):
            receipt = await commit(*args, **kwargs)
            if str(kwargs.get("operation_id", "")).startswith("FORMATION-REVISE-"):
                raise asyncio.CancelledError
            return receipt
        with patch.object(self.manager._activity, "schedule_notice"), patch.object(self.manager._records, "commit", lose_response):
            with self.assertRaises(asyncio.CancelledError):
                await self.manager.revise_team_formation(request.request_id, actor=self.root, base_revision=1,
                    changes=TeamFormationRevisionPatch(unanimous_acceptance_action=UnanimousAcceptanceAction.AUTO_CREATE))
            while self.manager._formations.tasks:
                await asyncio.gather(*tuple(self.manager._formations.tasks))
        accepted = self.manager.get_team_formation(request.request_id)
        self.assertEqual(accepted.status.value, "created")
        self.assertIn(accepted.created_team_id, self.manager.teams)
        self.assertFalse(self.manager._inbox._staged_mail_ids)

    async def test_post_commit_identity_journal_is_not_left_in_the_candidate_batch(self):
        self.manager = self.make_manager(self.root, durable=True)
        request = self.proposal()
        with patch.object(self.manager._activity, "schedule_notice"):
            created = await self.manager.create_team_from_formation(request.request_id, actor=self.root, proposal_revision=1)
            await self.manager.flush_state()
        team = self.manager.teams[created.team_id]
        state = await self.manager._persistence.read(self.manager.db_path)
        self.manager._validate_state_snapshot(state)
        registered = {event["agent_id"] for event in state["memory_events"] if event["event_type"] == "agent_registered"}
        self.assertTrue({agent.agent_id for agent in team.members if agent is not self.root}.issubset(registered))

    async def test_waiting_draft_refreshes_its_base_after_another_revision_wins(self):
        request = self.proposal()
        draft = await self.manager.prepare_team_formation_draft(actor=self.root,
            objective="A candidate for the original exact revision.", candidate=self.candidate(), request_id=request.request_id)
        request_lock = ObservedLock(self.manager._formations._request_locks.setdefault(request.request_id, asyncio.Lock()))
        self.manager._formations._request_locks[request.request_id] = request_lock
        with patch.object(self.manager._activity, "schedule_notice"):
            async with request_lock:
                revision = asyncio.create_task(self.manager.revise_team_formation(request.request_id, actor=self.root,
                    base_revision=1, changes=TeamFormationRevisionPatch(team_purpose="Accepted successor")))
                await request_lock.wait_for_attempt(revision)
                publication = asyncio.create_task(self.manager.publish_team_formation_draft(draft.draft_id, actor=self.root))
                await request_lock.wait_for_attempt(publication)
            await revision
            result = await publication
        self.assertEqual(result.status, "STALE_REVISION")
        self.assertEqual(self.manager.get_team_formation(request.request_id).team_purpose, "Accepted successor")
        self.assertEqual(self.manager.get_team_formation_draft(draft.draft_id, actor=self.root).status.value, "stale")
        self.assertEqual(len(self.manager.list_team_formation_revisions(request.request_id)), 2)
