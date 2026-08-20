#!/usr/bin/env python3
"""Seed one isolated SCRUM-41 SQL round-trip diagnostic fixture."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE_PATH = ROOT / "scripts/loadtest/seed-compose-load-data.py"
SPEC = importlib.util.spec_from_file_location("compose_seed_base", BASE_PATH)
if not SPEC or not SPEC.loader:
    raise RuntimeError("unable to import shared Compose seed helpers")
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)

ComposeSeed = BASE.ComposeSeed
SeedError = BASE.SeedError
DEFAULT_ENV_FILE = BASE.DEFAULT_ENV_FILE
DEFAULT_COMPOSE_FILE = BASE.DEFAULT_COMPOSE_FILE
parse_duration_ms = BASE.parse_duration_ms
parse_env_file = BASE.parse_env_file
sql_literal = BASE.sql_literal

ITEM_COUNTS = (3, 10, 25, 50, 100, 200)
MODES = ("noop", "reverse")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--compose-file", dest="compose_files", type=Path, action="append")
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--data-file", type=Path, required=True)
    parser.add_argument("--seed-tag", required=True)
    return parser.parse_args()


def safe_tag(value: str) -> str:
    tag = re.sub(r"[^A-Za-z0-9-]", "", value)
    if not tag:
        raise SeedError("--seed-tag must contain an alphanumeric character")
    return tag[-24:]


def insert_items(runtime: ComposeSeed, travel_id: str, item_count: int, seed_tag: str, mode: str) -> list[str]:
    item_ids = [str(uuid.uuid4()) for _ in range(item_count)]
    values = []
    for visit_order, item_id in enumerate(item_ids, start=1):
        values.append(
            "(" + ", ".join((
                sql_literal(item_id), sql_literal(travel_id), "1", "DATE '2026-08-01'", "NULL",
                sql_literal("기타"), "NULL", sql_literal(f"sql-diagnostic-{mode}-{item_count}-{visit_order}"),
                "NULL", str(visit_order), "NULL",
            )) + ")"
        )
    runtime.psql(
        "INSERT INTO timeline_table (id, planner_id, day_number, visit_date, city_id, category, "
        "food_subcategory, name, google_place_id, visit_order, memo) VALUES " + ",".join(values)
    )
    result = runtime.psql(
        "SELECT count(*) FROM timeline_table WHERE planner_id = " + sql_literal(travel_id) + " AND day_number = 1"
    ).strip()
    if result != str(item_count):
        raise SeedError("fixture item count verification failed")
    return item_ids


def write_credentials(path: Path, payload: dict[str, object]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
    os.replace(temporary, path)


def seed(args: argparse.Namespace) -> None:
    tag = safe_tag(args.seed_tag)
    env_values = parse_env_file(args.env_file)
    runtime = ComposeSeed(args, env_values)
    user_id = str(uuid.uuid4())
    provider_user_id = f"sql-diag-{tag}"
    nickname = "sql" + hashlib.sha256(tag.encode()).hexdigest()[:12]
    runtime.psql(
        "INSERT INTO user_table (id, provider, provider_user_id, email, name, nickname, "
        "profile_completed, created_at, updated_at) VALUES (" + ", ".join((
            sql_literal(user_id), "'GOOGLE'", sql_literal(provider_user_id),
            sql_literal(provider_user_id + "@diagnostic.local"), "'SQL Diagnostic'", sql_literal(nickname),
        "TRUE", "now()", "now()",
        )) + ")"
    )
    ttl_ms = parse_duration_ms(env_values.get("REFRESH_TOKEN_TTL"))
    refresh_token, family_id = runtime.seed_redis_token(user_id, ttl_ms)
    access_token, refresh_token = runtime.refresh(refresh_token)
    stages: dict[str, dict[str, object]] = {}
    stage_index = 0
    for item_count in ITEM_COUNTS:
        for mode in MODES:
            stage_index += 1
            travel_id = runtime.create_travel(access_token, 9000 + stage_index)
            item_ids = insert_items(runtime, travel_id, item_count, tag, mode)
            stages[f"{mode}-{item_count}"] = {
                "travelId": travel_id, "timelineItemIds": item_ids,
                "itemCount": item_count, "mode": mode,
            }
            print(f"[sql-seed] stage {stage_index}/12 prepared: {mode} itemCount={item_count}")
    write_credentials(args.data_file, {
        "seedVersion": "compose-sql-round-trip-s1", "seedTag": tag,
        "seededAt": datetime.now(timezone.utc).isoformat(),
        "credentials": [{
            "userId": user_id, "accessToken": access_token, "refreshToken": refresh_token,
            "refreshFamilyId": family_id, "visitDate": "2026-08-01", "sqlDiagnosticStages": stages,
        }],
    })
    print("[sql-seed] complete: 12 isolated stages prepared")


def main() -> int:
    args = parse_args()
    args.env_file = args.env_file.resolve()
    args.compose_files = [path.resolve() for path in (args.compose_files or [DEFAULT_COMPOSE_FILE])]
    args.data_file = args.data_file.resolve()
    if not args.env_file.is_file() or any(not path.is_file() for path in args.compose_files):
        raise SeedError("env-file and every compose-file must exist")
    seed(args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SeedError as error:
        print(f"[sql-seed] ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
