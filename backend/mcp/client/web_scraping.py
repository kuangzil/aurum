"""Compatibility entry point; implementation lives in tools/web_scraping/."""
from backend.mcp.tools.web_scraping.client import local_server_parameters, main, scrape_webpage

__all__ = ["local_server_parameters", "main", "scrape_webpage"]


if __name__ == "__main__":
    main()
