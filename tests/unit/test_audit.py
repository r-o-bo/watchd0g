import sys, os, json, tempfile
sys.path.insert(0, "agent")
import importlib
os.environ["AUDIT_DIR"] = tempfile.mkdtemp()
import app.config as cfg
importlib.reload(cfg)
import app.audit as audit
importlib.reload(audit)

def test_redaction_and_append():
    audit.write("unit", GEMINI_API_KEY="abc", nested={"SLACK_WEBHOOK_URL":"x"})
    with open(cfg.AUDIT_FILE) as f:
        rec = json.loads(f.readline())
    assert rec["GEMINI_API_KEY"] == "***REDACTED***"
    assert rec["nested"]["SLACK_WEBHOOK_URL"] == "***REDACTED***"
