import importlib.util
import pathlib
import sys

from fastapi.testclient import TestClient

METRIC_NAMES = [
    "edge_output_bitrate_mbps",
    "edge_latency_ms",
    "edge_http_4xx_ratio",
    "edge_capacity_utilization_ratio",
    "edge_healthy",
    "edge_active",
    "simulated_workers",
]


def _load_simulator():
    """Load simulated/app.py in-process under a unique module name.

    The unique name avoids colliding with the agent's ``app`` package that the
    other unit tests import, and means these tests need no running Docker stack.
    """
    path = pathlib.Path(__file__).resolve().parents[2] / "simulated" / "app.py"
    spec = importlib.util.spec_from_file_location("watchd0g_simulated_app", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_SIM = _load_simulator()
client = TestClient(_SIM.app)


def test_metric_names_present():
    text = client.get("/metrics").text
    for name in METRIC_NAMES:
        assert name in text, f"missing metric {name}"


def test_degrade_changes_state_and_reset_restores():
    client.post("/simulate/reset")
    d = client.post("/simulate/degrade").json()
    assert d["healthy"] == 0
    assert d["bitrate"] < 5
    assert d["latency"] > 200
    assert d["err"] > 0.05
    r = client.post("/simulate/reset").json()
    assert r["healthy"] == 1
    assert r["bitrate"] == 8.0
    assert r["workers"] == 1


def test_scale_formula_halves_excess():
    client.post("/simulate/reset")
    client.post("/simulate/load")
    u1 = client.post("/scale", json={"workers": 1}).json()["util"]
    u2 = client.post("/scale", json={"workers": 2}).json()["util"]
    assert abs(u1 - 2 * u2) < 1e-6
    l1 = client.post("/scale", json={"workers": 1}).json()["latency"]
    l2 = client.post("/scale", json={"workers": 2}).json()["latency"]
    # latency = 50 + (base - 50) / workers, so the excess over 50 halves
    assert abs((l1 - 50.0) - 2 * (l2 - 50.0)) < 1e-6
    client.post("/simulate/reset")


def test_set_active_validates_0_or_1():
    assert client.post("/simulate/set-active", json={"active": 1}).status_code == 200
    assert client.post("/simulate/set-active", json={"active": 0}).status_code == 200
    assert client.post("/simulate/set-active", json={"active": 5}).status_code == 422
