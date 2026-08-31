#!/usr/bin/env bash
set -euo pipefail

run_frontend=false
run_backend=false
run_monitoring=false
run_terraform=false
run_k8s=false
run_compose=false
run_backend_dev_image=false
run_load_test=false
classification_error=false
source_policy_error=false
verification_mode=invalid
changed_count=0
skip_specialists=false

mark_all() {
  run_frontend=true
  run_backend=true
  run_monitoring=true
  run_terraform=true
  run_k8s=true
  run_compose=true
  run_backend_dev_image=true
  run_load_test=true
}

apply_pr_policy() {
  local base_branch="$1"
  local head_branch="$2"

  case "${base_branch}" in
    develop)
      verification_mode=development
      ;;
    main)
      case "${head_branch}" in
        develop)
          verification_mode=release-promotion
          skip_specialists=true
          ;;
        hotfix/*)
          verification_mode=hotfix
          ;;
        *)
          verification_mode=invalid
          source_policy_error=true
          skip_specialists=true
          printf 'unsupported main PR source: %s\n' "${head_branch}" >&2
          ;;
      esac
      ;;
    *)
      verification_mode=invalid
      source_policy_error=true
      skip_specialists=true
      printf 'unsupported PR base: %s\n' "${base_branch}" >&2
      ;;
  esac
}

suppress_specialists() {
  run_frontend=false
  run_backend=false
  run_monitoring=false
  run_terraform=false
  run_k8s=false
  run_compose=false
  run_backend_dev_image=false
  run_load_test=false
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
    scripts/eks/*)
      # EKS automation crosses Terraform outputs, private Kubernetes stages
      # and monitoring manifests; route all three checks explicitly.
      run_terraform=true
      run_k8s=true
      run_monitoring=true
      ;;
    compose.monitoring.yml|compose.monitoring.dev.yml|compose.monitoring.diagnostic.yml|compose.monitoring.sql-diagnostic.yml)
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
    .github/workflows/load-test-verification.yml)
      run_load_test=true
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
    load-tests/*|scripts/loadtest/*)
      run_load_test=true
      ;;
    README.md|AGENTS.md|.gitignore|.gitattributes|.DS_Store|docs/*|reference/*|presentation/*|evidence/*|output/*|recovery-control/*|.agents/*|.codex/*|.github/pull_request_template.md|.github/PULL_REQUEST_TEMPLATE/*)
      ;;
    *)
      mark_all
      classification_error=true
      printf 'unclassified path: %s\n' "${changed_path}" >&2
      ;;
  esac
}

print_classification() {
  printf 'verification_mode=%s\n' "${verification_mode}"
  printf 'source_policy_error=%s\n' "${source_policy_error}"
  printf 'run_frontend=%s\n' "${run_frontend}"
  printf 'run_backend=%s\n' "${run_backend}"
  printf 'run_monitoring=%s\n' "${run_monitoring}"
  printf 'run_terraform=%s\n' "${run_terraform}"
  printf 'run_k8s=%s\n' "${run_k8s}"
  printf 'run_compose=%s\n' "${run_compose}"
  printf 'run_backend_dev_image=%s\n' "${run_backend_dev_image}"
  printf 'run_load_test=%s\n' "${run_load_test}"
  printf 'classification_error=%s\n' "${classification_error}"
  printf 'changed_count=%s\n' "${changed_count}"
}

if [[ $# -eq 3 && "$1" == "--stdin" ]]; then
  apply_pr_policy "$2" "$3"
  while IFS= read -r changed_path; do
    [[ -z "${changed_path}" ]] || classify_path "${changed_path}"
  done
elif [[ $# -eq 4 ]]; then
  base_branch="$1"
  head_branch="$2"
  base_sha="$3"
  head_sha="$4"
  apply_pr_policy "${base_branch}" "${head_branch}"
  git rev-parse --verify "${base_sha}^{commit}" >/dev/null
  git rev-parse --verify "${head_sha}^{commit}" >/dev/null

  while IFS= read -r changed_path; do
    [[ -z "${changed_path}" ]] || classify_path "${changed_path}"
  done < <(git diff --name-only --no-renames --diff-filter=ACMRD "${base_sha}" "${head_sha}")
else
  echo "usage: $0 <base-branch> <head-branch> <base-sha> <head-sha> | --stdin <base-branch> <head-branch>" >&2
  exit 64
fi

if [[ "${skip_specialists}" == "true" ]]; then
  suppress_specialists
fi

print_classification
