from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/loadtest/summarize-compose-timeline-order-optimization.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OPT = load_module("scrum41_timeline_optimization", SCRIPT)


EXPECTED_ORDER = {
    1: [(mode, count) for count in (3, 10, 25, 50, 100, 200) for mode in ("noop", "reverse")],
    2: [(mode, count) for count in (200, 100, 50, 25, 10, 3) for mode in ("reverse", "noop")],
    3: [("noop", 25), ("reverse", 25), ("reverse", 3), ("noop", 3), ("noop", 100), ("reverse", 100), ("reverse", 10), ("noop", 10), ("noop", 200), ("reverse", 200), ("reverse", 50), ("noop", 50)],
}


class TimelineOrderOptimizationTest(unittest.TestCase):
    def stages(self, *, reverse_calls: float = 1.0, rows_factor: float = 1.0, valid: bool = True, latency: bool = True):
        stages = []
        for replicate in (1, 2, 3):
            for sequence, (mode, count) in enumerate(EXPECTED_ORDER[replicate], start=1):
                is_reverse = mode == "reverse"
                p95 = None if not latency and is_reverse else (20.0 if count == 3 else 40.0 if is_reverse else 30.0)
                db = None if not latency and is_reverse else (2.0 if count == 3 else 5.0 if is_reverse else 1.0)
                calls = 0.0 if not is_reverse else reverse_calls
                rows = 0.0 if not is_reverse else count * rows_factor
                stages.append({
                    "replicate": replicate,
                    "sequence": sequence,
                    "mode": mode,
                    "itemCount": count,
                    "valid": valid,
                    "apiP95Ms": p95,
                    "totalDbExecMsPerRequest": db,
                    "totalSqlCallsPerRequest": 7.0,
                    "timelineUpdateCallsPerRequest": calls,
                    "timelineUpdateRowsPerRequest": rows,
                    "stats": {"deadlocks": 0.0},
                    "validity": {"contractFailureRate": 0.0, "genericContractFailureRate": 0.0, "httpFailedRate": 0.0, "unexpectedErrorRate": 0.0, "droppedIterations": 0.0},
                })
        return stages

    def baseline_stages(self):
        stages = self.stages(reverse_calls=300.0)
        for stage in stages:
            if stage["mode"] == "reverse":
                stage["totalSqlCallsPerRequest"] = 307.0 if stage["itemCount"] == 200 else 10.0
                stage["apiP95Ms"] = 83.106 if stage["itemCount"] == 200 else 20.0
                stage["totalDbExecMsPerRequest"] = 13.3254025 if stage["itemCount"] == 200 else 2.0
                stage["timelineUpdateRowsPerRequest"] = stage["itemCount"]
        return stages

    def manifests(self):
        digests = {key: f"{key}-digest" for key in ("profile", "effectiveProfile", "overlay", "prometheus", "dashboard", "k6Image", "pushgatewayImage")}
        profile = {"itemCounts": [3, 10, 25, 50, 100, 200], "modes": ["noop", "reverse"], "warmupIterations": 4, "measuredIterations": 30, "virtualUsers": 1, "pacingSeconds": 0.25, "replicates": 3, "orderByReplicate": {str(rep): {"itemCounts": [], "modeOrder": []} for rep in (1, 2, 3)}}
        order = {str(rep): [[mode, count] for mode, count in entries] for rep, entries in EXPECTED_ORDER.items()}
        profile["orderByReplicate"] = order
        return {"campaignId": "baseline", "sourceDigests": digests, "profile": profile, "stageOrder": order}, {"campaignId": "optimized", "sourceDigests": digests.copy(), "profile": profile, "stageOrder": order}

    def verdict(self, stages, *, latency=True):
        baseline = self.baseline_stages()
        baseline_manifest, optimized_manifest = self.manifests()
        _, payload = OPT.evaluate(stages, baseline, smoke=False, errors=[], baseline_errors=[], optimized_manifest=optimized_manifest, baseline_manifest=baseline_manifest)
        return payload["verdict"]

    def test_fixed_rules_cover_success_branch(self):
        self.assertEqual(self.verdict(self.stages()), "confirmed-round-trip-reduction")

    def test_functional_only_branch_is_deterministic_when_latency_missing(self):
        self.assertEqual(self.verdict(self.stages(latency=False)), "confirmed-sql-reduction-latency-inconclusive")

    def test_insufficient_branch_does_not_change_thresholds(self):
        self.assertEqual(self.verdict(self.stages(reverse_calls=2.0)), "optimization-insufficient")

    def test_invalid_branch_is_fail_closed(self):
        self.assertEqual(self.verdict(self.stages(valid=False)), "inconclusive-invalid-evidence")

    def test_source_digest_mismatch_is_rejected(self):
        baseline_manifest, optimized_manifest = self.manifests()
        optimized_manifest["sourceDigests"]["overlay"] = "changed"
        with self.assertRaises(OPT.OptimizationError):
            OPT.validate_optimized_provenance_from_manifests(optimized_manifest, baseline_manifest)

    def test_effective_profile_digest_mismatch_is_rejected_for_full(self):
        baseline_manifest, optimized_manifest = self.manifests()
        optimized_manifest["sourceDigests"]["effectiveProfile"] = "changed"
        with self.assertRaises(OPT.OptimizationError):
            OPT.validate_optimized_provenance_from_manifests(optimized_manifest, baseline_manifest)

    def test_smoke_allows_smaller_effective_profile(self):
        baseline_manifest, optimized_manifest = self.manifests()
        optimized_manifest["sourceDigests"]["effectiveProfile"] = "smoke-profile"
        OPT.validate_optimized_provenance_from_manifests(optimized_manifest, baseline_manifest, smoke=True)

    def test_replicate_stage_matrix_missing_or_duplicate_is_invalid(self):
        stages = self.stages()
        stages[-1] = dict(stages[0])
        self.assertEqual(self.verdict(stages), "inconclusive-invalid-evidence")


if __name__ == "__main__":
    unittest.main()
