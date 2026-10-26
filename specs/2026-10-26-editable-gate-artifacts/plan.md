# Plan: Editable artifacts in the approval dock

Backend first (PR A: groups 1–4), then the web and end-to-end checks (PR B: groups 5–7). The project stays green after each group. PR B is the one that touches this spec folder.

## 1. Contract first (docs)
- [ ] `specs/tech-stack.md`: add "Gate review (API contract)" with these parts:
  - the `changes` entry shape;
  - the editability rules and the caps (50 files, 256 KB per file, 512 KB in total);
  - `edits` on `POST /runs/{id}/approvals` and its `422` codes (`edit_not_allowed`, `edits_with_reject`, `edit_too_large`, `duplicate_edit`);
  - the commit made on approve and what `gate_decided` records.
- [ ] Same file, UI design system → Approval dock: the wide review sheet, the diff rules, "Approve with N edits", and the decided-with-edits step. Add a decisions-log row "Gate edits".

## 2. Engine: `GateReview` and edits in the decision
- [ ] `packages/engine/src/agentic_engine/gate.py`:
  - add `FileChange` and `FileEdit` (Pydantic, frozen) and `GateDecision.edits: list[FileEdit] = []`;
  - add a `GateReview` protocol (`changes(gate_id, writer_ids) -> list[FileChange]`, `apply(gate_id, edits) -> dict[node_id, commit]`).
- [ ] Caps and editability rules live as constants next to them (`MAX_REVIEW_FILES`, `MAX_REVIEW_FILE_BYTES`, `MAX_REVIEW_TOTAL_BYTES`), so the worker, the API and the tests share them.
- [ ] `graph/run.py`:
  - `run_workflow` / `resume_workflow` take `review: GateReview | None`;
  - `_wait` asks it for the changes of the writers that completed before the gate (from `state["order"]` and `writer_node_ids`) and adds `changes` to the `gate_waiting` payload (`[]` without a review).
  - Announcing the pause again on a resume without a decision recomputes the changes.
- [ ] `run_gate_node`: on approve with edits, call `review.apply` and add `edits` and `commits` to the `gate_decided` payload. An apply error ends the node `failed` with the reason. Reject never applies.
- [ ] Engine tests in `packages/engine/tests/test_gate.py` with a fake `GateReview`:
  - the payload carries the changes;
  - approve with edits calls apply once and logs them;
  - reject does not call apply;
  - a resume after a crash past the apply calls it again, and the fake shows it is idempotent.

## 3. Worker: `GateReview` over the sandbox
- [ ] `packages/sandbox/src/agentic_sandbox/review.py`:
  - `branch_changes(sandbox, run_id, node_ids)` runs one script per writer: `git diff --name-status -z <base>..<branch>`, `git cat-file -s`, and a NUL check, then `git show` for the editable files, within the caps. It returns `FileChange`s.
  - `commit_edits(sandbox, run_id, node_id, gate_id, edits)` writes each file into the worktree through `put_file` and a move with the same path checks as `repo.write_file` (reuse `agentic_tools/repo/paths.py`, or move it into `agentic_sandbox` if the import goes the wrong way). Then `git add` and `git commit` with `GIT_SAFETY` and `AGENT_IDENTITY`, the message `Edit at gate <id>` and the trailer `Edited-by: reviewer`. With no diff it makes no commit and returns the branch tip.
- [ ] `packages/worker/src/agentic_worker/main.py`: build a `SandboxGateReview` from the run's sandbox when the run has a repo, and pass it to `_workflow` → `run_workflow` / `resume_workflow`.
- [ ] Sandbox tests (`packages/sandbox/tests/`, Docker backend as in `test_docker_sandbox.py`) for:
  - added, modified, deleted, renamed, binary, too-large and over-limit files;
  - an edit committed on the branch;
  - a second apply with the same edits, which makes no commit;
  - a path escaping the worktree, which is refused.

## 4. Store and API: edits on the approval
- [ ] Alembic `0018_approval_edits.py`: `approvals.edits JSONB NULL`. `Approval.edits` in `models.py`.
- [ ] `agentic_store/approvals.py`:
  - `record_approval` checks the edits against the last `gate_waiting` payload's `changes` and raises `InvalidEditsError(code, message)`;
  - stores the edits with equal-to-`after` ones dropped;
  - `pending_decision` returns them in `GateDecision.edits`.
- [ ] `agentic_api/runs/models.py`: `ApprovalRequest.edits: list[FileEditIn] | None` with field limits. `routes.py` maps `InvalidEditsError` to `422 {code, message, path}`. `ApprovalResponse` gains `edited_files: int`.
- [ ] Tests:
  - `packages/store/tests/test_approvals.py`: every `422` code; edits stored and read back; edits equal to `after` dropped.
  - `packages/api/tests/test_runs.py`: approve with edits returns `202`, and each error returns its `422`.
  - Worker integration on the fake runtime with a sandbox: a docs-shaped run pauses with `changes`, is approved with an edit, and the bundle `openPR` pushes contains the edit commit (`agentic_github/testing.py` fake).
- [ ] CHANGELOG entry (backend part). Open PR A.

## 5. Web: review sheet with Monaco
- [ ] Check the Monaco setup with ctx7 (`@monaco-editor/react`, local `monaco-editor`, workers under Next.js 16). Add both to `web/package.json`.
- [ ] `npm run gen:api` for the new approval request and response.
- [ ] `web/src/runs/gates.ts`: parse `changes` into `PendingGate.changes` and defend against bad payloads (data, never instructions). Add `decidedGate(events)` with the edits from `gate_decided`.
- [ ] `web/src/runs/console/use-gate-edits.ts`: edits state per file (dirty, discard, count), and `beforeunload` while dirty.
- [ ] `web/src/runs/console/gate-review-sheet.tsx`:
  - layout: a file list (status icon + label, "Edited", read-only reason), or a Select below 1024 px, and a lazy `DiffEditor` (side by side from 1024 px, inline below);
  - theme from `next-themes`; read-only original; modified side editable when the file is editable;
  - footer: "N files edited", Discard, and "Approve with N edits" / Approve.
  - Loading skeleton while Monaco loads, and an error state with Retry if it fails to load.
- [ ] `approval-dock.tsx`:
  - "Review details" opens the review sheet when `changes` is non-empty, else the current sheet;
  - Approve sends `edits` and its label shows the count;
  - Reject with edits says they will be dropped;
  - a `422` shows in an `Alert` in the sheet, naming the file.
- [ ] `use-gate-shortcuts.ts`: confirm that Monaco's textarea counts as an editable field. Add a test.
- [ ] Timeline gate step and graph node sheet: "Approved with edits to N files", each file opening a read-only diff (`after` → edit) in the same sheet component.

## 6. Web tests
- [ ] Vitest:
  - `gates.test.ts` for parsing `changes` and decided edits, including malformed payloads;
  - `use-gate-edits.test.ts`;
  - `gate-review-sheet.test.tsx` (Monaco mocked with a textarea), covering the file list, dirty state, discard, the Approve label, read-only files, the `A` shortcut not firing in the editor, and the `422` Alert.

## 7. End to end, demo and wrap-up
- [ ] Playwright `web/e2e/gate-edits.spec.ts` on the docs run over the fixture repo (fake runtime, fake GitHub):
  - open Review details and pick a page;
  - type in the modified side, then Approve with 1 edit;
  - the step shows "Approved with edits to 1 file";
  - the `publish` result's commit is on the fixture remote with the edit. Check through `git show` in the compose fixture, or the `gate_decided` commit equal to the pushed head.
- [ ] Add the review sheet to `a11y.spec.ts` (axe, light and dark) and `layout.spec.ts` (375 / 768 / 1440 px, no horizontal scroll).
- [ ] Manual demo on a real GitHub repo (see validation.md). Note the PR link in PR B's description.
- [ ] CHANGELOG entry (web part). Open PR B; CI marks 3.6 done.
