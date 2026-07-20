#!/bin/sh
set -eu

boot_pid=""
compiler_pid=""
management_port="${MANAGEMENT_SERVER_PORT:-9091}"
management_health_url="http://127.0.0.1:${management_port}/actuator/health"

cleanup() {
  if [ -n "$compiler_pid" ]; then
    kill "$compiler_pid" 2>/dev/null || true
  fi
  if [ -n "$boot_pid" ]; then
    kill "$boot_pid" 2>/dev/null || true
  fi
  wait 2>/dev/null || true
}

trap cleanup EXIT INT TERM

./gradlew bootRun --console=plain &
boot_pid=$!

until wget -q -O /dev/null "$management_health_url" 2>/dev/null; do
  if ! kill -0 "$boot_pid" 2>/dev/null; then
    if wait "$boot_pid"; then
      boot_status=1
    else
      boot_status=$?
    fi
    boot_pid=""
    echo "Backend bootRun exited before management health became ready." >&2
    exit "$boot_status"
  fi
  sleep 2
done

./gradlew classes --continuous --console=plain &
compiler_pid=$!

wait "$boot_pid"
