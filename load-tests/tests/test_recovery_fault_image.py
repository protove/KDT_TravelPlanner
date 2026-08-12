import http.client
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path


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


def request(port: int, path: str) -> tuple[int, dict, dict[str, str]]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    connection.request("GET", path)
    response = connection.getresponse()
    body = json.loads(response.read().decode("utf-8"))
    headers = {key.lower(): value for key, value in response.getheaders()}
    connection.close()
    return response.status, body, headers


class RecoveryFaultFixtureTest(unittest.TestCase):
    def start_fixture(self, mode: str) -> tuple[subprocess.Popen[str], int, int]:
        app_port, management_port = free_port(), free_port()
        environment = {
            **os.environ,
            "FAULT_MODE": mode,
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

    def test_contract_declares_digest_and_safety_boundaries(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertTrue(contract["image"]["requiresDigest"])
        self.assertTrue(contract["image"]["baseImageRequiresDigest"])
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

    def test_build_helper_rejects_unpinned_base_image_without_building(self):
        result = subprocess.run(
            [
                "bash", str(BUILD_HELPER),
                "--image-ref", "registry.example/recovery-fault:dev",
                "--base-image", "python:3.12-alpine",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sha256", result.stderr)

    def test_deployment_verifier_rejects_mutable_image_reference(self):
        result = subprocess.run(
            [
                "bash", str(VERIFY_HELPER),
                "--image-ref", "registry.example/recovery-fault:dev",
                "--base-image", "python:3.12-alpine@sha256:" + "a" * 64,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("digest-pinned", result.stderr)

    def test_deployment_verifier_accepts_digest_pinned_references(self):
        result = subprocess.run(
            [
                "bash", str(VERIFY_HELPER),
                "--image-ref", "registry.example/recovery-fault:20260812@sha256:" + "b" * 64,
                "--base-image", "python:3.12-alpine@sha256:" + "a" * 64,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("deployment_image_ref=verified", result.stdout)


if __name__ == "__main__":
    unittest.main()
