from datetime import datetime
from typing import Literal, Optional, List, Dict
from pydantic import BaseModel, Field

EdgeName = Literal["backend-a","backend-b"]
RootCause = Literal["edge_degraded","capacity_exhausted","network_latency",
                    "http_error_spike","unknown"]

class EdgeMetrics(BaseModel):
    bitrate: float
    latency: float
    err: float
    util: float
    healthy: int
    active: int
    workers: int

class Snapshot(BaseModel):
    ts: datetime
    edges: Dict[str, EdgeMetrics]

class Diagnosis(BaseModel):
    root_cause: RootCause
    summary: str = Field(min_length=1)
    evidence: List[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

class PolicyDecision(BaseModel):
    allow: bool
    playbook: Optional[str] = None
    reason: str

class ActionResult(BaseModel):
    ok: bool
    playbook: str
    detail: str
    verified: bool = False
