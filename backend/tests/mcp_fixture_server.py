"""Subprocess fixture: real MCP transport with deterministic website responses."""
import argparse

import httpx

from backend.mcp.tools.web_scraping.scraper import WebScraper
from backend.mcp.tools.web_scraping.server import create_server

HTML = """<!doctype html><html><head><title>Gold research fixture</title></head>
<body><main><h1>Example article</h1><p>This is a test fixture, not market evidence.</p>
<a href="/methodology">Methodology</a></main></body></html>"""


async def resolve(host, port):
    return ["93.184.215.14"]


def respond(request):
    return httpx.Response(200, text=HTML, headers={"content-type": "text/html; charset=utf-8"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    server = create_server(WebScraper(resolver=resolve, transport=httpx.MockTransport(respond)))
    if args.port:
        server.run(transport="streamable-http", host="127.0.0.1", port=args.port)
    else:
        server.run()
