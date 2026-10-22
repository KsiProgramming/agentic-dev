# Validation: `loop` primitive + CEL expressions

## Done when (from roadmap)
> A reviewer loop stops on its condition or at max iterations

## Automated checks
User choice: engine unit tests are the required new tests for this phase. They run on the fake runtime with LangGraph's `InMemorySaver`, with no network and no database.

- [ ] `test_expr.py`:
  - Valid conditions evaluate to `True` and `False`.
  - A syntax error, an unknown variable, a non-bool result, an over-long expression and an evaluation error each raise `ExpressionError` with a clear message.
- [ ] `test_spec.py`:
  - `valid/review-loop.json` validates.
  - Each `invalid/loop-*.json` and `invalid/nested-loop.json` is rejected, and the error names the node and its path.
  - The exported JSON Schema contains `loop` with `max_iterations` at most 5.
- [ ] `test_loop.py`, stop on condition: the reviewer fixture, with the fake runtime answering `APPROVED` on iteration 2, ends the loop after 2 iterations with `stop_reason: "condition"`.
- [ ] `test_loop.py`, stop at max: the reviewer never approves, so the loop ends after `max_iterations` with `stop_reason: "max_iterations"`, and the run completes.
- [ ] `test_loop.py`, feedback: iteration N+1's first body node receives iteration N's output as input.
- [ ] `test_loop.py`, events:
  - `node_started(loop)` and `node_completed(loop)` appear exactly once.
  - There is one `loop_iteration_started` and one `loop_condition_evaluated` per iteration, in order.
  - `seq` runs 1..n with no gaps.
- [ ] `test_loop.py`, failures:
  - A failing body node stops the run at that node.
  - A CEL evaluation error fails the loop node and the run, with the message.
- [ ] `test_loop.py`, resume: after an interruption once iteration 1 has completed, `resume_workflow` continues at iteration 2, and no iteration marker is duplicated (AC-8).
- [ ] `test_loop.py`, recursion limit: 5 iterations of a 3-step body complete.
- [ ] The existing engine, store, API, worker and sandbox suites still pass. Tests change only where the `Node` union widened.
- [ ] `ruff check`, `ruff format --check`, and strict `pyright`/`mypy` are clean across the workspace.
- [ ] CI is green.

## Manual / demo checks
These are optional. The user chose engine tests as the proof for this phase.
- [ ] `uv run pytest packages/engine/tests/test_loop.py -v` passes locally, and the event list from the stop-on-condition test reads correctly.

## Merge criteria
- [ ] All checks above pass in CI.
- [ ] README "Loops" section and CHANGELOG are updated, and the JSON Schema is re-exported.
- [ ] `cel-python` is in the lockfile. No custom CEL functions are registered.
- [ ] The roadmap phase 1.9 is marked done in the PR (`complete-phase`).
