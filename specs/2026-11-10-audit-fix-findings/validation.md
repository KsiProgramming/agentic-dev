# Validation: Audit "fix selected findings" step with orchestrator

## Done when (from roadmap)

> Selected findings become fix PRs

Made checkable: in an "Audit codebase" run with `fix` on, a person selects some findings at the selection gate. The run fixes exactly those, on task branches merged into one integration branch, and after the PR gate opens one pull request whose body lists each selected finding as fixed or not fixed. Rejecting at the selection gate completes the audit with no change to the repo.

## Automated checks

- [ ] **Engine: selection gate**
  - `gate_waiting` carries `select` with the artifact version, the item count and the preselected keys.
  - An approval's output is the document filtered to the selection, in the original order, with a findings report's `counts` recomputed. `writes` stores it.
  - `selection_required`, `selection_not_allowed`, `unknown_selection`, `duplicate_selection` and `selection_too_small` each refuse the decision.
- [ ] **Engine: `on_reject: end`.** A rejection logs `gate_decided`, runs no later step and completes the run. A worker restart while the gate waits resumes at the gate, and a decision after it still ends the run.
- [ ] **Engine: validation.** `invalid_gate` for each bad `select` or `on_reject` case, `artifact_unknown` for `select.artifact` and `openPR`'s `body_from`, `invalid_expression` for a bad `preselect`.
- [ ] **Engine: what agents receive** (lessons rule 1), fake runtime:
  - the hub's input is exactly the selected findings and its tools are only `repo` read tools;
  - each fixer gets its task and the selected report, has the write tools, and its calls go out as `fix.<task>`;
  - `approve_pr` shows the integration branch as the one writer;
  - `openPR`'s body ends with `fixes.md`;
  - an end at `select_fixes` spawns no hub.
- [ ] **Template**
  - every `AuditParams` combination validates;
  - with `fix` off, the spec is unchanged from 4.6;
  - with `fix` on, no node publishes except `publish`, and `publish` comes after `approve_pr`.
- [ ] **Fixtures.** `audit-fix-run.json` and `node-types.json` are up to date (their tests fail when stale).
- [ ] **API**
  - each selection `422` code;
  - the selection is stored on the approval;
  - the `gate.approved` audit row has `selected` (a count, no items);
  - `GET /runs/{id}/gate` returns `select`;
  - the OpenAPI client is regenerated with no diff left.
- [ ] **Web unit**
  - the checklist from the fixture: preselected rows checked, select all, clear, the count;
  - Approve is disabled under `min`, with its reason;
  - the approval body holds `selection`;
  - Reject reads "End run here" for `on_reject: end`;
  - the decided step reads "Selected N of M".
- [ ] **Web e2e**
  - select two findings in the Inbox and approve: the run goes on to the fix tasks and the PR gate;
  - from the console, `A` opens the review instead of approving;
  - keyboard only: tab to the checkboxes, Space toggles, approve.
- [ ] **a11y and layout.** axe passes for the checklist at 375, 768 and 1440 px, light and dark. The layout screenshots pass, with no horizontal page scroll.
- [ ] **Lint and types**
  - `uv run ruff check`, `uv run ruff format --check`, `uv run pyright` (strict) and `uv run pytest` are green;
  - in `web/`, `pnpm lint && pnpm typecheck && pnpm test && pnpm test:e2e` are green.

## Manual / demo checks

- [ ] **Real run with Claude** (`AGENTIC_RUNTIME=claude`, required by lessons rule 1) on a small real repo with five planted findings:
  1. Start "Audit codebase" with `fix` on. The run pauses at `select_fixes`, and the Inbox shows the findings with the critical and high ones preselected.
  2. Select exactly two findings and approve.
  3. In the console, the hub plans tasks that cover those two findings and no others. Its Activity shows it read the files involved.
  4. Each fixer's Activity shows it read the code, changed only its task's files and committed. The orchestrator's Output shows the integration branch with the tasks merged.
  5. `approve_pr` shows a diff limited to the two fixes, and `fixes.md` among the run artifacts. Approve it.
  6. The PR on GitHub fixes the two findings, touches nothing else, and its body lists both as fixed (or says why one was not).
- [ ] **Decline path.** A second run, rejected at `select_fixes` ("End run here"), ends Completed with `findings.json` and `report.md`, no branch pushed and no PR.
- [ ] **Screens.** Look at the checklist at 375 and 1440 px, in light and dark.

## Merge criteria

- [ ] All checks above pass locally. CI minutes are limited, so the run isn't watched in CI unless asked.
- [ ] The real run was read step by step, and anything it revealed is fixed, with a `lessons.md` entry when tests had missed it.
- [ ] tech-stack, roadmap (`[Plan]` link) and `CHANGELOG.md` are updated in the same PR. Code and specs agree, or the PR says which one changed.
- [ ] Neither events, the audit log nor the PR body hold secrets. A planted secret's value never appears in `fixes.md` or the PR.
- [ ] With `fix` off, the audit template is still read-only: tests check it has no writer, gate or `github.*` tool.
