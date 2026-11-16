"""Safe arithmetic tool.

Never uses `eval`. The expression is parsed with `ast` and walked with an
allowlist of node types, so `__import__('os')` and friends are impossible.
"""

from __future__ import annotations

import ast
import math
import operator
from typing import Any, Callable

from .base import Tool, ToolError

MAX_EXPRESSION_LENGTH = 300
MAX_EXPONENT = 64

_BIN_OPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "factorial": math.factorial,
    "floor": math.floor,
    "ceil": math.ceil,
}
_CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


def _eval(node: ast.AST) -> Any:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ToolError("Only numeric literals are allowed")
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise ToolError(f"Operator {type(node.op).__name__} is not allowed")
        left, right = _eval(node.left), _eval(node.right)
        if op is operator.pow and abs(right) > MAX_EXPONENT:
            raise ToolError(f"Exponent too large (limit {MAX_EXPONENT})")
        try:
            return op(left, right)
        except ZeroDivisionError as exc:
            raise ToolError("Division by zero") from exc
        except OverflowError as exc:
            raise ToolError("Result too large") from exc
    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise ToolError("Unary operator not allowed")
        return op(_eval(node.operand))
    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        raise ToolError(f"Unknown name '{node.id}'")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
            raise ToolError("Only whitelisted math functions can be called")
        if node.keywords:
            raise ToolError("Keyword arguments are not supported")
        args = [_eval(arg) for arg in node.args]
        try:
            return _FUNCTIONS[node.func.id](*args)
        except (ValueError, TypeError) as exc:
            raise ToolError(f"{node.func.id}() failed: {exc}") from exc
    raise ToolError(f"Disallowed syntax: {type(node).__name__}")


def evaluate(expression: str) -> float | int:
    """Evaluate a numeric expression safely."""
    expression = expression.strip()
    if not expression:
        raise ToolError("Expression is empty")
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ToolError("Expression is too long")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ToolError(f"Could not parse expression: {exc.msg}") from exc
    return _eval(tree)


async def calculator(expression: str) -> str:
    """Tool entrypoint: evaluate and return a short human-readable result."""
    result = evaluate(expression)
    if isinstance(result, float):
        if result.is_integer() and abs(result) < 1e15:
            result = int(result)
        else:
            result = round(result, 10)
    return f"{expression} = {result}"


calculator_tool = Tool(
    name="calculator",
    description=(
        "Evaluate a numeric expression with + - * / // % ** and functions like sqrt, log, "
        "sin, cos, factorial. Use this for any arithmetic instead of guessing."
    ),
    parameters={
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "e.g. '(1200 * 1.18) / 3' or 'sqrt(144) + 2**10'",
            }
        },
        "required": ["expression"],
    },
    func=calculator,
    max_output_chars=500,
)
