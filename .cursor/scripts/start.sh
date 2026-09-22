#!/usr/bin/env bash
#
# Cloud Agent start script for NetBox.
#
# Per-boot reconciliation: ensures PostgreSQL and Redis are running before
# the agent (and the dev server terminal) start doing work. Idempotent and
# safe to run on every boot.
set -euo pipefail

PG_VERSION=16
PG_CLUSTER=main

echo "==> Ensuring PostgreSQL is running"
sudo pg_ctlcluster "${PG_VERSION}" "${PG_CLUSTER}" start 2>/dev/null || true
for _ in $(seq 1 30); do
    if sudo pg_isready -q; then
        echo "    PostgreSQL is ready"
        break
    fi
    sleep 1
done

echo "==> Ensuring Redis is running"
sudo redis-server /etc/redis/redis.conf --daemonize yes 2>/dev/null || true
for _ in $(seq 1 30); do
    if redis-cli ping >/dev/null 2>&1; then
        echo "    Redis is ready"
        break
    fi
    sleep 1
done

echo "==> Services ready."
