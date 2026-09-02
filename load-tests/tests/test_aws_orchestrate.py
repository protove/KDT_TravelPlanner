from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

# Every subprocess in this module inherits an isolated evidence base so a
# test run can never write into the repository's protected evidence/ tree
# (a real B-01 run's diagnostic files were overwritten by this suite on
# 2026-08-12 before this guard existed).
_EVIDENCE_ISOLATION = tempfile.TemporaryDirectory(prefix="b01-test-evidence-")
os.environ["B01_EVIDENCE_BASE"] = _EVIDENCE_ISOLATION.name
os.environ["AWS_RECOVERY_EVIDENCE_BASE"] = _EVIDENCE_ISOLATION.name

SCRIPT = REPOSITORY_ROOT / "scripts/loadtest/aws/orchestrate-aws-b01.sh"
PROFILE = REPOSITORY_ROOT / "load-tests/aws/profiles/ec2-b01.json"
DESTROY_GATE = REPOSITORY_ROOT / "scripts/loadtest/aws/check-destroy-gate.sh"
LOAD_RUNNER_TERRAFORM = REPOSITORY_ROOT / "infra/modules/load_test_runner/main.tf"
LOAD_RUNNER_USER_DATA = REPOSITORY_ROOT / "infra/modules/load_test_runner/templates/runner-user-data.sh.tftpl"
AWS_K6_RUNNER = REPOSITORY_ROOT / "scripts/loadtest/aws/run-k6-aws-scenario.sh"
AWS_PHASE_RUNNER = REPOSITORY_ROOT / "scripts/loadtest/aws/run-aws-b01.sh"
K6_ROOT = REPOSITORY_ROOT / "load-tests/k6"
K6_DATA = K6_ROOT / "lib/data.js"


class AwsOrchestrationContractTests(unittest.TestCase):
    def test_aws_k6_runner_mounts_shared_modules_and_run_credentials(self) -> None:
        runner_source = AWS_K6_RUNNER.read_text(encoding="utf-8")
        orchestrator_source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('K6_DIR="$REPOSITORY_ROOT/load-tests/k6"', runner_source)
        self.assertNotIn('K6_DIR="$REPOSITORY_ROOT/load-tests/k6/aws"', runner_source)
        self.assertIn('-v "$K6_DIR:/scripts:ro"', runner_source)
        self.assertIn('-v "$DATA_FILE:/data/data.json:ro"', runner_source)
        self.assertIn('-e DATA_FILE=/data/data.json', runner_source)
        self.assertIn('-e REQUIRE_UNIQUE_CREDENTIALS=1', runner_source)
        self.assertIn('-e REQUIRED_UNIQUE_CREDENTIAL_COUNT="$EFFECTIVE_MAX_VUS"', runner_source)
        self.assertIn('-e MAX_VUS="${MAX_VUS:-}"', runner_source)
        self.assertIn('EFFECTIVE_MAX_VUS="${EFFECTIVE_MAX_VUS:?', runner_source)
        self.assertIn('len(credentials) < required', runner_source)
        self.assertIn('payload.get("seedState") != "complete"', runner_source)
        self.assertIn('payload.get("fixtureState") != "verified"', runner_source)
        self.assertIn('--user 0:0', runner_source)
        self.assertIn('--cap-drop ALL', runner_source)
        self.assertIn('--security-opt no-new-privileges', runner_source)
        self.assertIn('"/scripts/aws/scenarios/$SCENARIO_FILE"', runner_source)
        self.assertIn('DATA_FILE="${DATA_FILE:?', runner_source)
        self.assertIn('export DATA_FILE', orchestrator_source)

        data_source = K6_DATA.read_text(encoding="utf-8")
        self.assertIn("REQUIRE_UNIQUE_CREDENTIALS === '1'", data_source)
        self.assertIn("credentialIndex >= credentials.length", data_source)
        self.assertIn("credentials[credentialIndex]", data_source)
        self.assertIn("credentials.length < requiredCredentialCount", data_source)
        self.assertIn("parsed.seedState !== 'complete'", data_source)

        import_pattern = re.compile(r"from ['\"](\.\./[^'\"]+)['\"]")
        for scenario in sorted((K6_ROOT / "aws/scenarios").glob("*.js")):
            for module_specifier in import_pattern.findall(scenario.read_text(encoding="utf-8")):
                module_path = (scenario.parent / module_specifier).resolve()
                self.assertTrue(
                    module_path.is_file(),
                    f"{scenario.relative_to(REPOSITORY_ROOT)} cannot resolve {module_specifier}",
                )
                self.assertTrue(
                    module_path.is_relative_to(K6_ROOT.resolve()),
                    f"{module_path} escapes the read-only k6 mount",
                )

    def test_target_discovery_separates_multiple_healthy_instance_ids(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn(r'print("\n".join(', source)
        self.assertNotIn(r'print("\\n".join(', source)

    def test_target_group_cloudwatch_dimension_keeps_required_prefix(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn(
            '"targetGroupDimension": suffix(target_group_arn, "targetgroup/", include_marker=True)',
            source,
        )

    def test_runner_role_can_read_every_target_discovery_dependency_in_region(self) -> None:
        source = LOAD_RUNNER_TERRAFORM.read_text(encoding="utf-8")
        self.assertIn('sid = "LoadTestTargetDiscovery"', source)
        for action in (
            "autoscaling:DescribeAutoScalingInstances",
            "autoscaling:DescribeScalingActivities",
            "ec2:DescribeInstances",
            "elasticloadbalancing:DescribeLoadBalancers",
            "elasticloadbalancing:DescribeTargetGroups",
            "elasticloadbalancing:DescribeTargetHealth",
            "ssm:DescribeInstanceInformation",
        ):
            self.assertIn(f'"{action}"', source)
        self.assertIn('variable = "aws:RequestedRegion"', source)
        self.assertIn("values   = [var.aws_region]", source)

    def test_runner_eks_observer_permissions_are_optional_and_bastion_tagged(self) -> None:
        source = LOAD_RUNNER_TERRAFORM.read_text(encoding="utf-8")
        self.assertIn('var.eks_observation_stack != ""', source)
        for action in ("eks:DescribeNodegroup", "cloudwatch:GetMetricStatistics", "ssm:SendCommand", "ssm:GetCommandInvocation"):
            self.assertIn(f'"{action}"', source)
        self.assertIn('variable = "ssm:resourceTag/Stack"', source)
        self.assertIn('values   = [var.eks_observation_stack]', source)
        self.assertNotIn("eks:AccessKubernetesApi", source)

    def test_eks_target_requires_private_runner_readiness_before_seed(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        bootstrap = (REPOSITORY_ROOT / "scripts/loadtest/aws/bootstrap-load-runner-source.sh").read_text(encoding="utf-8")
        user_data = LOAD_RUNNER_USER_DATA.read_text(encoding="utf-8")
        self.assertIn("validate_runner_bootstrap_readiness", source)
        self.assertIn("runner-readiness.json", source)
        self.assertIn("RUNNER_BOOTSTRAP_RUN_ID", source)
        self.assertIn("--mock-image DIGEST", source)
        self.assertIn("s3api put-object", bootstrap)
        self.assertIn("ssm send-command", bootstrap)
        self.assertNotIn("git clone", user_data)
        self.assertNotIn("docker pull", user_data)
        self.assertNotIn("source_repository_url", LOAD_RUNNER_TERRAFORM.read_text(encoding="utf-8"))

    def test_eks_runner_readiness_is_verified_on_remote_runner_over_ssm(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("validate_runner_bootstrap_readiness_remote", source)
        self.assertIn('ssm send-command --instance-ids "$RUNNER_ID"', source)
        self.assertIn("__SCRUM80_RUNNER_READINESS_BEGIN__", source)
        self.assertIn("/var/lib/travel-planner/load-test-evidence/base-ready.json", source)
        self.assertIn('f"for _ in $(seq 1 60);', source)
        self.assertIn("<<'PY'\\n", source)
        self.assertIn("local node_group_adapter_args=(\n", source)
        self.assertIn("validate_runner_base_url_remote", source)
        self.assertIn("runner-base-url-verification.json", source)
        self.assertIn("AWS_TARGET_HOST_IPS", source)
        self.assertIn("--connect-to", source)
        self.assertNotIn('[[ -s "$base_receipt" ]]', source)
        self.assertIn('base.get("status") != "base-ready" or base.get("dockerActive") is not True', source)

    def test_runner_dispatched_orchestrator_uses_local_receipts_without_self_ssm(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('if [[ "${RUNNER_EXECUTION:-0}" == "1" ]]', source)
        self.assertIn('"execution": "runner-local"', source)
        self.assertIn('ssmStatus": "local-runner"', source)

    def test_target_resume_digest_does_not_bind_to_runtime_target_group_arn(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('target_group_digest = "" if stage == "target" else target_group_arn', source)
        self.assertIn('"targetGroupArnHash": hashlib.sha256(target_group_digest.encode()).hexdigest()', source)

    def test_resumed_eks_stages_restore_target_group_from_sealed_target_evidence(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn(
            'TARGET_GROUP_ARN="$(python3 - "$EVIDENCE_ROOT/aws/eks-alb-target-health.json"',
            source,
        )
        self.assertIn(
            'payload.get("targetGroupArn", "")',
            source,
        )

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
        self.assertIn("--target-platform PLATFORM", result.stdout)
        self.assertIn("--eks-bastion-id INSTANCE_ID", result.stdout)
        self.assertIn("--runner-instance-type TYPE", result.stdout)
        self.assertIn("d005-record", result.stdout)
        self.assertIn("Default: 80", result.stdout)

    def test_eks_target_dry_run_uses_explicit_adapter_and_writes_sanitized_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = {**os.environ, "B01_EVIDENCE_BASE": directory}
            result = subprocess.run(
                [
                    "bash", str(SCRIPT), "target", "--dry-run",
                    "--target-platform", "eks",
                    "--region", "ap-northeast-2", "--environment", "dev",
                    "--expected-account-id", "111111111111",
                    "--alb-arn", "arn:aws:elasticloadbalancing:ap-northeast-2:111111111111:loadbalancer/app/example/1234567890abcdef",
                    "--base-url", "https://b01.example.com",
                    "--runner-id", "i-0123456789abcdef0",
                    "--eks-bastion-id", "i-0fedcba9876543210",
                    "--max-rate", "30", "--max-vus", "100",
                    "--run-id", "aws-b01-eks-adapter-test", "--profile", str(PROFILE),
                ],
                cwd=REPOSITORY_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = Path(directory) / "aws-b01-eks-adapter-test" / "aws"
            self.assertEqual(json.loads((evidence / "eks-evidence.json").read_text())['platform'], "eks")
            self.assertFalse(json.loads((evidence / "eks-kubectl-invocation.json").read_text()).get("rawOutputStored"))

    def test_eks_adapter_does_not_derive_backend_asg_from_alb_targets(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        start = source.index("eks_target_stage()")
        end = source.index("\ntarget_stage()", start)
        eks_source = source[start:end]
        self.assertIn("describe-nodegroup", eks_source)
        self.assertIn("eks_target_adapter.py", eks_source)
        self.assertNotIn("describe-auto-scaling-instances", eks_source)
        self.assertIn("EKS ALB targets Pod IPs", eks_source)

    def test_eks_capacity_path_wires_observer_coordinator_and_evaluator(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("capacity_stress_stage()", source)
        self.assertIn("observe-aws-capacity-stress.py", source)
        self.assertIn("coordinate-aws-capacity-stress.py", source)
        self.assertIn("evaluate-aws-capacity-stress.py", source)
        self.assertIn("--eks-evidence-file", source)
        self.assertIn('phase" == "capacity-stress" && "$TARGET_PLATFORM" == "eks"', source)

    def test_adaptive_capacity_delegate_exports_reviewed_profile_path(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        start = source.index("adaptive_capacity_stress_stage()")
        end = source.index("\ncapacity_stress_stage()", start)
        helper = source[start:end]
        self.assertIn('export RUN_ID AWS_PROFILE_FILE="$PROFILE"', helper)

    def test_eks_campaign_has_separate_baseline_pod_node_and_recovery_paths(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        for stage in ("eks-baseline", "pod-scale-out", "node-scale-out-breakpoint", "recovery"):
            self.assertIn(stage, source)
        phase_source = AWS_PHASE_RUNNER.read_text(encoding="utf-8")
        self.assertIn("TARGET_PLATFORM\" == \"eks\"", phase_source)
        self.assertIn("observe-aws-capacity-stress.py", phase_source)
        self.assertIn('CAPACITY_STAGE="$PHASE"', phase_source)

    def test_recovery_target_allows_observed_ca_desired_without_relaxing_bounds(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        start = source.index("eks_target_stage()")
        end = source.index("\ntarget_stage()", start)
        eks_source = source[start:end]
        self.assertIn('if [[ "$MODE" == "recovery" ]]', eks_source)
        self.assertIn("--allow-current-desired", eks_source)
        self.assertIn('shape.get("min") == 2 and shape.get("max") == 4', (REPOSITORY_ROOT / "scripts/loadtest/aws/eks_target_adapter.py").read_text(encoding="utf-8"))

    def test_adaptive_eks_lifecycle_binds_mock_hpa_and_restores_both(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        for helper in (
            "run_eks_bastion_command",
            "apply_eks_google_mock_binding",
            "apply_eks_run_scoped_hpa",
            "restore_eks_canonical_hpa",
            "restore_eks_google_api_binding",
            "__SCRUM80_HPA_APPLY_BEGIN__",
            "__SCRUM80_HPA_RESTORE_BEGIN__",
        ):
            self.assertIn(helper, source)
        self.assertIn("run_stage_once hpa-override apply_eks_run_scoped_hpa", source)
        self.assertIn("run_stage_once hpa-restore restore_eks_canonical_hpa", source)
        self.assertIn("run_stage_once mock-restore restore_eks_google_api_binding", source)
        self.assertIn("run_stage_once capacity-stress k6_phase_stage capacity-stress", source)

    def test_eks_mock_binding_receipt_limits_ssm_stdout(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        start = source.index("apply_eks_google_mock_binding()")
        end = source.index("\napply_eks_run_scoped_hpa()", start)
        helper = source[start:end]
        self.assertIn("get configmap backend-config -o json | jq -c", helper)
        self.assertIn("get deployment {q(deployment)} -o json | jq -c", helper)
        self.assertIn("SSM RunShellScript stdout limit", helper)
        self.assertNotIn("get configmap backend-config -o json;", helper)
        self.assertNotIn("get deployment {q(deployment)} -o json;", helper)

    def test_mock_evidence_keeps_http_status_as_text(self) -> None:
        source = AWS_K6_RUNNER.read_text(encoding="utf-8")
        start = source.index('python3 - "$RUN_DIR/mock/evidence.json"')
        end = source.index("\nelse\n", start)
        helper = source[start:end]
        self.assertIn(
            "output, status, access_path, error_path, inspect_path, stats_path = sys.argv[1:]",
            helper,
        )
        self.assertNotIn(
            "output, status, access_path, error_path, inspect_path, stats_path = map(Path, sys.argv[1:])",
            helper,
        )

    def test_eks_breakpoint_profile_is_referenced_by_the_runner_contract(self) -> None:
        profile = REPOSITORY_ROOT / "load-tests/aws/profiles/eks-monolith-breakpoint-v1.0.json"
        self.assertTrue(profile.is_file())
        runner_source = AWS_K6_RUNNER.read_text(encoding="utf-8")
        self.assertIn("aws-eks-monolith-breakpoint-v1.0", runner_source)
        self.assertIn("eks-scale-capacity.js", runner_source)

    def test_eks_breakpoint_profile_defaults_to_its_t3_small_contract(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("BREAKPOINT_PROFILE=1", source)
        self.assertIn("eks-monolith-breakpoint-slo-v1.0.json", source)
        self.assertIn("historical t3.medium contract is not valid here", source)

    def test_eks_v21_adaptive_profile_does_not_require_finite_rate_ceiling(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        profile = REPOSITORY_ROOT / "load-tests/aws/profiles/eks-monolith-breakpoint-v2.1.json"
        slo = REPOSITORY_ROOT / "load-tests/aws/contracts/eks-monolith-breakpoint-slo-v2.1.json"
        self.assertIn("eks-monolith-breakpoint-v2.1.json", source)
        self.assertIn("eks-monolith-breakpoint-slo-v2.1.json", source)
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    "bash", str(SCRIPT), "target", "--dry-run",
                    "--target-platform", "eks",
                    "--region", "ap-northeast-2", "--environment", "dev-eks",
                    "--expected-account-id", "111111111111",
                    "--alb-arn", "arn:aws:elasticloadbalancing:ap-northeast-2:111111111111:loadbalancer/app/example/1234567890abcdef",
                    "--base-url", "https://b01.example.com",
                    "--runner-id", "i-0123456789abcdef0",
                    "--eks-bastion-id", "i-0fedcba9876543210",
                    "--max-vus", "16384",
                    "--run-id", "aws-b01-eks-v21-adaptive-test",
                    "--profile", str(profile),
                    "--slo-contract", str(slo),
                ],
                cwd=REPOSITORY_ROOT,
                env={**os.environ, "B01_EVIDENCE_BASE": directory},
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("--max_rate is required", result.stderr)

    def test_msa_v11_capacity_path_continues_after_balanced_rates(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        runner_source = AWS_K6_RUNNER.read_text(encoding="utf-8")
        scenario_source = (K6_ROOT / "aws/scenarios/eks-scale-capacity.js").read_text(encoding="utf-8")
        self.assertIn("eks-monolith-msa-boundary-v1.1.json", source)
        self.assertIn('if [[ "$campaign_stage" == "capacity-stress" ]]', source)
        self.assertIn("target_rate=$((target_rate * 2))", source)
        self.assertNotIn("BOUNDARY_SCHEDULE_COMPLETE", source)
        self.assertIn('aws-eks-monolith-msa-boundary-v1.1', runner_source)
        self.assertIn("aws-eks-monolith-msa-boundary-v1.1", scenario_source)

    def test_shared_k6_profile_gets_action_time_platform_environment(self) -> None:
        runner_source = AWS_PHASE_RUNNER.parent.joinpath("run-k6-aws-scenario.sh").read_text(encoding="utf-8")
        orchestrator_source = SCRIPT.read_text(encoding="utf-8")
        config_source = (K6_ROOT / "aws/config.js").read_text(encoding="utf-8")
        self.assertIn('TARGET_PLATFORM="$TARGET_PLATFORM"', runner_source)
        self.assertIn('TARGET_ENVIRONMENT="$ENVIRONMENT"', runner_source)
        self.assertIn(
            "export REPOSITORY_ROOT EVIDENCE_ROOT BASE_URL REGION ENVIRONMENT TARGET_PLATFORM MAX_RATE",
            orchestrator_source,
        )
        self.assertIn('seed_credentials "$fixture_id" 1', orchestrator_source)
        self.assertIn("__ENV.TARGET_ENVIRONMENT || PROFILE.environment", config_source)
        self.assertIn("__ENV.TARGET_REGION || PROFILE.region", config_source)

    def test_eks_k6_slo_producer_uses_non_interactive_safe_shutdown(self) -> None:
        runner_source = AWS_PHASE_RUNNER.parent.joinpath("run-k6-aws-scenario.sh").read_text(encoding="utf-8")
        self.assertIn('kill -TERM "$slo_producer_pid"', runner_source)
        self.assertIn('"$slo_producer_status" -eq 143', runner_source)

    def test_eks_baseline_creates_phase_directory_before_observer_redirect(self) -> None:
        phase_source = AWS_PHASE_RUNNER.read_text(encoding="utf-8")
        self.assertIn('mkdir -p "$run_dir"', phase_source)
        self.assertLess(phase_source.index('mkdir -p "$run_dir"'), phase_source.index('> "$run_dir/observer.log"'))

    def test_k6_runner_keeps_custom_host_and_allows_operator_ip_resolution(self) -> None:
        runner_source = AWS_PHASE_RUNNER.parent.joinpath("run-k6-aws-scenario.sh").read_text(encoding="utf-8")
        self.assertIn("AWS_TARGET_HOST_IPS", runner_source)
        self.assertIn("DOCKER_HOST_ARGS+=(--add-host", runner_source)
        self.assertIn('"method": "docker-add-host"', runner_source)
        self.assertIn(
            'AWS_PROFILE_FILE="$(cd "$(dirname "$AWS_PROFILE_FILE")" && pwd -P)/$(basename "$AWS_PROFILE_FILE")"',
            runner_source,
        )
        self.assertNotIn("amazonaws.com", runner_source)

    def test_d005_and_spike_are_fail_closed_on_baseline_candidate(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("require_baseline_candidate_gate", source)
        self.assertIn("require_d005_record_gate", source)
        self.assertIn("baseline-candidate.json is missing", source)
        self.assertIn("Baseline x3 gate has not passed; refusing D-005/Spike", source)
        self.assertIn("validate-aws-run.py", source)
        self.assertIn("--baseline-candidate-only", source)
        self.assertIn("baselineCandidateSha256", source)
        self.assertIn("sourceCommitSha", source)
        self.assertIn("profileSha256", source)
        self.assertIn("profile digest does not match this run", source)
        self.assertIn("inputDigestContractPassed", source)
        self.assertIn('"sourceCommitSha": source_commit_sha', source)

    def test_spike_peak_is_bounded_by_profile_and_operator_limits(self) -> None:
        phase_source = AWS_PHASE_RUNNER.read_text(encoding="utf-8")
        spike_source = (K6_ROOT / "aws/scenarios/b01-spike.js").read_text(encoding="utf-8")
        self.assertIn("spike peak rate", phase_source)
        self.assertIn("profile limits.maxRate", phase_source)
        self.assertIn("RATE < REQUESTED_PEAK_RATE", spike_source)
        self.assertIn("REQUESTED_PEAK_RATE > LIMITS.maxRate", spike_source)
        self.assertIn("operator --max-rate", phase_source)

    def test_spike_rejects_peak_above_profile_before_starting_k6(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = {
                "REPOSITORY_ROOT": str(REPOSITORY_ROOT),
                "EVIDENCE_ROOT": directory,
                "BASE_URL": "https://b01.example.com",
                "K6_IMAGE_DIGEST": "grafana/k6:0.54.0@sha256:" + "a" * 64,
                "RUN_ID": "aws-b01-spike-gate-test",
                "AWS_PROFILE_FILE": str(PROFILE),
                "REGION": "ap-northeast-2",
                "ENVIRONMENT": "dev",
                "MAX_RATE": "30",
                "MAX_VUS": "100",
                "EFFECTIVE_MAX_VUS": "80",
                "CONFIRMED_RATE": "20",
                "DATA_FILE": str(Path(directory) / "missing-data.json"),
            }
            result = subprocess.run(
                ["bash", str(AWS_PHASE_RUNNER), "spike"],
                cwd=REPOSITORY_ROOT,
                env={**os.environ, **environment},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exceeds profile limits.maxRate", result.stderr)

    def test_phase_credential_refresh_and_profile_vu_defaults_are_preserved(self) -> None:
        orchestrator_source = SCRIPT.read_text(encoding="utf-8")
        phase_runner_source = AWS_PHASE_RUNNER.read_text(encoding="utf-8")

        self.assertIn("USERS=80", orchestrator_source)
        self.assertIn('seed_credentials "seed"', orchestrator_source)
        self.assertIn('--reset-fixture --fixture-id "$fixture_id"', orchestrator_source)
        self.assertIn('--fixture-result-file "$FIXTURES_DIR/$fixture_id.json"', orchestrator_source)
        self.assertIn('validate_phase_credential_capacity "$phase"', orchestrator_source)
        self.assertIn('configure_phase_max_vus ramp "${RAMP_MAX_VUS:-}"', phase_runner_source)
        self.assertIn('configure_phase_max_vus baseline "${BASELINE_MAX_VUS:-}"', phase_runner_source)
        self.assertIn('configure_phase_max_vus spike "${SPIKE_MAX_VUS:-}"', phase_runner_source)
        self.assertIn('profile limits.maxVUs', phase_runner_source)
        self.assertNotIn('${RAMP_MAX_VUS:-$MAX_VUS}', phase_runner_source)
        self.assertNotIn('${BASELINE_MAX_VUS:-$MAX_VUS}', phase_runner_source)
        self.assertNotIn('${SPIKE_MAX_VUS:-$MAX_VUS}', phase_runner_source)

    def test_ramp_rejects_operator_ceiling_below_profile_default(self) -> None:
        result = subprocess.run(
            [
                "bash", str(SCRIPT), "ramp", "--dry-run",
                "--region", "ap-northeast-2", "--environment", "dev",
                "--expected-account-id", "111111111111",
                "--alb-arn", "arn:aws:elasticloadbalancing:ap-northeast-2:111111111111:loadbalancer/app/example/1234567890abcdef",
                "--base-url", "https://b01.example.com",
                "--runner-id", "i-0123456789abcdef0",
                "--max-rate", "30", "--max-vus", "20",
                "--run-id", "aws-b01-capacity-test", "--profile", str(PROFILE),
            ],
            cwd=REPOSITORY_ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("exceeds operator --max-vus ceiling", result.stderr)

    def test_ramp_rejects_seed_count_below_effective_max_vus(self) -> None:
        result = subprocess.run(
            [
                "bash", str(SCRIPT), "ramp", "--dry-run",
                "--region", "ap-northeast-2", "--environment", "dev",
                "--expected-account-id", "111111111111",
                "--alb-arn", "arn:aws:elasticloadbalancing:ap-northeast-2:111111111111:loadbalancer/app/example/1234567890abcdef",
                "--base-url", "https://b01.example.com",
                "--runner-id", "i-0123456789abcdef0",
                "--max-rate", "30", "--max-vus", "100", "--users", "59",
                "--run-id", "aws-b01-capacity-test", "--profile", str(PROFILE),
            ],
            cwd=REPOSITORY_ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("AWS VUs may not share refresh credentials", result.stderr)

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
        self.assertIn('"fixtureResultPath": f"fixtures/{stage}.json"', source)
        self.assertIn('"fixtureExpectedUsers": int(users_raw)', source)
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
            self.assertEqual(marker["fixtureId"], "smoke")
            self.assertEqual(marker["fixtureResultPath"], "fixtures/smoke.json")
            self.assertEqual(marker["fixtureExpectedUsers"], 20)
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



class EvidenceIsolationTests(unittest.TestCase):
    def test_orchestrators_support_isolated_evidence_bases(self) -> None:
        b01_source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('EVIDENCE_BASE="${B01_EVIDENCE_BASE:-$REPOSITORY_ROOT/evidence/aws-load-tests}"', b01_source)
        recovery_source = (
            REPOSITORY_ROOT / "scripts/loadtest/aws/orchestrate-aws-recovery.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('${AWS_RECOVERY_EVIDENCE_BASE:-$REPOSITORY_ROOT/evidence/aws-recovery}', recovery_source)

    def test_writing_invocation_lands_in_isolated_base_not_repository(self) -> None:
        run_id = "aws-b01-isolation-check"
        repository_run = REPOSITORY_ROOT / "evidence/aws-load-tests" / run_id
        self.assertFalse(repository_run.exists())
        with tempfile.TemporaryDirectory(prefix="b01-isolation-") as isolated:
            env = {**os.environ, "B01_EVIDENCE_BASE": isolated}
            result = subprocess.run(
                [
                    "bash", str(SCRIPT), "ramp", "--dry-run",
                    "--region", "ap-northeast-2", "--environment", "dev",
                    "--expected-account-id", "111111111111",
                    "--alb-arn", "arn:aws:elasticloadbalancing:ap-northeast-2:111111111111:loadbalancer/app/example/1234567890abcdef",
                    "--base-url", "https://b01.example.com",
                    "--runner-id", "i-0123456789abcdef0",
                    "--max-rate", "30", "--max-vus", "20",
                    "--run-id", run_id, "--profile", str(PROFILE),
                ],
                cwd=REPOSITORY_ROOT, capture_output=True, text=True, check=False, env=env,
            )
            self.assertEqual(result.returncode, 1)
            self.assertFalse(repository_run.exists())
            isolated_run = Path(isolated) / run_id
            if not isolated_run.exists():
                self.skipTest("this invocation exited before writing evidence; repository stayed clean")
            self.assertTrue((isolated_run / "operations.jsonl").exists() or any(isolated_run.iterdir()))


if __name__ == "__main__":
    unittest.main()
