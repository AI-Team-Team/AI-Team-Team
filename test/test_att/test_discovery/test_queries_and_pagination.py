"""Entity-based ranges, stable mixed ordering, strict queries, and live results."""

import unittest

from ai_team_team import AgentDirectoryRecord, EntityDiscoveryResult
from ai_team_team.core.manager.discovery import DiscoveryService

from ._fixture import DiscoveryFixture


class DiscoveryQueryTests(DiscoveryFixture, unittest.IsolatedAsyncioTestCase):
    async def test_default_size_and_explicit_range_have_no_thirty_entity_cap(self):
        for index in range(70):
            self.person(f"Person{index:03}")
        first = self.manager.list_entities("agent")
        self.assertIsInstance(first, EntityDiscoveryResult)
        self.assertEqual(first.returned_count, 30)
        self.assertEqual(first.requested_end_index, 30)
        self.assertEqual(first.total_results, 71)
        page = self.manager.list_entities("agent", start_index=21)
        self.assertEqual((page.actual_start_index, page.actual_end_index), (21, 50))
        self.assertEqual(page.requested_end_index, 50)
        self.assertEqual(page.items[0].name, "Person020")
        self.assertEqual(page.items[-1].name, "Person049")
        explicit = self.manager.list_entities("agent", start_index=1, end_index=65)
        self.assertEqual(explicit.returned_count, 65)
        self.assertEqual(explicit.actual_end_index, 65)

    async def test_truncated_and_empty_results_report_actual_entity_positions(self):
        for index in range(26):
            self.person(f"Person{index:02}", description="Several\nphysical\nlines.")
        page = self.manager.list_entities("agent", 21, 40)
        self.assertEqual(
            page.model_dump(exclude={"items"}),
            {
                "requested_start_index": 21,
                "requested_end_index": 40,
                "actual_start_index": 21,
                "actual_end_index": 27,
                "maximum_index": 27,
                "total_results": 27,
                "returned_count": 7,
            },
        )
        empty = self.manager.list_entities("agent", 41)
        self.assertEqual(empty.requested_end_index, 70)
        self.assertIsNone(empty.actual_start_index)
        self.assertIsNone(empty.actual_end_index)
        self.assertEqual(empty.maximum_index, 27)
        self.assertEqual(empty.items, [])
        no_teams = self.manager.list_entities("agent_team")
        self.assertEqual(no_teams.maximum_index, 0)
        self.assertEqual(no_teams.total_results, 0)
        self.assertIsNone(no_teams.actual_start_index)

    async def test_ordering_is_case_insensitive_with_uppercase_first(self):
        for name in ("b", "a", "B", "A"):
            self.person(name)
        self.assertEqual(
            [item.name for item in self.manager.list_entities("agent").items],
            ["A", "a", "B", "b", "ZRoot"],
        )
        self.assertEqual(
            [item.name for item in self.manager.search_entities(["a", "b"], "agent").items],
            ["A", "a", "B", "b", "ZRoot"],
        )

    async def test_equal_labels_use_type_and_stable_id_not_insertion_order(self):
        team = self.manager.create_agent_team(self.root)
        person = self.person(team.team_id)
        page = self.manager.search_entities([team.team_id])
        self.assertEqual([record.entity_type for record in page.items], ["agent", "agent_team"])
        self.assertEqual(page.items[0].agent_id, person.agent_id)
        records = [
            AgentDirectoryRecord(agent_id=identifier, name="Same", role="", role_description="")
            for identifier in ("b", "a")
        ]
        self.assertEqual(
            [record.agent_id for record in sorted(records, key=DiscoveryService.sort_key)],
            ["a", "b"],
        )

    async def test_punctuation_and_non_latin_names_have_deterministic_non_locale_order(self):
        for name in ("研究", "ä", "!Alpha", "Ა", "ა", "Ä"):
            self.person(name)
        expected = ["!Alpha", "ZRoot", "Ä", "ä", "Ა", "ა", "研究"]
        self.assertEqual(
            [record.name for record in self.manager.list_entities("agent").items], expected
        )
        self.assertEqual(
            [record.name for record in self.manager.list_entities("agent").items], expected
        )

    async def test_or_substring_search_deduplicates_then_sorts_and_paginates_matches(self):
        self.person("Alpha", description="Database researcher")
        self.person("Bravo", description="Evidence research and DATABASE reviews")
        self.person("Charlie", role="database")
        self.person("Unrelated", role="Observer")
        page = self.manager.search_entities([" DATA ", "RESEARCH", "data"], "agent", 2, 9)
        self.assertEqual([record.name for record in page.items], ["Bravo", "Charlie"])
        self.assertEqual(page.total_results, 3)
        self.assertEqual((page.actual_start_index, page.actual_end_index), (2, 3))
        exact_id = self.manager.search_entities([page.items[0].agent_id], "agent")
        self.assertEqual(exact_id.items, [page.items[0]])
        self.assertEqual(self.manager.search_entities(["[database]"], "agent").total_results, 0)

    async def test_invalid_ranges_keywords_and_types_fail_without_coercion(self):
        for value in (0, -1, 1.5, True, False, "1"):
            for parameter in ("start_index", "end_index"):
                with self.subTest(value=value, parameter=parameter), self.assertRaises(ValueError):
                    self.manager.list_entities(**{parameter: value})
        with self.assertRaises(ValueError):
            self.manager.list_entities(start_index=3, end_index=2)
        for keywords in ([], [""], ["  "], ["valid", "\t"], "database", [1], [None], [True]):
            with self.subTest(keywords=keywords), self.assertRaises(ValueError):
                self.manager.search_entities(keywords)
        for kind in ("library", "AGENT", None, True):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.manager.list_entities(kind)
        with self.assertRaises(ValueError):
            self.manager.inspect_entity("all", self.root.agent_id)
        with self.assertRaises(ValueError):
            self.manager.inspect_entity("agent", "")

    async def test_mixed_entities_each_occupy_one_result_position(self):
        team = self.manager.create_agent_team(self.root, team_purpose="Database\nresearch")
        all_items = self.manager.list_entities(end_index=999).items
        self.assertEqual(len(all_items), len(self.manager.agents) + len(self.manager.teams))
        for position, item in enumerate(all_items, 1):
            self.assertEqual(
                self.manager.list_entities(start_index=position, end_index=position).items, [item]
            )
        teams = self.manager.search_entities(["DATABASE"], "agent_team")
        self.assertEqual([item.team_id for item in teams.items], [team.team_id])

    async def test_inspect_and_subsequent_pages_read_current_not_persisted_snapshots(self):
        person = self.person("OldName", description="Original profile")
        before = self.manager.inspect_entity("agent", person.agent_id)
        person.role_description = "Latest profile"
        after = self.manager.inspect_entity("agent", person.agent_id)
        self.assertEqual(before.role_description, "Original profile")
        self.assertEqual(after.role_description, "Latest profile")
        first = self.manager.list_entities("agent", 1, 1)
        self.person("Aardvark")
        next_page = self.manager.list_entities("agent", 2, 2)
        self.assertEqual(first.items, next_page.items)
        self.assertEqual(next_page.total_results, first.total_results + 1)
