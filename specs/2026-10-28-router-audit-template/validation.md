# Validation: `router` primitive and the "Audit codebase" template

## Done when (from roadmap)
> An audit run branches on a condition and produces findings.json + a readable report

## Automated checks
- [ ] Engine, spec and validation (`test_spec.py`, `test_validate.py`, `test_artifact_flow.py`, `test_expr.py`):
  - the valid router fixtures pass;
  - each invalid fixture returns its code on the right path (`root.steps[2].routes[0].when`);
  - an artifact written by only one route is `artifact_unknown` for a later reader.
- [ ] Engine runtime on the fake runtime (`test_router.py`):
  - the first match wins; `default` runs when nothing matches; no match and no default fails with one line;
  - the classifier picks a route and its reason is logged; an unknown route or a wrong shape fails as a port error;
  - only the chosen route's nodes log events;
  - a router works in a loop, a map and a parallel branch;
  - usage and `agents_spawned` count only what ran.
- [ ] Durable (`test_resume.py`): a worker killed inside a route resumes in the same route, and the classifier is not asked again.
- [ ] API: run summaries and events carry `route_chosen`; the OpenAPI and workflow schema exports are up to date (CI diff check).
- [ ] Template (`test_audit_template.py`):
  - every `checks` and `reviewers` combination builds and validates under `PLATFORM_POLICY`;
  - the spec holds no write tool, gate or `github.*` tool;
  - every route writes `report.md`;
  - `reviewers: 1` holds no `vote`; `reviewers: 3` validates with the nested `parallel` + `vote` within `agents_alive`;
  - with `reviewer_model` / `report_model` unset, no node has a `model`; when set, the matching nodes carry it; an unpriced model id is refused.
- [ ] Nesting in parallel (`test_parallel.py`, `test_validate.py`):
  - a nested `parallel` + `vote` in a branch runs;
  - a `reduce` with `writes`, a gate or a `loop` in a branch is still `not_allowed_in_parallel`;
  - nested branches above `agents_alive` are refused.
- [ ] Integration with a Docker sandbox, real scanners and fake agents, on the seeded fixture repos:
  - a repo with a planted secret takes `fix_first`; a clean repo takes `clean`;
  - both store `findings.json` (valid against `schemas/findings.v1.json`) and `report.md`;
  - no branch or commit is created.
- [ ] Web: `pnpm lint && pnpm typecheck && pnpm test` (`spec-graph.test.ts` with ELK, `step-entries.test.ts`, `templates-view.test.tsx`).
- [ ] Web: `pnpm test:e2e`. The existing a11y (axe) and layout suites pass; layout screenshots are re-baselined for ELK and reviewed by eye. No new audit-specific Playwright spec (user choice).
- [ ] Backend: `uv run ruff check`, `uv run pyright` (strict), `uv run pytest`.
- [ ] CI: every check is green, including "Roadmap phase marked done" and the CHANGELOG check.

## Manual / demo checks
- [ ] **Live demo on real Claude.**
  1. Connect Claude and GitHub, then open Templates → "Audit codebase".
  2. Start a run on a real repo with the default params.
  3. Expected:
     - the run completes with no gate and no PR;
     - the console shows the scanners and specialists side by side, the merge, then "Routed to …" with the rule;
     - `findings.json` opens in the Findings view, and `report.md` renders as Markdown in the artifact sheet.

  Record the active time, cost and route in the PR.
- [ ] Run again with `reviewers: 3` on the same repo. The console shows the `vote` merge line, and the cost is about 3× for the agent reviews.
- [ ] Check the graph tab at 375 and 1440 px, light and dark:
  - the router's routes are drawn as branches, with the taken one marked and the others Skipped;
  - parallel, map and loop runs still read correctly with ELK;
  - there is no horizontal page scroll.

## Merge criteria
- [ ] All checks above pass in CI.
- [ ] The tech-stack has "Router (API contract)", the audit template, the `FindingsReport` additions and the decisions-log rows (router semantics; ELK).
- [ ] `CHANGELOG.md` has its `[Unreleased]` entry, and roadmap 4.6 is marked done.
- [ ] No reference to phase 4.7 is left in `specs/`, `packages/` or `web/src` (`grep -rnw "4\.7"`).
- [ ] Issue #69 is closed as merged into #68.
- [ ] No secret appears in logs, events or `report.md`: the secret fixture's value never shows up in any of them.
