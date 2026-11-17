# Plan: Per-project field mapping (acceptance criteria, components)

Contract first, then the backend from the client outward, then the UI and the proof. Each group keeps the project green.

## 1. Contract and spike
- [ ] Spike on the real Jira site: `GET /rest/api/3/field` lists a company-managed and a team-managed project's "Acceptance criteria" and story-points fields, with their `schema` (type, `custom`); record the result in this folder. **Partly done** (`spike.md`): the site has no field of either role yet; the shapes are confirmed in group 7.
- [x] `specs/tech-stack.md`: "Jira field mapping (API contract)" (roles, field list, mapping routes, errors), `mapped` in "Jira tools", the issue brief under "What an agent is told", the Input tab's "Run context" and the "Map fields" sheet in the UI design system; decisions-log rows (fixed roles, brief read once on first attempt, field list source).
- [x] `CHANGELOG.md` entry under `[Unreleased]`.

## 2. Jira client
- [x] `JiraPlatform.list_fields(cloud_id)` on `AtlassianApp` (`/rest/api/3/field`), models `JiraField` (`id`, `name`, `type`, `custom`) and role fit (`ROLE_TYPES`, `ROLE_SUGGESTED_NAMES`).
- [x] `get_issue(..., extra_fields=)` asks for the mapped field ids and returns their raw values; reading a value per role (ADF or string → Markdown, number) in one helper.
- [x] `FakeAtlassian`: seeded fields (a rich-text AC, a plain-text AC, story points, one of each wrong type) and issues that carry them.
- [ ] Drop `read:jira-user` from `SCOPES` only after group 7's real run (tracked there).

## 3. Store, migration and API
- [x] Alembic `0035_jira_field_mappings`: `workspace_id`, `cloud_id`, `project_id`, `role`, `field_id`, `field_name`, unique per project and role; removed with the picked project and the connection.
- [x] `agentic_store`: read, replace and list mappings; `jira_project_mapping(workspace, cloud_id, project_key)`.
- [x] Routes: `GET …/sites/{cloud_id}/fields?role=`, `GET`/`PUT …/projects/{key}/fields`, mappings in `GET /workspaces/{id}/jira`; `422` `unknown_field`, `field_type_mismatch`, `project_not_allowed`.
- [x] Unpicking a project or disconnecting removes its mapping (test).

## 4. `jira.getIssue` mapped fields
- [x] `agentic_tools.jira`: `mapped` from the issue's current project's mapping; `null` for unmapped, empty or gone fields; same caps as the description.
- [x] Tool tests: mapped rich-text AC as Markdown, story points, moved issue uses the new project's mapping, no field content in logs.

## 5. Issue brief in the run context
- [x] `IssueBrief` model and its text (`agentic_engine.agent`), `RunContext.issue` and `text()` adding it after the request between `<jira-issue>` tags with the data wording; size cap constant.
- [x] `runs.jira_brief` (JSON, in the same migration or `0036`); the worker reads it on a run's first attempt when `jira_issue` is set, through the same reader as the tool, stores it, and `run_context` passes it; resume and rerun from a step reuse it; failures end the run before any step with the fixed reasons.
- [x] Engine and worker tests: what an agent *receives* (system prompt carries the brief with mapped AC and components; a second agent after a parallel still has it), a brief read once across a resume, no read for a run without `jira_issue`.

## 6. Web
- [x] API client regenerated; `JiraFieldsSheet` (`@/settings/jira-fields-sheet`), shaped as the projects sheet: project select, a select per role (suggested first, type in caption), Save fields; refusals in an `Alert`.
- [x] Jira card: "Map fields" on each site row; each project shows "Fields mapped" / "No fields mapped".
- [x] Run console Input tab: "Run context" section (repository, request, Jira issue brief as sanitised Markdown), from `GET /runs/{id}` (`jira_brief` added to the run detail; the repo and input were already there).
- [x] Unit tests; e2e for mapping a field (fake Atlassian) and the Input tab's brief; axe and layout screenshots.

## 7. Spec-writer test workflow and real run
- [x] Test fixture workflow: `spec_writer` (read tools, `jira.getIssue`) writing `spec.md` from the brief; used by the engine test of group 5.
- [ ] Real run with Claude on a real site and repo, started by moving an issue (7.3), read step by step in the console; record findings, add a `lessons.md` entry if something reached the run that tests missed.
- [ ] Settle `read:jira-user` in `SCOPES` and tech-stack from what the run used.
