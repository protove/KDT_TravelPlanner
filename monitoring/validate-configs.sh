#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

for profile in dev prod; do
  docker run --rm \
    --entrypoint /bin/promtool \
    -v "$SCRIPT_DIR/prometheus:/etc/prometheus:ro" \
    prom/prometheus:v3.13.1 \
    check config "/etc/prometheus/prometheus.$profile.yml"

  docker run --rm \
    -v "$SCRIPT_DIR/loki:/etc/loki:ro" \
    grafana/loki:3.7.2 \
    -verify-config=true \
    -config.file="/etc/loki/loki.$profile.yml"

  docker run --rm \
    -v "$SCRIPT_DIR/alloy:/etc/alloy:ro" \
    grafana/alloy:v1.16.1 \
    validate "/etc/alloy/config.$profile.alloy"
done

docker run --rm \
  --entrypoint /bin/promtool \
  -v "$SCRIPT_DIR/prometheus:/etc/prometheus:ro" \
  prom/prometheus:v3.13.1 \
  check config "/etc/prometheus/prometheus.ec2.yml"

python3 -m json.tool \
  "$SCRIPT_DIR/grafana/dashboards/backend-overview.json" \
  >/dev/null
