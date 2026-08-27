import os
import subprocess
import hashlib
import json
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).parents[2]
RUNNER = ROOT / "scripts/loadtest/aws/run-k6-aws-recovery.sh"
ENTRYPOINT = ROOT / "scripts/loadtest/aws/run-aws-recovery-workload.sh"
ORCHESTRATOR = ROOT / "scripts/loadtest/aws/orchestrate-aws-recovery.sh"


class AwsRecoveryRunnerContractTest(unittest.TestCase):
    def test_runner_shell_syntax_and_no_literal_escape(self):
        subprocess.run(["bash", "-n", str(RUNNER)], check=True)
        source = RUNNER.read_text(encoding="utf-8")
        self.assertNotRegex(source, r"\\\$[A-Za-z#{(]")

    def test_runner_preserves_preflight_metadata_and_records_profile_digest(self):
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("metadata = {}", source)
        self.assertIn("if output_path.exists()", source)
        self.assertIn("metadata.update({", source)
        self.assertIn('"profileSha256": hashlib.sha256(Path(profile_path).read_bytes()).hexdigest()', source)

    def test_runner_supports_operator_pinned_custom_origin_resolution(self):
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("AWS_TARGET_HOST_IPS", source)
        self.assertIn("DOCKER_HOST_ARGS+=(--add-host", source)
        self.assertIn('"method": "docker-add-host"', source)

    def test_planned_entrypoint_delegates_to_k6_runner(self):
        source = ENTRYPOINT.read_text(encoding="utf-8")
        self.assertIn("run-k6-aws-recovery.sh", source)
        self.assertIn("run-aws-recovery-workload.sh", ORCHESTRATOR.read_text(encoding="utf-8"))

    def test_runner_has_required_evidence_outputs_and_no_intervention(self):
        source = RUNNER.read_text(encoding="utf-8")
        for output in ("metadata.json", "raw.json", "summary.json", "k6-native-summary.json", "run-status.json", "runner-stats.jsonl"):
            self.assertIn(output, source)
        self.assertIn('metadata["endedAtUtc"]', source)
        self.assertIn('"event": "RUN_START"', source)
        self.assertIn("RUN_END", source)
        self.assertNotRegex(source, r"(terminate-instances|start-instance-refresh|terraform\\s+destroy)")

    def test_orchestrator_has_dry_run_and_no_overwrite_guards(self):
        source = ORCHESTRATOR.read_text(encoding="utf-8")
        self.assertIn('[dry-run] would run AWS Recovery workload', source)
        self.assertIn('if [[ "$MODE" == "run" ]]', source)
        self.assertIn('refusing to reuse Recovery run with existing output', source)
        self.assertIn('--launch-template-id', source)
        self.assertIn('--launch-template-version', source)
        self.assertIn('LaunchTemplateId', source)
        self.assertIn('launch_template.get("Version")', source)
        self.assertIn('D-005 profileSha256 does not match --b01-profile', source)
        self.assertIn('D-005 baselineCandidateSha256 does not match --baseline-candidate', source)
        self.assertIn('D-006 freeze runId does not match D-005 runId', source)

    def test_orchestrator_requires_strict_recovery_inputs_before_live_run(self):
        source = ORCHESTRATOR.read_text(encoding="utf-8")
        self.assertIn('python3 - "$D005_RATE_FILE" "$FREEZE_METADATA" "$B01_PROFILE"', source)
        self.assertIn('if [[ "$DRY_RUN" == "1" ]]; then', source)
        self.assertIn('would run AWS Recovery workload', source)

    def test_coordinator_detaches_background_workload_stdin(self):
        source = (ROOT / "scripts/loadtest/aws/coordinate-aws-recovery.py").read_text(encoding="utf-8")
        self.assertIn("systemd-run --unit=", source)
        self.assertIn("--collect --no-block", source)
        self.assertIn("echo started:", source)

    def test_v11_orchestrator_accepts_ec2_and_eks_action_time_targets(self):
        source_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        profile = ROOT / "load-tests/aws/profiles/ec2-eks-recovery-v1.1.json"
        target_group = (
            "arn:aws:elasticloadbalancing:ap-northeast-2:419496180357:"
            "targetgroup/fixture/0123456789abcdef"
        )
        alb = (
            "arn:aws:elasticloadbalancing:ap-northeast-2:419496180357:"
            "loadbalancer/app/fixture/0123456789abcdef"
        )
        for platform, extra in (
            (
                "ec2",
                [
                    "--asg-name", "kdt-travelplanner-dev-backend",
                    "--launch-template-id", "lt-0123456789abcdef0",
                    "--launch-template-version", "1",
                ],
            ),
            (
                "eks",
                [
                    "--cluster-name", "kdt-travelplanner-dev-eks",
                    "--node-group-name", "kdt-travelplanner-dev-eks-nodes",
                    "--eks-bastion-id", "i-0fedcba9876543210",
                ],
            ),
        ):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as directory:
                command = [
                    "bash", str(ORCHESTRATOR), "preflight", "--dry-run",
                    "--target-platform", platform,
                    "--run-id", f"scrum43-r03-{platform}-fixture",
                    "--profile", str(profile),
                    "--region", "ap-northeast-2",
                    "--environment", "dev-runtime" if platform == "ec2" else "dev-eks",
                    "--expected-account-id", "419496180357",
                    "--alb-arn", alb,
                    "--target-group-arn", target_group,
                    "--runner-id", "i-0123456789abcdef0",
                    "--base-url", "https://fixture.example.com",
                    "--rate", "4",
                    "--source-sha", source_sha,
                    *extra,
                ]
                environment = {**os.environ, "AWS_RECOVERY_EVIDENCE_BASE": directory}
                result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                metadata = json.loads(
                    (Path(directory) / f"scrum43-r03-{platform}-fixture" / "metadata.json").read_text()
                )
                self.assertEqual(metadata["platform"], platform)

    def test_operator_recovery_event_is_distinct_from_automated_t4(self):
        with tempfile.TemporaryDirectory() as directory:
            source_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
            run_id = "scrum43-r03-ec2-event-fixture"
            common = [
                "bash", str(ORCHESTRATOR),
                "--target-platform", "ec2",
                "--run-id", run_id,
                "--profile", str(ROOT / "load-tests/aws/profiles/ec2-eks-recovery-v1.1.json"),
                "--region", "ap-northeast-2",
                "--environment", "dev-runtime",
                "--expected-account-id", "419496180357",
                "--alb-arn", "arn:aws:elasticloadbalancing:ap-northeast-2:419496180357:loadbalancer/app/fixture/0123456789abcdef",
                "--target-group-arn", "arn:aws:elasticloadbalancing:ap-northeast-2:419496180357:targetgroup/fixture/0123456789abcdef",
                "--asg-name", "kdt-travelplanner-dev-backend",
                "--launch-template-id", "lt-0123456789abcdef0",
                "--launch-template-version", "1",
                "--runner-id", "i-0123456789abcdef0",
                "--base-url", "https://fixture.example.com",
                "--rate", "4",
                "--source-sha", source_sha,
            ]
            environment = {**os.environ, "AWS_RECOVERY_EVIDENCE_BASE": directory}
            preflight = subprocess.run(
                [*common, "preflight", "--dry-run"], cwd=ROOT, env=environment,
                capture_output=True, text=True,
            )
            self.assertEqual(preflight.returncode, 0, preflight.stderr)
            result = subprocess.run(
                [
                    *common, "event", "--event", "OPERATOR_RECOVERY", "--detail", "manual recovery completed",
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            event = json.loads(
                (Path(directory) / run_id / "operations.jsonl").read_text().splitlines()[0]
            )
            self.assertEqual(event["event"], "OPERATOR_RECOVERY")
            self.assertEqual(event["actor"], "operator")

    def test_preflight_evidence_is_idempotent_and_rejects_mismatch(self):
        run_id = f"aws-recovery-preflight-{uuid.uuid4().hex}"
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory)
            # Keep test writes out of the repository's protected evidence tree.
            evidence_base = fixture / "evidence-base"
            evidence_base.mkdir()
            environment = {**os.environ, "AWS_RECOVERY_EVIDENCE_BASE": str(evidence_base)}
            run_dir = evidence_base / run_id
            b01_profile = fixture / "b01-profile.json"
            candidate = fixture / "baseline-candidate.json"
            freeze = fixture / "freeze-metadata.json"
            d005 = fixture / "d005-rate.json"
            b01_profile.write_text('{"profileVersion":"fixture-b01"}\n', encoding="utf-8")
            candidate.write_text('{"candidate":"fixture"}\n', encoding="utf-8")
            b01_sha = hashlib.sha256(b01_profile.read_bytes()).hexdigest()
            candidate_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
            source_sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip()
            manifest_inputs = {
                "sourceCommitSha": source_sha,
                "b01ProfileSha256": b01_sha,
                "baselineCandidateSha256": candidate_sha,
                "d005RateRecordSha256": "c" * 64,
                "d005ArrivalRate": 1,
            }
            spike_effective = {
                "scenario": "spike",
                "classification": "diagnostic",
                "profileSha256": b01_sha,
                "baselineRate": 1.0,
                "peakRateMultiplier": 2.0,
                "peakRate": 2.0,
                "hold": "1m",
                "preAllocatedVUs": 1,
                "maxVUs": 2,
                "timeUnit": "1s",
            }
            spike_digest = hashlib.sha256(
                json.dumps(spike_effective, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            manifest_inputs["spikeEffectiveConfigSha256"] = spike_digest
            contract_path = ROOT / "load-tests/aws/contracts/slo-v1.0.json"
            manifest = {
                "schemaVersion": "aws-d006-freeze-input-manifest-v1",
                "runId": "aws-b01-preflight-fixture",
                "sloVersion": "v1.0-frozen",
                "contract": {
                    "path": "load-tests/aws/contracts/slo-v1.0.json",
                    "sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
                },
                "inputs": manifest_inputs,
                "spike": {
                    "classification": "diagnostic",
                    "effectiveConfigSha256": spike_digest,
                    "effectiveConfig": spike_effective,
                },
                "inputDigest": hashlib.sha256(
                    json.dumps(manifest_inputs, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
            }
            freeze_manifest = fixture / "freeze-input-manifest.json"
            freeze_manifest.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
            freeze.write_text(json.dumps({
                "runId": "aws-b01-preflight-fixture",
                "sloVersion": "v1.0-frozen",
                "approvedBy": "test",
                "freezeInputManifest": "freeze-input-manifest.json",
                "freezeInputDigest": manifest["inputDigest"],
                "sloContractSha256": manifest["contract"]["sha256"],
            }) + "\n", encoding="utf-8")
            d005.write_text(json.dumps({
                "runId": "aws-b01-preflight-fixture",
                "arrivalRate": 1,
                "sourceCommitSha": source_sha,
                "profileSha256": b01_sha,
                "baselineCandidateSha256": candidate_sha,
            }) + "\n", encoding="utf-8")
            common = [
                str(ORCHESTRATOR), "preflight", "--dry-run",
                "--run-id", run_id,
                "--profile", str(ROOT / "load-tests/aws/profiles/ec2-recovery.json"),
                "--region", "ap-northeast-2",
                "--environment", "dev-runtime",
                "--expected-account-id", "123456789012",
                "--alb-arn", "arn:aws:elasticloadbalancing:ap-northeast-2:123456789012:loadbalancer/app/fixture/abc",
                "--asg-name", "travel-planner-backend",
                "--launch-template-id", "lt-abc123",
                "--launch-template-version", "1",
                "--runner-id", "i-abc123",
                "--base-url", "https://approved.example.com",
                "--rate", "1",
                "--freeze-metadata", str(freeze),
                "--d005-rate-file", str(d005),
                "--b01-profile", str(b01_profile),
                "--baseline-candidate", str(candidate),
                "--source-sha", source_sha,
            ]
            try:
                first = subprocess.run(common, cwd=ROOT, capture_output=True, text=True, env=environment)
                self.assertEqual(first.returncode, 0, first.stderr)
                paths = [
                    run_dir / "metadata.json",
                    run_dir / "aws-alb.json",
                    run_dir / "aws-asg.json",
                    run_dir / "aws-target-health.json",
                ]
                before = {path: path.read_bytes() for path in paths}

                second = subprocess.run(common, cwd=ROOT, capture_output=True, text=True, env=environment)
                self.assertEqual(second.returncode, 0, second.stderr)
                self.assertEqual(before, {path: path.read_bytes() for path in paths})

                mismatch = list(common)
                mismatch[mismatch.index("--alb-arn") + 1] = (
                    "arn:aws:elasticloadbalancing:ap-northeast-2:123456789012:"
                    "loadbalancer/app/fixture/changed"
                )
                rejected = subprocess.run(mismatch, cwd=ROOT, capture_output=True, text=True, env=environment)
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn("immutable preflight metadata", rejected.stderr)
                self.assertEqual(before, {path: path.read_bytes() for path in paths})

                (run_dir / "aws-alb.json").write_text('{"tampered":true}\n', encoding="utf-8")
                tampered = subprocess.run(common, cwd=ROOT, capture_output=True, text=True, env=environment)
                self.assertNotEqual(tampered.returncode, 0)
                self.assertIn("immutable preflight evidence", tampered.stderr)
            finally:
                if run_dir.exists():
                    shutil.rmtree(run_dir)


if __name__ == "__main__":
    unittest.main()
