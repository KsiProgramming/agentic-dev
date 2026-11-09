# `subflow` primitive

Roadmap phase: 6.5
Branch: plan/6.5-subflow-primitive

## Context

The mission lists `subflow` among the engine primitives ("Open orchestration"), and the product spec defines it as "call another workflow by id and version" with a workflow ref and an input mapping. It is the last primitive the engine is missing. 5.7 made stored workflows versioned and immutable (`workflow_versions` is append-only) and let a run start from `stored_workflow {id, version}`, so a version is a stable thing to call. 6.1–6.4 are done: the orchestrator and the console's handling of dynamic children set the patterns this phase reuses (scoped writer keys, nested steps in the step list and the run map, a recorded run fixture for the web).

It unblocks 6.6 (composites are saved subflows reused and updated by version, AC-3) and 6.8 (AC-2: a canvas flow with every primitive). The Roadmap's "Next up" line still names Milestone 4, which is done. This phase is the first unplanned one in file order, and the line should be updated in its own PR.

Principles that drive it:
- **One spec, many views (1):** the parent's spec names the child by id and version. The child is never copied into the parent's stored spec, so a version diff of the parent shows only the call changing.
- **Safe by construction (2):** the child's nodes are validated and limited as part of the parent's run, with the same checks they would get inline. A call cycle is refused at validation.
- **Humans approve irreversible actions (3):** a child that publishes carries its own gate, which its own validation already requires. The parent cannot publish a child's writer in this phase.
- **Transparency (6):** the child's steps, cost and events are part of the parent's run and log, shown under the subflow.

## Scope

### In scope

- **Spec:** `{type: "subflow", id, workflow: {id, version}, input?}`. `version` is required. `input` is an optional CEL expression over `last`, `input`, `results` and `artifacts` that gives the child's input. Without it, the child gets the subflow's input (the previous output), as any step does.
- **Resolution at run start, inline execution:** `POST /runs` and rerun resolve every subflow (and the subflows inside it) from the run's workspace. They keep a snapshot in the run (`runs.subflows`, `{"<id>@<version>": spec}`), and the worker compiles the child's root as the subflow's body in the same run. The child shares the parent's run, sandbox, repo, budget, policy limits, event log and artifacts. The subflow's output and `data` are the child's.
- **Ids:** a child's node keeps its id unless the run already has it; then it runs as `<subflow>-<id>` (cut to fit a `NodeId`, numbered when taken), and its references (a reduce's `from`, a publisher's `from_node`) follow. The child's own expressions still name its nodes by its ids. Run ids stay `NodeId`s, so a child's writer gets `agent/<run>/<id>` as any writer does. *(Changed while building, see Decisions.)*
- **Validation:**
  - `subflow_unknown`: the workspace has no such workflow or version.
  - `subflow_cycle`: a workflow on the call path is called again.
  - The child's own issues are found by validating the parent with its children expanded. They are reported on the subflow node, prefixed with "in workflow 'docs' version 3: …". So a child is allowed where its contents are allowed: a child with a gate cannot be called from a map, for example.
  - A subflow is one level of `max_depth`. Limits and budget checks count the expanded tree.
  - A subflow cannot be in an orchestrator's body (`not_allowed_in_orchestrator`).
  - The validator takes a resolver, so it stays free of the database. `POST /workflows/{id}/validate` and stored-version issues resolve from the workspace.
- **Events:** `node_started` for the subflow carries `workflow {id, version, name}`. The child's events follow under their run ids (no extra tag: the console places them from `calls`), then the subflow's `node_completed` / `node_failed` / `node_cancelled`. A gate inside the child pauses the run as usual, and resume continues inside the child (the checkpointer covers it).
- **API:** `runs.subflows` keeps the copies (Alembic `0026_run_subflows`). `GET /runs/{id}` returns `calls`: per subflow id, the workflow it calls and its root as it runs (run ids), and which ids were renamed, so the console draws and nests what ran without mirroring the renaming. *(Changed while building: the plan had the raw copies here.)*
- **Manifest and palette:** a `subflow` manifest (category `flow`, a lucide icon) with no slots. Its `workflow` field uses a new side-panel field `ui:field: workflow_ref`: a combobox of the workspace's workflows (`GET /workflows`, excluding the one being edited) and a version select (`GET /workflows/{id}/versions`, the latest by default).
- **Canvas:** the subflow card reads "Calls docs · version 3", and links to `/workflows/docs?version=3`. When a newer version exists it also says "Version 5 is the latest" in muted text. The child is not drawn or edited inline: it is another workflow, edited on its own page. Live validation shows the child's issues on the subflow card.
- **Run console:**
  - The child's steps nest under the subflow in the step list, with step keys `<subflow>/<node>`. The subflow's line reads "Calls docs · version 3", then the child's progress ("4 of 6 steps").
  - The run map hangs the child's tree off the subflow card, as it does a container's body, from `subflows`.
  - Output shows the child's answer. Input shows the workflow and version, linked to the builder. Usage lists the child's tokens and cost.
- **Fixtures:** `schemas/fixtures/subflow-run.json`, recorded by an engine test, as `orchestrator-run.json` is. Graph-ops and port-check cases for subflow are added to the shared fixtures.
- **Specs and docs:** tech-stack gets a new "Subflow (API contract)" section, plus updates to the validation codes, the run history contract, Run console, Builder canvas and Node manifests. Its decisions log gets new rows. `docs/architecture/overview.md` and `decisions.md` no longer call `subflow` planned. The phase also adds the roadmap `[Plan]` link and a `CHANGELOG.md` entry.

### Out of scope

- A child as a separate run (its own run row, console and history). It stays one run (see Decisions).
- Calling "the latest" version, or a version range. The parent must be edited to move a call to a newer version. 6.6's composites add "updated by version".
- Publishing a subflow as one writer from the parent (`from_node` set to the subflow is a `reference` issue: it is not a writer). A parent's publisher may name a writer of the child by its run id, behind a gate, as any earlier writer; the builder does not offer it. Revisit in 6.6/6.8.
- Drawing or editing the child inline on the parent's canvas, and `wrap` / `extract` (6.6).
- Calling a workflow of another workspace, or a template by id (templates are not stored workflows. "Edit in builder" stores one first).
- Typed ports through a subflow: like a container, a subflow breaks the `port_mismatch` edge. Mismatches inside the child are still checked, and runtime checks still apply.
- Audit actions of its own: the run's existing entries cover it.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| How a child runs | Inline in the parent's run: its root compiled as the subflow's body | Sandbox, repo, budget, limits, events, resume and the console all work as they already do. A separate child run would need run linkage, cost roll-up and cancel propagation across runs. Chosen in the interview. |
| Version | Required, pinned in the spec | The Done when is "by id + version". Runs are reproducible, and a child's new version never changes a parent silently. Moving a call to a newer version is a visible parent edit. |
| When it is resolved | At `POST /runs` / rerun, snapshotted in `runs.subflows` | The worker needs no workflow store, the run is self-contained for resume and the console, and versions are immutable, so a snapshot cannot go stale. |
| Where the snapshot lives | A new `runs.subflows` JSONB column, with `runs.spec` unchanged | `runs.spec` stays the parent as written (the console's map, search on `spec->>'name'`). Children are keyed `<id>@<version>`, so a child called twice is stored once. |
| Validation of the child | Validate the parent with children expanded, issues reported on the subflow node | One validator. A child is allowed exactly where its contents are allowed, so there are no special rules per container. The message names the child and version, so the fix is clear. |
| Validator and the database | `validate_workflow` takes a `resolve(id, version)` callable | It keeps the validator pure and testable, as `priced` already is. The API passes a workspace-backed resolver. |
| Node id clashes | Kept, renamed `<subflow>-<id>` only when the run already has the id; the child's expressions see its own ids (`expression_views`) | **Changed while building.** Scoping every id (`<subflow>/<node>`) breaks the `NodeId` pattern that branches, worktrees, tool routing and approvals check. Requiring unique ids instead refused almost every call: root sequences are `main`, and every blank workflow starts with `sequence_1` and `agent_1`. |
| What the console gets | `calls` on `GET /runs/{id}`: each call's root as it runs | **Changed while building.** The console draws and nests what ran, with its run ids, and never mirrors the renaming. |
| Structure check of a calling spec | Skipped when the spec is parsed; run on the expanded tree (`expand_workflow`, `validate_workflow`) | What a caller reads or publishes may come from a call, so it can only be checked once the calls are resolved. Every path that runs a spec expands it first, and an unresolved call never compiles. |
| Artifacts | One namespace for the run: the child reads and writes the run's artifacts | The main use is a child producing `findings.json` or `report.md` for the parent. Conflicts and unknown reads are caught on the expanded tree. |
| Depth | A subflow is one level of `max_depth`; calls are resolved at most `max_depth + 1` deep | Bounds nesting of calls (mission "Safe by construction") and keeps a chain of calls from growing the tree. Cycles are a separate, earlier check, by workflow id. |
| Order of work | Contract, then engine, then web | Chosen in the interview: the spec, validation codes and tech-stack contract settle first, so the engine and web build to a fixed shape. |

## Open questions

- None blocking. To confirm while building: the lucide icon name for the manifest (`workflow` is the candidate), and whether "Version N is the latest" on the canvas card needs one `GET /workflows/{id}/versions` per subflow or can use the list's `latest_version` (preferred: `GET /workflows` already returns it).
