import asyncio
from pathlib import Path
import subprocess
import sys

import httpx
from mcp import Client, StdioServerParameters
import pytest

from backend.mcp.tools.web_scraping.client import scrape_webpage
from backend.mcp.tools.web_scraping.schemas import ScrapedPage
from backend.mcp.tools.web_scraping.scraper import ScrapeError, WebScraper, normalize_url
from backend.mcp.tools.web_scraping.server import create_server
from backend.tests.conftest import free_port

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_IP = "93.184.215.14"
HTML = """<!doctype html><html><head><title>黄金 Research</title><style>bad-style</style></head>
<body><nav>bad-navigation</nav><main><h1>黄金研究</h1><p>Public article text.</p>
<script>bad-script</script><div hidden>bad-hidden</div>
<a href="/next">Next page</a><a href="/next">Duplicate</a><a href="javascript:alert(1)">Unsafe link</a>
<a href="mailto:test@example.com">Email</a></main><footer>bad-footer</footer></body></html>"""


async def public_dns(host, port):
    return [PUBLIC_IP]


def scraper(handler, **kwargs):
    return WebScraper(transport=httpx.MockTransport(handler), resolver=public_dns, **kwargs)


def page_response(body=HTML, status=200, **headers):
    return httpx.Response(status, content=body.encode(), headers={"content-type": "text/html; charset=utf-8", **headers})


async def test_extracts_readable_text_metadata_and_deduplicated_links():
    def respond(request):
        assert request.url.host == PUBLIC_IP
        assert request.headers["host"] == "example.com"
        assert request.extensions["sni_hostname"] == "example.com"
        assert request.headers["accept-encoding"] == "identity"
        return page_response()

    result = await scraper(respond).scrape("https://example.com/page#section")
    assert result.title == "黄金 Research"
    assert "黄金研究" in result.text
    assert "bad-" not in result.text
    assert len(result.links) == 1
    assert result.links[0].url == "https://example.com/next"
    assert result.final_url == "https://example.com/page"
    assert result.fetched_at.tzinfo is not None
    assert result.evidence_kind == "external_web_unverified"


async def test_text_truncation_is_explicit():
    result = await scraper(lambda request: page_response("<main>" + "字" * 200 + "</main>")).scrape("https://example.com", 100)
    assert result.text == "字" * 100
    assert result.truncated


async def test_plain_text():
    result = await scraper(lambda request: page_response("Hello world", **{"content-type": "text/plain"})).scrape("https://example.com")
    assert result.text == "Hello world"
    assert result.title == ""
    assert result.links == []
    assert not result.truncated


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com", "http://localhost", "http://foo.localhost", "http://printer.local", "https://user:pass@example.com", "http://example.com:8000", "https://example.com\\@127.0.0.1", "https://example.com\n/foo", "not-a-url"])
def test_rejects_unsafe_url_forms(url):
    with pytest.raises(ScrapeError):
        normalize_url(url)


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "192.168.1.1", "::1", "::ffff:127.0.0.1", "ff02::1", "224.0.0.1"])
async def test_blocks_private_and_special_dns_addresses_before_fetch(ip):
    async def resolve(host, port):
        return [PUBLIC_IP, ip]

    def never_fetch(request):
        pytest.fail("Blocked address reached HTTP transport")

    with pytest.raises(ScrapeError, match="non-public"):
        await WebScraper(resolver=resolve, transport=httpx.MockTransport(never_fetch)).scrape("https://example.com")


async def test_blocks_literal_loopback_with_real_resolver():
    with pytest.raises(ScrapeError, match="non-public"):
        await WebScraper().scrape("http://127.0.0.1")


async def test_redirects_are_resolved_and_validated_again():
    calls = []

    async def resolve(host, port):
        return ["127.0.0.1"] if host == "internal.example" else [PUBLIC_IP]

    def respond(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "http://internal.example/admin"})

    with pytest.raises(ScrapeError, match="non-public"):
        await WebScraper(resolver=resolve, transport=httpx.MockTransport(respond)).scrape("https://example.com")
    assert len(calls) == 1


async def test_follows_relative_redirect_and_reports_final_url():
    def respond(request):
        if request.url.path == "/":
            return httpx.Response(302, headers={"location": "/article", "set-cookie": "secret=test; Path=/"})
        assert "cookie" not in request.headers
        return page_response()

    result = await scraper(respond).scrape("https://example.com/")
    assert result.final_url == "https://example.com/article"


async def test_redirect_loop_is_bounded():
    with pytest.raises(ScrapeError, match="redirect limit"):
        await scraper(lambda request: httpx.Response(302, headers={"location": "/again"})).scrape("https://example.com")


@pytest.mark.parametrize("response, message", [
    (page_response(status=403), "HTTP 403"),
    (page_response(**{"content-type": "application/pdf"}), "content type"),
    (page_response(**{"content-encoding": "br"}), "uncompressed"),
    (page_response("<script>only javascript</script>"), "No readable text"),
    (page_response(**{"content-length": "3000000"}), "size limit"),
])
async def test_reports_upstream_and_content_failures(response, message):
    with pytest.raises(ScrapeError, match=message):
        await scraper(lambda request: response).scrape("https://example.com")


async def test_streamed_body_size_limit_without_content_length():
    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"a" * 100
            yield b"b" * 100

    with pytest.raises(ScrapeError, match="size limit"):
        await scraper(lambda request: httpx.Response(200, headers={"content-type": "text/plain"}, stream=Body()), max_bytes=150).scrape("https://example.com")


async def test_total_timeout_covers_slow_dns():
    async def slow_dns(host, port):
        await asyncio.sleep(2)
        return [PUBLIC_IP]

    with pytest.raises(ScrapeError, match="timed out"):
        await WebScraper(timeout=0.02, resolver=slow_dns).scrape("https://example.com")


async def test_mcp_discovery_structured_output_and_error_contract():
    async with Client(create_server(scraper(lambda request: page_response()))) as client:
        tools = (await client.list_tools()).tools
        assert [tool.name for tool in tools] == ["scrape_webpage"]
        assert tools[0].annotations.read_only_hint
        assert "text" in tools[0].output_schema["properties"]
        result = await client.call_tool("scrape_webpage", {"url": "https://example.com"})
        assert not result.is_error
        assert ScrapedPage.model_validate(result.structured_content).title == "黄金 Research"
        error = await client.call_tool("scrape_webpage", {"url": "http://localhost"})
        assert error.is_error
        invalid = await client.call_tool("scrape_webpage", {"url": "https://example.com", "max_chars": 999999})
        assert invalid.is_error


async def test_real_mcp_stdio_subprocess_roundtrip():
    parameters = StdioServerParameters(command=sys.executable, args=["-m", "backend.tests.mcp_fixture_server"], cwd=ROOT)
    async with Client(parameters, read_timeout_seconds=5) as client:
        assert (await client.list_tools()).tools[0].name == "scrape_webpage"
        result = await client.call_tool("scrape_webpage", {"url": "https://example.com"})
        page = ScrapedPage.model_validate(result.structured_content)
        assert page.title == "Gold research fixture"
        assert "test fixture" in page.text


async def test_default_client_launches_relocated_server_from_any_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # This reaches the real relocated server without making an external request.
    with pytest.raises(RuntimeError, match="non-public"):
        await scrape_webpage("http://127.0.0.1")


async def test_discovered_tool_maps_to_an_existing_skill():
    import yaml

    async with Client(create_server()) as client:
        tool = (await client.list_tools()).tools[0]
        binding = tool.meta["aurum/skill"]
        skill_path = ROOT / binding["path"]
        frontmatter = yaml.safe_load(skill_path.read_text().split("---", 2)[1])
        assert skill_path.parent.name == binding["name"] == frontmatter["name"]
        assert frontmatter["metadata"]["mcp-tool"] == tool.name
        # The declared client/server entry points must be importable and callable.
        from importlib import import_module
        assert callable(import_module(frontmatter["metadata"]["client-module"]).scrape_webpage)
        assert callable(import_module(frontmatter["metadata"]["server-module"]).create_server)


async def test_real_http_mcp_client_roundtrip(tmp_path):
    port = free_port()
    endpoint = f"http://127.0.0.1:{port}/mcp"
    with (tmp_path / "mcp.log").open("w+") as log:
        process = subprocess.Popen([sys.executable, "-m", "backend.tests.mcp_fixture_server", "--port", str(port)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        try:
            async with httpx.AsyncClient(timeout=0.3) as http:
                for _ in range(100):
                    assert process.poll() is None, "MCP fixture server exited"
                    try:
                        # A GET without SSE accept returns 406; it still proves readiness.
                        await http.get(endpoint)
                        break
                    except httpx.TransportError:
                        await asyncio.sleep(0.05)
                else:
                    pytest.fail("MCP fixture server did not start")
            result = await scrape_webpage("https://example.com", server_url=endpoint)
            assert result.title == "Gold research fixture"
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
