"""A repository's modules and their stack, from the manifests in it: shared by `repo.list_modules`
and the `scan` tools (4.4), so agents and scanners agree on what the repo's stack is.

`MODULES_SCRIPT` runs in the sandbox with no user argument; `find_modules` reads its output.
"""

import posixpath
from fnmatch import fnmatchcase
from typing import Literal

from pydantic import BaseModel, Field

type ModuleKind = Literal["python", "node", "go", "rust", "java", "dotnet", "directory", "repo"]

# Manifest file names (or `*.ext` patterns) and the module kind each marks, in priority order.
MANIFESTS: tuple[tuple[str, ModuleKind], ...] = (
    ("pyproject.toml", "python"),
    ("package.json", "node"),
    ("go.mod", "go"),
    ("Cargo.toml", "rust"),
    ("pom.xml", "java"),
    ("*.csproj", "dotnet"),
)
# Directories that never hold a module: dependencies, build output and existing docs. Hidden
# directories are skipped too.
SKIPPED_DIRS = ("node_modules", "vendor", "dist", "build", "target", "venv", "docs")
MANIFEST_DEPTH = 3

# Prints the manifests in directories down to `MANIFEST_DEPTH` levels, a marker line, then the
# top-level directories. No user argument reaches the script.
_FIND_NAMES = " -o ".join(f"-name '{name}'" for name, _ in MANIFESTS)
_FIND_SKIPPED = " -o ".join(f"-name {name}" for name in ("'.*'", *SKIPPED_DIRS))
MODULES_SCRIPT = f"""
find . -mindepth 1 -maxdepth {MANIFEST_DEPTH + 1} \\( -type d \\( {_FIND_SKIPPED} \\) -prune \\) \\
  -o -type f \\( {_FIND_NAMES} \\) -print || exit 1
echo ::dirs::
find . -mindepth 1 -maxdepth 1 -type d ! -name '.*' -print || exit 1
"""


class Module(BaseModel):
    path: str = Field(description="The module's directory, relative to the repository root.")
    kind: ModuleKind = Field(
        description="What marks it: its manifest's ecosystem, `directory` for a top-level "
        "directory of a repo with no manifests, `repo` for the whole repository."
    )


class ModulesOut(BaseModel):
    """The repository's modules, sorted by path."""

    modules: list[Module]
    truncated: bool = Field(description="True when more modules were found than are listed.")


def _manifest_kind(name: str) -> ModuleKind | None:
    return next((kind for pattern, kind in MANIFESTS if fnmatchcase(name, pattern)), None)


def find_modules(stdout: str) -> list[Module]:
    """Modules from `MODULES_SCRIPT`'s output: each directory with a manifest (the root only
    when nothing below it has one, as a workspace root just groups its members); else each
    top-level directory; else the whole repository."""
    manifests, _, dirs = stdout.partition("::dirs::")
    kinds: dict[str, ModuleKind] = {}
    for line in manifests.splitlines():
        if not line.startswith("./"):
            continue
        directory, name = posixpath.split(line[2:])
        kind = _manifest_kind(name)
        current = kinds.get(directory or ".")
        if kind is not None and (current is None or _rank(kind) < _rank(current)):
            kinds[directory or "."] = kind
    if len(kinds) > 1:
        kinds.pop(".", None)
    if kinds:
        return [Module(path=path, kind=kind) for path, kind in sorted(kinds.items())]
    top = sorted(
        line[2:]
        for line in dirs.splitlines()
        if line.startswith("./") and line[2:] not in SKIPPED_DIRS
    )
    if top:
        return [Module(path=path, kind="directory") for path in top]
    return [Module(path=".", kind="repo")]


def _rank(kind: ModuleKind) -> int:
    return next(i for i, (_, k) in enumerate(MANIFESTS) if k == kind)
