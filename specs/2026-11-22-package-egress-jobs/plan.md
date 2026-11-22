# Plan: Package egress for build and test jobs

Each group leaves `main` working: NuGet keeps working after group 2, and the tool only appears in group 5.

## 1. Spike: what each package manager really needs

- [ ] Build throwaway proxies from `packages/egress-proxy` with a wide-open allow file and `LogLevel Info`. Then restore sample repos through them, one per manager: npm, pnpm, yarn 1, yarn 4 (PnP and `node-modules`), uv.lock, requirements.txt, poetry. Use real small public repos, including one with a native module (e.g. `esbuild`, `sharp`) and one with a compiled wheel (e.g. `pydantic-core`, `numpy`).
- [ ] Record every host each manager contacts. Then narrow each allow file to those hosts and run the samples again.
- [ ] Settle the exact commands:
  - Restore: scripts off, wheels only (`uv sync --frozen --no-install-project --no-build`, plus the build-system's requirements), with the platform config and the repo's sources ignored.
  - Offline build: `<manager> rebuild`, `run build`, and `uv sync --frozen --offline`.
- [ ] Run the samples on Alpine and on Debian-slim. Count the modules that fail only because of musl (no wheel or prebuilt binary), then decide: keep the sandbox image, or add a job image for Node and Python.
- [ ] Choose how to handle poetry: run poetry, or read `poetry.lock` ourselves into uv requirements. Check that `requires-plugins` would otherwise run.
- [ ] Write the results to `specs/2026-11-22-package-egress-jobs/findings.md`: hosts, commands, image size, and the musl/glibc and poetry decisions. Add the rows to the tech-stack decisions log.

## 2. One network and proxy per registry (NuGet moved onto it)

- [ ] `packages/sandbox/src/agentic_sandbox/protocol.py`: `JobNetwork = Literal["none", "nuget", "npm", "pypi"]`; update the `job_networks` docstring.
- [ ] `docker_backend.py`: replace `NugetEgress` with `RegistryEgress(network, proxy_url)` and a `Mapping[JobNetwork, RegistryEgress]`. A job on a registry network gets that network and `HTTPS_PROXY`, and nothing else. Do the same in `fake.py`.
- [ ] `packages/worker/src/agentic_worker/main.py`: read the settings `sandbox_{nuget,npm,pypi}_{network,proxy}`. A registry turns on only when both are set.
- [ ] `packages/egress-proxy/`: one `tinyproxy.conf` and allow file per registry (`nuget.conf` + `nuget.allow`, `npm.*`, `pypi.*`), using the hosts from group 1. The image's default `CMD` stays NuGet's, so existing deployments are unchanged.
- [ ] `docker-compose.yml`: add `egress-proxy-npm` and `egress-proxy-pypi` (same image, `command: [... -c /etc/tinyproxy/npm.conf]`) and the internal networks `agentic-npm` and `agentic-pypi`, and set the worker's variables.
- [ ] Tests:
  - `packages/sandbox/tests/test_docker_jobs.py`: extend it for the new networks.
  - Unit tests for the egress mapping and the worker settings.
  - The 4.8 tests (`test_scan_dotnet.py`, `test_scan_dotnet_docker.py`) still pass unchanged.

## 3. Toolchains in the sandbox image (or the job image)

- [ ] `packages/sandbox/Dockerfile` (or a new `packages/sandbox/build.Dockerfile` if group 1 chose glibc):
  - Node 22 LTS, npm, pnpm, yarn 1 and yarn 4, Python 3.12, uv, and poetry if kept.
  - Each is a pinned version checked against its sha256 or an image digest (amd64 and arm64), as the scanners are.
  - Corepack's downloads are off (`COREPACK_ENABLE_NETWORK=0`).
- [ ] `/opt/build/`: the platform's `npmrc`, `yarnrc.yml` and `uv.toml`, each pointing at the registry only.
- [ ] If a job image was chosen: `run_job` takes `image=`, the worker reads `SANDBOX_BUILD_IMAGE`, and the sweep's label covers it.
- [ ] Record the image size(s) in tech-stack → Sandbox.

## 4. Restore and offline build (`agentic_tools.build`)

- [ ] `build/stack.py`: per module (reusing `agentic_tools.repo.stack`), pick the ecosystem, the manager and the lockfile. Tell yarn classic from berry by the lockfile's `__metadata`. Read `packageManager`, `engines` and `requires-python` to produce the `needs …` reasons.
- [ ] `build/workdir.py`:
  - Copy the module to a work directory under staging, leaving out `.git`, `node_modules`, `.venv`, `dist` and `build`.
  - Drop `.npmrc`, `.yarnrc`, `pip.conf` and `uv.toml`.
  - Rewrite `.yarnrc.yml` and `[tool.uv]` down to the layout keys from group 1.
  - Refuse `yarnPath`.
- [ ] `build/node.py` and `build/python.py`: the restore job script (registry network) and the build job script (`none`), using the per-run caches under `/workspace/.cache/<manager>`. Map the exit codes and log patterns to the fixed reasons. A poetry lock is converted here if group 1 chose that.
- [ ] `build/report.py` + `schemas/build.v1.json`: the build report (`checks`, `counts`), defined in `agentic_runtime` beside the findings model if the engine needs to read it.
- [ ] `BuildLimits` (copy 120 s, restore 300 s, build 600 s). Remove the work directory in a `finally`.
- [ ] Unit tests on `FakeSandbox` (`packages/tools/tests/test_build.py`): one per manager's detection, and one per fixed reason, including "not configured" when the registry's network is missing and "no lockfile".

## 5. `build.restore` for tool nodes

- [ ] `build/server.py`: `build_build_server(sandbox, limits)`. `build.restore {path?, ecosystems?}` returns the report as structured data, with strict arguments (`strict_tool`).
- [ ] `packages/engine/src/agentic_engine/spec/models.py`:
  - `BUILD_TOOLS = frozenset({"build.restore"})`; add `"build."` to `REPO_TOOL_PREFIXES`.
  - Validation refuses a build tool on an agent, a hub, a classifier or a reduce agent (a new issue code, e.g. `tool_node_only`), the same way publish tools are refused.
- [ ] Node manifest and palette (5.3): `build.restore` is listed for tool nodes with its parameters, so no frontend change is needed. Check that the side panel renders it.
- [ ] Worker: open the `build` server for runs whose spec names it, beside `scan`.
- [ ] Tests:
  - Engine validation: `build.restore` is accepted on a tool node and refused on an agent.
  - A sequence with a `build.restore` tool node writing `build.json` runs end to end on `FakeSandbox`.

## 6. Docker integration tests

- [ ] Fixtures under `packages/tools/tests/fixtures/build/`: a small Node repo (pnpm lockfile, a native dependency, a `postinstall` that tries `fetch("https://example.com")`, and a `build` script) and a small Python repo (`uv.lock` with a compiled wheel and the repo's own package).
- [ ] `packages/tools/tests/test_build_docker.py` (`pytestmark = pytest.mark.integration`). It builds the sandbox and proxy images if the daemon lacks them, as `test_scan_dotnet_docker.py` does. It checks that:
  - both fixtures restore and build;
  - the postinstall's `fetch` fails, because the build job has no network;
  - a `curl https://github.com` in an `npm` job and a `curl https://pypi.org` in an `npm` job are both refused, and appear in that proxy's log.
- [ ] Add the new proxy configs to `ci.yml`'s egress-proxy build step if needed.

## 7. Specs, docs and changelog

- [ ] `specs/tech-stack.md`:
  - Sandbox: "Package egress (13.2)" replaces "NuGet egress (4.8)" as the general rule, with NuGet as one registry. Add the toolchains in the image.
  - Tool layer: `build.restore` and its report.
  - Decisions log: rows for one network per registry, no repo code while online, the tool-node-only rule, musl or glibc, and poetry.
- [ ] `docs/security/security-model.md` (egress per registry, what can and cannot leave), `docs/operations/deployment.md` and `configuration.md` (the new proxies and variables).
- [ ] `specs/roadmap.md`: add the plan link on 13.2's row. `CHANGELOG.md`: an entry under `## [Unreleased]`.
