# Changelog

## 0.2.0 (13 November 2026)

- **Diff-aware planning:** `plan_checks` / `k11-release-gate-mcp plan --base REF` maps the files changed since a git ref to the evidence they need, using the policy's `triggers` (defaults for API specs, UI files, prompts and services).
- `evaluate --base REF` / `evaluate_release(base_ref=...)` requires exactly the evidence the change triggers, and says which files made it required; the plan is saved in the decision record.

## 0.1.0 (13 November 2026)

- First release: evidence from five K11 tools and JUnit, 21 policy rules, deterministic verdict, audit record with SHA-256s.
