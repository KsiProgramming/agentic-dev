# Typed ports: input/output JSON Schemas validated at each edge

Roadmap phase: 4.2
Branch: plan/4.2-typed-ports

## Context
Today nodes hand each other plain text (`RunState.last_text`). Tool nodes also return a structured `data` dict, but nothing says what shape it has. Agents return prose. Milestone 4 builds the audit flow, in which nodes exchange `findings.json` (4.3), tool outputs feed specialist agents (4.4), and reduces merge findings by severity and confidence (4.5). Each of these steps breaks quietly when one node outputs a shape the next does not expect. Typed ports make that a loud failure at the edge where it happens, with a message that says which node, which side and where in the JSON.

It depends on these phases, all done:
- 3.4: the one engine validator (`validate_workflow`) behind `POST /workflows/{id}/validate` and `POST /runs`. The new issue codes go there.
- 4.1: parallel. A branch's first node gets the parallel's input, so input ports work inside branches through the same step runner.
- 11.6 and 11.8: the run console's step panel and failure banner, which already name the failing step and its error.

It unblocks:
- 4.3, 4.4, 4.5 and 4.7: `findings.json` gets a schema that every audit node is checked against.
- 5.6: live validation on the canvas, which marks incompatible ports and starts from `port_mismatch`.
- 6.1: an orchestrator's plan, which is a typed output.

Principles that apply:
- **Open, but safe by construction (2):** a schema is checked when the spec is validated (`invalid_schema`, `port_mismatch`) and again at runtime on every edge.
- **Repo, Jira and web content are data (5):** an agent's output is parsed as JSON and checked. It is never run. A remote `$ref` is refused, so validating a schema never reaches the network.
- **Transparency (6):** a port failure is a `node_failed` event with a structured `port` payload. The console shows where the JSON went wrong, not only that it did.
- **Small, verifiable steps (7):** ports go on agent and tool nodes only, and the static check stays deliberately light.
- **One spec, many views (1):** ports are spec fields, exported in the JSON Schema, so the canvas (5.4 and 5.6) and the Architect read them from the same document.

Tech-stack choices that apply:
- Pydantic v2 models, exported as JSON Schema (`schemas/workflow-spec.v0.json`), and the generated OpenAPI client for the web.
- One engine validator (tech-stack → Workflow validation) with stable issue codes.
- The `AgentRuntime` interface is unchanged. As with the tool intent (11.8), the engine asks for the output in the agent's instructions, so Claude and Copilot behave alike.
- The run console rules (tech-stack → Run console): failure banner, step panel tabs, `JsonView`, no JSON in a table cell.

## Scope
### In scope
- **Spec:** `AgentNode` and `ToolNode` gain optional `input_schema` and `output_schema`, each a JSON Schema object (`dict[str, JsonValue]`).
  - Dialect: JSON Schema 2020-12. The root must be `"type": "object"`, so a typed value is always a dict and fits `AgentNodeResult.data`.
  - Only local `$ref`s (`#/$defs/…`) are allowed. A schema is at most 16 KB as JSON.
  - Both fields default to `None`, and an untyped node behaves exactly as today.
- **Validation** (one validator, so `POST /runs` and `/validate` agree), with two new codes:
  - `invalid_schema`: the schema is not valid 2020-12, its root is not an object, it has a non-local `$ref`, or it is too large. The `path` points at the field (`root.steps[1].output_schema`).
  - `port_mismatch`: a light static check on consecutive steps of a sequence. Gates are looked through, because a gate passes its input on unchanged. When producer A has an `output_schema` and consumer B has an `input_schema`, the check fails when a property in B's `required` is not declared in A's `properties`, or when that property's top-level `type` differs between the two schemas. The issue is on B. It is not full schema subsumption (see Out of scope).
- **Engine (runtime edge checks):**
  - **Output side:** after an agent or tool node completes, if it has an `output_schema`, its output is parsed and checked.
    - For an agent, the output is its final text. The text is parsed as JSON, and when it holds exactly one fenced code block, that block is parsed.
    - For a tool, the output is its `data` when present, otherwise its text parsed as JSON.
    - On success, the parsed object becomes the result's `data` (CEL reads `results.<id>.data.*`), and the result's text becomes the canonical JSON (`json.dumps(…, indent=2)`), which is what the next node receives.
    - On failure, the node ends `failed`. Its usage is still counted.
  - **Input side:** before a node with an `input_schema` starts, its input is parsed as JSON and checked. The input is the previous output, the run input for the first step, a map item, or a parallel's input. On failure, the node logs `node_started` and then `node_failed`, and no agent is started.
  - **Instructions:** an agent with an `output_schema` gets one more paragraph in its instructions (`OUTPUT_SCHEMA_INSTRUCTION`): end with one JSON object that matches this schema and nothing else, followed by the schema. This is added beside `TOOL_INTENT_INSTRUCTION` in `to_request`.
  - **Error text**, one line and at most 500 characters, of the form `output of 'scanner' does not match its output_schema at /findings/0/severity: 'urgent' is not one of ['low', 'high'] (and 2 more)`.
    - On the input side it reads `input of 'triage' (from 'scanner') does not match its input_schema …`.
    - When the text is not JSON: `output of 'scanner' is not JSON: Expecting value: line 1 column 1`.
    - The first error reported is `jsonschema`'s `best_match`.
  - A port failure inside a map item or a parallel branch fails that item or branch like any other failure. The map, or the parallel's join policy, then decides.
- **Events:** `node_failed` for a port failure carries `port`: `{side: "input" | "output", node_id, from_node_id?, errors: [{pointer, message}]}`, with at most 10 errors. Other events do not change.
- **API:** the spec JSON Schema, the OpenAPI spec and `web/src/api/schema.d.ts` are re-exported. tech-stack's codes list gains `invalid_schema` and `port_mismatch`.
- **Web (run console):**
  - **Output tab of a step that failed at a port:** a "Wrong shape" alert gives the side ("Output" / "Input from `scanner`") and lists each error as its pointer in mono with the message as text. When there are more than 5 errors, the rest are behind "Show all". The banner keeps its one-line reason (the step's error).
  - **Input tab:** a typed node shows "Input schema" and "Output schema", each in a `JsonView`.
  - All agent-derived text is rendered as plain text (mission principle 5).
- **Fixtures:**
  - Valid: `typed-ports.json`, a scanner tool → typed agent → gate → typed consumer.
  - Invalid: `port-invalid-schema`, `port-not-object`, `port-remote-ref`, `port-mismatch-required`, `port-mismatch-type`.
- **Docs:**
  - A README "Typed ports" section.
  - A CHANGELOG entry.
  - In tech-stack.md: the spec rule, the validation codes, a "Typed ports" contract section, the run console rule for the "Wrong shape" alert, and a decisions log row.

### Out of scope
- **Ports on containers**, that is, map items, parallel branches, loop bodies and a reduce's output as typed values in their own right. Their inner agent and tool nodes can be typed.
- **A workflow-level `input_schema`** that checks the run input on `POST /runs`. Template fields already have their own schema. This may come with 5.x.
- **Full schema compatibility** (subsumption, `$ref` following, `anyOf` reasoning) in the static check. This belongs to 5.6, live validation on the canvas.
- **Native structured output modes in the adapters** (Claude's JSON schema output format) and a repair turn when the output does not match. Both are possible later behind the same `output_schema` field, as the validator already flags capability gaps.
- **Named multi-port nodes** (several inputs or outputs per node) and explicit edge mappings. Nodes still take the previous output. Named artifacts are 4.3.
- **Schemas for the platform tools' own `data`**. The spec author declares the shape they rely on in `output_schema`.

## Decisions
| Decision | Choice | Rationale |
|---|---|---|
| Scope | Ports on agent and tool nodes, runtime checks on both sides of each edge, `invalid_schema` and a light `port_mismatch` | User choice. It meets "Done when" and catches the obvious wiring mistakes before a run spends tokens, without a schema-subsumption engine. |
| How an agent produces JSON | The engine adds the schema to the instructions and parses the final message (one fenced block allowed), with no repair turn | User choice. The adapters and the `AgentRuntime` contract are unchanged, so Claude and Copilot behave alike, as with the tool intent (11.8). A wrong shape fails clearly instead of costing a hidden second turn. |
| Library | `jsonschema` (Draft 2020-12, `Draft202012Validator`, `referencing` with no retrieval), added to the engine's dependencies | The reference Python implementation. It is already in the lockfile through `mcp`, and it gives JSON pointers and `best_match` for clear errors. Pydantic validates models, not arbitrary user schemas. |
| Root type | `"type": "object"` required | A typed value then always fits `AgentNodeResult.data: dict` and reads as `results.x.data.field` in CEL. A list goes in a property. |
| Remote `$ref` | Refused (`invalid_schema`) | Validating must never fetch a URL (mission principle 5 and the sandbox egress rules). Local `$defs` cover reuse inside a spec. |
| Typed text | The next node receives the canonical JSON, not the raw message | A fenced or chatty answer becomes clean data for the consumer. The raw message is still in the events and the console. |
| Where a failure lands | Output side: on the producer. Input side: on the consumer, which logs `node_started` then `node_failed` | The console's "Failed at <step>" then names the node whose schema was broken, which is the one to fix. |
| Error payload | One-line `error` plus a structured `port` on `node_failed` | The banner and the audit stay one line, and the console can list the pointers without parsing a string. |

## Open questions
- **The roadmap's "Next up" line still names Milestone 11, which is now fully done.** CLAUDE.md says to change it in its own PR with a changelog entry, so it should move to Milestone 4 in a small separate PR, before or beside this one.
