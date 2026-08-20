from __future__ import annotations

import importlib.util
import json
import stat
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts/loadtest/seed-compose-diagnostic-data.py"
SPEC = importlib.util.spec_from_file_location("seed_compose_diagnostic_data", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.counter = 0

    def psql(self, sql: str) -> str:
        self.calls.append(("psql", sql))
        return ""

    def seed_redis_token(self, user_id: str, ttl_ms: int) -> tuple[str, str]:
        self.counter += 1
        return f"refresh-{self.counter}", f"family-{self.counter}"

    def refresh(self, token: str) -> tuple[str, str]:
        return "access-token", f"rotated-{token}"

    def create_travel(self, access_token: str, index: int) -> str:
        self.counter += 1
        return f"travel-{self.counter}"

    def create_timeline_items(self, access_token: str, travel_id: str) -> list[str]:
        self.counter += 1
        return [f"{travel_id}-item-{index}" for index in range(1, 4)]

    def write_credentials(self, payload: dict, path: Path) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


class SeedDiagnosticTest(unittest.TestCase):
    def test_seed_tag_is_sanitized_and_bounded(self) -> None:
        self.assertEqual(MODULE.safe_seed_tag("r/1 fixed card"), "r1fixedcard")
        self.assertLessEqual(len(MODULE.safe_seed_tag("x" * 100)), 32)
        with self.assertRaises(MODULE.SeedError):
            MODULE.safe_seed_tag("---")

    def test_seed_layout_has_separate_fixed_and_growing_travels(self) -> None:
        runtime = FakeRuntime()
        args = type("Args", (), {"seed_tag": "test-seed", "variant": "growing-cardinality-mixed", "users": 1, "data_file": Path()})()
        with tempfile.TemporaryDirectory() as directory:
            args.data_file = Path(directory) / "credentials.json"
            MODULE.seed_variant(runtime, args, 1000)
            payload = json.loads(args.data_file.read_text(encoding="utf-8"))
        credential = payload["credentials"][0]
        self.assertEqual(len(credential["fixedOrderTimelineItemIds"]), 3)
        self.assertEqual(len(credential["growingTimelineItemIds"]), 3)
        self.assertNotEqual(credential["fixedOrderTravelId"], credential["growingTravelId"])
        self.assertEqual(payload["seedVersion"], "compose-diagnostic-s1")


if __name__ == "__main__":
    unittest.main()
