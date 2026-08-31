"""Executable offline proof for the authenticated v11 no-Terraform resume path."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
COORDINATOR = ROOT / "scripts" / "eks" / "run-dev-eks-repair-and-resume.sh"
DEPLOYER = ROOT / "scripts" / "eks" / "deploy-dev-eks.sh"
CAPSULE = ROOT / "evidence" / "eks-deploy" / "20260824T133440Z-15798" / "action-values.json"

# The fake AWS end-to-end fixture uses a disposable temp receipt/preflight.
os.environ.setdefault("OFFLINE_TEST", "true")


class V11RepairEndToEndTest(unittest.TestCase):
    def test_authenticated_repair_resume_smoke_consumes_receipt_without_terraform(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            capsule = root / "action-values.json"
            capsule.write_bytes(CAPSULE.read_bytes())
            capsule.chmod(0o600)
            capsule_values = json.loads(capsule.read_text(encoding="utf-8"))
            run_id = "20260825T001500Z-9511"
            retained_run = "20260825T054716Z-45689"
            render_sha = "b" * 64
            cname = "k8s-travelplanner-123.ap-northeast-2.elb.amazonaws.com"
            state_payload = {
                "lineage": "v11-test-lineage",
                "serial": 9,
                "resources": [],
                "outputs": {
                    "vpc_id": {"value": capsule_values["vpc_id"]},
                    "public_subnet_ids": {"value": capsule_values["public_subnet_ids"]},
                    "api_certificate_arn": {"value": capsule_values["api_certificate_arn"]},
                    "backend_ecr_repository_url": {"value": "419496180357.dkr.ecr.ap-northeast-2.amazonaws.com/kdt-travelplanner-dev-backend"},
                    "profile_image_bucket_name": {"value": "kdt-travelplanner-dev-profile-images-419496180357"},
                    "profile_image_public_base_url": {"value": "https://images.example.com"},
                    "monitoring_config_bucket_name": {"value": "kdt-travelplanner-dev-eks-monitoring-config-419496180357"},
                    "monitoring_bundle_prefix": {"value": "kubernetes/monitoring"},
                    "monitoring_bundle_revision": {"value": "a" * 64},
                    "deployment_contract_s3_key": {"value": "kubernetes/monitoring/runtime-contract.json"},
                    "deployment_contract_sha256": {"value": "c" * 64},
                    "bastion_instance_id": {"value": "i-0123456789abcdef0"},
                    "cluster_name": {"value": "kdt-travelplanner-dev-eks"},
                    "node_group_name": {"value": "kdt-travelplanner-dev-eks-nodes"},
                    "database_identifier": {"value": "kdt-travelplanner-dev-postgres"},
                    "redis_replication_group_id": {"value": "kdt-travelplanner-dev-redis"},
                    "redis_primary_endpoint": {"value": "master.kdt-travelplanner-dev-redis.example.com"},
                    "redis_port": {"value": 6379},
                    "redis_auth_secret_arn": {"value": "arn:aws:secretsmanager:ap-northeast-2:419496180357:secret:redis-test"},
                    "monitoring_instance_id": {"value": "i-0fedcba9876543210"},
                    "monitoring_private_dns_name": {"value": "monitoring.dev-eks.example.com"},
                    "cluster_version": {"value": "1.35"},
                },
            }
            state_bytes = json.dumps(state_payload, sort_keys=True, separators=(",", ":")).encode()
            state_sha = hashlib.sha256(state_bytes).hexdigest()
            preflight = root / "live-preflight.private.json"
            preflight.write_text(
                json.dumps(
                    {
                        "schema_version": "dev-eks-v11-live-preflight/v1",
                        "expected_account_id": "419496180357",
                        "expected_region": "ap-northeast-2",
                        "backend_config_sha256": hashlib.sha256((ROOT / "infra" / "environments" / "dev-eks" / "backend.hcl").read_bytes()).hexdigest(),
                        "bastion_instance_id": "i-0123456789abcdef0",
                        "cluster_name": "kdt-travelplanner-dev-eks",
                        "monitoring_bucket": "kdt-travelplanner-dev-eks-monitoring-config-419496180357",
                        "monitoring_prefix": "kubernetes/monitoring",
                        "retained_v9_run_id": retained_run,
                        "retained_v9_plan_sha256": "5bc719aeb6c0ed2087095d056e11fb0766c580dd28c297b859cab33d5a169f3a",
                        "bundle_revision_sha256": "a" * 64,
                        "kubernetes_version": "1.35",
                        "kubernetes_version_status": "STANDARD_SUPPORT",
                        "bastion_tags": {"Environment": "dev", "Stack": "dev-eks", "Phase": "eks-baseline", "Project": "kdt-travelplanner", "Name": "kdt-travelplanner-dev-eks-bastion"},
                        "kubectl_version": "1.35.6",
                        "dev_eks_state_sha256": state_sha,
                        "dev_eks_state_lineage": state_payload["lineage"],
                        "dev_eks_state_serial": state_payload["serial"],
                        "state_fingerprints": [
                            {"key": key, "sha256": state_sha, "lineage": state_payload["lineage"], "serial": state_payload["serial"]}
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
                    str(COORDINATOR), "--mode", "issue", "--action-values-capsule", str(capsule),
                    "--preflight-json", str(preflight), "--authorization-receipt", str(receipt), "--run-id", run_id,
                ], cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(issue.returncode, 0, issue.stderr)
            receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
            receipt_payload["status"] = "active"
            receipt_payload["paid_approval"]["status"] = "approved"
            receipt_payload["paid_approval"]["action"] = "APPLY DEV-EKS REPAIR-AND-RESUME " + receipt_payload["repair_scope_sha256"]
            receipt.write_text(json.dumps(receipt_payload), encoding="utf-8")
            receipt.chmod(0o600)

            state_file = root / "state.json"
            state_file.write_bytes(state_bytes)
            backend_digest = json.loads(capsule.read_text(encoding="utf-8"))["backend_image"].split("sha256:", 1)[1]
            stage_file = root / "stage.txt"
            terraform_log = root / "terraform.log"
            (fake_bin / "terraform").write_text(
                "#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> \"${FAKE_TERRAFORM_LOG}\"\nexit 97\n",
                encoding="utf-8",
            )
            (fake_bin / "terraform").chmod(0o755)
            fake_aws = f'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
joined = " ".join(args)
def value(flag):
    return args[args.index(flag) + 1]
def write(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(data)
if "sts" in args and "get-caller-identity" in args:
    print("419496180357")
elif "eks" in args and "describe-cluster-versions" in args:
    print(json.dumps({{"clusterVersions":[{{"clusterVersion":"1.35","clusterType":"eks","versionStatus":"STANDARD_SUPPORT"}}]}}))
elif "ecr" in args and "describe-images" in args:
    print("sha256:" + {backend_digest!r})
elif "s3api" in args and "head-object" in args:
    print("{{}}")
elif "s3api" in args and "get-object" in args:
    key = value("--key")
    destination = args[-1]
    if key.endswith("bundle-manifest.json"):
        write(destination, json.dumps({{"schema_version":"dev-eks-bundle/v1","revision":"a" * 64}}))
    else:
        write(destination, open({str(state_file)!r}, encoding="utf-8").read())
    print("{{}}")
elif "s3api" in args and "head-bucket" in args:
    print("{{}}")
elif args[:2] == ["s3", "cp"]:
    pass
elif "ssm" in args and "send-command" in args:
    comment = value("--comment")
    stage = next((candidate for candidate in ("repair-smoke", "namespace-secret", "ingress-wait") if comment.endswith(candidate)), comment.rsplit("-", 1)[-1])
    with open({str(stage_file)!r}, "w", encoding="utf-8") as handle:
        handle.write(stage)
    print("00000000-0000-4000-8000-000000000001")
elif "ssm" in args and "get-command-invocation" in args:
    stage = open({str(stage_file)!r}, encoding="utf-8").read()
    if stage == "prepare":
        stdout = ""
        stderr = "stage=prepare status=success render_sha256={render_sha}\\n"
    elif stage == "ingress-wait":
        stdout = "CLOUDFLARE_CNAME_TARGET={cname}\\n"
        stderr = ""
    elif stage == "repair-smoke":
        stdout = "stage=repair-smoke status=success\\n"
        stderr = ""
    else:
        stdout = ""
        stderr = ""
    print(json.dumps({{"CommandId":"00000000-0000-4000-8000-000000000001","InstanceId":"i-0123456789abcdef0","Status":"Success","ResponseCode":0,"StandardOutputContent":stdout,"StandardErrorContent":stderr}}))
elif "elbv2" in args and "describe-load-balancers" in args:
    print(json.dumps([{{"LoadBalancerArn":"arn:aws:elasticloadbalancing:ap-northeast-2:419496180357:loadbalancer/app/travel/123"}}]))
elif "elbv2" in args and "describe-tags" in args:
    print(json.dumps({{"TagDescriptions":[{{"Tags":[{{"Key":"elbv2.k8s.aws/cluster","Value":"kdt-travelplanner-dev-eks"}},{{"Key":"ingress.k8s.aws/stack","Value":"kdt-travelplanner-dev-eks"}}]}}]}}))
elif "elbv2" in args and "describe-target-groups" in args:
    print("arn:aws:elasticloadbalancing:ap-northeast-2:419496180357:targetgroup/travel/123")
elif "elbv2" in args and "describe-target-health" in args:
    print(json.dumps({{"TargetHealthDescriptions":[{{"TargetHealth":{{"State":"healthy"}}}}]}}))
elif "rds" in args and "describe-db-instances" in args:
    print("available")
elif "elasticache" in args and "describe-replication-groups" in args:
    print("available")
else:
    raise SystemExit(0)
'''
            (fake_bin / "aws").write_text(fake_aws, encoding="utf-8")
            (fake_bin / "aws").chmod(0o755)
            result = subprocess.run(
                [
                    str(DEPLOYER), "--mode", "resume", "--resume-from", "prepare", "--resume-run-id", retained_run,
                    "--run-id", run_id, "--skip-terraform-apply", "--non-interactive", "--offline-test",
                    "--aws-profile", "offline", "--region", "ap-northeast-2", "--expected-account-id", "419496180357",
                    "--backend-image", json.loads(capsule.read_text(encoding="utf-8"))["backend_image"],
                    "--backend-hostname", json.loads(capsule.read_text(encoding="utf-8"))["backend_hostname"],
                    "--frontend-origin", json.loads(capsule.read_text(encoding="utf-8"))["frontend_origin"],
                    "--action-values-capsule", str(capsule), "--authorization-receipt", str(receipt),
                    "--repair-preflight-json", str(preflight), "--plan-handoff", str(ROOT / ".codex/plans/dev-eks-deployment-automation/handoff-v11.yaml"),
                ], cwd=ROOT, env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}", "FAKE_TERRAFORM_LOG": str(terraform_log), "DEV_EKS_DEFER_CNAME_OUTPUT": "true"}, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(result.stdout, "")
            final_cname = ROOT / "evidence" / "eks-deploy" / run_id / "final-cname.private.txt"
            self.addCleanup(lambda: final_cname.parent.exists() and __import__("shutil").rmtree(final_cname.parent, ignore_errors=True))
            self.assertTrue(final_cname.exists(), result.stderr + result.stdout)
            self.assertEqual(final_cname.read_text(encoding="utf-8").strip(), "CLOUDFLARE_CNAME_TARGET=" + cname)
            self.assertFalse(terraform_log.exists(), "authenticated v11 repair/resume invoked Terraform")
            terminal = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(terminal["status"], "consumed")
            self.assertEqual(terminal["terminal_result"], "completed")
            summary = json.loads((final_cname.parent / "deployment-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "success")


if __name__ == "__main__":
    unittest.main()
