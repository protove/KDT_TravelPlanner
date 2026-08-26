"""Offline contracts for the exact in-place Bastion kubectl repair."""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "scripts" / "eks" / "repair-dev-eks-bastion.sh"
DEPLOYER = ROOT / "scripts" / "eks" / "deploy-dev-eks.sh"
COORDINATOR = ROOT / "scripts" / "eks" / "run-dev-eks-repair-and-resume.sh"


class BastionRepairContractTest(unittest.TestCase):
    def test_helper_is_executable_and_shell_clean(self) -> None:
        self.assertTrue(os.access(HELPER, os.X_OK))
        self.assertEqual(subprocess.run(["bash", "-n", str(HELPER)]).returncode, 0)

    def test_helper_is_pinned_and_never_runs_package_or_cleanup_workflow(self) -> None:
        source = HELPER.read_text(encoding="utf-8")
        self.assertIn('KUBECTL_VERSION" == "1.35.6"', source)
        self.assertIn("dl.k8s.io/release/v${KUBECTL_VERSION}", source)
        self.assertIn("sha256sum -c -", source)
        self.assertIn("kubectl --kubeconfig \"$KUBECONFIG_PATH\" get --raw=/version", source)
        self.assertIn("kubectl --kubeconfig \"$KUBECONFIG_PATH\" get nodes --no-headers", source)
        self.assertNotIn("dnf install", source)
        self.assertNotIn("terraform", source)
        self.assertNotIn("kubectl delete", source)
        self.assertNotIn("reboot", source)

    def test_failure_evidence_and_json_ssm_transport_are_present(self) -> None:
        deployer = DEPLOYER.read_text(encoding="utf-8")
        coordinator = COORDINATOR.read_text(encoding="utf-8")
        self.assertIn("persist_ssm_failure", deployer)
        self.assertIn('schema_version:"dev-eks-ssm-failure/v1"', deployer)
        self.assertIn("chmod 0600", deployer)
        self.assertIn("jq -cn --arg command", coordinator)
        self.assertIn("{commands:[$command]}", coordinator)
        self.assertIn("--document-name AWS-RunShellScript", coordinator)

    def test_work_directory_is_private_and_scoped(self) -> None:
        source = HELPER.read_text(encoding="utf-8")
        self.assertIn("/var/tmp/travel-planner-dev-eks-*/*", source)
        self.assertIn("chmod 0700", source)
        self.assertIn("rmdir \"$WORK_DIR/download\"", source)

    def test_traversal_and_symlink_work_directories_are_rejected_before_tools(self) -> None:
        base = [
            str(HELPER),
            "--kubectl-version", "1.35.6",
            "--cluster-name", "kdt-travelplanner-dev-eks",
            "--region", "ap-northeast-2",
            "--expected-account-id", "419496180357",
        ]
        for work_dir in ("/var/tmp/travel-planner-dev-eks-x/../escape", "/var/tmp/travel-planner-dev-eks-x//repair"):
            result = subprocess.run(base + ["--work-dir", work_dir], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("work directory", result.stderr)

        symlink = Path(f"/var/tmp/travel-planner-dev-eks-symlink-{os.getpid()}")
        try:
            try:
                symlink.symlink_to(Path("/private/tmp"), target_is_directory=True)
            except PermissionError:
                self.skipTest("sandbox does not permit creating a temporary /var/tmp symlink")
            result = subprocess.run(base + ["--work-dir", f"{symlink}/repair"], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symlink", result.stderr)
        finally:
            symlink.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
