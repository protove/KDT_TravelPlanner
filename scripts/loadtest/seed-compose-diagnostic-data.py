#!/usr/bin/env python3
"""Seed isolated, variant-scoped Compose data for SCRUM-41 diagnostics.

The script deliberately uses the existing SQL/API contracts and never writes a
credential to stdout. Each credential owns four travels so read, fixed-order,
scratch-create, and growing-order behavior can be measured independently.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASE_SEED_PATH = ROOT / "scripts/loadtest/seed-compose-load-data.py"
SPEC = importlib.util.spec_from_file_location("compose_seed_base", BASE_SEED_PATH)
if not SPEC or not SPEC.loader:
    raise RuntimeError("unable to load shared Compose seed helpers")
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)

ComposeSeed = BASE.ComposeSeed
SeedError = BASE.SeedError
DEFAULT_ENV_FILE = BASE.DEFAULT_ENV_FILE
DEFAULT_COMPOSE_FILE = BASE.DEFAULT_COMPOSE_FILE
parse_duration_ms = BASE.parse_duration_ms
parse_env_file = BASE.parse_env_file
sql_literal = BASE.sql_literal

VARIANTS = {
    "refresh-only",
    "read-only",
    "fixed-cardinality-mixed",
    "growing-cardinality-mixed",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=sorted(VARIANTS), required=True)
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--tokens-only", action="store_true")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--compose-file", dest="compose_files", type=Path, action="append")
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--data-file", type=Path, required=True)
    parser.add_argument("--seed-tag", required=True)
    return parser.parse_args()


def safe_seed_tag(value: str) -> str:
    tag = re.sub(r"[^A-Za-z0-9-]", "", value)
    if not tag or not re.search(r"[A-Za-z0-9]", tag):
        raise SeedError("--seed-tag must contain an alphanumeric character")
    return tag[-32:]


def refresh_only(runtime: ComposeSeed, args: argparse.Namespace, ttl_ms: int) -> None:
    path = args.data_file.resolve()
    if not path.exists():
        raise SeedError(f"diagnostic credential file does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    for credential in payload.get("credentials", []):
        refresh_token, family_id = runtime.seed_redis_token(credential["userId"], ttl_ms)
        credential["refreshToken"] = refresh_token
        credential["refreshFamilyId"] = family_id
    payload["seededAt"] = datetime.now(timezone.utc).isoformat()
    runtime.write_credentials(payload, path)
    print(f"[diagnostic-seed] refresh tokens renewed: {len(payload.get('credentials', []))} users")


def seed_variant(runtime: ComposeSeed, args: argparse.Namespace, ttl_ms: int) -> None:
    seed_tag = safe_seed_tag(args.seed_tag)
    credentials: list[dict[str, object]] = []
    for index in range(1, args.users + 1):
        provider_user_id = f"diag-{seed_tag}-{index:03d}"
        user_id = str(uuid.uuid4())
        runtime.psql(
            "INSERT INTO user_table "
            "(id, provider, provider_user_id, email, name, nickname, profile_completed, created_at, updated_at) VALUES "
            f"({sql_literal(user_id)}, 'GOOGLE', {sql_literal(provider_user_id)}, "
            f"{sql_literal(provider_user_id + '@diagnostic.local')}, {sql_literal('Diagnostic ' + str(index))}, "
            f"{sql_literal('diag' + hashlib.sha256(f'{args.variant}:{seed_tag}:{index}'.encode()).hexdigest()[:12])}, TRUE, now(), now())"
        )
        refresh_token, family_id = runtime.seed_redis_token(user_id, ttl_ms)
        access_token, refresh_token = runtime.refresh(refresh_token)

        read_travel_id = runtime.create_travel(access_token, index * 10 + 1)
        read_items = runtime.create_timeline_items(access_token, read_travel_id)
        scratch_travel_id = runtime.create_travel(access_token, index * 10 + 2)
        scratch_items = runtime.create_timeline_items(access_token, scratch_travel_id)
        fixed_travel_id = runtime.create_travel(access_token, index * 10 + 3)
        fixed_items = runtime.create_timeline_items(access_token, fixed_travel_id)
        growing_travel_id = runtime.create_travel(access_token, index * 10 + 4)
        growing_items = runtime.create_timeline_items(access_token, growing_travel_id)

        credentials.append({
            "userId": user_id,
            "travelId": read_travel_id,
            "readTravelId": read_travel_id,
            "scratchTravelId": scratch_travel_id,
            "fixedOrderTravelId": fixed_travel_id,
            "growingTravelId": growing_travel_id,
            "refreshToken": refresh_token,
            "refreshFamilyId": family_id,
            "visitDate": "2026-08-01",
            "timelineItemIds": read_items,
            "readTimelineItemIds": read_items,
            "scratchTimelineItemIds": scratch_items,
            "fixedOrderTimelineItemIds": fixed_items,
            "growingTimelineItemIds": growing_items,
        })
        print(f"[diagnostic-seed] {args.variant} user {index}/{args.users} prepared")

    runtime.write_credentials({
        "seedVersion": "compose-diagnostic-s1",
        "seedTag": seed_tag,
        "variant": args.variant,
        "seededAt": datetime.now(timezone.utc).isoformat(),
        "credentials": credentials,
    }, args.data_file)
    print(f"[diagnostic-seed] complete: {len(credentials)} users for {args.variant}")


def main() -> int:
    args = parse_args()
    if args.users < 1 or args.users > 200:
        raise SeedError("--users must be between 1 and 200")
    args.env_file = args.env_file.resolve()
    args.compose_files = [path.resolve() for path in (args.compose_files or [DEFAULT_COMPOSE_FILE])]
    args.data_file = args.data_file.resolve()
    if not args.env_file.exists() or any(not path.exists() for path in args.compose_files):
        raise SeedError("env-file and every compose-file must exist")
    env_values = parse_env_file(args.env_file)
    runtime = ComposeSeed(args, env_values)
    ttl_ms = parse_duration_ms(env_values.get("REFRESH_TOKEN_TTL"))
    if args.tokens_only:
        refresh_only(runtime, args, ttl_ms)
    else:
        seed_variant(runtime, args, ttl_ms)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SeedError as error:
        print(f"[diagnostic-seed] ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
