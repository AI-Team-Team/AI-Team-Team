"""Pair-owned controls, historical consent, and atomic directional allowances."""

from ai_team_team.core.chat import ChatRelationship, FriendshipRequestView
from ai_team_team.core.exceptions import ToolBusinessError
from ai_team_team.database.persistence.records import thaw
from ..activity.values import capture
from .base import identity, inspected


class RelationshipMixin:
    def find_pair(self, left, right):
        pair = tuple(sorted((left, right)))
        return next((row for row in self.rows("direct_relationships")
                     if (row.values["agent_a_id"], row.values["agent_b_id"]) == pair), None)

    def pair(self, actor, other_agent_id, *, require_active=True):
        if actor.agent_id == other_agent_id:
            raise ToolBusinessError("Direct contact requires another Agent identity.")
        if require_active:
            self.manager._activity.require_agent(other_agent_id)
        relation = self.find_pair(actor.agent_id, other_agent_id)
        if relation is not None:
            return relation
        self.manager._activity.require_agent(other_agent_id)
        left, right = sorted((actor.agent_id, other_agent_id))
        return capture(self.manager, "direct_relationships", relationship_id=identity("PAIR"),
            agent_a_id=left, agent_b_id=right, friendship=0, blocked_a=0, blocked_b=0,
            refused_a=0, refused_b=0, generation=1, allowance_a=3, allowance_b=3)

    @staticmethod
    def side(relation, owner):
        return "a" if relation.values["agent_a_id"] == owner else "b"

    def check_delivery(self, relation, sender, *, consume=False):
        values = relation.values
        side = self.side(relation, sender.agent_id)
        other = "b" if side == "a" else "a"
        if values["blocked_a"] or values["blocked_b"] or values[f"refused_{other}"]:
            raise ToolBusinessError("The current relationship does not permit this delivery.")
        if not values["friendship"] and values[f"allowance_{side}"] <= 0:
            raise ToolBusinessError("The three-message stranger allowance is exhausted.")
        if consume and not values["friendship"]:
            return capture(self.manager, "direct_relationships", **{**thaw(values),
                           f"allowance_{side}": values[f"allowance_{side}"] - 1})
        return relation

    async def send_direct_message(self, other_agent_id, markdown, *, actor=None, operation_key=None, reply_to=None):
        from .markdown import extract
        actor = self.actor(actor)
        extract(markdown, self.manager.config.conversations)
        operation = self.operation(actor, "send_direct", [other_agent_id, markdown, reply_to], operation_key)
        self.manager._activity.require_agent(other_agent_id)
        async with self.contact_lock(actor.agent_id, other_agent_id), self.manager._activity.lock:
            self.manager._activity.check_open()
            actor = self.actor(actor)
            previous = await self.replay(actor, "send_direct", operation)
            if previous is not None:
                return previous
            relation = self.pair(actor, other_agent_id)
            admitted = self.check_delivery(relation, actor, consume=True)
            stream = next((row for row in self.rows("chat_streams") if row.values["relationship_id"] == relation.values["relationship_id"]), None)
            if stream is None:
                stream = capture(self.manager, "chat_streams", stream_id=identity("CS"),
                                 relationship_id=relation.values["relationship_id"], next_position=1)
            # A first publication updates the not-yet-published stream cursor.
            records, result, notices = self.publication(actor, stream, markdown, operation[0],
                [actor.agent_id, other_agent_id], reply_to=reply_to)
            return await self.finish(actor, "send_direct", operation, [admitted, *records], result, notifications=notices)

    @inspected
    def inspect_relationship(self, other_agent_id, *, actor=None):
        actor = self.actor(actor)
        relation = self.find_pair(actor.agent_id, other_agent_id)
        if relation is None:
            if other_agent_id == actor.agent_id:
                raise ToolBusinessError("Direct contact requires another Agent identity.")
            self.manager._activity.require_agent(other_agent_id)
            return ChatRelationship(relationship_id="unestablished", other_agent_id=other_agent_id, generation=1,
                friendship=False, blocked_by_self=False, blocked_by_other=False,
                refusal_by_self=False, refusal_by_other=False, remaining_messages=3)
        side = self.side(relation, actor.agent_id)
        other = "b" if side == "a" else "a"
        values = relation.values
        return ChatRelationship(relationship_id=values["relationship_id"], other_agent_id=other_agent_id,
            generation=values["generation"], friendship=bool(values["friendship"]),
            blocked_by_self=bool(values[f"blocked_{side}"]), blocked_by_other=bool(values[f"blocked_{other}"]),
            refusal_by_self=bool(values[f"refused_{side}"]), refusal_by_other=bool(values[f"refused_{other}"]),
            remaining_messages=values[f"allowance_{side}"])

    @inspected
    def list_friendship_requests(self, *, actor=None):
        actor = self.actor(actor)
        return tuple(FriendshipRequestView.model_validate({key: thaw(row.values[key]) for key in FriendshipRequestView.model_fields})
            for row in self.rows("friendship_requests")
            if actor.agent_id in {row.values["sender_agent_id"], row.values["recipient_agent_id"]})

    async def relationship_command(self, command, *, other_agent_id=None, request_id=None, actor=None, operation_key=None):
        actor = self.actor(actor)
        operation = self.operation(actor, command, [other_agent_id, request_id], operation_key)
        request = self.manager._records.index.get(("friendship_requests", (request_id,))) if request_id else None
        if request_id:
            if request is None or actor.agent_id not in {request.values["sender_agent_id"], request.values["recipient_agent_id"]}:
                raise PermissionError("The friendship request is not addressed to this actor.")
            other_agent_id = next(owner for owner in (request.values["sender_agent_id"], request.values["recipient_agent_id"]) if owner != actor.agent_id)
        async with self.contact_lock(actor.agent_id, other_agent_id), self.manager._activity.lock:
            self.manager._activity.check_open()
            actor = self.actor(actor)
            replay = await self.replay(actor, command, operation)
            if replay is not None:
                return replay
            relation = self.pair(actor, other_agent_id, require_active=command in {"request_friendship", "accept_friendship"})
            values = thaw(relation.values)
            side = self.side(relation, actor.agent_id)
            other = "b" if side == "a" else "a"
            records, dirty, notices, mail_ids, mail_specs = [relation], None, (), [], []
            result = {"status": "UNCHANGED", "relationship_id": values["relationship_id"], "generation": values["generation"]}
            if command == "request_friendship":
                if values["blocked_a"] or values["blocked_b"] or values[f"refused_{other}"]:
                    raise ToolBusinessError("The recipient's relationship controls do not permit an invitation.")
                pending = next((row for row in self.rows("friendship_requests") if row.values["relationship_id"] == values["relationship_id"]
                    and row.values["generation"] == values["generation"] and row.values["status"] == "pending"
                    and row.values["sender_agent_id"] == actor.agent_id), None)
                if values["friendship"]:
                    result["status"] = "ALREADY_FRIENDS"
                elif pending is not None:
                    result.update(status="PENDING", request_id=pending.values["request_id"])
                else:
                    request = capture(self.manager, "friendship_requests", request_id=identity("FRIEND"),
                        relationship_id=values["relationship_id"], sender_agent_id=actor.agent_id,
                        recipient_agent_id=other_agent_id, generation=values["generation"], status="pending",
                        created_at=self.clock.wall_time())
                    records.append(request)
                    result.update(status="PENDING", request_id=request.values["request_id"])
                    mail_specs.append((other_agent_id, "friendship_request", {
                        "request_id": request.values["request_id"], "sender_agent_id": actor.agent_id,
                        "relationship_id": values["relationship_id"], "generation": values["generation"]}))
            elif command in {"accept_friendship", "reject_friendship", "ignore_friendship", "cancel_friendship_request"}:
                if request is None:
                    raise PermissionError("A concrete friendship request is required.")
                expected = request.values["sender_agent_id"] if command == "cancel_friendship_request" else request.values["recipient_agent_id"]
                if actor.agent_id != expected:
                    raise PermissionError("Only the addressed request endpoint may perform this response.")
                request = self.manager._records.index[request.identity]
                if request.values["generation"] != values["generation"]:
                    result.update(status="STALE_REQUEST", request_id=request.values["request_id"])
                elif request.values["status"] != "pending":
                    result.update(status="ALREADY_RESOLVED", request_id=request.values["request_id"])
                else:
                    if values["blocked_a"] or values["blocked_b"]:
                        raise ToolBusinessError("An effective block prevents this relationship response.")
                    state = {"accept_friendship": "accepted", "reject_friendship": "rejected",
                             "ignore_friendship": "ignored", "cancel_friendship_request": "cancelled"}[command]
                    if command == "accept_friendship":
                        if values["refused_a"] or values["refused_b"]:
                            raise ToolBusinessError("Lift the applicable refusal explicitly before accepting friendship.")
                        values["friendship"] = 1
                    elif command == "reject_friendship":
                        values[f"refused_{side}"] = 1
                    records.append(capture(self.manager, "friendship_requests", request_id=request.values["request_id"],
                        status=state, responded_at=self.clock.wall_time()))
                    result.update(status=state.upper(), request_id=request.values["request_id"])
            elif command == "block_agent":
                values.update(friendship=0, **{f"blocked_{side}": 1})
                result["status"] = "BLOCKED"
                if not relation.values[f"blocked_{side}"] and self.manager._agents_by_id[other_agent_id].lifecycle_state == "active":
                    mail_specs.append((other_agent_id, "relationship_changed", {
                        "relationship_id": values["relationship_id"], "actor_agent_id": actor.agent_id, "change": "blocked"}))
            elif command == "unblock_agent":
                if values[f"blocked_{side}"]:
                    values[f"blocked_{side}"] = 0
                    if not values[f"blocked_{other}"]:
                        values.update(friendship=0, generation=values["generation"] + 1, allowance_a=3, allowance_b=3)
                result["status"] = "UNBLOCKED"
            elif command == "remove_friendship":
                if values["friendship"]:
                    values.update(friendship=0, generation=values["generation"] + 1, allowance_a=3, allowance_b=3)
                result["status"] = "REMOVED"
            elif command == "lift_direct_refusal":
                values[f"refused_{side}"] = 0
                result["status"] = "REFUSAL_LIFTED"
            else:
                raise ToolBusinessError("Unknown relationship operation.")
            records[0] = capture(self.manager, "direct_relationships", **values)
            result["generation"] = values["generation"]
            try:
                for owner, message_type, payload in mail_specs:
                    mail_ids.append((owner, self.manager._inbox.notify(owner, message_type, payload)))
                if mail_ids:
                    dirty = self.manager._new_dirty_state()
                    dirty["agent_inboxes"].update(owner for owner, _ in mail_ids)
                    arrivals, notices = self.manager._activity.mail_records(dirty["agent_inboxes"])
                    records.extend(arrivals)
                return await self.finish(actor, command, operation, records, result, dirty=dirty, notifications=notices)
            finally:
                if operation[2] not in self.manager._records.receipts:
                    for owner, mail_id in mail_ids:
                        person = self.manager._agents_by_id[owner]
                        with person.inbox_lock:
                            person.agent_inbox[:] = [item for item in person.agent_inbox if item["message_id"] != mail_id]
