# Validation: Dry run for every write

## Done when (from roadmap)

> A Jira comment and transition are approved from their plan at the gate, and the event log shows the plan and the result side by side

Made checkable:
1. An SDD run's `approve_pr` gate shows a plan for the pull request, the Jira comment and the Jira transition. The comment's text is shown as it will be posted, and the transition as "from → to".
2. After approval, each of the three writes has a `write_checked` event that holds `plan` and `result` together, with `outcome: as_planned`.
3. A plan that went stale while the gate waited writes nothing (`plan_stale`). A result that differs from its plan is flagged.

## Automated checks

- [ ] **Tools** (`packages/tools/tests`):
  - each plan matches what the real call then does (`FakeAtlassian`, `FakeGithubApp`);
  - plan mode writes nothing (`posted`, `moved`, pushes and created repos stay empty);
  - `transition_unavailable` and "no change" plans;
  - `plan_stale` for each `expect`;
  - `test_every_outward_write_has_a_plan_mode`.
- [ ] **Spec**:
  - `planned_writes` for SDD (with and without checks and review), docs, audit fix, new repo and `post_questions`;
  - `plan` and `expect` in a tool node's `args` are refused;
  - the manifests do not list them;
  - the regenerated JSON Schema is committed.
- [ ] **Engine** (`test_write_plans.py` and the apply tests):
  - the gate shows three plans in run order;
  - plans are made again on each loop pass;
  - a send-back plans nothing;
  - a restart plans once and checks the batch once;
  - approval gives `as_planned` with the links filled in;
  - a moved issue gives `plan_stale`, with no PR and no Jira write;
  - a gate edit gives `as_planned`;
  - a difference is flagged and the run goes on;
  - the 7.6 follow-up push and the new repo are planned and checked;
  - `plan_missing`.
- [ ] **Store and API**, run from `packages/api`: `GET /runs/{id}/gate` `plans`, the `write.not_as_planned` and `write.plan_stale` audit rows, and the OpenAPI spec and web client regenerated with no diff left.
- [ ] **Web**:
  - `write-plans.test.tsx`, covering each kind, would fail, the placeholders, an issue URL left unlinked when it is not https, and HTML in Markdown dropped;
  - the timeline folding of `writes_planned` and `write_checked`;
  - the write step's "As planned" and "Not as planned";
  - `inbox-view.test.tsx`;
  - the audit formatter.
- [ ] **e2e** on the local stack (`AGENTIC_JIRA=fake`, `AGENTIC_GITHUB=fake`, fake runtime): an SDD run from a fake issue reaches `approve_pr`, and the Inbox and the dock's sheet show three plan cards. Approving gives three steps that read "As planned". `a11y.spec.ts` covers the cards (axe, no serious issues), and `layout.spec.ts` takes screenshots at 375, 768 and 1440 px, light and dark.
- [ ] `uv run` lint, type check (strict) and tests for every package changed. `cd web && pnpm lint && pnpm typecheck && pnpm test && pnpm test:e2e`.
- [ ] Do not run `packages/sandbox/tests` as a whole (its sweep test removes the dev stack's waiting runs). Run only the files this phase touches.

## Manual / demo checks

- [ ] **Real SDD run** with Claude (`AGENTIC_RUNTIME=claude`) on a real Jira site and a real repo, with `move_to` set:
  - the `approve_pr` gate shows the PR plan (head, base, commit count, title, body), the comment as it will be posted, with the links placeholder, and "In Progress → <status>";
  - approve it, then check in GitHub and Jira that the PR, the comment (now with its links) and the move are as shown;
  - the console's Events tab shows `writes_planned`, then three `write_checked` with `as_planned`, plan and result side by side;
  - the run id and screenshots go in `findings.md`.
- [ ] **Stale on the real site**: start a second run and let it reach `approve_pr`. Move the issue in Jira by hand, then approve. The run fails `plan_stale`, naming the status that changed. No PR is opened and nothing is posted to Jira. The audit log has `write.plan_stale`.
- [ ] **A plan that would fail**: on a fake issue whose workflow offers no move to `move_to`, the gate shows "Would fail: transition_unavailable" with the moves offered.
- [ ] **New repo** on the fake stack: `approve_repo` shows "Create the private repo <org>/<name>", and the step after it reads "As planned".
- [ ] Look at the Inbox review, the dock's sheet and a write step at 375 and 1440 px, in light and dark, against the running stack (lessons 11).

## Merge criteria

- [ ] All checks above pass in CI, and the e2e failures, if any, match `main`'s (compare with main's CI before blaming the branch).
- [ ] tech-stack (Write plans contract, Tool layer rule, UI subsection, decisions log), the roadmap link and the CHANGELOG entry are in the same PR as the code.
- [ ] No token, secret or host path appears in a plan, an event or an audit entry. A plan carries comment and PR text, which are data, rendered as sanitised Markdown or text only.
- [ ] `findings.md` records the real run and the stale check. Any mistake they found that tests missed has a `lessons.md` entry.
- [ ] A clean clone of the branch passes (lessons 12): new source files are tracked, and none hides behind `.gitignore`.
