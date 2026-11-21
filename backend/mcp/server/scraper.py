"""Compatibility imports for the web scraping implementation."""
from backend.mcp.tools.web_scraping.scraper import (
    MAX_BYTES,
    MAX_REDIRECTS,
    TIMEOUT_SECONDS,
    USER_AGENT,
    ScrapeError,
    WebScraper,
    extract_page,
    normalize_url,
    public_address,
    resolve_addresses,
)

__all__ = [
    "MAX_BYTES", "MAX_REDIRECTS", "TIMEOUT_SECONDS", "USER_AGENT",
    "ScrapeError", "WebScraper", "extract_page", "normalize_url",
    "public_address", "resolve_addresses",
]
