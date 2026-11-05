"""Which linter `scan.lint` runs where (4.4), from the repo's own stack and config, never a
generic set.

`PROBE_SCRIPT` lists, with no user argument, the repo's modules (`repo.stack`), the linter
configs in it and its source files; `plan_lint` turns that into one `LintTarget` per module and
language, or a skipped `Check` saying why:

- the module configures a linter we run (ruff, Biome): that linter, with the repo's config;
- it configures one we cannot run offline (ESLint, flake8, pylint): skipped, never replaced;
- a language we lint with no linter configured: our linter with the platform's conservative
  rules, its findings marked `platform-default`;
- a C# project (4.8): the `dotnet` engine, a build with the SDK's analyzers and the repo's own
  (`agentic_tools.scan.dotnet`), config `repo` when the repo sets analysis up (an `.editorconfig`
  with `dotnet_`/`csharp_` settings, a `.globalconfig`, or analysis settings or analyzer packages
  in a project or `Directory.Build.props`), else `platform-default` (the SDK's defaults);
- a stack we have no linter for (Go, Rust, Java, F#, VB): skipped.

Shell scripts are checked once, across the repo, by ShellCheck. A config applies to its directory
and everything under it, as the linters themselves look for it.
"""

import posixpath
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from agentic_tools.repo.stack import (
    MANIFEST_DEPTH,
    MODULES_SCRIPT,
    SKIPPED_DIRS,
    Module,
    find_modules,
)
from agentic_tools.scan.report import Check, ConfigSource

type Linter = Literal["ruff", "biome", "shellcheck", "dotnet"]
LINTERS: tuple[Linter, ...] = ("ruff", "biome", "shellcheck", "dotnet")

type Language = Literal["python", "node", "shell", "csharp"]

_LINTER_OF: Mapping[Language, Linter] = {
    "python": "ruff",
    "node": "biome",
    "shell": "shellcheck",
    "csharp": "dotnet",
}
_LANGUAGE_OF: Mapping[Linter, Language] = {v: k for k, v in _LINTER_OF.items()}

# A config file marks the linter it belongs to. Foreign linters are ones we cannot run offline;
# a module configured for one is skipped rather than linted by another tool.
_OWN = {"ruff": "ruff", "biome": "biome", "dotnet": "dotnet"}
_FOREIGN: Mapping[Language, tuple[str, ...]] = {
    "python": ("flake8", "pylint"),
    "node": ("eslint",),
    "csharp": (),
}
_UNSUPPORTED_KINDS = ("go", "rust", "java")
# What a .NET module holds besides C#, named in its skip reason.
_DOTNET_OTHERS = (("fsproj", "fsharp"), ("vbproj", "vb"))
# MSBuild settings that mean the repo set its analysis up (in a project or Directory.Build.props).
_DOTNET_ANALYSIS = (
    'AnalysisLevel|AnalysisMode|Analyzers"|CodeAnalysisRuleSet|EnforceCodeStyleInBuild'
)

_SOURCE_EXTENSIONS: Mapping[str, Language] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "node",
    ".jsx": "node",
    ".mjs": "node",
    ".cjs": "node",
    ".ts": "node",
    ".tsx": "node",
    ".mts": "node",
    ".cts": "node",
    ".sh": "shell",
    ".bash": "shell",
}
MAX_SOURCE_FILES = 5000
"""The most source files the probe lists (the shell scripts ShellCheck gets, and the languages
of directories with no manifest)."""

_PRUNE = " -o ".join(f"-name {name}" for name in ("'.*'", *SKIPPED_DIRS))
_CONFIG_NAMES = " -o ".join(
    f"-name '{n}'"
    for n in (
        "pyproject.toml",
        "ruff.toml",
        ".ruff.toml",
        "setup.cfg",
        "tox.ini",
        ".flake8",
        ".pylintrc",
        "pylintrc",
        "biome.json",
        "biome.jsonc",
        ".eslintrc*",
        "eslint.config.*",
        "package.json",
        ".shellcheckrc",
        "*.csproj",
        "*.fsproj",
        "*.vbproj",
        "Directory.Build.props",
        ".editorconfig",
        "*.globalconfig",
    )
)
_SOURCE_NAMES = " -o ".join(f"-name '*{ext}'" for ext in _SOURCE_EXTENSIONS)

PROBE_SCRIPT = f"""{MODULES_SCRIPT}
echo ::configs::
find . -mindepth 1 -maxdepth {MANIFEST_DEPTH + 1} \\( -type d \\( {_PRUNE} \\) -prune \\) \\
  -o -type f \\( {_CONFIG_NAMES} \\) -print | while IFS= read -r f; do
  case "$f" in
    */pyproject.toml)
      grep -qE '^\\[tool\\.ruff' "$f" && echo "ruff $f"
      grep -qE '^\\[tool\\.flake8' "$f" && echo "flake8 $f"
      grep -qE '^\\[tool\\.pylint' "$f" && echo "pylint $f" ;;
    */setup.cfg|*/tox.ini) grep -qE '^\\[flake8\\]' "$f" && echo "flake8 $f" ;;
    */package.json) grep -q '"eslintConfig"' "$f" && echo "eslint $f" ;;
    */ruff.toml|*/.ruff.toml) echo "ruff $f" ;;
    */.flake8) echo "flake8 $f" ;;
    */.pylintrc|*/pylintrc) echo "pylint $f" ;;
    */biome.json|*/biome.jsonc) echo "biome $f" ;;
    */.shellcheckrc) echo "shellcheckrc $f" ;;
    *.csproj)
      echo "csproj $f"
      grep -qE '{_DOTNET_ANALYSIS}' "$f" && echo "dotnet $f" ;;
    *.fsproj) echo "fsproj $f" ;;
    *.vbproj) echo "vbproj $f" ;;
    */Directory.Build.props) grep -qE '{_DOTNET_ANALYSIS}' "$f" && echo "dotnet $f" ;;
    */.editorconfig) grep -qE '^[[:space:]]*(dotnet_|csharp_)' "$f" && echo "dotnet $f" ;;
    *.globalconfig) echo "dotnet $f" ;;
    *) echo "eslint $f" ;;
  esac
done
echo ::sources::
find . -mindepth 1 \\( -type d \\( {_PRUNE} \\) -prune \\) \\
  -o -type f \\( {_SOURCE_NAMES} \\) -print | head -n {MAX_SOURCE_FILES}
"""


@dataclass(frozen=True)
class Probe:
    """What `PROBE_SCRIPT` found: modules, config tags (tag -> directories holding one) and
    source files, all relative to the repo root."""

    modules: list[Module]
    configs: Mapping[str, frozenset[str]]
    sources: list[str]


def read_probe(stdout: str) -> Probe:
    head, _, rest = stdout.partition("::configs::")
    configs_part, _, sources_part = rest.partition("::sources::")
    configs: dict[str, set[str]] = {}
    for line in configs_part.splitlines():
        tag, _, path = line.partition(" ")
        if path.startswith("./"):
            configs.setdefault(tag, set()).add(posixpath.dirname(path[2:]) or ".")
    sources = [line[2:] for line in sources_part.splitlines() if line.startswith("./")]
    return Probe(
        modules=find_modules(head),
        configs={tag: frozenset(dirs) for tag, dirs in configs.items()},
        sources=sources,
    )


@dataclass(frozen=True)
class LintTarget:
    """One linter run: `tool` on `target` (the module, or the `path` asked for inside it), with
    `config` found in `module`'s directory or above it. ShellCheck gets `files`."""

    tool: Linter
    module: str
    target: str
    kind: str
    config: ConfigSource
    files: tuple[str, ...] = ()


def _under(path: str, directory: str) -> bool:
    return directory == "." or path == directory or path.startswith(f"{directory}/")


def _ancestors(directory: str) -> list[str]:
    out = [directory]
    while directory != ".":
        directory = posixpath.dirname(directory) or "."
        out.append(directory)
    return out


def _configured(probe: Probe, module: str, tags: Iterable[str]) -> str | None:
    """The first of `tags` with a config in `module` or a directory above it."""
    for directory in _ancestors(module):
        for tag in tags:
            if directory in probe.configs.get(tag, ()):
                return tag
    return None


def _languages(module: Module, probe: Probe) -> list[Language]:
    if module.kind == "python":
        return ["python"]
    if module.kind == "node":
        return ["node"]
    if module.kind == "dotnet":
        return ["csharp"] if module.path in probe.configs.get("csproj", ()) else []
    if module.kind in ("directory", "repo"):
        found = {
            _SOURCE_EXTENSIONS[posixpath.splitext(s)[1]]
            for s in probe.sources
            if _under(s, module.path) and posixpath.splitext(s)[1] in _SOURCE_EXTENSIONS
        }
        return [lang for lang in ("python", "node") if lang in found]
    return []


def _scope(module: str, path: str) -> str | None:
    """What to lint of `module` when `path` is asked for: all of it, the part asked for, or
    nothing."""
    if _under(module, path):
        return module
    if _under(path, module):
        return path
    return None


def plan_lint(
    probe: Probe, path: str = ".", linters: Collection[Linter] | None = None
) -> tuple[list[LintTarget], list[Check]]:
    """The linter runs for `path` and the checks skipped, from the repo's stack (`linters` is
    None, `auto`) or for the linters named."""
    targets: list[LintTarget] = []
    skipped: list[Check] = []
    explicit = linters is not None
    wanted = set(LINTERS if linters is None else linters)
    seen_languages: set[Language] = set()
    for module in probe.modules:
        target = _scope(module.path, path)
        if target is None:
            continue
        if module.kind in _UNSUPPORTED_KINDS:
            if not explicit:
                skipped.append(
                    Check(
                        path=target,
                        kind=module.kind,
                        tool=None,
                        status="skipped",
                        reason=f"no supported linter for {module.kind}",
                    )
                )
            continue
        languages = _languages(module, probe)
        if module.kind == "dotnet" and not languages:
            if not explicit:
                other = next(
                    (
                        name
                        for tag, name in _DOTNET_OTHERS
                        if module.path in probe.configs.get(tag, ())
                    ),
                    "dotnet",
                )
                skipped.append(
                    Check(
                        path=target,
                        kind=module.kind,
                        tool=None,
                        status="skipped",
                        reason=f"no supported linter for {other}",
                    )
                )
            continue
        for language in languages:
            linter = _LINTER_OF[language]
            if linter not in wanted:
                continue
            seen_languages.add(language)
            kind = module.kind if module.kind in ("python", "node", "dotnet") else language
            own = _configured(probe, module.path, [_OWN[linter]])
            foreign = _configured(probe, module.path, _FOREIGN[language])
            if own is not None:
                config: ConfigSource = "repo"
            elif foreign is not None and not explicit:
                skipped.append(
                    Check(
                        path=target,
                        kind=kind,
                        tool=foreign,
                        status="skipped",
                        reason=f"{foreign} is not supported",
                    )
                )
                continue
            else:
                config = "platform-default"
            targets.append(LintTarget(linter, module.path, target, kind, config))
    if "shellcheck" in wanted:
        scripts = tuple(
            s
            for s in probe.sources
            if posixpath.splitext(s)[1] in (".sh", ".bash") and _under(s, path)
        )
        if scripts:
            seen_languages.add("shell")
            config = "repo" if probe.configs.get("shellcheckrc") else "platform-default"
            targets.append(LintTarget("shellcheck", ".", path, "shell", config, scripts))
    if explicit:
        for linter in sorted(wanted, key=LINTERS.index):
            language = _LANGUAGE_OF[linter]
            if language not in seen_languages:
                skipped.append(
                    Check(
                        path=path,
                        kind=language,
                        tool=linter,
                        status="skipped",
                        reason=f"no {language} files to lint",
                    )
                )
    return targets, skipped
