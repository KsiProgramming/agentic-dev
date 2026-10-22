# Plan: `loop` primitive + CEL expressions

The CEL module is built first, then the spec, then the engine. Each group leaves the project working and CI green.

## 1. CEL expression module
- [x] Add `cel-python` to `packages/engine/pyproject.toml` and run `uv lock`. Context7 has no index for `cel-python`, so the API was read from the installed package (0.5.0).
- [x] `packages/engine/src/agentic_engine/expr.py`:
  - `ExpressionError(ValueError)` with `source`, `message` and `column` when the error has one.
  - `CompiledCondition` wraps the `celpy` program and keeps its source.
  - `compile_condition(source: str) -> CompiledCondition`:
    - It enforces a length limit of 1,000 characters.
    - It parses the expression.
    - `celpy` has no declared-type checker. Instead, the expression tree is walked, and unknown variables and functions are rejected (variables bound by macros such as `exists(k, …)` are allowed).
    - It raises `ExpressionError` on any error.
  - `CompiledCondition.evaluate(*, last, iteration, results) -> bool` (a method rather than a free function):
    - It converts the values with `json_to_cel`.
    - It raises `ExpressionError` on an evaluation error or a non-bool result.
    - It trims the activation dump that `celpy` appends to some messages.
  - No custom functions are registered. The docstring explains the sandbox. `matches` uses RE2, which runs in linear time.
- [x] `packages/engine/tests/test_expr.py`:
  - true and false results
  - `last.contains`
  - `iteration >= 2`
  - `results.review.status == "completed"`
  - `has(results.review.data)`
  - macros
  - `matches`
  - syntax error with column
  - unknown variable
  - unknown function (`lowerAscii`)
  - non-bool result
  - too long
  - evaluation error (missing key)

## 2. Spec: `LoopNode`
- [x] `spec/models.py`:
  - Add `LoopNode` (`type: "loop"`, `id`, `body: Node`, `until: NonEmptyStr`, `max_iterations: int` with `ge=1, le=MAX_LOOP_ITERATIONS`) to the `Node` union.
  - `MAX_LOOP_ITERATIONS = 5`, with a comment that 2.2 makes it configurable.
  - `iter_nodes` yields `body` at `path.body`. `node_tools(LoopNode)` returns `[]`.
- [x] `WorkflowSpec` validator `_loops_can_run` calls `loop_errors(root)`, merging the two planned validators. For each problem it reports `loop 'x' at <path>: invalid until: …`, or `<kind> 'y' at <path> cannot be inside a loop yet`, where the kind is gate, writer, publisher or loop.
- [x] `publish_gate_errors` skips loop containers. `writer_node_ids` is unchanged.
- [x] Re-export the JSON Schema, the OpenAPI spec and the web client.
- [x] Fixtures:
  - `valid/review-loop.json`
  - `invalid/loop-bad-cel.json`
  - `invalid/loop-too-many-iterations.json`
  - `invalid/loop-with-gate.json`
  - `invalid/loop-with-writer.json`
  - `invalid/nested-loop.json`
- [x] `test_spec.py`: the expected rejections name the node and path, and the schema assertion includes `LoopNode` with `max_iterations` from 1 to 5.

## 3. Engine: compile and run loops
- [x] `graph/state.py`:
  - Add `iterations: Annotated[dict[str, int], merge_counts]` to `RunState` and `RunUpdate`.
  - Add `usage: Annotated[list[Usage], operator.add]`. This was not planned: `results` keeps only each node's latest result, so a loop's earlier iterations were missing from the run's usage. `Usage` joins `CHECKPOINT_TYPES`.
- [x] `events.py`: add `LOOP_ITERATION_STARTED` and `LOOP_CONDITION_EVALUATED`.
- [x] `graph/compile.py`: a recursive builder, `add(node, then) -> entry`, wires each node to what follows it. It keeps the "continue only if completed" routing.
  - Loop:
    - The entry node `<loop.id>` emits `node_started` on the first iteration, then increments `iterations` and emits `loop_iteration_started`.
    - The check node is `<loop.id>.check`. `NodeId` forbids `.`, and LangGraph only reserves `:` and `|`.
      - It evaluates `until` and emits `loop_condition_evaluated`.
      - It routes back to the entry until the loop has a result.
      - When the loop stops, it records the result and emits `node_completed(loop)` with `stop_reason` and `iterations`.
    - An `ExpressionError` gives `node_failed(loop)`, and the run ends with `stopped_at` set to the loop.
  - `step_nodes` walks into loop bodies, and the docstring is updated.
- [x] `graph/run.py`:
  - Pass `recursion_limit(spec)` in the config for run and resume. This LangGraph version's default is 10,007, not 25, so the computed limit has no floor and acts as a tight runtime backstop.
  - `completed_nodes` is deduplicated.
  - Usage comes from `RunState.usage`, falling back to `results` for checkpoints saved before 1.9.
- [x] `packages/engine/tests/test_loop.py` (fake runtime, `InMemorySaver`). It covers:
  - stop on condition
  - stop at max
  - feedback between iterations
  - event order and `seq`
  - a failing body node
  - a CEL runtime error
  - `results` and `iteration` in a condition
  - usage across iterations
  - the recursion limit with 5 iterations of a 3-step body
  - resume mid-loop in iteration 2

## 4. Docs
- [x] README: a "Loops" section, plus the node list and the Engine section.
- [x] CHANGELOG entry (Added, plus Fixed for usage).
- [x] Tick this plan.
