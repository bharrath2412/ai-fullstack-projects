"""Tool-level tests: safety properties matter more than happy paths here."""

from __future__ import annotations

import asyncio

import pytest

from app.agent.tools import build_registry
from app.agent.tools.base import ToolError
from app.agent.tools.calculator import evaluate
from app.agent.tools.doc_search import knowledge_base
from app.agent.tools.http_fetch import _check_url, html_to_text
from app.agent.tools.sqlite_query import _validate, format_table, run_query
from app.agent.tools.calculator import calculator_tool
from app.agent.tools.sqlite_query import sqlite_tool
from app.schemas import ToolCall


# --------------------------------------------------------------------- calc
@pytest.mark.parametrize(
    "expression,expected",
    [
        ("2 + 2", 4),
        ("(1200 * 1.18) / 3", pytest.approx(472.0)),
        ("2 ** 10", 1024),
        ("sqrt(144)", 12),
        ("10 % 3", 1),
        ("-5 * (3 + 2)", -25),
        ("factorial(5)", 120),
        ("pi", pytest.approx(3.14159265, rel=1e-6)),
    ],
)
def test_evaluate_valid(expression, expected):
    assert evaluate(expression) == expected


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo pwned')",
        "open('/etc/passwd').read()",
        "exec('1+1')",
        "2 ** 100000",
        "1 / 0",
        "[1,2,3]",
        "lambda x: x",
        "",
        "a + b",
    ],
)
def test_evaluate_rejects_unsafe(expression):
    with pytest.raises(ToolError):
        evaluate(expression)


def test_calculator_tool_wraps_errors_in_result():
    result = asyncio.run(
        calculator_tool.run(ToolCall(name="calculator", arguments={"expression": "__import__('os')"}))
    )
    assert result.ok is False
    assert result.error, "a rejected expression must return an explanation"
    assert "whitelisted" in result.error or "Disallowed" in result.error


# ---------------------------------------------------------------------- sql
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "select name from customers limit 3",
        "WITH x AS (SELECT 1) SELECT * FROM x",
    ],
)
def test_validate_allows_select(sql):
    assert _validate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM customers",
        "DROP TABLE orders",
        "UPDATE orders SET total = 0",
        "PRAGMA table_info(customers)",
        "SELECT 1; DROP TABLE orders",
        "INSERT INTO customers VALUES (99,'x','y','z','2020-01-01')",
        "ATTACH DATABASE '/tmp/x.db' AS x",
        "-- comment\nDELETE FROM orders",
    ],
)
def test_validate_blocks_writes(sql):
    with pytest.raises(ToolError):
        _validate(sql)


def test_query_returns_rows():
    columns, rows = run_query("SELECT COUNT(*) AS n FROM customers", max_rows=1)
    assert columns == ["n"]
    assert rows[0][0] >= 20


def test_format_table_renders_header_and_rows():
    table = format_table(["a", "b"], [(1, "x"), (2, None)])
    assert "a" in table and "|" in table
    assert "NULL" in table


def test_unknown_table_is_reported_not_raised():
    result = asyncio.run(
        sqlite_tool.run(ToolCall(name="sqlite_query", arguments={"sql": "SELECT * FROM nope"}))
    )
    assert result.ok is False
    assert "SQL error" in (result.error or "")


# --------------------------------------------------------------------- http
def test_url_allowlist_blocks_internal_hosts():
    with pytest.raises(ToolError):
        _check_url("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(ToolError):
        _check_url("file:///etc/passwd")
    with pytest.raises(ToolError):
        _check_url("https://evil.example.org/steal")
    assert _check_url("https://en.wikipedia.org/wiki/Retrieval-augmented_generation")


def test_html_to_text_strips_markup_and_scripts():
    title, text = html_to_text(
        "<html><head><title>Hi</title><style>.x{}</style></head>"
        "<body><h1>Hello</h1><script>alert(1)</script><p>World</p></body></html>"
    )
    assert title == "Hi"
    assert "Hello" in text and "World" in text
    assert "alert(1)" not in text and ".x{}" not in text


# ---------------------------------------------------------------------- docs
def test_doc_search_finds_relevant_chunk():
    hits = knowledge_base().search("how does the agent loop work", top_k=3)
    assert hits, "expected at least one hit"
    combined = " ".join(h["text"] for h in hits).lower()
    assert "loop" in combined


# ------------------------------------------------------------------- registry
def test_registry_rejects_unknown_tool():
    registry = build_registry()
    result = asyncio.run(registry.run(ToolCall(name="rm_rf", arguments={})))
    assert result.ok is False
    assert "No tool named" in (result.error or "")


def test_registry_validates_arguments():
    registry = build_registry()
    result = asyncio.run(registry.run(ToolCall(name="calculator", arguments={"expr": "1+1"})))
    assert result.ok is False
    assert "Unknown argument" in (result.error or "")

    missing = asyncio.run(registry.run(ToolCall(name="calculator", arguments={})))
    assert missing.ok is False
    assert "Missing required" in (missing.error or "")


def test_registry_can_disable_network_tool():
    registry = build_registry(allow_network=False)
    names = {spec.name for spec in registry.specs()}
    assert "http_fetch" not in names
    result = asyncio.run(registry.run(ToolCall(name="http_fetch", arguments={"url": "https://example.com"})))
    assert result.ok is False
    assert "disabled" in (result.error or "")
