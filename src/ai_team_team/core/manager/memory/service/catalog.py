"""Owner-scoped Memory Catalog search, recall, retention, and forgetting."""

import base64
import hashlib
import json
import time
import uuid
from typing import TYPE_CHECKING, List, Optional, Sequence

from ai_team_team.core.memory import (
    MemoryCardStatus,
    MemoryOperationResult,
    MemoryRecallResult,
    MemorySearchItem,
    MemorySearchResult,
    RetainedMemoryReference,
)
from ai_team_team.core.memory.sanitization import (
    content_digest,
    normalize_tag,
    normalize_tags,
)

if TYPE_CHECKING:
    from ai_team_team.core.agent import Agent


class MemoryCatalogMixin:
    def _require_catalog_enabled(self) -> None:
        """Fails closed when a stale tool reference outlives runtime disablement."""
        self.ensure_enabled()
        if not self.manager.config.episodic_memory.enabled:
            raise RuntimeError("Selective episodic memory is disabled.")

    def _require_active_agent(self) -> "Agent":
        agent = self.manager._active_tool_agent.get()
        if (
            agent is None
            or self.manager._agents_by_id.get(agent.agent_id) is not agent
            or agent.lifecycle_state != "active"
        ):
            raise PermissionError(
                "Episodic memory requires an active registered Agent invocation."
            )
        team = self.manager._active_team.get()
        if team is None or agent not in team.members:
            raise PermissionError(
                "Episodic memory requires the Agent's invocation-scoped AgentTeam membership."
            )
        return agent

    @staticmethod
    def _cursor_signature(
        agent_id: str,
        query: Optional[str],
        tags: Sequence[str],
        team_id: Optional[str],
        discussion_id: Optional[str],
    ) -> str:
        source = json.dumps(
            [agent_id, query or "", list(tags), team_id, discussion_id],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(source.encode("utf-8")).hexdigest()

    async def search(
        self,
        *,
        query: Optional[str] = None,
        tags: Optional[List[str]] = None,
        team_id: Optional[str] = None,
        discussion_id: Optional[str] = None,
        limit: int = 20,
        cursor: Optional[str] = None,
    ) -> MemorySearchResult:
        self._require_catalog_enabled()
        agent = self._require_active_agent()
        maximum = self.manager.config.episodic_memory.max_search_results
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > maximum:
            raise ValueError(f"limit must be between 1 and {maximum}.")
        normalized_tags = normalize_tags(
            tags or [],
            maximum=self.manager.config.episodic_memory.max_tags_per_card,
        )
        normalized_query = normalize_tag(query) if query is not None else None
        signature = self._cursor_signature(
            agent.agent_id,
            normalized_query,
            normalized_tags,
            team_id,
            discussion_id,
        )
        offset = 0
        if cursor:
            try:
                decoded = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
                if decoded["signature"] != signature:
                    raise ValueError
                offset = int(decoded["offset"])
                if offset < 0:
                    raise ValueError
            except Exception as exc:
                raise ValueError("The memory-search cursor is invalid for this query.") from exc
        cards = [
            card
            for card in self.cards.values()
            if card.agent_id == agent.agent_id
            and card.status is MemoryCardStatus.ACTIVE
            and (team_id is None or card.origin_team_id == team_id)
            and (discussion_id is None or card.discussion_id == discussion_id)
            and all(tag in card.tags for tag in normalized_tags)
        ]
        if normalized_query:
            if self.manager.db_path:
                # Enabling the optional mode and indexing a card both submit
                # asynchronous FTS deltas. Search only after those accepted
                # writes are durable so it cannot observe a missing/stale FTS
                # table while the in-memory catalog is already current.
                await self.manager.flush_state()
                ranked_ids = await self.manager._persistence.search_memory_card_ids(
                    self.manager.db_path,
                    agent.agent_id,
                    normalized_query,
                    max(1, len(self.cards)),
                )
                rank = {memory_id: index for index, memory_id in enumerate(ranked_ids)}
                cards = [card for card in cards if card.memory_id in rank]
                cards.sort(key=lambda card: (rank[card.memory_id], -card.created_at))
            else:
                terms = normalized_query.split()
                cards = [
                    card
                    for card in cards
                    if all(
                        term
                        in normalize_tag(
                            " ".join([card.title, card.summary, *card.tags])
                        )
                        for term in terms
                    )
                ]
                cards.sort(key=lambda card: (-card.created_at, card.memory_id))
        else:
            cards.sort(key=lambda card: (-card.created_at, card.memory_id))
        page = cards[offset : offset + limit]
        next_cursor = None
        if offset + limit < len(cards):
            next_cursor = base64.urlsafe_b64encode(
                json.dumps(
                    {"signature": signature, "offset": offset + limit},
                    separators=(",", ":"),
                ).encode("utf-8")
            ).decode("ascii")
        self.record_event(
            "memory_searched",
            agent=agent,
            team=self.manager._active_team.get(),
            payload={
                "query_sha256": (
                    hashlib.sha256((query or "").encode("utf-8")).hexdigest()
                    if query is not None
                    else None
                ),
                "tags": normalized_tags,
                "origin_team_id": team_id,
                "discussion_id": discussion_id,
                "result_count": len(page),
            },
            redacted=query is not None,
        )
        return MemorySearchResult(
            items=[
                MemorySearchItem(
                    memory_id=card.memory_id,
                    title=card.title,
                    summary=card.summary,
                    tags=card.tags,
                    origin_team_id=card.origin_team_id,
                    discussion_id=card.discussion_id,
                    created_at=card.created_at,
                )
                for card in page
            ],
            next_cursor=next_cursor,
        )

    async def recall(
        self,
        memory_id: str,
        start_line: int = 1,
        end_line: Optional[int] = None,
    ) -> MemoryRecallResult:
        self._require_catalog_enabled()
        agent = self._require_active_agent()
        card = self.cards.get(memory_id)
        if (
            card is None
            or card.agent_id != agent.agent_id
            or card.status is not MemoryCardStatus.ACTIVE
        ):
            raise PermissionError("The requested active memory is not owned by this Agent.")
        segment = self.segments.get(card.segment_id)
        if segment is None or content_digest(segment.recall_content) != segment.content_sha256:
            raise RuntimeError("The memory segment is missing or failed integrity validation.")
        if not isinstance(start_line, int) or isinstance(start_line, bool) or start_line < 1:
            raise ValueError("start_line must be a positive integer.")
        configured_lines = self.manager.config.episodic_memory.max_recall_lines
        if end_line is None:
            end_line = start_line + configured_lines - 1
        if not isinstance(end_line, int) or isinstance(end_line, bool) or end_line < start_line:
            raise ValueError("end_line must be an integer greater than or equal to start_line.")
        end_line = min(end_line, start_line + configured_lines - 1)
        lines = segment.recall_content.splitlines()
        selected = lines[start_line - 1 : end_line]
        content = "\n".join(selected)
        truncated = end_line < len(lines)
        maximum_chars = self.manager.config.episodic_memory.max_recall_chars
        if len(content) > maximum_chars:
            content = content[:maximum_chars]
            truncated = True
        alias = self.manager.resolve_runtime_model_alias(agent.llm_client)
        maximum_tokens = self.manager.config.episodic_memory.max_recall_tokens
        if content and self.manager.count_tokens(content, alias) > maximum_tokens:
            lower = 0
            upper = len(content)
            while lower < upper:
                midpoint = (lower + upper + 1) // 2
                if self.manager.count_tokens(content[:midpoint], alias) <= maximum_tokens:
                    lower = midpoint
                else:
                    upper = midpoint - 1
            content = content[:lower]
            truncated = True
        turn_id = self.manager._active_agent_turn_id.get()
        if not turn_id:
            raise RuntimeError("Memory recall requires an active Agent turn.")
        self._recalled_by_turn.setdefault(turn_id, set()).add(memory_id)
        self.record_event(
            "memory_recalled",
            agent=agent,
            team=self.manager._active_team.get(),
            payload={
                "memory_id": memory_id,
                "start_line": start_line,
                "end_line": start_line + content.count("\n"),
                "truncated": truncated,
            },
            redacted=True,
        )
        actual_end_line = start_line + content.count("\n")
        if not selected:
            content = ""
            actual_end_line = start_line
            truncated = False
        return MemoryRecallResult(
            memory_id=memory_id,
            origin_team_id=card.origin_team_id,
            discussion_id=card.discussion_id,
            content=content,
            start_line=start_line,
            end_line=actual_end_line,
            truncated=truncated,
        )

    async def keep(self, memory_id: str, note: Optional[str] = None) -> MemoryOperationResult:
        self._require_catalog_enabled()
        agent = self._require_active_agent()
        card = self.cards.get(memory_id)
        if card is None or card.agent_id != agent.agent_id or card.status is not MemoryCardStatus.ACTIVE:
            raise PermissionError("The requested active memory is not owned by this Agent.")
        turn_id = self.manager._active_agent_turn_id.get()
        if not turn_id or memory_id not in self._recalled_by_turn.get(turn_id, set()):
            raise ValueError("The memory must be recalled earlier in the current Agent turn.")
        retained_note = card.summary if note is None else note.strip()
        if not retained_note or len(retained_note) > 1000:
            raise ValueError("A retained memory note must contain 1 to 1000 characters.")
        reference = RetainedMemoryReference(
            reference_id=f"MRF-{uuid.uuid4().hex}",
            agent_id=agent.agent_id,
            memory_id=memory_id,
            note=retained_note,
            created_at=time.time(),
        )
        with self._lock:
            self.references[reference.reference_id] = reference
            owned = sorted(
                (
                    item
                    for item in self.references.values()
                    if item.agent_id == agent.agent_id
                ),
                key=lambda item: (item.created_at, item.reference_id),
            )
            maximum = self.manager.config.episodic_memory.max_retained_context_items
            removed = owned[:-maximum]
            for item in removed:
                self.references.pop(item.reference_id, None)
        self.manager._auto_save(
            memory_references={reference.reference_id},
            deleted_memory_references={item.reference_id for item in removed},
        )
        self.record_event(
            "memory_retained",
            agent=agent,
            team=self.manager._active_team.get(),
            payload={"memory_id": memory_id, "reference_id": reference.reference_id},
        )
        return MemoryOperationResult(status="RETAINED", memory_id=memory_id)

    async def forget(self, memory_id: str, reason: Optional[str] = None) -> MemoryOperationResult:
        self._require_catalog_enabled()
        agent = self._require_active_agent()
        card = self.cards.get(memory_id)
        if card is None or card.agent_id != agent.agent_id:
            raise PermissionError("The requested memory is not owned by this Agent.")
        if card.status is MemoryCardStatus.FORGOTTEN:
            return MemoryOperationResult(status="ALREADY_FORGOTTEN", memory_id=memory_id)
        card.status = MemoryCardStatus.FORGOTTEN
        card.version += 1
        card.updated_at = time.time()
        removed_reference_ids = {
            reference.reference_id
            for reference in self.references.values()
            if reference.agent_id == agent.agent_id
            and reference.memory_id == memory_id
        }
        for reference_id in removed_reference_ids:
            self.references.pop(reference_id, None)
        self.manager._auto_save(
            memory_cards={memory_id},
            deleted_memory_references=removed_reference_ids,
        )
        self.record_event(
            "memory_forgotten",
            agent=agent,
            team=self.manager._active_team.get(),
            payload={
                "memory_id": memory_id,
                "reason_sha256": (
                    hashlib.sha256(reason.encode("utf-8")).hexdigest()
                    if reason
                    else None
                ),
            },
            redacted=bool(reason),
        )
        return MemoryOperationResult(status="FORGOTTEN", memory_id=memory_id)

    async def restore_forgotten(self, agent_id: str, memory_id: str) -> MemoryOperationResult:
        self.ensure_enabled()
        card = self.cards.get(memory_id)
        if card is None or card.agent_id != agent_id:
            raise KeyError(f"Unknown memory ID {memory_id!r} for Agent {agent_id!r}.")
        if card.status is MemoryCardStatus.ACTIVE:
            return MemoryOperationResult(status="ALREADY_ACTIVE", memory_id=memory_id)
        card.status = MemoryCardStatus.ACTIVE
        card.version += 1
        card.updated_at = time.time()
        self.manager._auto_save(memory_cards={memory_id})
        self.record_event(
            "memory_restored",
            agent=self.manager._agents_by_id.get(agent_id),
            payload={"memory_id": memory_id},
            inherit_context=False,
        )
        return MemoryOperationResult(status="RESTORED", memory_id=memory_id)

    def retained_context(self, agent_id: str) -> str:
        references = sorted(
            (
                item for item in self.references.values() if item.agent_id == agent_id
            ),
            key=lambda item: (item.created_at, item.reference_id),
        )
        if not references:
            return ""
        lines = ["## DELIBERATELY RETAINED MEMORY REFERENCES"]
        for reference in references:
            card = self.cards.get(reference.memory_id)
            if (
                card is not None
                and card.agent_id == agent_id
                and card.status is MemoryCardStatus.ACTIVE
            ):
                lines.append(f"- {reference.memory_id}: {reference.note}")
        if len(lines) == 1:
            return ""
        return "\n".join(lines) + "\n"
