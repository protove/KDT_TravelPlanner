"""Unit tests for lease and delete-only destroy-plan validation."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/eks/verify-dev-eks-destroyed.py"
SPEC = importlib.util.spec_from_file_location("verify_dev_eks_destroyed", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def lease_for(state: Path, addresses: Path) -> dict:
    address_values = sorted(
        line
        for line in addresses.read_text(encoding="utf-8").splitlines()
        if line and not any(part == "data" for part in line.split("."))
    )
    return {
        "schema_version": "dev-eks-cleanup-lease/v1",
        "lifecycle_run_id": "20260824T153735Z-1",
        "issued_at": "2099-01-01T00:00:00Z",
        "expires_at": "2099-01-01T01:00:00Z",
        "expected_account_sha256": hashlib.sha256(b"123456789012").hexdigest(),
        "expected_region": "ap-northeast-2",
        "terraform_backend_key": "dev-eks/terraform.tfstate",
        "state_lineage": "lineage-1",
        "state_serial": 4,
        "state_sha256": hashlib.sha256(state.read_bytes()).hexdigest(),
        "managed_address_sha256": hashlib.sha256(("\n".join(address_values) + "\n").encode()).hexdigest(),
        "managed_address_count": len(address_values),
        "cluster_name": "kdt-travelplanner-dev-eks",
        "helper_sha256": "a" * 64,
        "forbidden_actions": ["create", "update", "replace", "import", "state edit"],
    }


class DestroyVerifierTest(unittest.TestCase):
    def test_lease_and_exact_delete_only_plan_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state.json"
            addresses = root / "addresses.txt"
            state.write_text(json.dumps({"lineage": "lineage-1", "serial": 4, "resources": []}), encoding="utf-8")
            addresses.write_text("module.eks.aws_eks_cluster.this\nmodule.eks.aws_eks_node_group.this\ndata.terraform_remote_state.persistent\n", encoding="utf-8")
            lease = lease_for(state, addresses)
            managed, _ = MODULE.validate_lease(lease, state, addresses, "123456789012", "ap-northeast-2")
            self.assertEqual(managed, ["module.eks.aws_eks_cluster.this", "module.eks.aws_eks_node_group.this"])
            plan = {
                "resource_changes": [
                    {"mode": "managed", "address": address, "change": {"actions": ["delete"]}}
                    for address in managed
                ]
            }
            validation = MODULE.validate_destroy_plan(plan, managed)
            self.assertTrue(validation["delete_only"])
            self.assertEqual(validation["delete_address_count"], 2)

    def test_lease_tamper_and_foreign_plan_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state.json"
            addresses = root / "addresses.txt"
            state.write_text(json.dumps({"lineage": "lineage-1", "serial": 4, "resources": []}), encoding="utf-8")
            addresses.write_text("module.eks.aws_eks_cluster.this\n", encoding="utf-8")
            lease = lease_for(state, addresses)
            tampered = dict(lease, expected_region="us-east-1")
            with self.assertRaises(MODULE.VerificationError):
                MODULE.validate_lease(tampered, state, addresses, "123456789012", "ap-northeast-2")
            managed = ["module.eks.aws_eks_cluster.this"]
            foreign_plan = {
                "resource_changes": [
                    {"mode": "managed", "address": managed[0], "change": {"actions": ["delete", "create"]}}
                ]
            }
            with self.assertRaises(MODULE.VerificationError):
                MODULE.validate_destroy_plan(foreign_plan, managed)

    def test_expired_lease_cannot_be_replayed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state.json"
            addresses = root / "addresses.txt"
            state.write_text(json.dumps({"lineage": "lineage-1", "serial": 4, "resources": []}), encoding="utf-8")
            addresses.write_text("module.eks.aws_eks_cluster.this\n", encoding="utf-8")
            lease = lease_for(state, addresses)
            lease["issued_at"] = "2000-01-01T00:00:00Z"
            lease["expires_at"] = "2000-01-01T01:00:00Z"
            with self.assertRaises(MODULE.VerificationError):
                MODULE.validate_lease(lease, state, addresses, "123456789012", "ap-northeast-2")

    def test_native_inventory_distinguishes_not_found_from_access_denied(self) -> None:
        env = {"AWS_PROFILE": "offline", "AWS_REGION": "ap-northeast-2"}
        not_found = MODULE.subprocess.CompletedProcess(
            args=["aws"], returncode=254, stdout="", stderr="ResourceNotFoundException: not found"
        )
        with patch.object(MODULE.subprocess, "run", return_value=not_found):
            self.assertEqual(MODULE.aws_json(["eks", "describe-cluster"], env, allow={0, 254}), {"_not_found": True})

        denied = MODULE.subprocess.CompletedProcess(
            args=["aws"], returncode=254, stdout="", stderr="AccessDeniedException: denied"
        )
        with patch.object(MODULE.subprocess, "run", return_value=denied):
            with self.assertRaises(MODULE.VerificationError):
                MODULE.aws_json(["eks", "describe-cluster"], env, allow={0, 254})

    def test_missing_managed_delete_fails_closed(self) -> None:
        with self.assertRaises(MODULE.VerificationError):
            MODULE.validate_destroy_plan(
                {"resource_changes": [{"mode": "managed", "address": "module.eks.a", "change": {"actions": ["delete"]}}]},
                ["module.eks.a", "module.eks.b"],
            )

    def test_native_inventory_uses_state_nodegroup_names_not_list_nodegroups(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"describe-nodegroup"', source)
        self.assertIn('resource_values(state, "aws_eks_node_group")', source)
        self.assertNotIn('"list-nodegroups"', source)
        self.assertNotIn('"resourcegroupstaggingapi"', source)
        self.assertIn('"describe-tags"', source)


if __name__ == "__main__":
    unittest.main()
