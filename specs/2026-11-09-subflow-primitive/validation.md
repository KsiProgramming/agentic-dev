# Validation: `subflow` primitive

## Done when (from roadmap)
> One workflow calls another by id + version

Made checkable: a stored workflow with a `subflow` node naming another stored workflow by id and version runs end to end. The child's steps run inside the parent's run and show under the subflow in the console and the run map. A new version of the child does not change what the parent calls, and a missing version or a call cycle is refused before the run starts.

## Automated checks

### Engine (`uv run pytest packages/engine`)
- [ ] Spec: a valid subflow parses. A missing `version`, a `version` < 1, or an `input` that is not CEL is refused. The JSON Schema export and `node-types.json` are fresh (the stale-fixture tests fail otherwise).
- [ ] Validation:
  - `subflow_unknown` for an unknown workflow and for an unknown version;
  - `subflow_cycle` for a self-call and for A → B → A;
  - `policy_limit` on depth when a subflow takes nesting past `max_depth`;
  - a child with a gate called from a map refused on the subflow node with the "in workflow '…' version N:" prefix;
  - a child's `unknown_tool` reported on the subflow;
  - the same node id in parent and child allowed;
  - `not_allowed_in_orchestrator` for a subflow in a worker;
  - a parent reading an artifact the child writes accepted, and one the child never writes `artifact_unknown`.
- [ ] Ops and ports: the subflow cases in `schemas/fixtures/graph-ops.json` and `port-checks.json` pass in the engine (and in the web, below).
- [ ] Run on the fake runtime:
  - parent `a → call → b` with child `x → y` runs `a, x, y, b` in order;
  - child events tagged `subflow: ["call"]`;
  - the subflow's output equals `y`'s;
  - `input` CEL maps what the child gets;
  - a child gate pauses the run and an approval resumes inside the child;
  - a failure in `y` fails `call` and the run, naming `y`;
  - a child writer commits on `agent/<run>/call.<node>`.
- [ ] Resume: killing the worker after `x` completes and restarting it resumes at `y`, not at `a` or `x` (AC-8).
- [ ] `test_subflow_fixture.py` writes and checks `schemas/fixtures/subflow-run.json`.

### Store and API (Testcontainers Postgres)
- [ ] Alembic upgrades and downgrades `0026_run_subflows` cleanly.
- [ ] `POST /runs` with `stored_workflow` for a parent calling `child@1`: `runs.subflows` holds `child@1`'s spec. Then `PATCH` the child to version 2: a new run of the parent still runs version 1.
- [ ] `POST /runs` for a parent calling a version that does not exist returns `422` with a `subflow_unknown` issue, and no run is created.
- [ ] Rerun copies `runs.subflows` unchanged. `GET /runs/{id}` returns `subflows`.
- [ ] `POST /workflows/{id}/validate` with a workspace resolves subflows from it. A stored version with a cycle is saved, with `valid: false` and the `subflow_cycle` issue.

### Web (`cd web && pnpm lint && pnpm typecheck && pnpm test`)
- [ ] `workflow_ref` field:
  - lists the workspace's other workflows;
  - defaults to the latest version;
  - changing either one is one `setParam` edit;
  - read-only on an older version;
  - has loading, empty and error with Retry states.
- [ ] Canvas card: "Calls <name> · version N" linking to the right version, "Version M is the latest" only when newer, and a child's issue shown on the card.
- [ ] `ops.test.ts` / `ports.test.ts` pass the shared fixture's subflow cases.
- [ ] Timeline from `subflow-run.json`:
  - child steps nested under the subflow with keys `call/x`, `call/y`;
  - the subflow's one-liner at each stage;
  - its cost equals the sum of its child's steps;
  - runs without subflows are unchanged (existing tests green).
- [ ] Run map: the child's chain hangs off the subflow card, and the accessible names contain the visible text.
- [ ] Child names, answers and errors render as text (a `<b>` in a child agent's answer is not HTML).

### End to end (`cd web && pnpm test:e2e`)
- [ ] `subflow.spec.ts`: create a child and a parent workflow, add a subflow on the canvas with the picker, save, and run the parent. The console shows the child's steps under the subflow, and the Graph tab shows the child's chain.
- [ ] `a11y.spec.ts` (axe) and `layout.spec.ts` (screenshots) pass for the builder and the console with a subflow at 375, 768 and 1440 px, light and dark.

## Manual checks
- [ ] Look at the builder (subflow card, side panel picker) and the console (nested steps, run map) at 375 and 1440 px, in light and dark. Check there is no horizontal page scroll.

## Merge criteria
- [ ] All automated checks above pass locally (CI minutes are limited, so CI runs on the PR but is not watched step by step).
- [ ] `specs/tech-stack.md` (Subflow contract, validation codes, run history `subflows`, Node manifests, Run console, Builder canvas, decisions log), the roadmap `[Plan]` link, `docs/architecture/*` and `CHANGELOG.md` are updated in the same PR.
- [ ] Colours come from tokens only. No JSON in a table cell. Child content is rendered as text or sanitised Markdown. Values go through `@/components/display`.
- [ ] No secret or child spec content in audit entries or logs beyond what a run already logs.
- [ ] CI marks the phase done on the PR branch.
