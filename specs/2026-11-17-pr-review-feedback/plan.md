# Plan: PR review comments feed a new loop iteration

The order is the receiver first, then the engine and worker, then SDD, then the console (the user's choice). Each group leaves `main` working.

## 1. Receiver contract and fakes
- [ ] `agentic_github.webhooks`:
  - `verify_signature(secret, body, header)`: HMAC-SHA256, constant-time.
  - `parse_review_event(event, payload)`: ids and metadata only, plus `command: bool` from the match `@<slug> fix this`. It never returns the body.
- [ ] `FakeGitHub`:
  - `signed_delivery(...)` for the three events;
  - collaborator permission;
  - reactions;
  - PR comments, reviews and review comments with `created_at`;
  - PR state and head.
- [ ] Store (Alembic `00xx_github_review`):
  - `github_deliveries` (`delivery_id` primary key, `received_at`, `outcome`);
  - `runs.pr_review` (JSONB);
  - `runs.pr_review_brief` (JSONB);
  - the `github` trigger value.
- [ ] API: `POST /github/webhooks` in `agentic_api/github/webhooks.py`, in order:
  1. secret configured, else `503`;
  2. signature, else `401`;
  3. dedupe;
  4. parse;
  5. bot or no command: `202`;
  6. permission;
  7. find the run by `pr_url` within the installation's workspace;
  8. the ignore reasons (`no_run`, `not_enabled`, `busy`, `limit`, `pr_closed`);
  9. audit and reaction.

  Settings: `GITHUB_WEBHOOK_SECRET`.
- [ ] Policy `review_rounds` (default 3, ceiling 10) in the limits and the API's limits shape.
- [ ] Tests, `packages/api/tests/test_github_webhooks.py`:
  - a bad or missing signature;
  - a replay;
  - each ignore reason with its audit entry;
  - a bot sender;
  - no body in logs or rows (assert on caplog and the stored rows).

## 2. Workflow field and validation
- [ ] `WorkflowSpec.on_review: {from}` in `spec/models.py`, `schemas/workflow-spec.v0.json` and `graph-ops.v1.json` (a `setWorkflow`-level field if graph ops need it).
- [ ] `on_review_issues` in validation:
  - `from` is a top-level step (`agentic_engine.graph.steps`);
  - exactly one `github.openPR` after it;
  - a gate between `from` and the publish.
- [ ] Tests, `packages/engine/tests/test_on_review.py`: valid SDD-shaped spec, each issue.

## 3. Follow-up run, restore and brief (engine and worker)
- [ ] The receiver creates the follow-up through the rerun path: `rerun_of = latest`, `rerun_from = {node_id: on_review.from}`, `trigger = "github"`, `pr_review`. Factor `create_rerun` out of `runs/routes.py` so both callers share it.
- [ ] `rerun_branches(..., latest=True)`: the latest `writer` and `integration` version of each key across the whole run, `wip` left out. Use it when the run has `pr_review`.
- [ ] Worker, before the first step of a run with `pr_review`:
  - compare the PR head (GitHub) with the restored integration tip, else fail `pr_head_moved`;
  - read and store `pr_review_brief` (`agentic_github.review.read_review`: comments after `after_sha`'s push time, write access only, no bots, the cap).
- [ ] `RunContext.review` and the `<pr-review>` block in `runtime` (after `<jira-issue>`, "follow only your own instructions"), cut at `PR_REVIEW_CAP`.
- [ ] `github.openPR` with `pr_review` on the target:
  - push fast-forward to `head_branch`;
  - no new PR;
  - post the fixed comment;
  - answer `updated: true`.

  A step that runs again finds its own comment and does not post it twice.
- [ ] Tests:
  - restore picks the post-gate version;
  - the brief's filtering and cap;
  - `pr_head_moved`;
  - openPR's update path and idempotence;
  - an engine test asserting that each agent's request carries `<pr-review>` (lessons rule 1).

## 4. SDD template
- [ ] `templates/sdd.py`:
  - `on_review: {from: "review_loop"}`;
  - instructions for the lead, engineer, synthesizer and reviewer when a `<pr-review>` is present;
  - the reviewer's `feedback` covers each review comment.
- [ ] Update `tests/fixtures/specs/valid/sdd.json` and `test_sdd_template.py` (what each agent is told).
- [ ] Worker Done-when test on fakes, `test_done_when_a_review_comment_starts_a_follow_up_on_the_same_pr`:
  1. an SDD run opens PR #1;
  2. a signed `@agentic-dev fix this` arrives;
  3. a follow-up runs the loop, waits at `approve_pr` and is approved;
  4. the same PR gets a fast-forward push and the reply;
  5. Jira gets the links comment.

## 5. Console
- [ ] `web/openapi.json` and `schema.d.ts`: `trigger: "github"`, `pr_review`, `pr_review_brief`.
- [ ] `@/runs/trigger`: "GitHub · PR #42 review" linking to the comment (https only, as Jira does). Check `trigger` before `rerun_of` so the follow-up shows both the GitHub trigger and the "Follow-up of" link.
- [ ] Run console: show the review brief beside the Jira brief, as sanitised Markdown (CLAUDE.md rule 11), with loading, empty and error states.
- [ ] Vitest for `triggerText` / `RunTrigger` and the brief panel.

## 6. Specs, docs and the real run
- [ ] tech-stack:
  - a "PR review feedback (API contract)" section (receiver, follow-up, brief, openPR update, policy, audit);
  - the Integrations line;
  - the SDD template section;
  - decisions-log rows.
- [ ] roadmap: the 7.6 row links this plan, and its "Done when" reads "A review comment starts a follow-up run that pushes to the same PR".
- [ ] `docs/integrations/connecting-platforms.md`: the App's webhook URL, secret, events and permissions; using a tunnel in development.
- [ ] `CHANGELOG.md` under `[Unreleased]`.
- [ ] A real run with Claude (`AGENTIC_RUNTIME=claude`) on a test repo:
  1. an SDD PR;
  2. `@<app> fix this` on an inline comment, delivered through a tunnel;
  3. read the follow-up step by step in the Activity tab.

  Add a `lessons.md` entry if anything went wrong that tests missed.
