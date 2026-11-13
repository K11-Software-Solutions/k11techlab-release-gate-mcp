---
description: Decide whether this build can ship, from the QA evidence and the release policy, and explain why
argument-hint: [release label, e.g. v2.4.0] [--refresh to run the checks first]
---

Make a release decision for this project using the release-gate MCP tools.

Input: $ARGUMENTS

1. Call `collect_evidence`. For each required kind that is missing or stale, say which tool produces it:
   - UI tests with self-healing: k11 Playwright QA or Selenium QA (`heal-ci`)
   - API contract: k11 API Contract QA (`contract-ci`)
   - API functional tests: k11 API Functional QA (`run`)
   - LLM red-team: LLM Assure (`llm-assure run`)
   - other test suites: any JUnit XML
   If `--refresh` was given and those MCP servers are available in this session, run them first (read-only and test environments only); otherwise ask the user before running anything.
2. Call `evaluate_release` with the label.
3. Report the verdict exactly as returned: **ship**, **ship with conditions**, **needs a person** (name the approvers) or **block**. Never soften or override it.
4. For each blocker, say what failed, where the evidence is, and the smallest change that would clear it. For each condition, say who must do what.
5. List anything not tested, and say that untested is not the same as passing.

Finish with the path to release-decision.md.
