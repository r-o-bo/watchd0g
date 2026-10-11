import httpx, time
from . import config, audit
from .schemas import ActionResult, Snapshot

def _post(url: str, data=None, timeout=5.0):
    with httpx.Client(timeout=timeout) as c:
        r = c.post(url, json=data)
        r.raise_for_status()
        return r.json()

def _active_map(snapshot: Snapshot):
    return {e: m.active for e, m in snapshot.edges.items()}

def _poll_until(predicate, timeout: float = 15.0, interval: float = 1.0) -> tuple:
    """Poll Prometheus until predicate(snapshot) is true or the timeout elapses.

    Prometheus scrapes every 5s, so a change made on an edge is not visible to
    an instant query immediately; we must wait for the next scrape(s).
    """
    from .observer import poll as _poll
    deadline = time.time() + timeout
    snapshot = _poll()
    while not predicate(snapshot):
        if time.time() >= deadline:
            return snapshot, False
        time.sleep(interval)
        snapshot = _poll()
    return snapshot, True

def execute_failover(degraded_edge: str, snapshot: Snapshot) -> ActionResult:
    standby = "backend-b" if degraded_edge == "backend-a" else "backend-a"
    before = _active_map(snapshot)
    try:
        s = snapshot.edges[standby]
        if s.healthy != 1:
            return ActionResult(ok=False, playbook="failover",
                                detail=f"standby {standby} unhealthy", verified=False)
        _post(config.BACKEND_URLS[standby] + "/simulate/set-active", {"active": 1})
        _post(config.BACKEND_URLS[degraded_edge] + "/simulate/set-active", {"active": 0})
        after_snap, ok = _poll_until(
            lambda snap: snap.edges[standby].active == 1
            and snap.edges[degraded_edge].active == 0
        )
        after = _active_map(after_snap)
        audit.write("playbook_result", playbook="failover",
                    degraded=degraded_edge, standby=standby,
                    before=before, after=after, verified=ok)
        return ActionResult(ok=ok, playbook="failover",
                            detail=f"{degraded_edge}->{standby}", verified=ok)
    except Exception as e:
        audit.write("playbook_error", playbook="failover", error=str(e))
        return ActionResult(ok=False, playbook="failover", detail=str(e), verified=False)

def execute_scale_up(edge: str, target_workers: int = 2) -> ActionResult:
    try:
        _post(config.BACKEND_URLS[edge] + "/scale", {"workers": target_workers})
        snap, verified = _poll_until(
            lambda s: s.edges[edge].workers == target_workers
        )
        audit.write("playbook_result", playbook="scale_up",
                    edge=edge, target=target_workers, verified=verified)
        return ActionResult(ok=verified, playbook="scale_up",
                            detail=f"{edge} workers -> {target_workers}", verified=verified)
    except Exception as e:
        audit.write("playbook_error", playbook="scale_up", error=str(e))
        return ActionResult(ok=False, playbook="scale_up", detail=str(e), verified=False)
