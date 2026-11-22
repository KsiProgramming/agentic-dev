"""Which package manager restores a module, from its lockfile (13.2), and whether the image's
toolchain can build it.

`DESCRIBE_SCRIPT` prints the manifests and lockfiles of one module (its directory is its only
argument, besides a random marker); `describe` reads them, and `plan` turns that into the
module's `Plan`s, one per ecosystem, each ready to run or carrying the fixed reason it cannot.
"""

import json
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal, cast

from agentic_tools.build.report import Ecosystem

type Manager = Literal["npm", "pnpm", "yarn1", "yarn4", "uv-lock", "uv-requirements"]

NODE_MAJOR = 22
PYTHON_VERSION = (3, 12)
MANAGER_MAJORS: Mapping[str, int] = {"npm": 10, "pnpm": 10, "yarn1": 1, "yarn4": 4}
"""What the sandbox image holds: Node's major, Python's major and minor, the managers' majors."""
MANAGER_VERSIONS: Mapping[str, str] = {
    "npm": "10.9.2",
    "pnpm": "10.34.9",
    "yarn1": "1.22.22",
    "yarn4": "4.19.0",
    "uv-lock": "0.9.30",
    "uv-requirements": "0.9.30",
}
"""The managers' exact versions in the image."""
MANAGER_NAME: Mapping[Manager, str] = {
    "npm": "npm",
    "pnpm": "pnpm",
    "yarn1": "yarn",
    "yarn4": "yarn",
    "uv-lock": "uv",
    "uv-requirements": "uv",
}

CONFINE_FAILED = 125
GENERATED_REQUIREMENTS = ".agentic-requirements.txt"

_LIMIT = 262144
_LOCK_HEAD = 4096
# Prints each file of the module that decides how it is restored, after a marker line `$2 <name>`;
# the marker is random, so a file cannot forge another's section. Symlinks are not followed, and
# lockfiles other than poetry's are cut short (the first bytes tell yarn's formats apart).
DESCRIBE_SCRIPT = f"""
root=$(pwd -P)
cd -P -- "./$1" 2>/dev/null || exit {CONFINE_FAILED}
case "$(pwd -P)/" in "$root"/*) ;; *) exit {CONFINE_FAILED} ;; esac
marker=$2
show() {{
  if [ -f "$1" ] && [ ! -L "$1" ]; then echo "$marker $1"; head -c "$2" "$1"; echo; fi
}}
for f in package.json .yarnrc.yml pyproject.toml; do show "$f" {_LIMIT}; done
for f in package-lock.json pnpm-lock.yaml yarn.lock uv.lock; do show "$f" {_LOCK_HEAD}; done
show poetry.lock 2097152
for f in requirements*.txt; do show "$f" {_LIMIT}; done
exit 0
"""


@dataclass(frozen=True)
class Described:
    """A module's manifests and lockfiles, as text."""

    files: Mapping[str, str]


def describe(stdout: str, marker: str) -> Described:
    files: dict[str, str] = {}
    name: str | None = None
    lines: list[str] = []
    for line in stdout.split("\n"):
        if line.startswith(f"{marker} "):
            if name is not None:
                files[name] = "\n".join(lines)
            name, lines = line[len(marker) + 1 :], []
        elif name is not None:
            lines.append(line)
    if name is not None:
        files[name] = "\n".join(lines)
    return Described(files)


@dataclass(frozen=True)
class Plan:
    """What to run for one module and ecosystem."""

    ecosystem: Ecosystem
    manager: Manager | None
    lockfile: str | None
    skip: str | None = None
    """A reason the module is not restored, and that is fine (`skipped: no lockfile`)."""
    fail: str | None = None
    """A reason the module cannot be restored or built (`needs Node 20`)."""
    has_build_script: bool = False
    project: bool = False
    """Python: the module is itself a package to build (it has a `[build-system]`)."""
    build_requires: tuple[str, ...] = ()
    """Python: what its build backend needs, fetched while the network is up."""
    requirements: str | None = None
    """Python: the requirements file to install, in the module or the generated one."""
    generated: str | None = None
    """Python: the contents of the requirements file the work copy gets."""
    hashes: bool = False
    """Python: the requirements are hash-pinned (from `poetry.lock`)."""


def as_table(value: object) -> dict[str, Any]:
    """`value` if it is a mapping (parsed JSON or TOML), else an empty one."""
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def as_list(value: object) -> list[Any]:
    """`value` if it is a list (parsed JSON or TOML), else an empty one."""
    return cast("list[Any]", value) if isinstance(value, list) else []


def _json(text: str | None) -> dict[str, Any]:
    try:
        return as_table(json.loads(text or ""))
    except ValueError:
        return {}


def toml_table(text: str | None) -> dict[str, Any]:
    try:
        return tomllib.loads(text or "")
    except tomllib.TOMLDecodeError:
        return {}


_COMPARATOR = re.compile(r"^(>=|<=|>|<|=|\^|~)?v?(\d+)(?:\.(\d+|x|\*))?")


def node_range_allows(spec: str, major: int) -> bool:
    """Whether a Node `engines` range (`>=18`, `^20 || ^22`, `20.x`) allows `major`. A range not
    understood allows it: only a clear mismatch stops a build."""
    alternatives = [a for a in spec.split("||") if a.strip()]
    return not alternatives or any(_all_hold(a, major) for a in alternatives)


def _all_hold(alternative: str, major: int) -> bool:
    for token in re.sub(r"(>=|<=|>|<|=|\^|~)\s+", r"\1", alternative.strip()).split():
        found = _COMPARATOR.match(token)
        if found is None:
            continue
        op, wanted, minor = found.group(1) or "=", int(found.group(2)), found.group(3)
        exact_minor = minor is not None and minor not in ("x", "*") and int(minor) > 0
        holds = {
            ">=": major >= wanted,
            ">": major > wanted,
            "<=": major <= wanted,
            "<": major <= wanted if exact_minor else major < wanted,
            "=": major == wanted,
            "^": major == wanted,
            "~": major == wanted,
        }[op]
        if not holds:
            return False
    return True


def python_range_allows(spec: str, version: tuple[int, int]) -> bool:
    """Whether a `requires-python` specifier set allows `version`; a specifier not understood
    allows it."""
    for part in spec.split(","):
        found = re.match(r"^\s*(>=|<=|>|<|==|~=|!=)\s*(\d+)(?:\.(\d+|\*))?", part)
        if found is None:
            continue
        op, major, minor_text = found.group(1), int(found.group(2)), found.group(3)
        wildcard = minor_text in (None, "*")
        target = (major, 0 if wildcard else int(minor_text or 0))
        same_major = version[0] == major
        holds = {
            ">=": version >= target,
            ">": version[0] > major if wildcard else version > target,
            "<=": version[0] <= major if wildcard else version <= target,
            "<": version < target,
            "==": same_major if wildcard else version == target,
            "~=": same_major and version >= target,
            "!=": not same_major if wildcard else version != target,
        }[op]
        if not holds:
            return False
    return True


def _first_number(spec: str) -> str:
    found = re.search(r"\d+(?:\.\d+)?", spec)
    return found.group(0) if found else "another version"


def _needs_manager(package_manager: object, manager: Manager) -> str | None:
    """`needs <manager> <major>` when `packageManager` names another major than the image's."""
    if not isinstance(package_manager, str):
        return None
    found = re.match(r"^(npm|pnpm|yarn)@(\d+)", package_manager)
    if found is None or found.group(1) != MANAGER_NAME[manager]:
        return None
    major = int(found.group(2))
    return None if major == MANAGER_MAJORS[manager] else f"needs {found.group(1)} {major}"


def _plan_node(described: Described) -> Plan | None:
    files = described.files
    if "package.json" not in files:
        return None
    manifest = _json(files["package.json"])
    manager: Manager
    if "pnpm-lock.yaml" in files:
        manager, lockfile = "pnpm", "pnpm-lock.yaml"
    elif "package-lock.json" in files:
        manager, lockfile = "npm", "package-lock.json"
    elif "yarn.lock" in files:
        berry = "__metadata:" in files["yarn.lock"]
        manager, lockfile = ("yarn4" if berry else "yarn1"), "yarn.lock"
    else:
        return Plan("node", None, None, skip="skipped: no lockfile")
    scripts = as_table(manifest.get("scripts"))
    plan = Plan("node", manager, lockfile, has_build_script="build" in scripts)
    node_range = as_table(manifest.get("engines")).get("node")
    if manager == "yarn4" and re.search(r"^yarnPath\s*:", files.get(".yarnrc.yml", ""), re.M):
        fail = "the repo's own yarn release is not run"
    elif isinstance(node_range, str) and not node_range_allows(node_range, NODE_MAJOR):
        fail = f"needs Node {_first_number(node_range)}"
    else:
        fail = _needs_manager(manifest.get("packageManager"), manager)
    return replace(plan, fail=fail)


def _requirements_file(files: Mapping[str, str]) -> str | None:
    names = sorted(n for n in files if re.fullmatch(r"requirements.*\.txt", n))
    return "requirements.txt" if "requirements.txt" in files else (names[0] if names else None)


def _dependencies(pyproject: dict[str, Any]) -> list[str]:
    deps = as_list(as_table(pyproject.get("project")).get("dependencies"))
    return [d for d in deps if isinstance(d, str)]


def _plan_python(described: Described, poetry_requirements: str | None) -> Plan | None:
    files = described.files
    requirements = _requirements_file(files)
    if not (
        "pyproject.toml" in files or "uv.lock" in files or "poetry.lock" in files or requirements
    ):
        return None
    pyproject = toml_table(files.get("pyproject.toml"))
    build_system = pyproject.get("build-system")
    requires = tuple(
        r for r in as_list(as_table(build_system).get("requires")) if isinstance(r, str)
    )
    common = Plan(
        "python",
        "uv-requirements",
        None,
        project=isinstance(build_system, dict),
        build_requires=requires,
    )
    if "uv.lock" in files:
        plan = replace(common, manager="uv-lock", lockfile="uv.lock")
    elif "poetry.lock" in files:
        plan = replace(
            common,
            lockfile="poetry.lock",
            requirements=GENERATED_REQUIREMENTS,
            generated=poetry_requirements,
            hashes=True,
        )
    elif requirements:
        plan = replace(common, lockfile=requirements, requirements=requirements)
    else:
        dependencies = _dependencies(pyproject)
        if not dependencies:
            return Plan("python", None, None, skip="skipped: no lockfile")
        plan = replace(
            common, requirements=GENERATED_REQUIREMENTS, generated="\n".join(dependencies) + "\n"
        )
    required = as_table(pyproject.get("project")).get("requires-python")
    if isinstance(required, str) and not python_range_allows(required, PYTHON_VERSION):
        plan = replace(plan, fail=f"needs Python {_first_number(required)}")
    return plan


def plan(
    described: Described, ecosystems: tuple[Ecosystem, ...], poetry_requirements: str | None = None
) -> list[Plan]:
    """The plans for one module: Node when it has a `package.json`, Python when it has a
    `pyproject.toml`, a lockfile or requirements; one each in a module with both.
    `poetry_requirements` is `poetry.lock` read into hash-pinned requirements."""
    plans: list[Plan | None] = []
    if "node" in ecosystems:
        plans.append(_plan_node(described))
    if "python" in ecosystems:
        plans.append(_plan_python(described, poetry_requirements))
    return [p for p in plans if p is not None]
