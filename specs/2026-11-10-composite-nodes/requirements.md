# `wrap` / `extract` operations; composite nodes (draft → published)

Roadmap phase: 6.6
Branch: plan/6.6-composite-nodes

## Context

The mission promises that users extend the primitives with **composite nodes (no code)**, and that a tech lead reuses workflows across the team by "publishing templates and composite nodes". The product spec describes a composite as "a saved sub-flow with typed inputs and outputs" that "appears in the palette like a primitive", made by selecting nodes and choosing "Make reusable node". It also lists `wrap` and `extract` among the graph operations. AC-3: *a composite node saved in one workflow can be used in another and is updated by version.*

Everything 6.6 builds on is done:
- 5.1 graph operations and immutable versions;
- 5.3 manifests and the palette served by `GET /node-types`;
- 5.7 history, diff, restore and running any version;
- 6.5 `subflow`, which calls a stored workflow by pinned id and version, inline in the caller's run, with validation on the expanded tree, `calls` for the console, and the side panel's `workflow_ref` field.

So a composite does not need a new runtime. **A composite is a stored workflow whose versions are published**, and using one is a `subflow` pinned to a published version. This phase adds what 6.5 left out: a way to make one from a selection (`extract`), a draft → published status, a palette section for the workspace's composites, typed inputs and outputs at the workflow level, and a visible "update to version N" on callers. It also adds `wrap`, the other missing structural operation.

It unblocks 6.7 and 6.8 (AC-2: a canvas flow built with every primitive) and 9.x (the Architect saves the composites it invents as drafts, for a human to publish).

Principles that drive it:
- **One spec, many views (1):** `wrap` and `extract` are graph operations, so the canvas and (later) the Architect use them, and each is one undoable edit with a diff. A caller's spec names the composite by id and version and never holds a copy of it.
- **Open, but safe by construction (2):** a composite is checked where it is used, on the expanded tree (6.5). A caller moves to a new version only through a visible edit, never silently.
- **Transparency (6):** publishing and extracting are audited.
- **Small, verifiable steps (7):** the engine runtime does not change. Only the spec (workflow-level port schemas), the ops, the store and the builder change.

Tech-stack choices it follows: graph ops in `agentic_engine.spec.ops` with the browser mirror `@/workflows/ops` kept alike by `schemas/fixtures/graph-ops.json`; append-only versions (`workflow_versions`); manifests served by `GET /node-types`; the subflow contract; and the builder rules (every edit is a menu item, no drag).

## Scope

### In scope

- **Draft → published.**
  - `POST /workflows/{id}/publish {version}` publishes a stored version. This is recorded in a new append-only `workflow_publications` table (Alembic `0027_workflow_publications`), because `workflow_versions` refuses `UPDATE`.
  - A version that has issues cannot be published (`422`, with the issues). Publishing the same version twice is `409 already_published`.
  - A workflow with at least one published version is a **composite**. Its unpublished versions are **drafts**.
  - `GET /workflows` and `GET /workflows/{id}` gain `published_version` (the latest published version, or `null`). `GET /workflows/{id}/versions` gains `published_at` for each version.
- **Calls to drafts.**
  - Once a workflow is a composite, a subflow that calls one of its unpublished versions gets a new issue, `subflow_unpublished`, on `<path>.workflow`. `POST /runs` refuses it, as it does any issue.
  - A workflow that has never been published can still be called at any version, as in 6.5, so existing callers keep working.
- **Typed inputs and outputs.**
  - The workflow spec takes optional `input_schema` and `output_schema`, with the same rules as a node's (4.2).
  - A subflow's ports are its called workflow's schemas. `port_mismatch` checks through a subflow, so a subflow no longer breaks the edge when the called workflow is typed. At runtime the subflow's input and output are checked at its boundary.
  - Both are set in the builder's Workflow panel ("Inputs and outputs", advanced).
- **Palette: "Workspace nodes".**
  - `GET /node-types?workspace_id=` adds one manifest per composite after the primitives: `kind: subflow`, category `workspace`, the composite's name and description, icon `workflow`, a `composite: {workflow_id, version}` field, and a `default` subflow already pinned to the latest published version.
  - Without `workspace_id`, the answer is the primitives, as today.
  - The palette shows a "Workspace nodes" group, with no web list of composites (5.3's rule). The workflow being edited is left out.
- **`extract` operation.**
  - `extract {node_ids, subflow_id, workflow: {id, name, description?}}`. The nodes must be consecutive steps of one sequence, or a single node anywhere a step can go.
  - They become the root of a new workflow (a sequence when there are several, the node itself when there is one). In their place is a `subflow` with id `subflow_id`, calling that workflow's version 1.
  - It is refused (`invalid_extract`, naming the node) when a reference crosses the boundary in either direction: a reduce's `from`, a publisher's `from_node`, or a CEL `results.<id>` that names an extracted node from outside, or an outside node from inside.
  - It is also refused for the root, or when the selection is not contiguous.
  - The workflow-level `input` and the port schemas of the new workflow are taken from the first and last extracted nodes when they are typed.
  - **Transaction:** `PATCH /workflows/{id}` with an `extract` creates the new workflow (version 1, a draft) and the caller's new version in one database transaction. `409 workflow_exists` refuses the whole batch.
  - The browser's `applyOps` mirrors the spec side. The new document is returned so the canvas can show it before Save.
  - At most one `extract` per batch.
- **`wrap` operation.**
  - `wrap {node_ids, with: {type, id, …params}, sequence_id?}` puts consecutive steps of one sequence (or one node) into a new container in their place:
    - `sequence`: the steps.
    - `parallel`: each node is a branch, at least 2 nodes.
    - `loop` or `map`: the body is the one node, or a new sequence `sequence_id` when there are several.
  - The container's other parameters come from `with`, else from its manifest's `default`. Its id must be new.
  - It is refused when the result breaks a container rule the ops already enforce (`invalid_placement`, `invalid_wrap`). Rules that validation catches (a gate in a loop) are left to validation, as with any edit.
- **Update by version.**
  - A subflow card that calls a composite older than its latest published version reads "Calls Security review · version 2 · version 3 is published", and its menu has **Update to version 3**: one `setParam` on `workflow.version`, then one undo step. With Compare, the diff shows the call changing.
  - The composite's builder page lists **Used by**: the workspace's workflows whose latest version calls it, with the version each one calls (`GET /workflows/{id}/callers`). Each is a link to that caller.
  - Callers are never updated automatically.
- **Builder.**
  - A card's "⋯" menu gains **Extract to composite…** and **Wrap in…** (sequence, parallel, loop, map). Both open a dialog that picks the range ("from this step through …", a select of the later steps in the same sequence) and, for extract, the name, id (slug as in 5.8) and description.
  - A blocked choice is disabled, with its reason, as in 5.6.
  - The header gets **Publish version N** on a valid latest version with no unsaved edits. It asks for confirmation in a dialog that names the callers it does not change.
  - The status line reads "Draft" or "Published version N".
  - History marks published versions with a neutral "Published" badge.
  - The Workflows list shows a "Composite" badge and the published version.
- **Audit:** `workflow.published` (`workflow_id`, `version`). An extract writes `workflow.created` for the composite, with `extracted_from: {workflow_id, version}`, and `workflow.updated` for the caller, whose `ops` counts include `extract`.
- **Fixtures:** `graph-ops.json` gets `wrap` and `extract` cases, each refusal included, run by the engine and the web. `port-checks.json` gets cases for typed subflows. `node-types.json` stays the primitives only.
- **Specs and docs:**
  - tech-stack: the graph-ops contract (wrap, extract, codes), a new "Composites (API contract)" section, the subflow contract (publication rule, ports), node manifests (category `workspace`, `composite`), Builder canvas, validation codes, the database row, and decisions-log rows.
  - roadmap: a `[Plan]` link.
  - `docs/architecture/business-flows.md`: no longer "planned".
  - `CHANGELOG.md`.

### Out of scope

- A separate `node_types` table and a `{type: "composite"}` node. A composite is a stored workflow called by `subflow` (see Decisions).
- Automatic or bulk update of callers, version ranges, and "always the latest". Each caller moves by its own edit.
- Unpublishing, deprecating, deleting or renaming a composite. Published versions are immutable, like versions.
- Sharing composites across workspaces, and promoting a workflow to a template (ideas.md, 9.9).
- Composite parameters beyond its input: a composite is configured through its `input`, not exposed inner parameters.
- Drawing or editing a composite inline on the caller's canvas. It is edited on its own page, as in 6.5.
- Multi-select on the canvas or drag. The range is picked in a dialog, so every edit stays a keyboard-reachable menu item.
- `wrap` into an orchestrator, a router or a gate. `extract` from inside an orchestrator's worker, since a subflow is not allowed there (6.5).
- The Architect creating draft composites (9.3). This phase only makes drafts possible.
- Publishing a subflow as one writer from the caller (still a `reference` issue, as in 6.5).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| What a composite is | A stored workflow with published versions, used through a `subflow` pinned to a published version | Chosen in the interview. 6.5 already resolves, validates, runs, resumes and shows a called workflow. A second node type would duplicate all of it. The product spec's `composite:security-review@2` is a `subflow` with `workflow: {id, version}`. |
| Where "published" lives | A new append-only `workflow_publications` table, not a column on `workflow_versions` | `workflow_versions` refuses `UPDATE` by trigger (5.1). Publishing is an event with a time, which is what an append-only row records. |
| Drafts and existing callers | `subflow_unpublished` only for workflows that have been published at least once | A composite's drafts must not leak into callers, but 6.5's calls to plain workflows keep working with no migration. |
| How the palette learns of composites | `GET /node-types?workspace_id=` adds a manifest for each composite | It keeps 5.3's rule that the web holds no list of kinds. The product spec already puts composites in `GET /node-types`. |
| `extract` across two workflows | An op in the batch, which the API applies with the creation of the new workflow in one transaction | It is one graph operation, as the product spec says (one undo step, one diff on the caller). The pure op returns the new document and the store writes both, or neither. |
| Picking a range without multi-select | A dialog from the card's menu: "from this step through …" | It keeps "every edit is a menu item, no drag" (5.2) and works from the keyboard and at 375 px. |
| Typed composites | Workflow-level `input_schema` / `output_schema` used as the subflow's ports | "Typed inputs and outputs" is in the product spec's definition. Without them a composite breaks every port edge it sits on. |
| Order of work | Contract, then engine and fixtures, then store and API, then web, in one PR | Chosen in the interview, as in 6.5: the shape is fixed before the code. |

## Open questions

- None blocking. To confirm while building:
  - How the CEL boundary check for `extract` finds `results.<id>`: a parse of each expression's identifiers is preferred over a text scan.
  - Whether "Used by" can come from `workflow_versions` with a JSONB path query, or needs a small `workflow_calls` index table written with each version.
