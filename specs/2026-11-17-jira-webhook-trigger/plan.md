# Plan: Jira webhook trigger on configured status/label

Order chosen in the interview: a spike on a real Jira Cloud site, then the contract, then the code, back end before UI. The project keeps working after each group.

## 1. Spike on real Jira (timeboxed, no merged code)
- [ ] Register a webhook with the deployment's own Atlassian app on a test site, reached through a tunnel, using a throwaway script in the scratchpad (not committed).
- [ ] Record the delivery's authorization: the header, the JWT algorithm, `iss`, `aud`, `qsh`, `exp`, and what is signed. Check that it verifies with the client secret.
- [ ] Record the payloads of `jira:issue_updated` (a status move, a label added, a label removed) and of `jira:issue_created` with a label: `changelog.items`, `user.accountId`, `matchedWebhookIds`, and any delivery or event id.
- [ ] Confirm the app-owner delivery rule, i.e. that nothing is delivered when another account registers the webhook.
- [ ] Try `jqlFilter` with `project in (…)`, `status = …` and `labels = …`. Find the per-site webhook limit, and check what `refresh` and `DELETE` return.
- [ ] Write "Jira triggers (API contract)" in `specs/tech-stack.md` from the findings: the receiver's checks, the tables, the routes, the outcomes, the audit actions and the env vars. Add the decisions-log rows. Update `requirements.md` wherever a finding changes a decision.

## 2. Client and fake (`packages/jira`)
- [ ] Add to `JiraPlatform`: `register_webhooks`, `refresh_webhooks`, `delete_webhooks` and `project_statuses`, called through `agentic_jira.call` (refresh, one `401` retry).
- [ ] Add `agentic_jira.webhooks`: `verify_delivery(headers, body, client_secret)`, which returns the claims or raises a fixed error kind, and `parse_event(payload)`, which returns a typed event (`issue_id`, `key`, `project`, `account_id`, `status_to`, `labels_added`, `delivery_key`, `webhook_ids`) and reads nothing else.
- [ ] `FakeAtlassian` records registrations, renewals and deletions with expiry dates, serves statuses, and gains a `signed_delivery(...)` test helper.
- [ ] Add tests for verification (valid, wrong secret, expired, wrong claims, missing header), for parsing recorded payloads (fixtures from the spike, normalised to LF), and for the client's URLs. Check that no token or body appears in any error.

## 3. Store and migration (`packages/store`, Alembic `0034_jira_triggers`)
- [ ] Create the tables:
  - `jira_triggers` (workspace, cloud_id, project_key/id, `on` `status` | `label`, `value`, `template` or `workflow_id` + `workflow_version`, repo, ref, enabled, timestamps);
  - `jira_webhooks` (workspace, cloud_id, webhook ids, projects, `expires_at`, `renewed_at`, `error`);
  - `jira_deliveries` (a unique `delivery_key`, workspace, received_at, issue key, outcome, reason, trigger_id, run_id).
- [ ] Add to `runs`: `jira_trigger_id` and `jira_issue` (JSON). Add `trigger = 'jira'` to the allowed values. Add `account_id` to the Jira connection, filled when the token is next used (`/me`).
- [ ] Add the store functions: rule CRUD; `match_triggers(workspace, event)`; `record_delivery` (insert-or-skip on the key); `active_run_for(trigger, issue)`; `webhooks_due(now)`; and pruning deliveries older than 30 days.
- [ ] Add store tests for matching (case-insensitive status, label added versus already present, disabled rule, disabled site, unpicked project) and for dedupe under a concurrent insert.

## 4. Receiver and run creation (`packages/api`)
- [ ] Add `POST /jira/webhooks/{workspace_id}`. It caps the body, then runs `verify_delivery` (`401`), the webhook id check, dedupe, `jira_project_allowed`, the own-change check, matching, and the active-run check. Then it creates the run and records the outcome. It answers `202`, and writes no payload text to any log.
- [ ] Move the run-creation path behind `POST /runs` into a function the receiver calls with `trigger="jira"`, `input=<key>`, the rule's target, repo and ref, so every connection and validation check is the same.
- [ ] Add the rule routes (`GET`/`POST`/`PATCH`/`DELETE /workspaces/{id}/jira/triggers`) and the statuses route. A rule is validated on save: its project is picked, its workflow declares a required input, and it passes the same checks as a runnable workflow. Write the audit entries.
- [ ] `GET /workspaces/{id}/jira` gains `webhooks`, and `GET /runs` and `GET /runs/{id}` gain `jira_issue`.
- [ ] Add API tests for every receiver outcome; for a started run (trigger `jira`, input set to the key, `jira_issue` set, audit `jira.trigger_fired`); for `start_failed` when GitHub is disconnected; for one run when the same delivery arrives twice; and for the rule validation errors.

## 5. Registration and renewal (`packages/worker`, API on rule change)
- [ ] Add `sync_jira_webhooks(workspace, cloud_id)`, which works out the needed project set and then registers, registers again or deletes. It is called after a rule is saved or deleted, after a site is turned on or off or its projects change, and on disconnect (best effort).
- [ ] Add a worker sweep every `JIRA_WEBHOOK_SWEEP_S` (default 6 h) that renews webhooks expiring within 10 days and registers again any that are missing. Each run is locked (`SKIP LOCKED`) so that two workers never renew the same site. A failure is stored on `jira_webhooks.error`, and the `jira.webhook_failed` audit entry is written once per failure.
- [ ] Add `JIRA_WEBHOOK_BASE_URL` to settings and to `.env.example`.
- [ ] Add tests on the fake for: registration after the first rule, a new registration when the projects change, deletion after the last rule, renewal near expiry, and an error stored and then cleared.

## 6. UI: Settings › Triggers (`web/`)
- [ ] Read `specs/tech-stack.md` → UI design system, `specs/design-language.md` and `web/AGENTS.md` first. Add "Triggers" to the settings nav and create `web/src/app/settings/triggers/page.tsx`.
- [ ] Build the rules list in `web/src/settings/jira-triggers/`, as a table from `md` and cards below it. Each row has its sentence; the last fire shown with `RelativeTime`, a `StatusBadge` and a link to the run; an enabled switch; and a delete confirmed in a dialog. Add the per-site listening line, and the loading, empty (with a link to Integrations when Jira is not connected) and error states.
- [ ] Add the "New trigger" sheet, shaped like the New run sheet: site, project, when (a status from the live list, or a label), the workflow (templates and stored workflows that declare an input), repo, branch. A refused save stays open and shows the reason.
- [ ] Runs list and console: show the trigger as "Jira · PROJ-12", with the key linking to the issue (`badgeStatus`/`statusLabel` are untouched). Update the trigger label helper in `@/runs/summaries`.
- [ ] Add Vitest tests for the rule sentence, the form validation and the trigger label. Add a Playwright spec `jira-triggers.spec.ts` (create, see it listed, toggle, delete) and add the page to the axe and layout specs.

## 7. Docs, specs and the real demo
- [ ] Update tech-stack: the `trigger` values (Run history), Settings › Triggers (UI design system), the audit actions table, and the final decisions-log rows. Update `docs/integrations/connecting-platforms.md` (public URL, app-owner rule, tunnel), `docs/security/security-model.md` (the receiver's checks) and `CHANGELOG.md` under `[Unreleased]`.
- [ ] Real demo (see validation.md), and record its result in validation.md. Add a lesson to `lessons.md` if the real run teaches one.
