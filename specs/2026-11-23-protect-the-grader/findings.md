# Findings: Protect the grader (group 4 spike)

What was run, on what, and what it showed. Anything not listed here was **not** run.

## ruff (run)

Run with `scan.lint {node, config: "base"}` on the host's ruff (the fake sandbox), a real git repo with a committed base config and a writer's worktree branch:

- A writer that adds an unused import and changes `ruff.toml` from `select = ["F"]` to `select = ["E"]`: its own config reports nothing, the base's reports `src/bad.py` (F401). 
- A writer that removes the base's `ruff.toml` and adds a `src/ruff.toml` that ignores `F`: the base's config is back and the nested file is gone, so the finding is reported.
- A writer that changes `[tool.ruff.lint]` in `pyproject.toml`: with the base's `pyproject.toml` laid over the archived tree, ruff reads the base's table and reports the finding. A `pyproject.toml` has no safe "table only" merge, so the whole file is the base's for the lint copy; it is never written back.
- The checkout's `ruff.toml` and the writer's worktree are unchanged afterwards, and the `config-*` directory under the staging directory is removed.

Decision: the overlay is `agentic_tools.tree.base_config_tree`: archive the writer's branch, remove every analyzer config file (`ANALYZER_CONFIG_GLOBS`) the base does not have, replace the ones it has with the base's, and replace a `pyproject.toml` the base has. It lists files with `git ls-tree -r -z` on both trees (`agentic_sandbox.tree_paths`), so it works after a restore.

## .NET analyzers (not run)

`.editorconfig`, `*.globalconfig` and `Directory.Build.props` are laid over the tree by the same code, but this has **not** been run against a real .NET repo: no .NET SDK image run was made for 13.5. Whether a `dotnet build` reads the base's `.editorconfig` at the tree root is the build's documented behaviour, not something this phase observed. Lessons rule 14 applies: the Docker fixture (`test_scan_dotnet_docker.py`-style) and a real run on a .NET repo are still to do before the .NET half of "analyzers use the base's config" is called done.

## Known gaps (unchanged from the plan)

- Analyzer settings inside a `.csproj` (`NoWarn`, `AnalysisLevel`, `TreatWarningsAsErrors`) and suppressions written in code (`# noqa`, `#pragma warning disable`, `biome-ignore`) are not caught here.
- A `pyproject.toml` of a module the writer **added** has no base copy to match; it is left as the writer wrote it.
