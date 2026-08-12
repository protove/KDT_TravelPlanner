import subprocess
import unittest
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


if __name__ == "__main__":
    unittest.main()
