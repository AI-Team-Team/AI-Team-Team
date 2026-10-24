"""Independent endpoints exempt their own side, not an attached counterpart."""

import unittest

from ai_team_team import ATTConfig, ApprovalPrincipal, ParentApprovalCommunicationConfig
from ai_team_team.core.organization import communication_route


def team(identity):
    return ApprovalPrincipal(kind="agent_team", principal_id=identity)


class ExplicitRouteTests(unittest.TestCase):
    def test_independent_pair_is_permissive_under_every_policy(self):
        for policy in ("permissive", "parent_approval", "lineage_approval"):
            principals, evidence = communication_route("A", "B", {"A": None, "B": None}, policy)
            self.assertEqual(principals, [])
            if policy != "permissive":
                self.assertEqual([item["authority"] for item in evidence["endpoints"]], ["EXEMPT", "EXEMPT"])

    def test_cross_tree_lineage_has_no_synthetic_root(self):
        principals, evidence = communication_route("A", "B",
            {"A": team("P"), "P": None, "B": team("Q"), "Q": None}, "lineage_approval")
        self.assertEqual(principals, [team("P"), team("Q"), team("B")])
        self.assertNotIn("Root", str(evidence))

    def test_independent_parent_still_approves_for_attached_child(self):
        parents = {"A": team("P"), "P": None}
        self.assertEqual(communication_route("A", "P", parents, "parent_approval")[0], [team("P")])
        self.assertEqual(communication_route("A", "P", parents, "lineage_approval")[0], [team("P")])
        self.assertEqual(communication_route("P", "A", parents, "lineage_approval")[0], [team("A")])

    def test_communication_wake_is_rejected_at_construction_and_assignment(self):
        with self.assertRaises(ValueError):
            ATTConfig(communication={"policy": "parent_approval", "request_delivery": "wake"})
        config = ParentApprovalCommunicationConfig()
        with self.assertRaises(ValueError):
            config.request_delivery = "wake"
