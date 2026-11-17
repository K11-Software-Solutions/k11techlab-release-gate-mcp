"""Which checks does this change need? Changed files (git diff against a base) -> evidence kinds.

Policies map file patterns to kinds under ``triggers:``; the defaults below cover common layouts.
A kind is needed when it is always required by the policy, or when a changed file matches one of
its triggers. The plan is deterministic and recorded in the decision, so "why was the LLM red-team
required for this release?" always has an answer.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
from pathlib import Path
from typing import Any

from .evidence import KINDS, LABELS

DEFAULT_TRIGGERS: dict[str, list[str]] = {
    "contract": ["**/openapi*.yaml", "**/openapi*.yml", "**/openapi*.json", "**/swagger*.json", "**/swagger*.yaml",
                 "**/*.graphql", "**/*.graphqls", "**/*.proto", "**/asyncapi*.yaml", "**/asyncapi*.yml", "**/*.wsdl"],
    "api_tests": ["**/api/**", "**/routes/**", "**/controllers/**", "**/handlers/**", "**/endpoints/**",
                  "**/services/**", "**/migrations/**", "**/*.sql", "**/openapi*.yaml", "**/openapi*.json",
                  "tests/api/**"],
    "ui_heal": ["**/*.tsx", "**/*.jsx", "**/*.vue", "**/*.svelte", "**/*.html", "**/*.css", "**/*.scss",
                "**/components/**", "**/pages/**", "**/templates/**", "**/views/**", "tests/e2e/**", "tests/ui/**"],
    "llm": ["**/prompts/**", "**/*.prompt", "**/*prompt*.md", "**/*prompt*.txt", "**/llm/**", "**/agents/**",
            "**/rag/**", "**/guardrails/**", "**/chatbot/**"],
    "perf": ["**/migrations/**", "**/*.sql", "**/queries/**", "**/repositories/**", "**/repository/**", "**/dao/**",
             "**/cache/**", "**/caching/**", "**/db/**", "**/database/**", "**/perf/**", "tests/perf/**",
             ".qa-mcp/perf.yaml", "**/*.k6.js", "**/k6/**", "**/nginx*.conf", "**/gunicorn*.py", "**/pool*.yaml"],
    "security": ["**/auth/**", "**/authn/**", "**/authz/**", "**/security/**", "**/permissions/**", "**/policies/**",
                 "**/middleware/**", "**/*auth*.py", "**/*auth*.ts", "**/*Auth*.java", "**/*Security*.java",
                 "**/routes/**", "**/controllers/**", "**/handlers/**", "**/requirements*.txt", "**/pyproject.toml",
                 "**/package.json", "**/package-lock.json", "**/pom.xml", "**/build.gradle*", "**/go.mod",
                 "**/Dockerfile", ".qa-mcp/security.yaml", ".qa-mcp/security-accepted.yaml"],
    "integration": ["**/consumers/**", "**/consumer/**", "**/producers/**", "**/producer/**", "**/listeners/**",
                    "**/messaging/**", "**/events/**", "**/kafka/**", "**/queues/**", "**/streams/**", "**/jobs/**",
                    "**/batch/**", "**/schedulers/**", "**/workers/**", "**/middleware/**",
                    "**/*Consumer*.java", "**/*Listener*.java", "**/*Producer*.java", "**/*consumer*.py",
                    "**/*producer*.py", "**/*worker*.py", "**/asyncapi*.yaml", "**/asyncapi*.yml",
                    "tests/integration/**", ".qa-mcp/integration.yaml"],
}
HOW = {
    "ui_heal": "k11 Playwright QA or Selenium QA: heal-ci (or run_tests + heal_locator)",
    "contract": "k11 API Contract QA: contract-ci (or assess_impact with write_report)",
    "api_tests": "k11 API Functional QA: run (or run_flows)",
    "llm": "LLM Assure: llm-assure run (or run_assessment)",
    "perf": "k11 Performance QA: k11-performance-qa-mcp run (or run_load_test)",
    "security": "k11 API Security QA: k11-api-security-qa-mcp run (or run_security_tests)",
    "integration": "k11 Integration QA: k11-integration-qa-mcp run (or run_integration_tests)",
    "junit": "your existing test suites with JUnit XML output",
}
REF = re.compile(r"^[\w./~^@{}-]+$")


def _match(path: str, pattern: str) -> bool:
    if fnmatch.fnmatch(path, pattern):
        return True
    return pattern.startswith("**/") and fnmatch.fnmatch(path, pattern[3:])


def changed_files(root: Path, base: str, include_uncommitted: bool = True) -> list[str]:
    if not REF.match(base) or base.startswith("-"):
        raise ValueError(f"Invalid git ref: {base!r}")

    def git(*args: str) -> list[str]:
        r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60)
        if r.returncode != 0:
            msg = (r.stderr.strip().splitlines() or ["git error"])[-1]
            raise ValueError(f"git {' '.join(args[:2])} failed: {msg}")
        return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]

    files = set(git("diff", "--name-only", f"{base}...HEAD"))
    if include_uncommitted:
        files |= set(git("diff", "--name-only", "HEAD"))
        files |= set(git("ls-files", "--others", "--exclude-standard"))
    return sorted(f.replace("\\", "/") for f in files)


def plan(files: list[str], triggers: dict[str, list[str]], always: list[str]) -> dict[str, Any]:
    kinds: dict[str, dict] = {}
    for kind in KINDS:
        pats = triggers.get(kind, [])
        hits = [f for f in files if any(_match(f, p) for p in pats)]
        needed = kind in always or bool(hits)
        why = ("always required by the policy" if kind in always else
               f"{len(hits)} changed file(s) match its triggers" if hits else "no changed file matches its triggers")
        kinds[kind] = {"label": LABELS[kind], "needed": needed, "why": why, "matched_files": hits[:15],
                       "matched_count": len(hits), "how": HOW[kind]}
    return {"changed_files": len(files), "needed": [k for k, v in kinds.items() if v["needed"]], "kinds": kinds}
