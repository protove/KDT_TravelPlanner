"""Offline contracts for the SCRUM-53 creation-only coordinator."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from scripts.eks.tests.test_deploy_dev_eks import OperatorOrchestratorContractTest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "eks" / "run-dev-eks-create-and-deploy.sh"
DEPLOY = ROOT / "scripts" / "eks" / "deploy-dev-eks.sh"
CAPSULE = ROOT / "evidence" / "eks-deploy" / "20260824T133440Z-15798" / "action-values.json"
BACKEND_CONFIG_SHA256 = hashlib.sha256((ROOT / "infra" / "environments" / "dev-eks" / "backend.hcl").read_bytes()).hexdigest()
V9_HANDOFF = ROOT / ".codex" / "plans" / "dev-eks-deployment-automation" / "handoff-v9.yaml"
V9_MANIFEST = ROOT / ".codex" / "plans" / "dev-eks-deployment-automation" / "plan-v9.yaml"
V9_MANIFEST_SHA256 = hashlib.sha256(V9_MANIFEST.read_bytes()).hexdigest()
V9_HANDOFF_SHA256 = hashlib.sha256(V9_HANDOFF.read_bytes()).hexdigest()


class CreateCoordinatorContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SCRIPT.read_text(encoding="utf-8")
        cls.deploy_source = DEPLOY.read_text(encoding="utf-8")

    def _preflight_fake(self, root: Path, *, deny_simulation: bool = False, bad_tag: bool = False) -> tuple[Path, str]:
        fake_bin = root / "bin"
        fake_bin.mkdir()
        digest = json.loads(CAPSULE.read_text(encoding="utf-8"))["backend_image"].split("@", 1)[1]
        stack = "wrong-stack" if bad_tag else "dev-eks"
        iam_decision = "implicitDeny" if deny_simulation else "allowed"
        policy = json.dumps({
            "Version": "2012-10-17",
            "Statement": [
                {"Effect": "Allow", "Action": "ssm:SendCommand", "Resource": "arn:aws:ec2:ap-northeast-2:419496180357:instance/*", "Condition": {"StringEquals": {"ssm:resourceTag/Environment": "dev", "ssm:resourceTag/Stack": stack, "ssm:resourceTag/Name": "kdt-travelplanner-dev-eks-bastion"}}},
                {"Effect": "Allow", "Action": "ssm:SendCommand", "Resource": "arn:aws:ssm:ap-northeast-2::document/AWS-RunShellScript"},
                {"Effect": "Allow", "Action": "ssm:GetCommandInvocation", "Resource": "*", "Condition": {"StringEquals": {"aws:RequestedRegion": "ap-northeast-2"}}},
            ],
        })
        aws_script = (
            "#!/usr/bin/env bash\n"
            "if [[ \"$*\" == *'sts get-caller-identity'* && \"$*\" == *'--query Arn'* ]]; then printf 'arn:aws:sts::419496180357:assumed-role/AWSReservedSSO_KDT-Terraform-Operator_87fdfd2c7e1ece2c/protove\\n'; exit 0; fi\n"
            "if [[ \"$*\" == *'sts get-caller-identity'* ]]; then printf '419496180357\\n'; exit 0; fi\n"
            "if [[ \"$*\" == *'iam get-role'* ]]; then printf 'arn:aws:iam::419496180357:role/AWSReservedSSO_KDT-Terraform-Operator_87fdfd2c7e1ece2c\\n'; exit 0; fi\n"
            "if [[ \"$*\" == *'iam list-attached-role-policies'* ]]; then printf 'arn:aws:iam::419496180357:policy/kdt-travelplanner-dev-eks-bastion-run-command\\n'; exit 0; fi\n"
            "if [[ \"$*\" == *'iam get-policy '* ]]; then printf 'v1\\n'; exit 0; fi\n"
            f"if [[ \"$*\" == *'iam get-policy-version'* ]]; then printf '%s' '{policy}'; exit 0; fi\n"
            f"if [[ \"$*\" == *'iam simulate-principal-policy'* ]]; then printf '%s' '{{\"EvaluationResults\":[{{\"EvalDecision\":\"{iam_decision}\",\"MatchedStatements\":[]}}]}}'; exit 0; fi\n"
            "if [[ \"$*\" == *'eks describe-cluster-versions'* ]]; then printf '%s' '{\"clusterVersions\":[{\"clusterVersion\":\"1.35\",\"clusterType\":\"eks\",\"versionStatus\":\"STANDARD_SUPPORT\"}]}'; exit 0; fi\n"
            f"if [[ \"$*\" == *'ecr describe-images'* ]]; then printf '{digest}\\n'; exit 0; fi\n"
            "if [[ \"$*\" == *'s3api head-object'* ]]; then printf '{}'; exit 0; fi\n"
            "if [[ \"$*\" == *'s3api get-object'* ]]; then printf '%s' '{\"resources\":[]}' > \"${!#}\"; printf '{}'; exit 0; fi\n"
            "exit 0\n"
        )
        (fake_bin / "aws").write_text(aws_script, encoding="utf-8")
        (fake_bin / "terraform").write_text(
            "#!/usr/bin/env bash\n"
            "if [[ \"$*\" == *' plan '* ]]; then output=\"${!#}\"; output=\"${output#-out=}\"; printf 'fake-plan-bytes' > \"$output\"; exit 0; fi\n"
            "if [[ \"$*\" == *' show -json '* ]]; then printf '%s' '{\"variables\":{\"kubernetes_version\":{\"value\":\"1.35\"}},\"resource_changes\":[],\"planned_values\":{\"root_module\":{\"resources\":[{\"address\":\"module.eks.aws_eks_cluster.this\",\"mode\":\"managed\",\"type\":\"aws_eks_cluster\",\"name\":\"this\",\"values\":{\"version\":\"1.35\"}}]}}}'; exit 0; fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        for executable in (fake_bin / "aws", fake_bin / "terraform"):
            executable.chmod(0o755)
        return fake_bin, digest

    def test_shell_syntax_and_shellcheck(self) -> None:
        for path in (SCRIPT, DEPLOY):
            syntax = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
            self.assertEqual(syntax.returncode, 0, syntax.stderr)
            lint = subprocess.run(["shellcheck", "--severity=warning", str(path)], capture_output=True, text=True)
            self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)

    def test_coordinator_has_create_only_surface_and_no_retirement_call(self) -> None:
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        self.assertIn("dev-eks-create-authorization/v1", self.source)
        self.assertIn("APPLY DEV-EKS CREATE-AND-RETAIN", self.source)
        self.assertIn("terraform -chdir=\"$TERRAFORM_ROOT\" plan", self.source)
        self.assertNotIn("run-dev-eks-ephemeral-lifecycle.sh", self.source)
        self.assertNotRegex(self.source, r"terraform\\s+(-[^\\n]+\\s+)*destroy")
        self.assertNotRegex(self.source, r"kubectl\\s+delete")
        self.assertNotIn("cloudflare" + " record", self.source.lower())

    def test_authenticated_hashes_are_pinned_and_backend_drift_is_rejected(self) -> None:
        self.assertIn('EXPECTED_PLAN_HANDOFF_SHA256="' + V9_HANDOFF_SHA256 + '"', self.source)
        self.assertIn('EXPECTED_PLAN_MANIFEST_SHA256="' + V9_MANIFEST_SHA256 + '"', self.source)
        self.assertIn('EXPECTED_BACKEND_CONFIG_SHA256="' + BACKEND_CONFIG_SHA256 + '"', self.source)
        self.assertIn('[[ "$BACKEND_CONFIG_SHA256" == "$EXPECTED_BACKEND_CONFIG_SHA256" ]]', self.source)
        self.assertIn('[[ "$PLAN_HANDOFF_SHA256" == "$EXPECTED_PLAN_HANDOFF_SHA256" ]]', self.source)
        self.assertIn('[[ "$PLAN_MANIFEST_SHA256" == "$EXPECTED_PLAN_MANIFEST_SHA256" ]]', self.source)

    def test_plan_mode_creates_pending_receipt_without_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            digest = json.loads(CAPSULE.read_text(encoding="utf-8"))["backend_image"].split("@", 1)[1]
            (fake_bin / "aws").write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"$*\" == *'sts get-caller-identity'* && \"$*\" == *'--query Arn'* ]]; then printf 'arn:aws:sts::419496180357:assumed-role/AWSReservedSSO_KDT-Terraform-Operator_87fdfd2c7e1ece2c/protove\\n'; exit 0; fi\n"
                "if [[ \"$*\" == *'sts get-caller-identity'* ]]; then printf '419496180357\\n'; exit 0; fi\n"
                "if [[ \"$*\" == *'iam get-role'* ]]; then printf 'arn:aws:iam::419496180357:role/AWSReservedSSO_KDT-Terraform-Operator_87fdfd2c7e1ece2c\\n'; exit 0; fi\n"
                "if [[ \"$*\" == *'iam list-attached-role-policies'* ]]; then printf 'arn:aws:iam::419496180357:policy/kdt-travelplanner-dev-eks-bastion-run-command\\n'; exit 0; fi\n"
                "if [[ \"$*\" == *'iam get-policy '* ]]; then printf 'v1\\n'; exit 0; fi\n"
                "if [[ \"$*\" == *'iam get-policy-version'* ]]; then printf '%s' '{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"ssm:SendCommand\",\"Resource\":\"arn:aws:ec2:ap-northeast-2:419496180357:instance/*\",\"Condition\":{\"StringEquals\":{\"ssm:resourceTag/Environment\":\"dev\",\"ssm:resourceTag/Stack\":\"dev-eks\",\"ssm:resourceTag/Name\":\"kdt-travelplanner-dev-eks-bastion\"}}},{\"Effect\":\"Allow\",\"Action\":\"ssm:SendCommand\",\"Resource\":\"arn:aws:ssm:ap-northeast-2::document/AWS-RunShellScript\"},{\"Effect\":\"Allow\",\"Action\":\"ssm:GetCommandInvocation\",\"Resource\":\"*\",\"Condition\":{\"StringEquals\":{\"aws:RequestedRegion\":\"ap-northeast-2\"}}}]}'; exit 0; fi\n"
                "if [[ \"$*\" == *'iam simulate-principal-policy'* ]]; then printf '%s' '{\"EvaluationResults\":[{\"EvalDecision\":\"allowed\",\"MatchedStatements\":[]}]}'; exit 0; fi\n"
                "if [[ \"$*\" == *'eks describe-cluster-versions'* ]]; then printf '%s' '{\"clusterVersions\":[{\"clusterVersion\":\"1.35\",\"clusterType\":\"eks\",\"versionStatus\":\"STANDARD_SUPPORT\"}]}'; exit 0; fi\n"
                f"if [[ \"$*\" == *'ecr describe-images'* ]]; then printf '{digest}\\n'; exit 0; fi\n"
                "if [[ \"$*\" == *'s3api head-object'* ]]; then printf '{}'; exit 0; fi\n"
                "if [[ \"$*\" == *'s3api get-object'* ]]; then printf '%s' '{\"resources\":[]}' > \"${!#}\"; printf '{}'; exit 0; fi\n"
                "exit 0\n", encoding="utf-8")
            (fake_bin / "terraform").write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"$*\" == *' plan '* ]]; then output=\"${!#}\"; output=\"${output#-out=}\"; printf 'fake-plan-bytes' > \"$output\"; exit 0; fi\n"
                "if [[ \"$*\" == *' show -json '* ]]; then printf '%s' '{\"variables\":{\"kubernetes_version\":{\"value\":\"1.35\"}},\"resource_changes\":[],\"planned_values\":{\"root_module\":{\"resources\":[{\"address\":\"module.eks.aws_eks_cluster.this\",\"mode\":\"managed\",\"type\":\"aws_eks_cluster\",\"name\":\"this\",\"values\":{\"version\":\"1.35\"}}]}}}'; exit 0; fi\n"
                "exit 0\n", encoding="utf-8")
            for executable in (fake_bin / "aws", fake_bin / "terraform"):
                executable.chmod(0o755)
            report_root = root / "run"
            result = subprocess.run(
                ["bash", str(SCRIPT), "--mode", "plan", "--aws-profile", "offline", "--offline-test", "--report-root", str(report_root)],
                cwd=ROOT, env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 20, result.stderr)
            match = re.search(r"run_id=([^ ]+) plan_sha256=([0-9a-f]{64})", result.stderr)
            self.assertIsNotNone(match, result.stderr)
            receipt = report_root / "creation-authorization.private.json"
            self.assertTrue(receipt.exists())
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "dev-eks-create-authorization/v1")
            self.assertEqual(payload["plan_id"], "dev-eks-deployment-automation")
            self.assertEqual(payload["plan_version"], 9)
            self.assertEqual(payload["manifest_sha256"], V9_MANIFEST_SHA256)
            self.assertEqual(payload["manifest_path"], str(V9_MANIFEST))
            self.assertEqual(payload["handoff_path"], str(V9_HANDOFF))
            self.assertEqual(payload["handoff_sha256"], V9_HANDOFF_SHA256)
            self.assertEqual(payload["status"], "active")
            self.assertEqual(payload["paid_approval"]["status"], "pending")
            self.assertEqual(payload["terraform_plan_sha256"], hashlib.sha256(b"fake-plan-bytes").hexdigest())
            self.assertNotIn("SecretString", receipt.read_text(encoding="utf-8"))

    def test_wrong_approval_fails_before_delegate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            digest = json.loads(CAPSULE.read_text(encoding="utf-8"))["backend_image"].split("@", 1)[1]
            (fake_bin / "aws").write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"$*\" == *'sts get-caller-identity'* && \"$*\" == *'--query Arn'* ]]; then printf 'arn:aws:sts::419496180357:assumed-role/AWSReservedSSO_KDT-Terraform-Operator_87fdfd2c7e1ece2c/protove\\n'; exit 0; fi\n"
                "if [[ \"$*\" == *'sts get-caller-identity'* ]]; then printf '419496180357\\n'; exit 0; fi\n"
                "if [[ \"$*\" == *'iam get-role'* ]]; then printf 'arn:aws:iam::419496180357:role/AWSReservedSSO_KDT-Terraform-Operator_87fdfd2c7e1ece2c\\n'; exit 0; fi\n"
                "if [[ \"$*\" == *'iam list-attached-role-policies'* ]]; then printf 'arn:aws:iam::419496180357:policy/kdt-travelplanner-dev-eks-bastion-run-command\\n'; exit 0; fi\n"
                "if [[ \"$*\" == *'iam get-policy '* ]]; then printf 'v1\\n'; exit 0; fi\n"
                "if [[ \"$*\" == *'iam get-policy-version'* ]]; then printf '%s' '{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"ssm:SendCommand\",\"Resource\":\"arn:aws:ec2:ap-northeast-2:419496180357:instance/*\",\"Condition\":{\"StringEquals\":{\"ssm:resourceTag/Environment\":\"dev\",\"ssm:resourceTag/Stack\":\"dev-eks\",\"ssm:resourceTag/Name\":\"kdt-travelplanner-dev-eks-bastion\"}}},{\"Effect\":\"Allow\",\"Action\":\"ssm:SendCommand\",\"Resource\":\"arn:aws:ssm:ap-northeast-2::document/AWS-RunShellScript\"},{\"Effect\":\"Allow\",\"Action\":\"ssm:GetCommandInvocation\",\"Resource\":\"*\",\"Condition\":{\"StringEquals\":{\"aws:RequestedRegion\":\"ap-northeast-2\"}}}]}'; exit 0; fi\n"
                "if [[ \"$*\" == *'iam simulate-principal-policy'* ]]; then printf '%s' '{\"EvaluationResults\":[{\"EvalDecision\":\"allowed\",\"MatchedStatements\":[]}]}'; exit 0; fi\n"
                "if [[ \"$*\" == *'eks describe-cluster-versions'* ]]; then printf '%s' '{\"clusterVersions\":[{\"clusterVersion\":\"1.35\",\"clusterType\":\"eks\",\"versionStatus\":\"STANDARD_SUPPORT\"}]}'; exit 0; fi\n"
                f"if [[ \"$*\" == *'ecr describe-images'* ]]; then printf '{digest}\\n'; exit 0; fi\n"
                "if [[ \"$*\" == *'s3api head-object'* ]]; then printf '{}'; exit 0; fi\n"
                "if [[ \"$*\" == *'s3api get-object'* ]]; then printf '%s' '{\"resources\":[]}' > \"${!#}\"; printf '{}'; exit 0; fi\n"
                "exit 0\n", encoding="utf-8")
            (fake_bin / "terraform").write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"$*\" == *' plan '* ]]; then output=\"${!#}\"; output=\"${output#-out=}\"; printf 'fake-plan-bytes' > \"$output\"; exit 0; fi\n"
                "if [[ \"$*\" == *' show -json '* ]]; then printf '%s' '{\"variables\":{\"kubernetes_version\":{\"value\":\"1.35\"}},\"resource_changes\":[],\"planned_values\":{\"root_module\":{\"resources\":[{\"address\":\"module.eks.aws_eks_cluster.this\",\"mode\":\"managed\",\"type\":\"aws_eks_cluster\",\"name\":\"this\",\"values\":{\"version\":\"1.35\"}}]}}}'; exit 0; fi\n"
                "exit 0\n", encoding="utf-8")
            for executable in (fake_bin / "aws", fake_bin / "terraform"):
                executable.chmod(0o755)
            report_root = root / "run"
            plan_result = subprocess.run(
                ["bash", str(SCRIPT), "--mode", "plan", "--aws-profile", "offline", "--offline-test", "--report-root", str(report_root)],
                cwd=ROOT, env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
            )
            self.assertEqual(plan_result.returncode, 20, plan_result.stderr)
            run_match = re.search(r"run_id=([^ ]+) plan_sha256=([0-9a-f]{64})", plan_result.stderr)
            self.assertIsNotNone(run_match, plan_result.stderr)
            result = subprocess.run(
                ["bash", str(SCRIPT), "--mode", "run", "--aws-profile", "offline", "--offline-test", "--report-root", str(report_root), "--run-id", run_match.group(1), "--approval", "wrong"],
                cwd=ROOT, env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exact paid create approval does not match", result.stderr)

    def test_altered_handoff_and_manifest_pair_is_rejected_executably(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_root = root / "run"
            report_root.mkdir()
            altered_manifest = report_root / "plan-v9-altered.yaml"
            altered_manifest.write_bytes(V9_MANIFEST.read_bytes() + b"\n# altered test bytes\n")
            altered_handoff = report_root / "handoff-v9-altered.yaml"
            handoff_text = V9_HANDOFF.read_text(encoding="utf-8")
            handoff_text = handoff_text.replace(str(V9_MANIFEST), str(altered_manifest))
            handoff_text = handoff_text.replace(V9_MANIFEST_SHA256, hashlib.sha256(altered_manifest.read_bytes()).hexdigest())
            altered_handoff.write_text(handoff_text, encoding="utf-8")
            altered_handoff.chmod(0o600)
            result = subprocess.run(
                [
                    "bash", str(SCRIPT), "--mode", "plan", "--aws-profile", "offline", "--offline-test",
                    "--report-root", str(report_root), "--plan-handoff", str(altered_handoff),
                ],
                cwd=ROOT, env={**os.environ, "PATH": os.environ["PATH"]},
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 20)
            self.assertIn("canonical v9 plan handoff hash does not match the authenticated plan", result.stderr)

    def test_altered_backend_hash_is_rejected_before_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin, _ = self._preflight_fake(root)
            real_sha = shutil.which("sha256sum")
            assert real_sha
            altered_hash = "0" * 64
            (fake_bin / "sha256sum").write_text(
                "#!/usr/bin/env bash\n"
                "for value in \"$@\"; do\n"
                f"  case \"$value\" in *infra/environments/dev-eks/backend.hcl) printf '%s  %s\\n' '{altered_hash}' \"$value\"; exit 0 ;; esac\n"
                "done\n"
                f"exec {real_sha} \"$@\"\n",
                encoding="utf-8",
            )
            (fake_bin / "sha256sum").chmod(0o755)
            report_root = root / "run"
            result = subprocess.run(
                ["bash", str(SCRIPT), "--mode", "plan", "--aws-profile", "offline", "--offline-test", "--report-root", str(report_root)],
                cwd=ROOT, env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 20)
            self.assertIn("dev-eks backend configuration hash does not match the authenticated plan", result.stderr)

    def test_iam_denial_and_wrong_tag_fail_before_terraform_plan(self) -> None:
        for option in ({"deny_simulation": True}, {"bad_tag": True}):
            with self.subTest(option=option), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                fake_bin, _ = self._preflight_fake(root, **option)
                report_root = root / "run"
                result = subprocess.run(
                    ["bash", str(SCRIPT), "--mode", "plan", "--aws-profile", "offline", "--offline-test", "--report-root", str(report_root)],
                    cwd=ROOT,
                    env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 20, result.stderr)
                self.assertFalse((report_root / "create.tfplan").exists())
                self.assertIn("status=failed", result.stderr)

    def test_noninteractive_deploy_requires_v9_receipt_for_mutation(self) -> None:
        self.assertIn("non-interactive mutation requires a v9 authorization receipt", self.deploy_source)
        self.assertIn("non-empty Terraform plan hash", self.deploy_source)
        self.assertIn("capture_failure_protected_state_evidence", self.deploy_source)
        self.assertIn('LAST_STAGE="$stage"', self.deploy_source)
        self.assertIn("dev-eks-create-authorization/v1", self.deploy_source)
        self.assertIn("terminal_result", self.deploy_source)

    def test_noninteractive_mutation_without_receipt_is_rejected_executably(self) -> None:
        result = subprocess.run(
            [
                "bash", str(DEPLOY), "--mode", "run", "--non-interactive", "--skip-terraform-apply",
                "--aws-profile", "offline", "--region", "ap-northeast-2", "--expected-account-id", "123456789012",
                "--kubernetes-render-sha256", "b" * 64,
                "--backend-image", "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/backend@sha256:" + "c" * 64,
                "--backend-hostname", "api.example.com", "--frontend-origin", "https://www.example.com",
            ],
            cwd=ROOT, env={**os.environ, "PATH": os.environ["PATH"]}, capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("non-interactive mutation requires an authorization receipt", result.stderr)

    def test_legacy_v7_receipt_cannot_reach_run_apply_without_capsule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "legacy-v7.json"
            receipt.write_text(json.dumps({
                "schema_version": "dev-eks-autonomous-authorization/v1",
                "plan_id": "dev-eks-deployment-automation", "plan_version": 7,
                "manifest_sha256": "d3a35fe33b73a0d5d22af5b21f44d36caa8f447831ecca3977043e5637806e67",
                "lifecycle_run_id": "20260825T000000Z-77", "status": "active", "single_use": True,
                "expected_account_sha256": "a" * 64, "expected_region": "ap-northeast-2",
                "terraform_backend_key": "dev-eks/terraform.tfstate", "state_sha256": "b" * 64,
                "managed_address_sha256": "c" * 64, "managed_address_count": 0,
                "runtime_values_sha256": "d" * 64, "render_sha256": None,
                "protected_backends": ["dev/terraform.tfstate", "dev-runtime/terraform.tfstate", "dev-load-test/terraform.tfstate"],
                "forbidden_actions": ["Terraform create/apply", "Cloudflare mutation"],
                "expires_at": "2030-01-01T00:00:00Z",
            }), encoding="utf-8")
            receipt.chmod(0o600)
            result = subprocess.run(
                [
                    "bash", str(DEPLOY), "--mode", "run", "--non-interactive",
                    "--aws-profile", "offline", "--region", "ap-northeast-2", "--expected-account-id", "123456789012",
                    "--terraform-plan", str(Path(directory) / "plan.tfplan"), "--terraform-plan-sha256", "c" * 64,
                    "--backend-image", "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/backend@sha256:" + "c" * 64,
                    "--backend-hostname", "api.example.com", "--frontend-origin", "https://www.example.com",
                    "--authorization-receipt", str(receipt),
                ],
                cwd=ROOT, env={**os.environ, "PATH": os.environ["PATH"]}, capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("legacy v7 authorization receipt is valid only for --mode resume --skip-terraform-apply", result.stderr)


    def _write_v9_receipt(self, receipt: Path, capsule: Path, run_id: str, *, tamper: str | None = None) -> None:
        capsule_sha = hashlib.sha256(capsule.read_bytes()).hexdigest()
        plan_sha = "c" * 64
        payload = {
            "schema_version": "dev-eks-create-authorization/v1",
            "handoff_schema_version": "plan-handoff/v1", "handoff_path": str(V9_HANDOFF), "handoff_sha256": V9_HANDOFF_SHA256,
            "manifest_schema_version": "plan-manifest/v3", "manifest_path": str(V9_MANIFEST),
            "plan_id": "dev-eks-deployment-automation", "plan_version": 9,
            "manifest_sha256": V9_MANIFEST_SHA256,
            "run_id": run_id, "issued_at": "2026-08-25T00:00:00Z", "expires_at": "2030-01-01T00:00:00Z",
            "status": "active", "single_use": True, "expected_account_id": "123456789012", "expected_region": "ap-northeast-2",
            "terraform_backend_key": "dev-eks/terraform.tfstate", "terraform_backend_config_sha256": BACKEND_CONFIG_SHA256, "terraform_plan_sha256": plan_sha,
            "input_capsule_path": os.path.abspath(str(capsule)),
            "input_capsule_sha256": capsule_sha, "backend_image": "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/backend@sha256:" + "c" * 64,
            "backend_hostname": "api.example.com", "frontend_origin": "https://www.example.com",
            "kubernetes_version": "1.35", "kubernetes_version_status": "STANDARD_SUPPORT",
            "bundle_revision_sha256": None, "runtime_values_sha256": None, "render_sha256": None,
            "protected_backends": ["dev/terraform.tfstate", "dev-runtime/terraform.tfstate", "dev-load-test/terraform.tfstate"],
            "protected_resources": ["persistent VPC and subnets", "ACM certificates", "ECR repositories and images", "profile image storage", "application Secrets Manager", "external DNS provider"],
            "permitted_actions": ["apply exact create/update-only dev-eks Terraform plan", "run exact staged Kubernetes deployment through tagged private Bastion", "run bounded ALB/HTTPS/observability smoke", "retain created dev-eks resources"],
            "forbidden_actions": ["terraform destroy", "Kubernetes delete", "replace or import", "Cloudflare mutation", "protected State mutation"],
            "paid_approval": {"status": "approved", "action": "APPLY DEV-EKS CREATE-AND-RETAIN " + plan_sha, "plan_sha256": plan_sha},
        }
        if tamper == "hostname":
            payload["backend_hostname"] = "tampered.example.com"
        elif tamper == "replay":
            payload["status"] = "consumed"
        elif tamper == "expired":
            payload["expires_at"] = "2020-01-01T00:00:00Z"
        elif tamper == "foreign":
            payload["expected_account_id"] = "999999999999"
        elif tamper == "destroy":
            payload["permitted_actions"] = ["terraform destroy dev-eks"]
        receipt.write_text(json.dumps(payload), encoding="utf-8")
        receipt.chmod(0o600)

    def test_v9_receipt_is_consumed_on_success_and_replay_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capsule = root / "capsule.json"
            capsule.write_text(json.dumps({
                "vpc_id": "vpc-0123456789abcdef0", "public_subnet_ids": ["subnet-a", "subnet-b"],
                "api_certificate_arn": "arn:aws:acm:ap-northeast-2:123456789012:certificate/a",
                "backend_image": "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/backend@sha256:" + "c" * 64,
                "backend_hostname": "api.example.com", "frontend_origin": "https://www.example.com"}), encoding="utf-8")
            capsule.chmod(0o600)
            receipt = root / "receipt.json"
            run_id = "20260825T000000Z-1"
            self._write_v9_receipt(receipt, capsule, run_id)
            legacy = OperatorOrchestratorContractTest()
            fake_bin, _ = legacy._operator_fixture(root / "fake")
            args = legacy._operator_args() + ["--run-id", run_id, "--action-values-capsule", str(capsule), "--authorization-receipt", str(receipt)]
            result = subprocess.run(args, cwd=ROOT, env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            consumed = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(consumed["status"], "consumed")
            replay = subprocess.run(args, cwd=ROOT, env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"}, capture_output=True, text=True)
            self.assertNotEqual(replay.returncode, 0)
            self.assertIn("v9 authorization receipt binding or approval is invalid", replay.stderr)

    def test_v9_receipt_tampered_binding_fails_before_ssm(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capsule = root / "capsule.json"
            capsule.write_text(json.dumps({
                "vpc_id": "vpc-0123456789abcdef0", "public_subnet_ids": ["subnet-a", "subnet-b"],
                "api_certificate_arn": "arn:aws:acm:ap-northeast-2:123456789012:certificate/a",
                "backend_image": "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/backend@sha256:" + "c" * 64,
                "backend_hostname": "api.example.com", "frontend_origin": "https://www.example.com"}), encoding="utf-8")
            capsule.chmod(0o600)
            receipt = root / "receipt.json"
            run_id = "20260825T000000Z-2"
            self._write_v9_receipt(receipt, capsule, run_id, tamper="hostname")
            legacy = OperatorOrchestratorContractTest()
            fake_bin, _ = legacy._operator_fixture(root / "fake")
            command_log = root / "ssm.log"
            args = legacy._operator_args() + ["--run-id", run_id, "--action-values-capsule", str(capsule), "--authorization-receipt", str(receipt)]
            result = subprocess.run(args, cwd=ROOT, env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}", "FAKE_SSM_COMMAND_LOG": str(command_log)}, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("v9 authorization receipt binding or approval is invalid", result.stderr)
            self.assertFalse(command_log.exists())

    def test_obsolete_v8_receipt_is_rejected_before_ssm(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capsule = root / "capsule.json"
            capsule.write_text(json.dumps({
                "vpc_id": "vpc-0123456789abcdef0", "public_subnet_ids": ["subnet-a", "subnet-b"],
                "api_certificate_arn": "arn:aws:acm:ap-northeast-2:123456789012:certificate/a",
                "backend_image": "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/backend@sha256:" + "c" * 64,
                "backend_hostname": "api.example.com", "frontend_origin": "https://www.example.com"}), encoding="utf-8")
            capsule.chmod(0o600)
            receipt = root / "v8-receipt.json"
            run_id = "20260825T000000Z-3"
            self._write_v9_receipt(receipt, capsule, run_id)
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            payload["plan_version"] = 8
            payload["manifest_sha256"] = "cf9c66b578a7dda328d307aeee47b4280b19c06055e25f2b9157463eaba937ad"
            receipt.write_text(json.dumps(payload), encoding="utf-8")
            receipt.chmod(0o600)
            legacy = OperatorOrchestratorContractTest()
            fake_bin, _ = legacy._operator_fixture(root / "fake")
            command_log = root / "ssm.log"
            args = legacy._operator_args() + ["--run-id", run_id, "--action-values-capsule", str(capsule), "--authorization-receipt", str(receipt)]
            result = subprocess.run(args, cwd=ROOT, env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}", "FAKE_SSM_COMMAND_LOG": str(command_log)}, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("v9 authorization receipt binding or approval is invalid", result.stderr)
            self.assertFalse(command_log.exists())

    def test_untrusted_handoff_path_is_rejected_before_ssm(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capsule = root / "capsule.json"
            capsule.write_text(json.dumps({
                "vpc_id": "vpc-0123456789abcdef0", "public_subnet_ids": ["subnet-a", "subnet-b"],
                "api_certificate_arn": "arn:aws:acm:ap-northeast-2:123456789012:certificate/a",
                "backend_image": "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/backend@sha256:" + "c" * 64,
                "backend_hostname": "api.example.com", "frontend_origin": "https://www.example.com"}), encoding="utf-8")
            capsule.chmod(0o600)
            receipt = root / "receipt.json"
            run_id = "20260825T000000Z-4"
            self._write_v9_receipt(receipt, capsule, run_id)
            untrusted_handoff = root / "handoff-v9.yaml"
            shutil.copy2(V9_HANDOFF, untrusted_handoff)
            legacy = OperatorOrchestratorContractTest()
            fake_bin, _ = legacy._operator_fixture(root / "fake")
            command_log = root / "ssm.log"
            args = legacy._operator_args() + ["--run-id", run_id, "--action-values-capsule", str(capsule), "--plan-handoff", str(untrusted_handoff), "--authorization-receipt", str(receipt)]
            result = subprocess.run(args, cwd=ROOT, env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}", "FAKE_SSM_COMMAND_LOG": str(command_log)}, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("plan handoff path is not the authenticated v15 handoff", result.stderr)
            self.assertFalse(command_log.exists())

    def test_v9_receipt_missing_expired_foreign_and_destroy_scoped_fail_before_ssm(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capsule = root / "capsule.json"
            capsule.write_text(json.dumps({
                "vpc_id": "vpc-0123456789abcdef0", "public_subnet_ids": ["subnet-a", "subnet-b"],
                "api_certificate_arn": "arn:aws:acm:ap-northeast-2:123456789012:certificate/a",
                "backend_image": "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/backend@sha256:" + "c" * 64,
                "backend_hostname": "api.example.com", "frontend_origin": "https://www.example.com"}), encoding="utf-8")
            capsule.chmod(0o600)
            legacy = OperatorOrchestratorContractTest()
            fake_bin, _ = legacy._operator_fixture(root / "fake")
            missing_args = legacy._operator_args() + ["--run-id", "20260825T000000Z-10", "--action-values-capsule", str(capsule), "--authorization-receipt", str(root / "missing-receipt.json")]
            missing = subprocess.run(missing_args, cwd=ROOT, env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"}, capture_output=True, text=True)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("authorization receipt must be a regular file", missing.stderr)
            for index, tamper in enumerate(("expired", "foreign", "destroy"), start=1):
                receipt = root / f"receipt-{tamper}.json"
                run_id = f"20260825T000000Z-{index + 10}"
                self._write_v9_receipt(receipt, capsule, run_id, tamper=tamper)
                args = legacy._operator_args() + ["--run-id", run_id, "--action-values-capsule", str(capsule), "--authorization-receipt", str(receipt)]
                result = subprocess.run(args, cwd=ROOT, env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"}, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0, tamper)
                self.assertIn("v9 authorization receipt", result.stderr, tamper)


if __name__ == "__main__":
    unittest.main()
