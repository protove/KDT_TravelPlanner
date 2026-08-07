import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[2] / "scripts/loadtest/evaluate-recovery.py"
SPEC = importlib.util.spec_from_file_location("evaluate_recovery", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class EvaluateRecoveryTest(unittest.TestCase):
    def test_timestamp_accepts_k6_nanosecond_precision(self):
        parsed = MODULE.timestamp("2026-01-01T00:00:00.123456789Z")

        expected = datetime(2026, 1, 1, 0, 0, 0, 123456, tzinfo=timezone.utc).timestamp()
        self.assertAlmostEqual(parsed, expected, places=6)

    def test_successful_two_minute_window_reaches_t6_within_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            start = datetime(2026, 1, 1, tzinfo=timezone.utc)
            points = []
            for bucket in range(0, 170, 10):
                point_time = (start + timedelta(seconds=bucket)).isoformat().replace("+00:00", "Z")
                points.extend([
                    {"type": "Point", "metric": "http_req_duration", "data": {"time": point_time, "value": 100}},
                    {"type": "Point", "metric": "successful_requests", "data": {"time": point_time, "value": 10}},
                    {"type": "Point", "metric": "unexpected_errors", "data": {"time": point_time, "value": 0}},
                    {"type": "Point", "metric": "contract_fail", "data": {"time": point_time, "value": 0}},
                ])
            (run_dir / "raw.json").write_text("\n".join(json.dumps(point) for point in points) + "\n", encoding="utf-8")
            event_time = (start + timedelta(seconds=40)).isoformat().replace("+00:00", "Z")
            (run_dir / "operations.jsonl").write_text(
                json.dumps({"ts": event_time, "event": "T1", "detail": "test", "actor": "test"}) + "\n",
                encoding="utf-8",
            )

            args = type("Args", (), {
                "run_dir": run_dir,
                "warmup_sec": 20,
                "window_sec": 120,
                "budget_sec": 600,
                "bucket": 10,
                "recovery_event": "T1",
            })()
            result = MODULE.evaluate(args)

            self.assertTrue(result["withinBudget"])
            self.assertEqual(result["recoveryEvent"], "T1")
            self.assertEqual(result["recoverySeconds"], 120.0)
            self.assertTrue((run_dir / "verdict.json").exists())

    def test_empty_or_missing_point_stream_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            (run_dir / "raw.json").write_text("not-json\n", encoding="utf-8")
            args = type("Args", (), {
                "run_dir": run_dir,
                "warmup_sec": 20,
                "window_sec": 120,
                "budget_sec": 600,
                "bucket": 10,
                "recovery_event": "T1",
            })()

            with self.assertRaises(ValueError):
                MODULE.evaluate(args)


if __name__ == "__main__":
    unittest.main()
