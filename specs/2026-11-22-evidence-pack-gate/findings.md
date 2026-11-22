# Findings: test runners offline (13.3)

Written while building 13.3, **before** the planned spike on real sample repos was run. The plan's group 1 asked for five sample repos (Jest and Vitest, pytest with `uv.lock` and with `requirements.txt`, xUnit), each restored on the registry network and built and tested on `none` in the current sandbox image. That needs the registry proxies and the image from 13.2 running, and it was not done in this session. What follows says what each choice rests on, and what a real run still has to confirm. Per lessons rule 10, treat everything marked "not verified" as a conditional go.

## What was decided, and on what

| Open question | Choice | Rests on | Verified? |
|---|---|---|---|
| How to get Node test counts | Read the runner's own summary line from the job's output: Jest `Tests: N failed, N passed, N total`, Vitest `Tests  N failed \| N passed (N)`, `node:test` as spec (`ℹ tests N`) or TAP (`# tests N`). No JUnit reporter. | A JUnit reporter is a package the repo may not have, and adding one would change the repo. These summaries are what the runners print, and a run with none still has its exit code (`failed`, with no counts). | Parsers are tested on text shaped like each runner's output (`test_build_test.py`). **Not verified** against real Jest, Vitest or Node output of the versions in the image. |
| Node test command | The module's `test` script, run by the lockfile's manager (`npm test`, `pnpm run test`, `yarn run test`, `yarn4 run test`) with `CI=true`; npm's placeholder (`no test specified`) is no script | The same managers and offline environment as the build job (13.2). | **Not verified** offline. A test script that needs a browser or a service will fail, which is reported as `tests failed`. |
| How to detect pytest | The project's `pyproject.toml` has `[tool.pytest…]` or mentions `pytest` (a dependency or group), or a `requirements*.txt` line starts with `pytest` | The restore installs what those files name, so a project that does not list pytest cannot run it. `uv.lock` is only read for its first 4 KB, so `pyproject.toml` decides. | Unit-tested. **Not verified** on a `uv.lock` project with pytest in a dependency group. |
| Where pytest's results land | `--junitxml` in the work copy, printed after a marker by the job and read from stdout | A job's only output is its result; files in the work copy are removed. | Tested with a scripted job. **Not verified** in a real job. |
| Test timeout | 600 s (`BuildLimits.test_timeout_s`), like the build | The plan's default. | No sample repo needed more; none was run. |
| .NET | Not run (`no supported test runner for dotnet`) | `dotnet test` needs `scan.lint`'s solution restore and a TRX reader. | Out of this session. A follow-up. |

## Not done

- The Docker tests on fixture repos (plan 3, last item): Node, Python and .NET, each passing and failing, a test that reaches the network failing, and the checkout unchanged. The job code is the same as 13.2's (`run_job`, network `none`), whose Docker tests exist, but 13.3's own are not written.
- The real run on GitHub Copilot (plan 6, last item): a real repo, a writer that breaks a test, read step by step in the console. It needs a personal Copilot connection and the stack, and was not done. The flow is covered by fake-runtime tests that assert what the writer receives (`test_evidence_gate.py`, `test_ac2_checks.py`, `packages/store/tests/test_evidence_gate.py`).
- The e2e specs (a passing and a failing pack at 375 and 1440 px, light and dark, with axe) are written (`layout.spec.ts`, `a11y.spec.ts`, helpers in `runs.ts`) and typecheck, but were not run: they need the compose stack rebuilt with this change.

## Decisions-log rows

The rows for these choices are in `specs/tech-stack.md` (decisions log, "13.3").
