"""What the restore and build jobs run for each package manager (13.2), and the fixed reasons their
failures are reported as.

The restore job is the only one with a network. It downloads and unpacks, and runs no code of the
repo: lifecycle scripts are off, Python takes wheels only, and the repo's own yarn release,
pnpm hook and package sources are gone from the work copy (`workdir`). Lifecycle scripts, the
repo's own build and the build of its own Python package run afterwards, in a job with no network,
from the caches the restore filled.

Every script is a fixed string; what varies is passed as arguments or environment variables, so
nothing from the repo is interpolated into a shell.
"""

import re
from collections.abc import Mapping, Sequence

from agentic_tools.build.report import Ecosystem
from agentic_tools.build.stack import Manager, Plan

TIMED_OUT = 124
PACKAGES_MARKER = "::packages::"

NPM_REGISTRY = "https://registry.npmjs.org"
UV_CONFIG = "/opt/build/uv.toml"
NPMRC = "/opt/build/npmrc"

# The restores: `$CACHE` is the manager's cache directory, `$HTTPS_PROXY` the registry's proxy
# (set by the sandbox for the job). Each ends by printing about how many packages are installed.
_COUNT_NODE = (
    f'echo "{PACKAGES_MARKER} '
    '$(find -L node_modules -maxdepth 3 -name package.json 2>/dev/null | wc -l)"'
)
# pnpm links only a module's direct dependencies into node_modules; its store holds them all.
_COUNT_PNPM = (
    f'echo "{PACKAGES_MARKER} '
    "$(ls node_modules/.pnpm 2>/dev/null | grep -v -e '^node_modules$' -e '^lock.yaml$' | wc -l)"
    '"'
)
_RESTORE: Mapping[Manager, str] = {
    "npm": "npm ci --ignore-scripts --no-audit --no-fund",
    "pnpm": 'pnpm install --frozen-lockfile --ignore-scripts --store-dir "$CACHE"',
    "yarn1": (
        "yarn install --frozen-lockfile --ignore-scripts --non-interactive "
        f'--cache-folder "$CACHE" --registry {NPM_REGISTRY} --https-proxy "$HTTPS_PROXY"'
    ),
    "yarn4": "yarn4 install --immutable --mode=skip-build",
}
_BUILD_NODE: Mapping[Manager, tuple[str, str]] = {
    "npm": ("npm rebuild", "npm run build"),
    "pnpm": ('pnpm rebuild --store-dir "$CACHE"', "pnpm run build"),
    "yarn1": ("npm rebuild", "yarn run build"),
    "yarn4": ("yarn4 rebuild", "yarn4 run build"),
}

_UV = f"--config-file {UV_CONFIG}"
# `$@`: what the module's build backend needs, fetched into the cache so the offline build finds
# it (the wheels, never an sdist).
_WARM = (
    f'if [ $# -gt 0 ]; then uv pip install {_UV} --no-build --target ../warm "$@" || exit $?; fi'
)
_COUNT_PYTHON = (
    f'echo "{PACKAGES_MARKER} '
    '$(uv pip list --python .venv/bin/python 2>/dev/null | tail -n +3 | wc -l)"'
)


def cache_dir(staging_dir: str, plan: Plan) -> str:
    """The manager's cache, in the staging directory so it outlives the work copy and later jobs
    install offline from it."""
    name = plan.manager or "none"
    return f"{staging_dir}/.cache/{name}"


def job_env(staging_dir: str, work: str, plan: Plan, *, online: bool) -> Mapping[str, str]:
    cache = cache_dir(staging_dir, plan)
    env = {"HOME": f"{work}/home", "CACHE": cache}
    if plan.ecosystem == "node":
        env |= {
            "npm_config_userconfig": NPMRC,
            "npm_config_globalconfig": "/dev/null",
            "npm_config_cache": cache,
            "npm_config_update_notifier": "false",
            "YARN_ENABLE_TELEMETRY": "false",
            "YARN_ENABLE_GLOBAL_CACHE": "true",
            "YARN_GLOBAL_FOLDER": cache,
            "YARN_NPM_REGISTRY_SERVER": NPM_REGISTRY,
        }
        if online:
            env["YARN_ENABLE_SCRIPTS"] = "false"
        else:
            env |= {"npm_config_offline": "true", "YARN_ENABLE_NETWORK": "false"}
    else:
        env |= {"UV_CACHE_DIR": cache}
    return env


def restore_script(plan: Plan) -> tuple[str, Sequence[str]]:
    """The restore job's `sh -c` script, and its arguments."""
    if plan.ecosystem == "node":
        assert plan.manager is not None
        yarn = 'export YARN_HTTPS_PROXY="$HTTPS_PROXY"\n' if plan.manager == "yarn4" else ""
        return f"{yarn}{_RESTORE[plan.manager]} || exit $?\n{_COUNT_NODE}\n", ()
    if plan.manager == "uv-lock":
        install = f"uv sync {_UV} --frozen --no-install-project --no-install-workspace --no-build"
    else:
        hashes = "--require-hashes --no-deps " if plan.hashes else ""
        install = (
            f"uv venv {_UV} -q .venv || exit $?\n"
            f"uv pip install {_UV} --python .venv/bin/python --no-build {hashes}"
            f"-r {plan.requirements}"
        )
    return f"{install} || exit $?\n{_WARM}\n{_COUNT_PYTHON}\n", plan.build_requires


def build_script(plan: Plan) -> str | None:
    """The build job's `sh -c` script, or None when there is nothing to build."""
    if plan.ecosystem == "node":
        assert plan.manager is not None
        rebuild, run = _BUILD_NODE[plan.manager]
        return f"{rebuild} || exit $?\n" + (f"{run}\n" if plan.has_build_script else "")
    if not plan.project:
        return None
    if plan.manager == "uv-lock":
        return f"uv sync {_UV} --frozen --offline --no-editable\n"
    return f"uv pip install {_UV} --python .venv/bin/python --offline --no-deps .\n"


def packages_in(output: str) -> int | None:
    """The package count the restore script printed, or None."""
    found = re.findall(rf"^{re.escape(PACKAGES_MARKER)} (\d+)\s*$", output, re.MULTILINE)
    count = int(found[-1]) if found else 0
    return count or None


_PACKAGE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
_OUT_OF_DATE = re.compile(
    r"in sync|ERR_PNPM_OUTDATED_LOCKFILE|lockfile needs to be updated|YN0028|"
    r"lockfile.{0,40}(out of date|needs to be updated)|would be modified",
    re.IGNORECASE,
)
_NOT_FOUND = re.compile(
    r"\bE404\b|404 Not Found|ERR_PNPM_FETCH_404|YN0035|Response Code: 404|"
    r"not found in the package registry|No solution found|couldn't find",
    re.IGNORECASE,
)
_ELSEWHERE = re.compile(
    r"EUNSUPPORTEDPROTOCOL|git\+|git@|ssh://|git (ls-remote|clone|fetch)|\bE403\b|403 Forbidden|"
    r"CONNECT tunnel failed|ERR_PNPM_.*(GIT|TARBALL)|github\.com|codeload|"
    r"Git (URL|dependency)|direct URL|YN0001.*(git|https?://)",
    re.IGNORECASE,
)
_NO_WHEEL = re.compile(
    r"--no-build|no-build|doesn't have a source distribution or wheel|no wheels? with a matching|"
    r"wheel.{0,40}(platform|current)|requires building|cannot be built",
    re.IGNORECASE,
)
_WHEEL_OF = re.compile(r"`([A-Za-z0-9][A-Za-z0-9._-]*)(?:[=<>!~@ \]\[][^`]*)?`")


def _wheel_less(text: str) -> str:
    found = _WHEEL_OF.search(text)
    name = found.group(1) if found and _PACKAGE_NAME.match(found.group(1)) else "a package"
    return f"restore failed: {name} has no wheel for this platform"


def restore_failure(ecosystem: Ecosystem, exit_code: int, output: str) -> str:
    """The fixed reason a failed restore is reported as, read from the job's exit code and
    output; never the tool's own words."""
    if exit_code == TIMED_OUT:
        return "restore timed out"
    registry = "npm" if ecosystem == "node" else "PyPI"
    if _OUT_OF_DATE.search(output):
        return "restore failed: the lockfile is out of date"
    if ecosystem == "python" and _NO_WHEEL.search(output):
        return _wheel_less(output)
    if _ELSEWHERE.search(output):
        return "restore failed: a dependency comes from git or a URL"
    if _NOT_FOUND.search(output):
        return f"restore failed: a package is not on {registry}"
    return f"restore failed (exit {exit_code})"
