"""The release gate on real evidence from the five K11 tools, plus policy, guardrails, CLI and MCP."""

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anyio
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from k11_release_gate import __version__, gate
from k11_release_gate.cli import main as cli
from k11_release_gate.evidence import collect, detect
from k11_release_gate.server import create_server

DEMO = Path(__file__).resolve().parents[1] / "demo"


@pytest.fixture
def rc(tmp_path):
    def make(name):
        dest = tmp_path / name
        shutil.copytree(DEMO / name, dest, ignore=shutil.ignore_patterns("release-gate"))
        return dest
    return make


def findings(result):
    return {f["rule"]: f for f in result["findings"]}


def test_every_tool_report_is_recognised(rc):
    ev = collect(rc("rc1"), gate.Policy().evidence)
    assert sorted(e.kind for e in ev) == ["api_tests", "contract", "junit", "llm", "ui_heal"]
    assert all(len(e.sha256) == 64 and e.generated_at for e in ev)
    f = {e.kind: e.facts for e in ev}
    assert f["api_tests"]["server_errors"] == 2 and f["contract"]["breaking"] == 6
    assert f["ui_heal"]["applied"] == 1 and len(f["ui_heal"]["unresolved"]) == 2
    assert (f["llm"]["grade"], f["llm"]["critical"]) == ("F", 6) and f["junit"]["tests"] == 16


def test_rc1_blocks_with_every_reason(rc):
    root = rc("rc1")
    r = gate.evaluate(root, gate.load_policy(root), "rc1")
    assert r["verdict"] == "block"
    fs = findings(r)
    for rule in ("api.server_error", "api.flow_failed", "contract.breaks_critical_consumer", "ui.real_failures",
                 "ui.unresolved_locators", "llm.critical", "llm.high"):
        assert fs[rule]["outcome"] == "block", rule
    assert fs["contract.escalation"]["outcome"] == "needs_human"
    assert fs["ui.healed"]["outcome"] == "conditional"
    assert len(fs["llm.high"]["details"]) == 13  # every finding of that severity, not a truncated list
    assert "billing-svc (critical, owner @team-billing)" in fs["contract.breaks_critical_consumer"]["details"][0]


def test_rc2_needs_a_named_person(rc):
    root = rc("rc2")
    r = gate.evaluate(root, gate.load_policy(root), "rc2")
    assert r["verdict"] == "needs_human"
    assert r["approvers"] == ["@qa-lead", "@ai-safety-lead"]
    assert set(findings(r)) == {"llm.inconclusive", "ui.healed", "llm.low"}


def test_policy_overrides_change_the_verdict(rc):
    root = rc("rc2")
    pol = root / ".qa-mcp/release-policy.yaml"
    pol.write_text(pol.read_text() + "rules:\n  llm.inconclusive: conditional\n")
    assert gate.evaluate(root, gate.load_policy(root))["verdict"] == "ship_with_conditions"
    pol.write_text(pol.read_text() + "  ui.healed: info\n")
    assert gate.evaluate(root, gate.load_policy(root))["verdict"] == "ship_with_conditions"  # llm.inconclusive still a condition
    pol.write_text(pol.read_text().replace("llm.inconclusive: conditional", "llm.inconclusive: info"))
    assert gate.evaluate(root, gate.load_policy(root))["verdict"] == "ship"
    pol.write_text(pol.read_text() + "  llm.low: off\n")
    r = gate.evaluate(root, gate.load_policy(root))
    assert "llm.low" not in findings(r) and r["policy"]["overrides"]["llm.low"] == "off"


def test_missing_and_stale_evidence(rc):
    root = rc("rc2")
    shutil.rmtree(root / "llm-assure-report")
    r = gate.evaluate(root, gate.load_policy(root))
    assert r["verdict"] == "block" and findings(r)["evidence.missing"]["kind"] == "llm"
    pol = gate.load_policy(root)
    pol.required = ["api_tests"]
    pol.max_age_hours = 1
    later = datetime.now(timezone.utc) + timedelta(days=3)
    r = gate.evaluate(root, pol, now=later)
    assert findings(r)["evidence.stale"]["outcome"] == "conditional"
    assert "LLM red-team" not in r["not_tested"] and "llm" in r["not_tested"]


def test_same_evidence_same_verdict(rc):
    root = rc("rc1")
    now = datetime(2026, 11, 13, 16, 0, tzinfo=timezone.utc)
    a = gate.evaluate(root, gate.load_policy(root), now=now)
    b = gate.evaluate(root, gate.load_policy(root), now=now)
    assert a == b


def test_policy_validation_and_paths(tmp_path):
    with pytest.raises(ValueError, match="unknown rule"):
        gate.parse_policy("rules:\n  llm.huge: block\n", "p.yaml")
    with pytest.raises(ValueError, match="outcome must be"):
        gate.parse_policy("rules:\n  llm.high: maybe\n", "p.yaml")
    with pytest.raises(ValueError, match="unknown key"):
        gate.parse_policy("requird: [api_tests]\n", "p.yaml")
    with pytest.raises(ValueError, match="inside the project"):
        collect(tmp_path, {"junit": ["../outside/*.xml"]})
    gate.parse_policy(gate.default_policy_text(), "default")  # the starter policy is valid
    assert detect({"something": "else"}) is None


def test_unreadable_evidence_is_reported_not_skipped(rc):
    root = rc("rc2")
    (root / ".qa-mcp/contract-report/contract-report.json").write_text("{ not json")
    r = gate.evaluate(root, gate.load_policy(root))
    assert findings(r)["evidence.unreadable"]["outcome"] == "needs_human"
    assert r["verdict"] == "block"  # contract evidence is required and now effectively missing


def test_cli(rc, monkeypatch, tmp_path):
    root = rc("rc1")
    out = tmp_path / "gh"
    monkeypatch.setenv("QA_MCP_ROOT", str(root))
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert cli(["evaluate", "--label", "rc1"]) == 1
    o = dict(line.split("=", 1) for line in out.read_text().splitlines())
    assert o["verdict"] == "block" and o["blockers"] == "7"
    md = (root / ".qa-mcp/release-gate/release-decision.md").read_text("utf8")
    assert "Release gate: 🔴 Block — rc1" in md and "| `.qa-mcp/heal-report/heal-report.json` |" in md
    assert cli(["evaluate", "--fail-on", "never"]) == 0
    assert cli(["evaluate", "--report-dir", "../escape"]) == 1
    root2 = rc("rc2")
    monkeypatch.setenv("QA_MCP_ROOT", str(root2))
    assert cli(["evaluate"]) == 0  # needs_human doesn't fail the default --fail-on block
    assert cli(["evaluate", "--fail-on", "needs-human"]) == 1


def test_mcp(rc, monkeypatch):
    root = rc("rc2")
    monkeypatch.setenv("QA_MCP_ROOT", str(root))

    async def go():
        async with create_connected_server_and_client_session(create_server()._mcp_server) as c:
            info = await c.initialize()
            assert (info.serverInfo.name, info.serverInfo.version) == ("k11-release-gate", __version__)
            names = sorted(t.name for t in (await c.list_tools()).tools)
            assert names == ["collect_evidence", "evaluate_release", "init_policy", "list_rules", "plan_checks"]

            def j(r):
                assert not r.isError, r.content[0].text
                return json.loads(r.content[0].text)

            rules = j(await c.call_tool("list_rules", {}))
            assert len(rules["rules"]) == 21
            ev = j(await c.call_tool("collect_evidence", {}))
            assert ev["missing_required"] == [] and len(ev["evidence"]) == 5
            res = j(await c.call_tool("evaluate_release", {"label": "rc2"}))
            assert res["verdict"] == "needs_human" and res["report"]["json"].endswith("release-decision.json")
            assert (await c.call_tool("init_policy", {})).isError  # won't overwrite
    anyio.run(go)
