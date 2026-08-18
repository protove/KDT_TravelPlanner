#!/usr/bin/env bash
set -euo pipefail

run_frontend=false
run_backend=false
run_monitoring=false
run_terraform=false
run_k8s=false
run_compose=false
run_backend_dev_image=false
classification_error=false
changed_count=0

mark_all() {
  run_frontend=true
  run_backend=true
  run_monitoring=true
  run_terraform=true
  run_k8s=true
  run_compose=true
  run_backend_dev_image=true
}

classify_path() {
  local changed_path="$1"
  changed_count=$((changed_count + 1))

  case "${changed_path}" in
    frontend/*)
      run_frontend=true
      ;;
    backend/Dockerfile|backend/docker/*)
      run_backend=true
      run_backend_dev_image=true
      run_k8s=true
      ;;
    backend/src/main/kotlin/*/logging/*|backend/src/main/kotlin/*/monitoring/*|backend/src/main/kotlin/*/SecurityConfig.kt|backend/src/main/resources/application.yml|backend/src/main/resources/application-dev.yml|backend/src/main/resources/application-prod.yml|backend/src/main/resources/logback-spring.xml)
      run_backend=true
      run_monitoring=true
      ;;
    backend/*)
      run_backend=true
      ;;
    monitoring/*)
      run_monitoring=true
      ;;
    infra/*)
      run_terraform=true
      ;;
    k8s/*)
      run_k8s=true
      ;;
    compose.monitoring.yml|compose.monitoring.dev.yml)
      run_monitoring=true
      run_compose=true
      ;;
    compose.yml|compose.dev.yml|compose.test.yml)
      run_compose=true
      run_backend_dev_image=true
      ;;
    .env.dev.example)
      run_monitoring=true
      run_compose=true
      run_backend_dev_image=true
      run_k8s=true
      ;;
    .env.prod.example)
      run_monitoring=true
      run_compose=true
      ;;
    .github/workflows/frontend-test.yml)
      run_frontend=true
      ;;
    .github/workflows/backend-test.yml)
      run_backend=true
      ;;
    .github/workflows/monitoring-verification.yml)
      run_monitoring=true
      ;;
    .github/workflows/terraform-verification.yml)
      run_terraform=true
      ;;
    .github/workflows/k8s-verify.yml)
      run_k8s=true
      ;;
    .github/workflows/compose-build.yml)
      run_compose=true
      ;;
    .github/workflows/backend-dev-image.yml)
      run_backend_dev_image=true
      ;;
    .github/workflows/frontend-deploy-dev.yml)
      run_frontend=true
      ;;
    .github/workflows/backend-deploy-dev.yml)
      run_backend=true
      run_compose=true
      ;;
    .github/workflows/release-main-dev.yml)
      run_frontend=true
      run_backend=true
      run_compose=true
      ;;
    .github/workflows/pr-verification.yml|.github/scripts/classify-pr-changes.sh|.github/scripts/test-classify-pr-changes.sh)
      mark_all
      ;;
    .github/scripts/classify-main-release-changes.sh|.github/scripts/test-classify-main-release-changes.sh)
      run_frontend=true
      run_backend=true
      run_compose=true
      ;;
    README.md|AGENTS.md|.gitignore|.gitattributes|.DS_Store|docs/*|reference/*|presentation/*|evidence/*|output/*|recovery-control/*|load-tests/*|scripts/loadtest/*|.agents/*|.codex/*|.github/pull_request_template.md|.github/PULL_REQUEST_TEMPLATE/*)
      ;;
    *)
      mark_all
      classification_error=true
      printf 'unclassified path: %s\n' "${changed_path}" >&2
      ;;
  esac
}

print_classification() {
  printf 'run_frontend=%s\n' "${run_frontend}"
  printf 'run_backend=%s\n' "${run_backend}"
  printf 'run_monitoring=%s\n' "${run_monitoring}"
  printf 'run_terraform=%s\n' "${run_terraform}"
  printf 'run_k8s=%s\n' "${run_k8s}"
  printf 'run_compose=%s\n' "${run_compose}"
  printf 'run_backend_dev_image=%s\n' "${run_backend_dev_image}"
  printf 'classification_error=%s\n' "${classification_error}"
  printf 'changed_count=%s\n' "${changed_count}"
}

if [[ $# -eq 1 && "$1" == "--stdin" ]]; then
  while IFS= read -r changed_path; do
    [[ -z "${changed_path}" ]] || classify_path "${changed_path}"
  done
elif [[ $# -eq 2 ]]; then
  base_sha="$1"
  head_sha="$2"
  git rev-parse --verify "${base_sha}^{commit}" >/dev/null
  git rev-parse --verify "${head_sha}^{commit}" >/dev/null

  while IFS= read -r changed_path; do
    [[ -z "${changed_path}" ]] || classify_path "${changed_path}"
  done < <(git diff --name-only --no-renames --diff-filter=ACMRD "${base_sha}" "${head_sha}")
else
  echo "usage: $0 <base-sha> <head-sha> | --stdin" >&2
  exit 64
fi

print_classification
