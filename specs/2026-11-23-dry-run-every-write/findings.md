# Findings: Dry run for every write

What building 13.8 showed, and what is still to be run. Written when the code was done, before the real run.

## Verified by tests

- **The tools plan what they then do.** On `FakeAtlassian` and the fake GitHub, each plan matches what the real call then does (`compare` finds nothing), plan mode writes nothing (`posted`, `moved`, pushes and created repos stay empty), a move that is not offered and one that changes nothing are plans, and each `expect` is refused with `plan_stale`.
- **The engine on the real Jira tools.** `packages/worker/tests/test_write_plans.py` runs the engine through `open_jira_tools` on `FakeAtlassian`: the gate shows the two plans, someone moves the issue while it waits, the approval fails `plan_stale: move: …` and nothing is posted. This is the one test where the engine reads the tool's real refusal text.
- **The engine on a fake world** (`test_write_applies.py`): SDD's `approve_pr` is as planned for the pull request and both Jira writes with the links filled in; a moved issue stops the batch with no pull request; a gate edit moves the tip and is as planned; a branch that moves after the batch check is refused by the tool; a result that differs is flagged and the run goes on; a plan that would fail stops the batch; a follow-up push and a new repo are planned and checked; `plan_missing`; a rerun from the gate plans again.
- **Store, API and web:** `pending_gate().plans`, the two audit rows, `GET /runs/{id}/gate` `plans`, the timeline folding, `WritePlans` (each kind, would fail, placeholders, an issue address that is not https left unlinked, HTML and images dropped), the write step's lines, the Inbox and the audit formatter.

## What building it found

Each of these was caught by a test, not by a real run; none is a lesson for `lessons.md` (the rule behind each is in tech-stack).

1. **A union return type wraps the result.** The MCP SDK wraps a `A | B` return in `{"result": …}`, which would have changed every structured answer of the four tools. `strict_tool(plannable=True)` replaces the output model by the union itself, so `data` is still the tool's own answer or a plan (tech-stack decisions).
2. **A `wait_for` is a gate.** `WaitForNode` subclasses `GateNode`, so the first `planned_writes` made `wait_for_answers` a deciding gate and planned writes on it.
3. **The MCP server prefixes a tool's error** (`Error executing tool x: plan_stale: …`), so the engine reads the fixed code after the prefix (`split_error`), and a test on the real Jira tools covers it.
4. **A rerun from a gate skipped the gate's own steps.** `checkpoint_before` looked for the gate's id, which is the *last* of its steps (checks, review, plan), so a rerun carried stale plans. It now starts at the gate's first step. This also makes a rerun from a gate with `evidence` check again, which is what "rerun from the gate" says.
5. **Informative fields are no precondition.** A gate edit adds a commit, a step run again finds its comment posted, a pull request has a number: `commits`, `created`, `offered` and `number` are shown but not compared by `same_plan`, or each would be a false `plan_stale`.
6. **A gate that passes by itself still plans.** Skipping it left a workflow whose only gate passes by itself (`pause: on_failure`) with writes that had no plan, which now fail `plan_missing`.

## Not run: to do before this is merged

The session that built this had no Jira site, no Claude key and no permission to rebuild the running dev stack (the repo's rule: ask first, a second worker sweeps the first one's sandboxes), so these checks of `validation.md` are open:

- [ ] **Real SDD run with Claude** (`AGENTIC_RUNTIME=claude`) on a real Jira site and repo, with `move_to` set: the `approve_pr` gate shows the three plans; approve; check GitHub and Jira against what was shown; the Events tab shows `writes_planned`, then three `write_checked` with `as_planned`. Record the run id and screenshots here. This is where the Jira and GitHub calls are checked against the real services once (lessons 10): the plan's comparison of a real comment's text (Jira may store it as ADF and give it back changed; the tool compares `to_markdown(from_markdown(text))` for the "already posted" check, but the result's `text` is the text it posted, not Jira's copy), a real transition's `expect`, and `find_open_pull_request` against GitHub.
- [ ] **Stale on the real site:** start a second run to `approve_pr`, move the issue in Jira by hand, approve. Expected: `plan_stale` naming the status, no pull request, nothing posted, `write.plan_stale` in the audit log.
- [ ] **A plan that would fail** on a fake issue whose workflow has no move to `move_to`: "Would fail: transition_unavailable".
- [ ] **New repo** on the fake stack: `approve_repo` shows "Create the private repo …" and the step after reads "As planned".
- [ ] **e2e and screenshots** on a rebuilt stack: `web/e2e/write-plans.spec.ts`, the new cases of `a11y.spec.ts` and `layout.spec.ts` (written, not run: the running stack is the old code), and the Inbox review, the dock's sheet and a write step at 375 and 1440 px, light and dark (lessons 11).

## Known limits

- A run paused at a gate before this change has no plans: approving it fails `plan_missing` and writes nothing; "Rerun from the gate" plans again.
- The "Inbox" and dock show a plan as it was when the gate paused. A gate that waits for days is checked again at approval (`plan_stale`), not while it waits ("Check again" is out of scope).
- The batch check plans each write once more before the first write, so an approval costs three more Jira reads and one export of the branch; a step cut off between the check and its first write checks again, and the tools' own idempotency (a comment already posted, a branch already pushed) keeps the write single.
