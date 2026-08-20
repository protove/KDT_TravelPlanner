#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
classifier="${script_dir}/classify-pr-changes.sh"

assert_case() {
  local case_name="$1"
  local path_list="$2"
  shift 2
  local output
  output="$(printf '%s\n' "${path_list}" | "${classifier}" --stdin develop feat/SCRUM-1-example 2>/dev/null)"

  for expected in "$@"; do
    if ! grep -Fxq "${expected}" <<<"${output}"; then
      echo "${case_name}: missing ${expected}" >&2
      printf '%s\n' "${output}" >&2
      exit 1
    fi
  done
}

assert_route_case() {
  local case_name="$1"
  local base_branch="$2"
  local head_branch="$3"
  local path_list="$4"
  shift 4
  local output
  output="$(printf '%s\n' "${path_list}" | "${classifier}" \
    --stdin "${base_branch}" "${head_branch}" 2>/dev/null)"

  for expected in "$@"; do
    if ! grep -Fxq "${expected}" <<<"${output}"; then
      echo "${case_name}: missing ${expected}" >&2
      printf '%s\n' "${output}" >&2
      exit 1
    fi
  done
}

all_false=(
  'run_frontend=false'
  'run_backend=false'
  'run_monitoring=false'
  'run_terraform=false'
  'run_k8s=false'
  'run_compose=false'
  'run_backend_dev_image=false'
)

assert_case frontend 'frontend/src/app/page.tsx' \
  'run_frontend=true' 'run_backend=false' 'run_monitoring=false' \
  'run_terraform=false' 'run_k8s=false' 'run_compose=false' \
  'run_backend_dev_image=false' 'classification_error=false'

assert_case backend 'backend/src/main/kotlin/example/App.kt' \
  'run_frontend=false' 'run_backend=true' 'run_monitoring=false' \
  'run_terraform=false' 'run_k8s=false' 'run_compose=false' \
  'run_backend_dev_image=false' 'classification_error=false'

assert_case backend-dockerfile 'backend/Dockerfile' \
  'run_backend=true' 'run_k8s=true' 'run_backend_dev_image=true' \
  'run_monitoring=false' 'run_compose=false' 'classification_error=false'

assert_case backend-monitoring 'backend/src/main/resources/logback-spring.xml' \
  'run_backend=true' 'run_monitoring=true' 'run_compose=false' \
  'classification_error=false'

assert_case monitoring 'monitoring/prometheus/prometheus.yml' \
  'run_monitoring=true' 'run_backend=false' 'run_compose=false' \
  'classification_error=false'

assert_case terraform 'infra/modules/network/main.tf' \
  'run_terraform=true' 'run_backend=false' 'run_k8s=false' \
  'classification_error=false'

assert_case k8s 'k8s/backend-deployment.yaml' \
  'run_k8s=true' 'run_backend=false' 'run_compose=false' \
  'classification_error=false'

assert_case compose 'compose.yml' \
  'run_compose=true' 'run_backend_dev_image=true' 'run_backend=false' \
  'classification_error=false'

assert_case monitoring-compose 'compose.monitoring.yml' \
  'run_monitoring=true' 'run_compose=true' 'run_backend_dev_image=false' \
  'classification_error=false'

assert_case monitoring-diagnostic-compose $'compose.monitoring.diagnostic.yml\ncompose.monitoring.sql-diagnostic.yml' \
  'run_monitoring=true' 'run_compose=true' 'run_backend_dev_image=false' \
  'classification_error=false' 'changed_count=2'

assert_case dev-env '.env.dev.example' \
  'run_monitoring=true' 'run_k8s=true' 'run_compose=true' \
  'run_backend_dev_image=true' 'classification_error=false'

assert_case mixed $'frontend/src/app/page.tsx\ninfra/modules/network/main.tf\nk8s/backend-service.yaml' \
  'run_frontend=true' 'run_terraform=true' 'run_k8s=true' \
  'run_backend=false' 'classification_error=false' 'changed_count=3'

assert_case docs 'reference/strategy/git/GIT_STRATEGY.md' \
  "${all_false[@]}" 'classification_error=false' 'changed_count=1'

assert_case router '.github/workflows/pr-verification.yml' \
  'run_frontend=true' 'run_backend=true' 'run_monitoring=true' \
  'run_terraform=true' 'run_k8s=true' 'run_compose=true' \
  'run_backend_dev_image=true' 'classification_error=false'

assert_case unknown 'new-runtime-contract.txt' \
  'run_frontend=true' 'run_backend=true' 'run_monitoring=true' \
  'run_terraform=true' 'run_k8s=true' 'run_compose=true' \
  'run_backend_dev_image=true' 'classification_error=true'

assert_route_case develop-chore develop chore/SCRUM-18-optimize-pr-workflows \
  '.github/workflows/pr-verification.yml' \
  'verification_mode=development' 'source_policy_error=false' \
  'run_frontend=true' 'run_backend=true' 'classification_error=false'

assert_route_case develop-front-integration develop develop-front \
  'frontend/src/app/page.tsx' \
  'verification_mode=development' 'source_policy_error=false' \
  'run_frontend=true' 'run_backend=false' 'classification_error=false'

assert_route_case release-promotion main develop 'frontend/src/app/page.tsx' \
  'verification_mode=release-promotion' 'source_policy_error=false' \
  "${all_false[@]}" 'classification_error=false'

assert_route_case hotfix main hotfix/SCRUM-99-repair-release-workflow \
  'backend/src/main/kotlin/example/App.kt' \
  'verification_mode=hotfix' 'source_policy_error=false' \
  'run_backend=true' 'run_frontend=false' 'classification_error=false'

for invalid_head in \
  chore/SCRUM-1-example \
  ci/SCRUM-1-example \
  fix/SCRUM-1-example \
  feat/SCRUM-1-example
do
  assert_route_case "invalid-main-${invalid_head%%/*}" main "${invalid_head}" \
    'backend/src/main/kotlin/example/App.kt' \
    'verification_mode=invalid' 'source_policy_error=true' \
    "${all_false[@]}" 'classification_error=false'
done

assert_route_case release-unknown main develop 'new-runtime-contract.txt' \
  'verification_mode=release-promotion' 'source_policy_error=false' \
  "${all_false[@]}" 'classification_error=true'

assert_route_case unsupported-base develop-front feat/SCRUM-1-example \
  'frontend/src/app/page.tsx' \
  'verification_mode=invalid' 'source_policy_error=true' \
  "${all_false[@]}" 'classification_error=false'

if "${classifier}" >/dev/null 2>&1; then
  echo "missing arguments should fail" >&2
  exit 1
fi

test_repo="$(mktemp -d)"
trap 'rm -rf "${test_repo}"' EXIT
git -C "${test_repo}" init -q
git -C "${test_repo}" config user.email "ci-test@example.invalid"
git -C "${test_repo}" config user.name "CI Test"
mkdir -p "${test_repo}/frontend/src"
printf 'baseline\n' > "${test_repo}/frontend/src/page.tsx"
git -C "${test_repo}" add frontend/src/page.tsx
git -C "${test_repo}" commit -qm "baseline"
base_commit="$(git -C "${test_repo}" rev-parse HEAD)"

mkdir -p "${test_repo}/backend/src"
git -C "${test_repo}" mv frontend/src/page.tsx backend/src/page.tsx
git -C "${test_repo}" commit -qm "rename frontend file"
rename_output="$(cd "${test_repo}" && "${classifier}" develop feat/SCRUM-1-example "${base_commit}" HEAD)"
for expected in 'run_frontend=true' 'run_backend=true' 'classification_error=false' 'changed_count=2'; do
  if ! grep -Fxq "${expected}" <<<"${rename_output}"; then
    echo "git-range rename: missing ${expected}" >&2
    printf '%s\n' "${rename_output}" >&2
    exit 1
  fi
done

git -C "${test_repo}" reset --hard -q "${base_commit}"
git -C "${test_repo}" rm -q frontend/src/page.tsx
git -C "${test_repo}" commit -qm "delete frontend file"
delete_output="$(cd "${test_repo}" && "${classifier}" develop fix/SCRUM-1-example "${base_commit}" HEAD)"
for expected in 'run_frontend=true' 'classification_error=false' 'changed_count=1'; do
  if ! grep -Fxq "${expected}" <<<"${delete_output}"; then
    echo "git-range delete: missing ${expected}" >&2
    printf '%s\n' "${delete_output}" >&2
    exit 1
  fi
done

echo "PR change classification fixtures passed"
