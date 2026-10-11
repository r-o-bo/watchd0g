#!/usr/bin/env bash
# watchd0g demo driver.
# Brings the stack up if needed, resets the edges, and walks the human through
# the demo with pauses. It never triggers an anomaly on its own.
set -euo pipefail
cd "$(dirname "$0")"

A=http://localhost:8001
B=http://localhost:8002
AGENT=http://localhost:8000

healthy_count() {
  docker compose ps --format '{{.Status}}' 2>/dev/null | grep -c '(healthy)' || true
}

pause() {
  printf '\n   -- press Enter to continue --\n'
  read -r _ || true
}

echo "==> Checking stack health"
if [ "$(healthy_count)" -lt 5 ]; then
  echo "==> Not all services healthy; bringing the stack up (docker compose up -d --build)"
  docker compose up -d --build
fi

echo "==> Waiting up to 90s for all 5 services to be healthy"
deadline=$(( $(date +%s) + 90 ))
while [ "$(healthy_count)" -lt 5 ]; do
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "!! Timed out waiting for health. Current status:"
    docker compose ps
    exit 1
  fi
  sleep 2
done
docker compose ps

echo
echo "==> Resetting both edges to baseline (A active, B standby)"
curl -sf -X POST "$A/simulate/reset" >/dev/null
curl -sf -X POST "$B/simulate/reset" >/dev/null
curl -sf -X POST "$A/simulate/set-active" -H 'Content-Type: application/json' -d '{"active":1}' >/dev/null
curl -sf -X POST "$B/simulate/set-active" -H 'Content-Type: application/json' -d '{"active":0}' >/dev/null

cat <<EOF

================ watchd0g demo ================
Stack is up and both edges are at baseline.
All actions below are SIMULATED.

Console:    http://localhost:8000
Grafana:    http://localhost:3000
Prometheus: http://localhost:9090
===============================================
EOF

echo
echo "STEP 1 - Degrade the ACTIVE edge A, then watch the agent react"
echo "  curl -sX POST $A/simulate/degrade"
echo "  # ~11s to detect; with a Gemini key, ~12-15s to failover to B"
echo "  curl -s $AGENT/api/status | python3 -m json.tool | tail -40"
echo "  # expect last_action.playbook=failover, verified=true, B active=1, A active=0"
pause

echo
echo "STEP 2 - Reset, then load the STANDBY edge B and scale it up"
echo "  for e in 8001 8002; do curl -sX POST http://localhost:\$e/simulate/reset; done"
echo "  curl -sX POST $B/simulate/set-active -H 'Content-Type: application/json' -d '{\"active\":1}'"
echo "  curl -sX POST $A/simulate/set-active -H 'Content-Type: application/json' -d '{\"active\":0}'"
echo "  sleep 6"
echo "  curl -sX POST $B/simulate/load"
echo "  # ~14s to detect; expect last_action.playbook=scale_up, B workers=2"
pause

echo
echo "STEP 3 - Prove the safety path (escalation, no action)"
echo "  sed -i 's/AUTO_REMEDIATE_ENABLED=true/AUTO_REMEDIATE_ENABLED=false/' .env"
echo "  docker compose up -d --force-recreate agent && sleep 10"
echo "  curl -sX POST $A/simulate/degrade"
echo "  sleep 20"
echo "  ls -la audit/escalations/ && cat \"\$(ls -t audit/escalations/*.json | head -1)\""
echo "  # restore afterwards:"
echo "  sed -i 's/AUTO_REMEDIATE_ENABLED=false/AUTO_REMEDIATE_ENABLED=true/' .env"
echo "  docker compose up -d --force-recreate agent"
pause

echo
echo "STEP 4 - Trace the incident"
echo "  tail -20 audit/agent_audit.jsonl"

echo
echo "==> Done. The stack is left running at baseline."
