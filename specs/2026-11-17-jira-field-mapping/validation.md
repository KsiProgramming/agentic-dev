# Validation: Per-project field mapping (acceptance criteria, components)

## Done when (from roadmap)
> Spec-writer receives mapped fields

Made checkable: a spec-writer agent in a run started by a Jira trigger is told the issue's mapped acceptance criteria, story points and components in its run context, without calling a tool, and `jira.getIssue` returns the same mapped fields.

## Automated checks

Unit and integration (chosen):
- [ ] Jira client: field list parsed and filtered per role; suggested names; mapped values read (ADF → Markdown, plain string, number, missing field → `null`).
- [ ] Store and API: mapping saved, replaced and listed; `unknown_field`, `field_type_mismatch`, `project_not_allowed`; mapping removed when its project is unpicked and on disconnect; migration up and down.
- [ ] `jira.getIssue`: `mapped` for a mapped project, `null`s for an unmapped one, a moved issue uses its new project's mapping; project scoping unchanged; no field content in logs (`test_jira_tokens_appear_nowhere` style).
- [ ] Brief: read once on the first attempt and stored; reused on resume and rerun from a step; a run without `jira_issue` reads nothing; each failure ends the run before any step with its fixed reason; the cap cuts description and acceptance criteria first.

"What it receives" (chosen, lessons rule 1):
- [ ] Engine test with the spec-writer fixture workflow: the spec-writer's request context holds the issue brief between `<jira-issue>` tags with the mapped acceptance criteria, story points and components; an agent after a parallel still holds it.

Required by the repo for any `web/` change (CLAUDE.md):
- [ ] `cd web && pnpm lint && pnpm typecheck && pnpm test`
- [ ] `pnpm test:e2e`, including `a11y.spec.ts` and `layout.spec.ts` with the "Map fields" sheet and the Input tab's "Run context".

Backend:
- [ ] `uv run ruff check`, `uv run pyright` (strict) and the package test suites touched (never `packages/sandbox/tests` as a whole).

## Manual / demo checks

- [ ] On Settings › Integrations, map a project's "Acceptance criteria" and "Story points" fields from the suggested entries; the project row reads "Fields mapped". Checked at 375 and 1440 px, light and dark.
- [ ] **Real run (required by the roadmap preamble and lessons rule 1, since this phase changes what agents receive):** with `AGENTIC_RUNTIME=claude`, move an issue with acceptance criteria to the trigger's status; read the run step by step in the console. The Input tab's "Run context" shows the brief, and the spec-writer's Activity uses the acceptance criteria without calling `jira.getIssue` for them.
- [ ] The run's events and the worker's logs hold no token. The brief appears only in the run context.

## Merge criteria
- [ ] All checks above pass locally and in CI.
- [ ] `specs/tech-stack.md` holds the field-mapping contract, the brief and the UI rules, with decisions-log rows. The roadmap row links this plan.
- [ ] `CHANGELOG.md` entry under `[Unreleased]`.
- [ ] `read:jira-user` decided and recorded (kept with a reason, or dropped).
- [ ] A `lessons.md` entry if the real run showed something tests did not.
