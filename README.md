# k11 Release Gate — MCP server & CI gate

<!-- mcp-name: io.github.K11-Software-Solutions/release-gate -->

**One release decision from all your QA evidence, under a policy you can read, with an audit trail.**

Teams already have the evidence: UI test runs, API checks, security scans, JUnit files. What they lack is a consistent answer to "can we ship?". Today that answer is a person reading five dashboards under deadline pressure. k11 Release Gate reads the evidence, applies a written policy and returns one verdict, with every reason and the file it came from:

| Verdict | Meaning |
|---|---|
| 🟢 **ship** | nothing in the policy objects |
| 🟡 **ship with conditions** | ship, but someone must do something (e.g. approve the locator-heal PR) |
| 🟠 **needs a person** | ship only with sign-off from a named approver: risk-proportionate human-in-the-loop |
| 🔴 **block** | don't ship; here is each blocker and its evidence |

**Deterministic.** The same evidence and the same policy always give the same verdict. There's no LLM in the decision, so it holds up in an audit. Every evidence file is recorded with its SHA-256, timestamp and age, alongside the policy's own hash and the git commit.

## What it reads

The kind of evidence is recognised from the file's content:

| Evidence | Produced by |
|---|---|
| UI tests with self-healing (`heal-report.json`) | [k11 Playwright QA](https://github.com/K11-Software-Solutions/k11techlab-playwright-qa-mcp) or [k11 Selenium QA](https://github.com/K11-Software-Solutions/k11techlab-selenium-qa-mcp) `heal-ci` |
| API contract (`contract-report.json`) | [k11 API Contract QA](https://github.com/K11-Software-Solutions/k11techlab-api-contract-qa-mcp) `contract-ci` |
| API functional tests (`api-test-report.json`) | [k11 API Functional QA](https://github.com/K11-Software-Solutions/k11techlab-api-functional-qa-mcp) `run` |
| LLM red-team (`assessment.json`) | [LLM Assure](https://github.com/K11-Software-Solutions/k11techlab-llm-assurance-toolkit) |
| Any JUnit XML | pytest, Maven Surefire, Gradle, Jest, Playwright, … |

Missing evidence is never treated as a pass. Required kinds that are missing **block** by default, and optional kinds without evidence are listed as **not tested**.

## See it decide

`demo/` contains two release candidates whose evidence comes from **real runs of the five K11 tools** against their own demos.

**rc1 → 🔴 Block,** with 7 blockers, each traced to its source:

> - **1 UI test failed for reasons other than locators** (`ui.real_failures`): page title changed
> - **2 broken locators still unresolved** (`ui.unresolved_locators`): "Edit profile" needs review; `cart-btn` heal reverted
> - **API change breaks billing-svc, checkout-web, notification-svc** (`contract.breaks_critical_consumer`): billing-svc is critical, owner @team-billing
> - **2 API flows failed** (`api.flow_failed`): "Order total is quantity times price", negative tests for `POST /orders`
> - **2 server errors (5xx) in API tests** (`api.server_error`): wrong type / missing `items[0].qty`
> - **6 critical** and **13 high-severity LLM findings** (`llm.critical`, `llm.high`): unverified refund, other customers' records, indirect prompt injection, …
>
> Needs a person: the contract check escalated (3 consumers break). Conditions: approve the healed `view-orders` locator; confirm the consumer list for 3 unused breaking changes.

**rc2 (after the fixes) → 🟠 Needs a person's sign-off:**

> **Sign-off needed from @qa-lead, @ai-safety-lead** before release.
> - Needs a person: **1 LLM probe inconclusive** (`llm.inconclusive`)
> - Condition: **1 locator healed and verified: approve the heal pull request**

Everything passes, but one security probe couldn't be decided automatically, so the policy asks a named person to look. It doesn't let it through silently and doesn't block the release outright.

```bash
QA_MCP_ROOT=demo/rc1 k11-release-gate-mcp evaluate --label rc1
QA_MCP_ROOT=demo/rc2 k11-release-gate-mcp evaluate --label rc2
```

## The policy: `.qa-mcp/release-policy.yaml`

```yaml
name: Order platform release policy
evidence:                                   # where each tool writes its report (globs inside the project)
  api_tests: [".qa-mcp/api-test-report/api-test-report.json"]
  junit: ["test-results/**/*.xml"]
required: [api_tests, contract, ui_heal, llm]
max_age_hours: 24                           # older evidence → evidence.stale
critical_consumers: [critical, high]        # their breakage blocks
approvers: ["@qa-lead", "@ai-safety-lead"]  # named on a needs_human verdict
rules:                                      # override any rule: block | needs_human | conditional | info | off
  llm.medium: needs_human
  ui.healed: info
```

`k11-release-gate-mcp init` writes a commented starter policy; `k11-release-gate-mcp rules` lists every rule.

## Rules

| Rule | Default | Fires when |
|---|---|---|
| `evidence.missing` | block | a required kind has no evidence |
| `evidence.unreadable` | needs a person | an evidence file can't be parsed |
| `evidence.stale` | condition | evidence is older than `max_age_hours` |
| `api.server_error` | block | an API returned a 5xx during functional tests |
| `api.flow_failed` | block | an API flow failed |
| `api.flow_not_run` | needs a person | a flow was blocked by guardrails or errored, so it proved nothing |
| `contract.breaks_critical_consumer` | block | an API change breaks a consumer in `critical_consumers` |
| `contract.breaks_consumer` | needs a person | it breaks another consumer |
| `contract.escalation` | needs a person | the contract check asked for a person |
| `contract.breaking_unused` | condition | breaking changes with no known consumer |
| `ui.real_failures` | block | UI tests failed for reasons other than locators |
| `ui.unresolved_locators` | block | broken locators were reverted, need review or weren't found |
| `ui.healed` | condition | locators were healed and verified; approve the heal PR |
| `ui.suggested` | condition | heals were suggested in a dry run |
| `llm.critical`, `llm.high` | block | LLM security findings at that severity |
| `llm.medium` | condition | medium findings |
| `llm.inconclusive` | needs a person | probes that need review or errored |
| `llm.low` | note | low findings |
| `junit.failures` | block | failures or errors in any JUnit file |
| `junit.skipped` | note | skipped tests |

## Tools

| Tool | What it does |
|---|---|
| `evaluate_release` | The verdict, every finding with its evidence, what wasn't tested; writes `release-decision.md` / `.json`. |
| `collect_evidence` | What evidence exists: kind, file, age, SHA-256, key numbers, missing required kinds. |
| `list_rules` | Every rule with its default and its outcome under your policy. |
| `init_policy` | Writes a commented starter policy (never overwrites without asking). |

The Claude Code plugin adds `/release-check`, which collects the evidence, tells you which tool produces anything missing, evaluates and explains, without ever softening the verdict.

## In CI

```bash
k11-release-gate-mcp evaluate --label v2.4.0
```

It writes `release-decision.md` (the PR comment) and `release-decision.json` (the audit record), sets GitHub Actions outputs (`verdict`, `blockers`, `needs_human`, `conditions`, `report`) and exits non-zero according to `--fail-on block | needs-human | conditions | never`. See [`docs/release-gate.yml`](docs/release-gate.yml).

## Install

```text
/plugin marketplace add K11-Software-Solutions/k11techlab-release-gate-mcp
/plugin install release-gate@k11-release-gate
```

Or the MCP server only: `claude mcp add release-gate -- uvx k11-release-gate-mcp`, or `pip install k11-release-gate-mcp` for CI.

## Background

This puts into practice the risk-proportionate human-in-the-loop idea from the K11 research on [autonomous CI/CD quality assurance](https://doi.org/10.18535/ijecs/v15i06.5563) (IJECS, 2026): automate the clear cases and send the uncertain ones to a named person, with the evidence attached. It's an independent implementation and doesn't depend on the research code.

## Development

```bash
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"   # bin/pip on macOS/Linux
pytest   # real evidence from all five tools, policy, determinism, CLI, MCP (10)
```

## Roadmap

- A GitHub Check with per-rule annotations
- Signed decision records (Sigstore) for regulated releases
- Approvals recorded against the decision (who signed off a `needs_human` verdict, and when)
- The Release Readiness Agent: a Claude Code plugin that decides which checks a change needs, runs them through the K11 servers, and asks this gate for the verdict

---

Built by [K11 Software Solutions](https://k11softwaresolutions.com). Part of the K11 Tech Lab agentic QA series. MIT licensed.
