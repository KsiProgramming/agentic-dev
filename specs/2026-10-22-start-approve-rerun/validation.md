# Validation: Start, approve and rerun

## Done when (from roadmap)
> A user connects Claude and GitHub and starts a docs run without reading any help text. Its gate is visible and approved without scrolling at every viewport, desktop and mobile. A failed run is rerun from the console or the runs list, and the new run links back to the original.

## Automated checks

### Backend (pytest, Testcontainers Postgres and Redis)
- [ ] `GET /templates` returns `requires` for `generate-docs`.
- [ ] `PUT …/connections/claude`:
  - A valid key is stored.
  - An invalid key returns 422 `invalid_key`.
  - An unreachable verifier returns 502 `verify_unavailable`, and nothing is stored.
  - The key string never appears in captured logs or response bodies.
- [ ] GitHub `ConnectionOut.manage_url` is correct for user and org installations.
- [ ] Fake mode: fake repos list, fixture clone and fake `openPR` work. The API refuses to start with a fake mode under `AGENTIC_ENV=production`.
- [ ] `POST /runs` stores `template_parameters` for template runs and `NULL` for workflow runs. The migration upgrades and downgrades.
- [ ] `POST /runs/{id}/rerun`:
  - Copies spec, input, repo, workspace, `template_id` and `template_parameters`, and sets `rerun_of` to the parent.
  - The original's row and events are unchanged.
  - 404 for an unknown run; 409 `run_not_ended` for queued, running and waiting.
  - 409 when a GitHub tool needs a connection that was removed.
  - A rerun of a rerun points to its immediate parent.
  - The new run is listed by `GET /runs` with `rerun_of`.
- [ ] `ruff`, strict type check and `test_migrations.py` are green.

### Frontend (Vitest)
- [ ] Schema form renderer: each supported keyword renders and validates; an unsupported schema shows the error state; a 422 `loc` maps to a field.
- [ ] "New run" sheet:
  - The checklist disables submit until the required connections exist.
  - The inline Claude key form works.
  - The combobox filters and supports the keyboard.
  - The last-used repo is preselected only when it is still listed.
- [ ] Settings cards: every state (not configured, not connected, connected, needs attention). Remove and Disconnect ask for confirmation.
- [ ] `gateSummary`: prompt first, else the first non-empty artifact line, truncated at 140.
- [ ] Approval dock:
  - Shows while waiting and hides on `gate_decided`.
  - Approve is one click; Reject sends `comment`; buttons are disabled while pending.
  - Shortcuts fire on the console, and are ignored in fields and with a dialog open.
- [ ] Waiting signals: the sidebar badge updates from the stream; tab title rules on the console and on other pages.
- [ ] Rerun: the button shows only on failed, cancelled and succeeded; success navigates with a toast; errors show a toast; the "Rerun of" link is rendered.
- [ ] ESLint, Prettier and `tsc --noEmit` are green. The generated API client is up to date (the CI diff check).

### End to end (Playwright on docker compose, `AGENTIC_RUNTIME=fake`, `AGENTIC_GITHUB=fake`, `CLAUDE_KEY_CHECK=fake`)
- [ ] `journey.spec.ts` runs the full Done-when story:
  1. Connect Claude and GitHub from Settings.
  2. Start "Generate docs" on the fixture repo from the gallery sheet.
  3. Reject at the dock with a comment, and the run ends cancelled with the comment on its gate.
  4. Rerun from the console, approve, and the PR link appears.
  5. Rerun from the runs list.
  6. Both reruns link back.
- [ ] `layout.spec.ts`, at 375, 768, 1024 and 1440:
  - No horizontal scroll on the gallery, sheet, settings states, the console with the dock, and the runs list with the menu open.
  - The dock's bounding box is fully inside the viewport, and the last timeline item is not covered by it.
  - Screenshots are uploaded.
- [ ] `a11y.spec.ts`, at 375 and 1440, light and dark: axe finds no serious or critical issues on the gallery, sheet, settings states, dock, details sheet, reject dialog and row menu.
- [ ] Keyboard: the sheet, the combobox, the dock (including `A` and `R`) and the row menu all work without a mouse.

## Manual / demo checks
- [ ] **Real stack** (`AGENTIC_RUNTIME=claude`, real GitHub App, test repo):
  1. On a fresh workspace, connect Claude with a real key. A wrong key shows a field error and is not saved.
  2. Install the App, then pick the test repo in the combobox.
  3. Start "Generate docs" with no help text needed.
- [ ] At a phone-width window (375 px), the dock is visible without scrolling. "Review details" shows the artifact. Approve, and the PR opens on GitHub.
- [ ] Force a failure (for example reject at the gate). Click Rerun in the console header; the new run opens with "Rerun of …". Rerun again from the runs list.
- [ ] With a run waiting, open the Runs page and Settings. The sidebar badge shows the count, and the tab title shows "(1) ● Needs approval · …".
- [ ] Remove the GitHub installation on github.com. Settings shows "Needs attention" with Reconnect.

## Merge criteria
- [ ] PRs A and B: their own pytest, Vitest, layout and a11y checks are green; they don't touch this spec folder.
- [ ] PR C: all checks above pass in CI, including the roadmap check (2.6 marked "✅ Done").
- [ ] `specs/tech-stack.md` UI design system describes every new pattern (PR A).
- [ ] No Claude key or GitHub token appears in logs, events, error bodies or screenshots.
- [ ] Fake modes default to off in `docker-compose.yml`, and they cannot start in production.
- [ ] CHANGELOG entries are added for the start screen, settings, approval dock and rerun.
