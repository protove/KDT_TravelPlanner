#!/usr/bin/env bash
# Planned AWS Recovery workload entrypoint. Keep the implementation in the
# k6-specific runner so a future non-k6 adapter can share the orchestrator.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/run-k6-aws-recovery.sh" "$@"
