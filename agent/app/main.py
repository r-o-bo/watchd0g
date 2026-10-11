import asyncio, os
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from . import config, observer, detector, audit, policy, playbooks
from .reasoner import Reasoner, ReasonerError

app = FastAPI(title="watchd0g agent")

STATE = {
    "last_snapshot": None,
    "detector_state": detector.DetectorState(),
    "policy_state": policy.PolicyState(),
    "last_detection": None,
    "last_diagnosis": None,
    "last_policy": None,
    "last_action": None,
    "last_update": None,
    "reasoner": Reasoner(),
    "busy": False,
}

async def handle_detection(det, snap):
    audit.write("detection", edge=det.edge, kind=det.kind, reason=det.reason)
    try:
        diag = STATE["reasoner"].diagnose(snap)
        STATE["last_diagnosis"] = diag.model_dump()
        audit.write("diagnosis", **diag.model_dump())
    except ReasonerError as e:
        audit.write("diagnosis_failed", error=str(e))
        STATE["last_diagnosis"] = {"error": str(e)}
        _escalate(det, snap, reason=f"diagnosis failed: {e}")
        return
    standby = "backend-b" if det.edge == "backend-a" else "backend-a"
    standby_healthy = snap.edges[standby].healthy == 1
    decision = policy.evaluate(det.kind, det.edge, standby_healthy, STATE["policy_state"])
    STATE["last_policy"] = decision.model_dump()
    audit.write("policy", **decision.model_dump())
    if not decision.allow:
        _escalate(det, snap, reason=decision.reason)
        return
    if decision.playbook == "failover":
        result = playbooks.execute_failover(det.edge, snap)
    elif decision.playbook == "scale_up":
        result = playbooks.execute_scale_up(det.edge, target_workers=2)
    else:
        return
    STATE["last_action"] = result.model_dump()
    audit.write("action", **result.model_dump())
    if result.ok:
        policy.mark_executed(STATE["policy_state"], det.edge, decision.playbook)
    else:
        _escalate(det, snap, reason=f"action failed: {result.detail}")

def _escalate(det, snap, reason: str):
    os.makedirs(config.ESCALATION_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(config.ESCALATION_DIR, f"ESC-{ts}-{det.edge}.json")
    import json
    payload = {"ts": ts, "edge": det.edge, "kind": det.kind, "reason": reason,
               "snapshot": snap.model_dump(mode="json"),
               "diagnosis": STATE.get("last_diagnosis")}
    with open(path, "w") as f: json.dump(payload, f, indent=2, default=str)
    audit.write("escalation", path=path, reason=reason)
    if config.SLACK_WEBHOOK_URL:
        try:
            import httpx
            httpx.post(config.SLACK_WEBHOOK_URL,
                       json={"text": f"watchd0g escalation: {reason}"}, timeout=5)
        except Exception as e:
            audit.write("slack_failed", error=str(e))

async def loop():
    while True:
        try:
            if not STATE["busy"]:
                STATE["busy"] = True
                snap = observer.poll()
                STATE["last_snapshot"] = snap.model_dump(mode="json")
                STATE["last_update"] = datetime.now(timezone.utc).isoformat()
                det = detector.update(snap, STATE["detector_state"])
                if det:
                    STATE["last_detection"] = det.__dict__
                    await handle_detection(det, snap)
                STATE["busy"] = False
        except Exception as e:
            audit.write("error", where="loop", error=str(e))
            STATE["busy"] = False
        await asyncio.sleep(config.POLL_INTERVAL_SECONDS)

@app.on_event("startup")
async def start():
    asyncio.create_task(loop())

@app.get("/healthz")
def healthz(): return {"status": "ok"}

@app.get("/api/status")
def status():
    return {
        "last_update": STATE["last_update"],
        "snapshot": STATE["last_snapshot"],
        "last_detection": STATE["last_detection"],
        "last_diagnosis": STATE["last_diagnosis"],
        "last_policy": STATE["last_policy"],
        "last_action": STATE["last_action"],
        "auto_remediate": config.AUTO_REMEDIATE_ENABLED,
        "reasoner_configured": bool(config.GEMINI_API_KEY and config.GEMINI_MODEL),
    }

@app.get("/api/events")
def events(limit: int = 50):
    return {"events": audit.recent(limit)}

@app.get("/")
def index():
    p = "/app/console/index.html"
    if os.path.exists(p): return FileResponse(p)
    return JSONResponse({"detail": "console not mounted yet"}, status_code=404)
