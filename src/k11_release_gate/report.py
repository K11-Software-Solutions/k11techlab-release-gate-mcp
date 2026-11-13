"""The release decision record: Markdown (PR comment / step summary) and JSON (audit trail)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .evidence import LABELS

HEAD = {"ship": "🟢 Ship", "ship_with_conditions": "🟡 Ship with conditions",
        "needs_human": "🟠 Needs a person's sign-off", "block": "🔴 Block"}
SECTION = {"block": "Blockers", "needs_human": "Needs a person", "conditional": "Conditions", "info": "Notes"}


def _summary_cell(e: dict) -> str:
    f, k = e["facts"], e["kind"]
    if e.get("error"):
        return f"unreadable: {e['error']}"
    if k == "api_tests":
        return f"{f['passed']}/{f['flows']} flows passed, {f['server_errors']} server errors"
    if k == "contract":
        return f"{f['breaking']} breaking, {len(f['consumers_broken'])} consumer(s) affected"
    if k == "ui_heal":
        return (f"{f['applied']} healed, {len(f['unresolved'])} unresolved, "
                f"{len(f['other_failures'])} other failure(s)")
    if k == "llm":
        return (f"grade {f['grade']}, critical {f['critical']}, high {f['high']}, medium {f['medium']}, low {f['low']}")
    if k == "junit":
        return f"{f['tests']} tests, {f['failures'] + f['errors']} failed, {f['skipped']} skipped"
    return ""


def to_markdown(r: dict[str, Any]) -> str:
    v = r["verdict"]
    title = f"## Release gate: {HEAD[v]}" + (f" — {r['label']}" if r.get("label") else "")
    L = [title, ""]
    c = r["counts"]
    L.append(f"{c['block']} blocker(s), {c['needs_human']} needing a person, {c['conditional']} condition(s). "
             f"Policy **{r['policy']['name']}** ({r['policy']['source']}).")
    if r.get("commit"):
        L[-1] += f" Commit `{r['commit'][:12]}`."
    L.append("")
    if v == "needs_human":
        who = ", ".join(r["approvers"]) if r["approvers"] else "an approver (none named in the policy)"
        L += [f"> **Sign-off needed from {who}** before release.", ""]
    for outcome in ("block", "needs_human", "conditional", "info"):
        fs = [f for f in r["findings"] if f["outcome"] == outcome]
        if not fs:
            continue
        L += [f"### {SECTION[outcome]}", ""]
        for f in fs:
            L.append(f"- **{f['message']}** (`{f['rule']}`" + (f", {f['evidence']}" if f.get("evidence") else "") + ")")
            for d in f["details"][:8]:
                L.append(f"  - {d}")
            if len(f["details"]) > 8:
                L.append(f"  - … and {len(f['details']) - 8} more")
        L.append("")
    L += ["### Evidence", "", "| Area | File | Result | Age | SHA-256 |", "|---|---|---|---|---|"]
    for e in r["evidence"]:
        age = f"{e['age_hours']:.1f} h" if e.get("age_hours") is not None else "–"
        L.append(f"| {LABELS.get(e['kind'], e['kind'])} | `{e['path']}` | {_summary_cell(e)} | {age} | `{e['sha256'][:12]}` |")
    if not r["evidence"]:
        L.append("| – | no evidence found | | | |")
    L.append("")
    if r["not_tested"]:
        L += ["**Not tested** (no evidence, not required by the policy): " + ", ".join(LABELS[k] for k in r["not_tested"]), ""]
    L.append(f"<sub>Decided by {r['tool']} at {r['evaluatedAt']}, deterministically from the evidence and policy above. "
             "Full record: release-decision.json.</sub>")
    return "\n".join(L) + "\n"


def write(r: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {"markdown": out_dir / "release-decision.md", "json": out_dir / "release-decision.json"}
    paths["markdown"].write_text(to_markdown(r), "utf8")
    paths["json"].write_text(json.dumps(r, indent=2, ensure_ascii=False) + "\n", "utf8")
    return paths
