# `router` primitive and the "Audit codebase" template

Roadmap phase: 4.6
Branch: plan/4.6-router-audit-template

## Context

This phase merges two roadmap rows: the old 4.6, the `router` primitive (rule + classifier agent), and the old 4.7, the "Audit codebase" template (read-only, report only). The template is the router's first real use, and its report path is the branch that proves the router works. Keeping the two apart would ship a primitive with no product use, then a template with nothing to branch on. The number 4.7 is retired and not reused (roadmap rule: existing phase numbers never change). Issue #69 is closed as merged into #68.

Done when: **an audit run branches on a condition and produces `findings.json` and a readable report.**

It builds on what is done:

- 1.9 CEL expressions (`agentic_engine.expr`): the router's rules are CEL conditions, like `loop.until`.
- 4.1 `parallel`: scanners and specialists run side by side; a route follows a branch's shape.
- 4.2 typed ports: the classifier answers through an `output_schema`; specialists are typed as findings.
- 4.3 run artifacts: `findings.json` and `report.md`; CEL reads `artifacts`.
- 4.4 scanners (`scan.lint`, `scan.secrets`, `scan.dependencies`) and `FindingsReport`.
- 4.5 `reduce` `dedupe` and `vote`.

It unblocks 6.7 (fix selected findings), 5.3 and 5.5 (the router in the palette and drawn as a container), and the "Heal repo" idea (`specs/ideas.md`).

Principles that drive it (mission):

- **1, one spec, many views:** routes and their conditions live in the spec; the validator, console and graph all read them.
- **2, safe by construction:** a rule is CEL, never code; a classifier can only answer with a route id it was given.
- **3, humans approve irreversible actions:** the audit is read-only. It has no write tool, no gate and no PR.
- **5, repo content is data:** findings and code reach the classifier and the report agent as input, never as instructions.
- **6, transparency:** the route taken and why (the rule, or the classifier's reason) is an event and is shown in the console.

## Scope

### In scope

**`router` primitive (engine)**
- Spec: `{type: "router", id, routes: [{id, when?: <CEL>, then: <node>}], default?: <node>, classifier?: {instructions, model?, provider?}}`. With no `classifier`, every route has `when`; with a `classifier`, no route has `when`.
- **Rule mode:** routes are tried in order; the first whose `when` is true runs, else `default`. No match and no `default` fails the router with `no route matched in 'report_path'`.
- **Classifier mode:** one agent is asked to choose. Its `output_schema` is fixed by the engine: `{route: <enum of the route ids, plus "default" when there is one>, reason: string ≤ 300}`. A wrong-shaped answer fails the router as a port error (4.2). The agent counts toward `agents_spawned` and its usage toward the run's cost.
- CEL reads `last`, `results` and `artifacts`, as `map.over` does; the expression is compiled when the spec is validated.
- Exactly one route runs, on the router's input. The router's output (and its `data`) is the chosen route's output. Routes not taken never start.
- Event `route_chosen {route, mode: "rule" | "classifier", reason}` is logged before the route starts. In rule mode, `reason` is the matching `when` text, or `"default"`.
- **Nesting:** a router can sit anywhere: a sequence, a loop body, a map body or a parallel branch. A route is one `agent`, `tool` or `sequence` node. It may hold a gate, writer or publisher only where its parent allows one (a map body still cannot write).
- **Parallel branches may nest (relaxes 4.1):** today `parallel_issues` returns `not_allowed_in_parallel` for any `parallel`, `reduce` or `router` inside a branch. A branch may now hold:
  - a `parallel`;
  - a `reduce` with no `writes`;
  - a `router`.

  Gates, writers and publishers stay forbidden, and `loop` and `map` stay forbidden too, as today. Agents over `agents_alive` (a parallel inside a branch) wait for a slot at runtime instead of being refused (changed during the build, with the user: see the decision below); only a parallel with more direct branches than the limit is refused, as before. `invalid_vote` checks a nested `vote` against its own parallel. A reduce's `from` must be in the same branch, route or body, or around it.
- **Validation:** route ids are unique and distinct from `default`, and the modes are not mixed (`schema` errors). `invalid_expression` for a `when` that is not valid CEL; `invalid_router` for a route that is not an agent, tool or sequence node. For artifacts, a name written after the router counts as always written only when every route, `default` included, writes it. Port checks (as built): a router breaks the edge like a container; a read of an artifact its routes write is typed by their writer when they all give it the same `output_schema`. A publisher after the router cannot rely on a writer or gate inside a route.
- Durable: a resume inside a route continues in that route; the choice is in the checkpoint, so a classifier is not asked again.
- Policy: depth, iterations and `agents_spawned` count only the route that runs; at validation the worst-case route counts.

**API**
- `GET /runs/{id}` and the event stream carry `route_chosen`. The OpenAPI and the workflow JSON Schema (`schemas/workflow-spec.v0.json`) are regenerated.
- `GET /templates` lists the new template.

**"Audit codebase" template (`audit-codebase`)**
- Read-only: agents get only `repo.list_files`, `repo.read_file`, `repo.search`, `artifacts.*` and `scan.*`. There is no write tool, gate, `github.*` tool or PR.
- Flow:
  1. A `parallel` (`join: all`) of the chosen checks: the scanner tool nodes `scan.lint`, `scan.secrets` and `scan.dependencies`, and an agent-review branch with the specialists (security, tests, architecture and maintainability). Each specialist answers with a `FindingsReport` (typed port).
  2. A `dedupe` reduce writes `findings.json`.
  3. A rule `router` named `report_path` reads `artifacts["findings.json"]`:
     - route `clean` when there are no findings: a short "No issues found" report listing the checks that ran;
     - route `fix_first` when any finding is high or critical: a report that opens with a "Fix first" section;
     - `default`, `standard`: the full report.

     Every route is one report agent that writes `report.md`.
- **Reviewers:** a `reviewers` param (1–3, default 1). With 2 or 3, each specialist's branch of the outer parallel is a sequence: a nested `parallel` of that many copies, then a `vote` reduce (majority, no `writes`). The outer `dedupe` then merges them with the scanners. Scanner findings are deduped, never voted. Each review is its own branch, so the merge sees each one's report (a sequence of reviews in one branch would output only the last). The worst case, 3 reviews × 3 agents = 9, is above `agents_alive` (8): the extra agents wait for a slot.
- **Params** (`AuditParams`, rendered by the New run sheet from JSON Schema). This is the "which checks" input deferred from 4.4.
  - `checks`: a subset of `lint`, `secrets`, `dependencies`, `security`, `tests`, `architecture`; default all; at least one.
  - `path`: the folder to audit; default the repo root.
  - `min_severity`: the lowest severity the report lists; default `low`. `findings.json` keeps everything.
  - `reviewers`.
  - `reviewer_model` and `report_model`: optional. Unset means the workspace default (Sonnet 5.5 in the adapter today). When set, each must be a Claude model id the platform prices (`agentic_runtime.pricing`), so the cost is always known; another value is a 422 on the field.
- `FindingsReport` grows additively: `scanner` may be `agent`, and `category` may be `security`, `tests` or `architecture` (deferred from 4.5). `schemas/findings.v1.json` is regenerated.
- `requires`: `claude`, `github`.

**UI (`web/`)**
- Console, router step: Output reads "Took route `fix_first`" with its reason, then the routes not taken, each marked Skipped. The step-list line reads "Routed to fix_first". The chosen route's steps nest under the router as a container's do.
- Graph tab: **switch the whole graph to ELK (`elkjs`, lazy-loaded)**, as the decision log planned for the router. Routes are drawn as branches of the router's box, with the taken one marked and the others muted and labelled Skipped. Parallel, map and loop boxes move to the same layout.
- Template gallery: an "Audit codebase" card with an icon, "Requires Claude, GitHub" and a "Read-only: no pull request" line. The form comes from `AuditParams`.
- `report.md` and `findings.json` are shown through the existing artifact cards, Markdown renderer and Findings view. No new screen.

**Specs**
- tech-stack: a "Router (API contract)" section; the audit template in "Tool layer" or its own section; the `FindingsReport` additions; a decisions-log row for the router semantics; the "Run graph" row updated from "hand-written layout" to ELK.
- roadmap: the merged 4.6 row and the "Next up" line (done in this planning PR).

### Out of scope

- Picking findings to fix and fix PRs: 6.7 (orchestrator).
- A classifier router inside the audit template: the classifier is proven by engine tests and a sample spec. The template's router is a rule, so audits stay cheap and repeatable.
- A performance specialist and a "dependencies and licences" agent review: later, as more template checks.
- Saved or versioned user templates: 5.7 and 9.9.
- Editing routes on the canvas: 5.2–5.5.
- A new Playwright spec for the audit run. The existing e2e, axe and layout suites must pass, with screenshots re-baselined for ELK.
- Scheduled audits ("Heal repo" idea).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Roadmap merge | Old 4.7 merged into 4.6; 4.7 retired; every reference rewritten to 4.6; #69 closed as merged into #68 | User choice. The template is the router's first use and the proof of its "Done when". Numbers never change, so 4.7 is not reused. |
| Router semantics | First match in order, optional `default`; one route runs | User choice. Easy to read and to show in the console; "every match" would duplicate `parallel`. |
| Classifier | An agent answers `{route, reason}` through an engine-made `output_schema` with an enum of route ids | Reuses 4.2 typed ports: an invented route fails as a port error, with no new parser. The reason is shown to the user (principle 6). |
| Router in the audit | A rule on `findings.json` picks the report path (`clean`, `fix_first`, `standard`) | User choice. Deterministic and free. The classifier is covered by engine tests, not run on every audit. |
| Nesting | Anywhere; a route is agent, tool or sequence and may hold a gate or writer only where its parent allows | User choice. Unlike a parallel's branches, routes do not run at once, so a writer in a route makes no branch conflict. |
| Artifacts after a router | Written always only when every route writes it | Same rule as a loop body's first iteration (4.3): a reader must never find a name missing. |
| Audit checks | Scanners + specialist agents, merged by `dedupe`; optional `vote` with `reviewers` 2–3 | User choice. `vote` cuts false positives from agents only; it is off by default to keep the default run cheap. |
| Nesting in parallel branches | Allowed for `parallel`, non-writing `reduce` and `router` | User choice, over a reduce that reads several artifacts or dropping `vote`. Scanners and voted specialists run side by side under one merge, and it lets a router sit in a branch as promised above. |
| Agents alive when nested | Throttled, not refused: agents over `agents_alive` wait for a slot | Decided with the user during the build (2026-10-28): each review must be its own branch for the merge, so `reviewers: 3` needs 9 agents; the runtime already throttles, and refusing would only fail workspaces with a low limit. |
| Models | `reviewer_model` and `report_model` template params, both unset by default (the workspace default) | User choice. The cost of a default audit stays predictable, especially with `reviewers: 3`. This departs from tech-stack's "Opus for reviewers" default: a user picks Opus per run. Tech-stack records it. |
| Report | `report.md` written by one agent per route; `min_severity` filters the report, not `findings.json` | The machine output stays complete for 6.7. The human report stays short. |
| Graph layout | ELK now, for the whole graph | User choice. It does what the 3.5 and 4.1 decision rows promised for the router, with one layout path rather than two. |
| Build order | Engine → API → template → UI → specs | User choice. Each group leaves `main` working, and the UI builds on recorded events. |

## Open questions

- None. The reviewers topology (nesting allowed) and the models (template params) were settled with the user on 2026-10-28, before implementation.
