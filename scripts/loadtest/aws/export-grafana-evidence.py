#!/usr/bin/env python3
"""Export Grafana Dashboard/Annotation/Query evidence into a downloaded local
AWS load-test evidence bundle, per aws-load-test-handoff/plans/05_EVIDENCE_EXPORT_PLAN.md
and contracts/EVIDENCE_BUNDLE_CONTRACT.md's `grafana/` layout.

This is deliberately a separate, later step from
scripts/loadtest/aws/orchestrate-aws-b01.sh's own evidence_stage(): that stage
does a best-effort live annotation publish and two hardcoded instant PromQL
queries while the Runner still has network access to Grafana/Prometheus. This
script runs afterwards (typically on an operator's machine, after
download-aws-evidence.sh has pulled the bundle from S3, reached over an SSM
port-forward tunnel per Plan05 step 1) and does the complete, reproducible
collection for report-writing: the full Dashboard JSON, the actual Annotation
list (not just publish results), and a range query per panel (Prometheus/Loki
via Grafana's datasource proxy, CloudWatch via the AWS CLI directly) over the
run's fixed startedAtUtc/endedAtUtc window — never the dashboard's live "now".

D-003-R1 (see aws-load-test-handoff/decisions/DECISION_LOG.md) decided PNG
capture is required and settled the method: no renderer sidecar/plugin, an
operator opens an SSM port-forward tunnel to Grafana and captures each fixed
Panel ID with a browser, per TEAM_MEMBER_B01_ACTION_REQUEST.md section 4.4.
This script cannot drive that capture itself (no headless browser dependency,
and there is no live Grafana to test against yet) — what it does instead is
write the *capture contract* section 4.4 requires: for every panel, a
grafana/panels/panel-<id>.capture.json with the runId/fromUtc/toUtc/dashboard
UID+version/Panel ID/Query JSON path already resolved, plus the exact
`?viewPanel=` URL to open for the screenshot. Once an operator saves
panel-<id>.png next to it, build-evidence-manifest.py's determine_png_status()
treats that pairing as this panel being captured.

Auth values (--password / GRAFANA_EVIDENCE_PASSWORD) are used only in an HTTP
Basic Authorization header and are never written to any output file or
printed to stdout/stderr.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

QUERYABLE_DATASOURCE_TYPES = {"prometheus", "loki", "cloudwatch"}
CLOUDWATCH_DIMENSION_VARIABLES = {
    "alb_dimension": "albDimension",
    "target_group_dimension": "targetGroupDimension",
    "autoscaling_group_name": "autoScalingGroupName",
    "db_instance_identifier": "dbInstanceIdentifier",
    "cache_cluster_id": "cacheClusterId",
}


class ExportError(RuntimeError):
    """A sanitized Grafana evidence export failure."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True, help="Local evidence bundle directory, e.g. evidence/aws-load-tests/<run-id> after download-aws-evidence.sh")
    parser.add_argument("--grafana-url", required=True, help="Grafana base URL, typically http://127.0.0.1:<port> over an SSM port-forward tunnel to the Monitoring EC2")
    parser.add_argument("--user", default=os.environ.get("GRAFANA_EVIDENCE_USER", ""), help="Read-only Evidence Exporter Grafana account (Plan05 step 2); default: $GRAFANA_EVIDENCE_USER")
    parser.add_argument("--password", default=os.environ.get("GRAFANA_EVIDENCE_PASSWORD", ""), help="Default: $GRAFANA_EVIDENCE_PASSWORD; never logged")
    parser.add_argument("--dashboard-uid", default="aws-load-test-b01", help="Default: the B-01 evidence dashboard's fixed UID (monitoring/grafana/dashboards/aws-load-test.json)")
    parser.add_argument("--run-id", default="", help="Default: metadata.json's runId")
    parser.add_argument("--from-utc", default="", help="Default: metadata.json's startedAtUtc")
    parser.add_argument("--to-utc", default="", help="Default: metadata.json's endedAtUtc")
    parser.add_argument("--region", default="", help="Required to collect CloudWatch panel queries")
    parser.add_argument("--dry-run", action="store_true", help="Resolve inputs and print the plan; make no network/AWS CLI calls")
    return parser.parse_args()


def resolve_time_range(evidence_root: Path, from_utc: str, to_utc: str) -> tuple[str, str]:
    if from_utc and to_utc:
        return from_utc, to_utc
    metadata_path = evidence_root / "metadata.json"
    if not metadata_path.exists():
        raise ExportError("metadata.json not found under --evidence-root and --from-utc/--to-utc were not both supplied")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    started = from_utc or metadata.get("startedAtUtc")
    ended = to_utc or metadata.get("endedAtUtc")
    if not started or not ended:
        raise ExportError(
            "metadata.json is missing startedAtUtc/endedAtUtc (the run may not have reached "
            "cleanup_stage yet, which is what fills endedAtUtc in); supply --from-utc/--to-utc explicitly"
        )
    return started, ended


def resolve_run_id(evidence_root: Path, run_id: str) -> str:
    if run_id:
        return run_id
    metadata_path = evidence_root / "metadata.json"
    if metadata_path.exists():
        metadata_run_id = json.loads(metadata_path.read_text(encoding="utf-8")).get("runId")
        if metadata_run_id:
            return metadata_run_id
    raise ExportError("--run-id is required when metadata.json is absent or has no runId")


def to_epoch_seconds(utc_iso: str) -> int:
    return int(datetime.fromisoformat(utc_iso.replace("Z", "+00:00")).timestamp())


def basic_auth_header(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def grafana_request(url: str, auth_header: str, timeout: int = 15) -> bytes:
    request = Request(url, headers={"Authorization": auth_header})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except (HTTPError, URLError) as error:
        raise ExportError(f"Grafana request failed: {error}") from error


def run_command(command: list[str]) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()[-1:] or ["command failed"]
        raise ExportError(f"command failed ({completed.returncode}): {' '.join(command[:4])}; {detail[0]}")
    return completed.stdout


def fetch_dashboard(grafana_url: str, auth_header: str, dashboard_uid: str) -> dict:
    url = f"{grafana_url.rstrip('/')}/api/dashboards/uid/{dashboard_uid}"
    return json.loads(grafana_request(url, auth_header))


def fetch_annotations(grafana_url: str, auth_header: str, run_id: str, from_ms: int, to_ms: int) -> list:
    query = urllib.parse.urlencode({"tags": f"run:{run_id}", "from": from_ms, "to": to_ms, "limit": 500})
    url = f"{grafana_url.rstrip('/')}/api/annotations?{query}"
    return json.loads(grafana_request(url, auth_header))


def load_resource_dimensions(evidence_root: Path) -> dict:
    """Load the non-secret CloudWatch dimension contract written by target_stage."""
    path = evidence_root / "aws" / "resource-dimensions.json"
    if not path.exists():
        raise ExportError("aws/resource-dimensions.json is missing; target validation must resolve CloudWatch resources before Grafana export")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ExportError("aws/resource-dimensions.json is not valid JSON") from error
    return payload


def _is_runtime_placeholder(value: object) -> bool:
    return (
        not isinstance(value, str)
        or not value.strip()
        or value.startswith("<")
        or value == "__runtime__"
    )


def validate_resource_dimensions(resource_dimensions: dict) -> None:
    """Require every B-01 CloudWatch dimension before a dashboard capture."""
    if not isinstance(resource_dimensions, dict):
        raise ExportError("aws/resource-dimensions.json must contain a JSON object")
    missing = [
        key
        for key in sorted(set(CLOUDWATCH_DIMENSION_VARIABLES.values()))
        if _is_runtime_placeholder(resource_dimensions.get(key))
    ]
    if missing:
        raise ExportError(
            "aws/resource-dimensions.json is missing runtime CloudWatch dimensions: "
            + ", ".join(missing)
        )


def resolve_cloudwatch_dimensions(dimensions: dict, resource_dimensions: dict | None) -> dict:
    """Resolve dashboard `$variable` dimensions to exact AWS identifiers."""
    if resource_dimensions is None:
        return dimensions or {}
    if not dimensions:
        raise ExportError("a CloudWatch panel has empty dimensions; refusing an unscoped metric query")
    resolved = {}
    for name, value in dimensions.items():
        if isinstance(value, str) and value.startswith("$"):
            variable_name = value[1:]
            resource_key = CLOUDWATCH_DIMENSION_VARIABLES.get(variable_name)
            if resource_key is None:
                raise ExportError(f"unknown CloudWatch dashboard dimension variable: {variable_name}")
            value = resource_dimensions.get(resource_key)
            if _is_runtime_placeholder(value):
                raise ExportError(f"CloudWatch dimension {variable_name} is missing from aws/resource-dimensions.json")
        if _is_runtime_placeholder(value):
            raise ExportError(f"CloudWatch dimension {name} is empty")
        resolved[name] = value
    return resolved


def extract_panel_queries(dashboard_payload: dict, resource_dimensions: dict | None = None) -> list[dict]:
    """Pure/offline: derive one collectible query per panel target from a
    fetched (or test-supplied) Grafana dashboard API payload. No network
    calls — safe to unit test without mocking HTTP."""
    panels = dashboard_payload.get("dashboard", {}).get("panels", [])
    queries = []
    for panel in panels:
        datasource = panel.get("datasource") or {}
        ds_type = datasource.get("type")
        ds_uid = datasource.get("uid")
        if ds_type not in QUERYABLE_DATASOURCE_TYPES:
            continue
        for target in panel.get("targets", []):
            entry = {
                "panelId": panel.get("id"),
                "panelTitle": panel.get("title"),
                "refId": target.get("refId"),
                "datasourceType": ds_type,
                "datasourceUid": ds_uid,
            }
            if ds_type in {"prometheus", "loki"}:
                if not target.get("expr"):
                    continue
                entry["expr"] = target["expr"]
            else:
                if not target.get("metricName"):
                    continue
                entry["cloudwatch"] = {
                    "namespace": target.get("namespace"),
                    "metricName": target.get("metricName"),
                    "statistic": target.get("statistic", "Average"),
                    "period": target.get("period", "60"),
                    "dimensions": resolve_cloudwatch_dimensions(target.get("dimensions") or {}, resource_dimensions),
                }
            queries.append(entry)
    return queries


def collect_datasource_range_query(grafana_url: str, auth_header: str, ds_type: str, ds_uid: str, expr: str, from_utc: str, to_utc: str) -> dict:
    start_epoch = to_epoch_seconds(from_utc)
    end_epoch = to_epoch_seconds(to_utc)
    if ds_type == "prometheus":
        step = max(1, (end_epoch - start_epoch) // 250) if end_epoch > start_epoch else 15
        query = urllib.parse.urlencode({"query": expr, "start": start_epoch, "end": end_epoch, "step": step})
        url = f"{grafana_url.rstrip('/')}/api/datasources/proxy/uid/{ds_uid}/api/v1/query_range?{query}"
    else:  # loki
        query = urllib.parse.urlencode({
            "query": expr,
            "start": start_epoch * 1_000_000_000,
            "end": end_epoch * 1_000_000_000,
            "limit": 1000,
        })
        url = f"{grafana_url.rstrip('/')}/api/datasources/proxy/uid/{ds_uid}/loki/api/v1/query_range?{query}"
    return json.loads(grafana_request(url, auth_header))


def collect_cloudwatch_query(namespace: str, metric_name: str, statistic: str, period, dimensions: dict, region: str, from_utc: str, to_utc: str) -> dict:
    command = [
        "aws", "cloudwatch", "get-metric-statistics",
        "--namespace", namespace, "--metric-name", metric_name,
        "--statistics", statistic, "--period", str(period),
        "--start-time", from_utc, "--end-time", to_utc,
        "--region", region, "--output", "json",
    ]
    if dimensions:
        command += ["--dimensions"]
        command += [f"Name={key},Value={value}" for key, value in dimensions.items()]
    return json.loads(run_command(command))


def collect_panel_queries(grafana_url: str, auth_header: str, panel_queries: list[dict], from_utc: str, to_utc: str, region: str, queries_dir: Path) -> tuple[int, int]:
    collected = 0
    failed = 0
    for entry in panel_queries:
        filename = f"panel-{entry['panelId']}-{entry['refId']}.json"
        try:
            if entry["datasourceType"] in {"prometheus", "loki"}:
                result = collect_datasource_range_query(
                    grafana_url, auth_header, entry["datasourceType"], entry["datasourceUid"], entry["expr"], from_utc, to_utc,
                )
            else:
                if not region:
                    raise ExportError("--region is required to collect CloudWatch panel queries")
                cloudwatch = entry["cloudwatch"]
                result = collect_cloudwatch_query(
                    cloudwatch["namespace"], cloudwatch["metricName"], cloudwatch["statistic"],
                    cloudwatch["period"], cloudwatch["dimensions"], region, from_utc, to_utc,
                )
            record = {**entry, "fromUtc": from_utc, "toUtc": to_utc, "status": "collected", "result": result}
            collected += 1
        except ExportError as error:
            record = {**entry, "fromUtc": from_utc, "toUtc": to_utc, "status": "error", "detail": str(error)}
            failed += 1
        (queries_dir / filename).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return collected, failed


def build_dashboard_url(grafana_url: str, dashboard_uid: str, resource_dimensions: dict | None = None) -> str:
    """Build a dashboard URL with run-specific CloudWatch variables."""
    base_url = f"{grafana_url.rstrip('/')}/d/{dashboard_uid}"
    if resource_dimensions is None:
        return base_url
    validate_resource_dimensions(resource_dimensions)
    variables = [
        (f"var-{variable_name}", resource_dimensions[resource_key])
        for variable_name, resource_key in CLOUDWATCH_DIMENSION_VARIABLES.items()
    ]
    return f"{base_url}?{urllib.parse.urlencode(variables)}"


def build_panel_capture_contracts(
    dashboard_payload: dict,
    panel_queries: list[dict],
    grafana_url: str,
    run_id: str,
    from_utc: str,
    to_utc: str,
    resource_dimensions: dict | None = None,
) -> list[dict]:
    """Pure/offline: one capture contract per panel (TEAM_MEMBER_B01_ACTION_REQUEST.md
    section 4.4's "고정 UTC 범위·Panel ID·Query JSON을 캡처 계약에 포함"). Groups
    panel_queries (one entry per target/refId) by panelId, since a panel with
    multiple targets still gets exactly one PNG. No network calls — safe to
    unit test without mocking HTTP."""
    dashboard = dashboard_payload.get("dashboard", {})
    dashboard_uid = dashboard.get("uid", "")
    dashboard_version = dashboard.get("version")
    dashboard_url = build_dashboard_url(grafana_url, dashboard_uid, resource_dimensions)
    from_ms = to_epoch_seconds(from_utc) * 1000
    to_ms = to_epoch_seconds(to_utc) * 1000

    by_panel: dict[int, dict] = {}
    for entry in panel_queries:
        panel_id = entry["panelId"]
        panel = by_panel.setdefault(panel_id, {
            "panelId": panel_id,
            "panelTitle": entry.get("panelTitle"),
            "queryJsonPaths": [],
        })
        panel["queryJsonPaths"].append(f"grafana/queries/panel-{panel_id}-{entry['refId']}.json")

    contracts = []
    for panel_id in sorted(by_panel):
        panel = by_panel[panel_id]
        contracts.append({
            "runId": run_id,
            "fromUtc": from_utc,
            "toUtc": to_utc,
            "dashboardUid": dashboard_uid,
            "dashboardVersion": dashboard_version,
            "panelId": panel_id,
            "panelTitle": panel["panelTitle"],
            "queryJsonPaths": panel["queryJsonPaths"],
            "dashboardUrl": dashboard_url,
            "captureUrl": (
                f"{dashboard_url}&viewPanel={panel_id}&from={from_ms}&to={to_ms}&tz=utc"
                if "?" in dashboard_url
                else f"{dashboard_url}?viewPanel={panel_id}&from={from_ms}&to={to_ms}&tz=utc"
            ),
            "expectedPngPath": f"grafana/panels/panel-{panel_id}.png",
            "instructions": (
                "SSM port-forward to the Monitoring EC2's Grafana (see download-aws-evidence.sh), "
                "open captureUrl in a browser signed in as the read-only Evidence Exporter account, "
                "and save a screenshot of just this panel as expectedPngPath. Secrets/cookies/tokens "
                "must not be visible in the capture (TEAM_MEMBER_B01_ACTION_REQUEST.md 4.4)."
            ),
        })
    return contracts


def write_panel_capture_contracts(contracts: list[dict], panels_dir: Path) -> None:
    for contract in contracts:
        path = panels_dir / f"panel-{contract['panelId']}.capture.json"
        path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    evidence_root = args.evidence_root.resolve()
    if not evidence_root.is_dir():
        raise ExportError("--evidence-root does not exist or is not a directory")

    from_utc, to_utc = resolve_time_range(evidence_root, args.from_utc, args.to_utc)
    run_id = resolve_run_id(evidence_root, args.run_id)

    if not args.user or not args.password:
        raise ExportError("--user/--password or GRAFANA_EVIDENCE_USER/GRAFANA_EVIDENCE_PASSWORD are required")

    grafana_dir = evidence_root / "grafana"
    queries_dir = grafana_dir / "queries"
    panels_dir = grafana_dir / "panels"

    if args.dry_run:
        print(
            f"[grafana-export] dry-run: dashboard={args.dashboard_uid} run-id={run_id} "
            f"range={from_utc}..{to_utc} region={args.region or '<none>'}"
        )
        return 0

    queries_dir.mkdir(parents=True, exist_ok=True)
    panels_dir.mkdir(parents=True, exist_ok=True)

    auth_header = basic_auth_header(args.user, args.password)

    dashboard_payload = fetch_dashboard(args.grafana_url, auth_header, args.dashboard_uid)
    (grafana_dir / "dashboard.json").write_text(json.dumps(dashboard_payload, indent=2) + "\n", encoding="utf-8")

    resource_dimensions = load_resource_dimensions(evidence_root)
    validate_resource_dimensions(resource_dimensions)
    (grafana_dir / "resource-dimensions.json").write_text(
        json.dumps(resource_dimensions, indent=2) + "\n", encoding="utf-8",
    )
    (grafana_dir / "dashboard-url.json").write_text(
        json.dumps({
            "dashboardUid": args.dashboard_uid,
            "url": build_dashboard_url(args.grafana_url, args.dashboard_uid, resource_dimensions),
            "resourceDimensionsPath": "aws/resource-dimensions.json",
        }, indent=2) + "\n",
        encoding="utf-8",
    )

    from_ms = to_epoch_seconds(from_utc) * 1000
    to_ms = to_epoch_seconds(to_utc) * 1000
    annotations = fetch_annotations(args.grafana_url, auth_header, run_id, from_ms, to_ms)
    (grafana_dir / "annotations.json").write_text(
        json.dumps({"runId": run_id, "fromUtc": from_utc, "toUtc": to_utc, "annotations": annotations}, indent=2) + "\n",
        encoding="utf-8",
    )

    panel_queries = extract_panel_queries(dashboard_payload, resource_dimensions)
    collected, failed = collect_panel_queries(args.grafana_url, auth_header, panel_queries, from_utc, to_utc, args.region, queries_dir)

    contracts = build_panel_capture_contracts(
        dashboard_payload, panel_queries, args.grafana_url, run_id, from_utc, to_utc, resource_dimensions,
    )
    write_panel_capture_contracts(contracts, panels_dir)
    (panels_dir / "status.json").write_text(json.dumps({
        "status": "pending-manual-capture",
        "reason": (
            "D-003-R1 decided PNG capture is required, via SSM port-forward + browser screenshot "
            "(no renderer sidecar). This script wrote one panel-<id>.capture.json per panel with the "
            "exact URL, fixed UTC range, and Query JSON path to capture against — see download-aws-evidence.sh "
            "for the SSM tunnel command. Query JSON under grafana/queries/ remains the evidence of record "
            "until the corresponding panel-<id>.png is saved."
        ),
        "panelCount": len(contracts),
    }, indent=2) + "\n", encoding="utf-8")

    print(f"[grafana-export] dashboard + annotations written; panel queries collected={collected} failed={failed}; capture contracts written={len(contracts)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ExportError as error:
        print(f"[grafana-export] ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
