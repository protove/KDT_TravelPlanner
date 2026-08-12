"""Shared validation for split AWS load-test source lineage.

The B-01 measurements were produced by one immutable source revision while
the Recovery controller may be executed from a later, reviewed revision.  A
lineage document binds those two revisions without rewriting the original
B-01/D-006 evidence.  This module is deliberately side-effect free; callers
must perform all writes only after :func:`assert_new_output_path` succeeds.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


LINEAGE_SCHEMA = "aws-recovery-source-lineage-v1"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# These are the workload inputs whose contents must remain byte-identical
# between the recorded B-01 measurement revision and the Recovery controller
# revision.  Contract/evidence helpers may evolve; the profile and actual
# scenario/metric flow may not silently change under a no-rerun delta.
WORKLOAD_INPUT_PREFIXES = (
    "load-tests/aws/profiles/",
    "load-tests/k6/aws/scenarios/",
    "load-tests/k6/aws/lib/",
    "load-tests/k6/lib/",
)


class SourceLineageError(ValueError):
    """Raised when a source-lineage or output-boundary contract is invalid."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise SourceLineageError(f"cannot read file for SHA-256: {path}") from error
    return digest.hexdigest()


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SourceLineageError(f"{label} is missing or invalid: {path}") from error
    if not isinstance(payload, dict):
        raise SourceLineageError(f"{label} must be a JSON object: {path}")
    return payload


def require_commit(value: Any, field: str) -> str:
    if not isinstance(value, str) or not COMMIT_RE.fullmatch(value):
        raise SourceLineageError(f"{field} must be a 40-character lowercase commit SHA")
    return value


def require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise SourceLineageError(f"{field} must be a lowercase SHA-256 digest")
    return value


def git_head(repository_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise SourceLineageError("unable to read repository HEAD") from error
    return require_commit(result.stdout.strip(), "repository HEAD")


def assert_clean_controller_worktree(repository_root: Path) -> None:
    """Require committed controller code while allowing generated outputs."""

    try:
        result = subprocess.run(
            ["git", "-C", str(repository_root), "status", "--porcelain=v1", "--untracked-files=all"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise SourceLineageError("unable to inspect controller worktree status") from error
    unexpected = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        path = line[3:] if len(line) >= 4 else line
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path.startswith(("evidence/", "recovery-control/")):
            continue
        unexpected.append(path)
    if unexpected:
        raise SourceLineageError("controller worktree has uncommitted non-output changes: " + ",".join(unexpected))


def changed_paths(repository_root: Path, measurement_sha: str, controller_sha: str) -> list[str]:
    measurement_sha = require_commit(measurement_sha, "measurementSourceCommitSha")
    controller_sha = require_commit(controller_sha, "controllerSourceCommitSha")
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repository_root),
                "diff",
                "--name-only",
                f"{measurement_sha}..{controller_sha}",
                "--",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise SourceLineageError("unable to inspect source revision diff") from error
    return sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})


def workload_input_changes(paths: list[str]) -> list[str]:
    return [
        path
        for path in paths
        if any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in WORKLOAD_INPUT_PREFIXES)
    ]


def _relative_to_root(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise SourceLineageError(f"path is outside repository root: {path}") from error


def load_protected_manifest(path: Path) -> dict[str, Any]:
    payload = read_json(path, "protected evidence manifest")
    if payload.get("schemaVersion") != "aws-preexisting-evidence-protection-v1":
        raise SourceLineageError("protected evidence manifest schemaVersion is invalid")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise SourceLineageError("protected evidence manifest has no files")
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise SourceLineageError("protected evidence manifest contains an invalid path entry")
        if Path(entry["path"]).is_absolute() or ".." in Path(entry["path"]).parts:
            raise SourceLineageError("protected evidence manifest contains an unsafe path")
        require_sha256(entry.get("sha256"), f"protected evidence {entry['path']} sha256")
    return payload


def assert_protected_manifest_unchanged(manifest_path: Path, repository_root: Path) -> None:
    manifest = load_protected_manifest(manifest_path)
    expected_count = manifest.get("fileCount")
    manifest_root = manifest.get("repositoryRoot")
    root = Path(manifest_root).resolve() if isinstance(manifest_root, str) and manifest_root else repository_root.resolve()
    actual = []
    for entry in manifest["files"]:
        relative = entry["path"]
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise SourceLineageError(f"protected evidence file is missing or is a symlink: {relative}")
        digest = sha256_file(path)
        if digest != entry["sha256"]:
            raise SourceLineageError(f"protected evidence SHA-256 changed: {relative}")
        actual.append(relative)
    if expected_count != len(actual):
        raise SourceLineageError("protected evidence file count does not match manifest")


def _ancestor_is_symlink(path: Path, stop: Path) -> bool:
    current = path
    stop = stop.resolve()
    while True:
        if current.is_symlink():
            return True
        if current == stop:
            return False
        if current.parent == current:
            return False
        current = current.parent


def assert_new_output_path(
    output_path: Path,
    *,
    repository_root: Path,
    protected_manifest: Path | None = None,
    allow_existing_directory: bool = False,
) -> Path:
    """Fail closed before writing a new control/run output.

    Existing protected files may not be overwritten.  A new run directory may
    live beside old evidence, but it must not already exist unless the caller
    explicitly allows a directory for a read-only check.
    """

    root = repository_root.resolve()
    candidate = output_path.resolve()
    if _ancestor_is_symlink(output_path, root):
        raise SourceLineageError(f"output path has a symlink ancestor: {output_path}")
    if protected_manifest is not None:
        manifest = load_protected_manifest(protected_manifest)
        manifest_root = manifest.get("repositoryRoot")
        protected_root = Path(manifest_root).resolve() if isinstance(manifest_root, str) and manifest_root else root
        protected_paths = {protected_root / entry["path"] for entry in manifest["files"]}
        if candidate in protected_paths:
            raise SourceLineageError(f"refusing to overwrite protected evidence: {output_path}")
        # A pre-existing directory containing protected files is never a safe
        # target for a new run; callers must choose a fresh Run ID.
        if candidate.is_dir() and any(path == candidate or candidate in path.parents for path in protected_paths):
            raise SourceLineageError(f"output path contains protected evidence: {output_path}")
    if output_path.exists() or output_path.is_symlink():
        if allow_existing_directory and output_path.is_dir() and not output_path.is_symlink():
            return candidate
        raise SourceLineageError(f"output path already exists; use a new path: {output_path}")
    return candidate


def validate_lineage(
    payload: dict[str, Any],
    *,
    repository_root: Path,
    expected_controller_sha: str,
    expected_run_id: str | None = None,
    expected_protected_manifest: Path | None = None,
    expected_inputs: dict[str, str] | None = None,
    require_clean_worktree: bool = False,
) -> dict[str, Any]:
    if payload.get("schemaVersion") != LINEAGE_SCHEMA:
        raise SourceLineageError("source lineage schemaVersion is invalid")
    measurement_sha = require_commit(payload.get("measurementSourceCommitSha"), "measurementSourceCommitSha")
    controller_sha = require_commit(payload.get("controllerSourceCommitSha"), "controllerSourceCommitSha")
    expected_controller_sha = require_commit(expected_controller_sha, "expected controller SHA")
    if controller_sha != expected_controller_sha:
        raise SourceLineageError("controllerSourceCommitSha does not match the executing controller")
    if git_head(repository_root) != controller_sha:
        raise SourceLineageError("repository HEAD does not match controllerSourceCommitSha")
    if require_clean_worktree:
        assert_clean_controller_worktree(repository_root)
    if expected_run_id is not None and payload.get("b01RunId") != expected_run_id:
        raise SourceLineageError("source lineage B-01 runId does not match the freeze record")
    source_diff = payload.get("sourceDiff")
    if not isinstance(source_diff, dict) or source_diff.get("measurementSourceCommitSha") != measurement_sha or source_diff.get("controllerSourceCommitSha") != controller_sha:
        raise SourceLineageError("source lineage sourceDiff binding is invalid")
    changed = source_diff.get("changedFiles")
    if not isinstance(changed, list) or any(not isinstance(path, str) for path in changed):
        raise SourceLineageError("source lineage changedFiles is invalid")
    actual_changed = changed_paths(repository_root, measurement_sha, controller_sha)
    if sorted(changed) != actual_changed:
        raise SourceLineageError("source lineage changedFiles does not match the Git revision diff")
    workload_changes = source_diff.get("workloadInputChanges")
    if workload_changes != [] or workload_input_changes(changed) != []:
        raise SourceLineageError("source lineage permits workload input changes")
    inputs = payload.get("inputs")
    if expected_inputs is not None:
        if not isinstance(inputs, dict):
            raise SourceLineageError("source lineage inputs are missing")
        required_inputs = {
            "b01ProfileSha256",
            "baselineCandidateSha256",
            "d005RateRecordSha256",
            "freezeInputDigest",
        }
        if set(inputs) != required_inputs:
            raise SourceLineageError("source lineage inputs do not match the required D-005/D-006 contract")
        for field in required_inputs:
            actual = require_sha256(inputs.get(field), f"source lineage inputs.{field}")
            expected = require_sha256(expected_inputs.get(field), f"expected inputs.{field}")
            if actual != expected:
                raise SourceLineageError(f"source lineage inputs.{field} does not match the approved input")
    protected_digest = payload.get("protectedEvidenceManifestSha256")
    require_sha256(protected_digest, "protectedEvidenceManifestSha256")
    if expected_protected_manifest is not None:
        if sha256_file(expected_protected_manifest) != protected_digest:
            raise SourceLineageError("source lineage protected manifest digest does not match")
        assert_protected_manifest_unchanged(expected_protected_manifest, repository_root)
    claimed_lineage_sha = payload.get("lineageSha256")
    if claimed_lineage_sha is not None:
        unsigned = dict(payload)
        unsigned.pop("lineageSha256", None)
        if claimed_lineage_sha != digest_json(unsigned):
            raise SourceLineageError("source lineage digest does not match its contents")
    return {
        "measurementSourceCommitSha": measurement_sha,
        "controllerSourceCommitSha": controller_sha,
        "sourceLineageSha256": digest_json(payload),
        "protectedEvidenceManifestSha256": protected_digest,
    }


def build_lineage(
    *,
    repository_root: Path,
    b01_run_id: str,
    measurement_sha: str,
    controller_sha: str,
    d005: dict[str, Any],
    freeze: dict[str, Any],
    b01_profile_sha: str,
    baseline_candidate_sha: str,
    d005_rate_sha: str,
    freeze_input_digest: str,
    protected_manifest: Path,
) -> dict[str, Any]:
    measurement_sha = require_commit(measurement_sha, "measurementSourceCommitSha")
    controller_sha = require_commit(controller_sha, "controllerSourceCommitSha")
    if git_head(repository_root) != controller_sha:
        raise SourceLineageError("repository HEAD does not match controllerSourceCommitSha")
    if d005.get("runId") != b01_run_id or freeze.get("runId") != b01_run_id:
        raise SourceLineageError("B-01 runId is not consistent across D-005 and D-006")
    if d005.get("sourceCommitSha") != measurement_sha:
        raise SourceLineageError("D-005 sourceCommitSha does not match measurementSourceCommitSha")
    if freeze.get("sloVersion") != "v1.0-frozen":
        raise SourceLineageError("D-006 freeze is not v1.0-frozen")
    if d005.get("profileSha256") != b01_profile_sha:
        raise SourceLineageError("D-005 profile digest does not match B-01 profile")
    if d005.get("baselineCandidateSha256") != baseline_candidate_sha:
        raise SourceLineageError("D-005 baseline candidate digest does not match")
    require_sha256(b01_profile_sha, "b01ProfileSha256")
    require_sha256(baseline_candidate_sha, "baselineCandidateSha256")
    require_sha256(d005_rate_sha, "d005RateRecordSha256")
    require_sha256(freeze_input_digest, "freezeInputDigest")
    assert_protected_manifest_unchanged(protected_manifest, repository_root)
    changed = changed_paths(repository_root, measurement_sha, controller_sha)
    workload_changes = workload_input_changes(changed)
    if workload_changes:
        raise SourceLineageError("workload input files changed; no-rerun lineage is not valid: " + ",".join(workload_changes))
    payload = {
        "schemaVersion": LINEAGE_SCHEMA,
        "b01RunId": b01_run_id,
        "measurementSourceCommitSha": measurement_sha,
        "controllerSourceCommitSha": controller_sha,
        "sourceDiff": {
            "measurementSourceCommitSha": measurement_sha,
            "controllerSourceCommitSha": controller_sha,
            "changedFiles": changed,
            "workloadInputPathsChecked": list(WORKLOAD_INPUT_PREFIXES),
            "workloadInputChanges": workload_changes,
            "classification": "controller-contract-and-evidence-only",
        },
        "inputs": {
            "b01ProfileSha256": b01_profile_sha,
            "baselineCandidateSha256": baseline_candidate_sha,
            "d005RateRecordSha256": d005_rate_sha,
            "freezeInputDigest": freeze_input_digest,
        },
        "protectedEvidenceManifestSha256": sha256_file(protected_manifest),
        "compatibility": {
            "b01SeedBaselineSpikeCleanupRerunRequired": False,
            "existingEvidenceRewriteRequired": False,
        },
    }
    payload["lineageSha256"] = digest_json(payload)
    return payload
