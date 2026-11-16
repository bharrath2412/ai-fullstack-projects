"""Allowlisted HTTP GET tool with HTML -> text conversion.

The domain allowlist prevents SSRF (`http://169.254.169.254/...`) and any
unexpected egress from the agent.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

from ...config import settings
from .base import Tool, ToolError

_BLOCK_TAGS = {"script", "style", "noscript", "svg", "head"}
_WS = re.compile(r"[ \t\r\f\v]+")
_NL = re.compile(r"\n{3,}")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs):  # noqa: D102
        if tag in _BLOCK_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "section", "article"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str):  # noqa: D102
        if tag in _BLOCK_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str):  # noqa: D102
        if self._in_title:  # <title> lives inside <head>, which we otherwise skip
            self.title += data
            return
        if self._skip_depth:
            return
        self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        raw = _WS.sub(" ", raw)
        raw = "\n".join(line.strip() for line in raw.splitlines())
        return _NL.sub("\n\n", raw).strip()


def _check_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ToolError("Only http(s) URLs are allowed")
    if not parsed.hostname:
        raise ToolError("URL must include a hostname")
    host = parsed.hostname.lower()
    allowed = [d.lower() for d in settings.http_allowed_domains]
    if not any(host == domain or host.endswith("." + domain) for domain in allowed):
        raise ToolError(
            f"Domain '{host}' is not on the allowlist. Allowed: {', '.join(allowed)}"
        )
    return url


def html_to_text(html: str) -> tuple[str, str]:
    parser = _TextExtractor()
    parser.feed(html)
    return parser.title.strip(), parser.text()


async def http_fetch(url: str, max_chars: int = 3000) -> str:
    url = _check_url(url)
    headers = {"User-Agent": "AgentForge/1.0 (+agent demo)", "Accept": "text/html,text/plain,application/json"}
    try:
        async with httpx.AsyncClient(
            timeout=settings.http_timeout_seconds, follow_redirects=True
        ) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise ToolError(f"Request failed: {exc}") from exc

    if response.status_code >= 400:
        raise ToolError(f"HTTP {response.status_code} from {url}")

    body = response.content[: settings.http_max_bytes]
    content_type = response.headers.get("content-type", "")
    text = body.decode(response.encoding or "utf-8", errors="replace")

    if "html" in content_type:
        title, text = html_to_text(text)
        header = f"# {title}\n{url}\n\n" if title else f"# {url}\n\n"
    else:
        header = f"# {url}\n\n"

    if len(text) > max_chars:
        text = text[:max_chars] + f"\n…[truncated, page was {len(text)} chars]"
    return header + text


http_tool = Tool(
    name="http_fetch",
    description=(
        "Fetch a web page or JSON API from an allowlisted domain and return readable text. "
        "Useful for looking up current information on the public internet."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Absolute http(s) URL"},
            "max_chars": {"type": "integer", "description": "Max characters to return (default 3000)"},
        },
        "required": ["url"],
    },
    func=http_fetch,
    requires_network=True,
    timeout_seconds=15,
    max_output_chars=4000,
)
