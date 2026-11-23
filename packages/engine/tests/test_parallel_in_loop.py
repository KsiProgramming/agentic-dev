"""A parallel in a loop's body (13.6): its branches run again on each pass, each pass joins only
its own branches' outcomes, and the join is decided afresh."""

from langgraph.checkpoint.memory import InMemorySaver

from agentic_engine.events import InMemoryEventSink
from agentic_engine.graph import checkpoint_serde, run_workflow
from agentic_engine.spec import WorkflowSpec, parse_spec
from agentic_runtime import AgentRequest, AgentRun, Failed, Message
from agentic_runtime.fake import ECHO_USAGE, FakeRuntime, Script


class Recording:
    """A fake runtime that answers `<node>(<pass>)` and records every request. A node in `fail`
    fails on the passes it names."""

    def __init__(self, fail: dict[str, set[int]] | None = None) -> None:
        self.requests: list[AgentRequest] = []
        self._fail = fail or {}

    def count(self, node_id: str) -> int:
        return [r.node_id for r in self.requests].count(node_id)

    def start(self, request: AgentRequest) -> AgentRun:
        self.requests.append(request)
        nth = self.count(request.node_id)
        script: Script = (
            [Failed(error="model refused")]
            if nth in self._fail.get(request.node_id, set())
            else [Message(text=f"{request.node_id}#{nth}"), ECHO_USAGE]
        )
        return FakeRuntime({request.node_id: script}).start(request)


def lens(lens_id: str) -> dict[str, object]:
    return {"type": "agent", "id": lens_id, "role": "R", "instructions": "Look."}


def spec(join: str = "all", passes: int = 2) -> WorkflowSpec:
    return parse_spec(
        {
            "spec_version": "0", "id": "p", "name": "P",
            "root": {
                "type": "loop", "id": "again", "until": f"iteration >= {passes}",
                "max_iterations": 3,
                "body": {
                    "type": "sequence", "id": "round",
                    "steps": [
                        {"type": "parallel", "id": "lenses", "join": join,
                         "branches": [lens("a"), lens("b")]},
                        {"type": "reduce", "id": "merge", "from": "lenses", "strategy": "concat"},
                    ],
                },
            },
        }
    )  # fmt: skip


async def go(workflow: WorkflowSpec, runtime: Recording) -> str:
    result = await run_workflow(
        workflow, runtime, "brief", sink=InMemoryEventSink(),
        checkpointer=InMemorySaver(serde=checkpoint_serde()),
    )  # fmt: skip
    assert result.status == "completed"
    return result.text


async def test_a_parallel_in_a_loop_runs_its_branches_on_every_pass() -> None:
    runtime = Recording()

    output = await go(spec(), runtime)

    assert (runtime.count("a"), runtime.count("b")) == (2, 2)
    assert output == "a#2\n\nb#2"  # the second pass's outputs, not the first's


async def test_a_pass_never_joins_the_branches_of_an_earlier_pass() -> None:
    """With `settled`, a lens that fails on pass 2 is missing from that pass's join even though it
    completed on pass 1."""
    runtime = Recording(fail={"b": {2}})

    output = await go(spec(join="settled"), runtime)

    assert output == "a#2"


async def test_a_decided_join_does_not_cancel_the_next_pass() -> None:
    runtime = Recording()

    await go(spec(join="any", passes=3), runtime)

    assert runtime.count("a") == 3  # a branch cancelled in one pass runs in the next
