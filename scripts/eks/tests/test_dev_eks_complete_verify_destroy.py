"""Synthetic completion gate for the v15 deploy -> prove -> destroy contract."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
LIFECYCLE = ROOT / "scripts/eks/run-dev-eks-ephemeral-lifecycle.sh"
VERIFIER = ROOT / "scripts/eks/verify-dev-eks-destroyed.py"
DEPLOY = ROOT / "scripts/eks/deploy-dev-eks.sh"


class CompleteVerifyDestroyContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lifecycle = LIFECYCLE.read_text(encoding="utf-8")
        cls.verifier = VERIFIER.read_text(encoding="utf-8")
        cls.deploy = DEPLOY.read_text(encoding="utf-8")

    def test_destroy_is_disarmed_until_full_live_success_freeze(self) -> None:
        self.assertIn("FULL_SUCCESS_EVIDENCE_FROZEN=false", self.lifecycle)
        self.assertIn("DESTROY_ARMED=false", self.lifecycle)
        self.assertIn("FULL_SUCCESS_EVIDENCE_FROZEN=true", self.lifecycle)
        self.assertIn("DESTROY_ARMED=true", self.lifecycle)
        cleanup = self.lifecycle.split("run_cleanup_and_destroy()", 1)[1].split("finalize()", 1)[0]
        self.assertIn('[[ "$FULL_SUCCESS_EVIDENCE_FROZEN" == true && "$DESTROY_ARMED" == true ]]', cleanup)
        smoke = self.lifecycle.split("run_smoke()", 1)[1].split("run_cleanup_and_destroy()", 1)[0]
        self.assertLess(smoke.index("capture_full_success_evidence"), smoke.index("return 0"))
        finalize = self.lifecycle.split("finalize()", 1)[1]
        self.assertIn('FULL_SUCCESS_EVIDENCE_FROZEN" == true', finalize)
        self.assertIn('DESTROY_ARMED" == true', finalize)

    def test_destroy_plan_and_native_verification_are_exact_and_protected(self) -> None:
        self.assertIn('"preview", "apply-destroy", "verify"', self.verifier)
        self.assertIn('actions != ["delete"]', self.verifier)
        self.assertIn("protected-states-before", self.verifier)
        self.assertIn("verify_protected_state_fingerprints", self.verifier)
        self.assertIn("destroy-mode no-change", self.verifier)
        self.assertIn("destroy-plan-preview.private.json", self.lifecycle)
        self.assertNotIn("terraform destroy -auto-approve", self.lifecycle)
        self.assertNotIn("terraform destroy -auto-approve", self.verifier)

    def test_v15_autonomous_receipt_is_current_and_cloudflare_is_excluded(self) -> None:
        self.assertIn("PLAN_VERSION=15", self.lifecycle)
        self.assertIn("handoff-v15.yaml", self.lifecycle)
        self.assertIn("destroy before full live success", self.lifecycle)
        self.assertIn("Cloudflare mutation", self.lifecycle)
        self.assertNotIn("api.cloudflare", self.lifecycle)
        self.assertIn("plan_version == $version", self.deploy)


if __name__ == "__main__":
    unittest.main()
