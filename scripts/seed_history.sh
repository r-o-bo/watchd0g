#!/usr/bin/env bash
# seed_history.sh — warm the Grafana panels with ~10 minutes of varied
# metric history so the dashboard is alive the moment the demo opens.
#
# SIMULATED ONLY. This drives the local FastAPI edge simulators so Prometheus
# (5s scrape) records healthy / loaded / degraded episodes on both edges. No
# real viewer traffic, CDN, load balancer, or worker pool is involved.
#
# The agent is paused for the duration: otherwise it would detect every
# provoked anomaly, act on it (flipping active flags), and spend real LLM
# calls. It is always started again on exit. Re-runnable and idempotent.
set -uo pipefail
cd "$(dirname "$0")/.."

A=http://localhost:8001
B=http://localhost:8002
SLEEP="${SEED_SLEEP:-15}"

say() { printf '\n== %s\n' "$*"; }

healthy_count() { docker compose ps --format '{{.Status}}' 2>/dev/null | grep -c '(healthy)' || true; }
reset()      { curl -sf -X POST "$1/simulate/reset" >/dev/null 2>&1 || true; }
degrade()    { curl -sf -X POST "$1/simulate/degrade" >/dev/null 2>&1 || true; }
load()       { curl -sf -X POST "$1/simulate/load" >/dev/null 2>&1 || true; }
set_active() { curl -sf -X POST "$1/simulate/set-active" -H 'Content-Type: application/json' -d "{\"active\":$2}" >/dev/null 2>&1 || true; }

baseline() {
  reset "$A"; reset "$B"
  set_active "$A" 1; set_active "$B" 0
}

# Always bring the agent back, even if we are interrupted.
restart_agent_on_exit() { docker compose start agent >/dev/null 2>&1 || true; }
trap restart_agent_on_exit EXIT

say "Ensuring the stack is up"
if [ "$(healthy_count)" -lt 5 ]; then docker compose up -d; fi
for _ in $(seq 1 90); do [ "$(healthy_count)" -ge 5 ] && break; sleep 2; done

say "Pausing the agent during warm-up (keeps the history clean, no LLM calls spent)"
docker compose stop agent >/dev/null 2>&1 || true

baseline

say "Phase 1/3 - healthy baseline on both edges (20 cycles x ${SLEEP}s)"
for i in $(seq 1 20); do
  sleep "$SLEEP"
  printf '  healthy    %2d/20\n' "$i"
done

say "Phase 2/3 - backend-b load episodes (6 cycles)"
for i in $(seq 1 6); do
  set_active "$A" 0; set_active "$B" 1
  load "$B"; sleep "$SLEEP"
  reset "$B"; set_active "$B" 0
  sleep "$SLEEP"
  printf '  b load     %2d/6\n' "$i"
done

say "Phase 3/3 - backend-a degradation episodes (6 cycles)"
for i in $(seq 1 6); do
  set_active "$A" 1; set_active "$B" 0
  degrade "$A"; sleep "$SLEEP"
  reset "$A"; set_active "$A" 1
  sleep "$SLEEP"
  printf '  a degrade  %2d/6\n' "$i"
done

say "Resetting both edges to a healthy baseline (A active, B standby)"
baseline

say "Starting the agent again"
docker compose start agent >/dev/null 2>&1 || true
for _ in $(seq 1 30); do
  [ -n "$(curl -s http://localhost:8000/api/status 2>/dev/null)" ] && break
  sleep 1
done
baseline

echo "History seeded"
