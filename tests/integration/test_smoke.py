import json, pathlib, subprocess, time, urllib.request

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.read().decode()


def post(url, data=None):
    body = json.dumps(data or {}).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode())


def _agent_status():
    try:
        return json.loads(get("http://localhost:8000/api/status"))
    except Exception:
        return {}


def _agent_e2e_ready():
    st = _agent_status()
    return bool(st.get("reasoner_configured")) and bool(st.get("auto_remediate"))


AGENT_E2E_READY = _agent_e2e_ready()
E2E_SKIP_REASON = (
    "agent is not configured for remediation: set GEMINI_API_KEY and "
    "GEMINI_MODEL in .env, keep AUTO_REMEDIATE_ENABLED=true, then recreate "
    "the agent container"
)


def _set_active(port, value):
    post(f"http://localhost:{port}/simulate/set-active", {"active": value})


def _reset_edges():
    post("http://localhost:8001/simulate/reset")
    post("http://localhost:8002/simulate/reset")


def _restart_agent():
    """Restart the agent to clear in-memory cooldowns, streaks and last_action.

    ``docker compose restart`` keeps the container's environment (so the Gemini
    key stays), and gives each end-to-end test a hermetic starting point.
    """
    subprocess.run(["docker", "compose", "restart", "agent"],
                   cwd=ROOT, check=True, capture_output=True, timeout=90)
    deadline = time.time() + 60
    while time.time() < deadline:
        if _agent_e2e_ready():
            return
        time.sleep(2)
    raise AssertionError("agent did not become ready after restart")


def _wait_for_action(playbook, timeout=50):
    deadline = time.time() + timeout
    while time.time() < deadline:
        act = _agent_status().get("last_action") or {}
        if act.get("playbook") == playbook and act.get("ok"):
            return True
        time.sleep(3)
    return False


def _wait_for_snapshot(predicate, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = (_agent_status().get("snapshot") or {}).get("edges") or {}
        if snap and predicate(snap):
            return True
        time.sleep(2)
    return False


def test_all_up():
    for u in ["http://localhost:8000/healthz",
              "http://localhost:8001/healthz",
              "http://localhost:8002/healthz",
              "http://localhost:9090/-/healthy",
              "http://localhost:3000/api/health"]:
        assert "ok" in get(u).lower() or "healthy" in get(u).lower()


def test_agent_api_and_console():
    st = _agent_status()
    assert "snapshot" in st
    assert "auto_remediate" in st
    events = json.loads(get("http://localhost:8000/api/events?limit=5"))
    assert "events" in events
    html = get("http://localhost:8000/")
    assert "watchd0g" in html.lower()


def test_degrade_flows_to_prometheus_and_agent():
    _reset_edges()
    _set_active(8001, 1)
    _set_active(8002, 0)
    time.sleep(7)
    post("http://localhost:8001/simulate/degrade")
    time.sleep(12)
    txt = get("http://localhost:9090/api/v1/query?query=edge_healthy")
    assert '"backend-a"' in txt
    st = _agent_status()
    assert st["snapshot"]["edges"]["backend-a"]["healthy"] == 0
    assert st["last_detection"] is not None
    _reset_edges()
    _set_active(8001, 1)
    _set_active(8002, 0)


@pytest.mark.skipif(not AGENT_E2E_READY, reason=E2E_SKIP_REASON)
def test_failover_end_to_end():
    _restart_agent()
    _reset_edges()
    _set_active(8001, 1)
    _set_active(8002, 0)
    time.sleep(7)
    post("http://localhost:8001/simulate/degrade")
    assert _wait_for_action("failover"), "failover playbook did not complete"
    assert _wait_for_snapshot(
        lambda e: e["backend-b"]["active"] == 1 and e["backend-a"]["active"] == 0
    ), "failover did not leave B active and A inactive"
    _set_active(8001, 1)
    _set_active(8002, 0)
    _reset_edges()


@pytest.mark.skipif(not AGENT_E2E_READY, reason=E2E_SKIP_REASON)
def test_scale_up_end_to_end():
    _restart_agent()
    _reset_edges()
    _set_active(8001, 0)
    _set_active(8002, 1)
    time.sleep(7)
    post("http://localhost:8002/simulate/load")
    assert _wait_for_action("scale_up"), "scale-up playbook did not complete"
    assert _wait_for_snapshot(
        lambda e: e["backend-b"]["workers"] == 2
    ), "scale-up did not set backend-b workers to 2"
    _reset_edges()
    _set_active(8001, 1)
    _set_active(8002, 0)
