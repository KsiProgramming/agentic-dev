# Plan: Workflow spec v0

Order: test first. Fixtures and failing tests land first (marked `xfail` so CI stays green), then the models make them pass, then the schema export is added. The repo stays green after each group.

## 1. Fixtures and tests (red)
- [x] `packages/engine/tests/fixtures/specs/valid/`:
  - `single-agent.json`: the root is one agent.
  - `two-step-sequence.json`: the shape 0.4 will run.
  - `nested-sequence.json`: a sequence inside a sequence.
- [x] `packages/engine/tests/fixtures/specs/invalid/`, one file per rule. Each file is named after the rule it breaks:
  - `unknown-node-type.json`
  - `missing-instructions.json`
  - `extra-key.json`
  - `duplicate-node-id.json`
  - `empty-sequence.json`
  - `bad-node-id.json`
  - `wrong-spec-version.json`
  - `unknown-provider.json`
- [x] `packages/engine/tests/test_spec.py`:
  - Parametrized over `valid/*`: the spec parses, and a `model_dump(mode="json")` round-trip gives an equal model.
  - Parametrized over `invalid/*`: parsing raises `ValidationError`. Each case also states the expected error `loc` or message substring, so it fails for the intended reason.
  - Mark the tests `xfail(strict=True)` until group 2 lands.

## 2. Spec models (green)
- [x] Add `pydantic>=2.11` as a direct dependency of `packages/engine/pyproject.toml`, then run `uv lock`.
- [x] `agentic_engine/spec/models.py`:
  - a `_Base` model with `ConfigDict(extra="forbid", frozen=True)`
  - a `NodeId` annotated type with the slug pattern
  - `AgentNode` and `SequenceNode`, both with `type: Literal[...]`
  - a recursive discriminated `Node` union
  - the `WorkflowSpec` envelope
- [x] A `model_validator(mode="after")` on `WorkflowSpec` that walks the tree and rejects duplicate ids, naming the duplicated id. Use `min_length=1` on `steps` and on the agent text fields.
- [x] `agentic_engine/spec/__init__.py`:
  - export the public names
  - add a `parse_spec(data: object) -> WorkflowSpec` helper that wraps `WorkflowSpec.model_validate`
- [x] Remove the `xfail` marks. `pytest`, `pyright` (strict) and `ruff` pass.

## 3. JSON Schema export
- [x] `scripts/export_workflow_schema.py`, written in the style of `export_openapi.py`. It writes `WorkflowSpec.model_json_schema()` to `schemas/workflow-spec.v0.json`, with `$id` and `title` set, LF line endings and a stable key order.
- [x] Commit the generated `schemas/workflow-spec.v0.json`.
- [x] Add one test that the exported schema contains a discriminated `oneOf` covering `agent` and `sequence`, so the export is not empty or broken.
- [x] `.github/workflows/ci.yml`: in the `python` job, after `uv sync`, run `uv run python scripts/export_workflow_schema.py` and then `git diff --exit-code -- schemas/`. On failure, print a hint to re-run the script and commit the result, matching the API contract job.

## 4. Docs
- [x] A short "Workflow spec" section in `README.MD` that links the schema and the valid fixtures as examples.
- [x] A `CHANGELOG.md` entry.
