"""Compatibility entry point; implementation lives in tools/web_scraping/."""
from backend.mcp.tools.web_scraping.server import create_server, main

__all__ = ["create_server", "main"]


if __name__ == "__main__":
    main()
