"""A local membership proposal never mutates registered people or live proposals."""

import asyncio
import copy

from ai_team_team.database.persistence.receipts import settle_commit


class MembershipChange:
    def __init__(self, manager, team):
        self.manager = manager
        self.members = list(team.members)
        self.proposals = copy.deepcopy(team.proposals)
        self.registrations = {}

    def register_agent(self, agent):
        reservation = self.manager._agent_registry.reserve(agent)
        self.registrations[agent.agent_id] = reservation

    async def prepare(self):
        def prepare_all():
            for registration in self.registrations.values():
                registration.prepare()
        await settle_commit(asyncio.create_task(asyncio.to_thread(prepare_all)))

    async def release(self):
        if not self.registrations:
            return

        def release_all():
            errors = []
            for registration in self.registrations.values():
                try:
                    registration.release()
                except Exception as error:
                    errors.append(error)
            if errors:
                raise errors[0]
        # One accepted cleanup owns every reservation, even if this observer
        # receives cancellation repeatedly while a filesystem worker is busy.
        await settle_commit(asyncio.create_task(asyncio.to_thread(release_all)))
