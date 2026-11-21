"""Reusable MCP client and command-line example for the scraping tool."""
import argparse
import asyncio
from pathlib import Path
import sys

from mcp import Client, StdioServerParameters

from backend.mcp.tools.web_scraping import TOOL_NAME
from backend.mcp.tools.web_scraping.schemas import ScrapedPage, ScrapeRequest

ROOT = Path(__file__).resolve().parents[4]


def local_server_parameters() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable, args=["-m", "backend.mcp.tools.web_scraping.server"], cwd=ROOT,
    )


async def scrape_webpage(url: str, max_chars: int = 12000, *, server_url: str | None = None) -> ScrapedPage:
    request = ScrapeRequest(url=url, max_chars=max_chars)
    # SDK handles initialization, discovery, tools/call and transport cleanup.
    async with Client(server_url or local_server_parameters(), read_timeout_seconds=30) as client:
        result = await client.call_tool(TOOL_NAME, request.model_dump())
    # Close SDK task groups before raising application errors so callers receive
    # the actual tool failure rather than a nested transport ExceptionGroup.
    if result.is_error:
        message = "\n".join(part.text for part in result.content if part.type == "text")
        raise RuntimeError(message or "The scraping MCP tool failed.")
    if result.structured_content is None:
        raise RuntimeError("The scraping MCP server returned no structured result.")
    return ScrapedPage.model_validate(result.structured_content)


def main():
    parser = argparse.ArgumentParser(description="Fetch a webpage through the Aurum MCP tool")
    parser.add_argument("url")
    parser.add_argument("--max-chars", type=int, default=12000)
    parser.add_argument("--server-url", help="Existing Streamable HTTP MCP endpoint; otherwise launches stdio locally")
    args = parser.parse_args()
    try:
        result = asyncio.run(scrape_webpage(args.url, args.max_chars, server_url=args.server_url))
    except Exception as exc:
        print(f"Scraping failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
