"""A run's top-level steps (12.4): the steps of its root sequence, nested sequences flattened,
or the root alone when it is not a sequence. A container (loop, map, parallel, orchestrator,
router, subflow) is one step. A rerun from a step starts at one of them."""

from collections.abc import Iterator

from agentic_engine.spec import Node, SequenceNode, WorkflowSpec, iter_nodes


class StepNotFoundError(ValueError):
    """The node is not one of the run's top-level steps."""


def top_level_steps(spec: WorkflowSpec) -> list[Node]:
    """The run's top-level steps in order: the root sequence's steps, nested sequences
    flattened, or the root alone when it is not a sequence."""

    def flatten(node: Node) -> Iterator[Node]:
        if isinstance(node, SequenceNode):
            for step in node.steps:
                yield from flatten(step)
        else:
            yield node

    return list(flatten(spec.root))


def top_step_of(spec: WorkflowSpec) -> dict[str, str]:
    """Every node id of the spec (its subflows' calls included), by the id of the top-level step
    it runs in."""
    owners: dict[str, str] = {}
    for step in top_level_steps(spec):
        for _, node in iter_nodes(step):
            owners.setdefault(node.id, step.id)
    return owners


def steps_before(spec: WorkflowSpec, node_id: str) -> list[str]:
    """The ids of the top-level steps before `node_id`, in order. Raises `StepNotFoundError` if
    `node_id` is not a top-level step."""
    ids = [step.id for step in top_level_steps(spec)]
    if node_id not in ids:
        raise StepNotFoundError(f"{node_id!r} is not a top-level step of the workflow")
    return ids[: ids.index(node_id)]
