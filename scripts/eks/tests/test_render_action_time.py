"""Offline contract tests for the dev-eks action-time renderer."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "scripts" / "eks" / "render-action-time.py"
SPEC = importlib.util.spec_from_file_location("render_action_time", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


INPUTS = {
    "vpc_id": "vpc-0123456789abcdef0",
    "public_subnet_ids": ["subnet-0123456789abcdef0", "subnet-abcdef0123456789"],
    "api_certificate_arn": "arn:aws:acm:ap-northeast-2:123456789012:certificate/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "backend_hostname": "api.example.com",
    "backend_origin": "https://api.example.com",
    "backend_image": "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/travel-planner-backend@sha256:" + "a" * 64,
    "frontend_origin": "https://www.example.com",
}
CONTRACT = {
    "schema_version": "dev-eks-deployment-contract/v1",
    "aws_account_id": "123456789012",
    "aws_region": "ap-northeast-2",
    "backend_ecr_repository_url": "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/travel-planner-backend",
    "profile_image_bucket_name": "kdt-travelplanner-dev-profile-images",
    "profile_image_public_base_url": "https://images.example.com",
}


class RenderActionTimeTest(unittest.TestCase):
    def test_repository_snapshot_renders_all_three_roots_and_hashes_aggregate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.mkdir()
            shutil.copytree(ROOT / "k8s" / "base", source / "base")
            shutil.copytree(ROOT / "k8s" / "overlays", source / "overlays")
            result = MODULE.render(
                source,
                Path(directory) / "rendered",
                INPUTS,
                CONTRACT,
                "kubectl",
            )
            self.assertRegex(result["render_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(set(result["stage_render_sha256"]), {"aggregate", "platform", "workload"})
            self.assertTrue(all(count >= 1 for count in result["replacement_counts"].values()))
            aggregate = subprocess.run(
                ["kubectl", "kustomize", str(Path(directory) / "rendered" / "overlays" / "dev-eks")],
                check=True,
                capture_output=True,
            ).stdout.decode("utf-8")
            self.assertNotIn("__ACTION_TIME_", aggregate)

    def test_malformed_values_fail_closed(self) -> None:
        malformed = dict(INPUTS, backend_image="repo:latest")
        with self.assertRaises(MODULE.RenderError):
            MODULE.validate_values(malformed, CONTRACT)

    def test_backend_image_must_match_trusted_ecr_repository_and_digest(self) -> None:
        trusted = CONTRACT["backend_ecr_repository_url"]
        rejected = (
            "docker.io/travel-planner/backend@sha256:" + "a" * 64,
            "000000000000.dkr.ecr.ap-northeast-2.amazonaws.com/travel-planner-backend@sha256:" + "a" * 64,
            "123456789012.dkr.ecr.us-east-1.amazonaws.com/travel-planner-backend@sha256:" + "a" * 64,
            "123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/other-backend@sha256:" + "a" * 64,
            trusted + ":latest",
            trusted + "@sha256:" + "A" * 64,
            trusted + "@sha256:" + "a" * 63,
        )
        for image in rejected:
            with self.subTest(image=image):
                with self.assertRaises(MODULE.RenderError):
                    MODULE.validate_values(dict(INPUTS, backend_image=image), CONTRACT)

        accepted = MODULE.validate_values(INPUTS, CONTRACT)
        self.assertEqual(accepted["__ACTION_TIME_ECR_BACKEND_IMAGE_DIGEST__"], INPUTS["backend_image"])

    def test_trusted_ecr_contract_must_match_account_and_region(self) -> None:
        with self.assertRaisesRegex(MODULE.RenderError, "account"):
            MODULE.validate_values(INPUTS, dict(CONTRACT, backend_ecr_repository_url="000000000000.dkr.ecr.ap-northeast-2.amazonaws.com/travel-planner-backend"))
        with self.assertRaisesRegex(MODULE.RenderError, "region"):
            MODULE.validate_values(INPUTS, dict(CONTRACT, backend_ecr_repository_url="123456789012.dkr.ecr.us-east-1.amazonaws.com/travel-planner-backend"))

    def test_backend_origin_must_match_hostname(self) -> None:
        malformed = dict(INPUTS, backend_origin="https://other.example.com")
        with self.assertRaises(MODULE.RenderError):
            MODULE.validate_values(malformed, CONTRACT)

    def test_unknown_token_and_missing_token_are_rejected(self) -> None:
        replacements = {token: "value" for token in MODULE.TOKENS}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            root.mkdir()
            (root / "values.yaml").write_text(
                "\n".join(MODULE.TOKENS) + "\n__ACTION_TIME_UNKNOWN__\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(MODULE.RenderError, "unknown action-time token"):
                MODULE.replace_tokens(root, Path(directory) / "unknown-output", replacements)
            with self.assertRaises(MODULE.RenderError):
                MODULE.assert_rendered_clean(b"__ACTION_TIME_UNKNOWN__", "fixture")

            with self.assertRaises(MODULE.RenderError):
                MODULE.assert_rendered_clean(b"__ACTION_TIME_unknown__", "fixture")

            (root / "values.yaml").write_text(MODULE.TOKENS[0], encoding="utf-8")
            with self.assertRaises(MODULE.RenderError):
                MODULE.replace_tokens(root, Path(directory) / "missing-output", replacements)

    def test_unknown_non_rendered_bundle_file_fails_and_legacy_base_tokens_are_allowed(self) -> None:
        replacements = {token: "value" for token in MODULE.TOKENS}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            (root / "base").mkdir(parents=True)
            (root / "overlays" / "dev-eks").mkdir(parents=True)
            (root / "base" / "values.yaml").write_text("\n".join(MODULE.TOKENS), encoding="utf-8")
            (root / "base" / "legacy.yaml").write_text(
                "__ACTION_TIME_DATABASE_HOST__ __ACTION_TIME_DATABASE_NAME__ __ACTION_TIME_REDIS_HOST__",
                encoding="utf-8",
            )
            (root / "notes.md").write_text("__ACTION_TIME_UNKNOWN__", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.RenderError, "unknown action-time token"):
                MODULE.replace_tokens(root, Path(directory) / "unknown-output", replacements)

            (root / "notes.md").write_text("legacy note", encoding="utf-8")
            counts = MODULE.replace_tokens(root, Path(directory) / "legacy-output", replacements)
            self.assertTrue(all(count == 1 for count in counts.values()))

    def test_renderer_script_literals_do_not_satisfy_manifest_token_requirements(self) -> None:
        replacements = {token: "value" for token in MODULE.TOKENS}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            (root / "base").mkdir(parents=True)
            (root / "scripts" / "eks").mkdir(parents=True)
            (root / "base" / "values.yaml").write_text(MODULE.TOKENS[0], encoding="utf-8")
            (root / "scripts" / "eks" / "render-action-time.py").write_text("\n".join(MODULE.TOKENS[1:]), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.RenderError, "required action-time token"):
                MODULE.replace_tokens(root, Path(directory) / "missing-output", replacements)

    def test_output_root_must_be_isolated_and_new(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            root.mkdir()
            (root / "values.yaml").write_text("x", encoding="utf-8")
            with self.assertRaises(MODULE.RenderError):
                MODULE.replace_tokens(root, root, {})
            output = Path(directory) / "output"
            output.mkdir()
            with self.assertRaises(MODULE.RenderError):
                MODULE.replace_tokens(root, output, {})


if __name__ == "__main__":
    unittest.main()
