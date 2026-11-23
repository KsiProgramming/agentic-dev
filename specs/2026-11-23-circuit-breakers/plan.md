# Plan: Circuit breakers

One breaker (repeat) goes end to end first, through engine, store, API and console, so the pause and resume path is proved before the other three detectors use it. Read `specs/lessons.md` before group 1: it changes the engine and what agents receive.

## 1. Breaker policy, the watcher and the pause (engine)

- [x] `agentic_engine.policy`: add `BreakerPolicy` (`repeat_calls`, `repeat_errors`, `cost_multiple`, `cost_floor_usd`, `flip_flops`) with the defaults and `BREAKER_RANGES`. Add `Policy.breakers`, defaulted so runs frozen before 13.7 still load. Add `with_breakers(policy, spec_breakers)`, which applies workflow over workspace over platform, clamped to the ranges.
- [x] `agentic_engine.spec`: add `WorkflowSpec.breakers` (optional, per field). Validation reports `breakers_out_of_range`. Regenerate the JSON Schema in `schemas/`.
- [x] `agentic_engine.breakers` (new):
  - `BreakerWatch`, one per step execution. `see(event)` raises `BreakerTripped` with `breaker`, `trigger`, `threshold`, `observed`, `details` and `reason`.
  - The repeat breaker: canonical arguments with `description` dropped; error text with whitespace collapsed and cut at 500 characters.
- [x] `events.py`: add `BREAKER_TRIPPED` with its payload documented.
- [x] `graph/compile.py`: create a watch where each agent, classifier and hub step starts. Feed it beside `limits.budget.add`, at the three `on_event` sites (agent, router classifier, orchestrator hub), and in orchestrator tasks and review lenses through the agent path.
- [x] `graph/run.py` `_finish`: catch `BreakerTripped` (also as a `CancelledError` arg, as `PolicyLimitExceeded` is caught). The running nodes end `node_cancelled`. Then write `breaker_tripped`, then `gate_waiting` on the tripped node with `breaker`, `ttl_s` from `approval_ttl_s` and `expires_at`, and return `waiting` (`waiting_at` is the tripped node).
- [x] Engine tests (`test_breakers.py`, fake runtime):
  - A scripted agent repeating a failing call pauses at 3 errors. One repeating a successful call pauses at 5.
  - The thresholds come from `Policy.breakers`.
  - A trip inside one parallel branch cancels the other, and the run ends `waiting`.
  - Each map item has its own counters.

## 2. Resume and cancel (engine, worker, store, API)

- [x] `resume_workflow`: take a breaker decision.
  - `approve`: write `gate_decided` `{decision, source: "breaker"}` after `run_resumed`, then go on from the checkpoint (`start=None`).
  - `reject`: write `gate_decided` and `run_cancelled` (reason "Cancelled after a circuit breaker"), with no graph run.
- [x] "# Paused before" (`agentic_engine.agent`):
  - Build the section from the trip (breaker, threshold, observed, and the call, error or path between tags, as data). Add it after "# Protected paths", for the tripped node's next run only.
  - `node_started` carries `resumed_after`.
  - The worker reads the trip from the pause's `gate_waiting` payload and passes it in, as `RunContext` items are passed.
- [x] Worker (`agentic_worker.main`): pass the recorded decision for a breaker pause. Add `BREAKER_PAUSE_EXPIRED_REASON` to `_end_cancelled`'s expired reasons. A worker restart while paused leaves the run waiting.
- [x] Store:
  - `sink.py`: `breaker_tripped` adds one to `runs.breaker_trips`. `waiting_gate` keeps `breaker`.
  - `approvals.py`: `record_approval` accepts a breaker pause for `approve` and `reject` only (`breaker_decision_invalid`).
  - `expiry.py`: a breaker pause gets its own reason.
  - `audit.py`: `breaker.tripped`, `breaker.resumed`, `breaker.cancelled`, `breaker.expired`.
- [x] Alembic `0043_circuit_breakers`: `runs.breaker_trips` (int, default 0) and `runs.cost_baselines` (JSONB, null).
- [x] API (`runs/routes.py`, `runs/models.py`): the approvals docstring and `422 breaker_decision_invalid`, `waiting_gate.breaker` in summaries, `GET /runs/{id}/gate` `breaker`, and `breaker_trips` on `GET /runs/{id}`. Regenerate the OpenAPI and web client.
- [x] Tests:
  - Engine: Resume reruns the tripped step and not the steps that completed. What the resumed agent receives: its system prompt holds "# Paused before", and its input is unchanged (lessons 1). Reject cancels.
  - Store and API, run from `packages/api` (the root `.env` breaks `create_app` in tests): status `waiting`, waiting time, the approval round trip, `422`, expiry, audit rows, and a restart while paused.

## 3. A pause in the console, the Inbox and the runs list (web)

Read `specs/design-language.md`, tech-stack → UI design system, and `web/AGENTS.md` first.

- [ ] `@/runs/summaries`: `badgeStatus` and `statusLabel` map a waiting run with `breaker` to "Paused" (the waiting colour). `@/runs/status` `displayStatus` does the same for the live console. The page title prefix reads "● Paused".
- [ ] `@/runs/timeline`: fold `breaker_tripped` and `gate_waiting.breaker` into the step: status "Paused", and `GateInfo.breaker`.
- [ ] `BreakerDetails` (`web/src/runs/console/breaker-details.tsx`), all through `@/components/display`:
  - the breaker as a neutral badge and the reason as text;
  - the threshold and what was seen;
  - the tool (mono) and its `describeTool` line;
  - the error clamped to two lines, as text;
  - cost as `Money` against the average;
  - the path as `TruncatedPath` with the declared globs (mono);
  - the flipped file and its flip count.
  - It has loading, error and empty states (rule 5).
- [ ] `run-banner.tsx`: the paused variant ("Paused by a circuit breaker: <reason>", `ExpiresIn`, Go to step, Resume, Cancel run).
- [ ] `approval-dock.tsx` and `decision-controls.tsx`: labels Resume and Cancel run for a breaker pause. Cancel run asks in a dialog. `A` and `R` keep working.
- [ ] Step Output (`step-output.tsx`) shows `BreakerDetails` for the tripped step. Step Input (`step-input.tsx`) shows "Paused before" from `node_started.resumed_after`.
- [ ] `run-tiles.tsx`: a "Breakers" tile only above zero, in the same responsive grid rule as Protected files.
- [ ] Inbox (`inbox-review.tsx`, `use-run-gate.ts`): a breaker pause's review is `BreakerDetails`, Resume and Cancel run.
- [x] Audit log formatter: the four `breaker.*` actions (done with group 2, so the typed action map stays whole).
- [ ] Vitest: `breaker-details.test.tsx`, the banner, dock labels, the timeline fold, `badgeStatus`, and the Inbox review.
- [ ] e2e:
  - Add a test-only scripted repeat to the stack's fake runtime (`fake_runtime_factory`): an agent whose instructions start with `[fake:repeat-failing-call]` calls `repo.read_file` on a missing path until it is stopped.
  - `web/e2e/breaker.spec.ts`: the banner, Resume (the run goes on), Cancel (a confirm dialog), and the Inbox entry.
  - Add the paused console to `a11y.spec.ts` and `layout.spec.ts`.

## 4. The cost, paths and flip-flop breakers (engine, tools, store)

- [ ] **Cost:**
  - `agentic_store` `cost_baselines(sessions, workflow_key, node_ids)` returns the mean per execution from `usage` events of the last 20 completed runs, keeping nodes with 5 or more runs.
  - `create_run` stores the result on the run. The worker passes it to the engine. The watch sums the step's `estimated_usd` and trips at `max(multiple × avg, avg + floor)`.
  - Tests: a store test on seeded runs, and an engine test.
- [ ] **Paths:**
  - `AgentNode.paths` (glob list), with validation `paths_without_writes` and glob syntax.
  - The watch trips on `tool_call` `repo.write_file` outside `paths`.
  - `DeclaredPaths` in `agentic_runtime.tools`, beside `ProtectedPaths`, set by the engine per step. `repo.write_file` and `repo.commit` refuse a path outside it with one fixed text.
  - Check whether the Copilot adapter emits `tool_call` before it runs the tool, and record the answer.
  - Tests: an engine test proves the tool is never called; tool tests cover write, commit, rename and a symlinked directory.
- [ ] **Flip-flop:** the watch keeps each path's content hashes for the step, counts returns to an earlier content, and trips at `flip_flops`. Engine test.
- [ ] Each breaker's `reason` is a fixed sentence pattern, so the console and the "# Paused before" text say the same thing. Add a test per breaker.

## 5. Thresholds: workspace, workflow, builder (API, web)

- [ ] `PUT /workspaces/{id}/policy` takes `breakers`. `GET` returns `defaults`, `ranges`, `overrides` and `effective` for them. Add API tests.
- [ ] `create_run` and rerun resolve `with_breakers` and freeze them in `runs.policy`. `POST /workflows/{id}/validate` gives the same errors as the spec.
- [ ] Node manifests: `paths` in the agent manifest and `breakers` as a document param, both `advanced`. Add a shared case to `schemas/fixtures/graph-ops.json` if `breakers` is a document param.
- [ ] Web: a "Circuit breakers" card in `web/src/settings/run-limits.tsx` (units, ranges in help text, the sticky save bar, Reset to defaults). The builder's side panel shows `paths` and `breakers` from the manifest with no new code beyond the field types. Add Vitest for the card.

## 6. Specs, docs and the real run

- [ ] `specs/tech-stack.md`:
  - a "Circuit breakers (API contract)" section (breakers, thresholds and ranges, events, pause and resume, the approvals codes, the cost baseline, "# Paused before");
  - Security & secrets: breaker thresholds beside the policy limits;
  - Tool layer: declared paths beside protected paths;
  - UI design system: Run console banner, dock, step status and tile, Inbox, Settings card;
  - decisions log rows for each decision in `requirements.md`, and the Copilot `tool_call` order.
- [ ] `specs/roadmap.md`: add `[Plan](2026-11-23-circuit-breakers/requirements.md)` to the 13.7 row.
- [ ] `docs/architecture/technical-flows.md` (the pause and resume flow) and `docs/security/` (breakers as a guardrail).
- [ ] `CHANGELOG.md` under `## [Unreleased]`.
- [ ] Real Claude run (`AGENTIC_RUNTIME=claude`, real repo): a one-agent workflow told to read a file that does not exist "until it succeeds".
  - Read step by step in the console: it pauses at 3 errors with the reason; Resume; the resumed agent's Activity shows that it read "# Paused before" and acted differently; the run goes on.
  - Then try one paths trip on a writer with `paths: ["docs/**"]` asked to edit `README.md`.
- [ ] `specs/lessons.md`: add an entry if the real run shows something the tests did not.
