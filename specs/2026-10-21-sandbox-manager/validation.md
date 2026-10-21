# Validation: Sandbox manager

## Done when (from roadmap)
> An agent can list files in a cloned repo inside the container

To check this: a run started with `POST /runs` and a `repo` streams a `tool_call` for `repo.list_files` and a `tool_result` listing the repo's files. The files were read from inside a Docker container that no longer exists after the run. The proof is in two places:
- `packages/worker/tests/test_worker.py::test_done_when_an_agent_lists_files_in_a_cloned_repo_inside_a_container`, a real Docker sandbox driven by the worker.
- The CI smoke job's "Sandbox demo (phase 1.1)" step, which runs the full compose stack.

## Automated checks
- [x] `packages/sandbox/tests/test_fake_sandbox.py`:
  - Open, exec and close. The temp dir is removed after success, after an exception and after cancellation.
  - A bad repo raises `SandboxError`.
  - Commands time out.
- [x] `packages/sandbox/tests/test_source.py`:
  - `RepoSource` accepts `https://` and local paths.
  - It rejects `ssh://`, `git@…`, `http://`, `file://`, `ext::`, an empty URL, URLs with credentials, and option-like values.
  - Local paths outside the allowed root are refused.
  - A failed clone's error names no host path.
- [x] `packages/sandbox/tests/test_tools.py`: `repo.list_files` on the fake and Docker backends
  - Lists the fixture files and respects `max_depth`.
  - Excludes `.git`.
  - Rejects `/etc`, `../..`, drive and UNC paths, and symlinks out of the repo (Linux only).
  - Truncates with a note.
  - Reports bad arguments.
  - `ClaudeRuntime` routes `repo__list_files` to it.
- [x] `packages/sandbox/tests/test_docker_sandbox.py` (marker `integration`, skipped without a daemon):
  - Clone and list files inside the container.
  - The container and volume are removed after `open` exits, including on error and after a failed clone.
  - The container has no network (only `lo`, `wget` fails).
  - The root is read-only and the clone too.
  - The process runs as uid 1000.
  - Commands time out.
  - `sweep_orphans` removes a labelled leftover.
- [x] `packages/runtime/tests/test_fake_runtime.py`:
  - `CallTool` steps emit `tool_call` then `tool_result`.
  - Errors become error results.
  - With no executor, the run fails.
  - Unscripted nodes call their requested tools only when tools are set.
- [x] `packages/engine/tests/test_run_events.py`: `record_unstarted_run` writes `run_started` then `run_failed`/`run_cancelled`.
- [x] `packages/api/tests/test_runs.py`:
  - `POST /runs` with `repo` stores it.
  - A spec that uses a `repo.*` tool without `repo` returns `422`.
  - Unsafe repos return `422`.
- [x] `packages/api/tests/test_migrations.py`: head is `0004_run_repo`, it downgrades and upgrades, and the models match.
- [x] Worker tests:
  - A run with a repo (fake sandbox) produces a `tool_result` with the fixture files, and the sandbox is removed.
  - A failing clone gives `run_started` + `run_failed` with no host path, and the worker carries on.
  - The Done-when test on Docker passes.
  - Sandbox settings come from the environment.
  - `SANDBOX_BACKEND=docker` without Docker fails fast.
- [x] `ruff`, `pyright` strict and the existing tests are green.
- [ ] CI is green, including the compose smoke job with the sandbox demo.

## Manual / demo checks
- [x] `docker compose up --build` starts all services, and the worker reports ready.
- [x] `python scripts/sandbox_demo.py` (or the `curl` in the README) streams:
  1. `run_started` and `node_started`;
  2. `tool_call` for `repo.list_files`;
  3. `tool_result` listing this repo (`.claude/`, `CHANGELOG.md`, `packages/`, `pyproject.toml`, …);
  4. `message`, `usage`, `completed`, `node_completed` and `run_completed`.

  The worker logs `sandbox … ready` and `sandbox … removed`, and `docker ps -a --filter label=agentic.run_id` is empty afterwards.
- [ ] The run page in the browser (0.8) shows the same `tool_call`/`tool_result` events.
- [ ] Optional: with `AGENTIC_RUNTIME=claude` and a key set, an agent asked "What files are in this repo?" calls `repo.list_files` and names them. This is documented but not a merge gate.

## Merge criteria
- [ ] All automated checks above pass in CI, including the `integration` tests and the compose sandbox demo.
- [x] The README "Sandbox" section and the CHANGELOG are updated.
- [x] No host paths, stack traces or secrets appear in run events or logs.
- [ ] Roadmap phase 1.1 is marked done in the implementing PR (`complete-phase`).
