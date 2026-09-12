"""Owner-scoped Memory Catalog search, recall, retention, and forgetting."""

import base64
import bisect
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


def _line_start_offsets(content: str) -> List[int]:
    """Returns absolute offsets for each one-based normalized line."""

    offsets = [0]
    offsets.extend(
        index + 1 for index, character in enumerate(content) if character == "\n"
    )
    return offsets


def _position_to_offset(
    content: str,
    line_offsets: Sequence[int],
    line: int,
    character: int,
) -> int:
    """Converts a one-based line and character position to an absolute offset."""

    if line > len(line_offsets):
        raise ValueError("start_line is beyond the end of the memory segment.")
    line_start = line_offsets[line - 1]
    newline_offset = content.find("\n", line_start)
    line_limit = newline_offset if newline_offset >= 0 else len(content)
    maximum_character = line_limit - line_start + 1
    if character > maximum_character:
        raise ValueError(
            "start_character is beyond the requested memory segment line."
        )
    return line_start + character - 1


def _offset_to_position(
    line_offsets: Sequence[int], offset: int
) -> tuple[int, int]:
    """Converts an absolute offset to one-based continuation coordinates."""

    line_index = bisect.bisect_right(line_offsets, offset) - 1
    line_start = line_offsets[line_index]
    return line_index + 1, offset - line_start + 1


def _offset_after_line(
    content: str, line_offsets: Sequence[int], line: int
) -> int:
    """Returns the offset immediately after an inclusive one-based line."""

    if line < len(line_offsets):
        return line_offsets[line]
    return len(content)


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
        start_character: int = 1,
        character_count: Optional[int] = None,
        expected_segment_version: Optional[str] = None,
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
        for name, value in {
            "start_line": start_line,
            "start_character": start_character,
        }.items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer.")
        if end_line is not None and (
            not isinstance(end_line, int)
            or isinstance(end_line, bool)
            or end_line < start_line
        ):
            raise ValueError(
                "end_line must be an integer greater than or equal to start_line."
            )
        if character_count is not None and (
            not isinstance(character_count, int)
            or isinstance(character_count, bool)
            or character_count < 1
        ):
            raise ValueError("character_count must be a positive integer.")
        if end_line is not None and character_count is not None:
            raise ValueError(
                "end_line and character_count are mutually exclusive."
            )
        if expected_segment_version is not None and (
            not isinstance(expected_segment_version, str)
            or not expected_segment_version
        ):
            raise ValueError(
                "expected_segment_version must be a non-empty string when provided."
            )
        if (
            expected_segment_version is not None
            and expected_segment_version != segment.content_sha256
        ):
            raise ValueError(
                "The memory segment changed after the recall cursor was created."
            )

        source = segment.recall_content
        line_offsets = _line_start_offsets(source)
        start_offset = _position_to_offset(
            source,
            line_offsets,
            start_line,
            start_character,
        )
        if character_count is not None:
            requested_end_offset = min(
                len(source), start_offset + character_count
            )
        elif end_line is not None:
            requested_end_offset = _offset_after_line(
                source, line_offsets, end_line
            )
        else:
            requested_end_offset = len(source)

        configured_lines = self.manager.config.episodic_memory.max_recall_lines
        line_limited_end = _offset_after_line(
            source,
            line_offsets,
            start_line + configured_lines - 1,
        )
        maximum_chars = self.manager.config.episodic_memory.max_recall_chars
        bounded_end_offset = min(
            requested_end_offset,
            line_limited_end,
            start_offset + maximum_chars,
        )
        recalled_content = source[start_offset:bounded_end_offset]
        alias = self.manager.resolve_runtime_model_alias(agent.llm_client)
        maximum_tokens = self.manager.config.episodic_memory.max_recall_tokens
        content_token_count = self.manager.count_tokens(recalled_content, alias)
        if recalled_content and content_token_count > maximum_tokens:
            lower = 0
            upper = len(recalled_content)
            while lower < upper:
                midpoint = (lower + upper + 1) // 2
                if (
                    self.manager.count_tokens(recalled_content[:midpoint], alias)
                    <= maximum_tokens
                ):
                    lower = midpoint
                else:
                    upper = midpoint - 1
            recalled_content = recalled_content[:lower]
            bounded_end_offset = start_offset + lower
            content_token_count = self.manager.count_tokens(recalled_content, alias)

        truncated = bounded_end_offset < requested_end_offset
        if truncated and bounded_end_offset == start_offset:
            raise RuntimeError(
                "The configured memory recall token budget cannot return the next "
                "Unicode character."
            )
        if truncated:
            next_line, next_character = _offset_to_position(
                line_offsets, bounded_end_offset
            )
        else:
            next_line = None
            next_character = None
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
                "start_character": start_character,
                "end_line": start_line + recalled_content.count("\n"),
                "next_line": next_line,
                "next_character": next_character,
                "segment_version": segment.content_sha256,
                "truncated": truncated,
            },
            redacted=True,
        )
        actual_end_line = start_line + recalled_content.count("\n")
        return MemoryRecallResult(
            memory_id=memory_id,
            origin_team_id=card.origin_team_id,
            discussion_id=card.discussion_id,
            content=recalled_content,
            start_line=start_line,
            start_character=start_character,
            end_line=actual_end_line,
            next_line=next_line,
            next_character=next_character,
            segment_version=segment.content_sha256,
            content_token_count=content_token_count,
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
