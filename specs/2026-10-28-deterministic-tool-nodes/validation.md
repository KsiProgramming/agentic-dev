# Validation: Deterministic tool nodes: linter, dependency scanner, secret scanner

## Done when (from roadmap)

> Tool outputs feed specialist agents

Checkable form: a run of `valid/scan-specialists.json` runs `scan.lint`, `scan.secrets` and `scan.dependencies` as tool nodes. Each writes a findings artifact, and the `triage` agent's input is exactly those three reports, checked by its `input_schema`.

## Automated checks

- [ ] **Contract:**
  - `test_scan_report.py`: the fingerprint is stable for the same rule, path and line text, the cap keeps the most severe 1,000 with `truncated`, and `schemas/findings.v1.json` is in sync.
  - `test_validate.py`: `scan.*` is accepted in sequence, parallel, map and loop, and refused for a run with no repo. The `PLATFORM_TOOLS` sync test passes with the `scan` server.
- [ ] **Stack scoping** (`test_scan_stack.py`):
  - `auto` gives each module the linter its stack and config call for.
  - A repo configured for ESLint (or another linter we do not ship) is reported `skipped: … is not supported`, and Biome does not run on it.
  - A Python module with no config runs ruff with the platform default, and its findings carry `config: "platform-default"`.
  - Go, Rust, Java and .NET modules are skipped with their reason.
  - An explicit `linters` list runs only what it names.
  - `test_list_modules.py` stays green on the shared detection.
- [ ] **Server on a fake sandbox** (`test_scan_server.py`):
  - Each normaliser maps recorded tool output to the expected findings and severities.
  - An engine that times out or errors is `skipped` while the others report, and all engines failing is an error result.
  - `path` outside the repo and unknown arguments are refused.
  - The secret value from the recorded gitleaks output is absent from the serialized result.
- [ ] **Docker sandbox on the fixture repo** (`test_scan_docker.py`, docker marker, runs in CI):
  - ruff (`py/`), Biome (`web/`) and ShellCheck (`scripts/`) each report their planted finding with `config: "repo"`.
  - `legacy/` (ESLint) is in `stack` as skipped, with no findings.
  - gitleaks reports the planted key with no value.
  - osv-scanner reports the planted advisory offline, with `db_as_of` set.
  - Each finishes within its timeout. The container still has `network_mode=none`.
- [ ] **Engine end to end on the fake runtime** (`test_scan_flow.py`):
  - The parallel scans write `lint.json`, `secrets.json` and `dependencies.json` (v1).
  - `triage`'s `node_started.reads` lists them, and its input is the object of the three reports.
  - A malformed report fails at the edge with the 4.2 error line.
- [ ] **Worker** (`test_worker.py`): the scan tools are offered when the run has a sandbox and absent without a repo.
- [ ] **Secrets never leak:** a test runs the scan flow and asserts the planted secret appears in no `run_events` payload, no artifact and no captured log.
- [ ] **Backend gates:** `ruff`, strict `pyright`/`mypy` and `pytest` across the packages are green.
- [ ] **Frontend:**
  - `pnpm lint && pnpm typecheck && pnpm test`, including `findings.test.tsx` and `step-view.test.tsx`.
  - `pnpm test:e2e`: `a11y.spec.ts` has no serious axe issues on the findings view, and `layout.spec.ts` shows no horizontal scroll at 375, 768 and 1440 px.
- [ ] CI is green, including the sandbox image build.

## Manual / demo checks

- [ ] Rebuild the image with `docker build -t agentic-dev/sandbox:dev packages/sandbox`, then record its size and `OSV_DB_AS_OF` in the PR.
- [ ] With `docker compose up`, a Claude key and a GitHub repo connected, start a run of the sample workflow on a real repo (Python and JS):
  - The step list shows `lint`, `secrets` and `deps` running in parallel, then `triage`.
  - Each scan step's Output shows the findings view (counts, rows, `path:line`), and the Artifacts tab lists three `.json` artifacts.
  - The lint step's "Checked" lines match the repo's real stack: only the linters its modules configure, and anything we cannot run named as skipped.
  - `triage`'s Input lists "Artifacts read" with versions, and its answer cites findings by fingerprint or `path:line`.
- [ ] Run the same flow on a repo with a planted test secret. The secret appears nowhere in the console, the raw events or the artifact download.
- [ ] Look at the findings view at 375 and 1440 px, in light and dark. Severity is an icon plus a label with no status colour, and keyboard tabbing reaches "Show all" and the help links.

## Merge criteria

- [ ] All checks above pass in CI.
- [ ] `specs/tech-stack.md` updated: Scanners (4.4) under Tool layer, the Sandbox image, the findings view in UI design system, and decisions log rows. The osv ecosystem list matches what the image ships.
- [ ] `CHANGELOG.md` has an `[Unreleased]` entry, and the roadmap 4.4 status is set by the PR.
- [ ] Binary versions and checksums are pinned in the Dockerfile, with no `latest`.
- [ ] No secret, token or secret match text in logs, events, artifacts or test snapshots.
- [ ] A demo screenshot of the scan steps and the triage answer is in the PR.
