# Plan: Deterministic tool nodes: linter, dependency scanner, secret scanner

The work goes contract first: the findings shape and the spec rules, then the server tested on a fake sandbox, then the real image, then the wiring, the console and the demo. The project works after each group.

## 1. Contract: findings shape and spec

- [ ] New `packages/tools/src/agentic_tools/scan/report.py`:
  - Pydantic `FindingsReport`, `Finding`, `ToolRun` (engine, version, `skipped` reason), `Severity` and `Category`.
  - `fingerprint(tool, rule, path, line_text)`.
  - `MAX_FINDINGS = 1000` and `cap(findings)` (most severe first, then path and line).
- [ ] `scripts/` export: `schemas/findings.v1.json` from `FindingsReport`. A test checks it is in sync, like the workflow schema.
- [ ] `agentic_engine/spec/models.py`:
  - `SCAN_TOOLS = {"scan.lint", "scan.secrets", "scan.dependencies"}`, documented and added to `PLATFORM_TOOLS`.
  - Allowed wherever `READ_TOOLS` are: loops, maps and parallels.
  - They need a repo: wherever a run without a repo refuses `repo.*`, it refuses `scan.*` too. Check every use of `READ_TOOLS`.
- [ ] Re-export `schemas/workflow-spec.v0.json` if the descriptions change.
- [ ] Unit tests:
  - `test_scan_report.py`: the fingerprint is stable, the cap order is right, and the schema is in sync.
  - `test_validate.py`: scan tools are allowed in parallel, map and loop, and a run with no repo is refused.

## 2. `scan` MCP server (fake sandbox)

- [ ] New `packages/tools/src/agentic_tools/scan/server.py`, built like `repo/server.py`:
  - `build_scan_server(sandbox)` and `open_scan_tools(sandbox)`, which returns an `McpToolExecutor`.
  - Three tools through `strict_tool`. Each takes `path` (repo-relative, checked like `repo.*` paths); `scan.lint` also takes `linters`.
- [ ] Stack detection, shared with `repo.list_modules`:
  - Move `_MANIFESTS` and the module finder into `agentic_tools/repo/stack.py` and use them from both servers. `test_list_modules.py` stays green.
  - New `scan/stack.py` builds a `LintPlan`. For each module, it reads which linter config is present:
    - Python: `[tool.ruff]` in `pyproject.toml`, `ruff.toml`, `.ruff.toml`; or a foreign linter (`[tool.pylint]`, `[tool.flake8]`, `.flake8`, `setup.cfg [flake8]`).
    - Node: `biome.json(c)`; or a foreign linter (`.eslintrc*`, `eslint.config.*`, `eslintConfig` in `package.json`).
    - Shell: `*.sh` files and `.shellcheckrc`.
  - Each module then gets one of:
    - the repo's config;
    - the platform default (a supported language with no linter configured);
    - `skipped: <linter> is not supported` (a foreign linter we cannot run);
    - `skipped: no supported linter for <kind>` (Go, Rust, Java, .NET).
  - With an explicit `linters` list, only those linters run, on the modules of their language. A linter with no matching module is skipped with its reason.
  - The plan becomes the report's `stack`.
  - Reading config files is a fixed `find`/`cat` in the sandbox. No repo content is run.
- [ ] Each linter run is one `sandbox.exec` (no shell) with `timeout_s=120`, once per module that gets it:
  - ruff: `ruff check --output-format json --no-cache --exit-zero <module>`, with `--config /opt/scan/ruff.toml` when the module uses the platform default.
  - Biome: `biome lint --reporter=json <module>`, with `--config-path /opt/scan` when the module uses the platform default.
  - ShellCheck: `shellcheck -f json1` on the module's `*.sh` files.
  - Platform defaults are conservative (likely bugs only, no style rules): ruff `F` and `E9`, and Biome `recommended` with the `style` group off. Each of their findings gets `config: "platform-default"`.
  - gitleaks: `gitleaks dir --redact --report-format json --report-path <staging>/gitleaks.json --exit-code 0 <path>`, read back with `take_file`.
  - osv-scanner: `osv-scanner scan source --offline --format json -r <path>`. Exit code 1 means findings; 128 means no lockfiles, which is skipped and not an error.
- [ ] Normalisers in `scan/normalise.py`, one per tool, each mapping the tool's own JSON to `Finding`:
  - One severity table, documented in the module.
  - For secrets, keep only the rule, path, line and description. Never `Secret`, `Match` or the line text.
- [ ] A finding's `fingerprint` hashes the line text, read in the sandbox. For secrets it hashes the rule, path and line number only.
- [ ] The structured `data` is the report. The text is a one-line summary ("lint: 12 findings (3 high) from ruff, Biome; ShellCheck skipped: no files").
- [ ] An engine that fails or times out goes in `tools[].skipped`, and the others still report. Only "every engine failed" is an error result, which fails a tool node.
- [ ] `agentic_tools.scan.__init__`: `SERVER_NAME = "scan"` and the tool names. The `PLATFORM_TOOLS` sync test stays green.
- [ ] Tests in `packages/tools/tests/test_scan_stack.py` for the lint plan on fake repos:
  - Python with `[tool.ruff]` gets ruff with the repo's config.
  - Python with no config gets ruff with the platform default.
  - TS with `eslint.config.js` is skipped as not supported, and Biome does not run.
  - TS with `biome.json` gets Biome.
  - A Go module is skipped with no supported linter.
  - A monorepo mixes all of these per module.
  - An explicit `["ruff"]` list on a Node-only repo skips with its reason.
- [ ] Tests in `packages/tools/tests/test_scan_server.py` with `FakeSandbox` and recorded JSON from each tool:
  - Normalising, the severity map and the caps.
  - A secret value never appears in the result (assert on the whole serialized output).
  - Skips, and the "all failed" error.
  - A `path` outside the repo is refused.
  - Unknown arguments are refused.

## 3. Sandbox image

- [ ] `packages/sandbox/Dockerfile`:
  - A multi-stage build. The download stage fetches pinned releases with sha256 checks (ruff, Biome, ShellCheck, gitleaks and osv-scanner, musl and static builds for alpine).
  - It fetches the osv offline database for `OSV_ECOSYSTEMS` into `/opt/osv`.
  - The final stage copies the binaries to `/usr/local/bin` and the database (read-only), and sets `OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY=/opt/osv` and `OSV_DB_AS_OF` (build date, plus a label).
  - Platform default configs in `/opt/scan/` (`ruff.toml`, `biome.json`).
- [ ] Check the image size and record it. If the database is too large, cut the ecosystems (the open question) and write it down.
- [ ] Check `/tmp` (64 MB, noexec) is enough with caches off.
- [ ] `docker_backend.py`: nothing changes unless a tool needs a writable path. Use `staging_dir` for the gitleaks report.
- [ ] `packages/sandbox/tests/fixtures/scan-repo/`, a tiny monorepo with:
  - `py/` with `[tool.ruff]` and a ruff violation.
  - `web/` with `biome.json` and a Biome violation.
  - `legacy/` with an ESLint config, which must be skipped.
  - `scripts/` with a ShellCheck warning.
  - A fake key that matches a gitleaks rule. It is clearly fake and allowlisted for our own CI secret scanning.
  - A `requirements.txt` or `package-lock.json` pinning a version with a known OSV advisory.
- [ ] `packages/tools/tests/test_scan_docker.py` (marked docker, like the other sandbox tests). Each tool finds exactly its expected finding in the fixture, and the secret value is absent.
- [ ] `ci.yml`: the image build stays one step. Use a Docker layer cache so the database is not fetched on every run.

## 4. Engine and worker wiring

- [ ] Worker `main.py`: when the run has a sandbox, add `open_scan_tools(sandbox)` to `RunTools`, entered after the sandbox like the repo tools.
- [ ] Check the tool node path: a tool's structured `data` passes the output port check and is written as the `.json` artifact unchanged (4.2, 4.3). Fix it if not.
- [ ] `agentic_engine` instructions: none. Agents read the reports through `reads` or `artifacts.read`.
- [ ] Spec fixture `valid/scan-specialists.json`:
  - A `parallel` (join `all`) of three tool nodes (`lint` → `lint.json`, `secrets` → `secrets.json`, `deps` → `dependencies.json`), each with `output_schema` set to the findings schema.
  - Then an agent `triage` that `reads` all three, with an `input_schema` requiring the three keys and an `output_schema` for `{summary, top: [{fingerprint, why}]}`.
- [ ] `packages/engine/tests/test_scan_flow.py` (fake runtime, fake tool executor returning recorded reports):
  - The run completes and three artifacts are written at v1.
  - `triage`'s input is the object of the three reports, and its `node_started.reads` lists them.
  - A wrong-shaped report fails at the edge.
- [ ] `packages/worker/tests/test_worker.py`: the scan tools are offered when there is a sandbox and absent without a repo.

## 5. Console

- [ ] `web/src/runs/findings/`:
  - `findings.ts`: a type guard for a findings report (from the exported schema), sorting, and the severity label and icon map.
  - `findings-view.tsx`:
    - `StatTile`s for the counts by severity.
    - A "Checked" line per module from `stack`: its path (mono), kind, linter, and "repo config" or "platform default". Skipped modules show their reason as text.
    - A table from `md` and cards below: severity (lucide icon + label in a neutral `Badge`), rule (mono, a link to `help_url` when there is one), `path:line` (mono), and the message as text.
    - Dependencies also show the package, version and fixed versions.
    - 50 rows, then "Show all". `EmptyState` for "No findings".
- [ ] `step-output.tsx`: a tool step whose `data` is a report renders `FindingsView`, and raw JSON stays in its Events tab. `artifact-cards.tsx` and the sheet: a findings `.json` artifact renders the same view, with a JSON toggle.
- [ ] `tool-describe.ts`: lines for `scan.lint` ("Lint `src/` with ruff, Biome"), `scan.secrets` and `scan.dependencies`.
- [ ] Vitest:
  - `findings.test.tsx`: the type guard, sorting, the table/card switch and "Show all".
  - No secret text is rendered (the shape has none).
  - `step-view.test.tsx`: a scan step shows the view.
- [ ] e2e: add a scan step to the console fixture so `a11y.spec.ts` and `layout.spec.ts` cover the view at 375, 768 and 1440 px.

## 6. Specs, changelog, demo

- [ ] `specs/tech-stack.md`:
  - Tool layer → "Scanners (4.4)":
    - The author chooses the checks, and `auto` follows the repo's stack: the per-module rules, skipped and never replaced, and platform defaults marked as such.
    - The tools, their arguments, the report shape, caps, redaction and the severity map.
  - Sandbox → the image's tools and the offline database with `OSV_DB_AS_OF`.
  - UI design system → Run console → "Findings": the severity rule.
  - Decisions log rows: who chooses the checks, stack-scoped `auto`, platform defaults, the linters, the secret scanner, the offline dependency scanner, the findings shape and severity in the UI.
- [ ] `CHANGELOG.md` `[Unreleased]` entry. The roadmap 4.4 status is set by CI or `complete-phase`.
- [ ] Live demo on Claude (see validation) and a screenshot in the PR.
