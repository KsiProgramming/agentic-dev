# Validation: `repo` MCP server (read only) wired into the agent runtime

## Done when (from roadmap)
> An agent answers a question about the repo using the tools

To check this: a run of `ask-repo.json` started with `POST /runs` on a repo streams `tool_call`/`tool_result` events for `repo.list_files`, `repo.read_file` and `repo.search`. The calls go through the `repo` MCP server into the run's sandbox. The results hold the facts that answer the question: the workspace package directories and the root `pyproject.toml` members. The run then completes with a `message`. The proof is in two places:
- `packages/worker/tests/test_worker.py::test_done_when_an_agent_answers_a_question_about_the_repo`, which uses a real Docker sandbox.
- The CI compose job's "Repo MCP demo (phase 1.2)" step.

The agent is the scripted fake runtime: no live Claude check was chosen. The Claude path is covered by the adapter routing test through the bridge.

## Automated checks
- [ ] `packages/tools/tests/test_list_files.py`: every 1.1 `list_files` case passes through an MCP `Client`. That covers depth, `.git` skipped, truncation, bad arguments, and `/etc`, `../..`, drive/UNC and symlink escapes refused.
- [ ] `packages/tools/tests/test_read_file.py`:
  - Reads numbered lines, and a line range.
  - `end_line` past EOF is fine.
  - It refuses a directory, a missing file, a binary file and every path-escape case, including a symlink out of the repo (Linux only).
  - It truncates at the line and byte caps with a note.
  - Its errors name no host path.
- [ ] `packages/tools/tests/test_search.py`:
  - Fixed-string and regex search, and case-insensitive search.
  - The `path` scope is respected.
  - `.git` and binary files are skipped.
  - Hits and line lengths are capped with a note.
  - A pattern containing `'; rm -rf / #` or `$(…)` is matched literally and runs nothing.
  - A path escape is refused.
- [ ] `packages/tools/tests/test_mcp_bridge.py`:
  - Definitions are prefixed `repo.*` and carry the server's schemas, including `examples`.
  - `isError` maps to `is_error=True`.
  - An unknown tool and a raised exception become error outputs.
  - `ClaudeRuntime` with a stubbed client calls `repo__read_file` and receives the file text as a `tool_result`.
- [ ] Docker variants of the three tool suites (marker `integration`, skipped without a daemon) pass against `alpine:3.20` with network `none`.
- [ ] `packages/runtime/tests/test_fake_runtime.py`: an unscripted node calls tools with the schema's first example, or `{}` when there is none.
- [ ] `packages/engine/tests/test_spec.py`: `ask-repo.json` validates.
- [ ] Worker tests:
  - A repo run on the fake sandbox goes through the MCP bridge.
  - The MCP client closes before the sandbox, including when the run fails or is cancelled.
  - The Done-when Docker test passes.
- [ ] `agentic_sandbox` no longer exports `SandboxTools`, and no import of it remains (`rg SandboxTools` is empty).
- [ ] `ruff`, `pyright` strict and every existing test (1.1 included) are green.

## Manual / demo checks
- [ ] `docker compose up --build`, then `python scripts/sandbox_demo.py --spec packages/engine/tests/fixtures/specs/valid/ask-repo.json` streams:
  1. `run_started` and `node_started`;
  2. `tool_call` for `repo.list_files`, then a `tool_result` that includes `packages/`;
  3. `tool_call` for `repo.read_file` on `pyproject.toml`, then a numbered `tool_result` that lists the workspace members;
  4. `tool_call` for `repo.search`, then a `tool_result` with `path:line:` hits;
  5. `message`, `node_completed` and `run_completed`.
- [ ] `docker ps -a --filter label=agentic.run_id` is empty after the run.
- [ ] The 1.1 demo (`sandbox_demo.py` with no `--spec`) still behaves as before.
- [ ] The worker logs show no file contents beyond the existing event logging, and no host paths in tool errors.

## Merge criteria
- [ ] All checks above pass in CI, including the compose job with both the 1.1 and the 1.2 demo steps.
- [ ] README updated: the three tools, their limits, the MCP architecture and the demo command.
- [ ] `specs/roadmap.md` 1.2 is marked done by the implementing PR (`complete-phase`).
- [ ] No new network access from the sandbox, and no secrets or host paths in tool output or logs.
