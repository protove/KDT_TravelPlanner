#!/usr/bin/env bash
set -euo pipefail

# In-place recovery only. The AMI already provides curl-minimal; this helper
# deliberately never runs a package manager and never replaces the Bastion.
umask 077

KUBECTL_VERSION=""
CLUSTER_NAME=""
REGION=""
EXPECTED_ACCOUNT_ID=""
WORK_DIR="/var/tmp/travel-planner-dev-eks-repair"
KUBECONFIG_PATH=""
binary=""
published_sha=""

usage() {
  cat >&2 <<'USAGE'
Usage: repair-dev-eks-bastion.sh --kubectl-version 1.35.6
  --cluster-name <cluster> --region <region> --expected-account-id <12 digits>
  [--work-dir /var/tmp/travel-planner-dev-eks-<run>/repair]
USAGE
}

die() { printf 'stage=bastion-repair status=failed reason=%s\n' "$1" >&2; exit 1; }

cleanup() {
  local exit_status=$?
  [[ -n "${binary:-}" ]] && rm -f -- "$binary"
  [[ -n "${published_sha:-}" ]] && rm -f -- "$published_sha"
  [[ -n "${KUBECONFIG_PATH:-}" ]] && rm -f -- "$KUBECONFIG_PATH"
  [[ -n "${WORK_DIR:-}" && -d "$WORK_DIR/download" && ! -L "$WORK_DIR/download" ]] && rmdir "$WORK_DIR/download" 2>/dev/null || true
  exit "$exit_status"
}
trap cleanup EXIT

while (($#)); do
  case "$1" in
    --kubectl-version) KUBECTL_VERSION="${2:?missing value for --kubectl-version}"; shift 2 ;;
    --cluster-name) CLUSTER_NAME="${2:?missing value for --cluster-name}"; shift 2 ;;
    --region) REGION="${2:?missing value for --region}"; shift 2 ;;
    --expected-account-id) EXPECTED_ACCOUNT_ID="${2:?missing value for --expected-account-id}"; shift 2 ;;
    --work-dir) WORK_DIR="${2:?missing value for --work-dir}"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) usage; die "unknown argument" ;;
  esac
done

[[ "$KUBECTL_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "kubectl version is invalid"
[[ "$KUBECTL_VERSION" == "1.35.6" ]] || die "kubectl version is not the authenticated pinned release"
[[ "$CLUSTER_NAME" =~ ^[a-z0-9][a-z0-9-]{0,99}$ ]] || die "cluster name is invalid"
[[ "$REGION" =~ ^[a-z0-9-]+$ ]] || die "region is invalid"
[[ "$EXPECTED_ACCOUNT_ID" =~ ^[0-9]{12}$ ]] || die "expected account id is invalid"
[[ "$WORK_DIR" == /var/tmp/travel-planner-dev-eks-*/* ]] || die "work directory is outside the private repair prefix"
[[ "$WORK_DIR" != *".."* ]] || die "work directory contains traversal or repeated separators"
[[ "$WORK_DIR" != *"//"* ]] || die "work directory contains traversal or repeated separators"
[[ "$WORK_DIR" != */./* ]] || die "work directory contains traversal or repeated separators"
[[ "$WORK_DIR" != */. ]] || die "work directory contains traversal or repeated separators"

validate_private_path() {
  local path="$1" current component
  current="$(cd /var/tmp && pwd -P)"
  [[ "$path" == /var/tmp/* ]] || die "work directory is outside the private repair prefix"
  while IFS= read -r component; do
    [[ -n "$component" ]] || die "work directory contains an empty path component"
    current="$current/$component"
    [[ ! -L "$current" ]] || die "work directory parent must not be a symlink"
  done < <(printf '%s\n' "${path#/var/tmp/}" | tr '/' '\n')
}

validate_private_path "$WORK_DIR"
[[ ! -L "$WORK_DIR" ]] || die "work directory must not be a symlink"

for command_name in aws curl sha256sum install mktemp jq; do
  command -v "$command_name" >/dev/null 2>&1 || die "required command unavailable: $command_name"
done

if [[ -e "$WORK_DIR" ]]; then
  [[ -d "$WORK_DIR" && ! -L "$WORK_DIR" ]] || die "work directory is not a private directory"
else
  mkdir -p "$WORK_DIR"
fi
[[ ! -L "$WORK_DIR/download" ]] || die "download directory must not be a symlink"
mkdir -p "$WORK_DIR/download"
chmod 0700 "$WORK_DIR" "$WORK_DIR/download"
binary="$WORK_DIR/download/kubectl"
published_sha="$WORK_DIR/download/kubectl.sha256"
KUBECONFIG_PATH="$WORK_DIR/kubeconfig"

curl -fsSL --retry 2 --retry-all-errors -o "$binary" "https://dl.k8s.io/release/v${KUBECTL_VERSION}/bin/linux/amd64/kubectl" || die "pinned kubectl download failed"
curl -fsSL --retry 2 --retry-all-errors -o "$published_sha" "https://dl.k8s.io/release/v${KUBECTL_VERSION}/bin/linux/amd64/kubectl.sha256" || die "kubectl published checksum download failed"
expected_sha="$(awk '{print $1}' "$published_sha")"
[[ "$expected_sha" =~ ^[0-9a-f]{64}$ ]] || die "published kubectl checksum is malformed"
printf '%s  %s\n' "$expected_sha" "$binary" | sha256sum -c - >/dev/null || die "kubectl SHA-256 verification failed"
install -m 0755 "$binary" /usr/local/bin/kubectl || die "kubectl installation failed"

client_json="$(kubectl version --client --output=json 2>/dev/null)" || die "kubectl client version check failed"
jq -e --arg expected "v${KUBECTL_VERSION}" '.clientVersion.gitVersion == $expected' <<<"$client_json" >/dev/null || die "installed kubectl version does not match the pinned release"
caller_account="$(aws sts get-caller-identity --query Account --output text 2>/dev/null)" || die "Bastion AWS identity check failed"
[[ "$caller_account" == "$EXPECTED_ACCOUNT_ID" ]] || die "Bastion AWS account does not match the authorized account"
export KUBECONFIG="$KUBECONFIG_PATH"
aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$REGION" --kubeconfig "$KUBECONFIG_PATH" >/dev/null 2>&1 || die "kubeconfig update failed after kubectl repair"
cluster_version_response=""
if ! cluster_version_response="$(kubectl --kubeconfig "$KUBECONFIG_PATH" get --raw=/version 2>&1)"; then
  printf 'kubectl_raw_version_error=%s\n' "$(tr '\n' ' ' <<<"$cluster_version_response" | cut -c1-400)" >&2
  die "EKS cluster access check failed after kubectl repair"
fi
node_response=""
if ! node_response="$(kubectl --kubeconfig "$KUBECONFIG_PATH" get nodes --no-headers 2>&1)"; then
  printf 'kubectl_nodes_error=%s\n' "$(tr '\n' ' ' <<<"$node_response" | cut -c1-400)" >&2
  die "EKS node access check failed after kubectl repair"
fi
printf 'stage=bastion-repair status=success kubectl_version=%s\n' "$KUBECTL_VERSION"
