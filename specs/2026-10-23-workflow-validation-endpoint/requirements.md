# Validation endpoint: `POST /workflows/{id}/validate`

Roadmap phase: 3.4
Branch: plan/3.4-workflow-validation-endpoint

## Context
Milestone 3 gives admins and authors control before a run costs anything. 3.2 and 3.3 added the policy and budget checks, but they only run inside `POST /runs` and rerun, and every check reports a flat string:
- The spec's model validators (`_unique_node_ids`, `loop_errors`, `map_errors`, `publish_gate_errors` in `agentic_engine/spec/models.py`) join their problems with `"; "` into one Pydantic `ValueError`. A client cannot tell which node is wrong without parsing prose.
- `policy_errors` and `budget_errors` return `list[str]`, and `POST /runs` wraps them in `PolicyErrorDetail.errors: list[str]`.
- Unknown tool names (`agent.tools`, `tool.tool`) are only caught at runtime, by the Claude adapter (`unknown tools: …`), after the sandbox is up.
- Nothing can check a spec without starting a run.

3.4 adds one place that answers "can this workflow run here, and if not, exactly what to fix". It is the `validate` building block that later phases call: live validation on the canvas (5.6) and the Architect's `validate` tool and repair loop (9.2, 9.3).

The roadmap row says "schema, ports, cycles, policy". In today's spec:
- **ports:** typed ports arrive in 4.2. Today the cross-node links are references: `reduce.from` must name an earlier map, and a publisher's `from_node` must name an earlier writer with a gate in between. These are the "ports" checked in 3.4.
- **cycles:** the spec is a tree (`root` → `steps` / `body`), so it cannot hold a cycle. The only possible loops are references to a node that runs later or to the node itself. They are reported as reference errors.

Principles that drive it:
- **Mission 2 (safe by construction):** limits are checked at validation time and again at runtime. This endpoint is the validation-time half, and it runs before anything costs money.
- **Mission 1 (one spec, many views):** one validator in the engine serves the API, `POST /runs`, the canvas and the Architect, so they never disagree.
- **Mission 3 (gates before irreversible actions):** the publish-after-gate rule is reported like any other error, with the node to fix.
- **Tech stack, Pydantic v2:** the error shape is a Pydantic model exported through OpenAPI, so the frontend gets a typed client.

Depends on: 0.2 (spec), 1.6 to 1.10 (primitives and their checks), 3.2 (policy), 3.3 (budget). All are done.
Unblocks: 4.2 (port type errors use the same issue shape), 5.1 (stored workflows reuse this route's `{id}`), 5.6 (canvas errors on nodes), 9.2 and 9.3 (Architect `validate` tool and repair loop).

## Scope
### In scope
- **Issue model** `agentic_engine.spec.ValidationIssue`:
  - `code`: a stable slug, e.g. `schema`, `duplicate_node_id`, `unknown_tool`, `invalid_expression`, `not_allowed_in_loop`, `not_allowed_in_map`, `reference`, `publish_without_gate`, `policy_limit`, `budget_unpriced_model`;
  - `path`: the JSON path in the spec, e.g. `root.steps[1].body`;
  - `node_id`: the node to fix, if there is one;
  - `message`: one sentence that names the problem and what to change;
  - `limit` and `value`: for policy issues only (`limit` is a `PolicyLimit`).
- **One validator** `validate_workflow(raw, *, policy, priced, default_model, known_tools) -> list[ValidationIssue]`:
  - **schema:** Pydantic errors become `schema` issues, with the `loc` turned into the spec's path (`root.steps[0].role`) and the node id taken from the nearest node;
  - **structure:** duplicate node ids, loop and map rules, CEL `until` / `over`;
  - **references ("ports, cycles"):** `reduce.from` and a publisher's `from_node` must name a node that runs before it, of the right kind (map, writer). A reference to itself or to a later node is reported here;
  - **gates:** a publisher needs a gate between its writer and itself;
  - **tools:** each name in `agent.tools` and `tool.tool` must be a platform tool;
  - **policy:** `policy_errors` against the workspace's effective policy, and `budget_errors` when a budget applies;
  - it collects every issue in one pass and returns them in run order (depth first). If the schema fails, only schema issues are returned, since later checks need a parsed spec.
- **Existing checks return issues:** `loop_errors`, `map_errors`, `publish_gate_errors`, `policy_errors` and `budget_errors` return `ValidationIssue`s. The `WorkflowSpec` model validators still raise on the same problems (so a bad spec can never be built), with messages built from the issues.
- **Endpoint** `POST /workflows/{id}/validate` (new `agentic_api.workflows` router, `operation_id="validateWorkflow"`):
  - body: `{workflow: <raw JSON object>, workspace_id?: UUID, budget_usd?: decimal}`. The workflow is taken as raw JSON, so that a broken spec is reported in the response rather than refused by FastAPI;
  - `{id}` must equal `workflow.id`, else the response has an `id_mismatch` issue;
  - `200 {valid: bool, issues: ValidationIssue[], policy: Policy}`: an invalid spec is a normal answer, not an HTTP error. `policy` is the effective policy it was checked against;
  - `404` if the workspace does not exist; `422` only for a malformed request envelope (for example, `workflow` is not an object);
  - read only: no run, no storage, no events, no sandbox. It does not need a GitHub or Claude connection. A missing connection is a `POST /runs` concern.
- **`POST /runs` and rerun use the same shape:** their policy and budget `422` detail gains `issues: ValidationIssue[]` next to the existing `errors: list[str]` (kept for compatibility).
- **OpenAPI:** the new operation and models are in the spec, and `web/src/api/schema.d.ts` is regenerated (`npm run gen:api`). No UI uses it yet.

### Out of scope
- Storing workflows, `GET /workflows/{id}`, versions: 5.1. Until then `{id}` is only checked against the body.
- Typed input/output ports and JSON Schema checks at edges: 4.2 (it adds a `port_type` code to the same model).
- Calling validate from the UI (New run sheet, canvas errors on nodes): 5.6. Template runs keep their current `422`.
- Capability-gap checks across providers: 8.3.
- Runtime limits (agents spawned, wall time, budget metering): already enforced by 3.2 and 3.3.
- Connection checks (GitHub installed, Claude key present): they stay on `POST /runs` (`409`).
- Playwright or web tests (the user chose engine unit tests and API integration tests).

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| What `{id}` refers to | The spec's own `id`, sent in the body; no storage | 5.1 owns stored, versioned workflows. Keeping the route shape now means 5.1 only makes the body optional. |
| Invalid spec status | `200` with `valid: false` | Validation answering "invalid" is a success of the endpoint. The canvas and the Architect read `issues` without treating it as a failure. `422` stays for a malformed request. |
| Error shape | Structured `ValidationIssue` with a stable `code`, `path`, `node_id` and `message` | "Actionable" means a client can put the error on the right node and a person can read the fix. Stable codes let the Architect repair loop branch on them. |
| Where the checks live | One `validate_workflow` in `agentic_engine.spec`, used by the endpoint, the model validators and `POST /runs` | One source, so the canvas, the Architect and the run never disagree (mission 1). This was the user's choice ("engine-first, one source"). |
| Raw JSON in the body | `workflow: dict[str, JsonValue]`, parsed by the validator | A typed `WorkflowSpec` body would turn every schema error into a FastAPI `422` and skip the other checks. |
| Platform tool list | `PLATFORM_TOOLS` in `agentic_engine.spec`, next to `WRITE_TOOLS` and `PUBLISH_TOOLS`; `validate_workflow` takes it as the default `known_tools` | The engine already names the write and publish tools. A worker test checks that the tool servers register exactly these names, so they cannot drift, and the engine does not depend on `agentic_tools`. |
| Errors after a schema failure | Only schema issues | The structural and policy checks need a parsed spec. Fixing the schema issues reveals the rest. |
| `POST /runs` compatibility | Add `issues`, keep `errors: list[str]` | The web client and tests read `errors` today. Nothing breaks, and new clients use `issues`. |

## Open questions
- None. The platform tool list was settled during implementation (see Decisions).
