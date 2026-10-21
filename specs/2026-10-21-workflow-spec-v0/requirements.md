# Workflow spec v0

Roadmap phase: 0.2
Branch: plan/0.2-workflow-spec-v0

## Context
Mission principle 1 (*one spec, many views*) makes the versioned workflow spec the single source of truth. The canvas, Architect, monitor and engine all read or change it. This phase defines the first, smallest version of that spec. It is built as Pydantic v2 models, which the tech stack picks for the workflow spec, and exported as JSON Schema, which the tech stack uses to share contracts between backend and frontend.

It depends only on 0.1 (repo scaffold, done). It unblocks:
- 0.3: the fake runtime needs an agent node's params to run.
- 0.4: compiles `sequence` of `agent` into LangGraph.
- 0.6: `POST /runs` takes a spec as its body.

The v0 shape must let later primitives (`tool`, `gate`, `loop`, `map`, …) be added as new members of a union. Adding one should not break existing specs.

## Scope
### In scope
- `agentic_engine.spec` module with Pydantic v2 models:
  - `WorkflowSpec` envelope: `spec_version: Literal["0"]`, `id`, `name`, optional `description`, and one `root` node.
  - `Node`: a discriminated union on `type`, with members `AgentNode` and `SequenceNode` only.
  - `AgentNode`: `id`, `role`, `instructions`, optional `provider` (`"claude"` only for now), optional `model`, and `tools: list[str]` (default empty). Tool names are plain strings. They have no meaning until 1.2/1.6.
  - `SequenceNode`: `id`, `steps: list[Node]`, which must not be empty. Sequences may nest.
- Spec-level checks:
  - `extra="forbid"` on every model, so typos and unknown keys are rejected.
  - Node ids are unique across the whole tree.
  - Node ids use a safe slug pattern (`^[a-z][a-z0-9_-]{0,62}$`). Ids are later used in branch names `agent/<run>/<node>`.
  - `sequence.steps` has at least one step.
  - Non-empty `role` and `instructions` on agents.
- JSON Schema export: `scripts/export_workflow_schema.py` writes the committed `schemas/workflow-spec.v0.json`.
- A CI step that re-exports the schema and fails if the committed `schemas/workflow-spec.v0.json` is out of date, as the API contract job does for OpenAPI.
- Sample valid and invalid spec fixtures, plus fixture-driven pytest.

### Out of scope
- Other primitives: `tool` (1.6), `gate` (1.7), `loop` (1.9), `map`/`reduce` (1.10), `parallel` (3.1), `router` (3.6), `orchestrator` (5.1), `subflow` (5.5).
- Typed input/output ports and edge validation (3.2).
- CEL expressions (1.9).
- Policy limits such as depth, budget and iterations (2.2–2.4). The validation endpoint is 2.4.
- Graph operations and stored, immutable versions (4.1). v0 is only the document shape and is not persisted.
- TypeScript types generated from the schema for `web/`. The canvas needs them in 4.2.
- Copilot as a `provider` value (7.2).

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Where the models live | `packages/engine/src/agentic_engine/spec/` | The engine compiles the spec (0.4). The API can import it from there. A separate package is not worth the extra scaffolding yet. |
| Source of truth | Pydantic models; JSON Schema is generated from them | Tech stack: Pydantic v2 for the spec, exported as JSON Schema. |
| Polymorphism | `Annotated[AgentNode \| SequenceNode, Field(discriminator="type")]` | Gives clear error paths and a `oneOf` + `discriminator` in the schema. New primitives are added as new union members. |
| Versioning | `spec_version: Literal["0"]` on the envelope | Specs are versioned and immutable later (4.1). An explicit version lets us migrate them. |
| Strictness | `extra="forbid"`, unique ids, id slug pattern | Bad specs fail early with an actionable error. Supports principle 2 (*safe by construction*). |
| `provider` | Optional, `Literal["claude"]` | Only Claude exists before 7.x. Leaving it unset means "use the workspace default". |
| Schema location | `schemas/workflow-spec.v0.json` at repo root | Neutral location that both the Python and TS sides can consume. |
| Schema freshness | CI step re-exports the schema and fails on `git diff` | Without it, a model change could leave the committed schema stale, and nothing would catch it until the canvas starts using the schema in 4.2. It costs about one CI step. |
| Build order | Test first | Write fixtures and failing tests first, then the models. The "Done when" check is the first thing written. |

## Open questions
- None
