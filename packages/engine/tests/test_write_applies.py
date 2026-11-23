"""The engine applies against the plan (13.8, group 3): nothing is written unless the plans a person
approved still hold, each write is called with its `expect`, and each result is compared with its
plan (`write_checked`). The tools are a fake world that plans and refuses stale plans as the real
ones do (`agentic_tools.jira`, `agentic_tools.github`: their own tests); the worker's tests run
the engine on the real tools."""

import json
from collections.abc import Sequence
from typing import Any
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from pydantic import JsonValue

from agentic_engine.agent import RunContext
from agentic_engine.artifacts import InMemoryArtifactStore
from agentic_engine.events import InMemoryEventSink
from agentic_engine.gate import FileChange, FileEdit, GateDecision
from agentic_engine.graph import checkpoint_serde, rerun_workflow, resume_workflow, run_workflow
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import Message, ToolDefinition, ToolOutput
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime
from agentic_runtime.plans import PlanAction, PlanError, PlanTarget, WritePlan
from agentic_runtime.testing import is_plan_call

from .test_sdd_template import SddRun

PR = "https://github.com/acme/shop/pull/9"
FOOTER = "_Posted by agentic-dev run [12345678](https://app.test/runs/x)_"


class World:
    """GitHub and Jira as a fake executor that keeps their state: an issue with a status, a
    branch with a tip, a repo name. It plans the way the real tools do (`expect` handed back is
    checked) and records what it is asked to write apart from what it is asked to plan."""

    def __init__(self) -> None:
        self.status = "To Do"
        self.tip = "a" * 40
        self.taken = False
        self.follow_up = False
        self.deviate: dict[str, JsonValue] = {}
        self.calls: list[tuple[str, dict[str, JsonValue], str | None]] = []
        self.plan_calls: list[tuple[str, dict[str, JsonValue]]] = []
        self.written: list[str] = []

    def definitions(self) -> Sequence[ToolDefinition]:
        names = ("github.openPR", "github.createRepo", "jira.comment", "jira.transition")
        return [ToolDefinition(name=name) for name in names]

    async def call(
        self, name: str, arguments: dict[str, JsonValue], *, node_id: str | None = None
    ) -> ToolOutput:
        args = {k: v for k, v in arguments.items() if k not in ("plan", "expect")}
        expect = arguments.get("expect")
        if is_plan_call(arguments):
            self.plan_calls.append((name, arguments))
            return self._plan(name, args)
        self.calls.append((name, arguments, node_id))
        if isinstance(expect, dict) and (why := self._stale(name, expect)):
            return ToolOutput(text=f"Error executing tool x: plan_stale: {why}", is_error=True)
        return self._write(name, args)

    # --- plan mode ---------------------------------------------------------------------------

    def _plan(self, name: str, args: dict[str, JsonValue]) -> ToolOutput:
        match name:
            case "jira.comment":
                body = str(args["body"])
                text = f"{body.rstrip()}\n\n{FOOTER}"
                plan = self._made(
                    name,
                    "comment",
                    f"Comment on {args['issue']}",
                    "issue",
                    str(args["issue"]),
                    {"key": args["issue"], "text": text, "footer": FOOTER},
                    body=text,
                    expect={"project": "API"},
                )
            case "jira.transition":
                moves = {"To Do": ("11", "In Progress"), "In Progress": ("31", "Done")}
                found = moves.get(self.status)
                if found is None or found[1] == self.status:
                    error = PlanError(code="transition_unavailable", message=f"{self.status}")
                    plan = self._made(
                        name, "transition", "Move", "issue", str(args["issue"]), {}, error=error
                    )
                else:
                    plan = self._made(
                        name,
                        "transition",
                        f"Move {args['issue']} from {self.status} to {found[1]}",
                        "issue",
                        str(args["issue"]),
                        {"key": args["issue"], "from_status": self.status, "to_status": found[1]},
                        expect={"status": self.status, "transition_id": found[0]},
                    )
            case "github.openPR":
                action: PlanAction = "push_to_pr" if self.follow_up else "open_pr"
                fields: dict[str, JsonValue] = {
                    "repo": "acme/shop",
                    "head": "agent/run/writer",
                    "base": "main",
                    "commit": self.tip,
                    "commits": 1,
                }
                if not self.follow_up:
                    fields |= {"title": args["title"], "body": args.get("body", "")}
                plan = self._made(
                    name, action, "Open", "repo", "acme/shop", fields, expect={"tip": self.tip}
                )
            case _:
                error = PlanError(code="repo_exists", message="taken") if self.taken else None
                plan = self._made(
                    name,
                    "create_repo",
                    "Create the private repo acme/docs-new",
                    "repo",
                    "acme/docs-new",
                    {"full_name": "acme/docs-new", "private": True},
                    expect={"name": "free"},
                    error=error,
                )
        return ToolOutput(text=plan.summary, data=plan.model_dump(mode="json"))

    @staticmethod
    def _made(
        tool: str,
        action: PlanAction,
        summary: str,
        kind: str,
        label: str,
        fields: dict[str, JsonValue],
        body: str | None = None,
        expect: dict[str, JsonValue] | None = None,
        error: PlanError | None = None,
    ) -> WritePlan:
        return WritePlan(
            tool=tool,
            action=action,
            summary=summary,
            target=PlanTarget(kind=kind, label=label),  # type: ignore[arg-type]
            fields=fields,
            body=body,
            expect=expect or {},
            error=error,
        )

    # --- the real call -----------------------------------------------------------------------

    def _stale(self, name: str, expect: dict[str, Any]) -> str | None:
        if name == "jira.transition" and expect.get("status") not in (None, self.status):
            return f"the issue is now {self.status}"
        if name == "github.openPR" and expect.get("tip") not in (None, self.tip):
            return f"the branch is now at {self.tip[:7]}"
        if name == "github.createRepo" and self.taken:
            return "the name was taken"
        return None

    def _write(self, name: str, args: dict[str, JsonValue]) -> ToolOutput:
        self.written.append(name)
        match name:
            case "jira.comment":
                text = f"{str(args['body']).rstrip()}\n\n{FOOTER}"
                data: dict[str, JsonValue] = {
                    "key": args["issue"],
                    "comment_id": "9001",
                    "url": "https://acme.atlassian.net/browse/PROJ-12",
                    "created": True,
                    "text": text,
                }
            case "jira.transition":
                before = self.status
                self.status = "In Progress" if before == "To Do" else "Done"
                data = {
                    "key": args["issue"],
                    "from_status": before,
                    "to_status": self.status,
                    "changed": True,
                }
            case "github.openPR":
                data = {
                    "url": PR,
                    "number": 9,
                    "head": "agent/run/writer",
                    "base": "main",
                    "commit": self.tip,
                    "repo": "acme/shop",
                    "title": args.get("title", ""),
                    "body": args.get("body", ""),
                    "updated": self.follow_up,
                }
            case _:
                data = {
                    "full_name": "acme/docs-new",
                    "url": "https://github.com/acme/docs-new",
                    "default_branch": "main",
                    "private": True,
                    "created": True,
                }
        return ToolOutput(text=json.dumps(data), data=data | self.deviate)


# --- a run of the SDD template on that world ------------------------------------------------


class Edited:
    """The integration branch as a dict; applying an edit moves the world's branch tip, as the
    real commit does."""

    def __init__(self, world: World) -> None:
        self.world = world
        self.files: dict[str, str] = {}

    async def changes(self, ran: Sequence[str]) -> list[FileChange]:
        return [
            FileChange(node_id="implement", path=p, status="added", editable=True, after=t)
            for p, t in self.files.items()
        ]

    async def apply(self, gate_id: str, edits: Sequence[FileEdit]) -> dict[str, str]:
        return await self.commit(edits, gate_id)

    async def commit(self, edits: Sequence[FileEdit], message: str) -> dict[str, str]:
        self.files.update({e.path: e.content for e in edits})
        self.world.tip = "b" * 40
        return {"implement": self.world.tip}


async def at_the_pr_gate(world: World | None = None) -> tuple[SddRun, World]:
    """An SDD run paused at `approve_pr`, on `world`."""
    world = world or World()
    run = SddRun()
    run.common["tools"] = world
    run.common["review"] = Edited(world)
    await run.start()
    await run.decide()  # approve_spec
    await run.decide()  # post_questions
    await run.answer()  # wait_for_answers
    await run.decide()  # approve_spec again
    assert run.waiting_at() == "approve_pr"
    return run, world


def checked(run: SddRun) -> list[tuple[str | None, str, list[str]]]:
    """Each `write_checked`: the write, its outcome and the fields that differ."""
    found: list[tuple[str | None, str, list[str]]] = []
    for event in run.sink.events:
        if event.type == "write_checked" and event.payload is not None:
            diffs = [d["field"] for d in event.payload["differences"]]  # type: ignore[index, union-attr]
            found.append((event.node_id, str(event.payload["outcome"]), diffs))
    return found


async def test_approving_as_planned_checks_all_three_writes_and_fills_in_the_links() -> None:
    run, world = await at_the_pr_gate()

    done = await run.decide()

    assert done.status == "completed"
    assert world.written == ["jira.comment", "github.openPR", "jira.comment", "jira.transition"]
    assert checked(run)[1:] == [
        ("publish", "as_planned", []),
        ("jira_update", "as_planned", []),
        ("move", "as_planned", []),
    ]
    links = next(
        e for e in run.sink.events if e.type == "write_checked" and e.node_id == "jira_update"
    )
    assert links.payload is not None
    assert PR in str(links.payload["result"]["text"])  # type: ignore[index]
    assert PR not in str(links.payload["plan"]["fields"]["text"])  # type: ignore[index]
    batch = [c for c in world.plan_calls]
    # Planned once for the gate, and once again before the first write; never again.
    assert [name for name, _ in batch].count("github.openPR") == 2


async def test_a_plan_and_its_result_are_side_by_side_in_one_event() -> None:
    run, _ = await at_the_pr_gate()
    await run.decide()

    event = next(e for e in run.sink.events if e.type == "write_checked" and e.node_id == "move")

    assert event.payload is not None
    assert event.payload["gate"] == "approve_pr"
    assert event.payload["plan"]["fields"]["to_status"] == "In Progress"  # type: ignore[index]
    assert event.payload["result"]["to_status"] == "In Progress"  # type: ignore[index]


async def test_an_issue_moved_while_the_gate_waits_writes_nothing() -> None:
    run, world = await at_the_pr_gate()
    published = len(world.written)
    world.status = "In Progress"  # someone moved it by hand

    done = await run.decide()

    assert done.status == "failed"
    assert done.stopped_at == "publish"
    assert world.written[published:] == []  # no pull request, no comment, no move
    failed = next(e for e in run.sink.events if e.type == "node_failed" and e.node_id == "publish")
    assert failed.payload is not None
    assert str(failed.payload["error"]).startswith("plan_stale: move: ")
    assert "In Progress" in str(failed.payload["error"])
    assert [(n, o) for n, o, _ in checked(run)[1:]] == [("move", "stale")]


async def test_a_gate_edit_moves_the_tip_and_the_write_is_as_planned() -> None:
    run, world = await at_the_pr_gate()
    edit = FileEdit(node_id="implement", path="specs/x/spec.md", content="edited\n")

    run.attempt += 1
    done = await resume_workflow(
        run.spec,
        run.runtime,
        "PROJ-12",
        next_seq=run.sink.events[-1].seq + 1,
        attempt=run.attempt,
        decision=GateDecision(decision="approve", edits=[edit]),
        **run.common,
    )

    assert done.status == "completed"
    assert ("publish", "as_planned", []) in checked(run)
    opened = next(c for c in world.calls if c[0] == "github.openPR")
    assert opened[1]["expect"] == {"tip": "b" * 40}


async def test_a_branch_that_moves_after_the_batch_check_is_refused_by_the_tool() -> None:
    """The seconds between the batch check and the call: the tool checks `expect` itself."""
    run, world = await at_the_pr_gate()
    original = world.call

    async def moving(name: str, arguments: dict[str, JsonValue], **kw: Any) -> ToolOutput:
        if name == "github.openPR" and not is_plan_call(arguments):
            world.tip = "c" * 40  # pushed between the check and the call
        return await original(name, arguments, **kw)

    world.call = moving  # type: ignore[method-assign]

    done = await run.decide()

    assert done.status == "failed"
    assert "github.openPR" not in world.written
    stale = [c for c in checked(run) if c[1] == "stale"]
    assert [n for n, _, _ in stale] == ["publish"]
    assert stale[0][2] == ["commit", "expect.tip"]


async def test_a_result_that_differs_from_its_plan_is_flagged_and_the_run_goes_on() -> None:
    run, world = await at_the_pr_gate()
    world.deviate = {"base": "develop"}

    done = await run.decide()

    assert done.status == "completed"
    assert ("publish", "differs", ["base"]) in checked(run)
    assert world.written[-1] == "jira.transition"  # the writes after it still ran


async def test_a_write_with_no_plan_is_not_written() -> None:
    run, world = await at_the_pr_gate()
    run.common["tools"] = world
    # A checkpoint from before 13.8 has no plans.
    state = await _forget_plans(run)

    done = await run.decide()

    assert state
    assert done.status == "failed"
    failed = next(e for e in run.sink.events if e.type == "node_failed" and e.node_id == "publish")
    assert failed.payload is not None
    assert str(failed.payload["error"]).startswith("plan_missing: ")
    assert "github.openPR" not in world.written


async def _forget_plans(run: SddRun) -> bool:
    graph_config = {"configurable": {"thread_id": str(run.common["run_id"]), "checkpoint_ns": ""}}
    saver = run.common["checkpointer"]
    found = await saver.aget_tuple(graph_config)
    assert found is not None
    values = found.checkpoint["channel_values"]
    values["write_plans"] = {}
    await saver.aput(
        graph_config,
        found.checkpoint,
        found.metadata,
        dict(found.checkpoint["channel_versions"]),
    )
    return True


# --- a plan that would fail, a follow-up and a new repo -----------------------------------------

WRITER: dict[str, Any] = {
    "type": "agent",
    "id": "writer",
    "role": "W",
    "instructions": "Write.",
    "tools": ["repo.write_file", "repo.commit"],
}
GATE: dict[str, Any] = {"type": "gate", "id": "gate", "title": "Publish?"}
PUBLISH: dict[str, Any] = {
    "type": "tool",
    "id": "publish",
    "tool": "github.openPR",
    "args": {"from_node": "writer", "title": "Add notes"},
}


def plain(*steps: dict[str, Any]) -> WorkflowSpec:
    return parse_spec(
        {
            "spec_version": "0",
            "id": "publish",
            "name": "Publish",
            "root": {"type": "sequence", "id": "main", "steps": list(steps)},
        }
    )


class Simple:
    def __init__(self, spec: WorkflowSpec, world: World) -> None:
        self.spec, self.world = spec, world
        self.runtime = FakeRuntime({"writer": [Message(text="done"), ECHO_USAGE]})
        self.run_id = uuid4()
        self.sink = InMemoryEventSink()
        self.checkpointer = InMemorySaver(serde=checkpoint_serde())
        self.attempt = 1

    async def start(self) -> Any:
        return await run_workflow(
            self.spec,
            self.runtime,
            "go",
            run_id=self.run_id,
            sink=self.sink,
            checkpointer=self.checkpointer,
            tools=self.world,
            artifacts=InMemoryArtifactStore(),
            context=RunContext(request="go"),
        )

    async def resume(self) -> Any:
        self.attempt += 1
        return await resume_workflow(
            self.spec,
            self.runtime,
            "go",
            run_id=self.run_id,
            sink=self.sink,
            checkpointer=self.checkpointer,
            next_seq=self.sink.events[-1].seq + 1,
            attempt=self.attempt,
            tools=self.world,
            decision=GateDecision(decision="approve"),
            artifacts=InMemoryArtifactStore(),
            context=RunContext(request="go"),
        )

    def outcomes(self) -> list[tuple[str | None, str]]:
        return [
            (e.node_id, str(e.payload["outcome"]))
            for e in self.sink.events
            if e.type == "write_checked" and e.payload is not None
        ]


async def test_a_plan_that_would_fail_stops_the_batch_before_anything_is_written() -> None:
    world = World()
    world.status = "Done"  # no move is offered from there
    move = {
        "type": "tool",
        "id": "move",
        "tool": "jira.transition",
        "args": {"issue": "API-1", "to": "Reviewed"},
    }
    run = Simple(plain(WRITER, GATE, PUBLISH, move), world)

    await run.start()
    waiting = [e for e in run.sink.events if e.type == "gate_waiting"][-1]
    assert waiting.payload is not None
    would_fail = [p for p in waiting.payload["plans"] if p.get("error")]  # type: ignore[union-attr]
    assert [p["error"]["code"] for p in would_fail] == ["transition_unavailable"]

    done = await run.resume()

    assert done.status == "failed"
    assert world.written == []  # not even the pull request
    failed = next(e for e in run.sink.events if e.type == "node_failed" and e.node_id == "publish")
    assert failed.payload is not None
    assert str(failed.payload["error"]).startswith("plan_would_fail: move: transition_unavailable")


async def test_a_follow_up_push_is_planned_and_checked() -> None:
    world = World()
    world.follow_up = True
    run = Simple(plain(WRITER, GATE, PUBLISH), world)

    await run.start()
    waiting = [e for e in run.sink.events if e.type == "gate_waiting"][-1]
    assert waiting.payload is not None
    assert waiting.payload["plans"][0]["action"] == "push_to_pr"  # type: ignore[index]

    assert (await run.resume()).status == "completed"
    assert run.outcomes() == [("publish", "as_planned")]


async def test_a_new_repo_is_planned_and_checked() -> None:
    world = World()
    create = {
        "type": "tool",
        "id": "create_repo",
        "tool": "github.createRepo",
        "args": {"name": "docs-new", "private": True},
    }
    run = Simple(
        plain({"type": "gate", "id": "approve_repo", "title": "Create?"}, create, WRITER), world
    )

    paused = await run.start()
    assert paused.waiting_at == "approve_repo"
    waiting = [e for e in run.sink.events if e.type == "gate_waiting"][-1]
    assert waiting.payload is not None
    assert waiting.payload["plans"][0]["summary"] == "Create the private repo acme/docs-new"  # type: ignore[index]

    suspended = await run.resume()

    assert suspended.status == "suspended"
    assert run.outcomes() == [("create_repo", "as_planned")]


async def test_a_rerun_from_the_gate_plans_again_and_asks_again() -> None:
    world = World()
    run = Simple(plain(WRITER, GATE, PUBLISH), world)
    await run.start()
    assert (await run.resume()).status == "completed"
    planned = len(world.plan_calls)
    world.tip = "d" * 40  # the code the rerun starts from has moved on

    sink = InMemoryEventSink()
    waiting = await rerun_workflow(
        run.spec,
        run.runtime,
        "go",
        run_id=uuid4(),
        source_run=run.run_id,
        from_node="gate",
        sink=sink,
        checkpointer=run.checkpointer,
        tools=world,
        artifacts=InMemoryArtifactStore(),
        context=RunContext(request="go"),
    )

    assert waiting.status == "waiting"
    assert len(world.plan_calls) == planned + 1
    shown = [e for e in sink.events if e.type == "gate_waiting"][-1]
    assert shown.payload is not None
    assert shown.payload["plans"][0]["fields"]["commit"] == "d" * 40  # type: ignore[index]
