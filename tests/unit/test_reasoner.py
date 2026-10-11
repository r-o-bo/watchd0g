import json, sys, types
from datetime import datetime, timezone

sys.path.insert(0, "agent")

import pytest
import google

from app.reasoner import Reasoner, ReasonerError
from app.schemas import Snapshot, EdgeMetrics


def _snap():
    return Snapshot(
        ts=datetime.now(timezone.utc),
        edges={
            "backend-a": EdgeMetrics(bitrate=2.4, latency=500.0, err=0.15,
                                     util=0.65, healthy=0, active=1, workers=1),
            "backend-b": EdgeMetrics(bitrate=8.0, latency=60.0, err=0.01,
                                     util=0.65, healthy=1, active=0, workers=1),
        },
    )


def _fake_genai(monkeypatch, response):
    """Install a fake google.genai so no real API key/network is needed."""
    text = json.dumps(response) if isinstance(response, (dict, list)) else response

    class _Resp:
        def __init__(self, text):
            self.text = text

    class _Models:
        def generate_content(self, model, contents, config=None):
            return _Resp(text)

    class _Client:
        def __init__(self, api_key=None):
            self.models = _Models()

    monkeypatch.setattr(google, "genai", types.SimpleNamespace(Client=_Client),
                        raising=False)


def test_not_configured_raises():
    r = Reasoner(api_key="", model="")
    with pytest.raises(ReasonerError):
        r.diagnose(_snap())


def test_valid_json_passes(monkeypatch):
    _fake_genai(monkeypatch, {
        "root_cause": "edge_degraded",
        "summary": "backend-a bitrate collapsed while latency spiked",
        "evidence": ["edge_output_bitrate_mbps=2.4", "edge_latency_ms=500"],
        "confidence": 0.82,
    })
    diag = Reasoner(api_key="k", model="m").diagnose(_snap())
    assert diag.root_cause == "edge_degraded"
    assert 0.0 <= diag.confidence <= 1.0
    assert diag.evidence


def test_ungrounded_evidence_rejected(monkeypatch):
    _fake_genai(monkeypatch, {
        "root_cause": "unknown",
        "summary": "the vibes were off",
        "evidence": ["something felt wrong"],
        "confidence": 0.2,
    })
    with pytest.raises(ReasonerError):
        Reasoner(api_key="k", model="m").diagnose(_snap())


def test_invalid_root_cause_rejected(monkeypatch):
    _fake_genai(monkeypatch, {
        "root_cause": "aliens",
        "summary": "unexpected visitors",
        "evidence": ["edge_latency_ms=500"],
        "confidence": 0.5,
    })
    with pytest.raises(ReasonerError):
        Reasoner(api_key="k", model="m").diagnose(_snap())


def test_invalid_json_rejected(monkeypatch):
    _fake_genai(monkeypatch, "this is not json")
    with pytest.raises(ReasonerError):
        Reasoner(api_key="k", model="m").diagnose(_snap())


def test_hourly_cap_enforced(monkeypatch):
    import app.config as config
    monkeypatch.setattr(config, "MAX_LLM_CALLS_PER_HOUR", 0)
    _fake_genai(monkeypatch, {
        "root_cause": "unknown",
        "summary": "x",
        "evidence": ["edge_latency_ms=1"],
        "confidence": 0.1,
    })
    with pytest.raises(ReasonerError):
        Reasoner(api_key="k", model="m").diagnose(_snap())
