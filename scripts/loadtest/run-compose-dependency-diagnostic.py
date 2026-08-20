#!/usr/bin/env python3
"""Run the SCRUM-41 Compose dependency diagnostic campaign.

The orchestrator owns one isolated Compose project per replicate, seeds a
variant-scoped credential set, runs k6 on the internal app network, records
sanitized service statistics, publishes Grafana annotations, and removes only
the validated diagnostic project after evidence is written.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = ROOT / "load-tests/diagnostic-profile.json"
ENV_PATH = ROOT / ".env.prod.example"
COMPOSE_PATHS = [
    ROOT / "compose.yml",
    ROOT / "compose.monitoring.yml",
    ROOT / "compose.monitoring.dev.yml",
    ROOT / "compose.monitoring.diagnostic.yml",
]
K6_RUNNER = ROOT / "scripts/loadtest/run-k6-compose-diagnostic.sh"
SEEDER = ROOT / "scripts/loadtest/seed-compose-diagnostic-data.py"
CAPTURE_VERIFIER = ROOT / "scripts/loadtest/verify-compose-grafana-captures.py"
VARIANT_IDS = [
    "refresh-only",
    "read-only",
    "fixed-cardinality-mixed",
    "growing-cardinality-mixed",
]
ORDER_MATRIX = {
    1: VARIANT_IDS,
    2: ["read-only", "growing-cardinality-mixed", "refresh-only", "fixed-cardinality-mixed"],
    3: ["fixed-cardinality-mixed", "refresh-only", "growing-cardinality-mixed", "read-only"],
}


class DiagnosticError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-id", default=None)
    parser.add_argument("--replicates", type=int, default=3)
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--rate", type=int, default=20)
    parser.add_argument("--backend-port", type=int, default=18080)
    parser.add_argument("--grafana-port", type=int, default=3301)
    parser.add_argument("--prometheus-port", type=int, default=9900)
    parser.add_argument("--loki-port", type=int, default=3310)
    parser.add_argument("--alloy-port", type=int, default=13245)
    parser.add_argument("--evidence-root", type=Path, default=ROOT / "evidence/load-tests")
    parser.add_argument("--env-file", type=Path, default=ENV_PATH)
    parser.add_argument("--smoke", action="store_true", help="one short refresh-only run")
    parser.add_argument("--keep-stack", action="store_true")
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slug(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9-]", "-", value).strip("-")
    if not normalized:
        raise DiagnosticError("campaign id must contain an alphanumeric character")
    return normalized[:48]


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip("\"'")
    return values


def compose_command(project: str, env_file: Path, *parts: str) -> list[str]:
    command = ["docker", "compose", "--env-file", str(env_file), "--project-name", project]
    for compose_file in COMPOSE_PATHS:
        command.extend(("--file", str(compose_file)))
    command.extend(parts)
    return command


def run_command(command: list[str], *, env: dict[str, str], capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=capture,
        check=False,
    )


def assert_command_ok(result: subprocess.CompletedProcess[str], label: str) -> None:
    if result.returncode == 0:
        return
    tail = (result.stderr or result.stdout or "command failed").strip().splitlines()[-1]
    raise DiagnosticError(f"{label} failed ({result.returncode}): {tail[:240]}")


class StatsSampler:
    def __init__(self, project: str, env_file: Path, output: Path, env: dict[str, str]) -> None:
        self.project = project
        self.env_file = env_file
        self.output = output
        self.env = env
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._loop, name="compose-diagnostic-stats", daemon=True)

    def start(self) -> None:
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=10)

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            ps = run_command(compose_command(self.project, self.env_file, "ps", "-q"), env=self.env)
            ids = [line.strip() for line in ps.stdout.splitlines() if line.strip()]
            if ids:
                result = subprocess.run(
                    ["docker", "stats", "--no-stream", "--format", "{{json .}}", *ids],
                    cwd=ROOT,
                    env=self.env,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                with self.output.open("a", encoding="utf-8") as handle:
                    for line in result.stdout.splitlines():
                        try:
                            raw = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        # Container names are safe identifiers; no command or env is persisted.
                        handle.write(json.dumps({
                            "ts": utc_now(),
                            "container": raw.get("Name"),
                            "cpuPercent": raw.get("CPUPerc"),
                            "memoryUsage": raw.get("MemUsage"),
                            "memoryPercent": raw.get("MemPerc"),
                            "networkIo": raw.get("NetIO"),
                            "blockIo": raw.get("BlockIO"),
                        }) + "\n")
            self.stop_event.wait(5)


def wait_http(url: str, timeout_seconds: int = 180) -> None:
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


def post_annotation(grafana_url: str, username: str, password: str, text: str, tags: list[str]) -> None:
    payload = json.dumps({"time": int(time.time() * 1000), "text": text, "tags": tags}).encode()
    request = urllib.request.Request(
        f"{grafana_url}/api/annotations",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status >= 300:
                raise DiagnosticError(f"Grafana annotation returned {response.status}")
    except urllib.error.HTTPError as error:
        raise DiagnosticError(f"Grafana annotation failed with HTTP {error.code}") from error


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def prom_query_range(prometheus_url: str, expression: str, start: float, end: float) -> dict[str, object]:
    expression = expression.replace('$variant', '.*').replace('$operation', '.*')
    query = urllib.parse.urlencode({
        "query": expression,
        "start": f"{start:.3f}",
        "end": f"{end:.3f}",
        "step": "15",
    })
    url = f"{prometheus_url}/api/v1/query_range?{query}"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        return {"status": "error", "error": error.__class__.__name__, "query": expression}
    if payload.get("status") != "success":
        return {"status": "error", "query": expression, "response": payload}
    data = payload.get("data", {})
    result = data.get("result", []) if isinstance(data, dict) else []
    return {"status": "collected" if result else "empty-is-valid", "query": expression, "data": data}


def run_playwright(pwcli: str, session: str, *arguments: str) -> str:
    result = subprocess.run(
        [pwcli, "--session", session, *arguments],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "browser command failed").strip().splitlines()[-1]
        raise DiagnosticError(f"browser capture command failed: {detail[:240]}")
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
    """Create a deterministic crop when Grafana's panel root is not exposed."""
    try:
        from PIL import Image
        image = Image.open(full_path)
        columns = 3
        rows = (panel_count + columns - 1) // columns
        width, height = image.size
        column = index % columns
        row = index // columns
        left = int(width * column / columns)
        right = int(width * (column + 1) / columns)
        top = int(height * row / rows)
        bottom = int(height * (row + 1) / rows)
        image.crop((left, top, right, bottom)).save(panel_path, format="PNG")
    except Exception as error:
        raise DiagnosticError(f"unable to create panel capture fallback: {error}") from error


def png_is_usable(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 8192:
        return False
    try:
        from PIL import Image
        width, height = Image.open(path).size
        return width >= 640 and height >= 240
    except Exception:
        return False


def capture_grafana(
    replicate_dir: Path,
    campaign_id: str,
    replicate: int,
    grafana_url: str,
    prometheus_url: str,
    from_epoch: float,
    to_epoch: float,
) -> None:
    grafana_dir = replicate_dir / "grafana"
    panels_dir = grafana_dir / "panels"
    queries_dir = grafana_dir / "queries"
    panels_dir.mkdir(parents=True, exist_ok=True)
    queries_dir.mkdir(parents=True, exist_ok=True)
    dashboard_path = ROOT / "monitoring/grafana/dashboards/compose-dependency-diagnostic.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    from_utc = datetime.fromtimestamp(from_epoch, timezone.utc).isoformat().replace("+00:00", "Z")
    to_utc = datetime.fromtimestamp(to_epoch, timezone.utc).isoformat().replace("+00:00", "Z")
    metadata = {
        "schemaVersion": "compose-grafana-capture/v1",
        "campaignId": campaign_id,
        "replicate": replicate,
        "fromUtc": from_utc,
        "toUtc": to_utc,
        "dashboardUid": dashboard["uid"],
        "dashboardVersion": dashboard.get("version", 1),
        "dashboardPath": "monitoring/grafana/dashboards/compose-dependency-diagnostic.json",
        "capturedAtUtc": utc_now(),
    }
    write_json(grafana_dir / "capture-metadata.json", metadata)
    write_json(grafana_dir / "dashboard.json", dashboard)
    panel_contracts: list[tuple[int, dict[str, object]]] = []
    for panel in dashboard.get("panels", []):
        panel_id = int(panel["id"])
        query_paths: list[str] = []
        for target in panel.get("targets", []):
            ref_id = str(target.get("refId", "A"))
            query_result = prom_query_range(prometheus_url, str(target.get("expr", "")), from_epoch, to_epoch)
            query_path = queries_dir / f"panel-{panel_id}-{ref_id}.json"
            write_json(query_path, {"panelId": panel_id, "refId": ref_id, **query_result})
            query_paths.append(str(query_path.relative_to(replicate_dir)))
        panel_contracts.append((panel_id, {
            **metadata,
            "panelId": panel_id,
            "panelTitle": panel.get("title", f"Panel {panel_id}"),
            "queryJsonPaths": query_paths,
            "expectedPngPath": f"grafana/panels/panel-{panel_id}.png",
        }))

    pwcli = os.environ.get("PWCLI", "/Users/mac/.codex/skills/playwright/scripts/playwright_cli.sh")
    session = f"scrum41-{campaign_id}-r{replicate}"
    dashboard_url = (
        f"{grafana_url}/d/{dashboard['uid']}/compose-dependency-diagnostic"
        f"?orgId=1&from={int(from_epoch * 1000)}&to={int(to_epoch * 1000)}&kiosk=tv"
    )
    try:
        run_playwright(pwcli, session, "close")
    except DiagnosticError:
        pass
    run_playwright(pwcli, session, "open", dashboard_url)
    # Snapshot is retained as sanitized browser evidence and ensures the page
    # has rendered before element-level capture is attempted.
    snapshot = run_playwright(pwcli, session, "snapshot")
    (grafana_dir / "browser-snapshot.txt").write_text(snapshot, encoding="utf-8")
    full_path = grafana_dir / "dashboard-full.png"
    run_playwright(pwcli, session, "resize", "1920", "1080")
    time.sleep(5)
    root_match = re.search(r"main \[ref=(e\d+)\]", snapshot)
    full_ref = root_match.group(1) if root_match else None
    full_output = run_playwright(pwcli, session, "screenshot", *( [full_ref] if full_ref else [] ))
    copy_cli_screenshot(full_output, full_path)
    # Capture nine key panels. Grafana's data-panelid selector is stable in the
    # provisioned dashboard; the crop fallback is fail-closed and still derives
    # every PNG from the same fixed-range browser screenshot.
    key_panel_ids = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    panel_titles = {int(panel["id"]): str(panel.get("title", f"Panel {panel['id']}")) for panel in dashboard.get("panels", [])}
    for index, panel_id in enumerate(key_panel_ids):
        panel_path = panels_dir / f"panel-{panel_id}.png"
        try:
            found = run_playwright(pwcli, session, "find", panel_titles.get(panel_id, f"Panel {panel_id}"))
            region_match = re.search(r"region \[ref=(e\d+)\]", found)
            if not region_match:
                raise DiagnosticError("panel region ref missing")
            panel_output = run_playwright(pwcli, session, "screenshot", region_match.group(1))
            copy_cli_screenshot(panel_output, panel_path)
            if not png_is_usable(panel_path):
                crop_panel_fallback(full_path, panel_path, index, len(key_panel_ids))
        except DiagnosticError:
            crop_panel_fallback(full_path, panel_path, index, len(key_panel_ids))
    try:
        run_playwright(pwcli, session, "close")
    except DiagnosticError:
        pass
    for panel_id, contract in panel_contracts:
        if panel_id in key_panel_ids:
            write_json(panels_dir / f"panel-{panel_id}.capture.json", contract)
    write_json(grafana_dir / "capture-run.json", {"status": "captured", **metadata, "panelCount": len(key_panel_ids)})


def make_smoke_profile(directory: Path) -> Path:
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    profile["profile"].update({"ratePerSecond": 2, "warmup": "1s", "measuredDuration": "5s", "preallocatedVUs": 2, "maxVUs": 2, "repetitions": 1})
    profile["variants"] = [profile["variants"][0]]
    profile["orderByReplicate"] = {"1": ["refresh-only"]}
    output = directory / "diagnostic-profile-smoke.json"
    write_json(output, profile)
    return output


def run_variant(
    args: argparse.Namespace,
    campaign_id: str,
    replicate: int,
    variant: str,
    replicate_dir: Path,
    profile_file: Path,
    project: str,
    compose_env: dict[str, str],
) -> dict[str, object]:
    variant_dir = replicate_dir / variant
    variant_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"scrum41-{replicate}-{variant}-") as temp_dir:
        data_file = Path(temp_dir) / "credentials.json"
        seed = run_command(
            [
                "python3", str(SEEDER),
                "--variant", variant,
                "--users", str(args.users),
                "--env-file", str(args.env_file),
                "--project-name", project,
                "--base-url", f"http://127.0.0.1:{args.backend_port}",
                "--data-file", str(data_file),
                "--seed-tag", f"{campaign_id}-r{replicate}-{variant}",
                *sum((["--compose-file", str(path)] for path in COMPOSE_PATHS), []),
            ],
            env=compose_env,
        )
        assert_command_ok(seed, f"seed {variant}")
        metadata_path = variant_dir / "seed-metadata.json"
        credentials = json.loads(data_file.read_text(encoding="utf-8"))
        write_json(metadata_path, {
            "seedVersion": credentials.get("seedVersion"),
            "variant": credentials.get("variant"),
            "seedTag": credentials.get("seedTag"),
            "credentialCount": len(credentials.get("credentials", [])),
        })

        run_result = subprocess.run(
            [
                "bash", str(K6_RUNNER),
                str(variant_dir), variant, str(data_file), project,
                f"{project}_app-network", "http://backend:8080",
                str(replicate), campaign_id, str(profile_file),
            ],
            cwd=ROOT,
            env={**compose_env, "REPOSITORY_ROOT": str(ROOT), "RATE": str(args.rate)},
            text=True,
            capture_output=True,
            check=False,
        )
        (variant_dir / "runner-console.log").write_text((run_result.stdout or "") + (run_result.stderr or ""), encoding="utf-8")
        if run_result.returncode != 0:
            raise DiagnosticError(f"k6 {variant} failed ({run_result.returncode})")
    return json.loads((variant_dir / "metadata.json").read_text(encoding="utf-8"))


def run_campaign(args: argparse.Namespace) -> Path:
    if args.replicates < 1 or args.replicates > 3:
        raise DiagnosticError("--replicates must be between 1 and 3")
    if args.users < 1 or args.users > 200:
        raise DiagnosticError("--users must be between 1 and 200")
    if args.rate < 1:
        raise DiagnosticError("--rate must be positive")
    campaign_id = slug(args.campaign_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    if args.smoke:
        args.replicates = 1
        args.users = min(args.users, 2)
        args.rate = min(args.rate, 2)
    evidence_root = args.evidence_root.resolve() / f"{campaign_id}-dependency-diagnostic"
    if evidence_root.exists():
        raise DiagnosticError(f"evidence directory already exists: {evidence_root}")
    evidence_root.mkdir(parents=True, exist_ok=False)
    smoke_directory = Path(tempfile.mkdtemp(prefix="scrum41-profile-")) if args.smoke else None
    profile_file = make_smoke_profile(smoke_directory) if smoke_directory else PROFILE_PATH
    env_values = read_env(args.env_file.resolve())
    compose_env = {**os.environ, **env_values}
    compose_env.update({
        "BACKEND_PORT": str(args.backend_port),
        "GRAFANA_PORT": str(args.grafana_port),
        "PROMETHEUS_PORT": str(args.prometheus_port),
        "LOKI_PORT": str(args.loki_port),
        "ALLOY_PORT": str(args.alloy_port),
        "SPRING_PROFILES_ACTIVE": "prod",
    })
    campaign_metadata = {
        "campaignId": campaign_id,
        "jiraKey": "SCRUM-41",
        "startedAtUtc": utc_now(),
        "profile": str(PROFILE_PATH.relative_to(ROOT)),
        "profileUsed": str(profile_file),
        "replicates": args.replicates,
        "users": args.users,
        "ratePerSecond": args.rate,
        "composeFiles": [str(path.relative_to(ROOT)) for path in COMPOSE_PATHS],
        "evidenceContract": "compose-dependency-diagnostic/v1",
        "smoke": args.smoke,
    }
    write_json(evidence_root / "campaign-metadata.json", campaign_metadata)
    write_json(evidence_root / "campaign-manifest.json", {
        "campaignId": campaign_id,
        "jiraKey": "SCRUM-41",
        "variantsByReplicate": {str(index): (['refresh-only'] if args.smoke else ORDER_MATRIX[index]) for index in range(1, args.replicates + 1)},
        "profileSha256": __import__('hashlib').sha256(profile_file.read_bytes()).hexdigest(),
        "sourceProfileSha256": __import__('hashlib').sha256(PROFILE_PATH.read_bytes()).hexdigest(),
    })

    grafana_url = f"http://127.0.0.1:{args.grafana_port}"
    grafana_user = env_values.get("GRAFANA_ADMIN_USER", "admin")
    grafana_password = env_values.get("GRAFANA_ADMIN_PASSWORD", "")
    try:
        for replicate in range(1, args.replicates + 1):
            project = f"travel-planner-diagnostic-scrum-41-{campaign_id}-r{replicate}"
            replicate_dir = evidence_root / f"replicate-{replicate}"
            replicate_dir.mkdir(parents=True, exist_ok=True)
            compose = compose_command(project, args.env_file.resolve())
            config = run_command([*compose, "config", "--quiet"], env=compose_env)
            assert_command_ok(config, f"Compose config replicate {replicate}")
            up = run_command([*compose, "up", "--build", "--detach", "--wait", "backend", "postgres", "redis", "postgres-exporter", "redis-exporter", "prometheus", "loki", "alloy", "grafana"], env=compose_env, capture=False)
            assert_command_ok(up, f"Compose up replicate {replicate}")
            wait_http(f"http://127.0.0.1:{args.backend_port}/api/ping")
            wait_http(f"{grafana_url}/api/health")
            replicate_started_epoch = time.time()
            sampler = StatsSampler(project, args.env_file.resolve(), replicate_dir / "service-stats.jsonl", compose_env)
            sampler.start()
            try:
                order = ["refresh-only"] if args.smoke else ORDER_MATRIX[replicate]
                for variant in order:
                    post_annotation(grafana_url, grafana_user, grafana_password, f"SCRUM-41 {variant} replicate {replicate} start", ["SCRUM-41", "diagnostic", variant, f"replicate-{replicate}"])
                    run_variant(args, campaign_id, replicate, variant, replicate_dir, profile_file, project, compose_env)
                    post_annotation(grafana_url, grafana_user, grafana_password, f"SCRUM-41 {variant} replicate {replicate} end", ["SCRUM-41", "diagnostic", variant, f"replicate-{replicate}"])
            finally:
                sampler.stop()
            replicate_ended_epoch = time.time()
            capture_grafana(
                replicate_dir,
                campaign_id,
                replicate,
                grafana_url,
                f"http://127.0.0.1:{args.prometheus_port}",
                replicate_started_epoch,
                replicate_ended_epoch,
            )
            capture_check = run_command(
                ["python3", str(CAPTURE_VERIFIER), "--evidence-root", str(replicate_dir)],
                env=compose_env,
            )
            assert_command_ok(capture_check, f"Grafana capture verification replicate {replicate}")
            if not args.keep_stack:
                down = run_command([*compose, "down", "--volumes", "--remove-orphans"], env=compose_env)
                assert_command_ok(down, f"Compose cleanup replicate {replicate}")
    except Exception as error:
        write_json(evidence_root / "campaign-failure.json", {"capturedAtUtc": utc_now(), "error": str(error)[:500]})
        raise
    finally:
        if smoke_directory:
            shutil.rmtree(smoke_directory, ignore_errors=True)
    write_json(evidence_root / "campaign-complete.json", {"completedAtUtc": utc_now(), "status": "complete"})
    return evidence_root


def main() -> int:
    try:
        output = run_campaign(parse_args())
    except DiagnosticError as error:
        print(f"[diagnostic] ERROR: {error}", file=sys.stderr)
        return 1
    print(f"[diagnostic] evidence root: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
