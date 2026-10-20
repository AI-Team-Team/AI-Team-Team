"""Resource exclusion never certifies that a custom operation has no source."""

from pathlib import Path

from ai_team_team import ResourceClaim
from ai_team_team.database.persistence.records import thaw

from ._support import BackgroundTestCase, contract


class SourceProvenanceTests(BackgroundTestCase):
    async def test_nonlibrary_claims_are_opaque_under_restrictive_result_access(self):
        async def operation() -> str:
            return "OPAQUE_EXTERNAL_RESULT"

        cases = ("global", "external", "host_resource")
        for namespace in cases:
            with self.subTest(namespace=namespace):
                name = f"read_{namespace}"
                self.manager.register_tool(name, func=operation, execution_contract=contract(),
                    resource_resolver=lambda scope, arguments, ns=namespace: (
                        ResourceClaim(namespace=ns, resource_id="shared", access="read"),))
                handle = await self.start(name)
                await self.finish(handle)
                row = self.manager._records.index[("executions", (handle.execution_id,))]
                self.assertEqual(thaw(row.values["source_references"]), [{"kind": "external", "executor": "callable"}])
                self.assertIn("OPAQUE_EXTERNAL_RESULT", (await self.manager.read_background_task_result(handle.execution_id, actor=self.root)).content)
                self.manager.config.executions.retain_results_after_source_revocation = False
                try:
                    with self.assertRaises(PermissionError):
                        await self.manager.read_background_task_result(handle.execution_id, actor=self.root)
                    self.assertFalse(self.manager.inspect_background_task(handle.execution_id, actor=self.root).result_available)
                finally:
                    self.manager.config.executions.retain_results_after_source_revocation = True

    async def test_explicit_empty_resolution_preserves_source_free_access(self):
        async def operation() -> str:
            return "SOURCE_FREE_RESULT"

        self.manager.register_tool("source_free", func=operation, execution_contract=contract(),
            resource_resolver=lambda scope, arguments: ())
        handle = await self.start("source_free")
        await self.finish(handle)
        self.manager.config.executions.retain_results_after_source_revocation = False
        row = self.manager._records.index[("executions", (handle.execution_id,))]
        self.assertEqual(row.values["source_references"], ())
        self.assertIn("SOURCE_FREE_RESULT", (await self.manager.read_background_task_result(handle.execution_id, actor=self.root)).content)

    async def test_global_source_provenance_survives_save_and_restore(self):
        async def operation() -> str:
            return "OPAQUE_PERSISTED_RESULT"

        self.manager.register_tool("global_read", func=operation, execution_contract=contract(),
            resource_resolver=lambda scope, arguments: (ResourceClaim(namespace="global", resource_id="external", access="read"),))
        handle = await self.start("global_read")
        await self.finish(handle)
        self.manager.config.executions.retain_results_after_source_revocation = False
        path = str(Path(self.workspace.name) / "opaque.sqlite")
        await self.manager.save_state(path)
        await self.manager.load_state(path)
        with self.assertRaises(PermissionError):
            await self.manager.read_background_task_result(handle.execution_id, actor=self.manager.root_ai)
        self.assertFalse(self.manager.inspect_background_task(handle.execution_id, actor=self.manager.root_ai).result_available)
