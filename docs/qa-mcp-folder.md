# The `.qa-mcp/` folder

Every K11 QA tool keeps its settings and its reports in one folder at the root of your project: `.qa-mcp/`.
It works like `.github/`: a known place, versioned with your code, that the tools and your CI agree on.

- [How it works](#how-it-works)
- [Settings you write](#settings-you-write)
- [Baselines the tools record](#baselines-the-tools-record)
- [Reports the tools write](#reports-the-tools-write)
- [What to commit, what to ignore](#what-to-commit-what-to-ignore)
- [A complete example](#a-complete-example)
- [Where the project root is](#where-the-project-root-is)

## How it works

```text
you write settings ──► each tool reads its settings, tests your system, writes a report ──► Release Gate reads every report
  .qa-mcp/*.yaml                                                       .qa-mcp/*-report/          .qa-mcp/release-gate/
```

1. **Settings** describe your system once: environments, test users, the test database, who consumes your API, your release policy.
   Several tools share `api-test.yaml`, so environments and users are defined in one place.
2. **Each tool writes a report** in a known folder: Markdown for people and pull request comments, JSON as evidence.
3. **Release Gate** reads every report it finds (recognising each by its content), applies `release-policy.yaml`, and writes
   one decision. In CI, test jobs upload their reports and the gate job downloads them back into `.qa-mcp/`.

## Settings you write

Plain YAML or JSON, committed with your code. Secrets are never written here: use `${ENV:NAME}`, and the tools mask the values
in every report. Performance QA, API Security QA, Integration QA and Release Gate have an `init` command that writes a
starter file with comments; the other tools' READMEs show a complete example.

| File | Read by | What it describes |
|---|---|---|
| `api-test.yaml` | [API Functional QA](https://github.com/K11-Software-Solutions/k11techlab-api-functional-qa-mcp), and shared with [API Security QA](https://github.com/K11-Software-Solutions/k11techlab-api-security-qa-mcp), [Integration QA](https://github.com/K11-Software-Solutions/k11techlab-integration-qa-mcp) and [Performance QA](https://github.com/K11-Software-Solutions/k11techlab-performance-qa-mcp) | The API spec, **environments** (URLs, and which may be written to; production-like names are protected), **auth profiles** for test users, the **test database**, and fixtures |
| `consumers.yaml` | [API Contract QA](https://github.com/K11-Software-Solutions/k11techlab-api-contract-qa-mcp) | Who calls your API, how critical each consumer is, and which fields each one reads or sends, so a breaking change names who it breaks |
| `security.yaml` | [API Security QA](https://github.com/K11-Software-Solutions/k11techlab-api-security-qa-mcp) | Test identities (e.g. alice and bob), the objects to test with, admin-only paths, which OWASP checks run, scanner SARIF paths |
| `security-accepted.yaml` | API Security QA | Accepted risks, each with an owner, a reason and an **expiry date**; expired ones count again, and the security report shows them to Release Gate |
| `integration.yaml` | [Integration QA](https://github.com/K11-Software-Solutions/k11techlab-integration-qa-mcp) | Message brokers (Kafka), batch jobs, the AsyncAPI file, topics never to publish to |
| `perf.yaml` | [Performance QA](https://github.com/K11-Software-Solutions/k11techlab-performance-qa-mcp) | Load scenarios (from your API flows), the load profile, SLOs per endpoint |
| `heal.config.json` | [Playwright QA](https://github.com/K11-Software-Solutions/k11techlab-playwright-qa-mcp), [Selenium QA](https://github.com/K11-Software-Solutions/k11techlab-selenium-qa-mcp), [Appium QA](https://github.com/K11-Software-Solutions/k11techlab-appium-qa-mcp) | Optional: which page each test is on, the base URL, login state to use when healing locators |
| `appium.yaml` | Appium QA | Appium server URL and device capabilities for live sessions (device clouds included) |
| `release-policy.yaml` | [Release Gate](https://github.com/K11-Software-Solutions/k11techlab-release-gate-mcp) and the [Release Gate Action](https://github.com/K11-Software-Solutions/k11techlab-release-gate-action) | Required evidence, how fresh it must be, who signs off, what each rule means, and which changes need which evidence |

Test flows live next to your tests, not here: `tests/api/*.yaml` (API Functional QA) and `tests/integration/*.yaml` (Integration QA).

## Baselines the tools record

Recorded from your main branch so that pull requests can be compared with it. Commit them, and update them with a deliberate commit.

| File | Written by | What it holds |
|---|---|---|
| `baselines.json` | Playwright QA, Selenium QA (`capture_baseline`) | A fingerprint of the element each locator matches, taken while tests pass; healing compares against it |
| `appium-baselines.json` | Appium QA | The same for mobile screens |
| `perf-baseline/<scenario>-<environment>.json` | Performance QA (`baseline` on main) | Latency samples per endpoint; regressions are judged against them |
| `security-baseline.json` | API Security QA (`baseline` on main) | Scanner findings that already existed, so only new ones count |

## Reports the tools write

Regenerated on every run. Each holds a Markdown summary and a JSON file that Release Gate reads as evidence.

| Folder | Written by | Main file |
|---|---|---|
| `api-test-report/` | API Functional QA | `api-test-report.json` (+ JUnit XML) |
| `contract-report/` | API Contract QA | `contract-report.json` |
| `security-report/` | API Security QA | `security-report.json` |
| `integration-report/` | Integration QA | `integration-report.json` (+ JUnit XML) |
| `perf-report/` | Performance QA | `perf-report.json`, `samples.json` |
| `heal-report/` | Playwright, Selenium and Appium QA (`heal-ci`) | `heal-report.json` |
| `release-gate/` | Release Gate | `release-decision.md`, `release-decision.json` (the audit record) |
| `llm-assure/` | [LLM Assure](https://github.com/K11-Software-Solutions/k11techlab-llm-assurance-toolkit), if pointed here | `assessment.json` (by default LLM Assure writes `llm-assure-report/` at the project root; Release Gate reads both) |

Working files that are also regenerated: `appium-screens/` (saved device screens) and `auth/` (see below).

The report locations are Release Gate's defaults. A policy can point elsewhere with its `evidence:` key; see the
[Release Gate Action reference](https://github.com/K11-Software-Solutions/k11techlab-release-gate-action/blob/main/docs/reference.md#evidence-kinds-and-default-locations).

## What to commit, what to ignore

| Commit | Ignore |
|---|---|
| every settings file (`*.yaml`, `heal.config.json`) | every `*-report/` folder and `release-gate/` |
| baselines (`baselines.json`, `appium-baselines.json`, `perf-baseline/`, `security-baseline.json`) | `appium-screens/` |
| | **`auth/`: saved browser logins. Never commit it.** (`save_login_state` adds it to `.gitignore` for you.) |

A `.gitignore` that does this:

```gitignore
.qa-mcp/*-report/
.qa-mcp/release-gate/
.qa-mcp/appium-screens/
.qa-mcp/auth/
```

## A complete example

The [K11 Shop demo](https://github.com/K11-Software-Solutions/k11techlab-release-gate-demo) has a working `.qa-mcp/` for an API
with Kafka events, used by five tools and the Release Gate Action on every pull request:

```text
.qa-mcp/
├── api-test.yaml          environments (ci, prod), test users alice and bob, the SQLite test database, a fixture
├── consumers.yaml         mobile-app (critical) reads total; analytics (medium) reads createdAt
├── security.yaml          alice owns a test order; bob must not reach it
├── integration.yaml       Kafka from ${ENV:KAFKA_BOOTSTRAP}, the sku_totals batch job, asyncapi.yaml
└── release-policy.yaml    unit and API tests always; the rest required by what a change touches
```

In CI, the same folder fills up with `api-test-report/`, `security-report/`, `contract-report/`, `integration-report/` and
finally `release-gate/`.

## Where the project root is

The folder sits at the project root. The tools find it in:

- **`QA_MCP_ROOT`**, when set: the Claude Code plugins set it to your project (`${CLAUDE_PROJECT_DIR}`);
- otherwise **the current directory**, which is what CI uses;
- in the GitHub Action, **`working-directory`**, so a monorepo can keep one `.qa-mcp/` per service.
