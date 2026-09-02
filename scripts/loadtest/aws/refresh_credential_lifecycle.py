"""Safely revoke AWS load-test refresh-token families from a credential file.

The load-test Redis IAM user intentionally has no read commands. Revocation
therefore uses the backend's existing refresh-token reuse detection and then
deletes only keys that can be derived exactly from the private credential
file. No token, cookie, response body, or Redis value is returned or logged.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
TOKEN_HASH_PATTERN = re.compile(r"^[a-f0-9]{64}$")
MAX_REFRESH_REVOCATION_ATTEMPTS = 4
REFRESH_REVOCATION_RETRY_SECONDS = 0.25


class CredentialLifecycleError(RuntimeError):
    """A sanitized credential-file or token-family revocation failure."""


@dataclass(frozen=True)
class RefreshCredential:
    refresh_token: str
    family_id: str


@dataclass(frozen=True)
class RevocationResult:
    credential_count: int
    refresh_request_count: int
    redis_key_count: int
    redis_deleted_count: int


def redis_refresh_token_key(token_hash: str) -> str:
    if not TOKEN_HASH_PATTERN.fullmatch(token_hash):
        raise CredentialLifecycleError(
            "refusing to address a Redis key outside the refresh-token namespace"
        )
    return f"auth:refresh:token:{token_hash}"


def redis_refresh_family_key(family_id: str) -> str:
    if not TOKEN_PATTERN.fullmatch(family_id):
        raise CredentialLifecycleError(
            "refusing to address a Redis key outside the refresh-family namespace"
        )
    return f"auth:refresh:family:{family_id}"


def redis_used_refresh_token_key(token_hash: str) -> str:
    if not TOKEN_HASH_PATTERN.fullmatch(token_hash):
        raise CredentialLifecycleError(
            "refusing to address a Redis key outside the used-refresh-token namespace"
        )
    return f"auth:refresh:used:{token_hash}"


def load_refresh_credentials(path: Path, expected_run_id: str) -> list[RefreshCredential]:
    path = path.resolve()
    if not path.exists():
        raise CredentialLifecycleError("--data-file does not exist")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CredentialLifecycleError("--data-file is not valid readable JSON") from error
    if not isinstance(payload, dict) or payload.get("runId") != expected_run_id:
        raise CredentialLifecycleError(
            "--data-file runId does not match --run-id; refusing to touch its credential state"
        )
    raw_credentials = payload.get("credentials")
    if not isinstance(raw_credentials, list) or not raw_credentials:
        raise CredentialLifecycleError("--data-file must contain at least one credential")

    credentials: list[RefreshCredential] = []
    for raw_credential in raw_credentials:
        if not isinstance(raw_credential, dict):
            raise CredentialLifecycleError("--data-file contains an invalid credential entry")
        refresh_token = raw_credential.get("refreshToken")
        family_id = raw_credential.get("refreshFamilyId")
        if not isinstance(refresh_token, str) or not TOKEN_PATTERN.fullmatch(refresh_token):
            raise CredentialLifecycleError("--data-file contains an invalid refresh token")
        if not isinstance(family_id, str) or not TOKEN_PATTERN.fullmatch(family_id):
            raise CredentialLifecycleError("--data-file contains an invalid refresh family ID")
        credentials.append(RefreshCredential(refresh_token, family_id))
    return credentials


def revoke_refresh_credentials(
    credentials: Sequence[RefreshCredential],
    refresh_status: Callable[[str], int],
    delete_exact_redis_keys: Callable[[Sequence[str]], int],
) -> RevocationResult:
    """Revoke each family without Redis reads, then delete exact known keys.

    A stored token that is still active returns 200 once. Reusing that same
    token immediately must return 401 and invokes the backend's family
    revocation path. A token already rotated by k6 returns 401 on the first
    request and invokes the same path. Any other status is a contract failure.
    """

    refresh_request_count = 0
    redis_keys: list[str] = []
    for credential in credentials:
        def request_status() -> int:
            nonlocal refresh_request_count
            last_status = 0
            for attempt in range(MAX_REFRESH_REVOCATION_ATTEMPTS):
                last_status = refresh_status(credential.refresh_token)
                refresh_request_count += 1
                if last_status in (200, 401):
                    return last_status
                if attempt + 1 < MAX_REFRESH_REVOCATION_ATTEMPTS:
                    time.sleep(REFRESH_REVOCATION_RETRY_SECONDS * (2 ** attempt))
            return last_status

        first_status = request_status()
        if first_status == 200:
            second_status = None
            for reuse_attempt in range(MAX_REFRESH_REVOCATION_ATTEMPTS):
                second_status = request_status()
                if second_status == 401:
                    break
                # A second 200 means the backend observed a rotation race;
                # retry the exact original token until reuse is rejected.
                if reuse_attempt + 1 < MAX_REFRESH_REVOCATION_ATTEMPTS:
                    time.sleep(REFRESH_REVOCATION_RETRY_SECONDS)
            if second_status != 401:
                raise CredentialLifecycleError(
                    "refresh-token reuse revocation failed with an unexpected status"
                )
        elif first_status != 401:
            raise CredentialLifecycleError(
                "refresh-token family revocation failed with an unexpected status"
            )

        token_hash = hashlib.sha256(credential.refresh_token.encode("utf-8")).hexdigest()
        redis_keys.extend(
            (
                redis_refresh_token_key(token_hash),
                redis_refresh_family_key(credential.family_id),
                redis_used_refresh_token_key(token_hash),
            )
        )

    redis_deleted_count = delete_exact_redis_keys(redis_keys)
    if not isinstance(redis_deleted_count, int) or not 0 <= redis_deleted_count <= len(redis_keys):
        raise CredentialLifecycleError("Redis DEL returned an invalid deletion count")
    return RevocationResult(
        credential_count=len(credentials),
        refresh_request_count=refresh_request_count,
        redis_key_count=len(redis_keys),
        redis_deleted_count=redis_deleted_count,
    )


def revoke_credential_file(
    path: Path,
    expected_run_id: str,
    refresh_status: Callable[[str], int],
    delete_exact_redis_keys: Callable[[Sequence[str]], int],
) -> RevocationResult:
    credentials = load_refresh_credentials(path, expected_run_id)
    return revoke_refresh_credentials(credentials, refresh_status, delete_exact_redis_keys)
