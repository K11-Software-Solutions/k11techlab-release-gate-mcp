"""Diff-aware planning: which evidence a change needs, from real git diffs."""

import shutil
import subprocess
from pathlib import Path

import pytest

from k11_release_gate import gate
from k11_release_gate.cli import main as cli
from k11_release_gate.plan import DEFAULT_TRIGGERS, changed_files, plan

DEMO = Path(__file__).resolve().parents[1] / "demo"


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=cwd, check=True,
                   capture_output=True)


@pytest.fixture
def repo(tmp_path):
    """rc2's evidence in a git repo with one base commit."""
    root = tmp_path / "svc"
    shutil.copytree(DEMO / "rc2", root, ignore=shutil.ignore_patterns("release-gate"))
    (root / "README.md").write_text("service\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "base")
    git(root, "tag", "base")
    return root


def write(root, rel, text="x\n"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_plan_maps_changed_files_to_kinds():
    files = ["api/openapi.yaml", "web/src/components/Cart.tsx", "assistant/prompts/system.md", "README.md"]
    p = plan(files, DEFAULT_TRIGGERS, ["api_tests"])
    assert p["needed"] == ["ui_heal", "contract", "api_tests", "llm"]
    assert p["kinds"]["llm"]["matched_files"] == ["assistant/prompts/system.md"]
    assert p["kinds"]["api_tests"]["why"] == "always required by the policy"
    docs_only = plan(["README.md", "docs/guide.md"], DEFAULT_TRIGGERS, [])
    assert docs_only["needed"] == []


def test_changed_files_include_committed_and_uncommitted(repo):
    write(repo, "src/components/Button.tsx")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "ui")
    write(repo, "prompts/system.md")          # untracked
    (repo / "README.md").write_text("changed\n")  # modified, not committed
    assert changed_files(repo, "base") == ["README.md", "prompts/system.md", "src/components/Button.tsx"]
    assert changed_files(repo, "base", include_uncommitted=False) == ["src/components/Button.tsx"]
    with pytest.raises(ValueError, match="Invalid git ref"):
        changed_files(repo, "--output=/tmp/x")


def test_change_makes_missing_evidence_required(repo):
    pol = repo / ".qa-mcp/release-policy.yaml"
    pol.write_text("name: Diff-aware policy\nrequired: [api_tests]\nmax_age_hours: 87600\napprovers: ['@qa-lead']\n")
    shutil.rmtree(repo / ".qa-mcp/heal-report")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "policy")
    git(repo, "tag", "-f", "base")
    # a docs-only change: UI evidence isn't needed, so its absence is just "not tested"
    write(repo, "docs/notes.md")
    r = gate.evaluate(repo, gate.load_policy(repo), base="base")
    assert "evidence.missing" not in {f["rule"] for f in r["findings"]} and "ui_heal" in r["not_tested"]
    # a UI change: now UI evidence is required, and its absence blocks with the reason
    write(repo, "web/src/components/Cart.tsx")
    r = gate.evaluate(repo, gate.load_policy(repo), base="base")
    missing = [f for f in r["findings"] if f["rule"] == "evidence.missing"]
    assert r["verdict"] == "block" and missing[0]["kind"] == "ui_heal"
    assert "1 changed file(s) match its triggers" in missing[0]["message"]
    assert missing[0]["details"] == ["web/src/components/Cart.tsx"]
    assert r["plan"]["needed"] == ["ui_heal", "api_tests"]


def test_policy_triggers_override_defaults(repo):
    pol = repo / ".qa-mcp/release-policy.yaml"
    pol.write_text(pol.read_text() + "triggers:\n  llm: ['src/assistant/**']\n")
    p = gate.load_policy(repo)
    assert p.triggers["llm"] == ["src/assistant/**"]
    assert plan(["prompts/x.md"], p.triggers, [])["needed"] == []           # default llm triggers replaced
    assert plan(["src/assistant/flow.py"], p.triggers, [])["needed"] == ["llm"]
    with pytest.raises(ValueError, match="unknown trigger kind"):
        gate.parse_policy("triggers:\n  perf: ['**']\n", "p.yaml")


def test_cli_plan_and_evaluate_with_base(repo, monkeypatch, capsys):
    monkeypatch.setenv("QA_MCP_ROOT", str(repo))
    write(repo, "assistant/prompts/system.md")
    assert cli(["plan", "--base", "base"]) == 0
    out = capsys.readouterr().out
    assert "NEEDED  LLM red-team" in out and "1 file(s) changed since base" in out
    assert cli(["evaluate", "--base", "base", "--fail-on", "needs-human"]) == 1  # rc2 still needs a person
