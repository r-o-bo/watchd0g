import glob
import json
import sys
import types
from datetime import datetime, timezone

sys.path.insert(0, "agent")

import app.config as config
import app.main as main
from app.schemas import Snapshot, EdgeMetrics


def _snap():
    degraded = EdgeMetrics(bitrate=2.4, latency=500.0, err=0.15,
                           util=0.65, healthy=0, active=1, workers=1)
    standby = EdgeMetrics(bitrate=8.0, latency=60.0, err=0.01,
                          util=0.65, healthy=1, active=0, workers=1)
    return Snapshot(ts=datetime.now(timezone.utc),
                    edges={"backend-a": degraded, "backend-b": standby})


def test_escalation_artifact_written(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AUDIT_DIR", str(tmp_path))
    monkeypatch.setattr(config, "AUDIT_FILE", str(tmp_path / "agent_audit.jsonl"))
    monkeypatch.setattr(config, "ESCALATION_DIR", str(tmp_path / "escalations"))
    main.STATE["last_diagnosis"] = {"error": "Gemini not configured"}

    det = types.SimpleNamespace(edge="backend-a", kind="failover")
    main._escalate(det, _snap(), reason="diagnosis failed: Gemini not configured")

    files = glob.glob(str(tmp_path / "escalations" / "ESC-*.json"))
    assert len(files) == 1
    payload = json.load(open(files[0]))
    assert payload["edge"] == "backend-a"
    assert payload["kind"] == "failover"
    assert "Gemini not configured" in payload["reason"]
    assert payload["diagnosis"] == {"error": "Gemini not configured"}


def test_escalation_recorded_in_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AUDIT_DIR", str(tmp_path))
    monkeypatch.setattr(config, "AUDIT_FILE", str(tmp_path / "agent_audit.jsonl"))
    monkeypatch.setattr(config, "ESCALATION_DIR", str(tmp_path / "escalations"))
    main.STATE["last_diagnosis"] = {"error": "Gemini not configured"}

    det = types.SimpleNamespace(edge="backend-a", kind="failover")
    main._escalate(det, _snap(),
                   reason="policy denied: AUTO_REMEDIATE_ENABLED is false")

    with open(config.AUDIT_FILE) as f:
        rec = json.loads(f.readline())
    assert rec["event_type"] == "escalation"
    assert "AUTO_REMEDIATE_ENABLED" in rec["reason"]
