"""Tool registry factory."""

from __future__ import annotations

from .base import Tool, ToolError, ToolRegistry
from .calculator import calculator_tool
from .doc_search import doc_search_tool
from .http_fetch import http_tool
from .sqlite_query import sqlite_tool

__all__ = ["Tool", "ToolError", "ToolRegistry", "build_registry"]


def build_registry(*, allow_network: bool = True, allow_sql: bool = True) -> ToolRegistry:
    """Register the default tool set, optionally tightening policy."""
    registry = ToolRegistry()
    registry.register(calculator_tool)
    registry.register(doc_search_tool)
    if allow_sql:
        registry.register(sqlite_tool)
    else:
        registry.disabled.add("sqlite_query")
    if allow_network:
        registry.register(http_tool)
    else:
        registry.disabled.add("http_fetch")
    return registry
