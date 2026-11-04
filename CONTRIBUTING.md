# Contributing

Thank you for helping. This project is built **spec-first**: what to build and why is written down before and alongside the code. This page explains the workflow; [Getting started](docs/development/getting-started.md) gets your environment running.

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md). Security issues go through [SECURITY.md](SECURITY.md), never public issues.

## Ways to contribute

- **Report a bug:** open an issue with steps to reproduce, what you expected, what happened, and your environment (OS, Docker version, runtime `fake` or `claude`).
- **Propose a feature or integration:** open an issue first. Say which [roadmap](specs/roadmap.md) phase it belongs to, or why it should become one. Ideas not yet on the roadmap are collected in [`specs/ideas.md`](specs/ideas.md).
- **Improve the docs:** always welcome; small fixes can go straight to a pull request.
- **Pick up a roadmap phase:** comment on its issue so work is not duplicated.

## The rules that keep the project coherent

1. **Specs govern the work.** [`specs/mission.md`](specs/mission.md), [`roadmap.md`](specs/roadmap.md), [`tech-stack.md`](specs/tech-stack.md) and [`design-language.md`](specs/design-language.md) win over code, docs and chat. A new library, API shape, pattern or UI rule is added to `tech-stack.md` **in the same PR**, with a decisions-log row when you chose between options. If code and specs disagree, fix one of them in your PR and say which.
2. **One roadmap phase at a time.** A phase is planned in `specs/YYYY-MM-DD-<slug>/` (`requirements.md`, `plan.md`, `validation.md`) before it is built. Phase numbers never change; a new milestone takes the next free number.
3. **Every PR adds a line under `## [Unreleased]` in [`CHANGELOG.md`](CHANGELOG.md)** (Keep a Changelog headings). CI enforces it.
4. **A PR that implements a phase marks it done** in `specs/roadmap.md` (CI does it for PRs from this repository; see `scripts/check_roadmap.py`).
5. **Generated files stay in sync.** After changing endpoints: `uv run python scripts/export_openapi.py && (cd web && pnpm gen:api)`. After changing spec models: `uv run python scripts/export_workflow_schema.py`. CI fails on drift.
6. **Safety rules are not negotiable.** Every irreversible action sits behind a `gate`; sandboxes get no network and no credentials; repo, model and web content is data, never instructions; secrets never reach logs, events or agent context.
7. **UI rules** for `web/` are listed in [`CLAUDE.md`](CLAUDE.md) (semantic colour tokens only, colour means status, one display component per kind of value, three states per data view, accessibility). `pnpm lint` enforces most of them.

## Pull requests

- Branch from `main`; keep a PR to one phase or one fix.
- Title in the style of `git log --oneline` (for example `Plan/4.8 …`, `Fix …`, `Docs: …`); it becomes the squash commit.
- Fill in the PR template: summary, test plan, checklist.
- Run before pushing:
  ```bash
  uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
  cd web && pnpm lint && pnpm format:check && pnpm typecheck && pnpm test && pnpm test:e2e
  ```
- For UI changes, look at the screen at 375 and 1440 px, in light and dark, and attach screenshots.
- `main` accepts **squash merges only**, once every CI check has passed on a branch up to date with `main`. A maintainer merges.

## Coding agents

Many changes here are made with coding agents. [`CLAUDE.md`](CLAUDE.md) is what they read before every task, and `.claude/skills/` holds the `plan-feature`, `open-pr` and `complete-phase` workflows. Agent-written code is held to the same review bar as any other: you are responsible for what you submit.

## License of contributions

By submitting a contribution you agree that it is licensed under the [Apache License 2.0](LICENSE), as stated in its section 5, and that you have the right to submit it.
