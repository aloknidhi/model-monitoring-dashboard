#!/usr/bin/env bash
# Healthcheck: wait for the monitoring backend to be ready
set -euo pipefail

HOST="${MONITORING_HOST:-localhost}"
PORT="${MONITORING_PORT:-8001}"
URL="http://${HOST}:${PORT}/monitoring/health"
TIMEOUT="${1:-60}"

echo "Waiting for monitoring backend at ${URL} (${TIMEOUT}s timeout)..."

elapsed=0
until curl -fsS "${URL}" >/dev/null 2>&1; do
  if (( elapsed >= TIMEOUT )); then
    echo "ERROR: monitoring backend not healthy after ${TIMEOUT}s"
    exit 1
  fi
  sleep 2
  elapsed=$((elapsed + 2))
done

echo "OK: monitoring backend is healthy"
