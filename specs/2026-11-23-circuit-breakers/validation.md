# Validation: Circuit breakers

## Done when (from roadmap)
> Each of the four breakers pauses a test run with its own reason; an agent that repeats the same failing call is paused and goes on once a person resumes it

## Automated checks

- [ ] **Each breaker pauses with its own reason** (engine, `test_breakers.py`, fake runtime). Each ends the run `waiting` with `breaker_tripped` and then `gate_waiting.breaker`:
  - **repeat:** a scripted agent repeating a failing call pauses at `repeat_errors` (3), and one repeating a successful call pauses at `repeat_calls` (5);
  - **cost:** a step whose usage crosses 3× its baseline and the floor pauses mid-step; a node with fewer than 5 past runs is not watched; a step under the floor does not trip;
  - **paths:** a `repo.write_file` outside `paths` pauses, and the tool executor is never called for it; a node with no `paths` writes anywhere;
  - **flip-flop:** A → B → A → B on one path pauses at 2 flips; rewrites of distinct contents do not.
- [ ] **The pause:**
  - the steps running beside the tripped one end `node_cancelled`;
  - the first trip wins;
  - each map item, branch and task has its own counters;
  - a pause uses no loop pass (lessons 13: a loop's pass count is unchanged after Resume).
- [ ] **Resume** (engine and worker):
  - `approve` writes `gate_decided` `source: "breaker"`;
  - the tripped step runs again from its start, and steps that completed (one in a sibling branch included) are not run again;
  - `reject` ends the run `cancelled` with the reason and no step runs;
  - a worker restart while paused leaves the run waiting.
- [ ] **What the resumed agent receives** (lessons 1): its system prompt holds "# Paused before" with the breaker and the quoted call or error as data; its input equals the first attempt's; `node_started.resumed_after` is set; an agent that was not tripped gets no such section.
- [ ] **Thresholds:**
  - `with_breakers` gives workflow over workspace over platform, clamped;
  - a value out of range is a validation error (`breakers_out_of_range`);
  - `paths_without_writes`;
  - a policy frozen before 13.7 loads with defaults;
  - a run keeps its thresholds after the workspace changes them.
- [ ] **Tools:** `repo.write_file` and `repo.commit` refuse a path outside `DeclaredPaths` (write, staged file, both sides of a rename, a symlinked directory), with one fixed text and nothing committed.
- [ ] **Store and API** (run from `packages/api`, Testcontainers):
  - status `waiting` with `waiting_gate.breaker`, and waiting time not counted as active time;
  - `POST /runs/{id}/approvals` resumes and cancels, and refuses edits, selections and dismissals (`422 breaker_decision_invalid`);
  - the expiry sweep cancels a pause with "Breaker pause expired", `expired: true`;
  - `runs.breaker_trips`;
  - the four `breaker.*` audit rows;
  - `cost_baselines` on seeded runs (last 20, at least 5, per execution);
  - `PUT /workspaces/{id}/policy` `breakers` with ranges;
  - the migration upgrades and downgrades.
- [ ] **Web unit tests** (Vitest):
  - `BreakerDetails` for each breaker and its three states;
  - the paused banner, and the dock labels Resume and Cancel run;
  - the timeline fold ("Paused" step);
  - `badgeStatus` and `statusLabel` "Paused";
  - the Inbox review of a pause;
  - the Breakers tile above zero only;
  - the Circuit breakers settings card;
  - the audit formatter.
- [ ] **e2e** (`pnpm test:e2e`):
  - `breaker.spec.ts`: a fake agent repeating a failing call is paused; the banner and the Inbox show it; Resume lets it go on; Cancel asks first and ends it;
  - `a11y.spec.ts` (axe) and `layout.spec.ts` cover the paused console and Inbox at 375, 768 and 1440 px, light and dark.
- [ ] **Repo checks:** `uv run ruff check`, `ruff format --check`, `pyright` (strict), and the backend test suites; in `web/`, `pnpm lint && pnpm typecheck && pnpm test`; the regenerated JSON Schema and OpenAPI client have no diff.

## Manual / demo checks

- [ ] **Real Claude run** (`AGENTIC_RUNTIME=claude`, a real repo). A one-agent workflow told to read `docs/does-not-exist.md` until it succeeds:
  - it pauses after 3 identical errors, and the banner names the repeat breaker and the call;
  - read its Activity step by step in the console;
  - Resume, then check that the resumed agent's turn shows it was told why ("# Paused before") and that it stops retrying and answers;
  - the run completes.
- [ ] **Real paths trip:** a writer with `paths: ["docs/**"]` asked to update `README.md` is paused before the write. The repo shows no change to `README.md` on its branch, and Cancel keeps the sandbox (12.3).
- [ ] **Look at the screens:** the paused console (banner, dock, step Output, tile) and the Inbox review at 375 and 1440 px, in light and dark; the Circuit breakers card on Settings › Limits and budgets; `paths` and `breakers` in the builder's side panel.
- [ ] **Keyboard:** in the dock and the Inbox, `A` resumes and `R` opens the Cancel dialog; every action is reachable by Tab.

## Merge criteria

- [ ] All checks above pass in CI.
- [ ] The real Claude run is described in the PR (what each step received and did), with a `specs/lessons.md` entry if it showed something the tests did not.
- [ ] Specs updated in the same PR:
  - `tech-stack.md`: the contract section, policy, tool layer, UI sections and decisions log, including the Copilot `tool_call` order;
  - `roadmap.md`: the 13.7 row's Plan link;
  - `docs/` (flows and security);
  - `CHANGELOG.md` under `## [Unreleased]`.
- [ ] No secret or file content in `breaker_tripped`, the audit details or the logs (the payloads pass through the worker's redaction; `flip_flop` details hold hashes and counts, not contents).
- [ ] New source directories are seen by git (lessons 12: `git status --short` lists them).
