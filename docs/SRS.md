# Software Requirements Specification — watchd0g

**Document type:** IEEE 830-style SRS
**Product:** watchd0g — agentic technical producer for live OTT streaming (prototype)
**Status:** describes the prototype as built and tested

---

## 1. Introduction

### 1.1 Purpose
This document specifies the requirements for watchd0g, a prototype agent that
supervises two simulated OTT streaming edges. It observes edge telemetry from
Prometheus, detects anomalies with deterministic consecutive-sample rules, asks a
large language model (Google Gemini) to diagnose the probable root cause, applies
a deterministic allow-listed policy, executes a **simulated** remediation playbook,
verifies the effect by re-querying Prometheus, and appends every step to an audit
trail. This SRS is written against the code and tests in this repository; every
functional requirement below is traceable to an existing automated test.

### 1.2 Scope
watchd0g is a **prototype only**. It runs as a single-node Docker Compose stack on
one host. It monitors **simulated** CDN edges — FastAPI processes that emit fake
Prometheus metrics. There is **no real viewer traffic, no real CDN, no real load
balancer, and no real worker pool**. "Failover" and "scale-up" are simulated state
changes on those edge processes; they do not shift traffic or provision capacity.
Out of scope: multi-tenant operation, production authentication, autoscaling of the
stack itself, and any integration with a real streaming origin.

### 1.3 Definitions
| Term | Meaning |
|------|---------|
| **OTT** | "Over-the-top" — video streamed to viewers over the public internet. |
| **CDN edge** | A point of presence that serves content close to viewers. Here, a simulated FastAPI service (`backend-a`, `backend-b`). |
| **Metric contract** | The frozen set of Prometheus gauge names and label values that all components agree on. |
| **Snapshot** | One poll of both edges: all seven metrics per edge at one instant (`app.schemas.Snapshot`). |
| **Detector** | The consecutive-sample rule engine that turns snapshots into detections (`app.detector`). |
| **Reasoner** | The Gemini-backed component that produces a schema-validated diagnosis (`app.reasoner`). |
| **Policy engine** | The deterministic guardrail layer that decides whether a detected anomaly may be remediated (`app.policy`). |
| **Playbook** | A fixed, deterministic remediation routine: `failover` or `scale_up` (`app.playbooks`). |
| **Incident** | A sustained anomaly on the active edge that has passed the detector threshold. |
| **MTTR** | Mean time to recovery — time from anomaly onset to a verified healthy state. |
| **Escalation** | A JSON artifact written when diagnosis fails or policy denies, so a human can intervene. |

### 1.4 References
1. Prometheus HTTP API — `https://prometheus.io/docs/prometheus/latest/querying/api/`
2. Google Gen AI SDK for Python (`google-genai`) — `https://googleapis.github.io/python-genai/`
3. IEEE Std 830-1998, *Recommended Practice for Software Requirements Specifications*
4. Project README (`README.md`), demo script (`docs/DEMO.md`), handoff (`docs/HANDOFF.md`)

---

## 2. Overall Description

### 2.1 Product perspective
watchd0g is a self-contained local system. It is a five-container Docker Compose
stack on a single network:

| Service | Image / build | Host port | Role |
|---------|---------------|-----------|------|
| `backend-a` | `simulated/` | 127.0.0.1:8001 | Simulated CDN edge A |
| `backend-b` | `simulated/` | 127.0.0.1:8002 | Simulated CDN edge B |
| `prometheus` | `prom/prometheus` | 127.0.0.1:9090 | Scrapes both edges every 5s |
| `grafana` | `grafana/grafana` | 127.0.0.1:3000 | Provisioned datasource + edge dashboard |
| `agent` | `agent/` | 127.0.0.1:8000 | Observe→…→Audit loop + console + HTTP API |

All host ports bind to `127.0.0.1` only. Service-to-service traffic uses Compose
service names. Both edges are the **same image** differentiated by the `EDGE_NAME`
and `EDGE_PORT` environment variables. The agent holds no Docker socket and cannot
control the stack; it only calls the edges' HTTP APIs and queries Prometheus.

### 2.2 Product functions
- **Observe** — the agent queries the Prometheus HTTP API every `POLL_INTERVAL_SECONDS` (default 5s) and builds a `Snapshot` of both edges.
- **Detect** — consecutive-sample rules turn snapshots into `failover` / `scale_up` detections.
- **Diagnose** — the reasoner asks Gemini for a structured root-cause diagnosis and validates it.
- **Apply policy** — a deterministic, allow-listed policy decides whether the detection may be remediated.
- **Act** — the chosen playbook calls the edge's HTTP API (simulated state change).
- **Verify** — the agent re-queries Prometheus to confirm the action took effect before logging success.
- **Audit** — every detection, diagnosis, policy decision, action and escalation is appended to a JSONL file, with secrets redacted.
- **Console** — the agent serves a plain HTML/JS page that polls `/api/status` and `/api/events` and offers edge control buttons.

### 2.3 User characteristics
The intended users are a two-student lab team with an SRE/operations background.
They are comfortable with Docker Compose, `curl`, and reading JSON and Prometheus
metrics. No end-user (viewer) interacts with the system.

### 2.4 Constraints
- Free-tier Google Gemini API; the model name must be one the key can access.
- Simulated edges only — no real traffic is ever affected.
- Local only; the sole outbound network dependency is the Gemini API.
- Docker Compose only — no Kubernetes, no orchestrator.
- The agent has no Docker socket access and cannot alter the stack.
- The metric contract names are frozen and must not be renamed.

### 2.5 Assumptions and dependencies
- Docker Engine and Docker Compose v2 are installed and working.
- A `GEMINI_API_KEY` and a `GEMINI_MODEL` the key can access are supplied in `.env`.
- Roughly 2 GB of free disk for images (python base, Prometheus, Grafana).
- The container registry is reachable (a mirror may be required on slow links).

---

## 3. Specific Requirements

### 3.1 External interfaces

#### 3.1.1 Simulator HTTP API (both edges)
| Method | Path | Request body | Success response |
|--------|------|--------------|------------------|
| GET | `/healthz` | — | `{"status":"ok","edge":"<name>"}` |
| GET | `/metrics` | — | Prometheus text exposition (all 7 gauges, `edge="<name>"`) |
| POST | `/simulate/degrade` | — | state object (below) |
| POST | `/simulate/load` | — | state object |
| POST | `/simulate/reset` | — | state object, restores healthy baseline |
| POST | `/simulate/set-active` | `{"active": 0\|1}` | state object; `422` if not 0/1 |
| POST | `/scale` | `{"workers": 1..4}` | state object; `422` if out of range |

The state object returned by the POST endpoints is:
`{"bitrate": float, "latency": float, "err": float, "util": float, "healthy": int, "active": int, "workers": int}`.
The frozen metric names are `edge_output_bitrate_mbps`, `edge_latency_ms`,
`edge_http_4xx_ratio`, `edge_capacity_utilization_ratio`, `edge_healthy`,
`edge_active`, and `simulated_workers`.

#### 3.1.2 Prometheus HTTP API
The agent reads metrics via `GET {PROMETHEUS_URL}/api/v1/query?query=<metric_name>`.
The instant-query endpoint is used (not range queries or `query_range`) because the
control loop needs the current value at each poll. The response is parsed from
`data.result[]`, keying each series by its `metric.edge` label and reading the
sample value `value[1]`.

#### 3.1.3 Gemini SDK
The reasoner uses the `google-genai` Python SDK:
`from google import genai; client = genai.Client(api_key=...);`
`client.models.generate_content(model=<GEMINI_MODEL>, contents=<prompt>, config={"temperature":0.1,"response_mime_type":"application/json"})`.
The response text must be JSON validating against the `Diagnosis` schema; the model
only *explains* and never authorizes an action.

#### 3.1.4 Agent HTTP API
| Method | Path | Response |
|--------|------|----------|
| GET | `/healthz` | `{"status":"ok"}` |
| GET | `/api/status` | snapshot, last detection/diagnosis/policy/action, `auto_remediate`, `reasoner_configured` |
| GET | `/api/events?limit=N` | the N most recent audit events |
| GET | `/` | the console (`console/index.html`) |

### 3.2 Functional requirements

> Each requirement is a verifiable behavior and maps to an existing test. Paths are
> relative to the repository root.

**Simulator contract**
- **FR-1** The simulator shall expose exactly the frozen metric names in its `/metrics` output.
  *Verified by:* `tests/unit/test_simulator_contract.py::test_metric_names_present`
- **FR-2** `POST /simulate/degrade` shall move an edge to degraded state and `POST /simulate/reset` shall restore the healthy baseline.
  *Verified by:* `tests/unit/test_simulator_contract.py::test_degrade_changes_state_and_reset_restores`
- **FR-3** Scaling workers shall divide baseline utilization by the worker count and divide the latency excess over 50 ms by the worker count.
  *Verified by:* `tests/unit/test_simulator_contract.py::test_scale_formula_halves_excess`
- **FR-4** `POST /simulate/set-active` shall accept only `0` or `1` and reject other values with HTTP 422.
  *Verified by:* `tests/unit/test_simulator_contract.py::test_set_active_validates_0_or_1`

**Detection**
- **FR-5** The detector shall fire `failover` after 2 consecutive degraded samples (bitrate < 5, latency > 200, 4xx > 0.05) on the active edge.
  *Verified by:* `tests/unit/test_detector.py::test_failover_requires_two_consecutive`
- **FR-6** The detector shall fire `scale_up` after 3 consecutive loaded samples (utilization > 0.90, latency > 120, healthy) on the active edge.
  *Verified by:* `tests/unit/test_detector.py::test_scale_up_three_samples`
- **FR-7** A non-degraded sample shall reset the anomaly streak.
  *Verified by:* `tests/unit/test_detector.py::test_recovery_resets_streak`
- **FR-8** Recovery shall require 3 consecutive healthy samples, and any anomalous sample shall reset the recovery streak.
  *Verified by:* `tests/unit/test_detector.py::test_recovery_requires_three_consecutive_healthy_samples`
- **FR-9** The detector shall ignore a degraded edge that is not active.
  *Verified by:* `tests/unit/test_detector.py::test_inactive_degraded_does_not_trigger`
- **FR-9.1** A sustained incident shall emit exactly one detection until the edge recovers, so the agent does not re-diagnose on every poll.
  *Verified by:* `tests/unit/test_detector.py::test_sustained_incident_emitted_once_until_recovery`

**Diagnosis (reasoner)**
- **FR-10** The reasoner shall raise an error when no API key or model is configured, rather than attempt a call.
  *Verified by:* `tests/unit/test_reasoner.py::test_not_configured_raises`
- **FR-11** The reasoner shall validate the LLM response against the `Diagnosis` schema and return it when valid.
  *Verified by:* `tests/unit/test_reasoner.py::test_valid_json_passes`
- **FR-12** The reasoner shall reject a diagnosis whose `root_cause` is not in the allowed enum.
  *Verified by:* `tests/unit/test_reasoner.py::test_invalid_root_cause_rejected`
- **FR-13** The reasoner shall reject non-JSON model output.
  *Verified by:* `tests/unit/test_reasoner.py::test_invalid_json_rejected`
- **FR-14** The reasoner shall reject evidence that does not cite a known metric name.
  *Verified by:* `tests/unit/test_reasoner.py::test_ungrounded_evidence_rejected`
- **FR-15** The reasoner shall cap LLM calls at `MAX_LLM_CALLS_PER_HOUR`.
  *Verified by:* `tests/unit/test_reasoner.py::test_hourly_cap_enforced`

**Policy guardrails**
- **FR-16** The policy engine shall deny every action when `AUTO_REMEDIATE_ENABLED` is false.
  *Verified by:* `tests/unit/test_policy.py::test_disabled_by_default`
- **FR-17** The policy engine shall deny `failover` unless the standby edge is healthy.
  *Verified by:* `tests/unit/test_policy.py::test_failover_requires_standby`
- **FR-18** The policy engine shall permit `failover` when remediation is enabled and the standby is healthy.
  *Verified by:* `tests/unit/test_policy.py::test_failover_allowed`
- **FR-19** The policy engine shall enforce a per-(edge, playbook) cooldown.
  *Verified by:* `tests/unit/test_policy.py::test_cooldown`
- **FR-20** The policy engine shall reject unknown detection kinds and any playbook outside the allowlist.
  *Verified by:* `tests/unit/test_policy.py::test_unknown_kind`

**Playbooks**
- **FR-21** The failover playbook shall set the standby edge active, then deactivate the degraded edge, and verify both in Prometheus before reporting success.
  *Verified by:* `tests/unit/test_playbooks.py::test_failover_promotes_standby_and_deactivates_degraded`
- **FR-22** The failover playbook shall refuse to act when the standby edge's `edge_healthy` is not 1.
  *Verified by:* `tests/unit/test_playbooks.py::test_failover_refuses_when_standby_unhealthy`
- **FR-23** The scale-up playbook shall set the target worker count and verify `simulated_workers` in Prometheus.
  *Verified by:* `tests/unit/test_playbooks.py::test_scale_up_sets_workers_and_verifies`
- **FR-24** The scale-up playbook shall be idempotent for a repeated call with the same target.
  *Verified by:* `tests/unit/test_playbooks.py::test_scale_up_is_idempotent`

**Audit and escalation**
- **FR-25** The audit writer shall redact `GEMINI_API_KEY`, `SLACK_WEBHOOK_URL`, and `GF_SECURITY_ADMIN_PASSWORD`, and append one JSON object per line.
  *Verified by:* `tests/unit/test_audit.py::test_redaction_and_append`
- **FR-26** An escalation artifact shall be written whenever diagnosis fails or policy denies, recording edge, kind, reason, and snapshot.
  *Verified by:* `tests/unit/test_escalation.py::test_escalation_artifact_written`
- **FR-27** Writing an escalation shall also append an `escalation` event to the audit log.
  *Verified by:* `tests/unit/test_escalation.py::test_escalation_recorded_in_audit`

**Agent API, console, and integration**
- **FR-28** The agent shall expose `/healthz`, `/api/status`, `/api/events`, and `/`, and the five services shall each answer a health endpoint.
  *Verified by:* `tests/integration/test_smoke.py::test_all_up`, `tests/integration/test_smoke.py::test_agent_api_and_console`
- **FR-29** The console shall be served at `/` and reflect current agent status.
  *Verified by:* `tests/integration/test_smoke.py::test_agent_api_and_console`
- **FR-30** A degraded edge shall propagate through Prometheus to the agent's status and detection.
  *Verified by:* `tests/integration/test_smoke.py::test_degrade_flows_to_prometheus_and_agent`
- **FR-31** With a configured reasoner and remediation enabled, the failover playbook shall complete end-to-end and verify.
  *Verified by:* `tests/integration/test_smoke.py::test_failover_end_to_end`
- **FR-32** With a configured reasoner and remediation enabled, the scale-up playbook shall complete end-to-end and verify `workers == 2`.
  *Verified by:* `tests/integration/test_smoke.py::test_scale_up_end_to_end`

### 3.3 Performance requirements
- **PR-1** Detection shall fire within 15 s of the onset of a sustained anomaly, given a 5 s Prometheus scrape interval and a 5 s agent poll interval (2–3 samples plus one observation interval).
- **PR-2** `/api/status` and `/api/events` shall respond in under 1 s under normal lab load (they read in-memory state only).
- **PR-3** The control loop shall not overlap polls; a single `busy` guard prevents concurrent iterations.

### 3.4 Safety requirements
- **SR-1** Only the allow-listed playbooks `failover` and `scale_up` may execute.
- **SR-2** LLM output shall never authorize an action; it only explains. The policy engine, not the model, decides.
- **SR-3** `AUTO_REMEDIATE_ENABLED` shall default to `false` in `.env.example`.
- **SR-4** Secrets (`GEMINI_API_KEY`, `SLACK_WEBHOOK_URL`, `GF_SECURITY_ADMIN_PASSWORD`) shall never be written to logs or the audit trail.
- **SR-5** On failed diagnosis or denied policy, the agent shall write an escalation and take no action.
- **SR-6** Failover and scale-up are simulations; the documentation shall never describe them as real traffic shifting.

### 3.5 Design constraints
- **DC-1** Deployment shall be Docker Compose only; no Kubernetes or other orchestrator.
- **DC-2** The agent shall not mount or access the Docker socket.
- **DC-3** Both edges shall be built from one image and differentiated by environment variables.
- **DC-4** All host port bindings shall be `127.0.0.1` only.
- **DC-5** The metric contract names in §3.1.1 are frozen and shall not be renamed.
