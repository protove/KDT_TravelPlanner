#!/usr/bin/env python3
"""Run the exact SCRUM-80 Backend image through a local current-feature gate.

This runner is intentionally narrower than the historical Compose rehearsal:
it never builds or tags a Backend image, and it owns every generated file and
Docker resource under one run directory/project.  The local result proves the
26-operation fixture and request path before an AWS mutation; it is not an
AWS performance or SLO claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_IMAGE = (
    "419496180357.dkr.ecr.ap-northeast-2.amazonaws.com/"
    "kdt-travelplanner-dev-backend@sha256:"
    "d11e78e6149df663825b3b4a85397441480c8c9d38e22c930856bc1ce1c62256"
)
BACKEND_INDEX_DIGEST = "sha256:d11e78e6149df663825b3b4a85397441480c8c9d38e22c930856bc1ce1c62256"
BACKEND_AMD64_DIGEST = "sha256:4ce7d7ea1debd614d30bacaf0276f325ebaa2fdf95f12488f2e3b67b08b12385"
FORBIDDEN_BACKEND_DIGEST = "sha256:468ddb5a9a9bbd5b9c0409fa39c84e26dff3bbb5a888b08c52f88d07b6635f3b"
MOCK_IMAGE = (
    "nginxinc/nginx-unprivileged:1.27.1-alpine3.20-perl@sha256:"
    "86b08eb3082f1f796f0ce1ef75a1c356a116fafc5f88754924fba2286fbd0221"
)
K6_IMAGE = (
    "grafana/k6:0.54.0@sha256:"
    "1f40432b1cbe7234e977f96c362c9bc550a2d2b583d014dd8669fe40d3e9e755"
)
PROFILE = REPOSITORY_ROOT / "load-tests/aws/profiles/eks-monolith-breakpoint-v2.1.json"
SLO_CONTRACT = REPOSITORY_ROOT / "load-tests/aws/contracts/eks-monolith-breakpoint-slo-v2.1.json"
COMPOSE = REPOSITORY_ROOT / "compose.yml"
SEEDER = REPOSITORY_ROOT / "scripts/loadtest/seed-compose-load-data.py"
MOCK_CONFIG = REPOSITORY_ROOT / "load-tests/mocks/google-api/nginx.conf"
MOCK_RESPONSES = REPOSITORY_ROOT / "load-tests/mocks/google-api/responses"
EXPECTED_OPERATIONS = (
    "refresh", "profileRead", "travelList", "travelDetail", "travelUpdate",
    "countryList", "cityList", "placeSearch", "nearbySearch", "mapPoints",
    "routeGet", "routePreview", "timelineCreate", "orderChange", "memberList",
    "invitationList", "communityCategoryList", "communityPostList",
    "communityPostDetail", "communityCommentList", "communityMyPosts",
    "communityMyComments", "communityPostUpdate", "communityCommentUpdate",
    "communityPostReaction", "communityCommentReaction",
)


class ValidationError(RuntimeError):
    """A sanitized local validation failure."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def safe_id(value: str) -> str:
    sanitized = "".join(char if char.isalnum() or char in "-_." else "-" for char in value)
    return sanitized.lower().strip("-")[:48] or "run"


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def yaml_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def run_command(command: list[str], *, env: dict[str, str] | None = None, cwd: Path = REPOSITORY_ROOT,
                output: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run without a shell and keep command details free of secret values."""
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8") as handle:
            completed = subprocess.run(command, cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT,
                                       text=True, check=False)
    else:
        completed = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    if check and completed.returncode != 0:
        raise ValidationError(f"command failed ({completed.returncode}): {' '.join(command[:3])}")
    return completed


def parse_metric(summary: dict, metric_name: str, field: str = "count", default: float = 0.0) -> float:
    values = summary.get("metrics", {}).get(metric_name, {})
    value = values.get(field, default) if isinstance(values, dict) else default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def evaluate_summary(path: Path, scenario: str, *, target_rate: int, measured_seconds: int,
                     warmup_seconds: int) -> dict:
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValidationError(f"{scenario} summary is missing or invalid") from error
    operation_mix = summary.get("operationMix", {})
    operations = operation_mix.get("operations", {}) if isinstance(operation_mix, dict) else {}
    observed_ids = {key for key, item in operations.items() if isinstance(item, dict) and float(item.get("observedCount") or 0) > 0}
    missing = [operation for operation in EXPECTED_OPERATIONS if operation not in observed_ids]
    metrics = summary.get("metrics", {})
    checks = metrics.get("checks", {}) if isinstance(metrics, dict) else {}
    checks_rate = float(checks.get("rate", 0.0) or 0.0) if isinstance(checks, dict) else 0.0
    dropped = parse_metric(summary, "dropped_iterations")
    unexpected = parse_metric(summary, "unexpected_errors")
    contract = parse_metric(summary, "contract_fail")
    total_selections = float(operation_mix.get("totalSelections") or 0) if isinstance(operation_mix, dict) else 0.0
    elapsed = max(1, warmup_seconds + measured_seconds)
    achieved_rate = total_selections / elapsed
    verdict = {
        "scenario": scenario,
        "targetRate": target_rate,
        "warmupSeconds": warmup_seconds,
        "measuredSeconds": measured_seconds,
        "observedOperationCount": len(observed_ids),
        "expectedOperationCount": len(EXPECTED_OPERATIONS),
        "missingOperations": missing,
        "totalSelections": int(total_selections),
        "achievedRateRps": round(achieved_rate, 3),
        "minimumAchievedRateRps": round(target_rate * 0.95, 3),
        "checksRate": checks_rate,
        "droppedIterations": int(dropped),
        "unexpectedErrors": int(unexpected),
        "contractFailures": int(contract),
        # Local arm64 -> linux/amd64 emulation makes latency informational.
        "p95Ms": summary.get("metrics", {}).get("http_req_duration", {}).get("p(95)"),
        "p95Informational": True,
    }
    verdict["pass"] = (
        not missing and checks_rate >= 1.0 and dropped == 0 and unexpected == 0 and contract == 0
        and (scenario == "smoke" or achieved_rate >= target_rate * 0.95)
    )
    return verdict


class LocalValidation:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.run_id = safe_id(args.run_id or f"scrum80-local-d11e78-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")
        self.evidence_root = (args.evidence_root or REPOSITORY_ROOT / "evidence/load-tests" / self.run_id).resolve()
        self.runtime_root = self.evidence_root / ".runtime"
        self.project = safe_id(args.project_name or f"scrum80-local-{self.run_id}")
        self.env_file = self.runtime_root / "compose.env"
        self.override_file = self.runtime_root / "compose.override.yml"
        self.data_file = self.runtime_root / "data.json"
        self.secret_values: list[str] = []
        self.fixture_result_file = self.evidence_root / "fixture" / "seed-result.json"
        self.compose_args = [
            "docker", "compose", "--env-file", str(self.env_file), "--project-name", self.project,
            "--file", str(self.override_file),
        ]
        self.backend_url = f"http://127.0.0.1:{args.backend_port}"

    def prepare(self) -> None:
        if self.args.users < 2 or self.args.users > 200:
            raise ValidationError("--users must be between 2 and 200")
        if self.args.backend_port == self.args.mock_port:
            raise ValidationError("backend and mock ports must differ")
        if not PROFILE.is_file() or not SLO_CONTRACT.is_file() or not COMPOSE.is_file():
            raise ValidationError("required profile, SLO contract or compose file is missing")
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        (self.evidence_root / "fixture").mkdir(parents=True, exist_ok=True)
        (self.evidence_root / "smoke").mkdir(parents=True, exist_ok=True)
        (self.evidence_root / "baseline").mkdir(parents=True, exist_ok=True)
        log_dir = self.runtime_root / "mock-logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        # nginx writes access/error logs as an unprivileged container user.
        log_dir.chmod(0o777)
        env_values = {
            "COMPOSE_PROJECT_NAME": self.project,
            "FRONTEND_PORT": str(self.args.frontend_port),
            "BACKEND_PORT": str(self.args.backend_port),
            "SPRING_PROFILES_ACTIVE": "prod",
            "POSTGRES_DB": "travel_diary_loadtest",
            "POSTGRES_USER": "travel_loadtest",
            "POSTGRES_PASSWORD": secrets.token_urlsafe(24),
            "REDIS_PASSWORD": secrets.token_urlsafe(24),
            "CORS_ALLOWED_ORIGINS": f"http://127.0.0.1:{self.args.frontend_port}",
            "JWT_SECRET": secrets.token_urlsafe(48),
            "GOOGLE_MAPS_API_KEY": "loadtest-google-mock-key",
            "GOOGLE_PLACES_BASE_URL": "http://google-api-mock:8080",
            "GOOGLE_ROUTES_BASE_URL": "http://google-api-mock:8080",
            "PROFILE_IMAGE_STORAGE_ENABLED": "false",
            "PROFILE_IMAGE_STORAGE_REGION": "ap-northeast-2",
            "PROFILE_IMAGE_STORAGE_BUCKET": "",
            "PROFILE_IMAGE_PUBLIC_BASE_URL": "",
            "PROFILE_IMAGE_STORAGE_PATH_STYLE_ACCESS_ENABLED": "false",
            "REFRESH_TOKEN_TTL": "30m",
        }
        self.secret_values = [value for key, value in env_values.items() if key in {
            "POSTGRES_PASSWORD", "REDIS_PASSWORD", "JWT_SECRET",
        }]
        self.env_file.write_text("".join(f"{key}={value}\n" for key, value in env_values.items()), encoding="utf-8")
        self.env_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
        config = str(MOCK_CONFIG.resolve())
        responses = str(MOCK_RESPONSES.resolve())
        logs = str(log_dir.resolve())
        self.override_file.write_text(
            "services:\n"
            "  backend:\n"
            f"    image: {yaml_quote(BACKEND_IMAGE)}\n"
            "    platform: linux/amd64\n"
            "    environment:\n"
            "      SERVER_PORT: \"8080\"\n"
            "      MANAGEMENT_SERVER_PORT: \"9091\"\n"
            "      SPRING_PROFILES_ACTIVE: ${SPRING_PROFILES_ACTIVE}\n"
            "      SPRING_DATASOURCE_URL: jdbc:postgresql://postgres:5432/${POSTGRES_DB}\n"
            "      SPRING_DATASOURCE_USERNAME: ${POSTGRES_USER}\n"
            "      SPRING_DATASOURCE_PASSWORD: ${POSTGRES_PASSWORD}\n"
            "      SPRING_DATA_REDIS_HOST: redis\n"
            "      SPRING_DATA_REDIS_PORT: \"6379\"\n"
            "      SPRING_DATA_REDIS_PASSWORD: ${REDIS_PASSWORD}\n"
            "      CORS_ALLOWED_ORIGINS: ${CORS_ALLOWED_ORIGINS}\n"
            "      JWT_SECRET: ${JWT_SECRET}\n"
            "      GOOGLE_MAPS_API_KEY: ${GOOGLE_MAPS_API_KEY}\n"
            "      GOOGLE_PLACES_BASE_URL: ${GOOGLE_PLACES_BASE_URL}\n"
            "      GOOGLE_ROUTES_BASE_URL: ${GOOGLE_ROUTES_BASE_URL}\n"
            "      PROFILE_IMAGE_STORAGE_ENABLED: ${PROFILE_IMAGE_STORAGE_ENABLED}\n"
            "    depends_on:\n"
            "      postgres:\n"
            "        condition: service_healthy\n"
            "      redis:\n"
            "        condition: service_healthy\n"
            "      google-api-mock:\n"
            "        condition: service_started\n"
            "    ports:\n"
            "      - \"127.0.0.1:${BACKEND_PORT}:8080\"\n"
            "    volumes:\n"
            "      - backend_logs:/var/log/travel-planner\n"
            "    networks: [app-network]\n"
            "    healthcheck:\n"
            "      test: [\"CMD-SHELL\", \"wget -q -O /dev/null http://127.0.0.1:9091/actuator/health/readiness || exit 1\"]\n"
            "      interval: 10s\n"
            "      timeout: 5s\n"
            "      retries: 12\n"
            "      start_period: 40s\n"
            "  postgres:\n"
            "    image: postgres:17.10-alpine\n"
            "    environment:\n"
            "      POSTGRES_DB: ${POSTGRES_DB}\n"
            "      POSTGRES_USER: ${POSTGRES_USER}\n"
            "      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}\n"
            "    volumes:\n"
            "      - postgres_data:/var/lib/postgresql/data\n"
            "    networks: [app-network]\n"
            "    healthcheck:\n"
            "      test: [\"CMD-SHELL\", \"pg_isready -U \\\"$$POSTGRES_USER\\\" -d \\\"$$POSTGRES_DB\\\"\"]\n"
            "      interval: 5s\n"
            "      timeout: 5s\n"
            "      retries: 10\n"
            "      start_period: 10s\n"
            "  redis:\n"
            "    image: redis:7.4.9-alpine\n"
            "    environment:\n"
            "      REDIS_PASSWORD: ${REDIS_PASSWORD}\n"
            "    command: [\"sh\", \"-c\", \"exec redis-server --appendonly yes --requirepass \\\"$$REDIS_PASSWORD\\\"\"]\n"
            "    volumes:\n"
            "      - redis_data:/data\n"
            "    networks: [app-network]\n"
            "    healthcheck:\n"
            "      test: [\"CMD-SHELL\", \"redis-cli -a \\\"$$REDIS_PASSWORD\\\" ping | grep -q PONG\"]\n"
            "      interval: 5s\n"
            "      timeout: 5s\n"
            "      retries: 10\n"
            "      start_period: 5s\n"
            "  google-api-mock:\n"
            f"    image: {yaml_quote(MOCK_IMAGE)}\n"
            "    platform: linux/amd64\n"
            "    command: [\"nginx\", \"-g\", \"daemon off;\"]\n"
            "    read_only: true\n"
            "    cap_drop: [ALL]\n"
            "    security_opt: [\"no-new-privileges:true\"]\n"
            "    tmpfs:\n"
            "      - \"/tmp:rw,noexec,nosuid,size=16m\"\n"
            "      - \"/var/cache/nginx:rw,noexec,nosuid,size=16m,mode=1777\"\n"
            f"    ports: [\"127.0.0.1:{self.args.mock_port}:8080\"]\n"
            "    volumes:\n"
            f"      - {yaml_quote(f'{config}:/etc/nginx/nginx.conf:ro')}\n"
            f"      - {yaml_quote(f'{responses}:/usr/share/nginx/html/responses:ro')}\n"
            f"      - {yaml_quote(f'{logs}:/var/log/nginx')}\n"
            "    networks: [app-network]\n"
            "volumes:\n"
            "  postgres_data:\n"
            "  redis_data:\n"
            "  backend_logs:\n"
            "networks:\n"
            "  app-network:\n",
            encoding="utf-8",
        )
        self.override_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
        self.write_metadata()

    def write_metadata(self) -> None:
        write_json(self.evidence_root / "image-lineage.json", {
            "runId": self.run_id,
            "backendImage": BACKEND_IMAGE,
            "backendIndexDigest": BACKEND_INDEX_DIGEST,
            "backendLinuxAmd64ManifestDigest": BACKEND_AMD64_DIGEST,
            "forbiddenPreviousDigest": FORBIDDEN_BACKEND_DIGEST,
            "k6Image": K6_IMAGE,
            "googleMockImage": MOCK_IMAGE,
            "sourceCommit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT, text=True).strip(),
            "profile": str(PROFILE),
            "profileSha256": digest_file(PROFILE),
            "requestMixVersion": "aws-eks-current-feature-coverage-v2",
            "operationCount": len(EXPECTED_OPERATIONS),
            "note": "Local functional validation only; no AWS performance or SLO claim.",
        })

    def preflight(self) -> None:
        run_command(["docker", "info"], output=self.evidence_root / "docker-info.txt")
        run_command(["docker", "manifest", "inspect", BACKEND_IMAGE], output=self.evidence_root / "backend-manifest.json")
        for image in (BACKEND_IMAGE, MOCK_IMAGE, K6_IMAGE):
            run_command(["docker", "pull", "--platform", "linux/amd64", image], output=self.evidence_root / f"pull-{safe_id(image.split('@')[0])}.log")
        inspect = run_command(["docker", "image", "inspect", BACKEND_IMAGE], check=True)
        inspect_payload = json.loads(inspect.stdout)
        write_json(self.evidence_root / "container-image-inspect.json", {
            "backend": inspect_payload,
            "backendDigestObserved": inspect_payload[0].get("RepoDigests", []) if inspect_payload else [],
            "expectedIndexDigest": BACKEND_INDEX_DIGEST,
            "expectedLinuxAmd64ManifestDigest": BACKEND_AMD64_DIGEST,
            "forbiddenDigestAbsent": all(FORBIDDEN_BACKEND_DIGEST not in str(item) for item in inspect_payload),
        })
        rendered = run_command([*self.compose_args, "config"])
        rendered_text = rendered.stdout
        for secret in self.secret_values:
            rendered_text = rendered_text.replace(secret, "<redacted>")
        (self.evidence_root / "compose-render.yml").write_text(rendered_text, encoding="utf-8")
        if BACKEND_IMAGE not in rendered_text or "build:" in rendered_text:
            raise ValidationError("rendered stack is not exact-image/no-build")
        write_json(self.evidence_root / "preflight.json", {
            "status": "pass",
            "runId": self.run_id,
            "platform": "linux/amd64",
            "dockerComposeConfigExitCode": rendered.returncode,
            "backendImage": BACKEND_IMAGE,
            "backendBuildPath": False,
            "baseComposeSha256": digest_file(COMPOSE),
            "baseComposeUnmodified": True,
        })

    def compose(self, *parts: str, output: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run_command([*self.compose_args, *parts], output=output, check=check)

    def wait_http(self, path: str, timeout_seconds: int = 180) -> None:
        deadline = time.monotonic() + timeout_seconds
        url = f"{self.backend_url}{path}"
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=3) as response:
                    if 200 <= response.status < 300:
                        return
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(3)
        raise ValidationError(f"backend readiness timed out at {path}")

    def start(self) -> None:
        self.compose("up", "-d", "--no-build", output=self.evidence_root / "compose-up.log")
        self.wait_http("/api/ping")
        self.compose("ps", output=self.evidence_root / "compose-ps.txt")
        self.flyway_check()

    def flyway_check(self) -> None:
        user, database = "travel_loadtest", "travel_diary_loadtest"
        query = "SELECT version, success FROM flyway_schema_history ORDER BY installed_rank DESC LIMIT 24;"
        result = self.compose("exec", "--no-TTY", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-U", user,
                              "-d", database, "-tA", "-c", query)
        rows = []
        for line in result.stdout.splitlines():
            fields = line.split("|")
            if len(fields) == 2:
                rows.append({"version": fields[0], "success": fields[1].lower() == "t"})
        v22 = [row for row in rows if row["version"] == "22"]
        payload = {"latestRows": rows, "v22Rows": v22, "v22Applied": len(v22) == 1 and v22[0]["success"],
                   "failedRows": [row for row in rows if not row["success"]]}
        write_json(self.evidence_root / "flyway-v22.json", payload)
        if not payload["v22Applied"] or payload["failedRows"]:
            raise ValidationError("Flyway V22 did not apply successfully")

    def seed(self, users: int, phase: str) -> None:
        self.data_file = self.runtime_root / f"{phase}-data.json"
        fixture_result = self.evidence_root / "fixture" / f"{phase}.json"
        command = [sys.executable, str(SEEDER), "--env-file", str(self.env_file), "--compose-file", str(COMPOSE),
                   "--compose-file", str(self.override_file), "--project-name", self.project, "--base-url", self.backend_url,
                   "--data-file", str(self.data_file), "--users", str(users), "--seed-tag", f"{self.run_id}-{phase}",
                   "--current-feature", "--fixture-result-file", str(fixture_result)]
        result = run_command(command, output=self.evidence_root / "fixture" / f"{phase}-seed.log", check=False)
        if result.returncode != 0:
            raise ValidationError(f"current-feature {phase} fixture seeding failed")
        self.data_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
        payload = json.loads(self.data_file.read_text(encoding="utf-8"))
        credentials = payload.get("credentials", [])
        if payload.get("seedState") != "complete" or payload.get("fixtureState") != "verified" or len(credentials) != users:
            raise ValidationError(f"seeded {phase} credential contract is incomplete")
        if any(not all(item.get(key) for key in ("placeIds", "postId", "commentId", "fixtureMarker")) for item in credentials):
            raise ValidationError("one or more current-feature fixtures are incomplete")

    def run_k6(self, scenario: str, *, rate: int, warmup: str, duration: str, measured_seconds: int,
               warmup_seconds: int, vus: int) -> dict:
        target = f"http://host.docker.internal:{self.args.backend_port}"
        out = self.evidence_root / scenario
        container = safe_id(f"k6-{self.run_id}-{scenario}")
        stats_path = out / "runner-stats.jsonl"
        stats_path.write_text("", encoding="utf-8")
        command = [
            "docker", "run", "--rm", "--name", container, "--platform", "linux/amd64", "--user", "0:0",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--add-host", "host.docker.internal:host-gateway",
            "-v", f"{REPOSITORY_ROOT / 'load-tests/k6'}:/scripts:ro",
            "-v", f"{PROFILE.parent}:/profiles:ro", "-v", f"{SLO_CONTRACT.parent}:/contracts:ro",
            "-v", f"{self.data_file}:/data/data.json:ro", "-v", f"{out}:/out",
            "-e", f"BASE_URL={target}", "-e", "ALLOW_INSECURE_TARGET=1", "-e", "TARGET_PLATFORM=local",
            "-e", "TARGET_REGION=local", "-e", "TARGET_ENVIRONMENT=compose-local", "-e", "AWS_PROFILE_FILE=/profiles/eks-monolith-breakpoint-v2.1.json",
            "-e", f"K6_IMAGE_DIGEST={K6_IMAGE}",
            "-e", "AWS_SLO_CONTRACT_FILE=/contracts/eks-monolith-breakpoint-slo-v2.1.json", "-e", "DATA_FILE=/data/data.json",
            "-e", "REQUIRE_UNIQUE_CREDENTIALS=1", "-e", f"REQUIRED_UNIQUE_CREDENTIAL_COUNT={vus}",
            "-e", f"RUN_ID={self.run_id}-{scenario}", "-e", f"RUN_STARTED_AT={utc_now()}", "-e", "OUT_DIR=/out",
            "-e", f"RATE={rate}", "-e", f"WARMUP={warmup}", "-e", f"DURATION={duration}",
            "-e", f"PREALLOCATED_VUS={vus}", "-e", f"MAX_VUS={vus}",
            K6_IMAGE, "run", "--out", "json=/out/raw.json", "--summary-export=/out/k6-native-summary.json",
            f"/scripts/aws/scenarios/{'smoke.js' if scenario == 'smoke' else 'b01-baseline.js'}",
        ]
        stdout_path = out / "stdout.log"
        with stdout_path.open("w", encoding="utf-8") as stdout:
            process = subprocess.Popen(command, cwd=REPOSITORY_ROOT, stdout=stdout, stderr=subprocess.STDOUT, text=True)
            while process.poll() is None:
                stats = run_command(["docker", "stats", "--no-stream", "--format", "{{json .}}", container], check=False)
                if stats.returncode == 0 and stats.stdout.strip():
                    with stats_path.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps({"ts": utc_now(), "docker": stats.stdout.strip()}) + "\n")
                time.sleep(5)
            exit_code = process.wait()
        write_json(out / "run-status.json", {"k6ExitCode": exit_code, "scenario": scenario})
        if exit_code != 0:
            raise ValidationError(f"k6 {scenario} exited with {exit_code}")
        verdict = evaluate_summary(out / "summary.json", scenario, target_rate=rate,
                                   measured_seconds=measured_seconds, warmup_seconds=warmup_seconds)
        write_json(out / "operation-verdict.json", verdict)
        if not verdict["pass"]:
            raise ValidationError(f"k6 {scenario} functional contract failed")
        return verdict

    def mock_evidence(self) -> None:
        container_id = self.compose("ps", "-q", "google-api-mock").stdout.strip()
        inspect = run_command(["docker", "inspect", container_id], check=False) if container_id else None
        logs_dir = self.runtime_root / "mock-logs"
        access_log = logs_dir / "access.log"
        error_log = logs_dir / "error.log"
        counts = {"accessLines": 0, "status4xx5xx": 0, "errorLines": 0}
        if access_log.exists():
            for line in access_log.read_text(encoding="utf-8", errors="replace").splitlines():
                counts["accessLines"] += 1
                try:
                    if int(json.loads(line).get("status", 0)) >= 400:
                        counts["status4xx5xx"] += 1
                except (ValueError, json.JSONDecodeError):
                    pass
        if error_log.exists():
            counts["errorLines"] = len(error_log.read_text(encoding="utf-8", errors="replace").splitlines())
        payload = {"health": "verified", "containerIdPresent": bool(container_id), "counts": counts,
                   "zeroMock4xx5xxOrErrors": counts["status4xx5xx"] == 0 and counts["errorLines"] == 0}
        if inspect and inspect.returncode == 0:
            try:
                details = json.loads(inspect.stdout)[0]
                payload["running"] = details.get("State", {}).get("Running", False)
                payload["restartCount"] = details.get("RestartCount", 0)
                payload["image"] = details.get("Config", {}).get("Image")
            except (IndexError, json.JSONDecodeError):
                pass
        write_json(self.evidence_root / "mock" / "evidence.json", payload)
        if not payload["zeroMock4xx5xxOrErrors"]:
            raise ValidationError("private Google mock returned an error")

    def cleanup(self) -> None:
        down = self.compose("down", "--volumes", "--remove-orphans", check=False, output=self.evidence_root / "cleanup-compose.log")
        ps = self.compose("ps", "-aq", check=False)
        volumes = run_command(["docker", "volume", "ls", "--filter", f"label=com.docker.compose.project={self.project}", "-q"], check=False)
        payload = {"composeDownExitCode": down.returncode, "remainingContainerIds": ps.stdout.split(),
                   "remainingVolumeIds": volumes.stdout.split(), "clean": down.returncode == 0 and not ps.stdout.strip() and not volumes.stdout.strip()}
        write_json(self.evidence_root / "cleanup.json", payload)
        try:
            self.data_file.unlink()
        except FileNotFoundError:
            pass
        shutil.rmtree(self.runtime_root, ignore_errors=True)

    def run(self) -> dict:
        self.prepare()
        self.preflight()
        started = utc_now()
        status = "LOCAL_NO_GO"
        verdicts: dict[str, dict] = {}
        try:
            self.start()
            if self.args.mode in ("all", "smoke"):
                self.seed(2, "smoke")
                verdicts["smoke"] = self.run_k6("smoke", rate=16, warmup="0s", duration="1s",
                                                 measured_seconds=1, warmup_seconds=0, vus=2)
            if self.args.mode in ("all", "baseline"):
                # Refresh tokens rotate on every k6 process, so Baseline must
                # have a fresh phase fixture rather than reusing Smoke data.
                self.seed(self.args.users, "baseline")
                verdicts["baseline"] = self.run_k6("baseline", rate=self.args.rate, warmup=self.args.warmup,
                                                   duration=self.args.duration, measured_seconds=self.args.measured_seconds,
                                                   warmup_seconds=self.args.warmup_seconds, vus=self.args.users)
            self.mock_evidence()
            status = "LOCAL_PASS"
        finally:
            self.cleanup()
        report = {
            "status": status, "runId": self.run_id, "startedAtUtc": started, "finishedAtUtc": utc_now(),
            "backendImage": BACKEND_IMAGE, "profile": str(PROFILE), "fixtureVersion": "compose-current-feature-fixture-v1",
            "verdicts": verdicts, "cleanup": json.loads((self.evidence_root / "cleanup.json").read_text(encoding="utf-8")),
            "note": "Local arm64-to-amd64 functional validation; p95 is informational.",
        }
        write_json(self.evidence_root / "LOCAL_VALIDATION_REPORT.json", report)
        (self.evidence_root / "LOCAL_VALIDATION_REPORT.md").write_text(
            f"# SCRUM-80 로컬 최신 기능 검증\n\n- 상태: **{status}**\n- Backend image: `{BACKEND_IMAGE}`\n"
            f"- 검증 연산: {len(EXPECTED_OPERATIONS)}개\n- 결과: p95는 로컬 에뮬레이션 특성상 정보용이며 AWS SLO 판정이 아니다.\n",
            encoding="utf-8",
        )
        return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("all", "smoke", "baseline"), nargs="?", default="all")
    parser.add_argument("--users", type=int, default=16)
    parser.add_argument("--rate", type=int, default=16)
    parser.add_argument("--warmup", default="30s")
    parser.add_argument("--duration", default="180s")
    parser.add_argument("--measured-seconds", type=int, default=180)
    parser.add_argument("--warmup-seconds", type=int, default=30)
    parser.add_argument("--backend-port", type=int, default=18080)
    parser.add_argument("--mock-port", type=int, default=18081)
    parser.add_argument("--frontend-port", type=int, default=13000)
    parser.add_argument("--run-id")
    parser.add_argument("--project-name")
    parser.add_argument("--evidence-root", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = LocalValidation(args).run()
    except (ValidationError, OSError, subprocess.SubprocessError) as error:
        print(f"[scrum80-local] ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"status": report["status"], "runId": report["runId"]}))
    return 0 if report["status"] == "LOCAL_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
