"""Formation notifications delivered through the shared personal inbox service."""


class FormationNotificationMixin:
    def _notify_agent(self, agent_id, message_type, payload):
        return self.manager._inbox.notify(agent_id, message_type, payload)

    def list_agent_inbox(self, agent_id, *, unread_only=True):
        return self.manager._inbox.list(agent_id, unread_only=unread_only)

    async def mark_agent_inbox_read(self, agent_id, message_ids=None):
        return await self.manager._inbox.mark_read(agent_id, message_ids)

    def render_agent_inbox(self, agent_id, *, limit=20):
        return self.manager._inbox.render(agent_id, limit=limit)
