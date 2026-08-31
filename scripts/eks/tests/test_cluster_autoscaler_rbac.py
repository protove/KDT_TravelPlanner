"""Focused least-privilege contract for the EKS 1.35 Cluster Autoscaler."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
RBAC = ROOT / "k8s/base/platform/cluster-autoscaler-clusterrole.yaml"


class ClusterAutoscalerRbacTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.role = yaml.safe_load(RBAC.read_text(encoding="utf-8"))

    def test_required_v135_reads_are_present_without_wildcards(self) -> None:
        rules = self.role["rules"]
        self.assertEqual(self.role["kind"], "ClusterRole")
        self.assertEqual(self.role["metadata"]["name"], "system:cluster-autoscaler")
        self.assertTrue(all("*" not in rule.get("apiGroups", []) for rule in rules))
        self.assertTrue(all("*" not in rule.get("resources", []) for rule in rules))
        self.assertTrue(all("*" not in rule.get("verbs", []) for rule in rules))

        def has(api_group: str, resource: str, verbs: set[str]) -> bool:
            return any(
                api_group in rule.get("apiGroups", [])
                and resource in rule.get("resources", [])
                and verbs <= set(rule.get("verbs", []))
                for rule in rules
            )

        for resource in ("nodes", "namespaces", "pods"):
            self.assertTrue(has("", resource, {"get", "list", "watch"}), resource)
        for resource in ("volumeattachments",):
            self.assertTrue(has("storage.k8s.io", resource, {"get", "list", "watch"}), resource)
        for resource in ("deviceclasses", "resourceslices", "resourceclaims"):
            self.assertTrue(has("resource.k8s.io", resource, {"get", "list", "watch"}), resource)

    def test_role_document_is_valid_kubernetes_yaml(self) -> None:
        self.assertEqual(self.role["apiVersion"], "rbac.authorization.k8s.io/v1")
        self.assertEqual(self.role["kind"], "ClusterRole")
        self.assertIn("system:cluster-autoscaler", self.role["metadata"]["name"])


if __name__ == "__main__":
    unittest.main()
