# Validation: Editable artifacts in the approval dock

## Done when (from roadmap)
> Gate is approved from the UI with edits

Checkable as: on a docs run waiting at its gate, the approver opens "Review details", sees the writer's changed files as diffs, edits one, and clicks "Approve with 1 edit". The run continues, and the pull request it opens contains the edit as a commit `Edit at gate approve`.

## Automated checks
### Engine (`packages/engine/tests/test_gate.py`, fake runtime, fake `GateReview`)
- [ ] `gate_waiting` carries the `changes` from the review for the writers that completed before the gate. It carries `[]` without a review or without writers.
- [ ] Approve with edits calls `apply` once. `gate_decided` records `edits` and `commits`. The gate's output is unchanged.
- [ ] Reject never calls `apply`.
- [ ] An `apply` error ends the run `failed` with a readable reason. It is never approved without its edits.
- [ ] A run cut off after `apply` and before the checkpoint applies again on resume and ends with one edit commit (with the idempotent fake).

### Sandbox (`packages/sandbox/tests/`, Docker backend)
- [ ] `branch_changes` lists added, modified, deleted and renamed files with the right status. `before` / `after` are right for text files.
- [ ] A binary file, a file over 256 KB, and files past 50 files or 512 KB in total are listed with no contents and the right reason.
- [ ] `commit_edits` makes one commit per writer with the message, identity and trailer. A second call with the same edits makes no commit.
- [ ] A path outside the worktree (`../x`, absolute, `.git/…`) is refused.

### Store and API (Testcontainers Postgres)
- [ ] `POST /runs/{id}/approvals` with edits returns `202`. The edits are stored on the approval and returned by `pending_decision`.
- [ ] `422` with the right `code` for each of:
  - an unlisted or non-editable path (`edit_not_allowed`);
  - edits with reject (`edits_with_reject`);
  - an over-size file or total (`edit_too_large`);
  - a duplicate path (`duplicate_edit`).
- [ ] An edit equal to `after` is dropped. Approving with only such edits is a plain approve.
- [ ] Migration `0018` upgrades and downgrades cleanly. Old approvals read back with no edits.

### Worker integration (fake runtime + sandbox + fake GitHub)
- [ ] A docs-shaped run pauses with `changes`, is approved with one edit, and the branch `openPR` pushes holds the edit commit on top of the writer's commit.
- [ ] A worker restart while the run waits at the gate keeps the edits (stored on the approval) and applies them once.

### Web (Vitest + Testing Library)
- [ ] `gates.ts` parses `changes` and decided edits, and ignores malformed entries (wrong types, missing paths).
- [ ] Review sheet:
  - lists each file with its status icon and label, and shows the reason for read-only files;
  - marks a file "Edited" after typing, and clears the mark on Discard;
  - the Approve label shows the count;
  - `A` does not approve while focus is in the editor;
  - a `422` shows in an Alert naming the file.
- [ ] A gate with no changes shows the current prompt-and-artifact sheet.
- [ ] The decided gate step reads "Approved with edits to N files".

### End to end (Playwright, CI "Compose smoke test + e2e")
- [ ] `gate-edits.spec.ts`:
  - edit a page in the diff, Approve with 1 edit;
  - the run succeeds, and the pushed head on the fixture remote contains the edited text.
- [ ] axe finds no serious issues on the review sheet, light and dark.
- [ ] Screenshots at 375 / 768 / 1440 px show no horizontal page scroll; the diff scrolls inside its own box.

### CI
- [ ] `ruff`, `pyright` strict, `pytest`, ESLint, Prettier, `tsc`, Vitest, and the compose e2e job are all green.
- [ ] OpenAPI client regenerated with no diff in CI.

## Manual / demo checks
- [ ] With `docker compose up` and a real Claude key and GitHub App, start "Generate docs" on a small real repo. At the gate:
  - Review details shows the generated pages as added files;
  - edit one page's title, then Approve with 1 edit;
  - the opened PR has two commits (`docs: generate module documentation` and `Edit at gate approve`), and the page shows the new title.
- [ ] At 375 px the sheet is a bottom sheet with a file picker and an inline diff. Typing works with the on-screen keyboard.
- [ ] Pressing Reject with edits warns that they will be dropped. The run ends `cancelled`, and no edit commit is made.
- [ ] Reloading the console with unsaved edits asks for confirmation.

## Merge criteria
- [ ] All checks above pass in CI (PR A: backend groups; PR B: web, e2e and the rest).
- [ ] `specs/tech-stack.md` has the gate review contract and UI rules, merged with PR A before any UI is built.
- [ ] CHANGELOG entries under `[Unreleased]` in both PRs.
- [ ] No file contents or edits appear in application logs (only in run events).
- [ ] The demo's PR link is in PR B's description.
