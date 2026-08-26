"""Offline contract tests for the disposable dev-eks lifecycle."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
LIFECYCLE = ROOT / "scripts/eks/run-dev-eks-ephemeral-lifecycle.sh"
REMOTE = ROOT / "scripts/eks/run-dev-eks-lifecycle-remote.sh"
VERIFIER = ROOT / "scripts/eks/verify-dev-eks-destroyed.py"


class EphemeralLifecycleContractTest(unittest.TestCase):
    def test_scripts_have_bounded_cleanup_and_no_direct_destroy_shortcut(self) -> None:
        lifecycle = LIFECYCLE.read_text(encoding="utf-8")
        remote = REMOTE.read_text(encoding="utf-8")
        self.assertIn("AUTHORIZE DEV-EKS CLEANUP", lifecycle)
        self.assertIn("APPLY KUBERNETES", ROOT.joinpath("scripts/eks/deploy-dev-eks.sh").read_text(encoding="utf-8"))
        self.assertIn("cleanup-ingress", lifecycle)
        self.assertIn("cleanup-workload", lifecycle)
        self.assertIn("cleanup-platform", lifecycle)
        self.assertIn("plan -destroy", lifecycle)
        self.assertIn("Ingress", remote)
        self.assertIn("describe-tags", lifecycle)
        self.assertIn("finalizers", remote)
        self.assertNotIn("terraform destroy -auto-approve", lifecycle)
        self.assertNotIn("curl https://api.cloudflare", lifecycle)

    def test_cleanup_retry_is_single_scope_reinventory(self) -> None:
        lifecycle = LIFECYCLE.read_text(encoding="utf-8")
        self.assertIn("destroy_retry", lifecycle)
        self.assertIn("same_scope_reinventory", lifecycle)
        self.assertIn("blocked_scope_changed", lifecycle)
        self.assertIn("!/^data\\./ && !/\\.data\\./", lifecycle)
        self.assertEqual(lifecycle.count("apply_destroy_plan"), 3)

    def test_signal_and_result_state_machine_is_explicit(self) -> None:
        lifecycle = LIFECYCLE.read_text(encoding="utf-8")
        for signal in ("INT", "TERM", "HUP"):
            self.assertIn(f"trap 'exit", lifecycle)
            self.assertIn(signal, lifecycle)
        self.assertIn("trap 'finalize \"$?\"' EXIT", lifecycle)
        self.assertIn("LEASE_ACCEPTED", lifecycle)
        self.assertIn("run_cleanup_and_destroy", lifecycle)
        self.assertIn("verification_failed_cleanup_succeeded", lifecycle)
        self.assertIn("blocked_before_lease_current_environment_still_active", lifecycle)

    def test_remote_cleanup_order_and_alb_ownership_are_fail_closed(self) -> None:
        lifecycle = LIFECYCLE.read_text(encoding="utf-8")
        remote = REMOTE.read_text(encoding="utf-8")
        stage_order = [lifecycle.index(f"send_remote_helper_stage {stage}") for stage in ("cleanup-ingress", "cleanup-workload", "cleanup-platform")]
        self.assertEqual(stage_order, sorted(stage_order))
        self.assertLess(remote.index("cleanup_ingress()"), remote.index("cleanup_workload()"))
        self.assertLess(remote.index("cleanup_workload()"), remote.index("cleanup_platform()"))
        self.assertIn("describe-target-health", lifecycle)
        self.assertIn("cleanup_operator_owned_albs", lifecycle)
        self.assertIn("operator_native_smoke", lifecycle)
        self.assertIn("owned_alb_cleanup_deferred", remote)
        self.assertIn("finalizers", remote)
        self.assertIn("--timeout=\"${TIMEOUT_SECONDS}s\"", remote)
        self.assertIn("--request-timeout=30s", remote)
        self.assertNotIn("eval ", remote)

    def test_remote_helper_uses_one_explicit_private_kubeconfig_for_all_stages(self) -> None:
        remote = REMOTE.read_text(encoding="utf-8")
        self.assertIn('KUBECONFIG_PATH="$WORK_DIR/kubeconfig"', remote)
        self.assertIn('export KUBECONFIG="$KUBECONFIG_PATH"', remote)
        self.assertIn('aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$REGION" --kubeconfig "$KUBECONFIG_PATH"', remote)
        self.assertIn('kubectl --kubeconfig "$KUBECONFIG_PATH" get --request-timeout=30s --raw=/version', remote)
        self.assertIn('rm -f -- "$KUBECONFIG_PATH"', remote)
        self.assertIn('chmod 0600 "$LOG_FILE"', remote)
        self.assertIn('if [[ "$exit_status" -eq 0 ]]', remote)

    def test_smoke_keeps_raw_material_private_and_reports_redacted_summary(self) -> None:
        remote = REMOTE.read_text(encoding="utf-8")
        self.assertIn("--connect-to", remote)
        self.assertIn("smoke-report.json", remote)
        self.assertIn("redacted-at-boundary", remote)
        self.assertIn("rm -f --", remote)
        self.assertIn("secret_key_count:9", remote)
        self.assertIn(".data | keys | sort", remote)

    def test_smoke_evidence_comes_from_fresh_runtime_probes(self) -> None:
        remote = REMOTE.read_text(encoding="utf-8")
        for probe in (
            "kubectl logs --request-timeout=30s deployment/backend",
            "getent hosts",
            "Backend overall health",
            "RedisReactiveHealthIndicator",
            "operator-data-evidence",
            "operator cloud smoke evidence checksum",
            'SMOKE_RAW_FILES=("$ingress_json")',
            "SMOKE_RAW_FILES",
            "cleanup_remote",
        ):
            self.assertIn(probe, remote)
        for operator_supplied_flag in ("--rds-available", "--redis-available", "--profile-image-identity"):
            self.assertNotIn(operator_supplied_flag, remote)
        self.assertNotIn("secretsmanager get-secret-value", remote)
        self.assertNotIn("AUTH/PING", remote)
        for forbidden_cloud_probe in ("rds describe-db-instances", "elasticache describe-replication-groups", "s3api head-bucket", "elbv2 describe-"):
            self.assertNotIn(forbidden_cloud_probe, remote)

    def test_failed_ssm_stage_keeps_only_sanitized_reason_evidence(self) -> None:
        lifecycle = LIFECYCLE.read_text(encoding="utf-8")
        self.assertIn("dev-eks-ssm-failure/v1", lifecycle)
        self.assertIn("StandardErrorContent", lifecycle)
        self.assertIn("stage=[A-Za-z0-9-]+ status=failed reason=", lifecycle)
        self.assertIn("failure.private.json", lifecycle)
        self.assertIn("chmod 0600", lifecycle)

    def test_protected_scope_and_cloudflare_are_explicitly_excluded(self) -> None:
        lifecycle = LIFECYCLE.read_text(encoding="utf-8")
        self.assertIn("dev-runtime", lifecycle)
        self.assertIn("dev-load-test", lifecycle)
        self.assertIn("Cloudflare mutation", lifecycle)
        self.assertNotIn("cloudflare", lifecycle.lower().replace("cloudflare mutation", ""))

    def test_help_is_local_and_does_not_require_live_aws(self) -> None:
        result = subprocess.run(["bash", str(LIFECYCLE), "--help"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cleanup lease", result.stderr)
        self.assertIn("Terraform create-plan arguments", result.stderr)

    def test_unknown_create_plan_argument_is_rejected_before_live_calls(self) -> None:
        result = subprocess.run(
            [
                "bash",
                str(LIFECYCLE),
                "--terraform-plan",
                "infra/environments/dev-eks/dev-eks.tfplan",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown argument", result.stderr)

    def test_lifecycle_starts_its_own_caffeinate_assertion(self) -> None:
        lifecycle = LIFECYCLE.read_text(encoding="utf-8")
        self.assertIn("caffeinate -dimsu -w", lifecycle)
        self.assertIn("KEEP_AWAKE_PID", lifecycle)

    def test_preflight_reaches_identity_after_keep_awake_start(self) -> None:
        result = subprocess.run(
            [
                "bash",
                str(LIFECYCLE),
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
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("AWS identity lookup failed", result.stderr)

    def test_input_capsule_is_strict_and_mode_checked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            capsule = Path(directory) / "inputs.json"
            capsule.write_text(
                json.dumps(
                    {
                        "aws_profile": "offline",
                        "region": "ap-northeast-2",
                        "expected_account_id": "123456789012",
                        "backend_image": "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/backend@sha256:" + "a" * 64,
                        "backend_hostname": "api.example.com",
                        "frontend_origin": "https://www.example.com",
                    }
                ),
                encoding="utf-8",
            )
            capsule.chmod(0o644)
            result = subprocess.run(
                [
                    "bash",
                    str(LIFECYCLE),
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
                    "--input-json",
                    str(capsule),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("mode 0600", result.stderr)

    def test_remote_helper_and_verifier_are_executable_contracts(self) -> None:
        for path in (REMOTE, VERIFIER):
            self.assertTrue(path.is_file())
        self.assertIn("dev-eks-cleanup-lease/v1", LIFECYCLE.read_text(encoding="utf-8"))
        self.assertIn("delete-only", VERIFIER.read_text(encoding="utf-8"))

    def test_v7_autonomous_contract_has_no_horizon_gate_or_user_input_path(self) -> None:
        lifecycle = LIFECYCLE.read_text(encoding="utf-8")
        self.assertIn("--autonomous", lifecycle)
        self.assertIn("CANONICAL_INPUT_SHA256", lifecycle)
        self.assertIn("verify_refreshable_sso", lifecycle)
        self.assertIn("credential_heartbeat", lifecycle)
        self.assertIn("generate_authorization_receipt", lifecycle)
        self.assertIn("bind_render_authorization", lifecycle)
        self.assertNotIn("SSO credential horizon is shorter", lifecycle)
        autonomous_section = lifecycle.split("if [[ \"$AUTONOMOUS\" == true ]]; then", 1)[1]
        self.assertNotIn("DEV_EKS_SSM_TIMEOUT_SECONDS", autonomous_section.split("else", 1)[0])

    def test_v7_autonomous_rejects_static_credential_shadowing_before_identity(self) -> None:
        result = subprocess.run(
            ["bash", str(LIFECYCLE), "--autonomous"],
            cwd=ROOT,
            env={**os.environ, "AWS_ACCESS_KEY_ID": "private-marker"},
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("static AWS credential environment variable is set", result.stderr)
        self.assertNotIn("private-marker", result.stderr + result.stdout)

    def test_send_command_denial_has_only_exact_owned_alb_fallback(self) -> None:
        lifecycle = LIFECYCLE.read_text(encoding="utf-8")
        self.assertIn("SSM_TRANSPORT_DENIED", lifecycle)
        self.assertIn("verify_no_controller_owned_alb", lifecycle)
        self.assertIn("ssm_transport_denied_no_alb_fallback", lifecycle)
        self.assertIn("describe-tags", lifecycle)
        self.assertIn("elbv2.k8s.aws/cluster", lifecycle)
        self.assertIn("ingress.k8s.aws/stack", lifecycle)
        self.assertNotIn('.LoadBalancers | type == "array" and length == 0', lifecycle)

    def test_v15_success_freeze_is_the_only_destroy_arm(self) -> None:
        lifecycle = LIFECYCLE.read_text(encoding="utf-8")
        self.assertIn("FULL_SUCCESS_EVIDENCE_FROZEN=true", lifecycle)
        self.assertIn("DESTROY_ARMED=true", lifecycle)
        self.assertIn("blocked_until_full_success_evidence", lifecycle)
        self.assertIn("full-live-success.private.json", lifecycle)
        self.assertIn("PLAN_VERSION=15", lifecycle)
        self.assertIn("handoff-v15.yaml", lifecycle)


if __name__ == "__main__":
    unittest.main()
