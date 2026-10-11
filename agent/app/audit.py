import json, os, threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, List
from . import config

_lock = threading.Lock()
_SECRETS = ("GEMINI_API_KEY","SLACK_WEBHOOK_URL","GF_SECURITY_ADMIN_PASSWORD")
_EVENTS = deque(maxlen=500)

def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: ("***REDACTED***" if k in _SECRETS else _redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    return obj

def write(event_type: str, **fields):
    os.makedirs(config.AUDIT_DIR, exist_ok=True)
    rec = {"ts": datetime.now(timezone.utc).isoformat(),
           "event_type": event_type}
    rec.update(_redact(fields))
    line = json.dumps(rec, default=str)
    with _lock:
        _EVENTS.append(rec)
        with open(config.AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    return rec

def recent(limit: int = 50) -> List[dict]:
    with _lock:
        return list(_EVENTS)[-limit:]
