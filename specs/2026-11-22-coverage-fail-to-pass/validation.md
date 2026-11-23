# Validation: Coverage and fail-to-pass

## Done when (from roadmap)
> An SDD run's gate shows coverage of the changed lines and lists each criterion with a test that failed before and passes after; a criterion with no such test sends the work back

This phase covers Python and .NET repos; Node is 13.11.

## Automated checks

- [ ] **Unit (`packages/tools`)**:
  - `parse_junit` and `parse_trx` keep every test's result;
  - the id regex matches `AC-001`, `ac_001`, `AC001` and parametrized names, and rejects `TRACK001` and `AC-0011`;
  - the changed-line maths: added, modified and deleted lines, a renamed file, a file with only comments changed, test files left out;
  - caps on cases, files and ranges;
  - the Node reasons.
- [ ] **Docker fixture tests** (`test_build_docker.py`, real job containers). Run them by file, never `packages/sandbox/tests` as a whole (its sweep test removes the dev stack's sandboxes).
  - A Python and a .NET fixture repo, each with a base commit and a change:
    - coverage of the changed lines matches a hand count;
    - a linked test that fails on the base and passes on the change is `proven`;
    - one that passes on both is `not_proven`;
    - a criterion with no test is `untested`;
    - a new test that cannot import or build on the base fails before.
  - Test and coverage jobs run on network `none`, and a fixture test that reaches the network fails.
  - The checkout and the writer's worktree are unchanged after.
  - 13.3's missing fixtures: a Node and a Python repo with a passing and a failing variant, reported as `passed` and `tests failed (N of M)`.
- [ ] **Engine (fake runtime, `test_evidence_gate.py`)**:
  - a criterion with no test sends the work back with no person, no approval row and no `gate_waiting`, and the writer's next input holds `## Criteria`;
  - coverage below `coverage_min` sends it back with `## Coverage`;
  - once every criterion is proven and coverage is met, the gate pauses with both checks in `evidence`;
  - `unchecked` (a Node module) pauses for a person;
  - the send-backs of every check share one rounds counter, and the last pass is never sent back (lessons 13);
  - a restart between the evidence step and the gate runs no job twice;
  - with the new checks `off`, 13.3's tests pass unchanged.
- [ ] **Validation**: `artifact_unknown` for `criteria_from`, `invalid_evidence` for a non-Markdown name or a `coverage_min` out of range, and `commit_specs` and `links_from` accepted in a loop body that is a root step, each with an actionable message.
- [ ] **Templates**: both SDD builders with `checks` on and off. The tests assert what the spec writer, tasker, lead and engineer receive (the naming rule, the send-back headings). AC-2's conformance check and "Plan, build and review" are unchanged.
- [ ] **Worker**: the AC-5 test and the spec-file test with `checks` on, and the 7.6 follow-up still starts at `review_loop`.
- [ ] **API**: `GET /runs/{id}/gate` returns a pack with coverage and criteria (tests run from `packages/api`).
- [ ] **Web**: `evidence-strip.test.tsx` covers each criterion state, coverage pass and fail, the Node reasons, loading, empty and error.
- [ ] **Web e2e on the rebuilt compose stack**:
  - the gate review with a coverage and criteria pack, in the dock, the Inbox and the review sheet;
  - `layout.spec.ts` at 375, 768 and 1440 px and `a11y.spec.ts` (axe), in light and dark.

  Run them here, not only written as in 13.3.
- [ ] `uv run` lint, strict type check and tests; `cd web && pnpm lint && pnpm typecheck && pnpm test && pnpm test:e2e`.
- [ ] `git status --short` lists every new file, and a clean clone of the branch imports and tests (lessons 12).

## Manual / demo checks

- [ ] **Real run on GitHub Copilot.** Run "Build from a spec file" with `checks` on, on a real Python or .NET repo, with the provider set to Copilot and the starter's personal connection (8.2, 8.3). The spec has at least three `AC-` criteria. Read it step by step in the console's Activity tab:
  - the tasker gives each criterion a test task, and the engineers name each test with its id;
  - if a pass leaves a criterion unproven or coverage short, the step list shows "Sent back by checks", and the next pass's input shows the `## Criteria` or `## Coverage` comments;
  - the gate shows Coverage and Criteria beside the diff, each criterion with its tests and "fails before → passes after".

  If the writers prove everything on the first pass, the PR says so, and points to the engine and Docker tests for the send-back. Anything wrong goes into `specs/lessons.md`.
- [ ] Look at the gate review against the real stack at 375 and 1440 px, in light and dark (lessons 11).
- [ ] Read the event and audit logs: a send-back by the criteria check shows `source: "checks"` and no person.

## Merge criteria

- [ ] All automated checks above pass in CI.
- [ ] `findings.md` is committed, with a decisions-log row for each choice the spike made.
- [ ] These land in this PR: tech-stack (Tool layer, Sandbox if changed, Gate review, UI design system → Gate evidence, SDD template, decisions log), the roadmap (13.4's plan link and scope note, the new 13.11 row), `docs/security/security-model.md` and the `CHANGELOG.md` entry.
- [ ] The PR says the real run used GitHub Copilot instead of Claude, a one-off deviation from lessons rule 1, and links the run.
- [ ] The PR says that a writer can still weaken a linked test until 13.5.
- [ ] Only capped test names, paths and line ranges reach events, artifacts and the writer. No coverage file or test output leaves the sandbox, and no secret appears in a log.
