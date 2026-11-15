# Changelog

## 0.3.0 (15 November 2026)

- **Performance evidence:** `perf-report.json` from [k11 Performance QA](https://github.com/K11-Software-Solutions/k11techlab-performance-qa-mcp) is a sixth evidence kind (`perf`), recognised by its content.
- Seven new rules: `perf.server_errors` and `perf.slo_breached` and `perf.aborted` block; `perf.regression` (significantly slower than the baseline) and `perf.not_run` need a person; `perf.no_baseline` and `perf.insufficient_samples` are recorded.
- Diff-aware planning triggers load tests for changes to migrations, SQL, repositories, caches, database code and performance config.

## 0.2.0 (13 November 2026)

- **Diff-aware planning:** `plan_checks` / `k11-release-gate-mcp plan --base REF` maps the files changed since a git ref to the evidence they need, using the policy's `triggers` (defaults for API specs, UI files, prompts and services).
- `evaluate --base REF` / `evaluate_release(base_ref=...)` requires exactly the evidence the change triggers, and says which files made it required; the plan is saved in the decision record.

## 0.1.0 (13 November 2026)

- First release: evidence from five K11 tools and JUnit, 21 policy rules, deterministic verdict, audit record with SHA-256s.
