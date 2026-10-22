# Validation: `map` + `reduce` (concat/agent) primitives

## Done when (from roadmap)
> Map over 3 modules with max concurrency, then reduce

## Automated checks
User choice: engine unit tests on the fake runtime are the proof for this phase. They use LangGraph's `InMemorySaver` and need no network and no database.

- [ ] `test_expr.py`: `over` returns a list. A non-list result, an unknown variable (`iteration`) and an evaluation error each raise `ExpressionError` with a clear message. The existing condition tests are unchanged.
- [ ] `test_spec.py`:
  - `valid/map-modules.json` and `valid/map-reduce-agent.json` validate.
  - Each `invalid/map-*.json`, `invalid/nested-map.json` and `invalid/reduce-*.json` is rejected, and the error names the node and its path.
  - The exported JSON Schema contains `map`, with `max_concurrency` at most 8, and `reduce`, with `concat` and `agent`.
- [ ] `test_map.py`, Done when:
  - A tool node lists 3 modules.
  - A map with `max_concurrency: 2` runs an agent per module.
  - A concat reduce then joins the outputs.
  - The fake runtime's peak in-flight count is exactly 2.
  - The run completes, and its text holds the 3 outputs in module order.
- [ ] `test_map.py`, reduce agent: the reduce agent's input is the `[{item, output}]` JSON array in item order, and its output is the run's text.
- [ ] `test_map.py`, edge cases:
  - Items finishing out of order still give outputs in order.
  - 0 items: the map completes and the run continues.
  - A non-list `over` fails the map.
  - More than 40 items fail the map with the limit in the error.
  - A failing item stops the run at the map, with the item index in the error.
- [ ] `test_map.py`, events:
  - `node_started` and `node_completed` for the map appear exactly once.
  - Each item has one `map_item_started` and one `map_item_completed`.
  - Body events carry `payload.item`.
  - `seq` runs 1..n with no gaps.
- [ ] `test_map.py`, resume (added during implementation): after a cut-off once item 0 has finished, `resume_workflow` runs only items 1 and 2 again (AC-8).
- [ ] `test_map.py`, usage: the run's usage sums every item's usage and the reduce agent's usage.
- [ ] The existing engine, store, API, worker and sandbox suites still pass. Tests change only where the `Node` union widened.
- [ ] `ruff check`, `ruff format --check`, and strict `pyright`/`mypy` are clean across the workspace.
- [ ] CI is green.

## Manual / demo checks
These are optional. The user chose engine tests as the proof for this phase.
- [ ] `uv run pytest packages/engine/tests/test_map.py -v` passes locally, and the event list from the Done-when test shows the items overlapping two at a time.

## Merge criteria
- [ ] All checks above pass in CI.
- [ ] The JSON Schema, the OpenAPI spec and the web client are re-exported, and the README "Map and reduce" section and the CHANGELOG are updated.
- [ ] No custom CEL functions are registered. The limits (8 alive, 40 spawned) are named constants marked for 2.2.
- [ ] The roadmap phase 1.10 is marked done in the PR (`complete-phase`).
