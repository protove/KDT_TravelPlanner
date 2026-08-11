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
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlencode

DEFAULT_REFRESH_TTL_MS = 4 * 60 * 60 * 1000  # 4h — short-lived by design; this is a shared, persistent store
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,40}$")
ACCOUNT_ID_PATTERN = re.compile(r"^\d{12}$")
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
REDIS_TOKEN_HASH_PATTERN = re.compile(r"^[a-f0-9]{64}$")
POSTGRES_CLIENT_IMAGE = "postgres:17-alpine"
REDIS_CLIENT_IMAGE = "redis:7-alpine"


class SeedError(RuntimeError):
    """A sanitized seed or contract verification failure."""


class SecretContractError(SeedError):
    """The Secrets Manager value did not match the expected {username,
    password} test-credential contract. Distinguished from other SeedErrors
    with its own exit code (2) so an operator can tell "the wrong secret is
    wired in" apart from "the DB/Redis/API itself failed" (1) at a glance."""


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def new_opaque_token() -> str:
    token = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")
    if not TOKEN_PATTERN.fullmatch(token):
        raise SeedError("generated opaque token has an invalid format")
    return token


def provider_user_id(run_id: str, index: int) -> str:
    """Deterministic per (run_id, index) — this is what makes seeding
    idempotent and what cleanup-aws-load-data.py filters on."""
    return f"loadtest-aws-{run_id}-{index:03d}"[:255]


def synthetic_email(run_id: str, index: int) -> str:
    # @loadtest.local matches the synthetic_email pattern already scanned by
    # scripts/loadtest/verify-evidence-safety.py, so existing evidence
    # scanning covers AWS runs without changes.
    return f"{provider_user_id(run_id, index)}@loadtest.local"


def synthetic_nickname(run_id: str, index: int) -> str:
    # nickname has its own UNIQUE constraint and a 30-char limit; derive it
    # from run_id so re-seeding the same run_id/index is deterministic.
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:10]
    return f"lt{digest}{index:03d}"[:30]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, help="RUN_METADATA_CONTRACT runId; tags every row this run creates")
    parser.add_argument("--users", type=int, default=20)
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
    parser.add_argument("--refresh-ttl-ms", type=int, default=DEFAULT_REFRESH_TTL_MS)
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

    def psql(self, sql: str) -> str:
        env = {**os.environ, "PGPASSWORD": self.database_password, "PGSSLMODE": "require"}
        return run(
            [
                "docker", "run", "--rm", "--network", "host",
                "-e", "PGPASSWORD", "-e", "PGSSLMODE",
                POSTGRES_CLIENT_IMAGE, "psql",
                "-h", self.args.database_host, "-p", str(self.args.database_port),
                "-U", self.database_username, "-d", self.args.database_name,
                "-v", "ON_ERROR_STOP=1", "-tA", "-c", sql,
            ],
            env=env,
        )

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
            with urlopen(request, payload, timeout=15) as response:
                return response.status, json.loads(response.read() or b"{}"), response.headers.get_all("Set-Cookie") or []
        except HTTPError as error:
            return error.code, {}, error.headers.get_all("Set-Cookie") or []
        except URLError as error:
            raise SeedError(f"API request failed: {error.reason}") from error

    def find_existing_user_id(self, run_id: str, index: int) -> str | None:
        result = self.psql(
            "SELECT id FROM user_table WHERE provider = 'GOOGLE' AND provider_user_id = "
            f"{sql_literal(provider_user_id(run_id, index))}"
        ).strip()
        return result or None

    def insert_user(self, run_id: str, index: int) -> tuple[str, bool]:
        """Returns (user_id, already_existed)."""
        existing = self.find_existing_user_id(run_id, index)
        if existing:
            return existing, True
        user_id = str(uuid.uuid4())
        inserted = self.psql(
            "INSERT INTO user_table "
            "(id, provider, provider_user_id, email, name, nickname, profile_completed, created_at, updated_at) VALUES "
            f"({sql_literal(user_id)}, 'GOOGLE', {sql_literal(provider_user_id(run_id, index))}, "
            f"{sql_literal(synthetic_email(run_id, index))}, {sql_literal('LoadTest AWS ' + str(index))}, "
            f"{sql_literal(synthetic_nickname(run_id, index))}, TRUE, now(), now()) "
            "ON CONFLICT (provider, provider_user_id) DO NOTHING "
            "RETURNING id"
        ).strip()
        if inserted:
            return inserted, False
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

    def seed_redis_token(self, user_id: str, ttl_ms: int) -> tuple[str, str]:
        token = new_opaque_token()
        family_id = new_opaque_token()
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
            status, body, _ = self.api(
                "POST", f"/travels/{travel_id}/timeline-items", token=access_token,
                body={
                    "dayNumber": 1, "visitDate": "2026-08-01", "category": "관광지",
                    "name": f"seed-item-{visit_order}", "visitOrder": visit_order,
                },
            )
            item_id = body.get("data", {}).get("timelineItemId") if isinstance(body, dict) else None
            if status not in (200, 201) or not isinstance(item_id, str):
                raise SeedError(f"timeline creation contract failed with status {status}")
            item_ids.append(item_id)
        return item_ids

    def write_credentials(self, payload: dict, path: Path) -> None:
        path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(payload, temporary, indent=2)
            temporary.write("\n")
        temporary_path.chmod(0o600)
        os.replace(temporary_path, path)


def seed_all(runtime: AwsSeed, args: argparse.Namespace) -> None:
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
    credentials = []
    skipped = 0
    for index in range(1, args.users + 1):
        user_id, already_existed = runtime.insert_user(run_id, index)
        refresh_token, family_id = runtime.seed_redis_token(user_id, args.refresh_ttl_ms)
        access_token, refresh_token = runtime.refresh(refresh_token)
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
        credentials.append({
            "userId": user_id,
            "travelId": travel_id,
            "refreshToken": refresh_token,
            "refreshFamilyId": family_id,
            "visitDate": "2026-08-01",
            "timelineItemIds": timeline_ids,
        })
    runtime.write_credentials(
        {
            "runId": run_id,
            "seedVersion": "aws-s1",
            "seededAt": datetime.now(timezone.utc).isoformat(),
            "skippedAlreadySeeded": skipped,
            "credentials": credentials,
        },
        args.data_file,
    )
    print(f"[seed] complete: {len(credentials)} synthetic users seeded, {skipped} already present")


def main() -> int:
    args = parse_args()
    if not RUN_ID_PATTERN.fullmatch(args.run_id):
        raise SeedError("--run-id must be 1-40 chars of [A-Za-z0-9-]")
    if args.users < 1 or args.users > 200:
        raise SeedError("--users must be between 1 and 200")
    args.data_file = args.data_file.resolve()
    verify_account(args.expected_account_id, args.region)
    database_username, database_password = read_secret_credential(args.database_secret_arn, args.region)
    runtime = AwsSeed(args, database_username, database_password)
    seed_all(runtime, args)
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
