# watchd0g

Agentic technical producer for live OTT streaming — **prototype**.

**Observe → Detect → Diagnose → Apply policy → Act → Verify → Audit**

## Quick start

    cp .env.example .env       # fill GEMINI_API_KEY and GEMINI_MODEL
    docker compose up --build -d

- Console:  http://localhost:8000
- Grafana:  http://localhost:3000
- Prometheus: http://localhost:9090

## Metric contract

| name | unit | healthy |
|---|---|---|
| edge_output_bitrate_mbps | Mbps | 8.0 |
| edge_latency_ms | ms | 60 |
| edge_http_4xx_ratio | 0–1 | 0.01 |
| edge_capacity_utilization_ratio | 0–1 | 0.65 |
| edge_healthy | 0/1 | 1 |
| edge_active | 0/1 | A=1 |
| simulated_workers | count | 1 |

## Safety

- `AUTO_REMEDIATE_ENABLED=false` by default.
- Only two playbooks, both simulated.
- Every decision is appended to `audit/agent_audit.jsonl`.
- Escalations are written to `audit/escalations/`.

## Known limitations

No real traffic, no real load balancer, no real workers, single-tenant, local only.
