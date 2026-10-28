# Plan: `router` primitive and the "Audit codebase" template

Order: engine → API → template → UI → specs (user choice). Each group leaves `main` working.

## 0. Roadmap merge (this planning PR)
- [x] `specs/roadmap.md`: one 4.6 row (router + audit), a note that 4.7 is retired, and the "Next up" line set to Milestone 4 at 4.6.
- [x] Rewrite every "4.7" pointer to "4.6":
  - `specs/tech-stack.md`
  - `specs/ideas.md`
  - `packages/runtime/src/agentic_runtime/findings.py`
  - the dated plan folders (shared-run-artifacts, typed-ports, deterministic-tool-nodes, reduce-dedupe-vote, parallel-join-policies, create-repo-scaffold)
- [x] Fix two pointers that were already wrong, to 5.7 / 9.9 ("saved and versioned templates"): `templates/__init__.py` and `2026-10-22-generate-docs-template`.
- [x] `CHANGELOG.md` entry under `[Unreleased]`.
- [ ] Close issue #69 as "not planned" with the comment "Merged into 4.6 (#68)". After the merge to `main`, the roadmap-board sync renames #68.

## 1. `router` spec and validation (engine)
- [ ] `spec/models.py`:
  - `Route` (`id`, `when?`, `then: Node`), `RouterClassifier` (`instructions`, `model?`, `provider?`) and `RouterNode` (`routes` 1–8, `default?`, `classifier?`), added to the `Node` union.
  - Model validators: one mode only, unique route ids, no id `default`.
- [ ] `expr.py`: `ROUTE_VARIABLES` (`last`, `results`, `artifacts`). Update the module docstring, which says "later `router`".
- [ ] Structure rules in the validator:
  - nesting rules (a route is agent/tool/sequence; gate, writer and publisher follow the parent);
  - `invalid_expression` on `routes[i].when`;
  - `invalid_router`;
  - the artifact flow (always written only when every route writes it);
  - `port_mismatch` against every route's last output;
  - worst-case policy counts.
- [ ] Relax `parallel_issues` (`not_allowed_in_parallel`): a branch may hold a `parallel`, a `reduce` without `writes` and a `router`. Gates, writers, publishers, `loop` and `map` stay forbidden.
  - The `agents_alive` check counts nested branches at their worst case.
  - Update the `ParallelNode` docstring and tech-stack's parallel rules.
  - Tests: `test_parallel.py` (a nested parallel + vote runs; a writing reduce in a branch is still refused) and `test_validate.py`.
- [ ] Fixtures: `fixtures/specs/valid/parallel-nested-vote.json`, `fixtures/specs/valid/router-rule.json`, `router-classifier.json`, `router-in-map.json`. Under `invalid/`: `router-mixed-modes.json`, `router-bad-cel.json`, `router-artifact-one-route.json`, `router-writer-in-map.json`.
- [ ] Regenerate `schemas/workflow-spec.v0.json` (`scripts/export_workflow_schema.py`).
- [ ] Tests: `test_spec.py`, `test_validate.py`, `test_artifact_flow.py`, `test_expr.py`.

## 2. `router` at runtime (engine)
- [ ] `graph/compile.py`:
  - compile the router to a choose step plus one subgraph per route;
  - store the choice in `RunState`, so a resume skips the choice;
  - the router's result is the route's result.
- [ ] Classifier: an `AgentNode` built by the engine with the enum `output_schema`. It runs through the normal agent step (usage, events, port check).
- [ ] `events.py`: the `route_chosen` payload. No match and no default fails the router with one line.
- [ ] Tests: a new `test_router.py` on the fake runtime:
  - first match, default, no match;
  - the classifier picks, or answers an unknown route, or answers a wrong shape;
  - a router in a loop, a map and a parallel branch;
  - a worker restart inside a route (`test_resume.py`);
  - `agents_spawned` and budget counts.

## 3. API
- [ ] The run summaries and event types carry `route_chosen`. Regenerate the OpenAPI (`scripts/export_openapi.py`) and the web client types.
- [ ] Test: `test_run_summaries.py` / events API with a router run.

## 4. "Audit codebase" template
- [ ] `agentic_runtime/findings.py`: `Scanner` adds `agent`, `Category` adds `security`, `tests` and `architecture`. Regenerate `schemas/findings.v1.json`.
- [ ] `templates/audit.py`:
  - `AuditParams` (`checks`, `path`, `min_severity`, `reviewers`, `reviewer_model`, `report_model`) and `build_audit_spec`;
  - the models: unset means no `model` on the node (the workspace default); set must be priced in `agentic_runtime.pricing`;
  - specialist instructions (repo content is data; answer as a `FindingsReport`);
  - the reviewers topology (in the outer parallel, one branch of specialists in sequence, each a nested `parallel` + `vote`);
  - the `report_path` router with `clean`, `fix_first` and `standard`, each writing `report.md`.
- [ ] Register `audit-codebase` in `templates/__init__.py` (`requires=("claude", "github")`).
- [ ] Tests (`test_templates.py`, a new `test_audit_template.py`):
  - every `checks` and `reviewers` combination builds and validates against `PLATFORM_POLICY`;
  - no write tool, gate or `github.*` anywhere in the spec;
  - each route writes `report.md`.
- [ ] Integration (Docker sandbox, `test_scan_flow.py` style):
  - the audit on a seeded fixture repo, with real scanners and fake agents;
  - assert `findings.json`, `report.md` and `route_chosen` (`fix_first` with a planted secret; `clean` on a clean fixture);
  - assert no commit or branch.

## 5. UI
- [ ] `web/src/runs/types.ts`: the `router` node and `route_chosen` event types.
- [ ] `runs/console/step-entries.ts` and `step-list.tsx`:
  - the router as a container: its chosen route nests under it;
  - the line "Routed to fix_first";
  - Output: the route taken, its reason, and the routes not taken shown as Skipped (`StatusBadge`).
- [ ] `runs/graph/spec-graph.ts`: replace the hand-written layout with ELK (`elkjs`, loaded through a dynamic import).
  - Router routes become branches with edges out of the router's box. The taken route is marked; the others are muted and labelled Skipped.
  - Parallel, map and loop move to ELK too.
  - Graph keeps its loading state while the layout runs.
- [ ] `node-status.ts`: a route not taken has the status Skipped.
- [ ] Template gallery: the audit card (lucide icon, "Read-only: no pull request").
- [ ] Vitest:
  - `spec-graph.test.ts` (ELK output for sequence, parallel, map, loop and router);
  - `step-entries.test.ts` (router nesting and Skipped);
  - `templates-view.test.tsx`.
- [ ] Re-baseline the layout screenshots for ELK (`layout.spec.ts`).

## 6. Specs and changelog (implementation PR)
- [ ] tech-stack:
  - "Router (API contract)";
  - the audit template (params, flow, read-only tools);
  - the `FindingsReport` additions;
  - Run console: the router step;
  - the decisions log: router semantics, the "Run graph" row moved to ELK, nesting in parallel branches, and the audit's model params (a departure from "Opus for reviewers").
- [ ] Update the run-graph rows in the plan folders only if the implementation diverges. Otherwise tech-stack is enough.
- [ ] `CHANGELOG.md` `Added` lines. The roadmap 4.6 status is marked done by CI.
