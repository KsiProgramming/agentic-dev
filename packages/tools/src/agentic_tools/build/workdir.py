"""The work copy a restore runs in (13.2): the module without its VCS data, dependencies and build
output, and without the repo's own say over where packages come from.

A repo picks its packages, never its package sources (4.8's rule, for npm and PyPI): the copy
drops `.npmrc`, `.yarnrc`, `pip.conf`, `uv.toml`, `.pnpmfile.cjs` (a pnpm hook that runs code) and
yarn's vendored releases and plugins. `.yarnrc.yml` and `pyproject.toml`'s `[tool.uv]` keep only
the keys that set the repo's layout. `poetry.lock` is read here, not by poetry, so no plugin a
repo declares runs; a requirements file keeps only its requirements.
"""

import json
import re
import tomllib
from collections.abc import Mapping
from datetime import date, datetime, time
from typing import Any

from agentic_tools.build.stack import CONFINE_FAILED, as_list, as_table, toml_table

# Copies the module `$2` (confined to the repo, which is the current directory) into `$1/src`,
# and drops the files that name package sources or run code. `$3` is `yarn1` when yarn 1 is the
# manager: its lockfile names registry.yarnpkg.com, which the platform's allowlist does not.
COPY_SCRIPT = f"""
work=$1; module=$2; manager=$3
root=$(pwd -P)
cd -P -- "./$module" 2>/dev/null || exit {CONFINE_FAILED}
case "$(pwd -P)/" in "$root"/*) ;; *) exit {CONFINE_FAILED} ;; esac
mkdir -p "$work/src" "$work/home" || exit 1
tar -cf - --exclude=.git --exclude=node_modules --exclude=./.venv --exclude=./dist \\
  --exclude=./build . | tar -C "$work/src" -xf - || exit 1
cd "$work/src" || exit 1
find . \\( -name .npmrc -o -name .yarnrc -o -name pip.conf -o -name uv.toml \\
  -o -name .pnpmfile.cjs \\) -delete
rm -rf ./.yarn/releases ./.yarn/plugins
if [ "$manager" = yarn1 ] && [ -f yarn.lock ]; then
  sed -i 's#https://registry.yarnpkg.com/#https://registry.npmjs.org/#g' yarn.lock || exit 1
fi
exit 0
"""

# Moves a staged file into the work copy: `$1` is the staged file, `$2` the work directory, `$3`
# the file's name in the copy.
PLACE_SCRIPT = """
mv -f -- "$1" "$2/src/$3"
"""

YARNRC_KEYS = frozenset({"nodeLinker", "pnpMode", "enableGlobalCache"})
UV_KEYS = frozenset(
    {"package", "managed", "dev-dependencies", "default-groups", "required-version", "workspace"}
)
FROM_ELSEWHERE = "restore failed: a dependency comes from git or a URL"


class Refused(Exception):
    """A module cannot be restored, for a fixed reason that is safe to show."""


def prune_yarnrc(text: str) -> str:
    """`.yarnrc.yml` with only the layout keys (`nodeLinker`, `pnpMode`, `enableGlobalCache`), each
    a plain top-level `key: value` line."""
    kept: list[str] = []
    for line in text.splitlines():
        found = re.match(r"^([A-Za-z]+)\s*:\s*([A-Za-z0-9._-]+)\s*(?:#.*)?$", line)
        if found and found.group(1) in YARNRC_KEYS:
            kept.append(f"{found.group(1)}: {found.group(2)}")
    return "\n".join(kept) + "\n" if kept else ""


def prune_pyproject(text: str) -> str | None:
    """`pyproject.toml` rewritten without what names a package source, or None if it has none.

    In `[tool.uv]` only the layout keys stay, and of `sources` only the entries that are
    `{ workspace = true }`; `[tool.uv.pip]`, `index`, `find-links` and the rest are dropped."""
    data = toml_table(text)
    tool = as_table(data.get("tool"))
    uv = as_table(tool.get("uv"))
    if not uv:
        return None
    kept = {k: v for k, v in uv.items() if k in UV_KEYS}
    workspace = {k: v for k, v in as_table(uv.get("sources")).items() if v == {"workspace": True}}
    if workspace:
        kept["sources"] = workspace
    if kept == uv:
        return None
    return dump_toml({**data, "tool": {**tool, "uv": kept}})


_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def _key(key: str) -> str:
    return key if _BARE_KEY.match(key) else json.dumps(key)


def _value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if (items := as_list(value)) or value == []:
        return "[" + ", ".join(_value(v) for v in items) + "]"
    if (mapping := as_table(value)) or value == {}:
        return "{ " + ", ".join(f"{_key(k)} = {_value(v)}" for k, v in mapping.items()) + " }"
    raise TypeError(f"cannot write {type(value).__name__} as TOML")


def _is_table(value: object) -> bool:
    return isinstance(value, dict)


def _is_table_list(value: object) -> bool:
    items = as_list(value)
    return bool(items) and all(isinstance(v, dict) for v in items)


def _plain(value: object) -> bool:
    return not _is_table(value) and not _is_table_list(value)


def dump_toml(table: Mapping[str, Any], prefix: tuple[str, ...] = ()) -> str:
    """`table` as TOML: scalars and arrays first, then sub-tables and arrays of tables."""
    lines = [f"{_key(k)} = {_value(v)}" for k, v in table.items() if _plain(v)]
    out = "\n".join(lines) + "\n" if lines else ""
    for key, value in table.items():
        path = (*prefix, key)
        header = ".".join(_key(p) for p in path)
        if _is_table(value):
            out += f"\n[{header}]\n{dump_toml(as_table(value), path)}"
        elif _is_table_list(value):
            for item in as_list(value):
                out += f"\n[[{header}]]\n{dump_toml(as_table(item), path)}"
    return out


_REQUIREMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9._,\s-]+\])?\s*([=<>!~(;].*)?$")


def safe_requirements(text: str) -> str:
    """A requirements file's requirements, with each option line dropped (`--index-url`,
    `--find-links`, `-r`, `-c`, …) so the file cannot name a package source. A requirement that
    is a path, a URL or a VCS reference, or an editable one, is refused: `Refused`."""
    kept: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("--hash=") or line == "\\":
            kept.append(raw)
            continue
        if line.startswith("-"):
            if line.split()[0] in ("-e", "--editable"):
                raise Refused(FROM_ELSEWHERE)
            continue
        requirement = line.removesuffix("\\").strip()
        spec = requirement.split(" --hash", 1)[0].split(";", 1)[0]
        if re.search(r"[@/]|://", spec) or not _REQUIREMENT.match(requirement):
            raise Refused(FROM_ELSEWHERE)
        kept.append(raw)
    return "\n".join(kept) + "\n"


def poetry_requirements(text: str) -> str:
    """`poetry.lock` as hash-pinned requirements for `uv pip install --require-hashes --no-deps`.

    Raises `Refused` for a package from git, a URL, a path or another index."""
    try:
        lock = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        raise Refused("restore failed: the lockfile cannot be read") from None
    lines: list[str] = []
    for package in as_list(lock.get("package")):
        entry = as_table(package)
        source = as_table(entry.get("source"))
        if source.get("type") in ("git", "url", "directory", "file"):
            raise Refused(FROM_ELSEWHERE)
        if source.get("type") == "legacy":
            raise Refused("restore failed: a package is not on PyPI")
        name, version = entry.get("name"), entry.get("version")
        if not (isinstance(name, str) and isinstance(version, str)):
            continue
        requirement = f"{name}=={version}"
        marker = entry.get("markers")
        if isinstance(marker, str) and marker:
            requirement += f" ; {marker}"
        hashes = [
            f"--hash={f['hash']}"
            for f in map(as_table, as_list(entry.get("files")))
            if isinstance(f.get("hash"), str)
        ]
        lines.append(" \\\n    ".join([requirement, *hashes]))
    return "\n".join(lines) + "\n" if lines else ""
