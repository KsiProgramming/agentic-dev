# Plan: `map` + `reduce` (concat/agent) primitives

The work goes in this order: spec, then the map engine, then reduce, then docs (user choice). Each group leaves the project working and CI green.

## 1. CEL list expressions + spec models
- [x] `expr.py`:
  - Generalise the compile step so the allowed variables are a parameter.
  - Add `compile_expression(source, variables)` and `CompiledExpression.evaluate_list(*, last, results) -> list[JsonValue]`. A non-list result raises `ExpressionError`.
  - Keep `compile_condition` and its behaviour the same.
- [x] `test_expr.py`:
  - A list is returned from `results.x.data.modules`.
  - A list literal is returned.
  - A non-list result is rejected.
  - `iteration` is unknown in `over`.
  - An evaluation error is raised for a missing key.
- [x] `spec/models.py`:
  - Add `MAX_AGENTS_ALIVE = 8` and `MAX_AGENTS_SPAWNED = 40`, with comments that 2.2 makes them configurable.
  - Add `MapNode` and `ReduceNode`. `ReduceNode.from` is the field `from_` with the alias `from`. For `strategy="agent"` the `agent` config is required, and for `concat` it is forbidden.
  - Both join the `Node` union. `iter_nodes` recurses into `map.body`, and `node_tools` returns `[]` for both.
- [x] `WorkflowSpec` validators:
  - `_maps_can_run`: the CEL in `over` compiles, and the body has no gate, writer, publisher, loop or map. A map is not allowed inside a loop.
  - `_reduce_sources`: `from` names a `map` that comes earlier in spec order.
  - `publish_gate_errors` and `loop_errors` treat map and reduce correctly.
- [x] Re-export the JSON Schema, the OpenAPI spec and the generated web client.
- [x] Fixtures:
  - `valid/map-modules.json`
  - `valid/map-reduce-agent.json`
  - `invalid/map-with-writer.json`
  - `invalid/map-with-gate.json`
  - `invalid/nested-map.json`
  - `invalid/map-too-concurrent.json`
  - `invalid/map-bad-cel.json`
  - `invalid/reduce-unknown-from.json`
  - `invalid/reduce-from-non-map.json`
  - `invalid/reduce-before-map.json`
- [x] `test_spec.py`:
  - The expected rejections name the node and its path.
  - The schema includes `MapNode` (`max_concurrency` from 1 to 8) and `ReduceNode`.
- [x] Groups 1 to 3 landed together, so no temporary `CompileError` for map and reduce was needed.

## 2. Engine: map fan-out
- [x] `graph/state.py`:
  - Add `map_results: Annotated[dict[str, dict[int, AgentNodeResult]], merge_map_results]` to `RunState`, `RunUpdate` and `initial_state`. The reducer merges by map id, then by index.
  - Add the worker's `Send` payload type, `MapItem` (`index`, `item`, `item_input`). The key `input` would clash with `RunState.input`.
- [x] `events.py`:
  - Add `MAP_ITEM_STARTED` and `MAP_ITEM_COMPLETED`.
  - `RunEventLog.emit` and `agent_event` take an optional `item: int`, which is written into the payload.
- [x] `graph/compile.py`:
  - The entry node `<map>` evaluates `over`, checks the count against `MAX_AGENTS_SPAWNED`, and logs `node_started` with `items`. Its conditional edge returns `[Send("<map>.item", ...)]`, or `"<map>.join"` when there are no items. A CEL or limit error leads to `node_failed(map)` and `END`.
  - The worker `<map>.item` does the following:
    - It takes the map's semaphore and logs `map_item_started`.
    - It runs the body's steps in order using the existing `_run_step` logic, refactored out of `_step` so it can run with an `item` tag.
  - `typings/langgraph` gains `Send`, `add_node(..., input_schema=)` and `Send` routes in `add_conditional_edges`.
    - It stops at the first step that does not complete, and logs `map_item_completed`.
    - It returns `map_results` and `usage`.
  - The join node `<map>.join` does the following:
    - It orders the outputs by index and builds the map's `AgentNodeResult` (joined text, `data.outputs`). If an item failed, it sets `failed` with the index.
    - It logs `node_completed` or `node_failed`, and sets `last_text`, `results[map]` and `order`.
    - It routes with `_continue_if_completed`.
  - `step_nodes` walks map bodies. `recursion_limit` counts a map as `body steps + 3`, because the `Send` workers share a superstep.
- [x] `packages/engine/tests/test_map.py` uses the fake runtime and `InMemorySaver`. The fake runtime records how many calls are in flight at once (peak). It covers:
  - 3 items with `max_concurrency` 2: the peak is 2 or less, and all 3 complete.
  - Outputs follow item order even when the fake runtime finishes items in reverse.
  - Each item's value reaches the body as input, with non-strings JSON-encoded.
  - A sequence body runs in order for each item.
  - 0 items: the map completes with empty output and the run continues.
  - An `over` that is not a list fails the map.
  - More than 40 items fail the map with the limit in the error.
  - A failing item fails the map and the run, naming the index.
  - The events: one `node_started`/`node_completed` for the map, start and complete markers for each item, the `item` tag on body events, and `seq` running 1..n with no gaps.
  - Usage from every item is summed into the run's usage.
  - Resume mid-map: only the unfinished items run again. This was not planned, but was added to back the README's durability claim.

## 3. Engine: reduce
- [x] `graph/compile.py`: the reduce step reads `state["map_results"][from]` in index order.
  - `concat` joins the outputs with `separator`. It makes no model call and has no usage.
  - `agent` builds an `AgentNode` from the config, with `id` set to the reduce id. Its input is the JSON array `[{item, output}]`, and it calls `run_agent_node`.
  - Both log the normal `node_*` events, and `agent` also logs agent events.
  - Reduce reads the map's `data` (`items`, `outputs`) rather than `map_results`. Item results carry their item in `data.item`.
- [x] `test_map.py` (reduce cases):
  - `concat` with the default separator and with a custom one.
  - `agent` gets the JSON array as input, and its output becomes the run's text.
  - The full Done-when flow: a tool lists 3 modules, the map runs with concurrency 2, then reduce produces the final text in order.

## 4. Docs
- [x] README: a "Map and reduce" section covering the spec shape, the `over` variables, the limits, the events and the restrictions. Update the node list and the Engine section.
- [x] CHANGELOG entry.
- [x] Tick this plan, and record answers to the open questions in `requirements.md`.
