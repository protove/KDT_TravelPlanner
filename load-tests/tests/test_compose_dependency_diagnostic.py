from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]
PROFILE = ROOT / "load-tests/diagnostic-profile.json"
RUNNER = ROOT / "scripts/loadtest/run-compose-dependency-diagnostic.py"
SPEC = importlib.util.spec_from_file_location("compose_diagnostic_runner", RUNNER)
assert SPEC and SPEC.loader
RUNNER_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER_MODULE)
SAFETY = ROOT / "scripts/loadtest/verify-compose-diagnostic-evidence.py"
SAFETY_SPEC = importlib.util.spec_from_file_location("compose_diagnostic_safety", SAFETY)
assert SAFETY_SPEC and SAFETY_SPEC.loader
SAFETY_MODULE = importlib.util.module_from_spec(SAFETY_SPEC)
SAFETY_SPEC.loader.exec_module(SAFETY_MODULE)


class ComposeDependencyDiagnosticContractTest(unittest.TestCase):
    def test_profile_has_four_variants_and_controlled_order_matrix(self) -> None:
        profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        self.assertEqual({variant["id"] for variant in profile["variants"]}, set(RUNNER_MODULE.VARIANT_IDS))
        self.assertEqual(profile["profile"]["ratePerSecond"], 20)
        for replicate in ("1", "2", "3"):
            self.assertEqual(len(profile["orderByReplicate"][replicate]), 4)
            self.assertEqual(set(profile["orderByReplicate"][replicate]), set(RUNNER_MODULE.VARIANT_IDS))

    def test_variant_mix_sums_to_one_hundred(self) -> None:
        profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        for variant in profile["variants"]:
            self.assertEqual(sum(variant["requestMix"].values()), 100, variant["id"])

    def test_runner_rejects_non_diagnostic_project(self) -> None:
        with self.assertRaises(RUNNER_MODULE.DiagnosticError):
            RUNNER_MODULE.slug("!!!")

    def test_required_artifacts_exist(self) -> None:
        for relative in (
            "load-tests/k6/scenarios/dependency-diagnostic.js",
            "load-tests/k6/flows/dependency-diagnostic.js",
            "scripts/loadtest/seed-compose-diagnostic-data.py",
            "scripts/loadtest/run-k6-compose-diagnostic.sh",
            "compose.monitoring.diagnostic.yml",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_evidence_safety_accepts_replicate_capture_layout(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            evidence_root = Path(directory)
            for replicate in ("replicate-1", "replicate-2", "replicate-3"):
                capture_dir = evidence_root / replicate / "grafana"
                capture_dir.mkdir(parents=True)
                (capture_dir / "capture-status.json").write_text(
                    json.dumps({"status": "captured"}), encoding="utf-8"
                )
            for required in ("campaign-metadata.json", "campaign-manifest.json", "summary.json", "verdict.json"):
                (evidence_root / required).write_text("{}", encoding="utf-8")

            report = SAFETY_MODULE.verify(evidence_root, require_captures=True)

            self.assertEqual(report["status"], "pass")


if __name__ == "__main__":
    unittest.main()
