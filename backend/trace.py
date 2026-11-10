import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger("aurum.trace")


class TraceEvent(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    agent: Literal["research", "validation", "a2a"]
    stage: str
    detail: str
    message_id: str | None = None


Reporter = Callable[[TraceEvent], Awaitable[None]]


async def no_report(event: TraceEvent) -> None:
    pass
