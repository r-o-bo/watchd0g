import sys
sys.path.insert(0, "agent")
import app.config as config
from app.policy import evaluate, mark_executed, PolicyState

def test_disabled_by_default(monkeypatch):
    monkeypatch.setattr(config, "AUTO_REMEDIATE_ENABLED", False)
    d = evaluate("failover", "backend-a", True, PolicyState())
    assert not d.allow and "AUTO_REMEDIATE_ENABLED" in d.reason

def test_failover_requires_standby(monkeypatch):
    monkeypatch.setattr(config, "AUTO_REMEDIATE_ENABLED", True)
    d = evaluate("failover", "backend-a", False, PolicyState())
    assert not d.allow and "standby" in d.reason

def test_failover_allowed(monkeypatch):
    monkeypatch.setattr(config, "AUTO_REMEDIATE_ENABLED", True)
    d = evaluate("failover", "backend-a", True, PolicyState())
    assert d.allow and d.playbook == "failover"

def test_cooldown(monkeypatch):
    monkeypatch.setattr(config, "AUTO_REMEDIATE_ENABLED", True)
    monkeypatch.setattr(config, "PLAYBOOK_COOLDOWN_SECONDS", 60)
    s = PolicyState()
    d1 = evaluate("scale_up", "backend-a", True, s)
    assert d1.allow
    mark_executed(s, "backend-a", "scale_up")
    d2 = evaluate("scale_up", "backend-a", True, s)
    assert not d2.allow and "cooldown" in d2.reason

def test_unknown_kind(monkeypatch):
    monkeypatch.setattr(config, "AUTO_REMEDIATE_ENABLED", True)
    assert not evaluate("nope", "backend-a", True, PolicyState()).allow

def test_low_confidence_blocks_action(monkeypatch):
    monkeypatch.setattr(config, "AUTO_REMEDIATE_ENABLED", True)
    d = evaluate("failover", "backend-a", True, PolicyState(),
                 diagnosis_confidence=0.35)
    assert not d.allow and "confidence" in d.reason

def test_high_confidence_allows_action(monkeypatch):
    monkeypatch.setattr(config, "AUTO_REMEDIATE_ENABLED", True)
    d = evaluate("failover", "backend-a", True, PolicyState(),
                 diagnosis_confidence=0.95)
    assert d.allow and d.playbook == "failover"
