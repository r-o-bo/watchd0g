import os, threading
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST

EDGE_NAME = os.environ.get("EDGE_NAME", "backend-a")
EDGE_PORT = int(os.environ.get("EDGE_PORT", "8001"))
L_BASE = 50.0

g_bitrate = Gauge("edge_output_bitrate_mbps", "Output bitrate Mbps", ["edge"])
g_latency = Gauge("edge_latency_ms", "Latency ms", ["edge"])
g_4xx     = Gauge("edge_http_4xx_ratio", "4xx ratio", ["edge"])
g_util    = Gauge("edge_capacity_utilization_ratio", "Utilization", ["edge"])
g_healthy = Gauge("edge_healthy", "Healthy", ["edge"])
g_active  = Gauge("edge_active", "Active", ["edge"])
g_workers = Gauge("simulated_workers", "Workers", ["edge"])

_lock = threading.Lock()
state = {
    "mode": "healthy",
    "workers": 1,
    "active": 1 if EDGE_NAME == "backend-a" else 0,
}

def _baseline():
    if state["mode"] == "degraded":
        return 2.4, 500.0, 0.15, 0.65, 0
    if state["mode"] == "loaded":
        return 8.0, 250.0, 0.01, 0.95, 1
    return 8.0, 60.0, 0.01, 0.65, 1

def render():
    with _lock:
        workers = state["workers"]
        bitrate, latency, err, util, healthy = _baseline()
        active = state["active"]
    util = max(0.0, min(1.0, util / workers))
    latency = L_BASE + (latency - L_BASE) / workers
    g_bitrate.labels(EDGE_NAME).set(bitrate)
    g_latency.labels(EDGE_NAME).set(latency)
    g_4xx.labels(EDGE_NAME).set(err)
    g_util.labels(EDGE_NAME).set(util)
    g_healthy.labels(EDGE_NAME).set(healthy)
    g_active.labels(EDGE_NAME).set(active)
    g_workers.labels(EDGE_NAME).set(workers)
    return {"bitrate":bitrate,"latency":latency,"err":err,"util":util,
            "healthy":healthy,"active":active,"workers":workers}

app = FastAPI()

class ActiveBody(BaseModel):
    active: int = Field(ge=0, le=1)
class ScaleBody(BaseModel):
    workers: int = Field(ge=1, le=4)

@app.get("/healthz")
def healthz():
    return {"status": "ok", "edge": EDGE_NAME}

@app.get("/metrics")
def metrics():
    render()
    return PlainTextResponse(generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)

@app.post("/simulate/degrade")
def degrade():
    with _lock: state["mode"] = "degraded"
    return render()

@app.post("/simulate/load")
def load():
    with _lock: state["mode"] = "loaded"
    return render()

@app.post("/simulate/reset")
def reset():
    with _lock:
        state["mode"] = "healthy"
        state["workers"] = 1
    return render()

@app.post("/simulate/set-active")
def set_active(body: ActiveBody):
    with _lock: state["active"] = body.active
    return render()

@app.post("/scale")
def scale(body: ScaleBody):
    with _lock: state["workers"] = body.workers
    return render()
