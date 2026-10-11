from datetime import datetime, timezone
import httpx
from . import config
from .schemas import EdgeMetrics, Snapshot

METRICS = {
    "bitrate": "edge_output_bitrate_mbps",
    "latency": "edge_latency_ms",
    "err":     "edge_http_4xx_ratio",
    "util":    "edge_capacity_utilization_ratio",
    "healthy": "edge_healthy",
    "active":  "edge_active",
    "workers": "simulated_workers",
}

def _query(client: httpx.Client, name: str) -> dict:
    r = client.get(f"{config.PROMETHEUS_URL}/api/v1/query", params={"query": name})
    r.raise_for_status()
    data = r.json()["data"]["result"]
    out = {}
    for series in data:
        edge = series["metric"].get("edge")
        if edge:
            out[edge] = float(series["value"][1])
    return out

def poll(timeout: float = 5.0) -> Snapshot:
    with httpx.Client(timeout=timeout) as c:
        rows = {k: _query(c, m) for k, m in METRICS.items()}
    edges = {}
    for edge in ("backend-a","backend-b"):
        edges[edge] = EdgeMetrics(**{k: rows[k].get(edge, 0.0) for k in METRICS})
    return Snapshot(ts=datetime.now(timezone.utc), edges=edges)
