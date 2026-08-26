"""Offline contracts for the v11 split-principal smoke path."""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "scripts" / "eks" / "run-dev-eks-repair-smoke.sh"
DEPLOYER = ROOT / "scripts" / "eks" / "deploy-dev-eks.sh"


class RepairSmokeContractTest(unittest.TestCase):
    def test_bastion_helper_is_executable_and_shell_clean(self) -> None:
        self.assertTrue(os.access(HELPER, os.X_OK))
        self.assertEqual(subprocess.run(["bash", "-n", str(HELPER)]).returncode, 0)

    def test_bastion_helper_has_only_private_kubernetes_probes(self) -> None:
        source = HELPER.read_text(encoding="utf-8")
        self.assertIn("aws eks update-kubeconfig", source)
        self.assertIn('KUBECONFIG_PATH="$WORK_DIR/kubeconfig"', source)
        self.assertIn('export KUBECONFIG="$KUBECONFIG_PATH"', source)
        self.assertIn('--kubeconfig "$KUBECONFIG_PATH"', source)
        self.assertIn("kubectl get --request-timeout=30s ingress backend", source)
        self.assertIn("kubectl get --request-timeout=30s secret backend-secret", source)
        self.assertIn("Redis TLS AUTH/PING", source)
        self.assertIn("Prometheus private query", source)
        self.assertIn("Loki private query", source)
        self.assertIn("--connect-to", source)
        self.assertIn("Flyway success evidence", source)
        for forbidden in (
            "elbv2",
            "rds describe",
            "elasticache",
            "s3api",
            "resourcegroupstaggingapi",
            "kubectl delete",
            "terraform",
            "iam",
        ):
            self.assertNotIn(forbidden, source)

    def test_private_files_are_scoped_and_redacted_summary_is_written(self) -> None:
        source = HELPER.read_text(encoding="utf-8")
        self.assertIn("/var/tmp/travel-planner-dev-eks-*/*", source)
        self.assertIn("chmod 0700", source)
        self.assertIn("chmod 0600", source)
        self.assertIn("unset REDIS_AUTH_PASSWORD", source)
        self.assertIn("dev-eks-repair-smoke/v1", source)
        self.assertIn("stage=repair-smoke status=success", source)

    def test_traversal_work_directory_is_rejected_before_remote_probes(self) -> None:
        result = subprocess.run(
            [
                str(HELPER),
                "--cluster-name", "kdt-travelplanner-dev-eks",
                "--region", "ap-northeast-2",
                "--backend-hostname", "api.example.com",
                "--monitoring-dns", "monitoring.example.com",
                "--redis-endpoint", "redis.example.com",
                "--redis-port", "6379",
                "--work-dir", "/var/tmp/travel-planner-dev-eks-x/../escape",
            ],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("work directory", result.stderr)

    def test_parent_symlink_is_rejected_before_remote_probes(self) -> None:
        link = Path(f"/var/tmp/travel-planner-dev-eks-smoke-link-{os.getpid()}")
        try:
            try:
                link.symlink_to(Path("/private/tmp"), target_is_directory=True)
            except PermissionError:
                self.skipTest("sandbox does not permit creating a temporary /var/tmp symlink")
            result = subprocess.run(
                [
                    str(HELPER), "--cluster-name", "kdt-travelplanner-dev-eks", "--region", "ap-northeast-2",
                    "--backend-hostname", "api.example.com", "--monitoring-dns", "monitoring.example.com",
                    "--redis-endpoint", "redis.example.com", "--redis-port", "6379", "--work-dir", f"{link}/smoke",
                ], capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symlink", result.stderr)
        finally:
            link.unlink(missing_ok=True)

    def test_deployer_defers_v11_cname_until_both_smokes_pass(self) -> None:
        source = DEPLOYER.read_text(encoding="utf-8")
        self.assertIn("run_repair_remote_smoke", source)
        self.assertIn("run_operator_native_smoke", source)
        self.assertIn("finalize_repair_success", source)
        self.assertIn("describe-load-balancers", source)
        self.assertIn("describe-tags", source)
        self.assertIn("describe-target-groups", source)
        self.assertIn("describe-target-health", source)
        self.assertIn("head-bucket", source)
        self.assertIn('if type == "array" then length else error("native ALB response is not an array") end', source)
        self.assertIn(".[0].LoadBalancerArn", source)
        self.assertIn("DEV_EKS_DEFER_CNAME_OUTPUT", source)
        self.assertIn("final-cname.private.txt", source)
        self.assertNotIn("resourcegroupstaggingapi", source)
        kubernetes = source.split("run_kubernetes_stages()", 1)[1].split("main()", 1)[0]
        self.assertIn('if [[ "$CREATE_RECEIPT_SCHEMA" != "dev-eks-repair-authorization/v1" ]]', kubernetes)

    def test_native_alb_parser_accepts_the_real_array_response_shape(self) -> None:
        result = subprocess.run(
            ["bash", "-c", "set -e; lb_json='[{\"LoadBalancerArn\":\"arn:aws:elasticloadbalancing:ap-northeast-2:419496180357:loadbalancer/app/x/123\"}]'; count=$(jq -er 'if type == \"array\" then length else error(\"native ALB response is not an array\") end' <<<\"$lb_json\"); arn=$(jq -er '.[0].LoadBalancerArn | select(type == \"string\" and test(\"^arn:aws:elasticloadbalancing:\"))' <<<\"$lb_json\"); test \"$count\" = 1; test -n \"$arn\""],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
