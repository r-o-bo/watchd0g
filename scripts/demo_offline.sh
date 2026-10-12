#!/usr/bin/env bash
# demo_offline.sh — fallback demo for when Gemini is unavailable or
# rate-limited during the live demo.
#
# It drives the same scripted scenarios, narrates the expected LLM diagnosis
# with a CLEARLY LABELLED canned block ("no live LLM call"), and runs the
# safety scenario (Scenario 3) for real. SIMULATED ONLY — nothing here touches
# real traffic, a real CDN, or a real worker pool.
#
# Set NONINTERACTIVE=1 to run it without the pauses (for smoke-testing).
set -uo pipefail
cd "$(dirname "$0")/.."

A=http://localhost:8001
B=http://localhost:8002
AG=http://localhost:8000

say()  { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m   %s\033[0m\n' "$*"; }
note() { printf '\033[1;33m   %s\033[0m\n' "$*"; }
pause(){ if [ "${NONINTERACTIVE:-0}" = "1" ] || [ ! -t 0 ]; then return 0; fi
         printf '\n   -- press Enter to continue --\n'; read -r _ || true; }

healthy_count() { docker compose ps --format '{{.Status}}' 2>/dev/null | grep -c '(healthy)' || true; }
status() { curl -s "$AG/api/status"; }
query()  { status | python3 -c 'import json,sys;d=json.load(sys.stdin);print(eval(sys.argv[1],{},{"d":d}))' "$1"; }
sa()     { curl -sf -X POST "$1/simulate/set-active" -H 'Content-Type: application/json' -d "{\"active\":$2}" >/dev/null; }
sim()    { curl -sf -X POST "$1/simulate/$2" >/dev/null; }
reset_all() { sim "$A" reset; sim "$B" reset; }

restart_agent() {
  docker compose restart agent >/dev/null 2>&1
  for _ in $(seq 1 30); do [ -n "$(status)" ] && return 0; sleep 1; done
  return 1
}
wait_detection() {
  for _ in $(seq 1 25); do
    [ "$(query 'd.get("last_detection") is not None')" = "True" ] && return 0
    sleep 1
  done
  return 1
}
wait_policy_denied() {
  for _ in $(seq 1 40); do
    [ "$(query '(d.get("last_policy") or {}).get("allow",True)')" = "False" ] && return 0
    sleep 1
  done
  return 1
}

show() {
  python3 - "$(status)" <<'PY'
import json, sys
d = json.loads(sys.argv[1]); e = d.get("snapshot", {}).get("edges", {})
def row(n):
    m = e.get(n, {})
    return (f"{n}: healthy={m.get('healthy')} active={m.get('active')} "
            f"bitrate={m.get('bitrate')} latency={m.get('latency')} "
            f"util={m.get('util')} workers={m.get('workers')}")
print("   " + row("backend-a")); print("   " + row("backend-b"))
print(f"   policy: {json.dumps(d.get('last_policy'))}")
print(f"   action: {json.dumps(d.get('last_action'))}")
PY
}

canned() {  # $1 = expected playbook line
  cat <<EOF
============================================================
DEMO MODE - canned diagnosis; no live LLM call
  root_cause : (as recorded in the last live run)
  confidence : 0.95
  evidence   : edge_output_bitrate_mbps=2.4, edge_latency_ms=500.0,
               edge_http_4xx_ratio=0.15, edge_healthy=0
  expected   : $1
============================================================
EOF
}

printf '\033[1;33mNOTE: everything in this demo is SIMULATED.\033[0m\n'

say "Bringing up the stack"
if [ "$(healthy_count)" -lt 5 ]; then docker compose up -d --build; fi
for _ in $(seq 1 90); do [ "$(healthy_count)" -ge 5 ] && break; sleep 2; done
[ "$(healthy_count)" -ge 5 ] || { note "stack did not become healthy"; exit 1; }
printf '\n   Console:    http://localhost:8000\n   Grafana:    http://localhost:3000\n   Prometheus: http://localhost:9090\n'

# ------------------------------------------------------------ scenario 1
say "Scenario 1 - Edge failure & simulated failover (canned diagnosis)"
restart_agent; reset_all; sa "$A" 1; sa "$B" 0; sleep 5
echo "   provoked: POST $A/simulate/degrade"
sim "$A" degrade
wait_detection && ok "agent detected the anomaly on the active edge" || note "no detection observed"
pause
canned "policy permits failover; B becomes active (verified)"
pause
sleep 8
show
note "with a live key this diagnosis is a real Gemini call (engine=gemini);"
note "in REASONER_MODE=auto with no key the agent still completes via the deterministic mock."

# ------------------------------------------------------------ scenario 2
say "Scenario 2 - Capacity pressure & simulated scale-up (canned diagnosis)"
restart_agent; reset_all; sa "$A" 0; sa "$B" 1; sleep 5
echo "   provoked: POST $B/simulate/load"
sim "$B" load
wait_detection && ok "agent detected the load on the active edge" || note "no detection observed"
pause
cat <<'EOF'
============================================================
DEMO MODE - canned diagnosis; no live LLM call
  root_cause : capacity_exhausted
  confidence : 0.90
  evidence   : edge_capacity_utilization_ratio=0.95, edge_latency_ms=250.0
  expected   : policy permits; B scaled to 2 workers; utilization ~0.48
============================================================
EOF
pause
sleep 10
show

# ------------------------------------------------------------ scenario 3
say "Scenario 3 - Safety path (runs for real; no LLM needed)"
restart_agent; reset_all; sa "$A" 1; sa "$B" 0; sleep 4
echo "   provoked: degrade the STANDBY B, then the ACTIVE A"
sim "$B" degrade; sim "$A" degrade
if wait_policy_denied; then
  ok "policy DENIED the action - escalation written, nothing executed."
else
  note "policy denial not observed"
fi
show
LATEST=$(ls -t audit/escalations/*.json 2>/dev/null | head -1)
[ -n "$LATEST" ] && echo "   escalation: $LATEST" && \
  python3 -c "import json;print('   reason:', json.load(open('$LATEST'))['reason'])"

# ------------------------------------------------------------ reset + audit
say "Resetting to a clean baseline"
restart_agent; reset_all; sa "$A" 1; sa "$B" 0
ok "A active/healthy, B standby/healthy."

say "Audit trail (last 10 lines) - the full observe->detect->diagnose->policy->act->audit loop"
tail -10 audit/agent_audit.jsonl 2>/dev/null

echo
ok "Offline demo complete."
