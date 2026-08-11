from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_ROOT / "scripts/loadtest/aws/orchestrate-aws-b01.sh"
PROFILE = REPOSITORY_ROOT / "load-tests/aws/profiles/ec2-b01.json"
DESTROY_GATE = REPOSITORY_ROOT / "scripts/loadtest/aws/check-destroy-gate.sh"


class AwsOrchestrationContractTests(unittest.TestCase):
    def test_help_exposes_approved_operator_inputs(self) -> None:
        result = subprocess.run(
            ["bash", str(SCRIPT), "--help"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--base-url URL", result.stdout)
        self.assertIn("--runner-instance-type TYPE", result.stdout)
        self.assertIn("d005-record", result.stdout)

    def test_alb_dns_base_url_is_rejected_before_aws_calls(self) -> None:
        result = subprocess.run(
            [
                "bash",
                str(SCRIPT),
                "target",
                "--dry-run",
                "--region",
                "ap-northeast-2",
                "--environment",
                "dev",
                "--expected-account-id",
                "111111111111",
                "--alb-arn",
                "arn:aws:elasticloadbalancing:ap-northeast-2:111111111111:loadbalancer/app/example/1234567890abcdef",
                "--base-url",
                "https://internal-example.ap-northeast-2.elb.amazonaws.com",
                "--runner-id",
                "i-0123456789abcdef0",
                "--max-rate",
                "100",
                "--max-vus",
                "20",
                "--run-id",
                "aws-b01-orchestrate-test",
                "--profile",
                str(PROFILE),
            ],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("approved custom HTTPS hostname", result.stderr)

    def test_runner_validation_is_ec2_ssm_not_runner_asg_lookup(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("validate_runner_instance", source)
        self.assertIn("validate_runner_ssm", source)
        self.assertIn('PingStatus\") != \"Online\"', source)
        self.assertNotIn(
            'autoscaling describe-auto-scaling-instances --instance-ids "$RUNNER_ID"',
            source,
        )

    def test_stage_marker_is_bound_to_run_profile_and_rate(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('payload.get("runId") != run_id', source)
        self.assertIn('payload.get("profileSha256") != profile_sha', source)
        self.assertIn('(payload.get("confirmedRate") or "") != confirmed_rate', source)
        self.assertIn('baseline-*|d005|spike', source)
        self.assertIn('stage exists but profile/rate inputs differ', source)

    def test_destroy_gate_requires_local_export_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("freeze-metadata.json", "export-complete.json"):
                (root / name).write_text("{}", encoding="utf-8")
            blocked = subprocess.run(["bash", str(DESTROY_GATE), str(root)], capture_output=True, text=True, check=False)
            self.assertEqual(blocked.returncode, 1)
            self.assertIn("local-export-complete.json", blocked.stderr)

            (root / "local-export-complete.json").write_text("{}", encoding="utf-8")
            allowed = subprocess.run(["bash", str(DESTROY_GATE), str(root)], capture_output=True, text=True, check=False)
            self.assertEqual(allowed.returncode, 0, allowed.stderr)


if __name__ == "__main__":
    unittest.main()
