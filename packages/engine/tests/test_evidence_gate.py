"""A gate that checks a writer's work before a person sees it (13.3): the engine runs
`build.test` and `scan.lint` on the writer's branch, sends failing work back to the writer through
the request-changes path (7.8) with no one involved, and shows the pack once the checks pass or the
rounds run out. The tests assert what the writer is handed and what the gate shows (lessons, rule
1), not only the outcome."""

import json
from collections.abc import Mapping
from typing import Any, cast
from uuid import UUID, uuid4

from langgraph.checkpoint.memory import InMemorySaver
from pydantic import JsonValue

from agentic_engine.events import InMemoryEventSink, RunEvent
from agentic_engine.gate import GateDecision
from agentic_engine.graph import (
    WorkflowRunResult,
    checkpoint_serde,
    resume_workflow,
    run_workflow,
)
from agentic_engine.policy import PLATFORM_POLICY
from agentic_engine.spec import WorkflowSpec, parse_spec, validate_workflow
from agentic_runtime import Message, ReadableWriters, ToolOutput
from agentic_runtime.fake import ECHO_USAGE, CallTool, FakeRuntime
from agentic_runtime.testing import ScriptedToolExecutor

APPROVE = GateDecision(decision="approve", decided_by="ada")


def spec(
    *,
    max_rounds: int = 2,
    checks: Mapping[str, str] | None = None,
    max_iterations: int = 5,
    until: str = 'results.check.data.decision != "changes"',
) -> WorkflowSpec:
    """A writer and a gate with evidence in a loop that goes round while the gate sends it back."""
    evidence: dict[str, object] = {"node": "writer", "max_rounds": max_rounds}
    if checks is not None:
        evidence["checks"] = dict(checks)
    return parse_spec(
        {
            "spec_version": "0",
            "id": "evidence",
            "name": "Evidence",
            "root": {
                "type": "loop",
                "id": "build",
                "until": until,
                "max_iterations": max_iterations,
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
        }
    )


def report_of(*modules: dict[str, JsonValue]) -> ToolOutput:
    return ToolOutput(
        text="tests", data={"tool": "build.test", "checks": list(modules), "truncated": False}
    )


PASSING = report_of(
    {"path": ".", "ecosystem": "node", "runner": "jest", "status": "passed", "build": "ran",
     "passed": 3, "failed": 0, "skipped": 0, "failures": [], "test_ms": 900}
)  # fmt: skip
FAILING = report_of(
    {"path": ".", "ecosystem": "node", "runner": "jest", "status": "failed", "build": "ran",
     "reason": "tests failed (1 of 3)", "passed": 2, "failed": 1, "skipped": 0, "test_ms": 800,
     "failures": [{"name": "sum > adds", "file": "src/sum.test.js", "message": "expected 3"}]}
)  # fmt: skip


def lint(*fingerprints: str) -> ToolOutput:
    findings: list[JsonValue] = [
        {"fingerprint": f, "tool": "ruff", "rule": "F401", "path": f"{f}.py", "line": 1,
         "severity": "low", "message": "unused import"}
        for f in fingerprints
    ]  # fmt: skip
    return ToolOutput(text="lint", data={"tool": "lint", "findings": findings, "checks": []})


class Checks(ScriptedToolExecutor):
    """`build.test` and `scan.lint` answer from queues (the last answer repeats), and every call
    is recorded with the arguments and the node id it went out as."""

    def __init__(
        self,
        tests: list[ToolOutput],
        branch_lint: list[ToolOutput] | None = None,
        base_lint: ToolOutput | None = None,
    ) -> None:
        super().__init__({"repo.write_file": "wrote", "repo.commit": "abc on agent/x: done"})
        self.tests = tests
        self.branch_lint = branch_lint or [lint()]
        self.base_lint = base_lint or lint()
        self.jobs: list[tuple[str, dict[str, JsonValue], str | None]] = []

    async def call(
        self, name: str, arguments: dict[str, JsonValue], *, node_id: str | None = None
    ) -> ToolOutput:
        if name not in ("build.test", "scan.lint"):
            return await super().call(name, arguments, node_id=node_id)
        self.jobs.append((name, arguments, node_id))
        if name == "build.test":
            queue = self.tests
        elif "node" in arguments:
            queue = self.branch_lint
        else:
            return self.base_lint
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def count(self, name: str) -> int:
        return sum(1 for job in self.jobs if job[0] == name)


class Run:
    """One run across its pauses, as `test_gate.Run` does."""

    def __init__(self, workflow: WorkflowSpec, tools: Checks, writes: int = 6) -> None:
        self.spec = workflow
        self.tools = tools
        self.readable = ReadableWriters(lambda node: f"agent/run/{node}")
        # Each repetition differs, as a writer's work does: the same call five times in one step
        # is what the repeat breaker (13.7) pauses.
        script = [
            step
            for i in range(writes)
            for step in (
                CallTool("repo.write_file", {"path": "a.js", "content": f"x{i}"}),
                CallTool("repo.commit", {"message": f"work {i}"}),
                Message(text="Done."),
                ECHO_USAGE,
            )
        ]
        self.runtime = FakeRuntime({"writer": script}, tools=tools)
        self.run_id: UUID = uuid4()
        self.sink = InMemoryEventSink()
        self.checkpointer = InMemorySaver(serde=checkpoint_serde())
        self.attempt = 1

    async def start(self) -> WorkflowRunResult:
        return await run_workflow(
            self.spec, self.runtime, "Add sum().", run_id=self.run_id, sink=self.sink,
            checkpointer=self.checkpointer, tools=self.tools, readable=self.readable,
        )  # fmt: skip

    async def resume(self, decision: GateDecision) -> WorkflowRunResult:
        self.attempt += 1
        return await resume_workflow(
            self.spec, self.runtime, "Add sum().", run_id=self.run_id, sink=self.sink,
            checkpointer=self.checkpointer, next_seq=self.sink.events[-1].seq + 1,
            attempt=self.attempt, decision=decision, tools=self.tools, readable=self.readable,
        )  # fmt: skip

    def events(self, kind: str) -> list[RunEvent]:
        return [e for e in self.sink.events if e.type == kind]


async def test_failing_tests_send_the_writer_back_with_no_gate_and_no_person() -> None:
    run = Run(spec(), Checks([FAILING, PASSING]))

    first = await run.start()

    # The run paused only once: at the second pass, after the writer fixed it.
    assert first.status == "waiting"
    assert [e.payload["decision"] for e in run.events("gate_decided")] == ["changes"]
    sent = run.events("gate_decided")[0].payload
    assert sent["source"] == "checks"
    assert "decided_by" not in sent  # no person is named
    assert len(run.events("gate_waiting")) == 1
    assert run.events("gate_waiting")[0].seq > run.events("gate_decided")[0].seq


async def test_the_writer_is_handed_the_failures_under_fixed_headings() -> None:
    run = Run(spec(), Checks([FAILING, PASSING]))

    await run.start()

    first, second = (r for r in run.runtime.requests if r.node_id == "writer")
    assert first.input == "Add sum()."
    assert second.input.startswith(
        "## Tests\n\n- tests failed (1 of 3)\n- sum > adds (src/sum.test.js)"
    )
    assert ": expected 3" in second.input


def pack_of(run: Run, index: int = 0) -> dict[str, Any]:
    """The evidence a gate showed when it paused (`gate_waiting`'s `evidence`)."""
    return cast("dict[str, Any]", run.events("gate_waiting")[index].payload["evidence"])


def by_kind(pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["kind"]: c for c in pack["checks"]}


async def test_a_passing_change_reaches_the_gate_with_the_pack() -> None:
    run = Run(spec(), Checks([PASSING]))

    result = await run.start()

    assert result.status == "waiting"
    assert run.events("gate_decided") == []
    pack = pack_of(run)
    assert {k: c["status"] for k, c in by_kind(pack).items()} == {
        "build": "passed",
        "tests": "passed",
        "analyzers": "passed",
    }
    assert pack["rounds_left"] == 2
    [collected] = run.events("evidence_collected")
    assert collected.payload["sent_back"] is False
    assert (await run.resume(APPROVE)).status == "completed"


async def test_the_checks_run_on_the_writers_branch_and_the_base_once() -> None:
    tools = Checks([PASSING])
    run = Run(spec(), tools)

    await run.start()

    assert [(n, a.get("node")) for n, a, _ in tools.jobs if n == "build.test"] == [
        ("build.test", "writer")
    ]
    lints = [a for n, a, _ in tools.jobs if n == "scan.lint"]
    assert {"node": "writer", "path": ".", "config": "base"} in lints
    assert {"path": "."} in lints  # the base, no node
    assert {node for _, _, node in tools.jobs} == {"check.evidence"}


async def test_when_the_rounds_run_out_the_gate_pauses_with_the_failing_pack() -> None:
    run = Run(spec(max_rounds=1), Checks([FAILING]))

    result = await run.start()

    assert result.status == "waiting"
    assert [e.payload["decision"] for e in run.events("gate_decided")] == ["changes"]
    pack = pack_of(run)
    assert pack["rounds_left"] == 0
    assert by_kind(pack)["tests"]["status"] == "failed"
    # A person can now decide, and the failing pack stayed visible to them.
    assert (await run.resume(APPROVE)).status == "completed"


async def test_a_restart_between_the_checks_and_the_gate_runs_no_job_twice() -> None:
    tools = Checks([PASSING])
    run = Run(spec(), tools)
    await run.start()
    before = (tools.count("build.test"), tools.count("scan.lint"))

    # The gate runs again from its start when it continues; the checks do not.
    await run.resume(APPROVE)

    assert (tools.count("build.test"), tools.count("scan.lint")) == before


async def test_no_new_analyzers_pass_on_old_findings_and_fail_on_a_new_one() -> None:
    old = Run(spec(), Checks([PASSING], [lint("old")], lint("old")))
    new = Run(spec(max_rounds=1), Checks([PASSING], [lint("old", "fresh")], lint("old")))

    await old.start()
    await new.start()

    analyzers = by_kind(pack_of(old))["analyzers"]
    assert (analyzers["status"], analyzers["detail"]["new"]) == ("passed", 0)
    fresh = by_kind(pack_of(new))["analyzers"]
    assert (fresh["status"], fresh["detail"]["new"]) == ("failed", 1)
    assert fresh["detail"]["findings"][0]["path"] == "fresh.py"


async def test_a_check_that_could_not_run_reaches_a_person_instead_of_the_writer() -> None:
    broken = ToolOutput(text="could not read the writer's work", is_error=True)
    run = Run(spec(), Checks([broken]))

    result = await run.start()

    assert result.status == "waiting"
    assert run.events("gate_decided") == []  # an error is not the writer's failure
    statuses = {k: c["status"] for k, c in by_kind(pack_of(run)).items()}
    assert (statuses["build"], statuses["tests"]) == ("error", "error")


async def test_a_writer_with_no_work_has_nothing_to_check_and_is_not_an_error() -> None:
    refusal = ToolOutput(
        text="Error executing tool test: writer 'writer' has not run before this step",
        is_error=True,
    )
    run = Run(spec(), Checks([refusal]))

    result = await run.start()

    assert result.status == "waiting"
    assert run.events("gate_decided") == []
    checks = by_kind(pack_of(run))
    assert {k: c["status"] for k, c in checks.items()} == {
        "build": "skipped",
        "tests": "skipped",
        "analyzers": "passed",  # the lint tool answered; only build and tests refused
    }
    assert checks["tests"]["summary"] == "no changes to check"


async def test_checks_set_to_shown_never_send_the_work_back() -> None:
    run = Run(
        spec(checks={"build": "shown", "tests": "shown", "analyzers": "shown"}),
        Checks([FAILING]),
    )

    result = await run.start()

    assert result.status == "waiting"
    assert run.events("gate_decided") == []
    assert all(c["required"] is False for c in pack_of(run)["checks"])


async def test_the_pack_is_written_as_a_run_artifact() -> None:
    run = Run(spec(), Checks([PASSING]))

    await run.start()

    written = [e.payload["name"] for e in run.events("artifact_written")]
    assert written == ["check.evidence.json"]
    assert json.dumps(run.events("evidence_collected")[0].payload)  # JSON all the way down


# Validation (the three issue codes, each with a message that says what to change).


def raw_spec(**evidence: object) -> dict[str, Any]:
    gate_evidence: dict[str, object] = {"node": "writer", "max_rounds": 2, **evidence}
    writer: dict[str, object] = {
        "type": "agent", "id": "writer", "role": "W", "instructions": "Go.",
        "tools": ["repo.write_file", "repo.commit"],
    }  # fmt: skip
    gate = {"type": "gate", "id": "check", "title": "Right?",
            "evidence": gate_evidence}  # fmt: skip
    return {
        "spec_version": "0",
        "id": "evidence",
        "name": "Evidence",
        "root": {
            "type": "loop", "id": "build", "until": 'results.check.data.decision != "changes"',
            "max_iterations": 3,
            "body": {"type": "sequence", "id": "round", "steps": [writer, gate]},
        },
    }  # fmt: skip


def found(raw: dict[str, Any]) -> list[tuple[str, str]]:
    issues = validate_workflow(
        raw, policy=PLATFORM_POLICY, priced=frozenset({"default"}).__contains__,
        default_model="default",
    )  # fmt: skip
    return [(i.code, i.message) for i in issues]


def test_evidence_in_a_valid_loop_has_no_issue() -> None:
    assert found(raw_spec(max_rounds=2)) == []


def test_evidence_outside_a_loop_is_refused() -> None:
    raw = raw_spec()
    steps: list[dict[str, Any]] = raw["root"]["body"]["steps"]
    raw["root"] = {"type": "sequence", "id": "main", "steps": steps}

    [(code, message)] = found(raw)

    assert code == "evidence_not_in_loop"
    assert "in a loop's body" in message


def test_evidence_must_name_a_writer_that_runs_before_the_gate() -> None:
    ghost = found(raw_spec(node="ghost"))
    late = raw_spec()
    steps = late["root"]["body"]["steps"]
    steps.reverse()  # the gate now runs before the writer

    assert [c for c, _ in ghost] == ["evidence_unknown_writer"]
    assert "'ghost' is not a writer" in ghost[0][1]
    assert [c for c, _ in found(late)] == ["evidence_unknown_writer"]
    assert "does not run before the gate" in found(late)[0][1]


def test_max_rounds_may_equal_the_loops_passes_as_the_engine_never_uses_the_last() -> None:
    assert found(raw_spec(max_rounds=3)) == []  # the loop has 3 passes: the default form value


def test_evidence_needs_a_check_on_and_a_path_inside_the_repo() -> None:
    nothing = found(raw_spec(checks={"build": "off", "tests": "off", "analyzers": "off"}))
    outside = found(raw_spec(path="../elsewhere"))

    assert [c for c, _ in nothing] == ["invalid_evidence"]
    assert "every check is off" in nothing[0][1]
    assert [c for c, _ in outside] == ["invalid_evidence"]
    assert "inside the repository" in outside[0][1]


def test_build_test_is_for_tool_nodes_only() -> None:
    raw = raw_spec()
    raw["root"]["body"]["steps"][0]["tools"] = ["repo.write_file", "repo.commit", "build.test"]

    assert [c for c, _ in found(raw)] == ["tool_node_only"]


async def test_the_checks_never_send_the_work_back_on_the_loops_last_pass() -> None:
    """A send-back on the last pass would end the loop unapproved, and whatever follows it (a
    publish) would run: the gate pauses with the failing pack instead, with no round left. The
    loop here goes on to pass 2 whatever a person decides in pass 1, so the checks reach the last
    pass with a round they could still have used."""
    run = Run(
        spec(
            max_rounds=2,
            max_iterations=3,
            until='results.check.data.decision != "changes" && iteration >= 2',
        ),
        Checks([PASSING, FAILING]),
    )

    await run.start()  # pass 1: the checks pass and a person approves
    second = await run.resume(APPROVE)  # pass 2 fails and is sent back; pass 3 is the last

    assert second.status == "waiting"
    sources = [e.payload.get("source") for e in run.events("gate_decided")]
    assert sources == [None, "checks"]  # the person's approval, then pass 2's send-back
    pack = pack_of(run, -1)
    assert pack["rounds_left"] == 0  # a round was unused, but no pass is left to act on it
    assert by_kind(pack)["tests"]["status"] == "failed"
    assert (await run.resume(APPROVE)).status == "completed"


def test_a_gate_with_evidence_takes_no_request_for_changes() -> None:
    raw = raw_spec()
    raw["root"]["body"]["steps"][1]["on_changes"] = 1

    [(code, message)] = found(raw)

    assert code == "schema"
    assert "cannot be used with `on_changes`" in message
