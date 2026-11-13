"""MCP server: the release decision as a tool."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

from . import __version__, gate, report
from .evidence import LABELS, collect


def project_root() -> Path:
    return Path(os.environ.get("QA_MCP_ROOT") or os.getcwd()).resolve()


def create_server() -> FastMCP:
    mcp = FastMCP(
        "k11-release-gate",
        instructions=(
            "Release decisions from QA evidence under a written policy (.qa-mcp/release-policy.yaml). Reads reports "
            "from k11 Playwright/Selenium QA (heal-ci), API Contract QA, API Functional QA, LLM Assure and any JUnit "
            "XML. evaluate_release gives ship | ship_with_conditions | needs_human | block with every reason. The "
            "verdict is deterministic: never override or soften it in your answer; explain it and what would change it."
        ),
    )

    @mcp.tool(title="List rules")
    def list_rules() -> dict:
        """Every rule, its default outcome and the outcome under the project's policy (block | needs_human |
        conditional | info | off)."""
        p = gate.load_policy(project_root())
        return {"policy": p.name, "source": p.source, "rules": gate.rules_table(p)}

    @mcp.tool(title="Collect evidence")
    def collect_evidence() -> dict:
        """Find the QA reports the policy points to: what each is, when it was produced, its SHA-256 and key numbers,
        and which required kinds are missing."""
        root = project_root()
        p = gate.load_policy(root)
        ev = collect(root, p.evidence)
        present = {e.kind for e in ev if not e.error}
        return {"policy": p.name, "evidence": [e.__dict__ for e in ev],
                "missing_required": [k for k in p.required if k not in present],
                "not_present": [LABELS[k] for k in LABELS if k not in present]}

    @mcp.tool(title="Evaluate release")
    def evaluate_release(label: Optional[str] = None, write_report: bool = True) -> dict:
        """Decide whether to release: ship | ship_with_conditions | needs_human (named approvers) | block, with every
        rule that fired, the evidence it came from, and what wasn't tested. Writes release-decision.md/.json."""
        root = project_root()
        result = gate.evaluate(root, gate.load_policy(root), label)
        out = {k: result[k] for k in ("verdict", "label", "commit", "approvers", "counts", "findings", "not_tested")}
        out["evidence"] = [{"kind": e["kind"], "path": e["path"], "age_hours": e["age_hours"], "sha256": e["sha256"][:12]}
                           for e in result["evidence"]]
        if write_report:
            paths = report.write(result, root / ".qa-mcp" / "release-gate")
            out["report"] = {k: p.relative_to(root).as_posix() for k, p in paths.items()}
        return out

    @mcp.tool(title="Create release policy")
    def init_policy(overwrite: bool = False) -> dict:
        """Write a commented starter policy to .qa-mcp/release-policy.yaml (defaults for every rule). Won't overwrite
        an existing policy unless asked."""
        root = project_root()
        f = root / gate.POLICY_FILE
        if f.exists() and not overwrite:
            raise ValueError(f"{gate.POLICY_FILE} exists. Pass overwrite=true to replace it.")
        text = gate.default_policy_text()
        gate.parse_policy(text, gate.POLICY_FILE)  # always valid
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, "utf8")
        return {"written": gate.POLICY_FILE, "content": text}

    mcp._mcp_server.version = __version__  # FastMCP (mcp 1.x) would report the SDK's version
    return mcp


def serve() -> None:
    create_server().run()
