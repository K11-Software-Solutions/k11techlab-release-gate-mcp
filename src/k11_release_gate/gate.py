"""The release decision: evidence + a written policy -> one verdict, with every reason.

Outcomes, strongest first:
  block        don't release
  needs_human  release only with a named approver's sign-off (risk-proportionate human-in-the-loop)
  conditional  release, with conditions someone must meet (e.g. approve the locator-heal PR)
  info         recorded, no effect on the verdict

Verdict: block if any rule blocks; else needs_human; else ship_with_conditions; else ship.
The same evidence and policy always give the same verdict.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from . import __version__
from .evidence import KINDS, LABELS, Evidence, collect

OUTCOMES = ("block", "needs_human", "conditional", "info")
RANK = {o: i for i, o in enumerate(OUTCOMES)}
VERDICT = {"block": "block", "needs_human": "needs_human", "conditional": "ship_with_conditions", "info": "ship"}
POLICY_FILE = ".qa-mcp/release-policy.yaml"

DEFAULT_EVIDENCE = {
    "ui_heal": [".qa-mcp/heal-report/heal-report.json"],
    "contract": [".qa-mcp/contract-report/contract-report.json"],
    "api_tests": [".qa-mcp/api-test-report/api-test-report.json"],
    "llm": ["llm-assure-report/assessment.json", ".qa-mcp/llm-assure/assessment.json"],
    "junit": ["test-results/**/*.xml", "**/surefire-reports/TEST-*.xml", "junit*.xml"],
}


@dataclass
class Finding:
    rule: str
    outcome: str
    kind: str
    message: str
    evidence: str = ""  # file path
    details: list[str] = field(default_factory=list)


@dataclass
class Rule:
    id: str
    kind: str
    default: str
    title: str
    check: Callable[[dict, dict], list[tuple[str, list[str]]]]  # (facts, policy) -> [(message, details)]


def _n(x: int, one: str, many: str | None = None) -> str:
    return f"{x} {one if x == 1 else (many or one + 's')}"


RULES: list[Rule] = [
    # evidence (evaluated separately; listed so the policy can override them)
    Rule("evidence.missing", "evidence", "block", "Required evidence is missing", lambda f, p: []),
    Rule("evidence.stale", "evidence", "conditional", "Evidence is older than max_age_hours", lambda f, p: []),
    Rule("evidence.unreadable", "evidence", "needs_human", "An evidence file couldn't be read", lambda f, p: []),
    # API functional tests
    Rule("api.server_error", "api_tests", "block", "An API returned a 5xx during functional tests",
         lambda f, p: [(f"{_n(f['server_errors'], 'server error')} (5xx) in API tests", f["server_error_steps"])]
         if f.get("server_errors") else []),
    Rule("api.flow_failed", "api_tests", "block", "An API test flow failed",
         lambda f, p: [(f"{_n(f['failed'], 'API flow')} failed", f["failed_flows"])] if f.get("failed") else []),
    Rule("api.flow_not_run", "api_tests", "needs_human", "An API flow was blocked by guardrails or errored, so it proved nothing",
         lambda f, p: [(f"{_n(f['blocked'] + f['errors'], 'API flow')} didn't run (blocked or error)", f["not_run_flows"])]
         if f.get("blocked") or f.get("errors") else []),
    # API contract
    Rule("contract.breaks_critical_consumer", "contract", "block", "An API change breaks a critical consumer",
         lambda f, p: [(f"API change breaks {', '.join(c['consumer'] for c in crit)}",
                        [f"{c['consumer']} ({c['criticality']}, owner {c['owner'] or 'unknown'}): {_n(c['changes'], 'breaking change')}"
                         for c in crit])]
         if (crit := [c for c in f.get("consumers_broken", []) if c["criticality"] in p["critical_consumers"]]) else []),
    Rule("contract.breaks_consumer", "contract", "needs_human", "An API change breaks a (non-critical) consumer",
         lambda f, p: [(f"API change breaks {', '.join(c['consumer'] for c in other)}",
                        [f"{c['consumer']} ({c['criticality']}): {_n(c['changes'], 'breaking change')}" for c in other])]
         if (other := [c for c in f.get("consumers_broken", []) if c["criticality"] not in p["critical_consumers"]]) else []),
    Rule("contract.escalation", "contract", "needs_human", "The contract check asked for a person to decide",
         lambda f, p: [(f"Contract check escalated: {f['needs_human_reason']}", [])] if f.get("needs_human") else []),
    Rule("contract.breaking_unused", "contract", "conditional", "Breaking API changes that no known consumer uses",
         lambda f, p: [(f"{_n(f['breaking_unused'], 'breaking change')} with no known consumer: confirm the consumer list is complete", [])]
         if f.get("breaking_unused") else []),
    # UI tests with self-healing
    Rule("ui.real_failures", "ui_heal", "block", "UI tests failed for reasons other than locators",
         lambda f, p: [(f"{_n(len(f['other_failures']), 'UI test')} failed for reasons other than locators",
                        [f"{x['test']}: {x['error']}" for x in f["other_failures"]])] if f.get("other_failures") else []),
    Rule("ui.unresolved_locators", "ui_heal", "block", "Broken locators that weren't safely healed",
         lambda f, p: [(f"{_n(len(f['unresolved']), 'broken locator')} still unresolved (reverted, needs review or not found)",
                        [f"{x['test']}: {x['locator']} ({x['outcome'].replace('_', ' ')})" for x in f["unresolved"]])]
         if f.get("unresolved") else []),
    Rule("ui.healed", "ui_heal", "conditional", "Locators were healed and verified; the heal PR needs approval",
         lambda f, p: [(f"{_n(f['applied'], 'locator')} healed and verified: approve the heal pull request",
                        [f"{x['test']}: {x['from']} → {x['to']} ({round((x['confidence'] or 0) * 100)}%)" for x in f["healed"]])]
         if f.get("applied") else []),
    Rule("ui.suggested", "ui_heal", "conditional", "Heals were suggested (dry run) but not applied",
         lambda f, p: [(f"{_n(f['suggested'], 'locator heal')} suggested but not applied", [])] if f.get("suggested") else []),
    # LLM red-team
    Rule("llm.critical", "llm", "block", "Critical LLM security finding",
         lambda f, p: [(f"{_n(f['critical'], 'critical LLM finding')}", _llm(f, "critical"))] if f.get("critical") else []),
    Rule("llm.high", "llm", "block", "High-severity LLM security finding",
         lambda f, p: [(f"{_n(f['high'], 'high-severity LLM finding')}", _llm(f, "high"))] if f.get("high") else []),
    Rule("llm.medium", "llm", "conditional", "Medium-severity LLM security finding",
         lambda f, p: [(f"{_n(f['medium'], 'medium-severity LLM finding')}: plan a fix", _llm(f, "medium"))] if f.get("medium") else []),
    Rule("llm.low", "llm", "info", "Low-severity LLM security finding",
         lambda f, p: [(f"{_n(f['low'], 'low-severity LLM finding')}", _llm(f, "low"))] if f.get("low") else []),
    Rule("llm.inconclusive", "llm", "needs_human", "LLM probes that need review or errored",
         lambda f, p: [(f"{_n(f['needs_review'] + f['errors'], 'LLM probe')} inconclusive (needs review or error)", [])]
         if f.get("needs_review") or f.get("errors") else []),
    # Any JUnit suite
    Rule("junit.failures", "junit", "block", "Test failures or errors in a JUnit report",
         lambda f, p: [(f"{_n(f['failures'] + f['errors'], 'test')} failed", f["failed_tests"])]
         if f.get("failures") or f.get("errors") else []),
    Rule("junit.skipped", "junit", "info", "Skipped tests",
         lambda f, p: [(f"{_n(f['skipped'], 'test')} skipped", [])] if f.get("skipped") else []),
]
RULE_IDS = {r.id: r for r in RULES}


def _llm(f: dict, sev: str) -> list[str]:
    return [f"{x['probe']} {x['name']} ({x['suite']})" for x in f.get("top_findings", []) if x["severity"] == sev]


# ---- policy ---------------------------------------------------------------------------------

@dataclass
class Policy:
    name: str = "Default release policy"
    evidence: dict[str, list[str]] = field(default_factory=lambda: {k: list(v) for k, v in DEFAULT_EVIDENCE.items()})
    required: list[str] = field(default_factory=lambda: ["api_tests"])
    max_age_hours: float = 24
    critical_consumers: list[str] = field(default_factory=lambda: ["critical", "high"])
    approvers: list[str] = field(default_factory=list)
    overrides: dict[str, str] = field(default_factory=dict)
    source: str = "built-in defaults"
    sha256: str = ""

    def outcome(self, rule_id: str) -> str:
        return self.overrides.get(rule_id, RULE_IDS[rule_id].default)


POLICY_KEYS = {"name", "evidence", "required", "max_age_hours", "critical_consumers", "approvers", "rules"}


def parse_policy(text: str, source: str) -> Policy:
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"{source}: invalid YAML: {str(e).splitlines()[0]}") from None
    if not isinstance(data, dict):
        raise ValueError(f"{source}: the policy must be a mapping")
    unknown = set(data) - POLICY_KEYS
    if unknown:
        raise ValueError(f"{source}: unknown key(s) {sorted(unknown)}; allowed: {sorted(POLICY_KEYS)}")
    p = Policy(source=source, sha256=hashlib.sha256(text.encode()).hexdigest())
    p.name = str(data.get("name", p.name))
    if "evidence" in data:
        ev = data["evidence"] or {}
        bad = set(ev) - set(KINDS)
        if bad:
            raise ValueError(f"{source}: unknown evidence kind(s) {sorted(bad)}; known: {list(KINDS)}")
        p.evidence = {k: ([v] if isinstance(v, str) else list(v or [])) for k, v in ev.items()}
    p.required = list(data.get("required", p.required) or [])
    bad = set(p.required) - set(KINDS)
    if bad:
        raise ValueError(f"{source}: unknown required kind(s) {sorted(bad)}; known: {list(KINDS)}")
    missing_patterns = [k for k in p.required if k not in p.evidence]
    if missing_patterns:
        raise ValueError(f"{source}: required kind(s) {missing_patterns} have no evidence patterns")
    p.max_age_hours = float(data.get("max_age_hours", p.max_age_hours))
    p.critical_consumers = list(data.get("critical_consumers", p.critical_consumers))
    p.approvers = list(data.get("approvers", p.approvers) or [])
    for rid, outcome in (data.get("rules") or {}).items():
        if rid not in RULE_IDS:
            raise ValueError(f"{source}: unknown rule '{rid}'. Use list_rules to see them.")
        outcome = "off" if outcome is False else str(outcome)
        if outcome not in OUTCOMES + ("off",):
            raise ValueError(f"{source}: rule '{rid}' outcome must be one of {list(OUTCOMES) + ['off']}")
        p.overrides[rid] = outcome
    return p


def load_policy(root: Path, path: str | None = None) -> Policy:
    f = Path(root) / (path or POLICY_FILE)
    if not f.is_file():
        if path:
            raise ValueError(f"Policy not found: {path}")
        return Policy()
    return parse_policy(f.read_text("utf8"), f.relative_to(root).as_posix() if f.is_relative_to(root) else str(f))


def default_policy_text() -> str:
    lines = ["# Release policy for k11 Release Gate. Every rule and its default outcome: k11-release-gate-mcp rules",
             "name: Release policy", "",
             "# Where each kind of evidence is written (paths/globs inside the project).", "evidence:"]
    for k, v in DEFAULT_EVIDENCE.items():
        lines.append(f"  {k}: {json_list(v)}")
    lines += ["", "# Kinds that must be present; missing ones trigger evidence.missing (block by default).",
              "required: [api_tests]", "", "# Evidence older than this triggers evidence.stale.", "max_age_hours: 24", "",
              "# Consumer criticalities (from consumers.yaml) whose breakage blocks a release.",
              "critical_consumers: [critical, high]", "",
              "# Who signs off when the verdict is needs_human.", "approvers: []", "",
              "# Change a rule's outcome: block | needs_human | conditional | info | off", "rules:",
              "  # llm.medium: needs_human", "  # ui.healed: info", ""]
    return "\n".join(lines)


def json_list(v: list[str]) -> str:
    return "[" + ", ".join(f'"{x}"' for x in v) + "]"


# ---- evaluation ------------------------------------------------------------------------------

def _git_commit(root: Path) -> str | None:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10)
        return (r.stdout.strip() or None) if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def evaluate(root: Path, policy: Policy, label: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    root = Path(root).resolve()
    evidence = collect(root, policy.evidence, now)
    findings: list[Finding] = []

    def add(rule_id: str, kind: str, message: str, path: str = "", details: list[str] | None = None):
        outcome = policy.outcome(rule_id)
        if outcome != "off":
            findings.append(Finding(rule_id, outcome, kind, message, path, details or []))

    present = {e.kind for e in evidence if not e.error}
    for kind in policy.required:
        if kind not in present:
            add("evidence.missing", kind, f"No {LABELS[kind]} evidence found (looked in {', '.join(policy.evidence[kind])})")
    for e in evidence:
        if e.error:
            add("evidence.unreadable", e.kind, f"{e.path} couldn't be read: {e.error}", e.path)
            continue
        if e.age_hours is not None and e.age_hours > policy.max_age_hours:
            add("evidence.stale", e.kind, f"{e.path} is {e.age_hours:.0f} h old (limit {policy.max_age_hours:g} h)", e.path)
        for rule in RULES:
            if rule.kind != e.kind:
                continue
            for message, details in rule.check(e.facts, {"critical_consumers": policy.critical_consumers}):
                add(rule.id, e.kind, message, e.path, details)

    worst = min((f.outcome for f in findings), key=lambda o: RANK[o], default="info")
    verdict = VERDICT[worst]
    not_tested = [k for k in KINDS if k not in present and k not in policy.required]
    findings.sort(key=lambda f: (RANK[f.outcome], KINDS.index(f.kind) if f.kind in KINDS else 9, f.rule))
    return {
        "tool": f"k11-release-gate-mcp {__version__}",
        "evaluatedAt": now.isoformat(timespec="seconds"),
        "label": label,
        "commit": _git_commit(root),
        "verdict": verdict,
        "approvers": policy.approvers if verdict == "needs_human" else [],
        "policy": {"name": policy.name, "source": policy.source, "sha256": policy.sha256 or None,
                   "required": policy.required, "max_age_hours": policy.max_age_hours, "overrides": policy.overrides},
        "counts": {o: sum(f.outcome == o for f in findings) for o in OUTCOMES},
        "findings": [f.__dict__ for f in findings],
        "evidence": [e.__dict__ for e in evidence],
        "not_tested": not_tested,
    }


def rules_table(policy: Policy) -> list[dict]:
    return [{"id": r.id, "kind": r.kind, "title": r.title, "default": r.default, "outcome": policy.outcome(r.id),
             "overridden": r.id in policy.overrides} for r in RULES]
