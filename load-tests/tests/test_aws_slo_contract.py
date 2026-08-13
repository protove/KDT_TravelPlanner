from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]
CONTRACT_PATH = ROOT / "load-tests/aws/contracts/slo-v1.0.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


SLO = load_module("slo_contract", ROOT / "scripts/loadtest/aws/slo_contract.py")
FREEZE = load_module("build_freeze_input_manifest", ROOT / "scripts/loadtest/aws/build-freeze-input-manifest.py")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class SloBoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = SLO.load_contract(CONTRACT_PATH)

    def test_frozen_values_and_comparator_boundaries(self):
        self.assertTrue(SLO.satisfies(self.contract, "p95Ms", 500))
        self.assertFalse(SLO.satisfies(self.contract, "p95Ms", 500.001))
        self.assertTrue(SLO.satisfies(self.contract, "successRate", 0.99))
        self.assertFalse(SLO.satisfies(self.contract, "successRate", 0.989999))
        self.assertTrue(SLO.satisfies(self.contract, "unexpectedErrorRate", 0.009999))
        self.assertFalse(SLO.satisfies(self.contract, "unexpectedErrorRate", 0.01))
        self.assertTrue(SLO.satisfies(self.contract, "baselineContractFailureRate", 0.009999))
        self.assertFalse(SLO.satisfies(self.contract, "baselineContractFailureRate", 0.01))
        self.assertTrue(SLO.satisfies(self.contract, "recoveryContractFailureRate", 0))
        self.assertFalse(SLO.satisfies(self.contract, "recoveryContractFailureRate", 0.000001))
        self.assertTrue(SLO.satisfies(self.contract, "capacityFloorRatio", 0.9))
        self.assertTrue(SLO.satisfies(self.contract, "recoveryBudgetSeconds", 600))
        self.assertFalse(SLO.satisfies(self.contract, "recoveryBudgetSeconds", 600.001))

    def test_spike_is_diagnostic_only(self):
        self.assertEqual(self.contract["spike"]["classification"], "diagnostic")
        self.assertFalse(self.contract["spike"]["sloPassRequired"])

    def test_bool_is_not_accepted_as_numeric_metric(self):
        self.assertFalse(SLO.satisfies(self.contract, "p95Ms", True))
        self.assertTrue(SLO.satisfies(self.contract, "runnerBottleneckSuspected", False))


class FreezeInputManifestTest(unittest.TestCase):
    def fixture(self, root: Path):
        profile = root / "ec2-b01.json"
        candidate = root / "baseline-candidate.json"
        d005 = root / "d005-arrival-rate.json"
        spike = root / "k6/spike"
        profile.write_text(
            '{"profileVersion":"fixture","scenarios":{"spike":{"hold":"1m","preAllocatedVUs":20,"maxVUs":80}}}\n',
            encoding="utf-8",
        )
        candidate_payload = {"passed": True, "confirmedRate": 20, "baselineCandidate": {"frozen": True}}
        write_json(candidate, candidate_payload)
        profile_sha = hashlib.sha256(profile.read_bytes()).hexdigest()
        candidate_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
        write_json(d005, {
            "runId": "aws-b01-fixture",
            "arrivalRate": 20,
            "sourceCommitSha": "a" * 40,
            "profileSha256": profile_sha,
            "baselineCandidateSha256": candidate_sha,
        })
        write_json(spike / "metadata.json", {
            "runId": "aws-b01-fixture-spike",
            "effectiveInputs": {
                "scenario": "spike",
                "profileSha256": profile_sha,
                "classification": "diagnostic",
                "baselineRate": 20,
                "peakRateMultiplier": 1.5,
                "peakRate": 30,
                "hold": "1m",
                "preAllocatedVUs": 20,
                "maxVUs": 80,
                "timeUnit": "1s",
            },
        })
        return profile, candidate, d005, spike

    def test_manifest_hashes_effective_inputs_without_circular_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            profile, candidate, d005, spike = self.fixture(Path(directory))
            manifest = FREEZE.build_manifest(
                run_id="aws-b01-fixture",
                source_sha="a" * 40,
                contract_path=CONTRACT_PATH,
                b01_profile=profile,
                baseline_candidate=candidate,
                d005_rate_file=d005,
                spike_run_dir=spike,
            )
            self.assertEqual(manifest["schemaVersion"], "aws-d006-freeze-input-manifest-v1")
            self.assertEqual(manifest["spike"]["classification"], "diagnostic")
            self.assertEqual(manifest["inputs"]["d005ArrivalRate"], 20.0)
            self.assertTrue(FREEZE.verify_manifest(manifest, contract_path=CONTRACT_PATH))
            tampered = json.loads(json.dumps(manifest))
            tampered["inputs"]["d005ArrivalRate"] = 21
            with self.assertRaises(FREEZE.FreezeInputError):
                FREEZE.verify_manifest(tampered, contract_path=CONTRACT_PATH)

    def test_manifest_rejects_stale_spike_rate(self):
        with tempfile.TemporaryDirectory() as directory:
            profile, candidate, d005, spike = self.fixture(Path(directory))
            payload = json.loads((spike / "metadata.json").read_text(encoding="utf-8"))
            payload["effectiveInputs"]["baselineRate"] = 19
            payload["effectiveInputs"]["peakRate"] = 28.5
            write_json(spike / "metadata.json", payload)
            with self.assertRaises(FREEZE.FreezeInputError):
                FREEZE.build_manifest(
                    run_id="aws-b01-fixture",
                    source_sha="a" * 40,
                    contract_path=CONTRACT_PATH,
                    b01_profile=profile,
                    baseline_candidate=candidate,
                    d005_rate_file=d005,
                    spike_run_dir=spike,
                )

    def test_manifest_derives_effective_peak_from_legacy_spike_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            profile, candidate, d005, spike = self.fixture(Path(directory))
            metadata = json.loads((spike / "metadata.json").read_text(encoding="utf-8"))
            metadata.pop("effectiveInputs")
            metadata["rate"] = 20
            write_json(spike / "metadata.json", metadata)
            (spike / "stdout.log").write_text(
                "scenarios: (100.00%) 1 scenario, 3m max duration\n"
                "* spike: Up to 30.00 iterations/s for 3m0s over 5 stages\n",
                encoding="utf-8",
            )
            manifest = FREEZE.build_manifest(
                run_id="aws-b01-fixture",
                source_sha="a" * 40,
                contract_path=CONTRACT_PATH,
                b01_profile=profile,
                baseline_candidate=candidate,
                d005_rate_file=d005,
                spike_run_dir=spike,
            )
            self.assertEqual(manifest["spike"]["effectiveConfig"]["peakRate"], 30.0)
            self.assertEqual(
                manifest["spike"]["effectiveConfig"]["provenance"],
                "derived-from-legacy-spike-metadata-and-stdout",
            )

    def test_manifest_rejects_tampered_spike_effective_config(self):
        with tempfile.TemporaryDirectory() as directory:
            profile, candidate, d005, spike = self.fixture(Path(directory))
            manifest = FREEZE.build_manifest(
                run_id="aws-b01-fixture",
                source_sha="a" * 40,
                contract_path=CONTRACT_PATH,
                b01_profile=profile,
                baseline_candidate=candidate,
                d005_rate_file=d005,
                spike_run_dir=spike,
            )
            manifest["spike"]["effectiveConfig"]["peakRate"] = 999.0
            with self.assertRaises(FREEZE.FreezeInputError):
                FREEZE.verify_manifest(manifest, contract_path=CONTRACT_PATH)

    def test_manifest_rejects_tampered_version_or_run_id(self):
        with tempfile.TemporaryDirectory() as directory:
            profile, candidate, d005, spike = self.fixture(Path(directory))
            manifest = FREEZE.build_manifest(
                run_id="aws-b01-fixture",
                source_sha="a" * 40,
                contract_path=CONTRACT_PATH,
                b01_profile=profile,
                baseline_candidate=candidate,
                d005_rate_file=d005,
                spike_run_dir=spike,
            )
            manifest["sloVersion"] = "bogus"
            with self.assertRaises(FREEZE.FreezeInputError):
                FREEZE.verify_manifest(manifest, contract_path=CONTRACT_PATH)
            manifest["sloVersion"] = "v1.0-frozen"
            manifest["runId"] = ""
            with self.assertRaises(FREEZE.FreezeInputError):
                FREEZE.verify_manifest(manifest, contract_path=CONTRACT_PATH)


if __name__ == "__main__":
    unittest.main()
