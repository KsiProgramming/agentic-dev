# Package egress for build and test jobs

Roadmap phase: 13.2
Branch: plan/13.2-package-egress-jobs

## Context

13.3 builds the change and runs its tests in job containers before a gate, and 13.4 adds coverage. Neither can work on a Node or Python repo today: job containers (4.8) have no network except `nuget`, and the sandbox image holds no Node or Python. 4.8 solved this for .NET by restoring through an allowlisting proxy and then building with no network. 13.2 applies the same pattern to npm and PyPI. Like 4.8, it pulls a package-registry slice of 10.2's egress allowlist forward; 10.2 keeps the general allowlist and the production isolation.

The phase depends on 4.8 (job containers, the egress proxy, the `nuget` network), which is done. 13.1 is done but is not needed here. It unblocks 13.3 (build and tests in the evidence pack), 13.4 (coverage), 16.2 and 16.4 (dependency upgrades and fixes), 16.5 (CI pipeline) and 13.10's smoke test.

What drives the design:
- **Principle 2 (safe by construction)**, enforced by the platform rather than the graph. A job reaches only the registry it was given. The proxy refuses every other host and logs it.
- **Principle 5 (repo content is data)**. A repo picks its packages but never its package sources, and none of its code runs while the network is up.
- **Principle 3 (gates before irreversible actions)**. A restore only downloads; it publishes nothing. Even so, it opens a route out, so only a tool node may call it, never an agent (see Decisions).
- **tech-stack → Sandbox → Job containers / NuGet egress (4.8)**. Job containers, `JobLimits`, the tinyproxy image and the "copy the repo to a work directory" pattern are reused as they are.
- **Decisions log rows "How .NET packages arrive" and "Package sources" (4.8)**. These rules are extended to npm and PyPI: one registry per job, and the platform's config only.

## Scope

### In scope

- **One network and one proxy per registry.** `JobNetwork` becomes `none | nuget | npm | pypi`. Each registry gets its own internal Docker network (`agentic-npm`, `agentic-pypi`, `agentic-nuget`). Its only other member is an egress-proxy service built from the one `packages/egress-proxy` image, with that registry's config and allow file. A job on `npm` cannot reach PyPI or NuGet. The worker reads each registry's network and proxy from settings (`SANDBOX_<REGISTRY>_NETWORK`, `SANDBOX_<REGISTRY>_PROXY`). NuGet moves onto the general config with its variable names unchanged.
- **Allowlists** are set from the spike (plan group 1). The expected hosts are: npm `registry.npmjs.org`; PyPI `pypi.org` and `files.pythonhosted.org`. Yarn's default `registry.yarnpkg.com` is pointed at `registry.npmjs.org` by our config, so it is not allowlisted. Every refused host is logged by the proxy.
- **Toolchains in the sandbox image**, each pinned and checked: Node 22 LTS with npm, pnpm, yarn classic (1.x) and yarn berry (4.x) installed in the image (corepack's downloads off), Python 3.12, uv, and poetry if the spike keeps it (see Open questions). The new image size is recorded in tech-stack.
- **Package managers detected from the repo's lockfile**, per module, using the same module detection as `repo.list_modules`:
  - Node: `package-lock.json` → npm, `pnpm-lock.yaml` → pnpm, `yarn.lock` → yarn classic or berry (decided by the lockfile's format).
  - Python: `uv.lock` → uv, `poetry.lock` → poetry, `requirements*.txt` → uv pip.
  - A Node module with no lockfile is skipped with a reason. A Python module with only a `pyproject.toml` is restored with uv from its declared dependencies.
- **No repo code runs while the network is up.** The restore job downloads and unpacks only:
  - npm, pnpm and yarn classic run with `--ignore-scripts`; yarn berry runs with `enableScripts: false`.
  - Python takes wheels only (`--no-build`), so a package published only as an sdist fails with a fixed reason.
  - A yarn release vendored in the repo (`yarnPath`) is never run, and its module fails with a fixed reason.
  - Lifecycle scripts, `npm run build` and the build of the repo's own Python package run afterwards, in a `none` job.
- **The repo's package sources are never read.** The work copy drops `.npmrc`, `.yarnrc`, `pip.conf` and `uv.toml`. In `.yarnrc.yml` and `pyproject.toml`'s `[tool.uv]`, only the keys that set the layout are kept; the spike settles which ones. The platform's config, in `/opt/build`, sets the registry. A dependency from git, a URL or a private registry fails with a fixed reason; it never adds a host to the allowlist.
- **A restore + offline build module** (`agentic_tools.build`):
  - The repo is copied (without `.git`, `node_modules`, `.venv`, `dist`, `build`) to a work directory under the staging directory, as 4.8 does.
  - A restore job runs on the registry's network, then a build job runs on `none`. For Node, the build job runs `<manager> rebuild` and then the `build` script if `package.json` has one. For Python, it installs the project into a venv from the cache, offline.
  - The package-manager caches live in a per-run directory on the run's volume, outside the checkout (`/workspace/.cache/<manager>`), so 13.3's later jobs install offline from them. The work directory is removed after.
  - Timeouts: copy 120 s, restore 300 s, build 600 s (`BuildLimits`).
- **Fixed failure reasons, never the tool's words** (the 4.8 pattern):
  - `restore failed: a package is not on npm` / `… on PyPI`
  - `restore failed: a dependency comes from git or a URL`
  - `restore failed: <pkg> has no wheel for this platform`
  - `restore failed: the lockfile is out of date`
  - `needs Node <major>`, `needs Python <version>`, `needs <manager> <major>`
  - `the repo's own yarn release is not run`
  - `restore timed out`, `build failed (exit N)`, `build timed out`
  - `skipped: no lockfile`
  - `skipped: npm restore is not configured` / `… PyPI …` (no proxy for that registry)
- **A `build.restore` tool, for tool nodes only.**
  - Arguments: `{path?, ecosystems?: "auto" | ["node", "python"]}`.
  - It returns a build report (`schemas/build.v1.json`): `checks`, one per module (`path`, `ecosystem`, `manager`, `lockfile`, `status` ran/skipped/failed, `reason`, `version`, `packages`, `restore_ms`, `build_ms`), and `counts`.
  - A tool node may write the report as an artifact (`writes`). It is listed in the palette from its manifest (5.3), and it needs a repo (`build.` joins `REPO_TOOL_PREFIXES`).
  - It is a new set, `BUILD_TOOLS`, that only a tool node may name, like `PUBLISH_TOOLS`. Validation refuses it on an agent, hub, classifier or reduce agent.
- The specs, docs and changelog that go with it: tech-stack (Sandbox, Tool layer, decisions log), `docs/security/security-model.md` (egress), `docs/operations/deployment.md` and `configuration.md` (the new proxies and variables), `docker-compose.yml`, `CHANGELOG.md`, and the roadmap row's plan link.

### Out of scope

- Running the test suite, the evidence pack at the gate, and sending a failure back to the writer's loop: 13.3.
- Restoring or building a writer's branch (`node`, as in 13.1's reads): 13.3 adds it, building the change rather than the checkout.
- Coverage: 13.4.
- Private feeds and registries with credentials: they wait for connections that hold feed credentials (the same as 4.8's decision).
- Other ecosystems: Go modules, crates.io, Maven, RubyGems and Composer. Each would be its own registry later, through this same mechanism.
- Interpreter downloads. uv's managed Python and `.nvmrc` / `engines` versions other than the image's are fixed reasons, not downloads.
- Giving the tool to agents, and showing refused hosts in the run console: 10.2 or 13.7.
- Production isolation (gVisor or Firecracker) and the general egress allowlist: 10.2.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| How registries are kept apart | One proxy service and one internal network per registry, all from one image with a config per registry | A shared proxy with one port per registry lets any job on its network reach every port. Only the network keeps "each registry allowlisted on its own" true. |
| Package managers covered | npm, pnpm, yarn classic and berry; uv (uv.lock, requirements, pyproject) and poetry | The broad scope chosen in the interview: most real Node and Python repos are restored rather than skipped. |
| Code while the network is up | None from the repo. Scripts are off, Python takes wheels only, a vendored yarn is not run, and scripts and builds run in a `none` job | Install scripts, `setup.py` and `yarnPath` are repo-chosen code. With a route to a registry they could publish the repo out (an npm publish is an HTTPS call to an allowed host). Offline, they reach nothing. |
| Package sources | The platform's config only. Repo source settings are dropped from the work copy | Extends 4.8's "Package sources" row: a repo config could point a restore at any host. |
| Who may call `build.restore` | Tool nodes only (`BUILD_TOOLS`), never agents | It opens a route out of the sandbox. A deterministic step the workflow's author draws is visible in the graph, while an agent's call is chosen at run time from data (principle 5). It also keeps 13.9's lethal-trifecta check simple. |
| Where restored packages live | Package-manager caches in a per-run directory on the run's volume; a work copy per call, removed after | 13.3's build and test jobs reuse the cache offline. `node_modules` and venvs stay out of the checkout, a writer's branch and a gate's diff (4.8's row "Where .NET restores and builds run"). |
| Config names | `SANDBOX_<REGISTRY>_NETWORK` and `SANDBOX_<REGISTRY>_PROXY`, NuGet's unchanged | Existing deployments keep working. Each registry is turned on by setting its two variables. |
| Real run with Claude | Not required | No agent receives anything new: the tool is not an agent's, and no template uses it yet. 13.3 does the real run when its gate shows the checks (lessons, rule 1). |

## Open questions

These are settled by the spike (plan group 1) and recorded in the decisions log:
- **musl or glibc.** The sandbox image is Alpine (musl). Many wheels and npm prebuilt binaries ship for glibc only. If the spike's sample repos fail too often, Node and Python jobs run from a Debian-slim **job image** instead (`run_job` takes an image), and the sandbox image stays as it is.
- **Poetry.** Either run poetry itself, which can install plugins the repo declares (`requires-plugins`), or read `poetry.lock` ourselves into hash-pinned requirements for uv. The recommendation is to read it ourselves, so no repo-chosen plugin runs.
- **Exact hosts and keys.** The exact hosts each manager needs (redirects, a CDN), and which `.yarnrc.yml` and `[tool.uv]` keys are layout-only and can be kept.
