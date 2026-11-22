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

## Not verified in this session

- **.NET**: `--collect "Code Coverage;Format=cobertura"` offline, the TRX per test, and `--filter` by name. Unit-tested on shaped input only; a real run is the first thing the Docker tests must do (lessons 14).
- **13.3's leftovers** on real Jest, Vitest and node:test repos: not run. Node is 13.11 here.
