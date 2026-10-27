# Plan: Start, approve and rerun

Delivery is three stacked PRs. A and B are branched from `main`, do not touch this spec folder, and merge on their own. This branch (`plan/2.6-start-approve-rerun`) holds the spec folder and the roadmap merge of the former approval dock, rerun and start screen phases into 2.6. It is opened as a draft PR for plan review, rebased after A and B merge, and finished as PR C, which marks 2.6 done.

---

## PR A: Start screen and settings (`feat/2.6a-start-settings`)

### 1. Design rules first
- [x] `specs/tech-stack.md` → UI design system:
  - Add the template gallery card, the "New run" sheet (side on desktop, full-height bottom sheet under 768 px), the connection card states, the combobox, and form field errors.
  - Add the waiting count badge and tab-title rule, and the dock keyboard shortcuts.

### 2. Backend: templates, key verification, GitHub manage URL
- [x] `agentic_engine/templates`: each template declares `requires` (`generate-docs` → `["claude", "github"]`). `GET /templates` returns it (`templates/routes.py`, `models.py`).
- [x] Claude key verifier:
  - [x] Add a `ClaudeKeyVerifier` protocol and an Anthropic implementation (one list-models call, timeout 10 s).
  - [x] `PUT …/connections/claude` → 422 `{code:"invalid_key"}` or 502 `{code:"verify_unavailable"}`, and stores nothing on failure.
  - [x] Redact the key from every log and error.
- [x] `ConnectionOut.manage_url` for GitHub:
  - User account: `https://github.com/settings/installations/<id>`.
  - Org: `https://github.com/organizations/<login>/settings/installations/<id>`.
  - Store `account_type` on connect if it is missing (small migration if needed).
- [x] Fake mode (dev and e2e only; the API refuses to start with it when `AGENTIC_ENV=production`):
  - [x] Fake key verifier when `CLAUDE_KEY_CHECK=fake` (its own setting, so a dev on the fake runtime can still save a real key): the `sk-ant-test-` prefix passes.
  - [x] `AGENTIC_GITHUB=fake`:
    - The install URL redirects straight to `/github/setup` with a fake installation.
    - Fixed repos (`e2e-org/docs-demo`, `e2e-org/private-lib`).
    - Clones of `https://github.com/e2e-org/<name>` resolve to `/fixtures/<name>.git`.
    - A fake `openPR` returns `…/pull/<n>`.
  - [x] `docker-compose.yml`: seed the bare fixture repo (init service or entrypoint) and add the env vars, defaulting to off.
- [x] pytest:
  - [x] `test_templates.py` (`requires`).
  - [x] `test_workspaces.py`: valid, invalid and unavailable key with a stubbed verifier; the key is not in caplog.
  - [x] `test_github.py` (`manage_url`, fake mode).
  - [x] The production guard.
- [x] Regenerate the OpenAPI spec and client (`scripts/export_openapi.py`, `pnpm gen:api`).

### 3. Frontend foundations
- [x] Add the shadcn components `command`, `popover`, `form`, `dialog`, `checkbox` and `separator`, plus the `react-hook-form`, `zod` and `@hookform/resolvers` deps.
- [x] `web/src/api/queries/`: add `useTemplates`, `useConnections`, `useRepos`, `useSaveClaudeKey`, `useRemoveClaudeKey`, `useStartGithubInstall` and `useDisconnectGithub`, with cache invalidation after mutations.
- [x] `web/src/forms/schema-form/`:
  - [x] JSON Schema subset → fields + zod schema.
  - [x] Unsupported schema → error.
  - [x] Map a server 422 `loc` onto fields.
  - [x] Vitest coverage of every supported keyword and the unsupported path.

### 4. Settings redesign
- [x] `settings/connection-card.tsx`: a shared card with icon, title, purpose, status badge and an actions slot.
- [x] `settings/claude-key-form.tsx`: react-hook-form, a password input and a verify-on-save error on the field. It is reused by the sheet.
- [x] Rewrite `claude-connection.tsx`:
  - Not connected → form; connected → hint + updated time + Replace / Remove.
  - Remove confirms in an `AlertDialog`.
- [x] Rewrite `github-connection.tsx`:
  - States: not configured, not connected, connected (login, "N repositories accessible" collapsible, Manage on GitHub, Disconnect with confirm), and needs attention (`installation_gone` → Reconnect).
- [x] Update the Vitest tests for both cards. Drop the old `useEffect` loaders.

### 5. Template gallery and "New run" sheet
- [x] `templates/template-gallery.tsx`: cards (icon, name, description, "Requires" chips with live status, Start) plus skeleton, empty and error states.
- [x] `runs/new-run/new-run-sheet.tsx`:
  - [x] Template picker when opened from Runs.
  - [x] "Before you start" checklist from `requires`, with inline Claude key form and GitHub Connect that returns to `/templates?template=<id>`.
  - [x] Repo combobox (`repo-combobox.tsx`) with last-used preselect and the "Add repos on GitHub" footer.
  - [x] Schema fields.
  - [x] Submit `POST /runs`, then `router.push` to the run.
- [x] `/templates` page: header "Start a run", the gallery, and a `?template=` deep link that opens the sheet.
- [x] Runs page header: "New run" primary action.
- [x] Remove `docs-card.tsx`, `start-run-form.tsx` and `sample-spec.ts` and their tests (keep any sample-spec use in backend tests).
- [x] Vitest: gallery states, sheet checklist gating, combobox search and keyboard, last-used preselect, 422 mapping.

### 6. PR A e2e
- [x] Rewrite `monitor.spec.ts` "start from templates": gallery → sheet → combobox → submit → console.
- [x] `layout.spec.ts` + `a11y.spec.ts`:
  - Settings: not connected, connected and needs-attention states.
  - Gallery.
  - Sheet: checklist state and filled state.
  - Light and dark.
- [x] CI e2e job: enable `AGENTIC_GITHUB=fake` and the fixture repo.

---

## PR B: Approval dock and waiting signals (`feat/2.6b-approval-dock`)

### 7. Dock
- [x] `runs/gates.ts`: `gateSummary(gate)` (prompt, else the first non-empty artifact line, ≤ 140 chars), with unit tests.
- [x] `runs/console/approval-dock.tsx`:
  - [x] Layout: fixed to the bottom of the content area, safe-area inset, and a ResizeObserver that sets `--dock-height` for the page's bottom padding.
  - [x] Content: title, summary, "Review details" sheet (right side ≥ 768 px, bottom below that) with the prompt and the artifact in mono or Markdown (no raw HTML).
  - [x] Approve: one click.
  - [x] Reject: a `Dialog` with an optional comment → `POST /runs/{id}/approvals {node_id, decision, comment}`.
  - [x] Pending: buttons disabled, then a toast.
  - [x] Hides on `gate_decided`.
  - [x] Accessibility: `role=region`, `aria-label="Approval needed"`, polite announcement, no focus steal.
  - [x] Layering: z-index above content and below the sheet, dialog and drawer layers.
  - [x] Actions stack full width at 375 px.
- [x] Keyboard shortcuts with a `useGateShortcuts` hook:
  - `A` approves and `R` opens the reject dialog.
  - Ignored in inputs, textareas, contenteditable and while any dialog or sheet is open.
  - `aria-keyshortcuts`, and `<kbd>` hints from 768 px.
- [x] Replace `GatePanel` in `run-console.tsx` / `step-view.tsx` with the "Waiting for approval" marker (its button focuses the dock). Delete `gate-panel.tsx` and its test.
- [x] Vitest:
  - Dock appears and hides, approve, reject with comment, pending state.
  - Shortcuts: fire, ignored in a field, ignored with a dialog open.

### 8. Waiting signals
- [x] `runs/use-waiting-runs.ts`: the workspace waiting count from `GET /runs?status=waiting`, kept live by `GET /runs/stream` (reuse `use-runs-stream`).
- [x] Sidebar "Runs" badge (`components/shell/`) and the mobile drawer trigger badge, labelled "N runs need approval".
- [x] `useDocumentTitle`:
  - On the console of a waiting run: "● Needs approval · Run abcd1234".
  - Elsewhere while N > 0: "(N) ● Needs approval · <title>".
  - Restore on unmount.
- [x] Runs list: a "Review" button on waiting rows (table and cards).
- [x] Vitest: badge count updates from the stream, title rules, Review button.

### 9. PR B e2e
- [x] Rewrite `monitor.spec.ts`: start a docs run on the fixture repo; at the gate, approve from the dock; the fake PR link appears.
- [x] `layout.spec.ts`: at 375, 768, 1024 and 1440, assert the dock is fully inside the viewport (`boundingBox` within `viewport`) and that the last timeline item is not covered.
- [x] `a11y.spec.ts`: dock, details sheet and reject dialog, in light and dark.

---

## PR C: Rerun, then mark 2.6 done (this branch)

### 10. Backend
- [x] Alembic migration: `runs.template_parameters` JSONB (nullable). `test_migrations.py` covers it.
- [x] `agentic_store/runs.py`: `create_run(..., template_parameters=None, rerun_of=None)`. `POST /runs` stores `template.parameters`.
- [x] `POST /runs/{id}/rerun` in `runs/routes.py`:
  - [x] Load the original. 404 if it is unknown; 409 `run_not_ended` unless it is failed, cancelled or succeeded.
  - [x] Copy spec, input, repo, workspace, `template_id` and `template_parameters`; set `rerun_of`.
  - [x] Same connection checks as `POST /runs`; enqueue; return `CreateRunResponse`.
- [x] pytest (`test_runs.py`):
  - [x] Copied fields are equal, and `rerun_of` is set.
  - [x] The original row and events are unchanged.
  - [x] 404, and 409 for queued, running and waiting.
  - [x] 409 after GitHub is disconnected.
  - [x] A rerun of a rerun points to its parent.
  - [x] It appears in `GET /runs` with `rerun_of`.
- [x] Regenerate the OpenAPI spec and client.

### 11. Frontend
- [x] `runs/use-rerun.ts`: mutation → navigate to `/runs/<new>` and toast "Started rerun of abcd1234". Errors become a toast with the server message.
- [x] Console header: a Rerun button for failed and cancelled (primary) and succeeded (secondary). Hidden while live.
- [x] Runs list: a "⋯" row menu (table) and card menu (mobile) with Rerun for eligible runs.
- [x] "Rerun of abcd1234" link in the console header and the list row (from `RunSummary.rerun_of`).
- [x] Vitest: button visibility per status, navigation and toast, error toast, lineage link.

### 12. Journey e2e and wrap-up
- [x] `e2e/journey.spec.ts` on the fake stack:
  1. Settings: connect Claude (`sk-ant-test-…`) and GitHub (fake install).
  2. `/templates`: start "Generate docs" on `e2e-org/docs-demo` from the sheet.
  3. The dock is visible without scrolling; reject with a comment; the run ends failed with "rejected at gate: …".
  4. Rerun from the console; the new run shows "Rerun of …"; approve; the PR link appears.
  5. Rerun the first run again from the runs list menu, and check the link back.
- [x] `layout.spec.ts` / `a11y.spec.ts`: console header with Rerun and the list row menu open.
- [ ] Tick the boxes in this plan, then run the `complete-phase` skill to mark 2.6 done in `specs/roadmap.md`.
