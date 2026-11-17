"""Integration evidence from k11 Integration QA (a real report from the demo shop with its three bugs on)."""

import json
from pathlib import Path

from k11_release_gate import gate
from k11_release_gate.evidence import collect, detect
from k11_release_gate.plan import DEFAULT_TRIGGERS, plan

REPORT = Path(__file__).parent / "fixtures" / "integration-report.json"


def _project(tmp_path, doc=None):
    d = tmp_path / ".qa-mcp" / "integration-report"
    d.mkdir(parents=True)
    (d / "integration-report.json").write_text(json.dumps(doc or json.loads(REPORT.read_text("utf8"))), "utf8")
    (tmp_path / ".qa-mcp" / "release-policy.yaml").write_text("required: [integration]\nmax_age_hours: 87600\n", "utf8")
    return tmp_path


def test_integration_report_is_recognised_not_mistaken_for_api_tests(tmp_path):
    doc = json.loads(REPORT.read_text("utf8"))
    assert detect(doc) == "integration"
    assert detect({**doc, "tool": ""}) == "integration"          # by content too
    (ev,) = collect(_project(tmp_path), gate.Policy().evidence)
    f = ev.facts
    assert ev.kind == "integration" and f["status"] == "completed" and f["flows"] == 4 and f["failed"] == 4
    assert any("closest: $.qty: expected 3, got 1" in x for x in f["failed_flows"])   # the consumer bug
    assert any("orders.dlq" in x for x in f["failed_flows"])                          # the dead-letter bug
    assert any("expected 2, got 4" in x for x in f["failed_flows"])                   # the non-idempotent job


def test_failed_flows_block(tmp_path):
    root = _project(tmp_path)
    r = gate.evaluate(root, gate.load_policy(root))
    assert [f["rule"] for f in r["findings"]] == ["integration.failed"] and r["verdict"] == "block"


def test_passing_ships_refused_needs_a_person_and_nothing_run_needs_a_person(tmp_path):
    doc = json.loads(REPORT.read_text("utf8"))
    ok_flows = [{**f, "status": "passed", "steps": [{**s, "status": "passed"} for s in f["steps"]]} for f in doc["flows"]]
    passed = {**doc, "flows": ok_flows, "reason": "all flows passed", "summary": {**doc["summary"], "passed": 4, "failed": 0}}
    root = _project(tmp_path / "ok", passed)
    assert gate.evaluate(root, gate.load_policy(root))["verdict"] == "ship"

    refused = {**passed, "flows": [{**ok_flows[0], "status": "blocked", "error": None,
                                    "steps": [{**ok_flows[0]["steps"][0], "status": "blocked", "kind": "publish",
                                               "error": "Publishing refused on 'prod'"}]}] + ok_flows[1:]}
    root = _project(tmp_path / "refused", refused)
    r = gate.evaluate(root, gate.load_policy(root))
    assert [f["rule"] for f in r["findings"]] == ["integration.flows_not_run"] and r["verdict"] == "needs_human"
    assert "Publishing refused" in r["findings"][0]["details"][0]

    none = {**passed, "flows": [], "status": "not_run", "reason": "no integration flows found (tests/integration/*.yaml)",
            "summary": {**passed["summary"], "flows": 0, "passed": 0}}
    root = _project(tmp_path / "none", none)
    r = gate.evaluate(root, gate.load_policy(root))
    assert [f["rule"] for f in r["findings"]] == ["integration.not_run"] and r["verdict"] == "needs_human"


def test_consumer_job_and_asyncapi_changes_trigger_integration():
    assert "integration" in plan(["src/orders/consumers/inventory.py"], DEFAULT_TRIGGERS, [])["needed"]
    assert "integration" in plan(["jobs/nightly_totals.py"], DEFAULT_TRIGGERS, [])["needed"]
    assert "integration" in plan(["src/main/java/shop/OrderListener.java"], DEFAULT_TRIGGERS, [])["needed"]
    assert "integration" in plan(["asyncapi.yaml"], DEFAULT_TRIGGERS, [])["needed"]
    assert "integration" not in plan(["docs/guide.md", "src/components/Button.tsx",
                                       "db/migrations/0002_index.sql"], DEFAULT_TRIGGERS, [])["needed"]
