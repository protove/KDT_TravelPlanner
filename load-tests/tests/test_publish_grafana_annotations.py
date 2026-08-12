"""Idempotency and tagging tests for the Grafana annotation publisher."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


MODULE_PATH = (
    Path(__file__).parents[2] / "scripts" / "loadtest" / "publish-grafana-annotations.py"
)
SPEC = importlib.util.spec_from_file_location("publish_grafana_annotations", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def build_run_dir(root: Path) -> Path:
    (root / "metadata.json").write_text(
        json.dumps({"runId": "aws-b02-anno-1", "scenario": "recovery-steady"}),
        encoding="utf-8",
    )
    events = [
        {"ts": "2026-08-12T08:00:00.000Z", "event": "RUN_START", "detail": "start"},
        {"ts": "2026-08-12T08:05:00.000Z", "event": "T1", "detail": "fault"},
        {"ts": "2026-08-12T08:07:00.000Z", "event": "T5", "detail": "healthy"},
    ]
    (root / "operations.jsonl").write_text(
        "\n".join(json.dumps(item) for item in events) + "\n", encoding="utf-8"
    )
    return root


class AnnotationPublisherTests(unittest.TestCase):
    def test_payloads_use_requested_context_tag(self) -> None:
        with TemporaryDirectory() as raw:
            run_dir = build_run_dir(Path(raw))
            payloads = MODULE.payloads(run_dir, "aws-recovery")
            self.assertEqual(len(payloads), 3)
            for annotation in payloads:
                self.assertEqual(annotation["tags"][0], "aws-recovery")
                self.assertIn("run:aws-b02-anno-1", annotation["tags"])
                self.assertIn("scenario:recovery-steady", annotation["tags"])

    def test_publish_skips_annotations_that_already_exist(self) -> None:
        with TemporaryDirectory() as raw:
            run_dir = build_run_dir(Path(raw))
            expected = MODULE.payloads(run_dir, "aws-recovery")
            posted: list[dict] = []

            def fake_fetch_existing(url, auth, run_tag, times):
                self.assertEqual(run_tag, "run:aws-b02-anno-1")
                return [expected[0], expected[1]]

            class FakeResponse:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

            def fake_urlopen(request, timeout=10):
                posted.append(json.loads(request.data.decode("utf-8")))
                return FakeResponse()

            original_fetch = MODULE.fetch_existing
            original_urlopen = MODULE.urlopen
            MODULE.fetch_existing = fake_fetch_existing
            MODULE.urlopen = fake_urlopen
            try:
                result = MODULE.publish(
                    run_dir, "http://grafana.local", "user", "secret", False, "aws-recovery"
                )
            finally:
                MODULE.fetch_existing = original_fetch
                MODULE.urlopen = original_urlopen
            self.assertEqual(result["skippedDuplicates"], 2)
            self.assertEqual(len(posted), 1)
            self.assertEqual(posted[0]["text"], expected[2]["text"])

    def test_dry_run_never_posts(self) -> None:
        with TemporaryDirectory() as raw:
            run_dir = build_run_dir(Path(raw))

            def explode(*args, **kwargs):
                raise AssertionError("dry-run must not contact Grafana")

            original_fetch = MODULE.fetch_existing
            original_urlopen = MODULE.urlopen
            MODULE.fetch_existing = explode
            MODULE.urlopen = explode
            try:
                result = MODULE.publish(
                    run_dir, "http://grafana.local", "user", "secret", True, "aws-recovery"
                )
            finally:
                MODULE.fetch_existing = original_fetch
                MODULE.urlopen = original_urlopen
            self.assertEqual(result["annotationCount"], 3)
            self.assertTrue(all(item["status"] == "dry-run" for item in result["results"]))


if __name__ == "__main__":
    unittest.main()
