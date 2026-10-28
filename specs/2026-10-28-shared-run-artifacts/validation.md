# Validation: Shared run context: named artifacts in the run workspace

## Done when (from roadmap)
> Nodes exchange `findings.json` through artifacts

Made checkable: in a run of `valid/artifacts-findings.json`, the scanner writes `findings.json` (an `artifact_written` event, one row in `run_artifacts`). A reporter separated from it by an unrelated step and a gate starts with exactly that JSON as its input, and its `node_started` names `findings.json v1`. The artifact is listed by the API, shown in the console and in the gate's review, and readable as a file in the sandbox and through `artifacts.read`.

## Automated checks
- [ ] `uv run pytest packages/engine`:
  - Validation: `artifact_unknown` and `artifact_conflict` with the right `path` and `node_id`, in run order; port_mismatch through an artifact.
  - Fixtures: `valid/artifacts-findings.json` validates, and each `invalid/artifact-*.json` gives exactly its expected issue.
  - `test_artifacts_runtime.py`: every case in plan group 2, including the gate resume, the `any` join, the size caps and the CEL variable.
  - The existing compile, run and port tests stay green and unchanged.
- [ ] `uv run pytest packages/store packages/api packages/tools packages/sandbox packages/worker`:
  - The `run_artifacts` migration and versioning.
  - The artifacts endpoints (list, version, `404`, download headers incl. `nosniff`).
  - `GET /runs/{id}/gate` returns `run_artifacts`.
  - The `artifacts` MCP server (list, read, cap, unknown name).
  - `PLATFORM_TOOLS` in sync.
  - The Docker and fake sandbox `artifacts_dir`: readable, not writable by the sandbox user.
  - The worker grants the tools, mirrors after a write and re-mirrors on a fresh sandbox.
- [ ] Exports are up to date: `schemas/workflow-spec.v0.json` and `web/src/api/schema.d.ts` have no diff after re-export.
- [ ] `uv run ruff check`, `ruff format --check` and strict pyright/mypy.
- [ ] `cd web && pnpm lint && pnpm typecheck && pnpm test`: cards, sheet (sanitised Markdown), Artifacts view states, step sections and the Inbox section.
- [ ] `pnpm test:e2e`:
  - The new console test (plan group 6).
  - `a11y.spec.ts`: no serious axe issues on the Artifacts view and the sheet.
  - `layout.spec.ts` screenshots at 375 and 1440 px.

## Manual / demo checks
- [ ] **Validate:** `POST /workflows/<id>/validate` with `invalid/artifact-read-before-write.json` answers `200`, `valid: false`, with one `artifact_unknown` naming the reader and the missing name.
- [ ] **Run locally** (`docker compose up`, fake runtime): start `valid/artifacts-findings.json` with input `{"findings": [{"id": "F1", "severity": "high"}]}`, then approve the gate in the Inbox.
  - The Inbox review lists `findings.json`.
  - After approval, the reporter's Input tab shows `findings.json v1` with that JSON.
  - `GET /runs/{id}/artifacts` lists `findings.json` and `report.md`.
  - `GET /runs/{id}/artifacts/findings.json/download` saves the file.
- [ ] **Sandbox:** during the run, `docker exec <sandbox> cat /workspace/artifacts/findings.json` shows the content, and writing to it as the sandbox user is refused.
- [ ] **Worker restart:** kill the worker while the run waits at the gate, approve, and check that the new attempt still reads `findings.json`.
- [ ] **Console:** at 375 and 1440 px, in light and dark:
  - The Artifacts view, the cards and the sheet (JSON, Markdown, text).
  - No horizontal page scroll, no JSON in a table cell, and every action reachable by keyboard.
- [ ] **Real Claude run** (`AGENTIC_RUNTIME=claude`): a typed agent writes `findings.json` from a small repo, and a second agent granted `artifacts.read` summarises it into `report.md`. The console's activity shows the `artifacts.read` call with its intent.

## Merge criteria
- [ ] All automated checks above pass in CI.
- [ ] tech-stack.md has the Run artifacts contract, the codes, the tool, sandbox, gate and console rules, and the decisions log rows. README and CHANGELOG are updated in the same PR.
- [ ] The UI rules in CLAUDE.md are respected (semantic tokens only, `JsonView` for JSON, display components, three states, sanitised Markdown), or any break is stated in the PR and in tech-stack.
- [ ] Artifact content is never rendered as HTML. The sandbox copy is read-only. No size cap can be exceeded through the API or the tools.
- [ ] The roadmap phase is marked done by CI on the PR (open-pr).
