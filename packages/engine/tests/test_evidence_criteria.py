# ruff: noqa: E501
"""Coverage of the changed lines and fail-to-pass per criterion at a gate (13.4): the
engine reads the spec's criteria, asks `build.test` for the tests that name them (on the change, then
on the base), and sends work back through 13.3's path when a criterion is not proven or the changed
lines are not covered. The tests assert what the writer is handed, which jobs ran with which
arguments, and what the gate shows (lessons, rule 1)."""

from collections.abc import Mapping
from typing import Any

from pydantic import JsonValue

from agentic_engine.policy import PLATFORM_POLICY
from agentic_engine.spec import GateEvidence, WorkflowSpec, parse_spec, validate_workflow
from agentic_runtime import Message, ToolOutput
from agentic_runtime.fake import ECHO_USAGE, CallTool, FakeRuntime, Step

from .test_evidence_gate import APPROVE, Checks, Run, by_kind, pack_of

SPEC = """# Feature specification: Sum

## Requirements

- FR-001: The system shall add.

## Acceptance criteria

- AC-001: When two numbers are given, the system shall return their sum.
- AC-002: When none are given, the system shall return zero.

## Out of scope

AC-009 is mentioned here and is not a criterion.
"""


def case(name: str, status: str = "passed", *ids: str) -> dict[str, JsonValue]:
    return {"name": name, "file": "tests/test_sum.py", "status": status, "ids": list(ids)}


def module(
    *cases: dict[str, JsonValue],
    coverage: dict[str, JsonValue] | None = None,
    **extra: JsonValue,
) -> dict[str, JsonValue]:
    mod: dict[str, JsonValue] = {
        "path": ".", "ecosystem": "python", "runner": "pytest", "status": "passed",
        "build": "ran", "passed": len(cases), "failed": 0, "skipped": 0, "failures": [],
        "test_ms": 100, "cases": list(cases), "coverage": coverage,
    }  # fmt: skip
    mod.update(extra)
    return mod


def report(*modules: dict[str, JsonValue]) -> ToolOutput:
    return ToolOutput(
        text="tests", data={"tool": "build.test", "checks": list(modules), "truncated": False}
    )


def covering(changed: int, covered: int, *missed: tuple[int, int]) -> dict[str, JsonValue]:
    return {
        "changed": changed,
        "covered": covered,
        "files": [
            {"path": "src/sum.py", "changed": changed, "covered": covered,
             "uncovered": [list(m) for m in missed]}
        ] if changed else [],
        "truncated": False,
    }  # fmt: skip


BOTH_LINKED = report(
    module(case("tests.test_sum::test_ac_001_adds", "passed", "AC-001"),
           case("tests.test_sum::test_ac_002_zero", "passed", "AC-002"),
           coverage=covering(10, 10))
)  # fmt: skip
ONE_LINKED = report(
    module(case("tests.test_sum::test_ac_001_adds", "passed", "AC-001"), coverage=covering(10, 10))
)
NOT_ON_BASE = report(module())  # nothing linked passes on the base
PASSES_ON_BASE = report(
    module(case("tests.test_sum::test_ac_001_adds", "passed", "AC-001"),
           case("tests.test_sum::test_ac_002_zero", "passed", "AC-002"))
)  # fmt: skip


class Judged(Checks):
    """`Checks` whose base run (`on: base`) answers from its own queue."""

    def __init__(self, tests: list[ToolOutput], base: list[ToolOutput] | None = None) -> None:
        super().__init__(tests)
        self.base_tests = base or [NOT_ON_BASE]

    async def call(
        self, name: str, arguments: dict[str, JsonValue], *, node_id: str | None = None
    ) -> ToolOutput:
        if name == "build.test" and arguments.get("on") == "base":
            self.jobs.append((name, arguments, node_id))
            return self.base_tests.pop(0) if len(self.base_tests) > 1 else self.base_tests[0]
        return await super().call(name, arguments, node_id=node_id)


def spec(
    *,
    checks: Mapping[str, str] | None = None,
    max_rounds: int = 2,
    coverage_min: int | None = None,
    criteria_from: str | None = None,
) -> WorkflowSpec:
    chosen = {"build": "shown", "tests": "shown", "analyzers": "off",
              "coverage": "required", "criteria": "required"}  # fmt: skip
    chosen.update(checks or {})
    evidence: dict[str, Any] = {"node": "writer", "max_rounds": max_rounds, "checks": chosen}
    if coverage_min is not None:
        evidence["coverage_min"] = coverage_min
    if criteria_from is not None:
        evidence["criteria_from"] = criteria_from
    document: dict[str, Any] = {
        "spec_version": "0",
        "id": "criteria",
        "name": "Criteria",
        "root": {
            "type": "sequence",
            "id": "main",
            "steps": [
                {
                    "type": "agent",
                    "id": "speccer",
                    "role": "Spec",
                    "instructions": "Spec.",
                    "tools": [],
                    "writes": "spec.md",
                },
                {
                    "type": "loop",
                    "id": "build",
                    "max_iterations": 5,
                    "until": 'results.check.data.decision != "changes"',
                    "body": {
                        "type": "sequence",
                        "id": "round",
                        "steps": [
                            {
                                "type": "agent",
                                "id": "writer",
                                "role": "Writer",
                                "instructions": "Make the change.",
                                "tools": ["repo.write_file", "repo.commit"],
                            },
                            {
                                "type": "gate",
                                "id": "check",
                                "title": "Merge this?",
                                "evidence": evidence,
                            },
                        ],
                    },
                },
            ],
        },
    }
    return parse_spec(document)  # fmt: skip


def run_of(workflow: WorkflowSpec, tools: Judged) -> Run:
    run = Run(workflow, tools)
    # Each repetition differs, as a writer's work does: the same call five times in one step is
    # what the repeat breaker (13.7) pauses.
    work: list[Step] = [
        step
        for i in range(6)
        for step in (
            CallTool("repo.write_file", {"path": "a.py", "content": f"x{i}"}),
            CallTool("repo.commit", {"message": f"work {i}"}),
            Message(text="Done."),
            ECHO_USAGE,
        )
    ]
    run.runtime = FakeRuntime(
        {"speccer": [Message(text=SPEC), ECHO_USAGE], "writer": work}, tools=tools
    )
    return run


def criteria_of(run: Run, index: int = 0) -> dict[str, Any]:
    check = by_kind(pack_of(run, index))["criteria"]
    return {c["id"]: c for c in check["detail"]["criteria"]}


async def test_a_criterion_with_no_test_sends_the_writer_back_with_no_person() -> None:
    run = run_of(spec(), Judged([ONE_LINKED, BOTH_LINKED], [NOT_ON_BASE]))

    first = await run.start()

    assert first.status == "waiting"
    sent = run.events("gate_decided")[0].payload
    assert (sent["decision"], sent["source"]) == ("changes", "checks")
    assert "decided_by" not in sent
    _, second = (r for r in run.runtime.requests if r.node_id == "writer")
    assert second.input.startswith("## Criteria\n\n- 1 of 2 proven")
    assert "- AC-002: no test names it" in second.input
    assert "AC-001:" not in second.input  # a proven criterion is not sent back
    assert "AC-009" not in second.input  # only the criteria section is read
    # The second pass proved both, and the gate paused with the criteria it shows.
    states = {k: c["state"] for k, c in criteria_of(run).items()}
    assert states == {"AC-001": "proven", "AC-002": "proven"}
    assert criteria_of(run)["AC-001"]["before"] == "fails"


async def test_a_test_that_also_passes_on_the_base_proves_nothing() -> None:
    run = run_of(spec(max_rounds=1), Judged([BOTH_LINKED], [PASSES_ON_BASE]))

    await run.start()

    assert [e.payload["decision"] for e in run.events("gate_decided")] == ["changes"]
    [_, second] = (r for r in run.runtime.requests if r.node_id == "writer")
    assert "AC-001: every test of it also passes on the base" in second.input
    assert "(tests.test_sum::test_ac_001_adds)" in second.input


async def test_a_failing_test_of_a_criterion_is_sent_back() -> None:
    failing = report(
        module(case("tests.test_sum::test_ac_001_adds", "failed", "AC-001"),
               case("tests.test_sum::test_ac_002_zero", "passed", "AC-002"),
               coverage=covering(4, 4))
    )  # fmt: skip
    run = run_of(spec(max_rounds=1), Judged([failing]))

    await run.start()

    [_, second] = (r for r in run.runtime.requests if r.node_id == "writer")
    assert "AC-001: a test of it fails on the change" in second.input


async def test_the_base_run_names_the_linked_criteria_only_and_never_repeats_in_a_pass() -> None:
    tools = Judged([ONE_LINKED], [NOT_ON_BASE])
    run = run_of(spec(max_rounds=1), tools)

    await run.start()

    change = [a for n, a, _ in tools.jobs if n == "build.test" and "on" not in a]
    base = [a for n, a, _ in tools.jobs if n == "build.test" and a.get("on") == "base"]
    assert change[0] == {
        "path": ".", "node": "writer", "coverage": True, "select": ["AC-001", "AC-002"],
    }  # fmt: skip
    assert base == [{"path": ".", "node": "writer", "on": "base", "select": ["AC-001"]}] * len(base)
    assert len(base) == len(change)  # one base run per pass, none cached


async def test_no_base_run_when_no_test_names_a_criterion() -> None:
    none_linked = report(module(coverage=covering(2, 2)))
    tools = Judged([none_linked])
    run = run_of(spec(max_rounds=1), tools)

    await run.start()

    assert not [a for _, a, _ in tools.jobs if a.get("on") == "base"]
    assert {c["state"] for c in criteria_of(run).values()} == {"untested"}


async def test_coverage_below_the_minimum_sends_back_the_uncovered_lines() -> None:
    thin = report(module(case("t::test_ac_001", "passed", "AC-001"),
                         case("t::test_ac_002", "passed", "AC-002"),
                         coverage=covering(10, 5, (7, 9), (12, 12))))  # fmt: skip
    run = run_of(spec(checks={"criteria": "off"}), Judged([thin, BOTH_LINKED]))

    await run.start()

    [_, second] = (r for r in run.runtime.requests if r.node_id == "writer")
    assert second.input.startswith(
        "## Coverage\n\n- 50% of changed lines covered (5 of 10, needs 80%)"
    )
    assert "- src/sum.py: no test runs lines 7-9, 12" in second.input
    cov = by_kind(pack_of(run))["coverage"]
    assert (cov["status"], cov["detail"]["percent"], cov["detail"]["threshold"]) == (
        "passed",
        100.0,
        80,
    )


async def test_coverage_at_the_threshold_passes_and_the_threshold_is_the_policys() -> None:
    at = report(module(coverage=covering(10, 9, (3, 3))))
    run = run_of(spec(checks={"criteria": "off"}, coverage_min=90), Judged([at]))

    await run.start()

    assert run.events("gate_decided") == []
    assert by_kind(pack_of(run))["coverage"]["status"] == "passed"


async def test_a_change_with_no_executable_lines_passes_coverage() -> None:
    run = run_of(
        spec(checks={"criteria": "off"}), Judged([report(module(coverage=covering(0, 0)))])
    )

    await run.start()

    cov = by_kind(pack_of(run))["coverage"]
    assert (cov["status"], cov["summary"]) == ("passed", "no changed lines to cover")


async def test_a_module_that_cannot_report_reaches_a_person_not_the_writer() -> None:
    node = report(
        module(coverage=None, cases_reason="per-test results are not read for node yet",
               coverage_reason="coverage is not measured for node yet",
               ecosystem="node", runner="jest")
    )  # fmt: skip
    run = run_of(spec(), Judged([node]))

    result = await run.start()

    assert result.status == "waiting"
    assert run.events("gate_decided") == []  # not the writer's failure
    checks = by_kind(pack_of(run))
    assert checks["coverage"]["status"] == "error"
    assert checks["coverage"]["summary"] == "coverage is not measured for node yet"
    assert checks["criteria"]["status"] == "error"
    assert {c["state"] for c in criteria_of(run).values()} == {"unchecked"}


async def test_a_base_run_that_errored_leaves_the_criteria_unchecked() -> None:
    timed_out = report(module(status="error", reason="test run timed out"))
    run = run_of(spec(), Judged([BOTH_LINKED], [timed_out]))

    await run.start()

    assert run.events("gate_decided") == []
    assert {c["state"] for c in criteria_of(run).values()} == {"unchecked"}


async def test_a_base_that_does_not_build_counts_as_failing_before() -> None:
    cannot_build = report(
        module(status="failed", reason="the base run did not build", build="failed")
    )
    run = run_of(spec(max_rounds=1), Judged([ONE_LINKED, ONE_LINKED], [cannot_build]))

    await run.start()

    assert criteria_of(run)["AC-001"]["state"] == "proven"


async def test_one_rounds_counter_covers_every_check_and_the_last_round_is_not_used() -> None:
    thin = report(module(case("t::test_ac_001", "passed", "AC-001"),
                         case("t::test_ac_002", "passed", "AC-002"),
                         coverage=covering(10, 1, (1, 9))))  # fmt: skip
    run = run_of(spec(max_rounds=1), Judged([thin, ONE_LINKED], [NOT_ON_BASE]))

    result = await run.start()

    # Pass 1 failed coverage (the one round); pass 2 also fails (criteria) but no round is left.
    assert result.status == "waiting"
    assert [e.payload["source"] for e in run.events("gate_decided")] == ["checks"]
    pack = pack_of(run)
    assert pack["rounds_left"] == 0
    assert by_kind(pack)["criteria"]["status"] == "failed"  # shown to the person who decides
    assert (await run.resume(APPROVE)).status == "completed"


async def test_a_restart_between_the_checks_and_the_gate_runs_no_job_twice() -> None:
    tools = Judged([BOTH_LINKED], [NOT_ON_BASE])
    run = run_of(spec(), tools)
    await run.start()
    before = len(tools.jobs)

    await run.resume(APPROVE)

    assert len(tools.jobs) == before


async def test_with_the_new_checks_off_no_new_argument_goes_to_build_test() -> None:
    tools = Judged([report(module())])
    run = run_of(
        spec(
            checks={"coverage": "off", "criteria": "off", "build": "required", "tests": "required"}
        ),
        tools,
    )

    await run.start()

    assert [a for n, a, _ in tools.jobs if n == "build.test"] == [{"path": ".", "node": "writer"}]
    assert set(by_kind(pack_of(run))) == {"build", "tests"}


# Validation.


def raw(**evidence: object) -> dict[str, Any]:
    out = spec().model_dump(mode="json", by_alias=True, exclude_none=True)
    gate = out["root"]["steps"][1]["body"]["steps"][1]
    gate["evidence"].update(evidence)
    return out


def found(document: dict[str, Any]) -> list[tuple[str, str]]:
    issues = validate_workflow(
        document, policy=PLATFORM_POLICY, priced=frozenset({"default"}).__contains__,
        default_model="default",
    )  # fmt: skip
    return [(i.code, i.message) for i in issues]


def test_the_defaults_are_off_and_80_and_spec_md() -> None:
    evidence = GateEvidence(node="writer")

    assert (evidence.checks.coverage, evidence.checks.criteria) == ("off", "off")
    assert (evidence.coverage_min, evidence.criteria_from) == (80, "spec.md")


def test_a_valid_policy_has_no_issue() -> None:
    assert found(raw()) == []


def test_criteria_from_must_be_written_before_the_gate() -> None:
    [(code, message)] = found(raw(criteria_from="requirements.md"))

    assert code == "artifact_unknown"
    assert "'requirements.md'" in message
    assert "write it in an earlier step" in message


def test_criteria_from_must_be_markdown() -> None:
    issues = found(raw(criteria_from="criteria.json"))

    assert [c for c, _ in issues] == ["invalid_evidence"]
    assert "must be a Markdown (.md) artifact" in issues[0][1]


def test_coverage_min_must_be_a_percentage() -> None:
    issues = found(raw(coverage_min=140))

    assert [c for c, _ in issues] == ["invalid_evidence"]
    assert "use a percentage from 0 to 100" in issues[0][1]


def test_a_gate_with_only_the_new_checks_is_not_all_off() -> None:
    off = {"build": "off", "tests": "off", "analyzers": "off", "coverage": "off", "criteria": "off"}

    assert [c for c, _ in found(raw(checks=off))] == ["invalid_evidence"]
    assert found(raw(checks={**off, "coverage": "shown"})) == []


async def test_a_build_that_fails_sends_the_writer_the_error_codes_and_places() -> None:
    broken = report(
        module(
            status="failed",
            reason="does not build",
            build="failed",
            ecosystem="dotnet",
            build_errors=["S4144 tests/Core.Tests/ItemKindTests.cs:35", "CS1002 src/Core/A.cs:3"],
        )
    )
    run = run_of(
        spec(checks={"build": "required", "coverage": "off", "criteria": "off"}, max_rounds=1),
        Judged([broken, report(module())]),
    )

    await run.start()

    [_, second] = (r for r in run.runtime.requests if r.node_id == "writer")
    assert second.input.startswith("## Build\n\n- does not build")
    assert "- . does not build" in second.input
    assert "- error S4144 tests/Core.Tests/ItemKindTests.cs:35" in second.input
    assert "- error CS1002 src/Core/A.cs:3" in second.input
