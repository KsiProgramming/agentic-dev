# Validation: `reduce` strategies: dedupe, vote

## Done when (from roadmap)
> Duplicate findings are merged with severity and confidence

Checkable form: a run whose sources report the same issue more than once writes a `findings.json` with one finding for it, its highest severity, a `confidence` and the `sources` that reported it; `vote` drops what too few sources reported.

## Automated checks

### Unit: merge rules (`packages/runtime/tests/test_findings_merge.py`)
- [x] Same `fingerprint` from two sources → one finding, `sources` both ids in source order.
- [x] No `fingerprint` → merged by category + path + line + rule; whitespace in the rule does not matter; a different line does not merge.
- [x] Highest severity kept (`low` + `high` → `high`); the representative is the first source with it.
- [x] `aliases` and `fixed_versions` unioned in first-seen order; first `help_url`; `config` `repo` wins over `platform-default`.
- [x] Confidence: 2 of 3 sources → 0.67; own confidences 0.5 and 1.0 with 2 of 2 sources → 0.75; one source → its own (or 1).
- [x] A source reporting the same issue twice counts once.
- [x] Vote: `min_votes=2` keeps 2-source groups and drops 1-source ones; default is a majority; `n < min_votes` raises.
- [x] Output order (severity, confidence, path, line, rule), counts before the cap, cap at 1,000 with `truncated`, `truncated` carried from a source, oldest `db_as_of`, `checks` concatenated, `sources` list with counts.
- [x] Empty sources (no findings) → an empty merged report with every source listed.
- [x] Deterministic: same input, same output byte for byte.

### Engine (`packages/engine/tests/test_reduce_findings.py`, `test_spec.py`, `test_validate.py`)
- [x] Flow on the fake runtime: a `parallel` (`all`) of two tool nodes returning fixed reports and an agent returning findings JSON → `reduce` `dedupe` `writes: findings.json`; the artifact has the duplicates merged with severity and confidence; `node_completed.merged` counts are right.
- [x] Same flow with `vote` `min_votes: 2`: a single-source finding is dropped.
- [x] `parallel` `any`: only completed branches are sources; `vote` with too few completed fails with ``vote 'merge' needs 2 sources, 1 completed``.
- [x] A map of 3 items feeding `dedupe` (source ids `"0"`, `"1"`, `"2"`).
- [x] A source that is not a findings report fails the reduce with the one-line error and a `port` payload.
- [x] A typed agent after a `dedupe` reduce gets its input checked; a `port_mismatch` is reported statically when its `input_schema` needs a property the findings schema lacks.
- [x] Validator: `from` a parallel accepted; `from` a later node or an agent → `reference`; `min_votes` above the branch count or quorum → `invalid_vote`; `min_votes` with `dedupe` → `schema`; existing `concat` and `agent` reduces unchanged, and `concat` from a parallel works.
- [ ] Resume: killing the worker after the parallel and restarting reruns only the reduce (checkpointer), with the same result.

### Repo checks
- [x] `uv run ruff check`, `uv run ruff format --check`, `uv run pyright` (strict), `uv run pytest` green.
- [x] `schemas/findings.v1.json` and `schemas/workflow-spec.v0.json` in sync with the models (existing export test); every 4.4 scanner report still validates.
- [ ] Web, required by `CLAUDE.md` for any UI change: `pnpm lint && pnpm typecheck && pnpm test` and `pnpm test:e2e` (axe and layout screenshots) green, with the Findings view and `Percent` covered by Vitest. Status: lint, typecheck and `pnpm test` pass; `pnpm test:e2e` has 16 failures in tests this branch does not touch (stale selectors since 4.3/4.4, runs list 22 px wide at 375, two gate flows), not run in CI since 4.3.

## Manual / demo checks
- [x] Real sandbox demo: `docker compose up`, start the sample workflow (parallel `scan.lint` + `scan.secrets` + a reviewer agent, then `reduce` `dedupe` writing `findings.json`) on a real repo with a known lint error the reviewer also reports. In the console:
  - the reduce step reads "Merged N findings into M from 3 sources";
  - the `findings.json` artifact sheet shows that issue once, with its highest severity, its confidence and "Found by 2 of 3";
  - `GET /runs/{id}/artifacts/findings.json` returns the same report, and it validates against `schemas/findings.v1.json`.
- [x] Same run with `vote` (`min_votes: 2`): only the issues two sources found remain.
- [x] No secret value appears in the merged report or the events (`grep` the downloaded events for the planted secret).
- [x] Findings view at 375 and 1440 px, light and dark.

## Merge criteria
- [ ] All checks above pass in CI.
- [x] tech-stack updated (merge contract, schema change, `invalid_vote`, `Percent`, decisions log rows), `CLAUDE.md` display table, `CHANGELOG.md` under `## [Unreleased]`.
- [ ] The open question on the confidence label is decided and written down.
- [ ] Roadmap 4.5 marked done on the PR branch.
