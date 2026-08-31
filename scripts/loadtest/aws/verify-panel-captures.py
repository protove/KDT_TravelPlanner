#!/usr/bin/env python3
"""Verify browser-captured Grafana panel PNGs against their capture contracts.

For every ``panel-<id>.capture.json`` in the run's ``grafana/panels``
directory, this verifier requires the matching ``panel-<id>.png`` to exist,
be a structurally valid PNG of a usable size, and belong to the same run:
the contract's runId, fixed UTC range, dashboard UID, and dashboard version
must match the run's export summary. On success it rewrites
``grafana/panels/status.json`` from ``pending-manual-capture`` to
``captured`` with per-panel SHA-256 evidence. It never edits or deletes a
PNG; any mismatch fails closed with a sanitized reason.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
DEFAULT_MIN_WIDTH = 640
DEFAULT_MIN_HEIGHT = 240
DEFAULT_MIN_BYTES = 8 * 1024


class CaptureVerificationError(RuntimeError):
    """A sanitized, fail-closed capture verification failure."""


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CaptureVerificationError(f"invalid JSON evidence: {path.name}") from error
    if not isinstance(payload, dict):
        raise CaptureVerificationError(f"JSON object expected: {path.name}")
    return payload


def read_export_summary(evidence_root: Path) -> dict[str, Any]:
    """Read either a Recovery export summary or the shared Grafana summary."""
    candidates = (
        evidence_root / "recovery-export-summary.json",
        evidence_root / "grafana" / "export-summary.json",
    )
    for path in candidates:
        if path.is_file():
            return read_json(path)
    raise CaptureVerificationError("Grafana export summary is missing")


def png_dimensions(path: Path) -> tuple[int, int]:
    try:
        header = path.read_bytes()[:33]
    except OSError as error:
        raise CaptureVerificationError(f"cannot read PNG: {path.name}") from error
    if len(header) < 33 or not header.startswith(PNG_SIGNATURE):
        raise CaptureVerificationError(f"not a PNG file: {path.name}")
    if header[12:16] != b"IHDR":
        raise CaptureVerificationError(f"PNG missing IHDR chunk: {path.name}")
    width, height = struct.unpack(">II", header[16:24])
    return int(width), int(height)


def verify_captures(
    evidence_root: Path,
    *,
    min_width: int = DEFAULT_MIN_WIDTH,
    min_height: int = DEFAULT_MIN_HEIGHT,
    min_bytes: int = DEFAULT_MIN_BYTES,
) -> dict[str, Any]:
    panels_dir = evidence_root / "grafana" / "panels"
    summary = read_export_summary(evidence_root)
    run_id = summary.get("runId")
    contracts = sorted(panels_dir.glob("panel-*.capture.json"))
    if not contracts:
        raise CaptureVerificationError("no panel capture contracts found")
    expected = {
        "runId": summary.get("runId"),
        "fromUtc": summary.get("fromUtc"),
        "toUtc": summary.get("toUtc"),
        "dashboardUid": summary.get("dashboardUid"),
        "dashboardVersion": summary.get("dashboardVersion"),
    }
    panels: list[dict[str, Any]] = []
    for contract_path in contracts:
        contract = read_json(contract_path)
        for field, value in expected.items():
            if contract.get(field) != value:
                raise CaptureVerificationError(
                    f"{contract_path.name}: {field} does not match the export summary"
                )
        png_relative = contract.get("expectedPngPath")
        if not isinstance(png_relative, str) or not png_relative:
            raise CaptureVerificationError(f"{contract_path.name}: expectedPngPath is missing")
        if contract.get("noDataPanel") is True:
            # A panel whose query legitimately returned nothing renders "No data"
            # and has no plot to capture. Accept it only when every referenced
            # query JSON exists and itself reports an empty result, so a failed
            # or unrun query can never be waved through as "no data".
            for query_relative in contract.get("queryJsonPaths", []):
                query_path = evidence_root / str(query_relative)
                if not query_path.is_file():
                    raise CaptureVerificationError(
                        f"no-data panel {contract.get('panelId')} is missing its query JSON: {query_relative}"
                    )
                query = read_json(query_path)
                if query.get("status") not in {"empty", "empty-is-valid"}:
                    raise CaptureVerificationError(
                        f"no-data panel {contract.get('panelId')} query {query_relative} "
                        f"does not report an empty result (status={query.get('status')})"
                    )
            panels.append({
                "panelId": contract.get("panelId"),
                "panelTitle": contract.get("panelTitle"),
                "pngPath": None,
                "noDataPanel": True,
                "noDataReason": contract.get("noDataReason"),
                "contract": contract_path.name,
            })
            continue
        png_path = evidence_root / png_relative
        if png_path.is_symlink() or not png_path.is_file():
            raise CaptureVerificationError(f"missing panel capture PNG: {png_relative}")
        size = png_path.stat().st_size
        if size < min_bytes:
            raise CaptureVerificationError(
                f"panel capture PNG is implausibly small ({size} bytes): {png_relative}"
            )
        width, height = png_dimensions(png_path)
        if width < min_width or height < min_height:
            raise CaptureVerificationError(
                f"panel capture PNG is below the minimum size {min_width}x{min_height}: {png_relative}"
            )
        for query_relative in contract.get("queryJsonPaths", []):
            if not (evidence_root / str(query_relative)).is_file():
                raise CaptureVerificationError(
                    f"panel {contract.get('panelId')} query JSON is missing: {query_relative}"
                )
        panels.append(
            {
                "panelId": contract.get("panelId"),
                "panelTitle": contract.get("panelTitle"),
                "pngPath": png_relative,
                "bytes": size,
                "width": width,
                "height": height,
                "sha256": hashlib.sha256(png_path.read_bytes()).hexdigest(),
                "contract": contract_path.name,
            }
        )
    dashboard_contract_path = evidence_root / "grafana" / "dashboard.capture.json"
    dashboard_status: dict[str, Any] = {
        "status": "not-exported",
        "contract": None,
        "pngPath": None,
    }
    if dashboard_contract_path.is_file():
        dashboard_contract = read_json(dashboard_contract_path)
        for field, value in expected.items():
            if dashboard_contract.get(field) != value:
                raise CaptureVerificationError(
                    f"dashboard.capture.json: {field} does not match the export summary"
                )
        dashboard_relative = dashboard_contract.get("expectedPngPath")
        if dashboard_relative != "grafana/dashboard.png":
            raise CaptureVerificationError("dashboard.capture.json: expectedPngPath must be grafana/dashboard.png")
        dashboard_png = evidence_root / dashboard_relative
        if dashboard_png.is_symlink() or not dashboard_png.is_file():
            raise CaptureVerificationError("missing full-dashboard capture PNG: grafana/dashboard.png")
        dashboard_size = dashboard_png.stat().st_size
        if dashboard_size < min_bytes:
            raise CaptureVerificationError(
                f"full-dashboard capture PNG is implausibly small ({dashboard_size} bytes)"
            )
        dashboard_width, dashboard_height = png_dimensions(dashboard_png)
        if dashboard_width < min_width or dashboard_height < min_height:
            raise CaptureVerificationError(
                f"full-dashboard capture PNG is below the minimum size {min_width}x{min_height}"
            )
        dashboard_status = {
            "status": "captured",
            "contract": dashboard_contract_path.name,
            "pngPath": dashboard_relative,
            "bytes": dashboard_size,
            "width": dashboard_width,
            "height": dashboard_height,
            "sha256": hashlib.sha256(dashboard_png.read_bytes()).hexdigest(),
        }
    status = {
        "status": "captured",
        "runId": run_id,
        "fromUtc": expected["fromUtc"],
        "toUtc": expected["toUtc"],
        "dashboardUid": expected["dashboardUid"],
        "dashboardVersion": expected["dashboardVersion"],
        "panelCount": len(panels),
        "dashboard": dashboard_status,
        "verifiedAtUtc": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "panels": panels,
    }
    (panels_dir / "status.json").write_text(
        json.dumps(status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_root", type=Path)
    parser.add_argument("--min-width", type=int, default=DEFAULT_MIN_WIDTH)
    parser.add_argument("--min-height", type=int, default=DEFAULT_MIN_HEIGHT)
    parser.add_argument("--min-bytes", type=int, default=DEFAULT_MIN_BYTES)
    args = parser.parse_args(argv)
    try:
        status = verify_captures(
            args.evidence_root.resolve(),
            min_width=args.min_width,
            min_height=args.min_height,
            min_bytes=args.min_bytes,
        )
    except CaptureVerificationError as error:
        print(f"[capture-verify] FAILED: {error}", file=sys.stderr)
        return 1
    print(
        f"[capture-verify] captured panels={status['panelCount']} "
        f"dashboard={status['dashboard']['status']} run={status['runId']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
