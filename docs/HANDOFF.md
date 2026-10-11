# HANDOFF — watchd0g

Status: **complete and verified end-to-end.** Both simulated playbooks
(failover and scale-up) have run against the live Gemini API and passed. You do
not need to do anything further unless you change `.env` or want to re-verify.

## Re-verify in one block

```bash
docker compose up -d                 # stack up (idempotent)
sleep 10
.venv/bin/python -m pytest tests/ -v # expect: 33 passed, 0 skipped
```

`33 passed` = 28 unit + 5 integration (all-up, agent API/console, degrade
propagation, failover e2e, scale-up e2e). Nothing should skip.

## CRITICAL: `.env` changes need a recreate, not a restart

`docker compose restart agent` does **not** re-read `env_file`. After editing
`.env` (key, model, or `AUTO_REMEDIATE_ENABLED`) you must recreate the container:

```bash
docker compose up -d --force-recreate agent
sleep 10
```

Confirm the agent picked it up:

```bash
curl -s http://localhost:8000/api/status | python3 -m json.tool \
  | grep -E 'reasoner_configured|auto_remediate'
```

- `reasoner_configured: false` → `GEMINI_API_KEY`/`GEMINI_MODEL` missing or typo'd.
- `auto_remediate: false` → `AUTO_REMEDIATE_ENABLED` is not `true`.

A plain `restart` is fine to clear in-memory state (cooldowns, streaks,
`last_action`); it just won't change the environment.

## Gemini model notes

- The working model in `.env` is **`gemini-3.5-flash-lite`**. The original
  `gemini-2.5-flash` hit the free-tier **daily** limit (20 requests/day per
  model per project) during bring-up; the quota is per model, so a different
  model has a fresh bucket.
- If you hit `429 RESOURCE_EXHAUSTED`, the audit log records
  `diagnosis_failed` with the retry delay. Switch `GEMINI_MODEL` to another
  model the key can access, then recreate the agent.
- Free-tier models retire for new users over time (`gemini-2.5-flash-lite`
  already points to `gemini-3.5-flash-lite`). List what your key can use:
  ```bash
  set -a; . ./.env; set +a
  .venv/bin/python -c "from google import genai; print(*[m.name for m in genai.Client(api_key='$GEMINI_API_KEY').models.list()], sep='\n')"
  ```
- Each sustained incident triggers **one** LLM call (the detector emits a
  detection once per incident, not every poll), so normal demo usage stays well
  inside the quota.

## Demo sequence (copy-pasteable)

```bash
# 0. baseline: A active, B standby
for e in 8001 8002; do curl -sX POST http://localhost:$e/simulate/reset; done
curl -sX POST http://localhost:8001/simulate/set-active -H 'Content-Type: application/json' -d '{"active":1}'
curl -sX POST http://localhost:8002/simulate/set-active -H 'Content-Type: application/json' -d '{"active":0}'
sleep 6

# 1. degrade A -> ~11s detect, ~12-15s simulated FAILOVER to B
curl -sX POST http://localhost:8001/simulate/degrade
sleep 20
curl -s http://localhost:8000/api/status | python3 -m json.tool | tail -40
# expect: last_action.playbook=failover, ok=true, verified=true, B active=1, A active=0

# 2. reset, load B -> ~14s detect, simulated SCALE-UP of B
for e in 8001 8002; do curl -sX POST http://localhost:$e/simulate/reset; done
curl -sX POST http://localhost:8002/simulate/set-active -H 'Content-Type: application/json' -d '{"active":1}'
curl -sX POST http://localhost:8001/simulate/set-active -H 'Content-Type: application/json' -d '{"active":0}'
sleep 6
curl -sX POST http://localhost:8002/simulate/load
sleep 20
# expect: last_action.playbook=scale_up, B workers=2, util ~0.48, latency ~150ms

# 3. safety path: escalation, no action
sed -i 's/AUTO_REMEDIATE_ENABLED=true/AUTO_REMEDIATE_ENABLED=false/' .env
docker compose up -d --force-recreate agent && sleep 10
curl -sX POST http://localhost:8001/simulate/degrade && sleep 20
ls -la audit/escalations/   # a new ESC-*.json whose reason mentions AUTO_REMEDIATE_ENABLED
sed -i 's/AUTO_REMEDIATE_ENABLED=false/AUTO_REMEDIATE_ENABLED=true/' .env
docker compose up -d --force-recreate agent
```

Or just run `bash demo.sh` — it raises the stack, waits for health, resets the
edges, prints the URLs, and walks you through the sequence with pauses. It never
triggers an anomaly on its own.

## Everyday commands

```bash
# tail the audit trail
tail -f audit/agent_audit.jsonl

# list escalation artifacts
ls -la audit/escalations/

# see the last action / policy / diagnosis
curl -s http://localhost:8000/api/status | python3 -m json.tool | tail -40

# recreate the agent after a .env change
docker compose up -d --force-recreate agent

# plain restart to clear in-memory cooldowns/state
docker compose restart agent

# all container status
docker compose ps
```

## Known limits

- **Simulated only** — no real traffic, CDN, load balancer, or worker pool.
  Failover/scale-up are state changes on the edge simulators.
- **Single tenant, local only** — one host, ports bound to `127.0.0.1`.
- The only outbound network dependency is the Gemini API.
- Free-tier Gemini quotas are small (20 requests/day/model); each incident uses
  one call, and switching `GEMINI_MODEL` moves to a fresh per-model bucket.
