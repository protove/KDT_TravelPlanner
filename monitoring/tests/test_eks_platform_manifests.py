"""Static contracts for the EKS 1.35 metrics and autoscaling platform."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "k8s" / "overlays" / "dev-eks"
PLATFORM = OVERLAY / "platform"
TERRAFORM_ROOT = ROOT / "infra" / "environments" / "dev-eks" / "main.tf"


def render() -> list[dict]:
    result = subprocess.run(
        ["kubectl", "kustomize", str(OVERLAY)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [item for item in yaml.safe_load_all(result.stdout) if item]


def key(item: dict) -> tuple[str, str, str]:
    metadata = item["metadata"]
    return item["kind"], metadata.get("namespace", "-"), metadata["name"]


class EksPlatformManifestContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.items = render()
        cls.by_key = {key(item): item for item in cls.items}

    def test_platform_objects_are_unique_and_present(self) -> None:
        keys = [key(item) for item in self.items]
        self.assertEqual(len(keys), len(set(keys)))
        for expected in (
            ("Deployment", "kube-system", "metrics-server"),
            ("Deployment", "kube-system", "cluster-autoscaler"),
            ("APIService", "-", "v1beta1.metrics.k8s.io"),
            ("HorizontalPodAutoscaler", "travel-planner", "backend"),
        ):
            self.assertIn(expected, keys)

    def test_metrics_server_is_1_35_compatible_and_pinned(self) -> None:
        deployment = self.by_key[("Deployment", "kube-system", "metrics-server")]
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual(deployment["spec"]["replicas"], 2)
        self.assertEqual(
            container["image"],
            "registry.k8s.io/metrics-server/metrics-server:v0.8.1@sha256:b2d2efaf5ac3b366ed0f839d2412a2c4279d4fc2a2a733f12c52133faed36c41",
        )
        self.assertIn("--kubelet-preferred-address-types=InternalIP,Hostname", container["args"])
        self.assertIn("--kubelet-insecure-tls", container["args"])

    def test_cluster_autoscaler_is_pinned_and_discovers_only_dev_eks(self) -> None:
        deployment = self.by_key[("Deployment", "kube-system", "cluster-autoscaler")]
        pod = deployment["spec"]["template"]
        container = pod["spec"]["containers"][0]
        args = container["args"]
        self.assertEqual(
            container["image"],
            "registry.k8s.io/autoscaling/cluster-autoscaler:v1.35.0@sha256:2fc9433dd3b47baef0e68d6b1110b770a3c93db10c7bead4c5bc6cb21c72b875",
        )
        self.assertIn("--cluster-name=kdt-travelplanner-dev-eks", args)
        self.assertIn(
            "--node-group-auto-discovery=asg:tag=k8s.io/cluster-autoscaler/enabled,k8s.io/cluster-autoscaler/kdt-travelplanner-dev-eks",
            args,
        )
        self.assertIn("--max-nodes-total=4", args)
        self.assertNotIn("annotations", pod["metadata"])

    def test_load_balancer_controller_is_pinned_and_webhook_free(self) -> None:
        deployment = self.by_key[("Deployment", "kube-system", "aws-load-balancer-controller")]
        pod = deployment["spec"]["template"]
        container = pod["spec"]["containers"][0]
        self.assertEqual(
            container["image"],
            "public.ecr.aws/eks/aws-load-balancer-controller:v3.3.0@sha256:0efaddbfe2dda70d570fd262d26b434455cfb5e20d6947c4161fc73b08d6a550",
        )
        self.assertIn("--cluster-name=kdt-travelplanner-dev-eks", container["args"])
        self.assertIn("--ingress-class=alb", container["args"])
        self.assertNotIn("--enable-service-mutator-webhook=false", container["args"])
        self.assertIn("--webhook-bind-port=0", container["args"])
        self.assertIn("--aws-vpc-id=__ACTION_TIME_VPC_ID__", container["args"])
        self.assertNotIn("Secret", {item["kind"] for item in self.items})

    def test_hpa_and_hostname_spread_match_ec2_comparison_capacity(self) -> None:
        hpa = self.by_key[("HorizontalPodAutoscaler", "travel-planner", "backend")]
        self.assertEqual(hpa["spec"]["minReplicas"], 2)
        self.assertEqual(hpa["spec"]["maxReplicas"], 4)
        metric = hpa["spec"]["metrics"][0]
        self.assertEqual(metric["resource"]["name"], "cpu")
        self.assertEqual(metric["resource"]["target"]["averageUtilization"], 60)

        backend = self.by_key[("Deployment", "travel-planner", "backend")]
        constraints = backend["spec"]["template"]["spec"]["topologySpreadConstraints"]
        self.assertEqual(len(constraints), 1)
        self.assertEqual(constraints[0]["topologyKey"], "kubernetes.io/hostname")
        self.assertEqual(constraints[0]["whenUnsatisfiable"], "DoNotSchedule")
        self.assertEqual(constraints[0]["maxSkew"], 1)

    def test_ingress_matches_ec2_https_front_door_and_fails_closed_on_action_inputs(self) -> None:
        ingress = self.by_key[("Ingress", "travel-planner", "backend")]
        annotations = ingress["metadata"]["annotations"]
        self.assertEqual(ingress["spec"]["ingressClassName"], "alb")
        self.assertEqual(annotations["alb.ingress.kubernetes.io/scheme"], "internet-facing")
        self.assertEqual(annotations["alb.ingress.kubernetes.io/target-type"], "ip")
        self.assertEqual(annotations["alb.ingress.kubernetes.io/ssl-redirect"], "443")
        self.assertEqual(annotations["alb.ingress.kubernetes.io/healthcheck-port"], "9091")
        self.assertEqual(annotations["alb.ingress.kubernetes.io/healthcheck-path"], "/actuator/health/readiness")
        self.assertEqual(annotations["alb.ingress.kubernetes.io/certificate-arn"], "__ACTION_TIME_ACM_CERTIFICATE_ARN__")
        self.assertEqual(annotations["alb.ingress.kubernetes.io/subnets"], "__ACTION_TIME_PUBLIC_SUBNET_IDS__")
        self.assertEqual(ingress["spec"]["rules"][0]["host"], "__ACTION_TIME_BACKEND_HOSTNAME__")

    def test_service_accounts_are_annotation_free_and_rbac_has_no_log_access(self) -> None:
        for item in self.items:
            if item["kind"] == "ServiceAccount" and item["metadata"].get("namespace") in {"kube-system", "travel-planner"}:
                self.assertNotIn("annotations", item["metadata"])
            if item["kind"] in {"ClusterRole", "Role"}:
                for rule in item.get("rules", []):
                    self.assertNotIn("pods/log", rule.get("resources", []))

    def test_snapshot_upload_includes_platform_base(self) -> None:
        source = TERRAFORM_ROOT.read_text(encoding="utf-8")
        self.assertIn('fileset(local.kustomize_root, "base/**")', source)
        self.assertIn('fileset(local.kustomize_root, "overlays/dev-eks/**")', source)
        aggregate = (OVERLAY / "kustomization.yaml").read_text(encoding="utf-8")
        self.assertIn("- platform", aggregate)
        self.assertIn("- workload", aggregate)


if __name__ == "__main__":
    unittest.main()
