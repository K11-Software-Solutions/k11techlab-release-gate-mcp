# Changelog

## 0.4.0 (16 November 2026)

- **Security evidence:** `security-report.json` from [k11 API Security QA](https://github.com/K11-Software-Solutions/k11techlab-api-security-qa-mcp) is a seventh evidence kind (`security`): OWASP API Top 10 test findings plus new scanner findings and expired risk acceptances.
- Six new rules: `security.critical` and `security.high` block; `security.acceptance_expired` and `security.not_run` need a person; `security.medium` is a condition; `security.inconclusive` is recorded.
- Diff-aware planning triggers security checks for auth, permission, middleware, route and controller code, and dependency manifests.
- **Integration evidence:** `integration-report.json` from [k11 Integration QA](https://github.com/K11-Software-Solutions/k11techlab-integration-qa-mcp) is an eighth evidence kind (`integration`): flows across APIs, Kafka messages, batch jobs and databases.
- Three more rules: `integration.failed` blocks; `integration.flows_not_run` (refused or errored flows) and `integration.not_run` (no flows ran) need a person.
- Diff-aware planning triggers integration tests for consumers, producers, listeners, messaging, jobs, schedulers, workers, middleware and AsyncAPI documents.

## 0.3.0 (15 November 2026)

- **Performance evidence:** `perf-report.json` from [k11 Performance QA](https://github.com/K11-Software-Solutions/k11techlab-performance-qa-mcp) is a sixth evidence kind (`perf`), recognised by its content.
- Seven new rules: `perf.server_errors` and `perf.slo_breached` and `perf.aborted` block; `perf.regression` (significantly slower than the baseline) and `perf.not_run` need a person; `perf.no_baseline` and `perf.insufficient_samples` are recorded.
- Diff-aware planning triggers load tests for changes to migrations, SQL, repositories, caches, database code and performance config.

## 0.2.0 (13 November 2026)

- **Diff-aware planning:** `plan_checks` / `k11-release-gate-mcp plan --base REF` maps the files changed since a git ref to the evidence they need, using the policy's `triggers` (defaults for API specs, UI files, prompts and services).
- `evaluate --base REF` / `evaluate_release(base_ref=...)` requires exactly the evidence the change triggers, and says which files made it required; the plan is saved in the decision record.

## 0.1.0 (13 November 2026)

- First release: evidence from five K11 tools and JUnit, 21 policy rules, deterministic verdict, audit record with SHA-256s.
