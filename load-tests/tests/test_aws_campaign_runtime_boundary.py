from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "scripts/loadtest/aws/run-scrum80-lifecycle.sh"
PROFILE = ROOT / "load-tests/aws/profiles/eks-monolith-msa-boundary-v1.1.json"


class AwsCampaignRuntimeBoundaryTest(unittest.TestCase):
    def make_context(self, path: Path, *, minutes: int = 60, policy: str | None = None) -> None:
        payload = {
            "runId": "scrum80-runtime-boundary-test",
            "deadlineUtc": (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "reserveMinutes": 10,
        }
        if policy:
            payload.update({"policy": policy, "deadlineUtc": None, "reserveMinutes": None})
        path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    def run_wrapper(self, context: Path, lock: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(WRAPPER), "--context", str(context), "--cleanup-lock", str(lock), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_lifecycle_wrapper_dry_run_then_lock_and_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = root / "context.json"
            lock = root / "scrum80-lifecycle.lock"
            self.make_context(context)

            dry_run = self.run_wrapper(context, lock, "--dry-run", "--", "true")
            self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
            self.assertFalse(lock.exists())
            self.assertEqual(json.loads(dry_run.stdout)["lockCreated"], False)

            run = self.run_wrapper(context, lock, "--", "bash", "-c", "exit 0")
            self.assertEqual(run.returncode, 0, run.stderr)
            metadata = json.loads((lock / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["status"], "succeeded")
            self.assertEqual(metadata["runId"], "scrum80-runtime-boundary-test")

            release = self.run_wrapper(context, lock, "--release-lock")
            self.assertEqual(release.returncode, 0, release.stderr)
            self.assertFalse(lock.exists())

    def test_expired_deadline_is_rejected_before_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = root / "context.json"
            lock = root / "scrum80-lifecycle.lock"
            self.make_context(context, minutes=1)
            payload = json.loads(context.read_text(encoding="utf-8"))
            payload["reserveMinutes"] = 2
            context.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            result = self.run_wrapper(context, lock, "--", "true")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("deadline/reserve", result.stderr)
            self.assertFalse(lock.exists())

    def test_terminal_and_closure_policy_allows_long_run_without_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = root / "context.json"
            lock = root / "scrum80-lifecycle.lock"
            self.make_context(context, policy="until-validated-terminal-and-closure")
            run = self.run_wrapper(context, lock, "--dry-run", "--", "true")
            self.assertEqual(run.returncode, 0, run.stderr)
            payload = json.loads(run.stdout)
            self.assertEqual(payload["policy"], "until-validated-terminal-and-closure")
            self.assertIsNone(payload["remainingSeconds"])
            self.assertIsNone(payload["deadlineUtc"])

            run = self.run_wrapper(context, lock, "--", "true")
            self.assertEqual(run.returncode, 0, run.stderr)
            metadata = json.loads((lock / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["policy"], "until-validated-terminal-and-closure")
            self.assertIsInstance(metadata["pid"], int)
            self.assertGreater(metadata["pid"], 0)
            release = self.run_wrapper(context, lock, "--release-lock")
            self.assertEqual(release.returncode, 0, release.stderr)

    def test_v11_profile_keeps_terminal_only_continuation_contract(self) -> None:
        profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        stress = profile["capacityStress"]
        self.assertIsNone(profile["limits"]["maxRate"])
        self.assertEqual(stress["continuation"]["firstRate"], 512)
        self.assertEqual(stress["continuation"]["nextRateExpression"], "R[n+1] = R[n] * 2")
        self.assertEqual(stress["continuation"]["stop"], "terminalConditions only")


if __name__ == "__main__":
    unittest.main()
