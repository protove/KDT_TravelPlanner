import hashlib
import importlib.util
import json
import re
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


def _load(module_name: str, relative_path: str):
    script_path = Path(__file__).parents[2] / relative_path
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


SEED = _load("seed_aws_load_data", "scripts/loadtest/aws/seed-aws-load-data.py")
CLEANUP = _load("cleanup_aws_load_data", "scripts/loadtest/aws/cleanup-aws-load-data.py")
LIFECYCLE = sys.modules["refresh_credential_lifecycle"]

# Mirrors scripts/loadtest/verify-evidence-safety.py's synthetic_email pattern
# so the existing evidence safety scanner also covers AWS-seeded emails
# without any changes to that script.
SAFETY_SCANNER_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@loadtest\.local", re.IGNORECASE)


class FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class RefreshCredentialLifecycleTest(unittest.TestCase):
    def credential(self):
        return LIFECYCLE.RefreshCredential("a" * 43, "b" * 43)

    def test_active_token_is_rotated_then_reused_to_revoke_family(self):
        statuses = iter((200, 401))
        refresh_tokens = []
        deleted_keys = []

        result = LIFECYCLE.revoke_refresh_credentials(
            [self.credential()],
            lambda token: refresh_tokens.append(token) or next(statuses),
            lambda keys: deleted_keys.extend(keys) or 3,
        )

        self.assertEqual(refresh_tokens, ["a" * 43, "a" * 43])
        self.assertEqual(result.refresh_request_count, 2)
        self.assertEqual(result.redis_deleted_count, 3)
        token_hash = hashlib.sha256(("a" * 43).encode("utf-8")).hexdigest()
        self.assertEqual(
            deleted_keys,
            [
                f"auth:refresh:token:{token_hash}",
                "auth:refresh:family:" + "b" * 43,
                f"auth:refresh:used:{token_hash}",
            ],
        )

    def test_already_rotated_token_revokes_family_on_first_reuse(self):
        refresh_tokens = []
        result = LIFECYCLE.revoke_refresh_credentials(
            [self.credential()],
            lambda token: refresh_tokens.append(token) or 401,
            lambda keys: 0,
        )
        self.assertEqual(len(refresh_tokens), 1)
        self.assertEqual(result.refresh_request_count, 1)

    def test_unexpected_status_fails_without_exposing_token(self):
        with self.assertRaises(LIFECYCLE.CredentialLifecycleError) as context:
            LIFECYCLE.revoke_refresh_credentials(
                [self.credential()], lambda token: 500, lambda keys: 0,
            )
        self.assertNotIn("a" * 43, str(context.exception))
        self.assertNotIn("b" * 43, str(context.exception))

    def test_invalid_credential_file_fails_before_any_external_call(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            path.write_text(json.dumps({
                "runId": "run-a",
                "credentials": [{"refreshToken": "invalid", "refreshFamilyId": "b" * 43}],
            }), encoding="utf-8")
            with self.assertRaises(LIFECYCLE.CredentialLifecycleError):
                LIFECYCLE.revoke_credential_file(
                    path, "run-a", lambda token: calls.append(token) or 401,
                    lambda keys: calls.append(keys) or 0,
                )
        self.assertEqual(calls, [])


class SeedAwsLoadDataTest(unittest.TestCase):
    def test_provider_user_id_is_deterministic_and_bounded(self):
        first = SEED.provider_user_id("aws-b01-20260809-001", 7)
        second = SEED.provider_user_id("aws-b01-20260809-001", 7)
        self.assertEqual(first, second)
        self.assertEqual(first, "loadtest-aws-aws-b01-20260809-001-007")
        self.assertLessEqual(len(first), 255)

    def test_provider_user_id_differs_across_run_ids(self):
        a = SEED.provider_user_id("run-a", 1)
        b = SEED.provider_user_id("run-b", 1)
        self.assertNotEqual(a, b)

    def test_synthetic_nickname_fits_unique_column_limit(self):
        nickname = SEED.synthetic_nickname("aws-b01-20260809-001", 199)
        self.assertLessEqual(len(nickname), 30)
        self.assertEqual(nickname, SEED.synthetic_nickname("aws-b01-20260809-001", 199))

    def test_synthetic_email_matches_existing_safety_scanner(self):
        email = SEED.synthetic_email("aws-b01-20260809-001", 3)
        self.assertRegex(email, SAFETY_SCANNER_EMAIL_PATTERN)

    def test_sql_literal_escapes_single_quotes(self):
        self.assertEqual(SEED.sql_literal("o'brien"), "'o''brien'")

    def test_fixture_reset_is_scoped_to_run_owned_planners(self):
        runtime = object.__new__(SEED.AwsSeed)
        captured = []
        runtime.psql = lambda sql: captured.append(sql) or "2\n"

        self.assertEqual(runtime.reset_synthetic_planners("aws-b01-fixture"), 2)
        self.assertEqual(len(captured), 1)
        self.assertIn("DELETE FROM planners_table", captured[0])
        self.assertIn("provider_user_id LIKE 'loadtest-aws-aws-b01-fixture-%'", captured[0])
        self.assertNotIn("FLUSH", captured[0].upper())

    def test_fixture_counts_parse_sanitized_cardinality_contract(self):
        runtime = object.__new__(SEED.AwsSeed)
        captured = []
        runtime.psql = lambda sql: captured.append(sql) or "2|2|6|3|3\n"

        self.assertEqual(
            runtime.fixture_counts("aws-b01-fixture"),
            {
                "users": 2,
                "planners": 2,
                "timelineItems": 6,
                "minimumTimelineItemsPerPlanner": 3,
                "maximumTimelineItemsPerPlanner": 3,
            },
        )
        self.assertIn("planner_counts", captured[0])

    def test_fixture_count_validation_requires_normalized_three_item_planners(self):
        valid = {
            "users": 2,
            "planners": 2,
            "timelineItems": 6,
            "minimumTimelineItemsPerPlanner": 3,
            "maximumTimelineItemsPerPlanner": 3,
        }
        SEED.validate_fixture_counts(valid, 2)
        with self.assertRaises(SEED.SeedError):
            SEED.validate_fixture_counts({**valid, "timelineItems": 7}, 2)

    def test_opaque_token_matches_backend_format(self):
        token = SEED.new_opaque_token()
        self.assertEqual(len(token), 43)
        self.assertRegex(token, r"^[A-Za-z0-9_-]{43}$")

    def test_verify_account_rejects_non_12_digit_expected_id(self):
        with self.assertRaises(SEED.SeedError):
            SEED.verify_account("12345", "ap-northeast-2")

    def test_verify_account_raises_without_leaking_account_ids(self):
        original_run = subprocess.run
        subprocess.run = lambda *a, **k: FakeCompletedProcess(returncode=0, stdout="999999999999\n")
        try:
            with self.assertRaises(SEED.SeedError) as ctx:
                SEED.verify_account("111111111111", "ap-northeast-2")
            self.assertNotIn("999999999999", str(ctx.exception))
            self.assertNotIn("111111111111", str(ctx.exception))
        finally:
            subprocess.run = original_run

    def test_verify_account_passes_on_exact_match(self):
        original_run = subprocess.run
        subprocess.run = lambda *a, **k: FakeCompletedProcess(returncode=0, stdout="111111111111\n")
        try:
            SEED.verify_account("111111111111", "ap-northeast-2")  # must not raise
        finally:
            subprocess.run = original_run

    def test_read_secret_credential_requires_username_field(self):
        original_run = subprocess.run
        subprocess.run = lambda *a, **k: FakeCompletedProcess(returncode=0, stdout=json.dumps({"password": "s3cr3t"}))
        try:
            with self.assertRaises(SEED.SecretContractError):
                SEED.read_secret_credential("arn:aws:secretsmanager:...", "ap-northeast-2")
        finally:
            subprocess.run = original_run

    def test_read_secret_credential_requires_password_field(self):
        original_run = subprocess.run
        subprocess.run = lambda *a, **k: FakeCompletedProcess(returncode=0, stdout=json.dumps({"username": "test-db-user"}))
        try:
            with self.assertRaises(SEED.SecretContractError):
                SEED.read_secret_credential("arn:aws:secretsmanager:...", "ap-northeast-2")
        finally:
            subprocess.run = original_run

    def test_read_secret_credential_rejects_rds_master_secret_shape(self):
        # RDS-managed master secrets don't carry a 'username' field the same
        # way (and this must never be pointed at one anyway) — malformed/
        # unexpected JSON must fail loudly as a contract error, not silently
        # coerce.
        original_run = subprocess.run
        subprocess.run = lambda *a, **k: FakeCompletedProcess(returncode=0, stdout="not json")
        try:
            with self.assertRaises(SEED.SecretContractError):
                SEED.read_secret_credential("arn:aws:secretsmanager:...", "ap-northeast-2")
        finally:
            subprocess.run = original_run

    def test_read_secret_credential_extracts_username_and_password(self):
        original_run = subprocess.run
        subprocess.run = lambda *a, **k: FakeCompletedProcess(
            returncode=0, stdout=json.dumps({"username": "loadtest-db-user", "password": "s3cr3t"})
        )
        try:
            self.assertEqual(
                SEED.read_secret_credential("arn:aws:secretsmanager:...", "ap-northeast-2"),
                ("loadtest-db-user", "s3cr3t"),
            )
        finally:
            subprocess.run = original_run

    def test_generate_redis_iam_auth_token_fails_cleanly_without_botocore(self):
        missing_modules = {
            "botocore": None,
            "botocore.session": None,
            "botocore.auth": None,
            "botocore.awsrequest": None,
        }
        with mock.patch.dict(sys.modules, missing_modules):
            with self.assertRaises(SEED.SeedError) as ctx:
                SEED.generate_redis_iam_auth_token("loadtest-dev", "kdt-travelplanner-dev-redis", "ap-northeast-2")
        self.assertIn("botocore", str(ctx.exception))

    def test_generate_redis_iam_auth_token_uses_sigv4_query_contract(self):
        calls = []

        class FakeSession:
            def get_credentials(self):
                return object()

        class FakeRequest:
            def __init__(self, *, method, url):
                self.method = method
                self.url = url
                self.headers = {}

        class FakeSigner:
            def __init__(self, credentials, service_name, region, expires):
                calls.append((credentials, service_name, region, expires))

            def add_auth(self, request):
                self.request = request
                request.url += "&X-Amz-Signature=fake"

        botocore_module = types.ModuleType("botocore")
        botocore_module.__path__ = []
        session_module = types.ModuleType("botocore.session")
        session_module.get_session = lambda: FakeSession()
        auth_module = types.ModuleType("botocore.auth")
        auth_module.SigV4QueryAuth = FakeSigner
        awsrequest_module = types.ModuleType("botocore.awsrequest")
        awsrequest_module.AWSRequest = FakeRequest
        botocore_module.session = session_module

        original_modules = {name: sys.modules.get(name) for name in (
            "botocore", "botocore.session", "botocore.auth", "botocore.awsrequest",
        )}
        sys.modules.update({
            "botocore": botocore_module,
            "botocore.session": session_module,
            "botocore.auth": auth_module,
            "botocore.awsrequest": awsrequest_module,
        })
        try:
            seed_token = SEED.generate_redis_iam_auth_token(
                "loadtest-dev", "kdt-travelplanner-dev-redis", "ap-northeast-2",
            )
            cleanup_token = CLEANUP.generate_redis_iam_auth_token(
                "loadtest-dev", "kdt-travelplanner-dev-redis", "ap-northeast-2",
            )
        finally:
            for name, original in original_modules.items():
                if original is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = original

        self.assertIn("Action=connect", seed_token)
        self.assertIn("User=loadtest-dev", seed_token)
        self.assertIn("X-Amz-Signature=fake", seed_token)
        self.assertEqual(seed_token, cleanup_token)
        self.assertEqual(calls[0][1:], ("elasticache", "ap-northeast-2", 900))

    def test_redis_key_guards_reject_broad_or_malformed_keys(self):
        self.assertEqual(
            SEED.redis_refresh_token_key("a" * 64),
            "auth:refresh:token:" + "a" * 64,
        )
        self.assertEqual(
            SEED.redis_refresh_family_key("A" * 43),
            "auth:refresh:family:" + "A" * 43,
        )
        with self.assertRaises(SEED.SeedError):
            SEED.redis_refresh_token_key("*")
        with self.assertRaises(SEED.SeedError):
            SEED.redis_refresh_family_key("auth:refresh:family:*")
        with self.assertRaises(CLEANUP.CredentialFileError):
            CLEANUP.redis_refresh_token_key("not-a-sha256")
        with self.assertRaises(CLEANUP.CredentialFileError):
            CLEANUP.redis_refresh_family_key("*")

    def test_credential_file_is_written_with_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            runtime = object.__new__(SEED.AwsSeed)
            runtime.write_credentials({"credentials": []}, path)

            self.assertEqual(stat.S_IMODE(path.stat().st_mode), stat.S_IRUSR | stat.S_IWUSR)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"credentials": []})

    def test_docker_invocations_never_put_password_or_token_in_argv(self):
        captured = {}

        def fake_run(command, *, env=None, input_text=None):
            captured["command"] = command
            captured["env"] = env
            return "ok"

        original_run = SEED.run
        original_token_fn = SEED.generate_redis_iam_auth_token
        SEED.run = fake_run
        SEED.generate_redis_iam_auth_token = lambda user, rg, region: "signed-iam-token"
        try:
            runtime = object.__new__(SEED.AwsSeed)
            runtime.args = type("Args", (), {
                "database_host": "db.internal", "database_port": 5432,
                "database_name": "travel_diary_dev",
                "redis_host": "redis.internal", "redis_port": 6379,
                "redis_iam_user": "loadtest-dev", "redis_replication_group_id": "kdt-travelplanner-dev-redis",
                "region": "ap-northeast-2",
            })()
            runtime.database_username = "loadtest-db-user"
            runtime.database_password = "super-secret-db-password"
            runtime.psql("SELECT 1")
            self.assertNotIn("super-secret-db-password", captured["command"])
            self.assertIn("loadtest-db-user", captured["command"])
            self.assertEqual(captured["env"]["PGPASSWORD"], "super-secret-db-password")

            runtime.redis("SET", "k", "v")
            self.assertNotIn("signed-iam-token", captured["command"])
            self.assertIn("--user", captured["command"])
            self.assertIn("loadtest-dev", captured["command"])
            self.assertEqual(captured["env"]["REDISCLI_AUTH"], "signed-iam-token")
        finally:
            SEED.run = original_run
            SEED.generate_redis_iam_auth_token = original_token_fn

    def test_insert_user_does_not_include_psql_command_tag_in_user_id(self):
        runtime = object.__new__(SEED.AwsSeed)
        fixed_uuid = SEED.uuid.UUID("12345678-1234-5678-1234-567812345678")
        responses = iter([
            "",
            f"{fixed_uuid}\nINSERT 0 1\n",
        ])
        runtime.psql = lambda sql: next(responses)
        original_uuid4 = SEED.uuid.uuid4
        SEED.uuid.uuid4 = lambda: fixed_uuid
        try:
            user_id, already_existed = runtime.insert_user("aws-b01-command-tag", 1)
        finally:
            SEED.uuid.uuid4 = original_uuid4

        self.assertEqual(user_id, str(fixed_uuid))
        self.assertFalse(already_existed)

    def test_seed_all_gives_every_user_a_fresh_credential_even_when_skipped(self):
        # Regression test for the "credentials: [] overwrite" bug plus the
        # deeper staleness bug it was hiding: a user that's already fully
        # seeded (existing user_table + planners_table rows) must still get
        # a credentials[] entry with a *freshly minted* refresh token this
        # run, reusing its existing travel/timeline rather than either being
        # silently dropped from the file or given a possibly-expired token
        # carried over from whenever it was first seeded.
        runtime = object.__new__(SEED.AwsSeed)
        calls = {"seed_redis_token": [], "refresh": [], "create_travel": 0}

        def fake_insert_user(run_id, index):
            # user 2 is already fully seeded; the rest are brand new.
            return (f"user-{index}", index == 2)

        def fake_has_existing_travel(user_id):
            return user_id == "user-2"

        def fake_find_existing_travel(user_id):
            return "existing-travel-id"

        def fake_find_existing_timeline_items(travel_id):
            return ["existing-item-1", "existing-item-2", "existing-item-3"]

        def fake_seed_redis_token(user_id, ttl_ms, token, family_id):
            calls["seed_redis_token"].append(user_id)
            return (token, family_id)

        def fake_refresh(token):
            calls["refresh"].append(token)
            return (f"access-{token}", token)

        def fake_create_travel(access_token, index):
            calls["create_travel"] += 1
            return f"new-travel-{index}"

        def fake_create_timeline_items(access_token, travel_id):
            return [f"{travel_id}-item-1"]

        written = {}

        def fake_write_credentials(payload, path):
            written.update(payload)

        runtime.insert_user = fake_insert_user
        runtime.has_existing_travel = fake_has_existing_travel
        runtime.find_existing_travel = fake_find_existing_travel
        runtime.find_existing_timeline_items = fake_find_existing_timeline_items
        runtime.seed_redis_token = fake_seed_redis_token
        runtime.refresh = fake_refresh
        runtime.create_travel = fake_create_travel
        runtime.create_timeline_items = fake_create_timeline_items
        runtime.write_credentials = fake_write_credentials

        args = type("Args", (), {
            "run_id": "aws-b01-20260811-001", "users": 3, "refresh_ttl_ms": 1000,
            "data_file": Path("/tmp/unused.json"),
        })()

        SEED.seed_all(runtime, args)

        # Every user (including the skipped one) got a credentials entry.
        self.assertEqual(len(written["credentials"]), 3)
        self.assertEqual(written["skippedAlreadySeeded"], 1)

        skipped_entry = next(c for c in written["credentials"] if c["userId"] == "user-2")
        self.assertEqual(skipped_entry["travelId"], "existing-travel-id")
        self.assertEqual(skipped_entry["timelineItemIds"], ["existing-item-1", "existing-item-2", "existing-item-3"])
        # A fresh token was minted for the skipped user too, not carried
        # over from whatever token it had when first seeded.
        self.assertRegex(skipped_entry["refreshToken"], r"^[A-Za-z0-9_-]{43}$")

        # seed_redis_token/refresh ran for all 3 users, including the skip.
        self.assertEqual(sorted(calls["seed_redis_token"]), ["user-1", "user-2", "user-3"])
        self.assertEqual(len(calls["refresh"]), 3)
        # But the expensive travel/timeline creation only ran for the 2
        # genuinely-new users.
        self.assertEqual(calls["create_travel"], 2)

    def test_verified_fixture_is_recorded_before_complete_seed_state(self):
        runtime = object.__new__(SEED.AwsSeed)
        writes = []
        fixture_results = []
        runtime.insert_user = lambda run_id, index: (f"user-{index}", False)
        runtime.seed_redis_token = lambda user_id, ttl_ms, token, family_id: (token, family_id)
        runtime.refresh = lambda token: ("access-token", "r" * 43)
        runtime.has_existing_travel = lambda user_id: False
        runtime.create_travel = lambda access_token, index: f"travel-{index}"
        runtime.create_timeline_items = lambda access_token, travel_id: [
            f"{travel_id}-item-{item}" for item in (1, 2, 3)
        ]
        runtime.fixture_counts = lambda run_id: {
            "users": 2,
            "planners": 2,
            "timelineItems": 6,
            "minimumTimelineItemsPerPlanner": 3,
            "maximumTimelineItemsPerPlanner": 3,
        }
        runtime.write_credentials = lambda payload, path: writes.append(json.loads(json.dumps(payload)))
        runtime.write_fixture_result = lambda payload, path: fixture_results.append(json.loads(json.dumps(payload)))
        args = type("Args", (), {
            "run_id": "aws-b01-fixture-verified", "users": 2, "refresh_ttl_ms": 1000,
            "data_file": Path("/tmp/unused.json"), "fixture_id": "baseline-1",
            "fixture_result_file": Path("/tmp/fixture.json"),
        })()

        SEED.seed_all(runtime, args, reset_deleted_planners=2, verify_fixture=True)

        self.assertEqual(writes[-1]["seedState"], "complete")
        self.assertEqual(writes[-1]["fixtureState"], "verified")
        self.assertEqual(writes[-1]["fixtureId"], "baseline-1")
        self.assertTrue(writes[-1]["fixtureResetApplied"])
        self.assertEqual(writes[-1]["plannersDeletedBeforeSeed"], 2)
        self.assertEqual(fixture_results[-1]["actual"]["timelineItems"], 6)

    def test_fixture_mismatch_keeps_seed_in_progress_and_never_complete(self):
        runtime = object.__new__(SEED.AwsSeed)
        writes = []
        runtime.insert_user = lambda run_id, index: (f"user-{index}", False)
        runtime.seed_redis_token = lambda user_id, ttl_ms, token, family_id: (token, family_id)
        runtime.refresh = lambda token: ("access-token", "r" * 43)
        runtime.has_existing_travel = lambda user_id: False
        runtime.create_travel = lambda access_token, index: f"travel-{index}"
        runtime.create_timeline_items = lambda access_token, travel_id: [f"{travel_id}-item-1"]
        runtime.fixture_counts = lambda run_id: {
            "users": 1,
            "planners": 1,
            "timelineItems": 1,
            "minimumTimelineItemsPerPlanner": 1,
            "maximumTimelineItemsPerPlanner": 1,
        }
        runtime.write_credentials = lambda payload, path: writes.append(json.loads(json.dumps(payload)))
        args = type("Args", (), {
            "run_id": "aws-b01-fixture-invalid", "users": 1, "refresh_ttl_ms": 1000,
            "data_file": Path("/tmp/unused.json"), "fixture_id": "baseline-1",
            "fixture_result_file": None,
        })()

        with self.assertRaises(SEED.SeedError):
            SEED.seed_all(runtime, args, reset_deleted_planners=1, verify_fixture=True)

        self.assertEqual(writes[-1]["seedState"], "in-progress")
        self.assertEqual(writes[-1]["fixtureState"], "invalid")
        self.assertNotIn("complete", [payload["seedState"] for payload in writes])

    def test_seed_checkpoints_token_before_redis_mutation(self):
        runtime = object.__new__(SEED.AwsSeed)
        events = []
        writes = []
        runtime.insert_user = lambda run_id, index: ("user-1", False)
        runtime.seed_redis_token = (
            lambda user_id, ttl_ms, token, family_id:
            events.append(("redis", token, family_id)) or (token, family_id)
        )
        runtime.refresh = lambda token: ("access-token", "r" * 43)
        runtime.has_existing_travel = lambda user_id: False
        runtime.create_travel = lambda access_token, index: "travel-1"
        runtime.create_timeline_items = lambda access_token, travel_id: ["timeline-1"]

        def write_credentials(payload, path):
            writes.append(json.loads(json.dumps(payload)))
            events.append(("write", payload["credentials"][-1]["refreshToken"]))

        runtime.write_credentials = write_credentials
        args = type("Args", (), {
            "run_id": "aws-b01-checkpoint", "users": 1, "refresh_ttl_ms": 1000,
            "data_file": Path("/tmp/unused.json"),
        })()

        SEED.seed_all(runtime, args)

        self.assertEqual(events[0][0], "write")
        self.assertEqual(events[1][0], "redis")
        self.assertEqual(events[0][1], events[1][1])
        self.assertEqual(writes[0]["seedState"], "in-progress")
        self.assertEqual(writes[-1]["seedState"], "complete")
        self.assertEqual(writes[-1]["seedVersion"], "aws-s2")

    def test_seed_failure_keeps_private_in_progress_credential_checkpoint(self):
        runtime = object.__new__(SEED.AwsSeed)
        runtime.insert_user = lambda run_id, index: ("user-1", False)
        runtime.seed_redis_token = mock.Mock(side_effect=SEED.SeedError("redis unavailable"))
        runtime.write_credentials = SEED.AwsSeed.write_credentials.__get__(runtime, SEED.AwsSeed)

        with tempfile.TemporaryDirectory() as directory:
            data_file = Path(directory) / "data.json"
            args = type("Args", (), {
                "run_id": "aws-b01-partial", "users": 1, "refresh_ttl_ms": 1000,
                "data_file": data_file,
            })()
            with self.assertRaises(SEED.SeedError):
                SEED.seed_all(runtime, args)

            payload = json.loads(data_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["seedState"], "in-progress")
            self.assertEqual(len(payload["credentials"]), 1)
            self.assertRegex(payload["credentials"][0]["refreshToken"], r"^[A-Za-z0-9_-]{43}$")
            self.assertEqual(stat.S_IMODE(data_file.stat().st_mode), stat.S_IRUSR | stat.S_IWUSR)

    def test_previous_credential_file_is_revoked_before_reseeding(self):
        runtime = type("Runtime", (), {
            "refresh_status": lambda self, token: 401,
            "delete_exact_refresh_keys": lambda self, keys: 0,
        })()
        result = type("Result", (), {
            "credential_count": 1, "redis_deleted_count": 3, "redis_key_count": 3,
        })()
        with tempfile.TemporaryDirectory() as directory:
            data_file = Path(directory) / "data.json"
            data_file.write_text("{}", encoding="utf-8")
            args = type("Args", (), {
                "data_file": data_file, "run_id": "aws-b01-lifecycle-test",
            })()
            with mock.patch.object(SEED, "revoke_credential_file", return_value=result) as revoke:
                SEED.revoke_previous_credentials(runtime, args)

        revoke.assert_called_once_with(
            data_file,
            "aws-b01-lifecycle-test",
            runtime.refresh_status,
            runtime.delete_exact_refresh_keys,
        )


class CleanupResultFileTest(unittest.TestCase):
    def test_write_result_is_a_noop_when_no_path_given(self):
        # Must not raise even though None has no .resolve()/.write_text().
        CLEANUP.write_result(None, {"runId": "x"})

    def test_write_result_writes_json_with_completed_at(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cleanup-result.json"
            CLEANUP.write_result(path, {"runId": "aws-b01-20260811-001", "matchedUserCount": 3})
            written = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(written["runId"], "aws-b01-20260811-001")
            self.assertEqual(written["matchedUserCount"], 3)
            self.assertIn("completedAtUtc", written)

    def test_write_result_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "cleanup-result.json"
            CLEANUP.write_result(path, {"runId": "x"})
            self.assertTrue(path.exists())

    def test_main_writes_zero_match_result(self):
        original_verify = CLEANUP.verify_account
        original_read_secret = CLEANUP.read_secret_credential
        original_count = CLEANUP.matching_user_count
        CLEANUP.verify_account = lambda *a, **k: None
        CLEANUP.read_secret_credential = lambda *a, **k: ("u", "p")
        CLEANUP.matching_user_count = lambda *a, **k: 0
        try:
            with tempfile.TemporaryDirectory() as directory:
                result_path = Path(directory) / "cleanup-result.json"
                sys.argv = [
                    "cleanup-aws-load-data.py", "--run-id", "aws-b01-20260811-001",
                    "--expected-account-id", "111111111111", "--region", "ap-northeast-2",
                    "--database-host", "db.internal", "--database-name", "travel_diary_dev",
                    "--database-secret-arn", "arn:aws:secretsmanager:...",
                    "--result-file", str(result_path),
                ]
                self.assertEqual(CLEANUP.main(), 0)
                written = json.loads(result_path.read_text(encoding="utf-8"))
                self.assertEqual(written["matchedUserCount"], 0)
                self.assertFalse(written["dbDeleted"])
                self.assertEqual(written["redisSkippedReason"], "no-matching-data")
        finally:
            CLEANUP.verify_account = original_verify
            CLEANUP.read_secret_credential = original_read_secret
            CLEANUP.matching_user_count = original_count

    def test_main_writes_dry_run_result(self):
        original_verify = CLEANUP.verify_account
        original_read_secret = CLEANUP.read_secret_credential
        original_count = CLEANUP.matching_user_count
        CLEANUP.verify_account = lambda *a, **k: None
        CLEANUP.read_secret_credential = lambda *a, **k: ("u", "p")
        CLEANUP.matching_user_count = lambda *a, **k: 5
        try:
            with tempfile.TemporaryDirectory() as directory:
                result_path = Path(directory) / "cleanup-result.json"
                sys.argv = [
                    "cleanup-aws-load-data.py", "--run-id", "aws-b01-20260811-001",
                    "--expected-account-id", "111111111111", "--region", "ap-northeast-2",
                    "--database-host", "db.internal", "--database-name", "travel_diary_dev",
                    "--database-secret-arn", "arn:aws:secretsmanager:...",
                    "--result-file", str(result_path), "--dry-run",
                ]
                self.assertEqual(CLEANUP.main(), 0)
                written = json.loads(result_path.read_text(encoding="utf-8"))
                self.assertEqual(written["matchedUserCount"], 5)
                self.assertTrue(written["dryRun"])
                self.assertFalse(written["dbDeleted"])
        finally:
            CLEANUP.verify_account = original_verify
            CLEANUP.read_secret_credential = original_read_secret
            CLEANUP.matching_user_count = original_count

    def test_main_writes_full_result_with_redis_skipped(self):
        original_verify = CLEANUP.verify_account
        original_read_secret = CLEANUP.read_secret_credential
        original_count = CLEANUP.matching_user_count
        original_delete = CLEANUP.delete_matching_rows
        CLEANUP.verify_account = lambda *a, **k: None
        CLEANUP.read_secret_credential = lambda *a, **k: ("u", "p")
        CLEANUP.matching_user_count = lambda *a, **k: 2
        CLEANUP.delete_matching_rows = lambda *a, **k: None
        try:
            with tempfile.TemporaryDirectory() as directory:
                result_path = Path(directory) / "cleanup-result.json"
                sys.argv = [
                    "cleanup-aws-load-data.py", "--run-id", "aws-b01-20260811-001",
                    "--expected-account-id", "111111111111", "--region", "ap-northeast-2",
                    "--database-host", "db.internal", "--database-name", "travel_diary_dev",
                    "--database-secret-arn", "arn:aws:secretsmanager:...",
                    "--result-file", str(result_path),
                ]
                self.assertEqual(CLEANUP.main(), 0)
                written = json.loads(result_path.read_text(encoding="utf-8"))
                self.assertEqual(written["matchedUserCount"], 2)
                self.assertTrue(written["dbDeleted"])
                self.assertIsNone(written["redisKeysDeleted"])
                self.assertEqual(written["redisSkippedReason"], "no-redis-args")
        finally:
            CLEANUP.verify_account = original_verify
            CLEANUP.read_secret_credential = original_read_secret
            CLEANUP.matching_user_count = original_count
            CLEANUP.delete_matching_rows = original_delete

    def test_main_revokes_refresh_families_before_database_delete(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            data_file = Path(directory) / "data.json"
            data_file.write_text("{}", encoding="utf-8")
            result_file = Path(directory) / "cleanup-result.json"
            argv = [
                "cleanup-aws-load-data.py", "--run-id", "aws-b01-20260811-001",
                "--expected-account-id", "111111111111", "--region", "ap-northeast-2",
                "--database-host", "db.internal", "--database-name", "travel_diary_dev",
                "--database-secret-arn", "arn:aws:secretsmanager:...",
                "--redis-host", "redis.internal", "--redis-iam-user", "loadtest-dev",
                "--redis-replication-group-id", "travel-redis", "--data-file", str(data_file),
                "--base-url", "https://api.example.com", "--result-file", str(result_file),
            ]
            with (
                mock.patch.object(CLEANUP, "verify_account"),
                mock.patch.object(CLEANUP, "read_secret_credential", return_value=("u", "p")),
                mock.patch.object(CLEANUP, "matching_user_count", return_value=2),
                mock.patch.object(
                    CLEANUP, "cleanup_redis",
                    side_effect=lambda *args: calls.append("credentials") or (2, 6, 6),
                ),
                mock.patch.object(
                    CLEANUP, "delete_matching_rows",
                    side_effect=lambda *args: calls.append("database"),
                ),
                mock.patch.object(sys, "argv", argv),
            ):
                self.assertEqual(CLEANUP.main(), 0)

            self.assertEqual(calls, ["credentials", "database"])
            written = json.loads(result_file.read_text(encoding="utf-8"))
            self.assertEqual(written["refreshFamiliesRevoked"], 2)
            self.assertEqual(written["redisExactKeyCount"], 6)


class CleanupAwsLoadDataTest(unittest.TestCase):
    def test_like_pattern_prefix_is_hardcoded(self):
        pattern = CLEANUP.like_pattern("aws-b01-20260809-001")
        self.assertTrue(pattern.startswith("loadtest-aws-"))
        self.assertEqual(pattern, "loadtest-aws-aws-b01-20260809-001-%")

    def test_like_pattern_cannot_be_widened_by_run_id_content(self):
        # RUN_ID_PATTERN only allows [A-Za-z0-9-], so run_id itself can never
        # inject a LIKE wildcard; this documents that guarantee explicitly.
        self.assertIsNone(CLEANUP.RUN_ID_PATTERN.fullmatch("evil%"))
        self.assertIsNone(CLEANUP.RUN_ID_PATTERN.fullmatch("evil_"))

    def test_sql_literal_escapes_single_quotes(self):
        self.assertEqual(CLEANUP.sql_literal("o'brien"), "'o''brien'")

    def test_verify_account_rejects_non_12_digit_expected_id(self):
        with self.assertRaises(CLEANUP.CleanupError):
            CLEANUP.verify_account("abc", "ap-northeast-2")

    def test_read_secret_credential_requires_username_field(self):
        original_run = subprocess.run
        subprocess.run = lambda *a, **k: FakeCompletedProcess(returncode=0, stdout=json.dumps({"password": "s3cr3t"}))
        try:
            with self.assertRaises(CLEANUP.SecretContractError):
                CLEANUP.read_secret_credential("arn:aws:secretsmanager:...", "ap-northeast-2")
        finally:
            subprocess.run = original_run

    def test_read_secret_credential_extracts_username_and_password(self):
        original_run = subprocess.run
        subprocess.run = lambda *a, **k: FakeCompletedProcess(
            returncode=0, stdout=json.dumps({"username": "loadtest-db-user", "password": "s3cr3t"})
        )
        try:
            self.assertEqual(
                CLEANUP.read_secret_credential("arn:aws:secretsmanager:...", "ap-northeast-2"),
                ("loadtest-db-user", "s3cr3t"),
            )
        finally:
            subprocess.run = original_run

    def test_generate_redis_iam_auth_token_fails_cleanly_without_botocore(self):
        missing_modules = {
            "botocore": None,
            "botocore.session": None,
            "botocore.auth": None,
            "botocore.awsrequest": None,
        }
        with mock.patch.dict(sys.modules, missing_modules):
            with self.assertRaises(CLEANUP.CleanupError) as ctx:
                CLEANUP.generate_redis_iam_auth_token("loadtest-dev", "kdt-travelplanner-dev-redis", "ap-northeast-2")
        self.assertIn("botocore", str(ctx.exception))

    def test_matching_user_count_parses_psql_output(self):
        original_psql = CLEANUP.psql
        CLEANUP.psql = lambda args, username, password, sql: "3\n"
        try:
            self.assertEqual(CLEANUP.matching_user_count(object(), "u", "pw", "aws-b01-20260809-001"), 3)
        finally:
            CLEANUP.psql = original_psql

    def test_matching_user_count_zero_means_nothing_to_delete(self):
        original_psql = CLEANUP.psql
        CLEANUP.psql = lambda args, username, password, sql: ""
        try:
            self.assertEqual(CLEANUP.matching_user_count(object(), "u", "pw", "aws-b01-20260809-001"), 0)
        finally:
            CLEANUP.psql = original_psql

    def test_cleanup_redis_missing_data_file_is_a_credential_file_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "does-not-exist.json"
            args = type("Args", (), {"data_file": path})()
            with self.assertRaises(CLEANUP.CredentialFileError):
                CLEANUP.cleanup_redis(args, "aws-b01-20260809-001")

    def test_cleanup_redis_refuses_mismatched_run_id(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            path.write_text(json.dumps({"runId": "other-run", "credentials": []}), encoding="utf-8")
            args = type("Args", (), {"data_file": path})()
            with self.assertRaises(CLEANUP.CredentialFileError):
                CLEANUP.cleanup_redis(args, "aws-b01-20260809-001")

    def test_cleanup_redis_deletes_exact_recorded_keys_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            refresh_token = "a" * 43
            family_id = "b" * 43
            path.write_text(json.dumps({
                "runId": "aws-b01-20260809-001",
                "credentials": [{"userId": "u1", "refreshToken": refresh_token, "refreshFamilyId": family_id}],
            }), encoding="utf-8")
            args = type("Args", (), {
                "data_file": path, "redis_host": "redis.internal", "redis_port": 6379,
                "redis_iam_user": "loadtest-dev", "redis_replication_group_id": "kdt-travelplanner-dev-redis",
                "base_url": "https://api.example.com",
            })()

            captured_keys = []
            original_redis = CLEANUP.redis
            original_refresh_status = CLEANUP.refresh_status
            CLEANUP.refresh_status = lambda a, token: 401
            CLEANUP.redis = lambda a, *arguments: captured_keys.append(arguments) or "3"
            try:
                family_count, deleted, exact_key_count = CLEANUP.cleanup_redis(
                    args, "aws-b01-20260809-001"
                )
            finally:
                CLEANUP.redis = original_redis
                CLEANUP.refresh_status = original_refresh_status

            self.assertEqual((family_count, deleted, exact_key_count), (1, 3, 3))
            expected_token_hash = hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()
            self.assertEqual(len(captured_keys), 1)
            self.assertEqual(captured_keys[0][0], "DEL")
            self.assertIn(f"auth:refresh:token:{expected_token_hash}", captured_keys[0])
            self.assertIn(f"auth:refresh:family:{family_id}", captured_keys[0])
            self.assertIn(f"auth:refresh:used:{expected_token_hash}", captured_keys[0])

    def test_docker_invocations_never_put_password_or_token_in_argv(self):
        captured = {}

        def fake_run(command, *, env=None):
            captured["command"] = command
            captured["env"] = env
            return "ok"

        original_run = CLEANUP.run
        original_token_fn = CLEANUP.generate_redis_iam_auth_token
        CLEANUP.run = fake_run
        CLEANUP.generate_redis_iam_auth_token = lambda user, rg, region: "signed-iam-token"
        try:
            args = type("Args", (), {
                "database_host": "db.internal", "database_port": 5432,
                "database_name": "travel_diary_dev",
                "redis_host": "redis.internal", "redis_port": 6379,
                "redis_iam_user": "loadtest-dev", "redis_replication_group_id": "kdt-travelplanner-dev-redis",
                "region": "ap-northeast-2",
            })()
            CLEANUP.psql(args, "loadtest-db-user", "super-secret-db-password", "SELECT 1")
            self.assertNotIn("super-secret-db-password", captured["command"])
            self.assertIn("loadtest-db-user", captured["command"])
            self.assertEqual(captured["env"]["PGPASSWORD"], "super-secret-db-password")

            CLEANUP.redis(args, "PING")
            self.assertNotIn("signed-iam-token", captured["command"])
            self.assertIn("--user", captured["command"])
            self.assertEqual(captured["env"]["REDISCLI_AUTH"], "signed-iam-token")
        finally:
            CLEANUP.run = original_run
            CLEANUP.generate_redis_iam_auth_token = original_token_fn


if __name__ == "__main__":
    unittest.main()
