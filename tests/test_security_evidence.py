"""Security evidence from k11 API Security QA (a real report from the deliberately flawed demo bank)."""

import json
from pathlib import Path

from k11_release_gate import gate
from k11_release_gate.evidence import collect, detect
from k11_release_gate.plan import DEFAULT_TRIGGERS, plan

REPORT = Path(__file__).parent / "fixtures" / "security-report.json"


def _project(tmp_path, doc=None):
    d = tmp_path / ".qa-mcp" / "security-report"
    d.mkdir(parents=True)
    (d / "security-report.json").write_text(json.dumps(doc or json.loads(REPORT.read_text("utf8"))), "utf8")
    (tmp_path / ".qa-mcp" / "release-policy.yaml").write_text("required: [security]\nmax_age_hours: 87600\n", "utf8")
    return tmp_path


def test_security_report_is_recognised(tmp_path):
    assert detect(json.loads(REPORT.read_text("utf8"))) == "security"
    (ev,) = collect(_project(tmp_path), gate.Policy().evidence)
    f = ev.facts
    assert ev.kind == "security" and f["status"] == "completed"
    assert any("API5:2023" in x for x in f["critical"]) and any("API1:2023" in x for x in f["high"])
    assert any("generic-api-key" in x for x in f["critical"])                 # new scanner finding
    assert f["expired_acceptances"] and "@platform-team" in f["expired_acceptances"][0]


def test_findings_block_and_expired_acceptance_needs_a_person(tmp_path):
    root = _project(tmp_path)
    r = gate.evaluate(root, gate.load_policy(root))
    rules = {f["rule"]: f["outcome"] for f in r["findings"]}
    assert rules["security.critical"] == "block" and rules["security.high"] == "block"
    assert rules["security.acceptance_expired"] == "needs_human" and rules["security.medium"] == "conditional"
    assert r["verdict"] == "block"


def test_a_clean_run_ships_and_a_refused_run_needs_a_person(tmp_path):
    clean = {"tool": "k11-api-security-qa-mcp 0.1.0", "generatedAt": "2026-11-16T00:00:00+00:00", "status": "completed",
             "reason": "", "environment": "staging", "api": {"tests": [], "findings": []},
             "scanners": {"files": [], "findings": []},
             "summary": {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0, "verdict": "pass",
                         "api_tests": {"passed": 30, "failed": 0, "inconclusive": 0, "not_run": 0}}}
    root = _project(tmp_path / "clean", clean)
    assert gate.evaluate(root, gate.load_policy(root))["verdict"] == "ship"
    root = _project(tmp_path / "blocked", {**clean, "status": "blocked", "reason": "looks like production"})
    r = gate.evaluate(root, gate.load_policy(root))
    assert [f["rule"] for f in r["findings"]] == ["security.not_run"] and r["verdict"] == "needs_human"


def test_auth_code_and_dependency_changes_trigger_security():
    assert "security" in plan(["src/auth/session.py"], DEFAULT_TRIGGERS, [])["needed"]
    assert "security" in plan(["requirements.txt"], DEFAULT_TRIGGERS, [])["needed"]
    assert "security" not in plan(["docs/guide.md", "openapi.yaml"], DEFAULT_TRIGGERS, [])["needed"]
