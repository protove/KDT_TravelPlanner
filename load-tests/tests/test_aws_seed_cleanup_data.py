import hashlib
import importlib.util
import json
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


def _load(module_name: str, relative_path: str):
    script_path = Path(__file__).parents[2] / relative_path
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


SEED = _load("seed_aws_load_data", "scripts/loadtest/aws/seed-aws-load-data.py")
CLEANUP = _load("cleanup_aws_load_data", "scripts/loadtest/aws/cleanup-aws-load-data.py")

# Mirrors scripts/loadtest/verify-evidence-safety.py's synthetic_email pattern
# so the existing evidence safety scanner also covers AWS-seeded emails
# without any changes to that script.
SAFETY_SCANNER_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@loadtest\.local", re.IGNORECASE)


class FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


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

    def test_read_secret_password_requires_password_field(self):
        original_run = subprocess.run
        subprocess.run = lambda *a, **k: FakeCompletedProcess(returncode=0, stdout=json.dumps({"username": "x"}))
        try:
            with self.assertRaises(SEED.SeedError):
                SEED.read_secret_password("arn:aws:secretsmanager:...", "ap-northeast-2")
        finally:
            subprocess.run = original_run

    def test_read_secret_password_extracts_password(self):
        original_run = subprocess.run
        subprocess.run = lambda *a, **k: FakeCompletedProcess(returncode=0, stdout=json.dumps({"password": "s3cr3t"}))
        try:
            self.assertEqual(SEED.read_secret_password("arn:aws:secretsmanager:...", "ap-northeast-2"), "s3cr3t")
        finally:
            subprocess.run = original_run

    def test_credential_file_is_written_with_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            runtime = object.__new__(SEED.AwsSeed)
            runtime.write_credentials({"credentials": []}, path)

            self.assertEqual(stat.S_IMODE(path.stat().st_mode), stat.S_IRUSR | stat.S_IWUSR)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"credentials": []})

    def test_docker_invocations_never_put_password_in_argv(self):
        captured = {}

        def fake_run(command, *, env=None, input_text=None):
            captured["command"] = command
            captured["env"] = env
            return "ok"

        original_run = SEED.run
        SEED.run = fake_run
        try:
            runtime = object.__new__(SEED.AwsSeed)
            runtime.args = type("Args", (), {
                "database_host": "db.internal", "database_port": 5432,
                "database_user": "travel_planner", "database_name": "travel_diary_dev",
                "redis_host": "redis.internal", "redis_port": 6379,
            })()
            runtime.database_password = "super-secret-db-password"
            runtime.redis_password = "super-secret-redis-password"
            runtime.psql("SELECT 1")
            self.assertNotIn("super-secret-db-password", captured["command"])
            self.assertEqual(captured["env"]["PGPASSWORD"], "super-secret-db-password")

            runtime.redis("PING")
            self.assertNotIn("super-secret-redis-password", captured["command"])
            self.assertEqual(captured["env"]["REDISCLI_AUTH"], "super-secret-redis-password")
        finally:
            SEED.run = original_run


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

    def test_matching_user_count_parses_psql_output(self):
        original_psql = CLEANUP.psql
        CLEANUP.psql = lambda args, password, sql: "3\n"
        try:
            self.assertEqual(CLEANUP.matching_user_count(object(), "pw", "aws-b01-20260809-001"), 3)
        finally:
            CLEANUP.psql = original_psql

    def test_matching_user_count_zero_means_nothing_to_delete(self):
        original_psql = CLEANUP.psql
        CLEANUP.psql = lambda args, password, sql: ""
        try:
            self.assertEqual(CLEANUP.matching_user_count(object(), "pw", "aws-b01-20260809-001"), 0)
        finally:
            CLEANUP.psql = original_psql

    def test_cleanup_redis_refuses_mismatched_run_id(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            path.write_text(json.dumps({"runId": "other-run", "credentials": []}), encoding="utf-8")
            args = type("Args", (), {"data_file": path})()
            with self.assertRaises(CLEANUP.CleanupError):
                CLEANUP.cleanup_redis(args, "pw", "aws-b01-20260809-001")

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
            })()

            captured_keys = []
            original_redis = CLEANUP.redis
            CLEANUP.redis = lambda a, password, *arguments: captured_keys.append(arguments) or "1"
            try:
                deleted = CLEANUP.cleanup_redis(args, "pw", "aws-b01-20260809-001")
            finally:
                CLEANUP.redis = original_redis

            self.assertEqual(deleted, 2)
            expected_token_hash = hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()
            self.assertIn(("DEL", f"auth:refresh:token:{expected_token_hash}"), captured_keys)
            self.assertIn(("DEL", f"auth:refresh:family:{family_id}"), captured_keys)

    def test_docker_invocations_never_put_password_in_argv(self):
        captured = {}

        def fake_run(command, *, env=None):
            captured["command"] = command
            captured["env"] = env
            return "ok"

        original_run = CLEANUP.run
        CLEANUP.run = fake_run
        try:
            args = type("Args", (), {
                "database_host": "db.internal", "database_port": 5432,
                "database_user": "travel_planner", "database_name": "travel_diary_dev",
            })()
            CLEANUP.psql(args, "super-secret-db-password", "SELECT 1")
            self.assertNotIn("super-secret-db-password", captured["command"])
            self.assertEqual(captured["env"]["PGPASSWORD"], "super-secret-db-password")
        finally:
            CLEANUP.run = original_run


if __name__ == "__main__":
    unittest.main()
