# Validation: Compile spec → LangGraph graph for `sequence` of `agent` nodes

## Done when (from roadmap)
> A 2-node sequence runs end to end on the fake runtime

## Automated checks
- [ ] `packages/engine/tests/test_run_workflow.py::test_two_step_sequence_runs_on_fake_runtime`: `two-step-sequence.json` is parsed, compiled and run on `FakeRuntime` with the no-network guard active.
  - Status `completed`; order `["writer", "reviewer"]`.
  - The reviewer's request `input` is the writer's output text, and its `instructions` are the spec's text only.
  - The run's usage equals the sum of both nodes' usage.
- [ ] Edge cases in `test_run_workflow.py`:
  - Nested sequence runs `planner` → `implementer` → `tester`, each receiving the previous output.
  - A single `agent` root runs one node.
  - A failure in node 1 gives run status `failed`, `stopped_at == "writer"`, and node 2 is never requested.
  - Cancelling the calling task during node 1 yields a cancelled fake run within 100 ms and node 2 is never requested.
- [ ] `test_compile.py`: graph node names match the spec's agent ids; nested sequences flatten in depth-first order.
- [ ] `test_graph_state.py`: state reducers and `WorkflowRunResult` JSON round-trip.
- [ ] Existing CI jobs are green:
  - `ruff check` and `ruff format --check`
  - `pyright` (strict), with no `# type: ignore` added for LangGraph types
  - `pytest` (all packages)
  - schema freshness, web and API contract jobs
- [ ] `uv.lock` is updated and committed with `langgraph`.

## Manual / demo checks
- [ ] `uv run pytest packages/engine -v` offline. Expected: all tests pass.
- [ ] `uv run pytest packages/engine/tests/test_run_workflow.py -k two_step -v`. Expected: the Done-when test passes.

## Merge criteria
- [ ] All checks above pass in CI.
- [ ] The scope matches `requirements.md`:
  - No `run_events` table or persistence.
  - No API endpoints.
  - No real provider and no checkpointer.
- [ ] README and CHANGELOG are updated.
- [ ] Roadmap phase 0.4 is marked done in the PR (`complete-phase` skill or the CI check).
