import sys
sys.path.insert(0, "agent")
from app.incident import latest


def test_latest_assembles_full_trace():
    events = [
        {"event_type": "detection", "ts": "2026-10-12T06:00:00+00:00",
         "edge": "backend-a", "kind": "failover", "reason": "degraded",
         "signals": {"bitrate": 2.4, "latency": 500.0}},
        {"event_type": "diagnosis", "ts": "2026-10-12T06:00:03+00:00",
         "root_cause": "edge_degraded", "confidence": 0.95, "engine": "gemini"},
        {"event_type": "policy", "ts": "2026-10-12T06:00:03+00:00",
         "allow": True, "playbook": "failover", "reason": "policy permitted"},
        {"event_type": "action", "ts": "2026-10-12T06:00:06+00:00",
         "ok": True, "playbook": "failover", "verified": True},
    ]
    inc = latest(events)
    assert inc["incident_id"] == "INC-20261012T060000Z-backend-a"
    assert inc["signals"] == {"bitrate": 2.4, "latency": 500.0}
    assert inc["diagnosis"]["root_cause"] == "edge_degraded"
    assert inc["policy"]["allow"] is True
    assert inc["action"]["verified"] is True
    assert inc["duration_seconds"] == 6.0


def test_latest_none_when_no_detection():
    assert latest([{"event_type": "policy"}]) is None


def test_latest_reports_escalation_as_terminal():
    events = [
        {"event_type": "detection", "ts": "2026-10-12T06:00:00+00:00",
         "edge": "backend-a", "kind": "failover"},
        {"event_type": "policy", "ts": "2026-10-12T06:00:04+00:00",
         "allow": False, "reason": "standby edge unhealthy"},
        {"event_type": "escalation", "ts": "2026-10-12T06:00:05+00:00",
         "reason": "standby edge unhealthy"},
    ]
    inc = latest(events)
    assert inc["edge"] == "backend-a"
    assert inc["escalation"]["reason"] == "standby edge unhealthy"
    assert inc["action"] is None
    assert inc["duration_seconds"] == 5.0
