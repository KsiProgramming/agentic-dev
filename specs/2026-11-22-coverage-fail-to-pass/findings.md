# Findings: coverage and fail-to-pass (13.4)

Spike run 2026-11-22 in the current sandbox image (`agentic-dev/sandbox:dev`, Python 3.12.13, uv 0.9.30, .NET SDK 10.0.403), with the network disconnected for every test and coverage run.

## Python (verified on a real run)

| Question | Choice | Rests on |
|---|---|---|
| Coverage source | coverage.py 7.17.1 from a pinned wheel baked into the image (`/opt/build/wheels/`), put on the job's path, not the project's pytest-cov | `py3-none-any` wheel (219,074 bytes, sha256 `fda10238…041f`, published 2026-11-03), pure Python, same file for amd64 and arm64. Installed into the module's venv from the file during the offline job, `python -m coverage` works with no C tracer (slower, `COVERAGE_CORE=sysmon` on 3.12). |
| Executable lines | `coverage json`: per file `executed_lines` and `missing_lines`; executable = both | Run on a sample module: `pkg/calc.py` gave executed `[1,2,5,6,8,11]`, missing `[7,12]`. `--source=.` lists files that were never imported. |
| Per-test results | pytest `--junitxml` (`xunit2` default) | `<testcase classname="tests.test_calc" name="test_ac_001_adds">`. There is **no `file` attribute**: the file comes from `classname`. |
| A test that cannot import on the base | Counts as "failing before": a linked test is *proven* when it passes on the change and is **not reported passed** on the base | pytest ends the run with `Interrupted: 1 error during collection`, and the JUnit holds one `<testcase classname="" name="tests.test_new">` with an `<error>`: the module, not the test's name. The id can never be read from it, so "failed before" cannot mean "reported failed". |
| Selecting on the base | `-k` with the ids (as `ac_001 or ac_002`), then the result is filtered by the id regex | `-k` ran only the matching tests. |

## .NET (verified on a real run, `test_build_coverage_dotnet_docker.py`)

| Question | Choice | Rests on |
|---|---|---|
| Coverage source | Microsoft's collector, `dotnet test --collect "Code Coverage;Format=cobertura"`, no package added | A solution of one class library and one xUnit project (`Microsoft.NET.Test.Sdk` 17.14.1, xunit 2.9.3), restored on the NuGet network and tested on `none`: the Cobertura file was written under the results directory and read from the job's output. The changed lines, counted by hand (the change adds `Double`, run by a test, and `Triple`, run by none), came back as 2 changed, 1 covered, line 7 uncovered. |
| Per-test results | TRX, as 13.3 reads it | `AC001_Adds` and `AC002_Doubles` came back as cases with their ids and `passed`. |
| A base that cannot build | The change's test file laid over the base calls a method the base lacks: the run is `failed` with the fixed reason `the base run did not build`, no cases, and so every linked test fails before | Run for real: the whole test project failed to compile on the base. |
| Selecting on the base | `--filter "FullyQualifiedName~AC002|…"` | Only the script is exercised here (a base that builds and passes some tests was not run for .NET): **not verified** beyond the build-failure case. |

## Found by running it

- The runner reassigned the dict that held `cases` and `coverage` after seeding it, so the scripted unit tests passed while the real job's report had neither. The Docker run on the Python fixture showed it (lessons 14 again).
- A Python module needs a `pyproject.toml` to be found (`MODULES_SCRIPT`); a repo with only `requirements.txt` is not a module.

## Not verified in this session

- 13.3's leftovers on real Jest, Vitest and `node:test` repos and 13.3's Docker fixtures for Node (Node is 13.11 for 13.4's checks).
- .NET `--filter` on a base that builds.
- The e2e run on a rebuilt stack, and the real run on GitHub Copilot.
- **13.3's leftovers** on real Jest, Vitest and node:test repos: not run. Node is 13.11 here.
