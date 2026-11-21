"""Bounded single-page HTTP fetching and static HTML extraction."""
import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from backend.mcp.tools.web_scraping.schemas import PageLink, ScrapedPage, ScrapeRequest

MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
TIMEOUT_SECONDS = 20
USER_AGENT = "AurumWebScraper/0.1"


class ScrapeError(ValueError):
    """An expected, user-readable scraping failure."""


def normalize_url(value: str) -> httpx.URL:
    try:
        if len(value) > 2048 or any(ord(char) < 32 for char in value) or "\\" in value:
            raise ValueError
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ValueError
        if parsed.username is not None or parsed.password is not None:
            raise ValueError
        if parsed.port is not None and parsed.port not in {80, 443}:
            raise ValueError
        url = httpx.URL(value).copy_with(fragment=None)
        host = url.host.lower().rstrip(".")
        if not host or "%" in host or host == "localhost" or host.endswith((".localhost", ".local")):
            raise ValueError
        return url
    except (ValueError, httpx.InvalidURL) as exc:
        raise ScrapeError("Use a public HTTP(S) URL on port 80 or 443, without credentials.") from exc


async def resolve_addresses(host: str, port: int) -> list[str]:
    try:
        return [str(ipaddress.ip_address(host))]
    except ValueError:
        pass
    try:
        records = await asyncio.to_thread(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ScrapeError("The website hostname could not be resolved.") from exc
    return list(dict.fromkeys(record[4][0] for record in records))


def public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
        return ip.is_global and not ip.is_multicast and not ip.is_reserved
    except ValueError:
        return False


def extract_page(body: bytes, content_type: str, encoding: str | None, url: str, max_chars: int):
    """Extract content, never execute page scripts or follow the extracted links."""
    if content_type == "text/plain":
        try:
            text = body.decode(encoding or "utf-8", errors="replace").strip()
        except LookupError:
            text = body.decode("utf-8", errors="replace").strip()
        return "", text[:max_chars], [], len(text) > max_chars

    soup = BeautifulSoup(body, "html.parser", from_encoding=encoding)
    title = soup.title.get_text(" ", strip=True)[:500] if soup.title else ""
    for element in soup.select("script, style, noscript, template, nav, footer, aside, form, svg, canvas, head, [hidden], [aria-hidden='true']"):
        element.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    text = "\n".join(line.strip() for line in root.get_text("\n", strip=True).splitlines() if line.strip())
    links: list[PageLink] = []
    seen: set[str] = set()
    for anchor in root.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        if not href or href.startswith("#"):
            continue
        try:
            target = str(normalize_url(urljoin(url, href)))
        except (ScrapeError, ValueError):
            continue
        if target not in seen:
            links.append(PageLink(text=anchor.get_text(" ", strip=True)[:300], url=target))
            seen.add(target)
        if len(links) == 50:
            break
    return title, text[:max_chars], links, len(text) > max_chars


class WebScraper:
    def __init__(
        self,
        *,
        timeout: float = TIMEOUT_SECONDS,
        max_bytes: int = MAX_BYTES,
        resolver: Callable[[str, int], Awaitable[list[str]]] = resolve_addresses,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        # Dependency injection allows deterministic tests without external sites.
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.resolver = resolver
        self.transport = transport

    async def scrape(self, url: str, max_chars: int = 12000) -> ScrapedPage:
        request = ScrapeRequest(url=url, max_chars=max_chars)
        current = normalize_url(request.url)
        try:
            async with asyncio.timeout(self.timeout):
                async with httpx.AsyncClient(
                    timeout=self.timeout, follow_redirects=False, trust_env=False,
                    limits=httpx.Limits(max_keepalive_connections=0),
                    transport=self.transport,
                    headers={"User-Agent": USER_AGENT, "Accept": "text/html, application/xhtml+xml, text/plain", "Accept-Encoding": "identity"},
                ) as client:
                    for hop in range(MAX_REDIRECTS + 1):
                        addresses = await self.resolver(current.host, current.port or (443 if current.scheme == "https" else 80))
                        if not addresses or not all(public_address(address) for address in addresses):
                            raise ScrapeError("The URL resolves to a non-public address; local and private networks are not allowed.")
                        # Connect to the validated IP instead of resolving twice.
                        # Keep the original Host and TLS SNI/certificate hostname.
                        pinned = current.copy_with(host=addresses[0])
                        # Different origins can share an IP. Never reuse their
                        # TLS connection or carry response cookies across hops.
                        client.cookies.clear()
                        async with client.stream(
                            "GET", pinned, headers={"Host": current.netloc.decode("ascii")},
                            extensions={"sni_hostname": current.host},
                        ) as response:
                            if response.status_code in {301, 302, 303, 307, 308}:
                                location = response.headers.get("location")
                                if not location:
                                    raise ScrapeError("The website returned a redirect without a destination.")
                                if hop == MAX_REDIRECTS:
                                    raise ScrapeError("The website exceeded the redirect limit.")
                                current = normalize_url(urljoin(str(current), location))
                                continue
                            if not 200 <= response.status_code < 300:
                                raise ScrapeError(f"The website returned HTTP {response.status_code}.")
                            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                            if content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
                                raise ScrapeError("Unsupported content type. Only HTML and plain text pages are supported.")
                            # Refuse unsolicited compression to bound memory before
                            # decompression (the request explicitly asks for identity).
                            if response.headers.get("content-encoding", "identity").lower() != "identity":
                                raise ScrapeError("The website did not provide an uncompressed response as requested.")
                            length = response.headers.get("content-length", "")
                            if length.isdigit() and int(length) > self.max_bytes:
                                raise ScrapeError("The webpage exceeds the response size limit.")
                            body = bytearray()
                            async for chunk in response.aiter_bytes(chunk_size=65536):
                                body.extend(chunk)
                                if len(body) > self.max_bytes:
                                    raise ScrapeError("The webpage exceeds the response size limit.")
                            encoding = response.charset_encoding
                            title, text, links, truncated = await asyncio.to_thread(
                                extract_page, bytes(body), content_type, encoding, str(current), request.max_chars,
                            )
                            if not text:
                                raise ScrapeError("No readable text found. The page may require JavaScript or authentication.")
                            return ScrapedPage(
                                requested_url=request.url, final_url=str(current), title=title,
                                text=text, links=links, content_type=content_type,
                                status_code=response.status_code, fetched_at=datetime.now(timezone.utc), truncated=truncated,
                            )
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise ScrapeError("The webpage request timed out.") from exc
        except httpx.HTTPError as exc:
            raise ScrapeError("The website could not be fetched. Check its availability and TLS certificate.") from exc
        raise ScrapeError("The webpage could not be retrieved.")
