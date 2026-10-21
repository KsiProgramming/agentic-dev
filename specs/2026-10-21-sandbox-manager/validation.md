# Validation: Sandbox manager

## Done when (from roadmap)
> An agent can list files in a cloned repo inside the container

To check this: a run started with `POST /runs` and a `repo` streams a `tool_call` for `repo.list_files` and a `tool_result` listing the repo's files. The files were read from inside a Docker container that no longer exists after the run.

## Automated checks
- [ ] `packages/sandbox/tests/test_fake_sandbox.py`:
  - Open, exec and close. The temp dir is removed after success, after an exception and after cancellation.
  - A bad repo URL or ref raises `SandboxError`.
- [ ] `packages/sandbox/tests/test_source.py`:
  - `RepoSource` accepts a local path, `file://` and `https://`.
  - It rejects `ssh://`, `git@…`, an empty URL and option-like values (`--upload-pack=…`).
- [ ] `packages/sandbox/tests/test_tools.py`: `repo.list_files`
  - Lists the fixture files and respects `max_depth`.
  - Excludes `.git`.
  - Rejects `/etc` and `../..` with `is_error`.
  - Truncates at 1,000 entries with a note.
- [ ] `packages/sandbox/tests/test_docker_sandbox.py` (marker `docker`, runs in CI on `ubuntu-latest`):
  - Clone and list files inside the container.
  - The container is removed after `open` exits, including on error.
  - `wget`/`nc` to an external host fails (no network).
  - Writing to `/` fails (read-only root).
  - The process runs as a non-root user.
  - `sweep_orphans` removes a labelled leftover container.
- [ ] `packages/runtime/tests/test_fake_runtime.py`: a `CallTool` step emits `tool_call` then `tool_result`, and `check_events` passes.
- [ ] `packages/runtime/tests/test_claude_runtime.py`: a mocked `tool_use` for `repo__list_files` is routed to a `ToolExecutor` and its result is sent back.
- [ ] `packages/api/tests/test_runs.py`:
  - `POST /runs` with `repo` stores it.
  - A spec that uses a `repo.*` tool without `repo` returns `422`.
  - Migration `0004` upgrades and downgrades.
- [ ] Worker test (fake sandbox and fake runtime):
  - A run with a repo produces `tool_result` events containing the fixture file names, and the sandbox is closed.
  - A failing clone gives `run_failed` with no host path in the event.
- [ ] `ruff`, `pyright` strict and the existing tests are green. The compose smoke job is still green with the socket mount.

## Manual / demo checks
- [ ] `docker compose up --build` starts all services. The worker logs `worker ready` and sweeps any orphans.
- [ ] Run the demo with `FAKE_SCRIPT=list_files`:
  ```bash
  curl -s -X POST localhost:8000/runs -H 'content-type: application/json' \
    -d '{"workflow": <one agent node with tools ["repo.list_files"]>, "repo": {"url": "/samples/hello-repo"}}'
  curl -N localhost:8000/runs/<id>/events
  ```
  The expected stream is `tool_call` for `repo.list_files`, then `tool_result` with `README.md`, `src/…`, then `run_completed`.
- [ ] While the run is paused (`FAKE_STEP_DELAY_S=2`), `docker ps --filter label=agentic.run_id` shows one container. After the run it shows none.
- [ ] The run page in the browser (0.8) shows the same `tool_call`/`tool_result` events.
- [ ] Optional: with `AGENTIC_RUNTIME=claude` and a key set, an agent asked "What files are in this repo?" calls `repo.list_files` and names them. This is documented but not a merge gate.

## Merge criteria
- [ ] All automated checks above pass in CI, including the `docker`-marked tests.
- [ ] The README "Sandbox" section and the CHANGELOG are updated.
- [ ] No host paths, stack traces or secrets appear in run events or logs.
- [ ] Roadmap phase 1.1 is marked done in the implementing PR (`complete-phase`).
