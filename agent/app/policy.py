import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple
from . import config
from .schemas import PolicyDecision

ALLOWED_PLAYBOOKS = {"failover", "scale_up"}

@dataclass
class PolicyState:
    cooldowns: Dict[Tuple[str,str], float] = field(default_factory=dict)

def evaluate(kind: str, edge: str, standby_healthy: bool,
             state: PolicyState) -> PolicyDecision:
    if not config.AUTO_REMEDIATE_ENABLED:
        return PolicyDecision(allow=False, reason="AUTO_REMEDIATE_ENABLED is false")
    if kind == "failover":
        if not standby_healthy:
            return PolicyDecision(allow=False, reason="standby edge unhealthy")
        playbook = "failover"
    elif kind == "scale_up":
        playbook = "scale_up"
    else:
        return PolicyDecision(allow=False, reason=f"unknown kind {kind}")
    if playbook not in ALLOWED_PLAYBOOKS:
        return PolicyDecision(allow=False, reason="playbook not in allowlist")
    key = (edge, playbook)
    now = time.time()
    until = state.cooldowns.get(key, 0.0)
    if now < until:
        return PolicyDecision(allow=False, reason=f"cooldown active until {until:.0f}")
    return PolicyDecision(allow=True, playbook=playbook, reason="policy permitted")

def mark_executed(state: PolicyState, edge: str, playbook: str):
    state.cooldowns[(edge, playbook)] = time.time() + config.PLAYBOOK_COOLDOWN_SECONDS
