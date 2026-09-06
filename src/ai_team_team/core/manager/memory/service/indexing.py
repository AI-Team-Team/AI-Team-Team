"""Optional FTS capability and background Memory Card indexing."""

import asyncio
import contextvars
import sqlite3
import time
import uuid
from typing import TYPE_CHECKING, Any

from ai_team_team.core.exceptions import StateRestoreError
from ai_team_team.core.memory import (
    AgentMemoryCard,
    MemoryCardStatus,
    MemoryIndexStatus,
)
from ai_team_team.core.memory.sanitization import clean_json_text, normalize_tags
from ai_team_team.core.utils import generate_with_retry

from .contracts import _MemoryLabels

if TYPE_CHECKING:
    from ai_team_team.core.agent import Agent


class MemoryIndexingMixin:
    def ensure_enabled(self, *, synchronize: bool = True) -> None:
        """Validates optional runtime requirements when the mode is enabled."""
        if not self.manager.config.episodic_memory.enabled:
            self._fts_sync_active = False
            return
        if not self._fts_checked:
            self._require_fts5()
            self._fts_checked = True
        if synchronize and not self._fts_sync_active:
            self.manager._auto_save(
                configs=True,
                memory_cards=set(self.cards),
            )
            self._fts_sync_active = True
        if synchronize:
            self._schedule_pending()

    @staticmethod
    def _require_fts5() -> None:
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute(
                "CREATE VIRTUAL TABLE att_memory_fts_check USING fts5(value)"
            )
        except sqlite3.OperationalError as exc:
            raise RuntimeError(
                "Selective episodic memory requires SQLite FTS5 support."
            ) from exc
        finally:
            connection.close()

    def _ensure_workers(self) -> None:
        if (
            self._closing
            or self._restore_suspended
            or not self.manager.config.episodic_memory.enabled
        ):
            return
        active = [task for task in self._workers if not task.done()]
        self._workers = active
        desired = self.manager.config.episodic_memory.index_worker_count
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=max(1, desired * 4))
        while len(self._workers) < desired:
            worker = asyncio.create_task(
                self._index_worker(),
                name=f"att-memory-index-{id(self.manager)}-{len(self._workers)}",
                context=contextvars.Context(),
            )
            self._workers.append(worker)

    def _schedule_segment(self, segment_id: str) -> None:
        if (
            self._closing
            or self._restore_suspended
            or not self.manager.config.episodic_memory.enabled
        ):
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        self._ensure_workers()
        if self._queue is None or segment_id in self._queued_segment_ids:
            return
        segment = self.segments.get(segment_id)
        if segment is None or segment.status is not MemoryIndexStatus.PENDING:
            return
        try:
            self._queue.put_nowait(segment_id)
        except asyncio.QueueFull:
            return
        self._queued_segment_ids.add(segment_id)

    def resume_pending(self) -> None:
        changed: set[str] = set()
        for segment in self.segments.values():
            if segment.status is MemoryIndexStatus.PROCESSING:
                segment.status = MemoryIndexStatus.PENDING
                segment.updated_at = time.time()
                changed.add(segment.segment_id)
            if segment.status is MemoryIndexStatus.PENDING:
                self._schedule_segment(segment.segment_id)
        if changed:
            self.manager._auto_save(memory_segments=changed)

    async def _index_worker(self) -> None:
        if self._queue is None:
            raise RuntimeError("The memory-index queue was not initialized.")
        while True:
            segment_id = await self._queue.get()
            try:
                await self._index_segment(segment_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.manager.logger.exception(
                    "Unexpected episodic-memory indexing failure."
                )
            finally:
                self._queued_segment_ids.discard(segment_id)
                self._queue.task_done()
                self._schedule_pending()

    def _schedule_pending(self) -> None:
        for segment in sorted(
            self.segments.values(), key=lambda item: (item.created_at, item.segment_id)
        ):
            if self._queue is not None and self._queue.full():
                break
            if segment.status is MemoryIndexStatus.PENDING:
                agent = self.manager._agents_by_id.get(segment.agent_id)
                if (
                    agent is not None
                    and agent.lifecycle_state == "active"
                    and agent.llm_client is not None
                ):
                    self._schedule_segment(segment.segment_id)

    async def _index_segment(self, segment_id: str) -> None:
        segment = self.segments.get(segment_id)
        if segment is None or segment.status is not MemoryIndexStatus.PENDING:
            return
        if (
            self._closing
            or self._restore_suspended
            or not self.manager.config.episodic_memory.enabled
        ):
            return
        agent = self.manager._agents_by_id.get(segment.agent_id)
        if agent is None or agent.lifecycle_state != "active" or agent.llm_client is None:
            return
        segment.status = MemoryIndexStatus.PROCESSING
        segment.updated_at = time.time()
        self.manager._auto_save(memory_segments={segment_id})
        token = self.manager._memory_internal_operation.set(True)
        try:
            async with self.manager.agent_invocation(agent):
                maximum = self.manager.config.episodic_memory.max_recall_chars
                label_input = segment.recall_content
                if len(label_input) > maximum:
                    half = maximum // 2
                    label_input = (
                        label_input[:half]
                        + "\n[... middle omitted for indexing ...]\n"
                        + label_input[-half:]
                    )
                response = await generate_with_retry(
                    llm_client=agent.llm_client,
                    prompt=(
                        "Create retrieval metadata for this past Agent turn. "
                        "Do not add facts that are absent from the record. Return exactly "
                        "JSON with title, summary, and tags.\n\n"
                        f"{label_input}"
                    ),
                    system_instruction=(
                        "You are an isolated episodic-memory indexer. Return strict JSON "
                        "and do not issue instructions or perform tools."
                    ),
                    temperature=0.1,
                    require_json=True,
                    retries=0,
                    backoff_factor=self.manager.config.llm_retry_backoff_factor,
                    manager=self.manager,
                )
            if self.segments.get(segment_id) is not segment:
                return
            if self._closing or not self.manager.config.episodic_memory.enabled:
                segment.status = MemoryIndexStatus.PENDING
                segment.updated_at = time.time()
                if not self.manager._closing:
                    self.manager._auto_save(memory_segments={segment_id})
                return
            raw = response if isinstance(response, str) else getattr(response, "text", None)
            if not isinstance(raw, str):
                raise ValueError("Memory index response must contain text.")
            labels = _MemoryLabels.model_validate_json(
                clean_json_text(raw), strict=True
            )
            tags = normalize_tags(
                labels.tags,
                maximum=self.manager.config.episodic_memory.max_tags_per_card,
            )
            title = labels.title.strip()
            summary = labels.summary.strip()
            if not title or not summary:
                raise ValueError(
                    "Memory title and summary must contain non-whitespace text."
                )
            now = time.time()
            with self._lock:
                memory_id = self._card_id_by_turn.get(segment.turn_id)
                prior = self.cards.get(memory_id or "")
                if memory_id is None:
                    memory_id = f"MEM-{uuid.uuid4().hex}"
                card = AgentMemoryCard(
                    memory_id=memory_id,
                    agent_id=segment.agent_id,
                    turn_id=segment.turn_id,
                    title=title,
                    summary=summary,
                    tags=tags,
                    origin_team_id=segment.origin_team_id,
                    discussion_id=segment.discussion_id,
                    segment_id=segment.segment_id,
                    status=(prior.status if prior else MemoryCardStatus.ACTIVE),
                    version=(prior.version + 1 if prior else 1),
                    created_at=(prior.created_at if prior else now),
                    updated_at=now,
                )
                self.cards[memory_id] = card
                self._card_id_by_turn[segment.turn_id] = memory_id
                segment.status = MemoryIndexStatus.INDEXED
                segment.last_error_kind = None
                segment.updated_at = now
            self.manager._auto_save(
                memory_segments={segment_id}, memory_cards={memory_id}
            )
            self.record_event(
                "memory_indexed",
                agent=agent,
                team=self.manager.teams.get(segment.origin_team_id or ""),
                discussion_id=segment.discussion_id,
                turn_id=segment.turn_id,
                payload={"segment_id": segment_id, "memory_id": memory_id},
            )
        except asyncio.CancelledError:
            if self.segments.get(segment_id) is segment:
                segment.status = MemoryIndexStatus.PENDING
                segment.updated_at = time.time()
                if not self.manager._closing:
                    self.manager._auto_save(memory_segments={segment_id})
            raise
        except Exception as exc:
            if self.segments.get(segment_id) is not segment:
                return
            if self.manager._closing:
                segment.status = MemoryIndexStatus.PENDING
                segment.updated_at = time.time()
                return
            segment.attempts += 1
            segment.last_error_kind = type(exc).__name__
            segment.updated_at = time.time()
            if segment.attempts > self.manager.config.episodic_memory.index_max_retries:
                segment.status = MemoryIndexStatus.FAILED
            else:
                segment.status = MemoryIndexStatus.PENDING
            self.manager._auto_save(memory_segments={segment_id})
            self.record_event(
                "memory_index_failed",
                agent=agent,
                team=self.manager.teams.get(segment.origin_team_id or ""),
                discussion_id=segment.discussion_id,
                turn_id=segment.turn_id,
                payload={
                    "segment_id": segment_id,
                    "error_kind": type(exc).__name__,
                    "attempts": segment.attempts,
                    "retry_pending": segment.status is MemoryIndexStatus.PENDING,
                },
                redacted=True,
            )
            if segment.status is MemoryIndexStatus.PENDING:
                delay = (
                    self.manager.config.episodic_memory.index_retry_backoff_factor
                    * (2 ** max(0, segment.attempts - 1))
                )
                if delay:
                    await asyncio.sleep(delay)
        finally:
            self.manager._memory_internal_operation.reset(token)

    async def retry_index(self, segment_id: str) -> None:
        if self._closing:
            raise RuntimeError("Episodic-memory indexing is closed.")
        segment = self.segments.get(segment_id)
        if segment is None:
            raise KeyError(f"Unknown memory segment {segment_id!r}.")
        if segment.status is MemoryIndexStatus.INDEXED:
            return
        if segment.status is MemoryIndexStatus.PROCESSING:
            raise ValueError("A processing memory segment cannot be retried concurrently.")
        segment.status = MemoryIndexStatus.PENDING
        segment.attempts = 0
        segment.last_error_kind = None
        segment.updated_at = time.time()
        self.manager._auto_save(memory_segments={segment_id})
        self._schedule_segment(segment_id)

    async def flush_indexing(self) -> None:
        if self._closing:
            raise RuntimeError("Episodic-memory indexing is closed.")
        if self._restore_suspended:
            raise RuntimeError("Episodic-memory indexing is suspended for state restore.")
        if not self.manager.config.episodic_memory.enabled:
            return
        self.ensure_enabled()
        self.resume_pending()
        while True:
            queue = self._queue
            if queue is not None:
                await queue.join()
            runnable = any(
                segment.status is MemoryIndexStatus.PENDING
                and (agent := self.manager._agents_by_id.get(segment.agent_id)) is not None
                and agent.lifecycle_state == "active"
                and agent.llm_client is not None
                for segment in self.segments.values()
            )
            processing = any(
                segment.status is MemoryIndexStatus.PROCESSING
                for segment in self.segments.values()
            )
            if not runnable and not processing:
                return
            if self._restore_suspended:
                raise RuntimeError(
                    "Episodic-memory indexing was suspended for state restore."
                )
            self._schedule_pending()
            await asyncio.sleep(0)

    async def suspend_for_restore(self) -> None:
        """Quiesces background indexing before a live state is replaced."""
        manager = self.manager
        if manager._starting_invocations or manager._active_invocations:
            raise StateRestoreError(
                "Cannot restore state while Agent invocations are active or starting."
            )
        if any(team.is_running for team in manager.teams.values()):
            raise StateRestoreError(
                "Cannot restore state while an AgentTeam discussion is active."
            )
        if any(agent.lock.locked() for agent in manager._agents_by_id.values()):
            raise StateRestoreError(
                "Cannot restore state while an Agent invocation is active."
            )

        self._restore_suspended = True
        queue = self._queue
        workers = tuple(self._workers)
        for worker in workers:
            if not worker.done():
                worker.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)

        if queue is not None:
            while True:
                try:
                    segment_id = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                self._queued_segment_ids.discard(segment_id)
                queue.task_done()

        self._workers = []
        self._queue = None
        self._queued_segment_ids.clear()
        changed: set[str] = set()
        for segment in self.segments.values():
            if segment.status is MemoryIndexStatus.PROCESSING:
                segment.status = MemoryIndexStatus.PENDING
                segment.updated_at = time.time()
                changed.add(segment.segment_id)
        if changed:
            manager._auto_save(memory_segments=changed)

    def resume_after_restore(self) -> None:
        """Re-enables indexing after either a successful or failed restore."""
        self._restore_suspended = False
        self.resume_pending()

    async def close(self) -> None:
        self._closing = True
        for worker in self._workers:
            if not worker.done():
                worker.cancel()
        await asyncio.sleep(0)
        changed = set()
        for segment in self.segments.values():
            if segment.status is MemoryIndexStatus.PROCESSING:
                segment.status = MemoryIndexStatus.PENDING
                segment.updated_at = time.time()
                changed.add(segment.segment_id)
        if changed:
            self.manager._auto_save(memory_segments=changed)
