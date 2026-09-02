"""Offline contracts for the operator-side dev-eks orchestrator."""

from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "eks" / "deploy-dev-eks.sh"
BACKEND_CONFIG_SHA256 = hashlib.sha256((ROOT / "infra" / "environments" / "dev-eks" / "backend.hcl").read_bytes()).hexdigest()
V9_HANDOFF = ROOT / ".codex" / "plans" / "dev-eks-deployment-automation" / "handoff-v9.yaml"
V9_MANIFEST = ROOT / ".codex" / "plans" / "dev-eks-deployment-automation" / "plan-v9.yaml"
V9_MANIFEST_SHA256 = hashlib.sha256(V9_MANIFEST.read_bytes()).hexdigest()
V9_HANDOFF_SHA256 = hashlib.sha256(V9_HANDOFF.read_bytes()).hexdigest()
V15_HANDOFF = ROOT / ".codex" / "plans" / "dev-eks-deployment-automation" / "handoff-v15.yaml"
V15_MANIFEST = ROOT / ".codex" / "plans" / "dev-eks-deployment-automation" / "plan-v15.yaml"
V15_MANIFEST_SHA256 = hashlib.sha256(V15_MANIFEST.read_bytes()).hexdigest()
V15_HANDOFF_SHA256 = hashlib.sha256(V15_HANDOFF.read_bytes()).hexdigest()


class OperatorOrchestratorContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SCRIPT.read_text(encoding="utf-8")

    def test_shell_syntax_and_shellcheck_are_clean(self) -> None:
        syntax = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        lint = subprocess.run(["shellcheck", "--severity=warning", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)

    def test_modes_and_separate_exact_approval_prompts_are_present(self) -> None:
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        for mode in ("run", "prepare", "resume", "dry-run"):
            self.assertIn(mode, self.source)
        self.assertIn('APPLY TERRAFORM $TERRAFORM_PLAN_SHA256', self.source)
        self.assertIn('APPLY KUBERNETES $KUBERNETES_RENDER_SHA256', self.source)
        self.assertIn("--terraform-plan-sha256", self.source)
        self.assertIn("--kubernetes-render-sha256", self.source)
        self.assertNotIn("--yes", self.source)
        self.assertNotIn("auto-approve", self.source)

    def test_authenticated_handoff_manifest_backend_and_capsule_hashes_are_pinned(self) -> None:
        self.assertIn('EXPECTED_PLAN_HANDOFF_SHA256="' + V15_HANDOFF_SHA256 + '"', self.source)
        self.assertIn('EXPECTED_PLAN_MANIFEST_SHA256="' + V15_MANIFEST_SHA256 + '"', self.source)
        self.assertIn('EXPECTED_V9_PLAN_HANDOFF_SHA256="' + V9_HANDOFF_SHA256 + '"', self.source)
        self.assertIn('EXPECTED_V9_PLAN_MANIFEST_SHA256="' + V9_MANIFEST_SHA256 + '"', self.source)
        self.assertIn('EXPECTED_BACKEND_CONFIG_SHA256="' + BACKEND_CONFIG_SHA256 + '"', self.source)
        self.assertIn('EXPECTED_CAPSULE_SHA256="3c0a636a230247a10c785822487df1ca8b5a1cfeead4d695f54afdc98d4f44f8"', self.source)
        self.assertIn("production mutation requires the canonical action-values capsule path", self.source)

    def test_v7_receipt_and_prepare_only_contract_is_present(self) -> None:
        self.assertIn("--authorization-receipt", self.source)
        self.assertIn("--prepare-only", self.source)
        self.assertIn("validate_authorization_receipt", self.source)
        self.assertIn("dev-eks-autonomous-authorization/v1", self.source)
        self.assertIn('status="consumed"', self.source)
        self.assertIn("authorization receipt render hash does not match the actual render", self.source)

    def test_v15_prepare_binds_render_before_post_prepare_validation(self) -> None:
        self.assertIn("bind_autonomous_receipt_render()", self.source)
        self.assertIn('elif [[ "$CREATE_RECEIPT_SCHEMA" == "dev-eks-autonomous-authorization/v1" ]]; then\n    bind_autonomous_receipt_render', self.source)
        self.assertIn("autonomous receipt render binding differs before reuse", self.source)

    def test_cloud_smoke_uploads_operator_evidence_before_remote_helper(self) -> None:
        self.assertIn('schema_version:"dev-eks-operator-cloud-smoke/v1"', self.source)
        self.assertIn('OPERATOR_DATA_KEY="$MONITORING_PREFIX/runs/$RUN_ID/smoke/operator-data-evidence.json"', self.source)
        self.assertIn('--operator-data-key %q --expected-operator-data-sha256 %q', self.source)
        self.assertIn('OPERATOR_DATA_KEY="${OPERATOR_DATA_KEY:-offline/smoke/operator-data-evidence.json}"', self.source)
        self.assertIn('OPERATOR_DATA_SHA256="${OPERATOR_DATA_SHA256:-0000000000000000000000000000000000000000000000000000000000000000}"', self.source)
        self.assertIn('if [[ "$OFFLINE_TEST" == false ]]; then\n        run_operator_native_smoke\n      fi\n      run_remote_smoke', self.source)

    def test_state_and_plan_guards_are_fail_closed(self) -> None:
        self.assertIn("show -json", self.source)
        self.assertIn("dev-eks-post-apply", self.source)
        self.assertIn("trap cleanup EXIT", self.source)
        self.assertIn("dev-runtime", self.source)
        self.assertIn("dev-load-test", self.source)
        self.assertIn("SKIP_TERRAFORM_APPLY", self.source)
        self.assertIn("CLOUDFLARE_CNAME_TARGET=", self.source)
        self.assertIn("elb\\.amazonaws\\.com", self.source)
        self.assertIn("--expected-account-id", self.source)
        self.assertIn("--expected-region", self.source)
        self.assertIn("AWS_DEFAULT_REGION", self.source)
        self.assertIn("printf -v command", self.source)
        self.assertIn("approved_render", self.source)
        self.assertIn("candidate_count", self.source)
        self.assertIn('RESUME_FROM" == "prepare"', self.source)
        self.assertNotIn('if [[ "$MODE" == "resume" ]]; then\n      break', self.source)
        self.assertIn("State precondition could not be read", self.source)
        self.assertIn("TERRAFORM_PLAN=\"$plan_real\"", self.source)
        self.assertIn('AWS_PROFILE="$AWS_PROFILE" terraform', self.source)
        self.assertIn("saved plan enables public EKS endpoint access", self.source)
        self.assertIn("describe-cluster-versions", self.source)
        self.assertIn("resume-run-id", self.source)
        support_function = self.source.split("verify_eks_support_status()", 1)[1].split("validate_ecr_repository_url()", 1)[0]
        self.assertNotIn("1.35", support_function)
        for forbidden in ("--query", "--include-all", "--default-only", "--status", "--version-status"):
            self.assertNotIn(forbidden, support_function)

    def test_dry_run_does_not_require_aws(self) -> None:
        before = set((ROOT / "evidence" / "eks-deploy").glob("*/deployment-summary.json"))
        result = subprocess.run(
            [
                "bash",
                str(SCRIPT),
                "--mode",
                "dry-run",
                "--aws-profile",
                "offline",
                "--region",
                "ap-northeast-2",
                "--expected-account-id",
                "123456789012",
                "--backend-image",
                "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/backend@sha256:" + "a" * 64,
                "--backend-hostname",
                "api.example.com",
                "--frontend-origin",
                "https://www.example.com",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("status=dry-run", result.stderr)
        self.assertNotIn("CLOUDFLARE_CNAME_TARGET=", result.stdout)
        created = set((ROOT / "evidence" / "eks-deploy").glob("*/deployment-summary.json")) - before
        self.assertEqual(len(created), 1)
        summary = json.loads(next(iter(created)).read_text(encoding="utf-8"))
        self.assertEqual(summary.get("provenance_check"), "structural-only")
        self.assertEqual(summary.get("status"), "dry-run")

    def test_fake_aws_terraform_ssm_success_reaches_only_validated_cname(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            bundle_revision = "a" * 64
            render_sha = "b" * 64
            outputs = {
                "vpc_id": {"value": "vpc-0123456789abcdef0"},
                "public_subnet_ids": {"value": ["subnet-a", "subnet-b"]},
                "api_certificate_arn": {"value": "arn:aws:acm:ap-northeast-2:123456789012:certificate/a"},
                "backend_ecr_repository_url": {"value": "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/backend"},
                "profile_image_bucket_name": {"value": "kdt-travelplanner-profile-images"},
                "profile_image_public_base_url": {"value": "https://images.example.com"},
                "monitoring_config_bucket_name": {"value": "private-bucket"},
                "monitoring_bundle_prefix": {"value": "kubernetes/monitoring"},
                "monitoring_bundle_revision": {"value": bundle_revision},
                "deployment_contract_s3_key": {"value": "kubernetes/monitoring/runtime-contract.json"},
                "deployment_contract_sha256": {"value": "d" * 64},
                "bastion_instance_id": {"value": "i-0123456789abcdef0"},
                "cluster_name": {"value": "kdt-travelplanner-dev-eks"},
                "node_group_name": {"value": "kdt-travelplanner-dev-eks-ng"},
                "database_identifier": {"value": "kdt-travelplanner-dev-eks-db"},
                "redis_replication_group_id": {"value": "kdt-travelplanner-dev-eks-redis"},
                "redis_primary_endpoint": {"value": "redis.dev-eks.internal"},
                "redis_port": {"value": 6379},
                "redis_auth_secret_arn": {"value": "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:redis"},
                "monitoring_instance_id": {"value": "i-0fedcba9876543210"},
                "monitoring_private_dns_name": {"value": "monitoring.dev-eks.internal"},
                "cluster_version": {"value": "1.35"},
            }
            (fake_bin / "terraform").write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"$*\" == *' output -json'* ]]; then\n"
                f"  printf '%s' '{json.dumps(outputs)}'\n"
                "  exit 0\n"
                "fi\n"
                "if [[ \"$*\" == *' state list'* ]]; then exit 0; fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            (fake_bin / "aws").write_text(
                "#!/usr/bin/env bash\n"
                "case \"$*\" in\n"
                "  *'sts get-caller-identity'*) printf '123456789012\\n' ;;\n"
                "  *'eks describe-cluster-versions'*) printf '%s' '{\"clusterVersions\":[{\"clusterVersion\":\"1.35\",\"clusterType\":\"eks\",\"versionStatus\":\"STANDARD_SUPPORT\"}]}' ;;\n"
                "  *'ecr describe-images'*) printf 'sha256:" + "c" * 64 + "\\n' ;;\n"
                "  *'ssm send-command'*) printf '00000000-0000-4000-8000-000000000001\\n' ;;\n"
                "  *'ssm get-command-invocation'*) printf '%s' '{\"CommandId\":\"00000000-0000-4000-8000-000000000001\",\"InstanceId\":\"i-0123456789abcdef0\",\"Status\":\"Success\",\"ResponseCode\":0,\"StandardOutputContent\":\"CLOUDFLARE_CNAME_TARGET=k8s-default-ingress-abc.ap-northeast-2.elb.amazonaws.com\\nstage=smoke status=success\\n\",\"StandardErrorContent\":\"stage=prepare status=success render_sha256="
                f"{render_sha}\\n\"}}' ;;\n"
                "  *) exit 0 ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            for executable in (fake_bin / "terraform", fake_bin / "aws"):
                executable.chmod(0o755)
            self._operator_run_id = "20260825T000000Z-4242"
            self._operator_target_version = "1.35"
            self._operator_capsule = root / "action-values.json"
            self._operator_receipt = root / "authorization.json"
            self._write_operator_receipt(target_version="1.35")
            result = subprocess.run(
                [
                    "bash",
                    str(SCRIPT),
                    "--mode",
                    "run",
                    "--non-interactive",
                    "--offline-test",
                    "--skip-terraform-apply",
                    "--aws-profile",
                    "offline",
                    "--region",
                    "ap-northeast-2",
                    "--expected-account-id",
                    "123456789012",
                    "--kubernetes-render-sha256",
                    render_sha,
                    "--terraform-plan-sha256",
                    "c" * 64,
                    "--backend-image",
                    "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/backend@sha256:" + "c" * 64,
                    "--backend-hostname",
                    "api.example.com",
                    "--frontend-origin",
                    "https://www.example.com",
                    "--run-id",
                    self._operator_run_id,
                    "--action-values-capsule",
                    str(self._operator_capsule),
                    "--authorization-receipt",
                    str(self._operator_receipt),
                ],
                cwd=ROOT,
                env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(result.stdout.strip(), "CLOUDFLARE_CNAME_TARGET=k8s-default-ingress-abc.ap-northeast-2.elb.amazonaws.com")
            self.assertNotIn("SecretString", result.stdout)

    def _operator_fixture(
        self,
        root: Path,
        *,
        account: str = "123456789012",
        state_output: str = "",
        state_cluster_version: str = "1.35",
        include_cluster_version: bool = True,
        ssm_status: str = "Success",
        ssm_stdout: str = "CLOUDFLARE_CNAME_TARGET=k8s-default-ingress-abc.ap-northeast-2.elb.amazonaws.com\n",
        ssm_transient_count: int = 0,
        ssm_lookup_error: str | None = None,
        ssm_invocation_overrides: dict | None = None,
        ssm_remove_fields: tuple[str, ...] = (),
        ssm_raw_invocation: str | None = None,
        plan_json: dict | None = None,
        target_version: str = "1.35",
        eks_response: dict | None = None,
        eks_raw: str | None = None,
        eks_stderr: str = "",
        eks_exit_code: int = 0,
        ecr_digest: str = "c" * 64,
        aws_log: Path | None = None,
    ) -> tuple[Path, Path]:
        root.mkdir(parents=True, exist_ok=True)
        fake_bin = root / "bin"
        fake_bin.mkdir()
        env_log = root / "terraform-profile.log"
        outputs = {
            "vpc_id": {"value": "vpc-0123456789abcdef0"},
            "public_subnet_ids": {"value": ["subnet-a", "subnet-b"]},
            "api_certificate_arn": {"value": "arn:aws:acm:ap-northeast-2:123456789012:certificate/a"},
            "backend_ecr_repository_url": {"value": "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/backend"},
            "profile_image_bucket_name": {"value": "kdt-travelplanner-profile-images"},
            "profile_image_public_base_url": {"value": "https://images.example.com"},
            "monitoring_config_bucket_name": {"value": "private-bucket"},
            "monitoring_bundle_prefix": {"value": "kubernetes/monitoring"},
            "monitoring_bundle_revision": {"value": "a" * 64},
            "deployment_contract_s3_key": {"value": "kubernetes/monitoring/runtime-contract.json"},
            "deployment_contract_sha256": {"value": "d" * 64},
            "bastion_instance_id": {"value": "i-0123456789abcdef0"},
            "cluster_name": {"value": "kdt-travelplanner-dev-eks"},
            "node_group_name": {"value": "kdt-travelplanner-dev-eks-ng"},
            "database_identifier": {"value": "kdt-travelplanner-dev-eks-db"},
            "redis_replication_group_id": {"value": "kdt-travelplanner-dev-eks-redis"},
            "redis_primary_endpoint": {"value": "redis.dev-eks.internal"},
            "redis_port": {"value": 6379},
            "redis_auth_secret_arn": {"value": "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:redis"},
            "monitoring_instance_id": {"value": "i-0fedcba9876543210"},
            "monitoring_private_dns_name": {"value": "monitoring.dev-eks.internal"},
        }
        if include_cluster_version:
            outputs["cluster_version"] = {"value": state_cluster_version}
        plan_json = plan_json if plan_json is not None else {
            "variables": {"kubernetes_version": {"value": target_version}},
            "planned_values": {
                "root_module": {
                    "resources": [
                        {
                            "address": "module.eks.aws_eks_cluster.this",
                            "mode": "managed",
                            "type": "aws_eks_cluster",
                            "name": "this",
                            "values": {"version": target_version},
                        }
                    ]
                }
            },
            "resource_changes": [],
        }
        eks_response = eks_response if eks_response is not None else {
            "clusterVersions": [
                {
                    "clusterVersion": target_version,
                    "clusterType": "eks",
                    "versionStatus": "STANDARD_SUPPORT",
                }
            ]
        }
        eks_payload = eks_raw if eks_raw is not None else json.dumps(eks_response)
        ssm_overrides_json = json.dumps(ssm_invocation_overrides or {})
        ssm_remove_fields_json = json.dumps(list(ssm_remove_fields))
        terraform = (
            "#!/usr/bin/env bash\n"
            "if [[ -n \"${FAKE_TF_ENV_LOG:-}\" ]]; then printf '%s\\n' \"${AWS_PROFILE:-}\" >> \"$FAKE_TF_ENV_LOG\"; fi\n"
            "if [[ -n \"${FAKE_TF_CALL_LOG:-}\" ]]; then printf '%s\\n' \"$*\" >> \"$FAKE_TF_CALL_LOG\"; fi\n"
            "if [[ \"$*\" == *' output -json'* ]]; then\n"
            f"  printf '%s' '{json.dumps(outputs)}'\n"
            "  exit 0\n"
            "fi\n"
            "if [[ \"$*\" == *' show -json'* ]]; then\n"
            "  plan_path=\"${!#}\"\n"
            "  if [[ \"${FAKE_PLAN_SOURCE:-}\" ]]; then printf '%s' 'replaced-source-plan' > \"$FAKE_PLAN_SOURCE\"; fi\n"
            "  if [[ \"${FAKE_TAMPER_PLAN:-false}\" == true ]]; then chmod u+w \"$plan_path\"; printf '%s' 'tampered-snapshot-plan' > \"$plan_path\"; fi\n"
            f"  printf '%s' '{json.dumps(plan_json)}'\n"
            "  exit 0\n"
            "fi\n"
            "if [[ \"$*\" == *' apply '* ]]; then\n"
            "  plan_path=\"${!#}\"\n"
            "  if [[ \"${FAKE_APPLY_CAPTURE:-}\" ]]; then cat \"$plan_path\" > \"$FAKE_APPLY_CAPTURE\"; fi\n"
            "  exit 0\n"
            "fi\n"
            "if [[ \"$*\" == *' plan '* ]]; then exit 0; fi\n"
            "if [[ \"$*\" == *' state list'* ]]; then\n"
            f"  if [[ \"$*\" == *'/infra/environments/dev-eks '* && \"${{FAKE_DEV_EKS_STATE:-}}\" ]]; then printf '%s' \"${{FAKE_DEV_EKS_STATE}}\"; else printf '%s' {state_output!r}; fi\n"
            "  exit 0\n"
            "fi\n"
            "exit 0\n"
        )
        (fake_bin / "terraform").write_text(terraform, encoding="utf-8")
        aws = f"""#!/usr/bin/env python3
import json
import os
import sys

args = sys.argv[1:]
joined = " ".join(args)
if os.environ.get("FAKE_AWS_LOG"):
    with open(os.environ["FAKE_AWS_LOG"], "a", encoding="utf-8") as handle:
        handle.write(joined + "\\n")
if os.environ.get("FAKE_AWS_ARGV_LOG"):
    with open(os.environ["FAKE_AWS_ARGV_LOG"], "a", encoding="utf-8") as handle:
        handle.write(json.dumps(args) + "\\n")

def value_after(flag):
    index = args.index(flag)
    return args[index + 1]

if "sts" in args and "get-caller-identity" in args:
    print({account!r})
    raise SystemExit(0)
if "eks" in args and "describe-cluster-versions" in args:
    sys.stdout.write({eks_payload!r})
    if os.environ.get("FAKE_EKS_STDERR"):
        sys.stderr.write(os.environ["FAKE_EKS_STDERR"])
    raise SystemExit({eks_exit_code})
if "ecr" in args and "describe-images" in args:
    print("sha256:{ecr_digest}")
    raise SystemExit(0)
if "eks" in args and "describe-cluster" in args:
    print("ACTIVE")
    raise SystemExit(0)
if "eks" in args and "describe-nodegroup" in args:
    print("ACTIVE")
    raise SystemExit(0)
if "rds" in args and "describe-db-instances" in args:
    print("available")
    raise SystemExit(0)
if "elasticache" in args and "describe-replication-groups" in args:
    print("available")
    raise SystemExit(0)
if "ec2" in args and "describe-instances" in args:
    instance_id = value_after("--instance-ids")
    tags = [
        {{"Key": "Environment", "Value": "dev"}},
        {{"Key": "Stack", "Value": "dev-eks"}},
        {{"Key": "Name", "Value": "kdt-travelplanner-dev-eks-bastion"}},
    ] if instance_id == "i-0123456789abcdef0" else []
    print(json.dumps({{"Reservations": [{{"Instances": [{{"InstanceId": instance_id, "State": {{"Name": "running"}}, "Tags": tags}}]}}]}}))
    raise SystemExit(0)
if "s3api" in args and "head-object" in args:
    if os.environ.get("FAKE_AWS_UNAVAILABLE_DURING_FAILURE") == "true":
        sys.stderr.write("simulated AWS unavailable during retained evidence capture\\n")
        raise SystemExit(254)
    print("{{}}")
    raise SystemExit(0)
if "s3api" in args and "get-object" in args:
    with open(args[-1], "w", encoding="utf-8") as handle:
        handle.write('{{"resources":[]}}')
    print("{{}}")
    raise SystemExit(0)
if "ssm" in args and "send-command" in args:
    parameters = value_after("--parameters")
    try:
        decoded = json.loads(parameters)
        command_values = decoded.get("commands") if isinstance(decoded, dict) else None
        if not isinstance(command_values, list) or len(command_values) != 1 or not isinstance(command_values[0], str) or not command_values[0]:
            raise ValueError("commands must be one non-empty string")
    except Exception as error:
        sys.stderr.write("fake AWS rejected parameters JSON: " + str(error) + "\\n")
        raise SystemExit(64)
    if os.environ.get("FAKE_SSM_COMMAND_LOG"):
        with open(os.environ["FAKE_SSM_COMMAND_LOG"], "a", encoding="utf-8") as handle:
            handle.write(json.dumps({{"parameters": decoded, "command_sha256": __import__("hashlib").sha256(command_values[0].encode()).hexdigest()}}) + "\\n")
    if os.environ.get("FAKE_SSM_SEND_STDERR"):
        sys.stderr.write(os.environ["FAKE_SSM_SEND_STDERR"])
    if os.environ.get("FAKE_SSM_SEND_EXIT"):
        raise SystemExit(int(os.environ["FAKE_SSM_SEND_EXIT"]))
    print(os.environ.get("FAKE_SSM_COMMAND_ID", "00000000-0000-4000-8000-000000000001"))
    raise SystemExit(0)
if "ssm" in args and "get-command-invocation" in args:
    if {ssm_lookup_error!r}:
        sys.stderr.write({ssm_lookup_error!r})
        raise SystemExit(254)
    if {ssm_raw_invocation!r} is not None:
        sys.stdout.write({ssm_raw_invocation!r})
        raise SystemExit(0)
    state_path = os.environ.get("FAKE_SSM_STATE")
    current_count = 0
    if state_path and os.path.exists(state_path):
        current_count = int(open(state_path, encoding="utf-8").read() or "0")
    if current_count < {ssm_transient_count}:
        if state_path:
            with open(state_path, "w", encoding="utf-8") as handle:
                handle.write(str(current_count + 1))
        sys.stderr.write("An error occurred (InvocationDoesNotExist) when calling the GetCommandInvocation operation: not visible yet\\n")
        raise SystemExit(254)
    invocation = {{
        "CommandId": value_after("--command-id"),
        "InstanceId": value_after("--instance-id"),
        "Status": {ssm_status!r},
        "ResponseCode": 0 if {ssm_status!r} == "Success" else 1,
        "StandardOutputContent": {ssm_stdout!r} + "stage=smoke status=success\\n",
        "StandardErrorContent": "stage=prepare status=success render_sha256=" + "b" * 64 + "\\n",
    }}
    invocation.update(json.loads({ssm_overrides_json!r}))
    for field in json.loads({ssm_remove_fields_json!r}):
        invocation.pop(field, None)
    if os.environ.get("FAKE_SSM_INVALID_RESPONSE") == "missing-identity":
        invocation.pop("CommandId")
    print(json.dumps(invocation), end="")
    raise SystemExit(0)
raise SystemExit(0)
"""
        (fake_bin / "aws").write_text(aws, encoding="utf-8")
        for executable in (fake_bin / "terraform", fake_bin / "aws"):
            executable.chmod(0o755)
        self._operator_run_id = "20260825T000000Z-4242"
        self._operator_target_version = target_version
        self._operator_capsule = root / "action-values.json"
        self._operator_receipt = root / "authorization.json"
        self._write_operator_receipt(target_version=target_version)
        return fake_bin, env_log

    def _write_operator_receipt(self, *, target_version: str = "1.35", backend_image: str | None = None, plan_sha: str = "c" * 64) -> None:
        backend_image = backend_image or (
            "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/backend@sha256:" + "c" * 64
        )
        capsule_payload = {
            "vpc_id": "vpc-0123456789abcdef0",
            "public_subnet_ids": ["subnet-a", "subnet-b"],
            "api_certificate_arn": "arn:aws:acm:ap-northeast-2:123456789012:certificate/a",
            "backend_image": backend_image,
            "backend_hostname": "api.example.com",
            "frontend_origin": "https://www.example.com",
        }
        self._operator_capsule.write_text(json.dumps(capsule_payload), encoding="utf-8")
        self._operator_capsule.chmod(0o600)
        values = subprocess.run(
            [
                "jq", "-n", "--arg", "vpc_id", capsule_payload["vpc_id"],
                "--argjson", "public_subnet_ids", json.dumps(capsule_payload["public_subnet_ids"]),
                "--arg", "api_certificate_arn", capsule_payload["api_certificate_arn"],
                "--arg", "backend_hostname", capsule_payload["backend_hostname"],
                "--arg", "backend_origin", "https://api.example.com",
                "--arg", "backend_image", backend_image,
                "--arg", "frontend_origin", capsule_payload["frontend_origin"],
                "{vpc_id:$vpc_id,public_subnet_ids:$public_subnet_ids,api_certificate_arn:$api_certificate_arn,backend_hostname:$backend_hostname,backend_origin:$backend_origin,backend_image:$backend_image,frontend_origin:$frontend_origin}",
            ],
            check=True, capture_output=True,
        ).stdout
        runtime_sha = hashlib.sha256(values).hexdigest()
        capsule_sha = hashlib.sha256(self._operator_capsule.read_bytes()).hexdigest()
        payload = {
            "schema_version": "dev-eks-create-authorization/v1",
            "handoff_schema_version": "plan-handoff/v1", "handoff_path": str(V9_HANDOFF), "handoff_sha256": V9_HANDOFF_SHA256,
            "manifest_schema_version": "plan-manifest/v3", "manifest_path": str(V9_MANIFEST),
            "plan_id": "dev-eks-deployment-automation", "plan_version": 9,
            "manifest_sha256": V9_MANIFEST_SHA256,
            "run_id": self._operator_run_id, "issued_at": "2026-08-25T00:00:00Z", "expires_at": "2030-01-01T00:00:00Z",
            "status": "active", "single_use": True, "expected_account_id": "123456789012", "expected_region": "ap-northeast-2",
            "terraform_backend_key": "dev-eks/terraform.tfstate", "terraform_backend_config_sha256": BACKEND_CONFIG_SHA256, "terraform_plan_sha256": plan_sha,
            "input_capsule_path": os.path.abspath(str(self._operator_capsule)), "input_capsule_sha256": capsule_sha,
            "kubernetes_version": target_version, "kubernetes_version_status": "STANDARD_SUPPORT",
            "backend_image": backend_image, "backend_hostname": "api.example.com", "frontend_origin": "https://www.example.com",
            "bundle_revision_sha256": "a" * 64, "runtime_values_sha256": runtime_sha, "render_sha256": "b" * 64,
            "protected_backends": ["dev/terraform.tfstate", "dev-runtime/terraform.tfstate", "dev-load-test/terraform.tfstate"],
            "protected_resources": ["persistent VPC and subnets", "ACM certificates", "ECR repositories and images", "profile image storage", "application Secrets Manager", "external DNS provider"],
            "permitted_actions": ["apply exact create/update-only dev-eks Terraform plan", "run exact staged Kubernetes deployment through tagged private Bastion", "run bounded ALB/HTTPS/observability smoke", "retain created dev-eks resources"],
            "forbidden_actions": ["terraform destroy", "Kubernetes delete", "replace or import", "Cloudflare mutation", "protected State mutation"],
            "paid_approval": {"status": "approved", "action": "APPLY DEV-EKS CREATE-AND-RETAIN " + plan_sha, "plan_sha256": plan_sha},
        }
        self._operator_receipt.write_text(json.dumps(payload), encoding="utf-8")
        self._operator_receipt.chmod(0o600)

    def _bind_operator_receipt_plan(self, plan_sha: str) -> None:
        payload = json.loads(self._operator_receipt.read_text(encoding="utf-8"))
        payload["terraform_plan_sha256"] = plan_sha
        payload["paid_approval"]["action"] = "APPLY DEV-EKS CREATE-AND-RETAIN " + plan_sha
        payload["paid_approval"]["plan_sha256"] = plan_sha
        self._operator_receipt.write_text(json.dumps(payload), encoding="utf-8")
        self._operator_receipt.chmod(0o600)

    def _operator_args(
        self,
        *,
        skip_apply: bool = True,
        backend_image: str | None = None,
        mode: str = "run",
        resume_from: str | None = None,
        resume_run_id: str | None = None,
    ) -> list[str]:
        backend_image = backend_image or (
            "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/backend@sha256:" + "c" * 64
        )
        if backend_image != json.loads(self._operator_capsule.read_text(encoding="utf-8"))["backend_image"]:
            self._write_operator_receipt(target_version=self._operator_target_version, backend_image=backend_image)
        args = [
            "bash",
            str(SCRIPT),
            "--mode",
            mode,
            "--non-interactive",
            "--offline-test",
            "--aws-profile",
            "offline",
            "--region",
            "ap-northeast-2",
            "--expected-account-id",
            "123456789012",
            "--kubernetes-render-sha256",
            "b" * 64,
            "--terraform-plan-sha256",
            "c" * 64,
            "--backend-image",
            backend_image,
            "--backend-hostname",
            "api.example.com",
            "--frontend-origin",
            "https://www.example.com",
            "--run-id",
            self._operator_run_id,
            "--action-values-capsule",
            str(self._operator_capsule),
            "--authorization-receipt",
            str(self._operator_receipt),
        ]
        if mode == "run" and skip_apply:
            args.insert(5, "--skip-terraform-apply")
        if mode == "resume":
            args.extend(["--resume-from", resume_from or "platform", "--resume-run-id", resume_run_id or "20260824T071537Z-123"])
        return args

    def test_ssm_parameters_are_lossless_json_and_decoded_command_is_shell_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin, _ = self._operator_fixture(root)
            argv_log = root / "aws-argv.jsonl"
            command_log = root / "ssm-commands.jsonl"
            result = subprocess.run(
                self._operator_args(mode="prepare"),
                cwd=ROOT,
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}:{os.environ['PATH']}",
                    "FAKE_AWS_ARGV_LOG": str(argv_log),
                    "FAKE_SSM_COMMAND_LOG": str(command_log),
                },
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            command_records = [json.loads(line) for line in command_log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(command_records), 1)
            parameters = command_records[0]["parameters"]
            self.assertEqual(set(parameters), {"commands"})
            self.assertEqual(len(parameters["commands"]), 1)
            command = parameters["commands"][0]
            self.assertIn("jq -e --arg expected", command)
            self.assertIn("awk '{print $1}'", command)
            self.assertNotIn("commands=", command)
            syntax = subprocess.run(["bash", "-n"], input=command, capture_output=True, text=True)
            self.assertEqual(syntax.returncode, 0, syntax.stderr)
            argv_records = [json.loads(line) for line in argv_log.read_text(encoding="utf-8").splitlines()]
            send_calls = [record for record in argv_records if "send-command" in record]
            self.assertEqual(len(send_calls), 1)
            parameter_index = send_calls[0].index("--parameters")
            self.assertEqual(json.loads(send_calls[0][parameter_index + 1]), parameters)

    def test_custom_capsule_is_rejected_without_explicit_offline_test_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._operator_fixture(Path(directory))
            args = self._operator_args()
            args.remove("--offline-test")
            result = subprocess.run(
                args, cwd=ROOT, env={**os.environ, "PATH": os.environ["PATH"]}, capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("production mutation requires the canonical action-values capsule path", result.stderr)

    def test_non_empty_dev_eks_state_blocks_create_mode_before_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin, _ = self._operator_fixture(root, state_output="")
            plan = ROOT / "infra" / "environments" / "dev-eks" / f".offline-state-{os.getpid()}-plan"
            plan.write_bytes(b"synthetic-create-plan\n")
            plan_sha = hashlib.sha256(plan.read_bytes()).hexdigest()
            self._bind_operator_receipt_plan(plan_sha)
            args = self._operator_args(skip_apply=False)
            args.extend(["--terraform-plan", str(plan), "--terraform-plan-sha256", plan_sha])
            tf_log = root / "terraform.log"
            result = subprocess.run(
                args,
                cwd=ROOT,
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}:{os.environ['PATH']}",
                    "FAKE_DEV_EKS_STATE": "aws_eks_cluster.this",
                    "FAKE_TF_CALL_LOG": str(tf_log),
                },
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("dev-eks State is not empty; create-only ownership precondition failed", result.stderr)
            self.assertNotIn(" apply ", tf_log.read_text(encoding="utf-8") if tf_log.exists() else "")
            plan.unlink(missing_ok=True)

    def test_mutation_failure_retains_failure_evidence_and_fail_closed_variants(self) -> None:
        cases = [
            ("normal", {}, True),
            ("aws-unavailable", {"FAKE_AWS_UNAVAILABLE_DURING_FAILURE": "true"}, True),
        ]
        for label, extra_env, expect_protected in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                fake_bin, _ = self._operator_fixture(root, ssm_status="Failed")
                self._operator_run_id = f"20260825T000000Z-{os.getpid()}{len(label)}"
                self._write_operator_receipt(target_version=self._operator_target_version)
                args = self._operator_args()
                result = subprocess.run(
                    args,
                    cwd=ROOT,
                    env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}", **extra_env},
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                report = ROOT / "evidence" / "eks-deploy" / self._operator_run_id
                retained = report / "retained-result.private.json"
                protected = report / "protected-states-after.private.json"
                self.assertTrue(retained.exists(), result.stderr)
                self.assertTrue(protected.exists(), result.stderr)
                self.assertEqual(json.loads(retained.read_text(encoding="utf-8"))["status"], "failed")
                if expect_protected and label == "aws-unavailable":
                    statuses = {entry["status"] for entry in json.loads(protected.read_text(encoding="utf-8"))["scopes"]}
                    self.assertIn("unavailable", statuses)

    def test_failure_evidence_chmod_error_changes_terminal_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin, _ = self._operator_fixture(root, ssm_status="Failed")
            real_chmod = shutil.which("chmod")
            assert real_chmod
            (fake_bin / "chmod").write_text(
                "#!/usr/bin/env bash\n"
                "for value in \"$@\"; do\n"
                "  case \"$value\" in *protected-states-after.private.json|*retained-result.private.json) exit 1 ;; esac\n"
                "done\n"
                f"exec {real_chmod} \"$@\"\n",
                encoding="utf-8",
            )
            (fake_bin / "chmod").chmod(0o755)
            self._operator_run_id = f"20260825T000000Z-{os.getpid()}77"
            self._write_operator_receipt(target_version=self._operator_target_version)
            result = subprocess.run(
                self._operator_args(),
                cwd=ROOT,
                env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("failure evidence could not be retained", result.stderr)

    def test_resume_prepare_failure_records_prepare_as_failed_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin, _ = self._operator_fixture(root, ssm_status="Failed")
            self._operator_run_id = f"20260825T000000Z-{os.getpid()}88"
            self._write_operator_receipt(target_version=self._operator_target_version)
            result = subprocess.run(
                self._operator_args(mode="resume", resume_from="prepare", resume_run_id="20260824T133440Z-15798"),
                cwd=ROOT,
                env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            report = ROOT / "evidence" / "eks-deploy" / self._operator_run_id
            retained = report / "retained-result.private.json"
            self.assertTrue(retained.exists(), result.stderr)
            self.assertEqual(json.loads(retained.read_text(encoding="utf-8"))["failed_stage"], "prepare")

    def test_ssm_invocation_visibility_lag_retries_without_duplicate_send(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin, _ = self._operator_fixture(root, ssm_transient_count=1)
            (fake_bin / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            (fake_bin / "sleep").chmod(0o755)
            command_log = root / "ssm-commands.jsonl"
            argv_log = root / "aws-argv.jsonl"
            result = subprocess.run(
                self._operator_args(mode="prepare"),
                cwd=ROOT,
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}:{os.environ['PATH']}",
                    "FAKE_SSM_STATE": str(root / "ssm-state"),
                    "FAKE_SSM_COMMAND_LOG": str(command_log),
                    "FAKE_AWS_ARGV_LOG": str(argv_log),
                },
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(len(command_log.read_text(encoding="utf-8").splitlines()), 1)
            get_calls = [json.loads(line) for line in argv_log.read_text(encoding="utf-8").splitlines() if "get-command-invocation" in line]
            self.assertEqual(len(get_calls), 2)

    def test_ssm_invocation_schema_failure_is_sanitized_and_stops_before_next_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin, _ = self._operator_fixture(root)
            result = subprocess.run(
                self._operator_args(mode="prepare"),
                cwd=ROOT,
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}:{os.environ['PATH']}",
                    "FAKE_SSM_INVALID_RESPONSE": "missing-identity",
                    "FAKE_AWS_LOG": str(root / "aws.log"),
                },
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("SSM invocation response schema is invalid", result.stderr)
            self.assertNotIn("CommandId", result.stderr)
            trace = (root / "aws.log").read_text(encoding="utf-8")
            self.assertNotIn("namespace-secret", trace)

    def test_ssm_polling_failure_and_status_matrix_fails_closed(self) -> None:
        cases = [
            (
                "access denied lookup",
                {"ssm_lookup_error": "An error occurred (AccessDeniedException): raw-access-denied-marker\\n"},
                {},
                "SSM invocation lookup was denied by IAM",
                "raw-access-denied-marker",
            ),
            (
                "invalid lookup",
                {"ssm_lookup_error": "An error occurred (InvalidDocument): raw-invalid-document-marker\\n"},
                {},
                "SSM invocation lookup failed",
                "raw-invalid-document-marker",
            ),
            (
                "unknown lookup",
                {"ssm_lookup_error": "An error occurred (UnknownLookupError): raw-unknown-lookup-marker\\n"},
                {},
                "SSM invocation lookup failed",
                "raw-unknown-lookup-marker",
            ),
            ("malformed json", {"ssm_raw_invocation": "not-json"}, {}, "SSM invocation response schema is invalid", None),
            ("non-object array", {"ssm_raw_invocation": "[]"}, {}, "SSM invocation response schema is invalid", None),
            ("null root", {"ssm_raw_invocation": "null"}, {}, "SSM invocation response schema is invalid", None),
            ("empty response", {"ssm_raw_invocation": ""}, {}, "SSM invocation response schema is invalid", None),
            (
                "mismatched command",
                {"ssm_invocation_overrides": {"CommandId": "11111111-1111-4111-8111-111111111111"}},
                {},
                "SSM invocation response schema is invalid",
                None,
            ),
            (
                "mismatched instance",
                {"ssm_invocation_overrides": {"InstanceId": "i-fffffffffffffffff"}},
                {},
                "SSM invocation response schema is invalid",
                None,
            ),
            (
                "missing status",
                {"ssm_remove_fields": ("Status",)},
                {},
                "SSM invocation response schema is invalid",
                None,
            ),
            (
                "numeric status",
                {"ssm_invocation_overrides": {"Status": 1}},
                {},
                "SSM invocation response schema is invalid",
                None,
            ),
            (
                "unknown status",
                {"ssm_invocation_overrides": {"Status": "Queued"}},
                {},
                "SSM invocation status is unknown",
                None,
            ),
            (
                "pending bounded timeout",
                {"ssm_status": "Pending"},
                {"DEV_EKS_SSM_TIMEOUT_SECONDS": "1"},
                "SSM polling timeout",
                None,
            ),
            (
                "delayed bounded timeout",
                {"ssm_status": "Delayed"},
                {"DEV_EKS_SSM_TIMEOUT_SECONDS": "1"},
                "SSM polling timeout",
                None,
            ),
            (
                "numeric stdout",
                {"ssm_invocation_overrides": {"StandardOutputContent": 42}},
                {},
                "SSM invocation response schema is invalid",
                None,
            ),
            (
                "numeric stderr",
                {"ssm_invocation_overrides": {"StandardErrorContent": 42}},
                {},
                "SSM invocation response schema is invalid",
                None,
            ),
            (
                "missing response code",
                {"ssm_remove_fields": ("ResponseCode",)},
                {},
                "SSM invocation success response is invalid",
                None,
            ),
            (
                "string response code",
                {"ssm_invocation_overrides": {"ResponseCode": "0"}},
                {},
                "SSM invocation success response is invalid",
                None,
            ),
            (
                "fractional response code",
                {"ssm_invocation_overrides": {"ResponseCode": 0.5}},
                {},
                "SSM invocation success response is invalid",
                None,
            ),
            (
                "nonzero response code",
                {"ssm_invocation_overrides": {"ResponseCode": 1}},
                {},
                "SSM invocation success response is invalid",
                None,
            ),
            (
                "null response code",
                {"ssm_invocation_overrides": {"ResponseCode": None}},
                {},
                "SSM invocation success response is invalid",
                None,
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, (label, fixture_kwargs, env_overrides, expected, private_marker) in enumerate(cases):
                case_root = root / f"matrix-{index}"
                fake_bin, _ = self._operator_fixture(case_root, **fixture_kwargs)
                (fake_bin / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
                (fake_bin / "sleep").chmod(0o755)
                result = subprocess.run(
                    self._operator_args(mode="prepare"),
                    cwd=ROOT,
                    env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}", **env_overrides},
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0, label)
                self.assertIn(expected, result.stderr, label)
                if private_marker:
                    self.assertNotIn(private_marker, result.stderr + result.stdout, label)

    def test_ssm_malformed_command_id_stops_before_polling(self) -> None:
        for index, command_id in enumerate(("", "not-a-command-id", "!" * 36)):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                fake_bin, _ = self._operator_fixture(root)
                argv_log = root / "aws-argv.jsonl"
                result = subprocess.run(
                    self._operator_args(mode="prepare"),
                    cwd=ROOT,
                    env={
                        **os.environ,
                        "PATH": f"{fake_bin}:{os.environ['PATH']}",
                        "FAKE_SSM_COMMAND_ID": command_id,
                        "FAKE_AWS_ARGV_LOG": str(argv_log),
                    },
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0, index)
                self.assertIn("SSM command submission returned invalid command id", result.stderr, index)
                records = [json.loads(line) for line in argv_log.read_text(encoding="utf-8").splitlines()]
                self.assertFalse(any("get-command-invocation" in record for record in records), index)

    def test_ssm_submission_failure_does_not_leak_raw_aws_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin, _ = self._operator_fixture(root)
            marker = "raw-sensitive-ssm-command-marker"
            result = subprocess.run(
                self._operator_args(mode="prepare"),
                cwd=ROOT,
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}:{os.environ['PATH']}",
                    "FAKE_SSM_SEND_STDERR": marker,
                    "FAKE_SSM_SEND_EXIT": "1",
                },
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("SSM command submission failed", result.stderr)
            self.assertNotIn(marker, result.stderr + result.stdout)

    def test_resume_summary_distinguishes_local_and_remote_run_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin, _ = self._operator_fixture(root)
            # The operator now honors --run-id for its local evidence directory.
            # Use an instance-unique id so duplicate discovery of this imported
            # contract class cannot reuse a prior summary from another test.
            self._operator_run_id = f"20260825T000000Z-{os.getpid()}{time.time_ns()}"
            self._write_operator_receipt(target_version=self._operator_target_version)
            before = set((ROOT / "evidence" / "eks-deploy").glob("*/deployment-summary.json"))
            result = subprocess.run(
                self._operator_args(mode="resume", resume_from="platform", resume_run_id="20260824T133440Z-15798"),
                cwd=ROOT,
                env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            created = set((ROOT / "evidence" / "eks-deploy").glob("*/deployment-summary.json")) - before
            self.assertEqual(len(created), 1)
            summary = json.loads(next(iter(created)).read_text(encoding="utf-8"))
            self.assertEqual(summary["remote_run_id"], "20260824T133440Z-15798")
            self.assertEqual(summary["local_run_id"], summary["run_id"])
            self.assertEqual(summary["resume_from"], "platform")

    def test_target_version_comes_from_plan_or_state_and_request_has_no_ambiguous_selector(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, (mode, resume_from) in enumerate(
                (("run", None), ("prepare", None), ("resume", "platform"))
            ):
                case_root = root / f"state-{index}"
                fake_bin, _ = self._operator_fixture(
                    case_root,
                    target_version="1.32",
                    state_cluster_version="1.32",
                    eks_response={
                        "clusterVersions": [
                            {
                                "clusterVersion": "1.32",
                                "clusterType": "eks",
                                "versionStatus": "STANDARD_SUPPORT",
                                "futureField": "ignored",
                            }
                        ]
                    },
                )
                aws_log = case_root / "aws.log"
                result = subprocess.run(
                    self._operator_args(mode=mode, resume_from=resume_from),
                    cwd=ROOT,
                    env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}", "FAKE_AWS_LOG": str(aws_log)},
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, f"{mode}: {result.stderr}{result.stdout}")
                eks_lines = [line for line in aws_log.read_text(encoding="utf-8").splitlines() if "eks describe-cluster-versions" in line]
                self.assertEqual(len(eks_lines), 1)
                self.assertIn("--cluster-type eks", eks_lines[0])
                self.assertIn("--cluster-versions 1.32", eks_lines[0])
                self.assertIn("--no-paginate", eks_lines[0])
                self.assertIn("--output json", eks_lines[0])
                for forbidden in ("--query", "--include-all", "--default-only", "--status", "--version-status"):
                    self.assertNotIn(forbidden, eks_lines[0])

            plan_root = root / "plan"
            fake_bin, _ = self._operator_fixture(
                plan_root,
                target_version="1.34",
                state_cluster_version="1.35",
                eks_response={
                    "clusterVersions": [
                        {"clusterVersion": "1.34", "clusterType": "eks", "versionStatus": "STANDARD_SUPPORT"}
                    ]
                },
            )
            plan = ROOT / "infra" / "environments" / "dev-eks" / ".offline-version-source-plan"
            plan.write_bytes(b"synthetic-plan\n")
            aws_log = plan_root / "aws.log"
            tf_log = plan_root / "terraform.log"
            try:
                args = self._operator_args(skip_apply=False)
                plan_sha = hashlib.sha256(plan.read_bytes()).hexdigest()
                self._bind_operator_receipt_plan(plan_sha)
                args.extend(["--terraform-plan", str(plan.relative_to(ROOT)), "--terraform-plan-sha256", plan_sha])
                result = subprocess.run(
                    args,
                    cwd=ROOT,
                    env={
                        **os.environ,
                        "PATH": f"{fake_bin}:{os.environ['PATH']}",
                        "FAKE_AWS_LOG": str(aws_log),
                        "FAKE_TF_CALL_LOG": str(tf_log),
                    },
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                eks_lines = [line for line in aws_log.read_text(encoding="utf-8").splitlines() if "eks describe-cluster-versions" in line]
                self.assertEqual(len(eks_lines), 1)
                self.assertIn("--cluster-versions 1.34", eks_lines[0])
                self.assertIn(" apply ", tf_log.read_text(encoding="utf-8"))
            finally:
                plan.unlink(missing_ok=True)

    def test_plan_version_cross_check_fails_before_any_aws_or_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin, _ = self._operator_fixture(
                root,
                plan_json={
                    "variables": {"kubernetes_version": {"value": "1.34"}},
                    "planned_values": {
                        "root_module": {
                            "resources": [
                                {
                                    "address": "aws_eks_cluster.this",
                                    "mode": "managed",
                                    "type": "aws_eks_cluster",
                                    "name": "this",
                                    "values": {"version": "1.35"},
                                }
                            ]
                        }
                    },
                    "resource_changes": [],
                },
            )
            plan = ROOT / "infra" / "environments" / "dev-eks" / ".offline-version-mismatch-plan"
            plan.write_bytes(b"synthetic-plan\n")
            aws_log = root / "aws.log"
            try:
                args = self._operator_args(skip_apply=False)
                plan_sha = hashlib.sha256(plan.read_bytes()).hexdigest()
                self._bind_operator_receipt_plan(plan_sha)
                args.extend(["--terraform-plan", str(plan.relative_to(ROOT)), "--terraform-plan-sha256", plan_sha])
                result = subprocess.run(
                    args,
                    cwd=ROOT,
                    env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}", "FAKE_AWS_LOG": str(aws_log)},
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("does not match planned EKS cluster version", result.stderr)
                self.assertFalse(aws_log.exists())
            finally:
                plan.unlink(missing_ok=True)

    def test_plan_state_and_dry_run_source_negative_matrix(self) -> None:
        cluster = {
            "address": "aws_eks_cluster.this",
            "mode": "managed",
            "type": "aws_eks_cluster",
            "name": "this",
            "values": {"version": "1.35"},
        }
        valid_variable = {"kubernetes_version": {"value": "1.35"}}
        cases = [
            ("missing variable", {"planned_values": {"root_module": {"resources": [cluster]}}, "resource_changes": []}, "variable is missing or malformed"),
            ("numeric variable", {"variables": {"kubernetes_version": {"value": 1.35}}, "planned_values": {"root_module": {"resources": [cluster]}}, "resource_changes": []}, "variable is missing or malformed"),
            ("zero clusters", {"variables": valid_variable, "planned_values": {"root_module": {"resources": []}}, "resource_changes": []}, "exactly one managed aws_eks_cluster"),
            ("multiple clusters", {"variables": valid_variable, "planned_values": {"root_module": {"resources": [cluster, {**cluster, "address": "aws_eks_cluster.other"}]}}, "resource_changes": []}, "exactly one managed aws_eks_cluster"),
            ("missing resource version", {"variables": valid_variable, "planned_values": {"root_module": {"resources": [{**cluster, "values": {}}]}}, "resource_changes": []}, "EKS cluster version is missing or malformed"),
            ("numeric resource version", {"variables": valid_variable, "planned_values": {"root_module": {"resources": [{**cluster, "values": {"version": 1.35}}]}}, "resource_changes": []}, "EKS cluster version is missing or malformed"),
            ("malformed resource version", {"variables": valid_variable, "planned_values": {"root_module": {"resources": [{**cluster, "values": {"version": "latest"}}]}}, "resource_changes": []}, "EKS cluster version is malformed"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, (label, plan_json, expected) in enumerate(cases):
                case_root = root / f"plan-negative-{index}"
                fake_bin, _ = self._operator_fixture(case_root, plan_json=plan_json)
                plan = ROOT / "infra" / "environments" / "dev-eks" / f".offline-{index}-plan-source"
                plan.write_bytes(b"synthetic-plan\n")
                aws_log = case_root / "aws.log"
                tf_log = case_root / "terraform.log"
                try:
                    args = self._operator_args(skip_apply=False)
                    plan_sha = hashlib.sha256(plan.read_bytes()).hexdigest()
                    self._bind_operator_receipt_plan(plan_sha)
                    args.extend(["--terraform-plan", str(plan.relative_to(ROOT)), "--terraform-plan-sha256", plan_sha])
                    result = subprocess.run(
                        args,
                        cwd=ROOT,
                        env={
                            **os.environ,
                            "PATH": f"{fake_bin}:{os.environ['PATH']}",
                            "FAKE_AWS_LOG": str(aws_log),
                            "FAKE_TF_CALL_LOG": str(tf_log),
                        },
                        capture_output=True,
                        text=True,
                    )
                    self.assertNotEqual(result.returncode, 0, label)
                    self.assertIn(expected, result.stderr, label)
                    self.assertFalse(aws_log.exists(), label)
                    self.assertNotIn(" apply ", tf_log.read_text(encoding="utf-8"))
                finally:
                    plan.unlink(missing_ok=True)

            dry_root = root / "dry-run-plan"
            fake_bin, _ = self._operator_fixture(dry_root, target_version="1.33")
            plan = ROOT / "infra" / "environments" / "dev-eks" / ".offline-dry-run-plan-source"
            plan.write_bytes(b"synthetic-plan\n")
            try:
                args = self._operator_args(mode="dry-run", skip_apply=False)
                args.extend(["--terraform-plan", str(plan.relative_to(ROOT)), "--terraform-plan-sha256", hashlib.sha256(plan.read_bytes()).hexdigest()])
                result = subprocess.run(
                    args,
                    cwd=ROOT,
                    env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("status=dry-run", result.stderr)
            finally:
                plan.unlink(missing_ok=True)

            for index, state_value in enumerate((None, "not-a-minor", ["1.35"])):
                case_root = root / f"state-negative-{index}"
                fake_bin, _ = self._operator_fixture(case_root, state_cluster_version=state_value)
                aws_log = case_root / "aws.log"
                result = subprocess.run(
                    self._operator_args(),
                    cwd=ROOT,
                    env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}", "FAKE_AWS_LOG": str(aws_log)},
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("cluster_version", result.stderr)
                trace = aws_log.read_text(encoding="utf-8") if aws_log.exists() else ""
                self.assertNotIn("eks describe-cluster-versions", trace)
                self.assertNotIn("ecr describe-images", trace)
                self.assertNotIn("ssm send-command", trace)

            omitted_root = root / "state-negative-omitted"
            fake_bin, _ = self._operator_fixture(omitted_root, include_cluster_version=False)
            aws_log = omitted_root / "aws.log"
            result = subprocess.run(
                self._operator_args(),
                cwd=ROOT,
                env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}", "FAKE_AWS_LOG": str(aws_log)},
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("cluster_version", result.stderr)
            trace = aws_log.read_text(encoding="utf-8") if aws_log.exists() else ""
            self.assertNotIn("eks describe-cluster-versions", trace)

    def test_eks_diagnostics_do_not_leak_aws_or_jq_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin, _ = self._operator_fixture(root, eks_exit_code=7)
            aws_log = root / "aws.log"
            result = subprocess.run(
                self._operator_args(),
                cwd=ROOT,
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}:{os.environ['PATH']}",
                    "FAKE_AWS_LOG": str(aws_log),
                    "FAKE_EKS_STDERR": "raw-sensitive-account-999999999999-provider-diagnostic",
                },
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("EKS support metadata lookup failed", result.stderr)
            self.assertNotIn("raw-sensitive-account-999999999999-provider-diagnostic", result.stderr)
            self.assertNotIn("SecretString", result.stderr + result.stdout)

    def test_eks_response_matrix_is_distinct_and_fails_before_ecr_or_mutation(self) -> None:
        item = {"clusterVersion": "1.35", "clusterType": "eks", "versionStatus": "STANDARD_SUPPORT"}
        cases = [
            ("aws failure", item, None, 7, "EKS support metadata lookup failed"),
            ("malformed json", None, "not-json", 0, "response schema is invalid"),
            ("empty stdout", None, "", 0, "response schema is invalid"),
            ("scalar root", None, "42", 0, "response schema is invalid"),
            ("null root", None, "null", 0, "response schema is invalid"),
            ("root array", [item], None, 0, "response schema is invalid"),
            ("missing array", {}, None, 0, "response schema is invalid"),
            ("scalar array", {"clusterVersions": "not-array"}, None, 0, "response schema is invalid"),
            ("null array", {"clusterVersions": None}, None, 0, "response schema is invalid"),
            ("empty", {"clusterVersions": []}, None, 0, "result cardinality is invalid"),
            ("duplicate", {"clusterVersions": [item, item]}, None, 0, "result cardinality is invalid"),
            ("null item", {"clusterVersions": [None]}, None, 0, "item schema is invalid"),
            ("scalar item", {"clusterVersions": [42]}, None, 0, "item schema is invalid"),
            ("wrong version", {"clusterVersions": [{**item, "clusterVersion": "1.34"}]}, None, 0, "version does not match target"),
            ("numeric version", {"clusterVersions": [{**item, "clusterVersion": 1.35}]}, None, 0, "clusterVersion is missing or malformed"),
            ("wrong type", {"clusterVersions": [{**item, "clusterType": "STANDARD"}]}, None, 0, "clusterType is not eks"),
            ("numeric type", {"clusterVersions": [{**item, "clusterType": 1}]}, None, 0, "clusterType is missing or malformed"),
            ("null type", {"clusterVersions": [{**item, "clusterType": None}]}, None, 0, "clusterType is missing or malformed"),
            ("missing type", {"clusterVersions": [{k: v for k, v in item.items() if k != "clusterType"}]}, None, 0, "clusterType is missing or malformed"),
            ("missing status", {"clusterVersions": [{k: v for k, v in item.items() if k != "versionStatus"}]}, None, 0, "versionStatus is missing or malformed"),
            ("deprecated status only", {"clusterVersions": [{"clusterVersion": "1.35", "clusterType": "eks", "status": "STANDARD_SUPPORT"}]}, None, 0, "versionStatus is missing or malformed"),
            ("unknown status", {"clusterVersions": [{**item, "versionStatus": "FUTURE_SUPPORT"}]}, None, 0, "versionStatus is unknown"),
            ("numeric status", {"clusterVersions": [{**item, "versionStatus": 1}]}, None, 0, "versionStatus is missing or malformed"),
            ("null status", {"clusterVersions": [{**item, "versionStatus": None}]}, None, 0, "versionStatus is missing or malformed"),
            ("extended", {"clusterVersions": [{**item, "versionStatus": "EXTENDED_SUPPORT"}]}, None, 0, "EXTENDED_SUPPORT"),
            ("unsupported", {"clusterVersions": [{**item, "versionStatus": "UNSUPPORTED"}]}, None, 0, "UNSUPPORTED"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, (label, response, raw, exit_code, expected) in enumerate(cases):
                case_root = root / f"matrix-{index}"
                fake_bin, _ = self._operator_fixture(case_root, eks_response=response, eks_raw=raw, eks_exit_code=exit_code)
                aws_log = case_root / "aws.log"
                tf_log = case_root / "terraform.log"
                result = subprocess.run(
                    self._operator_args(),
                    cwd=ROOT,
                    env={
                        **os.environ,
                        "PATH": f"{fake_bin}:{os.environ['PATH']}",
                        "FAKE_AWS_LOG": str(aws_log),
                        "FAKE_TF_CALL_LOG": str(tf_log),
                    },
                    capture_output=True,
                    text=True,
                )
                if label == "extended":
                    self.assertEqual(result.returncode, 0, label)
                    self.assertIn("CLOUDFLARE_CNAME_TARGET=", result.stdout, label)
                else:
                    self.assertNotEqual(result.returncode, 0, label)
                    self.assertIn(expected, result.stderr, label)
                trace = aws_log.read_text(encoding="utf-8") if aws_log.exists() else ""
                if label != "extended":
                    self.assertNotIn("ecr describe-images", trace, label)
                    self.assertNotIn("s3 cp", trace, label)
                    self.assertNotIn("ssm send-command", trace, label)
                    tf_trace = tf_log.read_text(encoding="utf-8") if tf_log.exists() else ""
                    self.assertNotIn(" apply ", tf_trace, label)
                self.assertNotIn("SecretString", result.stderr + result.stdout)

    def test_fake_ssm_stage_trace_matches_every_mode_and_resume_suffix(self) -> None:
        expected = {
            ("run", None): ["prepare", "namespace-secret", "platform", "workload", "ingress-wait", "smoke"],
            ("prepare", None): ["prepare"],
            ("resume", "prepare"): ["prepare", "namespace-secret", "platform", "workload", "ingress-wait"],
            ("resume", "namespace-secret"): ["namespace-secret", "platform", "workload", "ingress-wait"],
            ("resume", "platform"): ["platform", "workload", "ingress-wait"],
            ("resume", "workload"): ["workload", "ingress-wait"],
            ("resume", "ingress-wait"): ["ingress-wait"],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, ((mode, resume_from), stages) in enumerate(expected.items()):
                case_root = root / f"trace-{index}"
                fake_bin, _ = self._operator_fixture(case_root)
                aws_log = case_root / "aws.log"
                result = subprocess.run(
                    self._operator_args(mode=mode, resume_from=resume_from),
                    cwd=ROOT,
                    env={
                        **os.environ,
                        "PATH": f"{fake_bin}:{os.environ['PATH']}",
                        "FAKE_AWS_LOG": str(aws_log),
                    },
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, f"{mode}/{resume_from}: {result.stderr}{result.stdout}")
                trace = aws_log.read_text(encoding="utf-8")
                observed = [
                    match.group(1)
                    for line in trace.splitlines()
                    for match in [re.search(r"--comment dev-eks-[^ ]+-(prepare|namespace-secret|platform|workload|ingress-wait|smoke)", line)]
                    if match
                ]
                self.assertEqual(observed, stages, f"{mode}/{resume_from}: {trace}")
                for line in trace.splitlines():
                    if "ssm send-command" in line:
                        self.assertIn("AWS_DEFAULT_REGION", line)

    def test_fake_boundaries_cover_stale_plan_state_account_ssm_and_cname_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tmp").mkdir()
            fake_bin, _ = self._operator_fixture(root)
            base_env = {**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"}

            wrong_account = self._operator_fixture(root / "wrong-account", account="000000000000")[0]
            result = subprocess.run(self._operator_args(), cwd=ROOT, env={**base_env, "PATH": f"{wrong_account}:{os.environ['PATH']}"}, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("AWS account does not match expected account", result.stderr)

            non_empty_state = self._operator_fixture(root / "non-empty-state", state_output="stale-resource\n")[0]
            result = subprocess.run(self._operator_args(), cwd=ROOT, env={**base_env, "PATH": f"{non_empty_state}:{os.environ['PATH']}"}, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("State is not empty", result.stderr)

            for status in ("Failed", "Cancelled", "TimedOut"):
                status_bin = self._operator_fixture(root / f"ssm-{status.lower()}", ssm_status=status)[0]
                result = subprocess.run(self._operator_args(), cwd=ROOT, env={**base_env, "PATH": f"{status_bin}:{os.environ['PATH']}"}, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"SSM stage failed with status {status}", result.stderr)

            timeout_bin = self._operator_fixture(root / "ssm-timeout", ssm_status="InProgress")[0]
            result = subprocess.run(
                self._operator_args(),
                cwd=ROOT,
                env={**base_env, "PATH": f"{timeout_bin}:{os.environ['PATH']}", "DEV_EKS_SSM_TIMEOUT_SECONDS": "0"},
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("SSM polling timeout", result.stderr)

            ambiguous_bin = self._operator_fixture(
                root / "ambiguous-cname",
                ssm_stdout="CLOUDFLARE_CNAME_TARGET=one.elb.amazonaws.com\nCLOUDFLARE_CNAME_TARGET=two.elb.amazonaws.com\n",
            )[0]
            result = subprocess.run(self._operator_args(), cwd=ROOT, env={**base_env, "PATH": f"{ambiguous_bin}:{os.environ['PATH']}"}, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exactly one validated CNAME target", result.stderr)

            plan = ROOT / "infra" / "environments" / "dev-eks" / ".offline-stale-plan"
            plan.write_text("stale-plan\n", encoding="utf-8")
            try:
                stale_args = self._operator_args(skip_apply=False)
                self._bind_operator_receipt_plan("0" * 64)
                stale_args.extend(["--terraform-plan", str(plan), "--terraform-plan-sha256", "0" * 64])
                result = subprocess.run(stale_args, cwd=ROOT, env=base_env, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(
                    "terraform plan sha256 does not match" in result.stderr
                    or "v9 authorization receipt binding or approval is invalid" in result.stderr
                )
            finally:
                plan.unlink(missing_ok=True)

    def test_backend_image_provenance_rejections_precede_fake_mutations(self) -> None:
        trusted = "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/backend"
        rejected = (
            "docker.io/travel-planner/backend@sha256:" + "c" * 64,
            "000000000000.dkr.ecr.ap-northeast-2.amazonaws.com/backend@sha256:" + "c" * 64,
            "123456789012.dkr.ecr.us-east-1.amazonaws.com/backend@sha256:" + "c" * 64,
            "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/other@sha256:" + "c" * 64,
            trusted + ":latest",
            trusted + "@sha256:" + "C" * 64,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, image in enumerate(rejected):
                case_root = root / f"rejected-{index}"
                fake_bin, _ = self._operator_fixture(case_root)
                aws_log = case_root / "aws.log"
                result = subprocess.run(
                    self._operator_args(backend_image=image),
                    cwd=ROOT,
                    env={
                        **os.environ,
                        "PATH": f"{fake_bin}:{os.environ['PATH']}",
                        "FAKE_AWS_LOG": str(aws_log),
                    },
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0, image)
                trace = aws_log.read_text(encoding="utf-8") if aws_log.exists() else ""
                self.assertNotIn("s3 cp", trace, image)
                self.assertNotIn("ssm send-command", trace, image)

            missing_root = root / "missing-digest"
            fake_bin, _ = self._operator_fixture(missing_root, ecr_digest="e" * 64)
            aws_log = missing_root / "aws.log"
            result = subprocess.run(
                self._operator_args(),
                cwd=ROOT,
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}:{os.environ['PATH']}",
                    "FAKE_AWS_LOG": str(aws_log),
                },
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not present in the trusted ECR repository", result.stderr)
            trace = aws_log.read_text(encoding="utf-8")
            self.assertIn("ecr describe-images", trace)
            self.assertNotIn("s3 cp", trace)
            self.assertNotIn("ssm send-command", trace)

    def test_saved_plan_rejects_public_endpoint_and_terraform_profile_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = ROOT / "infra" / "environments" / "dev-eks" / ".offline-public-endpoint-plan"
            plan.write_text("public-endpoint-plan\n", encoding="utf-8")
            try:
                fake_bin, env_log = self._operator_fixture(
                    root,
                    plan_json={"resource_changes": [], "planned_values": {"root_module": {"resources": [{"values": {"endpoint_public_access": True}}]}}},
                )
                args = self._operator_args(skip_apply=False)
                plan_sha = hashlib.sha256(plan.read_bytes()).hexdigest()
                self._bind_operator_receipt_plan(plan_sha)
                args.extend(["--terraform-plan", str(plan.relative_to(ROOT)), "--terraform-plan-sha256", plan_sha])
                result = subprocess.run(args, cwd=ROOT, env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}", "FAKE_TF_ENV_LOG": str(env_log)}, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("saved plan enables public EKS endpoint access", result.stderr)
                if env_log.exists():
                    self.assertTrue(all(line == "offline" for line in env_log.read_text(encoding="utf-8").splitlines()))
            finally:
                plan.unlink(missing_ok=True)

    def test_private_snapshot_is_applied_when_original_path_changes_after_inspection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tmp").mkdir()
            fake_bin, _ = self._operator_fixture(root)
            plan = ROOT / "infra" / "environments" / "dev-eks" / ".offline-snapshot-plan"
            capture = root / "applied-plan.bin"
            plan_bytes = b"approved-plan-bytes\\x00\\xff\\n"
            plan.write_bytes(plan_bytes)
            try:
                digest = hashlib.sha256(plan_bytes).hexdigest()
                args = self._operator_args(skip_apply=False)
                self._bind_operator_receipt_plan(digest)
                args.extend(["--terraform-plan", str(plan.relative_to(ROOT)), "--terraform-plan-sha256", digest])
                result = subprocess.run(
                    args,
                    cwd=ROOT,
                    env={
                        **os.environ,
                        "PATH": f"{fake_bin}:{os.environ['PATH']}",
                        "FAKE_PLAN_SOURCE": str(plan),
                        "FAKE_APPLY_CAPTURE": str(capture),
                        "TMPDIR": str(root / "tmp"),
                    },
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertEqual(capture.read_bytes(), plan_bytes)
                self.assertEqual(plan.read_bytes(), b"replaced-source-plan")
                self.assertEqual(list((root / "tmp").glob("dev-eks-plan.*")), [])
            finally:
                plan.unlink(missing_ok=True)

    def test_private_snapshot_tamper_is_rejected_before_apply_and_cleaned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tmp").mkdir()
            fake_bin, _ = self._operator_fixture(root)
            plan = ROOT / "infra" / "environments" / "dev-eks" / ".offline-snapshot-tamper-plan"
            plan_bytes = b"approved-plan-bytes\\n"
            plan.write_bytes(plan_bytes)
            capture = root / "applied-plan.bin"
            try:
                args = self._operator_args(skip_apply=False)
                plan_sha = hashlib.sha256(plan_bytes).hexdigest()
                self._bind_operator_receipt_plan(plan_sha)
                args.extend(["--terraform-plan", str(plan.relative_to(ROOT)), "--terraform-plan-sha256", plan_sha])
                result = subprocess.run(
                    args,
                    cwd=ROOT,
                    env={
                        **os.environ,
                        "PATH": f"{fake_bin}:{os.environ['PATH']}",
                        "FAKE_TAMPER_PLAN": "true",
                        "FAKE_APPLY_CAPTURE": str(capture),
                        "TMPDIR": str(root / "tmp"),
                    },
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("snapshot changed after inspection", result.stderr)
                self.assertFalse(capture.exists())
                self.assertEqual(list((root / "tmp").glob("dev-eks-plan.*")), [])
            finally:
                plan.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
