import os
def _b(v): return v.lower() in ("1","true","yes","on")
def _f(v, d): return float(v) if v not in (None, "") else d
def _i(v, d): return int(v) if v not in (None, "") else d

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")
POLL_INTERVAL_SECONDS = _i(os.environ.get("POLL_INTERVAL_SECONDS"), 5)
AUDIT_DIR = os.environ.get("AUDIT_DIR", "/app/audit")
AUDIT_FILE = os.path.join(AUDIT_DIR, "agent_audit.jsonl")
ESCALATION_DIR = os.path.join(AUDIT_DIR, "escalations")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "")
MAX_LLM_CALLS_PER_HOUR = _i(os.environ.get("MAX_LLM_CALLS_PER_HOUR"), 10)
# gemini: only the real API (raise on failure)
# mock:   only the deterministic local reasoner (no network)
# auto:   try Gemini, fall back to the deterministic reasoner on any failure
REASONER_MODE = os.environ.get("REASONER_MODE", "gemini").lower()

AUTO_REMEDIATE_ENABLED = _b(os.environ.get("AUTO_REMEDIATE_ENABLED", "false"))
PLAYBOOK_COOLDOWN_SECONDS = _i(os.environ.get("PLAYBOOK_COOLDOWN_SECONDS"), 60)

# Deterministic demo switch: when true, every diagnosis is forced to a low
# confidence so the low-confidence escalation path can be shown on demand.
FORCE_LOW_CONFIDENCE = _b(os.environ.get("FORCE_LOW_CONFIDENCE", "false"))
FORCED_CONFIDENCE_VALUE = _f(os.environ.get("FORCED_CONFIDENCE_VALUE"), 0.35)
# A diagnosis below this confidence is escalated instead of acted upon.
CONFIDENCE_MIN_THRESHOLD = _f(os.environ.get("CONFIDENCE_MIN_THRESHOLD"), 0.6)

FAILOVER_BITRATE_MAX_MBPS = _f(os.environ.get("FAILOVER_BITRATE_MAX_MBPS"), 5.0)
FAILOVER_LATENCY_MIN_MS = _f(os.environ.get("FAILOVER_LATENCY_MIN_MS"), 200.0)
FAILOVER_4XX_MIN_RATIO = _f(os.environ.get("FAILOVER_4XX_MIN_RATIO"), 0.05)
FAILOVER_CONSECUTIVE_SAMPLES = _i(os.environ.get("FAILOVER_CONSECUTIVE_SAMPLES"), 2)

SCALE_UTILIZATION_MIN_RATIO = _f(os.environ.get("SCALE_UTILIZATION_MIN_RATIO"), 0.90)
SCALE_LATENCY_MIN_MS = _f(os.environ.get("SCALE_LATENCY_MIN_MS"), 120.0)
SCALE_CONSECUTIVE_SAMPLES = _i(os.environ.get("SCALE_CONSECUTIVE_SAMPLES"), 3)

RECOVERY_CONSECUTIVE_SAMPLES = _i(os.environ.get("RECOVERY_CONSECUTIVE_SAMPLES"), 3)

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
BACKEND_URLS = {
    "backend-a": os.environ.get("BACKEND_A_URL", "http://backend-a:8001"),
    "backend-b": os.environ.get("BACKEND_B_URL", "http://backend-b:8002"),
}
