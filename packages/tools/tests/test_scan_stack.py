"""`plan_lint`: which linter runs on which module, from the repo's own stack and config (4.4,
.NET 4.8)."""

from collections.abc import Sequence

from agentic_tools.repo.stack import Module
from agentic_tools.scan.stack import LintTarget, Probe, plan_lint, read_probe


def _probe(
    modules: dict[str, str],
    configs: dict[str, set[str]] | None = None,
    sources: Sequence[str] = (),
) -> Probe:
    return Probe(
        modules=[Module.model_validate({"path": p, "kind": k}) for p, k in modules.items()],
        configs={tag: frozenset(dirs) for tag, dirs in (configs or {}).items()},
        sources=list(sources),
    )


def _runs(targets: list[LintTarget]) -> list[tuple[str, str, str]]:
    return [(t.tool, t.target, t.config) for t in targets]


def _skips(probe: Probe, **kwargs: object) -> list[tuple[str, str | None, str | None]]:
    _, skipped = plan_lint(probe, **kwargs)  # type: ignore[arg-type]
    return [(c.path, c.tool, c.reason) for c in skipped]


def test_a_python_module_with_ruff_config_gets_ruff_with_it() -> None:
    targets, skipped = plan_lint(_probe({"api": "python"}, {"ruff": {"api"}}))

    assert _runs(targets) == [("ruff", "api", "repo")]
    assert skipped == []


def test_a_config_at_the_root_applies_to_the_modules_under_it() -> None:
    targets, _ = plan_lint(_probe({"a": "python", "b/c": "python"}, {"ruff": {"."}}))

    assert _runs(targets) == [("ruff", "a", "repo"), ("ruff", "b/c", "repo")]


def test_a_python_module_with_no_linter_gets_the_platform_default() -> None:
    targets, _ = plan_lint(_probe({"api": "python"}))

    assert _runs(targets) == [("ruff", "api", "platform-default")]


def test_a_module_configured_for_a_linter_we_cannot_run_is_skipped_not_replaced() -> None:
    probe = _probe({"web": "node", "api": "python"}, {"eslint": {"web"}, "flake8": {"api"}})

    targets, _ = plan_lint(probe)

    assert targets == []
    assert _skips(probe) == [
        ("web", "eslint", "eslint is not supported"),
        ("api", "flake8", "flake8 is not supported"),
    ]


def test_our_own_linter_wins_when_both_are_configured() -> None:
    targets, _ = plan_lint(_probe({"web": "node"}, {"eslint": {"web"}, "biome": {"web"}}))

    assert _runs(targets) == [("biome", "web", "repo")]


def test_stacks_with_no_supported_linter_are_skipped_with_the_reason() -> None:
    probe = _probe(
        {"svc": "go", "core": "rust", "app": "java", "fs": "dotnet", "vb": "dotnet"},
        {"fsproj": {"fs"}, "vbproj": {"vb"}},
    )

    assert plan_lint(probe)[0] == []
    assert [reason for _, _, reason in _skips(probe)] == [
        "no supported linter for go",
        "no supported linter for rust",
        "no supported linter for java",
        "no supported linter for fsharp",
        "no supported linter for vb",
    ]


def test_a_csharp_project_gets_the_dotnet_analyzers() -> None:
    probe = _probe({"src/Api": "dotnet", "src/Core": "dotnet"}, {"csproj": {"src/Api", "src/Core"}})

    targets, skipped = plan_lint(probe)

    assert _runs(targets) == [
        ("dotnet", "src/Api", "platform-default"),
        ("dotnet", "src/Core", "platform-default"),
    ]
    assert [t.kind for t in targets] == ["dotnet", "dotnet"]
    assert skipped == []


def test_analysis_set_up_by_the_repo_makes_the_dotnet_config_the_repos() -> None:
    # An `.editorconfig` with analyzer settings at the root, or a project's own analysis settings.
    probe = _probe(
        {"src/Api": "dotnet", "tools/Gen": "dotnet"},
        {"csproj": {"src/Api", "tools/Gen"}, "dotnet": {"src"}},
    )

    targets, _ = plan_lint(probe)

    assert _runs(targets) == [
        ("dotnet", "src/Api", "repo"),
        ("dotnet", "tools/Gen", "platform-default"),
    ]


def test_a_csharp_project_beside_an_fsharp_one_is_linted() -> None:
    probe = _probe({"mixed": "dotnet"}, {"csproj": {"mixed"}, "fsproj": {"mixed"}})

    assert _runs(plan_lint(probe)[0]) == [("dotnet", "mixed", "platform-default")]


def test_dotnet_is_named_like_the_other_linters() -> None:
    probe = _probe({"src/Api": "dotnet", "web": "node"}, {"csproj": {"src/Api"}})

    targets, _ = plan_lint(probe, linters=["dotnet"])

    assert _runs(targets) == [("dotnet", "src/Api", "platform-default")]
    assert _skips(_probe({"web": "node"}), linters=["dotnet"]) == [
        (".", "dotnet", "no csharp files to lint")
    ]


def test_directories_with_no_manifest_are_linted_by_the_languages_in_them() -> None:
    probe = _probe(
        {"scripts": "directory", "site": "directory", "notes": "directory"},
        sources=["scripts/run.py", "site/app.ts", "site/tool.py"],
    )

    targets, _ = plan_lint(probe)

    assert _runs(targets) == [
        ("ruff", "scripts", "platform-default"),
        ("ruff", "site", "platform-default"),
        ("biome", "site", "platform-default"),
    ]
    assert [t.kind for t in targets] == ["python", "python", "node"]


def test_shell_scripts_are_checked_once_across_the_repo() -> None:
    probe = _probe(
        {"api": "python"},
        {"ruff": {"api"}, "shellcheckrc": {"."}},
        sources=["ops/deploy.sh", "api/run.bash", "api/main.py"],
    )

    targets, _ = plan_lint(probe)

    shell = [t for t in targets if t.tool == "shellcheck"]
    assert [(t.target, t.config, t.files) for t in shell] == [
        (".", "repo", ("ops/deploy.sh", "api/run.bash"))
    ]


def test_a_path_narrows_the_plan_to_what_it_covers() -> None:
    probe = _probe(
        {"api": "python", "web": "node"},
        {"ruff": {"api"}},
        sources=["ops/deploy.sh", "api/x.sh"],
    )

    targets, _ = plan_lint(probe, path="api/sub")

    assert _runs(targets) == [("ruff", "api/sub", "repo")]
    assert targets[0].module == "api"


def test_named_linters_run_with_the_default_even_where_a_foreign_one_is_configured() -> None:
    probe = _probe({"web": "node", "api": "python"}, {"eslint": {"web"}})

    targets, skipped = plan_lint(probe, linters=["biome"])

    assert _runs(targets) == [("biome", "web", "platform-default")]
    assert skipped == []


def test_a_named_linter_with_nothing_to_lint_is_skipped_with_the_reason() -> None:
    probe = _probe({"web": "node", "svc": "go"})

    assert plan_lint(probe, linters=["ruff", "shellcheck"])[0] == []
    assert _skips(probe, linters=["ruff", "shellcheck"]) == [
        (".", "ruff", "no python files to lint"),
        (".", "shellcheck", "no shell files to lint"),
    ]


def test_read_probe_reads_modules_configs_and_sources() -> None:
    stdout = (
        "./api/pyproject.toml\n./web/package.json\n::dirs::\n./api\n./web\n"
        "::configs::\nruff ./api/pyproject.toml\neslint ./web/.eslintrc.json\nbiome ./biome.json\n"
        "::sources::\n./api/main.py\n./web/a.ts\n"
    )

    probe = read_probe(stdout)

    assert [(m.path, m.kind) for m in probe.modules] == [("api", "python"), ("web", "node")]
    assert probe.configs == {
        "ruff": frozenset({"api"}),
        "eslint": frozenset({"web"}),
        "biome": frozenset({"."}),
    }
    assert probe.sources == ["api/main.py", "web/a.ts"]


def test_read_probe_reads_dotnet_projects_and_analysis_configs() -> None:
    stdout = (
        "./src/Api/Api.csproj\n./src/Fs/Fs.fsproj\n::dirs::\n./src\n"
        "::configs::\ncsproj ./src/Api/Api.csproj\ndotnet ./src/Api/Api.csproj\n"
        "fsproj ./src/Fs/Fs.fsproj\ndotnet ./.editorconfig\n::sources::\n"
    )

    probe = read_probe(stdout)

    assert [(m.path, m.kind) for m in probe.modules] == [
        ("src/Api", "dotnet"),
        ("src/Fs", "dotnet"),
    ]
    assert probe.configs == {
        "csproj": frozenset({"src/Api"}),
        "dotnet": frozenset({"src/Api", "."}),
        "fsproj": frozenset({"src/Fs"}),
    }
