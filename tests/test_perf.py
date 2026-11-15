"""Performance evidence from k11 Performance QA (a real report: GET /orders/{id} slowed and erroring)."""

import json
import shutil
from pathlib import Path

from k11_release_gate import gate
from k11_release_gate.evidence import collect, detect
from k11_release_gate.plan import DEFAULT_TRIGGERS, plan

REPORT = Path(__file__).parent / "fixtures" / "perf-report.json"


def _project(tmp_path, doc=None):
    d = tmp_path / ".qa-mcp" / "perf-report"
    d.mkdir(parents=True)
    if doc is None:
        shutil.copy(REPORT, d / "perf-report.json")
    else:
        (d / "perf-report.json").write_text(json.dumps(doc), "utf8")
    (tmp_path / ".qa-mcp" / "release-policy.yaml").write_text("required: [perf]\nmax_age_hours: 87600\n", "utf8")
    return tmp_path


def test_perf_report_is_recognised_with_facts(tmp_path):
    root = _project(tmp_path)
    assert detect(json.loads(REPORT.read_text("utf8"))) == "perf"
    (ev,) = collect(root, gate.Policy().evidence)
    f = ev.facts
    assert ev.kind == "perf" and f["status"] == "completed" and f["has_baseline"]
    assert f["server_errors"] and f["slo_breaches"] and f["regressions"]
    assert all("GET /orders/{id}" in m for m in f["server_errors"] + f["regressions"])


def test_perf_findings_block_and_regression_needs_a_person(tmp_path):
    root = _project(tmp_path)
    r = gate.evaluate(root, gate.load_policy(root))
    rules = {f["rule"]: f["outcome"] for f in r["findings"]}
    assert rules["perf.server_errors"] == "block" and rules["perf.slo_breached"] == "block"
    assert rules["perf.regression"] == "needs_human"
    assert r["verdict"] == "block"

    doc = json.loads(REPORT.read_text("utf8"))
    doc["findings"] = [x for x in doc["findings"] if x["type"] == "regression"]
    root2 = _project(tmp_path / "only-regression", doc)
    r2 = gate.evaluate(root2, gate.load_policy(root2))
    assert r2["verdict"] == "needs_human"


def test_perf_run_states(tmp_path):
    base = json.loads(REPORT.read_text("utf8"))
    for status, rule, verdict in (("blocked", "perf.not_run", "needs_human"), ("aborted", "perf.aborted", "block")):
        doc = {**base, "status": status, "reason": "guardrail", "findings": [], "comparison": None}
        root = _project(tmp_path / status, doc)
        r = gate.evaluate(root, gate.load_policy(root))
        assert {f["rule"] for f in r["findings"]} == {rule} and r["verdict"] == verdict
    clean = {**base, "findings": [], "comparison": None}
    root = _project(tmp_path / "clean", clean)
    r = gate.evaluate(root, gate.load_policy(root))
    assert [f["rule"] for f in r["findings"]] == ["perf.no_baseline"] and r["verdict"] == "ship"


def test_database_and_perf_changes_trigger_load_tests():
    p = plan(["db/migrations/0042_add_index.sql", "src/repositories/orders.py"], DEFAULT_TRIGGERS, [])
    assert "perf" in p["needed"]
    p = plan(["docs/readme.md", "openapi.yaml"], DEFAULT_TRIGGERS, [])
    assert "perf" not in p["needed"]
