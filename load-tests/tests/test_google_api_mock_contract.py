import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MOCK_ROOT = ROOT / "load-tests/mocks/google-api"


class GoogleApiMockContractTest(unittest.TestCase):
    def test_nginx_exposes_only_expected_private_routes(self):
        config = (MOCK_ROOT / "nginx.conf").read_text(encoding="utf-8")
        for path in (
            "/healthz",
            "/v1/places:searchText",
            "/v1/places:searchNearby",
            "/v1/places/",
            "/directions/v2:computeRoutes",
        ):
            self.assertIn(path, config)
        self.assertIn("listen 8080", config)
        self.assertNotIn("proxy_pass", config)
        self.assertNotIn("https://", config)

    def test_response_shapes_match_google_adapter_contracts(self):
        search = json.loads((MOCK_ROOT / "responses/places-search.json").read_text(encoding="utf-8"))
        nearby = json.loads((MOCK_ROOT / "responses/places-nearby.json").read_text(encoding="utf-8"))
        detail = json.loads((MOCK_ROOT / "responses/place-detail.json").read_text(encoding="utf-8"))
        routes = json.loads((MOCK_ROOT / "responses/routes-compute.json").read_text(encoding="utf-8"))
        for payload in (search, nearby):
            self.assertTrue(payload["places"])
            place = payload["places"][0]
            self.assertTrue(place["id"])
            self.assertTrue(place["displayName"]["text"])
            self.assertIn("latitude", place["location"])
            self.assertIn("longitude", place["location"])
        self.assertIn("latitude", detail["location"])
        self.assertIn("longitude", detail["location"])
        self.assertEqual(len(routes["routes"]), 1)
        self.assertEqual(len(routes["routes"][0]["legs"]), 2)
        self.assertTrue(routes["routes"][0]["polyline"]["encodedPolyline"])

    def test_mock_bootstrap_is_unprivileged_bounded_and_digest_pinned(self):
        template = (ROOT / "infra/modules/load_test_runner/templates/runner-user-data.sh.tftpl").read_text(encoding="utf-8")
        variables = (ROOT / "infra/modules/load_test_runner/variables.tf").read_text(encoding="utf-8")
        self.assertRegex(
            variables,
            r"nginxinc/nginx-unprivileged:[^\"\s]+@sha256:[0-9a-f]{64}",
        )
        self.assertIn("${google_mock_image_reference}", template)
        for flag in ("--read-only", "--cap-drop ALL", "--security-opt no-new-privileges", "--cpus 1", "--memory 256m", "--pids-limit 64", "--platform linux/amd64"):
            self.assertIn(flag, template)
        self.assertIn("/healthz", template)
        self.assertIn("--name travel-planner-google-api-mock", template)

    def test_mock_network_is_sg_referenced_and_not_public(self):
        security = (ROOT / "infra/modules/load_test_security/main.tf").read_text(encoding="utf-8")
        environment = (ROOT / "infra/environments/dev-load-test/main.tf").read_text(encoding="utf-8")
        self.assertIn("referenced_security_group_id = var.eks_cluster_security_group_id", security)
        self.assertRegex(security, r"from_port\s*=\s*8080")
        self.assertIn('type    = "A"', environment)
        self.assertIn('name    = "google-api-mock"', environment)
        self.assertNotIn("associate_public_ip_address = true", environment)

    def test_kustomize_mock_key_replaces_secret_reference(self):
        patch = (ROOT / "k8s/overlays/dev-eks/load-test/backend-google-api-mock.patch.yaml").read_text(encoding="utf-8")
        self.assertIn('GOOGLE_MAPS_API_KEY', patch)
        self.assertIn('value: "loadtest-google-mock-key"', patch)
        self.assertIn('valueFrom: null', patch)


if __name__ == "__main__":
    unittest.main()
