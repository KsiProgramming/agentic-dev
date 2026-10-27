# Start, approve and rerun

Roadmap phase: 2.6
Branch: plan/2.6-start-approve-rerun

## Context
Milestone 2 gave the product a design system (2.1), an app shell (2.2), a run history (2.3, 2.4) and a readable run console (2.5). The three moments where a user acts on a run are still debug-grade:
- **Start:** `/templates` has a hard-coded docs card and a raw JSON "Sample run" form.
- **Approve:** the gate panel sits inline in the waiting step, so it can be below the fold.
- **Recover:** a failed run cannot be rerun.

This phase used to be three phases (approval dock, rerun, and start screen and settings). It now covers the whole user journey: connect → start → approve → rerun.

Principles that drive it:
- **Mission 8 (calm, enterprise UI):** what needs the user, such as a waiting approval, is never below the fold. A user starts a docs run without help text.
- **Mission 9 (nothing is lost):** a failed or cancelled run can be rerun in one click.
- **Mission 3 (humans approve irreversible actions):** decisions are made on the console with full context, never from the list.
- **Tech stack:**
  - The rerun contract: a new run linked by `rerun_of`, and the original is never changed.
  - The design system: shadcn/ui, tokens, the approval dock rules, and 375–1440 px.
  - TanStack Query for data.

It depends on 2.3, 2.4 and 2.5 (all done). It unblocks:
- 3.6: edits and diffs inside the dock.
- 5.8: the provider picker and blank canvas on this start screen.
- Every later template (audit, SDD), which appears in the gallery with no frontend change.

## Scope
### In scope

**Delivery**
- Three stacked PRs: (A) start and settings, (B) approval dock, (C) rerun. See plan.md.

**Start screen (`/templates`)**
- A gallery of template cards from `GET /templates`, with loading, empty and error states.
- Clicking a card opens a "New run" sheet. `/templates?template=<id>` deep-links to it.
- A "New run" primary action in the Runs page header opens the same sheet with a template picker. A single template is preselected.
- The "Sample run" JSON form is removed from the UI.

**"New run" sheet**
- Template fields are generated from the template's JSON Schema by a small in-house renderer. It supports this subset:
  - `string`: min/max length, pattern, default, and a multi-line hint.
  - `array` of `string`, with item limits.
  - `enum`, `boolean`, `title` and `description`.
- A zod schema is derived from the same JSON Schema. The form uses react-hook-form, with shadcn `form` field errors. A server 422 is mapped onto fields by `loc`.
- An unsupported schema shows an error state instead of a broken form.
- **Repo combobox** (shadcn Command + Popover):
  - Searchable list of installed repos showing owner/name, a private icon and the default branch.
  - Preselects the last used repo (localStorage per workspace, wrapped in try/catch, and only if the repo is still listed).
  - Footer link "Add repos on GitHub" to the installation's settings.
- **"Before you start" checklist** for the connections the template requires. Submit stays disabled until all are connected.
  - A Claude key can be entered inline. It uses the same key form as Settings.
  - GitHub "Connect" runs the install flow and returns to `/templates?template=<id>`.

**Templates API**
- `GET /templates` adds `requires: ("claude" | "github")[]` per template. The sheet uses it for the checklist and to decide whether the repo field shows.

**Settings (`/settings`)**
- **Connection cards:** icon, name, one-line purpose, status badge (Connected / Not connected / Needs attention), and primary actions.
- **Claude card:**
  - Shows the key hint and last updated time.
  - Replace opens the key form.
  - Remove asks for confirmation in a dialog.
- **GitHub card:**
  - Shows the account login and "N repositories accessible" with an expandable list.
  - "Manage on GitHub" opens the installation's settings.
  - Disconnect asks for confirmation.
  - `installation_gone` shows an amber "Needs attention" state with Reconnect.
  - A server with no GitHub App configured shows a muted "not configured" state.
- `ConnectionOut` adds a GitHub `manage_url`, built from the installation id and account type.

**Claude key verification**
- `PUT …/connections/claude` makes one cheap Anthropic call (list models) before it stores the key.
  - An invalid key returns 422 `invalid_key`, shown as a field error.
  - If Anthropic is unreachable, it returns 502 `verify_unavailable` and nothing is stored.
- The key never appears in logs or error messages.

**Data fetching**
- Shared TanStack Query hooks (`useTemplates`, `useConnections`, `useRepos`, and connection mutations) replace the hand-written `useEffect` loaders in Settings and the docs card.

**Approval dock (run console)**
- **Layout:**
  - A bar fixed to the bottom of the console's content area while a gate is waiting.
  - The page reserves bottom padding equal to the dock height, so the dock never covers content.
  - It respects the safe-area inset.
  - At 375 px the actions stack to full width.
  - It sits above page content and below modal layers (sheets, dialogs and the open nav drawer).
- **Content:**
  - Gate title.
  - One-line summary: the gate `prompt`, or else the first non-empty line of the artifact, truncated to 140 characters.
  - "Review details": a side sheet on desktop and a bottom sheet on mobile, with the prompt and the full artifact.
- **Actions:**
  - Approve is one click.
  - Reject opens a confirm dialog with an optional comment, sent as `comment`.
  - Both buttons are disabled while a request is pending.
  - A toast confirms the result.
  - The dock disappears on `gate_decided`.
- **Keyboard shortcuts:**
  - `A` approves and `R` opens the reject dialog. They work only on the console, never while focus is in an editable field or a dialog is open, and declare `aria-keyshortcuts`.
  - The buttons show them as `<kbd>` hints from 768 px.
- **Accessibility:** the dock is `role="region"` with `aria-label="Approval needed"` and is announced politely. It never steals focus.
- **In the timeline:** the inline `GatePanel` is replaced by a short marker in the waiting step ("Waiting for approval", with a button that moves focus to the dock). `gate-panel.tsx` is removed.

**Waiting signals**
- **Tab title, waiting console:** "● Needs approval · Run abcd1234" while the gate waits.
- **Tab title, every other page:** "(N) ● Needs approval · <page title>" while any run in the workspace is waiting.
- **Sidebar:** a live count badge on "Runs", also on the mobile drawer trigger. It comes from `GET /runs?status=waiting` and the existing `GET /runs/stream`.
- **Runs list:** waiting rows get a "Review" button that opens the console. There is no approve or reject in the list.

**Rerun**
- **API:** `POST /runs/{id}/rerun`.
  - Creates a new run with the original's stored built spec, input, repo, workspace, `template_id` and `template_parameters`.
  - Sets `rerun_of` to the immediate parent.
  - Returns `CreateRunResponse`.
  - Answers 404 for an unknown run and 409 `run_not_ended` for queued, running or waiting runs.
  - Runs the same connection checks as `POST /runs` (409 if GitHub tools are used without a connection).
  - The original run is never changed.
- **Eligibility:** failed, cancelled and succeeded runs.
- **Where:**
  - Console header: primary for failed and cancelled, secondary for succeeded.
  - Runs list: row "⋯" menu on desktop and the card menu on mobile.
- **After a rerun:** the new console opens, with the toast "Started rerun of abcd1234".
- **Lineage:** "Rerun of abcd1234" links back from the new run's console header and its list row.

**Template parameters**
- A new `runs.template_parameters` JSONB column (migration), written by `POST /runs` for template runs and copied by rerun.
- It is not exposed in the API yet. It is stored so "Edit and rerun" can prefill later.

**Fake mode for dev and e2e**
- Only allowed outside production. The API refuses to start with a fake mode when `AGENTIC_ENV=production`.
- **Fake key verifier:** when `CLAUDE_KEY_CHECK=fake`, keys starting `sk-ant-test-` pass and others are rejected. It is its own setting rather than following `AGENTIC_RUNTIME=fake`, so a developer on the fake runtime can still save a real key.
- **`AGENTIC_GITHUB=fake`:** fake install, connection and repos. It maps `https://github.com/e2e-org/<name>` to a bare fixture repo seeded in compose, and a fake `openPR` returns a PR URL. It reuses `agentic_github/testing.py` where possible.

**tech-stack.md → UI design system**
- New patterns are written there before the UI is built, per the section's own rule: template gallery card, "New run" sheet, connection card, combobox, form field errors, waiting badge and tab title, and dock shortcuts.

### Out of scope
- "Edit and rerun" (prefill the sheet from a past run). The column is stored now; the UI comes later.
- Resuming a failed run from its last checkpoint (a later option, per tech-stack).
- Editable artifacts and diffs in the dock (3.6).
- Recording *who* approved (needs users and auth, TODO.md §1).
- Approve or reject from the runs list (by decision).
- "Rerun as …" links on the original run, and rerun lineage to the root.
- A "Test" button for a stored Claude key.
- Provider picker and blank canvas on the start screen (5.8).
- Custom JSON workflow runs in the UI (the API still accepts `workflow`).
- Template versioning.

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Delivery | One plan, 3 stacked PRs: A start+settings → B dock → C rerun | User choice. Follows the journey. Shared hooks and UI components land first. Only PR C touches this spec folder, so `check_roadmap.py` marks 2.6 done once. |
| Start screen | `/templates` gallery + global "New run" sheet; Sample run removed | User choice. One way to start a run, reachable from the home page. |
| Template fields | In-house renderer for a JSON Schema subset | User choice. New templates need no UI code. Lighter than `@rjsf/core` (kept for M5 side panels). |
| Forms | react-hook-form + zod (zod derived from the schema) | User choice. Field-level errors and aria wiring through shadcn `form`. |
| Repo picker | Searchable combobox + last-used preselect + "Add repos on GitHub" | User choice. No free-text URL: the App must have access anyway. |
| Missing connections | Inline checklist in the sheet; submit disabled | User choice. The user starts a run without reading help text (Done when). |
| Claude key | Verified on save with one Anthropic call | User choice. A bad key fails at Settings, not mid-run. |
| Settings data | TanStack Query hooks shared with the sheet | User choice. Tech stack names TanStack Query. One cache for connections and repos. |
| Dock summary | `prompt`, else the artifact's first line; no spec change | User choice. GateNode stays as it is. 3.6 adds richer content. |
| Decisions UX | Approve in 1 click; Reject via dialog with optional comment | User choice. Matches tech-stack's rule that destructive actions ask for confirmation. |
| Waiting signals | Dock + console tab title + sidebar badge + tab title on every page | User choice. A waiting approval is never missed. |
| List actions | "Review" link only, no approve from the list | User choice. Approvals are made with the artifact in view (mission 3). |
| Keyboard shortcuts | `A` / `R` on the console, not in fields or dialogs | User choice. Reject still confirms. Approve is as easy as the visible button. |
| Rerun copy | Stored built spec, input, repo, workspace, template id | User choice. Matches the tech-stack contract. The rerun is byte-identical, so history stays truthful. |
| Template params | Store `template_parameters` now, no UI | User choice. Cheap now, enables "Edit and rerun" later. |
| Rerun entry points | Console header + runs list menu; open the new run + toast | User choice. Meets "from the console or the runs list". |
| Lineage | "Rerun of" on the new run, immediate parent | User choice. Data already exists in `RunSummary.rerun_of`. |
| E2E fakes | Backend fake mode (key verifier, GitHub, fixture repo) | User choice. Real API, UI and events. No CI secrets. |
| E2E run | Docs template on a local fixture repo | User choice. Exercises the real template path through the gate. |

## Open questions
- **Shortcuts:** `A` approves without a confirm. If a review finds this too easy to trigger by accident, change it to `A` focusing the Approve button. This would be decided in PR B review.
- **Anthropic call:** the exact call for key verification (`models.list` with `limit=1` in the current SDK) will be checked against the current Anthropic SDK docs at implementation time.
