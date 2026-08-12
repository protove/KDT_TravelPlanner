import http.client
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).parents[1]
FIXTURE_DIR = ROOT / "fault-images" / "aws-recovery"
SERVER = FIXTURE_DIR / "server.py"
CONTRACT = FIXTURE_DIR / "artifact-contract.json"
BUILD_HELPER = Path(__file__).parents[2] / "scripts/loadtest/aws/build-recovery-fault-image.sh"
VERIFY_HELPER = Path(__file__).parents[2] / "scripts/loadtest/aws/verify-recovery-fault-image.sh"


def free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


IMAGE_REF = "registry.example/recovery-fault:20260812@sha256:" + "b" * 64
BASE_IMAGE = "python:3.12-alpine@sha256:" + "a" * 64
BUILD_IMAGE_REF = "registry.example/recovery-fault:20260812"
DEFAULT_FAULT_PATH = "/api/v1/travels"
DEFAULT_FAULT_CODE = "INTERNAL_SERVER_ERROR"
DEFAULT_FAULT_MESSAGE = "서버 내부 오류가 발생했습니다."


def request(port: int, path: str) -> tuple[int, dict, dict[str, str]]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    connection.request("GET", path)
    response = connection.getresponse()
    body = json.loads(response.read().decode("utf-8"))
    headers = {key.lower(): value for key, value in response.getheaders()}
    connection.close()
    return response.status, body, headers


class RecoveryFaultFixtureTest(unittest.TestCase):
    def start_fixture(
        self, mode: str, error_status: int = 500
    ) -> tuple[subprocess.Popen[str], int, int]:
        app_port, management_port = free_port(), free_port()
        environment = {
            **os.environ,
            "FAULT_MODE": mode,
            "FAULT_HTTP_STATUS": str(error_status),
            "PORT": str(app_port),
            "MANAGEMENT_PORT": str(management_port),
        }
        process = subprocess.Popen(
            [sys.executable, str(SERVER)],
            cwd=FIXTURE_DIR,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        deadline = time.time() + 5
        while time.time() < deadline:
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout else ""
                raise AssertionError(f"fixture exited early: {output}")
            try:
                request(management_port, "/actuator/health/liveness")
                return process, app_port, management_port
            except (ConnectionError, OSError):
                time.sleep(0.05)
        process.terminate()
        process.wait(timeout=3)
        self.fail("fixture did not become ready")

    def stop_fixture(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=3)
        if process.stdout is not None:
            process.stdout.close()

    def run_fixture_with_invalid_business_status(self, status: int) -> subprocess.CompletedProcess[str]:
        app_port, management_port = free_port(), free_port()
        environment = {
            **os.environ,
            "FAULT_MODE": "business_error",
            "FAULT_HTTP_STATUS": str(status),
            "PORT": str(app_port),
            "MANAGEMENT_PORT": str(management_port),
        }
        return subprocess.run(
            [sys.executable, str(SERVER)],
            cwd=FIXTURE_DIR,
            env=environment,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )

    @staticmethod
    def metadata(
        mode: str,
        *,
        image_ref: str = IMAGE_REF,
        base_image: str = BASE_IMAGE,
        fault_path: str = DEFAULT_FAULT_PATH,
        fault_error_code: str = DEFAULT_FAULT_CODE,
        fault_error_message: str = DEFAULT_FAULT_MESSAGE,
        fault_http_status: int = 500,
    ) -> dict:
        return {
            "contractVersion": "aws-recovery-fault-image-v1",
            "imageRef": image_ref,
            "baseImage": base_image,
            "mode": mode,
            "faultPath": fault_path,
            "faultErrorCode": fault_error_code,
            "faultErrorMessage": fault_error_message,
            "faultHttpStatus": fault_http_status,
        }

    def verify_metadata(
        self,
        metadata: Optional[dict],
        *,
        image_ref: str = IMAGE_REF,
        base_image: str = BASE_IMAGE,
        mode: str = "probe_failure",
        fault_path: str = DEFAULT_FAULT_PATH,
        fault_error_code: str = DEFAULT_FAULT_CODE,
        fault_error_message: str = DEFAULT_FAULT_MESSAGE,
        fault_http_status: int = 500,
        include_metadata_argument: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            metadata_path = Path(directory) / "artifact-metadata.json"
            if metadata is not None:
                metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            command = [
                "bash",
                str(VERIFY_HELPER),
                "--image-ref",
                image_ref,
                "--base-image",
                base_image,
                "--mode",
                mode,
                "--fault-path",
                fault_path,
                "--fault-error-code",
                fault_error_code,
                "--fault-error-message",
                fault_error_message,
                "--fault-http-status",
                str(fault_http_status),
            ]
            if include_metadata_argument:
                command.extend(["--metadata-file", str(metadata_path)])
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )

    def test_contract_declares_digest_and_safety_boundaries(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertTrue(contract["image"]["requiresDigest"])
        self.assertTrue(contract["image"]["baseImageRequiresDigest"])
        self.assertEqual(
            contract["metadata"]["requiredFields"],
            [
                "contractVersion",
                "imageRef",
                "baseImage",
                "mode",
                "faultPath",
                "faultErrorCode",
                "faultErrorMessage",
                "faultHttpStatus",
            ],
        )
        self.assertEqual(contract["metadata"]["faultParameters"]["faultHttpStatus"]["minimum"], 500)
        self.assertEqual(contract["metadata"]["faultParameters"]["faultHttpStatus"]["maximum"], 599)
        safety = contract["safety"]
        self.assertFalse(safety["usesDatabase"])
        self.assertFalse(safety["usesRedis"])
        self.assertFalse(safety["usesAws"])
        self.assertFalse(safety["usesGoogleApis"])
        self.assertFalse(safety["readsSecrets"])

    def test_probe_failure_keeps_liveness_and_application_reachable(self):
        process, app_port, management_port = self.start_fixture("probe_failure")
        try:
            readiness_status, readiness, _ = request(
                management_port, "/actuator/health/readiness"
            )
            liveness_status, liveness, _ = request(
                management_port, "/actuator/health/liveness"
            )
            ping_status, ping, _ = request(app_port, "/api/ping")
            self.assertEqual(readiness_status, 503)
            self.assertEqual(readiness["status"], "OUT_OF_SERVICE")
            self.assertEqual(liveness_status, 200)
            self.assertEqual(liveness["status"], "UP")
            self.assertEqual(ping_status, 200)
            self.assertEqual(ping["status"], "ok")
        finally:
            self.stop_fixture(process)

    def test_business_error_keeps_readiness_but_returns_backend_error_envelope(self):
        process, app_port, management_port = self.start_fixture("business_error")
        try:
            readiness_status, readiness, _ = request(
                management_port, "/actuator/health/readiness"
            )
            ping_status, ping, _ = request(app_port, "/api/ping")
            api_status, error, headers = request(app_port, "/api/v1/travels")
            self.assertEqual(readiness_status, 200)
            self.assertEqual(readiness["status"], "UP")
            self.assertEqual(ping_status, 200)
            self.assertEqual(ping["status"], "ok")
            self.assertEqual(api_status, 500)
            self.assertEqual(error["code"], "INTERNAL_SERVER_ERROR")
            self.assertIn("message", error)
            self.assertRegex(error["requestId"], r"^[0-9a-f-]{36}$")
            self.assertIn("x-request-id", headers)
        finally:
            self.stop_fixture(process)

    def test_business_error_rejects_4xx_status_before_server_starts(self):
        for status in (400, 499):
            with self.subTest(status=status):
                result = self.run_fixture_with_invalid_business_status(status)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("between 500 and 599", result.stdout + result.stderr)

    def test_business_error_accepts_500_and_599_statuses(self):
        for status in (500, 599):
            with self.subTest(status=status):
                process, app_port, management_port = self.start_fixture(
                    "business_error", error_status=status
                )
                try:
                    readiness_status, _, _ = request(
                        management_port, "/actuator/health/readiness"
                    )
                    api_status, error, _ = request(app_port, "/api/v1/travels")
                    self.assertEqual(readiness_status, 200)
                    self.assertEqual(api_status, status)
                    self.assertEqual(error["code"], "INTERNAL_SERVER_ERROR")
                finally:
                    self.stop_fixture(process)

    def test_build_helper_rejects_unpinned_base_image_without_building(self):
        result = subprocess.run(
            [
                "bash", str(BUILD_HELPER),
                "--image-ref", BUILD_IMAGE_REF,
                "--base-image", "python:3.12-alpine",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sha256", result.stderr)

    def test_build_helper_dry_run_binds_each_mode(self):
        for mode in ("probe_failure", "business_error"):
            with self.subTest(mode=mode):
                result = subprocess.run(
                    [
                        "bash", str(BUILD_HELPER),
                        "--image-ref", BUILD_IMAGE_REF,
                        "--base-image", BASE_IMAGE,
                        "--mode", mode,
                        "--dry-run",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"fault_mode=verified mode={mode}", result.stdout)

    def test_deployment_verifier_rejects_mutable_image_reference(self):
        result = subprocess.run(
            [
                "bash", str(VERIFY_HELPER),
                "--image-ref", "registry.example/recovery-fault:dev",
                "--base-image", BASE_IMAGE,
                "--mode", "probe_failure",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("digest-pinned", result.stderr)

    def test_deployment_verifier_accepts_digest_pinned_references(self):
        for mode in ("probe_failure", "business_error"):
            with self.subTest(mode=mode):
                metadata = self.metadata(mode)
                result = self.verify_metadata(
                    metadata,
                    mode=mode,
                    fault_http_status=500,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("deployment_image_ref=verified", result.stdout)
                self.assertIn(f"artifact_metadata=verified mode={mode}", result.stdout)

    def test_deployment_verifier_requires_metadata(self):
        result = self.verify_metadata(None, include_metadata_argument=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("metadata-file", result.stderr)

    def test_deployment_verifier_rejects_missing_metadata_fields(self):
        metadata = self.metadata("probe_failure")
        del metadata["mode"]
        result = self.verify_metadata(metadata)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fields mismatch", result.stderr)

    def test_deployment_verifier_rejects_metadata_mode_mismatch(self):
        metadata = self.metadata("probe_failure")
        result = self.verify_metadata(metadata, mode="business_error")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("metadata mismatch for mode", result.stderr)

    def test_deployment_verifier_rejects_metadata_digest_mismatch(self):
        metadata = self.metadata("probe_failure")
        metadata["imageRef"] = "registry.example/recovery-fault:20260812@sha256:" + "c" * 64
        result = self.verify_metadata(metadata)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("metadata mismatch for imageRef", result.stderr)

    def test_deployment_verifier_rejects_4xx_metadata_status(self):
        metadata = self.metadata("business_error", fault_http_status=400)
        result = self.verify_metadata(metadata, mode="business_error", fault_http_status=400)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("between 500 and 599", result.stderr)


if __name__ == "__main__":
    unittest.main()
