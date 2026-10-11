import sys
sys.path.insert(0, "agent")
from datetime import datetime, timezone
from app import config
from app.detector import DetectorState, update
from app.schemas import Snapshot, EdgeMetrics

def mk(**kw):
    base = dict(bitrate=8.0, latency=60.0, err=0.01, util=0.65,
                healthy=1, active=0, workers=1)
    base.update(kw)
    return EdgeMetrics(**base)

def snap(a, b):
    return Snapshot(ts=datetime.now(timezone.utc),
                    edges={"backend-a": a, "backend-b": b})

def test_failover_requires_two_consecutive():
    s = DetectorState()
    degraded = mk(bitrate=2.0, latency=500.0, err=0.15, active=1)
    healthy = mk(active=0)
    assert update(snap(degraded, healthy), s) is None
    d = update(snap(degraded, healthy), s)
    assert d is not None and d.kind == "failover" and d.edge == "backend-a"

def test_recovery_resets_streak():
    s = DetectorState()
    degraded = mk(bitrate=2.0, latency=500.0, err=0.15, active=1)
    healthy = mk(active=0)
    update(snap(degraded, healthy), s)
    update(snap(healthy, healthy), s)
    assert s.failover_streak["backend-a"] == 0
    assert update(snap(degraded, healthy), s) is None

def test_scale_up_three_samples():
    s = DetectorState()
    loaded = mk(util=0.95, latency=250.0, active=1)
    idle = mk(active=0)
    assert update(snap(loaded, idle), s) is None
    assert update(snap(loaded, idle), s) is None
    d = update(snap(loaded, idle), s)
    assert d is not None and d.kind == "scale_up"

def test_inactive_degraded_does_not_trigger():
    s = DetectorState()
    degraded_inactive = mk(bitrate=2.0, latency=500.0, err=0.15, active=0)
    healthy = mk(active=1)
    for _ in range(5):
        assert update(snap(degraded_inactive, healthy), s) is None


def test_recovery_requires_three_consecutive_healthy_samples():
    s = DetectorState()
    degraded = mk(bitrate=2.0, latency=500.0, err=0.15, active=1)
    healthy = mk(active=0)
    update(snap(degraded, healthy), s)
    assert s.recovery_streak == 0
    for n in (1, 2, 3):
        update(snap(healthy, healthy), s)
        assert s.recovery_streak == n
    assert s.recovery_streak >= config.RECOVERY_CONSECUTIVE_SAMPLES
    update(snap(degraded, healthy), s)
    assert s.recovery_streak == 0


def test_sustained_incident_emitted_once_until_recovery():
    s = DetectorState()
    degraded = mk(bitrate=2.0, latency=500.0, err=0.15, active=1)
    healthy = mk(active=0)
    assert update(snap(degraded, healthy), s) is None
    first = update(snap(degraded, healthy), s)
    assert first is not None and first.kind == "failover"
    # while the incident persists, no repeat emission
    assert update(snap(degraded, healthy), s) is None
    assert update(snap(degraded, healthy), s) is None
    # after the edge recovers, a new incident can be emitted again
    update(snap(healthy, healthy), s)
    assert update(snap(degraded, healthy), s) is None
    again = update(snap(degraded, healthy), s)
    assert again is not None and again.kind == "failover"
