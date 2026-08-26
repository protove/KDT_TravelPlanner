"""Offline contracts for the v11 retained-environment recovery coordinator."""

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
DEPLOYER = ROOT / "scripts" / "eks" / "deploy-dev-eks.sh"
HANDOFF = ROOT / ".codex" / "plans" / "dev-eks-deployment-automation" / "handoff-v11.yaml"
CAPSULE = ROOT / "evidence" / "eks-deploy" / "20260824T133440Z-15798" / "action-values.json"
HANDOFF_SHA256 = "b0441f0a4af42a807463a4d102c74e7606f36b16785f5544be365d05a626be19"
MANIFEST_SHA256 = "231da893f466968f34fadc7cd9c33eac26f72509f196da18cf93f2eac8c3d290"

# Offline fixtures intentionally use disposable temp roots instead of the live
# run evidence root; production invocations leave this unset.
os.environ.setdefault("OFFLINE_TEST", "true")


class RepairCoordinatorContractTest(unittest.TestCase):
    def test_shell_syntax_and_executable_surface(self) -> None:
        self.assertTrue(os.access(COORDINATOR, os.X_OK))
        self.assertEqual(subprocess.run(["bash", "-n", str(COORDINATOR)]).returncode, 0)
        source = COORDINATOR.read_text(encoding="utf-8")
        self.assertIn("dev-eks-repair-authorization/v1", source)
        self.assertIn("APPLY DEV-EKS REPAIR-AND-RESUME", source)
        self.assertIn("--skip-terraform-apply", source)
        self.assertIn("--resume-run-id", source)
        self.assertIn("validate_active_receipt", source)
        self.assertIn("consume_active_receipt", source)
        self.assertIn("smoke_helper_sha256", source)
        self.assertIn("deployment_runner_sha256", source)
        self.assertIn("validate_live_preflight_identity", source)
        self.assertIn("write_ssm_failure_evidence", source)
        self.assertIn("live-preflight-identity.private.json", source)
        self.assertIn("standard_error_present", source)
        self.assertNotIn("terraform apply", source)
        self.assertNotIn("terraform destroy", source)
        self.assertNotIn("resourcegroupstaggingapi", source)
        self.assertNotIn("run-dev-eks-lifecycle-remote.sh", source)
        self.assertIn('(.commands | type == "array") and (.commands | length == 1) and (.commands[0] | type == "string" and length > 0)', source)

    def test_deployer_has_v11_dispatch_without_removing_v9(self) -> None:
        source = DEPLOYER.read_text(encoding="utf-8")
        self.assertIn('EXPECTED_REPAIR_PLAN_HANDOFF_SHA256="' + HANDOFF_SHA256 + '"', source)
        self.assertIn('EXPECTED_REPAIR_PLAN_MANIFEST_SHA256="' + MANIFEST_SHA256 + '"', source)
        self.assertIn('dev-eks-repair-authorization/v1', source)
        self.assertIn('dev-eks-create-authorization/v1', source)
        self.assertIn('RESUME_FROM" == "prepare"', source)
        self.assertIn("bind_repair_receipt_render", source)
        self.assertIn("consume_authorization_receipt", source)

    def test_v11_contract_binds_support_tags_all_states_and_terminal_iam_classification(self) -> None:
        source = COORDINATOR.read_text(encoding="utf-8")
        for required in (
            'dev-eks-v11-live-preflight/v1',
            'versionStatus == "STANDARD_SUPPORT"',
            'Name == "kdt-travelplanner-dev-eks-bastion"',
            'dev-load-test/terraform.tfstate',
            'AccessDeniedException',
            'InvocationDoesNotExist',
            'final-cname.private.txt',
            'refusing to overwrite an existing or symlinked receipt',
        ):
            self.assertIn(required, source)
        self.assertNotIn('handoff-v10.yaml', source)

    def test_issue_mode_creates_pending_hash_bound_receipt_without_aws(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capsule = root / "action-values.json"
            capsule.write_bytes(CAPSULE.read_bytes())
            capsule.chmod(0o600)
            preflight = root / "preflight.json"
            preflight.write_text(
                json.dumps(
                    {
                        "schema_version": "dev-eks-v11-live-preflight/v1",
                        "expected_account_id": "419496180357",
                        "expected_region": "ap-northeast-2",
                        "backend_config_sha256": hashlib.sha256(
                            (ROOT / "infra" / "environments" / "dev-eks" / "backend.hcl").read_bytes()
                        ).hexdigest(),
                        "bastion_instance_id": "i-0123456789abcdef0",
                        "cluster_name": "kdt-travelplanner-dev-eks",
                        "monitoring_bucket": "private-bucket",
                        "monitoring_prefix": "kubernetes/monitoring",
                        "retained_v9_run_id": "20260825T054716Z-45689",
                        "retained_v9_plan_sha256": "5bc719aeb6c0ed2087095d056e11fb0766c580dd28c297b859cab33d5a169f3a",
                        "bundle_revision_sha256": "a" * 64,
                        "kubernetes_version": "1.35",
                        "kubernetes_version_status": "STANDARD_SUPPORT",
                        "bastion_tags": {"Environment": "dev", "Stack": "dev-eks", "Phase": "eks-baseline", "Project": "kdt-travelplanner", "Name": "kdt-travelplanner-dev-eks-bastion"},
                        "kubectl_version": "1.35.6",
                        "dev_eks_state_sha256": "b" * 64,
                        "dev_eks_state_lineage": "lineage",
                        "dev_eks_state_serial": 7,
                        "state_fingerprints": [
                            {"key": key, "sha256": "b" * 64, "lineage": "lineage", "serial": 7}
                            for key in ("dev/terraform.tfstate", "dev-runtime/terraform.tfstate", "dev-load-test/terraform.tfstate", "dev-eks/terraform.tfstate")
                        ],
                        "helper_sha256": hashlib.sha256((ROOT / "scripts" / "eks" / "repair-dev-eks-bastion.sh").read_bytes()).hexdigest(),
                        "smoke_helper_sha256": hashlib.sha256((ROOT / "scripts" / "eks" / "run-dev-eks-repair-smoke.sh").read_bytes()).hexdigest(),
                        "operator_iam_status": "operator-policy-evidence-verified",
                        "bastion_iam_status": "state-policy-evidence-verified",
                        "controller_iam_status": "state-policy-evidence-verified",
                    }
                ),
                encoding="utf-8",
            )
            preflight.chmod(0o600)
            receipt = root / "repair-authorization.private.json"
            result = subprocess.run(
                [
                    str(COORDINATOR),
                    "--mode",
                    "issue",
                    "--action-values-capsule",
                    str(capsule),
                    "--preflight-json",
                    str(preflight),
                    "--authorization-receipt",
                    str(receipt),
                    "--run-id",
                    "20260825T000000Z-4242",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("status=pending approval=APPLY DEV-EKS REPAIR-AND-RESUME ", result.stdout)
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "dev-eks-repair-authorization/v1")
            self.assertEqual(payload["status"], "pending")
            self.assertTrue(payload["single_use"])
            self.assertIsNone(payload["render_sha256"])
            self.assertEqual(payload["paid_approval"]["status"], "pending")
            self.assertEqual(payload["input_capsule_path"], os.path.abspath(capsule))
            self.assertEqual(payload["backend_image"], json.loads(capsule.read_text(encoding="utf-8"))["backend_image"])
            self.assertEqual(payload["backend_hostname"], json.loads(capsule.read_text(encoding="utf-8"))["backend_hostname"])
            self.assertEqual(payload["frontend_origin"], json.loads(capsule.read_text(encoding="utf-8"))["frontend_origin"])
            self.assertRegex(payload["repair_scope_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(payload["repair_helper_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(payload["smoke_helper_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(payload["deployment_runner_sha256"], r"^[0-9a-f]{64}$")
            self.assertNotIn("SecretString", receipt.read_text(encoding="utf-8"))
            self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)

    def test_issue_mode_rejects_incomplete_principal_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capsule = root / "action-values.json"
            capsule.write_bytes(CAPSULE.read_bytes())
            capsule.chmod(0o600)
            preflight = root / "preflight.json"
            preflight.write_text('{"schema_version":"dev-eks-v11-live-preflight/v1"}', encoding="utf-8")
            preflight.chmod(0o600)
            result = subprocess.run(
                [
                    str(COORDINATOR),
                    "--mode",
                    "issue",
                    "--action-values-capsule",
                    str(capsule),
                    "--preflight-json",
                    str(preflight),
                    "--authorization-receipt",
                    str(root / "receipt.json"),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("preflight is incomplete", result.stderr)

    def test_issue_mode_rejects_unverified_principal_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capsule = root / "action-values.json"
            capsule.write_bytes(CAPSULE.read_bytes())
            capsule.chmod(0o600)
            preflight = root / "preflight.json"
            payload = json.loads((ROOT / "evidence" / "eks-deploy" / "20260825T103000Z-9514" / "live-preflight.private.json").read_text(encoding="utf-8"))
            payload["operator_iam_status"] = "sts-account-verified"
            preflight.write_text(json.dumps(payload), encoding="utf-8")
            preflight.chmod(0o600)
            result = subprocess.run(
                [str(COORDINATOR), "--mode", "issue", "--action-values-capsule", str(capsule), "--preflight-json", str(preflight), "--authorization-receipt", str(root / "receipt.json"), "--run-id", "20260825T000032Z-4273"],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("preflight is incomplete", result.stderr)

    def test_issue_mode_rejects_symlinked_receipt_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preflight = root / "preflight.json"
            preflight_payload = json.loads((ROOT / "evidence" / "eks-deploy" / "20260825T103000Z-9514" / "live-preflight.private.json").read_text(encoding="utf-8"))
            preflight_payload["helper_sha256"] = hashlib.sha256((ROOT / "scripts" / "eks" / "repair-dev-eks-bastion.sh").read_bytes()).hexdigest()
            preflight_payload["smoke_helper_sha256"] = hashlib.sha256((ROOT / "scripts" / "eks" / "run-dev-eks-repair-smoke.sh").read_bytes()).hexdigest()
            preflight_payload["operator_iam_status"] = "operator-policy-evidence-verified"
            preflight_payload["bastion_iam_status"] = "state-policy-evidence-verified"
            preflight_payload["controller_iam_status"] = "state-policy-evidence-verified"
            preflight.write_text(json.dumps(preflight_payload), encoding="utf-8")
            preflight.chmod(0o600)
            real = root / "real"
            real.mkdir()
            link = root / "linked"
            link.symlink_to(real, target_is_directory=True)
            result = subprocess.run(
                [
                    str(COORDINATOR), "--mode", "issue", "--preflight-json", str(preflight),
                    "--authorization-receipt", str(link / "receipt.json"), "--run-id", "20260825T000020Z-4254",
                ], cwd=ROOT, capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("receipt parent path must not contain a symlink", result.stderr)

    def test_issue_mode_rejects_relative_and_traversal_receipt_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capsule = root / "action-values.json"
            capsule.write_bytes(CAPSULE.read_bytes())
            capsule.chmod(0o600)
            preflight = root / "preflight.json"
            preflight_payload = json.loads((ROOT / "evidence" / "eks-deploy" / "20260825T103000Z-9514" / "live-preflight.private.json").read_text(encoding="utf-8"))
            preflight_payload["helper_sha256"] = hashlib.sha256((ROOT / "scripts" / "eks" / "repair-dev-eks-bastion.sh").read_bytes()).hexdigest()
            preflight_payload["smoke_helper_sha256"] = hashlib.sha256((ROOT / "scripts" / "eks" / "run-dev-eks-repair-smoke.sh").read_bytes()).hexdigest()
            preflight.write_text(json.dumps(preflight_payload), encoding="utf-8")
            preflight.chmod(0o600)
            common = [
                str(COORDINATOR), "--mode", "issue", "--action-values-capsule", str(capsule),
                "--preflight-json", str(preflight), "--run-id", "20260825T000030Z-4271",
            ]
            relative = subprocess.run(common + ["--authorization-receipt", "relative-receipt.json"], cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(relative.returncode, 0)
            self.assertIn("receipt parent path must be absolute", relative.stderr)
            traversal = subprocess.run(common + ["--authorization-receipt", str(root / "nested" / ".." / "escape.json")], cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(traversal.returncode, 0)
            self.assertIn("receipt parent path contains an unsafe component", traversal.stderr)

    def test_preflight_mode_rejects_relative_output_path_before_aws(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capsule = root / "action-values.json"
            capsule.write_bytes(CAPSULE.read_bytes())
            capsule.chmod(0o600)
            result = subprocess.run(
                [str(COORDINATOR), "--mode", "preflight", "--aws-profile", "offline", "--expected-account-id", "419496180357", "--action-values-capsule", str(capsule), "--preflight-json", "relative-preflight.json", "--run-id", "20260825T000031Z-4272"],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("preflight output path must be absolute", result.stderr)

    def test_preflight_mode_builds_mode0600_v11_read_only_identity(self) -> None:
        run_id = "20260825T000020Z-4262"
        evidence_root = ROOT / "evidence" / "eks-deploy" / run_id
        shutil.rmtree(evidence_root, ignore_errors=True)
        self.addCleanup(lambda: shutil.rmtree(evidence_root, ignore_errors=True))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capsule = root / "action-values.json"
            capsule.write_bytes(CAPSULE.read_bytes())
            capsule.chmod(0o600)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            backend_digest = json.loads(CAPSULE.read_text(encoding="utf-8"))["backend_image"].split("@", 1)[1]
            bastion_policy = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["eks:DescribeCluster", "s3:ListBucket", "s3:GetObject", "ssm:GetParameter", "secretsmanager:GetSecretValue"]}]}, separators=(",", ":"))
            controller_policy = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["elasticloadbalancing:DescribeLoadBalancers", "elasticloadbalancing:DescribeTags", "elasticloadbalancing:DescribeTargetGroups", "elasticloadbalancing:DescribeTargetHealth", "elasticloadbalancing:CreateLoadBalancer", "elasticloadbalancing:CreateTargetGroup", "ec2:DescribeSubnets", "ec2:DescribeSecurityGroups", "acm:DescribeCertificate"]}]}, separators=(",", ":"))
            policy_state = json.dumps({"lineage": "lineage", "serial": 7, "resources": [
                {"type": "aws_iam_role", "name": "bastion", "instances": [{"attributes": {"name": "kdt-travelplanner-dev-eks-bastion"}}]},
                {"type": "aws_iam_role", "name": "load_balancer_controller", "instances": [{"attributes": {"name": "kdt-travelplanner-dev-aws-load-balancer-controller"}}]},
                {"type": "aws_iam_role_policy", "name": "bastion_runtime", "instances": [{"attributes": {"role": "kdt-travelplanner-dev-eks-bastion", "policy": bastion_policy}}]},
                {"type": "aws_iam_role_policy", "name": "load_balancer_controller", "instances": [{"attributes": {"role": "kdt-travelplanner-dev-aws-load-balancer-controller", "policy": controller_policy}}]},
                {"type": "aws_iam_role_policy_attachment", "name": "bastion_ssm", "instances": [{"attributes": {"role": "kdt-travelplanner-dev-eks-bastion", "policy_arn": "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"}}]},
            ]}, separators=(",", ":"))
            fake_aws = f'''#!/usr/bin/env bash
set -eu
case "$*" in
  *"sts get-caller-identity"*) printf '419496180357\\n' ;;
  *"ec2 describe-instances"*) printf '%s' '{{"Reservations":[{{"Instances":[{{"InstanceId":"i-0123456789abcdef0","State":{{"Name":"running"}},"Tags":[{{"Key":"Environment","Value":"dev"}},{{"Key":"Stack","Value":"dev-eks"}},{{"Key":"Phase","Value":"eks-baseline"}},{{"Key":"Project","Value":"kdt-travelplanner"}},{{"Key":"Name","Value":"kdt-travelplanner-dev-eks-bastion"}}]}}]}}]}}' ;;
  *"eks describe-cluster-versions"*) printf '%s' '{{"clusterVersions":[{{"clusterVersion":"1.35","clusterType":"eks","versionStatus":"STANDARD_SUPPORT"}}]}}' ;;
  *"eks describe-cluster"*) printf '%s' '{{"cluster":{{"arn":"arn:aws:eks:ap-northeast-2:419496180357:cluster/kdt-travelplanner-dev-eks","status":"ACTIVE","version":"1.35"}}}}' ;;
  *"s3api get-object"*"bundle-manifest.json"*) printf '%s' '{{"schema_version":"dev-eks-bundle/v1","revision":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}' > "${{!#}}" ;;
  *"s3api get-object"*) printf '%s' '{policy_state}' > "${{!#}}" ;;
  *"ecr describe-images"*) printf '%s' '{{"imageDetails":[{{"imageDigest":"{backend_digest}"}}]}}' ;;
  *"ssm describe-instance-information"*) printf '%s' '{{"InstanceInformationList":[{{"InstanceId":"i-0123456789abcdef0","PingStatus":"Online"}}]}}' ;;
  *"iam get-role"*) printf '%s' '{{"Role":{{"RoleName":"kdt-travelplanner-dev-eks-aws-load-balancer-controller"}}}}' ;;
  *) exit 1 ;;
esac
'''
            (fake_bin / "aws").write_text(fake_aws, encoding="utf-8")
            (fake_bin / "aws").chmod(0o755)
            result = subprocess.run(
                [
                    str(COORDINATOR), "--mode", "preflight", "--aws-profile", "offline",
                    "--expected-account-id", "419496180357", "--action-values-capsule", str(capsule),
                    "--preflight-json", str(evidence_root / "live-preflight.private.json"), "--run-id", run_id,
                ],
                cwd=ROOT,
                env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            preflight = evidence_root / "live-preflight.private.json"
            payload = json.loads(preflight.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "dev-eks-v11-live-preflight/v1")
            self.assertEqual(payload["kubernetes_version_status"], "STANDARD_SUPPORT")
            self.assertEqual(len(payload["state_fingerprints"]), 4)
            self.assertEqual(preflight.stat().st_mode & 0o777, 0o600)

    def test_run_rejects_tampered_smoke_helper_before_aws_and_consumes_active_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capsule = root / "action-values.json"
            capsule.write_bytes(CAPSULE.read_bytes())
            capsule.chmod(0o600)
            preflight = root / "preflight.json"
            preflight.write_text(
                json.dumps(
                    {
                        "schema_version": "dev-eks-v11-live-preflight/v1",
                        "expected_account_id": "419496180357",
                        "expected_region": "ap-northeast-2",
                        "backend_config_sha256": hashlib.sha256(
                            (ROOT / "infra" / "environments" / "dev-eks" / "backend.hcl").read_bytes()
                        ).hexdigest(),
                        "bastion_instance_id": "i-0123456789abcdef0",
                        "cluster_name": "kdt-travelplanner-dev-eks",
                        "monitoring_bucket": "private-bucket",
                        "monitoring_prefix": "kubernetes/monitoring",
                        "retained_v9_run_id": "20260825T054716Z-45689",
                        "retained_v9_plan_sha256": "5bc719aeb6c0ed2087095d056e11fb0766c580dd28c297b859cab33d5a169f3a",
                        "bundle_revision_sha256": "a" * 64,
                        "kubernetes_version": "1.35",
                        "kubernetes_version_status": "STANDARD_SUPPORT",
                        "bastion_tags": {"Environment": "dev", "Stack": "dev-eks", "Phase": "eks-baseline", "Project": "kdt-travelplanner", "Name": "kdt-travelplanner-dev-eks-bastion"},
                        "kubectl_version": "1.35.6",
                        "dev_eks_state_sha256": "b" * 64,
                        "dev_eks_state_lineage": "lineage",
                        "dev_eks_state_serial": 7,
                        "state_fingerprints": [
                            {"key": key, "sha256": "b" * 64, "lineage": "lineage", "serial": 7}
                            for key in ("dev/terraform.tfstate", "dev-runtime/terraform.tfstate", "dev-load-test/terraform.tfstate", "dev-eks/terraform.tfstate")
                        ],
                        "helper_sha256": hashlib.sha256((ROOT / "scripts" / "eks" / "repair-dev-eks-bastion.sh").read_bytes()).hexdigest(),
                        "smoke_helper_sha256": hashlib.sha256((ROOT / "scripts" / "eks" / "run-dev-eks-repair-smoke.sh").read_bytes()).hexdigest(),
                        "operator_iam_status": "operator-policy-evidence-verified",
                        "bastion_iam_status": "state-policy-evidence-verified",
                        "controller_iam_status": "state-policy-evidence-verified",
                    }
                ),
                encoding="utf-8",
            )
            preflight.chmod(0o600)
            receipt = root / "repair-authorization.private.json"
            issue = subprocess.run(
                [
                    str(COORDINATOR),
                    "--mode",
                    "issue",
                    "--action-values-capsule",
                    str(capsule),
                    "--preflight-json",
                    str(preflight),
                    "--authorization-receipt",
                    str(receipt),
                    "--run-id",
                    "20260825T000000Z-4242",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(issue.returncode, 0, issue.stderr)
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            payload["status"] = "active"
            payload["paid_approval"]["status"] = "approved"
            payload["smoke_helper_sha256"] = "0" * 64
            scope_fields = {
                "manifest_sha256": payload["manifest_sha256"],
                "handoff_sha256": payload["handoff_sha256"],
                "account": payload["expected_account_id"],
                "region": payload["expected_region"],
                "run_id": payload["run_id"],
                "backend_config_sha256": payload["terraform_backend_config_sha256"],
                "capsule_sha256": payload["input_capsule_sha256"],
                "backend_image": payload["backend_image"],
                "backend_hostname": payload["backend_hostname"],
                "frontend_origin": payload["frontend_origin"],
                "bastion_instance_id": payload["bastion_instance_id"],
                "bastion_tags": payload["bastion_tags"],
                "cluster_name": payload["cluster_name"],
                "kubernetes_version": payload["kubernetes_version"],
                "kubernetes_version_status": payload["kubernetes_version_status"],
                "state_fingerprints": payload["state_fingerprints"],
                "retained_v9_run_id": payload["retained_v9_run_id"],
                "retained_v9_plan_sha256": payload["retained_v9_plan_sha256"],
                "monitoring_bucket": payload["monitoring_bucket"],
                "monitoring_prefix": payload["monitoring_prefix"],
                "bundle_revision_sha256": payload["bundle_revision_sha256"],
                "repair_helper_sha256": payload["repair_helper_sha256"],
                "smoke_helper_sha256": payload["smoke_helper_sha256"],
                "deployment_runner_sha256": payload["deployment_runner_sha256"],
                "kubectl_version": payload["kubectl_version"],
                "dev_eks_state_sha256": payload["dev_eks_state_sha256"],
                "dev_eks_state_lineage": payload["dev_eks_state_lineage"],
                "dev_eks_state_serial": payload["dev_eks_state_serial"],
                "actions": payload["permitted_actions"],
            }
            canonical = json.dumps(scope_fields, sort_keys=True, separators=(",", ":")).encode()
            payload["repair_scope_sha256"] = hashlib.sha256(canonical).hexdigest()
            payload["paid_approval"]["scope_sha256"] = payload["repair_scope_sha256"]
            payload["paid_approval"]["action"] = "APPLY DEV-EKS REPAIR-AND-RESUME " + payload["repair_scope_sha256"]
            receipt.write_text(json.dumps(payload), encoding="utf-8")
            receipt.chmod(0o600)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            aws_log = root / "aws.log"
            (fake_bin / "aws").write_text(
                "#!/usr/bin/env bash\n"
                f"printf '%s\\n' \"$*\" >> {aws_log!s}\n"
                "exit 1\n",
                encoding="utf-8",
            )
            (fake_bin / "aws").chmod(0o755)
            approval = payload["paid_approval"]["action"]
            result = subprocess.run(
                [
                    str(COORDINATOR),
                    "--mode",
                    "run",
                    "--aws-profile",
                    "offline",
                    "--action-values-capsule",
                    str(capsule),
                    "--preflight-json",
                    str(preflight),
                    "--authorization-receipt",
                    str(receipt),
                    "--approval",
                    approval,
                    "--run-id",
                    "20260825T000000Z-4242",
                ],
                cwd=ROOT,
                env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("active v11 repair receipt binding", result.stderr)
            self.assertFalse(aws_log.exists(), "receipt validation must precede S3/SSM AWS calls")
            terminal = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(terminal["status"], "consumed")
            self.assertEqual(terminal["terminal_result"], "failed")

    def test_run_performs_read_only_identity_before_upload_and_redacts_ssm_terminal_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capsule = root / "action-values.json"
            capsule.write_bytes(CAPSULE.read_bytes())
            capsule.chmod(0o600)
            state_bytes = b'{"lineage":"lineage","serial":7,"resources":[]}'
            state_sha = hashlib.sha256(state_bytes).hexdigest()
            preflight = root / "preflight.json"
            preflight.write_text(
                json.dumps(
                    {
                        "schema_version": "dev-eks-v11-live-preflight/v1",
                        "expected_account_id": "419496180357",
                        "expected_region": "ap-northeast-2",
                        "backend_config_sha256": hashlib.sha256(
                            (ROOT / "infra" / "environments" / "dev-eks" / "backend.hcl").read_bytes()
                        ).hexdigest(),
                        "bastion_instance_id": "i-0123456789abcdef0",
                        "cluster_name": "kdt-travelplanner-dev-eks",
                        "monitoring_bucket": "private-bucket",
                        "monitoring_prefix": "kubernetes/monitoring",
                        "retained_v9_run_id": "20260825T054716Z-45689",
                        "retained_v9_plan_sha256": "5bc719aeb6c0ed2087095d056e11fb0766c580dd28c297b859cab33d5a169f3a",
                        "bundle_revision_sha256": "a" * 64,
                        "kubernetes_version": "1.35",
                        "kubernetes_version_status": "STANDARD_SUPPORT",
                        "bastion_tags": {"Environment": "dev", "Stack": "dev-eks", "Phase": "eks-baseline", "Project": "kdt-travelplanner", "Name": "kdt-travelplanner-dev-eks-bastion"},
                        "kubectl_version": "1.35.6",
                        "dev_eks_state_sha256": state_sha,
                        "dev_eks_state_lineage": "lineage",
                        "dev_eks_state_serial": 7,
                        "state_fingerprints": [
                            {"key": key, "sha256": state_sha, "lineage": "lineage", "serial": 7}
                            for key in ("dev/terraform.tfstate", "dev-runtime/terraform.tfstate", "dev-load-test/terraform.tfstate", "dev-eks/terraform.tfstate")
                        ],
                        "helper_sha256": hashlib.sha256((ROOT / "scripts" / "eks" / "repair-dev-eks-bastion.sh").read_bytes()).hexdigest(),
                        "smoke_helper_sha256": hashlib.sha256((ROOT / "scripts" / "eks" / "run-dev-eks-repair-smoke.sh").read_bytes()).hexdigest(),
                        "operator_iam_status": "operator-policy-evidence-verified",
                        "bastion_iam_status": "state-policy-evidence-verified",
                        "controller_iam_status": "state-policy-evidence-verified",
                    }
                ),
                encoding="utf-8",
            )
            preflight.chmod(0o600)
            receipt = root / "repair-authorization.private.json"
            issue = subprocess.run(
                [
                    str(COORDINATOR),
                    "--mode",
                    "issue",
                    "--action-values-capsule",
                    str(capsule),
                    "--preflight-json",
                    str(preflight),
                    "--authorization-receipt",
                    str(receipt),
                    "--run-id",
                    "20260825T000010Z-4252",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(issue.returncode, 0, issue.stderr)
            approval = "APPLY DEV-EKS REPAIR-AND-RESUME " + json.loads(receipt.read_text(encoding="utf-8"))["repair_scope_sha256"]
            fake_bin = root / "bin"
            fake_bin.mkdir()
            aws_log = root / "aws.log"
            fake_aws = r'''#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >> "$FAKE_AWS_LOG"
case "$*" in
  *"sts get-caller-identity"*) printf '419496180357\n' ;;
  *"ec2 describe-instances"*) printf '%s' '{"Reservations":[{"Instances":[{"InstanceId":"i-0123456789abcdef0","State":{"Name":"running"},"Tags":[{"Key":"Environment","Value":"dev"},{"Key":"Stack","Value":"dev-eks"},{"Key":"Phase","Value":"eks-baseline"},{"Key":"Project","Value":"kdt-travelplanner"},{"Key":"Name","Value":"kdt-travelplanner-dev-eks-bastion"}]}]}]}' ;;
  *"eks describe-cluster-versions"*) printf '%s' '{"clusterVersions":[{"clusterVersion":"1.35","clusterType":"eks","versionStatus":"STANDARD_SUPPORT"}]}' ;;
  *"eks describe-cluster"*) printf '%s' '{"cluster":{"arn":"arn:aws:eks:ap-northeast-2:419496180357:cluster/kdt-travelplanner-dev-eks","status":"ACTIVE","version":"1.35"}}' ;;
  *"s3api get-object"*"bundle-manifest.json"*) printf '%s' '{"schema_version":"dev-eks-bundle/v1","revision":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}' > "${!#}" ;;
  *"s3api get-object"*) printf '%s' '{"lineage":"lineage","serial":7,"resources":[]}' > "${!#}" ;;
  *"s3 cp"*) : ;;
  *"ssm send-command"*) printf 'not-a-command-id\n' ;;
  *) exit 1 ;;
esac
'''
            (fake_bin / "aws").write_text(fake_aws, encoding="utf-8")
            (fake_bin / "aws").chmod(0o755)
            failure = ROOT / "evidence" / "eks-deploy" / "20260825T000010Z-4252" / "ssm-repair-failure.private.json"
            self.addCleanup(lambda: shutil.rmtree(failure.parent, ignore_errors=True))
            result = subprocess.run(
                [
                    str(COORDINATOR),
                    "--mode",
                    "run",
                    "--aws-profile",
                    "offline",
                    "--action-values-capsule",
                    str(capsule),
                    "--preflight-json",
                    str(preflight),
                    "--authorization-receipt",
                    str(receipt),
                    "--approval",
                    approval,
                    "--run-id",
                    "20260825T000010Z-4252",
                ],
                cwd=ROOT,
                env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}", "FAKE_AWS_LOG": str(aws_log)},
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("repair SSM command id is invalid", result.stderr)
            records = aws_log.read_text(encoding="utf-8").splitlines()
            self.assertLess(next(i for i, line in enumerate(records) if "sts get-caller-identity" in line), next(i for i, line in enumerate(records) if "s3 cp" in line))
            self.assertLess(next(i for i, line in enumerate(records) if "s3 cp" in line), next(i for i, line in enumerate(records) if "ssm send-command" in line))
            self.assertTrue(failure.exists(), result.stderr)
            failure_payload = json.loads(failure.read_text(encoding="utf-8"))
            self.assertEqual(failure_payload["status"], "invalid_command_id")
            self.assertNotIn("StandardErrorContent", failure.read_text(encoding="utf-8"))
            self.assertEqual(json.loads(receipt.read_text(encoding="utf-8"))["status"], "consumed")


if __name__ == "__main__":
    unittest.main()
