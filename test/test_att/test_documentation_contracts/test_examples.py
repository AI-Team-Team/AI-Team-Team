"""The published complete examples execute offline from their exact Markdown source."""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from ._support import ROOT, runnable_blocks


class RunnableExampleTests(unittest.IsolatedAsyncioTestCase):
    def examples(self):
        result = {}
        for path in (ROOT / "docs/user/Quickstart.md", ROOT / "docs/Background_Tasks.md"):
            result.update(runnable_blocks(path))
        return result

    def load(self, source, name):
        namespace = {"__name__": name, "__file__": str(ROOT / name)}
        exec(compile(source, name, "exec"), namespace)
        return namespace

    def test_complete_fences_match_the_distributed_example_files(self):
        examples = self.examples()
        self.assertEqual(set(examples), {"examples/personal_activity.py", "examples/background_tasks.py"})
        for name, source in examples.items():
            with self.subTest(example=name):
                self.assertEqual(source, (ROOT / name).read_text(encoding="utf-8"))

    async def personal(self, native):
        example = self.load(self.examples()["examples/personal_activity.py"], "personal_activity")
        with tempfile.TemporaryDirectory(prefix="att-doc-personal-") as workspace:
            async with asyncio.timeout(30):
                result = await example["run_demo"](Path(workspace), native=native)
        self.assertEqual(result, {"intent": "idle", "model_calls": 2,
            "same_identity_restored": True, "durability": "durable"})

    async def test_native_example_has_explicit_idle_and_stable_restore_identity(self):
        await self.personal(True)

    async def test_text_example_uses_an_actual_text_action(self):
        await self.personal(False)

    async def test_background_example_reads_without_implicitly_acknowledging(self):
        examples = self.examples()
        personal = types.ModuleType("personal_activity")
        personal.__dict__.update(self.load(examples["examples/personal_activity.py"], "personal_activity"))
        with patch.dict(sys.modules, {"personal_activity": personal}):
            example = self.load(examples["examples/background_tasks.py"], "background_tasks")
            with tempfile.TemporaryDirectory(prefix="att-doc-background-") as workspace:
                async with asyncio.timeout(30):
                    result = await example["run_demo"](Path(workspace))
        self.assertEqual(result, {"admission": "BACKGROUND", "attention": "ACKNOWLEDGED",
            "durability": "durable", "execution": "completed"})

    async def run_script(self, name, *arguments):
        with tempfile.TemporaryDirectory(prefix="att-doc-cli-") as workspace:
            process = await asyncio.to_thread(subprocess.run,
                [sys.executable, str(ROOT / name), *arguments], cwd=workspace,
                capture_output=True, text=True, encoding="utf-8", timeout=40,
                env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONWARNINGS": "error::ResourceWarning"})
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertFalse((Path(workspace) / ".att_doc_libs").exists())
        self.assertNotIn("SOURCE_BODY", process.stdout)
        return json.loads(process.stdout)

    async def test_personal_cli_runs_from_outside_the_repository(self):
        self.assertTrue((await self.run_script("examples/personal_activity.py"))["same_identity_restored"])

    async def test_text_cli_runs_from_outside_the_repository(self):
        self.assertEqual((await self.run_script("examples/personal_activity.py", "--text"))["model_calls"], 2)

    async def test_background_cli_runs_from_outside_the_repository(self):
        self.assertEqual((await self.run_script("examples/background_tasks.py"))["attention"], "ACKNOWLEDGED")
