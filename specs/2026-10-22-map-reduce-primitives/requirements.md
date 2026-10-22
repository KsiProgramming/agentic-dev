# `map` + `reduce` (concat/agent) primitives

Roadmap phase: 1.10
Branch: plan/1.10-map-reduce-primitives

## Context
After 1.9, a run is a chain with loops: every node runs one at a time. The docs template (1.11) has to work on several modules of a repo, so it needs to fan out. It runs the same body once per module, at most N at a time, and then combines the outputs. This phase adds `map` for the fan-out and `reduce` for combining the outputs.

It depends on these phases, all done:
- 0.4/1.9: the recursive compiler (`add(node, then)`) and the CEL module (`agentic_engine/expr.py`).
- 0.5: the run event log.
- 1.3: the Postgres checkpointer, which keeps the outputs of finished items.

It unblocks:
- 1.11: the "Generate docs" template, which maps over modules and reduces into one docs set.
- 3.5: the dedupe and vote `reduce` strategies.
- 5.1: the `orchestrator`, which reuses the `Send` fan-out.

Principles that apply:
- **Open, but safe by construction (2):** `max_concurrency` is required and capped at the policy limit of 8 agents alive. The number of items is capped at the limit of 40 agents spawned. Both are checked when the spec is validated (concurrency) and at runtime (item count).
- **Repo content is data (5):** `over` is a sandboxed CEL expression. Each item reaches the body as input text, never as instructions.
- **Transparency (6):** every item's start and end, and every body event, is logged with its item index.
- **Small, verifiable steps (7):** the map body may only contain `agent`, `tool` and `sequence` nodes. Parallel writers need the integration branch from 5.3.

Tech-stack choices that apply:
- LangGraph `Send` for the dynamic fan-out, which the tech stack names for `map`.
- CEL (`cel-python`) for `over`.
- The Postgres checkpointer for durability.

## Scope
### In scope
- **CEL:** `expr.py` gains `compile_expression(source, variables)` and `CompiledExpression.evaluate_list(...) -> list[JsonValue]`. A non-list result or an evaluation error raises `ExpressionError`. `over` can only see `last` (string) and `results` (node id → `{status, text, data}`). Expressions keep the 1,000-character limit, and no custom functions are added.
- **Spec:**
  - `MapNode` is `{"type": "map", "id", "over": str, "body": Node, "max_concurrency": int}`, where `max_concurrency` is between 1 and 8 (`MAX_AGENTS_ALIVE`).
  - `ReduceNode` is `{"type": "reduce", "id", "from": NodeId, "strategy": "concat" | "agent"}`:
    - `concat` takes an optional `separator`, which defaults to `"\n\n"`.
    - `agent` requires `agent: {role, instructions, provider?, model?}`.
  - Both nodes join the `Node` union, and `iter_nodes` recurses into `map.body`.
  - The `WorkflowSpec` validator rejects these, naming the node and its path:
    - a bad `over` CEL
    - a map body that contains a gate, a writer, a publisher, a loop or a map
    - a `reduce.from` that is not an earlier `map` in the same run
  - The JSON Schema, the OpenAPI spec and the web client are re-exported.
- **Engine:**
  - A map compiles to:
    - an entry node `<map>` that evaluates `over` and logs `node_started`. It checks the item count (at most 40) and fans out with one `Send("<map>.item", {index, item})` per item. With 0 items it goes straight on.
    - a worker node `<map>.item` that runs the body for one item. Its input is the item: a string as-is, anything else as JSON.
    - a join node `<map>.join` that records the map's result and logs `node_completed`.
  - A per-map `asyncio.Semaphore(max_concurrency)` in the worker keeps at most N items in flight.
  - Item outputs go into `RunState.map_results[map_id][index]` through a reducer, so they are checkpointed per item and ordered by item index whatever order they finish in.
  - The map's output text is the item outputs joined by `"\n\n"`. Its `data` is `{"items": [...], "outputs": [...]}`, with the item values and outputs in item order.
  - If any item does not complete, the map fails with the failing index and the run stops at the map. Other items already in flight finish first.
  - Body node results are not written into `RunState.results`, because their ids repeat across items. Only their usage is added to `RunState.usage`.
  - Reduce has two strategies:
    - `concat` joins the `from` map's outputs in item order.
    - `agent` runs one agent turn whose input is the outputs as a JSON array (data, never instructions).
  - `recursion_limit` and `step_nodes` cover map and reduce.
- **Events:**
  - `node_started(map)` with `items: n`.
  - `map_item_started` and `map_item_completed` (`index`, `status`) for each item.
  - The body's `node_*` and agent events carry `payload.item`.
  - `node_completed(map)` or `node_failed(map)` ends the map.
  - Reduce uses the normal `node_*` events.
- **Fixtures:**
  - `valid/map-modules.json`: a `list_modules` tool node, then a map over `results.list_modules.data.modules` with `max_concurrency: 2`, then a concat reduce.
  - `valid/map-reduce-agent.json`.
  - Invalid fixtures: a writer in the map, a gate in the map, a nested map, `max_concurrency: 9`, bad CEL in `over`, a reduce from an unknown node, a reduce from a non-map node, and a reduce before its map.
- **Docs:** a README "Map and reduce" section and a CHANGELOG entry.

### Out of scope
- Writers, gates and publishers inside a map: these need per-item branches and approvals, plus the integration branch from 5.3.
- Nested maps, and maps inside loops: the depth limit comes in 2.2.
- The `dedupe` and `vote` reduce strategies: 3.5.
- Workspace-configurable limits: 2.2. The caps of 8 and 40 are hard-coded here.
- Tolerating partial failure (`on_item_failure: continue`): not needed for 1.11. Revisit in 3.x.
- Showing map children in the monitor graph: 2.5 and 5.4. The event list shows them as events.

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Item source | CEL `over` over `last` and `results`, which must return a list | User choice. 1.11 maps over the modules a previous node found, so a static list is not enough. |
| Map body | `agent`, `tool` and `sequence` only | User choice. Parallel writers need the integration branch from 5.3, and gates need per-item approvals. |
| Reduce shape | A separate `reduce` node with `from: <map id>` | User choice. It matches the mission's separate primitive, and 3.5 adds strategies to it. |
| Fan-out | LangGraph `Send` to one `<map>.item` worker per item | User choice and the tech-stack choice for `map`. The writes of finished tasks are checkpointed. |
| Concurrency | A per-map `asyncio.Semaphore(max_concurrency)` | User choice. LangGraph's `max_concurrency` config applies to the whole graph, not to one map node. |
| Limits | `max_concurrency` between 1 and 8, checked at validation. Item count up to 40, checked at runtime | Tech-stack policy defaults (8 agents alive, 40 agents spawned). The item count is only known at runtime. |
| Sequence body per item | The worker runs the body's steps in order inside one LangGraph node | A `Send` targets a single node. Steps keep their own events, tagged with `item`. |
| Result order | Outputs are kept by item index | The output is deterministic whatever order the items finish in, so tests and reduce are stable. |
| Item failure | Fail fast: the map fails once the items in flight have finished | This matches the existing rule that a node that does not complete ends the run. |
| Internal node names | `<map>.item` and `<map>.join` | `NodeId` forbids `.`, as for `<loop>.check` in 1.9. |

## Open questions
- ~~Should the map's own output text be the joined outputs or a JSON array?~~ Resolved: the outputs joined by a blank line, so a following agent reads them naturally. The map's `data` holds `items` and `outputs`, and reduce reads that.
- ~~Should the reduce agent's input include each item's value next to its output?~~ Resolved: yes, `[{item, output}]`, so the agent knows which module each output belongs to.
- No platform tool returns a module list as structured data yet. The `repo` tools return text, and CEL has no `split`. So the fixtures use a literal list in `over`, and the Done-when test uses a fake `repo.list_modules` tool that returns `data.modules`. Phase 1.11 needs a way to list modules: a tool that returns structured content, or an agent with structured output.
