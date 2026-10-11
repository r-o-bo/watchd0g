import json, re, time
from typing import Optional
from pydantic import ValidationError
from . import config
from .schemas import Snapshot, Diagnosis

# The frozen metric contract. Evidence must cite one of these names.
METRIC_NAMES = (
    "edge_output_bitrate_mbps",
    "edge_latency_ms",
    "edge_http_4xx_ratio",
    "edge_capacity_utilization_ratio",
    "edge_healthy",
    "edge_active",
    "simulated_workers",
)
# Unambiguous snapshot field names that map one-to-one onto the metrics above.
METRIC_ALIASES = ("bitrate", "latency", "err", "util", "utilization",
                  "healthy", "active", "workers")
_ALIAS_RE = re.compile(r"\b(" + "|".join(METRIC_ALIASES) + r")\b")


def _is_grounded(evidence: str) -> bool:
    if any(name in evidence for name in METRIC_NAMES):
        return True
    return bool(_ALIAS_RE.search(evidence))


class ReasonerError(Exception):
    pass

class Reasoner:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key if api_key is not None else config.GEMINI_API_KEY
        self.model = model if model is not None else config.GEMINI_MODEL
        self._calls_this_hour = 0
        self._hour_start = time.time()

    def _check_quota(self):
        if time.time() - self._hour_start > 3600:
            self._hour_start = time.time()
            self._calls_this_hour = 0
        if self._calls_this_hour >= config.MAX_LLM_CALLS_PER_HOUR:
            raise ReasonerError("LLM hourly cap reached")

    def diagnose(self, snapshot: Snapshot) -> Diagnosis:
        self._check_quota()
        if not self.api_key or not self.model:
            raise ReasonerError("Gemini not configured")
        from google import genai
        client = genai.Client(api_key=self.api_key)
        prompt = self._build_prompt(snapshot)
        try:
            resp = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={"temperature": 0.1, "response_mime_type": "application/json"},
            )
        except Exception as e:
            raise ReasonerError(f"Gemini call failed: {e}") from e
        self._calls_this_hour += 1
        text = getattr(resp, "text", None)
        if not text:
            raise ReasonerError("empty response from Gemini")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ReasonerError(f"invalid JSON: {e}") from e
        try:
            diag = Diagnosis.model_validate(data)
        except ValidationError as e:
            raise ReasonerError(f"schema mismatch: {e}") from e
        for ev in diag.evidence:
            if not _is_grounded(ev):
                raise ReasonerError(f"evidence not grounded: {ev}")
        return diag

    @staticmethod
    def _build_prompt(snapshot: Snapshot) -> str:
        payload = snapshot.model_dump(mode="json")
        metrics = ", ".join(METRIC_NAMES)
        return (
            "You are an OTT streaming SRE. Diagnose the most likely root cause "
            "from this edge metric snapshot.\n"
            "The only valid metric names are: " + metrics + ".\n"
            "Respond in strict JSON with fields: "
            "root_cause (one of edge_degraded, capacity_exhausted, network_latency, "
            "http_error_spike, unknown), summary (1-2 sentences), evidence (a list of "
            "strings; EACH string MUST cite one of the metric names above together "
            "with its observed value, formatted EXACTLY as \"<metric_name>=<value>\", "
            "for example \"edge_output_bitrate_mbps=2.4\"), confidence (0..1). "
            "Never propose commands. Snapshot (JSON): " + json.dumps(payload)
        )
