#!/usr/bin/env python3
"""Verify fixed-time Grafana dashboard and panel capture artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class CaptureError(RuntimeError):
    pass


def png_dimensions(path: Path) -> tuple[int, int]:
    raw = path.read_bytes()[:33]
    if len(raw) < 33 or not raw.startswith(PNG_SIGNATURE) or raw[12:16] != b"IHDR":
        raise CaptureError(f"invalid PNG: {path.name}")
    return struct.unpack(">II", raw[16:24])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--min-width", type=int, default=640)
    parser.add_argument("--min-height", type=int, default=240)
    parser.add_argument("--min-bytes", type=int, default=8192)
    return parser.parse_args()


def verify(root: Path, min_width: int, min_height: int, min_bytes: int) -> dict[str, object]:
    grafana = root / "grafana"
    metadata_path = grafana / "capture-metadata.json"
    if not metadata_path.is_file():
        raise CaptureError("capture-metadata.json is missing")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("dashboardUid") != "compose-dependency-diagnostic":
        raise CaptureError("unexpected dashboard UID")
    if not metadata.get("fromUtc") or not metadata.get("toUtc"):
        raise CaptureError("fixed UTC range is missing")
    full = grafana / "dashboard-full.png"
    if not full.is_file():
        raise CaptureError("dashboard-full.png is missing")
    width, height = png_dimensions(full)
    if full.stat().st_size < min_bytes or width < min_width or height < min_height:
        raise CaptureError("dashboard-full.png is below the capture contract size")
    panels_dir = grafana / "panels"
    panel_records = []
    contracts = sorted(panels_dir.glob("panel-*.capture.json"))
    if len(contracts) < 9:
        raise CaptureError("at least nine panel capture contracts are required")
    for contract_path in contracts:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        for field in ("campaignId", "replicate", "fromUtc", "toUtc", "dashboardUid"):
            if contract.get(field) != metadata.get(field):
                raise CaptureError(f"{contract_path.name}: {field} does not match metadata")
        png_relative = contract.get("expectedPngPath")
        if not isinstance(png_relative, str) or not png_relative.startswith("grafana/panels/"):
            raise CaptureError(f"{contract_path.name}: expectedPngPath is invalid")
        png_path = root / png_relative
        if png_path.is_symlink() or not png_path.is_file():
            raise CaptureError(f"missing panel PNG: {png_relative}")
        width, height = png_dimensions(png_path)
        if png_path.stat().st_size < min_bytes or width < min_width or height < min_height:
            raise CaptureError(f"panel PNG is below the capture contract size: {png_relative}")
        query_paths = contract.get("queryJsonPaths") or []
        if not query_paths or any(not (root / str(path)).is_file() for path in query_paths):
            raise CaptureError(f"{contract_path.name}: query evidence is incomplete")
        panel_records.append({
            "panelId": contract.get("panelId"),
            "panelTitle": contract.get("panelTitle"),
            "path": png_relative,
            "bytes": png_path.stat().st_size,
            "width": width,
            "height": height,
            "sha256": hashlib.sha256(png_path.read_bytes()).hexdigest(),
        })
    status = {"schemaVersion": "compose-grafana-capture/v1", "status": "captured", "dashboard": {"path": "grafana/dashboard-full.png", "bytes": full.stat().st_size, "width": png_dimensions(full)[0], "height": png_dimensions(full)[1], "sha256": hashlib.sha256(full.read_bytes()).hexdigest()}, "panelCount": len(panel_records), "panels": panel_records, "fromUtc": metadata["fromUtc"], "toUtc": metadata["toUtc"], "dashboardUid": metadata["dashboardUid"]}
    (grafana / "capture-status.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    return status


def main() -> int:
    args = parse_args()
    try:
        status = verify(args.evidence_root.resolve(), args.min_width, args.min_height, args.min_bytes)
    except (CaptureError, OSError, json.JSONDecodeError) as error:
        print(f"[diagnostic-capture] ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"status": status["status"], "panelCount": status["panelCount"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
