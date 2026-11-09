"""Sandboxed CEL expressions: conditions (`loop.until`, `router` routes), lists (`map.over`) and
values (`subflow.input`).

An expression is CEL text from the spec, run with `cel-python`. It can only read the variables it
is given and call CEL's standard functions and macros: no custom functions are registered, so an
expression never runs platform code, and `matches` uses RE2, which runs in linear time. The values
it reads (an agent's output, a tool's data) are data, never instructions.

`compile_condition` and `compile_list` parse an expression once and check that it names only
known variables and functions, so a bad expression fails when the spec is validated, not mid-run.
"""

import json
from collections.abc import Mapping
from typing import Final, cast

import celpy
import lark
from celpy import celtypes
from celpy.adapter import CELJSONEncoder, json_to_cel
from celpy.celparser import CELParseError
from celpy.evaluation import CELEvalError, CELSyntaxError, CELUnsupportedError, base_functions
from pydantic import JsonValue

type _Ast = lark.Tree[lark.Token]

MAX_EXPRESSION_LENGTH: Final = 1000

CONDITION_VARIABLES: Final = frozenset({"last", "iteration", "results", "artifacts"})
"""What a loop condition can read: `last` (string, the body's output for the iteration that just
ran), `iteration` (int, iterations completed, from 1), `results` (map: node id → `{status,
text, data}`, the latest result of each node run so far) and `artifacts` (map: run artifact name
→ its latest content, parsed for a `.json` artifact, else a string)."""

LIST_VARIABLES: Final = frozenset({"last", "results", "artifacts"})
"""What a map's `over` can read: `last` (string, the map's input), `results` and `artifacts` (as
for a condition)."""

ROUTE_VARIABLES: Final = frozenset({"last", "results", "artifacts"})
"""What a router's `when` can read: `last` (string, the router's input), `results` and
`artifacts` (as for a condition). Inside a map item or a parallel branch, `results` holds the
nodes that ran in it so far."""

VALUE_VARIABLES: Final = frozenset({"last", "results", "artifacts"})
"""What a subflow's `input` can read (6.5): `last` (string, the subflow's input), `results` and
`artifacts` (as for a condition)."""

_MACROS: Final = frozenset({"has", "all", "exists", "exists_one", "map", "filter"})
_FUNCTIONS: Final = frozenset(n for n in base_functions if not n.startswith("_") and n != "!_")
_BINDING_MACROS: Final = frozenset({"all", "exists", "exists_one", "map", "filter"})


class ExpressionError(ValueError):
    """An expression that does not parse, names something unknown, or fails when evaluated."""

    def __init__(self, source: str, message: str, column: int | None = None) -> None:
        where = f" at column {column}" if column is not None else ""
        super().__init__(f"{message}{where}: {source!r}")
        self.source = source
        self.message = message
        self.column = column


class CompiledExpression:
    """A parsed and checked expression, ready to evaluate many times."""

    def __init__(self, source: str, program: celpy.Runner) -> None:
        self.source = source
        self._program = program

    def _evaluate(self, activation: dict[str, celtypes.Value]) -> celtypes.Value:
        try:
            value = self._program.evaluate(activation)
        except CELEvalError as e:
            raise ExpressionError(self.source, _eval_message(e)) from e
        except (CELSyntaxError, CELUnsupportedError, TypeError, ValueError) as e:
            raise ExpressionError(self.source, str(e)) from e
        if isinstance(value, CELEvalError):
            raise ExpressionError(self.source, _eval_message(value))
        return value


class CompiledCondition(CompiledExpression):
    """A condition: an expression that must evaluate to a bool."""

    def evaluate(
        self,
        *,
        last: str,
        iteration: int,
        results: Mapping[str, JsonValue],
        artifacts: Mapping[str, JsonValue] | None = None,
    ) -> bool:
        """Evaluate against the loop's state. Raises `ExpressionError` if evaluation fails or the
        result is not a bool."""
        value = self._evaluate(
            {
                "last": celtypes.StringType(last),
                "iteration": celtypes.IntType(iteration),
                "results": json_to_cel(dict(results)),
                "artifacts": json_to_cel(dict(artifacts or {})),
            }
        )
        if not isinstance(value, celtypes.BoolType):
            raise ExpressionError(
                self.source, f"condition must be a bool, got {type(value).__name__}"
            )
        return bool(value)


class CompiledList(CompiledExpression):
    """A list expression: one that must evaluate to a list, whose items are returned as JSON."""

    def evaluate(
        self,
        *,
        last: str,
        results: Mapping[str, JsonValue],
        artifacts: Mapping[str, JsonValue] | None = None,
    ) -> list[JsonValue]:
        """Evaluate against the run's state. Raises `ExpressionError` if evaluation fails or the
        result is not a list."""
        value = self._evaluate(
            {
                "last": celtypes.StringType(last),
                "results": json_to_cel(dict(results)),
                "artifacts": json_to_cel(dict(artifacts or {})),
            }
        )
        if not isinstance(value, celtypes.ListType):
            raise ExpressionError(self.source, f"must be a list, got {type(value).__name__}")
        items = json.loads(json.dumps(value, cls=CELJSONEncoder))
        return cast(list[JsonValue], items)


class CompiledValue(CompiledExpression):
    """A value expression: any value, returned as the text it stands for (6.5)."""

    def evaluate(
        self,
        *,
        last: str,
        results: Mapping[str, JsonValue],
        artifacts: Mapping[str, JsonValue] | None = None,
    ) -> str:
        """Evaluate against the run's state: a string as it is, any other value as JSON. Raises
        `ExpressionError` if evaluation fails."""
        value = self._evaluate(
            {
                "last": celtypes.StringType(last),
                "results": json_to_cel(dict(results)),
                "artifacts": json_to_cel(dict(artifacts or {})),
            }
        )
        if isinstance(value, str):
            return str(value)
        return json.dumps(
            json.loads(json.dumps(value, cls=CELJSONEncoder)), indent=2, ensure_ascii=False
        )


_environment: celpy.Environment | None = None


def _env() -> celpy.Environment:
    # Created on first use: `celpy.Environment()` raises the interpreter's recursion limit.
    global _environment
    if _environment is None:
        _environment = celpy.Environment()
    return _environment


def compile_condition(
    source: str, variables: frozenset[str] = CONDITION_VARIABLES
) -> CompiledCondition:
    """Parse `source` and check it only names `variables` and CEL's standard functions. Raises
    `ExpressionError` with the column of the problem, if known."""
    return CompiledCondition(source, _compile(source, variables, "condition"))


def compile_list(source: str, variables: frozenset[str] = LIST_VARIABLES) -> CompiledList:
    """As `compile_condition`, for an expression that must evaluate to a list."""
    return CompiledList(source, _compile(source, variables, "expression"))


def compile_value(source: str, variables: frozenset[str] = VALUE_VARIABLES) -> CompiledValue:
    """As `compile_condition`, for an expression whose value is used as text (a subflow's
    `input`)."""
    return CompiledValue(source, _compile(source, variables, "expression"))


def _compile(source: str, variables: frozenset[str], kind: str) -> celpy.Runner:
    if len(source) > MAX_EXPRESSION_LENGTH:
        raise ExpressionError(
            source[:40] + "…", f"{kind} is longer than {MAX_EXPRESSION_LENGTH} characters"
        )
    env = _env()
    try:
        ast = cast(_Ast, env.compile(source))  # pyright: ignore[reportUnknownMemberType]
    except CELParseError as e:
        raise ExpressionError(source, "syntax error", e.column) from e
    _check_names(source, ast, variables)
    return env.program(ast)  # pyright: ignore[reportUnknownMemberType]


def _check_names(source: str, ast: _Ast, variables: frozenset[str]) -> None:
    """Reject unknown variables and functions up front; CEL only finds them when evaluating."""
    bound = set[str]()
    for tree in ast.iter_subtrees_topdown():
        if tree.data == "member_dot_arg" and _token(tree.children[1]) in _BINDING_MACROS:
            # `list.exists(x, …)` binds `x` for the rest of its arguments.
            args = tree.children[2] if len(tree.children) > 2 else None
            if isinstance(args, lark.Tree) and args.children:
                first = args.children[0]
                if isinstance(first, lark.Tree):
                    bound.update(t.value for t in first.scan_values(_is_token))
    for tree in ast.iter_subtrees_topdown():
        match tree.data:
            case "ident":
                token = tree.children[0]
                if isinstance(token, lark.Token) and token.value not in variables | bound:
                    known = ", ".join(sorted(variables))
                    raise ExpressionError(
                        source, f"unknown variable {token.value!r} (known: {known})", token.column
                    )
            case "ident_arg" | "member_dot_arg" | "dot_ident_arg":
                token = next(c for c in tree.children if isinstance(c, lark.Token))
                if token.value not in _FUNCTIONS | _MACROS:
                    raise ExpressionError(source, f"unknown function {token.value!r}", token.column)
            case _:
                pass


def _token(child: object) -> str | None:
    return child.value if isinstance(child, lark.Token) else None


def _is_token(value: object) -> bool:
    return isinstance(value, lark.Token)


def _eval_message(error: CELEvalError) -> str:
    message = str(error.args[0]) if error.args else "evaluation failed"
    # celpy appends the whole activation to some messages; it is noise, and may be large.
    return message.split(" (in activation", 1)[0]
