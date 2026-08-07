#!/usr/bin/env python3
"""Seed isolated Compose data for the TravelPlanner load rehearsal.

The script deliberately consumes the existing runtime contracts instead of
adding a test-only backend endpoint. It creates fresh synthetic users and
travels for each phase, seeds the Redis refresh-token family, verifies one
real refresh rotation, and writes a 0600 credential file for k6.
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


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_FILE = REPOSITORY_ROOT / "load-tests/k6/data/data.json"
DEFAULT_ENV_FILE = REPOSITORY_ROOT / ".env.prod.example"
DEFAULT_COMPOSE_FILE = REPOSITORY_ROOT / "compose.yml"
DEFAULT_REFRESH_TTL_MS = 30 * 24 * 60 * 60 * 1000
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


class SeedError(RuntimeError):
    """A sanitized seed or contract verification failure."""


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[name.strip()] = value
    return values


def parse_duration_ms(value: str | None) -> int:
    if not value:
        return DEFAULT_REFRESH_TTL_MS
    match = re.fullmatch(r"(\d+)([smhd])", value.strip())
    if not match:
        raise SeedError("REFRESH_TOKEN_TTL must use a simple s/m/h/d duration")
    amount = int(match.group(1))
    multiplier = {"s": 1_000, "m": 60_000, "h": 3_600_000, "d": 86_400_000}[match.group(2)]
    return amount * multiplier


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def new_opaque_token() -> str:
    token = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")
    if not TOKEN_PATTERN.fullmatch(token):
        raise SeedError("generated opaque token has an invalid format")
    return token


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--tokens-only", action="store_true")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE_FILE)
    parser.add_argument("--project-name", default=os.environ.get("COMPOSE_PROJECT_NAME"))
    parser.add_argument("--base-url", default=os.environ.get("BASE_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--data-file", type=Path, default=DEFAULT_DATA_FILE)
    parser.add_argument("--seed-tag", default=None)
    return parser.parse_args()


class ComposeSeed:
    def __init__(self, args: argparse.Namespace, env_values: dict[str, str]) -> None:
        self.args = args
        self.env_values = env_values
        project_name = args.project_name or env_values.get("COMPOSE_PROJECT_NAME")
        if not project_name:
            raise SeedError("--project-name or COMPOSE_PROJECT_NAME is required")
        self.project_name = project_name
        self.compose_file = args.compose_file.resolve()
        self.env_file = args.env_file.resolve()
        self.base_url = args.base_url.rstrip("/")
        self.runtime_env = {**os.environ, **env_values}
        self.runtime_env["COMPOSE_PROJECT_NAME"] = project_name

    def compose_command(self, *parts: str) -> list[str]:
        return [
            "docker",
            "compose",
            "--env-file",
            str(self.env_file),
            "--project-name",
            self.project_name,
            "--file",
            str(self.compose_file),
            *parts,
        ]

    def run(self, command: list[str], input_text: str | None = None) -> str:
        completed = subprocess.run(
            command,
            input=input_text,
            capture_output=True,
            text=True,
            env=self.runtime_env,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip().splitlines()[-1:] or ["command failed"]
            raise SeedError(f"command failed ({completed.returncode}): {' '.join(command[:4])}; {detail[0]}")
        return completed.stdout

    def psql(self, sql: str) -> str:
        user = self.env_values.get("POSTGRES_USER", "postgres")
        database = self.env_values.get("POSTGRES_DB", "travelplanner")
        return self.run(self.compose_command(
            "exec", "--no-TTY", "postgres", "psql", "-v", "ON_ERROR_STOP=1",
            "-U", user, "-d", database, "-tA", "-c", sql,
        ))

    def redis(self, *arguments: str) -> str:
        password = self.env_values.get("REDIS_PASSWORD", "")
        return self.run(self.compose_command(
            "exec", "--no-TTY", "redis", "redis-cli", "--no-auth-warning",
            "-a", password, *arguments,
        ))

    def api(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        refresh_cookie: str | None = None,
        body: dict | None = None,
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

    def seed_redis_token(self, user_id: str, ttl_ms: int) -> tuple[str, str]:
        token = new_opaque_token()
        family_id = new_opaque_token()
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        self.redis("SET", f"auth:refresh:token:{token_hash}", f"{user_id}|{family_id}", "PX", str(ttl_ms))
        self.redis("SET", f"auth:refresh:family:{family_id}", token_hash, "PX", str(ttl_ms))
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
            "POST",
            "/travels",
            token=access_token,
            body={"title": f"LoadTest Travel {index}", "startDate": "2026-08-01", "endDate": "2026-08-05"},
        )
        travel_id = body.get("data", {}).get("travelId") if isinstance(body, dict) else None
        if status not in (200, 201) or not isinstance(travel_id, str):
            raise SeedError(f"travel creation contract failed with status {status}")
        return travel_id

    def create_timeline_items(self, access_token: str, travel_id: str) -> list[str]:
        item_ids: list[str] = []
        for visit_order in (1, 2, 3):
            status, body, _ = self.api(
                "POST",
                f"/travels/{travel_id}/timeline-items",
                token=access_token,
                body={
                    "dayNumber": 1,
                    "visitDate": "2026-08-01",
                    "category": "관광지",
                    "name": f"seed-item-{visit_order}",
                    "visitOrder": visit_order,
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


def seed_all(runtime: ComposeSeed, args: argparse.Namespace, ttl_ms: int) -> None:
    seed_tag = re.sub(r"[^A-Za-z0-9-]", "", args.seed_tag or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"))[-18:]
    credentials = []
    for index in range(1, args.users + 1):
        provider_user_id = f"loadtest-{seed_tag}-{index:03d}"
        user_id = str(uuid.uuid4())
        runtime.psql(
            "INSERT INTO user_table "
            "(id, provider, provider_user_id, email, name, nickname, profile_completed, created_at, updated_at) VALUES "
            f"({sql_literal(user_id)}, 'GOOGLE', {sql_literal(provider_user_id)}, "
            f"{sql_literal(provider_user_id + '@loadtest.local')}, {sql_literal('LoadTest ' + str(index))}, "
            f"{sql_literal('load' + seed_tag[-8:] + str(index))}, TRUE, now(), now())"
        )
        refresh_token, family_id = runtime.seed_redis_token(user_id, ttl_ms)
        access_token, refresh_token = runtime.refresh(refresh_token)
        travel_id = runtime.create_travel(access_token, index)
        timeline_ids = runtime.create_timeline_items(access_token, travel_id)
        credentials.append({
            "userId": user_id,
            "travelId": travel_id,
            "refreshToken": refresh_token,
            "refreshFamilyId": family_id,
            "visitDate": "2026-08-01",
            "timelineItemIds": timeline_ids,
        })
        print(f"[seed] user {index}/{args.users} prepared")
    runtime.write_credentials(
        {"seedVersion": "s1", "seedTag": seed_tag, "seededAt": datetime.now(timezone.utc).isoformat(), "credentials": credentials},
        args.data_file,
    )
    print(f"[seed] complete: {len(credentials)} synthetic users")


def refresh_only(runtime: ComposeSeed, args: argparse.Namespace, ttl_ms: int) -> None:
    path = args.data_file.resolve()
    if not path.exists():
        raise SeedError(f"credential file does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    for credential in payload.get("credentials", []):
        refresh_token, family_id = runtime.seed_redis_token(credential["userId"], ttl_ms)
        credential["refreshToken"] = refresh_token
        credential["refreshFamilyId"] = family_id
    payload["seededAt"] = datetime.now(timezone.utc).isoformat()
    runtime.write_credentials(payload, path)
    print(f"[seed] refresh tokens renewed: {len(payload.get('credentials', []))} synthetic users")


def main() -> int:
    args = parse_args()
    if args.users < 1 or args.users > 200:
        raise SeedError("--users must be between 1 and 200")
    args.env_file = args.env_file.resolve()
    args.compose_file = args.compose_file.resolve()
    args.data_file = args.data_file.resolve()
    if not args.env_file.exists() or not args.compose_file.exists():
        raise SeedError("env-file and compose-file must exist")
    env_values = parse_env_file(args.env_file)
    runtime = ComposeSeed(args, env_values)
    ttl_ms = parse_duration_ms(env_values.get("REFRESH_TOKEN_TTL"))
    if args.tokens_only:
        refresh_only(runtime, args, ttl_ms)
    else:
        seed_all(runtime, args, ttl_ms)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SeedError as error:
        print(f"[seed] ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
