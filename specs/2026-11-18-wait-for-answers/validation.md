# Validation: A run that asks waits for the answer

## Done when (from roadmap)
> An SDD run on an issue with open questions posts them and builds nothing until a comment from another person arrives; the rewritten spec is approved again, and only then does `tasker` start. A real Claude run read step by step in the console

## Automated checks
- [ ] The run holds after `ask_jira`: status `waiting` at `wait_for_answers`, and `tasker` has not started
- [ ] Resume by webhook: a `jira:comment_created` from another account resumes the run; a retried delivery does not resume it twice
- [ ] Resume by direct check: the sweep and `POST /runs/{id}/answers/check` find a newer comment by another account and resume; with none, `found: false` and the run keeps waiting
- [ ] The platform's own comment (the questions comment, and any later comment by the connected account) does not resume the run, by webhook or by check
- [ ] A comment on another issue, or in a project not picked, resumes nothing
- [ ] The timeout: past `answer_ttl_s` the run ends `cancelled` with "Waiting for answers expired" and `tasker` never starts
- [ ] A restart mid-wait (worker stopped, sandbox kept, checkpoint reloaded) still waits, and still resumes on an answer
- [ ] Waiting is not active time: `active_ms` does not grow during the wait
- [ ] What agents receive: after a wait the spec writer's request lists the issue's comments after the questions (as data), the last `spec.md` and `plan.md`; the rewritten spec has the markers removed or narrowed; the run returns to `approve_spec` before `tasker`
- [ ] `max_clarifications`: after the last round with markers left, `build_on_assumptions` asks; rejecting ends the run completed with nothing built; approving builds
- [ ] Rejecting at `post_questions`, `approve_spec` or `build_on_assumptions` ends the run
- [ ] A human decision on a `wait_for` is `409 not_a_gate`; the payload's text is never stored or logged (ids only)
- [ ] Validation: `wait_for` refused in a `map` or `parallel`, and without a Jira connection; the template validates for every option; fixtures, JSON Schema and OpenAPI exports regenerated
- [ ] Web unit tests: the waiting state, Check now (found, not found, error), the Inbox row; `pnpm test:e2e` including axe and layout screenshots
- [ ] Backend: `uv run ruff check`, `uv run mypy`, `uv run pytest` per package (not `packages/sandbox/tests` whole)
- [ ] Web: `cd web && pnpm lint && pnpm typecheck && pnpm test`

## Manual / demo checks
- [ ] A real Claude run (`AGENTIC_RUNTIME=claude`) of SDD on an issue with real open questions, read step by step in the console (lessons rule 1 and 9): it posts the questions and holds; a comment from another person resumes it; the spec is rewritten with the answer; `approve_spec` shows it; only then do `tasker` and the build run
- [ ] Look at the waiting state at 375 and 1440 px, light and dark

## Merge criteria
- [ ] All checks above pass in CI
- [ ] `specs/lessons.md` has the entries from the real run
- [ ] `tech-stack.md`, `roadmap.md` (7.9 row), `docs/` and `CHANGELOG.md` updated in the same PR
- [ ] No Jira text in logs; the webhook reads ids only
