# watchd0g — rehearsed demo script

Everything below is **simulated**. No real viewer traffic, CDN, load balancer,
or worker pool is touched. "Failover" and "scale-up" are state changes on
simulated edges.

---

## Prerequisites

- The stack is up and all five services are healthy:
  ```bash
  docker compose ps        # expect 5 rows, every STATUS containing "(healthy)"
  ```
- `.env` has both values filled:
  ```bash
  grep -E '^GEMINI_(API_KEY|MODEL)=' .env   # neither may be empty
  ```
- `AUTO_REMEDIATE_ENABLED=true` in `.env` for the **full** demo. Flip it to
  `false` for the **observe-only / safety** demo.
- `GEMINI_MODEL` is a model your key can access and that still has quota;
  this repo is verified with `gemini-3.5-flash-lite`.
- **After any `.env` change, recreate the agent — do not just restart it:**
  ```bash
  docker compose up -d --force-recreate agent   # restart does NOT re-read .env
  ```
  A plain `docker compose restart agent` is only for clearing in-memory state.

If `.env` is missing a Gemini key, the agent still observes and detects, and it
escalates instead of acting — that is the safety path, useful as a fallback demo.

---

## Walk-through (timings measured on this machine)

### Step 0 — baseline (≈1 s)
```bash
for e in 8001 8002; do curl -sX POST http://localhost:$e/simulate/reset; done
curl -sX POST http://localhost:8001/simulate/set-active \
     -H 'Content-Type: application/json' -d '{"active":1}'
curl -sX POST http://localhost:8002/simulate/set-active \
     -H 'Content-Type: application/json' -d '{"active":0}'
```
Expected: each returns the state object with `"healthy":1,"bitrate":8.0,
"latency":60.0,"util":0.65,"workers":1`; A has `"active":1`, B `"active":0`.
Both edges healthy, A is the active edge, B is standby.

### Step 1 — show the watching surfaces (≈10 s)
Open all three:
- Console:   http://localhost:8000  (edges, latest diagnosis/policy/action, events)
- Grafana:   http://localhost:3000  (provisioned "watchd0g — Edges" dashboard)
- Prometheus:http://localhost:9090  (try `edge_healthy` on the Graph tab)

Console refreshes every 3 s; Grafana every 5 s.

### Step 2 — degrade the active edge A (detection ≈ 11 s; +action ≈ 3 s with a key)
Click **Degrade A** on the console, or:
```bash
curl -sX POST http://localhost:8001/simulate/degrade
```
Within ~11 s the agent detects (`failover`: bitrate<5, latency>200, 4xx>0.05 for
2 consecutive samples). In Grafana, watch bitrate drop to 2.4 and latency jump to
500 ms on `backend-a`.

With a Gemini key set, the reasoner diagnoses, the policy allows, and the
**failover** playbook runs: B is promoted (`active=1`), A is deactivated
(`active=0`), and both are verified in Prometheus. Allow ~12–15 s total.

Verify:
```bash
curl -s http://localhost:8000/api/status | python3 -m json.tool
tail -12 audit/agent_audit.jsonl
```
Acceptance:
- `last_action.playbook == "failover"`, `last_action.ok == true`, `last_action.verified == true`
- `snapshot.edges["backend-b"].active == 1`, `snapshot.edges["backend-a"].active == 0`

Without a key you will instead see `last_diagnosis.error` and a JSON file under
`audit/escalations/` (that is Step 4 below).

### Step 3 — reset, then scale up the loaded edge B (detection ≈ 14 s)
```bash
for e in 8001 8002; do curl -sX POST http://localhost:$e/simulate/reset; done
curl -sX POST http://localhost:8002/simulate/set-active \
     -H 'Content-Type: application/json' -d '{"active":1}'
curl -sX POST http://localhost:8001/simulate/set-active \
     -H 'Content-Type: application/json' -d '{"active":0}'
sleep 6
curl -sX POST http://localhost:8002/simulate/load
```
Within ~14 s the agent detects `scale_up` (util>0.90, latency>120 for 3
consecutive samples) and, with a key, runs the **scale-up** playbook: B's workers
go to 2, verified in Prometheus.

Verify:
```bash
curl -s http://localhost:8000/api/status | python3 -m json.tool | tail -40
```
Acceptance:
- `last_action.playbook == "scale_up"`, `last_action.ok == true`
- `snapshot.edges["backend-b"].workers == 2`
- B's `util` drops from 0.95 to ~0.48 and `latency` from 250 to ~150 ms.

### Step 4 — prove the safety path: escalation (≈ 20 s)
Force a case the policy cannot auto-fix, either by using an unconfigured key or
by turning remediation off:
```bash
sed -i 's/AUTO_REMEDIATE_ENABLED=true/AUTO_REMEDIATE_ENABLED=false/' .env
docker compose up -d --force-recreate agent && sleep 10
for e in 8001 8002; do curl -sX POST http://localhost:$e/simulate/reset; done
curl -sX POST http://localhost:8001/simulate/set-active \
     -H 'Content-Type: application/json' -d '{"active":1}'
curl -sX POST http://localhost:8001/simulate/degrade
sleep 20
```
Show the artifact and that no action was taken:
```bash
ls -la audit/escalations/
cat "$(ls -t audit/escalations/*.json | head -1)"
curl -s http://localhost:8000/api/status | python3 -m json.tool
```
Acceptance: a new `ESC-*.json` exists whose `reason` mentions
`AUTO_REMEDIATE_ENABLED` (or the missing Gemini config); `last_action` is `null`.

Restore remediation afterwards:
```bash
sed -i 's/AUTO_REMEDIATE_ENABLED=false/AUTO_REMEDIATE_ENABLED=true/' .env
docker compose up -d --force-recreate agent
```

### Step 5 — trace one incident (≈1 s)
```bash
tail -20 audit/agent_audit.jsonl
```
You should see the chain `detection → diagnosis → policy → action → playbook_result`
for a successful run, or `detection → diagnosis_failed → escalation` for the
safety path.

---

## Where to look

| Thing | Location |
|-------|----------|
| Live edges + diagnosis/action | http://localhost:8000 |
| Edge metric graphs | http://localhost:3000 |
| Raw metric queries | http://localhost:9090 |
| Full audit trail | `audit/agent_audit.jsonl` (one JSON object per line) |
| Escalations | `audit/escalations/ESC-<ts>-<edge>.json` |
| Agent logs | `docker compose logs -f agent` |

---

## What can go wrong (and how to recover)

1. **Cooldown active from a previous run.** The agent enforces a 60 s cooldown
   per (edge, playbook); `last_policy.reason` will say `cooldown active`.
   *Recovery:* `docker compose restart agent` clears the in-memory cooldown.
2. **Standby edge left unhealthy from a previous failover.** If B was degraded
   earlier, failover is denied with `standby edge unhealthy`.
   *Recovery:* reset both edges and re-set active: run the Step 0 commands.
3. **Gemini rate-limited (429) or model unavailable.** The run escalates; the
   audit shows `diagnosis_failed` with the SDK error and a retry delay.
   *Recovery:* switch `GEMINI_MODEL` in `.env` to another model the key can
   access, then `docker compose up -d --force-recreate agent`. The free tier is
   20 requests/day **per model**, so a different model is a fresh bucket.
4. **One LLM call per incident, not per poll.** The detector emits a detection
   once per incident and re-arms only after the edge recovers, so a stuck edge
   does not drain your Gemini quota with repeated diagnoses.
5. **Escalation files accumulate across runs.** Every failed/denied incident
   writes one `ESC-*.json`, and they are never cleaned automatically.
   *Recovery:* `rm -f audit/escalations/ESC-*.json` between runs for a clean slate.
6. **Stale metrics right after startup.** For the first ~10 s the snapshot may be
   zeros or the previous state.
   *Recovery:* wait one poll interval (5 s) before judging the console.

---

## Not required for the demo
- Slack (`SLACK_WEBHOOK_URL` stays empty) — notifications are optional.
- Grafana annotations — optional polish only.
- Any network access beyond this machine, with the single exception of the Gemini API.
