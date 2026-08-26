"""Static contracts for the data-aware EKS Backend Kustomize base.

These tests intentionally do not contact AWS or a Kubernetes API. They render
the repository-owned base and inspect the action-time overlay patches so a
review can distinguish Git-owned wiring from user-supplied runtime values.
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "k8s" / "base" / "backend"
OVERLAY = ROOT / "k8s" / "overlays" / "dev-eks"
LOGGING_PROFILE_TEST = ROOT / "backend" / "src" / "test" / "kotlin" / "com" / "ktcloud" / "travelplanner" / "global" / "logging" / "LoggingProfileIntegrationTest.kt"


def documents(text: str) -> list[dict]:
    return [item for item in yaml.safe_load_all(text) if item]


def render_base() -> list[dict]:
    rendered = subprocess.run(
        ["kubectl", "kustomize", str(BASE)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return documents(rendered.stdout)


class EksBackendObservabilityContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base_documents = render_base()
        cls.by_kind_name = {
            (item["kind"], item["metadata"]["name"]): item
            for item in cls.base_documents
        }
        cls.deployment = cls.by_kind_name[("Deployment", "backend")]
        cls.sidecar_config = cls.by_kind_name[("ConfigMap", "backend-alloy-sidecar-config")]
        cls.overlay_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((OVERLAY / "workload").glob("backend-*.yaml"))
        )

    def test_base_inventory_and_annotation_free_pod_identity(self) -> None:
        self.assertIn(("Namespace", "travel-planner"), self.by_kind_name)
        service_account = self.by_kind_name[("ServiceAccount", "backend")]
        self.assertNotIn("annotations", service_account["metadata"])
        self.assertEqual(self.deployment["spec"]["template"]["spec"]["serviceAccountName"], "backend")

    def test_backend_uses_external_secret_keys_without_a_secret_manifest(self) -> None:
        containers = self.deployment["spec"]["template"]["spec"]["containers"]
        backend = next(item for item in containers if item["name"] == "backend")
        expected = {
            "SPRING_DATASOURCE_USERNAME",
            "SPRING_DATASOURCE_PASSWORD",
            "SPRING_DATA_REDIS_PASSWORD",
            "JWT_SECRET",
            "GOOGLE_OAUTH_CLIENT_ID",
            "GOOGLE_OAUTH_CLIENT_SECRET",
            "NAVER_OAUTH_CLIENT_ID",
            "NAVER_OAUTH_CLIENT_SECRET",
            "GOOGLE_MAPS_API_KEY",
        }
        refs = {
            item["name"]: item["valueFrom"]["secretKeyRef"]
            for item in backend["env"]
        }
        self.assertEqual(set(refs), expected)
        self.assertTrue(all(ref["name"] == "backend-secret" for ref in refs.values()))
        self.assertTrue(all(ref["key"] == name for name, ref in refs.items()))
        self.assertFalse(any(item.get("kind") == "Secret" for item in self.base_documents))
        self.assertNotIn("stringData:", self.overlay_text)

    def test_prod_data_and_profile_configuration_is_action_time_safe(self) -> None:
        config = self.by_kind_name[("ConfigMap", "backend-config")]["data"]
        self.assertEqual(config["SPRING_PROFILES_ACTIVE"], "prod")
        self.assertEqual(config["LOGGING_FILE_NAME"], "/var/log/travel-planner/travel-planner.log")
        self.assertEqual(config["SPRING_DATA_REDIS_SSL_ENABLED"], "true")
        self.assertEqual(config["PROFILE_IMAGE_STORAGE_ENABLED"], "true")
        self.assertIn("postgres.dev-eks.kdt-travelplanner.internal", self.overlay_text)
        self.assertIn("redis.dev-eks.kdt-travelplanner.internal", self.overlay_text)
        for sentinel in (
            "__ACTION_TIME_PROFILE_IMAGE_BUCKET__",
            "__ACTION_TIME_PROFILE_IMAGE_PUBLIC_BASE_URL__",
            "__ACTION_TIME_ECR_BACKEND_IMAGE_DIGEST__",
        ):
            self.assertIn(sentinel, self.overlay_text)
        self.assertNotIn("localhost", self.overlay_text)
        self.assertNotIn("@sha256:", self.overlay_text)

    def test_scrape_probe_resources_and_hardening_contract(self) -> None:
        pod = self.deployment["spec"]["template"]
        annotations = pod["metadata"]["annotations"]
        self.assertEqual(
            annotations,
            {
                "prometheus.io/scrape": "true",
                "prometheus.io/port": "9091",
                "prometheus.io/path": "/actuator/prometheus",
            },
        )
        self.assertEqual(pod["spec"]["securityContext"]["fsGroup"], 10001)
        self.assertEqual(pod["spec"]["securityContext"]["fsGroupChangePolicy"], "Always")
        containers = {item["name"]: item for item in pod["spec"]["containers"]}
        backend = containers["backend"]
        self.assertEqual(backend["readinessProbe"]["httpGet"]["path"], "/actuator/health/readiness")
        self.assertEqual(backend["livenessProbe"]["httpGet"]["path"], "/actuator/health/liveness")
        self.assertIn("requests", backend["resources"])
        self.assertIn("limits", backend["resources"])
        volumes = {item["name"]: item for item in pod["spec"]["volumes"]}
        self.assertEqual(volumes["application-logs"]["emptyDir"]["sizeLimit"], "1Gi")
        self.assertEqual(volumes["alloy-positions"]["emptyDir"]["sizeLimit"], "128Mi")
        self.assertEqual(volumes["alloy-tmp"]["emptyDir"]["sizeLimit"], "128Mi")
        self.assertNotIn("hostPath", str(pod))

    def test_sidecar_reads_ecs_json_file_read_only_and_uses_private_loki(self) -> None:
        pod = self.deployment["spec"]["template"]
        sidecar = next(item for item in pod["spec"]["containers"] if item["name"] == "alloy-sidecar")
        self.assertIn("@sha256:", sidecar["image"])
        self.assertIn({"name": "alloy-tmp", "mountPath": "/tmp"}, sidecar["volumeMounts"])
        self.assertIn({"name": "alloy-positions", "mountPath": "/var/lib/alloy"}, sidecar["volumeMounts"])
        self.assertTrue(
            any(
                mount["name"] == "application-logs"
                and mount.get("readOnly") is True
                and mount["mountPath"] == "/var/log/travel-planner"
                for mount in sidecar["volumeMounts"]
            )
        )
        config = self.sidecar_config["data"]["config.alloy"]
        self.assertIn("/var/log/travel-planner/travel-planner.log", config)
        self.assertIn("stage.json", config)
        self.assertIn("loki.source.file", config)
        self.assertIn("monitoring.dev-eks.kdt-travelplanner.internal:3100", config)
        self.assertIn('values = ["service", "environment", "level"]', config)
        self.assertNotIn("/var/log/pods", config)
        self.assertNotIn("sys.env", config)
        self.assertNotIn("prometheus.remote_write", config)

    def test_backend_logging_regression_test_remains_present(self) -> None:
        self.assertTrue(LOGGING_PROFILE_TEST.is_file())
        source = LOGGING_PROFILE_TEST.read_text(encoding="utf-8")
        self.assertIn("prod profile writes ECS JSON rolling file", source)
        self.assertIn("assertFalse(capturedOutput.out", source)
        self.assertIn("/var/log", (ROOT / "backend" / "src" / "main" / "resources" / "application-prod.yml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
