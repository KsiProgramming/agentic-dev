# Compile spec → LangGraph graph for `sequence` of `agent` nodes

Roadmap phase: 0.4
Branch: plan/0.4-compile-sequence-langgraph

## Context
The tech stack picks LangGraph as the engine: "the workflow spec compiles to a LangGraph graph. Primitives map to nodes or subgraphs." This phase is the first compile step. It turns a `WorkflowSpec` (0.2) made of `sequence` and `agent` nodes into a runnable LangGraph graph. Each agent node runs through `run_agent_node` (0.3), the seam that 0.3 left for this phase.

It depends on 0.2 (spec models) and 0.3 (`AgentRuntime`, `FakeRuntime`, `run_agent_node`). Both are done. It unblocks:
- 0.5: the engine writes `run_events` while the compiled graph runs.
- 0.6: `POST /runs` starts a compiled graph.
- 0.7: the same graph runs on the Claude adapter, with no compiler changes.
- 1.3: the Postgres checkpointer attaches to this graph.
- Later primitives (`loop`, `map`, `gate`, …) are added to the same compiler.

Principles that apply:
- **One spec, many views (1)**: the spec is the input. The graph is derived from it and is never edited or stored.
- **Repo content is data (5)**: a node's output reaches the next node as `AgentRequest.input`, never merged into `instructions`.
- **Transparency (6)**: the run state keeps every node's full `AgentNodeResult` (events, usage, tool calls), ready for 0.5.
- **Small, verifiable steps (7)**: no persistence, API or real provider in this phase.

## Scope
### In scope
- Add the `langgraph` dependency to `agentic-engine`.
- `RunState`: a typed LangGraph state with:
  - the run input;
  - the last output text;
  - the per-node `AgentNodeResult`s, keyed by node id;
  - the order in which nodes ran.
- `compile_workflow(spec, runtime) -> CompiledGraph`:
  - Flat and nested `sequence`s are flattened, depth first, to a linear chain of agent nodes. `sequence` nodes do not become graph nodes.
  - Each LangGraph node is named after its spec node id (already unique and slug-safe from 0.2).
  - Each node wraps `run_agent_node`. The first node gets the run input; each later node gets the previous node's output text.
  - A node that ends `failed` or `cancelled` stops the run (conditional edge to `END`). Later nodes do not run.
  - A single `agent` root compiles to a one-node graph.
- `run_workflow(spec, runtime, input) -> WorkflowRunResult`:
  - Compiles and invokes the graph (`ainvoke`).
  - Returns the overall status (`completed` | `failed` | `cancelled`), the final text, the results in run order and the summed usage.
  - Cancelling the calling task cancels the in-flight agent run (via `run_agent_node`'s existing `finally`).

### Out of scope
- Persisting events in `run_events` (0.5).
- HTTP endpoints and SSE (0.6).
- The Claude adapter (0.7).
- The checkpointer and resume (1.3).
- One LangGraph subgraph per `sequence`. Container nodes as subgraphs come with `map`/`parallel`/`loop` (1.9, 1.10, 3.1).
- Typed ports and input mapping between nodes (3.2). For now, text flows from one node to the next.
- Policy limits, retries and budget (2.2, 2.3).
- A demo CLI. Tests are the demo for this phase.

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Graph shape | Flatten nested sequences to one linear chain | Smallest graph that runs nested specs correctly. Subgraphs wait for container primitives that need them. |
| Node naming | LangGraph node name = spec node id | The ids are unique and validated in 0.2. Events (0.5) and the monitor (0.8) can map graph nodes back to the spec with no lookup table. |
| Data flow | Previous node's `text` → next node's `AgentRequest.input` | Keeps repo/agent output as data (principle 5). Typed ports come in 3.2. |
| Failure handling | `failed`/`cancelled` result ends the run through a conditional edge; no exception | Matches 0.3's "results, not exceptions". The run result reports which node stopped it. |
| State | `TypedDict` with reducers for `results` and `order` | LangGraph's native state style. It stays checkpointable for 1.3 because `AgentNodeResult` is a Pydantic model. |
| Runtime binding | The runtime is passed to `compile_workflow` and captured by the node functions | Simple and testable. Per-node provider selection (7.3) can swap this for a resolver later. |
| Ordering of work | State model → compiler → runner → docs | User choice. Each group leaves CI green. |

## Open questions
- None
