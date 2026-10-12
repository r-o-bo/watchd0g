#!/usr/bin/env bash
# watchd0g — one-command automated demo.
# Raises the stack, resets to baseline, then runs three scenarios end-to-end:
#   1. failover   (degrade the active edge)
#   2. scale-up   (load the active edge)
#   3. safety     (standby unhealthy -> policy denies -> escalation, no action)
# Needs no Gemini key: with REASONER_MODE=auto it uses Gemini when available and
# falls back to the deterministic mock reasoner otherwise, so the demo never
# stalls on quota or network.
set -uo pipefail
cd "$(dirname "$0")"

A=http://localhost:8001
B=http://localhost:8002
AG=http://localhost:8000

say()  { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m   %s\033[0m\n' "$*"; }
bad()  { printf '\033[1;31m   %s\033[0m\n' "$*"; }

healthy_count() { docker compose ps --format '{{.Status}}' 2>/dev/null | grep -c '(healthy)' || true; }
status() { curl -s "$AG/api/status"; }
query()  { status | python3 -c 'import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1], {}, {"d": d}))' "$1"; }
sa()     { curl -sf -X POST "$1/simulate/set-active" -H 'Content-Type: application/json' -d "{\"active\":$2}" >/dev/null; }
reset_all() { curl -sf -X POST "$A/simulate/reset" >/dev/null; curl -sf -X POST "$B/simulate/reset" >/dev/null; }

restart_agent() {
  docker compose restart agent >/dev/null 2>&1
  for _ in $(seq 1 30); do
    [ -n "$(status)" ] && return 0
    sleep 1
  done
  return 1
}

wait_action() {  # $1 playbook
  for _ in $(seq 1 60); do
    [ "$(query '(d.get("last_action") or {}).get("playbook","")')" = "$1" ] \
      && [ "$(query '(d.get("last_action") or {}).get("ok",False)')" = "True" ] && return 0
    sleep 1
  done
  return 1
}

wait_policy_denied() {
  for _ in $(seq 1 60); do
    [ "$(query 'd.get("last_policy") is not None')" = "True" ] \
      && [ "$(query '(d.get("last_policy") or {}).get("allow",True)')" = "False" ] && return 0
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
    return f"{n}: healthy={m.get('healthy')} active={m.get('active')} bitrate={m.get('bitrate')} latency={m.get('latency')} util={m.get('util')} workers={m.get('workers')}"
print("   " + row("backend-a")); print("   " + row("backend-b"))
di = d.get("last_diagnosis") or {}
if di:
    print(f"   diagnosis: {di.get('root_cause')} (engine={di.get('engine')}, conf={di.get('confidence')})")
    print(f"     \"{di.get('summary')}\"")
    for ev in di.get("evidence", []): print(f"       - {ev}")
print(f"   policy:    {json.dumps(d.get('last_policy'))}")
print(f"   action:    {json.dumps(d.get('last_action'))}")
PY
}

# ---------------------------------------------------------------- bring up
say "Bringing up the stack"
if [ "$(healthy_count)" -lt 5 ]; then docker compose up -d --build; fi
for _ in $(seq 1 90); do [ "$(healthy_count)" -ge 5 ] && break; sleep 2; done
docker compose ps --format 'table {{.Name}}\t{{.Status}}'
[ "$(healthy_count)" -ge 5 ] || { bad "stack did not become healthy"; exit 1; }

printf '\n   Console:    http://localhost:8000\n   Grafana:    http://localhost:3000\n   Prometheus: http://localhost:9090\n'

# ---------------------------------------------------------------- act 1
say "ACT 1 - Anomaly on the ACTIVE edge A: failing over to standby B"
restart_agent
reset_all; sa "$A" 1; sa "$B" 0; sleep 6
echo "   POST $A/simulate/degrade"
curl -s -X POST "$A/simulate/degrade" >/dev/null
if wait_action failover; then
  ok "SIMULATED FAILOVER complete (verified)."
else
  bad "failover did not complete"; show; exit 1
fi
show

# ---------------------------------------------------------------- act 2
say "ACT 2 - Load on the ACTIVE edge B: scaling it out"
restart_agent
reset_all; sa "$A" 0; sa "$B" 1; sleep 6
echo "   POST $B/simulate/load"
curl -s -X POST "$B/simulate/load" >/dev/null
if wait_action scale_up; then
  ok "SIMULATED SCALE-UP complete (verified)."
else
  bad "scale-up did not complete"; show; exit 1
fi
show

# ---------------------------------------------------------------- act 3
say "ACT 3 - Safety path: standby is unhealthy, so policy refuses to fail over"
restart_agent
reset_all; sa "$A" 1; sa "$B" 0; sleep 4
echo "   POST $A/simulate/degrade  +  POST $B/simulate/degrade   (standby also down)"
curl -s -X POST "$A/simulate/degrade" >/dev/null
curl -s -X POST "$B/simulate/degrade" >/dev/null
if wait_policy_denied; then
  ok "POLICY DENIED the action - escalation written, nothing executed."
else
  bad "policy denial not observed"; show; exit 1
fi
show
LATEST=$(ls -t audit/escalations/*.json 2>/dev/null | head -1)
[ -n "$LATEST" ] && echo "   escalation: $LATEST" && python3 -c "import json;print('   reason:', json.load(open('$LATEST'))['reason'])"

# ---------------------------------------------------------------- reset
say "Resetting to a clean baseline"
restart_agent
reset_all; sa "$A" 1; sa "$B" 0
ok "done. A active/healthy, B standby/healthy."

say "Audit trail (last 6 lines)"
tail -6 audit/agent_audit.jsonl 2>/dev/null
