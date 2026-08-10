#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <base-sha> <head-sha>" >&2
  exit 64
fi

base_sha="$1"
head_sha="$2"

git rev-parse --verify "${base_sha}^{commit}" >/dev/null
git rev-parse --verify "${head_sha}^{commit}" >/dev/null

run_frontend_verify=false
run_backend_verify=false
run_compose_verify=false
deploy_frontend=false
publish_backend=false
classification_error=false

mark_frontend_verify() {
  run_frontend_verify=true
}

mark_backend_verify() {
  run_backend_verify=true
}

mark_compose_verify() {
  run_compose_verify=true
}

mark_all_verification() {
  run_frontend_verify=true
  run_backend_verify=true
  run_compose_verify=true
}

while IFS= read -r changed_path; do
  case "${changed_path}" in
    frontend/*)
      mark_frontend_verify
      deploy_frontend=true
      ;;
    backend/*)
      mark_backend_verify
      mark_compose_verify
      publish_backend=true
      ;;
    compose.yml|compose.dev.yml|compose.test.yml|.env.dev.example|.env.prod.example)
      mark_compose_verify
      ;;
    .github/workflows/frontend-test.yml)
      mark_frontend_verify
      ;;
    .github/workflows/frontend-deploy-dev.yml)
      mark_frontend_verify
      deploy_frontend=true
      ;;
    .github/workflows/backend-test.yml)
      mark_backend_verify
      ;;
    .github/workflows/backend-deploy-dev.yml)
      mark_backend_verify
      mark_compose_verify
      publish_backend=true
      ;;
    .github/workflows/compose-build.yml)
      mark_compose_verify
      ;;
    .github/workflows/release-main-dev.yml|.github/scripts/classify-main-release-changes.sh|.github/scripts/test-classify-main-release-changes.sh)
      mark_all_verification
      ;;
    .github/workflows/monitoring-verification.yml|.github/workflows/terraform-verification.yml|.github/workflows/backend-dev-image.yml)
      ;;
    compose.monitoring.yml|compose.monitoring.dev.yml|monitoring/*|infra/*|load-tests/*|scripts/loadtest/*|reference/*|presentation/*|evidence/*|output/*|.agents/*|.codex/*|README.md|AGENTS.md|.gitignore|.gitattributes|.DS_Store)
      ;;
    *)
      # Unknown paths must be reviewed before they can silently bypass a release.
      mark_all_verification
      classification_error=true
      ;;
  esac
done < <(git diff --name-only --no-renames --diff-filter=ACMRD "${base_sha}" "${head_sha}")

printf 'run_frontend_verify=%s\n' "${run_frontend_verify}"
printf 'run_backend_verify=%s\n' "${run_backend_verify}"
printf 'run_compose_verify=%s\n' "${run_compose_verify}"
printf 'deploy_frontend=%s\n' "${deploy_frontend}"
printf 'publish_backend=%s\n' "${publish_backend}"
printf 'classification_error=%s\n' "${classification_error}"
