"""Current guides retain usable navigation and executable test references."""

import ast
import re
import unicodedata
import unittest
from urllib.parse import unquote, urlsplit

from ai_team_team.database.persistence.constants import STATE_SCHEMA_VERSION

from ._support import ROOT, runnable_blocks


GUIDES = ("Personal_Activity.md", "Personal_Conversations.md", "Background_Tasks.md")


class DocumentationNavigationTests(unittest.TestCase):
    def current_documents(self):
        return [ROOT / "README.md", *(
            path for path in (ROOT / "docs").rglob("*.md")
            if "blueprints" not in path.parts and "autonomous_activity" not in path.parts
        )]

    def test_current_local_document_links_have_real_targets(self):
        for path in self.current_documents():
            for target in re.findall(r"(?<!!)\[[^\]\n]+\]\(([^)\n]+)\)", path.read_text(encoding="utf-8")):
                target = target.strip("<>")
                parsed = urlsplit(target)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                with self.subTest(document=path.relative_to(ROOT), target=target):
                    self.assertTrue((path.parent / unquote(parsed.path)).exists())

    def test_links_into_current_guides_use_actual_heading_anchors(self):
        targets = {name: ROOT / "docs" / name for name in GUIDES}
        targets["Quickstart.md"] = ROOT / "docs/user/Quickstart.md"
        targets["API_Reference.md"] = ROOT / "docs/user/API_Reference.md"
        checked = 0
        for document in self.current_documents():
            for target in re.findall(r"\[[^\]\n]+\]\(([^)\n]+)\)", document.read_text(encoding="utf-8")):
                parsed = urlsplit(target)
                if parsed.scheme or not parsed.fragment or not parsed.path:
                    continue
                path = (document.parent / unquote(parsed.path)).resolve()
                if path not in targets.values():
                    continue
                anchors = set()
                for heading in re.findall(r"^#{1,6} (.+)$", path.read_text(encoding="utf-8"), re.M):
                    plain = "".join(character for character in heading.strip().lower()
                                    if character in "_- " or unicodedata.category(character)[0] in "LMN")
                    plain = re.sub(r"[\ufe00-\ufe0f\U000e0100-\U000e01ef]", "", plain)
                    anchors.add(plain.replace(" ", "-"))
                with self.subTest(document=document.relative_to(ROOT), target=target):
                    self.assertIn(unquote(parsed.fragment), anchors)
                checked += 1
        self.assertGreater(checked, 0)

    def test_current_schema_statement_matches_the_store(self):
        text = (ROOT / "docs/State_Persistence.md").read_text(encoding="utf-8")
        current = re.search(r"The current persistence schema version is `(\d+)`\.", text)
        self.assertIsNotNone(current)
        self.assertEqual(current.group(1), STATE_SCHEMA_VERSION)

    def test_performance_workloads_reference_existing_test_methods(self):
        text = (ROOT / "docs/dev/Performance_Measurement.md").read_text(encoding="utf-8")
        selectors = re.findall(r"`(test_att\.[\w.]+\.test_\w+)`", text)
        self.assertTrue(selectors)
        for selector in selectors:
            module, class_name, method_name = selector.rsplit(".", 2)
            module_path = ROOT / "test" / (module.replace(".", "/") + ".py")
            if not module_path.exists():
                module_path = ROOT / "test" / module.replace(".", "/") / "__init__.py"
            with self.subTest(selector=selector):
                self.assertTrue(module_path.exists(), str(module_path))
                declarations = ast.parse(module_path.read_text(encoding="utf-8")).body
                owner = next(node for node in declarations
                             if isinstance(node, ast.ClassDef) and node.name == class_name)
                methods = {node.name for node in owner.body
                           if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
                self.assertIn(method_name, methods)

    def test_runnable_markers_are_unique_and_refer_to_example_sources(self):
        markers = []
        for document in self.current_documents():
            declarations = re.findall(r"^<!-- runnable: ([^\n]+) -->$", document.read_text(encoding="utf-8"), re.M)
            blocks = runnable_blocks(document)
            self.assertEqual(declarations, [name for name, _ in blocks], str(document))
            for name, _ in blocks:
                with self.subTest(document=document.relative_to(ROOT), example=name):
                    self.assertTrue(name.startswith("examples/"))
                    self.assertTrue((ROOT / name).is_file())
                markers.append(name)
        self.assertEqual(len(markers), len(set(markers)))
        self.assertEqual(set(markers), {"examples/personal_activity.py", "examples/background_tasks.py"})
