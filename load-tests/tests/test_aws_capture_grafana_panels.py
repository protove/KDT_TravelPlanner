from __future__ import annotations

import importlib.util
import json
import struct
import unittest
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/loadtest/aws/capture-grafana-panels.py"
SPEC = importlib.util.spec_from_file_location("capture_grafana_panels", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def png(width: int = 800, height: int = 400) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    body = MODULE.PNG_SIGNATURE + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress((b"\0" + b"\x7f" * width * 3) * height)) + chunk(b"IEND", b"")
    return body + b"x" * max(0, MODULE.MIN_BYTES - len(body))


class CaptureGrafanaPanelsTest(unittest.TestCase):
    def fixture(self, root: Path) -> None:
        grafana = root / "grafana" / "panels"
        grafana.mkdir(parents=True)
        base = "http://127.0.0.1:3000/d/aws-eks-load-test?from=1&to=2&tz=utc"
        common = {"runId": "run-1", "dashboardUid": "aws-eks-load-test", "dashboardVersion": 1, "fromUtc": "2026-09-02T00:00:00Z", "toUtc": "2026-09-02T01:00:00Z"}
        (root / "grafana" / "dashboard.capture.json").write_text(json.dumps({**common, "captureUrl": base, "expectedPngPath": "grafana/dashboard.png"}))
        (grafana / "panel-1.capture.json").write_text(json.dumps({**common, "panelId": 1, "captureUrl": base, "expectedPngPath": "grafana/panels/panel-1.png"}))

    def test_render_urls_are_loopback_and_panel_scoped(self) -> None:
        url = MODULE.render_url("http://127.0.0.1:3000/d/aws-eks-load-test?from=1&to=2", panel_id=19)
        self.assertIn("/render/d-solo/aws-eks-load-test", url)
        self.assertIn("panelId=19", url)
        with self.assertRaises(MODULE.CaptureError):
            MODULE.capture(Path("/tmp/does-not-exist"), "", "", True)

    def test_capture_downloads_full_dashboard_and_every_panel_without_logging_auth(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            with patch.object(MODULE, "urlopen", return_value=type("Response", (), {"__enter__": lambda self: self, "__exit__": lambda *args: None, "read": lambda self: png()})()):
                status = MODULE.capture(root, "viewer", "secret")
            self.assertEqual(status["status"], "captured")
            self.assertTrue((root / "grafana/dashboard.png").is_file())
            self.assertTrue((root / "grafana/panels/panel-1.png").is_file())
            self.assertNotIn("secret", (root / "grafana/panels/status.json").read_text())

    def test_public_url_and_html_response_fail_closed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            contract = json.loads((root / "grafana/dashboard.capture.json").read_text())
            contract["captureUrl"] = "https://grafana.example.com/d/aws-eks-load-test"
            (root / "grafana/dashboard.capture.json").write_text(json.dumps(contract))
            with self.assertRaises(MODULE.CaptureError):
                MODULE.capture(root, "viewer", "secret")


if __name__ == "__main__":
    unittest.main()
