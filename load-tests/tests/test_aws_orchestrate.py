from __future__ import annotations

import json
import shlex
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
        self.assertIn('payload.get("inputDigest") != input_digest', source)
        self.assertIn('"albArn": alb_arn', source)
        self.assertIn('"baseUrl": base_url', source)
        self.assertIn('"runnerId": runner_id', source)
        self.assertIn('"expectedAccountId": expected_account_id', source)
        self.assertIn('"region": region', source)
        self.assertIn('baseline-*|d005|spike', source)
        self.assertIn('stage exists but profile/rate inputs differ', source)

    def test_stage_marker_skips_with_same_inputs_and_rejects_changed_safety_input(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        start = source.index("stage_confirmed_rate()")
        end = source.index("\nverify_account()", start)
        function_fragment = source[start:end]

        common_setup = """
set -euo pipefail
RUN_ID=aws-b01-marker-test
PROFILE_SHA256=profile-sha
SOURCE_COMMIT_SHA=commit-sha
REGION=ap-northeast-2
ENVIRONMENT=dev
EXPECTED_ACCOUNT_ID=111111111111
ALB_ARN=arn:aws:elasticloadbalancing:ap-northeast-2:111111111111:loadbalancer/app/example/old
BASE_URL=https://b01.example.com
RUNNER_ID=i-0123456789abcdef0
RUNNER_INSTANCE_TYPE=t3.small
MAX_RATE=100
MAX_VUS=20
K6_IMAGE=sha256:k6
USERS=20
DATABASE_HOST=db.internal
DATABASE_PORT=5432
DATABASE_NAME=travel
DATABASE_SECRET_ARN=arn:aws:secretsmanager:ap-northeast-2:111111111111:secret:b01-test
DB_INSTANCE_IDENTIFIER=travel-db
REDIS_HOST=redis.internal
REDIS_PORT=6379
REDIS_IAM_USER=b01-test
REDIS_REPLICATION_GROUP_ID=travel-redis
CACHE_CLUSTER_ID=travel-redis-001
S3_BUCKET=b01-evidence
S3_PREFIX=evidence/aws-load-tests
GRAFANA_URL=http://grafana.internal
GRAFANA_ADMIN_USER=evidence
GRAFANA_ADMIN_PASSWORD=not-written-to-marker
PROMETHEUS_URL=http://prometheus.internal
SLO_FREEZE_APPROVED_BY=operator
CONFIRMED_RATE=80
START_RATE=1
DURATION=10m
WARMUP=3m
RAMP_PREALLOCATED_VUS=20
RAMP_MAX_VUS=21
BASELINE_PREALLOCATED_VUS=20
BASELINE_MAX_VUS=40
SPIKE_PREALLOCATED_VUS=20
SPIKE_MAX_VUS=80
SPIKE_PEAK_MULTIPLIER=3
SPIKE_HOLD=1m
DRY_RUN=0
STAGE_DIR={stage_dir}
source {fragment}
"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fragment_path = root / "marker-functions.sh"
            fragment_path.write_text(function_fragment, encoding="utf-8")
            stage_dir = root / "stages"
            setup_script = common_setup.format(stage_dir=shlex.quote(str(stage_dir)), fragment=shlex.quote(str(fragment_path)))
            first_script = setup_script + "\nmark_stage_complete smoke\n"
            first = subprocess.run(["bash", "-c", first_script], capture_output=True, text=True, check=False)
            self.assertEqual(first.returncode, 0, first.stderr)

            marker = json.loads((stage_dir / "smoke.json").read_text(encoding="utf-8"))
            self.assertEqual(len(marker["inputDigest"]), 64)
            self.assertNotIn("not-written-to-marker", (stage_dir / "smoke.json").read_text(encoding="utf-8"))

            same = subprocess.run(
                ["bash", "-c", setup_script + "\nrun_stage_once smoke true\n"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(same.returncode, 0, same.stderr)
            self.assertIn("already complete", same.stdout)

            changed_setup = setup_script.replace(
                "loadbalancer/app/example/old", "loadbalancer/app/example/new",
            )
            changed = subprocess.run(
                ["bash", "-c", changed_setup + "\nrun_stage_once smoke true\n"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(changed.returncode, 2)
            self.assertIn("safety input digest", changed.stderr)

            override_cases = (
                ("ramp", "RAMP_MAX_VUS=21", "RAMP_MAX_VUS=90"),
                ("baseline-1", "BASELINE_MAX_VUS=40", "BASELINE_MAX_VUS=90"),
                ("spike", "SPIKE_HOLD=1m", "SPIKE_HOLD=2m"),
            )
            for stage, original_input, changed_input in override_cases:
                create_marker = subprocess.run(
                    ["bash", "-c", setup_script + f"\nmark_stage_complete {stage}\n"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(create_marker.returncode, 0, create_marker.stderr)
                changed_override_setup = setup_script.replace(original_input, changed_input)
                changed_override = subprocess.run(
                    ["bash", "-c", changed_override_setup + f"\nrun_stage_once {stage} true\n"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(changed_override.returncode, 2, changed_override.stderr)
                self.assertIn("safety input digest", changed_override.stderr)

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
