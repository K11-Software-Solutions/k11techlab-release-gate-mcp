"""Command line: start the MCP server (default), evaluate a release in CI, list rules, or create a policy."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__

USAGE = f"""k11-release-gate-mcp {__version__}

Usage:
  k11-release-gate-mcp                         start the MCP server on stdio
  k11-release-gate-mcp evaluate [options]      decide: ship | ship_with_conditions | needs_human | block
  k11-release-gate-mcp rules                   list every rule and its outcome under the policy
  k11-release-gate-mcp init                    write a starter .qa-mcp/release-policy.yaml
  k11-release-gate-mcp --version

evaluate options:
  --label TEXT       release name or version shown in the report (e.g. v2.4.0)
  --policy PATH      default .qa-mcp/release-policy.yaml (built-in defaults if missing)
  --report-dir PATH  default .qa-mcp/release-gate
  --fail-on LEVEL    block (default) | needs-human | conditions | never

The project is QA_MCP_ROOT or the current directory.
"""

FAIL_ON = {"block": {"block"}, "needs-human": {"block", "needs_human"},
           "conditions": {"block", "needs_human", "ship_with_conditions"}, "never": set()}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        from .server import serve

        serve()
        return 0
    cmd = argv[0]
    if cmd in ("--version", "-v"):
        print(__version__)
        return 0
    if cmd in ("--help", "-h", "help"):
        print(USAGE)
        return 0
    from . import gate, report

    root = Path(os.environ.get("QA_MCP_ROOT") or os.getcwd()).resolve()
    if cmd == "rules":
        try:
            p = gate.load_policy(root)
        except ValueError as e:
            print(f"policy error: {e}", file=sys.stderr)
            return 1
        print(f"{'rule':34} {'kind':10} {'outcome':12} title")
        for r in gate.rules_table(p):
            print(f"{r['id']:34} {r['kind']:10} {r['outcome'] + ('*' if r['overridden'] else ''):12} {r['title']}")
        return 0
    if cmd == "init":
        f = root / gate.POLICY_FILE
        if f.exists():
            print(f"{gate.POLICY_FILE} already exists", file=sys.stderr)
            return 1
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(gate.default_policy_text(), "utf8")
        print(f"wrote {gate.POLICY_FILE}")
        return 0
    if cmd != "evaluate":
        print(f"Unknown command: {cmd}\n\n{USAGE}", file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser(prog="k11-release-gate-mcp evaluate")
    ap.add_argument("--label")
    ap.add_argument("--policy")
    ap.add_argument("--report-dir", default=".qa-mcp/release-gate")
    ap.add_argument("--fail-on", default="block", choices=list(FAIL_ON))
    a = ap.parse_args(argv[1:])
    out_dir = (root / a.report_dir).resolve()
    if root not in out_dir.parents and out_dir != root:
        print("--report-dir must be inside the project", file=sys.stderr)
        return 1
    try:
        result = gate.evaluate(root, gate.load_policy(root, a.policy), a.label)
    except ValueError as e:
        print(f"release gate failed: {e}", file=sys.stderr)
        return 1
    paths = report.write(result, out_dir)
    c = result["counts"]
    print(f"{result['verdict']}: {c['block']} blocker(s), {c['needs_human']} needing a person, "
          f"{c['conditional']} condition(s). Report: {paths['markdown']}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf8") as fh:
            fh.write(f"verdict={result['verdict']}\nblockers={c['block']}\nneeds_human={c['needs_human']}\n"
                     f"conditions={c['conditional']}\nreport={paths['markdown']}\nreport_json={paths['json']}\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf8") as fh:
            fh.write(paths["markdown"].read_text("utf8") + "\n")
    return 1 if result["verdict"] in FAIL_ON[a.fail_on] else 0


if __name__ == "__main__":
    raise SystemExit(main())
