# Deterministic tool nodes: linter, dependency scanner, secret scanner

Roadmap phase: 4.4
Branch: plan/4.4-deterministic-tool-nodes

## Context

The audit flow (4.7) needs facts an agent cannot be trusted to invent: lint errors, known-vulnerable dependencies and leaked secrets. Deterministic scanners produce them cheaply and the same way every time; specialist agents then judge, explain and prioritise them. 4.4 adds those scanners as platform tools, so a `tool` node (no model) runs one and its output feeds an agent.

It builds on what is done:

- 1.1 sandbox (one container per run, no network, read-only root, uid 1000): the scanners run there, like `repo.*`.
- 1.6 `tool` primitive: a tool node calls a scanner with fixed arguments.
- 4.2 typed ports: the findings shape is a JSON Schema the agent's `input_schema` can require.
- 4.3 run artifacts: a scan `writes: lint.json`, a specialist agent `reads` it.

It unblocks 4.5 (`reduce` dedupe and vote need one findings shape with a stable fingerprint), 4.7 (the "Audit codebase" template) and 6.7 (fix selected findings).

Principles that drive it (mission):

- **4, tools live in the platform:** scanners are a platform MCP server (`scan`), so they behave the same on Claude and on Copilot.
- **5, repo content is data:** scanner output is returned as data. A secret's value never leaves the sandbox.
- **2, open but safe by construction:** the scanners run offline, read-only, with time and size caps.
- **7, small steps:** one shape now. Dedupe, ranking and the audit report come later.

## Scope

### In scope

- **The workflow's author chooses the checks.** Each kind of check is its own tool, so a workflow runs only the scan nodes its author put in it. Nothing runs by default.
- **A `scan` MCP server with three read-only tools**, registered in `PLATFORM_TOOLS` as `SCAN_TOOLS`:
  - `scan.lint`: `linters` is either a list naming exactly what to run (`["ruff", "biome", "shellcheck"]`, any subset) or `"auto"` (the default). Optional `path` (a directory in the repo).
    - **`auto` follows the repo's own stack, never a generic set.** It detects the modules and their stack from their manifests, the same way `repo.list_modules` does (shared code, not a copy). Each module then gets its own linter:
      - **The repo configures a linter we run:** use it with the repo's config (`[tool.ruff]` or `ruff.toml` → ruff; `biome.json` → Biome; `.shellcheckrc` or shell files → ShellCheck).
      - **The repo configures a linter we cannot run offline** (ESLint, flake8, pylint): `skipped: eslint is not supported` for that module. We never put a different linter in its place.
      - **A language we support with no linter configured:** our linter with a small, conservative platform rule set (likely bugs, no style). Each of its findings is marked `config: "platform-default"`, so agents and users weigh it lower.
      - **A stack we have no linter for** (Go, Rust, Java, .NET): `skipped: no supported linter for go`.
    - With an explicit list, each named linter runs on the modules of its language, with the repo's config or the platform default. A linter named for a stack the repo does not have is skipped with its reason.
    - The report's `checks` say what was detected and run where (`[{path, kind, tool, config, status, reason}]`), with the reason for every skip, so the author sees why each check ran.
  - `scan.secrets`: runs gitleaks on the working tree (no git history in a shallow clone) with `--redact`. Optional `path`.
  - `scan.dependencies`: runs osv-scanner over the lockfiles the repo actually has, offline, against a vulnerability database baked into the sandbox image. So it follows the stack by construction, and a repo with no lockfile reports `skipped: no lockfiles`. Optional `path`.
  - They take the optional `description` (tool intent, 11.8) through `strict_tool`. Agents may call them too, as they are read-only, and they are allowed in loops, maps and parallels.
- **One normalised findings shape** (`agentic_tools.scan.FindingsReport`, exported as JSON Schema in `schemas/findings.v1.json`). It is the tool's structured `data`, so `output_schema` and `writes: *.json` work unchanged:
  - `scanner` (`lint` | `secrets` | `dependencies`).
  - `checks`: each engine on each module, with its config and version, or why it was skipped or failed (`… is not supported`, `no supported linter for go`, `no lockfiles`, `… exited with 2: …`).
  - `findings[]`, each with:
    - `fingerprint`: a sha256 of the tool, rule, path and the line's normalised content. Stable across runs, used by 4.5.
    - `tool`, `rule`, `severity` (`info` | `low` | `medium` | `high` | `critical`), `category` (`lint` | `secret` | `dependency`), `path`, `line`, `end_line`, `message` and `help_url`.
    - For lint only: `config` (`repo` | `platform-default`).
    - For dependencies only: `package`, `ecosystem`, `version`, `fixed_versions`, `aliases` (CVE ids).
  - `counts` by severity, `truncated`, and `db_as_of` for dependencies.
- **Caps and safety:**
  - Each engine has a timeout (120 s).
  - At most 1,000 findings, kept most severe first, with `truncated`. The report stays under the 1 MB artifact cap.
  - Paths are relative to the repo. Messages are capped at 500 characters.
  - Secret findings carry no match, secret or line text. gitleaks runs with `--redact`, and we also drop those fields.
  - Each tool's severity is mapped to ours through one documented table.
- **Sandbox image:**
  - Pinned binaries (ruff, Biome, ShellCheck, gitleaks, osv-scanner) with checksums.
  - The osv offline database for `OSV_ECOSYSTEMS` (PyPI, npm, Go, crates.io, Maven, NuGet, RubyGems, Packagist), fetched at image build into `/opt/osv/osv-scalibr/` (the layout osv-scanner 2 reads), dated in `/opt/osv/as-of` and reported in `db_as_of`.
  - Still no network at run time. Caches are off or go to `/tmp`.
- **Console:**
  - A tool step whose `data` is a findings report shows a findings view in its Output tab instead of raw JSON: counts as `StatTile`s, then one row per finding (severity as icon + text label, rule, `path:line` in mono, message as text). It is a table from `md` and cards below, capped with "Show all".
  - The artifact sheet uses the same view for a findings `.json` artifact.
  - `describeTool` lines for the `scan.*` tools.
- **A sample workflow** (spec fixture `valid/scan-specialists.json`, also used for the demo). It is an example of a choice an author makes, not a default:
  - A `parallel` of the three scan tool nodes (lint with `linters: "auto"`), writing `lint.json`, `secrets.json` and `dependencies.json`.
  - Then a specialist agent that `reads` all three, with an `input_schema` for them and an `output_schema` for a short triage.
- **Specs:**
  - tech-stack gets "Scanners (4.4)" under Tool layer, the image change under Sandbox, the findings view and severity rule under UI design system, and rows in the decisions log.
  - A CHANGELOG entry and the roadmap status.

### Out of scope

- Merging duplicate findings across scanners, voting and confidence: 4.5.
- The "Audit codebase" template and its readable report: 4.7. Choosing the checks when a run starts (a "which checks" input in the New run sheet) needs template inputs and comes with it. Until then, the choice lives in the workflow.
- Picking checks by drag and drop: the canvas palette (5.3). The Architect choosing checks from a repo profile: 9.1 and 9.2.
- Fixing findings or opening PRs from them: 6.7.
- Running the repo's own linter when we do not ship it: ESLint with the repo's plugins (it needs `node_modules`), golangci-lint, Checkstyle, Semgrep, hadolint and type checkers. Such a module is reported as skipped, not linted generically. A team's own linter comes as a plugin node: 10.1.
- Scanning git history for secrets (a shallow clone has none) and updating the osv database without a new image. A scheduled database refresh comes with production hardening (10.2 or 10.5).
- A run-wide "findings" tab or cross-run tracking.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Linters | ruff + Biome + ShellCheck | Static binaries that run offline with no `node_modules` or toolchain, and cover Python, JS/TS/JSON/CSS and shell. Semgrep is large, and the license of its registry rules restricts use in a hosted service. |
| Secret scanner | gitleaks, with `--redact`, working tree only | A single binary with a maintained rule set. Redacting in the tool and again in our normaliser keeps the value out of events, artifacts and logs (principle 5). |
| Dependency scanner | osv-scanner, offline, with its database baked into the sandbox image | The sandbox has no network at run time (1.1). OSV covers many ecosystems from lockfiles. The database age is shown (`db_as_of`), as with `PRICES_AS_OF`. |
| Where they run | In the run's sandbox, by the new `scan` MCP server through `sandbox.exec` | The same isolation and routing as `repo.*`, with no new sandbox plumbing. Separate sidecar images wait for plugin nodes (10.1). |
| Output | One normalised `FindingsReport` as the tool's structured `data`, with a stable `fingerprint` | Typed ports, artifacts, 4.5 dedupe and 4.7 all read one shape. Each tool's own JSON stays inside the server. |
| Severity in the UI | An icon and a text label in neutral colours, never a status colour | Colour means status only (design system rule 2). |
| Who chooses the checks | The workflow's author: one tool per kind of check, and `linters` is an explicit list or `"auto"` | Orchestration is open, never a fixed menu (mission). A run does only what its spec says. |
| What `auto` runs | The linter each module's stack and config call for. A linter we cannot run offline is reported as skipped, never replaced | A generic linter on a repo that chose another one gives findings against rules the team never chose. The report's `checks` say what was detected and why. |
| A supported language with no linter config | Our linter with a conservative platform rule set (likely bugs, no style), and each finding marked `config: platform-default` | Real errors are still caught, and agents and users can weigh these findings lower than the repo's own rules. |
| Stack detection | Shared with `repo.list_modules` (one manifest table) | One definition of "the repo's stack" for agents and scanners, ready for the RepoProfile (9.1). |
| Who may call them | Tool nodes and agents, everywhere (loops, maps, parallels) | They are read-only and deterministic. |
| Findings cap | 1,000 per report, most severe first, `truncated` | Fits the 1 MB artifact cap and an agent's context. |

## Open questions

- None. The osv database for all eight ecosystems is about 290 MB (npm alone 209 MB) and the image about 510 MB, so all eight are kept. Prettier is a formatter, not a linter, so it is not checked.
