#!/usr/bin/env python3
"""Delete only this Run ID's synthetic data, seeded by seed-aws-load-data.py.

Deletion is scoped by provider_user_id LIKE 'loadtest-aws-<run-id>-%' in a
single transaction, in FK-safe order:
  1. planners_table (owner_id) — cascades to timeline_table, planner_members,
     and planner_purposes (see backend/src/main/resources/db/migration/
     V4__create_planners_table.sql, V6/V5/V11 — all ON DELETE CASCADE from
     planners_table).
  2. user_table — only possible after step 1, because
     fk_planners_table_owner is ON DELETE RESTRICT: a user row cannot be
     deleted while it still owns a planner.

The 'loadtest-aws-' prefix is hardcoded (not derived from --run-id), so this
can never match a real user's provider_user_id even if --run-id were empty
or unusual — it only ever deletes rows this project's own seed script
created. Every AWS command this script runs is gated by the same
--expected-account-id check as seed-aws-load-data.py
(aws-load-test-handoff/contracts/RUN_METADATA_CONTRACT.md).

Redis cleanup is best-effort and exact-match only: it never SCANs the
keyspace (that would risk touching real users' active sessions). It only
deletes the two keys per credential recorded by seed-aws-load-data.py's
--data-file, computed from values already in that file. If --data-file is
omitted, Redis keys are left to expire on their own TTL
(--refresh-ttl-ms at seed time, 4h by default) and this is logged, not
treated as an error — the DB cleanup below is independent of the data file.

Credential contract (same as seed-aws-load-data.py, D-001-R1 후속,
aws-load-test-handoff/decisions/DECISION_LOG.md "Seed/Cleanup 최소권한"):
--database-secret-arn is a dedicated test-only Secret, JSON
{"username": "...", "password": "..."} — never the RDS master secret. Redis
uses ElastiCache RBAC with IAM authentication (--redis-iam-user +
--redis-replication-group-id), never the shared default-user AUTH secret.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,40}$")
ACCOUNT_ID_PATTERN = re.compile(r"^\d{12}$")
POSTGRES_CLIENT_IMAGE = "postgres:17-alpine"
REDIS_CLIENT_IMAGE = "redis:7-alpine"
PROVIDER_USER_ID_PREFIX = "loadtest-aws-"


class CleanupError(RuntimeError):
    """A sanitized cleanup or contract verification failure."""


class SecretContractError(CleanupError):
    """The Secrets Manager value did not match the expected {username,
    password} test-credential contract. Distinct exit code (2)."""


class CredentialFileError(CleanupError):
    """--data-file was given but missing/unreadable/malformed. Distinct
    exit code (3) so an operator can tell "Redis cleanup couldn't find its
    input file" apart from "DB or Redis cleanup itself failed" (1) or "wrong
    secret wired in" (2) — the DB cleanup above this in main() already
    succeeded by the time this can happen."""


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def like_pattern(run_id: str) -> str:
    # run_id is validated against RUN_ID_PATTERN ([A-Za-z0-9-] only), so it
    # can never introduce a LIKE wildcard (%, _) of its own.
    return f"{PROVIDER_USER_ID_PREFIX}{run_id}-%"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-account-id", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--database-host", required=True)
    parser.add_argument("--database-port", type=int, default=5432)
    parser.add_argument("--database-name", required=True)
    parser.add_argument("--database-secret-arn", required=True, help="Secrets Manager ARN of the dedicated test-only DB Secret, JSON {\"username\":..,\"password\":..} (never the RDS master secret)")
    parser.add_argument("--redis-host", default=None, help="Omit together with --redis-iam-user/--redis-replication-group-id to skip Redis cleanup entirely")
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument("--redis-iam-user", default=None, help="ElastiCache RBAC username this Runner authenticates as via IAM")
    parser.add_argument("--redis-replication-group-id", default=None, help="ElastiCache replication group ID the IAM auth token is signed for")
    parser.add_argument("--data-file", type=Path, default=None, help="seed-aws-load-data.py's credential file; enables exact-match Redis key cleanup")
    parser.add_argument("--dry-run", action="store_true", help="Report how many synthetic users match, delete nothing")
    parser.add_argument("--result-file", type=Path, default=None, help="Write a structured cleanup-result.json here (orchestrate-aws-b01.sh's cleanup-result record, TEAM_MEMBER_B01_ACTION_REQUEST.md §4.2)")
    return parser.parse_args()


def write_result(result_file: Path | None, result: dict) -> None:
    if result_file is None:
        return
    result = {**result, "completedAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")}
    result_file = result_file.resolve()
    result_file.parent.mkdir(parents=True, exist_ok=True)
    result_file.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def run(command: list[str], *, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, env=env, check=False)
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()[-1:] or ["command failed"]
        raise CleanupError(f"command failed ({completed.returncode}): {' '.join(command[:3])}; {detail[0]}")
    return completed.stdout


def verify_account(expected_account_id: str, region: str) -> None:
    if not ACCOUNT_ID_PATTERN.fullmatch(expected_account_id):
        raise CleanupError("--expected-account-id must be exactly 12 digits")
    completed = subprocess.run(
        ["aws", "sts", "get-caller-identity", "--region", region, "--query", "Account", "--output", "text"],
        capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0:
        raise CleanupError("sts:GetCallerIdentity failed; cannot verify the target AWS account")
    if completed.stdout.strip() != expected_account_id:
        raise CleanupError("observed AWS account does not match --expected-account-id; refusing to run")


def read_secret_credential(secret_arn: str, region: str) -> tuple[str, str]:
    """Returns (username, password) from a dedicated test-only Secret. Never
    call this with an RDS master secret ARN."""
    completed = subprocess.run(
        [
            "aws", "secretsmanager", "get-secret-value",
            "--secret-id", secret_arn, "--region", region,
            "--query", "SecretString", "--output", "text",
        ],
        capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0:
        raise CleanupError("failed to read a Secrets Manager value")
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
    """See seed-aws-load-data.py's copy of this function for the full
    explanation; duplicated rather than shared to match this repo's existing
    convention of standalone seed/cleanup scripts (psql()/redis()/
    verify_account() are already duplicated the same way)."""
    try:
        import botocore.session
        from botocore.signers import RequestSigner
    except ImportError as error:
        raise CleanupError(
            "botocore is required for Redis IAM authentication but is not installed "
            "(infra/modules/load_test_runner/templates/runner-user-data.sh.tftpl should have pip-installed it)"
        ) from error
    session = botocore.session.get_session()
    credentials = session.get_credentials()
    if credentials is None:
        raise CleanupError("no AWS credentials available to sign the Redis IAM auth token")
    request_signer = RequestSigner(
        service_id=session.get_service_model("elasticache").service_id,
        region_name=region,
        signing_name="elasticache",
        signature_version="v4",
        credentials=credentials,
        event_emitter=session.get_component("event_emitter"),
    )
    url = request_signer.generate_presigned_url(
        {
            "method": "GET",
            "url": f"https://{replication_group_id}/",
            "body": {"Action": "connect", "User": user_name},
            "context": {},
        },
        region_name=region,
        expires_in=900,
        operation_name="",
    )
    return url.removeprefix("https://")


def psql(args: argparse.Namespace, username: str, password: str, sql: str) -> str:
    env = {**os.environ, "PGPASSWORD": password, "PGSSLMODE": "require"}
    return run(
        [
            "docker", "run", "--rm", "--network", "host",
            "-e", "PGPASSWORD", "-e", "PGSSLMODE",
            POSTGRES_CLIENT_IMAGE, "psql",
            "-h", args.database_host, "-p", str(args.database_port),
            "-U", username, "-d", args.database_name,
            "-v", "ON_ERROR_STOP=1", "-tA", "-c", sql,
        ],
        env=env,
    )


def redis(args: argparse.Namespace, *arguments: str) -> str:
    auth_token = generate_redis_iam_auth_token(args.redis_iam_user, args.redis_replication_group_id, args.region)
    env = {**os.environ, "REDISCLI_AUTH": auth_token}
    return run(
        [
            "docker", "run", "--rm", "--network", "host",
            "-e", "REDISCLI_AUTH",
            REDIS_CLIENT_IMAGE, "redis-cli",
            "-h", args.redis_host, "-p", str(args.redis_port),
            "--tls", "--no-auth-warning", "--user", args.redis_iam_user, *arguments,
        ],
        env=env,
    )


def matching_user_count(args: argparse.Namespace, username: str, password: str, run_id: str) -> int:
    result = psql(
        args, username, password,
        "SELECT count(*) FROM user_table WHERE provider = 'GOOGLE' AND provider_user_id LIKE "
        f"{sql_literal(like_pattern(run_id))}",
    ).strip()
    return int(result or "0")


def delete_matching_rows(args: argparse.Namespace, username: str, password: str, run_id: str) -> None:
    pattern = sql_literal(like_pattern(run_id))
    script = (
        "BEGIN; "
        "DELETE FROM planners_table WHERE owner_id IN "
        f"(SELECT id FROM user_table WHERE provider = 'GOOGLE' AND provider_user_id LIKE {pattern}); "
        "DELETE FROM user_table WHERE provider = 'GOOGLE' AND provider_user_id LIKE "
        f"{pattern}; "
        "COMMIT;"
    )
    psql(args, username, password, script)


def cleanup_redis(args: argparse.Namespace, run_id: str) -> int:
    path = args.data_file.resolve()
    if not path.exists():
        raise CredentialFileError("--data-file does not exist")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise CredentialFileError("--data-file is not valid JSON") from error
    if payload.get("runId") != run_id:
        raise CredentialFileError("--data-file runId does not match --run-id; refusing to touch its Redis keys")
    deleted = 0
    for credential in payload.get("credentials", []):
        refresh_token = credential.get("refreshToken")
        family_id = credential.get("refreshFamilyId")
        if isinstance(refresh_token, str):
            token_hash = hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()
            redis(args, "DEL", f"auth:refresh:token:{token_hash}")
            deleted += 1
        if isinstance(family_id, str):
            redis(args, "DEL", f"auth:refresh:family:{family_id}")
            deleted += 1
    return deleted


def main() -> int:
    args = parse_args()
    if not RUN_ID_PATTERN.fullmatch(args.run_id):
        raise CleanupError("--run-id must be 1-40 chars of [A-Za-z0-9-]")
    if bool(args.redis_host) != bool(args.redis_iam_user) or bool(args.redis_host) != bool(args.redis_replication_group_id):
        raise CleanupError("--redis-host, --redis-iam-user, and --redis-replication-group-id must all be given together, or all omitted")

    verify_account(args.expected_account_id, args.region)
    database_username, database_password = read_secret_credential(args.database_secret_arn, args.region)

    count = matching_user_count(args, database_username, database_password, args.run_id)
    if count == 0:
        print("[cleanup] no synthetic data found for this run-id; nothing to do")
        write_result(args.result_file, {
            "runId": args.run_id, "dryRun": args.dry_run, "matchedUserCount": 0,
            "dbDeleted": False, "redisKeysDeleted": None, "redisSkippedReason": "no-matching-data",
        })
        return 0

    if args.dry_run:
        print(f"[cleanup] dry-run: {count} synthetic user(s) match this run-id; would be deleted")
        write_result(args.result_file, {
            "runId": args.run_id, "dryRun": True, "matchedUserCount": count,
            "dbDeleted": False, "redisKeysDeleted": None, "redisSkippedReason": "dry-run",
        })
        return 0

    delete_matching_rows(args, database_username, database_password, args.run_id)
    print(f"[cleanup] deleted {count} synthetic user(s) and their owned travels/timeline items")

    redis_deleted = None
    redis_skipped_reason = None
    if not (args.redis_host and args.redis_iam_user and args.redis_replication_group_id):
        redis_skipped_reason = "no-redis-args"
        print("[cleanup] no --redis-host/--redis-iam-user/--redis-replication-group-id given; skipping Redis key cleanup (keys expire on their own TTL)")
    elif not args.data_file:
        redis_skipped_reason = "no-data-file"
        print("[cleanup] no --data-file given; skipping Redis key cleanup (keys expire on their own TTL)")
    else:
        redis_deleted = cleanup_redis(args, args.run_id)
        print(f"[cleanup] deleted {redis_deleted} Redis key(s)")

    write_result(args.result_file, {
        "runId": args.run_id, "dryRun": False, "matchedUserCount": count,
        "dbDeleted": True, "redisKeysDeleted": redis_deleted, "redisSkippedReason": redis_skipped_reason,
    })
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SecretContractError as error:
        print(f"[cleanup] ERROR (secret contract): {error}", file=sys.stderr)
        raise SystemExit(2)
    except CredentialFileError as error:
        print(f"[cleanup] ERROR (credential file): {error}", file=sys.stderr)
        raise SystemExit(3)
    except CleanupError as error:
        print(f"[cleanup] ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
