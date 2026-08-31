from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/loadtest/aws/actions/start-recovery-rollout.py"
SPEC = importlib.util.spec_from_file_location("start_recovery_rollout", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class RecoveryRolloutActionTests(unittest.TestCase):
    def request(self, root: Path) -> MODULE.RolloutRequest:
        plan = root / "fault.tfplan"
        plan.write_bytes(b"fixture-plan")
        approval = root / "approval.json"
        approval.write_text(json.dumps({"approved": True, "approvedBy": "owner"}), encoding="utf-8")
        return MODULE.RolloutRequest(
            "scrum43-r03-eks-fixture", "R-03", "eks", "dev-eks", "ap-northeast-2",
            plan, approval, root / "evidence", root,
        )

    def test_plan_is_read_only_and_digest_bound(self):
        with tempfile.TemporaryDirectory() as raw:
            result = MODULE.run_action(self.request(Path(raw)), mode="plan")
            self.assertEqual(result["mode"], "plan")
            self.assertFalse(result["mutation"]["performed"])
            self.assertEqual(len(result["planSha256"]), 64)

    def test_rejects_auto_approve_command(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            request = self.request(root)
            with self.assertRaisesRegex(MODULE.RecoveryRolloutError, "auto-approve"):
                MODULE.run_action(request, mode="execute", terraform=["terraform", "apply", "-auto-approve", str(request.plan_file)])

    def test_source_contains_no_post_action_mutation_commands(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("set-desired-capacity", "kubectl apply", "terraform destroy"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
