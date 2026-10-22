"""Sandboxed CEL conditions (phase 1.9)."""

import pytest
from pydantic import JsonValue

from agentic_engine.expr import MAX_EXPRESSION_LENGTH, ExpressionError, compile_condition

RESULTS: dict[str, JsonValue] = {
    "draft": {"status": "completed", "text": "v2", "data": None},
    "review": {"status": "completed", "text": "APPROVED", "data": {"score": 9}},
}


def check(source: str, *, last: str = "APPROVED", iteration: int = 2) -> bool:
    return compile_condition(source).evaluate(last=last, iteration=iteration, results=RESULTS)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('last.contains("APPROVED")', True),
        ('last.contains("REJECTED")', False),
        ("iteration >= 2", True),
        ("iteration >= 3", False),
        ('results.review.status == "completed"', True),
        ("results.review.data.score > 8", True),
        ("has(results.review.data)", True),
        ("results.draft.data == null", True),
        ('results.exists(k, k == "review")', True),
        ('results.all(k, results[k].status == "completed")', True),
        ('last.matches("(?i)approved")', True),
        ("size(last) > 100", False),
    ],
)
def test_condition_evaluates(source: str, expected: bool) -> None:
    assert check(source) is expected


def test_condition_is_reusable() -> None:
    cond = compile_condition('last.contains("ok")')

    assert cond.evaluate(last="ok", iteration=1, results={}) is True
    assert cond.evaluate(last="no", iteration=2, results={}) is False


def test_syntax_error_has_column() -> None:
    with pytest.raises(ExpressionError) as exc:
        compile_condition("last.contains(")

    assert exc.value.message == "syntax error"
    assert exc.value.column == 14
    assert "column 14" in str(exc.value)


def test_unknown_variable_is_rejected_at_compile() -> None:
    with pytest.raises(ExpressionError, match=r"unknown variable 'reviewer'.*column 1"):
        compile_condition('reviewer.contains("x")')


def test_macro_variables_are_not_unknown() -> None:
    compile_condition('results.exists(node, results[node].status == "failed")')


def test_unknown_function_is_rejected_at_compile() -> None:
    with pytest.raises(ExpressionError, match="unknown function 'lowerAscii'"):
        compile_condition('last.lowerAscii() == "ok"')


def test_non_bool_result_fails() -> None:
    with pytest.raises(ExpressionError, match="must be a bool, got StringType"):
        check("last")


def test_too_long_is_rejected() -> None:
    with pytest.raises(ExpressionError, match=f"longer than {MAX_EXPRESSION_LENGTH}"):
        compile_condition("true || " * 200 + "true")


def test_evaluation_error_is_short_and_clear() -> None:
    with pytest.raises(ExpressionError) as exc:
        check('results.missing.text == "x"')

    assert "no such member in mapping: 'missing'" in exc.value.message
    assert "activation" not in str(exc.value)
