#!/usr/bin/env python3
"""Download fixed-range Grafana dashboard and panel renders safely.

The exporter first writes immutable capture contracts.  This companion uses
those contracts over an SSM loopback tunnel, stores only PNG bytes, and never
prints or persists the Basic-auth value.  It refuses public Grafana URLs and
HTML/login responses so a failed capture cannot be mistaken for evidence.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import struct
import sys
import urllib.parse
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MIN_BYTES = 8 * 1024
MIN_WIDTH = 640
MIN_HEIGHT = 240


class CaptureError(RuntimeError):
    """A sanitized capture failure."""


def read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CaptureError(f"invalid capture contract: {path.name}") from error
    if not isinstance(payload, dict):
        raise CaptureError(f"capture contract must be an object: {path.name}")
    return payload


def loopback(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def auth_header(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode("ascii")


def render_url(source_url: str, *, panel_id: int | None = None) -> str:
    parsed = urllib.parse.urlparse(source_url)
    path = parsed.path
    if "/d/" not in path:
        raise CaptureError("capture URL is not a Grafana dashboard URL")
    path = path.replace("/d/", "/render/d-solo/" if panel_id is not None else "/render/d/", 1)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    query.setdefault("width", ["1600"])
    query.setdefault("height", ["900" if panel_id is None else "600"])
    query.setdefault("tz", ["utc"])
    if panel_id is not None:
        query["panelId"] = [str(panel_id)]
    return urllib.parse.urlunparse(parsed._replace(path=path, query=urllib.parse.urlencode(query, doseq=True)))


def download(url: str, header: str | None) -> bytes:
    request = Request(url, headers={"Authorization": header} if header else {})
    try:
        with urlopen(request, timeout=30) as response:
            return response.read()
    except (HTTPError, URLError) as error:
        raise CaptureError(f"Grafana render request failed: {error}") from error


def png_dimensions(content: bytes) -> tuple[int, int]:
    if len(content) < 33 or not content.startswith(PNG_SIGNATURE) or content[12:16] != b"IHDR":
        raise CaptureError("Grafana render response is not a PNG")
    return struct.unpack(">II", content[16:24])


def save_png(path: Path, content: bytes) -> dict:
    if len(content) < MIN_BYTES:
        raise CaptureError(f"Grafana render response is implausibly small for {path.name}")
    width, height = png_dimensions(content)
    if width < MIN_WIDTH or height < MIN_HEIGHT:
        raise CaptureError(f"Grafana render for {path.name} is below {MIN_WIDTH}x{MIN_HEIGHT}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return {"path": str(path), "bytes": len(content), "width": width, "height": height}


def capture(evidence_root: Path, user: str, password: str, anonymous: bool = False) -> dict:
    grafana = evidence_root / "grafana"
    dashboard_contract_path = grafana / "dashboard.capture.json"
    if not dashboard_contract_path.is_file():
        raise CaptureError("grafana/dashboard.capture.json is missing")
    dashboard_contract = read_json(dashboard_contract_path)
    contracts_dir = grafana / "panels"
    contracts = sorted(contracts_dir.glob("panel-*.capture.json"))
    if not contracts:
        raise CaptureError("no panel capture contracts found")
    source_url = dashboard_contract.get("captureUrl")
    if not isinstance(source_url, str) or not loopback(source_url):
        raise CaptureError("dashboard capture URL must use a loopback SSM endpoint")
    if not anonymous and (not user or not password):
        raise CaptureError("Grafana credentials are required unless --anonymous-viewer is set")
    header = None if anonymous else auth_header(user, password)
    dashboard_path = evidence_root / "grafana" / "dashboard.png"
    dashboard_result = save_png(dashboard_path, download(render_url(source_url), header))
    panel_results = []
    for contract_path in contracts:
        contract = read_json(contract_path)
        if contract.get("runId") != dashboard_contract.get("runId") or contract.get("dashboardUid") != dashboard_contract.get("dashboardUid"):
            raise CaptureError(f"capture contract identity mismatch: {contract_path.name}")
        panel_id = contract.get("panelId")
        if not isinstance(panel_id, int):
            raise CaptureError(f"panel id is invalid: {contract_path.name}")
        png_relative = contract.get("expectedPngPath")
        if not isinstance(png_relative, str) or not png_relative.startswith("grafana/panels/"):
            raise CaptureError(f"panel PNG path is invalid: {contract_path.name}")
        panel_results.append({"panelId": panel_id, **save_png(evidence_root / png_relative, download(render_url(contract.get("captureUrl", source_url), panel_id=panel_id), header))})
    status = {
        "status": "captured",
        "runId": dashboard_contract.get("runId"),
        "dashboardUid": dashboard_contract.get("dashboardUid"),
        "dashboard": dashboard_result,
        "panels": panel_results,
        "captureMode": "grafana-render-over-ssm-loopback",
    }
    (contracts_dir / "status.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--user", default=os.environ.get("GRAFANA_EVIDENCE_USER", ""))
    parser.add_argument("--password", default=os.environ.get("GRAFANA_EVIDENCE_PASSWORD", ""))
    parser.add_argument("--anonymous-viewer", action="store_true")
    args = parser.parse_args(argv)
    try:
        status = capture(args.evidence_root.resolve(), args.user, args.password, args.anonymous_viewer)
    except CaptureError as error:
        print(f"[grafana-capture] FAILED: {error}", file=sys.stderr)
        return 1
    print(f"[grafana-capture] dashboard={status['dashboard']['bytes']} bytes panels={len(status['panels'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
