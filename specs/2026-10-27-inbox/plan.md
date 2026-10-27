# Plan: Inbox

## 1. API: the pending gate
- [ ] `agentic_store.approvals`: `pending_gate(sessions, run_id)` returning the last `gate_waiting` payload (title, prompt, artifact, changes, changes_error, expires_at) for a waiting run, reusing `_waiting_gate_changes`
- [ ] `agentic_api.runs`: `RunGate` model (with `repo`, `base`, `branches`) and `GET /runs/{id}/gate` (`getRunGate`): `404` unknown run, `409` not waiting or expired
- [ ] pytest (Testcontainers): a waiting run with and without changes, `changes_error`, a run not waiting, an expired gate, an unknown run
- [ ] Regenerate `openapi.json` and `web/src/api/schema.d.ts`

## 2. Shared review components (no visible change)
- [ ] `src/runs/console/use-gate-decision.ts`: approve (with edits) / reject (comment), toasts, `409` expiry message, `A` / `R` through `useGateShortcuts`
- [ ] `src/runs/console/decision-controls.tsx`: `ApproveButton`, `RejectButton`, `GateArtifact` and `GateDecisionDialogs` (review sheet or details sheet, and the Reject dialog)
- [ ] `approval-dock.tsx` keeps only its bar and uses them
- [ ] Existing console Vitest and e2e (`gate-edits.spec.ts`, `monitor.spec.ts`) green unchanged

## 3. Inbox page (web)
- [ ] `src/inbox/waiting.ts`: `useWaitingRuns` (the shell's waiting list, one query key) and `inboxRuns` (oldest first, expired left out); `attention.tsx` uses them
- [ ] `src/inbox/use-run-gate.ts`: `GET /runs/{id}/gate` → `InboxGate` (a `PendingGate` with repo, base, branches; `parseChanges` from `gates.ts`)
- [ ] `src/inbox/inbox-review.tsx`: header, what approving does, `StatTile`s (active time, cost), changed files or artifact, Approve / Reject / Open run
- [ ] `src/inbox/inbox-view.tsx` (with the list) + `src/app/inbox/page.tsx`: two panes from 1024 px, stacked below; `?run=` selection; next gate after a decision; three states each
- [ ] Vitest: ordering and expiry filtering, selection from the URL, review content, approve/reject calls, `A` / `R`, empty and error states

## 4. Shell
- [ ] `nav.ts`: "Inbox" first (`InboxIcon`); `sidebar.tsx` shows the waiting count on Inbox, not Runs; breadcrumbs for `/inbox`
- [ ] Update shell Vitest (`nav.test.ts`, `app-shell.test.tsx`)

## 5. e2e and specs
- [ ] `e2e/inbox.spec.ts`: a run waits at a gate in the E2E workspace; from `/inbox` it is approved (button, then `A` on a second run) without visiting `/runs/{id}`; the run resumes and leaves the list
- [ ] Add `/inbox` to the page lists of `layout.spec.ts` and `a11y.spec.ts` (every page is covered, CLAUDE.md rule 10)
- [ ] tech-stack: "Inbox" section moved out of UI v2, "Waiting signals" and "Approval dock" updated, `GET /runs/{id}/gate` in the gate review contract; `CHANGELOG.md`
