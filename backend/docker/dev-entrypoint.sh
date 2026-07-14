#!/bin/sh
set -eu

boot_pid=""
compiler_pid=""

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

until wget -q -O /dev/null http://127.0.0.1:8080/actuator/health; do
  if ! kill -0 "$boot_pid" 2>/dev/null; then
    wait "$boot_pid"
    exit $?
  fi
  sleep 2
done

./gradlew classes --continuous --console=plain &
compiler_pid=$!

wait "$boot_pid"
