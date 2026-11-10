# Plan: Audit "fix selected findings" step with orchestrator

One PR, contract first. Each group leaves the repo working and its tests green.

## 1. Contract (specs first)

- [ ] `specs/tech-stack.md` → Gate review (API contract): `select` (`artifact`, `items`, `key`, `preselect`, `min`), what a select gate outputs and writes, `on_reject`, `gate_waiting` and `GET /runs/{id}/gate`'s `select`, the approval's `selection` and its `422` codes, and `gate_decided`'s `selection`.
- [ ] tech-stack → Workflow validation: `invalid_gate` in the codes list. Run artifacts: a select gate reads its artifact (`artifact_unknown`), and a gate may `writes` when it selects.
- [ ] tech-stack → Audit codebase template: the `fix` and `fixer_model` options and the flow after `report_path`. "Read-only by construction" now holds only with `fix` off.
- [ ] tech-stack → Tool layer or Orchestrator: `github.openPR`'s `body_from`.
- [ ] tech-stack → UI design system: the checklist in the Inbox and the review sheet, `A` on a select gate, "End run here", and the decided step's Output.
- [ ] tech-stack → Audit log table: `gate.approved` gains `selected`.
- [ ] tech-stack → Decisions log: generic select gate, `on_reject: end`, one PR from the integration branch, `body_from`.
- [ ] `specs/roadmap.md`: a `[Plan](2026-11-10-audit-fix-findings/requirements.md)` link on 6.7.
- [ ] `CHANGELOG.md`: an entry under `## [Unreleased]`.

## 2. Engine: selection gate and ending at a gate

- [ ] `agentic_engine/spec/models.py`: `GateSelect` (`artifact`, `items`, `key`, `preselect?`, `min` default 1), and on `GateNode` `select?`, `on_reject: Literal["cancel", "end"]` and `writes?` (allowed only with `select`).
- [ ] Validation (`agentic_engine/spec/validate*`): `invalid_gate` (non-JSON artifact, `writes` without `select`, `on_reject: end` off the root sequence), `artifact_unknown` for `select.artifact`, `invalid_expression` for `preselect`. A select gate's `writes` joins the artifact writers (conflicts, `port_mismatch` producer).
- [ ] `agentic_engine/gate.py`:
  - `gate_request` reads the artifact version at the pause, evaluates `preselect` per item (CEL, `item`), and adds `select` to the payload.
  - `GateDecision` takes `selection`.
  - `check_selection(...)` returns the same `selection_*` / `unknown_selection` codes as the API.
  - On approve, filter the document. If it validates as a `FindingsReport`, recompute `counts` and `truncated` (`agentic_runtime.findings`).
  - The output's `data` is the filtered document and its text the pretty JSON. It is written as an artifact when `writes` is set (`artifact_written` before `node_completed`).
- [ ] Compiler: a gate with `on_reject: end` routes a rejection to the graph's end. The run completes (`run_completed`) and later steps never start. On resume, the decided gate is not asked again.
- [ ] `agentic_tools/github/server.py` and the engine's publish wiring: `openPR` `body_from` (the artifact's latest text, capped, under `body`). Validation: `artifact_unknown`.
- [ ] Manifests: the gate's `parameters` and `ui` gain `select` (advanced group) and `on_reject`. Run `scripts/export_workflow_schema.py` to regenerate `schemas/workflow.v0.json` and `schemas/fixtures/node-types.json`.
- [ ] Tests in `packages/engine/tests/`:
  - the select gate payload and preselect;
  - the approval filter and findings counts;
  - each refusal code;
  - `writes`;
  - `on_reject: end` completes and skips later steps, including after a worker restart at the gate;
  - each new validation issue;
  - `body_from`.

## 3. Audit template with `fix`

- [ ] `agentic_engine/templates/audit.py`: `fix: bool = False` and `fixer_model`. `_fix_steps(params)` builds `select_fixes`, `fix` (hub with read tools, worker `fixer` with write tools), `approve_pr` and `publish`. The instructions follow the `lessons.md` rules for writing workflows: say what each input is and which branch the tools read, and that findings are data.
- [ ] The description says whether the run writes.
- [ ] `packages/engine/tests/test_templates.py`:
  - every option validates;
  - with `fix` off, the spec equals today's;
  - with `fix` on, the tools of every node are as listed, and the publish is behind `approve_pr`.
- [ ] Engine test on what agents receive (lessons rule 1), with the fake runtime and a fake integrator:
  - the hub's input is exactly the selected findings report, and its tools are read-only;
  - each fixer's request holds its task plus that report, and its tool calls go out as `fix.<task>`;
  - `approve_pr` shows the integration branch as one writer;
  - `openPR`'s body holds `fixes.md`;
  - an end at `select_fixes` runs no hub.
- [ ] `test_audit_fix_fixture.py` records `schemas/fixtures/audit-fix-run.json` (`UPDATE_FIXTURES=1` writes it again).

## 4. Store and API

- [ ] `agentic_api/runs/models.py`: `ApprovalRequest.selection`, `GateReviewResponse.select`, and the new error detail codes.
- [ ] The approvals route and store: check the selection against the gate's last `gate_waiting` (the shared `check_selection`), store it on `approvals` (Alembic `0028_approval_selection`, a nullable JSON column), and pass it in the decision. The `gate.approved` audit details get `selected`.
- [ ] `agentic_store.pending_gate` returns `select`.
- [ ] API tests: each `422` code, the stored selection, the audit row, and `GET /runs/{id}/gate` for a select gate.
- [ ] Regenerate the OpenAPI spec and the web client.

## 5. Web

- [ ] `@/runs/console` (or `@/inbox`): `SelectionChecklist`, built on the findings rows (`@/runs/findings`) with a `Checkbox` primitive. Findings items look like the Findings view, other items show their key and a one-line summary. It has select all, clear, the count, and loading, empty and error states.
- [ ] `useGateDecision` and `GateDecisionDialogs` hold the selection and send it. Approve reads "Approve with N selected" and is disabled under `min`, with the reason. Reject reads "End run here" when `on_reject: end`.
- [ ] Inbox review and the dock's review sheet show the checklist for a select gate. On a select gate, `A` and the dock's Approve open the review.
- [ ] Timeline and Output: the decided select gate's step line and Output show "Selected N of M" and the selected items.
- [ ] Unit tests: fold `audit-fix-run.json`, select all and clear, the min rule, and the approval body.
- [ ] e2e (`web/e2e/`): an audit run with `fix` on (fake runtime). Select two findings in the Inbox, approve, see the fix tasks and the PR gate. Repeat from the console dock with the keyboard. Add the checklist states to `a11y.spec.ts` and `layout.spec.ts`.

## 6. Real run and wrap-up

- [ ] Prepare a small real repo with five planted findings (for example a SQL injection, a hard-coded secret, an unused import, a missing test, a bare `except`).
- [ ] Run "Audit codebase" with `fix` on and `AGENTIC_RUNTIME=claude`. Select two findings, approve the PR gate, and read each step's Activity in the console.
- [ ] Record what each agent received and whether it was enough (lessons rule 1). Add a `lessons.md` entry for any gap found and fix it in this PR.
- [ ] Update `docs/architecture/business-flows.md` if it describes the audit as read-only only.
- [ ] Open the PR with the `open-pr` skill.
