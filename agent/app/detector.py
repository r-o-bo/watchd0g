from dataclasses import dataclass, field
from typing import Dict, Optional
from . import config

@dataclass
class DetectorState:
    failover_streak: Dict[str, int] = field(default_factory=lambda: {"backend-a":0,"backend-b":0})
    scale_streak: Dict[str, int] = field(default_factory=lambda: {"backend-a":0,"backend-b":0})
    recovery_streak: int = 0
    # Kind already reported for an edge, so a sustained incident is emitted once
    # (and only re-armed after the edge recovers). Cleared to None on recovery.
    emitted: Dict[str, Optional[str]] = field(default_factory=lambda: {"backend-a":None,"backend-b":None})

@dataclass
class Detection:
    kind: str
    edge: str
    reason: str

def _is_degraded(m) -> bool:
    return (m.bitrate < config.FAILOVER_BITRATE_MAX_MBPS
            and m.latency > config.FAILOVER_LATENCY_MIN_MS
            and m.err > config.FAILOVER_4XX_MIN_RATIO)

def _is_loaded(m) -> bool:
    return (m.util > config.SCALE_UTILIZATION_MIN_RATIO
            and m.latency > config.SCALE_LATENCY_MIN_MS
            and m.healthy == 1)

def update(snapshot, state: DetectorState) -> Optional[Detection]:
    for edge, m in snapshot.edges.items():
        if m.active == 1 and _is_degraded(m):
            state.failover_streak[edge] += 1
        else:
            state.failover_streak[edge] = 0
    for edge, m in snapshot.edges.items():
        if m.active == 1 and _is_loaded(m):
            state.scale_streak[edge] += 1
        else:
            state.scale_streak[edge] = 0
    any_bad = any(_is_degraded(m) or _is_loaded(m) for m in snapshot.edges.values())
    state.recovery_streak = 0 if any_bad else state.recovery_streak + 1
    for edge in snapshot.edges:
        if state.failover_streak[edge] == 0 and state.scale_streak[edge] == 0:
            state.emitted[edge] = None
    for edge, n in state.failover_streak.items():
        if n >= config.FAILOVER_CONSECUTIVE_SAMPLES and state.emitted[edge] != "failover":
            state.emitted[edge] = "failover"
            return Detection(kind="failover", edge=edge,
                             reason=f"{edge} degraded for {n} consecutive samples")
    for edge, n in state.scale_streak.items():
        if n >= config.SCALE_CONSECUTIVE_SAMPLES and state.emitted[edge] != "scale_up":
            state.emitted[edge] = "scale_up"
            return Detection(kind="scale_up", edge=edge,
                             reason=f"{edge} loaded for {n} consecutive samples")
    return None
