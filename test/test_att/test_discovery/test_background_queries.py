"""Directory snapshots stay coherent for real worker-thread callbacks."""

import asyncio
import sys
import threading
import unittest
from unittest.mock import patch

from ai_team_team import Agent

from ._fixture import DiscoveryFixture


class _PausedRegistry(dict):
    """Pauses one reader after its live iterator has already been created."""

    def __init__(self, values, captured, release, mutation):
        super().__init__(values)
        self.captured = captured
        self.release = release
        self.mutation = mutation
        self.reader_thread = None
        self.armed = True

    def values(self):
        iterator = iter(super().values())
        if self.armed and threading.get_ident() == self.reader_thread:
            self.armed = False
            first = next(iterator)
            self.captured.set()
            if not self.release.wait(5):
                raise TimeoutError("The test directory capture was not released.")
            yield first
        yield from iterator

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.mutation.set()

    def pop(self, key, default=None):
        value = super().pop(key, default)
        self.mutation.set()
        return value


async def _wait_for(event):
    async with asyncio.timeout(5):
        while not event.is_set():
            await asyncio.sleep(0)


class BackgroundDiscoveryTests(DiscoveryFixture, unittest.IsolatedAsyncioTestCase):
    async def _query_during_lifecycle_change(self, action, *, inactive=False):
        person = self.person("ExistingPerson")
        if inactive:
            await self.manager.retire_agent(person.agent_id, policy="archive")
        expected_before = self.manager.list_entities("agent", end_index=999).model_dump()
        captured = threading.Event()
        release = threading.Event()
        mutation = threading.Event()
        registry = _PausedRegistry(self.manager._agents_by_id, captured, release, mutation)
        active = _PausedRegistry(self.manager.agents, captured, release, mutation)
        self.manager._agent_registry.replace_indexes(active, registry)
        pages = []
        errors = []

        def observer(event, payload):
            if event != "directory_snapshot":
                return
            registry.reader_thread = threading.get_ident()
            try:
                pages.append(self.manager.list_entities("agent", end_index=999).model_dump())
            except Exception as exc:
                errors.append(exc)

        def release_reader():
            # A broken writer releases the reader after mutating the dictionary.
            # A synchronized writer cannot mutate until the reader is released.
            mutation.wait(0.05)
            release.set()

        self.manager.on_system_event = observer
        releaser = threading.Thread(target=release_reader, daemon=True)
        try:
            self.manager._emit_callback("on_system_event", "directory_snapshot", {})
            await _wait_for(captured)
            releaser.start()
            await action(person)
            await self.manager.flush_callbacks()
        finally:
            release.set()
            if releaser.ident is not None:
                await asyncio.to_thread(releaser.join)
            await self.manager.flush_callbacks()
            self.manager.on_system_event = None
        self.assertEqual(errors, [])
        self.assertEqual(pages, [expected_before])
        return person

    async def test_callback_capture_serializes_with_agent_registration(self):
        async def register(_person):
            self.manager.register_agent(Agent("AddedPerson", "Observer", self.client))

        await self._query_during_lifecycle_change(register)
        names = [record.name for record in self.manager.list_entities("agent").items]
        self.assertIn("AddedPerson", names)

    async def test_callback_capture_serializes_with_agent_archive(self):
        async def archive(person):
            await self.manager.retire_agent(person.agent_id, policy="archive")

        person = await self._query_during_lifecycle_change(archive)
        with self.assertRaises(KeyError):
            self.manager.inspect_entity("agent", person.agent_id)

    async def test_callback_capture_serializes_with_agent_reactivation(self):
        async def reactivate(person):
            await self.manager.reactivate_agent(person.agent_id, "default")

        person = await self._query_during_lifecycle_change(reactivate, inactive=True)
        self.assertEqual(self.manager.inspect_entity("agent", person.agent_id).name, person.name)

    async def test_callback_capture_serializes_with_agent_deletion(self):
        async def delete(person):
            await self.manager.retire_agent(person.agent_id, policy="delete", confirm_delete=True)

        person = await self._query_during_lifecycle_change(delete)
        self.assertNotIn(person.agent_id, self.manager._agents_by_id)

    async def test_lifecycle_persistence_wait_does_not_hold_the_directory_lock(self):
        person = self.person("ExistingPerson")
        for state in ("archived", "active"):
            with self.subTest(state=state):
                saving = asyncio.Event()
                release = asyncio.Event()
                pages = []

                async def wait_for_commit():
                    saving.set()
                    await release.wait()

                def observer(event, payload):
                    if event == "directory_snapshot":
                        pages.append(self.manager.list_entities("agent", end_index=999))

                self.manager.on_system_event = observer
                operation = (
                    self.manager.retire_agent(person.agent_id, policy="archive")
                    if state == "archived"
                    else self.manager.reactivate_agent(person.agent_id, "default")
                )
                with patch.object(self.manager, "flush_state", side_effect=wait_for_commit):
                    task = asyncio.create_task(operation)
                    try:
                        async with asyncio.timeout(5):
                            await saving.wait()
                            self.manager._emit_callback("on_system_event", "directory_snapshot", {})
                            await self.manager.flush_callbacks()
                        self.assertEqual(len(pages), 1)
                        expected_count = 1 if state == "archived" else 2
                        self.assertEqual(pages[0].total_results, expected_count)
                    finally:
                        release.set()
                        await task
                        await self.manager.flush_callbacks()
                        self.manager.on_system_event = None

    async def test_repeated_real_callback_queries_during_registration_and_lifecycle_changes(self):
        started = threading.Event()
        stop = threading.Event()
        errors = []
        reads = []

        def observer(event, payload):
            if event != "directory_snapshot":
                return
            try:
                while not stop.is_set():
                    for page in (
                        self.manager.list_entities("agent", end_index=9999),
                        self.manager.search_entities(["Person", "ZRoot"], end_index=9999),
                    ):
                        self.assertEqual(page.total_results, len(page.items))
                        self.assertEqual(page.returned_count, len(page.items))
                        self.assertEqual(page.actual_end_index, page.total_results)
                    self.assertEqual(
                        self.manager.inspect_entity("agent", self.root.agent_id).name,
                        self.root.name,
                    )
                    reads.append(True)
                    started.set()
            except Exception as exc:
                errors.append(exc)
                started.set()
                stop.set()

        self.manager.on_system_event = observer
        previous_interval = sys.getswitchinterval()
        sys.setswitchinterval(0.00001)
        try:
            self.manager._emit_callback("on_system_event", "directory_snapshot", {})
            await _wait_for(started)
            for index in range(50):
                person = self.person(f"Person{index:03}")
                if index % 10 == 0:
                    await self.manager.retire_agent(person.agent_id, policy="archive")
                    await self.manager.reactivate_agent(person.agent_id, "default")
                await asyncio.sleep(0)
                if stop.is_set():
                    break
        finally:
            stop.set()
            await self.manager.flush_callbacks()
            self.manager.on_system_event = None
            sys.setswitchinterval(previous_interval)
        self.assertEqual(errors, [])
        self.assertTrue(reads)
        self.assertEqual(self.manager.list_entities("agent", end_index=9999).total_results, 51)
