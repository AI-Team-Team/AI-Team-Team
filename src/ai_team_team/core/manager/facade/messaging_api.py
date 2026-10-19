"""Host chat administration requires an explicit actor; tools cannot override one."""

from typing import Optional

from ...agent import Agent
from ...activity.contracts import ChatMessagePage, SourceDeliveryReceipt
from ...chat import ChatOperationResult, ChatReadResult, ChatRelationship, FriendshipRequestView, ChatReminderPage


class MessagingAPI:
    async def close_team_conversation(self, team_id: str):
        """Host archive finalization; this is not an AI dissolution decision tool."""
        return await self._messaging.close_team_conversation(team_id)

    def list_chat_reminders(self, *, actor: Agent, message_id: Optional[str] = None,
                            limit: int = 50, cursor: Optional[str] = None) -> ChatReminderPage:
        return self._messaging.list_chat_reminders(actor=actor, message_id=message_id, limit=limit, cursor=cursor)

    async def send_team_message(self, team_id: str, markdown: str, *, actor: Optional[Agent] = None,
                                operation_key: Optional[str] = None, reply_to: Optional[str] = None) -> SourceDeliveryReceipt:
        return await self._messaging.send_team_message(team_id, markdown, actor=actor, operation_key=operation_key, reply_to=reply_to)

    async def send_direct_message(self, agent_id: str, markdown: str, *, actor: Optional[Agent] = None,
                                  operation_key: Optional[str] = None, reply_to: Optional[str] = None) -> SourceDeliveryReceipt:
        return await self._messaging.send_direct_message(agent_id, markdown, actor=actor, operation_key=operation_key, reply_to=reply_to)

    def list_team_messages(self, team_id: str, *, actor: Agent, unread_only: bool = False, query: Optional[str] = None,
                           limit: int = 50, cursor: Optional[str] = None, include_deleted: bool = False) -> ChatMessagePage:
        return self._messaging.list_messages(team_id=team_id, actor=actor, unread_only=unread_only,
            query=query, limit=limit, cursor=cursor, include_deleted=include_deleted)

    def list_direct_messages(self, agent_id: str, *, actor: Agent, unread_only: bool = False, query: Optional[str] = None,
                             limit: int = 50, cursor: Optional[str] = None, include_deleted: bool = False) -> ChatMessagePage:
        return self._messaging.list_messages(other_agent_id=agent_id, actor=actor, unread_only=unread_only,
            query=query, limit=limit, cursor=cursor, include_deleted=include_deleted)

    async def read_chat_message(self, message_id: str, *, actor: Agent, version: Optional[int] = None,
                                start_line: int = 1, end_line: Optional[int] = None, start_character: int = 1,
                                character_count: Optional[int] = None, expected_file_version: Optional[str] = None) -> ChatReadResult:
        return await self._messaging.read_message(message_id, actor=actor, version=version, start_line=start_line,
            end_line=end_line, start_character=start_character, character_count=character_count, expected_file_version=expected_file_version)

    async def edit_chat_message(self, message_id: str, markdown: str, *, actor: Agent,
                                operation_key: Optional[str] = None) -> ChatOperationResult:
        return await self._messaging.change_message(message_id, markdown=markdown, actor=actor, operation_key=operation_key)

    async def withdraw_chat_message(self, message_id: str, *, actor: Agent, operation_key: Optional[str] = None) -> ChatOperationResult:
        return await self._messaging.change_message(message_id, withdraw=True, actor=actor, operation_key=operation_key)

    async def control_chat_message(self, command: str, message_id: str, *, actor: Agent,
                                   operation_key: Optional[str] = None) -> ChatOperationResult:
        return await self._messaging.personal_control(command, message_id, actor=actor, operation_key=operation_key)

    async def set_chat_details(self, *, actor: Agent, team_details: Optional[bool] = None,
                               direct_details: Optional[bool] = None, operation_key: Optional[str] = None) -> ChatOperationResult:
        return await self._messaging.set_chat_details(actor=actor, team_details=team_details,
            direct_details=direct_details, operation_key=operation_key)

    def inspect_direct_relationship(self, agent_id: str, *, actor: Agent) -> ChatRelationship:
        return self._messaging.inspect_relationship(agent_id, actor=actor)

    def list_friendship_requests(self, *, actor: Agent) -> tuple[FriendshipRequestView, ...]:
        return self._messaging.list_friendship_requests(actor=actor)

    async def request_friendship(self, agent_id: str, *, actor: Agent, operation_key: Optional[str] = None) -> ChatOperationResult:
        return await self._messaging.relationship_command("request_friendship", other_agent_id=agent_id, actor=actor, operation_key=operation_key)

    async def respond_friendship(self, request_id: str, decision: str, *, actor: Agent,
                                 operation_key: Optional[str] = None) -> ChatOperationResult:
        choices = {"accept": "accept_friendship", "reject": "reject_friendship", "ignore": "ignore_friendship", "cancel": "cancel_friendship_request"}
        if decision not in choices:
            raise ValueError("decision must be accept, reject, ignore, or cancel.")
        return await self._messaging.relationship_command(choices[decision], request_id=request_id, actor=actor, operation_key=operation_key)

    async def control_direct_relationship(self, agent_id: str, command: str, *, actor: Agent,
                                          operation_key: Optional[str] = None) -> ChatOperationResult:
        if command not in {"block_agent", "unblock_agent", "remove_friendship", "lift_direct_refusal"}:
            raise ValueError("Unknown direct relationship control.")
        return await self._messaging.relationship_command(command, other_agent_id=agent_id, actor=actor, operation_key=operation_key)
