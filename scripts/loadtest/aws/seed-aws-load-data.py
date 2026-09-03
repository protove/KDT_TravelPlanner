#!/usr/bin/env python3
"""Seed idempotent, Run ID-tagged synthetic data for AWS B-01 load tests.

This is the AWS counterpart to ../seed-compose-load-data.py. It does not
reuse that script directly because the connection surface is different:
Compose execs into containers on the same host (`docker compose exec`),
while this runs from the AWS Load Runner EC2 against the shared dev RDS
PostgreSQL and ElastiCache Redis over the private VPC network described in
aws-load-test-handoff/plans/02_AWS_LOAD_RUNNER_INFRA_PLAN.md.

The Runner's user-data installs only Docker and pre-pulls the k6 image (see
infra/modules/load_test_runner/templates/runner-user-data.sh.tftpl) — no
psql or redis-cli binary is installed on the host. This script therefore
shells out to short-lived `docker run --rm --network host <official image>`
containers for both the PostgreSQL and Redis clients, matching the "plus
DockerHub" allowance already carved into the Runner's HTTPS egress rule
(infra/modules/runtime_security/main.tf, load_runner_https).

Every row this script creates is tagged with --run-id (see
aws-load-test-handoff/contracts/RUN_METADATA_CONTRACT.md). Re-running with
the same --run-id is safe and idempotent:
  * user_table rows use `INSERT ... ON CONFLICT (provider, provider_user_id)
    DO NOTHING` (that pair has a UNIQUE constraint — see
    backend/src/main/resources/db/migration/V1__create_user_table.sql).
  * A synthetic user whose owner already has a planners_table row is
    treated as fully seeded and skipped, so a retry after a partial
    failure never creates a second travel/timeline set for the same user.

Account safety: this script executes real `aws` CLI commands (sts, Secrets
Manager) against whatever account the Runner's credentials resolve to. Per
RUN_METADATA_CONTRACT.md it refuses to run unless the observed account
matches --expected-account-id exactly, and it never prints a full account
ID, Secrets Manager ARN content, or database/Redis password to stdout or
stderr.

Credential contract (D-001-R1 후속, aws-load-test-handoff/decisions/DECISION_LOG.md
"Seed/Cleanup 최소권한"): this script never reads the RDS master secret or
the backend's shared Redis AUTH secret. --database-secret-arn must point to
a dedicated, least-privilege test-only Secret with the JSON shape
{"username": "...", "password": "..."} (both fields required — the DB
username comes from the secret now, not a separate flag). Redis uses
ElastiCache RBAC with IAM authentication instead of a Secret at all:
--redis-iam-user is the RBAC username (Terraform-provisioned, not secret)
and --redis-replication-group-id is the ElastiCache replication group ID
the IAM auth token is signed for. The actual DB role and Redis RBAC
user/Secret are created by the Infra owner (console or approved IaC), not
by this script.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import ipaddress
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlencode, urlsplit

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from refresh_credential_lifecycle import (  # noqa: E402
    CredentialLifecycleError,
    revoke_credential_file,
)

DEFAULT_REFRESH_TTL_MS = 4 * 60 * 60 * 1000  # 4h — short-lived by design; this is a shared, persistent store
# Keep the run-id contract aligned with the lifecycle's timestamped IDs.  A
# 40-character cap rejected otherwise safe SCRUM-80 IDs by one character
# before any fixture mutation; 64 leaves room for the Jira/campaign prefix
# while preserving the allow-list (letters, digits, hyphens only).
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,64}$")
FIXTURE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
ACCOUNT_ID_PATTERN = re.compile(r"^\d{12}$")
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
REDIS_TOKEN_HASH_PATTERN = re.compile(r"^[a-f0-9]{64}$")
POSTGRES_CLIENT_IMAGE = "postgres:17-alpine"
REDIS_CLIENT_IMAGE = "redis:7-alpine"
EXPECTED_TIMELINE_ITEMS_PER_PLANNER = 3
# The current-feature workload needs one deterministic Place fixture per
# seeded timeline item plus one post/comment pair per credential.  These are
# created through the authenticated API so the seed role keeps its existing
# planner-only database permissions; cleanup remains user-scoped and cascades
# the community rows.
CURRENT_FEATURE_FIXTURE_VERSION = "aws-current-feature-fixture-v1"
CURRENT_FEATURE_PLACE_IDS_PER_TRAVEL = EXPECTED_TIMELINE_ITEMS_PER_PLANNER
# The adaptive EKS breakpoint tops up one deterministic credential per VU.
# Keep a generous operational bound; the lifecycle capsule still supplies a
# lower accepted fixture/data guard at action time.
MAX_SYNTHETIC_USERS = 100000
# A preceding adaptive stage can leave several Backend/HPA connection pools
# draining while the next fixture top-up begins.  PostgreSQL reports this as
# a transient reserved-slot failure; retry only that bounded, sanitized class
# rather than turning a recoverable hand-off into an incomplete campaign.
PSQL_TRANSIENT_RETRY_ATTEMPTS = 8
PSQL_TRANSIENT_RETRY_BASE_SECONDS = 2.0
PSQL_TRANSIENT_RETRY_MAX_SECONDS = 10.0
PSQL_TRANSIENT_ERROR_MARKERS = (
    "remaining connection slots are reserved",
    "too many clients already",
)


class SeedError(RuntimeError):
    """A sanitized seed or contract verification failure."""


class SecretContractError(SeedError):
    """The Secrets Manager value did not match the expected {username,
    password} test-credential contract. Distinguished from other SeedErrors
    with its own exit code (2) so an operator can tell "the wrong secret is
    wired in" apart from "the DB/Redis/API itself failed" (1) at a glance."""


@contextlib.contextmanager
def resolved_target_host(host: str):
    """Temporarily resolve a private Runner's HTTPS target to ALB IPs.

    The approved custom hostname stays in the URL so TLS SNI and the HTTP
    Host header remain correct. ``AWS_TARGET_HOST_IPS`` is populated by the
    Runner-side ALB verification; replacing only ``getaddrinfo`` avoids
    persistent host-file changes and is scoped to this seed process. Without
    the mapping, urllib keeps its normal DNS behavior.
    """
    raw_ips = os.environ.get("AWS_TARGET_HOST_IPS", "")
    ips = [value.strip() for value in raw_ips.split(",") if value.strip()]
    if not ips:
        yield
        return
    for value in ips:
        try:
            parsed = ipaddress.ip_address(value)
        except ValueError as error:
            raise SeedError("AWS_TARGET_HOST_IPS contains an invalid IP address") from error
        if parsed.version != 4:
            raise SeedError("AWS_TARGET_HOST_IPS must contain IPv4 addresses")

    original_getaddrinfo = socket.getaddrinfo

    def mapped_getaddrinfo(requested_host, port, family=0, type=0, proto=0, flags=0):
        if requested_host != host:
            return original_getaddrinfo(requested_host, port, family, type, proto, flags)
        if family not in (0, socket.AF_INET):
            return original_getaddrinfo(requested_host, port, family, type, proto, flags)
        socket_type = type or socket.SOCK_STREAM
        socket_proto = proto or socket.IPPROTO_TCP
        return [
            (socket.AF_INET, socket_type, socket_proto, "", (value, port))
            for value in ips
        ]

    socket.getaddrinfo = mapped_getaddrinfo
    try:
        yield
    finally:
        socket.getaddrinfo = original_getaddrinfo


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def new_opaque_token() -> str:
    token = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")
    if not TOKEN_PATTERN.fullmatch(token):
        raise SeedError("generated opaque token has an invalid format")
    return token


def provider_user_id(run_id: str, index: int, index_width: int = 3) -> str:
    """Deterministic per (run_id, index) — this is what makes seeding
    idempotent and what cleanup-aws-load-data.py filters on."""
    if index_width < 3 or index_width > 6:
        raise SeedError("index_width must be between 3 and 6")
    if index < 1 or index >= 10 ** index_width:
        raise SeedError("index does not fit the registered provider ID width")
    return f"loadtest-aws-{run_id}-{index:0{index_width}d}"[:255]


def provider_user_id_regex(run_id: str, index_width: int = 3) -> str:
    """Match only this run's complete synthetic provider-user ID.

    A prefix-only LIKE predicate would make ``run-a`` overlap ``run-a-x``.
    The provider ID contract terminates in the registered index width, so an
    anchored PostgreSQL regular expression gives reset and count one exact
    ownership boundary without accepting a longer Run ID.
    """
    if index_width < 3 or index_width > 6:
        raise SeedError("index_width must be between 3 and 6")
    return f"^loadtest-aws-{run_id}-[0-9]{{{index_width}}}$"


def synthetic_email(run_id: str, index: int, index_width: int = 3) -> str:
    # @loadtest.local matches the synthetic_email pattern already scanned by
    # scripts/loadtest/verify-evidence-safety.py, so existing evidence
    # scanning covers AWS runs without changes.
    return f"{provider_user_id(run_id, index, index_width)}@loadtest.local"


def synthetic_nickname(run_id: str, index: int, index_width: int = 3) -> str:
    # nickname has its own UNIQUE constraint and a 30-char limit; derive it
    # from run_id so re-seeding the same run_id/index is deterministic.
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:10]
    return f"lt{digest}{index:0{index_width}d}"[:30]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, help="RUN_METADATA_CONTRACT runId; tags every row this run creates")
    parser.add_argument("--users", type=int, default=80)
    parser.add_argument("--expected-account-id", required=True, help="12-digit AWS account ID this run is approved to target")
    parser.add_argument("--region", required=True)
    parser.add_argument("--database-host", required=True)
    parser.add_argument("--database-port", type=int, default=5432)
    parser.add_argument("--database-name", required=True)
    parser.add_argument("--database-secret-arn", required=True, help="Secrets Manager ARN of the dedicated test-only DB Secret, JSON {\"username\":..,\"password\":..} (never the RDS master secret)")
    parser.add_argument("--redis-host", required=True)
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument("--redis-iam-user", required=True, help="ElastiCache RBAC username this Runner authenticates as via IAM (never the shared default-user AUTH token)")
    parser.add_argument("--redis-replication-group-id", required=True, help="ElastiCache replication group ID the IAM auth token is signed for")
    parser.add_argument("--base-url", required=True, help="ALB HTTPS base URL, e.g. https://api.kdt-travelplanner.protove.net")
    parser.add_argument("--data-file", type=Path, required=True, help="Where to write synthetic credentials (0600); cleanup-aws-load-data.py reads this to remove exact Redis keys")
    parser.add_argument("--reset-fixture", action="store_true", help="Delete this run's synthetic planners (and cascaded timeline rows) before seeding")
    parser.add_argument("--fixture-id", default="seed", help="Sanitized phase fixture identifier recorded in evidence")
    parser.add_argument("--fixture-result-file", type=Path, help="Optional sanitized phase fixture evidence JSON path")
    parser.add_argument("--refresh-ttl-ms", type=int, default=DEFAULT_REFRESH_TTL_MS)
    parser.add_argument("--index-width", type=int, default=3, help="Zero-padded provider ID width (3-6; default 3)")
    parser.add_argument("--incremental", action="store_true", help="Top up an existing verified run fixture without reset/revocation")
    parser.add_argument(
        "--refresh-tokens-only",
        action="store_true",
        help="Rotate only the existing verified credential ledger; do not inspect or create user/travel fixtures",
    )
    return parser.parse_args()


def run(command: list[str], *, env: dict[str, str] | None = None, input_text: str | None = None) -> str:
    completed = subprocess.run(
        command, input=input_text, capture_output=True, text=True, env=env, check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()[-1:] or ["command failed"]
        raise SeedError(f"command failed ({completed.returncode}): {' '.join(command[:3])}; {detail[0]}")
    return completed.stdout


def verify_account(expected_account_id: str, region: str) -> None:
    if not ACCOUNT_ID_PATTERN.fullmatch(expected_account_id):
        raise SeedError("--expected-account-id must be exactly 12 digits")
    completed = subprocess.run(
        ["aws", "sts", "get-caller-identity", "--region", region, "--query", "Account", "--output", "text"],
        capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0:
        raise SeedError("sts:GetCallerIdentity failed; cannot verify the target AWS account")
    # Never print the observed or expected account ID (RUN_METADATA_CONTRACT.md):
    # only the last 4 digits + a SHA-256 belong in metadata, and this script
    # doesn't even write metadata — it just refuses to run on a mismatch.
    if completed.stdout.strip() != expected_account_id:
        raise SeedError("observed AWS account does not match --expected-account-id; refusing to run")


def read_secret_credential(secret_arn: str, region: str) -> tuple[str, str]:
    """Returns (username, password) from a dedicated test-only Secret. Never
    call this with an RDS master or shared-Redis-AUTH secret ARN — those use
    a different JSON shape on purpose, and this function's strict
    username+password requirement makes accidentally wiring one of those in
    fail loudly (SecretContractError) instead of silently."""
    completed = subprocess.run(
        [
            "aws", "secretsmanager", "get-secret-value",
            "--secret-id", secret_arn, "--region", region,
            "--query", "SecretString", "--output", "text",
        ],
        capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0:
        raise SeedError("failed to read a Secrets Manager value")  # sanitized: no ARN or stderr detail
    raw = completed.stdout.strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SecretContractError("Secrets Manager value is not valid JSON") from error
    username = payload.get("username")
    password = payload.get("password")
    if not isinstance(username, str) or not username:
        raise SecretContractError("Secrets Manager value has no 'username' field (wrong secret? this must be a dedicated test-only credential)")
    if not isinstance(password, str) or not password:
        raise SecretContractError("Secrets Manager value has no 'password' field")
    return username, password


def generate_redis_iam_auth_token(user_name: str, replication_group_id: str, region: str) -> str:
    """Signs a short-lived (15 min) ElastiCache IAM auth token for RBAC
    username `user_name`, following AWS's documented technique for
    IAM-authenticated Redis OSS access: a SigV4-presigned "connect" request
    against a fake https://<replication-group-id>/ URL, with the scheme
    stripped before use as the redis-cli AUTH password. This never touches
    Secrets Manager and the token is never written to disk or logged — it is
    only ever passed to redis-cli via the REDISCLI_AUTH environment
    variable, mirroring how the (now-removed) Redis AUTH secret password was
    handled."""
    try:
        import botocore.session
        from botocore.auth import SigV4QueryAuth
        from botocore.awsrequest import AWSRequest
    except ImportError as error:
        raise SeedError(
            "botocore is required for Redis IAM authentication but is not installed "
            "(infra/modules/load_test_runner/templates/runner-user-data.sh.tftpl should have pip-installed it)"
        ) from error
    session = botocore.session.get_session()
    credentials = session.get_credentials()
    if credentials is None:
        raise SeedError("no AWS credentials available to sign the Redis IAM auth token")
    # AWS documents Redis IAM auth as a SigV4-signed GET whose Action/User
    # values are query parameters. AWSRequest supplies the headers mapping
    # Botocore expects; passing a hand-built RequestSigner dictionary with a
    # body fails before a request can be signed.
    query = urlencode({"Action": "connect", "User": user_name})
    request = AWSRequest(method="GET", url=f"https://{replication_group_id}/?{query}")
    SigV4QueryAuth(credentials, "elasticache", region, expires=900).add_auth(request)
    return request.url.removeprefix("https://")


def redis_refresh_token_key(token_hash: str) -> str:
    if not REDIS_TOKEN_HASH_PATTERN.fullmatch(token_hash):
        raise SeedError("refusing to address a Redis key outside the refresh-token namespace")
    return f"auth:refresh:token:{token_hash}"


def redis_refresh_family_key(family_id: str) -> str:
    if not TOKEN_PATTERN.fullmatch(family_id):
        raise SeedError("refusing to address a Redis key outside the refresh-family namespace")
    return f"auth:refresh:family:{family_id}"


class AwsSeed:
    def __init__(self, args: argparse.Namespace, database_username: str, database_password: str) -> None:
        self.args = args
        self.database_username = database_username
        self.database_password = database_password
        self.base_url = args.base_url.rstrip("/")
        self.index_width = getattr(args, "index_width", 3)

    @staticmethod
    def current_feature_marker(run_id: str, index: int, index_width: int = 3) -> str:
        """Stable, searchable owner marker for one run/user community fixture."""
        return f"loadtest-aws-{run_id}-{index:0{index_width}d}"

    @staticmethod
    def current_feature_place_ids(run_id: str, index: int, index_width: int = 3) -> list[str]:
        """Return the exact Google Place IDs used by the mock-backed flows."""
        marker = AwsSeed.current_feature_marker(run_id, index, index_width)
        return [
            f"{marker}-place-{place_index:03d}"
            for place_index in range(1, CURRENT_FEATURE_PLACE_IDS_PER_TRAVEL + 1)
        ]

    def psql(self, sql: str) -> str:
        env = {**os.environ, "PGPASSWORD": self.database_password, "PGSSLMODE": "require"}
        command = [
            "docker", "run", "--rm", "--network", "host",
            "-e", "PGPASSWORD", "-e", "PGSSLMODE",
            POSTGRES_CLIENT_IMAGE, "psql",
            "-h", self.args.database_host, "-p", str(self.args.database_port),
            "-U", self.database_username, "-d", self.args.database_name,
            "-v", "ON_ERROR_STOP=1", "-tA", "-c", sql,
        ]
        for attempt in range(PSQL_TRANSIENT_RETRY_ATTEMPTS):
            try:
                return run(command, env=env)
            except SeedError as error:
                message = str(error)
                transient = any(marker in message for marker in PSQL_TRANSIENT_ERROR_MARKERS)
                if not transient or attempt == PSQL_TRANSIENT_RETRY_ATTEMPTS - 1:
                    raise
                delay = min(
                    PSQL_TRANSIENT_RETRY_BASE_SECONDS * (2**attempt),
                    PSQL_TRANSIENT_RETRY_MAX_SECONDS,
                )
                print(
                    f"[seed] transient PostgreSQL connection exhaustion; retry {attempt + 1}/"
                    f"{PSQL_TRANSIENT_RETRY_ATTEMPTS} in {delay:g}s",
                    file=sys.stderr,
                )
                time.sleep(delay)
        raise AssertionError("unreachable")

    def redis(self, *arguments: str) -> str:
        # Freshly signed per call (tokens are valid 15 minutes): seed runs are
        # short but this avoids any expiry-timing assumption entirely.
        auth_token = generate_redis_iam_auth_token(
            self.args.redis_iam_user, self.args.redis_replication_group_id, self.args.region,
        )
        env = {**os.environ, "REDISCLI_AUTH": auth_token}
        return run(
            [
                "docker", "run", "--rm", "--network", "host",
                "-e", "REDISCLI_AUTH",
                REDIS_CLIENT_IMAGE, "redis-cli",
                "-h", self.args.redis_host, "-p", str(self.args.redis_port),
                "--tls", "--no-auth-warning", "--user", self.args.redis_iam_user, *arguments,
            ],
            env=env,
        )

    def api(
        self, method: str, path: str, *,
        token: str | None = None, refresh_cookie: str | None = None, body: dict | None = None,
    ) -> tuple[int, dict, list[str]]:
        request = Request(f"{self.base_url}/api/v1{path}", method=method)
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        if refresh_cookie:
            request.add_header("Cookie", f"refresh_token={refresh_cookie}")
        payload = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            request.add_header("Content-Type", "application/json")
        try:
            host = urlsplit(request.full_url).hostname or ""
            with resolved_target_host(host):
                with urlopen(request, payload, timeout=15) as response:
                    return response.status, json.loads(response.read() or b"{}"), response.headers.get_all("Set-Cookie") or []
        except HTTPError as error:
            return error.code, {}, error.headers.get_all("Set-Cookie") or []
        except URLError as error:
            raise SeedError(f"API request failed: {error.reason}") from error

    def find_existing_user_id(self, run_id: str, index: int) -> str | None:
        index_width = getattr(self, "index_width", 3)
        result = self.psql(
            "SELECT id FROM user_table WHERE provider = 'GOOGLE' AND provider_user_id = "
            f"{sql_literal(provider_user_id(run_id, index, index_width))}"
        ).strip()
        return result or None

    def insert_user(self, run_id: str, index: int) -> tuple[str, bool]:
        """Returns (user_id, already_existed)."""
        index_width = getattr(self, "index_width", 3)
        existing = self.find_existing_user_id(run_id, index)
        if existing:
            return existing, True
        user_id = str(uuid.uuid4())
        insert_output = self.psql(
            "INSERT INTO user_table "
            "(id, provider, provider_user_id, email, name, nickname, profile_completed, created_at, updated_at) VALUES "
            f"({sql_literal(user_id)}, 'GOOGLE', {sql_literal(provider_user_id(run_id, index, index_width))}, "
            f"{sql_literal(synthetic_email(run_id, index, index_width))}, {sql_literal('LoadTest AWS ' + str(index))}, "
            f"{sql_literal(synthetic_nickname(run_id, index, index_width))}, TRUE, now(), now()) "
            "ON CONFLICT (provider, provider_user_id) DO NOTHING "
            "RETURNING id"
        )
        # psql can append a command-status line such as INSERT 0 1 even
        # with tuples-only output. The UUID was generated locally, so use the
        # RETURNING row only as proof that this process inserted it; never
        # pass the full stdout into Redis as the refresh-token user payload.
        returned_rows = {line.strip() for line in insert_output.splitlines() if line.strip()}
        if user_id in returned_rows:
            return user_id, False
        # Lost a race with another process seeding the same run_id/index; re-read.
        existing = self.find_existing_user_id(run_id, index)
        if not existing:
            raise SeedError("user insert reported no row and no existing row was found")
        return existing, True

    def has_existing_travel(self, user_id: str) -> bool:
        result = self.psql(f"SELECT id FROM planners_table WHERE owner_id = {sql_literal(user_id)} LIMIT 1").strip()
        return bool(result)

    def find_existing_travel(self, user_id: str) -> str | None:
        result = self.psql(
            f"SELECT id FROM planners_table WHERE owner_id = {sql_literal(user_id)} ORDER BY created_at LIMIT 1"
        ).strip()
        return result or None

    def find_existing_timeline_items(self, travel_id: str) -> list[str]:
        result = self.psql(
            f"SELECT id FROM timeline_table WHERE planner_id = {sql_literal(travel_id)} ORDER BY visit_order"
        ).strip()
        return [line for line in result.splitlines() if line]

    def reset_synthetic_planners(self, run_id: str) -> int:
        """Delete only this run's planners; FK cascades remove its fixture rows."""
        pattern = sql_literal(provider_user_id_regex(run_id, getattr(self, "index_width", 3)))
        result = self.psql(
            "WITH deleted AS ("
            "DELETE FROM planners_table WHERE owner_id IN ("
            "SELECT id FROM user_table WHERE provider = 'GOOGLE' AND provider_user_id ~ "
            f"{pattern}"
            ") RETURNING id) SELECT count(*) FROM deleted"
        ).strip()
        try:
            return int(result or "0")
        except ValueError as error:
            raise SeedError("fixture reset returned a non-integer planner count") from error

    def fixture_counts(self, run_id: str) -> dict[str, int]:
        """Return sanitized counts for this run's users, planners and seed rows.

        The current-feature workload legitimately creates unassigned timeline
        items while it runs.  Count only the deterministic ``seed-item-*``
        rows when proving the reusable fixture cardinality; otherwise a
        healthy Baseline makes the next adaptive stage look corrupted.
        """
        pattern = sql_literal(provider_user_id_regex(run_id, getattr(self, "index_width", 3)))
        result = self.psql(
            "WITH synthetic_users AS ("
            "SELECT id FROM user_table WHERE provider = 'GOOGLE' AND provider_user_id ~ "
            f"{pattern}), synthetic_planners AS ("
            "SELECT p.id FROM planners_table p JOIN synthetic_users u ON u.id = p.owner_id), "
            "planner_counts AS ("
            "SELECT p.id, count(t.id)::int AS item_count FROM synthetic_planners p "
            "LEFT JOIN timeline_table t ON t.planner_id = p.id "
            "AND t.day_number IS NOT NULL AND t.visit_date IS NOT NULL "
            "AND t.name LIKE 'seed-item-%' GROUP BY p.id) "
            "SELECT "
            "(SELECT count(*) FROM synthetic_users)::text || '|' || "
            "(SELECT count(*) FROM synthetic_planners)::text || '|' || "
            "(SELECT count(*) FROM timeline_table t JOIN synthetic_planners p ON p.id = t.planner_id "
            "AND t.day_number IS NOT NULL AND t.visit_date IS NOT NULL "
            "AND t.name LIKE 'seed-item-%')::text || '|' || "
            "COALESCE((SELECT min(item_count) FROM planner_counts), 0)::text || '|' || "
            "COALESCE((SELECT max(item_count) FROM planner_counts), 0)::text"
        ).strip()
        fields = result.split("|")
        if len(fields) != 5:
            raise SeedError("fixture verification returned an invalid count shape")
        try:
            users, planners, timeline_items, minimum, maximum = (int(field) for field in fields)
        except ValueError as error:
            raise SeedError("fixture verification returned a non-integer count") from error
        return {
            "users": users,
            "planners": planners,
            "timelineItems": timeline_items,
            "minimumTimelineItemsPerPlanner": minimum,
            "maximumTimelineItemsPerPlanner": maximum,
        }

    def seed_redis_token(
        self, user_id: str, ttl_ms: int, token: str | None = None, family_id: str | None = None,
    ) -> tuple[str, str]:
        token = token or new_opaque_token()
        family_id = family_id or new_opaque_token()
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        self.redis("SET", redis_refresh_token_key(token_hash), f"{user_id}|{family_id}", "PX", str(ttl_ms))
        self.redis("SET", redis_refresh_family_key(family_id), token_hash, "PX", str(ttl_ms))
        return token, family_id

    @staticmethod
    def rotated_cookie(set_cookies: list[str]) -> str | None:
        for header in set_cookies:
            first_part = header.split(";", 1)[0].strip()
            if first_part.startswith("refresh_token="):
                value = first_part.split("=", 1)[1]
                return value or None
        return None

    def refresh(self, token: str) -> tuple[str, str]:
        status, body, set_cookies = self.api("POST", "/auth/token/refresh", refresh_cookie=token)
        rotated = self.rotated_cookie(set_cookies)
        access_token = body.get("data", {}).get("accessToken") if isinstance(body, dict) else None
        if status != 200 or not isinstance(access_token, str) or not TOKEN_PATTERN.fullmatch(rotated or ""):
            raise SeedError(f"refresh contract failed with status {status}")
        return access_token, rotated  # type: ignore[return-value]

    def refresh_status(self, token: str) -> int:
        request = Request(f"{self.base_url}/api/v1/auth/token/refresh", method="POST")
        request.add_header("Cookie", f"refresh_token={token}")
        try:
            host = urlsplit(request.full_url).hostname or ""
            with resolved_target_host(host):
                with urlopen(request, timeout=15) as response:
                    return response.status
        except HTTPError as error:
            return error.code
        except URLError as error:
            raise SeedError("refresh-token family revocation request failed") from error

    def delete_exact_refresh_keys(self, keys: list[str]) -> int:
        if not keys:
            return 0
        result = self.redis("DEL", *keys).strip()
        try:
            return int(result or "0")
        except ValueError as error:
            raise SeedError("Redis DEL returned a non-integer result") from error

    def create_travel(self, access_token: str, index: int) -> str:
        status, body, _ = self.api(
            "POST", "/travels", token=access_token,
            body={"title": f"LoadTest AWS Travel {index}", "startDate": "2026-08-01", "endDate": "2026-08-05"},
        )
        travel_id = body.get("data", {}).get("travelId") if isinstance(body, dict) else None
        if status not in (200, 201) or not isinstance(travel_id, str):
            raise SeedError(f"travel creation contract failed with status {status}")
        return travel_id

    def create_timeline_items(self, access_token: str, travel_id: str) -> list[str]:
        item_ids: list[str] = []
        for visit_order in (1, 2, 3):
            place_ids = getattr(self, "_active_place_ids", [])
            status, body, _ = self.api(
                "POST", f"/travels/{travel_id}/timeline-items", token=access_token,
                body={
                    "dayNumber": 1, "visitDate": "2026-08-01", "category": "관광지",
                    "name": f"seed-item-{visit_order}", "visitOrder": visit_order,
                    "googlePlaceId": place_ids[visit_order - 1] if len(place_ids) >= visit_order else None,
                },
            )
            item_id = body.get("data", {}).get("timelineItemId") if isinstance(body, dict) else None
            if status not in (200, 201) or not isinstance(item_id, str):
                raise SeedError(f"timeline creation contract failed with status {status}")
            item_ids.append(item_id)
        return item_ids

    def _travel_detail(self, access_token: str, travel_id: str) -> dict:
        status, body, _ = self.api("GET", f"/travels/{travel_id}", token=access_token)
        data = body.get("data") if isinstance(body, dict) else None
        if status != 200 or not isinstance(data, dict):
            raise SeedError(f"current-feature travel fixture lookup failed with status {status}")
        return data

    def _ensure_place_ids(
        self,
        access_token: str,
        travel_id: str,
        timeline_ids: list[str],
        desired_place_ids: list[str],
        travel_detail: dict,
    ) -> None:
        if len(timeline_ids) < CURRENT_FEATURE_PLACE_IDS_PER_TRAVEL:
            raise SeedError("current-feature fixture requires three timeline items")
        timeline_by_id = {
            str(item.get("timelineItemId")): item
            for item in travel_detail.get("timelineItems", [])
            if isinstance(item, dict) and item.get("timelineItemId")
        }
        for item_id, place_id in zip(timeline_ids, desired_place_ids):
            current = timeline_by_id.get(str(item_id), {}).get("googlePlaceId")
            if current == place_id:
                continue
            status, _, _ = self.api(
                "PATCH",
                f"/travels/{travel_id}/timeline-items/{item_id}",
                token=access_token,
                body={"googlePlaceId": place_id},
            )
            if status != 200:
                raise SeedError(f"current-feature Place fixture update failed with status {status}")

    def _find_or_create_post(
        self,
        access_token: str,
        travel_id: str,
        marker: str,
    ) -> tuple[str, int]:
        status, body, _ = self.api(
            "GET",
            f"/community/me/posts?{urlencode({'keyword': marker, 'page': 0, 'size': 50})}",
            token=access_token,
        )
        data = body.get("data") if isinstance(body, dict) else None
        content = data.get("content", []) if isinstance(data, dict) else []
        post_id = None
        for item in content if isinstance(content, list) else []:
            if isinstance(item, dict) and marker in str(item.get("title", "")):
                post_id = item.get("postId")
                break
        if status != 200:
            raise SeedError(f"current-feature community fixture lookup failed with status {status}")
        if not isinstance(post_id, str) or not post_id:
            body_json = {
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": marker}]}],
            }
            status, body, _ = self.api(
                "POST",
                "/community/posts",
                token=access_token,
                body={
                    "categoryCode": "TRAVEL_REVIEW",
                    "title": f"{marker} travel review",
                    "bodyJson": body_json,
                    "tags": ["loadtest", marker[-12:]],
                    "sourceTravelId": travel_id,
                },
            )
            data = body.get("data") if isinstance(body, dict) else None
            post_id = data.get("postId") if isinstance(data, dict) else None
            if status not in (200, 201) or not isinstance(post_id, str) or not post_id:
                raise SeedError(f"current-feature community post creation failed with status {status}")

        status, body, _ = self.api("GET", f"/community/posts/{post_id}", token=access_token)
        data = body.get("data") if isinstance(body, dict) else None
        version = data.get("version") if isinstance(data, dict) else None
        if status != 200 or not isinstance(version, int):
            raise SeedError(f"current-feature community post detail failed with status {status}")
        return post_id, version

    def _find_or_create_comment(self, access_token: str, post_id: str, marker: str) -> str:
        status, body, _ = self.api("GET", f"/community/posts/{post_id}/comments", token=access_token)
        data = body.get("data") if isinstance(body, dict) else None
        comment_id = None
        for item in data if isinstance(data, list) else []:
            if isinstance(item, dict) and marker in str(item.get("content", "")):
                comment_id = item.get("commentId")
                break
        if status != 200:
            raise SeedError(f"current-feature community comment lookup failed with status {status}")
        if not isinstance(comment_id, str) or not comment_id:
            status, body, _ = self.api(
                "POST",
                f"/community/posts/{post_id}/comments",
                token=access_token,
                body={"content": f"{marker} comment"},
            )
            data = body.get("data") if isinstance(body, dict) else None
            comment_id = data.get("commentId") if isinstance(data, dict) else None
            if status not in (200, 201) or not isinstance(comment_id, str) or not comment_id:
                raise SeedError(f"current-feature community comment creation failed with status {status}")
        return comment_id

    def ensure_current_feature_fixture(
        self,
        access_token: str,
        run_id: str,
        index: int,
        travel_id: str,
        timeline_ids: list[str],
    ) -> dict:
        """Ensure all stateful current-feature requests have reusable IDs.

        The method is deliberately API-only for timeline/community data.  The
        existing direct DB role remains limited to synthetic user/planner
        ownership and cannot read or write community tables.
        """
        place_id_values = self.current_feature_place_ids(run_id, index, getattr(self, "index_width", 3))
        detail = self._travel_detail(access_token, travel_id)
        self._ensure_place_ids(access_token, travel_id, timeline_ids, place_id_values, detail)
        marker = self.current_feature_marker(run_id, index, getattr(self, "index_width", 3))
        post_id, post_version = self._find_or_create_post(access_token, travel_id, marker)
        comment_id = self._find_or_create_comment(access_token, post_id, marker)
        travel_version = detail.get("version")
        if not isinstance(travel_version, int):
            raise SeedError("current-feature travel detail has no integer version")
        return {
            "fixtureMarker": marker,
            "placeIds": place_id_values,
            "postId": post_id,
            "commentId": comment_id,
            "travelVersion": travel_version,
            "postVersion": post_version,
            "commentSequence": 0,
        }

    def write_credentials(self, payload: dict, path: Path) -> None:
        path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(payload, temporary, indent=2)
            temporary.write("\n")
        temporary_path.chmod(0o600)
        os.replace(temporary_path, path)

    def write_fixture_result(self, payload: dict, path: Path) -> None:
        """Write non-sensitive fixture counts as an ordinary evidence artifact."""
        path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(payload, temporary, indent=2)
            temporary.write("\n")
        temporary_path.chmod(0o644)
        os.replace(temporary_path, path)


def validate_fixture_counts(counts: dict[str, int], expected_users: int) -> None:
    expected = {
        "users": expected_users,
        "planners": expected_users,
        "timelineItems": expected_users * EXPECTED_TIMELINE_ITEMS_PER_PLANNER,
        "minimumTimelineItemsPerPlanner": EXPECTED_TIMELINE_ITEMS_PER_PLANNER,
        "maximumTimelineItemsPerPlanner": EXPECTED_TIMELINE_ITEMS_PER_PLANNER,
    }
    if counts != expected:
        raise SeedError("seed fixture verification failed: expected normalized users/planners/timeline counts")


def seed_all(
    runtime: AwsSeed,
    args: argparse.Namespace,
    *,
    reset_deleted_planners: int | None = None,
    verify_fixture: bool = False,
    existing_credentials: list[dict] | None = None,
) -> None:
    # Every user always gets a credentials[] entry, whether freshly created
    # or already-seeded from a prior run. This fixes two related bugs: (1)
    # an all-skipped retry used to write {"credentials": []}, silently
    # discarding a richer prior data file that cleanup-aws-load-data.py and
    # k6 both depend on; (2) even a *partial* skip used to omit the skipped
    # users' entries entirely, and any refreshToken it *did* carry forward
    # from create_travel-time state would be minutes-to-hours stale against
    # its 4h Redis TTL by the time a later phase (Ramp/Baseline/Spike) reads
    # it. seed_redis_token()+refresh() mint a brand-new, valid token for
    # every user on every seed_all() call regardless of already_existed —
    # writing directly into Redis by hash, so it works the same for a
    # brand-new or a long-existing user_table row. Only the expensive
    # DB/API-side work (user insert, travel/timeline creation) is skipped
    # when already fully seeded.
    run_id = args.run_id
    fixture_id = getattr(args, "fixture_id", "seed")
    index_width = getattr(runtime, "index_width", 3)
    current_feature_enabled = bool(getattr(runtime, "_enable_current_feature_fixture", False))
    credentials = list(existing_credentials or [])
    # A recovery/capacity stage rotates every credential's refresh-token
    # family in k6.  Reusing a verified ledger therefore requires minting a
    # fresh token for each already-seeded user before the next workload
    # starts; otherwise a stage marker skip would feed revoked 401 tokens to
    # k6.  Keep the existing travel/timeline/current-feature IDs intact and
    # only replace the credential pair.  The old families are revoked by
    # main() before this function is called for --incremental.
    skipped = len(credentials)
    for index, existing in enumerate(list(credentials), start=1):
        if not isinstance(existing, dict) or not isinstance(existing.get("userId"), str) or not existing.get("userId"):
            raise SeedError(f"incremental credential entry {index} has no userId")
        fresh_token = new_opaque_token()
        fresh_family = new_opaque_token()
        refreshed = dict(existing)
        refreshed.update({"refreshToken": fresh_token, "refreshFamilyId": fresh_family})
        credentials[index - 1] = refreshed
        write_seed_checkpoint(runtime, args, credentials, skipped)
        runtime.seed_redis_token(existing["userId"], args.refresh_ttl_ms, fresh_token, fresh_family)
        _, rotated_token = runtime.refresh(fresh_token)
        refreshed["refreshToken"] = rotated_token
        credentials[index - 1] = refreshed
        write_seed_checkpoint(runtime, args, credentials, skipped)
    start_index = len(credentials) + 1
    if start_index > args.users + 1:
        raise SeedError("existing credential file contains more users than requested target")
    for index in range(start_index, args.users + 1):
        user_id, already_existed = runtime.insert_user(run_id, index)
        if current_feature_enabled:
            runtime._active_place_ids = runtime.current_feature_place_ids(run_id, index)
        refresh_token = new_opaque_token()
        family_id = new_opaque_token()
        pending_credential = {
            "userId": user_id,
            "refreshToken": refresh_token,
            "refreshFamilyId": family_id,
        }
        write_seed_checkpoint(runtime, args, credentials + [pending_credential], skipped)
        runtime.seed_redis_token(user_id, args.refresh_ttl_ms, refresh_token, family_id)
        access_token, refresh_token = runtime.refresh(refresh_token)
        pending_credential["refreshToken"] = refresh_token
        write_seed_checkpoint(runtime, args, credentials + [pending_credential], skipped)
        if already_existed and runtime.has_existing_travel(user_id):
            travel_id = runtime.find_existing_travel(user_id)
            if travel_id is None:
                raise SeedError(f"user {index} has_existing_travel reported true but no planners_table row was found")
            timeline_ids = runtime.find_existing_timeline_items(travel_id)
            skipped += 1
            print(f"[seed] user {index}/{args.users} already fully seeded, reused travel/timeline, minted fresh token")
        else:
            travel_id = runtime.create_travel(access_token, index)
            timeline_ids = runtime.create_timeline_items(access_token, travel_id)
            print(f"[seed] user {index}/{args.users} prepared")
        pending_credential.update({
            "travelId": travel_id,
            "visitDate": "2026-08-01",
            "timelineItemIds": timeline_ids,
        })
        if current_feature_enabled:
            pending_credential.update(
                runtime.ensure_current_feature_fixture(
                    access_token,
                    run_id,
                    index,
                    travel_id,
                    timeline_ids,
                )
            )
        credentials.append(pending_credential)
        write_seed_checkpoint(runtime, args, credentials, skipped)
    fixture_counts = None
    if verify_fixture:
        fixture_counts = runtime.fixture_counts(run_id)
        try:
            validate_fixture_counts(fixture_counts, args.users)
        except SeedError:
            # Preserve a private, incomplete checkpoint so k6 cannot consume
            # a fixture whose cardinality was not proven.
            runtime.write_credentials(
                {
                    "runId": run_id,
                    "seedVersion": "aws-s2",
                    "indexWidth": index_width,
                    "seedState": "in-progress",
                    "seededAt": datetime.now(timezone.utc).isoformat(),
                    "fixtureId": fixture_id,
                    "fixtureState": "invalid",
                    "fixture": fixture_counts,
                    "skippedAlreadySeeded": skipped,
                    "credentials": credentials,
                },
                args.data_file,
            )
            raise

    payload = {
        "runId": run_id,
        "seedVersion": "aws-s2",
        "indexWidth": index_width,
        "seedState": "complete",
        "seededAt": datetime.now(timezone.utc).isoformat(),
        "fixtureId": fixture_id,
        "fixtureResetApplied": reset_deleted_planners is not None,
        "plannersDeletedBeforeSeed": reset_deleted_planners or 0,
        "fixtureState": "verified" if fixture_counts is not None else "not-verified",
        "skippedAlreadySeeded": skipped,
        "credentials": credentials,
    }
    if fixture_counts is not None:
        payload["fixture"] = fixture_counts
    if current_feature_enabled:
        payload["currentFeatureFixture"] = {
            "version": CURRENT_FEATURE_FIXTURE_VERSION,
            "users": len(credentials),
            "usersWithPlaceIds": sum(bool(entry.get("placeIds")) for entry in credentials),
            "usersWithCommunityPost": sum(bool(entry.get("postId")) for entry in credentials),
            "usersWithCommunityComment": sum(bool(entry.get("commentId")) for entry in credentials),
        }
    runtime.write_credentials(payload, args.data_file)
    fixture_result_file = getattr(args, "fixture_result_file", None)
    if fixture_counts is not None and fixture_result_file is not None:
        runtime.write_fixture_result(
            {
                "runId": run_id,
                "fixtureId": fixture_id,
                "seedVersion": "aws-s2",
                "indexWidth": index_width,
                "resetApplied": reset_deleted_planners is not None,
                "plannersDeletedBeforeSeed": reset_deleted_planners or 0,
                "expected": {
                    "users": args.users,
                    "planners": args.users,
                    "timelineItems": args.users * EXPECTED_TIMELINE_ITEMS_PER_PLANNER,
                    "timelineItemsPerPlanner": EXPECTED_TIMELINE_ITEMS_PER_PLANNER,
                },
                "actual": fixture_counts,
                "currentFeatureFixture": (
                    {
                        "version": CURRENT_FEATURE_FIXTURE_VERSION,
                        "users": len(credentials),
                        "usersWithPlaceIds": sum(bool(entry.get("placeIds")) for entry in credentials),
                        "usersWithCommunityPost": sum(bool(entry.get("postId")) for entry in credentials),
                        "usersWithCommunityComment": sum(bool(entry.get("commentId")) for entry in credentials),
                    }
                    if current_feature_enabled else None
                ),
                "completedAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            },
            fixture_result_file,
        )
    print(f"[seed] complete: {len(credentials)} synthetic users seeded, {skipped} already present, fixture={fixture_id}")


def write_seed_checkpoint(
    runtime: AwsSeed,
    args: argparse.Namespace,
    credentials: list[dict],
    skipped: int,
) -> None:
    index_width = getattr(runtime, "index_width", 3)
    runtime.write_credentials(
        {
            "runId": args.run_id,
            "seedVersion": "aws-s2",
            "indexWidth": index_width,
            "seedState": "in-progress",
            "seededAt": datetime.now(timezone.utc).isoformat(),
            "fixtureId": getattr(args, "fixture_id", "seed"),
            "skippedAlreadySeeded": skipped,
            "credentials": credentials,
        },
        args.data_file,
    )


def revoke_previous_credentials(runtime: AwsSeed, args: argparse.Namespace) -> None:
    if not args.data_file.exists():
        return
    try:
        result = revoke_credential_file(
            args.data_file,
            args.run_id,
            runtime.refresh_status,
            runtime.delete_exact_refresh_keys,
        )
    except CredentialLifecycleError as error:
        raise SeedError(str(error)) from error
    print(
        "[seed] revoked "
        f"{result.credential_count} previous refresh-token family/families; "
        f"deleted {result.redis_deleted_count}/{result.redis_key_count} exact Redis key(s)"
    )


def load_incremental_credentials(args: argparse.Namespace) -> list[dict]:
    """Load the prior verified ledger before appending any new users."""
    if not args.data_file.is_file():
        raise SeedError("--incremental requires an existing verified credential file")
    try:
        payload = json.loads(args.data_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SeedError("incremental credential file is not valid JSON") from error
    if not isinstance(payload, dict) or payload.get("runId") != args.run_id:
        raise SeedError("incremental credential file runId does not match")
    if payload.get("seedState") != "complete" or payload.get("fixtureState") != "verified":
        raise SeedError("incremental credential file must be complete and fixture-verified")
    if payload.get("indexWidth", 3) != args.index_width:
        raise SeedError("incremental index width does not match the existing credential ledger")
    credentials = payload.get("credentials")
    if not isinstance(credentials, list) or not credentials:
        raise SeedError("incremental credential file has no credential ledger")
    for index, credential in enumerate(credentials, start=1):
        if not isinstance(credential, dict) or not all(
            isinstance(credential.get(key), str) and credential.get(key)
            for key in ("userId", "travelId", "refreshToken", "refreshFamilyId")
        ):
            raise SeedError(f"incremental credential entry {index} is incomplete")
    return credentials


def main() -> int:
    args = parse_args()
    if not RUN_ID_PATTERN.fullmatch(args.run_id):
        raise SeedError("--run-id must be 1-64 chars of [A-Za-z0-9-]")
    if args.users < 1 or args.users > MAX_SYNTHETIC_USERS:
        raise SeedError(f"--users must be between 1 and {MAX_SYNTHETIC_USERS}")
    if args.index_width < 3 or args.index_width > 6:
        raise SeedError("--index-width must be between 3 and 6")
    if args.index_width == 3 and args.users > 999:
        raise SeedError("--index-width 3 supports at most 999 users; use --index-width 6 for adaptive stages")
    if not FIXTURE_ID_PATTERN.fullmatch(args.fixture_id):
        raise SeedError("--fixture-id must be 1-64 chars of [A-Za-z0-9._-]")
    args.data_file = args.data_file.resolve()
    if args.fixture_result_file is not None:
        args.fixture_result_file = args.fixture_result_file.resolve()
    verify_account(args.expected_account_id, args.region)
    database_username, database_password = read_secret_credential(args.database_secret_arn, args.region)
    runtime = AwsSeed(args, database_username, database_password)
    # Opt in only the real AWS seed entrypoint.  Keeping this explicit lets
    # the legacy unit-test fakes and historical seed contract stay unchanged.
    runtime._enable_current_feature_fixture = True
    if args.incremental and args.refresh_tokens_only:
        raise SeedError("--incremental and --refresh-tokens-only cannot be combined")
    existing_credentials = load_incremental_credentials(args) if (args.incremental or args.refresh_tokens_only) else None
    # Revoke the prior ledger before replacing its tokens.  This is exact
    # run-scoped cleanup (the same contract used by the normal seed path) and
    # prevents the superseded Redis families from lingering until TTL expiry.
    if args.incremental and args.reset_fixture:
        raise SeedError("--incremental cannot be combined with --reset-fixture")
    if args.refresh_tokens_only and args.reset_fixture:
        raise SeedError("--refresh-tokens-only cannot be combined with --reset-fixture")
    if args.refresh_tokens_only:
        # k6 rotates refresh tokens in memory during each stage.  A later
        # stage therefore needs a fresh token per VU, but it must not repeat
        # the expensive user/travel/community fixture work.  Reuse the
        # verified ledger and run seed_all's credential-refresh path only;
        # the final cardinality query is retained as a cheap ownership
        # check, and no fixture rows are reset or recreated.
        revoke_previous_credentials(runtime, args)
        seed_all(
            runtime,
            args,
            verify_fixture=True,
            existing_credentials=existing_credentials,
        )
        return 0
    revoke_previous_credentials(runtime, args)
    reset_deleted_planners = None
    if args.reset_fixture:
        reset_deleted_planners = runtime.reset_synthetic_planners(args.run_id)
        print(f"[seed] reset fixture: deleted {reset_deleted_planners} planner(s) with cascaded timeline rows")
    seed_all(
        runtime,
        args,
        reset_deleted_planners=reset_deleted_planners,
        verify_fixture=True,
        existing_credentials=existing_credentials,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SecretContractError as error:
        # Distinct exit code (2): the Secrets Manager value doesn't match
        # the expected test-credential contract, as opposed to a DB/Redis/API
        # failure during seeding itself (1).
        print(f"[seed] ERROR (secret contract): {error}", file=sys.stderr)
        raise SystemExit(2)
    except SeedError as error:
        print(f"[seed] ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
