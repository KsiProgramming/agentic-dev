# Validation: Package egress for build and test jobs

## Done when (from roadmap)

> A Node and a Python repo restore their packages in a job and build with no network after it; a request to any other host is refused and logged

## Automated checks

- [ ] **Egress per registry** (`packages/sandbox/tests/test_docker_jobs.py`, unit tests for the worker settings):
  - a job on `npm`, `pypi` or `nuget` gets that network and its proxy only;
  - a registry whose two variables are not both set is missing from `job_networks`;
  - the NuGet variables keep their names and behaviour.
- [ ] **Detection** (`packages/tools/tests/test_build.py`):
  - each lockfile maps to its manager: npm, pnpm, yarn classic, yarn berry, uv, poetry, requirements;
  - a Node module with no lockfile is `skipped: no lockfile`;
  - a pyproject-only module is restored with uv.
- [ ] **Fixed reasons** (`test_build.py`, `FakeSandbox`): each reason in requirements.md comes from a scripted job result, never the tool's own words. That covers: not on the registry, git/URL dependency, no wheel for this platform, out-of-date lockfile, `needs Node/Python/<manager>`, vendored yarn, restore/build timeouts, `build failed (exit N)`, and not configured.
- [ ] **Repo sources ignored** (`test_build.py`):
  - the work copy has no `.npmrc`, `.yarnrc`, `pip.conf` or `uv.toml`;
  - `.yarnrc.yml` and `[tool.uv]` keep only the layout keys;
  - a `yarnPath` is refused.
- [ ] **Scripts off while online**:
  - the restore job's argv carries `--ignore-scripts` (or `enableScripts: false`) and `--no-build`;
  - the build job's network is `none`.
- [ ] **Tool-node only** (engine validation tests):
  - `build.restore` validates on a tool node;
  - it is refused on an agent, a hub, a classifier and a reduce agent, with the new issue code;
  - `build.restore` needs a repo.
- [ ] **End to end on the fake sandbox**: a sequence with a `build.restore` tool node writes `build.json` as a run artifact, and the report matches `schemas/build.v1.json`.
- [ ] **Docker integration** (`packages/tools/tests/test_build_docker.py`, marked `integration`):
  - the Node fixture restores through the npm proxy and builds offline (native module rebuilt, `build` script run);
  - the Python fixture restores through the PyPI proxy (compiled wheel included) and installs its own package offline;
  - the Node fixture's `postinstall` `fetch` fails in the build job (no network);
  - from an `npm` job, `https://github.com` and `https://pypi.org` are refused, and each refused host is in the proxy's log.
- [ ] **No regression**: `test_scan_dotnet.py` and `test_scan_dotnet_docker.py` pass unchanged on the reworked egress.
- [ ] `uv run ruff check`, `ruff format --check`, `pyright` (strict), and the JSON Schema export check for `build.v1.json`.

Run the sandbox tests by file (`test_docker_jobs.py`), never the whole `packages/sandbox/tests` folder: its sweep test removes the local stack's sandboxes.

## Manual / demo checks

- [ ] `docker compose up --build`. Then `docker compose logs egress-proxy-npm egress-proxy-pypi` shows the refused hosts from the integration run, and `docker network inspect agentic-npm` shows the network as internal, with only the proxy and job containers on it.
- [ ] The spike's `findings.md` is written. Its musl-or-glibc and poetry decisions are reflected in the decisions log.

## Merge criteria

- [ ] All checks above pass in CI, the `integration` job included.
- [ ] tech-stack (Sandbox, Tool layer, decisions log), `docs/security/security-model.md`, `docs/operations/deployment.md` and `configuration.md` describe the per-registry egress and `build.restore`. The 13.2 roadmap row links this plan, and `CHANGELOG.md` has an entry under `## [Unreleased]`.
- [ ] The new sandbox (or job) image size is recorded in tech-stack.
- [ ] No token, registry credential or repo config value appears in a job's logs or in the build report.
- [ ] No real Claude run is required: no agent receives anything new (lessons, rule 1). The PR says so, and 13.3 carries the real run.
