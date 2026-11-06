"""Current engineering references agree with executable schema and contracts."""

import ast
import json
import re
import sqlite3
import unittest
from contextlib import closing
from typing import Literal, get_args, get_origin

from sqlalchemy import create_engine, inspect

from ai_team_team.core.activity.contracts import ToolExecutionContract
from ai_team_team.database.models import Base
from ai_team_team.database.persistence.constants import STATE_SCHEMA_VERSION
from ai_team_team.database.persistence.records import valid_request_outcome

from ._support import ROOT, section, table, uncode


class EngineeringReferenceTests(unittest.TestCase):
    def test_sql_reference_has_the_current_physical_layout(self):
        sql = (ROOT / "docs/Database/Schema.sql").read_text(encoding="utf-8")
        version = re.search(r"^-- ATT schema (\d+):", sql)
        self.assertIsNotNone(version)
        self.assertEqual(version.group(1), STATE_SCHEMA_VERSION)

        def layout(connection):
            names = [row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )]
            result = {}
            for name in names:
                quoted = '"' + name.replace('"', '""') + '"'
                foreign_keys = {}
                for identity, position, target, source, destination, update, delete, match in connection.execute(
                    f"PRAGMA foreign_key_list({quoted})"
                ):
                    foreign_keys.setdefault(identity, []).append(
                        (position, target, source, destination, update, delete, match)
                    )
                indexes = []
                for _, index_name, unique, origin, partial in connection.execute(f"PRAGMA index_list({quoted})"):
                    index_quoted = '"' + index_name.replace('"', '""') + '"'
                    columns = tuple(row[2] for row in connection.execute(f"PRAGMA index_info({index_quoted})"))
                    statement = connection.execute(
                        "SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (index_name,)
                    ).fetchone()[0]
                    predicate = re.split(r"\bWHERE\b", statement or "", flags=re.I)[-1] if partial else ""
                    indexes.append((index_name if origin == "c" else "", unique, origin,
                                    columns, " ".join(predicate.split())))
                result[name] = {
                    "columns": list(connection.execute(f"PRAGMA table_info({quoted})")),
                    "references": sorted(tuple(sorted(rows)) for rows in foreign_keys.values()),
                    "indexes": sorted(indexes),
                }
            return result

        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        with closing(sqlite3.connect(":memory:")) as documented:
            documented.execute("PRAGMA foreign_keys=ON")
            documented.executescript(sql)
            with engine.connect() as connection:
                actual = connection.connection.driver_connection
                self.assertEqual(layout(documented), layout(actual))
            documented_engine = create_engine("sqlite://", creator=lambda: documented)
            try:
                source_reader, reference_reader = inspect(engine), inspect(documented_engine)
                for name in Base.metadata.tables:
                    with self.subTest(table=name):
                        normalize = lambda rows: sorted(
                            (row["name"] or "", " ".join(row["sqltext"].split())) for row in rows
                        )
                        self.assertEqual(normalize(reference_reader.get_check_constraints(name)),
                                         normalize(source_reader.get_check_constraints(name)))
            finally:
                documented_engine.dispose()

    def test_documented_dispatch_matrix_matches_all_request_profiles(self):
        text = (ROOT / "docs/Database/Request_and_Token_States.md").read_text(encoding="utf-8")
        rows = table(section(text, "## Legal Dispatch and Outcome Combinations"))[1:]
        documented = {uncode(row[0]): set(re.findall(r"`([^`]+)`", row[1])) for row in rows}
        dispatches = {"unsent", "confirmed_unsent", "sent", "unknown_sent"}
        outcomes = {"pending", "completed", "failed", "cancelled", "uncertain"}
        self.assertEqual(set(documented), dispatches)
        for dispatch in dispatches:
            for outcome in outcomes:
                with self.subTest(dispatch=dispatch, outcome=outcome):
                    self.assertEqual(valid_request_outcome(dispatch, outcome), outcome in documented[dispatch])

    def test_execution_contract_reference_has_exact_fields_and_defaults(self):
        text = (ROOT / "docs/Autonomous_Agent_Runtime_Architecture/Executor_Integration.md").read_text(encoding="utf-8")
        rows = table(section(text, "## ToolExecutionContract Fields"))[1:]
        documented = {uncode(row[0]): row for row in rows}
        self.assertEqual(set(documented), set(ToolExecutionContract.model_fields))

        def literal_choices(annotation):
            if get_origin(annotation) is Literal:
                return set(get_args(annotation))
            return set().union(*(literal_choices(child) for child in get_args(annotation)))

        for name, field in ToolExecutionContract.model_fields.items():
            with self.subTest(field=name):
                cell = documented[name][1]
                if field.is_required():
                    self.assertTrue(cell.startswith("Required"))
                else:
                    self.assertEqual(ast.literal_eval(uncode(cell)), field.default)
                choices = literal_choices(field.annotation)
                self.assertTrue(choices <= set(re.findall(r"`([^`]+)`", documented[name][2])))

    def test_contract_routes_bind_current_sections_implementation_and_behavior(self):
        directory = ROOT / "docs/dev/verification"
        ledger = json.loads((directory / "verification_cases.json").read_text(encoding="utf-8"))
        routes = json.loads((directory / "documentation_cases.json").read_text(encoding="utf-8"))
        self.assertEqual(routes["state_schema"], STATE_SCHEMA_VERSION)
        checks = {check["id"]: check for check in ledger["checks"]}
        mapped = {entry["verification_id"]: entry for entry in routes["contracts"]}
        self.assertEqual(len(mapped), len(routes["contracts"]))
        self.assertEqual(set(mapped), set(checks))
        for identity, entry in mapped.items():
            with self.subTest(requirement=identity):
                self.assertEqual(entry["requirement"], checks[identity]["requirement"])
                self.assertTrue(entry["documentation"])
                self.assertTrue(entry["implementation"])
                self.assertTrue(checks[identity]["selectors"])
                for reference in entry["documentation"]:
                    path = ROOT / reference["path"]
                    self.assertTrue(path.is_relative_to(ROOT / "docs"))
                    text = path.read_text(encoding="utf-8")
                    self.assertIn(reference["heading"], re.findall(r"^#{1,6} (.+)$", text, re.M))
                for implementation in entry["implementation"]:
                    path = ROOT / implementation
                    self.assertEqual(path.suffix, ".py")
                    ast.parse(path.read_text(encoding="utf-8"))
