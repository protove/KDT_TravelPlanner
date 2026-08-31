#!/usr/bin/env bash
# Deliver the exact reviewed load-test source to a private Runner.
#
# The operator runs this coordinator locally after the candidate commit is
# pushed. It creates a temporary shallow clone from the local repository,
# removes its remote, archives only that checked-out commit plus shallow Git
# metadata, uploads the archive to the existing private evidence bucket and
# uses SSM to verify/extract it on the Runner. No GitHub credential, public
# bucket or public Runner endpoint is involved.
set -euo pipefail

REPOSITORY_ROOT=""
RUN_ID=""
REGION=""
S3_BUCKET=""
S3_PREFIX="evidence/aws-load-tests"
RUNNER_ID=""
SOURCE_COMMIT_SHA=""
EVIDENCE_ROOT=""
BOTOCORE_VERSION="1.43.68"
K6_IMAGE=""
MOCK_IMAGE="nginxinc/nginx-unprivileged:1.27.1-alpine3.20-perl@sha256:86b08eb3082f1f796f0ce1ef75a1c356a116fafc5f88754924fba2286fbd0221"
DRY_RUN=0
ARCHIVE_OUTPUT=""

usage() {
  cat <<'USAGE'
usage: bootstrap-load-runner-source.sh [options]

Required:
  --repository-root PATH       Local repository containing the exact commit
  --source-commit SHA          40-character commit to deliver
  --run-id ID                  Run-scoped evidence identifier
  --region REGION
  --runner-id INSTANCE_ID      Private EC2 Runner SSM target
  --s3-bucket NAME             Existing private evidence bucket
  --evidence-root PATH         Local run evidence directory
  --k6-image IMAGE@sha256:...  Digest-pinned k6 image

Optional:
  --s3-prefix PREFIX           Default: evidence/aws-load-tests
  --botocore-version VERSION   Default: 1.43.68
  --mock-image IMAGE@sha256:... Digest-pinned private mock image
  --archive-output PATH        Preserve the generated archive at this path
  --dry-run                    Build/hash the archive but skip S3 and SSM
USAGE
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --repository-root) REPOSITORY_ROOT="$2"; shift 2 ;;
    --source-commit) SOURCE_COMMIT_SHA="$2"; shift 2 ;;
    --run-id) RUN_ID="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --runner-id) RUNNER_ID="$2"; shift 2 ;;
    --s3-bucket) S3_BUCKET="$2"; shift 2 ;;
    --s3-prefix) S3_PREFIX="$2"; shift 2 ;;
    --evidence-root) EVIDENCE_ROOT="$2"; shift 2 ;;
    --botocore-version) BOTOCORE_VERSION="$2"; shift 2 ;;
    --k6-image) K6_IMAGE="$2"; shift 2 ;;
    --mock-image) MOCK_IMAGE="$2"; shift 2 ;;
    --archive-output) ARCHIVE_OUTPUT="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

REPOSITORY_ROOT="${REPOSITORY_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || true)}"
EVIDENCE_ROOT="${EVIDENCE_ROOT:-$REPOSITORY_ROOT/evidence/aws-load-tests/$RUN_ID}"
for required in REPOSITORY_ROOT SOURCE_COMMIT_SHA RUN_ID REGION EVIDENCE_ROOT K6_IMAGE; do
  if [[ -z "${!required}" ]]; then
    echo "--${required,,} is required" >&2
    exit 2
  fi
done
if [[ "$DRY_RUN" != "1" ]]; then
  for required in RUNNER_ID S3_BUCKET; do
    if [[ -z "${!required}" ]]; then
      echo "--${required,,} is required unless --dry-run is used" >&2
      exit 2
    fi
  done
fi

if [[ ! -d "$REPOSITORY_ROOT/.git" && ! -f "$REPOSITORY_ROOT/.git" ]]; then
  echo "repository root is not a Git worktree" >&2
  exit 2
fi
if [[ ! "$SOURCE_COMMIT_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "--source-commit must be an exact lowercase 40-character SHA" >&2
  exit 2
fi
if [[ ! "$RUN_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]]; then
  echo "--run-id contains unsupported characters" >&2
  exit 2
fi
if [[ ! "$RUNNER_ID" =~ ^$|^i-[0-9a-f]{8,32}$ ]]; then
  echo "--runner-id must be an EC2 instance ID" >&2
  exit 2
fi
if [[ ! "$S3_PREFIX" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*[A-Za-z0-9]$ || "$S3_PREFIX" == *..* ]]; then
  echo "--s3-prefix contains an unsupported path" >&2
  exit 2
fi
if [[ ! "$K6_IMAGE" =~ ^grafana/k6:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}$ ]]; then
  echo "--k6-image must be a digest-pinned grafana/k6 image" >&2
  exit 2
fi
if [[ ! "$MOCK_IMAGE" =~ ^nginxinc/nginx-unprivileged:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}$ ]]; then
  echo "--mock-image must be a digest-pinned nginxinc/nginx-unprivileged image" >&2
  exit 2
fi
if [[ ! "$BOTOCORE_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "--botocore-version must be a pinned semantic version" >&2
  exit 2
fi

mkdir -p "$EVIDENCE_ROOT/aws"
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/scrum80-runner-source.XXXXXX")"
cleanup() { rm -rf -- "$work_dir"; }
trap cleanup EXIT
clone_dir="$work_dir/source"
archive_tmp="$work_dir/source-${SOURCE_COMMIT_SHA}.tar.gz"

git -C "$REPOSITORY_ROOT" cat-file -e "$SOURCE_COMMIT_SHA^{commit}" 2>/dev/null || {
  echo "source commit is not present in the local repository" >&2
  exit 1
}
git clone --quiet --no-checkout --depth 1 "file://$REPOSITORY_ROOT" "$clone_dir"
git -C "$clone_dir" fetch --quiet --depth 1 origin "$SOURCE_COMMIT_SHA"
git -C "$clone_dir" checkout --quiet --detach "$SOURCE_COMMIT_SHA"
actual_source_sha="$(git -C "$clone_dir" rev-parse HEAD)"
[[ "$actual_source_sha" == "$SOURCE_COMMIT_SHA" ]] || { echo "temporary clone SHA mismatch" >&2; exit 1; }
[[ "$(git -C "$clone_dir" rev-parse --is-shallow-repository)" == "true" ]] || { echo "source clone is not shallow" >&2; exit 1; }
git -C "$clone_dir" remote remove origin
[[ -z "$(git -C "$clone_dir" remote)" ]] || { echo "source clone remote removal failed" >&2; exit 1; }
[[ -z "$(git -C "$clone_dir" status --porcelain --untracked-files=all)" ]] || { echo "temporary source clone is not clean" >&2; exit 1; }
tree_sha="$(git -C "$clone_dir" rev-parse 'HEAD^{tree}')"

# The clone has no ignored working-tree content. Keeping .git is intentional:
# the Runner's existing source-lineage checks use git rev-parse HEAD.
tar -czf "$archive_tmp" -C "$clone_dir" .
archive_sha256="$(sha256sum "$archive_tmp" | awk '{print $1}')"
archive_size="$(python3 - "$archive_tmp" <<'PY'
import os
import sys
print(os.path.getsize(sys.argv[1]))
PY
)"
if [[ -n "$ARCHIVE_OUTPUT" ]]; then
  mkdir -p "$(dirname "$ARCHIVE_OUTPUT")"
  cp "$archive_tmp" "$ARCHIVE_OUTPUT"
  archive_path="$ARCHIVE_OUTPUT"
else
  archive_path="$archive_tmp"
fi

s3_key="${S3_PREFIX%/}/${RUN_ID}/bootstrap/source-${SOURCE_COMMIT_SHA}.tar.gz"
readiness_key="${S3_PREFIX%/}/${RUN_ID}/bootstrap/runner-readiness.json"
archive_metadata="$EVIDENCE_ROOT/aws/runner-source-bootstrap.json"

if [[ "$DRY_RUN" == "1" ]]; then
  python3 - "$archive_metadata" "$RUN_ID" "$SOURCE_COMMIT_SHA" "$tree_sha" "$archive_path" "$archive_sha256" "$archive_size" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

output, run_id, source_sha, tree_sha, archive, digest, size = sys.argv[1:]
Path(output).write_text(json.dumps({
    "schemaVersion": "scrum80-runner-source-bootstrap/v1",
    "status": "dry-run",
    "runId": run_id,
    "sourceCommitSha": source_sha,
    "sourceTreeSha": tree_sha,
    "archivePath": archive,
    "archiveSha256": digest,
    "archiveSizeBytes": int(size),
    "remoteRemoved": True,
    "shallowClone": True,
    "trackedOnly": True,
    "recordedAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  chmod 0600 "$archive_metadata"
  echo "[runner-bootstrap] dry-run archive=$archive_path sha256=$archive_sha256 size=$archive_size"
  exit 0
fi

aws s3api put-object --bucket "$S3_BUCKET" --key "$s3_key" --body "$archive_path" \
  --server-side-encryption AES256 \
  --metadata "source-commit-sha=$SOURCE_COMMIT_SHA,source-tree-sha=$tree_sha,archive-sha256=$archive_sha256,archive-size-bytes=$archive_size" \
  --region "$REGION" --output json >/dev/null
head_json="$(aws s3api head-object --bucket "$S3_BUCKET" --key "$s3_key" --region "$REGION" --output json)"
python3 - "$head_json" "$archive_sha256" "$archive_size" "$SOURCE_COMMIT_SHA" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
expected_sha, expected_size, expected_source = sys.argv[2:]
metadata = payload.get("Metadata") or {}
if int(payload.get("ContentLength", -1)) != int(expected_size):
    raise SystemExit("S3 source archive size read-back mismatch")
if metadata.get("archive-sha256") != expected_sha or metadata.get("source-commit-sha") != expected_source:
    raise SystemExit("S3 source archive metadata read-back mismatch")
PY

python3 - "$archive_metadata" "$RUN_ID" "$SOURCE_COMMIT_SHA" "$tree_sha" "$s3_key" "$archive_sha256" "$archive_size" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

output, run_id, source_sha, tree_sha, key, digest, size = sys.argv[1:]
Path(output).write_text(json.dumps({
    "schemaVersion": "scrum80-runner-source-bootstrap/v1",
    "status": "archive-uploaded",
    "runId": run_id,
    "sourceCommitSha": source_sha,
    "sourceTreeSha": tree_sha,
    "s3Key": key,
    "archiveSha256": digest,
    "archiveSizeBytes": int(size),
    "s3HeadReadBack": True,
    "recordedAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
chmod 0600 "$archive_metadata"

build_ssm_command() {
  python3 - "$REGION" "$S3_BUCKET" "$s3_key" "$readiness_key" "$SOURCE_COMMIT_SHA" "$tree_sha" \
    "$archive_sha256" "$archive_size" "$RUN_ID" "$BOTOCORE_VERSION" "$K6_IMAGE" "$MOCK_IMAGE" <<'PY'
import shlex
import sys

(region, bucket, archive_key, readiness_key, source_sha, tree_sha, archive_sha,
 archive_size, run_id, botocore_version, k6_image, mock_image) = sys.argv[1:]
q = shlex.quote
base = "/var/lib/travel-planner/load-test-evidence"
lines = [
    "set -euo pipefail",
    f"export AWS_DEFAULT_REGION={q(region)}",
    f"RUN_ID={q(run_id)}",
    f"EXPECTED_SOURCE_SHA={q(source_sha)}",
    f"EXPECTED_TREE_SHA={q(tree_sha)}",
    f"EXPECTED_ARCHIVE_SHA={q(archive_sha)}",
    f"EXPECTED_ARCHIVE_SIZE={q(archive_size)}",
    f"ARCHIVE_BUCKET={q(bucket)}",
    f"ARCHIVE_KEY={q(archive_key)}",
    f"READINESS_KEY={q(readiness_key)}",
    f"K6_IMAGE={q(k6_image)}",
    f"MOCK_IMAGE={q(mock_image)}",
    f"BOTOCORE_VERSION={q(botocore_version)}",
    f"BASE_ROOT={q(base)}",
    'BASE_RECEIPT="$BASE_ROOT/base-ready.json"',
    'test -s "$BASE_RECEIPT"',
    "command -v aws >/dev/null 2>&1",
    "command -v docker >/dev/null 2>&1",
    'python3 -c \'import json,sys; p=json.load(open(sys.argv[1])); assert p.get("status")=="base-ready" and p.get("dockerActive") is True\' "$BASE_RECEIPT"',
    'docker info >/dev/null 2>&1',
    'ARCHIVE_TMP="$BASE_ROOT/.source-${RUN_ID}.tar.gz"',
    'aws s3api get-object --bucket "$ARCHIVE_BUCKET" --key "$ARCHIVE_KEY" "$ARCHIVE_TMP" --region "$AWS_DEFAULT_REGION" --output json >/dev/null',
    'ACTUAL_ARCHIVE_SIZE="$(python3 -c \'import os,sys; print(os.path.getsize(sys.argv[1]))\' "$ARCHIVE_TMP")"',
    'ACTUAL_ARCHIVE_SHA="$(sha256sum "$ARCHIVE_TMP" | awk \'{print $1}\')"',
    'test "$ACTUAL_ARCHIVE_SIZE" = "$EXPECTED_ARCHIVE_SIZE"',
    'test "$ACTUAL_ARCHIVE_SHA" = "$EXPECTED_ARCHIVE_SHA"',
    'EXTRACT_TMP="/opt/.travel-planner-${RUN_ID}"',
    'rm -rf -- "$EXTRACT_TMP"',
    'install -d -m 0755 "$EXTRACT_TMP"',
    'tar --extract --gzip --file "$ARCHIVE_TMP" --directory "$EXTRACT_TMP" --no-same-owner --no-overwrite-dir',
    'test "$(git -C "$EXTRACT_TMP" rev-parse HEAD)" = "$EXPECTED_SOURCE_SHA"',
    'test "$(git -C "$EXTRACT_TMP" rev-parse \'HEAD^{tree}\')" = "$EXPECTED_TREE_SHA"',
    'test "$(git -C "$EXTRACT_TMP" rev-parse --is-shallow-repository)" = true',
    'test -z "$(git -C "$EXTRACT_TMP" remote)"',
    'test -z "$(git -C "$EXTRACT_TMP" status --porcelain --untracked-files=all)"',
    'OLD_SOURCE="/opt/travel-planner.previous-${RUN_ID}"',
    'rm -rf -- "$OLD_SOURCE"',
    'if [[ -e /opt/travel-planner ]]; then mv /opt/travel-planner "$OLD_SOURCE"; fi',
    'mv "$EXTRACT_TMP" /opt/travel-planner',
    'rm -rf -- "$OLD_SOURCE" "$ARCHIVE_TMP"',
    'python3 -m pip install --no-cache-dir --disable-pip-version-check "botocore==${BOTOCORE_VERSION}"',
    'docker pull "$K6_IMAGE"',
    'docker pull "$MOCK_IMAGE"',
    'MOCK_ROOT=/opt/travel-planner/load-tests/mocks/google-api',
    'test -s "$MOCK_ROOT/nginx.conf"',
    'test -s "$MOCK_ROOT/responses/places-search.json"',
    'test -s "$MOCK_ROOT/responses/places-nearby.json"',
    'test -s "$MOCK_ROOT/responses/place-detail.json"',
    'test -s "$MOCK_ROOT/responses/routes-compute.json"',
    'install -d -m 0755 "$MOCK_ROOT/responses" /var/lib/travel-planner/google-api-mock-logs',
    'chown 101:101 /var/lib/travel-planner/google-api-mock-logs',
    'docker rm -f travel-planner-google-api-mock >/dev/null 2>&1 || true',
    'docker run -d --name travel-planner-google-api-mock --restart unless-stopped --platform linux/amd64 --read-only --cap-drop ALL --security-opt no-new-privileges --cpus 1 --memory 256m --pids-limit 64 --tmpfs /tmp:rw,noexec,nosuid,size=16m -p 8080:8080 -v "$MOCK_ROOT/nginx.conf:/etc/nginx/nginx.conf:ro" -v "$MOCK_ROOT/responses:/usr/share/nginx/html/responses:ro" -v /var/lib/travel-planner/google-api-mock-logs:/var/log/nginx "$MOCK_IMAGE" nginx -g "daemon off;"',
    'for attempt in $(seq 1 30); do if curl --fail --silent --show-error --max-time 2 http://127.0.0.1:8080/healthz > "$BASE_ROOT/mock-health.json"; then break; fi; if [[ "$attempt" == 30 ]]; then exit 1; fi; sleep 2; done',
    'python3 - "$BASE_ROOT/mock-health.json" <<\'PYHEALTH\'\nimport json\nimport sys\npayload = json.load(open(sys.argv[1]))\nif payload.get("status") != "ok":\n    raise SystemExit("mock health body contract failed")\nPYHEALTH',
    'for route in "/v1/places:searchText" "/v1/places:searchNearby" "/v1/places/loadtest-place" "/directions/v2:computeRoutes"; do curl --fail --silent --show-error --max-time 3 "http://127.0.0.1:8080${route}" >/dev/null; done',
    'K6_IMAGE_ID="$(docker image inspect --format "{{.Id}}" "$K6_IMAGE")"',
    'MOCK_IMAGE_ID="$(docker image inspect --format "{{.Id}}" "$MOCK_IMAGE")"',
    'BASE_RECEIPT_SHA="$(sha256sum "$BASE_RECEIPT" | awk "{print \\$1}")"',
    'RECEIPT_TMP="$BASE_ROOT/.runner-readiness-${RUN_ID}.json.tmp"',
]
lines.append('''python3 - "$RECEIPT_TMP" "$RUN_ID" "$EXPECTED_SOURCE_SHA" "$EXPECTED_TREE_SHA" "$EXPECTED_ARCHIVE_SHA" "$EXPECTED_ARCHIVE_SIZE" "$BOTOCORE_VERSION" "$K6_IMAGE" "$K6_IMAGE_ID" "$MOCK_IMAGE" "$MOCK_IMAGE_ID" "$BASE_RECEIPT_SHA" <<'PYRECEIPT'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

(output, run_id, source_sha, tree_sha, archive_sha, archive_size, botocore_version,
 k6_image, k6_id, mock_image, mock_id, base_sha) = sys.argv[1:]
now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
Path(output).write_text(json.dumps({
    "schemaVersion": "scrum80-runner-readiness/v1",
    "status": "ready",
    "runId": run_id,
    "sourceCommitSha": source_sha,
    "sourceTreeSha": tree_sha,
    "archiveSha256": archive_sha,
    "archiveSizeBytes": int(archive_size),
    "baseReceiptSha256": base_sha,
    "botocoreVersion": botocore_version,
    "k6ImageReference": k6_image,
    "k6ImageId": k6_id,
    "mockImageReference": mock_image,
    "mockImageId": mock_id,
    "mock": {"containerName": "travel-planner-google-api-mock", "healthStatus": "ok", "contractRoutesVerified": 4},
    "recordedAtUtc": now,
}, sort_keys=True) + "\\n", encoding="utf-8")
PYRECEIPT''')
lines.extend([
    'chmod 0600 "$RECEIPT_TMP"',
    'mv -f "$RECEIPT_TMP" "$BASE_ROOT/runner-readiness.json"',
    'aws s3api put-object --bucket "$ARCHIVE_BUCKET" --key "$READINESS_KEY" --body "$BASE_ROOT/runner-readiness.json" --server-side-encryption AES256 --metadata "source-commit-sha=$EXPECTED_SOURCE_SHA,archive-sha256=$EXPECTED_ARCHIVE_SHA,archive-size-bytes=$EXPECTED_ARCHIVE_SIZE" --region "$AWS_DEFAULT_REGION" --output json >/dev/null',
    'printf "%s\\n" __SCRUM80_RUNNER_BOOTSTRAP_BEGIN__',
    'cat "$BASE_ROOT/runner-readiness.json"',
    'printf "%s\\n" __SCRUM80_RUNNER_BOOTSTRAP_END__',
])
print("\n".join(lines))
PY
}

ssm_command="$(build_ssm_command)"
ssm_parameters="$(jq -cn --arg command "$ssm_command" '{commands:[$command]}')"
invocation_json=""
last_status=""
last_error_kind=""
retry_count=0

is_transient_failure() {
  python3 - "$1" <<'PY'
import json
import re
import sys

try:
    payload = json.loads(sys.argv[1])
except json.JSONDecodeError:
    raise SystemExit(1)
text = " ".join(str(payload.get(key, "")) for key in ("StandardErrorContent", "StandardOutputContent")).lower()
patterns = (
    r"could not resolve", r"temporary failure", r"connection timed out", r"timed out",
    r"i/o timeout", r"network is unreachable", r"connection reset", r"service unavailable",
    r"too many requests", r"context deadline exceeded", r"tls handshake timeout",
    r"registry.*(503|500)",
)
raise SystemExit(0 if any(re.search(pattern, text) for pattern in patterns) else 1)
PY
}

invoke_ssm_once() {
  local command_json command_id status
  command_json="$(aws ssm send-command --instance-ids "$RUNNER_ID" --document-name AWS-RunShellScript \
    --comment "SCRUM-80 private Runner source bootstrap $RUN_ID" --parameters "$ssm_parameters" \
    --region "$REGION" --output json)"
  command_id="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["Command"]["CommandId"])' <<<"$command_json")"
  [[ "$command_id" =~ ^[A-Za-z0-9-]{36}$ ]] || { echo "SSM returned an invalid command id" >&2; return 1; }
  invocation_json=''
  status=''
  for _ in $(seq 1 90); do
    invocation_json="$(aws ssm get-command-invocation --command-id "$command_id" --instance-id "$RUNNER_ID" --region "$REGION" --output json)"
    status="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("Status", ""))' <<<"$invocation_json")"
    case "$status" in
      Success) last_status="$status"; return 0 ;;
      Failed|Cancelled|TimedOut|Cancelling) last_status="$status"; return 1 ;;
    esac
    sleep 5
  done
  last_status="TimedOut"
  return 1
}

for attempt in 0 1; do
  if invoke_ssm_once; then
    break
  fi
  last_error_kind="deterministic"
  if is_transient_failure "$invocation_json"; then last_error_kind="transient"; fi
  if [[ "$attempt" -eq 0 && "$last_error_kind" == "transient" ]]; then
    retry_count=1
    echo "[runner-bootstrap] one same-byte transient retry is allowed; retrying SSM command" >&2
    continue
  fi
  python3 - "$archive_metadata" "$RUN_ID" "$SOURCE_COMMIT_SHA" "$s3_key" "$archive_sha256" "$archive_size" "$readiness_key" "$last_status" "$last_error_kind" "$retry_count" "$invocation_json" <<'PY'
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

(output, run_id, source_sha, archive_key, archive_sha, archive_size, readiness_key,
 status, error_kind, retries, invocation_raw) = sys.argv[1:]
try:
    invocation = json.loads(invocation_raw)
except json.JSONDecodeError:
    invocation = {}
def digest(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()
Path(output).write_text(json.dumps({
    "schemaVersion": "scrum80-runner-source-bootstrap/v1",
    "status": "ssm-failed",
    "runId": run_id,
    "sourceCommitSha": source_sha,
    "s3Key": archive_key,
    "archiveSha256": archive_sha,
    "archiveSizeBytes": int(archive_size),
    "readinessKey": readiness_key,
    "ssmStatus": status,
    "failureKind": error_kind,
    "retryCount": int(retries),
    "stdoutSha256": digest(invocation.get("StandardOutputContent", "")),
    "stderrSha256": digest(invocation.get("StandardErrorContent", "")),
    "rawOutputStored": False,
    "recordedAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  echo "Runner staged bootstrap failed ($last_status/$last_error_kind); raw output was not stored" >&2
  exit 1
done

python3 - "$invocation_json" "$archive_metadata" "$RUN_ID" "$SOURCE_COMMIT_SHA" "$s3_key" "$readiness_key" "$archive_sha256" "$archive_size" "$retry_count" <<'PY'
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

(invocation_raw, output, run_id, source_sha, archive_key, readiness_key,
 archive_sha, archive_size, retries) = sys.argv[1:]
invocation = json.loads(invocation_raw)
stdout = str(invocation.get("StandardOutputContent", ""))
match = re.search(r"__SCRUM80_RUNNER_BOOTSTRAP_BEGIN__\s*(.*?)\s*__SCRUM80_RUNNER_BOOTSTRAP_END__", stdout, re.DOTALL)
if not match:
    raise SystemExit("Runner readiness markers are missing")
receipt = json.loads(match.group(1))
if receipt.get("status") != "ready" or receipt.get("runId") != run_id:
    raise SystemExit("Runner readiness receipt is not ready for this run")
if receipt.get("sourceCommitSha") != source_sha or receipt.get("archiveSha256") != archive_sha or int(receipt.get("archiveSizeBytes", -1)) != int(archive_size):
    raise SystemExit("Runner readiness receipt does not match the uploaded source archive")
Path(output).write_text(json.dumps({
    "schemaVersion": "scrum80-runner-source-bootstrap/v1",
    "status": "ready",
    "runId": run_id,
    "sourceCommitSha": source_sha,
    "s3Key": archive_key,
    "readinessKey": readiness_key,
    "archiveSha256": archive_sha,
    "archiveSizeBytes": int(archive_size),
    "readiness": receipt,
    "ssmStatus": invocation.get("Status"),
    "retryCount": int(retries),
    "stdoutSha256": hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
    "stderrSha256": hashlib.sha256(str(invocation.get("StandardErrorContent", "")).encode("utf-8")).hexdigest(),
    "rawOutputStored": False,
    "recordedAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
chmod 0600 "$archive_metadata"
readiness_head="$(aws s3api head-object --bucket "$S3_BUCKET" --key "$readiness_key" --region "$REGION" --output json)"
python3 - "$readiness_head" "$archive_sha256" "$archive_size" "$SOURCE_COMMIT_SHA" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
expected_sha, expected_size, expected_source = sys.argv[2:]
metadata = payload.get("Metadata") or {}
if int(payload.get("ContentLength", -1)) <= 0:
    raise SystemExit("Runner readiness object is empty")
if metadata.get("archive-sha256") != expected_sha or metadata.get("source-commit-sha") != expected_source or metadata.get("archive-size-bytes") != expected_size:
    raise SystemExit("Runner readiness S3 metadata does not match source archive")
PY
python3 - "$archive_metadata" "$readiness_key" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
payload["readinessS3HeadReadBack"] = True
payload["readinessKey"] = sys.argv[2]
path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
echo "[runner-bootstrap] Runner source and full readiness verified: $archive_metadata"
