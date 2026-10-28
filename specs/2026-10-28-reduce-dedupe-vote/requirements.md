# `reduce` strategies: dedupe, vote

Roadmap phase: 4.5
Branch: plan/4.5-reduce-dedupe-vote

## Context

The audit flow (4.7) gets findings from several sources: the 4.4 scanners (`scan.lint`, `scan.secrets`, `scan.dependencies`), often run as branches of a `parallel`, and specialist agents that restate or add findings. Today a `reduce` can only `concat` a map's outputs or hand them to an agent. Concatenating gives duplicates, and asking an agent to merge 1,000 findings costs tokens and is not reproducible. 4.5 adds two deterministic strategies that merge findings with no model call:

- `dedupe`: one finding per issue, with the highest severity and a confidence.
- `vote`: the same merge, keeping only the issues that enough sources reported.

It builds on what is done:

- 1.10 `map` + `reduce` (`concat`, `agent`).
- 4.1 `parallel`: its output is the completed branches' outputs by branch id.
- 4.2 typed ports: the merged report is typed, so the next node's `input_schema` is checked.
- 4.3 run artifacts: a reduce already takes `writes` (`findings.json`).
- 4.4 `FindingsReport` (`schemas/findings.v1.json`) with a stable `fingerprint`, which was made for this phase.

It unblocks 4.7 (the "Audit codebase" template: findings.json plus report) and 6.7 (fix selected findings).

Principles that drive it (mission):

- **1, one spec, many views:** the strategy and its threshold are in the spec, and the validator checks them before a run.
- **2, open but safe by construction:** the merge is deterministic and capped; it runs no model and no code from the spec.
- **5, content is data:** findings are parsed and checked against the schema, never followed as instructions.
- **6, transparency:** each merged finding says which sources reported it, and the console shows it.
- **7, small steps:** findings only. A general "dedupe any JSON list" can come later if a workflow needs it.

## Scope

### In scope

- **Two new strategies** on `reduce`: `strategy: "dedupe" | "vote"`, next to `concat` and `agent`.
  - `vote` takes `min_votes` (an integer ≥ 1; default: a majority of the sources that completed, `floor(n / 2) + 1`). `dedupe` takes no field of its own. `separator` and `agent` stay only for their strategies, and `min_votes` on another strategy is a `schema` error.
- **`from` may name a `parallel`** as well as a map, for every strategy. A source is one map item (named by its index, `"0"`, `"1"`…) or one completed parallel branch (named by its branch id). With a `parallel` `any` or `quorum` join, only the completed branches are sources.
- **Input:** each source's output must be a `FindingsReport` (parsed as JSON from its text, as typed ports do, and checked against the findings schema). A source that is not one fails the reduce with one line in the typed-port error format: ``input of 'merge' (from 'lint') does not match its input_schema at /findings/3/severity: 'urgent' is not one of […]``, with `port` on its `node_failed`. A finding may leave out `fingerprint` (an agent cannot compute a sha256); the reduce gives it the fallback key below.
- **Grouping:** findings are the same issue when they have the same `fingerprint`. A finding with no `fingerprint` gets one from its `category`, `path`, `line` and `rule` (`fingerprint()`, so whitespace is normalised). Agents that restate a scanner finding are asked to keep its `fingerprint` (said in the schema's description of the field).
- **Merge of one group:**
  - `severity`: the highest in the group.
  - The other fields come from the finding with that severity in the first source in order (map item order, then branch order). `aliases` and `fixed_versions` are the union of the group's, in first-seen order. `help_url` is the first one given. `config` is `repo` if any source found it with the repo's config.
  - `sources`: the ids of the sources that reported it, in source order (a source counts once, even if it reported the issue twice).
  - `confidence` (0 to 1, two decimals): the share of sources that reported it, times the mean of the group's own `confidence` values (a finding with none counts as 1). With one source every finding has confidence 1 times its own.
- **`vote`:** keeps the groups reported by at least `min_votes` sources. It fails, before merging, when fewer sources completed than `min_votes`: ``vote 'merge' needs 2 sources, 1 completed``. It never returns an empty report that only looks clean.
- **Output:** a `FindingsReport` with `scanner: "merged"`; `checks` from every source in source order; the merged findings most severe first, then highest confidence, then path and line; `counts` of the merged findings before the cap; the 1,000-finding cap and `truncated` (also true if any source was truncated); `db_as_of`, the oldest one given; and a new `sources` list (`{id, scanner, findings}` for each source, `findings` being how many it gave). The result's `data` is the report, its text the pretty JSON, as for a typed node. `writes: findings.json` stores it.
- **Schema change, additive (v1 stays v1):** `scanner` adds `"merged"`; `Finding` adds optional `confidence` (0 to 1) and `sources` (list of strings); `fingerprint` becomes optional on input (the reduce always sets it); `FindingsReport` adds optional `sources`. Scanner output only gains these fields as `null`. `schemas/findings.v1.json` is regenerated.
- **The findings model moves to `agentic_runtime.findings`**, which the engine and the tools both depend on; `agentic_tools.scan.report` re-exports it, so the scan server and its imports do not change.
- **Typed output:** a `dedupe` or `vote` reduce's output is typed as the findings schema, so `port_mismatch` checks the edge to the next node (a typed edge, where `reduce` broke the edge before) and `port_mismatch` follows a `reads` of its artifact to it.
- **Validation** (`validate_workflow`, in run order):
  - `reference`: `from` is not a map or a parallel that runs before the reduce (the existing message, now "a map or parallel").
  - `invalid_vote` (new code): `min_votes` greater than a parallel's branch count, or greater than its `quorum` join's `quorum` when that join lets fewer complete. Against a map it is checked at runtime only (its item count is not known before).
  - `port_mismatch`: a source of a `dedupe` or `vote` reduce whose `output_schema` declares a top-level `findings` property that is not an array, or a source node typed with an `output_schema` that has no `findings` property.
- **Events:** the reduce logs `node_started`, then `node_completed` with `merged: {sources, findings_in, findings_out}`, or `node_failed` with the error (and `port` for a source that is not a report).
- **Console:** the Findings view (`@/runs/findings`) of a merged report shows a "Merged from 3 sources: lint, secrets, reviewer" line, a Confidence column (a percentage, from `md`; on the cards below that) and "Found by 2 of 3" with the source ids under each finding. The step list line of a merging reduce reads "Merged 42 findings into 30 from 3 sources". A percentage goes through a new `Percent` display component (`@/components/display`), with its line in tech-stack and `CLAUDE.md`.
- **Specs:** tech-stack (spec fields, the merge rules, the findings schema change, the validation code, the decisions log), `CLAUDE.md` table line for `Percent`, `CHANGELOG.md`.

### Out of scope

- Fuzzy matching (nearby lines, similar messages, different rule ids for the same issue): only the fingerprint or the exact fallback key groups findings. Later, if the audit shows it is needed.
- Generic JSON dedupe with a CEL key, or reducing any other shape than findings.
- `reduce` with `reads` (merging artifacts written anywhere in the run): sources are only the map or parallel in `from`.
- New finding categories for agent findings (architecture, security review, tests): 4.7, with the audit template.
- Merging against findings of earlier runs, issues or PRs: later (see `specs/ideas.md`).
- Weighting sources (a scanner counting more than an agent) and severity by vote: everyone counts once, the highest severity wins.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Inputs | `from` a map or a parallel; every source's output a `FindingsReport` | The scanners run side by side as parallel branches (4.1, 4.4), and reviewers fan out in a map. One shape keeps the merge small and checkable. |
| Grouping key | The `fingerprint`, else a fingerprint of category, path, line and rule | Scanner fingerprints are stable across runs (4.4). Agents cannot compute a sha256, so the reduce computes their key, and they keep a scanner's fingerprint when they restate it. |
| Severity | The highest in the group | A merge must never make an issue look less severe than one source said. |
| Confidence | Share of sources that reported it, times the mean of the findings' own `confidence` | Explainable in one sentence, and the same number drives `vote`. Agents may give their own confidence; a scanner's finding counts as certain. |
| Vote threshold | `min_votes`, default a majority of the completed sources; too few sources fail the node | A vote with one voter is not a vote; failing is clearer than an empty report. |
| Where the model lives | `agentic_runtime.findings`, re-exported by `agentic_tools.scan.report` | The engine must parse and merge reports but does not depend on the tools package; both already depend on the runtime. |
| Schema version | Additive fields in v1 (`merged`, `confidence`, `sources`, optional `fingerprint` on input) | Every 4.4 report stays valid, and the console and ports read one schema. |
| No model call | Both strategies are pure functions | Reproducible, free, and fast on 1,000 findings; the `agent` strategy stays for judgement. |

## Open questions

- With `dedupe` over scanners that find different kinds of issues, a lint-only finding gets confidence 1/3. That is honest for agreement but may read as "unsure". The console labels the column "Agreement" if the demo shows it confuses; to decide in review of the UI step.
