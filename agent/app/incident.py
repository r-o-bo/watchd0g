"""Assemble one incident's end-to-end trace from the audit ring buffer.

An incident is one ``detection`` event followed by its diagnosis, policy
decision, action/playbook result, and (if any) escalation. This module only
re-shapes already-recorded audit events; it never calls Prometheus or the LLM.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


def _compact(ts: Optional[str]) -> str:
    dt = _parse(ts)
    return dt.strftime("%Y%m%dT%H%M%SZ") if dt else "unknown"


def latest(events: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    idx = None
    for i in range(len(events) - 1, -1, -1):
        if events[i].get("event_type") == "detection":
            idx = i
            break
    if idx is None:
        return None

    det = events[idx]
    tail: List[Dict[str, Any]] = []
    for e in events[idx + 1:]:
        if e.get("event_type") == "detection":
            break
        tail.append(e)

    diagnosis = policy = action = escalation = None
    for e in tail:
        t = e.get("event_type")
        if t in ("diagnosis", "diagnosis_failed"):
            diagnosis = e
        elif t == "policy":
            policy = e
        elif t == "action":
            action = e
        elif t == "escalation":
            escalation = e

    terminal = None
    for e in tail:
        if e.get("event_type") in ("action", "escalation"):
            terminal = e
    resolved_at = (terminal or (tail[-1] if tail else None) or {}).get("ts")

    d0, d1 = _parse(det.get("ts")), _parse(resolved_at)
    duration = round((d1 - d0).total_seconds(), 1) if (d0 and d1) else None

    edge = det.get("edge")
    return {
        "incident_id": f"INC-{_compact(det.get('ts'))}-{edge}",
        "edge": edge,
        "kind": det.get("kind"),
        "reason": det.get("reason"),
        "detected_at": det.get("ts"),
        "resolved_at": resolved_at,
        "duration_seconds": duration,
        "signals": det.get("signals"),
        "diagnosis": diagnosis,
        "policy": policy,
        "action": action,
        "escalation": escalation,
        "steps": tail,
    }
