#!/usr/bin/env python3
"""Small, dependency-free fault fixture for AWS recovery rehearsals.

This process is deliberately not the TravelPlanner backend. It exposes only
the management probes and a small API surface needed to prove that an AWS
rollout can distinguish a readiness failure from an application-level error.
It never connects to a database, Redis, Google API, AWS service, or secret
store.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import signal
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


ALLOWED_MODES = {"normal", "probe_failure", "business_error"}
ERROR_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
PATH_PATTERN = re.compile(r"^/api/v1/[A-Za-z0-9_./{}:-]+$")
MAX_BODY_BYTES = 1_048_576
IMMUTABLE_CONFIG_PATH = "/app/fault-config.json"
IMMUTABLE_CONFIG_FIELDS = {
    "contractVersion",
    "mode",
    "faultPath",
    "faultErrorCode",
    "faultErrorMessage",
    "faultHttpStatus",
}
CONTRACT_VERSION = "aws-recovery-fault-image-v1"


def _env_port(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if not 1 <= value <= 65535:
        raise ValueError(f"{name} must be between 1 and 65535")
    return value


def _env_mode() -> str:
    mode = os.getenv("FAULT_MODE", "normal").strip().lower()
    if mode not in ALLOWED_MODES:
        raise ValueError(f"FAULT_MODE must be one of {sorted(ALLOWED_MODES)}")
    return mode


def _env_fault_path() -> str:
    path = os.getenv("FAULT_PATH", "/api/v1/travels").strip()
    if not PATH_PATTERN.fullmatch(path):
        raise ValueError("FAULT_PATH must be a safe /api/v1/... path")
    return path


def _env_error_code() -> str:
    code = os.getenv("FAULT_ERROR_CODE", "INTERNAL_SERVER_ERROR").strip()
    if not ERROR_CODE_PATTERN.fullmatch(code):
        raise ValueError("FAULT_ERROR_CODE must be an uppercase error code")
    return code


def _env_error_status(mode: str = "normal") -> int:
    raw = os.getenv("FAULT_HTTP_STATUS", "500")
    try:
        status = int(raw)
    except ValueError as error:
        raise ValueError("FAULT_HTTP_STATUS must be an integer") from error
    if mode == "business_error":
        if not 500 <= status <= 599:
            raise ValueError(
                "FAULT_HTTP_STATUS for business_error must be between 500 and 599"
            )
    elif not 400 <= status <= 599:
        raise ValueError("FAULT_HTTP_STATUS must be an HTTP 4xx or 5xx status")
    return status


def _validate_fault_values(values: dict[str, Any]) -> dict[str, Any]:
    if set(values) != IMMUTABLE_CONFIG_FIELDS:
        raise ValueError("immutable fault configuration fields are invalid")
    if values["contractVersion"] != CONTRACT_VERSION:
        raise ValueError("immutable fault configuration contract version is invalid")
    mode = str(values["mode"]).strip().lower()
    if mode not in ALLOWED_MODES:
        raise ValueError(f"FAULT_MODE must be one of {sorted(ALLOWED_MODES)}")
    path = str(values["faultPath"]).strip()
    if not PATH_PATTERN.fullmatch(path):
        raise ValueError("FAULT_PATH must be a safe /api/v1/... path")
    code = str(values["faultErrorCode"]).strip()
    if not ERROR_CODE_PATTERN.fullmatch(code):
        raise ValueError("FAULT_ERROR_CODE must be an uppercase error code")
    message = values["faultErrorMessage"]
    if not isinstance(message, str) or len(message) > 256:
        raise ValueError("FAULT_ERROR_MESSAGE must be at most 256 characters")
    try:
        status = int(values["faultHttpStatus"])
    except (TypeError, ValueError) as error:
        raise ValueError("FAULT_HTTP_STATUS must be an integer") from error
    if mode == "business_error" and not 500 <= status <= 599:
        raise ValueError(
            "FAULT_HTTP_STATUS for business_error must be between 500 and 599"
        )
    if mode != "business_error" and not 400 <= status <= 599:
        raise ValueError("FAULT_HTTP_STATUS must be an HTTP 4xx or 5xx status")
    return {
        "contractVersion": CONTRACT_VERSION,
        "mode": mode,
        "faultPath": path,
        "faultErrorCode": code,
        "faultErrorMessage": message,
        "faultHttpStatus": status,
    }


def _load_immutable_fault_config() -> dict[str, Any] | None:
    path = Path(IMMUTABLE_CONFIG_PATH)
    behavior_sha_declared = "IMMUTABLE_BEHAVIOR_SHA256" in os.environ
    contract_declared = "IMMUTABLE_CONTRACT_VERSION" in os.environ
    behavior_sha = os.environ.get("IMMUTABLE_BEHAVIOR_SHA256", "")
    declared_contract = os.environ.get("IMMUTABLE_CONTRACT_VERSION", "")

    # Source-level subprocess tests may use mutable FAULT_* values only when
    # the packaged immutable contract is entirely absent. A packaged image
    # always declares both values, so every other state fails closed.
    if not behavior_sha_declared and not contract_declared:
        if not path.exists():
            return None
        raise ValueError(
            "immutable config exists but immutable declarations are missing"
        )
    if not behavior_sha_declared or not contract_declared:
        raise ValueError(
            "IMMUTABLE_BEHAVIOR_SHA256 and IMMUTABLE_CONTRACT_VERSION are both required"
        )
    if not re.fullmatch(r"[0-9a-f]{64}", behavior_sha):
        raise ValueError("IMMUTABLE_BEHAVIOR_SHA256 must be a 64-character lowercase hex digest")
    if declared_contract != CONTRACT_VERSION:
        raise ValueError("immutable fault configuration contract mismatch")
    if not path.is_file():
        raise ValueError("immutable fault configuration file is missing or not a regular file")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"unable to read immutable fault configuration: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError("immutable fault configuration must be a JSON object")
    values = _validate_fault_values(raw)
    canonical = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    actual_behavior_sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if behavior_sha != actual_behavior_sha:
        raise ValueError("immutable fault configuration digest mismatch")

    environment_values = {
        "FAULT_MODE": values["mode"],
        "FAULT_PATH": values["faultPath"],
        "FAULT_ERROR_CODE": values["faultErrorCode"],
        "FAULT_ERROR_MESSAGE": values["faultErrorMessage"],
        "FAULT_HTTP_STATUS": values["faultHttpStatus"],
    }
    for name, expected in environment_values.items():
        supplied = os.getenv(name)
        if supplied is None:
            continue
        normalized = supplied.strip().lower() if name == "FAULT_MODE" else supplied.strip()
        if name == "FAULT_HTTP_STATUS":
            try:
                normalized = int(normalized)
            except ValueError as error:
                raise ValueError(f"{name} runtime override is invalid") from error
        if normalized != expected:
            raise ValueError(f"{name} runtime override differs from immutable image configuration")
    return values


class FixtureConfig:
    def __init__(self) -> None:
        immutable = _load_immutable_fault_config()
        if immutable is None:
            self.mode = _env_mode()
            self.fault_path = _env_fault_path()
            self.error_code = _env_error_code()
            self.error_status = _env_error_status(self.mode)
            self.error_message = os.getenv(
                "FAULT_ERROR_MESSAGE", "서버 내부 오류가 발생했습니다."
            )[:256]
        else:
            self.mode = immutable["mode"]
            self.fault_path = immutable["faultPath"]
            self.error_code = immutable["faultErrorCode"]
            self.error_status = immutable["faultHttpStatus"]
            self.error_message = immutable["faultErrorMessage"]
        self.application_port = _env_port("PORT", 8080)
        self.management_port = _env_port("MANAGEMENT_PORT", 9091)
        if self.application_port == self.management_port:
            raise ValueError("PORT and MANAGEMENT_PORT must be different")


class FixtureHandler(BaseHTTPRequestHandler):
    server: "FixtureServer"

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        self._dispatch()

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        self._discard_body()
        self._dispatch()

    def do_PATCH(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        self._discard_body()
        self._dispatch()

    def do_DELETE(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        self._dispatch()

    def _discard_body(self) -> None:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError:
            length = 0
        if 0 < length <= MAX_BODY_BYTES:
            self.rfile.read(length)

    def _dispatch(self) -> None:
        path = urlsplit(self.path).path
        if self.server.management:
            self._dispatch_management(path)
        else:
            self._dispatch_application(path)

    def _dispatch_management(self, path: str) -> None:
        if path == "/actuator/health/liveness":
            self._send(HTTPStatus.OK, {"status": "UP"})
            return
        if path == "/actuator/health/readiness":
            if self.server.config.mode == "probe_failure":
                self._send(HTTPStatus.SERVICE_UNAVAILABLE, {"status": "OUT_OF_SERVICE"})
            else:
                self._send(HTTPStatus.OK, {"status": "UP"})
            return
        if path == "/actuator/health":
            ready = self.server.config.mode != "probe_failure"
            self._send(HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE, {
                "status": "UP" if ready else "OUT_OF_SERVICE",
            })
            return
        self._send_error(HTTPStatus.NOT_FOUND)

    def _dispatch_application(self, path: str) -> None:
        if path == "/api/ping":
            self._send(HTTPStatus.OK, {
                "status": "ok",
                "application": "travel-planner-backend-fault-fixture",
                "profile": "recovery-fixture",
            })
            return

        if self.server.config.mode == "business_error" and (
            path == self.server.config.fault_path
            or path.startswith(self.server.config.fault_path + "/")
        ):
            self._send_error(
                self.server.config.error_status,
                code=self.server.config.error_code,
                message=self.server.config.error_message,
            )
            return

        # The fixture intentionally returns a deterministic, dependency-free
        # success for the protected core path. It is not intended to emulate
        # the full TravelPlanner response schema.
        if path == "/api/v1/travels" or path.startswith("/api/v1/travels/"):
            self._send(HTTPStatus.OK, {"data": [], "fixtureMode": self.server.config.mode})
            return

        self._send_error(HTTPStatus.NOT_FOUND)

    def _send_error(
        self,
        status: int | HTTPStatus,
        *,
        code: str = "RESOURCE_NOT_FOUND",
        message: str = "요청한 리소스를 찾을 수 없습니다.",
    ) -> None:
        self._send(status, {
            "code": code,
            "message": message,
            "requestId": str(uuid.uuid4()),
        })

    def _send(self, status: int | HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json;charset=UTF-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Request-Id", str(uuid.uuid4()))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        # Keep logs structured and free of request bodies or credentials.
        print(json.dumps({
            "event": "http_request",
            "mode": self.server.config.mode,
            "management": self.server.management,
            "path": urlsplit(self.path).path,
            "message": format % args,
        }, ensure_ascii=False), flush=True)


class FixtureServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], config: FixtureConfig, management: bool) -> None:
        super().__init__(address, FixtureHandler)
        self.config = config
        self.management = management


def main() -> int:
    config = FixtureConfig()
    application = FixtureServer(("0.0.0.0", config.application_port), config, management=False)
    management = FixtureServer(("0.0.0.0", config.management_port), config, management=True)
    servers = (application, management)

    def stop(_signum: int, _frame: Any) -> None:
        for server in servers:
            server.shutdown()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(json.dumps({
        "event": "fixture_started",
        "mode": config.mode,
        "applicationPort": config.application_port,
        "managementPort": config.management_port,
        "faultPath": config.fault_path,
    }), flush=True)

    import threading

    threads = [
        threading.Thread(target=server.serve_forever, name=f"fixture-{index}", daemon=True)
        for index, server in enumerate(servers)
    ]
    for thread in threads:
        thread.start()
    try:
        for thread in threads:
            thread.join()
    finally:
        for server in servers:
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
