# Validation: PR review comments feed a new loop iteration

## Done when (from roadmap)
> Review comment resumes the run

Made checkable (and reworded in the roadmap in this PR): **an `@<app> fix this` comment from someone with write access on an SDD run's PR starts a follow-up run of the review loop, and after the PR gate it pushes to the same PR.**

## Automated checks
- [ ] Receiver (`packages/api/tests/test_github_webhooks.py`):
  - `401` on a missing or bad signature;
  - `503` with no secret;
  - a replayed `X-GitHub-Delivery` starts nothing;
  - each ignore reason (`not_allowed`, `no_run`, `not_enabled`, `busy`, `limit`, `pr_closed`) is audited once with the right reaction;
  - bot senders and comments without the command start nothing;
  - the comment body is in no row, audit entry or log line.
- [ ] Validation (`test_on_review.py`): `on_review` is accepted on SDD's shape and refused when `from` is not a top-level step, when there is no publish after it, or when no gate sits between them.
- [ ] Restore: a follow-up restores the latest saved integration version, the PR gate's edit commit included, not 12.4's "before the step" version.
- [ ] Brief:
  - only comments after the last push, by people with write access, with no bots;
  - inline comments carry path and line;
  - cut at `PR_REVIEW_CAP`;
  - resumes reuse it.
- [ ] What agents receive (lessons rule 1): an engine test asserts that the lead, the engineers, the synthesizer and the reviewer each get `<pr-review>` in their request's context, and that SDD's instructions tell them to address it.
- [ ] `github.openPR` in a follow-up:
  - fast-forward push to the PR's head branch;
  - no new PR;
  - one fixed reply, not posted twice on a re-run;
  - `pr_head_moved` when the head moved.
- [ ] Done-when on fakes: `test_done_when_a_review_comment_starts_a_follow_up_on_the_same_pr` (worker).
- [ ] Web: Vitest for the GitHub trigger text and link and for the review brief panel. The existing a11y and layout e2e specs stay green.
- [ ] `pnpm lint && pnpm typecheck && pnpm test` in `web/`. The Python lint, type and test jobs pass.

## Manual / demo checks
- [ ] Real run with Claude (lessons rule 1, required by the specs even though the chosen validation is tests on fakes):
  1. Configure the App's webhook to a tunnel with `GITHUB_WEBHOOK_SECRET` and run SDD on a test repo with `AGENTIC_RUNTIME=claude` until it opens a PR.
  2. As a collaborator, leave an inline comment and `@<app> fix this`. Expected: 👀 on the comment, and a follow-up run listed as "GitHub · PR #n review", linked as "Follow-up of <id>".
  3. In the Activity tab, read each agent's step and check that the lead plans from the review, the reviewer checks each comment, and the gate shows only the new change on top of the PR.
  4. Approve. Expected: new commits on the same PR, the fixed reply, and a Jira comment with the links.
  5. Repeat the command from a user without write access, and while a follow-up is running. Expected: nothing starts, 😕 for `busy`, and both are in the audit log.
- [ ] Look at the run page with the review brief at 375 and 1440 px, light and dark.

## Merge criteria
- [ ] All automated checks pass in CI.
- [ ] The real run above is done and read in the console. A `lessons.md` entry exists if it found something tests missed.
- [ ] tech-stack (contract section, decisions rows), roadmap (plan link, reworded Done when), connecting-platforms docs and `CHANGELOG.md` `[Unreleased]` are updated in the same PR.
- [ ] No comment text and no webhook secret in logs, audit entries or events.
