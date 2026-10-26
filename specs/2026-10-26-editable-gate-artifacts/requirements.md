# Editable artifacts in the approval dock

Roadmap phase: 3.6
Branch: plan/3.6-editable-gate-artifacts

## Context
2.6 gave the console an approval dock: a waiting gate shows its title, a one-line summary and a "Review details" sheet with the prompt and the gate's `artifact`. The approver can only approve or reject what they see.

In the only template with a gate ("Generate docs"), the `artifact` is the writer's reply (a commit summary). The pull request is pushed from the writer's branch (`agent/<run>/<node>`), which stays in the run's sandbox while the run waits. So editing the artifact text would change nothing in the PR. Edits that matter are edits to **the files the writers changed**. This phase shows those files as a diff and lets the approver edit them before approving. The edits land on the branch as a commit, so the PR carries them.

Principles that drive it:
- **Mission 3 (humans approve irreversible actions):** the approver sees exactly what will be pushed, and can fix it instead of only rejecting it.
- **Mission 5 (repo content is data):** file contents are shown in an editor, never rendered or executed. The approver's edits are committed as written.
- **Mission 6 (transparency):** the changes shown and the edits made are kept in the append-only log (`gate_waiting`, `gate_decided`).
- **Mission 7 (small, verifiable steps):** text files of writer branches only, within fixed size caps.
- **Tech stack:**
  - Monaco for editors and diffs.
  - A gate is a LangGraph `interrupt()`, continued with a `GateDecision`.
  - A paused run keeps its sandbox (`SandboxManager.keep`).
  - New UI patterns are written into the design system before they are built.

It depends on 1.6 (gate), 1.8 (open PR from a writer's branch), 2.6 (approval dock) and 3.5 (node detail sheet). All are done. It unblocks review of code changes in the SDD template (Milestone 6), which reuses the same gate review.

## Scope
### In scope

**Changes at the pause (engine and worker)**
- A `GateReview` interface the engine takes next to `tools`, with two methods:
  - `changes(gate_id)`: the files changed on the branches of the writers that ran before the gate.
  - `apply(edits)`: write edited files to their writer's branch and commit them.
- The worker implements `GateReview` with the run's sandbox. The engine never touches git.
- `gate_waiting` gains `changes`: one entry per changed file with `node_id` (the writer), `path`, `status` (`added` | `modified` | `deleted` | `renamed`), `before` and `after` (text or `null`), and `editable` with a `reason` when it is not editable.
- A file is editable when all of these hold:
  - it was added or modified (not deleted or renamed);
  - it is UTF-8 text with no NUL bytes;
  - it is at most 256 KB.

  Otherwise it is listed with its reason (`binary`, `too_large`, `deleted`, `renamed`, `over_limit`) and no contents.
- Caps on the payload: at most 50 files and 512 KB of contents in total. Files past the caps are listed without contents (`over_limit`).
- `before` is the file at the clone's `HEAD` (the branch's base) and `after` is the file at the branch tip.
- A gate with no writer before it has no `changes` (`[]`). The sheet then shows the artifact as today.

**Edits at approval (API and store)**
- `POST /runs/{id}/approvals` takes an optional `edits: [{node_id, path, content}]`.
- Edits are checked against the `changes` of the gate's last `gate_waiting`. Each one of these answers `422` with a stable `code`:
  - an edit on a path that is not listed and editable (`edit_not_allowed`);
  - an edit on a reject (`edits_with_reject`);
  - a file over 256 KB, or edits over 512 KB in total (`edit_too_large`);
  - the same path twice (`duplicate_edit`).
- An edit equal to `after` is dropped; it is not an edit.
- The edits are stored with the approval: a new `approvals.edits` JSONB column (Alembic migration). `GateDecision` gains `edits`.

**Applying the edits (engine)**
- On approve with edits, the gate node calls `GateReview.apply` before it completes. Per writer:
  - each file is written into the writer's worktree (staged through `put_file`, with the repo tool's path checks);
  - one commit is made: `Edit at gate <gate_id>`, with the platform's agent identity and a `Edited-by: reviewer` trailer.
- Applying is idempotent. If a worker dies after the commit and before the checkpoint, the gate runs again, the files already match, and no second commit is made.
- `gate_decided` records the edits: per file `node_id`, `path`, `content`, plus the new `commit` per writer.
- The gate's output is unchanged. The next node (`openPR`) pushes the branch, which now holds the edits.
- A failed apply ends the run `failed` with a readable reason. The run is never approved without its edits.

**Approval dock and review sheet (web)**
- "Review details" opens a **wide review sheet** when the gate has changes:
  - From 1024 px: right side, `min(1100px, 92vw)`, with the file list on the left and the diff on the right.
  - Below 1024 px: a full-height bottom sheet, with a file picker (Select) above the diff.
- The diff is a Monaco `DiffEditor`:
  - side by side from 1024 px, inline below;
  - the original side is read-only and the modified side can be edited when the file is editable;
  - the theme follows `next-themes`;
  - Monaco is bundled with the app (no CDN) and loaded lazily, only when the sheet opens.
- The file list shows each file's status (A / M / D / R icon + label), an "Edited" marker on dirty files, and the reason a file is read-only.
- Per-file "Discard edits", and a count of edited files in the sheet footer.
- When edits exist:
  - the dock's Approve becomes **"Approve with N edits"**, in both the dock and the sheet footer;
  - Reject asks for confirmation that the edits will be dropped.
- Edits live in client state for the open console. Leaving the page with edits asks for confirmation (`beforeunload`).
- Keyboard: `A` / `R` do not fire while focus is in the editor (an editable field). `Esc` closes the sheet and keeps the edits.
- The timeline's gate step (and the graph's node sheet) shows the decision with its edits: "Approved with edits to 2 files", and each edited file opens as a read-only diff of `after` against the edit.
- A gate with no changes keeps the current sheet: the prompt and the artifact as Markdown.

**Docs**
- `specs/tech-stack.md`, written first:
  - the review sheet layout and diff rules (UI design system → Approval dock);
  - a "Gate review (API contract)" section with the payloads, caps and error codes;
  - a decisions-log row.
- CHANGELOG entry.

### Out of scope
- Editing the text `artifact` of a gate with no writer before it. It stays read-only and could come later if a template needs it.
- Editing deleted, renamed or binary files, or adding and deleting files at the gate.
- Gates inside maps and loops (not allowed by validation today).
- Saving draft edits across reloads or devices. They live only in the open console.
- Recording *who* edited (needs users and auth). `decided_by` stays unset.
- Comments on lines, or suggestions sent back to the agent ("request changes"). A later idea.
- Merge conflicts between the gate's edits and a later writer: no node writes after the gate in any template today.

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| What is editable | Files changed on the writers' branches | User choice. It is what the PR pushes, so the edits reach the PR (Done when). |
| Who reads the sandbox | The worker, through a `GateReview` interface passed to the engine | The engine stays free of git and sandbox code. The worker already owns the sandbox and keeps it across the pause. |
| Where changes travel | In the `gate_waiting` payload, size-capped | The UI already reads the gate from the event stream. It needs no new endpoint, and the log records exactly what the approver saw (mission 6). |
| Caps | 50 files, 256 KB per file, 512 KB in total | Keeps events and SSE small. The docs template writes about 40 small Markdown pages. |
| Where edits apply | Inside the gate node, before it completes | It is checkpointed with the gate. A crash re-applies idempotently, and `openPR` sees the edits with no change. |
| Commit | One per writer, `Edit at gate <id>`, agent identity + `Edited-by: reviewer` trailer | The edit is visible as a separate commit in the PR. There are no users yet to author it. |
| Edits on reject | Refused (`422`) | A reject drops the run. Sending edits with it is a client bug. |
| Editor | Monaco `DiffEditor`, bundled and lazy-loaded | Tech stack choice. No CDN (CSP and offline e2e), and no cost on pages without a waiting gate. |
| Delivery | Two PRs: A backend (engine, worker, store, API), B web + e2e | User choice. The API contract lands and is tested before the UI. Only PR B touches this spec folder, so CI marks 3.6 done once. |
| Validation | Backend tests + Vitest + Playwright + a manual demo on a real repo | User choice. |

## Open questions
- **Monaco in Next.js 16:** check `@monaco-editor/react` with a local `monaco-editor` (`loader.config({ monaco })`) and its worker setup against current docs (ctx7) at implementation time. If it does not bundle cleanly, `monaco-editor` with a small hand-written wrapper is the fallback.
- None besides. (Event size was checked: `NOTIFY` carries only `<run_id>:<seq>`, and SSE reads the payload from `run_events`, so a 512 KB `gate_waiting` is fine.)
