#!/usr/bin/env bash
# VPS deploy: build -> migrate (idempotent, runs in api entrypoint) -> up -> health-gate.
# Run on the VPS host from the repo root with `.env.vps` filled in.
# Usage: DOMAIN=app.example.com ./scripts/deploy-vps.sh
set -euo pipefail

: "${DOMAIN:?export DOMAIN=app.example.com first}"
[[ -f .env.vps ]] || { echo "missing .env.vps (copy from .env.vps.example)"; exit 1; }

# Load .env.vps so HTTPS_PORT and AAROGYA_CERTS_DIR are available even if
# the caller did not export them.
set -a
source .env.vps
set +a

COMPOSE="docker compose -f docker-compose.vps.yml"
export DOMAIN
export HTTPS_PORT="${HTTPS_PORT:-20354}"
export AAROGYA_CERTS_DIR="${AAROGYA_CERTS_DIR:-$HOME/aarogya-certs}"

echo "[1/5] validating compose config..."
$COMPOSE config -q

echo "[2/5] building images..."
$COMPOSE build

echo "[3/5] starting stack (api runs alembic upgrade head on boot)..."
$COMPOSE up -d
$COMPOSE up -d --wait --wait-timeout 300 api || true

echo "[4/5] health gates..."
for i in $(seq 1 30); do
  if curl -fsS -m 5 "https://$DOMAIN:$HTTPS_PORT/health/ready" | grep -q '"ready"'; then
    echo "api READY"
    break
  fi
  if [[ "$i" == "30" ]]; then echo "api NOT ready after 150s"; $COMPOSE logs --tail=50 api; exit 1; fi
  sleep 5
done

echo "[5/5] status:"
$COMPOSE ps --format 'table {{.Name}}\t{{.Status}}'
echo
echo "Next: login, chat, voice call, 409-busy, Telegram test (see docs/RUNBOOK_VPS.md)."
