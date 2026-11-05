# Plan: .NET analyzers in the sandbox

Spike first, then bottom-up: image, then job containers and egress, then stack and normalising, then the audit and docs. The project stays green after each group. Until group 4 lands, `.NET` modules stay `skipped`, as today.

## 1. Spike: engine, limits and SDK pinning (no product code merged)

- [x] Build a throwaway image `FROM mcr.microsoft.com/dotnet/sdk:10.0-alpine` with the sandbox's user and hardening. Run it on three fixture repos (group 4's fixtures, drafted here), read-only root, uid 1000, all state under a volume.
- [x] On each, run both engines:
  - `dotnet build -p:ErrorLog=out.sarif%2Cversion=2.1 -p:EnableWindowsTargeting=true --no-restore`
  - `dotnet format analyzers --verify-no-changes --no-restore --report out/`
- [x] Compare which diagnostics each reports (with and without a code fix, `.editorconfig` severities, analyzer packages such as StyleCop), plus time and peak memory.
- [x] Try a `global.json` pinned to 8.0.x: what fails, and whether analysing with SDK 10 (`global.json` removed) changes the diagnostics.
- [x] Measure per-solution against per-project builds on a sample with three projects.
- [x] Write the outcome into `requirements.md` (resolve the open questions) and a decisions-log row in `specs/tech-stack.md`: the engine, the SDK-pinning rule, the solution/project rule and the job limits. If the engine is not `dotnet format`, reword the 4.8 row in `specs/roadmap.md`.

## 2. .NET SDK in the sandbox image

- [x] `packages/sandbox/Dockerfile`:
  - a `dotnet` stage `FROM mcr.microsoft.com/dotnet/sdk:10.0-alpine@sha256:…`, pinned per arch, then `COPY --from` `/usr/share/dotnet` into the final image;
  - add the runtime prerequisites (`icu-libs`, `libstdc++`, `libgcc`), or invariant globalization if the spike shows ICU is not needed;
  - `ENV`: `DOTNET_CLI_TELEMETRY_OPTOUT=1`, `DOTNET_NOLOGO=1`, `DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1`, `DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE=1`, `DOTNET_GENERATE_ASPNET_CERTIFICATE=false`; `DOTNET_CLI_HOME` and `NUGET_PACKAGES` under `/workspace/.scan/`.
- [x] `packages/sandbox/scan/nuget.config`: `<clear/>` plus nuget.org only, installed at `/opt/scan/nuget.config`.
- [x] `_VERSIONS_SCRIPT` (`scan/server.py`) also prints `dotnet --version`.
- [x] Record the new image size in tech-stack → Sandbox (today about 510 MB).
- [x] CI: the existing `Build the sandbox image` step keeps working (amd64). Add the multi-arch build check (group 6).

## 3. Job containers and the NuGet egress proxy

- [x] `agentic_sandbox.protocol`: `Sandbox.run_job(argv, *, network: Literal["none", "nuget"], limits: JobLimits, workdir) -> ExecResult`; `JobLimits` (memory, cpus, timeout_s, pids) with defaults from the spike.
- [x] `docker_backend.py`: create the job container from the same image on the run's volume, with the same hardening as `_create`. Attach it to `network_mode="none"` or the proxy's internal network, wait with a timeout, then always remove it. The sweeper also removes job containers (by `RUN_LABEL`). Add a Fake backend implementation for unit tests.
- [x] Egress proxy: `packages/egress-proxy/` (a small, pinned forward proxy image with a hosts allowlist: `api.nuget.org` and the package CDN hosts the spike observed) and a compose service on an `internal: true` network (`agentic-nuget`) with no other members. The proxy's own outbound route is the only way out. Refused `CONNECT`s are logged with the host.
- [x] Settings: `SANDBOX_NUGET_NETWORK` and `SANDBOX_NUGET_PROXY` (`http://egress-proxy:3128`). If they are unset, restore is unavailable and .NET checks are `skipped: NuGet restore is not configured`.
- [x] Tests: `test_docker_sandbox.py` (a job container is removed after success, failure and timeout, and runs with no network when `network="none"`); a fake-backend unit test.

## 4. Stack detection, planning and the `dotnet` lint engine

- [x] `agentic_tools.repo.stack`: also record `*.sln`/`*.slnx` (for grouping) and mark `*.fsproj`/`*.vbproj` modules. Keep `repo.list_modules` output compatible (`test_list_modules.py`).
- [x] `agentic_tools.scan.stack`:
  - `Linter` gains `"dotnet"` and `Language` gains `"csharp"` (`.cs`); remove `dotnet` from `_UNSUPPORTED_KINDS`;
  - config detection (`repo` / `platform-default`), using the rules in requirements;
  - F#/VB skipped;
  - grouping by solution, if the spike chose it.
- [x] `agentic_tools.scan.dotnet` (new):
  - `DOTNET_PREP_SCRIPT` copies the module or solution to `/workspace/.scan/dotnet/<id>/` (excluding `bin/`, `obj/` and `.git`) and applies the SDK-pinning rule;
  - restore through `run_job(network="nuget")` with `--configfile /opt/scan/nuget.config`;
  - analyse through `run_job(network="none")` with the chosen engine;
  - map restore and build outcomes to the fixed reasons (`NU1301` → source not reachable, `NETSDK1147` → workload, …);
  - clean the copy up.
- [x] `agentic_tools.scan.normalise`: `sarif_findings` (or `dotnet_format_findings`) with repo-relative paths, the severity mapping, hidden diagnostics dropped, `help_url`, and fingerprints through `with_line_texts`.
- [x] `scan/server.py`: `_lint_one` dispatches `dotnet`. The `linters` description, the schema enum and the module docstring gain .NET.
- [x] Fixtures under `packages/tools/tests/fixtures/dotnet/`:
  - `clean` (no warnings);
  - `warnings` (`.editorconfig` raising CA1822 and IDE0005, plus one diagnostic with no code fix);
  - `packages` (a `PackageReference` to StyleCop.Analyzers, `net8.0`);
  - `private-feed` (`nuget.config` with an unreachable source and a package only there);
  - `fsharp`.
- [x] Unit tests: `test_scan_stack.py` (planning, config detection, F#) and `test_scan_server.py` (recorded SARIF or report JSON → findings, severities, paths, hidden dropped; on the fake sandbox, a restore failure and a timeout are checks with their reason, and the other engines still report).

## 5. Audit, specs and docs

- [x] `agentic_engine.templates.audit`: no flow change. Check the template's tests still pass and that the description of `checks: lint` mentions .NET, if it lists stacks.
- [x] `specs/tech-stack.md`:
  - Tool layer → Scanners: the `dotnet` linter, the config rule, the reasons, and `linters` gaining `dotnet`; remove .NET from the skipped stacks;
  - Sandbox: the SDK, job containers, the NuGet proxy, and the image size;
  - decisions log rows for the requirements' decisions.
- [x] `docs/architecture/decisions.md` (the sandbox-egress consequence now has the NuGet exception), `docs/security/security-model.md` (repo MSBuild and analyzer code runs in job containers; NuGet-only egress; what an attacker could reach), `docs/operations/deployment.md` (the proxy service, the internal network, image size, job limits) and `docs/architecture/overview.md` (diagram edge for NuGet egress).
- [x] `CHANGELOG.md` entry under `## [Unreleased]`.

## 6. End-to-end proof and CI

- [x] Docker tests (`test_scan_docker.py`, marked like the existing ones) on the fixtures through the real image, compose proxy and job containers (expected results in `validation.md`).
- [x] Egress test: a restore job that tries `https://example.com` (a fixture `nuget.config` source the platform overrides, plus a direct `curl` in a job on the NuGet network) is refused and logged by the proxy.
- [x] CI: build the sandbox image for `linux/amd64` and `linux/arm64` (buildx, GHA cache) so both SDK digests are checked. Keep it to the build: Docker tests stay local.
- [ ] Demo: audit a real public .NET repo from the UI (`audit-codebase`, `checks: lint`). Note the run id and the finding counts for the PR.

## As built

Where the work departed from the plan above:

- **Engine (group 1):** `dotnet build` with SARIF logs, not `dotnet format` (decisions log, ".NET analyzer engine (4.8)"). The spike also found that MSBuild's worker nodes hang with `TMPDIR` on the run's volume, so jobs get their own writable `/tmp` tmpfs (`JobLimits.tmp`).
- **Platform files (group 2):** `nuget.config` and `scan.targets` live in `/opt/scan/dotnet/`. The proxy needs only `api.nuget.org`: package signatures are checked with revocation offline.
- **Job API (group 3):** `run_job(argv, *, network, cwd, timeout_s, env)` plus `job_networks`; limits are the manager's (`JobLimits`), not per call. `Worktree` delegates both. The egress proxy is excluded from the uv workspace (`packages/egress-proxy` is not a Python package). Job tests are in `packages/sandbox/tests/test_docker_jobs.py`. The sweep test only discards its own run, never the host's sandboxes.
- **Stack (group 4):** the engine builds one generated solution of the modules' C# projects, so the repo's own `*.sln`/`*.slnx` are not recorded. `*.fsproj`/`*.vbproj` are .NET manifests; a .NET module without a `*.csproj` is skipped as `fsharp`/`vb`. The dispatch is in `lint` (all C# modules in one build), not `_lint_one`. The fixtures are inline in the tests (`test_scan_dotnet_docker.py`), and the engine's unit tests are in `test_scan_dotnet.py`.
- **CI (group 6):** a `sandbox-arm64` job builds the sandbox image for arm64 and the egress proxy for both architectures. The amd64 image is still built and tested by the Python job, whose `pytest` now includes the .NET Docker tests (they restore from nuget.org).
