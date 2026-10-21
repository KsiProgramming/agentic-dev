# Plan: `repo` MCP server (read only) wired into the agent runtime

Order: server and tools on the fake sandbox first, then the bridge to `ToolExecutor`, then the worker wiring, then the demo. After each group the project builds, and the existing 1.1 demo still passes.

## 1. `agentic_tools` package with `list_files` over MCP
- [ ] Add `packages/tools` (`agentic_tools`, `py.typed`) to the `uv` workspace. It depends on `mcp>=2.3`, `agentic_sandbox` and `agentic_runtime`. Add it to the pyright and ruff configs and to the worker's dependencies.
- [ ] `agentic_tools/repo/paths.py`: move `repo_relative()` and the `cd -P` confinement shell snippet from `agentic_sandbox/tools.py`.
- [ ] `agentic_tools/repo/server.py`: `build_repo_server(sandbox, *, limits=RepoLimits())`, returning the SDK's high-level server (check the v2 class name with the docs when implementing), registering `list_files` with the 1.1 logic and schema. Add the `examples` entry to its schema.
- [ ] Move `packages/sandbox/tests/test_tools.py` to `packages/tools/tests/test_list_files.py`. Each case now calls the tool through `async with Client(build_repo_server(sandbox))`.
- [ ] Delete `agentic_sandbox/tools.py` and its export. Until group 3 the worker keeps a temporary import shim, so it still runs.

## 2. `read_file` and `search`
- [ ] `read_file`: confinement check, then `test -f`, a NUL check on the first 8 KiB (`head -c 8192 | tr -d '\000'` length compare), then `sed -n 'start,endp'` with numbering. Enforce the 2,000-line / 256 KiB cap in Python using the sandbox's `truncated` flag. Errors come back as MCP `isError` with a short message that names no host path.
- [ ] `search`: run grep in the sandbox with the pattern passed as `$1` (never interpolated), using `-F` unless `regex`, `-i` unless `case_sensitive`, line numbers, and skipping `.git` and binary files. Cap hits at `min(max_results, 500)` and lines at 300 characters, noting any truncation.
- [ ] Add a `RepoLimits` dataclass holding the caps, so tests can shrink them.
- [ ] Add an `examples` entry to each tool's input schema.
- [ ] Tests in `packages/tools/tests/test_read_file.py` and `test_search.py`, against the fake sandbox and the shared fixture repo.
- [ ] Docker variants marked `integration`. If busybox grep lacks a flag, apply the fallback recorded in the open questions.

## 3. MCP → `ToolExecutor` bridge and worker wiring
- [ ] `agentic_tools/mcp_bridge.py`: `McpToolExecutor(client, prefix)`. It lists the tools once, maps them to `ToolDefinition`s named `<prefix>.<name>` and maps `CallToolResult` to `ToolOutput`. An unknown name gives an error output, and an exception gives an error output with the exception type only.
- [ ] `agentic_tools/repo/__init__.py`: `open_repo_tools(sandbox) -> AsyncContextManager[ToolExecutor]`.
- [ ] Worker `main.py`: replace `SandboxTools(sandbox)` with `async with open_repo_tools(sandbox) as tools:`, nested inside the sandbox context. Remove the shim from group 1.
- [ ] Update the docstrings that mention "phase 1.2" (`agentic_runtime/tools.py`, worker module).
- [ ] Bridge tests: definitions, prefixing, error mapping, and `ClaudeRuntime` with a stubbed Anthropic client routing `repo__read_file` through the bridge to the server.

## 4. Fake runtime arguments, fixture and demo
- [ ] `agentic_runtime/fake.py`: a node with no script calls each requested tool with `input_schema["examples"][0]` if present, else `{}`. Update its docstring and add a test.
- [ ] Add the fixture `packages/engine/tests/fixtures/specs/valid/ask-repo.json`, which uses the three tools. Make sure the spec tests pick it up.
- [ ] `scripts/sandbox_demo.py`: add a `--spec` option. The default stays `list-repo-files.json`.
- [ ] Worker test `test_done_when_an_agent_answers_a_question_about_the_repo` (Docker, `integration`): an `ask-repo` run on this repo's `.git`. Its events hold `tool_result`s listing `packages/`, the root `pyproject.toml` contents naming the workspace members, and search hits, and the sandbox is gone afterwards.
- [ ] CI compose job: add a "Repo MCP demo (phase 1.2)" step that runs `sandbox_demo.py --spec ask-repo.json` and checks the three tool results and the absence of leftover containers.
- [ ] README: replace the single-tool paragraph with the three tools, their limits and the MCP architecture (in-process server per run, bridge). Add the new demo command.
