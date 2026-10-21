# Plan: Compile spec → LangGraph graph for `sequence` of `agent` nodes

Order: state model, then compiler, then runner, then docs. CI stays green after each group.

## 1. Dependency + state model
- [ ] `packages/engine/pyproject.toml`: add `langgraph` (current stable major), then run `uv lock`.
- [ ] `packages/engine/src/agentic_engine/graph/state.py`:
  - `RunState` `TypedDict`: `input: str`, `last_text: str`, `results: Annotated[dict[str, AgentNodeResult], merge]`, `order: Annotated[list[str], operator.add]`.
  - `WorkflowRunResult` (frozen Pydantic): `status`, `text`, `results` (in run order), `usage` (summed), `stopped_at: str | None`.
- [ ] Reuse `_total_usage` from `agentic_engine.agent` for summing usage. Make it public (`total_usage`) rather than copy it.
- [ ] `packages/engine/tests/test_graph_state.py`: the reducers merge results and append order; `WorkflowRunResult` round-trips through JSON.

## 2. Compiler
- [ ] `packages/engine/src/agentic_engine/graph/compile.py`:
  - `agent_nodes(root: Node) -> list[AgentNode]`: flatten sequences depth first (built on `iter_nodes`).
  - `compile_workflow(spec: WorkflowSpec, runtime: AgentRuntime)`:
    - One `StateGraph(RunState)` node per agent node, named by its id.
    - Each node function calls `run_agent_node(node, runtime, input)`, where `input` is `state["input"]` for the first node and `state["last_text"]` after that.
    - Returns `results`, `order` and `last_text` updates.
    - Edges: `START` → first node. Between nodes, a conditional edge goes to the next node if the status is `completed`, otherwise to `END`. Last node → `END`.
  - Raises `CompileError` for a node type the compiler does not support yet. Unreachable today; it keeps the `match` exhaustive for pyright when new primitives join the `Node` union.
- [ ] `agentic_engine/graph/__init__.py`: re-export `compile_workflow`, `run_workflow`, `RunState`, `WorkflowRunResult`, `CompileError`.
- [ ] `packages/engine/tests/test_compile.py`:
  - The graph for `two-step-sequence.json` has nodes `writer` and `reviewer` (plus LangGraph's start/end).
  - `nested-sequence.json` flattens to `planner`, `implementer`, `tester` in that order.
  - `single-agent.json` compiles to one node.

## 3. Runner + Done-when
- [ ] `packages/engine/src/agentic_engine/graph/run.py`: `async run_workflow(spec, runtime, input="") -> WorkflowRunResult`:
  - Compiles, then `ainvoke`s with the initial state.
  - Builds the result: status from the last result, `stopped_at` set when a node did not complete.
- [ ] `packages/engine/tests/test_run_workflow.py`:
  - **Done when**: `two-step-sequence.json` runs on `FakeRuntime`:
    - Status is `completed` and the order is `["writer", "reviewer"]`.
    - `FakeRuntime.requests[1].input` equals the writer's output text.
    - `reviewer`'s instructions do not contain the writer's output.
    - Usage is summed across both nodes.
  - Nested sequence runs all three agents in order, each receiving the previous output.
  - Single-agent root runs one node.
  - A scripted `failed` on `writer` gives run status `failed`, `stopped_at == "writer"`, and `reviewer` is never requested.
  - Cancelling the task running `run_workflow` while `writer` is in a `Delay` cancels the fake run promptly and does not start `reviewer`.

## 4. Docs
- [ ] README: a short "Engine" section showing `run_workflow(spec, FakeRuntime(), input)` and how sequences flatten.
- [ ] CHANGELOG: add a 0.4 entry.
