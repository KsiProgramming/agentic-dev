# PR review comments feed a new loop iteration

Roadmap phase: 7.6
Branch: plan/7.6-pr-review-feedback

## Context

Sixth phase of Milestone 7, which the roadmap's "Next up" line names. It builds on 7.5 (the SDD template, merged in #243): an SDD run implements a Jira issue in a review loop (`review_loop` over the `implement` orchestrator, `synthesizer`, `reviewer`), opens a PR from the integration branch through the `approve_pr` gate, and then **completes**. Today a reviewer's comments on that PR reach nobody. A person has to fix the code by hand or start a new run.

With this phase, a person with write access writes `@<app> fix this` on the PR (`<app>` is the deployment's GitHub App slug, the roadmap's `@platform`). That starts **one more pass of the run's review loop**, with the PR's review comments as data. The fix goes through the PR gate again and is pushed to the **same PR**.

"Resumes the run" is built as a **follow-up run** linked to the original (the user's choice), not a run reopened in place. Two decisions already in force require this: a rerun "is never resumed in place" (Run history and rerun), and a loop may not hold a gate or a publisher (`not_allowed_in_loop`). A follow-up reuses rerun-from-step (12.4): it carries the original's checkpoint up to the loop and restores its branches. Each round gets its own row in the history, its own cost and its own gate.

The GitHub App is configured for webhooks in tech-stack ("Integrations": webhooks for PR comments), but no receiver exists yet. This phase adds the first one, `POST /github/webhooks`, on the model of the Jira receiver (7.3).

It changes what agents receive (a PR review in the run context, and new instructions in SDD). So lessons rules 1 and 8 apply: tests assert what each agent receives, and the phase is done only after a real run with Claude has been read step by step in the console.

Principles that drive it:

- **3:** the push and the reply to the PR go through the PR gate again.
- **5:** comments are data. The receiver matches a fixed command and stores no text. The worker reads the review once and gives it to agents between tags. Replies posted to GitHub are platform text.
- **6:** every delivery that is accepted or ignored is audited with its reason.
- **7:** one generic workflow field, used by SDD.
- **10:** the contracts go into tech-stack in this PR.

Unblocks: nothing directly. 13.6 (independent review) and 18.x (continuous work) can later feed the same path.

## Scope

### In scope

- **Receiver `POST /github/webhooks`** (no session, no workspace in the URL):
  - It checks `X-Hub-Signature-256` (HMAC-SHA256 of the raw body with `GITHUB_WEBHOOK_SECRET`, constant-time compare). A failed check is `401` and nothing is read.
  - It dedupes on `X-GitHub-Delivery` (`github_deliveries`).
  - It handles `issue_comment.created` (on a PR), `pull_request_review.submitted` and `pull_request_review_comment.created`. Every other event and action is `202` and ignored.
  - It reads only ids and metadata: installation, repo, PR number, comment or review id, the sender's login, id and type. It reads the body only to match the command `@<GITHUB_APP_SLUG> fix this` (case-insensitive). It never stores, logs or returns the body.
  - Comments from bots, the App's own included, are ignored.
- **Who may ask:** the sender's permission on the repo must be `write`, `maintain` or `admin`, checked through the installation (`GET /repos/{o}/{r}/collaborators/{u}/permission`). Anyone else is ignored (`not_allowed`).
- **Which run:** the latest run in the installation's workspace whose `pr_url` is this PR. That is the original, or the last follow-up that pushed to the PR. It is ignored when:
  - no run has that PR (`no_run`);
  - its workflow has no `on_review` (`not_enabled`);
  - a run for that PR has not ended (`busy`);
  - the PR already had `review_rounds` follow-ups (`limit`);
  - the PR is closed or merged (`pr_closed`).
- **Acknowledging the delivery:** an accepted command gets the 👀 reaction on its comment. A refused one gets 😕 (`busy`, `limit`, `pr_closed`). No text reply comes from the receiver.
- **Workflow field `on_review: {from}`:** `from` names the top-level step a follow-up restarts at. Validation (`on_review_invalid`, `reference`):
  - `from` is a top-level step.
  - The workflow has exactly one `github.openPR`, after `from`, with a gate between them.
  - `from` is not after the publish.
- **The follow-up run:** it is created by the receiver (`trigger: "github"`) as a rerun from `on_review.from` of the latest run (`rerun_of`, `rerun_from`). It keeps `runs.pr_review`: `{pr_url, number, head_branch, comment_id, kind, author, after_sha}`, references only.
  - It restores the latest saved version of every branch of that run, gate edits included (a new restore mode, see Decisions), so it starts from what the PR holds.
  - Before the first step, the worker checks that the PR head on GitHub equals that run's pushed commit. If not, it fails with `pr_head_moved` (someone else pushed).
- **The review brief:** the worker reads the review once, before the first step, through the installation and stores it as `runs.pr_review_brief`. The brief holds:
  - the triggering comment;
  - every review comment, review body and PR comment posted after the run's last push by people with write access, bots left out;
  - for each inline comment, its `path`, `line` and diff hunk.

  `RunContext.review` tells every agent the brief after the issue, between `<pr-review>` tags, as data, as Markdown cut at 16,000 characters (`PR_REVIEW_CAP`). Resumes reuse the stored brief. `GET /runs/{id}` returns it as `pr_review_brief`.
- **Pushing to the same PR:** in a run with `pr_review`, `github.openPR` pushes its branch to the PR's `head_branch` as a fast-forward only (anything else fails `pr_head_moved`). It opens no new PR. It posts one fixed PR comment: "Pushed `<sha>` for @author's review, run [<short id>](<run url>)". It answers the same `url` and `number` with `updated: true`. The run's gate before the publish covers the push and the comment.
- **SDD template:**
  - `on_review: {from: "review_loop"}`.
  - The lead, the engineers, the synthesizer and the reviewer are told to address the `<pr-review>` when the run has one. The reviewer checks each comment as well as the spec's requirements.
  - The synthesizer's `pr-description.md` names what changed for the review.
  - The Jira steps run again: the issue receives a comment with the same links (traceable delivery), and the transition is a no-op (`changed: false`).
- **Policy:** `review_rounds`, the most follow-ups per PR, default 3, at most 10.
- **Audit:**
  - `github.review_received`: the delivery, the PR and the run it started.
  - `github.review_ignored`: the delivery, the PR and the reason. Each delivery is audited once.
- **Console:**
  - The trigger reads "GitHub · PR #42 review" and links to the comment.
  - The run header still links "Follow-up of <id>".
  - The run page shows the review brief where it shows the Jira brief.
- **Docs and configuration:**
  - The GitHub App's webhook URL, secret, events (`issue_comment`, `pull_request_review`, `pull_request_review_comment`) and permissions (Pull requests and Issues: read and write) go in `docs/integrations/connecting-platforms.md`.
  - `GITHUB_WEBHOOK_SECRET` is set on the API. With it unset, the receiver answers `503`.

### Out of scope

- A "Request changes" review starting a follow-up without the command (it costs a run on every review). Users can add it later as an option.
- A run that waits on its PR and resumes in place (see Decisions).
- `on_review` on "Plan, build and review" and other templates: a one-line change once SDD's real run has been read.
- Merging commits a person pushed to the PR branch into the follow-up. It fails `pr_head_moved` instead.
- Resolving review threads or replying on each inline comment.
- Check runs and labels as triggers (tech-stack lists them for the App; no phase needs them yet).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| How a comment "resumes the run" | A follow-up run: a rerun from `on_review.from` of the latest run on the PR, linked by `rerun_of`, pushing to the same PR | The user's choice. A run is never resumed in place, and a loop holds no gate or publisher. Each round is visible, costed and gated on its own (principles 3, 6, 9) |
| What starts it | Only `@<app slug> fix this`, from a sender with write access to the repo | The user's choice. An explicit request, and a public repo's stranger cannot spend the workspace's money or drive its agents (principle 5) |
| Reading the comment in the receiver | Only a fixed command match, and the body is never stored or logged; the worker reads the review afterwards | The same split as 7.3/7.4: the receiver reads no content, and one stored snapshot keeps a resumed run consistent |
| Which branches a follow-up restores | The latest saved version of each branch of the run it follows (all steps, gate edits included), not 12.4's "saved before the step" | The PR holds the loop's work and the PR gate's edits. Restoring from before `review_loop` would push a branch that drops them |
| Someone else pushed to the PR | Fail before the first step with `pr_head_moved`, and push fast-forward only | Never overwrite a person's commits (principle 3). Merging them is a later concern |
| Acknowledgement | A reaction on the comment (👀 accepted, 😕 refused); the reasons are in the audit log | It shows the command was heard without the receiver posting text. The gated publish posts the only text reply |
| Jira in a follow-up | SDD's Jira steps run again: a comment with the links, a transition that changes nothing | Every update to the PR stays traceable from the issue (mission, "Traceable delivery"), and the template needs no router |
| Build order | Receiver and its contract first, then the engine and worker, then SDD, then the console | The user's choice |
| Validation | Unit and integration tests on fakes (the user's choice), plus the real Claude run that lessons rule 1 requires | The specs bind the real run for a phase that changes what agents receive |

## Open questions

- None. The roadmap row's "Done when" is reworded to "A review comment starts a follow-up run that pushes to the same PR" in this PR (plan group 6).
