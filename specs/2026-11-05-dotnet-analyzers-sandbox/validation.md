# Validation: .NET analyzers in the sandbox

## Done when (from roadmap)

> An audit of a .NET repo reports analyzer findings instead of "no supported linter for dotnet"

Checkable form: an `audit-codebase` run with `checks: lint` on a public .NET repo that uses NuGet packages has a `findings.json` with `tool: "dotnet"` findings and a `ran` check per C# module. No check reads `no supported linter for dotnet`, and `report.md` lists the findings. The restore's only outbound connections went to NuGet hosts.

## Automated checks

- [x] **Stack and planning** (`test_scan_stack.py`):
  - a C# module with `linters: auto` gets the `dotnet` linter;
  - `.editorconfig` or `Directory.Build.props` analysis settings give `config: "repo"`, none gives `platform-default`;
  - F# and VB modules are skipped with their reason;
  - an explicit `linters: ["ruff"]` does not run `dotnet`, and `["dotnet"]` on a repo with no C# reports it skipped;
  - `test_list_modules.py` stays green.
- [x] **Normalising** (`test_scan_dotnet.py`), from recorded SARIF:
  - error → `medium`, warning → `low`, note → `info`; hidden (`none`), suppressed, location-less and `bin/`/`obj/` results dropped;
  - paths are repo-relative (URI-decoded, the work directory's prefix removed), and paths outside the copy are dropped;
  - `rule`, `message` and `help_url` (from the rule's `helpUri`) come from the log; a fingerprint is set;
  - compiler errors are counted, not reported.
- [x] **MSBuild errors** (`test_scan_dotnet.py`): each code maps to its fixed reason (NU1101, NU1301, other NU, NETSDK1045, NETSDK1147 with only workload ids taken from the text), a codeless error is "restore failed"/"build failed", and an error is attributed to the project it names (NuGet's file, else MSBuild's bracket).
- [x] **Engine on a scripted sandbox** (`test_scan_dotnet.py`):
  - findings land on their module, a finding in two logs (two target frameworks) is listed once, and findings outside the `path` asked for are left out;
  - the restore job runs on `nuget` with the platform's `nuget.config`, the build on `none` with `--no-restore` and `scan.targets`;
  - a package not on nuget.org, a missing workload and a compile failure fail only their module; a restore or build timeout, a restore with no error line, a failed copy and no project fail every module; a module with no log says so;
  - restore not configured gives `skipped: NuGet restore is not configured` and runs no job;
  - the work directory is removed in every case.
- [x] **Job containers** (`test_docker_jobs.py`, Docker):
  - a job works on the sandbox's files as the sandbox user, and is removed after success, failure and timeout (exit 124);
  - a job cannot change the checkout, and works only under the staging directory;
  - a `network="none"` job reaches nothing; with no proxy configured, a `nuget` job is refused;
  - discarding a run removes a job container it left behind (only that run's).
- [x] **Egress is NuGet only** (`test_docker_jobs.py`): a job on the NuGet network reaches `api.nuget.org` through the proxy, is refused `example.com` (logged by the proxy), and cannot reach anything around the proxy (no DNS, no route).
- [x] **Docker end to end** (`test_scan_dotnet_docker.py`, real image and a test egress proxy), on one .NET monorepo with a `global.json` pinned to SDK 8.0:
  - `clean`: `ran`, `platform-default`, built by SDK 10;
  - `warnings`: CA1822 (twice) and CA2201 (no code fix) at the `.editorconfig` severity, the `#pragma`-suppressed one absent, `config: "repo"`;
  - `packages` (net8.0 and net10.0, StyleCop from nuget.org): `SA*` findings, each once;
  - `feed` (a package only its own `nuget.config`'s feed has): `failed: restore failed: a package is not on nuget.org`, and that feed's host never contacted;
  - `broken`: `failed: does not compile (1 error)`, no findings;
  - `fsharp`: `skipped: no supported linter for fsharp`;
  - the checkout has no `bin/` or `obj/` and the staging directory is empty after;
  - `path` narrows the build's findings to that part; without a proxy, .NET is skipped with its reason.
- [x] **Audit template** tests (`test_audit_template.py`) and the engine scan flow (`test_scan_flow.py`) pass unchanged.
- [x] `uv run ruff check`, `uv run ruff format --check`, `uv run pyright` (strict), and `uv run pytest` on every package, locally.
- [x] `scripts/check_roadmap.py` passes. `schemas/` exports are in sync if the `linters` enum is part of an exported schema.
- [ ] **CI:** the sandbox image builds for `linux/amd64` and `linux/arm64` (both SDK digests verified), and the existing CI jobs are green.

## Manual / demo checks

- [ ] `docker compose up` with the egress proxy. Build the image with `docker build -t agentic-dev/sandbox:dev packages/sandbox`, and record its size in tech-stack (1.16 GB).
- [ ] From the UI, start "Audit codebase" with `checks: lint` on a public .NET repo with `PackageReference`s (chosen in the spike, for example a mid-size library with an `.editorconfig`). Expect:
  - the step's Findings view lists `dotnet` findings with rule links;
  - the "Checked" grid shows each C# module `ran`, with "repo config" or "platform default";
  - `report.md` includes them.
- [ ] The proxy's log for that run shows only NuGet hosts.
- [ ] A writer workflow on the same repo afterwards: its gate's diff shows no `bin/`, `obj/` or `.scan/` files.
- [ ] Remember: the Docker sandbox tests sweep run sandboxes. Run them when no dev run you care about is live.

## Merge criteria

- [ ] All automated checks above pass locally. The CI image build and the existing CI jobs are green.
- [ ] The spike's outcome is recorded: decisions-log rows (engine, egress for restore, job containers, SDK pinning), and the open questions in `requirements.md` resolved.
- [ ] `specs/tech-stack.md` (Scanners, Sandbox), the security model, deployment and architecture docs describe the NuGet-only egress and that repo code runs at restore/build time.
- [ ] No credentials or proxy secrets in job containers, logs or events. Tool output reaches the report only as normalised findings and fixed reasons.
- [ ] `CHANGELOG.md` has an entry under `## [Unreleased]`. The roadmap row is reworded if the engine changed, and 4.8 is marked done by CI on the PR.
