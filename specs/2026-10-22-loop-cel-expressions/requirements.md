# `loop` primitive + CEL expressions

Roadmap phase: 1.9
Branch: plan/1.9-loop-cel-expressions

## Context
After 1.8, a run is a straight line. It goes through `agent`, `tool` and `gate` nodes in order, and the first node that does not complete ends it. Many useful flows need to repeat. The typical case is a writer and a reviewer that go back and forth until the reviewer is satisfied. This phase adds the `loop` primitive and the CEL expression layer that decides when a loop stops.

It depends on these phases, all done:
- 0.2/0.4: the spec union and the compiler that flattens sequences into one chain.
- 0.5: the run event log.
- 1.3: the Postgres checkpointer. A loop's iteration count lives in the graph state, so a restart resumes at the right iteration.

It unblocks:
- 1.10: `map`/`reduce`, which reuse the recursive compiler and the CEL module.
- 1.11: the docs template, which can use a review loop.
- 2.2: policy limits on loop iterations, enforced at runtime.
- 3.6: `router`, which uses CEL conditions.
- 6.6: PR review comments that feed a new loop iteration.

Principles that apply:
- **Open, but safe by construction (2):** `max_iterations` is required and capped at the policy default of 5 (tech-stack policy limits). The spec is checked when it is validated, and the iteration count is checked again at runtime.
- **Repo content is data (5):** conditions are CEL, which is sandboxed. A condition can read the output text of the loop body, and that text never runs as code.
- **Transparency (6):** each iteration and the reason the loop stopped are written to the run event log.
- **Small, verifiable steps (7):** the loop body may only contain `agent`, `tool` and `sequence` nodes. Gates and writers inside loops come later.

Tech-stack choices that apply:
- CEL via `cel-python` for `loop.until`. Arbitrary code is never allowed.
- LangGraph conditional edges for the back-edge.
- The Postgres checkpointer for durability.

## Scope
### In scope
- **CEL module** (`agentic_engine/expr.py`):
  - `compile_condition(source)` parses and checks the expression once, and raises `ExpressionError` with the position and a message.
  - `evaluate(compiled, context) -> bool` evaluates against a fixed context. A non-bool result or an evaluation error raises `ExpressionError`.
  - The expression can only see these variables, with no custom functions:
    - `last` (string): the loop body's output for the iteration that just ran.
    - `iteration` (int): the number of completed iterations, starting at 1.
    - `results` (map): node id → `{status, text, data}` for nodes run so far, holding the latest iteration's values.
  - Expressions longer than 1,000 characters are rejected.
- **Spec:**
  - `LoopNode` is `{"type": "loop", "id", "body": Node, "until": str, "max_iterations": int}` and joins the `Node` union.
  - `max_iterations` must be between 1 and 5.
  - `iter_nodes` recurses into `body`.
  - The `WorkflowSpec` validator compiles every `until` and rejects invalid CEL with the node path.
  - It also rejects a loop body that contains a `gate`, a writer (`WRITE_TOOLS`), a publisher (`PUBLISH_TOOLS`) or another `loop`, and the error says why.
  - The JSON Schema is re-exported, and valid and invalid fixtures are added.
- **Engine:**
  - The compiler goes from a flat chain to recursive compilation. A loop becomes:
    - an entry node (named by the loop id) that starts an iteration,
    - its body steps,
    - an internal check node that evaluates `until` and either loops back to the first body step or continues.
  - Iteration counters are kept in `RunState` (`iterations: dict[loop_id, int]`), so they are checkpointed.
  - The input of iteration 1 is the loop's input. Each later iteration gets the previous iteration's body output. The loop's output is the output of its last iteration.
  - If a body node does not complete, the run ends as it does today, with `stopped_at` set to that node.
  - If the `until` condition fails to evaluate, the loop node fails with the CEL error.
  - The `recursion_limit` is computed from the spec, using step count × max iterations plus a margin. LangGraph's own default turned out to be 10,007, not 25, so this is a tight runtime backstop on the spec's bounds rather than a fix for a cut-off.
- **Events:**
  - `node_started(loop)` once.
  - `loop_iteration_started` (`iteration`) before each pass.
  - `loop_condition_evaluated` (`iteration`, `result`) after each pass.
  - `node_completed(loop)` with payload `stop_reason: "condition" | "max_iterations"` and `iterations`.
  - Reaching `max_iterations` completes the loop. It is not a failure.
  - The events of nodes inside the body are unchanged.
- **Fixtures:**
  - `valid/review-loop.json`: a sequence of a `draft` agent and a `review` agent, with `until: 'last.contains("APPROVED")'` and `max_iterations: 3`.
  - Invalid fixtures: bad CEL, `max_iterations: 6`, a gate inside a loop, a writer inside a loop, a nested loop.
- **Docs:** a README "Loops" section covers the spec shape, the CEL variables, the stop reasons and the restrictions. Add a CHANGELOG entry.

### Out of scope
- Gates, writers and publishers inside a loop. Approvals are unique on `(run_id, node_id)` and branches are `agent/<run>/<node>`, so both need an iteration key. This comes later, with 1.10/5.x or when 6.6 needs it.
- Nested loops. These come under the depth limit in 2.2.
- Workspace-configurable policy limits and runtime limit errors: 2.2. This phase hard-codes the default cap of 5.
- CEL for `router` (3.6) and for input mapping (3.2).
- Shared artifacts, so a writer can see both its earlier draft and the review: 3.3. For now each iteration only sees the previous iteration's output text.
- Showing iterations in the monitor graph: 2.5. The existing event list shows them as events.

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Scope | Body + `until` + `max_iterations`, with `last`, `iteration` and `results` in CEL | User choice. `results` lets a condition read a tool node's structured `data`, not only text. |
| Build order | CEL module first, then the spec, then the engine | User choice. The spec validator needs `compile_condition`, and each group stays green. |
| CEL library | `cel-python` (`celpy`) | Tech-stack choice. It is sandboxed, with no custom functions exposed. |
| When CEL is checked | It is compiled when the spec is validated, and evaluated at the check node | Invalid conditions fail early with the node path (principle 2). |
| `max_iterations` | Required, between 1 and 5 | The tech-stack policy default is 5 loop iterations. Making it required keeps the bound visible in the spec. |
| Reaching max | The loop ends `completed` with `stop_reason: "max_iterations"`, and the run continues | Done when: "stops on its condition or at max iterations". Both are normal stops. 2.2 decides whether a policy limit is a hard stop. |
| Feedback between iterations | Iteration N+1's input is iteration N's body output | It fits the existing single `last_text` channel. Richer context comes with 3.3 artifacts. |
| What is not allowed inside a loop | Gates, writers, publishers and nested loops | Approvals and branches are keyed by node id, so repeating them would collide. Allowing them needs iteration keys, which is out of scope. |
| Iteration count | Kept in `RunState`, which is checkpointed | A worker restart mid-loop resumes at the same iteration (AC-8). |
| Iteration events | Marker events at iteration boundaries, and body node events left unchanged | The monitor and SSE need no change. The `seq` order puts body events in the right iteration. |
| Check node name | `<loop id>` plus a separator that `NodeId` forbids (for example `.check`) | `NodeId` allows `_` and `-`, so a suffix such as `__check` could collide with a user node. LangGraph reserves `:` and `\|`, so the separator must avoid those too. |

## Open questions
- ~~Should `contains` ignore case?~~ Resolved: `cel-python` has no `lowerAscii`. Case-insensitive checks use `last.matches("(?i)approved")` (RE2).
- `results` holds only the latest iteration. Is a history (`history[i].last`) needed before 6.6? Proposal: no, revisit in 6.6.
