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
from urllib.parse import urlencode


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_FILE = REPOSITORY_ROOT / "load-tests/k6/data/data.json"
DEFAULT_ENV_FILE = REPOSITORY_ROOT / ".env.prod.example"
DEFAULT_COMPOSE_FILE = REPOSITORY_ROOT / "compose.yml"
DEFAULT_REFRESH_TTL_MS = 30 * 24 * 60 * 60 * 1000
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
CURRENT_FEATURE_FIXTURE_VERSION = "compose-current-feature-fixture-v1"
CURRENT_FEATURE_PLACE_IDS_PER_TRAVEL = 3


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
    parser.add_argument("--compose-file", dest="compose_files", type=Path, action="append")
    parser.add_argument("--project-name", default=os.environ.get("COMPOSE_PROJECT_NAME"))
    parser.add_argument("--base-url", default=os.environ.get("BASE_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--data-file", type=Path, default=DEFAULT_DATA_FILE)
    parser.add_argument("--seed-tag", default=None)
    parser.add_argument(
        "--current-feature",
        action="store_true",
        help="seed the Place and Community IDs required by the 26-operation current-feature flow",
    )
    parser.add_argument("--fixture-result-file", type=Path)
    return parser.parse_args()


class ComposeSeed:
    def __init__(self, args: argparse.Namespace, env_values: dict[str, str]) -> None:
        self.args = args
        self.env_values = env_values
        project_name = args.project_name or env_values.get("COMPOSE_PROJECT_NAME")
        if not project_name:
            raise SeedError("--project-name or COMPOSE_PROJECT_NAME is required")
        self.project_name = project_name
        self.compose_files = [path.resolve() for path in args.compose_files]
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
            *[argument for path in self.compose_files for argument in ("--file", str(path))],
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

    @staticmethod
    def current_feature_marker(seed_tag: str, index: int) -> str:
        safe_tag = re.sub(r"[^A-Za-z0-9-]", "", seed_tag)[-18:]
        return f"loadtest-{safe_tag}-{index:03d}"

    @classmethod
    def current_feature_place_ids(cls, seed_tag: str, index: int) -> list[str]:
        marker = cls.current_feature_marker(seed_tag, index)
        return [f"loadtest-{marker}-place-{place_index:03d}" for place_index in range(1, CURRENT_FEATURE_PLACE_IDS_PER_TRAVEL + 1)]

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
                    "googlePlaceId": getattr(self, "_active_place_ids", [None, None, None])[visit_order - 1],
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

    def _find_or_create_post(self, access_token: str, travel_id: str, marker: str) -> tuple[str, int]:
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
        seed_tag: str,
        index: int,
        travel_id: str,
        timeline_ids: list[str],
    ) -> dict:
        """Ensure every stateful ID used by the 26-operation flow exists."""
        place_ids = self.current_feature_place_ids(seed_tag, index)
        detail = self._travel_detail(access_token, travel_id)
        self._ensure_place_ids(access_token, travel_id, timeline_ids, place_ids, detail)
        marker = self.current_feature_marker(seed_tag, index)
        post_id, post_version = self._find_or_create_post(access_token, travel_id, marker)
        comment_id = self._find_or_create_comment(access_token, post_id, marker)
        travel_version = detail.get("version")
        if not isinstance(travel_version, int):
            raise SeedError("current-feature travel detail has no integer version")
        return {
            "fixtureMarker": marker,
            "placeIds": place_ids,
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
        if args.current_feature:
            runtime._active_place_ids = runtime.current_feature_place_ids(seed_tag, index)
        travel_id = runtime.create_travel(access_token, index)
        timeline_ids = runtime.create_timeline_items(access_token, travel_id)
        credential = {
            "userId": user_id,
            "travelId": travel_id,
            "refreshToken": refresh_token,
            "refreshFamilyId": family_id,
            "visitDate": "2026-08-01",
            "timelineItemIds": timeline_ids,
        }
        if args.current_feature:
            credential.update(runtime.ensure_current_feature_fixture(
                access_token, seed_tag, index, travel_id, timeline_ids,
            ))
        credentials.append(credential)
        print(f"[seed] user {index}/{args.users} prepared")
    payload = {
        "seedVersion": "s1",
        "seedTag": seed_tag,
        "seededAt": datetime.now(timezone.utc).isoformat(),
        "seedState": "complete",
        "fixtureState": "verified" if args.current_feature else "not-verified",
        "fixtureVersion": CURRENT_FEATURE_FIXTURE_VERSION if args.current_feature else None,
        "credentials": credentials,
    }
    runtime.write_credentials(payload, args.data_file)
    if args.fixture_result_file:
        result = {
            "schemaVersion": "compose-current-feature-fixture/v1",
            "status": "verified" if args.current_feature else "not-required",
            "seedTag": seed_tag,
            "users": len(credentials),
            "usersWithPlaceIds": sum(bool(item.get("placeIds")) for item in credentials),
            "usersWithCommunityPost": sum(bool(item.get("postId")) for item in credentials),
            "usersWithCommunityComment": sum(bool(item.get("commentId")) for item in credentials),
        }
        args.fixture_result_file.parent.mkdir(parents=True, exist_ok=True)
        args.fixture_result_file.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
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
    if not args.compose_files:
        args.compose_files = [DEFAULT_COMPOSE_FILE]
    args.compose_files = [path.resolve() for path in args.compose_files]
    args.data_file = args.data_file.resolve()
    if not args.env_file.exists() or any(not path.exists() for path in args.compose_files):
        raise SeedError("env-file and every compose-file must exist")
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
