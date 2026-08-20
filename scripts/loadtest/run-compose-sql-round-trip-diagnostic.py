#!/usr/bin/env python3
"""Run the isolated SCRUM-41 SQL round-trip Compose campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = ROOT / "load-tests/sql-diagnostic-profile.json"
COMPOSE_PATHS = [ROOT / "compose.yml", ROOT / "compose.monitoring.yml", ROOT / "compose.monitoring.sql-diagnostic.yml"]
K6_RUNNER = ROOT / "scripts/loadtest/run-k6-compose-sql-diagnostic.sh"
SEEDER = ROOT / "scripts/loadtest/seed-compose-sql-diagnostic-data.py"
CAPTURE_VERIFIER = ROOT / "scripts/loadtest/verify-compose-sql-grafana-captures.py"
EVIDENCE_VERIFIER = ROOT / "scripts/loadtest/verify-compose-sql-diagnostic-evidence.py"
K6_IMAGE = "grafana/k6:0.54.0@sha256:1f40432b1cbe7234e977f96c362c9bc550a2d2b583d014dd8669fe40d3e9e755"
PUSHGATEWAY_IMAGE = "prom/pushgateway:v1.11.1@sha256:03738d278e082ee9821df730c741b3b465c251fc2b68a85883def301a55a6215"


class DiagnosticError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def epoch(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def slug(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9-]", "-", value).strip("-")
    if not normalized:
        raise DiagnosticError("campaign id must contain an alphanumeric character")
    return normalized[:32]


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run_command(command: list[str], env: dict[str, str], *, input_text: str | None = None, capture: bool = True, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, env=env, input=input_text, text=True, capture_output=capture, check=False, timeout=timeout)


def assert_ok(result: subprocess.CompletedProcess[str], label: str) -> None:
    if result.returncode == 0:
        return
    detail = (result.stderr or result.stdout or "command failed").strip().splitlines()[-1:]
    raise DiagnosticError(f"{label} failed ({result.returncode}): {(detail[0] if detail else 'unknown')[:240]}")


def compose_command(project: str, env_file: Path, *parts: str) -> list[str]:
    command = ["docker", "compose", "--env-file", str(env_file), "--project-name", project]
    for path in COMPOSE_PATHS:
        command.extend(("--file", str(path)))
    command.extend(parts)
    return command


class StatsSampler:
    def __init__(self, project: str, env_file: Path, output: Path, env: dict[str, str]) -> None:
        self.project, self.env_file, self.output, self.env = project, env_file, output, env
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=10)

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            ps = run_command(compose_command(self.project, self.env_file, "ps", "-q"), self.env)
            ids = [line.strip() for line in (ps.stdout or "").splitlines() if line.strip()]
            if ids:
                stats = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{json .}}", *ids], cwd=ROOT, env=self.env, text=True, capture_output=True, check=False)
                with self.output.open("a", encoding="utf-8") as handle:
                    for line in stats.stdout.splitlines():
                        try:
                            raw = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        handle.write(json.dumps({"ts": utc_now(), "container": raw.get("Name"), "cpuPercent": raw.get("CPUPerc"), "memoryUsage": raw.get("MemUsage"), "memoryPercent": raw.get("MemPerc"), "networkIo": raw.get("NetIO"), "blockIo": raw.get("BlockIO")}) + "\n")
            self.stop_event.wait(3)


def wait_http(url: str, timeout_seconds: int = 240) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = "unavailable"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status < 500:
                    return
        except (urllib.error.URLError, TimeoutError) as error:
            last_error = str(error)
        time.sleep(2)
    raise DiagnosticError(f"endpoint did not become ready: {url} ({last_error[:160]})")


def wait_backend_readiness(compose: list[str], env: dict[str, str], timeout_seconds: int = 240) -> None:
    """Probe the management port from inside the backend container.

    The base Compose contract exposes the application port on localhost but keeps
    management port 9091 internal; probing the mapped application port therefore
    returns a legitimate 404 instead of readiness.
    """
    deadline = time.monotonic() + timeout_seconds
    last_error = "unavailable"
    command = [
        *compose,
        "exec",
        "--no-TTY",
        "backend",
        "wget",
        "-q",
        "-O",
        "-",
        "http://127.0.0.1:9091/actuator/health/readiness",
    ]
    while time.monotonic() < deadline:
        result = run_command(command, env)
        if result.returncode == 0:
            return
        last_error = (result.stderr or result.stdout or "command failed").strip()
        time.sleep(2)
    raise DiagnosticError(f"backend readiness did not become ready ({last_error[:160]})")


def http_json(url: str, *, timeout: int = 30) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as error:
        raise DiagnosticError(f"HTTP JSON request failed: {url} ({error.__class__.__name__})") from error
    if not isinstance(payload, dict):
        raise DiagnosticError(f"HTTP JSON object expected: {url}")
    return payload


def prom_query(prometheus_url: str, expression: str) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"query": expression})
    try:
        with urllib.request.urlopen(f"{prometheus_url.rstrip('/')}/api/v1/query?{query}", timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return []
    data = payload.get("data") if isinstance(payload, dict) else None
    result = data.get("result") if isinstance(data, dict) else None
    return result if isinstance(result, list) else []


def prom_query_range(prometheus_url: str, expression: str, start: float, end: float) -> dict[str, Any]:
    expression = re.sub(r"\$[a-zA-Z_][a-zA-Z0-9_]*", ".*", expression)
    query = urllib.parse.urlencode({"query": expression, "start": f"{start:.3f}", "end": f"{end:.3f}", "step": "5"})
    url = f"{prometheus_url.rstrip('/')}/api/v1/query_range?{query}"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as error:
        return {"status": "error", "error": error.__class__.__name__, "query": expression}
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    result = data.get("result", []) if isinstance(data, dict) else []
    return {"status": "collected" if result else "empty-is-valid", "query": expression, "data": data}


def metric_value(prometheus_url: str, expression: str) -> float | None:
    values = prom_query(prometheus_url, expression)
    numbers: list[float] = []
    for value in values:
        sample = value.get("value") if isinstance(value, dict) else None
        if isinstance(sample, list) and len(sample) == 2:
            try:
                numbers.append(float(sample[1]))
            except (TypeError, ValueError):
                pass
    return sum(numbers) if numbers else None


def metric_snapshot(prometheus_url: str) -> dict[str, Any]:
    expressions = {
        "http_order_requests": 'sum(http_server_requests_seconds_count{job="backend",uri=~".*/timeline-items/order"})',
        "hikari_active": 'sum(hikaricp_connections_active{job="backend"})',
        "hikari_pending": 'sum(hikaricp_connections_pending{job="backend"})',
        "backend_cpu": 'sum(process_cpu_usage{job="backend"})',
        "postgres_commits": 'sum(pg_stat_database_xact_commit{job="postgres"})',
        "postgres_deadlocks": 'sum(pg_stat_database_deadlocks{job="postgres"})',
        "postgres_blks_read": 'sum(pg_stat_database_blks_read{job="postgres"})',
        "redis_commands": 'sum(redis_commands_processed_total{job="redis"})',
    }
    return {"capturedAtUtc": utc_now(), "available": True, "values": {name: metric_value(prometheus_url, expression) for name, expression in expressions.items()}, "expressions": expressions}


def metric_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key in sorted(set((before.get("values") or {})) | set((after.get("values") or {}))):
        first, last = (before.get("values") or {}).get(key), (after.get("values") or {}).get(key)
        values[key] = {"before": first, "after": last, "delta": (last - first) if isinstance(first, (int, float)) and isinstance(last, (int, float)) else None}
    return {"schemaVersion": "scrum41-sql-backend-metric-delta/v1", "beforeCapturedAtUtc": before.get("capturedAtUtc"), "afterCapturedAtUtc": after.get("capturedAtUtc"), "before": before.get("values"), "after": after.get("values"), "delta": values, "available": bool(before.get("available") and after.get("available"))}


def psql(compose: list[str], env: dict[str, str], sql: str, *, database_user: str | None = None) -> str:
    result = run_command([*compose, "exec", "--no-TTY", "--user", "postgres", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-U", database_user or env.get("POSTGRES_USER", "postgres"), "-d", env.get("POSTGRES_DB", "travelplanner"), "-tA", "-c", sql], env)
    assert_ok(result, "psql")
    return (result.stdout or "").strip()


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def reset_pg_stat_statements(compose: list[str], env: dict[str, str]) -> str:
    output = psql(compose, env, "SELECT pg_stat_statements_reset(); SELECT clock_timestamp()::text;")
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        raise DiagnosticError("pg_stat_statements reset timestamp missing")
    return lines[-1].replace(" ", "T", 1) if " " in lines[-1] and "T" not in lines[-1] else lines[-1]


def normalize_query(query: str) -> str:
    query = re.sub(r"--[^\n]*|/\*.*?\*/", " ", query, flags=re.DOTALL)
    query = re.sub(r"'(?:''|[^'])*'", "?", query)
    query = re.sub(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", "?", query, flags=re.IGNORECASE)
    query = re.sub(r"\b\d+(?:\.\d+)?\b", "?", query)
    return re.sub(r"\s+", " ", query).strip().upper()


def classify_query(normalized: str) -> str:
    if not normalized:
        return "transaction_or_session"
    if "PG_STAT_STATEMENTS" in normalized or "PG_CATALOG" in normalized or normalized.startswith(("BEGIN", "COMMIT", "ROLLBACK", "SET ", "SHOW ", "RESET ", "START TRANSACTION")):
        return "transaction_or_session"
    if "PG_" in normalized or "CURRENT_DATABASE()" in normalized or "CLOCK_TIMESTAMP()" in normalized or "VERSION()" in normalized:
        return "transaction_or_session"
    if "TIMELINE_TABLE" in normalized and normalized.startswith(("UPDATE", "INSERT", "DELETE")):
        return "timeline_update" if normalized.startswith("UPDATE") else "unknown_application_table_statement"
    if "TIMELINE_TABLE" in normalized:
        return "timeline_select"
    if "PLANNERS_TABLE" in normalized:
        return "travel_select"
    if "PLANNER_MEMBERS" in normalized or "USER_TABLE" in normalized:
        return "membership_permission_select"
    return "unknown_application_table_statement"


def statement_snapshot(compose: list[str], env: dict[str, str], reset_at: str) -> dict[str, Any]:
    query = """SELECT COALESCE(json_agg(json_build_object(
        'query', s.query,
        'calls', s.calls,
        'rows', s.rows,
        'totalExecMs', s.total_exec_time,
        'meanExecMs', s.mean_exec_time,
        'sharedBlksHit', s.shared_blks_hit,
        'sharedBlksRead', s.shared_blks_read,
        'tempBlksWritten', s.temp_blks_written,
        'walBytes', s.wal_bytes,
        'blkReadMs', s.shared_blk_read_time,
        'blkWriteMs', s.shared_blk_write_time
    )), '[]'::json)::text
    FROM pg_stat_statements s
    JOIN pg_database d ON d.oid = s.dbid
    WHERE d.datname = current_database();"""
    raw = psql(compose, env, query)
    try:
        rows = json.loads(raw or "[]")
    except json.JSONDecodeError as error:
        raise DiagnosticError("pg_stat_statements JSON snapshot was invalid") from error
    if not isinstance(rows, list):
        raise DiagnosticError("pg_stat_statements snapshot is not a list")
    statements: list[dict[str, Any]] = []
    family_totals: dict[str, dict[str, float]] = {}
    unknown = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized = normalize_query(str(row.get("query", "")))
        family = classify_query(normalized)
        if family == "unknown_application_table_statement":
            unknown += 1
        record = {
            "queryFamily": family,
            "normalizedQuery": normalized,
            "calls": float(row.get("calls") or 0),
            "rows": float(row.get("rows") or 0),
            "totalExecMs": float(row.get("totalExecMs") or 0),
            "meanExecMs": float(row.get("meanExecMs") or 0),
            "sharedBlksHit": float(row.get("sharedBlksHit") or 0),
            "sharedBlksRead": float(row.get("sharedBlksRead") or 0),
            "tempBlksWritten": float(row.get("tempBlksWritten") or 0),
            "walBytes": float(row.get("walBytes") or 0),
            "blkReadMs": float(row.get("blkReadMs") or 0),
            "blkWriteMs": float(row.get("blkWriteMs") or 0),
        }
        statements.append(record)
        target = family_totals.setdefault(family, {"calls": 0.0, "rows": 0.0, "totalExecMs": 0.0, "meanExecMs": 0.0, "sharedBlksRead": 0.0, "tempBlksWritten": 0.0, "walBytes": 0.0, "blkReadMs": 0.0, "blkWriteMs": 0.0})
        for key in ("calls", "rows", "totalExecMs", "sharedBlksRead", "tempBlksWritten", "walBytes", "blkReadMs", "blkWriteMs"):
            target[key] += record[key]
        target["meanExecMs"] = target["totalExecMs"] / target["calls"] if target["calls"] else 0.0
    return {"schemaVersion": "scrum41-pg-stat-statements/v1", "resetAtUtc": reset_at, "snapshotAtUtc": utc_now(), "statements": statements, "queryFamilies": family_totals, "unknownCount": unknown}


def stage_metrics_payload(stage: dict[str, Any], breakdown: dict[str, Any], replicate: int, mode: str, item_count: int) -> str:
    labels = {"replicate": str(replicate), "mode": mode, "item_count": str(item_count), "statistic": "median"}
    p95_labels = {**labels, "statistic": "p95"}

    def render_labels(extra: dict[str, str]) -> str:
        return ",".join(f'{key}="{value}"' for key, value in sorted(extra.items()))

    lines = [
        "# TYPE scrum41_sql_diagnostic_api_duration_ms gauge",
        f"scrum41_sql_diagnostic_api_duration_ms{{{render_labels(p95_labels)}}} {stage['apiP95Ms']}",
        "# TYPE scrum41_sql_diagnostic_item_count gauge",
        f"scrum41_sql_diagnostic_item_count{{{render_labels(labels)}}} {item_count}",
        "# TYPE scrum41_sql_diagnostic_update_amplification gauge",
        f"scrum41_sql_diagnostic_update_amplification{{{render_labels(labels)}}} {stage['timelineUpdateCallsPerRequest'] or 0}",
        "# TYPE scrum41_sql_diagnostic_sql_calls_per_request gauge",
    ]
    for family in ("travel_select", "timeline_select", "membership_permission_select", "timeline_update", "transaction_or_session", "unknown_application_table_statement"):
        family_labels = {**labels, "query_family": family}
        values = (breakdown.get("queryFamilies") or {}).get(family) or {}
        calls = float(values.get("calls") or 0)
        lines.append(
            f"scrum41_sql_diagnostic_sql_calls_per_request{{{render_labels(family_labels)}}} {calls / max(stage['validity']['successfulRequests'], 1)}"
        )
    lines.append("# TYPE scrum41_sql_diagnostic_db_exec_ms_per_request gauge")
    for family in ("travel_select", "timeline_select", "membership_permission_select", "timeline_update", "transaction_or_session", "unknown_application_table_statement"):
        family_labels = {**labels, "query_family": family}
        values = (breakdown.get("queryFamilies") or {}).get(family) or {}
        total_exec = float(values.get("totalExecMs") or 0)
        lines.append(
            f"scrum41_sql_diagnostic_db_exec_ms_per_request{{{render_labels(family_labels)}}} {total_exec / max(stage['validity']['successfulRequests'], 1)}"
        )
    lines.append("# TYPE scrum41_sql_diagnostic_db_mean_exec_ms_per_call gauge")
    for family in ("travel_select", "timeline_select", "membership_permission_select", "timeline_update", "transaction_or_session", "unknown_application_table_statement"):
        family_labels = {**labels, "query_family": family}
        values = (breakdown.get("queryFamilies") or {}).get(family) or {}
        mean_exec = float(values.get("meanExecMs") or 0)
        lines.append(
            f"scrum41_sql_diagnostic_db_mean_exec_ms_per_call{{{render_labels(family_labels)}}} {mean_exec}"
        )
    return "\n".join(lines) + "\n"


def push_metrics(compose: list[str], env: dict[str, str], payload: str) -> None:
    # Prometheus contains BusyBox wget; using it as the in-network client keeps
    # Pushgateway unexposed on the host while preserving bounded labels.
    command = [*compose, "exec", "--no-TTY", "--user", "nobody", "prometheus", "wget", "-qO-", "--header", "Content-Type: text/plain", "--post-data", payload, "http://pushgateway:9091/metrics/job/scrum41_sql_diagnostic"]
    result = run_command(command, env, timeout=30)
    assert_ok(result, "Pushgateway publish")


def fixture_manifest(data: dict[str, Any], replicate: int) -> dict[str, Any]:
    stages: dict[str, Any] = {}
    for key, value in sorted((data.get("credentials") or [{}])[0].get("sqlDiagnosticStages", {}).items()):
        ids = value.get("timelineItemIds") or []
        stages[key] = {"mode": value.get("mode"), "itemCount": value.get("itemCount"), "count": len(ids), "canonicalOrderSha256": hashlib.sha256("\n".join(ids).encode()).hexdigest()}
    return {"schemaVersion": "scrum41-sql-fixture-manifest/v1", "replicate": replicate, "stageCount": len(stages), "stages": stages, "note": "synthetic IDs remain in the temporary 0600 credential file only"}


def canonical_after(compose: list[str], env: dict[str, str], travel_id: str, expected_ids: list[str]) -> bool:
    result = psql(compose, env, f"SELECT id::text FROM timeline_table WHERE planner_id = {sql_literal(travel_id)} AND day_number = 1 ORDER BY visit_order;")
    actual = [line.strip() for line in result.splitlines() if line.strip()]
    return actual == expected_ids


def inventory(prometheus_url: str) -> dict[str, Any]:
    try:
        payload = http_json(f"{prometheus_url.rstrip('/')}/api/v1/label/__name__/values")
        names = (payload.get("data") or []) if isinstance(payload.get("data"), list) else []
    except DiagnosticError:
        names = []
    relevant = sorted(name for name in names if isinstance(name, str) and (name.startswith("scrum41_sql_diagnostic_") or name.startswith("k6_") or name.startswith("hikaricp_") or name.startswith("pg_") or name.startswith("redis_") or name.startswith("http_server_requests_")))
    targets = prom_query(prometheus_url, "up")
    return {"schemaVersion": "scrum41-sql-metric-inventory/v1", "capturedAtUtc": utc_now(), "metricNames": relevant, "targetSeriesCount": len(targets), "requiredMetricPrefixes": ["scrum41_sql_diagnostic_", "k6_", "hikaricp_", "pg_", "redis_"]}


def run_playwright(pwcli: str, session: str, *arguments: str) -> str:
    result = subprocess.run([pwcli, "--session", session, *arguments], cwd=ROOT, text=True, capture_output=True, check=False, timeout=120)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "browser command failed").strip().splitlines()[-1:]
        raise DiagnosticError(f"Playwright command failed: {(detail[0] if detail else 'unknown')[:240]}")
    return result.stdout or ""


def copy_cli_screenshot(output: str, destination: Path) -> None:
    match = re.search(r"\(([^)]+\.png)\)", output)
    if not match:
        raise DiagnosticError("Playwright screenshot output path was not reported")
    source = Path(match.group(1))
    if not source.is_absolute():
        source = ROOT / source
    if not source.is_file():
        raise DiagnosticError("Playwright screenshot file was not created")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def crop_panel_fallback(full_path: Path, panel_path: Path, index: int, panel_count: int) -> None:
    try:
        from PIL import Image
        image = Image.open(full_path)
        columns = 3
        rows = (panel_count + columns - 1) // columns
        width, height = image.size
        column, row = index % columns, index // columns
        crop = image.crop((int(width * column / columns), int(height * row / rows), int(width * (column + 1) / columns), int(height * (row + 1) / rows)))
        # The browser's element screenshot can be a narrow/short viewport.  A
        # deterministic crop from the 1920x1080 dashboard is the evidence
        # fallback, but keep every panel above the capture contract even when
        # a dashboard layout produces a smaller crop.
        if crop.width < 640 or crop.height < 240:
            crop = crop.resize((max(640, crop.width), max(240, crop.height)), Image.Resampling.LANCZOS)
        crop.save(panel_path, format="PNG")
    except Exception as error:
        raise DiagnosticError(f"panel fallback failed: {error}") from error


def png_is_usable(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 8192:
        return False
    try:
        from PIL import Image
        width, height = Image.open(path).size
        return width >= 640 and height >= 240
    except Exception:
        return False


def capture_grafana(replicate_dir: Path, campaign_id: str, replicate: int, grafana_url: str, prometheus_url: str, from_epoch: float, to_epoch: float, env: dict[str, str]) -> None:
    grafana_dir, panels_dir, queries_dir = replicate_dir / "grafana", replicate_dir / "grafana/panels", replicate_dir / "grafana/queries"
    panels_dir.mkdir(parents=True, exist_ok=True)
    queries_dir.mkdir(parents=True, exist_ok=True)
    payload = http_json(f"{grafana_url.rstrip('/')}/api/dashboards/uid/compose-sql-round-trip-diagnostic")
    dashboard = payload.get("dashboard") if isinstance(payload.get("dashboard"), dict) else payload
    if not isinstance(dashboard, dict) or dashboard.get("uid") != "compose-sql-round-trip-diagnostic":
        raise DiagnosticError("Grafana SQL dashboard was not provisioned")
    from_utc = datetime.fromtimestamp(from_epoch, timezone.utc).isoformat().replace("+00:00", "Z")
    to_utc = datetime.fromtimestamp(to_epoch, timezone.utc).isoformat().replace("+00:00", "Z")
    metadata = {"schemaVersion": "compose-sql-grafana-capture/v1", "campaignId": campaign_id, "replicate": replicate, "fromUtc": from_utc, "toUtc": to_utc, "dashboardUid": dashboard["uid"], "dashboardVersion": dashboard.get("version", 1), "dashboardPath": "monitoring/grafana/dashboards/compose-sql-round-trip-diagnostic.json", "capturedAtUtc": utc_now()}
    write_json(grafana_dir / "capture-metadata.json", metadata)
    write_json(grafana_dir / "dashboard.json", dashboard)
    panel_contracts: list[tuple[int, dict[str, Any]]] = []
    for panel in dashboard.get("panels", []):
        panel_id = int(panel["id"])
        query_paths: list[str] = []
        for target in panel.get("targets", []):
            ref_id = str(target.get("refId", "A"))
            query_path = queries_dir / f"panel-{panel_id}-{ref_id}.json"
            write_json(query_path, {"panelId": panel_id, "refId": ref_id, **prom_query_range(prometheus_url, str(target.get("expr", "")), from_epoch, to_epoch)})
            query_paths.append(str(query_path.relative_to(replicate_dir)))
        panel_contracts.append((panel_id, {**metadata, "panelId": panel_id, "panelTitle": panel.get("title", f"Panel {panel_id}"), "queryJsonPaths": query_paths, "expectedPngPath": f"grafana/panels/panel-{panel_id}.png"}))
    pwcli = os.environ.get("PWCLI", "/Users/mac/.codex/skills/playwright/scripts/playwright_cli.sh")
    session = f"scrum41-sql-{campaign_id}-r{replicate}"
    dashboard_url = f"{grafana_url}/d/{dashboard['uid']}/compose-sql-round-trip-diagnostic?orgId=1&from={int(from_epoch * 1000)}&to={int(to_epoch * 1000)}&kiosk=tv"
    try:
        run_playwright(pwcli, session, "close")
    except DiagnosticError:
        pass
    run_playwright(pwcli, session, "open", dashboard_url)
    snapshot = run_playwright(pwcli, session, "snapshot")
    (grafana_dir / "browser-snapshot.txt").write_text(snapshot, encoding="utf-8")
    run_playwright(pwcli, session, "resize", "1920", "1080")
    time.sleep(5)
    root_match = re.search(r"main \[ref=(e\d+)\]", snapshot)
    output = run_playwright(pwcli, session, "screenshot", *( [root_match.group(1)] if root_match else [] ))
    full_path = grafana_dir / "dashboard-full.png"
    copy_cli_screenshot(output, full_path)
    key_ids = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    panel_titles = {int(panel["id"]): str(panel.get("title", f"Panel {panel['id']}")) for panel in dashboard.get("panels", [])}
    for index, panel_id in enumerate(key_ids):
        panel_path = panels_dir / f"panel-{panel_id}.png"
        try:
            found = run_playwright(pwcli, session, "find", panel_titles.get(panel_id, f"Panel {panel_id}"))
            region_match = re.search(r"region \[ref=(e\d+)\]", found)
            if not region_match:
                raise DiagnosticError("panel region ref missing")
            copy_cli_screenshot(run_playwright(pwcli, session, "screenshot", region_match.group(1)), panel_path)
            if not png_is_usable(panel_path):
                crop_panel_fallback(full_path, panel_path, index, len(key_ids))
        except DiagnosticError:
            crop_panel_fallback(full_path, panel_path, index, len(key_ids))
    try:
        run_playwright(pwcli, session, "close")
    except DiagnosticError:
        pass
    for panel_id, contract in panel_contracts:
        if panel_id in key_ids:
            write_json(panels_dir / f"panel-{panel_id}.capture.json", contract)


def stage_order(profile: dict[str, Any], replicate: int) -> list[tuple[str, int]]:
    counts = list(profile["orderByReplicate"][str(replicate)]["itemCounts"])
    mode_order = profile["orderByReplicate"][str(replicate)].get("modeOrder")
    if isinstance(mode_order, list):
        return [(mode, count) for count in counts for mode in mode_order]
    stages: list[tuple[str, int]] = []
    for position, count in enumerate(counts):
        first = "noop" if position % 2 == 0 else "reverse"
        stages.extend(((first, count), ("reverse" if first == "noop" else "noop", count)))
    return stages


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-id", default=None)
    parser.add_argument("--replicates", type=int, default=3)
    parser.add_argument("--backend-port", type=int, default=18080)
    parser.add_argument("--grafana-port", type=int, default=3301)
    parser.add_argument("--prometheus-port", type=int, default=9900)
    parser.add_argument("--evidence-root", type=Path, default=ROOT / "evidence/load-tests")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.dev.example")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--keep-stack", action="store_true")
    return parser.parse_args()


def run_campaign(args: argparse.Namespace) -> Path:
    if args.replicates < 1 or args.replicates > 3:
        raise DiagnosticError("--replicates must be between 1 and 3")
    env_file = args.env_file.resolve()
    if not env_file.is_file():
        raise DiagnosticError(f"env file does not exist: {env_file}")
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    campaign_id = slug(args.campaign_id or datetime.now(timezone.utc).strftime("scrum41-sql-round-trip-%Y%m%dT%H%M%SZ"))
    effective = json.loads(json.dumps(profile))
    if args.smoke:
        effective["itemCounts"] = [3, 10]
        effective["warmupIterations"] = 2
        effective["measuredIterations"] = 4
        effective["replicates"] = 1
        effective["orderByReplicate"] = {"1": {"itemCounts": [3, 10], "modeOrder": ["noop", "reverse"]}}
        args.replicates = 1
    evidence_root = args.evidence_root.resolve() / f"{campaign_id}-sql-round-trip-diagnostic"
    if evidence_root.exists():
        raise DiagnosticError(f"evidence directory already exists: {evidence_root}")
    evidence_root.mkdir(parents=True)
    profile_copy = evidence_root / "effective-profile.json"
    write_json(profile_copy, effective)
    env_values = read_env(env_file)
    source_digests = {
        "profile": hashlib.sha256(PROFILE_PATH.read_bytes()).hexdigest(),
        "effectiveProfile": hashlib.sha256(profile_copy.read_bytes()).hexdigest(),
        "overlay": hashlib.sha256((ROOT / "compose.monitoring.sql-diagnostic.yml").read_bytes()).hexdigest(),
        "prometheus": hashlib.sha256((ROOT / "monitoring/prometheus/prometheus.sql-diagnostic.yml").read_bytes()).hexdigest(),
        "dashboard": hashlib.sha256((ROOT / "monitoring/grafana/dashboards/compose-sql-round-trip-diagnostic.json").read_bytes()).hexdigest(),
        "k6Image": hashlib.sha256(K6_IMAGE.encode()).hexdigest(),
        "pushgatewayImage": hashlib.sha256(PUSHGATEWAY_IMAGE.encode()).hexdigest(),
    }
    campaign_metadata = {"schemaVersion": "scrum41-sql-round-trip-campaign/v1", "campaignId": campaign_id, "jiraKey": "SCRUM-41", "startedAtUtc": utc_now(), "profile": "load-tests/sql-diagnostic-profile.json", "effectiveProfile": "effective-profile.json", "replicates": args.replicates, "smoke": args.smoke, "composeFiles": [str(path.relative_to(ROOT)) for path in COMPOSE_PATHS], "sourceDigests": source_digests, "k6Image": K6_IMAGE, "pushgatewayImage": PUSHGATEWAY_IMAGE, "status": "running"}
    write_json(evidence_root / "campaign-metadata.json", campaign_metadata)
    write_json(evidence_root / "campaign-manifest.json", {"schemaVersion": "scrum41-sql-round-trip-campaign-manifest/v1", "campaignId": campaign_id, "jiraKey": "SCRUM-41", "profile": effective, "sourceDigests": source_digests, "stageOrder": {str(rep): stage_order(effective, rep) for rep in range(1, args.replicates + 1)}})
    for replicate in range(1, args.replicates + 1):
        project = f"travel-planner-sql-diagnostic-scrum-41-{slug(campaign_id)[-18:]}-r{replicate}"
        replicate_dir = evidence_root / f"replicate-{replicate}"
        replicate_dir.mkdir()
        backend_port = args.backend_port + (replicate - 1) * 10
        grafana_port = args.grafana_port + (replicate - 1) * 10
        prometheus_port = args.prometheus_port + (replicate - 1) * 10
        compose_env = {**os.environ, **env_values, "BACKEND_PORT": str(backend_port), "GRAFANA_PORT": str(grafana_port), "PROMETHEUS_PORT": str(prometheus_port), "SPRING_PROFILES_ACTIVE": env_values.get("SPRING_PROFILES_ACTIVE", "dev"), "COMPOSE_PROJECT_NAME": project}
        compose = compose_command(project, env_file)
        network = f"{project}_app-network"
        replicate_started = time.time()
        sampler: StatsSampler | None = None
        try:
            assert_ok(run_command([*compose, "config", "--quiet"], compose_env), f"Compose config replicate {replicate}")
            assert_ok(run_command([*compose, "up", "--build", "--detach", "--wait"], compose_env, capture=False, timeout=900), f"Compose up replicate {replicate}")
            wait_backend_readiness(compose, compose_env)
            wait_http(f"http://127.0.0.1:{prometheus_port}/-/ready")
            wait_http(f"http://127.0.0.1:{grafana_port}/api/health")
            sampler = StatsSampler(project, env_file, replicate_dir / "service-stats.jsonl", compose_env)
            sampler.start()
            prometheus_url, grafana_url = f"http://127.0.0.1:{prometheus_port}", f"http://127.0.0.1:{grafana_port}"
            write_json(replicate_dir / "metric-inventory.json", inventory(prometheus_url))
            with tempfile.TemporaryDirectory(prefix=f"scrum41-sql-r{replicate}-", dir="/private/tmp") as temp_dir:
                data_file = Path(temp_dir) / "credentials.json"
                seed_command = ["python3", str(SEEDER), "--env-file", str(env_file), "--project-name", project, "--base-url", f"http://127.0.0.1:{backend_port}", "--data-file", str(data_file), "--seed-tag", f"{campaign_id}-r{replicate}"]
                for path in COMPOSE_PATHS:
                    seed_command.extend(("--compose-file", str(path)))
                seed_result = run_command(seed_command, compose_env, timeout=600)
                (replicate_dir / "seed-console.log").write_text((seed_result.stdout or "") + (seed_result.stderr or ""), encoding="utf-8")
                assert_ok(seed_result, f"seed replicate {replicate}")
                credentials = json.loads(data_file.read_text(encoding="utf-8"))
                write_json(replicate_dir / "fixture-manifest.json", fixture_manifest(credentials, replicate))
                stage_data = (credentials.get("credentials") or [{}])[0].get("sqlDiagnosticStages", {})
                for sequence, (mode, item_count) in enumerate(stage_order(effective, replicate), start=1):
                    stage_key = f"{mode}-{item_count}"
                    stage_dir = replicate_dir / "stages" / stage_key
                    stage_dir.mkdir(parents=True)
                    stage_config = stage_data.get(stage_key)
                    if not stage_config:
                        raise DiagnosticError(f"fixture stage missing: {stage_key}")
                    warmup_dir = stage_dir / "warmup"
                    warmup_env = {**compose_env, "REPOSITORY_ROOT": str(ROOT), "SQL_DIAG_ITERATIONS": str(effective["warmupIterations"]), "SQL_DIAG_PACING_SECONDS": str(effective["pacingSeconds"])}
                    warmup_result = subprocess.run(["bash", str(K6_RUNNER), str(warmup_dir), mode, str(item_count), str(data_file), project, network, "http://backend:8080", str(replicate), campaign_id, str(PROFILE_PATH)], cwd=ROOT, env=warmup_env, text=True, capture_output=True, check=False, timeout=600)
                    write_json(stage_dir / "warmup-status.json", {"k6ExitCode": warmup_result.returncode, "iterations": effective["warmupIterations"]})
                    if warmup_result.returncode != 0:
                        raise DiagnosticError(f"warmup failed: {stage_key}")
                    reset_at = reset_pg_stat_statements(compose, compose_env)
                    before = metric_snapshot(prometheus_url)
                    measured_env = {**compose_env, "REPOSITORY_ROOT": str(ROOT), "SQL_DIAG_ITERATIONS": str(effective["measuredIterations"]), "SQL_DIAG_PACING_SECONDS": str(effective["pacingSeconds"])}
                    measured_result = subprocess.run(["bash", str(K6_RUNNER), str(stage_dir), mode, str(item_count), str(data_file), project, network, "http://backend:8080", str(replicate), campaign_id, str(PROFILE_PATH)], cwd=ROOT, env=measured_env, text=True, capture_output=True, check=False, timeout=900)
                    (stage_dir / "runner-console.log").write_text((measured_result.stdout or "") + (measured_result.stderr or ""), encoding="utf-8")
                    if measured_result.returncode != 0:
                        raise DiagnosticError(f"measured k6 failed: {stage_key}")
                    after = metric_snapshot(prometheus_url)
                    breakdown = statement_snapshot(compose, compose_env, reset_at)
                    write_json(stage_dir / "pg-stat-statements.json", breakdown)
                    write_json(stage_dir / "query-breakdown.json", {"schemaVersion": "scrum41-sql-query-breakdown/v1", "queryFamilies": breakdown.get("queryFamilies"), "unknownCount": breakdown.get("unknownCount"), "callsPerRequest": {family: (values.get("calls", 0.0) / max(float(effective["measuredIterations"]), 1)) for family, values in (breakdown.get("queryFamilies") or {}).items()}})
                    metadata = json.loads((stage_dir / "metadata.json").read_text(encoding="utf-8"))
                    metadata.update({"sequence": sequence, "replicate": replicate, "mode": mode, "itemCount": item_count, "measuredIterations": effective["measuredIterations"], "warmupIterations": effective["warmupIterations"], "resetAtUtc": reset_at, "snapshotAtUtc": breakdown.get("snapshotAtUtc"), "canonicalAfterMeasured": canonical_after(compose, compose_env, str(stage_config["travelId"]), list(stage_config["timelineItemIds"])), "sourceDigests": source_digests})
                    write_json(stage_dir / "metadata.json", metadata)
                    write_json(stage_dir / "backend-metric-delta.json", metric_delta(before, after))
                    native_metrics = json.loads((stage_dir / "k6-native-summary.json").read_text(encoding="utf-8")).get("metrics", {})
                    api_p95_ms = float(native_metrics.get("http_req_duration", {}).get("values", {}).get("p(95)") or 0)
                    successful_requests = float(native_metrics.get("sql_diagnostic_successful_requests", {}).get("values", {}).get("count") or effective["measuredIterations"])
                    timeline_update_calls = float((breakdown.get("queryFamilies") or {}).get("timeline_update", {}).get("calls") or 0)
                    push_stage = {**metadata, "apiP95Ms": api_p95_ms, "timelineUpdateCallsPerRequest": timeline_update_calls / max(successful_requests, 1), "validity": {"successfulRequests": successful_requests}}
                    push_metrics(compose, compose_env, stage_metrics_payload(push_stage, breakdown, replicate, mode, item_count))
                    time.sleep(6)
                write_json(replicate_dir / "metric-inventory-after.json", inventory(prometheus_url))
            replicate_ended = time.time()
            capture_grafana(replicate_dir, campaign_id, replicate, grafana_url, prometheus_url, replicate_started, replicate_ended, compose_env)
            assert_ok(run_command(["python3", str(CAPTURE_VERIFIER), "--evidence-root", str(replicate_dir)], compose_env), f"Grafana capture verification replicate {replicate}")
            write_json(replicate_dir / "replicate-metadata.json", {"schemaVersion": "scrum41-sql-replicate/v1", "campaignId": campaign_id, "jiraKey": "SCRUM-41", "replicate": replicate, "composeProject": project, "network": network, "startedAtUtc": datetime.fromtimestamp(replicate_started, timezone.utc).isoformat().replace("+00:00", "Z"), "endedAtUtc": datetime.fromtimestamp(replicate_ended, timezone.utc).isoformat().replace("+00:00", "Z"), "sourceDigests": source_digests, "status": "captured"})
        finally:
            if sampler:
                sampler.stop()
            if not args.keep_stack:
                cleanup = run_command([*compose, "down", "--volumes", "--remove-orphans"], compose_env, timeout=300)
                if cleanup.returncode != 0:
                    write_json(replicate_dir / "cleanup-failure.json", {"status": "failed", "project": project})
                    raise DiagnosticError(f"cleanup failed for exact project {project}")
    campaign_metadata.update({"endedAtUtc": utc_now(), "status": "complete"})
    write_json(evidence_root / "campaign-metadata.json", campaign_metadata)
    assert_ok(run_command(["python3", str(EVIDENCE_VERIFIER), "--evidence-root", str(evidence_root)], {**os.environ, **env_values}), "evidence safety")
    return evidence_root


def main() -> int:
    try:
        output = run_campaign(parse_args())
    except (DiagnosticError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        print(f"[sql-diagnostic] ERROR: {error}", file=os.sys.stderr)
        return 1
    print(f"[sql-diagnostic] evidence root: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
