import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/loadtest/aws/export-aws-recovery-evidence.py"
SPEC = importlib.util.spec_from_file_location("export_aws_recovery_evidence", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class RecoveryEvidenceFixtureTest(unittest.TestCase):
    def fixture(self) -> Path:
        root = Path(tempfile.mkdtemp())
        start = datetime(2026, 8, 12, 8, 0, tzinfo=timezone.utc)
        run_id = "aws-r05-fixture-001"
        write_json(root / "metadata.json", {
            "runId": run_id,
            "scenarioId": "AWS-RECOVERY",
            "startedAtUtc": start.isoformat().replace("+00:00", "Z"),
            "endedAtUtc": (start + timedelta(seconds=180)).isoformat().replace("+00:00", "Z"),
        })
        events = []
        for offset, name in enumerate(MODULE.REQUIRED_EVENTS):
            events.append({
                "ts": (start + timedelta(seconds=offset * 10)).isoformat().replace("+00:00", "Z"),
                "event": name,
                "detail": "fixture",
                "actor": "test",
            })
        (root / "operations.jsonl").write_text("\n".join(json.dumps(item) for item in events) + "\n", encoding="utf-8")
        required = json.loads((ROOT / "load-tests/aws/profiles/ec2-recovery.json").read_text(encoding="utf-8"))["observability"]["required"]
        write_json(root / "monitoring/required-metrics.json", {
            "metrics": {name: {"status": "collected", "datapointCount": 1} for name in required}
        })
        write_json(root / "aws/restoration-state.json", {
            "status": "verified", "desiredCapacity": 2, "minSize": 2, "maxSize": 4,
            "launchTemplateVersion": "7",
            "normalImageDigest": "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/backend@sha256:" + "a" * 64,
            "capacityRestored": True, "scalingPolicyEnabled": True,
        })
        return root

    def test_reads_and_orders_t0_to_t6(self):
        root = self.fixture()
        try:
            events = MODULE.read_recovery_events(root / "operations.jsonl")
            self.assertEqual(list(events), list(MODULE.REQUIRED_EVENTS))
            timing = MODULE.build_recovery_timing(events)
            self.assertEqual(timing["detectorToRollbackSeconds"], 10.0)
            self.assertEqual(timing["T4ToT6Seconds"], 20.0)
        finally:
            import shutil
            shutil.rmtree(root)

    def test_missing_event_is_rejected(self):
        root = self.fixture()
        try:
            path = root / "operations.jsonl"
            lines = [line for line in path.read_text(encoding="utf-8").splitlines() if '"event": "T4"' not in line]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(MODULE.RecoveryExportError):
                MODULE.read_recovery_events(path)
        finally:
            import shutil
            shutil.rmtree(root)

    def test_required_metrics_distinguish_missing_and_empty_is_valid(self):
        required = ["core_operations_total", "http_5xx", "aws_target_health"]
        result = MODULE.validate_required_metrics({"metrics": {
            "core_operations_total": {"status": "collected", "datapointCount": 1},
            "http_5xx": {"status": "collected", "datapointCount": 0},
            "aws_target_health": {"status": "collected", "datapointCount": 0},
        }}, required, {"http_5xx"})
        self.assertEqual(result["status"], "INVALID_OBSERVABILITY_EVIDENCE")
        self.assertEqual(result["emptyIsValid"], ["http_5xx"])
        self.assertEqual(result["emptyRequired"], ["aws_target_health"])

    def test_restoration_invariant_requires_digest_and_capacity_restore(self):
        root = self.fixture()
        try:
            result = MODULE.validate_restoration_invariant(root / "aws/restoration-state.json")
            self.assertEqual(result["status"], "verified")
            payload = json.loads((root / "aws/restoration-state.json").read_text(encoding="utf-8"))
            payload["capacityRestored"] = False
            (root / "aws/restoration-state.json").write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(MODULE.RecoveryExportError):
                MODULE.validate_restoration_invariant(root / "aws/restoration-state.json")
        finally:
            import shutil
            shutil.rmtree(root)

    def test_verdict_is_required_and_bound_to_run(self):
        root = self.fixture()
        try:
            write_json(root / "recovery-verdict.json", {
                "status": "PASSED", "runId": "aws-r05-fixture-001", "scenarioId": "AWS-RECOVERY",
                **{name: "2026-08-12T08:00:00Z" for name in ("T0", "T1", "T2", "T3", "T4", "T5", "T6", "RUN_END")},
            })
            result = MODULE.validate_verdict(root / "recovery-verdict.json", "aws-r05-fixture-001")
            self.assertEqual(result["status"], "PASSED")
            payload = json.loads((root / "recovery-verdict.json").read_text(encoding="utf-8"))
            payload["runId"] = "aws-r01-other"
            (root / "recovery-verdict.json").write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(MODULE.RecoveryExportError):
                MODULE.validate_verdict(root / "recovery-verdict.json", "aws-r05-fixture-001")
        finally:
            import shutil
            shutil.rmtree(root)

    def test_run_id_separates_recovery_scenarios(self):
        root = self.fixture()
        try:
            payload = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
            payload["runId"] = "aws-b01-fixture-001"
            (root / "metadata.json").write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(MODULE.RecoveryExportError):
                MODULE.resolve_run(root, "aws-r05-fixture-001")
        finally:
            import shutil
            shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
