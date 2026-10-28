"""The `scan` tools in the real sandbox image (4.4): each scanner finds what is planted in a small
monorepo, `auto` lints by each module's own stack, and a secret never leaves the sandbox. Needs
Docker; the image is built from `packages/sandbox` if the daemon lacks it."""

import json
import secrets
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import docker
import pytest
from docker.errors import DockerException
from mcp import Client

from agentic_sandbox import RepoSource, Sandbox
from agentic_sandbox.docker_backend import DockerSandboxManager
from agentic_sandbox.testing import ensure_sandbox_image, make_repo
from agentic_tools.scan import build_scan_server

pytestmark = pytest.mark.integration

# A monorepo with one planted issue per scanner. `legacy/` is configured for ESLint, which the
# sandbox cannot run: it must be skipped, not linted by Biome. `svc/` is Go: no supported linter.
MONOREPO: dict[str, str] = {
    "py/pyproject.toml": '[project]\nname = "py"\nversion = "0"\n\n'
    '[tool.ruff.lint]\nselect = ["F"]\n',
    "py/app.py": "import os\n\n\ndef f():\n    return undefined_name\n",
    "py/requirements.txt": "jinja2==2.10\n",
    "web/package.json": '{"name": "web", "version": "1.0.0"}\n',
    "web/biome.json": '{"linter": {"enabled": true, "rules": {"recommended": true}}}\n',
    "web/index.ts": "export function eq(a: unknown, b: unknown) {\n  return a == b;\n}\n",
    "legacy/package.json": '{"name": "legacy", "version": "1.0.0"}\n',
    "legacy/eslint.config.js": "export default [];\n",
    "legacy/index.js": "var x = 1\nif (x == 2) {}\n",
    "svc/go.mod": "module example.com/svc\n\ngo 1.22\n",
    "svc/main.go": "package main\n\nfunc main() {}\n",
    "scripts/deploy.sh": "#!/bin/sh\ncd $1\n",
}


@pytest.fixture(scope="module")
def secret() -> str:
    """A fresh, high-entropy credential, so no real-looking secret is committed to this repo."""
    return secrets.token_urlsafe(30)


@pytest.fixture
async def sandbox(tmp_path: Path, secret: str) -> AsyncIterator[Sandbox]:
    try:
        client = docker.from_env()
        client.ping()
    except DockerException:
        pytest.skip("no Docker daemon")
    ensure_sandbox_image(client)
    repos = tmp_path / "repos"
    files = {**MONOREPO, "cfg/settings.py": f'aws_secret_access_key = "{secret}"\n'}
    make_repo(repos / "mono", files)
    manager = DockerSandboxManager(client, local_root=repos)
    async with manager.open(uuid4(), RepoSource(url=str(repos / "mono"))) as box:
        yield box


async def _call(sandbox: Sandbox, tool: str, **arguments: Any) -> tuple[bool, dict[str, Any], str]:
    async with Client(build_scan_server(sandbox)) as client:
        result = await client.call_tool(tool, arguments)
    text = "\n".join(c.text for c in result.content if c.type == "text")
    return result.is_error, result.structured_content or {}, text


def _checks(report: dict[str, Any]) -> dict[tuple[str, str | None], dict[str, Any]]:
    return {(c["path"], c["tool"]): c for c in report["checks"]}


async def test_auto_lints_each_module_with_its_own_stack(sandbox: Sandbox) -> None:
    is_error, report, _ = await _call(sandbox, "lint")

    assert not is_error, report
    checks = _checks(report)
    assert checks[("py", "ruff")] | {"version": None} == {
        "path": "py",
        "kind": "python",
        "tool": "ruff",
        "config": "repo",
        "status": "ran",
        "reason": None,
        "version": None,
        "findings": 2,
    }
    assert checks[("web", "biome")]["config"] == "repo"
    assert checks[("legacy", "eslint")]["status"] == "skipped"
    assert checks[("legacy", "eslint")]["reason"] == "eslint is not supported"
    assert ("legacy", "biome") not in checks
    assert checks[("svc", None)]["reason"] == "no supported linter for go"
    assert checks[(".", "shellcheck")]["config"] == "platform-default"
    assert checks[("py", "ruff")]["version"] == "0.17.0"
    found = {(f["tool"], f["rule"], f["path"], f["line"]) for f in report["findings"]}
    assert found == {
        ("ruff", "F401", "py/app.py", 1),
        ("ruff", "F821", "py/app.py", 5),
        ("biome", "suspicious/noDoubleEquals", "web/index.ts", 2),
        ("shellcheck", "SC2164", "scripts/deploy.sh", 2),
    }
    assert all(f["path"] != "legacy/index.js" for f in report["findings"])


async def test_a_module_with_no_linter_config_gets_the_platform_default(
    sandbox: Sandbox,
) -> None:
    is_error, report, _ = await _call(sandbox, "lint", linters=["biome"], path="legacy")

    assert not is_error, report
    (check,) = report["checks"]
    assert check["tool"] == "biome"
    assert check["config"] == "platform-default"
    assert [(f["rule"], f["config"]) for f in report["findings"]] == [
        ("suspicious/noDoubleEquals", "platform-default")
    ]


async def test_named_linters_run_only_where_their_language_is(sandbox: Sandbox) -> None:
    is_error, report, _ = await _call(sandbox, "lint", linters=["ruff"], path="web")

    assert not is_error
    assert report["checks"] == [
        {
            "path": "web",
            "kind": "python",
            "tool": "ruff",
            "config": None,
            "status": "skipped",
            "reason": "no python files to lint",
            "version": None,
            "findings": 0,
        }
    ]
    assert report["findings"] == []


async def test_fingerprints_are_stable_across_calls(sandbox: Sandbox) -> None:
    _, first, _ = await _call(sandbox, "lint", path="py")
    _, second, _ = await _call(sandbox, "lint", path="py")

    prints = [f["fingerprint"] for f in first["findings"]]
    assert prints == [f["fingerprint"] for f in second["findings"]]
    assert len(set(prints)) == 2


async def test_secrets_are_found_and_never_returned(sandbox: Sandbox, secret: str) -> None:
    is_error, report, text = await _call(sandbox, "secrets")

    assert not is_error, report
    (finding,) = report["findings"]
    assert (finding["tool"], finding["path"], finding["line"], finding["severity"]) == (
        "gitleaks",
        "cfg/settings.py",
        1,
        "high",
    )
    assert secret not in text
    assert secret not in json.dumps(report)


async def test_vulnerable_dependencies_are_found_offline(sandbox: Sandbox) -> None:
    is_error, report, _ = await _call(sandbox, "dependencies")

    assert not is_error, report
    assert report["db_as_of"]
    (check,) = report["checks"]
    assert check["status"] == "ran"
    jinja = [f for f in report["findings"] if f["package"] == "jinja2"]
    assert jinja and all(f["path"] == "py/requirements.txt" for f in jinja)
    cve = next(f for f in jinja if "CVE-2019-10906" in f["aliases"])
    assert (cve["severity"], cve["ecosystem"], cve["version"]) == ("high", "PyPI", "2.10")
    assert "2.10.1" in cve["fixed_versions"]


async def test_a_directory_with_no_lockfile_is_skipped(sandbox: Sandbox) -> None:
    is_error, report, _ = await _call(sandbox, "dependencies", path="web")

    assert not is_error
    assert report["checks"][0]["status"] == "skipped"
    assert report["checks"][0]["reason"] == "no lockfiles"


async def test_a_path_outside_the_repo_is_refused(sandbox: Sandbox) -> None:
    is_error, _, text = await _call(sandbox, "lint", path="../etc")

    assert is_error
    assert "inside the repository" in text
