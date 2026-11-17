# Jira webhook trigger on configured status/label

Roadmap phase: 7.3
Branch: plan/7.3-jira-webhook-trigger

## Context

Third phase of Milestone 7, the milestone the roadmap's "Next up" line names. Today a run starts only by hand (the web app), from another client (`POST /runs`) or as a rerun. This phase adds the first run started by an outside event: moving a Jira issue to a configured status, or adding a configured label to it, starts a run on that issue.

It depends only on done work:

- **7.1** (#237): the workspace's Atlassian grant, its sites, the projects picked on each, `jira_project_allowed`, and `agentic_jira.access_token`. The `manage:jira-webhook` scope was asked for then so that this phase needs no second consent.
- **7.2** (#238): the `jira` tools and `issue_from: "request"`. A run started by this trigger has the issue key as its request, so `jira.getIssue`, `jira.comment` and `jira.transition` in the workflow find their issue with no new mechanism. "Answer a Jira issue" is the first workflow it can start.
- **2.3 / 11.4**: the runs row's `trigger` column, which gains `jira`.

It unblocks 7.5 (the SDD template, AC-5, which starts from a Jira issue) and is the pattern 18.3 reuses for GitHub labels.

Principles that drive it:

- **3. Humans approve irreversible actions.** A trigger only starts a run. Every write the run makes still goes through its gates, so a moved issue never pushes, opens a PR or changes Jira on its own.
- **5. Jira content is data.** The receiver reads only ids, the project, the event type, who made the change and the changelog's status and label items. The issue's summary, description and comments never become the run's request or instructions. The run reads them through `jira.getIssue` as tool results.
- **6. Transparency.** Every delivery we act on, and every one we drop, has a recorded outcome. Firing a trigger writes an audit entry, and the run shows which trigger and which issue started it.
- **2. Safe by construction.** A request whose signature cannot be checked starts nothing. A trigger cannot reach a project the workspace did not pick. A run cannot start itself again in a loop.

Atlassian facts this plan relies on, checked against the docs on 2026-11-17 ("Webhooks", "Register dynamic webhooks"). The spike confirms them before the contract is written:

- An OAuth 2.0 app registers webhooks with `POST /rest/api/3/webhook` (`url`, and `events` plus a `jqlFilter` for each webhook). This needs `read:jira-work` and `manage:jira-webhook`.
- Such a webhook **expires after 30 days** unless it is renewed (`PUT /rest/api/3/webhook/refresh`). Atlassian keeps it for 3 months after it expires.
- **For a non-public OAuth app, webhooks are delivered only when the app's owner is the account that registered them.** On a self-hosted deployment, the Jira account that connects (7.1) must own the deployment's Atlassian app, or the app must be shared.
- `jqlFilter` accepts only a subset of JQL. Which clauses it accepts, and how a delivery is signed (a JWT signed with the app's client secret), are both confirmed in the spike.

**Spike findings (2026-11-17, on a real Jira Cloud site with the deployment's own app).** These changed three decisions below:

- **Signature.** A delivery has `Authorization: Bearer <JWT>`, signed HS256 with the app's client secret (verified). Its claims are `iss` (the app's client id), `sub` (the account that registered the webhook), `context.cloudId` (the site), `iat`, `exp` (15 minutes after `iat`) and `jti`. There is no `aud` and no `qsh`.
- **Dedupe.** `X-Atlassian-Webhook-Identifier` is unique per tenant, and Atlassian documents it as the same across retries. The payload has `webhookEvent`, `issue_event_type_name`, `timestamp`, `user.accountId`, `issue` (`id`, `key`, `fields.project`, `fields.status`, `fields.labels`), `changelog` (`id`, `items` with `fieldId`, `fromString`, `toString`) and `matchedWebhookIds`. A delivery that matches several webhooks arrives **once**, listing them all.
- **Labels in the changelog.** A label change has `fieldId: "labels"`, with `fromString` and `toString` holding the space-separated label lists, so "added" means in `toString` but not in `fromString`. A created issue's changelog does not list its labels, so they are read from `issue.fields.labels`.
- **One URL per user.** Jira refuses a second registration URL for the same account: "Only a single URL per user is allowed to be registered via REST API". There may also be **at most 5 webhooks per app, per user, per site**. So the receiver's URL **cannot carry the workspace**. It is one fixed `/jira/webhooks`, and the workspace is found from the verified `context.cloudId` and `matchedWebhookIds`.
- **Filters.** `jqlFilter: "project in (KAN)"` works. Jira accepted `labels = …` too, but `labels` is not on the documented list of clauses, so we do not rely on it. `fieldIdsFilter: ["status", "labels"]` works: summary edits are not delivered, while status moves and created issues are. So each webhook uses `project in (…)` and that field filter.
- **Refresh and delete.** `PUT /webhook/refresh` answers `200` with the new `expirationDate`, even for an unknown id, so renewing cannot detect a missing webhook. The sweep lists `GET /webhook` instead. `DELETE /webhook` answers `202`.
- **Who made the change.** `user.accountId` is the account that made the change. On a site where the connected account is also the person moving issues, as on the spike's site, "ignore the connected account's changes" would drop every real event. So the loop guard records the moves a run's own `jira.transition` makes instead.

This phase does not change what agents receive: the request is an issue key, as in 7.2. As chosen in the interview, the "Done when" is still proven with a real Jira Cloud site, and that run is read in the console.

## Scope

### In scope

- **Spike (first, timeboxed).** On a real Jira Cloud site with the deployment's own app, reached through a tunnel, find out and record:
  - the exact form of the delivery's authorization (header name, JWT algorithm, `iss`/`aud`/`qsh` claims);
  - that the app-owner delivery rule holds;
  - which `jqlFilter` clauses are accepted (`project in (…)`, `status`, `labels`);
  - the payload shape of `jira:issue_updated` (the `changelog.items` for status and labels, `user.accountId`, `webhookEvent`, a delivery or event id usable for dedupe, and `matchedWebhookIds`) and of `jira:issue_created`;
  - how many webhooks an app may register per site.

  The findings go into tech-stack's new "Jira triggers (API contract)" section before any code is written. Any change to the decisions below goes into this file as well.
- **Trigger rules per workspace** (`jira_triggers`, Alembic `0034_jira_triggers`). Each rule has:
  - a site, and one project picked on that site (7.1);
  - **when**: `status` (the issue moves to a named status) or `label` (a named label is added, or an issue is created with it);
  - **what runs**: a template id, or a stored workflow `{id, version?}` where no version means the latest. The workflow must declare a required `input`, which receives the issue key;
  - the repo it runs on and an optional branch, when the workflow needs a repo;
  - `enabled`, and when it was created or changed.

  A rule is checked when it is saved, with the same checks `POST /runs` makes for a runnable workflow. An invalid rule is `422` with the reason.
- **Routes**:
  - `GET`, `POST`, `PATCH` and `DELETE /workspaces/{id}/jira/triggers[/{trigger_id}]`;
  - `GET …/sites/{cloud_id}/projects/{key}/statuses`, read live from Jira, for the status picker;
  - `GET /workspaces/{id}/jira` gains `webhooks`, the listening state of each site (`listening` / `not_needed` / `failed` with a reason, `expires_at`, `renewed_at`).
- **Webhook registration** (`jira_webhooks`). For each enabled site that has at least one enabled rule:
  - the platform registers one webhook for `jira:issue_updated` and `jira:issue_created`, with `jqlFilter: project in (…)` (the projects its rules use) and `fieldIdsFilter: ["status", "labels"]`, pointing at `<JIRA_WEBHOOK_BASE_URL or API_BASE_URL>/jira/webhooks`;
  - it registers it again when the set of projects changes, and deletes it once no rule needs it;
  - a worker sweep renews webhooks that are within 10 days of their expiry, and registers again any webhook that has gone missing. A failure is stored on the site and audited, and shown in the UI.
  - Disconnecting Jira (7.1) deletes the workspace's webhooks, on a best-effort basis.
- **Receiver**: `POST /jira/webhooks` (one URL for every workspace: Jira allows one per account). It returns `202` fast and holds no lock while it calls Jira. In order, it:
  1. caps the body at 1 MB;
  2. verifies the JWT against the app's client secret (HS256 only, signature, `iss` equal to the client id, `exp`, `context.cloudId`), and refuses a failed check with `401` and no further work;
  3. finds the workspaces whose registrations (`jira_webhooks`: cloud id and webhook id) are among `matchedWebhookIds`. A delivery that matches none is acknowledged and dropped (`unknown_webhook`). Each workspace found is handled on its own from here;
  4. drops duplicate deliveries by a unique key (`jira_deliveries`: workspace, cloud id, `X-Atlassian-Webhook-Identifier`);
  5. drops the event when its project is not allowed (`jira_project_allowed`);
  6. drops a status move that a run's own `jira.transition` made, recorded by the tool (`jira_own_moves`: site, issue id, status, within 10 minutes), so a run cannot start another run by moving its issue;
  7. matches the enabled rules against the changelog. Status names and labels are compared without regard to case, and a label must be newly added, not merely present;
  8. creates one run per matching rule, unless a run from the same rule on the same issue is still queued, running or waiting.

  Every delivery that passes the signature check records an outcome per workspace (`started`, `duplicate`, `no_match`, `project_not_allowed`, `own_change`, `already_running`, `start_failed` with a reason) and the run it started.
- **The run** is created through the same path as `POST /runs`, including its connection checks: `jira_not_connected`, and GitHub's for a repo. On the runs row:
  - `trigger` is `jira`, and the request (`input`) is the issue key;
  - `jira_trigger_id` and `jira_issue` (`{site, key, url}`) are set, and each summary returns `jira_issue`;
  - a start that fails, for example because GitHub was disconnected, starts nothing and writes a `jira.trigger_failed` audit entry.
- **Audit**: `jira.trigger_created`, `jira.trigger_updated`, `jira.trigger_deleted`, `jira.trigger_fired` (actor `system`, with the issue key and run id), `jira.trigger_failed`, `jira.webhook_registered`, `jira.webhook_failed`.
- **Fake.** `FakeAtlassian` records what is registered, renewed and deleted, serves project statuses, and has a test helper that builds a signed delivery. Tests and the e2e stack stay off the network.
- **UI: Settings › Triggers** (a new sub-page in the settings nav from 11.7):
  - `PageHeader` with a "New trigger" action;
  - the rules as a table from `md` and cards below it. Each row reads "When an issue in **PROJ** moves to **In Progress** → run **Answer a Jira issue** on `owner/repo`", followed by the last time it fired (`RelativeTime` plus a `StatusBadge` of the outcome, linking to its run), an enabled switch, and a delete confirmed in a dialog;
  - a listening line for each site (listening, renewed `RelativeTime`; or failed, with the reason);
  - a "New trigger" sheet shaped like the New run sheet: site, project (the picked ones), when (status from the live list, or a label as text), the workflow (templates and stored workflows whose spec declares an input), the repo combobox and the branch;
  - the three states. The empty state with no Jira connection links to Integrations.
- **Runs list and console**: the trigger reads "Jira · PROJ-12", with the key linking to the issue.
- **Specs and docs**:
  - tech-stack: "Jira triggers (API contract)", the `trigger` values, Settings › Triggers under UI, the audit actions, and decisions-log rows;
  - `docs/integrations/connecting-platforms.md`: the public URL, `JIRA_WEBHOOK_BASE_URL`, the app-owner rule, and a tunnel for local development;
  - `docs/security/security-model.md`: the receiver's checks;
  - `.env.example`, and `CHANGELOG.md`.

### Out of scope

- **Mapping fields to the run's input** (acceptance criteria, components): 7.4. Here the input is the issue key only.
- **The SDD template**: 7.5. It is the main user of this trigger once it exists.
- **GitHub webhooks** (PR review comments, `@platform fix this`): 7.6. GitHub labels starting runs: 18.3.
- **Conditions beyond one status or one label** (JQL rules, issue type, combined conditions, a transition's "from" status). A rule can say "moves to X" or "label L added", and nothing more.
- **Admin-configured system webhooks with a shared secret.** This was not chosen in the interview. Dynamic webhooks need no Jira admin and no copied secret.
- **Jira Data Center or Server.** These are Cloud-only webhooks, as in 7.1.
- **Scheduled triggers**: 18.1.
- **A fake end-to-end delivery test on the compose stack.** This was not chosen in the interview. The receiver is covered by API tests, and the run it creates is covered by the existing worker path.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| How Jira reaches us | Dynamic webhooks registered through the 7.1 OAuth app, renewed by a worker sweep | Chosen in the interview. No Jira admin is needed and no secret has to be copied by hand, and the scope was already granted in 7.1. The cost is the 30-day renewal and the app-owner rule, both documented. |
| How a delivery is trusted | The JWT (HS256, signed with the app's client secret) is checked before anything else; the workspace comes from the verified `context.cloudId` and `matchedWebhookIds` | The spike found that a delivery is signed this way and that Jira allows one URL per account, so the URL cannot name the workspace. The client secret is already on the API (7.1). |
| One webhook per workspace and site | `jqlFilter: project in (…)` (the projects its rules use) plus `fieldIdsFilter: ["status", "labels"]`; registered again when that set changes | Atlassian allows 5 webhooks per app, per user, per site (spike). The field filter keeps summary and description edits away. Our own allowlist and rule matching still decide, so the filter is not trusted. |
| What a rule matches | One status ("moves to") or one label ("added"), on one project, compared without regard to case | This is what the roadmap row names. Matching is done on the changelog, because `labels` is not a documented `jqlFilter` clause. |
| What the run receives | The issue key as its request, nothing from the issue's text | Principle 5. It is the seam 7.2 built (`issue_from: "request"`), and the run reads the issue through `jira.getIssue`. |
| Loop guard | `jira.transition` records each move it makes (`jira_own_moves`), and the receiver drops the matching status event within 10 minutes; at most one queued, running or waiting run per rule and issue | The spike showed that the connected account is often the person moving issues, so ignoring that account would drop real events. Recording our own moves is exact. `jira.transition` is the only Jira write that changes a status or a label. |
| Dedupe | `X-Atlassian-Webhook-Identifier` per workspace and site, unique in `jira_deliveries`, kept 30 days | Atlassian documents it as the same across retries. A second insert of the same key does nothing. |
| Where a rule points | A template, or a stored workflow (latest or a pinned version) that declares a required input | It reuses the run targets that exist (2.6, 5.7). A workflow with no input could not receive the issue. |
| Public URL | `JIRA_WEBHOOK_BASE_URL`, falling back to `API_BASE_URL` | A deployment behind a proxy, or a developer on a tunnel, can point Jira elsewhere without moving the OAuth callback. |
| Where rules are managed | Settings › Triggers, its own sub-page | Chosen in the interview. Rules span sites, workflows and repos, and they do not belong on the Integrations card, which manages the connection. |
| Order of work | A spike on real Jira first, then the contract, then the code | Chosen in the interview. The JWT form, the JQL subset and the payload are not settled in Atlassian's docs, and lessons.md records what guessing them cost before. |

## Open questions

- Several workspaces connected with the same Atlassian account to the same site share that account's 5 webhooks and its one URL. A sixth fails with `limit`, shown on the site's line. This is acceptable until users and roles exist.
- When the deployment's public URL changes, Jira refuses the new URL until the account's old webhooks are gone. The sync deletes the registrations it stored with another URL before it registers again. A webhook registered outside the platform with the same account blocks it, and the site's line shows `url_conflict`.
