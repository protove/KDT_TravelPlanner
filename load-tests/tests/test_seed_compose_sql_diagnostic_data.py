from __future__ import annotations

import importlib.util
import json
import stat
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts/loadtest/seed-compose-sql-diagnostic-data.py"
SPEC = importlib.util.spec_from_file_location("seed_sql_diagnostic", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeRuntime:
    def __init__(self) -> None:
        self.sql: list[str] = []

    def psql(self, sql: str) -> str:
        self.sql.append(sql)
        if sql.startswith("SELECT count(*)"):
            import re
            match = re.search(r"sql-diagnostic-(?:noop|reverse)-(\d+)", self.sql[-2])
            return match.group(1) if match else "0"
        return ""


class SeedSqlDiagnosticTest(unittest.TestCase):
    def test_item_counts_and_modes_are_bounded(self) -> None:
        self.assertEqual(MODULE.ITEM_COUNTS, (3, 10, 25, 50, 100, 200))
        self.assertEqual(MODULE.MODES, ("noop", "reverse"))

    def test_insert_items_uses_existing_timeline_columns_and_exact_count(self) -> None:
        runtime = FakeRuntime()
        ids = MODULE.insert_items(runtime, "travel-1", 3, "seed", "reverse")
        self.assertEqual(len(ids), 3)
        self.assertIn("INSERT INTO timeline_table", runtime.sql[0])
        self.assertIn("visit_order", runtime.sql[0])
        self.assertNotIn("accessToken", runtime.sql[0])

    def test_write_credentials_is_owner_readable_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.json"
            MODULE.write_credentials(path, {"credentials": [{"accessToken": "synthetic"}]})
            mode = path.stat().st_mode
            self.assertEqual(mode & (stat.S_IRWXG | stat.S_IRWXO), 0)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["credentials"][0]["accessToken"], "synthetic")


if __name__ == "__main__":
    unittest.main()
