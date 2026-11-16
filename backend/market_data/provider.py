import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from typing import Literal

import httpx
from pydantic import AwareDatetime, BaseModel, Field, ValidationError, field_validator

from backend.storage.sqlite import utc_now
from backend.trace import logger

ENDPOINT = 'https://api.gold-api.com/price/XAU'
SOURCE = 'gold-api.com'


class MarketDataUnavailable(RuntimeError):
    pass


class GoldQuote(BaseModel):
    symbol: Literal['XAU']
    currency: Literal['USD']
    price: Decimal = Field(gt=0, allow_inf_nan=False, max_digits=24, decimal_places=12)
    updated_at: AwareDatetime = Field(alias='updatedAt')

    @field_validator('updated_at', mode='before')
    @classmethod
    def timestamp_string(cls, value):
        if not isinstance(value, (str, datetime)):
            raise ValueError('Quote timestamp must be an ISO timestamp')
        return value

    @field_validator('updated_at')
    @classmethod
    def normalize_utc(cls, value):
        return value.astimezone(timezone.utc)


class GoldAPIProvider:
    def __init__(self, timeout: float = 10, attempts: int = 3, client: httpx.AsyncClient | None = None):
        if not 0 < timeout <= 30 or not 1 <= attempts <= 3:
            raise ValueError('Provider timeout/attempts must be bounded')
        self.timeout, self.attempts, self.client = timeout, attempts, client

    async def fetch(self) -> GoldQuote:
        if self.client is not None:
            return await self._fetch(self.client)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await self._fetch(client)

    async def _fetch(self, client: httpx.AsyncClient) -> GoldQuote:
        for attempt in range(self.attempts):
            try:
                response = await client.get(ENDPOINT, timeout=self.timeout)
                response.raise_for_status()
                # Parse floats directly as Decimal; never round-trip through binary float storage.
                quote = GoldQuote.model_validate(json.loads(response.text, parse_float=Decimal))
                if quote.updated_at > utc_now() + timedelta(minutes=5):
                    raise ValueError('Quote timestamp is in the future')
                return quote
            except (ValueError, ValidationError) as exc:
                raise MarketDataUnavailable('Gold provider returned invalid quote data.') from exc
            except httpx.HTTPError as exc:
                retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in (429, 500, 502, 503, 504)
                if not retryable or attempt + 1 == self.attempts:
                    raise MarketDataUnavailable('Gold provider is unavailable.') from exc
                logger.warning('gold_fetch_retry attempt=%s error_type=%s', attempt + 1, type(exc).__name__)
                await asyncio.sleep(1.0 * 2 ** attempt)
        raise MarketDataUnavailable('Gold provider is unavailable.')
