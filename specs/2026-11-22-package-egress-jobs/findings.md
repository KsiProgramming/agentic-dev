# Findings: package egress spike (13.2, group 1)

Run on 2026-11-22 with the sandbox image built from `packages/sandbox` (Alpine 3.20, musl), a job container as the sandbox runs them (uid 1000, read-only root, `cap_drop ALL`) and the real `packages/egress-proxy` image: one proxy per registry on its own internal network, each with its narrowed allow file. The samples were small projects locked with each manager (esbuild 0.25.5 and sharp 0.34.2 for Node, pydantic 2.11.7 and numpy 2.3.1 for Python) rather than public repos, so what was tested is each manager's network behaviour, not a repo's quirks.

## Hosts

| Registry | Hosts the restore contacted | Allow file |
|---|---|---|
| npm (npm, pnpm, yarn 1, yarn 4) | `registry.npmjs.org` | `npm.allow` |
| PyPI (uv sync, uv pip) | `pypi.org`, `files.pythonhosted.org` | `pypi.allow` |
| NuGet (4.8) | `api.nuget.org` | `nuget.allow` |

With the narrowed allow files the PyPI proxy refused nothing, and the npm proxy refused only `registry.yarnpkg.com` (see below). No CDN or redirect host was needed.

## What each manager needs to go through the proxy

- **npm, pnpm, uv** read `HTTPS_PROXY` from the environment.
- **yarn 1 ignores `HTTPS_PROXY`**: it needs `--https-proxy <url>` (the job passes it). It also fetches each package from the `resolved` URL in `yarn.lock`, which real lockfiles point at `registry.yarnpkg.com`. The work copy rewrites that host to `registry.npmjs.org` in `yarn.lock` (the `#sha1` fragment and `integrity` still check the bytes), so only one host is allowlisted. Pass `--registry https://registry.npmjs.org` too.
- **yarn 4 ignores `HTTPS_PROXY`** but reads `YARN_HTTPS_PROXY` and `YARN_NPM_REGISTRY_SERVER` (environment settings win over a repo's `.yarnrc.yml`). The platform's `yarnrc.yml` documents the same settings.
- A repo's own `.npmrc`, `.yarnrc`, `pip.conf` and `uv.toml` are not read, because the work copy drops them.

## Commands that worked

Restore (registry network, no repo code runs):

| Manager | Command |
|---|---|
| npm | `npm ci --ignore-scripts` |
| pnpm | `pnpm install --frozen-lockfile --ignore-scripts --store-dir /workspace/.cache/pnpm` |
| yarn 1 | `yarn install --frozen-lockfile --ignore-scripts --cache-folder … --registry … --https-proxy …` |
| yarn 4 | `YARN_ENABLE_SCRIPTS=false yarn4 install --immutable --mode=skip-build` |
| uv.lock | `uv sync --frozen --no-install-project --no-build` |
| requirements | `uv venv .venv` then `uv pip install --python .venv/bin/python --no-build -r requirements.txt` |

Then, for a Python project with its own package, the build backend's requirements are warmed into the cache on the same network: `uv pip install --no-build --target <tmp> <build-system.requires>`. Without it, the offline install of the project fails with "not found in the cache".

Build (network `none`):

| Manager | Commands |
|---|---|
| npm | `npm rebuild`, `npm run build` |
| pnpm | `pnpm rebuild --store-dir …`, `pnpm run build` |
| yarn 1 | `npm rebuild` (yarn 1 has no `rebuild`), `yarn run build` |
| yarn 4 | `yarn4 rebuild`, `yarn4 run build` |
| uv.lock | `uv sync --frozen --offline --no-editable` |
| requirements | `uv pip install --offline --no-build -r requirements.txt` |

`--no-editable` is needed offline: an editable install makes hatchling ask for `editables`, which is a pre-release-pinned requirement that was never cached. A non-editable install builds a wheel and needs nothing more.

## Decisions

- **musl is enough: keep the Alpine sandbox image, no job image.** esbuild and sharp (native, with their musl binaries as optional dependencies) rebuilt and ran, and pydantic-core and numpy came as musllinux wheels. Nothing failed for being musl in the samples. A module that has no musl wheel fails with the fixed reason "has no wheel for this platform"; if real repos hit it often, a Debian-slim job image is a later phase (`run_job` would take `image=`). `run_job` is unchanged.
- **Poetry: read `poetry.lock` ourselves.** `poetry.lock` pins every package with its file hashes, so it converts to a hash-pinned requirements file that `uv pip install --require-hashes --no-deps --no-build` installs. Poetry is not installed in the image, so a `requires-plugins` entry never runs.
- **Image size.** The sandbox image is 1.42 GB with Node 22.16 (npm 10.9, yarn 1.22.22, yarn 4.19.0, pnpm 10.34.9), Python 3.12 and uv 0.9.30, on top of the .NET SDK and scanners. Alpine alone is 8 MB.
- **Layout keys.** `.yarnrc.yml`: only `nodeLinker`, `pnpMode` and `enableGlobalCache` are kept; everything else (sources, plugins, `yarnPath`, scripts, proxies) is dropped, and a `yarnPath` fails the module. `[tool.uv]` in `pyproject.toml`: only `package`, `managed`, `dev-dependencies`, `default-groups`, `required-version` and `workspace` are kept; `index`, `index-url`, `extra-index-url`, `find-links` and `[tool.uv.pip]` are dropped, and so is every `sources` entry except `{ workspace = true }`, so a dependency pinned to a git, URL or path source fails restore with its fixed reason.
