from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/loadtest/run-compose-current-feature-validation.py"
SPEC = importlib.util.spec_from_file_location("scrum80_local_runner", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ComposeCurrentFeatureValidationTest(unittest.TestCase):
    def test_contract_binds_exact_backend_and_all_operations(self):
        self.assertIn("@sha256:d11e78", MODULE.BACKEND_IMAGE)
        self.assertNotIn(MODULE.FORBIDDEN_BACKEND_DIGEST, MODULE.BACKEND_IMAGE)
        self.assertEqual(len(MODULE.EXPECTED_OPERATIONS), 26)
        self.assertEqual(len(set(MODULE.EXPECTED_OPERATIONS)), 26)

    def test_parser_keeps_short_local_defaults_and_explicit_modes(self):
        args = MODULE.parse_args(["all"])
        self.assertEqual(args.rate, 16)
        self.assertEqual(args.duration, "180s")
        self.assertEqual(args.warmup, "30s")
        self.assertEqual(MODULE.parse_args(["smoke"]).mode, "smoke")

    def test_project_id_is_compose_safe(self):
        self.assertEqual(MODULE.safe_id("SCRUM80-20260901T112500Z"), "scrum80-20260901t112500z")

    def test_evaluator_requires_all_current_feature_operations_and_zero_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.json"
            operations = {
                operation: {"observedCount": 1} for operation in MODULE.EXPECTED_OPERATIONS
            }
            path.write_text(json.dumps({
                "operationMix": {"totalSelections": 3360, "operations": operations},
                "metrics": {
                    "checks": {"rate": 1},
                    "dropped_iterations": {"count": 0},
                    "unexpected_errors": {"count": 0},
                    "contract_fail": {"count": 0},
                    "http_req_duration": {"p(95)": 42},
                },
            }), encoding="utf-8")
            verdict = MODULE.evaluate_summary(path, "baseline", target_rate=16, measured_seconds=180, warmup_seconds=30)
            self.assertTrue(verdict["pass"])
            self.assertTrue(verdict["p95Informational"])

    def test_override_is_no_build_and_pins_mock(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"--no-build"', source)
        self.assertNotIn('"    build: null\\n"', source)
        self.assertIn("MOCK_IMAGE", source)
        self.assertNotIn("docker build", source)


if __name__ == "__main__":
    unittest.main()
