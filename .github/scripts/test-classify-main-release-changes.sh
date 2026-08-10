#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
classifier="${script_dir}/classify-main-release-changes.sh"
test_repo="$(mktemp -d)"
trap 'rm -rf "${test_repo}"' EXIT

git -C "${test_repo}" init -q
git -C "${test_repo}" config user.email "ci-test@example.invalid"
git -C "${test_repo}" config user.name "CI Test"

write_file() {
  local path="$1"
  mkdir -p "${test_repo}/$(dirname "${path}")"
  printf 'fixture\n' > "${test_repo}/${path}"
}

write_file "frontend/src/page.tsx"
write_file "backend/src/Main.kt"
git -C "${test_repo}" add -- frontend/src/page.tsx backend/src/Main.kt
git -C "${test_repo}" commit -qm "baseline"
base_commit="$(git -C "${test_repo}" rev-parse HEAD)"

reset_case() {
  git -C "${test_repo}" reset --hard -q "${base_commit}"
  git -C "${test_repo}" clean -fdq
}

commit_paths() {
  local message="$1"
  shift
  local paths=("$@")

  for path in "${paths[@]}"; do
    write_file "${path}"
  done
  git -C "${test_repo}" add -- "${paths[@]}"
  git -C "${test_repo}" commit -qm "${message}"
}

new_path_case() {
  local message="$1"
  shift
  reset_case
  commit_paths "${message}" "$@"
  (
    cd "${test_repo}"
    "${classifier}" "${base_commit}" "$(git rev-parse HEAD)"
  )
}

assert_flags() {
  local case_name="$1"
  local output="$2"
  shift 2

  for expected in "$@"; do
    if ! grep -Fxq "${expected}" <<<"${output}"; then
      echo "${case_name}: missing ${expected}" >&2
      echo "Actual output:" >&2
      printf '%s\n' "${output}" >&2
      exit 1
    fi
  done
}

assert_flags "frontend" "$(new_path_case "frontend" frontend/src/new.tsx)" \
  'run_frontend_verify=true' 'run_backend_verify=false' 'run_compose_verify=false' \
  'deploy_frontend=true' 'publish_backend=false' 'classification_error=false'

assert_flags "backend" "$(new_path_case "backend" backend/src/New.kt)" \
  'run_frontend_verify=false' 'run_backend_verify=true' 'run_compose_verify=true' \
  'deploy_frontend=false' 'publish_backend=true' 'classification_error=false'

assert_flags "frontend-and-backend" "$(new_path_case "frontend-and-backend" frontend/src/new.tsx backend/src/New.kt)" \
  'run_frontend_verify=true' 'run_backend_verify=true' 'run_compose_verify=true' \
  'deploy_frontend=true' 'publish_backend=true' 'classification_error=false'

assert_flags "compose" "$(new_path_case "compose" compose.yml)" \
  'run_frontend_verify=false' 'run_backend_verify=false' 'run_compose_verify=true' \
  'deploy_frontend=false' 'publish_backend=false' 'classification_error=false'

assert_flags "monitoring" "$(new_path_case "monitoring" monitoring/prometheus/prometheus.yml)" \
  'run_frontend_verify=false' 'run_backend_verify=false' 'run_compose_verify=false' \
  'deploy_frontend=false' 'publish_backend=false' 'classification_error=false'

assert_flags "terraform" "$(new_path_case "terraform" infra/modules/backend_service/main.tf)" \
  'run_frontend_verify=false' 'run_backend_verify=false' 'run_compose_verify=false' \
  'deploy_frontend=false' 'publish_backend=false' 'classification_error=false'

assert_flags "release-workflow" "$(new_path_case "release-workflow" .github/workflows/release-main-dev.yml)" \
  'run_frontend_verify=true' 'run_backend_verify=true' 'run_compose_verify=true' \
  'deploy_frontend=false' 'publish_backend=false' 'classification_error=false'

assert_flags "frontend-deploy-workflow" "$(new_path_case "frontend-deploy-workflow" .github/workflows/frontend-deploy-dev.yml)" \
  'run_frontend_verify=true' 'run_backend_verify=false' 'run_compose_verify=false' \
  'deploy_frontend=true' 'publish_backend=false' 'classification_error=false'

assert_flags "backend-test-workflow" "$(new_path_case "backend-test-workflow" .github/workflows/backend-test.yml)" \
  'run_frontend_verify=false' 'run_backend_verify=true' 'run_compose_verify=false' \
  'deploy_frontend=false' 'publish_backend=false' 'classification_error=false'

assert_flags "backend-deploy-workflow" "$(new_path_case "backend-deploy-workflow" .github/workflows/backend-deploy-dev.yml)" \
  'run_frontend_verify=false' 'run_backend_verify=true' 'run_compose_verify=true' \
  'deploy_frontend=false' 'publish_backend=true' 'classification_error=false'

assert_flags "document" "$(new_path_case "document" reference/strategy/ci-cd/example.md)" \
  'run_frontend_verify=false' 'run_backend_verify=false' 'run_compose_verify=false' \
  'deploy_frontend=false' 'publish_backend=false' 'classification_error=false'

assert_flags "ignored-document" "$(new_path_case "ignored-document" .gitignore)" \
  'run_frontend_verify=false' 'run_backend_verify=false' 'run_compose_verify=false' \
  'deploy_frontend=false' 'publish_backend=false' 'classification_error=false'

assert_flags "unknown" "$(new_path_case "unknown" new-runtime-contract.txt)" \
  'run_frontend_verify=true' 'run_backend_verify=true' 'run_compose_verify=true' \
  'deploy_frontend=false' 'publish_backend=false' 'classification_error=true'

reset_case
git -C "${test_repo}" rm -q frontend/src/page.tsx
git -C "${test_repo}" commit -qm "delete frontend file"
assert_flags "frontend-delete" "$(cd "${test_repo}" && "${classifier}" "${base_commit}" "$(git rev-parse HEAD)")" \
  'run_frontend_verify=true' 'run_backend_verify=false' 'run_compose_verify=false' \
  'deploy_frontend=true' 'publish_backend=false' 'classification_error=false'

reset_case
git -C "${test_repo}" mv frontend/src/page.tsx backend/src/page-renamed.tsx
git -C "${test_repo}" commit -qm "rename frontend file to backend"
assert_flags "rename" "$(cd "${test_repo}" && "${classifier}" "${base_commit}" "$(git rev-parse HEAD)")" \
  'run_frontend_verify=true' 'run_backend_verify=true' 'run_compose_verify=true' \
  'deploy_frontend=true' 'publish_backend=true' 'classification_error=false'

if "${classifier}" "missing-base" "${base_commit}" >/dev/null 2>&1; then
  echo "invalid SHA should fail" >&2
  exit 1
fi

echo "change classification fixtures passed"
