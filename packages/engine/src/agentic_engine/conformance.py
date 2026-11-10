"""Does a run match the graph that was drawn? (6.8, AC-2.)

`trace_mismatches` reads a run's events against the expanded tree of the workflow version it ran
(subflows resolved, as the engine runs them) and lists every way they disagree. A test and eval
helper: the monitor already draws a run on its version's spec, and this proves it can.

The rules, each a `Mismatch.rule`:

- `workflow`: the run names another workflow than the spec (`run_started.workflow_id`).
- `unknown_node`: an event names a node the tree does not have. An orchestrator's workers run as
  its body's node, tagged with the task's `item`, so they are known.
- `no_outcome`: the run completed, the slot a node sits in was entered, and the node has no event.
  A slot is entered when its container did what reaches it: a sequence's previous step completed
  (a gate rejected with `on_reject: end` does not go on), a parallel started its branches, a loop
  an iteration, a map an item, an orchestrator a task, a router chose that route, a subflow
  started. A node in a slot not entered was not on the path taken; one in an entered slot of a run
  that did not complete (failed, cancelled, waiting, still running) was not reached. Neither is a
  mismatch: `outcomes` names them.
- `outside_container`: a node's event falls outside every run of a container above it (its
  `node_started` to its end), e.g. a branch that ends after its parallel ended.
- `order`: a sequence's step started before the step before it ended, compared run by run within
  the same map item, task or branch.
- `loop_iterations`: a loop's iterations are not numbered 1, 2, … in order, or its end names
  another count.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import JsonValue

from agentic_engine.events import (
    GATE_DECIDED,
    LOOP_CONDITION_EVALUATED,
    LOOP_ITERATION_STARTED,
    MAP_ITEM_STARTED,
    NODE_CANCELLED,
    NODE_COMPLETED,
    NODE_FAILED,
    NODE_STARTED,
    PARALLEL_BRANCH_STARTED,
    ROUTE_CHOSEN,
    RUN_COMPLETED,
    RUN_STARTED,
    TASK_STARTED,
    RunEvent,
)
from agentic_engine.spec import (
    GateNode,
    LoopNode,
    MapNode,
    Node,
    OrchestratorNode,
    ParallelNode,
    RouterNode,
    SequenceNode,
    SubflowNode,
    iter_nodes,
)
from agentic_engine.spec.models import router_routes

type Rule = Literal[
    "workflow", "unknown_node", "no_outcome", "outside_container", "order", "loop_iterations"
]
type Outcome = Literal["ran", "not_taken", "not_reached"]
type _Slot = Literal["entered", "skipped", "pending"]
"""Whether a run entered a node's slot, decided against it, or has not decided yet."""

_ENDS = (NODE_COMPLETED, NODE_FAILED, NODE_CANCELLED)
_TAGS = ("item", "branch")


@dataclass(frozen=True)
class Mismatch:
    """One way the run disagrees with the drawn graph: the node (`None` for the run), its path in
    the tree, the rule and a sentence."""

    node_id: str | None
    path: str | None
    rule: Rule
    message: str


@dataclass(frozen=True)
class _Run:
    """One run of a node: from its `node_started` (or first event) to its end, if it ended, in
    the scope of its map item, task or branch (`tags`)."""

    tags: tuple[JsonValue, ...]
    start: int
    end: int | None
    status: str | None


class _Trace:
    """A run's events indexed by node."""

    def __init__(self, events: Iterable[RunEvent]) -> None:
        self.events = sorted(events, key=lambda e: e.seq)
        self.by_node: dict[str, list[RunEvent]] = defaultdict(list)
        for event in self.events:
            if event.node_id is not None:
                self.by_node[event.node_id].append(event)
        self.completed = any(e.type == RUN_COMPLETED for e in self.events)

    def of(self, node_id: str, *types: str) -> list[RunEvent]:
        return [e for e in self.by_node.get(node_id, []) if not types or e.type in types]

    def runs(self, node_id: str) -> list[_Run]:
        """Each run of `node_id`, in order: a `node_started` opens one in its tags' scope, the
        next end in the same scope closes it."""
        runs: list[_Run] = []
        open_: dict[tuple[JsonValue, ...], int] = {}
        for event in self.of(node_id, NODE_STARTED, *_ENDS):
            tags = _tags(event)
            if event.type == NODE_STARTED:
                open_[tags] = event.seq
            else:
                start = open_.pop(tags, event.seq)
                runs.append(_Run(tags, start, event.seq, event.type))
        runs += [_Run(tags, start, None, None) for tags, start in open_.items()]
        return sorted(runs, key=lambda r: r.start)


def _tags(event: RunEvent) -> tuple[JsonValue, ...]:
    """The scope `event` ran in: its map item or task (`item`) and parallel branch (`branch`)
    indexes. Only integers are tags: an orchestrator's end names its git `branch` by name."""
    return tuple(v if isinstance(v := event.payload.get(t), int) else None for t in _TAGS)


def trace_mismatches(
    root: Node, events: Iterable[RunEvent], workflow_id: str | None = None
) -> list[Mismatch]:
    """Every way `events` disagree with the expanded tree under `root` (and, if given, with the
    workflow `workflow_id`), in tree order; empty when the run matches the graph."""
    trace = _Trace(events)
    nodes = list(iter_nodes(root))
    paths = {node.id: path for path, node in nodes}
    mismatches: list[Mismatch] = []

    if workflow_id is not None:
        started = next((e for e in trace.events if e.type == RUN_STARTED), None)
        ran = started.payload.get("workflow_id") if started is not None else None
        if ran != workflow_id:
            message = f"the run is of workflow {ran!r}, not {workflow_id!r}"
            mismatches.append(Mismatch(None, None, "workflow", message))

    for node_id in trace.by_node:
        if node_id not in paths:
            message = f"the run has events for {node_id!r}, which the graph does not have"
            mismatches.append(Mismatch(node_id, None, "unknown_node", message))

    found = _visit(root, trace)
    for path, node in nodes:
        if trace.completed and found[node.id] == ("not_reached", "entered"):
            message = f"{node.id!r} was reached but has no event, and the run completed"
            mismatches.append(Mismatch(node.id, path, "no_outcome", message))

    for path, node in nodes:
        mismatches += _containment(node, path, trace)
        if isinstance(node, SequenceNode):
            mismatches += _sequence_order(node, path, trace)
        if isinstance(node, LoopNode):
            mismatches += _loop_iterations(node, path, trace)
    return mismatches


def outcomes(root: Node, events: Iterable[RunEvent]) -> dict[str, Outcome]:
    """What happened to each node under `root`: it `ran` (it has events; a sequence, when one of
    its steps ran); the run decided against its slot, so it was `not_taken` (a route not chosen, a
    gate that ended the run, a container that ended without running it); or it was
    `not_reached`, its slot entered or not decided yet."""
    return {node_id: outcome for node_id, (outcome, _) in _visit(root, _Trace(events)).items()}


def _visit(root: Node, trace: _Trace) -> dict[str, tuple[Outcome, _Slot]]:
    """Each node's outcome and the state of its slot."""
    found: dict[str, tuple[Outcome, _Slot]] = {}

    def visit(node: Node, slot: _Slot) -> None:
        for child, own in _slots(node, trace):
            visit(child, own if slot == "entered" else slot)
        if isinstance(node, SequenceNode):
            ran = any(found[s.id][0] == "ran" for s in node.steps)
        else:
            ran = bool(trace.by_node.get(node.id))
        outcome: Outcome = "ran" if ran else "not_taken" if slot == "skipped" else "not_reached"
        found[node.id] = (outcome, slot)

    visit(root, "entered" if any(e.type == RUN_STARTED for e in trace.events) else "pending")
    return found


def _slots(node: Node, trace: _Trace) -> list[tuple[Node, _Slot]]:
    """Each node directly under `node`, and the state `node` left its slot in."""
    started = bool(trace.of(node.id, NODE_STARTED))
    ended = bool(trace.of(node.id, *_ENDS))

    def by(entered: bool) -> _Slot:
        return "entered" if entered else "skipped" if ended else "pending"

    match node:
        case SequenceNode():
            # Once a step's slot is skipped, so are those of the steps after it.
            slots: list[tuple[Node, _Slot]] = []
            for i, step in enumerate(node.steps):
                previous = slots[-1][1] if slots else "entered"
                slot = previous if previous == "skipped" or i == 0 else None
                slots.append((step, slot or _after(node.steps[i - 1], trace)))
            return slots
        case ParallelNode():
            branched = by(bool(trace.of(node.id, PARALLEL_BRANCH_STARTED)))
            return [(b, branched) for b in node.branches]
        case LoopNode():
            return [(node.body, by(bool(trace.of(node.id, LOOP_ITERATION_STARTED))))]
        case MapNode():
            return [(node.body, by(bool(trace.of(node.id, MAP_ITEM_STARTED))))]
        case OrchestratorNode():
            return [(node.body, by(bool(trace.of(node.id, TASK_STARTED))))]
        case RouterNode():
            chosen = {str(e.payload.get("route")) for e in trace.of(node.id, ROUTE_CHOSEN)}
            undecided: _Slot = "skipped" if chosen or ended else "pending"
            return [
                (then, "entered" if route in chosen else undecided)
                for route, _, then in router_routes(node, "")
            ]
        case SubflowNode() if node.call is not None:
            return [(node.call, by(started))]
        case _:
            return []


def _after(step: Node, trace: _Trace) -> _Slot:
    """The state of the slot after `step` in its sequence: entered once the run went on past it
    (it completed; a sequence: its last step went on), skipped when it is a gate rejected with
    `on_reject: end`, else pending."""
    if isinstance(step, SequenceNode):
        return _after(step.steps[-1], trace) if step.steps else "entered"
    if not trace.of(step.id, NODE_COMPLETED):
        return "pending"
    if isinstance(step, GateNode) and step.on_reject == "end":
        decided = trace.of(step.id, GATE_DECIDED)
        if not any(e.payload.get("decision") == "approve" for e in decided):
            return "skipped"
    return "entered"


def _descendants(node: Node) -> list[str]:
    return [n.id for _, n in iter_nodes(node) if n is not node]


def _containment(node: Node, path: str, trace: _Trace) -> list[Mismatch]:
    """Events of nodes under `node` that fall outside every run of `node`. A sequence has no
    events of its own, so it holds nothing to check."""
    if isinstance(node, SequenceNode) or not trace.by_node.get(node.id):
        return []
    windows = [(r.start, r.end) for r in trace.runs(node.id)]
    mismatches: list[Mismatch] = []
    for inner in _descendants(node):
        outside = [
            e
            for e in trace.of(inner)
            if not any(start <= e.seq and (end is None or e.seq <= end) for start, end in windows)
        ]
        if outside:
            message = (
                f"{inner!r} has an event (seq {outside[0].seq}, {outside[0].type}) outside "
                f"every run of {node.id!r}, which holds it"
            )
            mismatches.append(Mismatch(inner, path, "outside_container", message))
    return mismatches


def _spans(node: Node, trace: _Trace) -> dict[tuple[JsonValue, ...], list[tuple[int, int | None]]]:
    """Each run of `node` as (first seq, last seq) by scope; a sequence's runs span its first
    step's starts to its last step's ends."""
    if isinstance(node, SequenceNode):
        if not node.steps:
            return {}
        firsts, lasts = _spans(node.steps[0], trace), _spans(node.steps[-1], trace)
        return {
            tags: [
                (start, lasts.get(tags, [])[k][1] if k < len(lasts.get(tags, [])) else None)
                for k, (start, _) in enumerate(runs)
            ]
            for tags, runs in firsts.items()
        }
    spans: dict[tuple[JsonValue, ...], list[tuple[int, int | None]]] = defaultdict(list)
    for run in trace.runs(node.id):
        spans[run.tags].append((run.start, run.end))
    return spans


def _sequence_order(node: SequenceNode, path: str, trace: _Trace) -> list[Mismatch]:
    """Steps of `node` that started before the step before them ended, run by run per scope."""
    mismatches: list[Mismatch] = []
    for before, after in zip(node.steps, node.steps[1:], strict=False):
        ended, started = _spans(before, trace), _spans(after, trace)
        for tags, runs in started.items():
            previous = ended.get(tags, [])
            for k, (start, _) in enumerate(runs):
                end = previous[k][1] if k < len(previous) else None
                if end is None or start < end:
                    message = (
                        f"{after.id!r} started (seq {start}) before {before.id!r} ended in "
                        f"{node.id!r}" + (f" ({_scope(tags)})" if tags != (None, None) else "")
                    )
                    mismatches.append(Mismatch(after.id, path, "order", message))
                    break
    return mismatches


def _scope(tags: Sequence[JsonValue]) -> str:
    return ", ".join(
        f"{name} {value}" for name, value in zip(_TAGS, tags, strict=True) if value is not None
    )


def _loop_iterations(node: LoopNode, path: str, trace: _Trace) -> list[Mismatch]:
    """Whether `node`'s iterations are 1, 2, … in order, each evaluated before the next, and its
    end names their count."""
    mismatches: list[Mismatch] = []
    expected = 1
    pending: int | None = None
    kinds = (LOOP_ITERATION_STARTED, LOOP_CONDITION_EVALUATED, NODE_COMPLETED)
    for event in trace.of(node.id, *kinds):
        number = event.payload.get("iteration")
        if event.type == LOOP_ITERATION_STARTED:
            if number != expected or pending is not None:
                message = f"loop {node.id!r} started iteration {number!r} where {expected} was due"
                mismatches.append(Mismatch(node.id, path, "loop_iterations", message))
                return mismatches
            pending = expected
        elif event.type == LOOP_CONDITION_EVALUATED:
            if number != pending:
                message = f"loop {node.id!r} evaluated iteration {number!r} while {pending!r} ran"
                mismatches.append(Mismatch(node.id, path, "loop_iterations", message))
                return mismatches
            pending, expected = None, expected + 1
        elif (count := event.payload.get("iterations")) != expected - 1:
            message = f"loop {node.id!r} ended after {count!r} iterations but ran {expected - 1}"
            mismatches.append(Mismatch(node.id, path, "loop_iterations", message))
    return mismatches


def events_from_json(rows: Sequence[Mapping[str, JsonValue]]) -> list[RunEvent]:
    """`RunEvent`s from rows as the API and the fixtures hold them."""
    return [RunEvent.model_validate(dict(row)) for row in rows]
