"""Static contracts for the canonical dev-eks metrics-only monitoring overlay."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "k8s" / "base" / "monitoring"
OVERLAY = ROOT / "k8s" / "overlays" / "dev-eks"
PLATFORM = OVERLAY / "platform"
WORKLOAD = OVERLAY / "workload"
ALLOY_CONFIG = ROOT / "monitoring" / "alloy" / "config.eks.alloy"
TERRAFORM_ROOT = ROOT / "infra" / "environments" / "dev-eks" / "main.tf"


def render(path: Path) -> list[dict]:
    result = subprocess.run(
        ["kubectl", "kustomize", str(path)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [item for item in yaml.safe_load_all(result.stdout) if item]


def object_key(item: dict) -> tuple[str, str, str]:
    metadata = item["metadata"]
    return (
        item["kind"],
        metadata.get("namespace", "-"),
        metadata["name"],
    )


class EksMonitoringManifestContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = render(BASE)
        cls.overlay = render(OVERLAY)
        cls.platform = render(PLATFORM)
        cls.workload = render(WORKLOAD)
        cls.base_by_key = {object_key(item): item for item in cls.base}
        cls.overlay_by_key = {object_key(item): item for item in cls.overlay}
        cls.daemonset = cls.base_by_key[("DaemonSet", "travel-planner-monitoring", "alloy")]
        cls.configmap = cls.base_by_key[("ConfigMap", "travel-planner-monitoring", "alloy-config")]
        cls.config = cls.configmap["data"]["config.alloy"]

    def test_overlay_contains_each_runtime_component_once(self) -> None:
        keys = [object_key(item) for item in self.overlay]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertIn(("Deployment", "travel-planner", "backend"), keys)
        self.assertIn(("DaemonSet", "travel-planner-monitoring", "alloy"), keys)
        self.assertIn(("Deployment", "travel-planner-monitoring", "kube-state-metrics"), keys)
        self.assertEqual(sum(key == ("ServiceAccount", "travel-planner", "backend") for key in keys), 1)
        self.assertEqual(sum(key == ("ConfigMap", "travel-planner", "backend-config") for key in keys), 1)

    def test_staged_roots_have_disjoint_runtime_ownership(self) -> None:
        platform_keys = {object_key(item) for item in self.platform}
        workload_keys = {object_key(item) for item in self.workload}
        self.assertTrue(platform_keys)
        self.assertTrue(workload_keys)
        self.assertTrue(platform_keys.isdisjoint(workload_keys))
        self.assertIn(("Deployment", "kube-system", "aws-load-balancer-controller"), platform_keys)
        self.assertIn(("Deployment", "travel-planner", "backend"), workload_keys)

    def test_alloy_is_metrics_only_and_uses_private_remote_write_dns(self) -> None:
        for required in (
            "prometheus.remote_write",
            "prometheus.scrape",
            "discovery.kubernetes",
            "kube-state-metrics.travel-planner-monitoring.svc.cluster.local:8080",
            "monitoring.dev-eks.kdt-travelplanner.internal:9090/api/v1/write",
        ):
            self.assertIn(required, self.config)
        for forbidden in (
            "loki.",
            "LOKI_PUSH_URL",
            "/var/log/pods",
            "stage.cri",
            "sys.env",
            "PROMETHEUS_REMOTE_WRITE_URL",
        ):
            self.assertNotIn(forbidden, self.config)

    def test_alloy_daemonset_has_no_pod_filesystem_or_aws_identity(self) -> None:
        pod = self.daemonset["spec"]["template"]
        serialized = str(pod)
        self.assertNotIn("hostPath", serialized)
        self.assertNotIn("/var/log/pods", serialized)
        self.assertNotIn("LOKI_PUSH_URL", serialized)
        self.assertNotIn("serviceAccountToken", serialized)
        self.assertNotIn("automountServiceAccountToken: true", serialized)
        self.assertEqual(pod["spec"]["containers"][0].get("env", []), [])
        volumes = {item["name"]: item for item in pod["spec"]["volumes"]}
        self.assertEqual(volumes["alloy-data"]["emptyDir"]["sizeLimit"], "256Mi")
        self.assertEqual(volumes["alloy-tmp"]["emptyDir"]["sizeLimit"], "128Mi")
        self.assertIn({"name": "alloy-tmp", "mountPath": "/tmp"}, pod["spec"]["containers"][0]["volumeMounts"])
        self.assertIn({"name": "alloy-data", "mountPath": "/var/lib/alloy"}, pod["spec"]["containers"][0]["volumeMounts"])
        self.assertEqual(pod["spec"]["securityContext"]["fsGroupChangePolicy"], "Always")
        self.assertTrue(pod["spec"]["containers"][0]["securityContext"]["readOnlyRootFilesystem"])

    def test_rbac_is_read_only_and_forbids_log_access(self) -> None:
        for item in self.base:
            if item["kind"] != "ClusterRole":
                continue
            for rule in item.get("rules", []):
                self.assertEqual(set(rule["verbs"]), {"get", "list", "watch"})
                self.assertNotIn("pods/log", rule.get("resources", []))

    def test_images_are_pinned_and_config_source_matches_repository_file(self) -> None:
        for item in self.base:
            for container in item.get("spec", {}).get("template", {}).get("spec", {}).get("containers", []):
                self.assertIn("@sha256:", container["image"])
                self.assertNotIn(":latest", container["image"])
        ksm = self.base_by_key[("Deployment", "travel-planner-monitoring", "kube-state-metrics")]
        ksm_image = ksm["spec"]["template"]["spec"]["containers"][0]["image"]
        self.assertEqual(
            ksm_image,
            "registry.k8s.io/kube-state-metrics/kube-state-metrics:v2.19.1@sha256:85108987d044b18a098126732f98602df408888c0f7d456241f5abefb9744bc1",
        )
        source = ALLOY_CONFIG.read_text(encoding="utf-8").strip()
        self.assertEqual(self.config.strip(), source)

    def test_terraform_upload_is_source_snapshot_not_legacy_endpoint_bundle(self) -> None:
        terraform = TERRAFORM_ROOT.read_text(encoding="utf-8")
        self.assertIn('fileset(local.kustomize_root, "base/**")', terraform)
        self.assertIn('fileset(local.kustomize_root, "overlays/dev-eks/**")', terraform)
        self.assertIn('monitoring_bundle_manifest', terraform)
        self.assertIn('"run-dev-eks-deployment.sh"', terraform)
        self.assertIn('"render-action-time.py"', terraform)
        self.assertNotIn("monitoring-endpoint-configmap.yaml\" = templatefile", terraform)
        self.assertNotIn("LOKI_PUSH_URL", terraform)


if __name__ == "__main__":
    unittest.main()
