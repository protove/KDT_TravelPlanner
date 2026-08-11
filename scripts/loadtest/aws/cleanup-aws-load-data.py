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
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,40}$")
ACCOUNT_ID_PATTERN = re.compile(r"^\d{12}$")
POSTGRES_CLIENT_IMAGE = "postgres:17-alpine"
REDIS_CLIENT_IMAGE = "redis:7-alpine"
PROVIDER_USER_ID_PREFIX = "loadtest-aws-"


class CleanupError(RuntimeError):
    """A sanitized cleanup or contract verification failure."""


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
    parser.add_argument("--database-user", required=True)
    parser.add_argument("--database-secret-arn", required=True)
    parser.add_argument("--redis-host", default=None, help="Omit together with --redis-secret-arn to skip Redis cleanup entirely")
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument("--redis-secret-arn", default=None)
    parser.add_argument("--data-file", type=Path, default=None, help="seed-aws-load-data.py's credential file; enables exact-match Redis key cleanup")
    parser.add_argument("--dry-run", action="store_true", help="Report how many synthetic users match, delete nothing")
    return parser.parse_args()


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


def read_secret_password(secret_arn: str, region: str) -> str:
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
        raise CleanupError("Secrets Manager value is not valid JSON") from error
    password = payload.get("password")
    if not isinstance(password, str) or not password:
        raise CleanupError("Secrets Manager value has no 'password' field")
    return password


def psql(args: argparse.Namespace, password: str, sql: str) -> str:
    env = {**os.environ, "PGPASSWORD": password, "PGSSLMODE": "require"}
    return run(
        [
            "docker", "run", "--rm", "--network", "host",
            "-e", "PGPASSWORD", "-e", "PGSSLMODE",
            POSTGRES_CLIENT_IMAGE, "psql",
            "-h", args.database_host, "-p", str(args.database_port),
            "-U", args.database_user, "-d", args.database_name,
            "-v", "ON_ERROR_STOP=1", "-tA", "-c", sql,
        ],
        env=env,
    )


def redis(args: argparse.Namespace, password: str, *arguments: str) -> str:
    env = {**os.environ, "REDISCLI_AUTH": password}
    return run(
        [
            "docker", "run", "--rm", "--network", "host",
            "-e", "REDISCLI_AUTH",
            REDIS_CLIENT_IMAGE, "redis-cli",
            "-h", args.redis_host, "-p", str(args.redis_port),
            "--tls", "--no-auth-warning", *arguments,
        ],
        env=env,
    )


def matching_user_count(args: argparse.Namespace, password: str, run_id: str) -> int:
    result = psql(
        args, password,
        "SELECT count(*) FROM user_table WHERE provider = 'GOOGLE' AND provider_user_id LIKE "
        f"{sql_literal(like_pattern(run_id))}",
    ).strip()
    return int(result or "0")


def delete_matching_rows(args: argparse.Namespace, password: str, run_id: str) -> None:
    pattern = sql_literal(like_pattern(run_id))
    script = (
        "BEGIN; "
        "DELETE FROM planners_table WHERE owner_id IN "
        f"(SELECT id FROM user_table WHERE provider = 'GOOGLE' AND provider_user_id LIKE {pattern}); "
        "DELETE FROM user_table WHERE provider = 'GOOGLE' AND provider_user_id LIKE "
        f"{pattern}; "
        "COMMIT;"
    )
    psql(args, password, script)


def cleanup_redis(args: argparse.Namespace, redis_password: str, run_id: str) -> int:
    path = args.data_file.resolve()
    if not path.exists():
        raise CleanupError("--data-file does not exist")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("runId") != run_id:
        raise CleanupError("--data-file runId does not match --run-id; refusing to touch its Redis keys")
    deleted = 0
    for credential in payload.get("credentials", []):
        refresh_token = credential.get("refreshToken")
        family_id = credential.get("refreshFamilyId")
        if isinstance(refresh_token, str):
            token_hash = hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()
            redis(args, redis_password, "DEL", f"auth:refresh:token:{token_hash}")
            deleted += 1
        if isinstance(family_id, str):
            redis(args, redis_password, "DEL", f"auth:refresh:family:{family_id}")
            deleted += 1
    return deleted


def main() -> int:
    args = parse_args()
    if not RUN_ID_PATTERN.fullmatch(args.run_id):
        raise CleanupError("--run-id must be 1-40 chars of [A-Za-z0-9-]")
    if bool(args.redis_host) != bool(args.redis_secret_arn):
        raise CleanupError("--redis-host and --redis-secret-arn must be given together, or both omitted")

    verify_account(args.expected_account_id, args.region)
    database_password = read_secret_password(args.database_secret_arn, args.region)

    count = matching_user_count(args, database_password, args.run_id)
    if count == 0:
        print("[cleanup] no synthetic data found for this run-id; nothing to do")
        return 0

    if args.dry_run:
        print(f"[cleanup] dry-run: {count} synthetic user(s) match this run-id; would be deleted")
        return 0

    delete_matching_rows(args, database_password, args.run_id)
    print(f"[cleanup] deleted {count} synthetic user(s) and their owned travels/timeline items")

    if not (args.redis_host and args.redis_secret_arn):
        print("[cleanup] no --redis-host/--redis-secret-arn given; skipping Redis key cleanup (keys expire on their own TTL)")
    elif not args.data_file:
        print("[cleanup] no --data-file given; skipping Redis key cleanup (keys expire on their own TTL)")
    else:
        redis_password = read_secret_password(args.redis_secret_arn, args.region)
        redis_deleted = cleanup_redis(args, redis_password, args.run_id)
        print(f"[cleanup] deleted {redis_deleted} Redis key(s)")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CleanupError as error:
        print(f"[cleanup] ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
