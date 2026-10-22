# Validation: "Generate docs" template

## Done when (from roadmap)
> AC-1: connect GitHub, pick a repo, docs run opens a PR

## Automated checks
- [ ] `packages/tools/tests/test_list_modules.py`: manifest detection, fallback dirs, `include` filter, 40 cap with `truncated`, structured output shape.
- [ ] `packages/engine/tests/test_templates.py`: `build_docs_spec` output validates for default and custom params; `output_dir` with `..` or an absolute path, and over-long `extra_instructions`, are rejected; `approve` gate always sits before `publish`.
- [ ] `packages/engine/tests/test_docs_template.py` (fakes only, no network): a 3-module repo maps 3 items, the writer commits `docs/README.md` + 3 module pages on `agent/<run>/writer`, the run pauses at `approve`, approval opens a PR on the fake GitHub; rejection pushes nothing.
- [ ] `packages/api/tests/test_templates.py`: `GET /templates` lists `docs` with its parameters schema.
- [ ] `packages/api/tests/test_runs.py`: `POST /runs` with `template` stores the built spec; both or neither of `workflow`/`template` → 422; unknown template → 422; bad params → 422 with the field path; template without `repo` → 422.
- [ ] Vitest: docs card (repo list, request body, errors, not-connected), approval buttons, PR link.
- [ ] OpenAPI and web client re-exported with no diff in CI.
- [ ] CI green: `ruff`, `pyright`/`mypy` strict, `pytest`, ESLint, Prettier, `tsc`, Vitest, roadmap check.

## Manual / demo checks
- [ ] `docker compose up` with a real GitHub App configured (README steps) and a Claude key saved in `/settings`.
- [ ] `/settings`: GitHub shows connected and lists the test repo (closes the 1.5 "live proof" question).
- [ ] Home page: pick the test repo, keep defaults, click **Generate docs** → redirected to `/runs/{id}`.
- [ ] Monitor shows `list_modules`, one `map_item_*` pair per module, `combine`, `writer` commit, then the gate waiting with **Approve**/**Reject**.
- [ ] Click **Approve** → `publish` completes and the monitor shows the PR link.
- [ ] On GitHub: the PR is open from `agent/<run>/writer` and contains `docs/README.md` plus one page per module; nothing was pushed before approval.
- [ ] Repeat with `output_dir: documentation` and a module filter; the PR only touches `documentation/` and the filtered modules.
- [ ] Logs from API, worker and tool servers contain no Claude key or GitHub token.

## Merge criteria
- [ ] All checks above pass in CI
- [ ] Manual AC-1 demo done; PR link and module count recorded in the PR description
- [ ] README "Generate docs" section and CHANGELOG entry added
- [ ] Roadmap phase 1.11 marked done (`complete-phase`)
