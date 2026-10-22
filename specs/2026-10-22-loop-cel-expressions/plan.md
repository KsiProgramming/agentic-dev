# Plan: `loop` primitive + CEL expressions

The CEL module is built first, then the spec, then the engine. Each group leaves the project working and CI green.

## 1. CEL expression module
- [ ] Add `cel-python` to `packages/engine/pyproject.toml` and run `uv lock`. Check the current `celpy` API with ctx7 before writing the code.
- [ ] `packages/engine/src/agentic_engine/expr.py`:
  - `ExpressionError(ValueError)` with `source`, `message` and `position` when the error has one.
  - `CompiledCondition` wraps the `celpy` program and keeps its source.
  - `compile_condition(source: str) -> CompiledCondition`:
    - It enforces a length limit of 1,000 characters.
    - It parses the expression with a declared environment (`last: string`, `iteration: int`, `results: map(string, dyn)`).
    - It raises `ExpressionError` on any error.
  - `evaluate(cond, *, last, iteration, results) -> bool`:
    - It converts the Python values into CEL values.
    - It raises `ExpressionError` on an evaluation error or a non-bool result.
  - No custom functions are registered. Write a docstring that explains the sandbox.
- [ ] `packages/engine/tests/test_expr.py`:
  - true and false results
  - `last.contains`
  - `iteration >= 2`
  - `results.review.status == "completed"`
  - `has(results.review.data)`
  - syntax error with position
  - unknown variable
  - non-bool result
  - too long
  - evaluation error (missing key)

## 2. Spec: `LoopNode`
- [ ] `spec/models.py`:
  - Add `LoopNode` (`type: "loop"`, `id`, `body: Node`, `until: NonEmptyStr`, `max_iterations: int` with `ge=1, le=MAX_LOOP_ITERATIONS`) to the `Node` union.
  - Set `MAX_LOOP_ITERATIONS = 5` and add a comment that 2.2 makes it configurable.
  - `iter_nodes` yields `body` at `path.body`. `node_tools(LoopNode)` returns `[]`.
- [ ] `WorkflowSpec` validators:
  - `_loop_conditions` compiles each `until` and reports `node 'x' at root.steps[1]: invalid until: …`.
  - `_loop_body_rules` rejects a gate, a writer, a publisher or a nested loop under a loop body, and names the offending node.
- [ ] Check that `publish_gate_errors` and `writer_node_ids` still behave the same. Loops cannot contain writers, so nothing changes.
- [ ] Re-export the JSON Schema and commit it.
- [ ] Fixtures:
  - `valid/review-loop.json`
  - `invalid/loop-bad-cel.json`
  - `invalid/loop-too-many-iterations.json`
  - `invalid/loop-with-gate.json`
  - `invalid/loop-with-writer.json`
  - `invalid/nested-loop.json`
- [ ] `test_spec.py`: the fixtures are covered by the existing parametrised tests. Add an assertion that the error messages name the node and path.

## 3. Engine: compile and run loops
- [ ] `graph/state.py`:
  - Add `iterations: Annotated[dict[str, int], merge]` to `RunState` and `RunUpdate`.
  - Initialise it as empty.
- [ ] `events.py`: add `LOOP_ITERATION_STARTED` and `LOOP_CONDITION_EVALUATED`.
- [ ] `graph/compile.py`: replace the flat `step_nodes` chain with a recursive builder.
  - Each spec node adds its LangGraph nodes and returns `(entry_id, exit_id)`, so the parent can wire edges and the existing "continue only if completed" routing.
  - Sequence: chain the children.
  - Loop:
    - The entry node `<loop.id>`:
      - On the first entry it emits `node_started` and keeps the loop input.
      - It increments `iterations[loop.id]` and emits `loop_iteration_started`.
    - Then come the body nodes.
    - The check node:
      - Its name uses a separator that `NodeId` forbids and LangGraph accepts (not `:` or `|`). Confirm this in a test.
      - It evaluates `until` with `last`, `iteration` and `results`, and emits `loop_condition_evaluated`.
      - Its route goes back to the entry when the condition is false and `iteration < max`. Otherwise it records the loop's result and emits `node_completed(loop)` with `stop_reason` and `iterations`, then continues.
    - An `ExpressionError` gives `node_failed(loop)` and ends the run, with `stopped_at` set to the loop.
  - Keep the gate and checkpointer check working on the recursive walk, and update the module docstring.
- [ ] `graph/run.py`: pass a `recursion_limit` computed from the spec (`compile.recursion_limit(spec)`) in the config for `ainvoke` in both run and resume.
- [ ] `packages/engine/tests/test_loop.py` (fake runtime, `InMemorySaver`):
  - The loop stops on its condition at iteration 2, with stop reason `condition`, and the next node receives the iteration 2 output.
  - The loop stops at `max_iterations=3` when the condition is never true, with stop reason `max_iterations`, and the run completes.
  - Iteration N+1's body receives iteration N's output.
  - The event order is `node_started(loop)`, then `loop_iteration_started(1)`, the body events and `loop_condition_evaluated(1,false)`, and so on up to `node_completed(loop)`. `seq` has no gaps.
  - A body node that fails stops the run with `stopped_at` set to that node, and no further iteration runs.
  - A CEL runtime error (for example `results.missing.text`) fails the loop with the message.
  - A loop inside a sequence, between other nodes.
  - Resume: a run interrupted after iteration 1 (a cancelled task, as in `test_resume.py`) resumes into iteration 2, not 1, and the events have no duplicate iteration markers.
  - A loop of 5 iterations with a 3-step body is not cut off by the recursion limit.

## 4. Docs
- [ ] README "Loops" section: the spec example, the CEL variables, the stop reasons, what is not allowed inside a loop and why, and the event sequence.
- [ ] CHANGELOG entry.
- [ ] Tick this plan.
