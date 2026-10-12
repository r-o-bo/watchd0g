# watchd0g — demo cheat sheet

One page to hold while presenting. **Everything shown is simulated.**
CSE3132 (Software Engineering Lab) — prototype demonstration.

---

## Before the demo (5 minutes before)

```bash
docker compose up -d --build            # bring the stack up
bash scripts/seed_history.sh            # optional: warm the Grafana panels (~10 min)
```

- Open tabs: **Console** http://localhost:8000 · **Grafana** http://localhost:3000 · **Prometheus** http://localhost:9090
- Have a terminal open at the repo root (`~/projects/AgeisOps/watchdog`).
- Confirm readiness: `curl -s localhost:8000/api/status | python3 -m json.tool | grep -E 'auto_remediate|reasoner_configured'` → both should be `true`.

## The 30-second pitch

> "An agentic technical producer for live OTT streaming: it observes
> **simulated** CDN edge metrics, uses **Gemini** to diagnose anomalies, and
> applies one of **two deterministic remediation playbooks** — never an
> LLM-generated action."

The loop: **Observe → Detect → Diagnose (LLM) → Policy → Act → Verify → Audit.**

## Demo flow (10 minutes)

1. **Console + Grafana side by side.** Point out the four Grafana panels
   (Bitrate, Latency, 4xx ratio, Utilization) and the console's edge cards
   (green healthy · amber inactive · red degraded).
2. **Click Scenario 1** (Edge failure & simulated failover). Narrate what to
   watch on each surface: A's bitrate drops, latency spikes; ~11 s later the
   agent detects, calls Gemini, policy permits, A→inactive, B→active.
3. **Open the "Reasoning trace" panel.** Point out the LLM's **root cause**,
   **evidence list** (grounded in the frozen metric names) and **confidence**,
   plus the duration from detection to resolution.
4. **Show `audit/agent_audit.jsonl`** (`tail -20 audit/agent_audit.jsonl`) and
   trace one incident: detection → diagnosis → policy → action → verified.
5. **Click Scenario 2** (Capacity pressure & simulated scale-up). B's
   utilization passes 90%; after 3 consecutive samples the agent scales B to
   2 workers; utilization and latency drop per the deterministic formula.
6. **Click Scenario 3** (Safety). A is degraded but standby B is unhealthy, so
   the policy **refuses** — nothing executes. Show the escalation JSON under
   `audit/escalations/`. This is the safety guarantee.
7. **Low confidence variant.** `sed -i 's/FORCE_LOW_CONFIDENCE=false/FORCE_LOW_CONFIDENCE=true/' .env`
   then `docker compose up -d --force-recreate agent`, and run Scenario 1 again.
   The agent diagnoses correctly but **escalates** (confidence 0.35 < 0.6).
   Restore afterwards.
8. **Answer questions** with pointers into `docs/SRS.md` (numbered FRs).

## Anticipated questions and answers

- **"Is this real?"** → No. Both edges are FastAPI simulators. Failover flips a
  state flag; scale-up raises a worker counter. Everything is labelled
  "simulated" in the UI and the docs.
- **"Why not let the LLM act directly?"** → Safety. There is a deterministic
  policy gate. The LLM *explains*; the policy *permits*; the playbook *executes*.
- **"What if the LLM is wrong?"** → Evidence grounding rejects ungrounded
  claims; low confidence (< 0.6) escalates; a failed call escalates. Nothing
  unsafe is ever executed.
- **"How do you know it works?"** → 40+ automated tests, each mapped to a
  numbered FR in `docs/SRS.md`, including two live end-to-end playbook tests.
- **"How would this scale to production?"** → See the v2 roadmap in
  `docs/HANDOFF.md`: MCP tools, LangGraph, real CDN integration, Loki. Out of
  scope for the prototype.

## Recovery from common failures

- **Agent not detecting** → `docker compose ps` (agent healthy?); `docker compose logs --tail=50 agent`; check `/api/status` shows `auto_remediate:true`.
- **Gemini rate-limited (429)** → run `bash scripts/demo_offline.sh` (canned diagnosis, clearly labelled), or switch `GEMINI_MODEL` in `.env` and `docker compose up -d --force-recreate agent`.
- **Grafana stale / empty** → reload; verify targets are UP at http://localhost:9090/targets.
- **Console says "stale / unreachable"** → the agent was mid-restart; it recovers within one 3 s refresh. If not, `docker compose ps`.

## If the LLM is unavailable or rate-limited during the demo

```bash
bash scripts/demo_offline.sh
```

Runs the same scenarios, prints a **"DEMO MODE — canned diagnosis; no live LLM
call"** block instead of a live Gemini result, and runs the safety scenario for
real. Honest and unblocking.
