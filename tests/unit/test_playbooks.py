import sys
from datetime import datetime, timezone

sys.path.insert(0, "agent")

import pytest

import app.config as config
import app.observer as observer
import app.playbooks as playbooks
from app.schemas import Snapshot, EdgeMetrics


def _mk(**kw):
    base = dict(bitrate=8.0, latency=60.0, err=0.01, util=0.65,
                healthy=1, active=0, workers=1)
    base.update(kw)
    return EdgeMetrics(**base)


def _snap(a, b):
    return Snapshot(ts=datetime.now(timezone.utc),
                    edges={"backend-a": a, "backend-b": b})


@pytest.fixture
def calls(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "AUDIT_DIR", str(tmp_path))
    monkeypatch.setattr(config, "AUDIT_FILE", str(tmp_path / "agent_audit.jsonl"))
    monkeypatch.setattr(playbooks.time, "sleep", lambda *a, **k: None)
    recorded = []

    def fake_post(url, data=None, timeout=5.0):
        recorded.append((url, data))
        return {}

    monkeypatch.setattr(playbooks, "_post", fake_post)
    return recorded


def test_failover_promotes_standby_and_deactivates_degraded(calls, monkeypatch):
    degraded = _mk(active=1, healthy=0, bitrate=2.4, latency=500.0, err=0.15)
    standby = _mk(active=0, healthy=1)
    after = _snap(
        _mk(active=0, healthy=0, bitrate=2.4, latency=500.0, err=0.15),
        _mk(active=1, healthy=1),
    )
    monkeypatch.setattr(observer, "poll", lambda *a, **k: after)

    result = playbooks.execute_failover("backend-a", _snap(degraded, standby))

    assert result.ok is True
    assert result.verified is True
    urls = [c[0] for c in calls]
    assert "http://backend-b:8002/simulate/set-active" in urls
    assert "http://backend-a:8001/simulate/set-active" in urls
    assert calls[0][1] == {"active": 1}
    assert calls[1][1] == {"active": 0}


def test_failover_refuses_when_standby_unhealthy(calls, monkeypatch):
    degraded = _mk(active=1, healthy=0, bitrate=2.4, latency=500.0, err=0.15)
    standby = _mk(active=0, healthy=0)
    monkeypatch.setattr(observer, "poll",
                        lambda *a, **k: _snap(degraded, standby))

    result = playbooks.execute_failover("backend-a", _snap(degraded, standby))

    assert result.ok is False
    assert result.verified is False
    assert calls == []


def test_scale_up_sets_workers_and_verifies(calls, monkeypatch):
    after = _snap(_mk(active=1), _mk(active=0, workers=2))
    monkeypatch.setattr(observer, "poll", lambda *a, **k: after)

    result = playbooks.execute_scale_up("backend-b", target_workers=2)

    assert result.ok is True
    assert result.verified is True
    assert calls[0] == ("http://backend-b:8002/scale", {"workers": 2})


def test_scale_up_is_idempotent(calls, monkeypatch):
    after = _snap(_mk(active=1), _mk(active=0, workers=2))
    monkeypatch.setattr(observer, "poll", lambda *a, **k: after)

    first = playbooks.execute_scale_up("backend-b", target_workers=2)
    second = playbooks.execute_scale_up("backend-b", target_workers=2)

    assert first.ok and first.verified
    assert second.ok and second.verified
    assert all(c[1] == {"workers": 2} for c in calls)
