"""Find and read QA evidence, whatever produced it.

Kinds, recognised from their content (not their file name):
  ui_heal     heal-report.json from k11 Playwright QA or k11 Selenium QA (heal-ci)
  contract    contract-report.json from k11 API Contract QA (contract-ci)
  api_tests   api-test-report.json from k11 API Functional QA
  llm         assessment.json from LLM Assure (k11-llm-assure-mcp)
  perf        perf-report.json from k11 Performance QA (load tests, SLOs, regressions)
  security    security-report.json from k11 API Security QA (OWASP API tests + scanner SARIF)
  junit       any JUnit XML (pytest, Maven Surefire, Gradle, Jest, Playwright, ...)

Each file becomes an Evidence record with its SHA-256, timestamp, age and a small set of
normalised facts the rules read. Files that can't be read are kept as 'unreadable', never skipped.
"""

from __future__ import annotations

import glob
import hashlib
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

KINDS = ("ui_heal", "contract", "api_tests", "llm", "perf", "security", "junit")
LABELS = {"ui_heal": "UI tests (self-healing)", "contract": "API contract", "api_tests": "API functional tests",
          "llm": "LLM red-team", "perf": "Performance (load tests)", "security": "Security (API tests and scanners)", "junit": "Test suites (JUnit)"}
MAX_BYTES = 50 * 1024 * 1024


@dataclass
class Evidence:
    kind: str
    path: str
    sha256: str
    generated_at: str | None
    age_hours: float | None
    tool: str = ""
    facts: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def detect(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    tool = str(data.get("tool", ""))
    if tool.startswith("k11-api-security-qa-mcp") or ("api" in data and "scanners" in data and "summary" in data):
        return "security"
    if tool.startswith("k11-performance-qa-mcp") or ("endpoints" in data and "slos" in data and "findings" in data):
        return "perf"
    if "heal-ci" in tool or ("items" in data and isinstance(data.get("counts"), dict) and "applied" in data["counts"]):
        return "ui_heal"
    if tool.startswith("k11-api-contract-qa-mcp") or ("impact" in data and "changes" in data):
        return "contract"
    if tool.startswith("k11-api-functional-qa-mcp") or ("flows" in data and isinstance(data.get("summary"), dict)
                                                         and "server_errors" in data["summary"]):
        return "api_tests"
    if "failures_by_severity" in data and "results" in data:
        return "llm"
    return None


def _facts(kind: str, d: dict) -> tuple[dict, str | None, str]:
    """(facts, generated_at, tool)"""
    if kind == "ui_heal":
        c = d.get("counts") or {}
        return ({"mode": d.get("mode"), "tests_run": d.get("testsRun", 0), "failures": d.get("failures", 0),
                 "applied": c.get("applied", 0), "suggested": c.get("suggested", 0), "reverted": c.get("reverted", 0),
                 "needs_review": c.get("needs_review", 0), "not_found": c.get("not_found", 0),
                 "unresolved": [{"test": i.get("test"), "locator": i.get("locator"), "outcome": i.get("outcome")}
                                for i in d.get("items", []) if i.get("outcome") in ("reverted", "needs_review", "not_found")][:20],
                 "healed": [{"test": i.get("test"), "from": i.get("locator"), "to": i.get("suggestion"),
                             "confidence": i.get("confidence")} for i in d.get("items", []) if i.get("outcome") == "applied"][:20],
                 "other_failures": [{"test": f.get("test"), "error": (f.get("error") or "")[:200]}
                                    for f in d.get("otherFailures", [])][:20]},
                d.get("generatedAt"), str(d.get("tool", "")))
    if kind == "contract":
        imp = d.get("impact") or {}
        return ({"api": d.get("api"), "base": d.get("base"), "head": d.get("head"),
                 "verdict": imp.get("verdict"), "needs_human": bool(imp.get("needs_human")),
                 "needs_human_reason": imp.get("needs_human_reason", ""),
                 "breaking": (d.get("summary") or {}).get("breaking", 0),
                 "consumers_broken": [{"consumer": b.get("consumer"), "criticality": b.get("criticality", "medium"),
                                       "owner": b.get("owner", ""), "changes": len(b.get("changes", []))}
                                      for b in imp.get("consumers_broken", [])],
                 "breaking_unused": len(imp.get("breaking_without_known_consumers", []))},
                d.get("generatedAt"), str(d.get("tool", "")))
    if kind == "api_tests":
        s = d.get("summary") or {}
        flows = d.get("flows", [])
        return ({"environment": d.get("environment"), "flows": s.get("flows", len(flows)), "passed": s.get("passed", 0),
                 "failed": s.get("failed", 0), "blocked": s.get("blocked", 0), "errors": s.get("error", 0),
                 "server_errors": s.get("server_errors", 0),
                 "failed_flows": [f.get("name") for f in flows if f.get("status") == "failed"][:20],
                 "not_run_flows": [f.get("name") for f in flows if f.get("status") in ("blocked", "error")][:20],
                 "server_error_steps": [f"{f.get('name')}: {st.get('name')}" for f in flows for st in f.get("steps", [])
                                        if not st.get("cleanup") and isinstance((st.get("response") or {}).get("status"), int)
                                        and st["response"]["status"] >= 500][:20]},
                d.get("generatedAt"), str(d.get("tool", "")))
    if kind == "llm":
        sev = d.get("failures_by_severity") or {}
        counts = d.get("counts") or {}
        failed = [r for r in d.get("results", []) if r.get("status") == "fail"]
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        failed.sort(key=lambda r: (order.get(r.get("severity"), 9), r.get("probe_id", "")))
        return ({"target": d.get("target"), "grade": d.get("grade"), "risk_score": d.get("risk_score"),
                 "critical": sev.get("critical", 0), "high": sev.get("high", 0), "medium": sev.get("medium", 0),
                 "low": sev.get("low", 0), "needs_review": counts.get("needs_review", 0), "errors": counts.get("error", 0),
                 "top_findings": [{"probe": r.get("probe_id"), "name": r.get("probe_name"), "severity": r.get("severity"),
                                   "suite": r.get("suite")} for r in failed[:200]]},
                d.get("finished_at") or d.get("started_at"), f"llm-assure {d.get('toolkit_version', '')}".strip())
    if kind == "perf":
        s = d.get("summary") or {}
        fs = d.get("findings") or []

        def msgs(*types: str) -> list[str]:
            return [f.get("message", "") for f in fs if f.get("type") in types][:20]

        return ({"environment": d.get("environment"), "scenario": d.get("scenario"), "engine": d.get("engine"),
                 "status": d.get("status"), "reason": d.get("reason", ""), "requests": s.get("requests", 0),
                 "error_rate": s.get("error_rate", 0), "p95": s.get("p95"), "verdict": s.get("verdict"),
                 "server_errors": msgs("server_errors"), "slo_breaches": msgs("slo_breach"),
                 "regressions": msgs("regression", "error_rate_regression"),
                 "insufficient_samples": len([f for f in fs if f.get("type") == "insufficient_samples"]),
                 "has_baseline": d.get("comparison") is not None},
                d.get("generatedAt"), str(d.get("tool", "")))
    if kind == "security":
        s = d.get("summary") or {}
        api = d.get("api") or {}
        counted = [f for f in (d.get("scanners") or {}).get("findings", []) if f.get("status") in ("new", "acceptance_expired")]

        def lines(sev: str) -> list[str]:
            out = [f"{f.get('id')} {f.get('title')} ({f.get('endpoint')})" for f in api.get("findings", []) if f.get("severity") == sev]
            out += [f"{f.get('tool')} {f.get('rule')} at {f.get('path')}{':' + str(f['line']) if f.get('line') else ''}"
                    + (" (acceptance expired)" if f.get("status") == "acceptance_expired" else "")
                    for f in counted if f.get("severity") == sev]
            return out[:20]

        tests = s.get("api_tests") or {}
        return ({"environment": d.get("environment"), "status": d.get("status"), "reason": d.get("reason", ""),
                 "critical": lines("critical"), "high": lines("high"), "medium": lines("medium"), "low": len(lines("low")),
                 "expired_acceptances": [f"{f.get('rule')} (owner {f.get('acceptance', {}).get('owner')}, expired {f.get('acceptance', {}).get('expires')})"
                                         for f in counted if f.get("status") == "acceptance_expired"][:20],
                 "tests_failed": tests.get("failed", 0), "tests_inconclusive": tests.get("inconclusive", 0),
                 "tests_not_run": tests.get("not_run", 0)},
                d.get("generatedAt"), str(d.get("tool", "")))
    return {}, None, ""


def _junit(path: Path) -> tuple[dict, str | None]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")
    if root.tag not in ("testsuite", "testsuites"):
        raise ValueError("not JUnit XML")
    tests = failures = errors = skipped = 0
    failed: list[str] = []
    stamp = None
    for s in suites:
        stamp = stamp or s.get("timestamp")
        for tc in s.iter("testcase"):
            tests += 1
            name = f"{tc.get('classname', '')}.{tc.get('name', '')}".strip(".")
            if tc.find("failure") is not None:
                failures += 1
                failed.append(name)
            elif tc.find("error") is not None:
                errors += 1
                failed.append(name)
            elif tc.find("skipped") is not None:
                skipped += 1
    return ({"tests": tests, "failures": failures, "errors": errors, "skipped": skipped, "failed_tests": failed[:20]}, stamp)


def read(path: Path, root: Path, now: datetime | None = None) -> Evidence | None:
    """An Evidence record, or None when the file isn't QA evidence we recognise."""
    now = now or datetime.now(timezone.utc)
    rel = path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        return Evidence("unknown", rel, hashlib.sha256(raw).hexdigest(), None, None, error="file larger than 50 MB")
    digest = hashlib.sha256(raw).hexdigest()
    mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    if path.suffix.lower() == ".xml":
        try:
            facts, stamp = _junit(path)
        except (ET.ParseError, ValueError):
            return None
        t = _parse_time(stamp) or mtime
        return Evidence("junit", rel, digest, t.isoformat(timespec="seconds"), round((now - t).total_seconds() / 3600, 2),
                        "junit", facts)
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as e:
        return Evidence("unknown", rel, digest, None, None, error=f"not valid JSON: {str(e)[:120]}")
    kind = detect(data)
    if kind is None:
        return None
    facts, stamp, tool = _facts(kind, data)
    t = _parse_time(stamp) or mtime
    return Evidence(kind, rel, digest, t.isoformat(timespec="seconds"), round((now - t).total_seconds() / 3600, 2), tool, facts)


def collect(root: Path, patterns: dict[str, list[str]], now: datetime | None = None) -> list[Evidence]:
    """Evidence from the policy's file patterns (relative to the project; never outside it)."""
    root = Path(root).resolve()
    seen: set[Path] = set()
    out: list[Evidence] = []
    for kind, globs in patterns.items():
        for pattern in globs:
            if ".." in Path(pattern).parts or Path(pattern).is_absolute():
                raise ValueError(f"Evidence pattern must stay inside the project: {pattern}")
            for hit in sorted(glob.glob(str(root / pattern), recursive=True)):
                p = Path(hit).resolve()
                if p in seen or not p.is_file() or (root not in p.parents):
                    continue
                seen.add(p)
                ev = read(p, root, now)
                if ev is None:
                    continue
                if ev.kind != kind and ev.kind != "unknown":
                    ev.facts["listed_under"] = kind  # found via another pattern; trust the content
                if ev.kind == "unknown":
                    ev.kind = kind
                out.append(ev)
    return out
