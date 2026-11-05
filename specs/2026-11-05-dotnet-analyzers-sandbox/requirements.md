# .NET analyzers in the sandbox

Roadmap phase: 4.8
Branch: plan/4.8-dotnet-analyzers-sandbox

## Context

A test audit (4.6) of a .NET repo skipped every module: `scan.lint` reports `skipped: no supported linter for dotnet`, because 4.4 shipped only linters that run offline as static binaries (ruff, Biome, ShellCheck). .NET is one of the most common stacks in the repos we audit, so the "Audit codebase" template is empty for them. 4.8 lints C#/.NET modules with the Roslyn analyzers, honouring the repo's own `.editorconfig` and analyzer packages.

What makes it more than one more linter:

- **Roslyn needs a restored project.** Analyzers run on a compilation, which needs the project's NuGet packages and, for any target framework other than the SDK's own, its reference packs. Both come from NuGet. The sandbox has no network (`network_mode="none"`; decisions log, "Dependency scanner (4.4)": "the sandbox has no network at run time"). The egress allowlist is phase 10.2.
- **Restore and build run repo code.** MSBuild evaluates the repo's targets and props, and analyzer packages are DLLs loaded into the compiler. ruff and Biome never execute repo code. That is acceptable only inside the sandbox, with no secrets, and is a new trust step that the security model must state.
- **The sandbox is sized for static binaries:** 512 MB of memory, 1 CPU, 120 s per engine, a 64 MB `noexec` `/tmp`, alpine (musl). A .NET restore and build need more.

Depends on 1.1 (sandbox), 4.4 (`scan` server, findings report, stack detection) and 4.6 (the audit template, which calls `scan.lint` with `linters: auto`). All are done. It pulls a NuGet-only slice of 10.2 (egress allowlist) forward; 10.2 keeps the general allowlist and gVisor/Firecracker.

Mission principles that drive it:

- **2, open but safe by construction:** the network is opened only for the restore, only to NuGet, through a proxy that refuses everything else. Analysis runs with no network.
- **5, repo content is data:** diagnostics are returned as data. Repo code that runs at restore or build time has no credentials and no route anywhere but NuGet.
- **Orchestration is open, never a fixed menu** (decisions log, "Who chooses the checks (4.4)"): `.NET` joins `auto` and the `linters` list. A run does only what its spec names.
- **4.4's rule "a linter we cannot run is skipped, never replaced"** stays: a .NET module we cannot restore or build is a skipped or failed check with its reason, never silently linted another way.

## Scope

### In scope

- **The .NET SDK in the sandbox image:** the current LTS SDK (.NET 10) for linux-musl, copied from Microsoft's pinned `sdk:*-alpine` image by digest (amd64 and arm64), with its prerequisites. Telemetry, first-run output and workload update checks are off. All dotnet and NuGet state lives in the job's work directory on the run's volume; only MSBuild's temp files use the job's own `/tmp`. Reference packs for older target frameworks (net6.0, net8.0, …) come from NuGet at restore time. One image for every deployment.
- **A NuGet-only egress proxy:** a small allowlisting forward proxy (`CONNECT` to port 443 of `api.nuget.org` only: the spike found no other host is needed) on an internal Docker network with no other route out. It is a compose service in dev and a documented component in `docs/operations/deployment.md`. Every refused connection is logged.
- **Restore and analysis in job containers:** each runs in a short-lived container from the sandbox image on the run's workspace volume, with the same hardening as the sandbox (uid 1000, read-only root, no capabilities, `no-new-privileges`) and its own limits:
  - *restore*: on the proxy's network only, with a platform `nuget.config` that clears the repo's sources and adds only nuget.org (default 2 GB, 2 CPUs, 300 s);
  - *analyse*: `network_mode="none"`, `--no-restore` (default 2 GB, 2 CPUs, 300 s).

  Both work on a throwaway copy of the module under `/workspace/.scan/`, so `obj/`, `bin/` and packages never touch the checkout or a writer's worktree. The run's main sandbox container is not changed. A `Sandbox.run_job(...)` method (protocol, Docker backend and fake) runs a job container; its limits are settings beside `SandboxLimits`.
- **The analyzer engine, chosen by a spike** (plan group 1): `dotnet build` with a SARIF 2.1 error log, or `dotnet format analyzers --report`, whichever reports every analyzer diagnostic (including those with no code fix) at the repo's configured severities. The choice and its reason go into the tech-stack decisions log, and the roadmap row is reworded if it is not `dotnet format`.
- **Stack and plan (`agentic_tools.scan.stack`):** `dotnet` leaves `_UNSUPPORTED_KINDS`. `Linter` gains `"dotnet"` and `Language` gains `"csharp"` (a module with a `*.csproj`; `.cs` files are not added to the probe's sources, which cap shell scripts). `auto` gives each C# module the `dotnet` linter:
  - **config `repo`** when the module, or a directory above it, has an `.editorconfig` with `dotnet_`/`csharp_`/diagnostic settings, a `Directory.Build.props`, or analyzer settings or packages (`AnalysisLevel`, `AnalysisMode`, `*.Analyzers` package references);
  - else **config `platform-default`**: the SDK's own default analyzers, as Microsoft ships them, with no rules of ours added.
- **Normalising:** diagnostics become `Finding`s with `tool: "dotnet"`. The rule is the diagnostic id (`CA1822`, `IDE0005`, `SA1200`); `help_url` comes from the diagnostic. The path is repo-relative (the copy's prefix removed) and the fingerprint is computed as for the other linters. Severity follows the 4.4 lint mapping: error → `medium`, warning → `low`, note/info → `info`. Hidden and suppressed diagnostics are dropped. A compiler error fails its module ("does not compile"), and its analyzer findings are dropped.
- **Checks with reasons:** one `Check` per module (`kind: "dotnet"`, `tool: "dotnet"`, `version`: the SDK's). Skipped or failed reasons are short and fixed, never the tool's raw output:
  - `restore failed: package source not reachable` (a private feed or a package not on nuget.org);
  - `restore failed: <NUxxxx>`;
  - `needs the <name> workload` (MAUI, Android, iOS);
  - `needs .NET SDK <version>` (see open questions);
  - `does not compile (<n> errors)`;
  - `timed out`.

  Windows-targeting projects (`net8.0-windows`) build with `EnableWindowsTargeting=true`.
- **Audit template:** no flow change. `scan.lint` with `linters: auto` now lints .NET modules, and the report lists their findings. The tool's description and the `linters` enum gain `dotnet`.
- **Specs and docs:**
  - tech-stack: Tool layer → Scanners, Sandbox, the decisions log;
  - roadmap: the 4.8 row's wording, if the engine is not `dotnet format`;
  - docs: `docs/architecture/decisions.md` (sandbox egress), `docs/security/security-model.md` (repo code runs at restore/build; NuGet-only egress), `docs/operations/deployment.md` (the proxy, image size, job container limits);
  - `CHANGELOG.md`.

### Out of scope

- Private NuGet feeds and feed credentials (the repo's `nuget.config` sources are ignored; such modules are skipped with their reason). Later, with workspace connections for package feeds.
- F# and VB.NET projects (`*.fsproj`, `*.vbproj`): detected as .NET but skipped (`no supported linter for fsharp`).
- Installing workloads (MAUI, Android, iOS, wasm): skipped with their reason.
- Several SDKs side by side in the image.
- Egress for anything but NuGet restore, gVisor/Firecracker, and an allowlist for other tools (npm, pip): 10.2.
- Running tests or `dotnet build` as a check in its own right: the build is only the vehicle for the analyzers.
- A separate, opt-in `.NET` image: one image for all deployments (the user's choice). Revisit if the size hurts.
- Any web change: the findings view and the "Checked" grid already show any tool and check (4.4, 11.9).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| How packages arrive | A restore step whose only route out is an allowlisting proxy to NuGet; analysis with no network | Offline-only would skip nearly every real repo (any `PackageReference`, any older target framework), so "Done when" would not hold. Restricting egress to one registry for one step keeps 4.4's "no network at run time" for everything that reads results. |
| Where restore and analysis run | Short-lived job containers from the sandbox image on the run's workspace volume, not the run's main sandbox | A container created with `network_mode="none"` cannot be put on a network later. Job containers also get .NET-sized memory and time without raising every run's sandbox limits. |
| Where they work | A throwaway copy of the module under `/workspace/.scan/` | `obj/`, `bin/` and packages never dirty the checkout or a writer's branch, and the gate's diff (Gate review) never shows build output. |
| Which package sources | The platform's `nuget.config` (nuget.org only), never the repo's | The repo's config could point the restore at any host. A private feed is skipped with its reason, not followed. |
| Image | One sandbox image with the .NET 10 SDK, copied from Microsoft's pinned alpine SDK image | Every deployment can audit .NET with no extra setup (the user's choice). Pinning by digest matches how the other scanners are pinned. |
| Analyzer engine | `dotnet build` with SARIF 2.1 logs (decided by the spike) | Both engines report diagnostics with no code fix; SARIF adds help links, end lines and compiler errors. Recorded in the decisions log; the roadmap row is reworded. |
| Config without repo settings | The SDK's default analyzers, marked `platform-default` | Same spirit as 4.4's "No linter config": real issues are caught and weighted lower. Microsoft's defaults are already conservative, so we add no rules of our own. |
| Severity | Error `medium`, warning `low`, note `info` (4.4's lint mapping) | One lint scale across stacks, so the audit's `min_severity` and router behave the same on a .NET repo. |

## Open questions

None. The spike (plan group 1) settled them; each is a row in tech-stack's decisions log:

- **Engine:** `dotnet build` with SARIF logs. On the same projects both engines reported a diagnostic with no code fix (CA2201), the `.editorconfig` severities and StyleCop's rules; SARIF also carries each rule's help link, end lines and compiler errors. Neither reports `IDE*` rules unless the repo sets `EnforceCodeStyleInBuild`, which follows the repo's own build.
- **A `global.json` pinning an SDK we do not ship:** inside the repo it stops `dotnet` entirely; run from outside the copy, the image's SDK builds it and the `msbuild-sdks` it lists still apply. Jobs run from the work directory, and the check's `version` names the SDK. Nothing is deleted from the copy.
- **Solution or project:** one generated solution of every C# project in the modules to lint (at most 500): one restore, one build, each project built once. A platform `scan.targets` gives every project and target framework its own SARIF log and records which project wrote it.
- **Job limits:** 2 GB, 2 CPUs, 512 PIDs and a 256 MB `/tmp` of the job's own; restore 300 s, build 600 s. A small solution peaked at about 140 MB and took 2 to 6 s per step. Found on the way: with `TMPDIR` on the run's volume MSBuild's worker nodes never connect, and the image's `/tmp` is not writable by its user, so jobs get their own tmpfs. Package signatures are checked with revocation offline (`NUGET_CERT_REVOCATION_MODE=offline`), so no CRL or OCSP host is allowed; the only host is `api.nuget.org`.
