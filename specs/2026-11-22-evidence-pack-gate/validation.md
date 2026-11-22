# Validation: Evidence pack at the gate

## Done when (from roadmap)
> A writer whose change breaks a test is sent back with no person involved; a passing change reaches the gate with its build, tests and analyzers shown

## Automated checks
- [ ] **Docker tests on fixture repos** (real job containers):
  - Each Node, Python and .NET fixture passes `build.test`, and its failing variant reports `tests failed (N of M)` with the failing test named.
  - Build and test jobs run with network `none`, and a fixture test that reaches the network fails.
  - The checkout and the writer's worktree are unchanged after.
- [ ] **Work copy**: `build.test {node}` and `scan.lint {node}` read the branch's committed tree. They work after a restore (12.2) and give 13.1's three refusal texts for an unknown, not-yet-run or empty writer.
- [ ] **Engine: send-back loop** (fake runtime):
  - A writer whose branch fails a required check is sent back. The gate completes with `source: "checks"` and no approval row, and no `gate_waiting` is written. The writer's next input holds the failures under `## Tests` and the other check headings.
  - A passing branch reaches the gate with `evidence` in `gate_waiting` and `GET /runs/{id}/gate`.
  - After `max_rounds` send-backs, the gate pauses with the failing pack and `rounds_left: 0`.
  - A worker restart between `<gate>:evidence` and the gate runs no job twice.
  - `analyzers: no_new` passes on old findings and fails on a new fingerprint.
- [ ] **Validation**: `evidence_not_in_loop`, `evidence_unknown_writer` and `invalid_evidence` each have a test with an actionable message. `build.test` on an agent is `tool_node_only`.
- [ ] **Templates**: the "Plan, build and review" and SDD template tests and the AC-2 conformance check (6.8) pass with the evidence gate in the loop.
- [ ] **API**: `GET /runs/{id}/gate` returns `evidence`, and the audit log lists `gate.sent_back_by_checks` (tests run from `packages/api`).
- [ ] **Web**: component tests for `EvidenceStrip` (passed, failed, skipped, no tests, loading, error). The e2e gate review with a passing and a failing pack passes at 375 and 1440 px in light and dark, and `a11y.spec.ts` (axe) and `layout.spec.ts` pass.
- [ ] `uv run` lint, type check (strict) and tests; `cd web && pnpm lint && pnpm typecheck && pnpm test && pnpm test:e2e`.

## Manual / demo checks
- [ ] **Real run on GitHub Copilot** (provider set to Copilot with the starter's personal connection, 8.2 and 8.3) of "Plan, build and review" on a real Node or Python repo, read step by step in the console's Activity tab:
  - The writer's first change breaks a test.
  - The gate is not shown. The step list shows "Sent back by checks", and the writer's next turn shows the failing test as its input.
  - The fixed change reaches the gate, with Build, Tests and Analyzers in the strip beside the diff.
  - The run is recorded in the PR. Anything wrong goes into `specs/lessons.md`.
- [ ] Look at the gate review in the dock and the Inbox at 375 and 1440 px, in light and dark, against a real stack (lessons, rule 11).
- [ ] Check the event log and audit log by hand. The sent-back pass shows `source: "checks"`, and no person is named as having decided it.

## Merge criteria
- [ ] All checks above pass in CI.
- [ ] The spike's `findings.md` is committed, with a decisions-log row for each choice it made.
- [ ] tech-stack (Tool layer, Gate review, UI design system, decisions log), the roadmap row's plan link, `docs/security/security-model.md` and the `CHANGELOG.md` entry land in this PR.
- [ ] The PR says the real run used GitHub Copilot instead of Claude (a deviation from lessons rule 1's wording) and links the run.
- [ ] No test output beyond the capped failure messages reaches events or artifacts, and no secret appears in a log.
- [ ] The PR notes that the writer can still edit failing tests until 13.5.
