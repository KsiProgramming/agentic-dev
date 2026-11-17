# Validation: Jira webhook trigger on configured status/label

## Done when (from roadmap)
> Moving an issue starts a run

Made checkable:

- On a real Jira Cloud site connected through 7.1, a trigger rule says "when an issue in PROJ moves to *In Progress*, run *Answer a Jira issue* on `owner/repo`".
- Moving a PROJ issue to In Progress in Jira starts exactly one run within a few seconds. Its trigger reads "Jira · PROJ-n" and its request is the issue key.
- The run reads that issue with `jira.getIssue` and stops at its gate.
- Moving the issue again, or adding a label no rule names, starts nothing more.

## Automated checks
- [ ] `packages/jira`:
  - `verify_delivery` accepts a valid delivery, and refuses a wrong secret, an expired token, wrong claims and a missing header;
  - `parse_event` reads the payloads recorded in the spike (status move, label added, label removed, created with a label) and nothing beyond its fields;
  - the client's URLs are correct for register, refresh, delete and statuses;
  - no token or body appears in any error.
- [ ] `packages/store`:
  - rule matching: status compared without regard to case; a label counts only when added, not when already present; disabled rule; disabled site; unpicked project;
  - delivery dedupe under a concurrent insert;
  - `active_run_for` sees queued, running and waiting runs, and not ended ones;
  - the migration upgrades and downgrades cleanly.
- [ ] `packages/api` receiver, one test per outcome:
  - `401` for an unsigned or badly signed delivery, and nothing recorded;
  - `202` with `duplicate`, `no_match`, `project_not_allowed`, `own_change`, `already_running`, and `start_failed` (GitHub disconnected, plus a `jira.trigger_failed` audit entry);
  - `started`: one run with `trigger: "jira"`, `input` set to the key, `jira_issue` set, and a `jira.trigger_fired` audit entry;
  - two rules matching one event start two runs;
  - a webhook id that is not this workspace's is refused;
  - no payload text in the logs.
- [ ] `packages/api` rules:
  - CRUD round trip;
  - `422` for an unpicked project, a workflow with no required input, and a workflow that cannot run;
  - the statuses route against the fake;
  - `GET /workspaces/{id}/jira` returns `webhooks`, and summaries return `jira_issue`.
- [ ] Worker (fake Atlassian):
  - registration after the first rule;
  - a new registration when the project set changes;
  - deletion after the last rule and on disconnect;
  - renewal within 10 days of expiry, by one worker only;
  - a failure stored and audited once, then cleared by a success.
- [ ] Web:
  - Vitest for the rule sentence, the New trigger form's validation and the "Jira · PROJ-12" trigger label;
  - `pnpm lint && pnpm typecheck && pnpm test`;
  - `pnpm test:e2e`, including the new `jira-triggers.spec.ts` (create, list, toggle, delete) and the Triggers page in the axe and layout specs at 375, 768 and 1440 px.
- [ ] `uv run ruff check`, the repo's Python type check, and the Python test suite are green. Never run `packages/sandbox/tests` whole against the dev stack.

## Manual / demo checks
- [x] **Spike recorded:** tech-stack's "Jira triggers (API contract)" names the JWT claims, the payload fields, the accepted `jqlFilter` clauses and the per-site webhook limit, each confirmed on a real site. Any decision the spike changed is updated in requirements.md.
  - Done on 2026-11-17 on a Jira Cloud site with the deployment's own app, through an ngrok tunnel. Confirmed there: the HS256 JWT verified with the client secret; the payload fields, including labels as space-separated lists; one delivery listing every matched webhook; `fieldIdsFilter` dropping summary edits; one URL per account (refused otherwise); and `refresh` answering `200` for an unknown id. From Atlassian's docs: 5 webhooks per account per site, the identifier stable across retries, and `labels` not a documented `jqlFilter` clause. A forced `500` was not retried within 10 minutes, so retry dedupe rests on the documented identifier. Three decisions changed (the receiver URL, the filter, the loop guard), and requirements.md records them.
  - The spike left two test issues on the site (KAN-2, KAN-3, titled "[7.3 spike] …"). Its webhooks were deleted.
- [ ] **Real demo**, with the API reachable through a tunnel (`JIRA_WEBHOOK_BASE_URL`), Jira connected with the account that owns the Atlassian app, one project picked, and `AGENTIC_RUNTIME=claude`:
  1. Create the rule above in Settings › Triggers. The site's line shows "Listening".
  2. Move an issue to In Progress in Jira. One run appears in the runs list as "Jira · PROJ-n".
  3. Read the run step by step in the console. The analyst called `jira.getIssue` on that key, and the issue's text arrived only as a tool result.
  4. Approve the gate. The comment is posted, and the issue does not start a second run (the `own_change` outcome).
  5. Move the issue to another status and back while the first run waits. Expected outcome: `already_running`.
  6. Add a label to an issue in an unpicked project. Nothing starts.

  Record the run id and the outcomes here.
- [ ] **Renewal:** set the registration's `expires_at` within 10 days, run the sweep, and confirm that Jira's expiry moved forward (`GET /rest/api/3/webhook`).
- [ ] **Triggers page:** check it at 375 and 1440 px in light and dark: the empty state with Jira disconnected, the list with two rules, the New trigger sheet, and the delete dialog.

## Merge criteria
- [ ] All the automated checks above pass in CI.
- [ ] The real demo was run and its result is recorded in this file. Any lesson it taught is in `lessons.md`.
- [ ] `specs/tech-stack.md` is updated (Jira triggers contract, `trigger` values, Settings › Triggers, audit actions, decisions log), along with the docs (`connecting-platforms.md`, `security-model.md`), `.env.example` and `CHANGELOG.md`, in the same PR.
- [ ] No token, authorization header, JWT or issue text appears in logs, events or audit entries.
- [ ] A delivery that fails verification starts nothing and stores nothing.
