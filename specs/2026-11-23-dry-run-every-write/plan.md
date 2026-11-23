# Plan: Dry run for every write

The plan contract and the tools' plan modes come first, then the engine plans before a gate and checks what it applies. API, events and audit follow, then the UI, then a real run. Read `specs/lessons.md` before group 1: this changes the tools and the engine. It does not change what agents receive (plans are for people), but its Jira and GitHub calls are checked against the real services (lessons 10).

## 1. The plan contract and plan mode in the tools

- [x] `agentic_runtime.plans` (new):
  - `WritePlan` (`node_id`, `tool`, `action`, `summary`, `target`, `fields`, `body`, `pending`, `expect`, `error`) and `PlanTarget`.
  - `compare(plan, result) -> list[Difference]`, the per-tool compared fields.
  - `same_plan(shown, again) -> list[Difference]`, which compares `fields`, `expect` and the body without its `pending` parts.
  - Export the model as `schemas/write-plan.v1.json`.
- [x] `agentic_tools.strict.strict_tool`: accept the engine-only `plan` and `expect` on the tools that declare a plan mode, and refuse them on every other tool.
- [x] `agentic_tools.jira.server`:
  - `comment` and `transition` take `plan`. In plan mode they resolve the site and issue exactly as the real call does and return a `WritePlan` (structured), posting and moving nothing.
  - With `expect`, `transition` refuses with `plan_stale: …` when the status or the transition id changed. `comment` refuses when the issue now answers from another project.
  - The `links_from` placeholder comes from the engine (group 2). The tool only puts the footer in place.
- [x] `agentic_tools.github.server`:
  - `open_pr` in plan mode exports the bundle and reads the tip and the commit count without pushing (`export_branch`). It resolves the base as the real call does and reports an open pull request from the head.
  - The 7.6 follow-up variant reads the PR's head and checks the fast-forward from `after_sha`.
  - `create_repo` in plan mode calls `get_repo` to say whether the name is free, or taken by this run.
  - With `expect`, `open_pr` refuses when the tip differs, and `create_repo` refuses when the name was taken by someone else.
- [x] `agentic_engine.spec`:
  - `OUTWARD_WRITE_TOOLS = PUBLISH_TOOLS | CREATE_TOOLS | JIRA_WRITE_TOOLS`.
  - A tool node's `args` may not set `plan` or `expect` (`reference`).
  - Regenerate the JSON Schema and check that the manifests do not show either.
- [x] Tool tests (`packages/tools/tests`):
  - Each plan matches what the real call then does, on `FakeAtlassian` and `FakeGithubApp`.
  - Plan mode writes nothing: `posted`, `moved` and pushes stay empty, and no repo is created.
  - `transition_unavailable` and "no change" plans.
  - `plan_stale` for each `expect`.
  - Every tool in `OUTWARD_WRITE_TOOLS` has a plan mode (`test_every_outward_write_has_a_plan_mode`).

## 2. The engine plans before a gate

- [x] `agentic_engine.spec.models`: `planned_writes(root) -> dict[gate_id, list[write_id]]`. A gate gets every outward write after it in run order, up to the next gate that counts for that write under validation's scope rule (`_runs_in`, `within`). `wait_for` plans nothing. Tests: SDD with and without checks and review (`approve_pr` plans `publish`, `jira_update` and `move`), docs, audit fix, new repo (`approve_repo` plans `create_repo`), and SDD's `post_questions` plans `ask_jira`.
- [x] `graph/compile.py`:
  - `plan_node_id(gate)` (`<gate>.plan`) and `_plan(gate, tools, log, limits)`, placed after `<gate>.evidence` and `<gate>.review` and skipped on their send-back.
  - It resolves each write's arguments with the helpers the tool node uses (`_with_issue_from`, `_with_body_from`), puts the `links_from` and `notes_from` placeholders in, and calls each tool with `plan: true` through the executor, routed as the write node (`node_id=write.id`).
  - It writes `writes_planned` and stores `RunState.plans[write_id] = {gate, plan}`, so the last gate's plans win.
- [x] `agentic_engine.gate.gate_request` and the runner: `gate_waiting` carries `plans`. `events.py`: `WRITES_PLANNED`, documented.
- [x] Engine tests (`test_write_plans.py`, fake runtime and fake tools):
  - The SDD gate shows three plans, in run order.
  - The plans of a gate in a loop are made again on each pass.
  - A gate that sends the work back plans nothing.
  - A worker restart between `<gate>.plan` and the gate does not plan twice.
  - A plan error (`transition_unavailable`) still lets the gate pause and show it.

## 3. The engine applies against the plan

- [x] `graph/compile.py`, the tool-node path:
  - Before the first write of a gate's batch, call plan mode again for every write in the batch and run `same_plan` against `RunState.plans`. The expected tip is moved first to the gate's edit commit (`gate_decided.commits`), and the review notes become concrete.
  - On a difference, the step fails `plan_stale: <what changed>` and nothing is written. The batch check runs once per batch: the state records that it passed, so a resumed step does not repeat it.
  - Each write is called with its `expect`.
- [x] After each write, `compare(plan, result)` with the links and review notes filled in from the platform's results. It writes `write_checked` (`gate`, `plan`, `result`, `outcome`, `differences`). A stale refusal writes `outcome: stale` with what is true now. `events.py`: `WRITE_CHECKED`, documented.
- [x] A write with no plan in the state (a spec validation should have refused) fails `plan_missing` instead of writing unshown.
- [x] Engine tests:
  - Approve as planned gives `as_planned` for all three SDD writes, and the comment's links are filled in.
  - A fake issue moved while the gate waits gives `plan_stale`, no pull request is opened and Jira is untouched.
  - A gate edit gives `as_planned`, with the edit commit pushed.
  - A result that differs is flagged and the run goes on.
  - A follow-up (7.6) push is planned and checked.
  - A new repo is planned and checked.
  - A restart after the batch check and before the first write does not check twice and writes once.

## 4. Store, API and audit

- [x] `agentic_store`: `pending_gate` returns `plans` from the last `gate_waiting`. The audit gains `write.not_as_planned` (from `write_checked` `differs`) and `write.plan_stale` (from `stale`), actor system, with the node, the tool and the fields.
- [x] API (`runs/routes.py`, `runs/models.py`): `GET /runs/{id}/gate` `plans` (`WritePlanView`). Regenerate the OpenAPI spec and the web client.
- [x] Tests, run from `packages/api` (the root `.env` breaks `create_app` in tests): the gate view's `plans`, the audit rows, and one `plans` payload over the round trip.

## 5. What approving does, in the web

Read `specs/design-language.md`, tech-stack → UI design system, and `web/AGENTS.md` first.

- [ ] `@/runs/timeline`: fold `writes_planned` into `GateInfo.plans`, and `write_checked` into the write step (`outcome`, `differences`).
- [ ] `WritePlans` (`web/src/runs/console/write-plans.tsx`, new):
  - One card per plan: a lucide icon for its kind (`aria-hidden`), the summary, and the target (`repoLabel` in mono; the issue key in mono, linked only when its address is https).
  - The body through the sanitised Markdown renderer (`AgentMessage`), capped with "Show full".
  - A transition as "from → to" in text, the placeholders as quiet `text-meta` lines.
  - "Would fail" with `StatusBadge` and the error as text.
  - Loading, empty and error states (rule 5) for a caller that loads its own data.
- [ ] Use it in `inbox/inbox-review.tsx` (in place of "Approving lets the run go on" when there are plans), in `approval-dock.tsx` and `gate-review-sheet.tsx` (details and review sheets), and in the gate step's Output (`step-output.tsx`).
- [ ] `step-output.tsx` and `step-list.tsx`: a write step shows "As planned at <gate>", or a `StatusBadge` "Not as planned" with the differences as a list of field, planned and actual, as text.
- [ ] `web/src/audit/actions.ts`: lines for `write.not_as_planned` and `write.plan_stale`.
- [ ] Tests: `write-plans.test.tsx` (each kind, a plan that would fail, the placeholders, a non-https issue URL left unlinked, Markdown with HTML dropped), the timeline folding, `inbox-view.test.tsx`, the audit formatter, and the e2e and axe specs below.

## 6. Specs, docs and a real run

- [ ] `specs/tech-stack.md`:
  - a "Write plans (API contract)" section with the contract, the plan step, the batch check, `expect`, `write_checked`, the audit actions and `GET /runs/{id}/gate` `plans`;
  - a Tool layer bullet with the rule "every outward write tool has a plan mode";
  - a UI design system → "What approving does (13.8)" subsection;
  - decisions-log rows for the choices in requirements.md, replacing 7.2's "stays in 13.8" note.
- [ ] `specs/roadmap.md`: add the `[Plan](2026-11-23-dry-run-every-write/requirements.md)` link to the 13.8 row. `CHANGELOG.md`: an entry under `## [Unreleased]`.
- [ ] `docs/` (security model or the gates guide, whichever describes what a gate shows): one paragraph on the plans and `plan_stale`.
- [ ] A real run (validation.md), recorded in `specs/2026-11-23-dry-run-every-write/findings.md`. If it shows a mistake the tests missed, add a `lessons.md` entry in the same PR.
