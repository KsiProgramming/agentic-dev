# Plan: `reduce` strategies: dedupe, vote

Engine first, UI last. Each group leaves the repo green.

## 1. Findings model in the runtime package, schema extension
- [x] Move `Finding`, `Check`, `FindingsReport`, `fingerprint`, `clip_message`, `build_report`, `SEVERITIES`, `MAX_FINDINGS` from `packages/tools/src/agentic_tools/scan/report.py` to `packages/runtime/src/agentic_runtime/findings.py`; `agentic_tools.scan.report` re-exports them (no import in the scan server changes).
- [x] Additive v1 fields: `Scanner` adds `"merged"`; `Finding.fingerprint` optional (`str | None`), with a description asking agents to keep a scanner finding's fingerprint; `Finding.confidence: float | None` (0 to 1); `Finding.sources: list[str]` (default empty); `FindingsReport.sources: list[Source] | None` (`{id, scanner, findings}`).
- [x] Scanners still always set `fingerprint` (a test on each scanner's report).
- [x] `uv run python scripts/export_workflow_schema.py` regenerates `schemas/findings.v1.json`; the schema-in-sync test passes.
- [x] Web: the Findings types (`web/src/runs/findings/findings.ts`) take the new fields, optional; the OpenAPI spec and `web/src/api/schema.d.ts` are regenerated.

## 2. Pure merge functions
- [x] `agentic_runtime/findings.py` (or `findings_merge.py` beside it): `merge_reports(sources: Sequence[tuple[str, FindingsReport]], *, min_votes: int | None) -> MergeResult` where `MergeResult` holds the report and `findings_in`.
  - Group key: `fingerprint`, else `fingerprint(category, path, line, rule)`.
  - Group merge: highest severity, representative from the first source with it, unions of `aliases` / `fixed_versions`, first `help_url`, `config` `repo` if any, `sources` deduplicated in source order, `confidence = round(len(sources) / n * mean(own or 1), 2)`.
  - `min_votes` given: keep groups with `len(sources) >= min_votes`; `VoteError` when `n < min_votes`.
  - Report: `scanner="merged"`, `checks` concatenated, order by severity, confidence desc, path, line, rule; counts before cap; cap 1,000; `truncated` if cut or any source was; `db_as_of` the oldest; `sources` list.
- [x] `packages/runtime/tests/test_findings_merge.py`: the unit tests listed in validation.md.

## 3. Spec model and validator
- [x] `ReduceNode` (`packages/engine/src/agentic_engine/spec/models.py`): `strategy` adds `"dedupe"`, `"vote"`; `min_votes: int | None` (`ge=1`, `vote` only, checked in `_strategy_fields`); docstring and `from` description say "map or parallel".
- [x] `map_issues`: `from` may name a map or a parallel that runs before the reduce (`reference` otherwise, message updated); new `invalid_vote` when `min_votes` exceeds a parallel's branches or a `quorum` join's `quorum` (add the code to the issue code list).
- [x] Ports (`agentic_engine/spec` port edges): a `dedupe`/`vote` reduce is a typed producer whose output schema is the findings schema (loaded from `agentic_runtime.findings`), so the edge to the next step and a `reads` of its artifact are checked; `port_mismatch` on a source whose `output_schema` has no `findings` array.
- [x] Budget check: `dedupe`/`vote` reduces have no model, so they are skipped (as `concat`).
- [x] Re-export the workflow JSON Schema (`schemas/workflow-spec.v0.json`).
- [x] Tests in `packages/engine/tests/test_spec.py` and `test_validate.py`.

## 4. Compiler wiring
- [x] `_reduce` in `packages/engine/src/agentic_engine/graph/compile.py`: read the sources from the map (`items`/`outputs`, ids `"0"`, `"1"`…) or the parallel (`outputs` by branch id, branch order); for `dedupe`/`vote` parse each output as JSON and validate it as `FindingsReport` (reuse the typed-port error formatting in `agentic_engine.ports` for the one-line error and the `port` payload); call `merge_reports`; result `data` = report dump, text = pretty JSON; `_write` when `writes`; `node_completed` with `merged: {sources, findings_in, findings_out}`.
- [x] `concat` and `agent` also accept a parallel `from` (branch outputs in branch order; the agent's input items are the branch ids).
- [x] Engine flow tests (`packages/engine/tests/test_reduce_findings.py`) on the fake runtime: see validation.md.

## 5. Console
- [x] `Percent` in `web/src/components/display` (built on a formatter in `@/lib/locale`), with a unit test.
- [x] `FindingsView`: "Merged from N sources: …" line, Confidence column from `md` and on the cards, "Found by 2 of 3" with source ids (mono) under a finding; unchanged for scanner reports.
- [x] Step list summary for a merging reduce from `node_completed.merged` ("Merged 42 findings into 30 from 3 sources").
- [x] Vitest for both.
- [ ] A merged report in an e2e run, so the layout and axe checks cover the merged Findings view (they cover the pages, not this step today); checked by hand in the demo instead.

## 6. Specs, demo, changelog
- [x] `specs/tech-stack.md`: a "Reduce strategies (4.5)" part under the tool layer or a new "Findings merge (API contract)" section (fields, grouping, merge, vote, output, events); the findings schema change in "Scanners (4.4)"; `invalid_vote` in the validation codes; `Percent` in Display values; decisions log rows (inputs, grouping key, confidence, vote threshold, where the model lives).
- [x] `CLAUDE.md`: `Percent` line in the display values table (written in tech-stack first).
- [x] `CHANGELOG.md` entry under `## [Unreleased]`.
- [x] Sample specs in the engine fixtures: `findings-merge.json` (two scans and a reviewer agent, then `dedupe` writing `findings.json`, then a typed summary) and `findings-merge-scans.json` (four overlapping scans, then `dedupe` and `vote`, no model), the second used for the real sandbox demo.
- [ ] Roadmap 4.5 marked done by CI on the PR (open-pr skill).
