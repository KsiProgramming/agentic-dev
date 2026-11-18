# Validation: Spec and prototype at one gate

## Done when (from roadmap)
> An SDD run's spec gate shows the spec, the plan and the prototype's diff; a comment sends the spec back, and the revised spec is approved and drives the build

## Automated checks
- [ ] Gate `on_changes` validates only inside a loop; a `changes` decision without comments, or on a gate without `on_changes`, is a `422`
- [ ] A `changes` decision completes the gate and the loop runs again; past `max_revisions` the gate offers no Request changes
- [ ] What agents receive: the spec writer's request holds the comments (as data, between tags) after a request for changes, and the last spec and plan; the prototype writer runs only when `has_ui` is true
- [ ] The prototype's branch cannot be published: validation rejects `github.openPR` and `repo.commitArtifacts` from it; no run in the tests pushes it
- [ ] `spec.md` carries `AC-` ids with "When … the system shall …" criteria, and `plan.md` has design, files touched, risks and test plan (format check on the fake runtime's typed answers)
- [ ] Worker AC test on the fake GitHub and Atlassian: comment, revised spec, approval, PR with the Spec Kit files and Jira links
- [ ] Web unit tests for Request changes in the dock and the Inbox
- [ ] Backend: `uv run ruff check`, `uv run mypy`, `uv run pytest` (not `packages/sandbox/tests` whole)
- [ ] Web: `cd web && pnpm lint && pnpm typecheck && pnpm test`; JSON Schema and OpenAPI exports regenerated and committed

## Manual / demo checks
- [ ] A real Claude run of SDD on a UI task, read step by step in the console (lessons rule 1): the spec gate shows the spec, the plan and the prototype's diff; Request changes with a comment on the spec; the next pass's spec answers it; approving starts the build from the approved files
- [ ] A backend-only task builds no prototype and the gate shows two items
- [ ] Look at the gate review at 375 and 1440 px, light and dark

## Merge criteria
- [ ] All checks above pass in CI
- [ ] `specs/lessons.md` has the entries from the real run
- [ ] `tech-stack.md`, `roadmap.md` (7.8 row and the "Next up" line), `docs/` and `CHANGELOG.md` updated in the same PR
- [ ] No secrets or Jira text in logs; the prototype branch appears in no push
