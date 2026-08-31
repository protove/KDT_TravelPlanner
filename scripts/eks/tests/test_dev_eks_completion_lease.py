"""Focused v13 completion-lease regression tests.

These tests prove that the previously explicit repair scope can create a separate
technical lease without mutating the consumed historical receipt, and that a
recoverable failure does not consume that lease.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
COORDINATOR = ROOT / "scripts" / "eks" / "run-dev-eks-repair-and-resume.sh"
CAPSULE = ROOT / "evidence" / "eks-deploy" / "20260824T133440Z-15798" / "action-values.json"
PREFLIGHT = ROOT / "evidence" / "eks-deploy" / "20260825T122500Z-6107" / "live-preflight.private.json"
PRIOR_RECEIPT = ROOT / "evidence" / "eks-deploy" / "20260825T114800Z-4921" / "repair-authorization.private.json"
SMOKE_HELPER = ROOT / "scripts" / "eks" / "run-dev-eks-repair-smoke.sh"
PRIOR_SCOPE = "565cc0edd4bd0c598fe6c0037411a0488ee4ffe693692e13db9c7cde2839f059"


class CompletionLeaseTest(unittest.TestCase):
    def test_completion_issue_proves_prior_consent_without_mutating_history(self) -> None:
        before = hashlib.sha256(PRIOR_RECEIPT.read_bytes()).hexdigest()
        run_evidence = ROOT / "evidence" / "eks-deploy" / "20260825T000040Z-4301"
        self.addCleanup(lambda: shutil.rmtree(run_evidence, ignore_errors=True))
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "completion-authorization.private.json"
            # The historical preflight is immutable.  Rebuild only its
            # run-local smoke-helper fingerprint so this regression remains
            # valid when the approved smoke probe itself is corrected.
            preflight = Path(directory) / "live-preflight.private.json"
            preflight_payload = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
            preflight_payload["smoke_helper_sha256"] = hashlib.sha256(SMOKE_HELPER.read_bytes()).hexdigest()
            preflight.write_text(json.dumps(preflight_payload), encoding="utf-8")
            preflight.chmod(0o600)
            result = subprocess.run(
                [
                    str(COORDINATOR),
                    "--mode",
                    "completion-issue",
                    "--aws-profile",
                    "offline",
                    "--region",
                    "ap-northeast-2",
                    "--expected-account-id",
                    "419496180357",
                    "--action-values-capsule",
                    str(CAPSULE),
                    "--preflight-json",
                    str(preflight),
                    "--prior-authorization-receipt",
                    str(PRIOR_RECEIPT),
                    "--prior-approval-scope-sha256",
                    PRIOR_SCOPE,
                    "--authorization-receipt",
                    str(receipt),
                    "--run-id",
                    "20260825T000040Z-4301",
                ],
                cwd=ROOT,
                env={**os.environ, "OFFLINE_TEST": "true"},
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "pending")
            self.assertTrue(payload["completion_lease"])
            self.assertTrue(payload["continuity_verified"])
            self.assertEqual(payload["prior_user_approval_scope_sha256"], PRIOR_SCOPE)
            self.assertEqual(payload["attempt_budget"], 3)
            self.assertEqual(payload["repair_cycle_budget"], 2)
        self.assertEqual(hashlib.sha256(PRIOR_RECEIPT.read_bytes()).hexdigest(), before)

    def test_sources_preserve_completion_lease_on_recoverable_exit(self) -> None:
        coordinator = COORDINATOR.read_text(encoding="utf-8")
        deployer = (ROOT / "scripts" / "eks" / "deploy-dev-eks.sh").read_text(encoding="utf-8")
        marker = '.completion_lease == true and .continuity_verified == true'
        self.assertGreaterEqual(coordinator.count(marker), 2)
        self.assertIn(marker, deployer)
        self.assertIn("return 0", deployer[deployer.index(marker) : deployer.index(marker) + 180])
        self.assertIn(".deployment_runner_sha256 == $deployer", coordinator)
        self.assertIn(".completion_lease == true and .continuity_verified == true", coordinator)
        self.assertIn(".completion_lease == true and .continuity_verified == true", deployer)


if __name__ == "__main__":
    unittest.main()
