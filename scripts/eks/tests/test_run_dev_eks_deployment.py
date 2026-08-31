"""Offline safety and sequencing contracts for the Bastion stage runner."""

from __future__ import annotations

import json
import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "eks" / "run-dev-eks-deployment.sh"


class BastionRunnerContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SCRIPT.read_text(encoding="utf-8")

    def test_shell_syntax_and_shellcheck_are_clean(self) -> None:
        syntax = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        lint = subprocess.run(["shellcheck", "--severity=warning", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)

    def test_stages_are_explicit_and_ordered(self) -> None:
        positions = [self.source.rindex(f'  {stage})') for stage in ("prepare", "namespace-secret", "platform", "workload", "ingress-wait")]
        self.assertEqual(positions, sorted(positions))
        for stage in ("prepare", "namespace-secret", "platform", "workload", "ingress-wait"):
            self.assertIn(stage, self.source)
        self.assertIn("require_prepared", self.source)
        self.assertIn("load_contract", self.source)
        self.assertIn("require_completed_stage", self.source)
        self.assertIn("completed_stages", self.source)
        self.assertIn("EXPECTED_CONTRACT_SHA256", self.source)
        self.assertIn("EXPECTED_VALUES_SHA256", self.source)
        self.assertIn("resume action-time render", self.source)
        self.assertIn("bundle manifest content revision mismatch", self.source)
        self.assertIn("platform ServiceAccount is missing", self.source)
        self.assertIn('type == "Available" and .status == "True"', self.source)
        self.assertIn("trap cleanup_transient EXIT", self.source)
        self.assertIn('"$RENDER_DIR/base/backend/namespace.yaml"', self.source)
        self.assertIn('"$RENDER_DIR/base/monitoring/namespace.yaml"', self.source)
        self.assertIn("both the backend and monitoring trees", self.source)

    def test_kubeconfig_is_explicit_and_shared_by_all_stage_invocations(self) -> None:
        self.assertIn('KUBECONFIG_PATH="$WORK_DIR/kubeconfig"', self.source)
        self.assertIn('export KUBECONFIG="$KUBECONFIG_PATH"', self.source)
        self.assertIn('aws eks update-kubeconfig --name "$cluster" --region "$region" --kubeconfig "$KUBECONFIG_PATH"', self.source)

    def test_stale_bundle_aws_lbc_compatibility_and_platform_failure_tail_are_explicit(self) -> None:
        self.assertIn("normalize_legacy_load_balancer_controller_args", self.source)
        self.assertIn('$BUNDLE_DIR/base/platform/aws-load-balancer-controller-deployment.yaml', self.source)
        self.assertIn('$BUNDLE_DIR/k8s/base/platform/aws-load-balancer-controller-deployment.yaml', self.source)
        self.assertIn("aws-load-balancer-webhook-tls", self.source)
        self.assertIn("ensure_controller_webhook_tls", self.source)
        self.assertIn("containerPort: 61779", self.source)
        self.assertIn("path: /readyz\\n              port: health", self.source)
        self.assertIn("path: /healthz\\n              port: health", self.source)
        self.assertIn("enable-service-mutator-webhook=false", self.source)
        self.assertIn("removed-unsupported-aws-lbc-flag", self.source)
        self.assertIn("platform_log_tail:", self.source)
        self.assertIn("normalize_dev_eks_workload_compatibility", self.source)
        self.assertIn("normalized-dev-eks-workload-security-requests-and-alb-security-group-strategy", self.source)
        self.assertIn("runAsUser: {uid}", self.source)
        self.assertIn("ensure_tmp_mount", self.source)
        self.assertIn('"alloy-tmp", "128Mi"', self.source)
        self.assertIn("ensure_fs_group_policy", self.source)
        self.assertIn("ensure_backend_rollout_strategy", self.source)
        self.assertIn("ensure_backend_cpu_resources", self.source)
        self.assertIn("ensure_storage_parent_mount", self.source)
        self.assertIn("ensure_ingress_security_group_strategy", self.source)
        self.assertIn("manage-backend-security-group-rules", self.source)
        self.assertIn("alb_security_group_id", self.source)
        self.assertIn("{alb_sg},{cluster_sg}", self.source)
        self.assertIn("clusterSecurityGroupId", self.source)
        self.assertIn('(\"640Mi\", \"512Mi\", \"448Mi\", \"384Mi\"), \"640Mi\"', self.source)
        self.assertIn('current in {\"250m\", \"200m\", \"384m\", \"550m\"}', self.source)
        self.assertIn('(\"128Mi\", \"64Mi\"), \"64Mi\"', self.source)
        self.assertIn('(\"256Mi\", \"128Mi\", \"64Mi\"), \"64Mi\"', self.source)

    def test_platform_manifest_does_not_pass_removed_aws_lbc_flag(self) -> None:
        manifest = ROOT / "k8s" / "base" / "platform" / "aws-load-balancer-controller-deployment.yaml"
        self.assertNotIn("--enable-service-mutator-webhook=false", manifest.read_text(encoding="utf-8"))
        self.assertIn("containerPort: 61779", manifest.read_text(encoding="utf-8"))
        self.assertIn("port: health", manifest.read_text(encoding="utf-8"))

    def test_secret_bootstrap_and_verification_never_print_values(self) -> None:
        self.assertIn("bootstrap-backend-secret.sh", self.source)
        self.assertIn("secret-metadata.json", self.source)
        self.assertIn(".data | keys | sort", self.source)
        self.assertIn("map({(.): null})", self.source)
        self.assertIn('has("SecretString")', self.source)
        self.assertNotIn("kubectl get secret backend-secret --namespace travel-planner --output jsonpath", self.source)
        self.assertNotIn("set -x", self.source)

    def test_mutation_is_bounded_and_cloudflare_handoff_is_stable(self) -> None:
        self.assertIn("--timeout \"$ROLLOUT_TIMEOUT\"", self.source)
        self.assertIn("INGRESS_TIMEOUT_SECONDS", self.source)
        self.assertIn("CLOUDFLARE_CNAME_TARGET=", self.source)
        self.assertRegex(self.source, r"elb\\\.amazonaws\\\.com")
        self.assertNotIn("--yes", self.source)
        self.assertNotIn("auto-approve", self.source)

    def test_fake_kubectl_platform_command_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            command_log = root / "kubectl.log"
            (fake_bin / "aws").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            (fake_bin / "kubectl").write_text(
                "#!/usr/bin/env bash\n"
                f"printf '%s\\n' \"$*\" >> {command_log}\n"
                "if [[ \"$1\" == get && \"$*\" == *'secret backend-secret'* ]]; then printf '%s' '{\"metadata\":{\"name\":\"backend-secret\",\"namespace\":\"travel-planner\"},\"data\":{\"GOOGLE_MAPS_API_KEY\":null,\"GOOGLE_OAUTH_CLIENT_ID\":null,\"GOOGLE_OAUTH_CLIENT_SECRET\":null,\"JWT_SECRET\":null,\"NAVER_OAUTH_CLIENT_ID\":null,\"NAVER_OAUTH_CLIENT_SECRET\":null,\"SPRING_DATA_REDIS_PASSWORD\":null,\"SPRING_DATASOURCE_PASSWORD\":null,\"SPRING_DATASOURCE_USERNAME\":null}}'; exit 0; fi\n"
                "if [[ \"$1\" == get && \"$2\" == serviceaccount ]]; then printf 'serviceaccount/%s\\n' \"$3\"; exit 0; fi\n"
                "if [[ \"$1\" == get && \"$2\" == deployment ]]; then printf '%s' '{\"status\":{\"conditions\":[{\"type\":\"Available\",\"status\":\"True\"}]}}'; exit 0; fi\n"
                "if [[ \"$1\" == diff ]]; then exit 0; fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            for executable in (fake_bin / "aws", fake_bin / "kubectl"):
                executable.chmod(0o755)

            work = root / "work"
            (work / "rendered/overlays/dev-eks/platform").mkdir(parents=True)
            bundle_file = work / "bundle/fixture.txt"
            bundle_file.parent.mkdir(parents=True)
            bundle_file.write_text("fixture\n", encoding="utf-8")
            bundle_files = {"fixture.txt": hashlib.sha256(bundle_file.read_bytes()).hexdigest()}
            revision = hashlib.sha256(json.dumps(bundle_files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            (work / "bundle/bundle-manifest.json").write_text(
                json.dumps({"schema_version": "dev-eks-bundle/v1", "revision": revision, "files": bundle_files}),
                encoding="utf-8",
            )
            render_sha = "b" * 64
            (work / "runtime-contract.json").write_text(
                json.dumps(
                    {
                        "schema_version": "dev-eks-deployment-contract/v1",
                        "aws_account_id": "123456789012",
                        "aws_region": "ap-northeast-2",
                        "cluster_name": "kdt-travelplanner-dev-eks",
                        "alb_security_group_id": "sg-0123456789abcdef0",
                        "bastion_instance_id": "i-0123456789abcdef0",
                        "bundle_revision_sha256": revision,
                        "vpc_id": "vpc-0123456789abcdef0",
                        "public_subnet_ids": ["subnet-a", "subnet-b"],
                        "api_certificate_arn": "arn:aws:acm:ap-northeast-2:123456789012:certificate/a",
                        "profile_image_bucket_name": "kdt-travelplanner-profile-images",
                        "profile_image_public_base_url": "https://images.example.com",
                        "backend_application_secret_arn": "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:app",
                        "database_master_secret_arn": "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:db",
                        "redis_auth_secret_arn": "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:redis",
                    }
                ),
                encoding="utf-8",
            )
            (work / "runner-state.json").write_text(
                json.dumps(
                    {
                        "schema_version": "dev-eks-runner-state/v1",
                        "stage": "prepare",
                        "status": "success",
                        "bundle_revision_sha256": revision,
                        "render_sha256": render_sha,
                        "completed_stages": ["prepare", "namespace-secret"],
                    }
                ),
                encoding="utf-8",
            )
            values = root / "values.json"
            values.write_text("{}", encoding="utf-8")
            result = subprocess.run(
                [
                    "bash",
                    str(SCRIPT),
                    "--stage",
                    "platform",
                    "--bucket",
                    "private-bucket",
                    "--values-file",
                    str(values),
                    "--expected-bundle-revision",
                    revision,
                    "--expected-render-sha256",
                    render_sha,
                    "--work-dir",
                    str(work),
                ],
                env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            commands = command_log.read_text(encoding="utf-8").splitlines()
            verbs = [line.split()[0] for line in commands]
            self.assertEqual(verbs[:2], ["get", "get"])
            self.assertIn(verbs[2:4], (["create", "apply"], ["apply", "create"]))
            self.assertEqual(
                verbs[4:],
                ["diff", "apply", "rollout", "rollout", "rollout", "get", "get", "get", "get", "get", "get"],
            )
            self.assertEqual(
                verbs[6:],
                ["rollout", "rollout", "rollout", "get", "get", "get", "get", "get", "get"],
            )


if __name__ == "__main__":
    unittest.main()
