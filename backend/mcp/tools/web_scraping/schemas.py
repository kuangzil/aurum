"""Structured contracts belonging to the web scraping MCP tool."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ScrapeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    url: str = Field(min_length=1, max_length=2048)
    max_chars: int = Field(default=12000, ge=100, le=50000, strict=True)


class PageLink(BaseModel):
    text: str
    url: str


class ScrapedPage(BaseModel):
    requested_url: str
    final_url: str
    title: str
    text: str
    links: list[PageLink]
    content_type: str
    status_code: int
    fetched_at: datetime
    truncated: bool
    evidence_kind: Literal["external_web_unverified"] = "external_web_unverified"
