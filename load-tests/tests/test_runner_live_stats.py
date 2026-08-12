"""Unit tests for the runner-side live k6 raw.json window summarizer."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


MODULE_PATH = (
    Path(__file__).parents[2] / "scripts" / "loadtest" / "aws" / "runner-live-stats.py"
)
SPEC = importlib.util.spec_from_file_location("runner_live_stats", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

NOW = 1_800_000_000.0


def point(metric: str, offset: float, value: float = 1.0) -> str:
    from datetime import datetime, timezone

    ts = (
        datetime.fromtimestamp(NOW + offset, tz=timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    return json.dumps({"type": "Point", "metric": metric, "data": {"time": ts, "value": value}})


class LiveStatsTests(unittest.TestCase):
    def test_missing_raw_json_reports_status(self) -> None:
        with TemporaryDirectory() as raw:
            result = MODULE.summarize(Path(raw) / "raw.json", 120, 1024, now=NOW)
            self.assertEqual(result["status"], "missing")

    def test_window_filters_old_points_and_sums_values(self) -> None:
        with TemporaryDirectory() as raw:
            path = Path(raw) / "raw.json"
            lines = [
                point("core_successful_operations_total", -300),  # outside window
                point("core_successful_operations_total", -60),
                point("core_successful_operations_total", -30, 2.0),
                point("core_unexpected_errors_total", -10),
                json.dumps({"type": "Metric", "metric": "core_successful_operations_total"}),
                "not json at all",
            ]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            result = MODULE.summarize(path, 120, 10 * 1024 * 1024, now=NOW)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["successful"], 3.0)
            self.assertEqual(result["unexpectedErrors"], 1.0)
            self.assertAlmostEqual(result["latestPointAgeSeconds"], 10.0, places=1)

    def test_tail_read_drops_partial_first_line(self) -> None:
        with TemporaryDirectory() as raw:
            path = Path(raw) / "raw.json"
            filler = point("core_successful_operations_total", -400)
            recent = point("core_successful_operations_total", -5)
            path.write_text(filler + "\n" + recent + "\n", encoding="utf-8")
            tail_bytes = len(recent) + 10
            result = MODULE.summarize(path, 120, tail_bytes, now=NOW)
            self.assertEqual(result["successful"], 1.0)

    def test_boolean_values_are_ignored(self) -> None:
        with TemporaryDirectory() as raw:
            path = Path(raw) / "raw.json"
            payload = json.dumps(
                {
                    "type": "Point",
                    "metric": "core_successful_operations_total",
                    "data": {"time": "2026-08-12T00:00:00Z", "value": True},
                }
            )
            path.write_text(payload + "\n", encoding="utf-8")
            result = MODULE.summarize(path, 10 ** 9, 1024, now=NOW)
            self.assertEqual(result["successful"], 0.0)


if __name__ == "__main__":
    unittest.main()
