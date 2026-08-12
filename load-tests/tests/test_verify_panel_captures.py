"""Tests for the Grafana panel PNG capture verifier."""

from __future__ import annotations

import importlib.util
import json
import struct
import unittest
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory


MODULE_PATH = (
    Path(__file__).parents[2] / "scripts" / "loadtest" / "aws" / "verify-panel-captures.py"
)
SPEC = importlib.util.spec_from_file_location("verify_panel_captures", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def make_png(width: int, height: int, pad_to: int = 9000) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = b"\x00" + b"\x7f" * (width * 3)
    idat = zlib.compress(row * height)
    png = (
        MODULE.PNG_SIGNATURE
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )
    if len(png) < pad_to:
        png += chunk(b"tEXt", b"pad\x00" + b"0" * (pad_to - len(png)))
    return png


def build_fixture(root: Path, *, panel_ids=(2, 3), png_size=(800, 400)) -> None:
    summary = {
        "runId": "aws-b02-capture-1",
        "fromUtc": "2026-08-12T08:00:00Z",
        "toUtc": "2026-08-12T09:00:00Z",
        "dashboardUid": "aws-recovery",
        "dashboardVersion": 4,
    }
    (root / "recovery-export-summary.json").write_text(json.dumps(summary), encoding="utf-8")
    panels = root / "grafana" / "panels"
    queries = root / "grafana" / "queries"
    panels.mkdir(parents=True)
    queries.mkdir(parents=True)
    for panel_id in panel_ids:
        query_rel = f"grafana/queries/panel-{panel_id}-A.json"
        (root / query_rel).write_text("{}", encoding="utf-8")
        contract = {
            **summary,
            "panelId": panel_id,
            "panelTitle": f"panel {panel_id}",
            "queryJsonPaths": [query_rel],
            "expectedPngPath": f"grafana/panels/panel-{panel_id}.png",
        }
        (panels / f"panel-{panel_id}.capture.json").write_text(
            json.dumps(contract), encoding="utf-8"
        )
        (panels / f"panel-{panel_id}.png").write_bytes(make_png(*png_size))


class CaptureVerifierTests(unittest.TestCase):
    def test_valid_captures_promote_status_to_captured(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            build_fixture(root)
            status = MODULE.verify_captures(root)
            self.assertEqual(status["status"], "captured")
            self.assertEqual(status["panelCount"], 2)
            written = json.loads((root / "grafana/panels/status.json").read_text())
            self.assertEqual(written["status"], "captured")
            self.assertTrue(all(len(panel["sha256"]) == 64 for panel in written["panels"]))

    def test_missing_png_fails_closed(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            build_fixture(root)
            (root / "grafana/panels/panel-3.png").unlink()
            with self.assertRaisesRegex(MODULE.CaptureVerificationError, "missing panel capture"):
                MODULE.verify_captures(root)

    def test_small_png_fails_closed(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            build_fixture(root, png_size=(320, 100))
            with self.assertRaisesRegex(MODULE.CaptureVerificationError, "minimum size"):
                MODULE.verify_captures(root)

    def test_non_png_bytes_fail_closed(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            build_fixture(root)
            (root / "grafana/panels/panel-2.png").write_bytes(b"JFIF not a png" * 1000)
            with self.assertRaisesRegex(MODULE.CaptureVerificationError, "not a PNG"):
                MODULE.verify_captures(root)

    def test_contract_run_mismatch_fails_closed(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            build_fixture(root)
            contract_path = root / "grafana/panels/panel-2.capture.json"
            contract = json.loads(contract_path.read_text())
            contract["runId"] = "aws-b02-other-run"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.CaptureVerificationError, "runId"):
                MODULE.verify_captures(root)

    def test_missing_query_json_fails_closed(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            build_fixture(root)
            (root / "grafana/queries/panel-2-A.json").unlink()
            with self.assertRaisesRegex(MODULE.CaptureVerificationError, "query JSON"):
                MODULE.verify_captures(root)


if __name__ == "__main__":
    unittest.main()
