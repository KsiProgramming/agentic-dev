"""A gate with `review` (13.6): the pending gate carries the review's comments, an approval may
dismiss some by fingerprint (stored on the approval and carried to the engine), and a dismissal
that does not fit what the gate showed is refused with a fixed code."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentic_engine.gate import GateDecision
from agentic_engine.graph import checkpoint_serde
from agentic_engine.review_gate import ReviewComment, ReviewShown
from agentic_store import (
    Approval,
    InvalidDismissalError,
    Run,
    RunEventRow,
    pending_decision,
    pending_gate,
    record_approval,
)

from .test_approvals import paused_run

pytestmark = pytest.mark.integration


def comment(fingerprint: str, path: str, line: int) -> ReviewComment:
    return ReviewComment(
        fingerprint=fingerprint, severity="medium", category="correctness", lenses=["correctness"],
        path=path, line=line, message="Look.", node_id="writer", in_diff=True,
    )  # fmt: skip


SHOWN = ReviewShown.model_validate(
    {
        "from": "review.json", "version": 1, "block_at": "high", "rounds_left": 1,
        "comments": [comment("a" * 8, "a.py", 3), comment("b" * 8, "b.py", 9)],
        "failed_lenses": ["performance"], "counts": {"medium": 2},
    }
)  # fmt: skip


async def reviewed_run(
    sessions: async_sessionmaker[AsyncSession], with_review: bool = True
) -> UUID:
    """A run paused at its gate, as a gate with `review` shows itself on its next pass."""
    run_id = await paused_run(sessions, InMemorySaver(serde=checkpoint_serde()))
    payload = {"title": "Merge?", "artifact": ""}
    if with_review:
        payload["review"] = SHOWN.model_dump(mode="json", by_alias=True)  # type: ignore[assignment]
    async with sessions.begin() as session:
        seq = await session.scalar(
            select(func.max(RunEventRow.seq)).where(RunEventRow.run_id == run_id)
        )
        session.add(
            RunEventRow(
                run_id=run_id, seq=(seq or 0) + 1, type="gate_waiting", node_id="gate",
                payload=payload, created_at=datetime.now(UTC),
            )
        )  # fmt: skip
        await session.execute(update(Run).where(Run.id == run_id).values(status="waiting"))
        # The first pause was decided already, so this is the gate's next pass.
        session.add(Approval(run_id=run_id, node_id="gate", iteration=1, decision="approve"))
    return run_id


async def test_the_pending_gate_carries_the_reviews_comments(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await reviewed_run(sessions)

    shown = (await pending_gate(sessions, run_id)).review

    assert shown is not None
    assert [(c.fingerprint, c.path, c.line) for c in shown.comments] == [
        ("a" * 8, "a.py", 3), ("b" * 8, "b.py", 9),
    ]  # fmt: skip
    assert shown.failed_lenses == ["performance"]
    assert shown.rounds_left == 1


async def test_an_approval_stores_its_dismissals_and_the_engine_is_handed_them(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await reviewed_run(sessions)

    recorded = await record_approval(
        sessions, run_id, "gate", GateDecision(decision="approve", dismissed=["a" * 8])
    )

    assert recorded.dismissed == ["a" * 8]
    async with sessions() as session:
        stored = await session.scalar(
            select(Approval.dismissed).where(Approval.run_id == run_id, Approval.iteration == 2)
        )
    assert stored == ["a" * 8]
    decision = await pending_decision(sessions, run_id)
    assert decision is not None and decision.dismissed == ["a" * 8]


async def test_a_comment_the_gate_did_not_show_cannot_be_dismissed(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await reviewed_run(sessions)

    with pytest.raises(InvalidDismissalError) as refused:
        await record_approval(
            sessions, run_id, "gate", GateDecision(decision="approve", dismissed=["zzzzzzzz"])
        )

    assert refused.value.code == "unknown_dismissal"
    assert await pending_decision(sessions, run_id) is None  # nothing was recorded


async def test_the_same_comment_twice_is_refused(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await reviewed_run(sessions)

    with pytest.raises(InvalidDismissalError) as refused:
        await record_approval(
            sessions, run_id, "gate",
            GateDecision(decision="approve", dismissed=["a" * 8, "a" * 8]),
        )  # fmt: skip

    assert refused.value.code == "duplicate_dismissal"


async def test_a_gate_with_no_review_takes_no_dismissals(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await reviewed_run(sessions, with_review=False)

    with pytest.raises(InvalidDismissalError) as refused:
        await record_approval(
            sessions, run_id, "gate", GateDecision(decision="approve", dismissed=["a" * 8])
        )

    assert refused.value.code == "dismiss_not_allowed"
