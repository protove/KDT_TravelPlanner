"""Bounded failure and resume guards for the EKS deployment contracts."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "scripts" / "eks" / "run-dev-eks-deployment.sh"
OPERATOR = ROOT / "scripts" / "eks" / "deploy-dev-eks.sh"
OPERATOR_README = ROOT / "infra" / "environments" / "dev-eks" / "README.md"
KUSTOMIZE_README = ROOT / "k8s" / "overlays" / "dev-eks" / "README.md"
RUNBOOK = ROOT / "reference" / "infrastructure" / "terraform" / "DEV_EKS_APPLY_RUNBOOK.local.md"


class FailureMatrixTest(unittest.TestCase):
    def test_operator_and_runner_fail_closed_on_terminal_ssm_and_ambiguous_outputs(self) -> None:
        operator_source = OPERATOR.read_text(encoding="utf-8")
        runner_source = RUNNER.read_text(encoding="utf-8")
        for status in ("Failed", "Cancelled", "TimedOut", "Cancelling"):
            self.assertIn(status, operator_source)
        self.assertIn("SSM polling timeout", operator_source)
        self.assertIn("candidate_count", operator_source)
        self.assertIn("exactly one validated CNAME target", operator_source)
        self.assertIn("index(true) == null", operator_source)
        self.assertIn("platform ServiceAccount is missing", runner_source)
        self.assertIn("platform Deployment is not Available", runner_source)

    def test_help_and_docs_match_stage_suffix_and_prepare_side_effects(self) -> None:
        help_result = subprocess.run(["bash", str(OPERATOR), "--help"], capture_output=True, text=True)
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("--resume-from prepare|namespace-secret|platform|workload|ingress-wait", help_result.stderr)
        operator_readme = OPERATOR_README.read_text(encoding="utf-8")
        kustomize_readme = KUSTOMIZE_README.read_text(encoding="utf-8")
        runbook = RUNBOOK.read_text(encoding="utf-8")
        for document in (operator_readme, kustomize_readme, runbook):
            self.assertIn("APPLY KUBERNETES", document)
        self.assertIn("--resume-from prepare|namespace-secret|platform|workload|ingress-wait", operator_readme)
        self.assertIn("완전한 read-only 단계로 취급하지 않는다", runbook)
        self.assertIn("private run-prefix", operator_readme)
        self.assertIn("provenance_check", operator_readme)
        self.assertNotIn("prepare`는 읽기 전용", operator_readme)

    def test_support_preflight_docs_use_current_fields_and_no_stale_query(self) -> None:
        operator_readme = OPERATOR_README.read_text(encoding="utf-8")
        automation = (ROOT / "reference" / "infrastructure" / "terraform" / "DEV_EKS_DEPLOYMENT_AUTOMATION.md").read_text(encoding="utf-8")
        runbook = (ROOT / "reference" / "infrastructure" / "terraform" / "DEV_EKS_DEPLOYMENT_RUNBOOK.md").read_text(encoding="utf-8")
        local_runbook = (ROOT / "reference" / "infrastructure" / "terraform" / "DEV_EKS_APPLY_RUNBOOK.local.md").read_text(encoding="utf-8")
        for document in (operator_readme, automation, runbook):
            self.assertIn("clusterVersion", document)
            self.assertIn("versionStatus", document)
            self.assertNotIn("version==`1.35`", document)
            self.assertNotIn(".[version,status,clusterType]", document)
        self.assertIn("cluster_version", local_runbook)
        self.assertIn("versionStatus", local_runbook)
        self.assertNotIn("version==`1.35`", local_runbook)
        self.assertNotIn(".[version,status,clusterType]", local_runbook)
        self.assertIn("variables.kubernetes_version.value", automation)
        self.assertIn("cluster_version", runbook)
        self.assertIn("EXTENDED_SUPPORT", local_runbook)

    def _runner_fixture(self, root: Path, completed: list[str]) -> tuple[Path, Path, list[str]]:
        fake_bin = root / "bin"
        fake_bin.mkdir()
        log = root / "kubectl.log"
        (fake_bin / "aws").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        (fake_bin / "kubectl").write_text(
            "#!/usr/bin/env bash\n"
            f"printf '%s\\n' \"$*\" >> {log}\n"
            "if [[ \"$1\" == diff ]]; then exit \"${FAKE_DIFF_STATUS:-0}\"; fi\n"
            "if [[ \"$1\" == get && \"$*\" == *'secret backend-secret'* ]]; then printf '%s' '{\"metadata\":{\"name\":\"backend-secret\",\"namespace\":\"travel-planner\"},\"data\":{\"GOOGLE_MAPS_API_KEY\":null,\"GOOGLE_OAUTH_CLIENT_ID\":null,\"GOOGLE_OAUTH_CLIENT_SECRET\":null,\"JWT_SECRET\":null,\"NAVER_OAUTH_CLIENT_ID\":null,\"NAVER_OAUTH_CLIENT_SECRET\":null,\"SPRING_DATASOURCE_PASSWORD\":null,\"SPRING_DATASOURCE_USERNAME\":null,\"SPRING_DATA_REDIS_PASSWORD\":null}}'; exit 0; fi\n"
            "if [[ \"$1\" == get && \"$*\" == *'deployment backend'* ]]; then printf '%s' '{\"status\":{\"readyReplicas\":2}}'; exit 0; fi\n"
            "if [[ \"$1\" == get && \"$*\" == *'hpa backend'* ]]; then printf '%s' '{\"spec\":{\"minReplicas\":2,\"maxReplicas\":4}}'; exit 0; fi\n"
            "if [[ \"$1\" == get && \"$*\" == *'ingress backend'* ]]; then printf '%s' '{\"status\":{\"loadBalancer\":{\"ingress\":[]}}}'; exit 0; fi\n"
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
                    "render_sha256": "b" * 64,
                    "completed_stages": completed,
                }
            ),
            encoding="utf-8",
        )
        values = root / "values.json"
        values.write_text("{}", encoding="utf-8")
        args = [
            "bash",
            str(RUNNER),
            "--bucket",
            "private-bucket",
            "--values-file",
            str(values),
            "--expected-bundle-revision",
            revision,
            "--expected-render-sha256",
            "b" * 64,
            "--work-dir",
            str(work),
        ]
        return fake_bin, work, args

    def test_runner_rejects_prerequisite_skip_and_diff_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin, _, args = self._runner_fixture(root, ["prepare"])
            missing = subprocess.run(
                [*args[:2], "--stage", "platform", *args[2:]],
                env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("required prior stage is not complete", missing.stderr)

            diff_root = root / "diff"
            diff_root.mkdir()
            fake_bin, _, args = self._runner_fixture(diff_root, ["prepare", "namespace-secret"])
            failed_diff = subprocess.run(
                [*args[:2], "--stage", "platform", *args[2:]],
                env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}", "FAKE_DIFF_STATUS": "2"},
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(failed_diff.returncode, 0)
            self.assertIn("kubernetes diff failed", failed_diff.stderr)

    def test_runner_ingress_wait_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin, _, args = self._runner_fixture(root, ["prepare", "namespace-secret", "platform", "workload"])
            timed_out = subprocess.run(
                [*args[:2], "--stage", "ingress-wait", *args[2:]],
                env={
                    **os.environ,
                    "PATH": f"{fake_bin}:{os.environ['PATH']}",
                    "DEV_EKS_INGRESS_TIMEOUT_SECONDS": "0",
                },
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(timed_out.returncode, 0)
            self.assertIn("did not become ready before timeout", timed_out.stderr)

    def test_runner_rejects_tampered_bundle_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin, work, args = self._runner_fixture(root, ["prepare", "namespace-secret"])
            (work / "bundle/fixture.txt").write_text("tampered\n", encoding="utf-8")
            failed = subprocess.run(
                [*args[:2], "--stage", "platform", *args[2:]],
                env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("bundle file checksum mismatch", failed.stderr)

    def test_operator_rejects_invalid_resume_and_account_before_aws(self) -> None:
        common = [
            "bash",
            str(OPERATOR),
            "--mode",
            "resume",
            "--resume-from",
            "invalid",
            "--aws-profile",
            "offline",
            "--region",
            "ap-northeast-2",
            "--expected-account-id",
            "123456789012",
            "--kubernetes-render-sha256",
            "b" * 64,
            "--backend-image",
            "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/backend@sha256:" + "c" * 64,
            "--backend-hostname",
            "api.example.com",
            "--frontend-origin",
            "https://www.example.com",
        ]
        invalid_resume = subprocess.run(common, cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(invalid_resume.returncode, 0)
        self.assertIn("resume requires an explicit named remote stage", invalid_resume.stderr)

        invalid_account_args = list(common)
        invalid_account_args[11] = "bad-account"
        invalid_account = subprocess.run(invalid_account_args, cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(invalid_account.returncode, 0)
        self.assertIn("expected account id must be 12 digits", invalid_account.stderr)


if __name__ == "__main__":
    unittest.main()
