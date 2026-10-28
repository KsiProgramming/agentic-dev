"""The `scan` server on a scripted sandbox: recorded scanner output in, `FindingsReport` out (4.4).
The real scanners run in `test_scan_docker.py`."""

import json
from collections.abc import Callable, Sequence
from typing import Any

import pytest
from mcp import Client

from agentic_sandbox import ExecResult
from agentic_tools.scan import (
    SCAN_TOOL_NAMES,
    Finding,
    ScanLimits,
    build_report,
    build_scan_server,
    fingerprint,
)
from agentic_tools.scan.server import PLATFORM_CONFIG_DIR

WORKDIR = "/workspace/repo"
STAGING = "/workspace/.incoming"
LEAKED = "hunter2-very-secret-value-0123456789"

RUFF = [
    {
        "code": "F401",
        "filename": f"{WORKDIR}/api/app.py",
        "location": {"row": 1, "column": 8},
        "end_location": {"row": 1, "column": 10},
        "message": "`os` imported but unused",
        "severity": "error",
        "url": "https://docs.astral.sh/ruff/rules/unused-import",
    },
    {
        "code": None,
        "filename": f"{WORKDIR}/api/bad.py",
        "location": {"row": 3, "column": 1},
        "message": "SyntaxError: Expected an expression",
        "severity": "error",
    },
    {"code": "F401", "filename": "/etc/passwd", "location": {"row": 1}, "message": "outside"},
]
BIOME = [
    {
        "description": "The use of the recommended field has been deprecated.",
        "check_name": "deserialize",
        "severity": "minor",
        "location": {"path": "biome.json", "lines": {"begin": 1}},
    },
    {
        "description": "Using == may be unsafe if you are relying on type coercion.",
        "check_name": "lint/suspicious/noDoubleEquals",
        "severity": "critical",
        "location": {"path": "src/index.ts", "lines": {"begin": 2}},
    },
]
SHELLCHECK = {
    "comments": [
        {
            "file": "./ops/deploy.sh",
            "line": 2,
            "endLine": 2,
            "level": "warning",
            "code": 2164,
            "message": "Use 'cd ... || exit' in case cd fails.",
        }
    ]
}
# As gitleaks writes it without `--redact`: the server must not need redaction to be safe.
GITLEAKS = [
    {
        "RuleID": "generic-api-key",
        "Description": "Detected a Generic API Key.",
        "StartLine": 4,
        "EndLine": 4,
        "Match": f'API_KEY = "{LEAKED}"',
        "Secret": LEAKED,
        "File": "cfg/settings.py",
        "Fingerprint": f"cfg/settings.py:generic-api-key:4:{LEAKED}",
    }
]
OSV = {
    "results": [
        {
            "source": {"path": f"{WORKDIR}/api/requirements.txt", "type": "lockfile"},
            "packages": [
                {
                    "package": {"name": "jinja2", "version": "2.10", "ecosystem": "PyPI"},
                    "groups": [
                        {
                            "ids": ["PYSEC-2019-217", "GHSA-462w-v97r-4m45"],
                            "aliases": ["CVE-2019-10906", "GHSA-462w-v97r-4m45"],
                            "max_severity": "8.6",
                        },
                        {"ids": ["GHSA-aaaa-bbbb-cccc"], "aliases": [], "max_severity": ""},
                    ],
                    "vulnerabilities": [
                        {
                            "id": "GHSA-462w-v97r-4m45",
                            "summary": "Jinja2 sandbox escape via str.format_map",
                            "affected": [
                                {
                                    "package": {"name": "jinja2"},
                                    "ranges": [
                                        {"events": [{"introduced": "0"}, {"fixed": "2.10.1"}]}
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    ]
}

PROBE = (
    "./api/pyproject.toml\n./web/package.json\n./svc/go.mod\n::dirs::\n./api\n./svc\n./web\n"
    "::configs::\nruff ./api/pyproject.toml\n::sources::\n./api/app.py\n./ops/deploy.sh\n"
)
VERSIONS = (
    "ruff ruff 0.17.0 \nbiome Version: 2.5.15 \nshellcheck ShellCheck version: 0.11.0 \n"
    "gitleaks 8.30.1 \nosv-scanner osv-scanner version: 2.7.0 \nosv-db 2026-10-28\n"
)

Engine = Callable[[list[str]], tuple[int, str]]


class ScriptedSandbox:
    """Answers the server's commands from `engines` (engine name -> (exit code, its report)),
    keeping each report in a staging file the server then takes."""

    workdir = WORKDIR
    worktrees_dir = "/workspace/worktrees"
    staging_dir = STAGING
    artifacts_dir = "/workspace/artifacts"

    def __init__(self, engines: dict[str, Engine], probe: str = PROBE) -> None:
        self.engines = engines
        self.probe = probe
        self.files: dict[str, bytes] = {}
        self.runs: list[tuple[str, list[str]]] = []

    async def exec(
        self, argv: Sequence[str], *, timeout_s: float = 30.0, cwd: str | None = None
    ) -> ExecResult:
        name = argv[3]
        if name == "versions":
            return ExecResult(exit_code=0, stdout=VERSIONS, stderr="")
        if name == "probe":
            return ExecResult(exit_code=0, stdout=self.probe, stderr="")
        if name == "lines":
            pairs = list(argv[4:])
            return ExecResult(
                exit_code=0,
                stdout="".join(
                    f"line {pairs[i]}:{pairs[i + 1]}\n" for i in range(0, len(pairs), 2)
                ),
                stderr="",
            )
        if len(argv) == 5:  # the path check
            outside = argv[4].startswith("..")
            return ExecResult(exit_code=4 if outside else 0, stdout="", stderr="")
        out, directory, command = argv[4], argv[5], list(argv[6:])
        self.runs.append((directory, command))
        code, report = self.engines[command[0]](command)
        own = next(
            (command[i + 1] for i, a in enumerate(command) if a in ("--report-path", "--output")),
            None,
        )
        self.files[out] = b"" if own else report.encode()
        if own:
            self.files[own] = report.encode()
        return ExecResult(exit_code=code, stdout="", stderr="" if code in (0, 1) else "boom")

    async def take_file(self, path: str) -> bytes:
        return self.files.pop(path)


def _ok(report: object, code: int = 0) -> Engine:
    return lambda _argv: (code, json.dumps(report))


def _fails(code: int = 2) -> Engine:
    return lambda _argv: (code, "")


async def _call(sandbox: ScriptedSandbox, tool: str, **arguments: Any) -> tuple[bool, Any, str]:
    server = build_scan_server(sandbox, limits=ScanLimits(max_findings=50))  # type: ignore[arg-type]
    async with Client(server) as client:
        result = await client.call_tool(tool, arguments)
    text = "\n".join(c.text for c in result.content if c.type == "text")
    return result.is_error, result.structured_content, text


ALL_LINTERS = {"ruff": _ok(RUFF), "biome": _ok(BIOME, 1), "shellcheck": _ok(SHELLCHECK, 1)}


async def test_the_server_offers_the_three_scan_tools() -> None:
    async with Client(build_scan_server(ScriptedSandbox({}))) as client:  # type: ignore[arg-type]
        names = {f"scan.{t.name}" for t in (await client.list_tools()).tools}
    assert names == SCAN_TOOL_NAMES == {"scan.lint", "scan.secrets", "scan.dependencies"}


async def test_lint_runs_each_modules_linter_and_normalises_the_findings() -> None:
    sandbox = ScriptedSandbox(ALL_LINTERS)

    is_error, report, _ = await _call(sandbox, "lint")

    assert not is_error, report
    checks = {(c["path"], c["tool"]): c for c in report["checks"]}
    assert checks[("api", "ruff")] | {"findings": 0} == {
        "path": "api",
        "kind": "python",
        "tool": "ruff",
        "config": "repo",
        "status": "ran",
        "reason": None,
        "version": "0.17.0",
        "findings": 0,
    }
    assert checks[("api", "ruff")]["findings"] == 2  # the one outside the repo is dropped
    assert checks[("web", "biome")]["config"] == "platform-default"
    assert checks[("svc", None)]["reason"] == "no supported linter for go"
    findings = {
        (f["tool"], f["rule"], f["path"], f["line"], f["severity"]) for f in report["findings"]
    }
    assert findings == {
        ("ruff", "F401", "api/app.py", 1, "medium"),
        ("ruff", "syntax-error", "api/bad.py", 3, "medium"),
        ("biome", "suspicious/noDoubleEquals", "web/src/index.ts", 2, "medium"),
        ("shellcheck", "SC2164", "ops/deploy.sh", 2, "low"),
    }
    biome = next(f for f in report["findings"] if f["tool"] == "biome")
    assert biome["help_url"] == "https://biomejs.dev/linter/rules/no-double-equals/"
    assert biome["config"] == "platform-default"
    assert report["counts"] == {"critical": 0, "high": 0, "medium": 3, "low": 1, "info": 0}


async def test_lint_runs_biome_in_its_module_and_defaults_from_the_platform_config() -> None:
    sandbox = ScriptedSandbox(ALL_LINTERS)

    await _call(sandbox, "lint")

    runs = {command[0]: (directory, command) for directory, command in sandbox.runs}
    assert runs["biome"] == (
        "web",
        [
            "biome",
            "lint",
            "--reporter=gitlab",
            "--colors=off",
            f"--config-path={PLATFORM_CONFIG_DIR}",
            "./.",
        ],
    )
    assert runs["ruff"][0] == "."
    assert "--config" not in runs["ruff"][1]  # the repo configures ruff
    assert runs["shellcheck"][1][-1] == "./ops/deploy.sh"
    assert "--severity=warning" in runs["shellcheck"][1]


async def test_lint_fingerprints_cover_the_lines_text() -> None:
    _, report, _ = await _call(ScriptedSandbox(ALL_LINTERS), "lint")

    f401 = next(f for f in report["findings"] if f["rule"] == "F401")
    assert f401["fingerprint"] == fingerprint("ruff", "F401", "api/app.py", "line api/app.py:1")


async def test_one_failing_linter_is_a_failed_check_not_an_error() -> None:
    sandbox = ScriptedSandbox({**ALL_LINTERS, "biome": _fails()})

    is_error, report, _ = await _call(sandbox, "lint")

    assert not is_error
    biome = next(c for c in report["checks"] if c["tool"] == "biome")
    assert (biome["status"], biome["reason"]) == ("failed", "biome exited with 2: boom")
    assert any(f["tool"] == "ruff" for f in report["findings"])


async def test_unreadable_output_is_a_failed_check() -> None:
    sandbox = ScriptedSandbox({**ALL_LINTERS, "ruff": lambda _a: (0, "Traceback: oops")})

    _, report, _ = await _call(sandbox, "lint")

    ruff = next(c for c in report["checks"] if c["tool"] == "ruff")
    assert ruff["status"] == "failed"
    assert ruff["reason"].startswith("ruff gave no report")


async def test_every_engine_failing_is_an_error() -> None:
    sandbox = ScriptedSandbox({"ruff": _fails(), "biome": _fails(), "shellcheck": _fails(127)})

    is_error, _, text = await _call(sandbox, "lint")

    assert is_error
    assert "every scanner failed" in text
    assert "shellcheck is not installed in the sandbox" in text


async def test_secrets_never_carry_the_secret_even_from_unredacted_output() -> None:
    is_error, report, text = await _call(ScriptedSandbox({"gitleaks": _ok(GITLEAKS)}), "secrets")

    assert not is_error
    (finding,) = report["findings"]
    assert (finding["rule"], finding["path"], finding["line"], finding["severity"]) == (
        "generic-api-key",
        "cfg/settings.py",
        4,
        "high",
    )
    assert finding["fingerprint"] == fingerprint(
        "gitleaks", "generic-api-key", "cfg/settings.py", 4
    )
    assert LEAKED not in text
    assert LEAKED not in json.dumps(report)


async def test_a_failing_secret_scan_does_not_repeat_the_engines_words() -> None:
    sandbox = ScriptedSandbox({"gitleaks": lambda _a: (2, "")})

    is_error, _, text = await _call(sandbox, "secrets")

    assert is_error
    assert text.endswith("gitleaks on .: gitleaks failed")
    assert "boom" not in text


async def test_dependencies_become_findings_per_advisory() -> None:
    is_error, report, _ = await _call(ScriptedSandbox({"osv-scanner": _ok(OSV, 1)}), "dependencies")

    assert not is_error
    assert report["db_as_of"] == "2026-10-28"
    ghsa, unknown = sorted(report["findings"], key=lambda f: f["severity"] != "high")
    assert ghsa | {"fingerprint": ""} == {
        "fingerprint": "",
        "tool": "osv-scanner",
        "rule": "GHSA-462w-v97r-4m45",
        "severity": "high",
        "category": "dependency",
        "path": "api/requirements.txt",
        "line": None,
        "end_line": None,
        "message": "jinja2 2.10: Jinja2 sandbox escape via str.format_map",
        "help_url": "https://osv.dev/vulnerability/GHSA-462w-v97r-4m45",
        "config": None,
        "package": "jinja2",
        "ecosystem": "PyPI",
        "version": "2.10",
        "fixed_versions": ["2.10.1"],
        "aliases": ["CVE-2019-10906"],
        "confidence": None,
        "sources": None,
    }
    assert unknown["severity"] == "medium"
    assert unknown["message"] == "jinja2 2.10: a known vulnerability"


async def test_no_lockfiles_is_a_skipped_check() -> None:
    sandbox = ScriptedSandbox({"osv-scanner": lambda _a: (128, "")})

    is_error, report, _ = await _call(sandbox, "dependencies")

    assert not is_error
    assert report["checks"][0]["status"] == "skipped"
    assert report["findings"] == []


@pytest.mark.parametrize("tool", ["lint", "secrets", "dependencies"])
async def test_a_path_outside_the_repo_is_refused(tool: str) -> None:
    is_error, _, text = await _call(ScriptedSandbox({}), tool, path="../../etc")

    assert is_error
    assert "inside the repository" in text


async def test_unknown_arguments_and_linters_are_refused() -> None:
    sandbox = ScriptedSandbox(ALL_LINTERS)

    assert (await _call(sandbox, "lint", paths=["."]))[0]
    assert (await _call(sandbox, "lint", linters=["eslint"]))[0]


def test_the_report_keeps_the_most_severe_findings_and_counts_them_all() -> None:
    def finding(severity: str, line: int) -> Finding:
        return Finding.model_validate(
            {
                "fingerprint": str(line),
                "tool": "t",
                "rule": "r",
                "severity": severity,
                "category": "lint",
                "path": "a.py",
                "line": line,
                "message": "m",
            }
        )

    report = build_report(
        "lint",
        [],
        [finding("low", 1), finding("critical", 9), finding("info", 2), finding("high", 3)],
        max_findings=2,
    )

    assert [f.severity for f in report.findings] == ["critical", "high"]
    assert report.truncated
    assert report.counts == {"critical": 1, "high": 1, "medium": 0, "low": 1, "info": 1}


def test_fingerprints_ignore_whitespace_but_not_content() -> None:
    assert fingerprint("ruff", "F401", "a.py", "  import os") == fingerprint(
        "ruff", "F401", "a.py", "import   os"
    )
    assert fingerprint("ruff", "F401", "a.py", "import os") != fingerprint(
        "ruff", "F401", "b.py", "import os"
    )
